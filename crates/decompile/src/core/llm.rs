//! LLM post-processing configuration and reporting for decompilation.

use heimdall_common::resources::llm::{
    AnnotatedContractResponse, LlmConfig, LlmOutcome, LlmResponseMode,
};
use serde::Serialize;

/// Report describing whether LLM post-processing was requested and what happened.
///
/// The report never contains credentials or reference Solidity; it is intended to make LLM
/// post-processing auditable alongside the deterministic baseline output.
#[derive(Debug, Clone, Serialize)]
pub struct LlmPostprocessReport {
    /// Whether LLM post-processing was requested.
    pub requested: bool,
    /// Whether an LLM response was accepted and applied to the final source.
    pub applied: bool,
    /// Credential-free endpoint label.
    pub endpoint: Option<String>,
    /// Model identifier sent to the endpoint.
    pub model: Option<String>,
    /// Requested structured-output format.
    pub requested_format: Option<String>,
    /// Format that produced the accepted response.
    pub response_mode: Option<LlmResponseMode>,
    /// Formats attempted, in order.
    pub attempted_modes: Vec<LlmResponseMode>,
    /// Reason for a format fallback, if one occurred.
    pub fallback_reason: Option<String>,
    /// Wall-clock latency of the successful request in milliseconds.
    pub latency_ms: u64,
    /// Error that prevented the response from being applied, if any.
    pub error: Option<String>,
}

impl LlmPostprocessReport {
    /// A report for a decompilation that did not request LLM post-processing.
    pub(crate) fn not_requested() -> Self {
        Self {
            requested: false,
            applied: false,
            endpoint: None,
            model: None,
            requested_format: None,
            response_mode: None,
            attempted_modes: Vec::new(),
            fallback_reason: None,
            latency_ms: 0,
            error: None,
        }
    }

    /// A report for a requested LLM post-processing pass that has not completed yet.
    pub(crate) fn requested(config: &LlmConfig) -> Self {
        Self {
            requested: true,
            applied: false,
            endpoint: Some(config.endpoint_label()),
            model: Some(config.model.clone()),
            requested_format: Some(config.response_format.to_string()),
            response_mode: None,
            attempted_modes: Vec::new(),
            fallback_reason: None,
            latency_ms: 0,
            error: None,
        }
    }

    /// Record a successful, validated response.
    pub(crate) fn record_success(&mut self, outcome: &LlmOutcome<AnnotatedContractResponse>) {
        self.applied = true;
        self.response_mode = Some(outcome.mode);
        self.attempted_modes = outcome.attempted_modes.clone();
        self.fallback_reason = outcome.fallback_reason.clone();
        self.latency_ms = outcome.latency.as_millis() as u64;
        self.error = None;
    }

    /// Record a failure while retaining the deterministic baseline source.
    pub(crate) fn record_failure(&mut self, error: &dyn std::fmt::Display) {
        self.applied = false;
        self.error = Some(error.to_string());
    }
}
