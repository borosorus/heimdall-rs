//! Stage `coerce-word-returns`: coerce word-sized returns to the declared type.
//!
//! Port of `prepare_candidate.coerce_word_returns`: the decompiler emits
//! `return <state>;` where the state's declared width differs from the
//! unit's single-word return (a `uint128` state from an `address`-returning
//! unit, observed on lighthouse read()); the EVM simply returned the word.
//! Explicit conversions make that faithful: into `address` via
//! `address(uint160(..))`, into `bytes32` via `bytes32(uint256(..))`.
//! Bare-identifier returns only; wider/narrower cases abstain.

use lazy_static::lazy_static;
use std::collections::HashMap;

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::mask,
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_STATE_ANY: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b(address|bytes32|uint\d+)\s+([A-Za-z_]\w*)\s*;")
            .expect("failed to build regex");
    static ref RE_RETURN: fancy_regex::Regex =
        fancy_regex::Regex::new(r"(?P<indent>[ \t]*)return\s+(?P<expr>[A-Za-z_]\w*)\s*;")
            .expect("failed to build regex");
    static ref RE_RETURNS_SINGLE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"returns\s*\((?P<t>[A-Za-z_0-9]+)\)")
            .expect("failed to build regex");
    static ref RE_UINT_STATE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^u?int\d+$").expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    // Python wraps the parse in try/except and abstains on failure
    let Ok(parsed) = parse_contract(source, None) else {
        return Ok(Stage {
            name: "coerce-word-returns",
            description: "word return coercion",
            source: source.to_string(),
            edits: Vec::new(),
            findings: Vec::new(),
        });
    };

    let unit_spans: Vec<(usize, usize)> =
        parsed.functions().map(|unit| (unit.start, unit.end)).collect();
    let in_unit = |offset: usize| unit_spans.iter().any(|(a, b)| *a <= offset && offset < *b);
    let mut state_types: HashMap<String, String> = HashMap::new();
    for captures in RE_STATE_ANY.captures_iter(&masked).flatten() {
        if let (Some(kind), Some(name)) = (captures.get(1), captures.get(2)) {
            if !in_unit(name.start()) {
                state_types.insert(name.as_str().to_string(), kind.as_str().to_string());
            }
        }
    }

    let mut edits: Vec<StageEdit> = Vec::new();
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;
    for unit in parsed.functions() {
        let header_masked =
            crate::prepare::parser::mask_strings_and_comments(&unit.header, 0, unit.header.len())?;
        let Some(want) = RE_RETURNS_SINGLE
            .captures(&header_masked)
            .unwrap_or(None)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().to_string())
        else {
            continue;
        };
        if want != "address" && want != "bytes32" {
            continue;
        }
        let body_masked = mask(&unit.text)?;
        for captures in RE_RETURN.captures_iter(&body_masked).flatten() {
            let whole = captures.get(0).expect("whole match");
            let expr = captures.name("expr").expect("expr").as_str();
            let Some(src_type) = state_types.get(expr) else {
                continue;
            };
            if !RE_UINT_STATE.is_match(src_type).unwrap_or(false) {
                continue;
            }
            let conversion = if want == "address" {
                format!("address(uint160({expr}))")
            } else {
                format!("bytes32(uint256({expr}))")
            };
            let indent = captures.name("indent").expect("indent").as_str();
            let replacement = format!("{indent}return {conversion};");
            let abs_start = unit.start + whole.start();
            let abs_end = unit.start + whole.end();
            pieces.push(source[last..abs_start].to_string());
            pieces.push(replacement);
            last = abs_end;
            edits.push(StageEdit {
                kind: "word-return-coerced".to_string(),
                detail: format!("{}: return {expr} -> {conversion}", unit.name),
                evidence: "word-width-preserving return coercion to the declared type".to_string(),
            });
        }
    }

    if pieces.is_empty() {
        return Ok(Stage {
            name: "coerce-word-returns",
            description: "word return coercion",
            source: source.to_string(),
            edits,
            findings: Vec::new(),
        });
    }
    pieces.push(source[last..].to_string());
    Ok(Stage {
        name: "coerce-word-returns",
        description: "word return coercion",
        source: pieces.concat(),
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn uint_state_returning_address_is_coerced() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    uint128 store_e; // storage slot: 0x03\n",
            "    function f() public view returns (address) {\n",
            "        return store_e;\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("return address(uint160(store_e));"));
    }

    #[test]
    fn matching_widths_are_untouched() {
        let source = concat!(
            "contract C {\n",
            "    address store_h; // storage slot: 0x04\n",
            "    function f() public view returns (address) {\n",
            "        return store_h;\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("return store_h;"));
        assert!(!staged.contains("uint160"));
    }
}
