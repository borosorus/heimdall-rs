//! Backwards-compatible OpenRouter helpers.
//!
//! New code should use [`crate::resources::llm`] so the base URL, model, authentication and
//! response format can be configured explicitly. These wrappers preserve the original public
//! functions and default to OpenRouter.

pub use crate::resources::llm::{
    AnnotatedContractResponse, LlmConfig, LlmError, LlmOutcome, LlmResponseFormat, LlmResponseMode,
    DEFAULT_MODEL, OPENROUTER_API_BASE,
};

use serde::{de::DeserializeOwned, Serialize};
use tracing::error;

use crate::resources::llm::DEFAULT_TEXT_TIMEOUT;

/// Complete the given prompt via chat using the OpenRouter API.
///
/// OpenRouter provides access to multiple LLM providers through a unified API.
/// Models are specified in the format "provider/model-name" (e.g., "openai/gpt-4o").
///
/// ```
/// use heimdall_common::resources::openrouter::complete_chat;
///
/// let prompt = "what is love?";
/// let api_key = "your-openrouter-api-key";
/// let model = "openai/gpt-4o-mini";
/// // complete_chat(prompt, api_key, model).await;
/// ```
pub async fn complete_chat(prompt: &str, api_key: &str, model: &str) -> Option<String> {
    let config = LlmConfig::openrouter(api_key, model).with_timeout(DEFAULT_TEXT_TIMEOUT);
    match crate::resources::llm::complete_chat_with_config(prompt, &config).await {
        Ok(outcome) => Some(outcome.value),
        Err(error) => {
            error!("failed to create completion request: {error}");
            None
        }
    }
}

/// Complete the given prompt via chat using structured JSON output via the OpenRouter API.
///
/// This function uses JSON Schema to ensure the response matches the expected structure.
///
/// ```
/// use heimdall_common::resources::openrouter::{complete_chat_structured, AnnotatedContractResponse};
///
/// let prompt = "Annotate this contract";
/// let api_key = "your-openrouter-api-key";
/// let model = "openai/gpt-4o-mini";
/// // complete_chat_structured::<AnnotatedContractResponse>(prompt, api_key, model, "annotated_contract").await;
/// ```
pub async fn complete_chat_structured<T: DeserializeOwned + Clone + Serialize>(
    prompt: &str,
    api_key: &str,
    model: &str,
    schema_name: &str,
) -> Option<T> {
    let config = LlmConfig::openrouter(api_key, model);
    match crate::resources::llm::complete_chat_structured_with_config::<T>(
        prompt,
        &config,
        schema_name,
    )
    .await
    {
        Ok(outcome) => Some(outcome.value),
        Err(error) => {
            error!("failed to create completion request: {error}");
            None
        }
    }
}
