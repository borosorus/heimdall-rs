//! Stage `truthiness`: rewrite truthiness tests into explicit compares.
//!
//! Port of `prepare_candidate.relax_truthiness_requires` (the sequential
//! re-masked form): the decompiler renders `x != 0` guards as `require(x, ..)`
//! / `if (x)` and negations as `!(x)` / `!x`; Solidity has no implicit
//! int-to-bool conversion. Four passes run IN ORDER, each re-masking the
//! previous result (stale-span discipline): (1) bare-identifier / literal
//! guards against known-uint/address names, (2) parenthesized flat-bitwise
//! negation in guard position, (3) uint negation in any expression position
//! with per-unit parameter kinds, (4) bool-context member chains ending in
//! `.length`. Everything else abstains.

use lazy_static::lazy_static;
use std::collections::BTreeSet;

use crate::prepare::{
    parser::{mask_strings_and_comments, parse_contract, ParseError, ParsedSource},
    stages::helpers::mask,
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_UINT_VAR: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\buint\d*\s+(var_[a-z]+)\b").expect("failed to build regex");
    static ref RE_STATE_UINT: fancy_regex::Regex = fancy_regex::Regex::new(
        r"\buint\d*\s+(?:public|private|internal|constant|immutable|override|[ \t])*([A-Za-z_]\w*)\s*(?:=[^;]+)?;",
    )
    .expect("failed to build regex");
    static ref RE_STATE_ADDR: fancy_regex::Regex = fancy_regex::Regex::new(
        r"\baddress\s+(?:public|private|internal|constant|immutable|override|[ \t])*([A-Za-z_]\w*)\s*(?:=[^;]+)?;",
    )
    .expect("failed to build regex");
    static ref RE_HEADER_KIND: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b(address|uint\d*)\s+([A-Za-z_]\w*)").expect("failed to build regex");
    static ref RE_HEADER_UINT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\buint\d*\s+([A-Za-z_]\w*)").expect("failed to build regex");
    static ref RE_GUARD: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?P<kw>\brequire\b|\bif\b)\s*\(\s*(?P<expr>[A-Za-z_][\w.]*|0x[0-9a-fA-F]+|\d+)\s*(?P<comma>,|\))",
    )
    .expect("failed to build regex");
    static ref RE_GUARD_LITERAL: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^(?:0x[0-9a-fA-F]+|\d+)$").expect("failed to build regex");
    static ref RE_GUARD_NEGATION: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?P<kw>\brequire\b|\bif\b)\s*\(\s*!\((?P<inner>[^()]*)\)\s*\)(?P<comma>,)?",
    )
    .expect("failed to build regex");
    static ref RE_EXPR_NEGATION: fancy_regex::Regex = fancy_regex::Regex::new(
        r"!\((?P<inner>[^()]*)\)|!\s?(?P<bare>[A-Za-z_][A-Za-z0-9_]*)",
    )
    .expect("failed to build regex");
    static ref RE_BARE_IDENT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^[A-Za-z_]\w*$").expect("failed to build regex");
    static ref RE_HEAD: fancy_regex::Regex =
        fancy_regex::Regex::new(r"(?P<kw>\brequire\b|\bif\b)\(").expect("failed to build regex");
    static ref RE_MEMBER_CHAIN: fancy_regex::Regex = fancy_regex::Regex::new(
        r"^[A-Za-z_][A-Za-z0-9_]*\([^()]*\)(?:\.\w+)+$",
    )
    .expect("failed to build regex");
    /// boolean-producing constructs (comparisons, logical operators, negation)
    static ref RE_HAS_BOOL_OP: fancy_regex::Regex = fancy_regex::Regex::new(
        r"&&|\|\||==|!=|<=|>=|<|>|(?<![A-Za-z_])!(?![=])",
    )
    .expect("failed to build regex");
    /// arithmetic / bitwise constructs (uint-by-construction)
    static ref RE_HAS_ARITH_OP: fancy_regex::Regex = fancy_regex::Regex::new(
        r"[-+*/%]|(?<![|&])&(?!&)|(?<![|^])\^(?!^)|(?<![|])\|(?!\|)",
    )
    .expect("failed to build regex");
}

/// `int(text, 0)` for the guard-constant shapes (`0x..` / decimal).
fn parse_int0(text: &str) -> Option<u64> {
    if let Some(hex) = text.strip_prefix("0x") {
        u64::from_str_radix(hex, 16).ok()
    } else {
        text.parse::<u64>().ok()
    }
}

