//! Stage `arity`: reconcile declared parameter counts with calldata guards.
//!
//! Port of `prepare_candidate.align_arities` with `_prune_param_docs` and
//! `_replace_params`: the function's own `msg.data.length` head guard proves
//! the calldata word count; excess unreferenced parameters are trimmed (with
//! their `@param` doc lines) and missing ones appended as `uint256` placeholders.
//! The `@custom:signature` provenance comment is re-synced in the same edit.

use alloy::primitives::U256;
use lazy_static::lazy_static;

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::{header_params, mask},
    Stage, StageEdit, StageFinding,
};

lazy_static! {
    static ref RE_FUNCTION_OPEN: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bfunction\s+[A-Za-z_]\w*\s*\(").expect("failed to build regex");
    static ref RE_FUNCTION_NAME: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bfunction\s+([A-Za-z_]\w*)").expect("failed to build regex");
    static ref RE_REQUIRE_GUARD: fancy_regex::Regex =
        fancy_regex::Regex::new(r"require\([^;]*msg\.data\.length[^;]*\)")
            .expect("failed to build regex");
    static ref RE_GUARD_CONSTANT: fancy_regex::Regex =
        fancy_regex::Regex::new(r">=\s*(0x[0-9a-fA-F]+|\d+)").expect("failed to build regex");
    static ref RE_VALUE_TYPE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^(uint\d+|int\d+|address|bool|bytes\d+)$")
            .expect("failed to build regex");
    static ref RE_ARG_INDEX: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^arg(\d+)$").expect("failed to build regex");
    static ref RE_SIGNATURE_COMMENT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"(?m)^(\s*///\s*@custom:signature\s+)([^\n]*)$")
            .expect("failed to build regex");
}

/// Calldata head size in words from the function's own msg.data guards.
///
/// Every `require(...)` mentioning `msg.data.length` contributes its
/// `>= <constant>` bounds; the largest constant divisible by 32 wins, in
/// words. `None` when no such guard exists. Mirrors
/// `prepare_candidate.head_guard_words`.
pub(crate) fn head_guard_words(masked_body: &str) -> Option<usize> {
    let mut words: Vec<usize> = Vec::new();
    for require in RE_REQUIRE_GUARD.find_iter(masked_body).flatten() {
        for capture in RE_GUARD_CONSTANT.captures_iter(require.as_str()).flatten() {
            let raw = match capture.get(1) {
                Some(m) => m.as_str(),
                None => continue,
            };
            // Python ints are unbounded; guard bounds are full-word values
            let value = match if let Some(hex) = raw.strip_prefix("0x") {
                U256::from_str_radix(hex, 16).ok()
            } else {
                U256::from_str_radix(raw, 10).ok()
            } {
                Some(value) => value,
                None => continue,
            };
            if value % U256::from(32u8) == U256::ZERO {
                if let Ok(words_count) =
                    usize::try_from(u128::try_from(value / U256::from(32u8)).unwrap_or(u128::MAX))
                {
                    words.push(words_count);
                }
            }
        }
    }
    words.into_iter().max()
}

/// Drops `/// @param <name>` lines from the unit's own doc block.
///
/// Mirrors `prepare_candidate._prune_param_docs` (solc error 3881: natspec
/// must not document parameters the signature no longer has).
fn prune_param_docs(unit_text: &str, dropped: &[String]) -> String {
    if dropped.is_empty() {
        return unit_text.to_string();
    }
    let patterns: Vec<fancy_regex::Regex> = dropped
        .iter()
        .map(|name| {
            fancy_regex::Regex::new(&format!("^///\\s*@param\\s+{}\\b", fancy_regex::escape(name)))
                .expect("failed to build regex")
        })
        .collect();
    let mut kept = Vec::new();
    for line in unit_text.split_inclusive('\n') {
        let stripped = line.trim();
        let matched = stripped.starts_with("///") &&
            patterns.iter().any(|re| re.is_match(stripped).unwrap_or(false));
        if !matched {
            kept.push(line.to_string());
        }
    }
    kept.concat()
}

