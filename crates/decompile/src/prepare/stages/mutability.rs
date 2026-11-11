//! Stage `mutability`: relax `pure` to `view` on state-reading functions.
//!
//! Port of `prepare_candidate.align_function_mutability`: once state variables
//! exist, a `pure` function whose body references one no longer compiles.
//! Parameter shadowing is respected; the whole header span (declaration and
//! provenance comment) is relaxed together.

use lazy_static::lazy_static;
use std::collections::BTreeSet;

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::{header_params, mask},
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_PURE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bpure\b").expect("failed to build regex");
    /// Declaration name after the type, skipping visibility/mutability
    /// modifiers; covers plain, `mapping(...)`, and fixed-array state.
    static ref RE_DECLARATION_NAME: fancy_regex::Regex = fancy_regex::Regex::new(
        "^(?:mapping\\s*\\([^)]*\\)|(?:address|uint\\d+|int\\d+|bytes\\d*|bytes|string|bool)(?:\\[[^\\]]*\\])*)\
         (?:\\s+(?:public|private|internal|constant|immutable|override))*\
         \\s+([A-Za-z_]\\w*)",
    )
    .expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let parsed = parse_contract(source, None)?;
    let mut state_names = BTreeSet::new();
    for unit in parsed.declarations() {
        if let Some(name) = RE_DECLARATION_NAME
            .captures(&unit.header)
            .ok()
            .flatten()
            .and_then(|c| c.get(1).map(|m| m.as_str().to_string()))
        {
            state_names.insert(name);
        }
    }

    let mut edits: Vec<StageEdit> = Vec::new();
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;
    for unit in parsed.functions() {
        let header_masked = mask(&unit.header)?;
        if !RE_PURE.is_match(&header_masked).unwrap_or(false) {
            continue;
        }
        let header_len = unit.header.len();
        let body_masked = mask(&unit.text)?;
        let body_masked = &body_masked[header_len.min(body_masked.len())..];
        let param_names: BTreeSet<String> =
            header_params(&header_masked).into_iter().map(|(_, name)| name).collect();
        let readable: Vec<&String> = state_names.difference(&param_names).collect();
        let reads_state = readable.iter().any(|name| {
            fancy_regex::Regex::new(&format!(r"\b{}\b", fancy_regex::escape(name)))
                .expect("failed to build regex")
                .is_match(body_masked)
                .unwrap_or(false)
        });
        if !reads_state {
            continue;
        }
        let (start, end) = (unit.start, unit.start + header_len);
        // the header span covers the @custom:signature comment and the
        // declaration; relax every `pure` in it so the provenance stays in sync
        let relaxed = RE_PURE.replace_all(&source[start..end], "view").to_string();
        pieces.push(source[last..start].to_string());
        pieces.push(relaxed);
        last = end;
        edits.push(StageEdit {
            kind: "mutability-relaxed".to_string(),
            detail: "pure -> view".to_string(),
            evidence: "pure function body reads contract state".to_string(),
        });
    }

    let staged = if pieces.is_empty() {
        source.to_string()
    } else {
        pieces.push(source[last..].to_string());
        pieces.concat()
    };
    Ok(Stage {
        name: "mutability",
        description: "pure vs state reads",
        source: staged,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn pure_reading_state_is_relaxed_to_view() {
        let source = concat!(
            "contract C {\n",
            "    uint256 var_c;\n",
            "    function f() public pure {\n",
            "        if (0 < var_c) {\n",
            "            return;\n",
            "        }\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("function f() public view {"));
    }

    #[test]
    fn pure_with_only_shadowed_state_name_stays_pure() {
        let source = concat!(
            "contract C {\n",
            "    uint256 var_c;\n",
            "    function f(uint256 var_c) public pure returns (uint256) {\n",
            "        return var_c + 1;\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("function f(uint256 var_c) public pure returns (uint256) {"));
    }

    #[test]
    fn mutability_reads_modified_and_mapping_state() {
        let source = concat!(
            "contract C {\n",
            "    uint256 public var_c;\n",
            "    mapping(address => uint256) public balances;\n",
            "    uint256[] var_a;\n",
            "    function f() public pure returns (uint256) {\n",
            "        return var_c + balances(address(0)) + var_a.length;\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("function f() public view returns (uint256) {"));
    }
}
