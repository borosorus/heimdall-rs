//! Stage `widen-packed-pair-returns`: widen under-declared packed tuple returns.
//!
//! Port of `prepare_candidate.widen_packed_pair_returns`: the decompiler
//! renders multi-value returns as `return abi.encodePacked(a, b);` while
//! declaring a single non-tuple return type (observed on the lighthouse peek
//! family). When EVERY return statement of a view unit is a two-argument
//! packed pair, the faithful signature is two words -
//! `returns (uint256, uint256)` with `return (uint256(a), uint256(b));` -
//! byte-identical returndata, 0.8-legal typing. Bool-valued terms cast via
//! the conditional (solc refuses `uint256(bool)`); mixed bare/packed units,
//! already-tuple headers and `bytes memory`/`string memory` singles abstain
//! (a dynamic single already encodes the packed tail as ONE value).

use lazy_static::lazy_static;

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::mask,
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_PAIR: fancy_regex::Regex =
        fancy_regex::Regex::new(r"return\s+abi\.encodePacked\([^;]*\);")
            .expect("failed to build regex");
    static ref RE_BARE_RETURN: fancy_regex::Regex =
        fancy_regex::Regex::new(r"return\s+(?!abi\.encodePacked)").expect("failed to build regex");
    static ref RE_RETURNS_CLAUSE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"returns\s*\(([^)]*)\)").expect("failed to build regex");
    static ref RE_TUPLE_HEADER: fancy_regex::Regex =
        fancy_regex::Regex::new(r"returns\s*\([^)]*,[^)]*\)").expect("failed to build regex");
    static ref RE_DYNAMIC_SINGLE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bbytes\d*\s+memory|\bstring\s+memory")
            .expect("failed to build regex");
    static ref RE_VIEW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bview\b").expect("failed to build regex");
    static ref RE_BOOL_TERM: fancy_regex::Regex =
        fancy_regex::Regex::new(r"==|!=|<=|>=|<|>|\btrue\b|\bfalse\b|^\s*!",)
            .expect("failed to build regex");
    static ref RE_RETURNS_SPAN: fancy_regex::Regex =
        fancy_regex::Regex::new(r"returns\s*\([^)]*\)").expect("failed to build regex");
}

/// Python `_word`: bool-valued terms cast via the conditional, others directly.
fn word(term: &str) -> String {
    if RE_BOOL_TERM.is_match(term).unwrap_or(false) {
        format!("({term} ? uint256(1) : uint256(0))")
    } else {
        format!("uint256({term})")
    }
}

/// `re.sub(pattern, literal_replacement, text)` via find-and-splice.
fn sub_literal(haystack: &str, regex: &fancy_regex::Regex, replacement: &str) -> String {
    let mut out = String::new();
    let mut last = 0usize;
    for m in regex.find_iter(haystack).flatten() {
        out.push_str(&haystack[last..m.start()]);
        out.push_str(replacement);
        last = m.end();
    }
    if out.is_empty() {
        return haystack.to_string();
    }
    out.push_str(&haystack[last..]);
    out
}

