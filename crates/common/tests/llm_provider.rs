//! Offline integration tests for the provider-neutral LLM client.

use std::{
    collections::{HashMap, VecDeque},
    io,
    net::SocketAddr,
    sync::{Arc, Mutex},
    time::Duration,
};

use heimdall_common::resources::llm::{
    AnnotatedContractResponse, LlmClient, LlmConfig, LlmError, LlmResponseFormat, LlmResponseMode,
    DEFAULT_MODEL, OPENROUTER_API_BASE,
};
use serde_json::{json, Value};
use tokio::{
    io::{AsyncReadExt, AsyncWriteExt},
    net::{TcpListener, TcpStream},
    task::JoinHandle,
    time::sleep,
};

#[derive(Clone, Debug)]
struct MockResponse {
    status: u16,
    body: String,
    delay: Duration,
}

impl MockResponse {
    fn ok(content: &str) -> Self {
        Self {
            status: 200,
            body: json!({
                "choices": [{
                    "message": { "content": content },
                    "finish_reason": "stop"
                }]
            })
            .to_string(),
            delay: Duration::ZERO,
        }
    }

    fn status(status: u16, body: &str) -> Self {
        Self { status, body: body.to_string(), delay: Duration::ZERO }
    }

    fn delayed(status: u16, body: &str, delay: Duration) -> Self {
        Self { status, body: body.to_string(), delay }
    }
}

#[derive(Clone, Debug)]
struct RecordedRequest {
    method: String,
    path: String,
    headers: HashMap<String, String>,
    body: Value,
}

struct MockServer {
    addr: SocketAddr,
    requests: Arc<Mutex<Vec<RecordedRequest>>>,
    handle: JoinHandle<()>,
}

impl MockServer {
    async fn spawn(responses: Vec<MockResponse>) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").await.expect("failed to bind mock server");
        let addr = listener.local_addr().expect("failed to read mock server address");
        let responses = Arc::new(Mutex::new(VecDeque::from(responses)));
        let requests = Arc::new(Mutex::new(Vec::new()));
        let requests_for_task = Arc::clone(&requests);

        let handle = tokio::spawn(async move {
            loop {
                let (mut stream, _) = match listener.accept().await {
                    Ok(value) => value,
                    Err(_) => break,
                };

                let request = match read_request(&mut stream).await {
                    Ok(request) => request,
                    Err(_) => continue,
                };
                requests_for_task.lock().expect("request lock poisoned").push(request);

                let response =
                    responses.lock().expect("response lock poisoned").pop_front().unwrap_or_else(
                        || MockResponse::status(500, "no mock response configured"),
                    );
                if !response.delay.is_zero() {
                    sleep(response.delay).await;
                }

                let reason = match response.status {
                    200 => "OK",
                    400 => "Bad Request",
                    401 => "Unauthorized",
                    404 => "Not Found",
                    422 => "Unprocessable Entity",
                    429 => "Too Many Requests",
                    500 => "Internal Server Error",
                    _ => "Unknown",
                };
                let wire = format!(
                    "HTTP/1.1 {} {}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    response.status,
                    reason,
                    response.body.len(),
                    response.body
                );
                let _ = stream.write_all(wire.as_bytes()).await;
                let _ = stream.shutdown().await;
            }
        });

        Self { addr, requests, handle }
    }

    fn url(&self, path: &str) -> String {
        format!("http://{}{}", self.addr, path)
    }

    fn requests(&self) -> Vec<RecordedRequest> {
        self.requests.lock().expect("request lock poisoned").clone()
    }
}

impl Drop for MockServer {
    fn drop(&mut self) {
        self.handle.abort();
    }
}

async fn read_request(stream: &mut TcpStream) -> io::Result<RecordedRequest> {
    let mut buffer = Vec::new();
    let mut header_end = None;

    loop {
        let mut chunk = [0u8; 1024];
        let read = stream.read(&mut chunk).await?;
        if read == 0 {
            break;
        }
        buffer.extend_from_slice(&chunk[..read]);
        if let Some(position) = buffer.windows(4).position(|window| window == b"\r\n\r\n") {
            header_end = Some(position + 4);
            break;
        }
    }

    let header_end =
        header_end.ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "missing headers"))?;
    let header_text = String::from_utf8_lossy(&buffer[..header_end]);
    let mut lines = header_text.lines();
    let request_line = lines.next().unwrap_or_default();
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or_default().to_string();
    let path = parts.next().unwrap_or_default().to_string();

    let mut headers = HashMap::new();
    let mut content_length = 0usize;
    for line in lines {
        if let Some((key, value)) = line.split_once(':') {
            let key = key.trim().to_ascii_lowercase();
            let value = value.trim().to_string();
            if key == "content-length" {
                content_length = value.parse().unwrap_or(0);
            }
            headers.insert(key, value);
        }
    }

    while buffer.len() < header_end + content_length {
        let mut chunk = [0u8; 1024];
        let read = stream.read(&mut chunk).await?;
        if read == 0 {
            break;
        }
        buffer.extend_from_slice(&chunk[..read]);
    }

    let end = (header_end + content_length).min(buffer.len());
    let body = serde_json::from_slice(&buffer[header_end..end]).unwrap_or(Value::Null);

    Ok(RecordedRequest { method, path, headers, body })
}

