# Configuring an OpenAI-compatible LLM provider

Heimdall's decompile post-processing can target any OpenAI-compatible chat-completions API. The
existing OpenRouter workflow remains the default when no custom base URL is configured.

This page covers the Phase 1 provider layer. It does not claim that a model improves decompilation;
that must be measured with the evaluation harness described in
[`llm-decompilation-evaluation-plan.md`](llm-decompilation-evaluation-plan.md).

## Decompile flags

| Flag | Purpose |
| --- | --- |
| `--llm-postprocess` (`-l`) | Request the optional LLM pass. Requires `--include-sol`. |
| `--llm-base-url <URL>` | Custom OpenAI-compatible base URL, for example `http://127.0.0.1:8000/v1`. |
| `--llm-api-key <KEY>` | Bearer token for the resolved endpoint. Empty means no `Authorization` header. |
| `--model <MODEL>` (`-m`) | Model ID sent verbatim to the endpoint. Required for custom endpoints. |
| `--llm-response-format <FORMAT>` | `auto`, `json-schema`, `json-object`, or `text`. |
| `--llm-max-tokens <TOKENS>` | Completion-token cap. Custom endpoints default to `32768`; OpenRouter omits the field. |
| `--llm-timeout <SECONDS>` | Per-request timeout. Custom endpoints default to `600`; OpenRouter to `120`. |
| `--llm-report <PATH>` | Write the post-processing report to an explicit path. |
| `--openrouter-api-key <KEY>` | Legacy OpenRouter-only override, preserved for compatibility. |
| `--no-update-check` | Global flag that skips the startup version-check request. |

## Configuration precedence

Resolution happens once in the CLI before decompilation:

1. Custom base URL: `--llm-base-url` > `HEIMDALL_LLM_BASE_URL` >
   `llm_base_url` in `~/.bifrost/config.toml`.
2. If any custom base URL is present, the endpoint is treated as custom:
   - API key: `--llm-api-key` > `HEIMDALL_LLM_API_KEY` > `llm_api_key`.
   - Model: `--model` > `llm_model`. A custom endpoint never inherits
     `openrouter_model`, `openrouter_api_key`, or MESC OpenRouter credentials.
3. If no custom base URL is present, OpenRouter is used:
   - API key: `--llm-api-key` > `--openrouter-api-key` > `HEIMDALL_LLM_API_KEY` >
     `llm_api_key` > `openrouter_api_key` (including MESC).
   - Model: `--model` > `llm_model` > `openrouter_model` > `openai/gpt-4o-mini`.
4. Response format: `--llm-response-format` > `llm_response_format` > `auto`.

The stored keys can be set with the existing config command:

```bash
heimdall --no-update-check config llm_base_url http://127.0.0.1:8000/v1
heimdall --no-update-check config llm_model your-served-model-id
heimdall --no-update-check config llm_response_format auto
```

To clear the stored key, edit `~/.bifrost/config.toml` and remove the `llm_api_key` value; the
`config` command itself only accepts nonempty values.

`heimdall config` prints a redacted `Configuration` view. API keys, RPC credentials, RPC paths, and
endpoint query parameters are not displayed.

## Structured-output behavior

`auto` tries the following modes in order:

1. `json_schema` with the fixed annotated-contract schema.
2. `json_object`.
3. Prompt-based JSON with no `response_format` field.

Fallback happens only when the endpoint explicitly rejects the requested format with HTTP 400 or
422. Authentication failures, missing endpoints, rate limits, server errors, timeouts, malformed
JSON, empty content, and truncated responses are reported as failures. A fixed format
(`json-schema`, `json-object`, or `text`) never falls back.

The schema name is `annotated_contract`, and the expected object is:

```json
{ "source": "complete annotated Solidity source" }
```

The returned source must be nonempty. Heimdall does not send reference Solidity, source diffs, or
evaluation-oracle information to the model.

## Reasoning models and token budgets

