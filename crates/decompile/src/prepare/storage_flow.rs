//! Typed storage-flow evidence map.
//!
//! Rust port of `evaluation/scripts/storage_flow.py` (minus the JSON export,
//! which is an evaluation-only artifact): correlates decompiled function stubs
//! with slot-annotated storage declarations by TYPE UNIFICATION alone - never
//! by fixture, name similarity, or reference knowledge. A function whose
//! declared parameter types and (missing) return match a mapping's key chain
//! and value type is a storage-getter candidate; the match is `exact` when
//! every position agrees and `hinted` when the unit's own `@param` provenance
//! or the decompiler's generic-uint default bridges the difference.

use lazy_static::lazy_static;
use std::collections::BTreeMap;

use crate::prepare::{
    parser::{header_param_span, parse_contract, ParseError},
    stages::helpers::mask,
};

lazy_static! {
    static ref MAPPING_RE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^(?P<decl>mapping\s*\((?P<inner>.*)\))(?P<tail>.*)$")
            .expect("failed to build regex");
    static ref PUBLIC_RE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bpublic\b").expect("failed to build regex");
    static ref SLOT_RE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"//\s*storage slot:\s*(0x[0-9a-fA-F]+)")
            .expect("failed to build regex");
    static ref RE_DECL_LINE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"(?m)^[ \t]*(?P<head>[A-Za-z_][\w]*)[ \t]*(?P<rest>[^;\n]*);")
            .expect("failed to build regex");
    static ref RE_SCALAR_HEAD: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^(?:uint\d+|int\d+|address|bool|bytes\d*|string)(?:\[\d*\])*$",)
            .expect("failed to build regex");
    static ref RE_ARRAY_PREFIX: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^[ \t]*(\[\d*\])").expect("failed to build regex");
    static ref RE_IDENTIFIER: fancy_regex::Regex =
        fancy_regex::Regex::new(r"[A-Za-z_][\w]*").expect("failed to build regex");
    static ref RE_SPACES: fancy_regex::Regex =
        fancy_regex::Regex::new(r"[ \t]+").expect("failed to build regex");
    static ref RE_ALL_WS: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\s+").expect("failed to build regex");
    static ref RE_UINT_CANON: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\buint\d+\b").expect("failed to build regex");
    static ref RE_INT_CANON: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bint\d+\b").expect("failed to build regex");
    static ref RE_PARAM_HINT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"///\s*@param\s+([A-Za-z_]\w*)\s+\[([^\]]*)\]")
            .expect("failed to build regex");
    static ref RE_HINT_TYPE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"[A-Za-z_][\w\[\]]*").expect("failed to build regex");
    static ref RE_RETURNS: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\breturns\s*\(([^)]*)\)").expect("failed to build regex");
    static ref RE_RETURN_KW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\breturn\b").expect("failed to build regex");
    static ref RE_GENERIC_UINT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^uint\d*$").expect("failed to build regex");
}

/// The declaration-name keywords skipped when extracting a state variable's
/// name; mirrors `storage_flow.parse_storage_declarations`.
const DECL_KEYWORDS: [&str; 5] = ["public", "private", "internal", "constant", "immutable"];

/// A contract-level state declaration with its slot provenance.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct StorageDecl {
    pub name: String,
    pub type_text: String,
    pub slot: Option<String>,
    pub public: bool,
}

impl StorageDecl {
    /// Flattened key types of the mapping chain, outermost first; `None` when
    /// the declaration is not a mapping.
    pub(crate) fn key_chain(&self) -> Option<Vec<String>> {
        self.mapping_inner().map(|inner| flatten_mapping(&inner).0)
    }

    /// Innermost value type: the type indexed by the full key chain.
    pub(crate) fn value_type(&self) -> Option<String> {
        self.mapping_inner().map(|inner| flatten_mapping(&inner).1)
    }

