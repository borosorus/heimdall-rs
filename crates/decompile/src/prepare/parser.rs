//! Scanner and contract parser for decompiled Solidity sources.
//!
//! Rust port of the parsing core of `evaluation/scripts/run_investigator.py`
//! (the `SourceUnit`/`ParsedSource` model, comment/string-aware scanning, and
//! `parse_contract`), restricted to what the preparation stages consume: unit
//! classification, spans, headers, and the contract body bounds. The per-unit
//! dependency computation of the Python module is omitted; no stage reads it.
//!
//! All offsets are byte offsets into the analyzed source. Scanners are
//! ASCII-aware and every returned position lies on a UTF-8 character boundary,
//! so spans compose safely with `str` slicing and regex matches.

use lazy_static::lazy_static;

/// A scanning or parsing failure, with the Python port's message text.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub(crate) struct ParseError(pub String);

/// The kind of a top-level contract unit.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum UnitKind {
    Function,
    Constructor,
    Fallback,
    Receive,
    Modifier,
    Declaration,
}

impl UnitKind {
    /// The identifier for this kind, mirroring the Python parser's kind string.
    pub(crate) fn as_str(&self) -> &'static str {
        match self {
            UnitKind::Function => "function",
            UnitKind::Constructor => "constructor",
            UnitKind::Fallback => "fallback",
            UnitKind::Receive => "receive",
            UnitKind::Modifier => "modifier",
            UnitKind::Declaration => "declaration",
        }
    }
}

/// A single top-level unit of the contract body.
///
/// `text` is `source[start..end]` and `header` is the declaration header
/// (everything before the unit's opening brace, trimmed); both are stored
/// verbatim to mirror the Python `SourceUnit`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct SourceUnit {
    pub kind: UnitKind,
    pub name: String,
    pub header: String,
    pub start: usize,
    pub end: usize,
    pub text: String,
}

/// The parse result for the contract under preparation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ParsedSource {
    pub contract_name: String,
    /// Offset just past the contract body's opening brace.
    pub body_start: usize,
    /// Offset of the contract body's closing brace.
    pub body_end: usize,
    pub units: Vec<SourceUnit>,
}

impl ParsedSource {
    /// The contract's state and declaration units, in source order.
    pub(crate) fn declarations(&self) -> impl Iterator<Item = &SourceUnit> {
        self.units.iter().filter(|u| matches!(u.kind, UnitKind::Declaration))
    }

    /// The contract's function units, in source order.
    pub(crate) fn functions(&self) -> impl Iterator<Item = &SourceUnit> {
        self.units.iter().filter(|u| matches!(u.kind, UnitKind::Function))
    }
}