/// Python `flat_uint`: a uint-by-construction expression - arithmetic / bitwise
/// operators and calls, no boolean producers (comparisons, `&&`, `||`, `!`).
fn flat_uint(inner: &str) -> bool {
    if RE_HAS_BOOL_OP.is_match(inner).unwrap_or(false) {
        return false;
    }
    RE_HAS_ARITH_OP.is_match(inner).unwrap_or(false)
}

/// Known uint/address names, per the Python `known_kinds` closure: `var_*`
/// uint locals, contract-level state declarations outside every unit
/// (visibility qualifiers accepted), and per-unit header parameters.
fn known_kinds(
    parsed: Option<&ParsedSource>,
    source: &str,
) -> (BTreeSet<String>, BTreeSet<String>) {
    let masked = mask(source).unwrap_or_else(|_| source.to_string());
    let mut uints: BTreeSet<String> = RE_UINT_VAR
        .captures_iter(&masked)
        .flatten()
        .filter_map(|c| c.get(1).map(|m| m.as_str().into()))
        .collect();
    let mut addrs: BTreeSet<String> = BTreeSet::from(["msg.sender".to_string()]);
    let Some(parsed) = parsed else {
        return (uints, addrs);
    };
    let spans: Vec<(usize, usize)> =
        parsed.functions().map(|unit| (unit.start, unit.end)).collect();
    let in_unit = |offset: usize| spans.iter().any(|(a, b)| *a <= offset && offset < *b);
    for captures in RE_STATE_UINT.captures_iter(&masked).flatten() {
        let outside = captures.get(0).map(|m| !in_unit(m.start())).unwrap_or(false);
        if outside {
            if let Some(m) = captures.get(1) {
                uints.insert(m.as_str().to_string());
            }
        }
    }
    for captures in RE_STATE_ADDR.captures_iter(&masked).flatten() {
        let outside = captures.get(0).map(|m| !in_unit(m.start())).unwrap_or(false);
        if outside {
            if let Some(m) = captures.get(1) {
                addrs.insert(m.as_str().to_string());
            }
        }
    }
    for unit in parsed.functions() {
        let header_masked =
            mask_strings_and_comments(&unit.header, 0, unit.header.len()).unwrap_or_default();
        for captures in RE_HEADER_KIND.captures_iter(&header_masked).flatten() {
            let (kind, name) = (captures.get(1), captures.get(2));
            if let (Some(kind), Some(name)) = (kind, name) {
                if kind.as_str() == "address" {
                    addrs.insert(name.as_str().to_string());
                } else {
                    uints.insert(name.as_str().to_string());
                }
            }
        }
    }
    (uints, addrs)
}

