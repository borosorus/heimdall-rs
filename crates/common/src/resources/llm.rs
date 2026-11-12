//! Provider-neutral client for OpenAI-compatible chat-completions APIs.
//!
//! The client is intentionally small: it sends one non-streaming chat-completions request,
//! validates the response, and reports how structured output was obtained. It does not store
//! credentials in logs or error messages.

use std::{
    fmt,
    str::FromStr,
    time::{Duration, Instant},
};

use reqwest::{Client, StatusCode, Url};
use serde::{de::DeserializeOwned, Deserialize, Serialize};
use serde_json::{json, Value};
use tracing::{debug, error};

/// The default model used by the OpenRouter compatibility path.
pub const DEFAULT_MODEL: &str = "openai/gpt-4o-mini";

/// The default OpenRouter API base URL.
pub const OPENROUTER_API_BASE: &str = "https://openrouter.ai/api/v1";

/// Default timeout for structured completions.
pub const DEFAULT_STRUCTURED_TIMEOUT: Duration = Duration::from_secs(120);

/// Default timeout for custom endpoints, which may run reasoning models.
pub const DEFAULT_CUSTOM_TIMEOUT: Duration = Duration::from_secs(600);

/// Default completion-token budget for custom endpoints.
///
/// Reasoning models can spend thousands of tokens before emitting final content.
pub const DEFAULT_CUSTOM_MAX_TOKENS: u32 = 32_768;

/// Default timeout for plain-text completions.
pub const DEFAULT_TEXT_TIMEOUT: Duration = Duration::from_secs(90);

/// Requested response format for a structured completion.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum LlmResponseFormat {
    /// Try JSON Schema, then JSON object, then prompt-based JSON when the server rejects the
    /// requested format.
    #[default]
    Auto,
    /// Require a strict JSON Schema response. Never falls back.
    JsonSchema,
    /// Require an OpenAI JSON-object response. Never falls back.
    JsonObject,
    /// Use prompt-based JSON without a `response_format` field. Never falls back.
    Text,
}

impl fmt::Display for LlmResponseFormat {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let value = match self {
            Self::Auto => "auto",
            Self::JsonSchema => "json-schema",
            Self::JsonObject => "json-object",
            Self::Text => "text",
        };
        f.write_str(value)
    }
}

impl FromStr for LlmResponseFormat {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_ascii_lowercase().replace('_', "-").as_str() {
            "auto" => Ok(Self::Auto),
            "json-schema" | "jsonschema" => Ok(Self::JsonSchema),
            "json-object" | "jsonobject" => Ok(Self::JsonObject),
            "text" | "plain" => Ok(Self::Text),
            other => Err(format!(
                "invalid response format '{other}'; expected auto, json-schema, json-object or text"
            )),
        }
    }
}

impl LlmResponseFormat {
    fn modes(self) -> Vec<LlmResponseMode> {
        match self {
            Self::Auto => {
                vec![
                    LlmResponseMode::JsonSchema,
                    LlmResponseMode::JsonObject,
                    LlmResponseMode::Text,
                ]
            }
            Self::JsonSchema => vec![LlmResponseMode::JsonSchema],
            Self::JsonObject => vec![LlmResponseMode::JsonObject],
            Self::Text => vec![LlmResponseMode::Text],
        }
    }
}

/// The response mode that actually produced a successful completion.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum LlmResponseMode {
    /// A strict JSON Schema response.
    JsonSchema,
    /// An OpenAI JSON-object response.
    JsonObject,
    /// Prompt-based JSON or plain text.
    Text,
}

impl LlmResponseMode {
    fn label(self) -> &'static str {
        match self {
            Self::JsonSchema => "json_schema",
            Self::JsonObject => "json_object",
            Self::Text => "text",
        }
    }
}

