//! Stage `fallback-shape`: make decompiled fallback dispatch compile.
//!
//! Port of `prepare_candidate.repair_fallback_shape`. Two shapes, both
//! accepted only where unambiguous: the selector self-check `<int const> ==
//! msg.data[0] >> 0xe0` becomes a words-wide selector compare, and a
//! value-returning fallback gains `returns (bytes memory)` with an
//! ABI-canonical `abi.encode` return (packed length differs from ABI encoding
//! for address and dynamic members; sealed modern-block-reader divergence).

use lazy_static::lazy_static;

use crate::prepare::{parser::ParseError, Stage, StageEdit};

lazy_static! {
    static ref RE_FALLBACK_HEADER: fancy_regex::Regex =
        fancy_regex::Regex::new(r"fallback\(\)\s*external\s*payable")
            .expect("failed to build regex");
    static ref RE_SELECTOR_CHECK: fancy_regex::Regex =
        fancy_regex::Regex::new(r"require\((0x[0-9a-fA-F]+) == msg\.data\[0\] >> 0xe0\)",)
            .expect("failed to build regex");
    static ref RE_PACKED_RETURN: fancy_regex::Regex =
        fancy_regex::Regex::new(r"return\s+abi\.encodePacked\(").expect("failed to build regex");
    static ref RE_PACKED_CALL: fancy_regex::Regex =
        fancy_regex::Regex::new(r"return abi\.encodePacked\(").expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let mut edits: Vec<StageEdit> = Vec::new();
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;

    for captures in RE_FALLBACK_HEADER.find_iter(source).flatten() {
        let (start, header_end) = (captures.start(), captures.end());
        let body_open = match source[header_end..].find('{') {
            Some(rel) => header_end + rel,
            None => continue,
        };
        // raw brace scan, exactly as the Python stage does
        let mut depth = 0usize;
        let mut end = None;
        let bytes = source.as_bytes();
        let mut index = body_open;
        while index < bytes.len() {
            match bytes[index] {
                b'{' => depth += 1,
                b'}' => {
                    depth -= 1;
                    if depth == 0 {
                        end = Some(index + 1);
                        break;
                    }
                }
                _ => {}
            }
            index += 1;
        }
        let end = match end {
            Some(end) => end,
            None => continue,
        };
        let text = &source[start..end];
        let header = captures.as_str().to_string();

        // selector self-check -> words-wide compare (capture-based splice)
        let mut new_text = String::new();
        let mut selector_edits = 0usize;
        let mut consumed = 0usize;
        for check in RE_SELECTOR_CHECK.captures_iter(text).flatten() {
            let whole = check.get(0).expect("whole match");
            let constant = check.get(1).map(|m| m.as_str()).unwrap_or_default();
            new_text.push_str(&text[consumed..whole.start()]);
            new_text.push_str(&format!("require(uint32(bytes4(msg.data[0:4])) == {constant})"));
            consumed = whole.end();
            selector_edits += 1;
        }
        new_text.push_str(&text[consumed..]);

        let added_returns =
            !header.contains("returns") && RE_PACKED_RETURN.is_match(&new_text).unwrap_or(false);
        if added_returns {
            // solc 5570: a value-returning fallback must take the calldata argument
            new_text = new_text.replacen(
                &header,
                "fallback(bytes calldata) external payable returns (bytes memory)",
                1,
            );
            // ABI-canonical encoding for the bytes-memory return: the packed
            // form loses the ABI wrapper for address/dynamic members; the
            // harness revalidation is the per-fixture gate
            new_text = RE_PACKED_CALL.replace_all(&new_text, "return abi.encode(").to_string();
        }
        if new_text == text {
            continue;
        }
        // a later phrase match may start inside the span already consumed by
        // the previous fallback's body; Python's oversize slice is empty
        if start >= last {
            pieces.push(source[last..start].to_string());
        }
        pieces.push(new_text);
        last = end;
        if selector_edits > 0 {
            edits.push(StageEdit {
                kind: "fallback-selector-compare".to_string(),
                detail: "bytes/int compare -> words selector compare".to_string(),
                evidence: "single-dispatch fallback selector check".to_string(),
            });
        }
        if added_returns {
            edits.push(StageEdit {
                kind: "fallback-returns".to_string(),
                detail: "fallback gains returns (bytes memory)".to_string(),
                evidence: "value-returning fallback".to_string(),
            });
        }
    }

    let staged = if pieces.is_empty() {
        source.to_string()
    } else {
        pieces.push(source[last..].to_string());
        pieces.concat()
    };
    Ok(Stage {
        name: "fallback-shape",
        description: "fallback dispatch shape",
        source: staged,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn fallback_selector_check_and_return_shape() {
        let source = concat!(
            "contract C {\n",
            "    fallback() external payable {\n",
            "        require(msg.data.length >= 0x04);\n",
            "        require(0x819439 == msg.data[0] >> 0xe0);\n",
            "        return abi.encodePacked(block.number, block.timestamp);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("fallback(bytes calldata) external payable returns (bytes memory)"));
        assert!(staged.contains("require(uint32(bytes4(msg.data[0:4])) == 0x819439);"));
    }

    #[test]
    fn fallback_value_return_encodes_not_packs() {
        let source = concat!(
            "contract C {\n",
            "    fallback() external payable {\n",
            "        require(msg.data.length >= 0x04);\n",
            "        require(0x819439 == msg.data[0] >> 0xe0);\n",
            "        return abi.encodePacked(block.number, address(block.coinbase));\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("fallback(bytes calldata) external payable returns (bytes memory)"));
        assert!(staged.contains("return abi.encode(block.number, address(block.coinbase));"));
        assert!(!staged.contains("abi.encodePacked"));
    }

    #[test]
    fn fallback_without_return_value_is_untouched() {
        let source = concat!(
            "contract C {\n",
            "    event Done();\n",
            "    fallback() external payable {\n",
            "        emit Done();\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("fallback() external payable {"));
    }
}