/// One sequential re-masked pass: matches `pattern` on the masked text, builds
/// replacements, splices into the raw source (the mask is length-preserving).
fn splice(
    source: &str,
    masked: &str,
    regex: &fancy_regex::Regex,
    mut build: impl FnMut(&fancy_regex::Captures<'_>) -> Option<(String, StageEdit)>,
) -> Result<(String, Vec<StageEdit>), ParseError> {
    let mut pieces: Vec<String> = Vec::new();
    let mut edits: Vec<StageEdit> = Vec::new();
    let mut last = 0usize;
    for captures in regex.captures_iter(masked).flatten() {
        let Some((replacement, record)) = build(&captures) else {
            continue;
        };
        let whole = captures.get(0).expect("whole match");
        pieces.push(source[last..whole.start()].to_string());
        pieces.push(replacement);
        last = whole.end();
        edits.push(record);
    }
    if pieces.is_empty() {
        return Ok((source.to_string(), edits));
    }
    pieces.push(source[last..].to_string());
    Ok((pieces.concat(), edits))
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let mut edits: Vec<StageEdit> = Vec::new();
    let parsed = parse_contract(source, None).ok();

    // ---- pass 1: bare-identifier / literal guards
    let (uints, addrs) = known_kinds(parsed.as_ref(), source);
    let build1 = |captures: &fancy_regex::Captures<'_>| -> Option<(String, StageEdit)> {
        let kw = captures.name("kw")?.as_str();
        let expr = captures.name("expr")?.as_str();
        let comma = captures.name("comma").map(|m| m.as_str() == ",")?;
        let cmp: String = if RE_GUARD_LITERAL.is_match(expr).unwrap_or(false) && kw == "if" {
            match parse_int0(expr) {
                Some(0) => "false".to_string(),
                Some(1) => "true".to_string(),
                _ => return None,
            }
        } else if addrs.contains(expr) {
            format!("{expr} != address(0)")
        } else if uints.contains(expr) || expr.ends_with(".length") {
            format!("{expr} != 0")
        } else {
            return None;
        };
        let replaced = if comma { format!("{kw}({cmp},") } else { format!("{kw}({cmp})") };
        Some((
            replaced,
            StageEdit {
                kind: "truthiness-guard".to_string(),
                detail: format!("{kw}({expr}...) -> {kw}({cmp}...)"),
                evidence: "truthiness condition without implicit bool conversion".to_string(),
            },
        ))
    };
    let masked = mask(source)?;
    let (source, new_edits) = splice(source, &masked, &RE_GUARD, build1)?;
    edits.extend(new_edits);

    // ---- pass 2: parenthesized flat-bitwise negation in guard position
    let build2 = |captures: &fancy_regex::Captures<'_>| -> Option<(String, StageEdit)> {
        let inner = captures.name("inner")?.as_str().trim();
        let kw = captures.name("kw")?.as_str();
        let comma = captures.name("comma").is_some();
        if inner.is_empty() || !flat_uint(inner) {
            return None;
        }
        // Python-verified renderings (pinned by the unit tests below):
        // comma match  -> `kw((inner) == 0,)`
        // bare match   -> `kw((inner) == 0))`
        let replaced = if comma {
            format!("{kw}(({inner}) == 0,)")
        } else {
            format!("{kw}(({inner}) == 0))")
        };
        Some((
            replaced,
            StageEdit {
                kind: "truthiness-negation".to_string(),
                detail: format!("{kw}(!({inner})) -> {kw}(({inner}) == 0...)"),
                evidence: "uint negation without implicit bool conversion".to_string(),
            },
        ))
    };
    let masked = mask(&source)?;
    let (source, new_edits) = splice(&source, &masked, &RE_GUARD_NEGATION, build2)?;
    edits.extend(new_edits);

    // ---- pass 3: uint negation in expression position (parenthesized or
    // bare); per-unit parameter kinds (cross-unit like-named params may be
    // bool). Python reparses the post-pass-2 source here - the earlier passes'
    // length-changing edits shift unit spans, so the stale parse must go
    let parsed3 = parse_contract(&source, None).ok();
    let (uints, _) = known_kinds(parsed3.as_ref(), &source);
    let unit_uint_params: Vec<(usize, usize, BTreeSet<String>)> = parsed3
        .as_ref()
        .map(|parsed| {
            parsed
                .functions()
                .map(|unit| {
                    let header_masked =
                        mask_strings_and_comments(&unit.header, 0, unit.header.len())
                            .unwrap_or_default();
                    let names: BTreeSet<String> = RE_HEADER_UINT
                        .captures_iter(&header_masked)
                        .flatten()
                        .filter_map(|c| c.get(1).map(|m| m.as_str().into()))
                        .collect();
                    (unit.start, unit.end, names)
                })
                .collect()
        })
        .unwrap_or_default();
    let uints_at = |offset: usize| -> BTreeSet<String> {
        // Python `uints_at`: the enclosing unit's uint params union the
        // declared set; outside every unit, the declared set alone
        for (a, b, names) in &unit_uint_params {
            if *a <= offset && offset < *b {
                let mut union = names.clone();
                union.extend(uints.iter().cloned());
                return union;
            }
        }
        uints.clone()
    };
    let build3 = |captures: &fancy_regex::Captures<'_>| -> Option<(String, StageEdit)> {
        let inner = captures
            .name("inner")
            .or_else(|| captures.name("bare"))
            .map(|m| m.as_str().trim())
            .unwrap_or("");
        if inner.is_empty() {
            return None;
        }
        let offset = captures.get(0).expect("whole").start();
        let bare_known =
            RE_BARE_IDENT.is_match(inner).unwrap_or(false) && uints_at(offset).contains(inner);
        if !(bare_known || flat_uint(inner)) {
            return None;
        }
        Some((
            format!("(({inner}) == 0)"),
            StageEdit {
                kind: "uint-negation-expression".to_string(),
                detail: format!("!({inner}) -> (({inner}) == 0)"),
                evidence: "uint negation in expression position".to_string(),
            },
        ))
    };
    let masked = mask(&source)?;
    let (source, new_edits) = splice(&source, &masked, &RE_EXPR_NEGATION, build3)?;
    edits.extend(new_edits);

    // ---- pass 4: bool-context member chains ending in `.length` (the chain
    // may contain one nested call with its own parens - balanced scan, wrap)
    let masked4 = mask(&source)?;
    let mut pieces4: Vec<String> = Vec::new();
    let mut last4 = 0usize;
    for head in RE_HEAD.captures_iter(&masked4).flatten() {
        let whole = head.get(0).expect("whole");
        let kw = head.name("kw").expect("kw").as_str();
        let open_paren = whole.end() - 1;
        let bytes = masked4.as_bytes();
        let mut depth = 0usize;
        let mut idx = open_paren;
        let mut close = None;
        while idx < bytes.len() {
            match bytes[idx] {
                b'(' => depth += 1,
                b')' => {
                    depth -= 1;
                    if depth == 0 {
                        close = Some(idx);
                        break;
                    }
                }
                _ => {}
            }
            idx += 1;
        }
        let Some(close) = close else { continue };
        let inner = masked4[open_paren + 1..close].trim();
        if !RE_MEMBER_CHAIN.is_match(inner).unwrap_or(false) {
            continue;
        }
        if !inner.ends_with("length") {
            continue;
        }
        let comma = masked4[close + 1..].starts_with(',');
        let replaced =
            if comma { format!("{kw}(({inner}) != 0,") } else { format!("{kw}(({inner}) != 0)") };
        pieces4.push(source[last4..whole.start()].to_string());
        pieces4.push(replaced);
        last4 = close + 1;
        // the Python detail truncates the chain to its first 40 chars
        let detail = if inner.len() > 40 {
            let mut cut = 40;
            while !source.is_char_boundary(cut) {
                cut += 1;
            }
            format!("{kw}({}...) -> ... != 0", &inner[..cut])
        } else {
            format!("{kw}({inner}...) -> ... != 0")
        };
        edits.push(StageEdit {
            kind: "truthiness-member-chain".to_string(),
            detail,
            evidence: "uint member chain in bool context".to_string(),
        });
    }
    let source = if pieces4.is_empty() {
        source
    } else {
        pieces4.push(source[last4..].to_string());
        pieces4.concat()
    };

    Ok(Stage {
        name: "truthiness",
        description: "truthiness require guards",
        source,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn bare_uint_guard_is_rewritten() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    function f() public pure returns (uint256) {\n",
            "        uint256 var_b = 0x1;\n",
            "        require(var_b);\n",
            "        return var_b;\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("require(var_b != 0);"));
    }

    #[test]
    fn msg_sender_guard_hits_address_zero() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    address owner;\n",
            "    function f() public view {\n",
            "        require(msg.sender);\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("require(msg.sender != address(0));"));
    }

    #[test]
    fn parenthesized_flat_negation_is_rewritten_in_guard() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    function f() public pure returns (uint256) {\n",
            "        uint256 var_b = 0x1;\n",
            "        require(!(var_b + 0x1));\n",
            "        return var_b;\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("require((var_b + 0x1) == 0));"));
    }

    #[test]
    fn bare_negation_in_expression_is_rewritten_for_known_uint() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    function f() public pure returns (uint256) {\n",
            "        uint256 var_b = 0x1;\n",
            "        uint256 var_c = !var_b;\n",
            "        return var_c;\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("uint256 var_c = ((var_b) == 0);"));
    }

    #[test]
    fn comparison_operands_are_left_to_the_owner_stage() {
        // `!(a == b)` is boolean negation, not uint negation: abstain in
        // expression position (the inner has comparison operators)
        let staged = prepare(concat!(
            "contract C {\n",
            "    function f() public pure returns (uint256) {\n",
            "        uint256 var_b = 0x1;\n",
            "        uint256 var_c = !(var_b == 0x1);\n",
            "        return var_c;\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("uint256 var_c = !(var_b == 0x1);"));
    }

    #[test]
    fn length_member_chain_in_guard_is_rewritten() {
        // the pass-4 shape: call-then-member chain (Python-verified)
        let staged = prepare(concat!(
            "contract C {\n",
            "    uint256[] items;\n",
            "    function f() public view returns (uint256) {\n",
            "        require(entries(0x1).length);\n",
            "        return 0x1;\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("require((entries(0x1).length) != 0);"));
    }

    #[test]
    fn pass2_comma_branch_renders_the_python_form() {
        // Python-verified: `if (!(0x1f & 0x2)), true` -> `if((0x1f & 0x2) == 0,) true`
        let staged = prepare(concat!(
            "contract C {\n",
            "    function f() public pure {\n",
            "        if (!(0x1f & 0x2)), true { revert(); }\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("if((0x1f & 0x2) == 0,) true"));
    }

    #[test]
    fn in_unit_length_change_does_not_hide_later_param_kinds() {
        // Python-verified: the pass-2 rewrite grows the unit before the
        // negation; the reparse keeps `var_f` known from the same unit's
        // signature -> `(((var_f) == 0))`
        let staged = prepare(concat!(
            "contract C {\n",
            "    function a(uint256 var_f) public pure returns (uint256) {\n",
            "        if (!(0x1f & 0x2)) { revert(); }\n",
            "        uint256 var_g = (!var_f);\n",
            "        return var_g;\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("uint256 var_g = (((var_f) == 0));"));
    }
}