/// Configuration for an OpenAI-compatible chat-completions endpoint.
#[derive(Clone)]
pub struct LlmConfig {
    /// Full API base URL, for example `http://127.0.0.1:11434/v1`.
    pub base_url: String,
    /// Optional bearer token. Local unauthenticated servers may omit it.
    pub api_key: Option<String>,
    /// Model identifier sent to the endpoint verbatim.
    pub model: String,
    /// Requested structured response format.
    pub response_format: LlmResponseFormat,
    /// Per-request timeout.
    pub timeout: Duration,
    /// Optional completion-token cap. `None` omits `max_tokens` from the request.
    pub max_tokens: Option<u32>,
    /// Optional reasoning-effort request, forwarded as `reasoning_effort` verbatim.
    /// `None` omits the field, keeping the request body identical to the legacy form.
    pub reasoning_effort: Option<String>,
}

impl fmt::Debug for LlmConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LlmConfig")
            .field("base_url", &self.endpoint_label())
            .field("api_key", &self.api_key.as_ref().map(|_| "<redacted>"))
            .field("model", &self.model)
            .field("response_format", &self.response_format)
            .field("timeout", &self.timeout)
            .field("max_tokens", &self.max_tokens)
            .field("reasoning_effort", &self.reasoning_effort)
            .finish()
    }
}

impl LlmConfig {
    /// Creates an OpenRouter configuration using the existing default base URL.
    ///
    /// An empty model falls back to [`DEFAULT_MODEL`], preserving the old CLI behavior.
    pub fn openrouter(api_key: impl Into<String>, model: impl Into<String>) -> Self {
        let model = model.into();
        Self {
            base_url: OPENROUTER_API_BASE.to_string(),
            api_key: non_empty_key(api_key.into()),
            model: if model.trim().is_empty() { DEFAULT_MODEL.to_string() } else { model },
            response_format: LlmResponseFormat::Auto,
            timeout: DEFAULT_STRUCTURED_TIMEOUT,
            max_tokens: None,
            reasoning_effort: None,
        }
    }

    /// Creates a configuration for a custom OpenAI-compatible endpoint.
    ///
    /// Validation is deferred to [`Self::validate`] or [`LlmClient::new`] so callers can report a
    /// single actionable error before decompilation starts.
    pub fn custom(
        base_url: impl Into<String>,
        api_key: Option<String>,
        model: impl Into<String>,
        response_format: LlmResponseFormat,
    ) -> Self {
        Self {
            base_url: base_url.into(),
            api_key: api_key.and_then(non_empty_key),
            model: model.into(),
            response_format,
            timeout: DEFAULT_CUSTOM_TIMEOUT,
            max_tokens: Some(DEFAULT_CUSTOM_MAX_TOKENS),
            reasoning_effort: None,
        }
    }

    /// Sets the per-request timeout.
    #[must_use]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// Sets or clears the completion-token cap.
    #[must_use]
    pub fn with_max_tokens(mut self, max_tokens: Option<u32>) -> Self {
        self.max_tokens = max_tokens;
        self
    }

    /// Sets or clears the reasoning-effort request.
    #[must_use]
    pub fn with_reasoning_effort(mut self, effort: Option<String>) -> Self {
        self.reasoning_effort = effort;
        self
    }

    /// Returns a credential-free endpoint label suitable for logs and reports.
    #[must_use]
    pub fn endpoint_label(&self) -> String {
        match Url::parse(self.base_url.trim()) {
            Ok(mut url) => {
                url.set_query(None);
                url.set_fragment(None);
                url.set_password(None).ok();
                url.set_username("").ok();
                url.to_string()
            }
            Err(_) => "<invalid LLM base URL>".to_string(),
        }
    }

