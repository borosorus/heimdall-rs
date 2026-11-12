//! Stage `wordify-address-mask`: make decompiled address-mask writes compile.
//!
//! Port of `prepare_candidate.wordify_address_mask_writes`: the decompiler
//! mirrors the EVM word ops verbatim, `X = A | MASK & S;` with an address
//! `A` and a `bytes32` state `S`; Solidity 0.8 refuses bitwise ops mixing
//! address/bytes32/int_const. The faithful rewrite performs the identical
//! word algebra over uint256 and converts to the left-hand side's declared
//! type:
//! `X = bytes32(uint256(uint160(A)) | (uint256(MASK) & uint256(S)));`
//! The `address(...)`-call form becomes
//! `address(uint160(uint256(uint160(A)) | (uint256(MASK) & uint256(S))))`.
//! Gates (proven shapes only): full 32-byte hex mask; `A` a bare identifier
//! declared `address` in the enclosing unit; assignment left-hand side a
//! `bytes32` state; the masked right-hand side a declared state. The two
//! statement forms are scanned in the Python order (all assignments, then
//! all expressions) with Python slice semantics at the splice.

use lazy_static::lazy_static;
use std::collections::HashMap;

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::mask,
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_ADDRESS_PARAM: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\baddress\s+([A-Za-z_]\w*)").expect("failed to build regex");
    static ref RE_STATE_WORD: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b(address|bytes32)\s+([A-Za-z_]\w*)\s*;").expect("failed to build regex");
    static ref RE_STMT: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?P<lhs>[A-Za-z_]\w*)\s*=\s*(?P<actor>[A-Za-z_]\w*)\s*\|\s*(?P<mask>0x[0-9a-fA-F]{64})\s*&\s*(?P<rhs>[A-Za-z_]\w*)\s*;",
    )
    .expect("failed to build regex");
    static ref RE_EXPR: fancy_regex::Regex = fancy_regex::Regex::new(
        r"address\((?P<actor>[A-Za-z_]\w*)\s*\|\s*(?P<mask>0x[0-9a-fA-F]{64})\s*&\s*(?P<rhs>[A-Za-z_]\w*)\)",
    )
    .expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    // Python wraps the parse in try/except and abstains on failure
    let Ok(parsed) = parse_contract(source, None) else {
        return Ok(Stage {
            name: "wordify-address-mask",
            description: "address-mask word writes",
            source: source.to_string(),
            edits: Vec::new(),
            findings: Vec::new(),
        });
    };

    let mut address_params: HashMap<String, Vec<(usize, usize)>> = HashMap::new();
    for unit in parsed.functions() {
        let header_masked =
            crate::prepare::parser::mask_strings_and_comments(&unit.header, 0, unit.header.len())?;
        for captures in RE_ADDRESS_PARAM.captures_iter(&header_masked).flatten() {
            if let Some(name) = captures.get(1) {
                address_params
                    .entry(name.as_str().to_string())
                    .or_default()
                    .push((unit.start, unit.end));
            }
        }
    }
    let unit_spans: Vec<(usize, usize)> =
        parsed.functions().map(|unit| (unit.start, unit.end)).collect();
    let in_unit = |offset: usize| unit_spans.iter().any(|(a, b)| *a <= offset && offset < *b);
    let mut state_types: HashMap<String, String> = HashMap::new();
    for captures in RE_STATE_WORD.captures_iter(&masked).flatten() {
        if let (Some(kind), Some(name)) = (captures.get(1), captures.get(2)) {
            if !in_unit(name.start()) {
                state_types.insert(name.as_str().to_string(), kind.as_str().to_string());
            }
        }
    }

    let mut edits: Vec<StageEdit> = Vec::new();
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;
    // Python order: every statement-form match, then every expression-form
    for captures in RE_STMT.captures_iter(&masked).chain(RE_EXPR.captures_iter(&masked)).flatten() {
        let whole = captures.get(0).expect("whole match");
        let actor = captures.name("actor").expect("actor").as_str();
        let mask_literal = captures.name("mask").expect("mask").as_str();
        let rhs = captures.name("rhs").expect("rhs").as_str();
        let lhs = captures.name("lhs").map(|m| m.as_str());
        let is_assign = lhs.is_some();
        if (is_assign
            && state_types.get(lhs.expect("checked")).map(String::as_str) != Some("bytes32"))
            || !state_types.contains_key(rhs)
        {
            continue;
        }
        let actor_ok = address_params
            .get(actor)
            .map(|spans| spans.iter().any(|(a, b)| *a <= whole.start() && whole.start() < *b))
            .unwrap_or(false);
        if !actor_ok {
            continue;
        }
        let replacement = if is_assign {
            format!(
                "{} = bytes32(uint256(uint160({})) | (uint256({}) & uint256({})));",
                lhs.expect("checked"),
                actor,
                mask_literal,
                rhs
            )
        } else {
            format!(
                "address(uint160(uint256(uint160({})) | (uint256({}) & uint256({}))))",
                actor, mask_literal, rhs
            )
        };
        let (start, end) = (whole.start(), whole.end());
        // matches keep the Python order (all assignments, then all expression
        // forms), so a later match may start before `last`; Python's
        // `source[last:start]` is the empty string there - skip alike
        if start > last {
            pieces.push(source[last..start].to_string());
        }
        pieces.push(replacement);
        last = end;
        let shown = lhs.unwrap_or("<expr>");
        edits.push(StageEdit {
            kind: "address-mask-wordified".to_string(),
            detail: format!("{shown} = {actor} | mask & {rhs} -> word algebra"),
            evidence: "address/bytes32 bitwise idiom; identical EVM word ops, 0.8-legal typing"
                .to_string(),
        });
    }

    if pieces.is_empty() {
        return Ok(Stage {
            name: "wordify-address-mask",
            description: "address-mask word writes",
            source: source.to_string(),
            edits,
            findings: Vec::new(),
        });
    }
    pieces.push(source[last.min(source.len())..].to_string());
    Ok(Stage {
        name: "wordify-address-mask",
        description: "address-mask word writes",
        source: pieces.concat(),
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn assignment_form_is_wordified() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    bytes32 store_a; // storage slot: 0x00\n",
            "    function f(address var_a) public {\n",
            "        store_a = var_a | 0x000000000000000000000000000000000000000000000000000000000000ff00 & store_a;\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains(
            "store_a = bytes32(uint256(uint160(var_a)) | (uint256(0x000000000000000000000000000000000000000000000000000000000000ff00) & uint256(store_a)));"
        ));
    }

    #[test]
    fn expression_form_is_wordified() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    bytes32 store_a; // storage slot: 0x00\n",
            "    function f(address var_a) public view returns (address) {\n",
            "        return address(var_a | 0x000000000000000000000000000000000000000000000000000000000000ff00 & store_a);\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains(
            "address(uint160(uint256(uint160(var_a)) | (uint256(0x000000000000000000000000000000000000000000000000000000000000ff00) & uint256(store_a))))"
        ));
    }
}