    fn mapping_inner(&self) -> Option<String> {
        MAPPING_RE
            .captures(&self.type_text)
            .ok()
            .flatten()
            .and_then(|c| c.name("inner").map(|m| m.as_str().trim().to_string()))
    }

    /// Mapping nesting depth; zero for non-mapping declarations.
    pub(crate) fn nesting_depth(&self) -> usize {
        self.key_chain().map_or(0, |keys| keys.len())
    }
}

/// ``address => mapping(address => uint256)`` -> ``([address, address], uint256)``.
///
/// Mirrors `storage_flow._flatten_mapping`.
fn flatten_mapping(inner: &str) -> (Vec<String>, String) {
    let split = match top_level_arrow(inner) {
        Some(split) => split,
        None => return (Vec::new(), inner.trim().to_string()),
    };
    let key = inner[..split].trim().to_string();
    let rest = inner[split + 2..].trim();
    if let Some(nested) = MAPPING_RE
        .captures(rest)
        .ok()
        .flatten()
        .and_then(|c| c.name("inner").map(|m| m.as_str().trim().to_string()))
    {
        let (mut keys, value) = flatten_mapping(&nested);
        keys.insert(0, key);
        return (keys, value);
    }
    (vec![key], rest.to_string())
}

/// Index of the first `=>` at parenthesis/angle-bracket depth zero.
///
/// Mirrors `storage_flow._top_level_arrow` (which counts `<`/`>` for generics).
fn top_level_arrow(text: &str) -> Option<usize> {
    let bytes = text.as_bytes();
    if text.is_empty() {
        return None;
    }
    let mut depth = 0i32;
    for i in 0..text.len() - 1 {
        match bytes[i] {
            b'(' | b'<' => depth += 1,
            b')' | b'>' => depth -= 1,
            _ => {}
        }
        if depth == 0 && bytes[i] == b'=' && bytes[i + 1] == b'>' {
            return Some(i);
        }
    }
    None
}

/// Canonical unification key: whitespace stripped, integer widths collapsed to
/// their signedness class. Mirrors `storage_flow.canonical_type`.
pub(crate) fn canonical_type(type_text: &str) -> String {
    let text = RE_ALL_WS.replace_all(type_text, "").to_string();
    let text = RE_UINT_CANON.replace_all(&text, "uint").to_string();
    RE_INT_CANON.replace_all(&text, "int").to_string()
}

/// A stub correlated with a storage mapping.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct GetterCandidate {
    pub function: String,
    /// Canonicalized parameter types.
    pub params: Vec<String>,
    pub param_names: Vec<String>,
    pub storage: String,
    pub key_chain: Vec<String>,
    pub value_type: String,
    pub slot: Option<String>,
    /// `exact` or `hinted`.
    pub evidence: &'static str,
    /// Unit span in the analyzed source, for consumers.
    pub start: usize,
    pub end: usize,
    pub header_len: usize,
}

/// The declarations/correlations result of the storage-flow analysis.
///
/// The Python `abstentions` records are an evaluation-JSON artifact and are
/// not part of the Rust surface.
#[derive(Debug, Clone, Default)]
pub(crate) struct StorageFlow {
    pub declarations: Vec<StorageDecl>,
    pub correlations: Vec<GetterCandidate>,
}