fn structured_content(source: &str) -> String {
    json!({ "source": source }).to_string()
}

#[tokio::test]
async fn custom_base_url_model_and_unauthenticated_mode() {
    let server =
        MockServer::spawn(vec![MockResponse::ok(&structured_content("contract X {}"))]).await;
    let config =
        LlmConfig::custom(server.url("/v1"), None, "local-model", LlmResponseFormat::JsonSchema);
    let client = LlmClient::new(config).expect("config should validate");

    let outcome = client
        .complete_structured::<AnnotatedContractResponse>("annotate", "annotated_contract")
        .await
        .expect("completion should succeed");

    assert_eq!(outcome.value.source, "contract X {}");
    assert_eq!(outcome.mode, LlmResponseMode::JsonSchema);
    assert_eq!(outcome.attempted_modes, vec![LlmResponseMode::JsonSchema]);

    let requests = server.requests();
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0].method, "POST");
    assert_eq!(requests[0].path, "/v1/chat/completions");
    assert_eq!(requests[0].body["model"], "local-model");
    assert_eq!(requests[0].body["response_format"]["type"], "json_schema");
    assert_eq!(requests[0].body["response_format"]["json_schema"]["name"], "annotated_contract");
    assert!(!requests[0].headers.contains_key("authorization"));
}

#[tokio::test]
async fn auth_header_is_forwarded_when_configured() {
    let server =
        MockServer::spawn(vec![MockResponse::ok(&structured_content("contract X {}"))]).await;
    let config = LlmConfig::custom(
        server.url("/v1"),
        Some("secret-token".to_string()),
        "model-id",
        LlmResponseFormat::JsonSchema,
    );
    let client = LlmClient::new(config).expect("config should validate");

    client
        .complete_structured::<AnnotatedContractResponse>("annotate", "annotated_contract")
        .await
        .expect("completion should succeed");

    let requests = server.requests();
    assert_eq!(requests.len(), 1);
    assert_eq!(
        requests[0].headers.get("authorization").map(String::as_str),
        Some("Bearer secret-token")
    );
}

#[tokio::test]
async fn auto_falls_back_from_json_schema_to_json_object_to_text() {
    let server = MockServer::spawn(vec![
        MockResponse::status(
            400,
            r#"{"error":{"message":"response_format json_schema is not supported"}}"#,
        ),
        MockResponse::status(
            400,
            r#"{"error":{"message":"response_format json_object is unsupported"}}"#,
        ),
        MockResponse::ok("```json\n{\"source\":\"contract X {}\"}\n```"),
    ])
    .await;
    let config = LlmConfig::custom(server.url("/v1"), None, "local-model", LlmResponseFormat::Auto);
    let client = LlmClient::new(config).expect("config should validate");

    let outcome = client
        .complete_structured::<AnnotatedContractResponse>("annotate", "annotated_contract")
        .await
        .expect("auto fallback should succeed");

    assert_eq!(outcome.value.source, "contract X {}");
    assert_eq!(outcome.mode, LlmResponseMode::Text);
    assert_eq!(
        outcome.attempted_modes,
        vec![LlmResponseMode::JsonSchema, LlmResponseMode::JsonObject, LlmResponseMode::Text]
    );
    assert!(outcome.fallback_reason.is_some());

    let requests = server.requests();
    assert_eq!(requests.len(), 3);
    assert_eq!(requests[1].body["response_format"]["type"], "json_object");
    assert!(requests[2].body.get("response_format").is_none());
    assert!(requests[2].body["messages"][0]["content"].as_str().unwrap().contains("JSON Schema"));
}

#[tokio::test]
async fn fixed_formats_do_not_fall_back() {
    for format in [LlmResponseFormat::JsonSchema, LlmResponseFormat::JsonObject] {
        let server = MockServer::spawn(vec![MockResponse::status(
            400,
            r#"{"error":{"message":"response_format is not supported"}}"#,
        )])
        .await;
        let config = LlmConfig::custom(server.url("/v1"), None, "local-model", format);
        let client = LlmClient::new(config).expect("config should validate");

        let error = client
            .complete_structured::<AnnotatedContractResponse>("annotate", "annotated_contract")
            .await
            .expect_err("fixed format must not fall back");

        assert!(matches!(error, LlmError::ResponseFormatRejected { .. }));
        assert_eq!(server.requests().len(), 1);
    }
}

