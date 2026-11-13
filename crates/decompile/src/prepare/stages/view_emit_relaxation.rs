//! Stage `view-emit-relaxation`: drop `view` from view units that emit.
//!
//! Port of `prepare_candidate.view_emit_relaxation` (stuck-breaker trial 1
//! distillation, promoted at the 20-stage freeze): a `view` unit whose body
//! contains `emit` cannot compile (8961) - the decompiler derives mutability
//! from opcode traces but emits the event header anyway. The faithful
//! relaxation drops `view` (the recorded `mutability` stage only tightens
//! pure->view; this is the reverse direction). Unit spans come from the
//! parser; the modifier scan runs on the post-parameter header region only,
//! because the preceding `/// @custom:signature` comment may itself contain
//! the word `view`; the emit scan runs on the masked body so string content
//! cannot fake an emit.

use lazy_static::lazy_static;

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::mask,
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_VIEW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bview\b").expect("failed to build regex");
    static ref RE_EMIT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bemit\s+[A-Za-z_]").expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    // Python wraps the parse in try/except and abstains on failure
    let Ok(parsed) = parse_contract(source, None) else {
        return Ok(Stage {
            name: "view-emit-relaxation",
            description: "view/emit mutability relaxation",
            source: source.to_string(),
            edits: Vec::new(),
            findings: Vec::new(),
        });
    };

    let mut edits: Vec<StageEdit> = Vec::new();
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;
    for unit in parsed.functions() {
        let header = &unit.header;
        let Some(function_index) = header.find("function ") else {
            continue;
        };
        let Some(open_paren) = header[function_index..].find('(').map(|n| function_index + n)
        else {
            continue;
        };
        let mut depth = 0usize;
        let mut params_close: Option<usize> = None;
        for (index, byte) in header.bytes().enumerate().skip(open_paren) {
            match byte {
                b'(' => depth += 1,
                b')' => {
                    depth -= 1;
                    if depth == 0 {
                        params_close = Some(index);
                        break;
                    }
                }
                _ => {}
            }
        }
        let Some(params_close) = params_close else {
            continue;
        };
        let mods_full = &header[params_close + 1..];
        let mods = match mods_full.find('{') {
            Some(brace) => &mods_full[..brace],
            None => mods_full,
        };
        // the scan runs on the length-preserving masked tail so a trailing
        // comment's `view` cannot shadow the real modifier
        let mods_masked = mask(mods)?;
        let Some(view_match) = RE_VIEW.find(&mods_masked).expect("static regex") else {
            continue;
        };
        let body = &unit.text[header.len()..];
        let body_masked = mask(body)?;
        if !RE_EMIT.is_match(&body_masked).unwrap_or(false) {
            continue;
        }
        let view_start = unit.start + params_close + 1 + view_match.start();
        pieces.push(source[last..view_start].to_string());
        last = view_start + "view".len();
        edits.push(StageEdit {
            kind: "view-emit-relaxed".to_string(),
            detail: format!("{}: view dropped (body emits)", unit.name),
            evidence: "view unit containing emit; 8961".to_string(),
        });
    }
    if pieces.is_empty() {
        return Ok(Stage {
            name: "view-emit-relaxation",
            description: "view/emit mutability relaxation",
            source: source.to_string(),
            edits,
            findings: Vec::new(),
        });
    }
    pieces.push(source[last..].to_string());
    Ok(Stage {
        name: "view-emit-relaxation",
        description: "view/emit mutability relaxation",
        source: pieces.concat(),
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn drops_view_once_and_is_idempotent() {
        let source = concat!(
            "contract C {\n",
            "    event E(uint256 a);\n",
            "    uint256 s;\n",
            "    function f(uint256 a) public view returns (uint256) {\n",
            "        emit E(a);\n",
            "        return a;\n",
            "    }\n",
            "}\n",
        );
        let stage = run(source).expect("stage runs");
        assert_eq!(stage.edits.len(), 1);
        assert_eq!(stage.edits[0].kind, "view-emit-relaxed");
        assert!(stage.source.contains("function f(uint256 a) public  returns (uint256) {"));
        assert!(!stage.source.contains("public view"));
        let again = run(&stage.source).expect("stage runs");
        assert_eq!(again.source, stage.source);
        assert!(again.edits.is_empty());
    }

    #[test]
    fn header_comment_view_words_do_not_confuse_the_span() {
        // the `/// @custom:signature` comment above the unit contains `view`;
        // the scan must drop the real modifier, once, at its own span
        let source = concat!(
            "contract C {\n",
            "    event E(uint256 a);\n",
            "    /// @custom:signature   f(uint256 a) public view overview\n",
            "    function f(uint256 a) public view returns (uint256) {\n",
            "        emit E(a);\n",
            "        return a;\n",
            "    }\n",
            "}\n",
        );
        let stage = run(source).expect("stage runs");
        assert_eq!(stage.edits.len(), 1);
        assert!(stage.source.contains("public  returns (uint256) {"));
        assert!(stage.source.contains("public view overview"));
    }

    #[test]
    fn trailing_comment_view_does_not_shadow_the_modifier() {
        // reviewer: a comment between the parameter list and the modifiers may
        // contain `view`; the masked scan must drop the REAL modifier
        let source = concat!(
            "contract C {\n",
            "    event E(uint256 a);\n",
            "    function f(uint256 a) public /* see view docs */ view returns (uint256) {\n",
            "        emit E(a);\n",
            "        return a;\n",
            "    }\n",
            "}\n",
        );
        let stage = run(source).expect("stage runs");
        assert_eq!(stage.edits.len(), 1);
        assert!(stage.source.contains("public /* see view docs */  returns (uint256) {"));
        let again = run(&stage.source).expect("stage runs");
        assert_eq!(again.source, stage.source);
    }

    #[test]
    fn string_emit_is_not_an_emit() {
        // `emit` appears only inside a string literal: masked body scan, no edit
        let source = concat!(
            "contract C {\n",
            "    function f() public view returns (string memory) {\n",
            "        return \"emit E(1);\";\n",
            "    }\n",
            "}\n",
        );
        let stage = run(source).expect("stage runs");
        assert!(stage.edits.is_empty());
        assert_eq!(stage.source, source);
    }

    #[test]
    fn noop_without_view_or_without_emit() {
        let emitter = concat!(
            "contract C {\n",
            "    event E();\n",
            "    function f() public {\n",
            "        emit E();\n",
            "    }\n",
            "}\n",
        );
        assert!(run(emitter).expect("stage runs").edits.is_empty());
        let viewer = "contract C { function f() public view returns (uint256) { return 1; } }\n";
        let staged = run(viewer).expect("stage runs");
        assert!(staged.edits.is_empty());
        assert_eq!(staged.source, viewer);
    }
}
