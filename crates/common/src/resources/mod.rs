/// Provider-neutral OpenAI-compatible chat-completions integration.
pub mod llm;

/// Backwards-compatible OpenRouter helpers built on [`llm`].
pub mod openrouter;

/// Transpose API integration for blockchain data access.
pub mod transpose;