/// Contract-level state-variable declarations with their slot comments.
///
/// Line-structured scan, no cross-field regex: head token, then a paren-
/// balanced span for mappings, then modifiers, name and an optional
/// initializer, anchored at the `;`. Matching runs on the comment-masked
/// text; the mask is length-preserving, so the same offsets address the real
/// source - the slot comment is read from the real line because the mask
/// blanks comments. Mirrors `storage_flow.parse_storage_declarations`.
fn parse_storage_declarations(source: &str) -> Result<Vec<StorageDecl>, ParseError> {
    let masked = mask(source)?;
    let mut decls: Vec<StorageDecl> = Vec::new();
    for captures in RE_DECL_LINE.captures_iter(&masked).flatten() {
        let whole = match captures.get(0) {
            Some(m) => (m.start(), m.end()),
            None => continue,
        };
        let head = match captures.name("head") {
            Some(m) => m.as_str().to_string(),
            None => continue,
        };
        let head_end = captures.name("head").map(|m| m.end()).unwrap_or(whole.0);
        let rest = (
            captures.name("rest").map(|m| m.start()).unwrap_or(whole.1),
            captures.name("rest").map(|m| m.end()).unwrap_or(whole.1),
        );

        // (type_text, text after the type) per declaration shape
        let parsed = if head == "mapping" {
            mapping_decl_text(&masked, whole, rest)
        } else if RE_SCALAR_HEAD.is_match(&head).unwrap_or(false) {
            scalar_decl_text(&masked, whole, head_end, rest)
        } else {
            // not a state-variable type head (e.g. `function`, `event`)
            None
        };
        let (type_text, after) = match parsed {
            Some(parsed) => parsed,
            None => continue,
        };

        // the name is the last non-keyword identifier before `;` or `=`
        let before_eq = after.split('=').next().unwrap_or("");
        let mut names: Vec<String> =
            RE_IDENTIFIER.find_iter(before_eq).flatten().map(|m| m.as_str().to_string()).collect();
        names.retain(|name| !DECL_KEYWORDS.contains(&name.as_str()));
        let name = match names.pop() {
            Some(name) => name,
            None => continue,
        };
        let line_start = source[..whole.0].rfind('\n').map_or(0, |p| p + 1);
        let line_end = source[whole.1..].find('\n').map_or(source.len(), |p| whole.1 + p);
        let real_line = &source[line_start..line_end];
        let slot = SLOT_RE
            .captures(real_line)
            .ok()
            .flatten()
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().to_lowercase());
        let public = PUBLIC_RE.is_match(&after).unwrap_or(false) ||
            PUBLIC_RE.is_match(&head).unwrap_or(false);
        decls.push(StorageDecl { name, type_text, slot, public });
    }
    Ok(decls)
}

/// The `mapping(...)` declaration shape: paren-balanced type span.
fn mapping_decl_text(
    masked: &str,
    whole: (usize, usize),
    rest: (usize, usize),
) -> Option<(String, String)> {
    let rel_paren = masked[rest.0..rest.1].find('(')?;
    let abs_open = rest.0 + rel_paren;
    let bytes = masked.as_bytes();
    let (mut depth, mut abs_close) = (0i32, None);
    let mut i = abs_open;
    while i < masked.len() {
        match bytes[i] {
            b'(' => depth += 1,
            b')' => {
                depth -= 1;
                if depth == 0 {
                    abs_close = Some(i + 1);
                    break;
                }
            }
            _ => {}
        }
        i += 1;
    }
    let abs_close = abs_close?;
    let type_text = RE_SPACES.replace_all(&masked[whole.0..abs_close], " ").trim().to_string();
    Some((type_text, masked[abs_close..whole.1].to_string()))
}

/// The scalar/array declaration shape: head token plus array suffixes.
fn scalar_decl_text(
    masked: &str,
    whole: (usize, usize),
    head_end: usize,
    rest: (usize, usize),
) -> Option<(String, String)> {
    let suffix = RE_ARRAY_PREFIX
        .captures(&masked[rest.0..rest.1])
        .ok()
        .flatten()
        .and_then(|c| c.get(1))
        .map(|m| m.as_str().to_string())
        .unwrap_or_default();
    let after_start = (head_end + suffix.len()).min(whole.1);
    let head_text = masked[whole.0..head_end].trim();
    Some((format!("{head_text}{suffix}"), masked[after_start..whole.1].to_string()))
}

