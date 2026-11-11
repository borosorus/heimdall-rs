//! Stage `packed-scalars`: retype `bytes` slots packing one uint scalar.
//!
//! Port of `prepare_candidate.recover_packed_scalar_storage` with
//! `_packed_close`, `_packed_uint_kind`, and `_packed_length_read`: a
//! slot-commented `bytes` whose single writer is `X = abi.encodePacked(<bare
//! uint param>)` and whose every other occurrence is a guarded `.length`
//! comparison or a packed-encode argument is a mis-typed scalar. The decl is
//! retyped, the writer stores the scalar directly, and `.length` reads are
//! unwrapped. Any unclassified occurrence abstains the whole variable.

use lazy_static::lazy_static;
use std::collections::BTreeMap;

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::{header_params, mask, split_top_level},
    Stage, StageEdit, StageFinding,
};

lazy_static! {
    static ref RE_SLOT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"//\s*storage slot:\s*(0x[0-9a-fA-F]+)")
            .expect("failed to build regex");
    static ref RE_PACKED_CALL: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\babi\s*\.\s*encodePacked\s*\(").expect("failed to build regex");
    static ref RE_BYTES_DECL: fancy_regex::Regex =
        fancy_regex::Regex::new(r"(?m)^[ \t]*bytes[ \t]+([A-Za-z_]\w*)[ \t]*;(?P<rest>[^\n]*)$")
            .expect("failed to build regex");
    static ref RE_ANY_SLOT_DECL: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?m)^[ \t]*(?P<type>[A-Za-z_][\w\[\]]*)[ \t]+(?P<name>[A-Za-z_]\w*)[ \t]*;[^\n]*$",
    )
    .expect("failed to build regex");
    static ref RE_DOT_LENGTH: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^\s*\.\s*length\b").expect("failed to build regex");
    static ref RE_BYTES_KW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bbytes\b").expect("failed to build regex");
    static ref RE_PACKED_RHS: fancy_regex::Regex =
        fancy_regex::Regex::new(r"abi\s*\.\s*encodePacked").expect("failed to build regex");
    static ref RE_BARE_IDENT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^[A-Za-z_]\w*$").expect("failed to build regex");
}

/// Offset just past the parenthesis matching `open_paren`; `None` unbalanced.
/// Mirrors `prepare_candidate._packed_close`.
fn packed_close(masked: &str, open_paren: usize) -> Option<usize> {
    let bytes = masked.as_bytes();
    let (mut depth, mut index) = (1usize, open_paren + 1);
    while index < bytes.len() && depth > 0 {
        match bytes[index] {
            b'(' => depth += 1,
            b')' => depth -= 1,
            _ => {}
        }
        index += 1;
    }
    if depth == 0 {
        Some(index)
    } else {
        None
    }
}

/// Per-function `(start, end, param name -> declared kind)` maps.
type ParamsByUnit = Vec<(usize, usize, BTreeMap<String, String>)>;

/// `abi.encodePacked` call spans: `(call start, close, argument spans)`.
type PackedSpans = Vec<(usize, usize, Vec<(usize, usize)>)>;

/// Per-variable edit plans: `(name, slot, scalar arg, spans, readers)`.
type Planned = Vec<(String, String, String, Vec<(usize, usize, String)>, usize)>;

/// Whether `ident` at `position` is a `uint`/`uint256` parameter of the
/// enclosing function. Mirrors `prepare_candidate._packed_uint_kind`.
fn packed_uint_kind(ident: &str, position: usize, params_by_unit: &ParamsByUnit) -> bool {
    for (start, end, params) in params_by_unit {
        if *start <= position && position < *end {
            return params.get(ident).is_some_and(|kind| kind == "uint" || kind == "uint256");
        }
    }
    false
}

const OTHER_CLASS: &str = r"[A-Za-z_]\w*|\d+|0x[0-9a-fA-F]+";

