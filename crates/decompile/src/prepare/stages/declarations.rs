//! Stage `declarations`: declare/reconcile error and event declarations.
//!
//! Port of `prepare_candidate.declare_missing_symbols` and its private
//! helpers. Two independent passes on fresh coordinates: first retype
//! declared symbols whose usage arity disagrees, then insert declarations for
//! symbols referenced but never declared. The declaration-inner slicing
//! mirrors the Python arithmetic (`text[idx('('):rindex(')')][1:-1]`)
//! including its off-by-one slack, which only ever widens the retype check.

use lazy_static::lazy_static;
use std::collections::BTreeSet;

use crate::prepare::{
    parser::{is_space, mask_strings_and_comments, parse_contract, ParseError, ParsedSource},
    stages::helpers::{
        body_open_line_end, header_params, mask, split_top_level, state_declaration_match,
        RE_IDENTIFIER, RE_LITERAL, RE_VAR_NAME,
    },
    Stage, StageEdit, StageFinding,
};

lazy_static! {
    static ref RE_ERROR_DECL_LINE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"(?m)^\s*error\s+\w+\([^;]*;\s*$").expect("failed to build regex");
    static ref RE_EVENT_DECL_LINE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"(?m)^\s*event\s+\w+\([^;]*;\s*$").expect("failed to build regex");
    static ref RE_DECLARED_ERROR: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\berror\s+([A-Za-z_]\w*)\s*\(").expect("failed to build regex");
    static ref RE_DECLARED_EVENT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bevent\s+([A-Za-z_]\w*)\s*\(").expect("failed to build regex");
    static ref RE_USED_ERROR: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b(CustomError_[0-9a-fA-F]{8})\s*\(")
            .expect("failed to build regex");
    static ref RE_USED_EVENT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b(Event_[0-9a-fA-F]{8})\s*\(").expect("failed to build regex");
    static ref RE_EVENT_NAME: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bevent\s+([A-Za-z_]\w*)\b").expect("failed to build regex");
    static ref RE_ERROR_NAME: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\berror\s+([A-Za-z_]\w*)\b").expect("failed to build regex");
}

/// Argument count at call/emit sites of `name`; `None` if none or ambiguous.
///
/// Mirrors `prepare_candidate._call_arity`; `skip` excludes one span (e.g.
/// the declaration itself) from the scan.
fn call_arity(masked: &str, name: &str, skip: Option<(usize, usize)>) -> Option<usize> {
    let pattern =
        fancy_regex::Regex::new(&format!(r"\b{name}\s*\(")).expect("failed to build regex");
    let mut arities = BTreeSet::new();
    let bytes = masked.as_bytes();
    for m in pattern.find_iter(masked).flatten() {
        if let Some((skip_start, skip_end)) = skip {
            if m.start() >= skip_start && m.end() <= skip_end {
                continue;
            }
        }
        let mut depth = 1usize;
        let mut index = m.end();
        let mut commas = 0usize;
        let mut seen_token = false;
        while index < bytes.len() && depth > 0 {
            match bytes[index] {
                b'(' => depth += 1,
                b')' => depth -= 1,
                b',' if depth == 1 => {
                    commas += 1;
                    seen_token = true;
                }
                b if !is_space(b) => seen_token = true,
                _ => {}
            }
            index += 1;
        }
        if depth != 0 {
            return None;
        }
        arities.insert(if seen_token { commas + 1 } else { 0 });
    }
    if arities.len() != 1 {
        return None;
    }
    arities.into_iter().next()
}

/// Offset past the end of the last mask-confirmed `pattern` line match.
///
/// Mirrors `prepare_candidate._insertion_offset`.
fn insertion_offset(
    source: &str,
    masked: &str,
    pattern: &fancy_regex::Regex,
    fallback: usize,
) -> usize {
    let mut offset = fallback;
    for m in pattern.find_iter(masked).flatten() {
        offset = match source[m.start()..].find('\n') {
            Some(rel) => m.start() + rel + 1,
            None => source.len(),
        };
    }
    offset
}

/// Source-derived type of a call argument.
///
/// Mirrors `prepare_candidate._infer_type`: a literal, `msg.sender`/
/// `msg.value`, or a bare name declared as a parameter of the enclosing unit
/// or as contract state; every other expression defaults to `uint256`. The
/// Python signature carries `source`/`masked` unused; they are kept
/// underscored for port fidelity.
fn infer_type(
    expression: &str,
    parsed: &ParsedSource,
    _source: &str,
    _masked: &str,
    site_offset: usize,
) -> String {
    if expression == "msg.sender" {
        return "address".to_string();
    }
    if expression == "msg.value" {
        return "uint256".to_string();
    }
    if RE_LITERAL.is_match(expression).unwrap_or(false) {
        return "uint256".to_string();
    }
    if expression == "true" || expression == "false" {
        return "bool".to_string();
    }
    if RE_IDENTIFIER.is_match(expression).unwrap_or(false) {
        for unit in parsed.functions() {
            if unit.start <= site_offset && site_offset < unit.end {
                let unit_masked = mask_strings_and_comments(&unit.header, 0, unit.header.len())
                    .unwrap_or_default();
                for (type_text, name) in header_params(&unit_masked) {
                    if name == expression {
                        return type_text;
                    }
                }
                break;
            }
        }
        for unit in parsed.declarations() {
            if let Some((ty, name)) = state_declaration_match(&unit.header) {
                if name == expression {
                    return ty;
                }
            }
        }
        if RE_VAR_NAME.is_match(expression).unwrap_or(false) {
            return "uint256".to_string();
        }
    }
    "uint256".to_string()
}

/// Retype a declared symbol whose usage arity disagrees, when provable.
///
/// Mirrors `prepare_candidate._reconcile_declaration`.
#[allow(clippy::too_many_arguments)]
fn reconcile_declaration(
    source: &str,
    masked: &str,
    parsed: &ParsedSource,
    name: &str,
    kind: &str,
    edits: &mut Vec<StageEdit>,
    findings: &mut Vec<StageFinding>,
) -> Result<String, ParseError> {
    let declaration = fancy_regex::Regex::new(&format!(r"\b{kind}\s+{name}\s*\([^;]*;"))
        .expect("failed to build regex");
    let whole = match declaration.captures(masked).ok().flatten().and_then(|c| c.get(0)) {
        Some(whole) => (whole.start(), whole.end()),
        None => return Ok(source.to_string()),
    };
    let text = &masked[whole.0..whole.1];
    // Python would raise on a missing `)` here; treat as no declaration.
    let open = match text.find('(') {
        Some(open) => open,
        None => return Ok(source.to_string()),
    };
    let close = match text.rfind(')') {
        Some(close) => close,
        None => return Ok(source.to_string()),
    };
    // declaration inner, mirroring the Python
    // `text[idx('('):rindex(')')][1:-1]` arithmetic including its slack
    let inner = if close > open { &text[open..close] } else { "" };
    let inner = if inner.len() >= 2 { &inner[1..inner.len() - 1] } else { "" };
    let inner = inner.trim();
    let declared = if inner.is_empty() {
        0
    } else {
        inner.split(',').filter(|p| !p.trim().is_empty()).count()
    };
    let use_arity = call_arity(masked, name, Some(whole));
    match use_arity {
        None => return Ok(source.to_string()),
        Some(arity) if arity == declared => return Ok(source.to_string()),
        _ => {}
    }
    let use_arity = use_arity.unwrap();

    let site_pattern =
        fancy_regex::Regex::new(&format!(r"\b{name}\s*\(")).expect("failed to build regex");
    let mut param_types: Vec<BTreeSet<String>> = (0..use_arity).map(|_| BTreeSet::new()).collect();
    for m in site_pattern.find_iter(masked).flatten() {
        if whole.0 <= m.start() && m.start() < whole.1 {
            continue;
        }
        let args = match split_top_level(masked, m.end() - 1) {
            Some(args) => args,
            None => return Ok(source.to_string()),
        };
        if args.len() != use_arity {
            return Ok(source.to_string());
        }
        for (position, arg) in args.into_iter().enumerate() {
            let inferred = infer_type(arg.trim(), parsed, source, masked, m.start());
            param_types[position].insert(inferred);
        }
    }
    if param_types.iter().any(|options| options.len() != 1) {
        findings.push(StageFinding {
            kind: format!("{kind}-arity-mismatch"),
            detail: name.to_string(),
            reason: format!(
                "declared with {declared} argument(s) but used with {use_arity} with conflicting \
                 inferred types; left for unit repair"
            ),
        });
        return Ok(source.to_string());
    }

    let rendered: String = param_types
        .iter()
        .map(|options| options.iter().next().unwrap().clone())
        .collect::<Vec<_>>()
        .join(", ");
    let open_offset = whole.0 + open;
    let close_offset = whole.0 + close;
    let updated = format!("{}{}{}", &source[..open_offset + 1], rendered, &source[close_offset..]);
    edits.push(StageEdit {
        kind: format!("{kind}-arity-retype"),
        detail: format!("{name}: ({inner}) -> ({rendered})"),
        evidence: "usage-site arity and argument types".to_string(),
    });
    Ok(updated)
}

/// Declared-symbol names for `kind`, from the masked text, sorted.
fn declared_names(masked: &str, pattern: &fancy_regex::Regex) -> BTreeSet<String> {
    pattern
        .captures_iter(masked)
        .flatten()
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .collect()
}

/// Usage-site names (`CustomError_`/`Event_` shape) from the masked text.
fn used_names(masked: &str, pattern: &fancy_regex::Regex) -> BTreeSet<String> {
    declared_names(masked, pattern)
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let mut edits: Vec<StageEdit> = Vec::new();
    let mut findings: Vec<StageFinding> = Vec::new();

    // pass one: retype declared symbols whose usage disagrees
    let mut current = source.to_string();
    for (kind, name_re) in [("event", &*RE_EVENT_NAME), ("error", &*RE_ERROR_NAME)] {
        for name in declared_names(&mask(&current)?, name_re) {
            let masked = mask(&current)?;
            let parsed = parse_contract(&current, None)?;
            current = reconcile_declaration(
                &current,
                &masked,
                &parsed,
                &name,
                kind,
                &mut edits,
                &mut findings,
            )?;
        }
    }

    // pass two: insert declarations referenced but never declared
    let masked = mask(&current)?;
    let parsed = parse_contract(&current, None)?;
    let body_start = body_open_line_end(&current, parsed.body_start);
    let declared_errors = declared_names(&masked, &RE_DECLARED_ERROR);
    let declared_events = declared_names(&masked, &RE_DECLARED_EVENT);
    let used_errors = used_names(&masked, &RE_USED_ERROR);
    let used_events = used_names(&masked, &RE_USED_EVENT);

    let mut insertions: Vec<(usize, String)> = Vec::new();
    for (alias, used, declared, decl_line, line_kind) in [
        ("error", &used_errors, &declared_errors, &*RE_ERROR_DECL_LINE, "undeclared-error"),
        ("event", &used_events, &declared_events, &*RE_EVENT_DECL_LINE, "undeclared-event"),
    ] {
        for name in used.difference(declared) {
            let arity = match call_arity(&masked, name, None) {
                Some(arity) => arity,
                None => {
                    findings.push(StageFinding {
                        kind: line_kind.to_string(),
                        detail: name.clone(),
                        reason: if alias == "error" {
                            "call sites disagree on arity".to_string()
                        } else {
                            "emit sites disagree on arity".to_string()
                        },
                    });
                    continue;
                }
            };
            let params: Vec<&str> = vec!["uint256"; arity];
            let params = params.join(", ");
            let line = format!("    {alias} {name}({params});\n");
            let offset = insertion_offset(&current, &masked, decl_line, body_start);
            insertions.push((offset, line));
            edits.push(StageEdit {
                kind: line_kind.to_string(),
                detail: format!("{alias} {name}({params})"),
                evidence: "referenced before declaration".to_string(),
            });
        }
    }

    let mut replacement = current;
    insertions.sort_by(|a, b| b.0.cmp(&a.0));
    for (offset, line) in insertions {
        replacement = format!("{}{}{}", &replacement[..offset], line, &replacement[offset..]);
    }

    Ok(Stage {
        name: "declarations",
        description: "error/event declarations",
        source: replacement,
        edits,
        findings,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const SOURCE: &str = concat!(
        "contract C {\n",
        "    error Known();\n",
        "    function f(uint256 a) public { require(a > 0, CustomError_1234abcd(a)); }\n",
        "    function g() public { emit Event_beefcafe(1, 2); }\n",
        "}\n",
    );

    #[test]
    fn declares_missing_error_and_event_with_site_arity() {
        let stage = run(SOURCE).unwrap();
        assert!(stage.source.contains("error CustomError_1234abcd(uint256);"));
        assert!(stage.source.contains("event Event_beefcafe(uint256, uint256);"));
        assert!(stage.source.contains("error Known();"));
    }

    #[test]
    fn inserts_after_existing_declaration_block() {
        let stage = run(SOURCE).unwrap();
        let error_pos = stage.source.find("error Known();").unwrap();
        let new_pos = stage.source.find("error CustomError_1234abcd").unwrap();
        assert!(new_pos > error_pos);
        assert!(stage.source.find("function f").unwrap() > new_pos);
    }

    #[test]
    fn retypes_declared_event_from_usage() {
        let source = concat!(
            "contract C {\n",
            "    event Empty();\n",
            "    function f(uint256 a) public { emit Empty(a, 2); }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert!(stage.source.contains("event Empty(uint256, uint256);"));
        assert_eq!(stage.edits[0].kind, "event-arity-retype");
    }

    #[test]
    fn conflicting_usage_types_remain_a_finding() {
        let source = concat!(
            "contract C {\n",
            "    event Empty();\n",
            "    function f(uint256 a) public {\n",
            "        if (a > 0) { emit Empty(a); } else { emit Empty(msg.sender); }\n",
            "    }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert!(stage.source.contains("event Empty();"));
        assert!(stage.findings.iter().any(|f| f.kind == "event-arity-mismatch"));
    }

    #[test]
    fn ambiguous_call_arity_is_a_finding() {
        let source = concat!(
            "contract C {\n",
            "    function f(uint256 a) public {\n",
            "        if (a > 0) { require(a, CustomError_11223344(a)); }\n",
            "        require(a, CustomError_11223344(a, a));\n",
            "    }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert!(!stage.source.contains("error CustomError_11223344"));
        assert!(stage.findings.iter().any(|f| f.kind == "undeclared-error"));
    }
}
