//! Stage `vars`: declare used-but-undeclared `var_*` state (unit-scoped).
//!
//! Port of `prepare_candidate.declare_undeclared_vars` /
//! `declare_undefined_vars`: a local declaration covers only its OWN unit
//! (the decompiler reuses register names across units, so a like-named local
//! elsewhere does NOT make a use visible - the lighthouse lesson);
//! contract-level state declarations (visibility qualifiers accepted) cover
//! every unit. A name used in some unit without a unit local or a state
//! declaration becomes contract-level `uint256`.

use lazy_static::lazy_static;
use std::collections::BTreeSet;

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::{body_open_line_end, mask},
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_VAR_WORD: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b(var_[a-z]+)\b").expect("failed to build regex");
    static ref RE_DECL_UINT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\buint\d*\s+(var_[a-z]+)\b").expect("failed to build regex");
    static ref RE_DECL_TYPED: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b(uint\d*|address|bool|bytes\d*)\s+(var_[a-z]+)\s*=[^=]",)
            .expect("failed to build regex");
    static ref RE_STATE_UINT_VIS: fancy_regex::Regex = fancy_regex::Regex::new(
        r"\buint\d*\s+(?:public|private|internal|constant|immutable|override|[ \t])*(var_[a-z]+)\b",
    )
    .expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    let parsed = parse_contract(source, None)?;
    let unit_spans: Vec<(usize, usize)> =
        parsed.functions().map(|unit| (unit.start, unit.end)).collect();
    let in_unit = |offset: usize| unit_spans.iter().any(|(a, b)| *a <= offset && offset < *b);

    // contract-level state declarations cover every unit
    let mut state_declared: BTreeSet<String> = RE_STATE_UINT_VIS
        .captures_iter(&masked)
        .flatten()
        .filter(|c| c.get(0).map(|m| !in_unit(m.start())).unwrap_or(false))
        .filter_map(|c| c.get(1).map(|m| m.as_str().into()))
        .collect();
    for c in RE_DECL_TYPED.captures_iter(&masked).flatten() {
        let outside = c.get(0).map(|m| !in_unit(m.start())).unwrap_or(false);
        if outside {
            if let Some(m) = c.get(2) {
                state_declared.insert(m.as_str().to_string());
            }
        }
    }

    // a use is covered by its OWN unit's locals plus the state declarations
    let mut missing: BTreeSet<String> = BTreeSet::new();
    for unit in parsed.functions() {
        let unit_masked = mask(&unit.text)?;
        let header_masked = mask(&unit.header)?;
        let used: BTreeSet<String> = RE_VAR_WORD
            .captures_iter(&unit_masked)
            .flatten()
            .filter_map(|c| c.get(1).map(|m| m.as_str().into()))
            .collect();
        let mut local: BTreeSet<String> = RE_DECL_UINT
            .captures_iter(&unit_masked)
            .flatten()
            .filter_map(|c| c.get(1).map(|m| m.as_str().into()))
            .collect();
        for c in RE_DECL_TYPED.captures_iter(&unit_masked).flatten() {
            if let Some(m) = c.get(2) {
                local.insert(m.as_str().to_string());
            }
        }
        for c in RE_VAR_WORD.captures_iter(&header_masked).flatten() {
            if let Some(m) = c.get(1) {
                local.insert(m.as_str().to_string());
            }
        }
        missing.extend(used.difference(&local).cloned());
    }
    let undeclared: BTreeSet<String> = missing.difference(&state_declared).cloned().collect();

    let mut edits: Vec<StageEdit> = Vec::new();
    if undeclared.is_empty() {
        return Ok(Stage {
            name: "vars",
            description: "undefined var_* state",
            source: source.to_string(),
            edits,
            findings: Vec::new(),
        });
    }
    let offset = body_open_line_end(source, parsed.body_start);
    let block: String = undeclared.iter().map(|name| format!("    uint256 {name};\n")).collect();
    let replacement = format!("{}{}{}", &source[..offset], block, &source[offset..]);
    for name in &undeclared {
        edits.push(StageEdit {
            kind: "undefined-var".to_string(),
            detail: format!("uint256 {name}"),
            evidence: "used before any declaration".to_string(),
        });
    }
    Ok(Stage {
        name: "vars",
        description: "undefined var_* state",
        source: replacement,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn declares_var_identifiers_once() {
        let source = concat!(
            "contract C {\n",
            "    function f() public returns (uint256) { return var_a + var_a; }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert_eq!(stage.source.matches("uint256 var_a;").count(), 1);
        assert_eq!(stage.edits.len(), 1);
    }

    #[test]
    fn leaves_declared_vars_alone() {
        let source = concat!(
            "contract C {\n",
            "    uint256 var_a;\n",
            "    function f() public returns (uint256) { var_a = 1; return var_a; }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert_eq!(stage.source, source);
        assert!(stage.edits.is_empty());
    }

    #[test]
    fn like_named_local_in_other_unit_does_not_declare() {
        // the lighthouse lesson: unit a's local must not cover unit b's use
        let source = concat!(
            "contract C {\n",
            "    function a() public pure { uint256 var_b = 0x1; var_b = var_b + 0x1; }\n",
            "    function b() public pure { var_b = 0x2; }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert!(stage.source.contains("uint256 var_b;\n"));
        assert_eq!(stage.edits.len(), 1);
    }

    #[test]
    fn visibility_qualified_state_declares() {
        let source = concat!(
            "contract C {\n",
            "    uint256 public var_c;\n",
            "    function f() public pure { var_c = 0x1; }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert_eq!(stage.source, source);
        assert!(stage.edits.is_empty());
    }
}