    /// Validates the base URL, model and key transport policy.
    pub fn validate(&self) -> Result<(), LlmError> {
        let base_url = self.base_url.trim();
        if base_url.is_empty() {
            return Err(LlmError::InvalidBaseUrl { reason: "base URL is empty".to_string() });
        }

        let url = Url::parse(base_url)
            .map_err(|error| LlmError::InvalidBaseUrl { reason: error.to_string() })?;
        if !matches!(url.scheme(), "http" | "https") {
            return Err(LlmError::InvalidBaseUrl {
                reason: format!("unsupported scheme '{}'; expected http or https", url.scheme()),
            });
        }
        let Some(host) = url.host_str() else {
            return Err(LlmError::InvalidBaseUrl { reason: "URL must include a host".to_string() });
        };
        if !url.username().is_empty() || url.password().is_some() {
            return Err(LlmError::InvalidBaseUrl {
                reason: "URL must not contain userinfo credentials".to_string(),
            });
        }
        if url.fragment().is_some() {
            return Err(LlmError::InvalidBaseUrl {
                reason: "URL must not contain a fragment".to_string(),
            });
        }
        if self.model.trim().is_empty() {
            return Err(LlmError::MissingModel);
        }
        if self.timeout.is_zero() {
            return Err(LlmError::InvalidTimeout);
        }
        if self.max_tokens == Some(0) {
            return Err(LlmError::InvalidMaxTokens);
        }
        if self.reasoning_effort.as_deref() == Some("") {
            return Err(LlmError::InvalidReasoningEffort);
        }
        if url.scheme() == "http"
            && !is_local_host(host)
            && self.api_key.as_deref().is_some_and(|key| !key.trim().is_empty())
        {
            return Err(LlmError::InsecureKeyTransport { host: host.to_string() });
        }

        Ok(())
    }

    /// Returns the full chat-completions URL, preserving the supplied base path.
    #[must_use]
    pub fn chat_completions_url(&self) -> String {
        let Ok(mut url) = Url::parse(self.base_url.trim()) else {
            return self.base_url.clone();
        };

        if !url.path().trim_end_matches('/').ends_with("/chat/completions") {
            let mut path = url.path().trim_end_matches('/').to_string();
            path.push_str("/chat/completions");
            url.set_path(&path);
        }

        url.to_string()
    }
}

fn non_empty_key(key: String) -> Option<String> {
    (!key.trim().is_empty()).then_some(key)
}

fn is_local_host(host: &str) -> bool {
    let host = host.trim_start_matches('[').trim_end_matches(']');
    host.eq_ignore_ascii_case("localhost")
        || host == "127.0.0.1"
        || host == "::1"
        || host.ends_with(".localhost")
}

/// Errors returned by the OpenAI-compatible client.
#[derive(Debug, thiserror::Error)]
pub enum LlmError {
    /// The configured base URL is not usable.
    #[error("invalid LLM base URL: {reason}")]
    InvalidBaseUrl {
        /// Human-readable reason.
        reason: String,
    },
    /// A custom endpoint was selected without an explicit model.
    #[error("LLM model ID is empty; a custom endpoint requires an explicit model")]
    MissingModel,
    /// The configured timeout is zero.
    #[error("LLM request timeout must be greater than zero")]
    InvalidTimeout,
    /// The configured completion-token cap is zero.
    #[error("LLM max_tokens must be greater than zero when set")]
    InvalidMaxTokens,
    /// The configured reasoning effort is empty.
    #[error("LLM reasoning_effort must not be empty when set")]
    InvalidReasoningEffort,
    /// A key would be sent over plaintext HTTP to a non-local host.
    #[error("refusing to send an API key over plaintext HTTP to non-local host '{host}'")]
    InsecureKeyTransport {
        /// Host that would receive the key.
        host: String,
    },
    /// The request timed out.
    #[error("LLM request timed out")]
    Timeout,
    /// A transport-level failure occurred.
    #[error("LLM request failed: {message}")]
    Transport {
        /// Sanitized transport error.
        message: String,
    },
    /// The endpoint returned a non-success HTTP status.
    #[error("LLM endpoint returned HTTP {status}: {body}")]
    HttpStatus {
        /// HTTP status code.
        status: u16,
        /// Bounded response body.
        body: String,
    },
    /// The endpoint explicitly rejected the requested response format.
    #[error("LLM endpoint rejected response format '{format}': {message}")]
    ResponseFormatRejected {
        /// Format that was rejected.
        format: &'static str,
        /// HTTP status code.
        status: u16,
        /// Bounded response body.
        message: String,
    },
    /// The response body was not valid JSON or did not match the expected shape.
    #[error("LLM response was malformed: {message}")]
    MalformedResponse {
        /// Description of the malformed response.
        message: String,
        /// Bounded raw content, when available.
        raw_content: Option<String>,
    },
    /// The model returned no content.
    #[error("LLM response content was empty")]
    EmptyContent,
    /// The model stopped because of a length limit or content filter.
    #[error("LLM response was incomplete (finish_reason={finish_reason})")]
    IncompleteResponse {
        /// Provider-reported finish reason.
        finish_reason: String,
    },
}