/// The two comma-separated arguments of one packed return, per the Python
/// depth scan over the RAW text (strings/comments are not skipped there).
fn pair_args(inner: &str) -> Option<(String, String)> {
    let open_paren = inner.find('(')?;
    let bytes = inner.as_bytes();
    let mut depth = 1usize;
    let mut idx = open_paren + 1;
    let mut start_arg = open_paren + 1;
    let mut args: Vec<String> = Vec::new();
    while idx < bytes.len() && depth > 0 {
        match bytes[idx] {
            b'(' => depth += 1,
            b')' => {
                depth -= 1;
                if depth == 0 {
                    args.push(inner[start_arg..idx].to_string());
                    break;
                }
            }
            b',' if depth == 1 => {
                args.push(inner[start_arg..idx].to_string());
                start_arg = idx + 1;
            }
            _ => {}
        }
        idx += 1;
    }
    if depth != 0 || args.len() != 2 {
        return None;
    }
    Some((args[0].trim().to_string(), args[1].trim().to_string()))
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    // Python wraps the parse in try/except and abstains on failure
    let Ok(parsed) = parse_contract(source, None) else {
        return Ok(Stage {
            name: "widen-packed-pair-returns",
            description: "packed pair return widening",
            source: source.to_string(),
            edits: Vec::new(),
            findings: Vec::new(),
        });
    };

    let mut rewrites: Vec<(usize, usize, String)> = Vec::new();
    let mut edits: Vec<StageEdit> = Vec::new();
    for unit in parsed.functions() {
        let header_masked =
            crate::prepare::parser::mask_strings_and_comments(&unit.header, 0, unit.header.len())?;
        if !RE_VIEW.is_match(&header_masked).unwrap_or(false) {
            continue;
        }
        let mut pairs: Vec<(String, String, String)> = Vec::new();
        for m in RE_PAIR.find_iter(&unit.text).flatten() {
            let inner = &unit.text[m.start()..m.end()];
            let Some((a, b)) = pair_args(inner) else {
                continue;
            };
            pairs.push((m.as_str().to_string(), a, b));
        }
        if pairs.is_empty() {
            continue;
        }
        let body_masked = mask(&unit.text)?;
        let bare_returns = RE_BARE_RETURN.find_iter(&body_masked).flatten().count();
        if bare_returns > 0 {
            continue; // mixed shapes abstain
        }
        if header_masked.contains("returns (")
            && RE_TUPLE_HEADER.is_match(&header_masked).unwrap_or(false)
        {
            continue; // already a tuple
        }
        let single = RE_RETURNS_CLAUSE
            .captures(&header_masked)
            .unwrap_or(None)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().to_string());
        // a bytes/string return already encodes the packed tail as ONE dynamic
        // value; widening would change the externally visible returndata
        if let Some(single) = &single {
            if RE_DYNAMIC_SINGLE.is_match(single).unwrap_or(false) {
                continue;
            }
        }
        if single.is_none() {
            continue;
        }
        let new_header = sub_literal(&unit.header, &RE_RETURNS_SPAN, "returns (uint256, uint256)");
        let mut new_body = unit.text.clone();
        let mut n_packed = 0usize;
        for (whole, a, b) in &pairs {
            new_body =
                new_body.replace(whole.as_str(), &format!("return ({}, {});", word(a), word(b)));
            n_packed += 1;
        }
        let header_len = unit.header.len().min(unit.text.len());
        rewrites.push((unit.start, unit.end, format!("{}{}", new_header, &new_body[header_len..])));
        edits.push(StageEdit {
            kind: "packed-pair-widened".to_string(),
            detail: format!(
                "{}: returns widened to (uint256, uint256) ({} sites)",
                unit.name, n_packed
            ),
            evidence: "every return is a two-argument abi.encodePacked; word-faithful tuple"
                .to_string(),
        });
    }

    if rewrites.is_empty() {
        return Ok(Stage {
            name: "widen-packed-pair-returns",
            description: "packed pair return widening",
            source: source.to_string(),
            edits,
            findings: Vec::new(),
        });
    }
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;
    for (start, end, replacement) in &rewrites {
        pieces.push(source[last..*start].to_string());
        pieces.push(replacement.clone());
        last = *end;
    }
    pieces.push(source[last..].to_string());
    Ok(Stage {
        name: "widen-packed-pair-returns",
        description: "packed pair return widening",
        source: pieces.concat(),
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn packed_pair_return_is_widened() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    uint256 store_e; // storage slot: 0x03\n",
            "    function f() public view returns (bool) {\n",
            "        return abi.encodePacked(store_e, 0x1);\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("returns (uint256, uint256)"));
        // the full ladder runs typed-packed-literals first: the bare 0x1 is
        // already uint256(..) when widen sees it (Python-verified final)
        assert!(staged.contains("return (uint256(store_e), uint256(uint256(0x1)));"));
    }

    #[test]
    fn bool_valued_term_uses_the_conditional() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    uint256 store_e; // storage slot: 0x03\n",
            "    function f() public view returns (bool) {\n",
            "        return abi.encodePacked(store_e, store_e == 0x1);\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged
            .contains("return (uint256(store_e), (store_e == 0x1 ? uint256(1) : uint256(0)));"));
    }

    #[test]
    fn mixed_bare_and_packed_returns_abstain() {
        let source = concat!(
            "contract C {\n",
            "    uint256 store_e; // storage slot: 0x03\n",
            "    function f() public view returns (bool) {\n",
            "        if (store_e == 0x1) { return true; }\n",
            "        return abi.encodePacked(store_e, 0x1);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        // typed-packed-literals fires first; the mixed-shape unit then abstains
        assert!(staged.contains("return abi.encodePacked(store_e, uint256(0x1));"));
        assert!(!staged.contains("returns (uint256, uint256)"));
    }
}