/// The `(type, name)` parameters of a unit header, location suffixes stripped.
///
/// Mirrors `storage_flow._function_params`.
fn function_params(masked_header: &str) -> Vec<(String, String)> {
    let inner = match header_param_span(masked_header) {
        Some(inner) => inner,
        None => return Vec::new(),
    };
    let mut params = Vec::new();
    for part in inner.split(',') {
        let mut tokens: Vec<&str> = part.split_whitespace().collect();
        if tokens.is_empty() {
            continue;
        }
        if matches!(tokens[0], "memory" | "calldata" | "storage") {
            tokens.remove(0);
        }
        if tokens.is_empty() {
            continue;
        }
        if tokens.len() > 1 {
            let name = tokens[tokens.len() - 1].to_string();
            let type_text = tokens[..tokens.len() - 1].join(" ");
            params.push((type_text, name));
        } else {
            params.push((tokens[0].to_string(), String::new()));
        }
    }
    params
}

/// `/// @param name ["t1", "t2"]` candidate lists from the unit's provenance.
///
/// Mirrors `storage_flow._param_type_hints`.
fn param_type_hints(unit_text: &str) -> BTreeMap<String, Vec<String>> {
    let mut hints = BTreeMap::new();
    for captures in RE_PARAM_HINT.captures_iter(unit_text).flatten() {
        let (name, list) = match (captures.get(1), captures.get(2)) {
            (Some(name), Some(list)) => (name.as_str().to_string(), list.as_str()),
            _ => continue,
        };
        let types: Vec<String> =
            RE_HINT_TYPE.find_iter(list).flatten().map(|m| m.as_str().to_string()).collect();
        if !types.is_empty() {
            hints.insert(name, types);
        }
    }
    hints
}

/// The declared return type of a unit header, location suffix dropped.
///
/// Mirrors `storage_flow._declared_returns`.
fn declared_returns(masked_header: &str) -> Option<String> {
    let captures = RE_RETURNS.captures(masked_header).ok()??;
    let inner = captures.get(1)?.as_str();
    let tokens: Vec<&str> = inner.split_whitespace().collect();
    match tokens.len() {
        0 => None,
        1 => Some(tokens[0].to_string()),
        _ => Some(tokens[..tokens.len() - 1].join(" ")),
    }
}