/// Result of a successful completion, including how the response was obtained.
#[derive(Debug, Clone)]
pub struct LlmOutcome<T> {
    /// Parsed or decoded value.
    pub value: T,
    /// Mode that produced the successful response.
    pub mode: LlmResponseMode,
    /// Modes attempted, in order.
    pub attempted_modes: Vec<LlmResponseMode>,
    /// Reason for the first format downgrade, if any.
    pub fallback_reason: Option<String>,
    /// Wall-clock latency of the successful request and parsing.
    pub latency: Duration,
}

/// A client bound to one validated [`LlmConfig`].
pub struct LlmClient {
    config: LlmConfig,
    http: Client,
}

impl fmt::Debug for LlmClient {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LlmClient")
            .field("endpoint", &self.endpoint_label())
            .field("model", &self.config.model)
            .finish()
    }
}

impl LlmClient {
    /// Creates a client and validates the configuration.
    pub fn new(config: LlmConfig) -> Result<Self, LlmError> {
        config.validate()?;
        let http = Client::builder()
            .timeout(config.timeout)
            .redirect(reqwest::redirect::Policy::none())
            .user_agent(concat!("heimdall-rs/", env!("CARGO_PKG_VERSION")))
            .build()
            .map_err(|error| LlmError::Transport { message: error.without_url().to_string() })?;
        Ok(Self { config, http })
    }

    /// Returns the credential-free endpoint label.
    #[must_use]
    pub fn endpoint_label(&self) -> String {
        self.config.endpoint_label()
    }

    /// Returns the configured model identifier.
    #[must_use]
    pub fn model(&self) -> &str {
        &self.config.model
    }

    /// Completes a prompt as plain text.
    pub async fn complete(&self, prompt: &str) -> Result<LlmOutcome<String>, LlmError> {
        let started = Instant::now();
        let content = self.send_request(prompt, LlmResponseMode::Text, "").await?;
        Ok(LlmOutcome {
            value: content,
            mode: LlmResponseMode::Text,
            attempted_modes: vec![LlmResponseMode::Text],
            fallback_reason: None,
            latency: started.elapsed(),
        })
    }