lazy_static! {
    static ref RE_FUNCTION_KW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bfunction\b").expect("failed to build regex");
    static ref RE_FUNCTION_NAME: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bfunction\s+([A-Za-z_]\w*)\s*\(")
            .expect("failed to build regex");
    static ref RE_CONSTRUCTOR_KW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bconstructor\b").expect("failed to build regex");
    static ref RE_FALLBACK_KW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bfallback\b").expect("failed to build regex");
    static ref RE_RECEIVE_KW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\breceive\b").expect("failed to build regex");
    static ref RE_MODIFIER_KW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bmodifier\b").expect("failed to build regex");
    static ref RE_CONTRACT_NAME: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bcontract\s+([A-Za-z_]\w*)").expect("failed to build regex");
}

/// Python `str.isspace()` restricted to the ASCII range, for the scanners.
///
/// Generated Solidity is ASCII; non-ASCII whitespace is treated as a token
/// character (a documented, benign divergence from the Python port).
pub(crate) fn is_space(b: u8) -> bool {
    matches!(b, b' ' | b'\t' | b'\n' | b'\r' | b'\x0b' | b'\x0c')
}

/// Advances `index` past one (possibly multibyte) character, so later
/// `source[index..]` slices stay on char boundaries.
fn advance(source: &str, index: usize) -> usize {
    let mut next = index + 1;
    while next < source.len() && !source.is_char_boundary(next) {
        next += 1;
    }
    next
}

/// Returns the offset just past a string literal starting at `index`.
///
/// Mirrors `run_investigator._skip_string`.
pub(crate) fn skip_string(source: &str, index: usize) -> Result<usize, ParseError> {
    let bytes = source.as_bytes();
    let quote = bytes[index];
    let mut index = index + 1;
    while index < bytes.len() {
        if bytes[index] == b'\\' {
            index += 2;
            continue;
        }
        if bytes[index] == quote {
            return Ok(index + 1);
        }
        index += 1;
    }
    Err(ParseError("unterminated string literal".to_string()))
}

/// Returns the offset just past a comment starting at `index`.
///
/// Mirrors `run_investigator._skip_comment`; a non-comment position is
/// returned unchanged.
pub(crate) fn skip_comment(source: &str, index: usize) -> Result<usize, ParseError> {
    if source[index..].starts_with("//") {
        let end = source[index + 2..].find('\n').map(|rel| index + 2 + rel).unwrap_or(source.len());
        return Ok(if end >= source.len() { source.len() } else { end + 1 });
    }
    if source[index..].starts_with("/*") {
        return match source[index + 2..].find("*/") {
            Some(rel) => Ok(index + 2 + rel + 2),
            None => Err(ParseError("unterminated block comment".to_string())),
        };
    }
    Ok(index)
}

/// The kind of boundary found by [`find_next_structural`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Structural {
    Declaration,
    Block,
    End,
}

/// Finds the next structural boundary at or after `index`.
///
/// Mirrors `run_investigator._find_next_structural`: whitespace, comments, and
/// string literals are skipped; a `;` ends a declaration, a matched `{...}`
/// ends a block unit, and a bare `}` ends the enclosing body.
fn find_next_structural(
    source: &str,
    mut index: usize,
    end: usize,
) -> Result<(Structural, usize), ParseError> {
    let bytes = source.as_bytes();
    while index < end {
        let b = bytes[index];
        if is_space(b) {
            index += 1;
        } else if source[index..].starts_with("//") || source[index..].starts_with("/*") {
            index = skip_comment(source, index)?;
        } else if b == b'"' || b == b'\'' {
            index = skip_string(source, index)?;
        } else if b == b';' {
            return Ok((Structural::Declaration, index + 1));
        } else if b == b'{' {
            let close = find_matching_brace(source, index)?;
            return Ok((Structural::Block, close + 1));
        } else if b == b'}' {
            return Ok((Structural::End, index));
        } else {
            index = advance(source, index);
        }
    }
    Ok((Structural::End, end))
}

/// Returns the offset of the `}` matching the `{` at `open_index`.
///
/// Mirrors `run_investigator._find_matching_brace`.
pub(crate) fn find_matching_brace(source: &str, open_index: usize) -> Result<usize, ParseError> {
    let bytes = source.as_bytes();
    if bytes.get(open_index) != Some(&b'{') {
        return Err(ParseError("expected opening brace".to_string()));
    }
    let mut depth = 1usize;
    let mut index = open_index + 1;
    while index < bytes.len() {
        let b = bytes[index];
        if source[index..].starts_with("//") || source[index..].starts_with("/*") {
            index = skip_comment(source, index)?;
        } else if b == b'"' || b == b'\'' {
            index = skip_string(source, index)?;
        } else if b == b'{' {
            depth += 1;
            index += 1;
        } else if b == b'}' {
            depth -= 1;
            if depth == 0 {
                return Ok(index);
            }
            index += 1;
        } else {
            index = advance(source, index);
        }
    }
    Err(ParseError("unmatched closing brace".to_string()))
}

