//! Stage `truthiness`: rewrite truthiness guards into explicit compares.
//!
//! Port of `prepare_candidate.relax_truthiness_requires`: the decompiler
//! renders `x != 0`-style guards as `require(x, ...)`/`if (x)`, but Solidity
//! has no implicit address/uint-to-bool conversion. Only unambiguous shapes
//! are rewritten: `msg.sender` against `address(0)`, declared uint locals
//! against `0`, and address/uint-typed parameters; everything else abstains.

use lazy_static::lazy_static;
use std::collections::BTreeSet;

use crate::prepare::{
    parser::{mask_strings_and_comments, parse_contract, ParseError, ParsedSource},
    stages::helpers::{header_params, mask, RE_IDENTIFIER, RE_VAR_NAME},
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_UINT_LOCAL: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\buint\d*\s+(var_[a-z]+)\b").expect("failed to build regex");
    static ref RE_UINT_KIND: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^u?int\d*$").expect("failed to build regex");
    static ref RE_GUARD: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?P<kw>\brequire\b|\bif\b)\s*\(\s*(?P<expr>[A-Za-z_][\w.]*|0x[0-9a-fA-F]+|\d+)\s*(?P<comma>,|\))",
    )
    .expect("failed to build regex");
    /// the guard-constant class of this stage (`0x..` / decimal), narrower
    /// than the shared literal class
    static ref RE_GUARD_LITERAL: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^(?:0x[0-9a-fA-F]+|\d+)$").expect("failed to build regex");
}

/// `(address|uint)`-ness of `name` in the function enclosing `offset`.
///
/// Port of the Python `param_kind` closure: every parameter of the first
/// enclosing function is inspected; a non-matching or kindless enclosing
/// unit yields `None`.
fn param_kind(parsed: &ParsedSource, offset: usize, name: &str) -> Option<&'static str> {
    for unit in parsed.functions() {
        if unit.start <= offset && offset < unit.end {
            let header_masked =
                mask_strings_and_comments(&unit.header, 0, unit.header.len()).unwrap_or_default();
            for (type_text, param) in header_params(&header_masked) {
                if param == name {
                    if type_text.starts_with("address") {
                        return Some("address");
                    }
                    if RE_UINT_KIND.is_match(&type_text).unwrap_or(false) {
                        return Some("uint");
                    }
                }
            }
            return None;
        }
    }
    None
}

/// Python `int(text, 0)` for the guard-constant shapes (`0x..` / decimal).
fn parse_int0(text: &str) -> Option<u64> {
    if let Some(hex) = text.strip_prefix("0x") {
        u64::from_str_radix(hex, 16).ok()
    } else {
        text.parse::<u64>().ok()
    }
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    let declared_uint: BTreeSet<String> = RE_UINT_LOCAL
        .captures_iter(&masked)
        .flatten()
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .collect();
    let parsed = parse_contract(source, None)?;

    let mut edits: Vec<StageEdit> = Vec::new();
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;

    // one combined pass over both truthiness shapes (require(...expr..., and
    // if(...expr...)): separate passes would emit overlapping replacements
    for captures in RE_GUARD.captures_iter(&masked).flatten() {
        let whole = match captures.get(0) {
            Some(m) => (m.start(), m.end()),
            None => continue,
        };
        let keyword = match captures.name("kw") {
            Some(m) => m.as_str().to_string(),
            None => continue,
        };
        let expr = match captures.name("expr") {
            Some(m) => m.as_str().to_string(),
            None => continue,
        };
        let comma = matches!(captures.name("comma"), Some(m) if m.as_str() == ",");
        let comparison = if RE_GUARD_LITERAL.is_match(&expr).unwrap_or(false) && keyword == "if" {
            // nonzero int constants 0/1 fold to false/true; larger constants
            // stay visible rather than being folded
            match parse_int0(&expr) {
                Some(0) => "false".to_string(),
                Some(1) => "true".to_string(),
                _ => continue,
            }
        } else if expr == "msg.sender" {
            "msg.sender != address(0)".to_string()
        } else if RE_VAR_NAME.is_match(&expr).unwrap_or(false) && declared_uint.contains(&expr) {
            format!("{expr} != 0")
        } else if RE_IDENTIFIER.is_match(&expr).unwrap_or(false) {
            match param_kind(&parsed, whole.0, &expr) {
                Some("address") => format!("{expr} != address(0)"),
                Some("uint") => format!("{expr} != 0"),
                _ => continue,
            }
        } else {
            continue;
        };
        let tail = if comma { "," } else { ")" };
        let replacement = format!("{keyword}({comparison}{tail}");
        pieces.push(source[last..whole.0].to_string());
        pieces.push(replacement);
        last = whole.1;
        edits.push(StageEdit {
            kind: "truthiness-guard".to_string(),
            detail: format!("{keyword}({expr}...) -> {keyword}({comparison}...)"),
            evidence: "truthiness condition without implicit bool conversion".to_string(),
        });
    }

    let staged = if pieces.is_empty() {
        source.to_string()
    } else {
        pieces.push(source[last..].to_string());
        pieces.concat()
    };
    Ok(Stage {
        name: "truthiness",
        description: "truthiness require guards",
        source: staged,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn truthiness_require_on_msg_sender_is_rewritten() {
        let source = concat!(
            "contract C {\n",
            "    error E();\n",
            "    function f() public view {\n",
            "        require(msg.sender, E());\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("require(msg.sender != address(0), E());"));
    }

    #[test]
    fn truthiness_require_abstains_on_unknown_expr() {
        let source = concat!(
            "contract C {\n",
            "    error E();\n",
            "    function f(string memory s) public pure {\n",
            "        require(s, E());\n",
            "        return;\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("require(s, E());"));
    }

    #[test]
    fn truthiness_require_on_address_param_is_rewritten() {
        let source = concat!(
            "contract C {\n",
            "    error E();\n",
            "    function f(address arg0) public pure {\n",
            "        require(arg0, E());\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("require(arg0 != address(0), E());"));
    }

    #[test]
    fn truthiness_checks_every_parameter_not_only_the_first() {
        // regression: the port must inspect all parameters of the enclosing
        // function, as the Python closure does
        let source = concat!(
            "contract C {\n",
            "    error E();\n",
            "    function f(uint256 arg0, address arg1) public pure {\n",
            "        require(arg1, E());\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("require(arg1 != address(0), E());"));
    }
}