/// Returns `unit_text` with the header's parameter list replaced.
///
/// The `@custom:signature` provenance comment is synced in the same edit: its
/// parameter list is refreshed while its own suffix (visibility/mutability/
/// returns as the comment stated them) is kept. Mirrors
/// `prepare_candidate._replace_params`.
fn replace_params(unit_text: &str, params: &[(String, String)]) -> Result<String, ParseError> {
    let masked = mask(unit_text)?;
    let open = match RE_FUNCTION_OPEN.captures(&masked).ok().flatten().map(|c| c.get(0)) {
        Some(Some(m)) => m.end(),
        _ => {
            return Err(ParseError(format!(
                "cannot locate parameter list in: {:?}",
                truncate80(unit_text)
            )))
        }
    };
    let bytes = masked.as_bytes();
    let mut depth = 1usize;
    let mut index = open;
    while index < bytes.len() && depth > 0 {
        match bytes[index] {
            b'(' => depth += 1,
            b')' => depth -= 1,
            _ => {}
        }
        index += 1;
    }
    if depth != 0 {
        return Err(ParseError(format!(
            "unbalanced parameter list in: {:?}",
            truncate80(unit_text)
        )));
    }
    let rendered: Vec<String> = params
        .iter()
        .map(
            |(type_text, name)| {
                if name.is_empty() {
                    type_text.clone()
                } else {
                    format!("{type_text} {name}")
                }
            },
        )
        .collect();
    let rendered = rendered.join(", ");
    let mut replaced = format!("{}{}{}", &unit_text[..open], rendered, &unit_text[index - 1..]);
    if let Some(captures) = RE_SIGNATURE_COMMENT.captures(&replaced).ok().flatten() {
        let comment = match captures.get(2) {
            Some(comment) => comment,
            // the group always participates when the regex matches
            None => return Ok(replaced),
        };
        let old_content = comment.as_str();
        let name = RE_FUNCTION_NAME
            .captures(&masked)
            .ok()
            .flatten()
            .and_then(|c| c.get(1).map(|m| m.as_str().to_string()))
            .unwrap_or_default();
        // keep the comment's own suffix; only its parameter list is refreshed
        let suffix = match old_content.find(')') {
            Some(close) => old_content[close + 1..].to_string(),
            None => String::new(),
        };
        let renamed = format!("{name}({rendered}){suffix}");
        replaced =
            format!("{}{}{}", &replaced[..comment.start()], renamed, &replaced[comment.end()..]);
    }
    Ok(replaced)
}

fn truncate80(text: &str) -> String {
    text.chars().take(80).collect()
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let parsed = parse_contract(source, None)?;
    let mut edits: Vec<StageEdit> = Vec::new();
    let mut findings: Vec<StageFinding> = Vec::new();
    // (start, end, replacement); units are disjoint, so descending start order
    // keeps every pending span valid even when the length changes
    let mut replacements: Vec<(usize, usize, String)> = Vec::new();

    for unit in parsed.functions() {
        let masked_unit = mask(&unit.text)?;
        let unit_masked_header = mask(&unit.header)?;
        let params = header_params(&unit_masked_header);
        let named = params.iter().filter(|(_, name)| !name.is_empty()).count();
        if named != params.len() {
            findings.push(StageFinding {
                kind: "arity".to_string(),
                detail: unit.name.clone(),
                reason: "a parameter has no name; left unchanged".to_string(),
            });
            continue;
        }
        let declared = params.len();
        if !params.iter().all(|(type_text, _)| RE_VALUE_TYPE.is_match(type_text).unwrap_or(false)) {
            findings.push(StageFinding {
                kind: "arity".to_string(),
                detail: unit.name.clone(),
                reason: "dynamic or composite parameter types; calldata-head arity \
                         alignment unsupported"
                    .to_string(),
            });
            continue;
        }
        let guard = match head_guard_words(&masked_unit) {
            Some(guard) if guard != declared => guard,
            _ => continue,
        };
        let body_open = match unit.text.find('{') {
            Some(open) => open,
            None => continue,
        };
        let body_masked = &masked_unit[body_open.min(masked_unit.len())..];
        if guard < declared {
            let excess = &params[guard..];
            let referenced: Vec<&String> = excess
                .iter()
                .filter(|(_, name)| {
                    fancy_regex::Regex::new(&format!(r"\b{}\b", fancy_regex::escape(name)))
                        .expect("failed to build regex")
                        .is_match(body_masked)
                        .unwrap_or(false)
                })
                .map(|(_, name)| name)
                .collect();
            if !referenced.is_empty() {
                let names: Vec<String> = referenced.into_iter().cloned().collect();
                findings.push(StageFinding {
                    kind: "arity-trim".to_string(),
                    detail: unit.name.clone(),
                    reason: format!(
                        "guard proves {guard} head word(s) but referenced parameter(s) {} \
                         would be dropped; left for unit repair",
                        names.join(", ")
                    ),
                });
                continue;
            }
            let dropped: Vec<String> = excess.iter().map(|(_, name)| name.clone()).collect();
            let kept: Vec<(String, String)> = params[..guard].to_vec();
            let new_text = prune_param_docs(&replace_params(&unit.text, &kept)?, &dropped);
            replacements.push((unit.start, unit.end, new_text));
            edits.push(StageEdit {
                kind: "arity-trim".to_string(),
                detail: format!("{}: {declared} -> {guard} parameter(s)", unit.name),
                evidence: "calldata-head guard; removed parameters unreferenced in body; \
                           pruned matching @param docs"
                    .to_string(),
            });
        } else {
            let mut next_index = 0usize;
            for (_, name) in &params {
                if let Some(captures) = RE_ARG_INDEX.captures(name).ok().flatten() {
                    if let Some(digits) = captures.get(1) {
                        if let Ok(value) = digits.as_str().parse::<usize>() {
                            next_index = next_index.max(value + 1);
                        }
                    }
                }
            }
            let mut extended = params.clone();
            for offset in 0..guard - declared {
                extended.push(("uint256".to_string(), format!("arg{}", next_index + offset)));
            }
            let new_text = replace_params(&unit.text, &extended)?;
            replacements.push((unit.start, unit.end, new_text));
            edits.push(StageEdit {
                kind: "arity-extend".to_string(),
                detail: format!("{}: {declared} -> {guard} parameter(s)", unit.name),
                evidence: "calldata-head guard proves additional head word(s); uint256 assumed"
                    .to_string(),
            });
        }
    }

    let mut staged = source.to_string();
    replacements.sort_by(|a, b| b.0.cmp(&a.0));
    for (start, end, text) in replacements {
        staged = format!("{}{}{}", &staged[..start], text, &staged[end..]);
    }

    Ok(Stage {
        name: "arity",
        description: "calldata-head arity alignment",
        source: staged,
        edits,
        findings,
    })
}