/// Finds the next occurrence of `target` at or after `index`, before `end`,
/// skipping comments and string literals. `None` mirrors the Python helper's
/// `-1` sentinel.
fn find_next_char(
    source: &str,
    mut index: usize,
    target: u8,
    end: usize,
) -> Result<Option<usize>, ParseError> {
    let bytes = source.as_bytes();
    while index < end {
        let b = bytes[index];
        if source[index..].starts_with("//") || source[index..].starts_with("/*") {
            index = skip_comment(source, index)?;
        } else if b == b'"' || b == b'\'' {
            index = skip_string(source, index)?;
        } else if b == target {
            return Ok(Some(index));
        } else {
            index = advance(source, index);
        }
    }
    Ok(None)
}

/// Blanks string literals and comments with spaces, preserving length and
/// newlines, over `source[start..end]`. Mirrors
/// `run_investigator._mask_strings_and_comments`.
pub(crate) fn mask_strings_and_comments(
    source: &str,
    start: usize,
    end: usize,
) -> Result<String, ParseError> {
    let bytes = source.as_bytes();
    let mut out = bytes[start..end].to_vec();
    let mut index = start;
    while index < end {
        let b = bytes[index];
        if source[index..].starts_with("//") || source[index..].starts_with("/*") {
            let stop = skip_comment(source, index)?;
            for position in index..stop.min(end) {
                if out[position - start] != b'\n' {
                    out[position - start] = b' ';
                }
            }
            index = stop;
        } else if b == b'"' || b == b'\'' {
            let stop = skip_string(source, index)?;
            for position in index..stop.min(end) {
                out[position - start] = b' ';
            }
            index = stop;
        } else {
            index = advance(source, index);
        }
    }
    Ok(String::from_utf8(out).unwrap_or_default())
}

/// Classifies a unit header, mirroring `run_investigator._unit_kind`.
fn unit_kind(header: &str) -> Result<(UnitKind, String), ParseError> {
    let masked = mask_strings_and_comments(header, 0, header.len())?;
    if RE_FUNCTION_KW.is_match(&masked).unwrap_or(false) {
        let name = RE_FUNCTION_NAME
            .captures(&masked)
            .unwrap_or(None)
            .and_then(|c| c.get(1).map(|m| m.as_str().to_string()));
        return match name {
            Some(name) => Ok((UnitKind::Function, name)),
            None => Err(ParseError("function header has no function name".to_string())),
        };
    }
    if RE_CONSTRUCTOR_KW.is_match(&masked).unwrap_or(false) {
        return Ok((UnitKind::Constructor, UnitKind::Constructor.as_str().to_string()));
    }
    if RE_FALLBACK_KW.is_match(&masked).unwrap_or(false) {
        return Ok((UnitKind::Fallback, UnitKind::Fallback.as_str().to_string()));
    }
    if RE_RECEIVE_KW.is_match(&masked).unwrap_or(false) {
        return Ok((UnitKind::Receive, UnitKind::Receive.as_str().to_string()));
    }
    if RE_MODIFIER_KW.is_match(&masked).unwrap_or(false) {
        return Ok((UnitKind::Modifier, UnitKind::Modifier.as_str().to_string()));
    }
    Ok((UnitKind::Declaration, String::new()))
}

/// Collect the contract-body units between `start` and `end`.
///
/// Mirrors `run_investigator._parse_units`.
fn parse_units(source: &str, start: usize, end: usize) -> Result<Vec<SourceUnit>, ParseError> {
    let mut units = Vec::new();
    let mut position = start;
    while position < end {
        let bytes = source.as_bytes();
        let mut next_position = position;
        while next_position < end && is_space(bytes[next_position]) {
            next_position += 1;
        }
        if next_position >= end {
            break;
        }
        position = next_position;
        let (structural, stop) = find_next_structural(source, position, end)?;
        if structural == Structural::End {
            break;
        }
        let text = source[position..stop].to_string();
        if structural == Structural::Declaration {
            let header = text.trim().to_string();
            let (kind, name) = unit_kind(&header)?;
            if kind == UnitKind::Declaration {
                units.push(SourceUnit { kind, name, header, start: position, end: stop, text });
            } else {
                return Err(ParseError("callable unit ended without a body".to_string()));
            }
        } else {
            let brace = find_next_char(source, position, b'{', stop)?;
            let brace = match brace {
                Some(brace) => brace,
                None => return Err(ParseError("block unit has no opening brace".to_string())),
            };
            let header = source[position..brace].trim().to_string();
            let (kind, name) = unit_kind(&header)?;
            units.push(SourceUnit { kind, name, header, start: position, end: stop, text });
        }
        position = stop;
    }
    Ok(units)
}