/// Whether this `X.length` is a comparison operand against a proven-unsigned
/// identifier or an integer literal. Mirrors
/// `prepare_candidate._packed_length_read`.
fn packed_length_read(
    masked: &str,
    start: usize,
    end: usize,
    params_by_unit: &ParamsByUnit,
) -> bool {
    let window_start = start.saturating_sub(160);
    let window = &masked[window_start..(end + 160).min(masked.len())];
    let occ = fancy_regex::escape(&masked[start..end]);
    let patterns = [
        format!(r"(?P<other>{})\s*(?:<=|>=|<|>)\s*uint256\s*\(\s*{}\s*\)", OTHER_CLASS, occ),
        format!(r"(?P<other>{})\s*(?:<=|>=|<|>)\s*{}\b", OTHER_CLASS, occ),
        format!(
            r"{}\s*\)?\s*(?:<=|>=|<|>)\s*(?:uint256\s*\(\s*(?P<wrapped>[A-Za-z_]\w*)\s*\)|(?P<other2>{}))",
            occ, OTHER_CLASS
        ),
    ];
    for pattern in &patterns {
        let re = fancy_regex::Regex::new(pattern).expect("failed to build regex");
        let captures = match re.captures(window).ok().flatten() {
            Some(captures) => captures,
            None => continue,
        };
        let group = |key: &str| captures.name(key).map(|m| m.as_str().to_string());
        let other = match group("other").or_else(|| group("other2")).or_else(|| group("wrapped")) {
            Some(other) => other,
            None => continue,
        };
        if other.chars().all(|c| c.is_ascii_digit()) || other.starts_with("0x") {
            return true;
        }
        let which = if group("other").is_some() {
            "other"
        } else if group("wrapped").is_some() {
            "wrapped"
        } else {
            "other2"
        };
        let absolute = window_start + captures.name(which).expect("named group").start();
        return packed_uint_kind(&other, absolute, params_by_unit);
    }
    false
}