#[cfg(test)]
mod tests {
    use super::head_guard_words;

    #[test]
    fn head_guard_words_parses_word_count() {
        let body = "require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);";
        assert_eq!(head_guard_words(body), Some(3));
        assert_eq!(head_guard_words("require(true);"), None);
        assert_eq!(head_guard_words("require(msg.data.length >= 0x21);"), None);
    }

    #[test]
    fn extends_arity_when_guard_proves_more_params() {
        let source = concat!(
            "contract C {\n",
            "    function Unresolved_23b872dd(uint256 arg0) public payable {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);\n",
            "        storage_map[arg0][msg.sender] = 1;\n",
            "    }\n",
            "}\n",
        );
        let stage = super::run(source).unwrap();
        assert!(stage.source.contains(
            "function Unresolved_23b872dd(uint256 arg0, uint256 arg1, uint256 arg2) public payable"
        ));
        assert_eq!(stage.edits[0].kind, "arity-extend");
    }

    #[test]
    fn trims_unused_params_when_guard_proves_fewer() {
        let source = concat!(
            "contract C {\n",
            "    function Unresolved_c47f0027(uint256 arg0, uint256 arg1) public payable {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n",
            "        store[arg0] = 1;\n",
            "    }\n",
            "}\n",
        );
        let stage = super::run(source).unwrap();
        assert!(stage.source.contains("function Unresolved_c47f0027(uint256 arg0) public payable"));
        assert_eq!(stage.edits[0].kind, "arity-trim");
    }

    #[test]
    fn abstains_when_excess_param_is_referenced() {
        let source = concat!(
            "contract C {\n",
            "    function f(uint256 arg0, uint256 arg1) public view {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n",
            "        g(arg1);\n",
            "    }\n",
            "    function g(uint256 a) internal {}\n",
            "}\n",
        );
        let stage = super::run(source).unwrap();
        assert!(stage.source.contains("function f(uint256 arg0, uint256 arg1)"));
        assert!(stage.findings.iter().any(|f| f.kind == "arity-trim"));
    }

    #[test]
    fn functions_without_guards_are_untouched() {
        let source = "contract C { function f(uint256 a) public pure { revert(); } }\n";
        let stage = super::run(source).unwrap();
        assert_eq!(stage.source, source);
        assert!(stage.edits.is_empty());
    }

    #[test]
    fn arity_extend_syncs_signature_comment() {
        let source = concat!(
            "contract C {\n",
            "    /// @custom:selector    0x23b872dd\n",
            "    /// @custom:signature   Unresolved_23b872dd(address arg0) public pure\n",
            "    /// @param              arg0 [\"address\", \"uint160\"]\n",
            "    function Unresolved_23b872dd(address arg0) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);\n",
            "    }\n",
            "}\n",
        );
        let stage = super::run(source).unwrap();
        assert!(stage.source.contains(
            "function Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public pure {"
        ));
        // provenance must name the same canonical signature as the declaration
        assert!(stage.source.contains(
            "/// @custom:signature   Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public pure"
        ));
        assert!(!stage
            .source
            .contains("/// @custom:signature   Unresolved_23b872dd(address arg0) public pure"));
    }

    #[test]
    fn arity_trim_syncs_signature_comment() {
        let source = concat!(
            "contract C {\n",
            "    /// @custom:signature   f(uint256 arg0, uint256 arg1) public pure\n",
            "    function f(uint256 arg0, uint256 arg1) public pure returns (uint256) {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n",
            "        return arg0;\n",
            "    }\n",
            "}\n",
        );
        let stage = super::run(source).unwrap();
        assert!(stage.source.contains("function f(uint256 arg0) public pure returns (uint256) {"));
        assert!(stage.source.contains("/// @custom:signature   f(uint256 arg0) public pure"));
    }

    #[test]
    fn arity_alignment_abstains_on_dynamic_params() {
        let source = concat!(
            "contract D {\n",
            "    function f(bytes calldata b) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);\n",
            "        require(b.length > 0);\n",
            "    }\n",
            "}\n",
        );
        let stage = super::run(source).unwrap();
        assert!(stage.source.contains("function f(bytes calldata b)"));
        assert!(stage.findings.iter().any(|f| f.reason.contains("dynamic or composite")));
    }
}