    /// Completes a prompt and parses a JSON object into `T`.
    ///
    /// The request schema is fixed to the annotated-contract shape (`{"source": "..."}`). Callers
    /// that need domain validation should validate the parsed value.
    pub async fn complete_structured<T: DeserializeOwned + Clone + Serialize>(
        &self,
        prompt: &str,
        schema_name: &str,
    ) -> Result<LlmOutcome<T>, LlmError> {
        let started = Instant::now();
        let schema = annotated_contract_schema();
        let modes = self.config.response_format.modes();
        let mut attempted_modes = Vec::new();
        let mut fallback_reason = None;
        let mut last_error = None;

        for (index, mode) in modes.iter().copied().enumerate() {
            attempted_modes.push(mode);
            let request_prompt = match mode {
                LlmResponseMode::JsonSchema => prompt.to_string(),
                LlmResponseMode::JsonObject | LlmResponseMode::Text => {
                    format!("{prompt}{}", structured_instruction(schema_name, &schema))
                }
            };

            match self.send_request(&request_prompt, mode, schema_name).await {
                Ok(content) => {
                    let parsed = parse_structured::<T>(&content)?;
                    return Ok(LlmOutcome {
                        value: parsed,
                        mode,
                        attempted_modes,
                        fallback_reason,
                        latency: started.elapsed(),
                    });
                }
                Err(error) => {
                    let can_fallback = self.config.response_format == LlmResponseFormat::Auto
                        && index + 1 < modes.len()
                        && matches!(error, LlmError::ResponseFormatRejected { .. });
                    if can_fallback {
                        fallback_reason.get_or_insert_with(|| error.to_string());
                        debug!(
                            endpoint = %self.endpoint_label(),
                            model = %self.config.model,
                            rejected_mode = mode.label(),
                            "response format rejected; trying compatibility fallback"
                        );
                        last_error = Some(error);
                        continue;
                    }
                    return Err(error);
                }
            }
        }

        Err(last_error.unwrap_or_else(|| LlmError::MalformedResponse {
            message: "no response format mode was attempted".to_string(),
            raw_content: None,
        }))
    }

    async fn send_request(
        &self,
        prompt: &str,
        mode: LlmResponseMode,
        schema_name: &str,
    ) -> Result<String, LlmError> {
        let url = self.config.chat_completions_url();
        let mut body = json!({
            "model": self.config.model,
            "messages": [{ "role": "user", "content": prompt }],
        });

        if let Some(max_tokens) = self.config.max_tokens {
            body["max_tokens"] = json!(max_tokens);
        }

        if let Some(effort) = &self.config.reasoning_effort {
            body["reasoning_effort"] = json!(effort);
        }

        if mode == LlmResponseMode::JsonSchema {
            body["response_format"] = json!({
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "description": "Annotated contract source code",
                    "schema": annotated_contract_schema(),
                    "strict": true,
                }
            });
        } else if mode == LlmResponseMode::JsonObject {
            body["response_format"] = json!({ "type": "json_object" });
        }

        debug!(
            endpoint = %self.endpoint_label(),
            model = %self.config.model,
            mode = mode.label(),
            "sending LLM chat-completions request"
        );

        let mut request = self.http.post(url.as_str()).json(&body);
        if let Some(api_key) = self.config.api_key.as_deref().filter(|key| !key.trim().is_empty()) {
            request = request.bearer_auth(api_key);
        }

        let response = request.send().await.map_err(|error| {
            if error.is_timeout() {
                LlmError::Timeout
            } else {
                LlmError::Transport { message: error.without_url().to_string() }
            }
        })?;

        let status = response.status();
        let response_body = response.text().await.map_err(|error| {
            if error.is_timeout() {
                LlmError::Timeout
            } else {
                LlmError::Transport { message: error.without_url().to_string() }
            }
        })?;

        if !status.is_success() {
            let body = bounded(&response_body);
            if is_response_format_rejection(status, &response_body) {
                return Err(LlmError::ResponseFormatRejected {
                    format: mode.label(),
                    status: status.as_u16(),
                    message: body,
                });
            }
            return Err(LlmError::HttpStatus { status: status.as_u16(), body });
        }

        let parsed: Value =
            serde_json::from_str(&response_body).map_err(|error| LlmError::MalformedResponse {
                message: format!("response body is not valid JSON: {error}"),
                raw_content: Some(bounded(&response_body)),
            })?;

        let choice = parsed
            .get("choices")
            .and_then(Value::as_array)
            .and_then(|choices| choices.first())
            .ok_or_else(|| LlmError::MalformedResponse {
                message: "response does not contain a nonempty choices array".to_string(),
                raw_content: Some(bounded(&response_body)),
            })?;

        if let Some(finish_reason) = choice.get("finish_reason").and_then(Value::as_str) {
            if matches!(finish_reason, "length" | "content_filter") {
                return Err(LlmError::IncompleteResponse {
                    finish_reason: finish_reason.to_string(),
                });
            }
        }

