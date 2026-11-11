//! Stage `placeholders`: rewrite placeholder width tokens.
//!
//! Port of `prepare_candidate.normalize_placeholders`: `uint0`/`int0`/
//! `bytes0` become their concrete types, outside comments and string
//! literals. Replacements are applied right-to-left within each token kind,
//! exactly as the Python stage does.

use crate::prepare::{
    parser::ParseError,
    stages::helpers::{collapse_whitespace, mask},
    Stage, StageEdit,
};

/// `(placeholder, concrete)` pairs, in application order.
const PLACEHOLDER_TYPES: [(&str, &str); 3] =
    [("uint0", "uint256"), ("int0", "int256"), ("bytes0", "bytes")];

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let mut masked = mask(source)?;
    let mut replacement = source.to_string();
    let mut edits = Vec::new();
    for (placeholder, concrete) in PLACEHOLDER_TYPES {
        let pattern =
            fancy_regex::Regex::new(&format!("(?<![A-Za-z0-9_]){placeholder}(?![A-Za-z0-9_])"))
                .expect("failed to build regex");
        let spans: Vec<(usize, usize)> =
            pattern.find_iter(&masked).flatten().map(|m| (m.start(), m.end())).collect();
        for (start, end) in spans.into_iter().rev() {
            replacement = format!("{}{concrete}{}", &replacement[..start], &replacement[end..]);
            masked = format!("{}{concrete}{}", &masked[..start], &masked[end..]);
            let window = &source[start.saturating_sub(48)..(end + 8).min(source.len())];
            edits.push(StageEdit {
                kind: "placeholder-type".to_string(),
                detail: format!("{placeholder} -> {concrete}"),
                evidence: collapse_whitespace(window),
            });
        }
    }
    Ok(Stage {
        name: "placeholders",
        description: "placeholder width tokens",
        source: replacement,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rewrites_code_tokens_only() {
        let source = concat!(
            "contract C {\n",
            "    function f(uint0 a, bytes0 b) public { string memory s = \"uint0\"; } // int0 note\n",
            "    uint0 x;\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert!(stage.source.contains("uint256 a, bytes b"));
        assert!(stage.source.contains("\"uint0\""));
        assert!(stage.source.contains("// int0 note"));
        assert!(stage.source.contains("uint256 x;"));
        let quoted: Vec<&str> = stage.source.split('"').collect();
        assert!(!quoted[2].contains("uint0 "));
        assert_eq!(stage.edits.len(), 3);
    }

    #[test]
    fn idempotent() {
        let source = "contract C { function f(uint256 a) public {} }\n";
        let once = run(source).unwrap();
        let again = run(&once.source).unwrap();
        assert_eq!(again.source, source);
        assert!(again.edits.is_empty());
    }

    #[test]
    fn keeps_identifier_suffixes() {
        // review regression: identifier tokens ending in `0` are not rewritten
        let source = "contract D { function mint0(uint256 x) public {} uint0 y; }\n";
        let stage = run(source).unwrap();
        assert!(stage.source.contains("function mint0(uint256 x)"));
        assert!(stage.source.contains("uint256 y;"));
    }
}