/// Locate contract bodies by name, mirroring `run_investigator._find_contract`.
///
/// Without `contract_name`, the candidate with the most functions wins; ties
/// keep the first (Python `max` semantics).
fn find_contract(
    source: &str,
    contract_name: Option<&str>,
) -> Result<(String, usize, usize, Vec<SourceUnit>), ParseError> {
    let masked = mask_strings_and_comments(source, 0, source.len())?;
    let mut candidates: Vec<(String, usize, usize, Vec<SourceUnit>)> = Vec::new();
    for captures in RE_CONTRACT_NAME.captures_iter(&masked).flatten() {
        let name = match captures.get(1) {
            Some(m) => m.as_str().to_string(),
            None => continue,
        };
        if let Some(want) = contract_name {
            if name != want {
                continue;
            }
        }
        let search_from = captures.get(0).map(|m| m.end()).unwrap_or(0);
        let brace = match find_next_char(source, search_from, b'{', source.len())? {
            Some(brace) => brace,
            None => return Err(ParseError(format!("contract {name} has no body"))),
        };
        let close = find_matching_brace(source, brace)?;
        let units = parse_units(source, brace + 1, close)?;
        candidates.push((name, brace + 1, close, units));
    }
    if contract_name.is_some() {
        return candidates.into_iter().next().ok_or_else(|| {
            ParseError(format!("contract {} not found", contract_name.unwrap_or("<auto>")))
        });
    }
    let mut best: Option<(String, usize, usize, Vec<SourceUnit>)> = None;
    let mut best_count = 0usize;
    for (name, body_start, body_end, units) in candidates {
        let count = units.iter().filter(|u| matches!(u.kind, UnitKind::Function)).count();
        if best.is_none() || count > best_count {
            best_count = count;
            best = Some((name, body_start, body_end, units));
        }
    }
    best.ok_or_else(|| ParseError("contract <auto> not found".to_string()))
}

/// The comma-separated parameter list of a `function name(...)` header.
///
/// Paren-balanced on the comment-masked text; `None` when no declaration or an
/// unbalanced list is present. Mirrors `run_investigator.header_param_span`.
pub(crate) fn header_param_span(masked_header: &str) -> Option<String> {
    let caps = RE_FUNCTION_NAME.captures(masked_header).ok()??;
    let start = caps.get(0)?.end();
    let bytes = masked_header.as_bytes();
    let mut depth = 1usize;
    let mut index = start;
    while index < bytes.len() && depth > 0 {
        match bytes[index] {
            b'(' => depth += 1,
            b')' => depth -= 1,
            _ => {}
        }
        index += 1;
    }
    if depth != 0 {
        return None;
    }
    Some(masked_header[start..index - 1].to_string())
}