        let content = choice
            .get("message")
            .and_then(|message| message.get("content"))
            .and_then(Value::as_str)
            .ok_or_else(|| LlmError::MalformedResponse {
                message: "response choice does not contain string message.content".to_string(),
                raw_content: Some(bounded(&response_body)),
            })?;

        if content.trim().is_empty() {
            return Err(LlmError::EmptyContent);
        }

        Ok(content.to_string())
    }
}

fn annotated_contract_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "The annotated and cleaned up Solidity source code"
            }
        },
        "required": ["source"],
        "additionalProperties": false
    })
}

fn structured_instruction(schema_name: &str, schema: &Value) -> String {
    format!(
        "\n\nRespond with a single JSON object matching this JSON Schema named '{schema_name}'. \
         Do not include markdown fences or any text outside the JSON object:\n{schema}"
    )
}

fn parse_structured<T: DeserializeOwned + Clone + Serialize>(content: &str) -> Result<T, LlmError> {
    let content = strip_unambiguous_fence(content);
    let mut parsed: T =
        serde_json::from_str(content).map_err(|error| LlmError::MalformedResponse {
            message: format!("failed to parse structured response: {error}"),
            raw_content: Some(bounded(content)),
        })?;
    // models fence the SOURCE inside the JSON string too; the same unambiguous
    // rule applies to the parsed payload's `source` field when present
    normalize_embedded_source(&mut parsed);
    Ok(parsed)
}

/// Strips one unambiguous markdown fence from a struct's `source: String` field, if any.
fn normalize_embedded_source<T: DeserializeOwned + Clone + Serialize>(value: &mut T) {
    let Ok(json) = serde_json::to_value(&*value) else {
        return;
    };
    let Some(source) = json.get("source").and_then(|s| s.as_str()).map(str::to_string) else {
        return;
    };
    let stripped = strip_unambiguous_fence(&source);
    if stripped == source {
        return;
    }
    let mut updated = match serde_json::to_value(&*value) {
        Ok(Value::Object(map)) => map,
        _ => return,
    };
    updated.insert("source".to_string(), Value::String(stripped.to_string()));
    if let Ok(round) = serde_json::from_value::<T>(Value::Object(updated)) {
        *value = round;
    }
}

fn is_response_format_rejection(status: StatusCode, body: &str) -> bool {
    if !matches!(status.as_u16(), 400 | 422) {
        return false;
    }

    let body = body.to_ascii_lowercase();
    let mentions_format = body.contains("response_format")
        || body.contains("json_schema")
        || body.contains("json schema")
        || body.contains("structured output")
        || body.contains("json object");
    let mentions_rejection = body.contains("unsupported")
        || body.contains("not support")
        || body.contains("invalid")
        || body.contains("unknown")
        || body.contains("rejected");

    mentions_format && mentions_rejection
}

fn strip_unambiguous_fence(content: &str) -> &str {
    let trimmed = content.trim();
    if !trimmed.starts_with("```") {
        return trimmed;
    }
    let Some(first_newline) = trimmed.find('\n') else {
        return trimmed;
    };
    let inner = &trimmed[first_newline + 1..];
    let Some(close) = inner.rfind("```") else {
        return trimmed;
    };
    if !inner[close + 3..].trim().is_empty() || inner[..close].contains("```") {
        return trimmed;
    }
    inner[..close].trim()
}

fn bounded(value: &str) -> String {
    const LIMIT: usize = 512;
    if value.chars().count() <= LIMIT {
        return value.to_string();
    }
    let mut bounded = value.chars().take(LIMIT).collect::<String>();
    bounded.push_str("...");
    bounded
}

/// Structured output response for annotated contract source code.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnnotatedContractResponse {
    /// The annotated and cleaned up Solidity source code.
    pub source: String,
}

