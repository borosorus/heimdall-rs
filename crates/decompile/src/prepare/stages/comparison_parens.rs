//! Stage `comparison-parens`: parenthesize comparisons under bitwise operators.
//!
//! Port of `prepare_candidate.comparison_parens` (stuck-breaker trial 1
//! distillation, promoted at the 20-stage freeze): solc binds `==`/`<`..`
//! tighter than `|`/`&`/`^`, so the decompiler's linear `a == b | c == d`
//! parses as `(a == (b|c)) == d` - bool vs uint (2271). The decompiler's
//! intent, confirmed behaviorally (stuck1-v1: 7/10+5/5), is the left-to-right
//! reading `(a == b) | (c == d)`; making the intended precedence explicit is
//! semantics-preserving by construction.
//!
//! Gate shape: the lhs of the bitwise op must already end a parenthesized
//! group (`...) op lhs cmp ...`); the rhs comparison is wrapped through its
//! extent at condition depth. Detection runs on the length-preserving masked
//! copy (string/comment content cannot confuse the depth scan); the emitted
//! replacement slices the ORIGINAL source so literals survive verbatim. A
//! match whose span a previous one-span replacement consumed is skipped; the
//! residual inner chain of a multi-link condition wraps on a later pipeline
//! pass to the same fixpoint the Python reference reaches.

use lazy_static::lazy_static;

use crate::prepare::{parser::ParseError, stages::helpers::mask, Stage, StageEdit};

lazy_static! {
    static ref RE_CMP: fancy_regex::Regex =
        fancy_regex::Regex::new(r"==|!=|<=|>=|<|>").expect("failed to build regex");
    static ref RE_BITWISE_TAIL: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?P<op>[|^&])\s+(?P<lhs>[A-Za-z_][A-Za-z0-9_.]*)\s*(?P<cmp>==|!=|<=|>=|<|>)\s",
    )
    .expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    let bytes = masked.as_bytes();
    let mut edits: Vec<StageEdit> = Vec::new();
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;
    for captures in RE_BITWISE_TAIL.captures_iter(&masked).flatten() {
        let op = captures.name("op").expect("op").as_str().to_string();
        let op_start = captures.name("op").expect("op").start();
        if op_start < last {
            // a previous one-span replacement consumed this match (it sat
            // inside the wrapped rhs); its text is already in the emitted group
            continue;
        }
        let lhs = captures.name("lhs").expect("lhs");
        let cmp = captures.name("cmp").expect("cmp");
        // the rhs comparison extends to a `,`/`;` or the closing paren at the
        // depth where the comparison itself lives
        let rhs_start = lhs.start();
        let mut depth = 0usize;
        let mut rhs_end: Option<usize> = None;
        let mut index = cmp.start();
        while index < masked.len() {
            match bytes[index] {
                b'(' | b'[' => depth += 1,
                b')' | b']' => {
                    if depth == 0 {
                        rhs_end = Some(index);
                        break;
                    }
                    depth -= 1;
                }
                b',' | b';' => {
                    // condition args end at `,`; for-header clauses at `;`
                    if depth == 0 {
                        rhs_end = Some(index);
                        break;
                    }
                }
                _ => {}
            }
            index += 1;
        }
        let Some(rhs_end) = rhs_end else { continue };
        let rhs_masked = masked[rhs_start..rhs_end].trim();
        if RE_CMP.find(rhs_masked).ok().flatten().is_none() || rhs_masked.starts_with('(') {
            continue;
        }
        // one-span replacement [op .. rhs_end): the op doubles when the lhs is
        // itself a parenthesized group (comparison|comparison -> comparisons
        // joined logically; 0.8 refuses bool|bool), and the rhs comparison is
        // wrapped - explicit precedence, the decompiler's linear reading.
        // Boundaries and the shape check come from the masked copy; the
        // emitted text is the original source slice so literals survive.
        let before = masked[..op_start].trim_end();
        let doubled = if before.ends_with(')') && (op == "|" || op == "&") {
            format!("{op}{op}")
        } else {
            op.clone()
        };
        pieces.push(source[last..op_start].to_string());
        pieces.push(format!("{doubled} ({})", source[rhs_start..rhs_end].trim()));
        last = rhs_end;
        edits.push(StageEdit {
            kind: "comparison-parens".to_string(),
            detail: format!("{op} {rhs_masked} -> {op} ({rhs_masked})"),
            evidence: "bitwise chain over unparenthesized comparison; solc precedence misparse (2271 class)"
                .to_string(),
        });
    }
    if pieces.is_empty() {
        return Ok(Stage {
            name: "comparison-parens",
            description: "comparison parenthesization",
            source: source.to_string(),
            edits,
            findings: Vec::new(),
        });
    }
    pieces.push(source[last..].to_string());
    Ok(Stage {
        name: "comparison-parens",
        description: "comparison parenthesization",
        source: pieces.concat(),
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run_once(source: &str) -> Stage {
        run(source).expect("stage runs")
    }

    #[test]
    fn rebalances_the_trial_chain_and_is_idempotent() {
        let source = concat!(
            "contract C {\n",
            "    function f(uint256 a) public view returns (bool) {\n",
            "        if (((a) == 0) | s == a * s / a) {\n",
            "            return a;\n",
            "        }\n",
            "        return false;\n",
            "    }\n",
            "}\n",
        );
        let stage = run_once(source);
        assert_eq!(stage.edits.len(), 1);
        assert!(stage.source.contains("if (((a) == 0) || (s == a * s / a)) {"));
        let again = run_once(&stage.source);
        assert_eq!(again.source, stage.source);
        assert!(again.edits.is_empty());
    }

    #[test]
    fn consumes_chain_matches_once_and_converges() {
        // a rhs scan swallows later chain links; each match wraps at most once
        // per sweep and the residual inner chain wraps on the next sweep
        let source = concat!(
            "contract C {\n",
            "    function f(uint256 a, uint256 b, uint256 c) public view returns (bool) {\n",
            "        return (a == 1) | b == 2 | c == 3;\n",
            "    }\n",
            "}\n",
        );
        let once = run_once(source);
        assert!(once.source.contains("return (a == 1) || (b == 2 | c == 3);"));
        assert_eq!(once.source.matches("b == 2").count(), 1);
        assert_eq!(once.source.matches("c == 3").count(), 1);
        let twice = run_once(&once.source);
        assert!(twice.source.contains("return (a == 1) || (b == 2 | (c == 3));"));
        let thrice = run_once(&twice.source);
        assert_eq!(thrice.source, twice.source);
    }

    #[test]
    fn emits_unmasked_source() {
        // the wrapped rhs is the ORIGINAL slice: the string literal survives
        // verbatim and its comma does not truncate the depth scan
        let source = concat!(
            "contract C {\n",
            "    function f(address a, string memory s) public view returns (bool) {\n",
            "        return (a == address(0)) | s == \"x,y\";\n",
            "    }\n",
            "}\n",
        );
        let stage = run_once(source);
        assert!(stage.source.contains("return (a == address(0)) || (s == \"x,y\");"));
        assert_eq!(run_once(&stage.source).source, stage.source);
    }

    #[test]
    fn noop_without_the_gate_shape() {
        // already-parenthesized rhs and bare identities are untouched
        let source = "contract C { function f(uint256 a) public view returns (bool) { return (a == 1) && (2 == a); } }\n";
        let stage = run_once(source);
        assert!(stage.edits.is_empty());
        assert_eq!(stage.source, source);
    }
}