Reasoning models such as DeepSeek-style or vLLM `--reasoning-parser` deployments emit their
chain-of-thought in a separate `reasoning` field, but those tokens still count against the
request's completion budget. If the budget runs out before the model produces `content`, the
endpoint reports `finish_reason: "length"`, `content` is empty or null, and Heimdall records a
truncated-response failure while retaining the baseline source.

The budget needed depends on the model and prompt, and it does not grow linearly with output
length: a model can spend tens of thousands of tokens reasoning before converging. Custom
endpoints therefore default to `--llm-max-tokens 32768` and `--llm-timeout 600`. If the report
shows an incomplete response, raise both values, for example:

```bash
  --llm-max-tokens 65536 --llm-timeout 900
```

OpenRouter keeps its previous behavior: no `max_tokens` field (the provider default applies) and a
120-second timeout. Override either value explicitly when using OpenRouter.

The report records the effective `max_tokens` and `timeout_seconds` so a failed run can be
distinguished from a configuration that was never applied.

## Local endpoint examples

vLLM (served model ID must match `--model`; enable guided decoding if you want strict JSON Schema):

```bash
./target/release/heimdall --no-update-check decompile evaluation/fixtures/modern-simple/runtime.hex \
  --include-sol --skip-resolving --default \
  --llm-postprocess \
  --llm-base-url http://127.0.0.1:8000/v1 \
  --model your-served-model-id \
  --llm-response-format auto \
  --output /tmp/heimdall-llm
```

Ollama's OpenAI-compatible endpoint:

```bash
./target/release/heimdall --no-update-check decompile evaluation/fixtures/modern-simple/runtime.hex \
  --include-sol --skip-resolving --default \
  --llm-postprocess \
  --llm-base-url http://127.0.0.1:11434/v1 \
  --model qwen2.5-coder:7b \
  --llm-response-format json-object \
  --output /tmp/heimdall-ollama
```

LM Studio typically serves on `http://127.0.0.1:1234/v1`. No API key is required for these local
examples; if the endpoint requires one, add `--llm-api-key` or set `HEIMDALL_LLM_API_KEY`.

A plaintext API key is refused for non-local HTTP hosts. HTTPS is required for remote endpoints
that use a key. Redirects are not followed, and URLs with embedded userinfo are rejected.

## Output artifacts

With `--output <DIR>` and the default name, a successful post-processing run writes:

- `decompiled.sol` — final source, which may be the LLM candidate.
- `decompiled.baseline.sol` — deterministic source before the LLM pass.
- `llm-report.json` — audit report.
- `abi.json` — reconstructed ABI.

`--name foo` prefixes the source and ABI files (`foo-decompiled.sol`, etc.). `--llm-report <PATH>`
writes the report exactly where requested. If the LLM pass fails, decompilation still succeeds,
`decompiled.sol` remains byte-identical to the baseline, and the report records `applied: false`
plus the error. A fallback is never reported as LLM success.

Example report:

```json
{
  "requested": true,
  "applied": true,
  "endpoint": "http://127.0.0.1:8000/v1",
  "model": "your-served-model-id",
  "requested_format": "auto",
  "response_mode": "json-schema",
  "attempted_modes": ["json-schema"],
  "fallback_reason": null,
  "latency_ms": 842,
  "max_tokens": 32768,
  "timeout_seconds": 600,
  "error": null
}
```

## Verification

```bash
# Baseline and final source must both exist, and the report must record the outcome.
ls -l /tmp/heimdall-llm/decompiled.sol \
      /tmp/heimdall-llm/decompiled.baseline.sol \
      /tmp/heimdall-llm/llm-report.json
python3 -m json.tool /tmp/heimdall-llm/llm-report.json

# A failed pass retains the deterministic source.
cmp /tmp/heimdall-llm/decompiled.sol /tmp/heimdall-llm/decompiled.baseline.sol
```

For offline provider tests without a model, run:

```bash
cargo test -p heimdall-common --test llm_provider
cargo test -p heimdall-decompiler
```

Provider compatibility is not universal. Some servers ignore `response_format`, some require
guided-decoding configuration, and some emit reasoning text alongside JSON. Start with `auto`,
record the report, and treat any unverified source as a candidate rather than a correct
decompilation.
