//! Deterministic post-decompilation preparation of the recovered Solidity.
//!
//! Rust port of `evaluation/scripts/prepare_candidate.py`: an ordered ladder
//! of source-to-source repair stages that turns the raw decompiled output into
//! a compilable, dispatch-stable candidate without any model call or reference
//! knowledge. Every edit records its evidence; every case the source does not
//! cover is recorded as a finding instead of being guessed.
//!
//! The ladder runs behind the `--prepare` flag (default off, preserving the
//! standard decompilation output) immediately after source assembly and before
//! optional LLM post-processing, so downstream consumers always see the
//! prepared, still fully deterministic source.
//!
//! Byte-parity with the Python implementation is enforced by tests against
//! committed seed candidates; per-stage behavior is pinned by ports of the
//! Python test corpus.

mod parser;
mod stages;

use tracing::debug;

use crate::prepare::{
    parser::ParseError,
    stages::{declarations, placeholders, selfref, vars},
};

/// A single recorded source edit.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct StageEdit {
    pub kind: String,
    pub detail: String,
    pub evidence: String,
}

/// A recorded abstention: a case the stage's evidence does not cover.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct StageFinding {
    pub kind: String,
    pub detail: String,
    pub reason: String,
}

/// The outcome of one ladder stage.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct Stage {
    pub name: &'static str,
    pub description: &'static str,
    pub source: String,
    pub edits: Vec<StageEdit>,
    pub findings: Vec<StageFinding>,
}

/// A preparation failure; always a wrapped parse error of the input source.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub(crate) struct PreparationError(pub String);

/// The prepared source plus the per-stage ladder trace.
#[derive(Debug, Clone)]
pub(crate) struct Prepared {
    pub source: String,
    pub stages: Vec<Stage>,
}

/// A ladder stage entry point: a pure source transform.
type StageFn = fn(&str) -> Result<Stage, ParseError>;

/// The ladder, in execution order. Mirrors `prepare_candidate.PREPARE_STAGES`;
/// stages land here as their ports are completed and parity-checked.
const PREPARE_STAGES: &[(&str, StageFn)] = &[
    ("normalize_placeholders", placeholders::run),
    ("declare_missing_symbols", declarations::run),
    ("split_selfref_initializers", selfref::run),
    ("declare_undefined_vars", vars::run),
];

/// Runs the full preparation ladder over `source`.
pub(crate) fn prepare(source: &str) -> Result<Prepared, PreparationError> {
    run_stages(source, PREPARE_STAGES)
}

fn run_stages(source: &str, registry: &[(&str, StageFn)]) -> Result<Prepared, PreparationError> {
    let mut stages = Vec::new();
    let mut current = source.to_string();
    for (name, stage) in registry {
        let stage = stage(&current).map_err(|error| {
            PreparationError(format!("source does not parse before {name}: {error}"))
        })?;
        debug!(
            stage = stage.name,
            edits = stage.edits.len(),
            findings = stage.findings.len(),
            "prepare stage applied"
        );
        stages.push(stage);
        current = stages.last().expect("stage pushed").source.clone();
    }
    Ok(Prepared { source: current, stages })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ladder_matches_the_python_registry_prefix() {
        let names: Vec<&str> = PREPARE_STAGES.iter().map(|(name, _)| *name).collect();
        assert_eq!(
            names,
            vec![
                "normalize_placeholders",
                "declare_missing_symbols",
                "split_selfref_initializers",
                "declare_undefined_vars",
            ]
        );
    }

    #[test]
    fn parse_failures_name_the_stage_and_cause() {
        // unterminated string literal: the first masking stage fails
        let source = "contract C { uint a = \"unterminated; }\n";
        let error = prepare(source).unwrap_err();
        assert!(
            error.to_string().starts_with(
                "source does not parse before normalize_placeholders: unterminated string literal"
            ),
            "unexpected error: {error}"
        );
    }

    #[test]
    fn ladder_is_a_noop_on_plain_sources() {
        let source = "contract C { function f() public pure { } }\n";
        let prepared = prepare(source).unwrap();
        assert_eq!(prepared.source, source);
        assert!(prepared.stages.iter().all(|stage| stage.edits.is_empty()));
    }

    /// Byte-parity with the Python reference ladder: every implemented prefix
    /// must reproduce the committed `stageNN-*.sol` references (see
    /// `tests/parity/README.md`).
    #[test]
    fn matches_the_python_reference_ladder() {
        let root = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/parity");
        for case in ["erc20-raw", "blockreader-raw"] {
            let input = std::fs::read_to_string(format!("{root}/{case}/input.sol"))
                .expect("parity fixture input");
            for (index, _) in PREPARE_STAGES.iter().enumerate() {
                let staged = run_stages(&input, &PREPARE_STAGES[..=index]).unwrap();
                let stage_name = staged.stages.last().expect("prefix ran").name;
                let reference = std::fs::read_to_string(format!(
                    "{root}/{case}/stage{:02}-{stage_name}.sol",
                    index + 1
                ))
                .expect("parity fixture reference");
                assert_eq!(staged.source, reference, "{case} after prefix {}", index + 1);
            }
        }
    }
}