/// Correlate function stubs with slot-annotated mappings.
///
/// Mirrors `storage_flow.build_storage_flow`; the ambiguity bookkeeping of
/// the Python version is evaluation-JSON-only and is omitted.
pub(crate) fn build_storage_flow(source: &str) -> Result<StorageFlow, ParseError> {
    let declarations = parse_storage_declarations(source)?;
    let parsed = parse_contract(source, None)?;
    let mapping_decls: Vec<&StorageDecl> =
        declarations.iter().filter(|d| d.nesting_depth() > 0).collect();

    let mut correlations: Vec<GetterCandidate> = Vec::new();
    for unit in parsed.functions() {
        let unit_masked = mask(&unit.text)?;
        let split = unit.header.len().min(unit_masked.len());
        let header_masked = &unit_masked[..split];
        let params = function_params(header_masked);
        if params.is_empty() {
            continue;
        }
        let param_types: Vec<String> =
            params.iter().map(|(type_text, _)| canonical_type(type_text)).collect();
        let hints = param_type_hints(&unit.text);
        let returns = declared_returns(header_masked);
        let body_masked = &unit_masked[split..];
        if RE_RETURN_KW.is_match(body_masked).unwrap_or(false) {
            continue; // not a stub: a body with returns carries its own evidence
        }

        let ret_canon = returns.as_ref().map(|r| canonical_type(r));
        let mut matches: Vec<(&StorageDecl, &'static str)> = Vec::new();
        for decl in &mapping_decls {
            let Some(raw_keys) = decl.key_chain() else { continue };
            let keys: Vec<String> = raw_keys.iter().map(|k| canonical_type(k)).collect();
            if keys.len() != param_types.len() {
                continue;
            }
            let value = canonical_type(&decl.value_type().unwrap_or_default());
            if let Some(ret_canon) = &ret_canon {
                if ret_canon != &value {
                    continue;
                }
            }
            let mut exact = true;
            let mut hinted = true;
            for (index, (_type_text, name)) in params.iter().enumerate() {
                let param_canon = &param_types[index];
                let key_canon = &keys[index];
                if param_canon == key_canon {
                    continue;
                }
                exact = false; // any mismatch demotes the match from exact
                let hinted_types: BTreeMap<String, ()> = hints
                    .get(name)
                    .map(|types| types.iter().map(|t| (canonical_type(t), ())).collect())
                    .unwrap_or_default();
                if hinted_types.contains_key(param_canon) || hinted_types.contains_key(key_canon) {
                    continue;
                }
                // the decompiler's generic uintN default only bridges keys the
                // synthesis stage can convert (uint -> address via uint160)
                if RE_GENERIC_UINT.is_match(param_canon).unwrap_or(false) && key_canon == "address"
                {
                    continue;
                }
                hinted = false;
            }
            if exact || hinted {
                matches.push((decl, if exact { "exact" } else { "hinted" }));
            }
        }
        if matches.len() == 1 {
            let (decl, evidence) = matches[0];
            correlations.push(GetterCandidate {
                function: unit.name.clone(),
                params: param_types.clone(),
                param_names: params.iter().map(|(_, name)| name.clone()).collect(),
                storage: decl.name.clone(),
                key_chain: decl.key_chain().unwrap_or_default(),
                value_type: decl.value_type().unwrap_or_default(),
                slot: decl.slot.clone(),
                evidence,
                start: unit.start,
                end: unit.end,
                header_len: unit.header.len(),
            });
        }
    }
    Ok(StorageFlow { declarations, correlations })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_mapping_declarations_and_chains() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => mapping(address => uint256)) public m; // storage slot: 0x01\n",
            "    uint256 x; // storage slot: 0x02\n",
            "}\n",
        );
        let flow = build_storage_flow(source).unwrap();
        assert_eq!(flow.declarations.len(), 2);
        let m = &flow.declarations[0];
        assert_eq!(m.name, "m");
        assert_eq!(m.slot.as_deref(), Some("0x01"));
        assert!(m.public);
        assert_eq!(m.key_chain().unwrap(), vec!["address", "address"]);
        assert_eq!(m.value_type().as_deref(), Some("uint256"));
        assert_eq!(m.nesting_depth(), 2);
        assert_eq!(flow.declarations[1].nesting_depth(), 0);
    }

    #[test]
    fn canonical_type_collapses_widths_and_whitespace() {
        assert_eq!(canonical_type("uint256"), "uint");
        assert_eq!(canonical_type("uint8"), "uint");
        assert_eq!(canonical_type("int 128"), "int");
        assert_eq!(canonical_type("address"), "address");
        assert_eq!(canonical_type("mapping(address => uint256)"), "mapping(address=>uint)");
    }

    #[test]
    fn correlates_stub_getter_candidates() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => uint256) balances; // storage slot: 0x00\n",
            "    function balanceOf(address arg0) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n",
            "    }\n",
            "}\n",
        );
        let flow = build_storage_flow(source).unwrap();
        assert_eq!(flow.correlations.len(), 1);
        let c = &flow.correlations[0];
        assert_eq!(c.function, "balanceOf");
        assert_eq!(c.storage, "balances");
        assert_eq!(c.evidence, "exact");
        assert_eq!(c.key_chain, vec!["address"]);
    }

    #[test]
    fn skips_stubs_with_return_bodies() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => uint256) balances; // storage slot: 0x00\n",
            "    function f(address a) public view returns (uint256) { return balances[a]; }\n",
            "}\n",
        );
        let flow = build_storage_flow(source).unwrap();
        assert!(flow.correlations.is_empty());
    }
}