/// Every slot-annotated state declaration as `(name, (type, slot))`.
///
/// Mirrors `prepare_candidate._all_slot_decls`: structure from the masked
/// text, slot comment from the raw source at the same offsets (case kept).
fn all_slot_decls(masked: &str, source: &str) -> BTreeMap<String, (String, String)> {
    let mut found = BTreeMap::new();
    for captures in RE_ANY_SLOT_DECL.captures_iter(masked).flatten() {
        let whole = match captures.get(0) {
            Some(m) => (m.start(), m.end()),
            None => continue,
        };
        let slot = RE_SLOT
            .captures(&source[whole.0..whole.1])
            .ok()
            .flatten()
            .and_then(|c| c.get(1).map(|m| m.as_str().to_string()));
        if let Some(slot) = slot {
            let name = captures.name("name").map(|m| m.as_str().to_string()).unwrap_or_default();
            let ty = captures.name("type").map(|m| m.as_str().to_string()).unwrap_or_default();
            found.insert(name, (ty, slot));
        }
    }
    found
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let mut edits: Vec<StageEdit> = Vec::new();
    let mut findings: Vec<StageFinding> = Vec::new();
    let masked = mask(source)?;
    let parsed = match parse_contract(source, None) {
        Ok(parsed) => parsed,
        Err(error) => {
            findings.push(StageFinding {
                kind: "packed-scalar-storage".to_string(),
                detail: "<source>".to_string(),
                reason: format!("source does not parse: {error}"),
            });
            return Ok(Stage {
                name: "packed-scalars",
                description: "packed scalar storage recovery",
                source: source.to_string(),
                edits,
                findings,
            });
        }
    };

    let mut params_by_unit: ParamsByUnit = Vec::new();
    for unit in parsed.functions() {
        let header_masked = mask(&unit.header)?;
        params_by_unit.push((
            unit.start,
            unit.end,
            header_params(&header_masked).into_iter().map(|(kind, name)| (name, kind)).collect(),
        ));
    }

    // spans of every abi.encodePacked(...) call and its top-level arguments
    let mut packed_spans: PackedSpans = Vec::new();
    for call in RE_PACKED_CALL.find_iter(&masked).flatten() {
        let close = match packed_close(&masked, call.end() - 1) {
            Some(close) => close,
            None => continue,
        };
        let args = split_top_level(&masked, call.end() - 1).unwrap_or_default();
        let mut cursor = call.end();
        let mut spans: Vec<(usize, usize)> = Vec::new();
        for arg in args {
            if cursor > close {
                break;
            }
            let rel = match masked[cursor..close].find(&arg) {
                Some(rel) => rel,
                None => continue,
            };
            let offset = cursor + rel;
            spans.push((offset, offset + arg.len()));
            cursor = offset + arg.len();
        }
        packed_spans.push((call.start(), close, spans));
    }

    // candidate declarations: slot-commented `bytes x;`, unique as a bare
    // `bytes x;` line, with no other slot declaration on the same slot
    let mut declarations: BTreeMap<String, (usize, usize, String)> = BTreeMap::new();
    let slot_decls = all_slot_decls(&masked, source);
    for captures in RE_BYTES_DECL.captures_iter(&masked).flatten() {
        let whole = match captures.get(0) {
            Some(m) => (m.start(), m.end()),
            None => continue,
        };
        let name = match captures.get(1) {
            Some(m) => m.as_str().to_string(),
            None => continue,
        };
        let slot = match RE_SLOT.captures(&source[whole.0..whole.1]).ok().flatten() {
            Some(c) => match c.get(1) {
                Some(g) => g.as_str().to_string(),
                None => continue,
            },
            None => continue,
        };
        let others = fancy_regex::Regex::new(&format!(
            r"(?m)^[ \t]*bytes[ \t]+{}[ \t]*;",
            fancy_regex::escape(&name)
        ))
        .expect("failed to build regex");
        if others.find_iter(&masked).flatten().any(|m| m.start() != whole.0) {
            continue;
        }
        if slot_decls.iter().any(|(other, (_, other_slot))| other != &name && other_slot == &slot) {
            continue;
        }
        declarations.insert(name, (whole.0, whole.1, slot));
    }

    // per-declaration planning
    let mut planned: Planned = Vec::new();
    for (name, (decl_start, decl_end, slot)) in &declarations {
        let escaped = fancy_regex::escape(name);
        let writer_re = fancy_regex::Regex::new(&format!(
            r"\b{escaped}\b\s*=(?!=)\s*abi\s*\.\s*encodePacked\s*\("
        ))
        .expect("failed to build regex");
        let writers: Vec<_> = writer_re.find_iter(&masked).flatten().collect();
        if writers.len() != 1 {
            findings.push(StageFinding {
                kind: "packed-scalar-storage".to_string(),
                detail: name.clone(),
                reason: format!("{} packed writer(s), need exactly 1", writers.len()),
            });
            continue;
        }
        let writer = writers[0];
        let close = packed_close(&masked, writer.end() - 1);
        let close = match close {
            Some(close) if masked[close.min(masked.len())..].trim_start().starts_with(';') => close,
            _ => {
                findings.push(StageFinding {
                    kind: "packed-scalar-storage".to_string(),
                    detail: name.clone(),
                    reason: "writer statement shape".to_string(),
                });
                continue;
            }
        };
        let args = split_top_level(&masked, writer.end() - 1).unwrap_or_default();
        if args.len() != 1 {
            findings.push(StageFinding {
                kind: "packed-scalar-storage".to_string(),
                detail: name.clone(),
                reason: format!("{} packed argument(s), need exactly 1", args.len()),
            });
            continue;
        }
        let arg = args[0].trim();
        if !RE_BARE_IDENT.is_match(arg).unwrap_or(false) {
            findings.push(StageFinding {
                kind: "packed-scalar-storage".to_string(),
                detail: name.clone(),
                reason: format!("packed argument {arg:?} is not a bare identifier"),
            });
            continue;
        }
        if !packed_uint_kind(arg, writer.start(), &params_by_unit) {
            findings.push(StageFinding {
                kind: "packed-scalar-storage".to_string(),
                detail: name.clone(),
                reason: format!("writer input {arg:?} is not a uint parameter"),
            });
            continue;
        }
        let length_reader = fancy_regex::Regex::new(&format!(r"\b{escaped}\s*\.\s*length\b"))
            .expect("failed to build regex");
        if length_reader.find_iter(&masked).flatten().next().is_none() {
            findings.push(StageFinding {
                kind: "packed-scalar-storage".to_string(),
                detail: name.clone(),
                reason: "no length reader to recover".to_string(),
            });
            continue;
        }

        let writer_span = (writer.start(), close);
        let decl_span = (*decl_start, *decl_end);
        let mut plan: Vec<(usize, usize, String)> = Vec::new();
        let mut readers = 0usize;
        let mut ok = true;
        let word =
            fancy_regex::Regex::new(&format!(r"\b{escaped}\b")).expect("failed to build regex");
        for occurrence in word.find_iter(&masked).flatten() {
            let (start, end) = (occurrence.start(), occurrence.end());
            if (decl_span.0 <= start && start < decl_span.1) ||
                (writer_span.0 <= start && start < writer_span.1)
            {
                continue;
            }
            let tail = &masked[end.min(masked.len())..];
            let dot = RE_DOT_LENGTH.captures(tail).ok().flatten().and_then(|c| c.get(0));
            if let Some(dot) = dot {
                if packed_length_read(&masked, start, end + dot.end(), &params_by_unit) {
                    plan.push((start, end + dot.end(), name.clone()));
                    readers += 1;
                    continue;
                }
                findings.push(StageFinding {
                    kind: "packed-scalar-storage".to_string(),
                    detail: name.clone(),
                    reason: "length read is not a guarded comparison".to_string(),
                });
                ok = false;
                break;
            }
            let packed_arg = packed_spans.iter().any(|(call_start, call_end, spans)| {
                *call_start <= start &&
                    start < *call_end &&
                    spans.iter().any(|(a, b)| masked[*a..*b].trim() == name.as_str())
            });
            if !packed_arg {
                findings.push(StageFinding {
                    kind: "packed-scalar-storage".to_string(),
                    detail: name.clone(),
                    reason: format!("unclassified occurrence at offset {start}"),
                });
                ok = false;
                break;
            }
        }
        if !ok {
            continue;
        }

        if let Some(bytes) = RE_BYTES_KW
            .captures(&masked[decl_span.0..decl_span.1])
            .ok()
            .flatten()
            .and_then(|c| c.get(0))
        {
            plan.push((
                decl_span.0 + bytes.start(),
                decl_span.0 + bytes.end(),
                "uint256".to_string(),
            ));
        }
        if let Some(rhs) = RE_PACKED_RHS
            .captures(&masked[writer.start()..writer.end()])
            .ok()
            .flatten()
            .and_then(|c| c.get(0))
        {
            plan.push((writer.start() + rhs.start(), close, arg.to_string()));
        }
        planned.push((name.clone(), slot.clone(), arg.to_string(), plan, readers));
    }

    // all spans are computed against the untouched source; splice once, in
    // descending order, after verifying the variables never overlap
    let mut merged: Vec<(usize, usize, String)> =
        planned.iter().flat_map(|(_, _, _, plan, _)| plan.clone()).collect();
    merged.sort_by_key(|(start, ..)| *start);
    for window in merged.windows(2) {
        if window[1].0 < window[0].1 {
            findings.push(StageFinding {
                kind: "packed-scalar-storage".to_string(),
                detail: "<overlap>".to_string(),
                reason: "edits overlap; abstaining".to_string(),
            });
            merged.clear();
            planned.clear();
            break;
        }
    }

    let mut staged = source.to_string();
    if !merged.is_empty() {
        for (start, end, text) in merged.iter().rev() {
            staged = format!("{}{}{}", &staged[..*start], text, &staged[*end..]);
        }
    }
    for (name, slot, arg, _, readers) in &planned {
        edits.push(StageEdit {
            kind: "packed-scalar-storage".to_string(),
            detail: format!("{name}: bytes -> uint256 (slot {slot})"),
            evidence: format!(
                "single writer '{name} = abi.encodePacked({arg})'; {readers} length-read(s) \
                 unwrapped; assumption: packed single scalar, dynamic length semantics not intended"
            ),
        });
    }

    Ok(Stage {
        name: "packed-scalars",
        description: "packed scalar storage recovery",
        source: staged,
        edits,
        findings,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const BASE: &str = concat!(
        "contract C {\n",
        "    bytes c; // storage slot: 0x02\n",
        "    bytes d; // storage slot: 0x03\n",
        "    error E();\n",
        "    function set(uint256 a) public { c = abi.encodePacked(a); }\n",
        "    function setD(uint256 a) public { d = abi.encodePacked(a); }\n",
        "    function chk(uint256 x) public view returns (bool) { return x < c.length; }\n",
        "    function guard(uint256 x) public view { require(x >= uint256(c.length), E()); }\n",
        "    function pair() public view returns (bytes memory) { return abi.encodePacked(c, d); }\n",
        "}\n",
    );

    #[test]
    fn recovers_uint256_packed_storage() {
        let stage = run(BASE).unwrap();
        assert_eq!(stage.name, "packed-scalars");
        let details: Vec<&str> = stage.edits.iter().map(|e| e.detail.as_str()).collect();
        assert_eq!(details, vec!["c: bytes -> uint256 (slot 0x02)"]);
        assert!(stage.source.contains("uint256 c; // storage slot: 0x02"));
        assert!(stage.source.contains("c = a;"));
        assert!(stage.source.contains("x < c;"));
        assert!(stage.source.contains("require(x >= uint256(c), E());"));
        assert!(stage.source.contains("abi.encodePacked(c, d)")); // legal: two packed words
        assert!(stage.source.contains("bytes d; // storage slot: 0x03")); // no length reader
    }

    #[test]
    fn multiple_writes_abstain() {
        let source = BASE.replace(
            "    function setD(uint256 a) public { d = abi.encodePacked(a); }",
            "    function set2(uint256 a) public { if (a > 0) { c = abi.encodePacked(a); } }",
        );
        let stage = run(&source).unwrap();
        assert!(stage.edits.is_empty());
        assert!(stage.findings.iter().any(|f| f.reason.contains("packed writer")));
        assert!(stage.source.contains("bytes c;"));
    }

    #[test]
    fn dynamic_or_non_uint256_input_abstains() {
        let bytes_arg = BASE.replace(
            "function set(uint256 a) public { c = abi.encodePacked(a); }",
            "function set(bytes memory b) public { c = abi.encodePacked(b); }",
        );
        let two_args = BASE.replace("c = abi.encodePacked(a);", "c = abi.encodePacked(a, a);");
        let narrow = BASE.replace("function set(uint256 a)", "function set(uint128 a)");
        for source in [&bytes_arg, &two_args, &narrow] {
            let stage = run(source).unwrap();
            assert!(stage.edits.is_empty(), "{}", &source[..60]);
            assert!(!stage.findings.is_empty());
        }
    }

    #[test]
    fn unclassified_storage_use_abstains() {
        let source = BASE.replace(
            "    function pair() public view returns (bytes memory) { return abi.encodePacked(c, d); }",
            "    function zap() public { delete c; }",
        );
        let stage = run(&source).unwrap();
        assert!(stage.edits.is_empty());
        assert!(stage.findings.iter().any(|f| f.reason.contains("unclassified occurrence")));
    }

    #[test]
    fn masks_comments_and_strings() {
        let commented = BASE.replace(
            "    error E();",
            concat!(
                "    // bytes zz; zz = abi.encodePacked(q); if (q < zz.length) {}\n",
                "    string memory note = \"bytes zz;\";\n",
                "    error E();",
            ),
        );
        let stage = run(&commented).unwrap();
        let details: Vec<&str> = stage.edits.iter().map(|e| e.detail.as_str()).collect();
        assert_eq!(details, vec!["c: bytes -> uint256 (slot 0x02)"]);
        assert!(stage
            .source
            .contains("// bytes zz; zz = abi.encodePacked(q); if (q < zz.length) {}"));
        assert!(!stage.source.contains("uint256 zz"));
    }

    #[test]
    fn recovery_is_idempotent() {
        let once = run(BASE).unwrap();
        let twice = run(&once.source).unwrap();
        assert!(twice.edits.is_empty());
        assert_eq!(once.source, twice.source);
    }

    #[test]
    fn fixture_sources_are_unchanged() {
        let fixtures =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../evaluation/fixtures");
        // one level: <fixtures>/<name>/*.sol
        let mut checked = 0usize;
        for contract in std::fs::read_dir(&fixtures).expect("fixtures directory") {
            let dir = contract.expect("fixture entry").path();
            if !dir.is_dir() {
                continue;
            }
            for file in std::fs::read_dir(&dir).expect("fixture files") {
                let path = file.expect("fixture file").path();
                if path.extension().and_then(|e| e.to_str()) != Some("sol") {
                    continue;
                }
                let source = std::fs::read_to_string(&path).expect("fixture source");
                let stage = run(&source).unwrap();
                assert_eq!(stage.source, source, "{}", path.display());
                checked += 1;
            }
        }
        assert!(checked >= 9);
    }

    #[test]
    fn runs_after_slot_aliases_in_pipeline() {
        let staged = crate::prepare::prepare(BASE).unwrap();
        let names: Vec<&str> = staged.stages.iter().map(|s| s.name).collect();
        let packed = names.iter().position(|n| *n == "packed-scalars").unwrap();
        let aliases = names.iter().position(|n| *n == "slot-aliases").unwrap();
        assert!(packed > aliases);
        assert!(staged.source.contains("uint256 c;"));
    }
}
