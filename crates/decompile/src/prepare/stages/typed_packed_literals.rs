//! Stage `typed-packed-literals`: type bare integer literals in `abi.encodePacked`.
//!
//! Port of `prepare_candidate.typed_packed_literals`: solc 0.8 refuses packed
//! encoding of untyped literals (error 7279); the decompiler emits them as raw
//! words mirrored from the bytecode's pushes, so the faithful typing is
//! `uint256(literal)` - a full 32-byte big-endian word, exactly the stack
//! width the push had. Non-literal arguments are untouched.

use lazy_static::lazy_static;

use crate::prepare::{stages::helpers::mask, ParseError, Stage, StageEdit};

lazy_static! {
    static ref RE_CALL: fancy_regex::Regex =
        fancy_regex::Regex::new(r"abi\.encodePacked\(").expect("failed to build regex");
    static ref RE_LITERAL: fancy_regex::Regex =
        fancy_regex::Regex::new(r"(?<![A-Za-z0-9_])(?P<lit>0x[0-9a-fA-F]+|\d+)(?![A-Za-z0-9_])",)
            .expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    let mut plans: Vec<(usize, usize, String)> = Vec::new();

    for call in RE_CALL.find_iter(&masked).flatten() {
        let open_paren = call.end() - 1;
        let bytes = masked.as_bytes();
        let mut depth = 1usize;
        let mut index = open_paren + 1;
        let mut arg_start = open_paren + 1;
        let mut closed = None;
        let mut args: Vec<(usize, usize)> = Vec::new();
        while index < bytes.len() && depth > 0 {
            match bytes[index] {
                b'(' => depth += 1,
                b')' => {
                    depth -= 1;
                    if depth == 0 {
                        args.push((arg_start, index));
                        closed = Some(index);
                        break;
                    }
                }
                b',' if depth == 1 => {
                    args.push((arg_start, index));
                    arg_start = index + 1;
                }
                _ => {}
            }
            index += 1;
        }
        if closed.is_none() {
            continue;
        }
        for (a, b) in args {
            let raw = &masked[a..b];
            let trimmed = raw.trim();
            let Some(literal) = RE_LITERAL.find(trimmed).unwrap_or(None) else {
                continue;
            };
            if literal.as_str().len() != trimmed.len() {
                continue; // fullmatch: the argument must be exactly one literal
            }
            let lead = raw.len() - raw.trim_start().len();
            let start = a + lead;
            plans.push((
                start,
                start + literal.as_str().len(),
                format!("uint256({})", literal.as_str()),
            ));
        }
    }

    if plans.is_empty() {
        return Ok(Stage {
            name: "typed-packed-literals",
            description: "packed-literal typing",
            source: source.to_string(),
            edits: Vec::new(),
            findings: Vec::new(),
        });
    }
    // descending splice on the raw source (the mask is length-preserving);
    // the edit log is ascending, i.e. the same plans walked backwards
    let mut descending = plans;
    descending.sort_by(|x, y| y.0.cmp(&x.0));
    let mut staged = source.to_string();
    for (start, end, replacement) in &descending {
        staged = format!("{}{}{}", &staged[..*start], replacement, &staged[*end..]);
    }
    let mut edits: Vec<StageEdit> = Vec::new();
    for (start, end, _) in descending.iter().rev() {
        edits.push(StageEdit {
            kind: "packed-literal-typed".to_string(),
            detail: format!("abi.encodePacked argument {} -> uint256(...)", &source[*start..*end]),
            evidence: "bare literal in packed encoding (solc 7279); word width preserved"
                .to_string(),
        });
    }
    Ok(Stage {
        name: "typed-packed-literals",
        description: "packed-literal typing",
        source: staged,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn bare_literal_in_packed_encoding_is_typed() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    function f() public pure returns (bytes memory) {\n",
            "        return abi.encodePacked(0x1, var_b);\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("abi.encodePacked(uint256(0x1), var_b)"));
    }

    #[test]
    fn already_typed_arguments_are_untouched() {
        let source = concat!(
            "contract C {\n",
            "    function f() public pure returns (bytes memory) {\n",
            "        return abi.encodePacked(uint256(0x1), var_b);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("abi.encodePacked(uint256(0x1), var_b)"));
        assert!(!staged.contains("uint256(uint256("));
    }
}
