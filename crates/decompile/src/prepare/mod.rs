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
mod storage_flow;

use tracing::debug;

use crate::prepare::{
    parser::ParseError,
    stages::{
        arity, coerce_word_returns, comparison_parens, declarations, fallback_shape,
        lower_unknown_external_calls, mutability, packed_scalars, param_types, placeholders,
        selfref, send_guards, slot_aliases, storage_getters, truthiness, typed_packed_literals,
        vars, view_emit_relaxation, widen_packed_pair_returns, wordify_address_mask,
    },
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
    ("align_function_mutability", mutability::run),
    ("align_arities", arity::run),
    ("unify_storage_views", slot_aliases::run),
    ("recover_packed_scalar_storage", packed_scalars::run),
    ("relax_truthiness_requires", truthiness::run),
    ("repair_fallback_shape", fallback_shape::run),
    ("infer_param_types_from_storage", param_types::run),
    ("synthesize_storage_getters", storage_getters::run),
    ("synthesize_send_guards", send_guards::run),
    ("typed_packed_literals", typed_packed_literals::run),
    ("wordify_address_mask_writes", wordify_address_mask::run),
    ("widen_packed_pair_returns", widen_packed_pair_returns::run),
    ("coerce_word_returns", coerce_word_returns::run),
    ("lower_unknown_external_calls", lower_unknown_external_calls::run),
    ("comparison_parens", comparison_parens::run),
    ("view_emit_relaxation", view_emit_relaxation::run),
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
                "align_function_mutability",
                "align_arities",
                "unify_storage_views",
                "recover_packed_scalar_storage",
                "relax_truthiness_requires",
                "repair_fallback_shape",
                "infer_param_types_from_storage",
                "synthesize_storage_getters",
                "synthesize_send_guards",
                "typed_packed_literals",
                "wordify_address_mask_writes",
                "widen_packed_pair_returns",
                "coerce_word_returns",
                "lower_unknown_external_calls",
                "comparison_parens",
                "view_emit_relaxation",
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

    /// Ported `PipelineTest`: the full ladder applies every tier in order and
    /// is idempotent on the decompiled-shaped baseline.
    const BASELINE: &str = concat!(
        "contract DecompiledContract {\n",
        "    error CustomError_00000000();\n",
        "    event Event_8c5be1e5();\n",
        "    address store_h;\n",
        "    mapping(address => uint256) public balances;\n",
        "\n",
        "    function Unresolved_095ea7b3(address arg0, uint0 arg1) public payable returns (bool) {\n",
        "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);\n",
        "        balances[msg.sender] = arg1;\n",
        "        require(msg.sender == store_h, CustomError_30cd7471());\n",
        "        return true;\n",
        "    }\n",
        "}\n",
    );

    #[test]
    fn full_ladder_applies_every_tier() {
        let staged = prepare(BASELINE).unwrap();
        let names: Vec<&str> = staged.stages.iter().map(|s| s.name).collect();
        assert_eq!(
            names,
            vec![
                "placeholders",
                "declarations",
                "selfref",
                "vars",
                "mutability",
                "arity",
                "slot-aliases",
                "packed-scalars",
                "truthiness",
                "fallback-shape",
                "param-types",
                "storage-getters",
                "send-guards",
                "typed-packed-literals",
                "wordify-address-mask",
                "widen-packed-pair-returns",
                "coerce-word-returns",
                "lower-unknown-external-calls",
                "comparison-parens",
                "view-emit-relaxation",
            ]
        );
        let staged_final = staged.source;
        assert!(staged_final.contains("uint256 arg1"));
        assert!(staged_final.contains("error CustomError_30cd7471();"));
    }

    #[test]
    fn ladder_is_idempotent() {
        let once = prepare(BASELINE).unwrap().source;
        let twice = prepare(&once).unwrap().source;
        assert_eq!(once, twice);
    }

    /// Byte-parity with the Python reference ladder: every implemented prefix
    /// must reproduce the committed `stageNN-*.sol` references (see
    /// `tests/parity/README.md`).
    #[test]
    fn matches_the_python_reference_ladder() {
        let root = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/parity");
        for case in ["erc20-raw", "blockreader-raw", "lighthouse-raw", "hdwallet-raw"] {
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