impl AnnotatedContractResponse {
    /// Validates that the model returned a nonempty Solidity contract.
    pub fn validate(&self) -> Result<(), LlmError> {
        if self.source.trim().is_empty() {
            return Err(LlmError::MalformedResponse {
                message: "structured response contained an empty source value".to_string(),
                raw_content: None,
            });
        }
        if !self.source.contains("contract") {
            return Err(LlmError::MalformedResponse {
                message: "structured response did not contain a `contract` declaration".to_string(),
                raw_content: None,
            });
        }
        Ok(())
    }
}

/// Completes a prompt and parses a JSON object using an explicit config.
pub async fn complete_chat_with_config(
    prompt: &str,
    config: &LlmConfig,
) -> Result<LlmOutcome<String>, LlmError> {
    LlmClient::new(config.clone())?.complete(prompt).await
}

/// Completes a prompt and parses a structured JSON object using an explicit config.
pub async fn complete_chat_structured_with_config<T: DeserializeOwned + Clone + Serialize>(
    prompt: &str,
    config: &LlmConfig,
    schema_name: &str,
) -> Result<LlmOutcome<T>, LlmError> {
    LlmClient::new(config.clone())?.complete_structured(prompt, schema_name).await
}

/// Compatibility wrapper: complete a prompt using OpenRouter defaults.
pub async fn complete_chat(prompt: &str, api_key: &str, model: &str) -> Option<String> {
    let config = LlmConfig::openrouter(api_key, model).with_timeout(DEFAULT_TEXT_TIMEOUT);
    match complete_chat_with_config(prompt, &config).await {
        Ok(outcome) => Some(outcome.value),
        Err(error) => {
            error!("failed to create completion request: {error}");
            None
        }
    }
}

