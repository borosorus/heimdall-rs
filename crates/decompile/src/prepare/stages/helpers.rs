//! Helpers shared by the preparation stages.
//!
//! Each item is a mechanical port of the same-named Python helper in
//! `evaluation/scripts/prepare_candidate.py`; the anchored regexes mirror the
//! Python `re.fullmatch`/`re.match` call sites and are anchored accordingly.

use lazy_static::lazy_static;

use crate::prepare::parser::{header_param_span, mask_strings_and_comments, ParseError};

lazy_static! {
    /// Collapses whitespace runs; mirrors `re.sub(r"\s+", " ", text)`.
    pub static ref WHITESPACE_RUN: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\s+").expect("failed to build regex");
    /// Numeric-literal class; mirrors `re.fullmatch(r"0x[0-9a-fA-F]+|\d+(\.\d+)?e?\d*|\d+", s)`.
    pub static ref RE_LITERAL: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^(?:0x[0-9a-fA-F]+|\d+(?:\.\d+)?e?\d*|\d+)$").expect("failed to build regex");
    /// Bare-identifier class; mirrors `re.fullmatch(r"[A-Za-z_]\w*", s)`.
    pub static ref RE_IDENTIFIER: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^[A-Za-z_]\w*$").expect("failed to build regex");
    /// `var_*` state-name class; mirrors `re.fullmatch(r"var_[a-z]+", s)` (via `re.match`).
    pub static ref RE_VAR_NAME: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^var_[a-z]+$").expect("failed to build regex");
    /// State-declaration prefix; mirrors `re.match(r"^(address|uint\d+|...)...", header)`.
    pub static ref RE_STATE_DECL: fancy_regex::Regex = fancy_regex::Regex::new(
        r"^(address|uint\d+|int\d+|bytes\d+|bytes|string|bool)\s+([A-Za-z_]\w*)\s*(?:=|;)",
    )
    .expect("failed to build regex");
}

/// A function header's `(type, name)` parameter pairs.
///
/// Mirrors `prepare_candidate._header_params`: the paren-balanced span of the
/// comment-masked header, split on top-level commas; the last word of each
/// entry is the name (empty when the parameter is unnamed).
pub(crate) fn header_params(masked_header: &str) -> Vec<(String, String)> {
    let inner = match header_param_span(masked_header) {
        Some(inner) => inner,
        None => return Vec::new(),
    };
    let mut params = Vec::new();
    for part in inner.split(',') {
        let words: Vec<&str> = part.split_whitespace().collect();
        if words.is_empty() {
            continue;
        }
        if words.len() > 1 {
            params.push((words[..words.len() - 1].join(" "), words[words.len() - 1].to_string()));
        } else {
            params.push((words[0].to_string(), String::new()));
        }
    }
    params
}

/// Masks comments and strings over the whole input; helper for stage code.
pub(crate) fn mask(source: &str) -> Result<String, ParseError> {
    mask_strings_and_comments(source, 0, source.len())
}

/// Offset past the end of the line containing `body_start`.
///
/// Mirrors `prepare_candidate._body_open_line_end`.
pub(crate) fn body_open_line_end(source: &str, body_start: usize) -> usize {
    let from = body_start.saturating_sub(1);
    match source[from..].find('\n') {
        Some(rel) => from + rel + 1,
        None => source.len(),
    }
}

/// The `(type, name)` of a state-declaration header prefix, mirroring the
/// Python `re.match(r"^(address|...)...")` check (`None` when it does not
/// prefix-match).
pub(crate) fn state_declaration_match(header: &str) -> Option<(String, String)> {
    let captures = RE_STATE_DECL.captures(header).ok()??;
    Some((captures.get(1)?.as_str().to_string(), captures.get(2)?.as_str().to_string()))
}

/// Collapses whitespace runs to single spaces and trims, mirroring
/// `re.sub(r"\s+", " ", text).strip()`; used for edit evidence excerpts.
pub(crate) fn collapse_whitespace(text: &str) -> String {
    WHITESPACE_RUN.replace_all(text, " ").trim().to_string()
}