#[tokio::test]
async fn unrelated_http_errors_do_not_fall_back() {
    for status in [401, 404, 429, 500] {
        let server = MockServer::spawn(vec![MockResponse::status(status, "server failure")]).await;
        let config =
            LlmConfig::custom(server.url("/v1"), None, "local-model", LlmResponseFormat::Auto);
        let client = LlmClient::new(config).expect("config should validate");

        let error = client
            .complete_structured::<AnnotatedContractResponse>("annotate", "annotated_contract")
            .await
            .expect_err("HTTP failure must not fall back");

        assert!(
            matches!(error, LlmError::HttpStatus { status: observed, .. } if observed == status)
        );
        assert_eq!(server.requests().len(), 1);
    }
}

#[tokio::test]
async fn malformed_empty_and_truncated_responses_are_reported() {
    let malformed = MockServer::spawn(vec![MockResponse::ok("not json")]).await;
    let config =
        LlmConfig::custom(malformed.url("/v1"), None, "local-model", LlmResponseFormat::Text);
    let error = LlmClient::new(config)
        .expect("config should validate")
        .complete_structured::<AnnotatedContractResponse>("annotate", "annotated_contract")
        .await
        .expect_err("malformed content must fail");
    assert!(matches!(error, LlmError::MalformedResponse { .. }));

    let empty = MockServer::spawn(vec![MockResponse::ok("")]).await;
    let config = LlmConfig::custom(empty.url("/v1"), None, "local-model", LlmResponseFormat::Text);
    let error = LlmClient::new(config)
        .expect("config should validate")
        .complete_structured::<AnnotatedContractResponse>("annotate", "annotated_contract")
        .await
        .expect_err("empty content must fail");
    assert!(matches!(error, LlmError::EmptyContent));

    let truncated = MockServer::spawn(vec![MockResponse {
        status: 200,
        body: json!({
            "choices": [{
                "message": { "content": structured_content("contract X {}") },
                "finish_reason": "length"
            }]
        })
        .to_string(),
        delay: Duration::ZERO,
    }])
    .await;
    let config =
        LlmConfig::custom(truncated.url("/v1"), None, "local-model", LlmResponseFormat::Text);
    let error = LlmClient::new(config)
        .expect("config should validate")
        .complete_structured::<AnnotatedContractResponse>("annotate", "annotated_contract")
        .await
        .expect_err("truncated content must fail");
    assert!(matches!(error, LlmError::IncompleteResponse { .. }));
}

#[tokio::test]
async fn timeouts_are_reported() {
    let server =
        MockServer::spawn(vec![MockResponse::delayed(200, "late", Duration::from_millis(300))])
            .await;
    let config = LlmConfig::custom(server.url("/v1"), None, "local-model", LlmResponseFormat::Text)
        .with_timeout(Duration::from_millis(30));
    let error = LlmClient::new(config)
        .expect("config should validate")
        .complete_structured::<AnnotatedContractResponse>("annotate", "annotated_contract")
        .await
        .expect_err("timeout must fail");
    assert!(matches!(error, LlmError::Timeout));
}

#[test]
fn plaintext_key_to_nonlocal_host_is_rejected_before_any_request() {
    let config = LlmConfig::custom(
        "http://example.com/v1",
        Some("secret-token".to_string()),
        "model-id",
        LlmResponseFormat::Auto,
    );
    assert!(matches!(LlmClient::new(config), Err(LlmError::InsecureKeyTransport { .. })));
}

#[test]
fn legacy_openrouter_defaults_are_preserved() {
    let config = LlmConfig::openrouter("key", "");
    assert_eq!(config.base_url, OPENROUTER_API_BASE);
    assert_eq!(config.model, DEFAULT_MODEL);
    assert_eq!(config.response_format, LlmResponseFormat::Auto);
    assert_eq!(config.endpoint_label(), OPENROUTER_API_BASE);
}

#[tokio::test]
async fn plain_completion_returns_text_without_response_format() {
    let server = MockServer::spawn(vec![MockResponse::ok("plain answer")]).await;
    let config = LlmConfig::custom(server.url("/v1"), None, "local-model", LlmResponseFormat::Text);
    let outcome = LlmClient::new(config)
        .expect("config should validate")
        .complete("question")
        .await
        .expect("plain completion should succeed");

    assert_eq!(outcome.value, "plain answer");
    assert_eq!(outcome.mode, LlmResponseMode::Text);

    let requests = server.requests();
    assert_eq!(requests.len(), 1);
    assert!(requests[0].body.get("response_format").is_none());
}