/// Compatibility wrapper: complete a prompt with structured JSON using OpenRouter defaults.
pub async fn complete_chat_structured<T: DeserializeOwned + Clone + Serialize>(
    prompt: &str,
    api_key: &str,
    model: &str,
    schema_name: &str,
) -> Option<T> {
    let config = LlmConfig::openrouter(api_key, model);
    match complete_chat_structured_with_config::<T>(prompt, &config, schema_name).await {
        Ok(outcome) => Some(outcome.value),
        Err(error) => {
            error!("failed to create completion request: {error}");
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn response_format_parsing_is_case_and_separator_insensitive() {
        assert_eq!("AUTO".parse(), Ok(LlmResponseFormat::Auto));
        assert_eq!("json_schema".parse(), Ok(LlmResponseFormat::JsonSchema));
        assert_eq!("json-object".parse(), Ok(LlmResponseFormat::JsonObject));
        assert_eq!("plain".parse(), Ok(LlmResponseFormat::Text));
        assert!("yaml".parse::<LlmResponseFormat>().is_err());
    }

    #[test]
    fn annotated_source_must_contain_a_contract_declaration() {
        assert!(AnnotatedContractResponse { source: "contract X {}".to_string() }
            .validate()
            .is_ok());
        assert!(AnnotatedContractResponse { source: "```...```".to_string() }.validate().is_err());
        assert!(AnnotatedContractResponse { source: "   ".to_string() }.validate().is_err());
    }

    #[test]
    fn chat_completions_path_is_appended_once() {
        let config =
            LlmConfig::custom("http://127.0.0.1:1234/v1/", None, "m", LlmResponseFormat::Auto);
        assert_eq!(config.chat_completions_url(), "http://127.0.0.1:1234/v1/chat/completions");

        let already_complete = LlmConfig::custom(
            "http://127.0.0.1:1234/v1/chat/completions",
            None,
            "m",
            LlmResponseFormat::Auto,
        );
        assert_eq!(
            already_complete.chat_completions_url(),
            "http://127.0.0.1:1234/v1/chat/completions"
        );
    }

    #[test]
    fn embedded_source_fence_is_stripped_unambiguously() {
        let mut fenced =
            AnnotatedContractResponse { source: "```solidity\ncontract X {}\n```".to_string() };
        normalize_embedded_source(&mut fenced);
        assert_eq!(fenced.source, "contract X {}");

        let mut trailing_newline =
            AnnotatedContractResponse { source: "```solidity\ncontract X {}\n```\n".to_string() };
        normalize_embedded_source(&mut trailing_newline);
        assert_eq!(trailing_newline.source, "contract X {}");

        let mut plain = AnnotatedContractResponse { source: "contract X {}".to_string() };
        normalize_embedded_source(&mut plain);
        assert_eq!(plain.source, "contract X {}");

        // no closing fence: ambiguous, untouched
        let mut open =
            AnnotatedContractResponse { source: "```solidity\ncontract X {}".to_string() };
        normalize_embedded_source(&mut open);
        assert_eq!(open.source, "```solidity\ncontract X {}");
    }

    #[test]
    fn reasoning_effort_round_trips_and_validates() {
        let plain =
            LlmConfig::custom("http://127.0.0.1:1234/v1", None, "m", LlmResponseFormat::Auto);
        assert_eq!(plain.reasoning_effort, None);
        assert!(plain.validate().is_ok());

        let effort = plain.clone().with_reasoning_effort(Some("max".to_string()));
        assert_eq!(effort.reasoning_effort.as_deref(), Some("max"));
        assert!(effort.validate().is_ok());

        let cleared = effort.with_reasoning_effort(None);
        assert_eq!(cleared.reasoning_effort, None);

        let empty = plain.with_reasoning_effort(Some(String::new()));
        assert!(matches!(empty.validate(), Err(LlmError::InvalidReasoningEffort)));
    }

    #[test]
    fn invalid_urls_and_missing_models_are_rejected() {
        let invalid = LlmConfig::custom("ftp://127.0.0.1/v1", None, "m", LlmResponseFormat::Auto);
        assert!(matches!(invalid.validate(), Err(LlmError::InvalidBaseUrl { .. })));

        let missing_model =
            LlmConfig::custom("http://127.0.0.1:1234/v1", None, "", LlmResponseFormat::Auto);
        assert!(matches!(missing_model.validate(), Err(LlmError::MissingModel)));

        let userinfo = LlmConfig::custom(
            "http://user:pass@127.0.0.1:1234/v1",
            None,
            "m",
            LlmResponseFormat::Auto,
        );
        assert!(matches!(userinfo.validate(), Err(LlmError::InvalidBaseUrl { .. })));
    }

    #[test]
    fn plaintext_key_transport_is_rejected_only_for_nonlocal_hosts() {
        let remote = LlmConfig::custom(
            "http://example.com/v1",
            Some("secret".into()),
            "m",
            LlmResponseFormat::Auto,
        );
        assert!(matches!(remote.validate(), Err(LlmError::InsecureKeyTransport { .. })));

        let local = LlmConfig::custom(
            "http://127.0.0.1:1234/v1",
            Some("secret".into()),
            "m",
            LlmResponseFormat::Auto,
        );
        assert!(local.validate().is_ok());
    }

    #[test]
    fn debug_and_endpoint_labels_hide_credentials() {
        let config = LlmConfig::custom(
            "https://example.com/v1?api_key=supersecret",
            Some("also-secret".into()),
            "m",
            LlmResponseFormat::Auto,
        );
        let debug = format!("{config:?}");
        let label = config.endpoint_label();
        assert!(!debug.contains("also-secret"));
        assert!(!debug.contains("supersecret"));
        assert!(!label.contains("supersecret"));
    }

    #[test]
    fn fences_are_stripped_only_when_unambiguous() {
        assert_eq!(
            strip_unambiguous_fence("```json\n{\"source\":\"x\"}\n```"),
            "{\"source\":\"x\"}"
        );
        assert_eq!(
            strip_unambiguous_fence("prefix\n```json\n{\"source\":\"x\"}\n```\nsuffix"),
            "prefix\n```json\n{\"source\":\"x\"}\n```\nsuffix"
        );
    }
}
