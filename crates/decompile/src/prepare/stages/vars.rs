//! Stage `vars`: declare used-but-undeclared `var_*` state.
//!
//! Port of `prepare_candidate.declare_undefined_vars`: `var_*` identifiers
//! with no declaration become contract-level `uint256` state, inserted on the
//! line following the contract body's opening brace.

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
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    let used: BTreeSet<String> = RE_VAR_WORD
        .captures_iter(&masked)
        .flatten()
        .filter_map(|c| c.get(1).map(|m| m.as_str().into()))
        .collect();
    let mut declared: BTreeSet<String> = RE_DECL_UINT
        .captures_iter(&masked)
        .flatten()
        .filter_map(|c| c.get(1).map(|m| m.as_str().into()))
        .collect();
    // typed local definitions declare; bare assignment targets do not
    for c in RE_DECL_TYPED.captures_iter(&masked).flatten() {
        if let Some(m) = c.get(2) {
            declared.insert(m.as_str().to_string());
        }
    }
    let undeclared: BTreeSet<String> = used.difference(&declared).cloned().collect();

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
    let parsed = parse_contract(source, None)?;
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
}