/// Parses the (single) contract of a decompiled source.
///
/// Mirrors `run_investigator.parse_contract` minus per-unit dependency
/// computation, which no preparation stage consumes.
pub(crate) fn parse_contract(
    source: &str,
    contract_name: Option<&str>,
) -> Result<ParsedSource, ParseError> {
    let (name, body_start, body_end, units) = find_contract(source, contract_name)?;
    Ok(ParsedSource { contract_name: name, body_start, body_end, units })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn masks_comments_and_strings() {
        let source = "contract C { string s = \"a;b\"; uint x; } // note; here\nuint y;\n";
        let masked = mask_strings_and_comments(source, 0, source.len()).unwrap();
        assert_eq!(masked.len(), source.len());
        // structural characters inside strings and comments are blanked
        assert!(masked.contains("uint x; } "));
        assert!(masked.contains("uint y;"));
        assert_eq!(masked.matches('\n').count(), 2);
    }

    #[test]
    fn mask_preserves_length_with_multibyte_content() {
        let source = "contract C { string s = \"éü\"; } // naïve\n";
        let masked = mask_strings_and_comments(source, 0, source.len()).unwrap();
        assert_eq!(masked.len(), source.len());
        assert_eq!(masked.matches('\n').count(), 1);
        // code outside comments/strings survives verbatim
        assert!(masked.contains("contract C "));
    }

    #[test]
    fn parses_contract_units_and_spans() {
        let source = concat!(
            "// header comment\n",
            "contract C {\n",
            "    uint256 a; // trailing\n",
            "    function f(uint256 x) public pure returns (uint256) { return x; }\n",
            "}\n",
        );
        let parsed = parse_contract(source, None).unwrap();
        assert_eq!(parsed.contract_name, "C");
        let functions: Vec<_> = parsed.functions().collect();
        assert_eq!(functions.len(), 1);
        assert_eq!(functions[0].name, "f");
        assert_eq!(&source[functions[0].start..functions[0].end], functions[0].text);
        // the unit span opens at the comment preceding the declaration, as in
        // the Python parser; the header is everything before the brace
        assert!(functions[0]
            .header
            .contains("function f(uint256 x) public pure returns (uint256)"));
        let declarations: Vec<_> = parsed.declarations().collect();
        assert_eq!(declarations.len(), 1);
        assert_eq!(declarations[0].header, "uint256 a;");
    }

    #[test]
    fn header_param_span_extracts_parameters() {
        let masked = "function f(uint256 a, mapping(address => uint256) m) public";
        assert_eq!(
            header_param_span(masked).as_deref(),
            Some("uint256 a, mapping(address => uint256) m")
        );
        assert_eq!(header_param_span("function empty() public"), Some(String::new()));
        assert_eq!(header_param_span("fallback() external"), None);
        assert_eq!(header_param_span("uint256 x;"), None);
    }

    #[test]
    fn multibyte_outside_comments_and_strings_does_not_panic() {
        // non-ASCII identifiers are legal Solidity; the byte scanners must
        // advance char-wise and never slice mid-character
        let source =
            "contract C { uint v\u{e9}rit\u{e9}; function f() public pure returns (uint256) { return v\u{e9}rit\u{e9}; } }\n";
        let masked = mask_strings_and_comments(source, 0, source.len()).unwrap();
        assert_eq!(masked.len(), source.len());
        let parsed = parse_contract(source, None).unwrap();
        assert_eq!(parsed.contract_name, "C");
        assert_eq!(parsed.functions().count(), 1);
        assert_eq!(parsed.declarations().count(), 1);
        let prepared = crate::prepare::prepare(source).unwrap();
        assert_eq!(prepared.source, source);
    }

    #[test]
    fn parse_errors_are_reported() {
        let err = parse_contract("contract C {", None).unwrap_err();
        assert_eq!(err.to_string(), "unmatched closing brace");
        let err = parse_contract("nothing here", None).unwrap_err();
        assert!(err.to_string().contains("not found"));
    }

    #[test]
    fn picks_first_contract_on_function_count_tie() {
        let source =
            "contract A { function f() public {} }\ncontract B { function g() public {} }\n";
        let parsed = parse_contract(source, None).unwrap();
        assert_eq!(parsed.contract_name, "A");
        let parsed = parse_contract(source, Some("B")).unwrap();
        assert_eq!(parsed.contract_name, "B");
    }
}
