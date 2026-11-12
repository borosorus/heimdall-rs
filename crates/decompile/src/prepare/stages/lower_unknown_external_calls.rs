//! Stage `lower-unknown-external-calls`: lower member calls to undeclared
//! external selectors.
//!
//! Port of `prepare_candidate.lower_unknown_external_calls`:
//! `(bool success, bytes memory ret0) = address(<expr>).Unresolved_<h8>{value: v}(args);`
//! (a named member call no declaration can back). Faithful lowering:
//! `<exprInner>.call{value: v}(abi.encodeWithSelector(0x<h8>, args))` where
//! the unresolved name carries its own selector. Gate: every argument a bare
//! word-sized atom, so the ABI payload is byte-identical; dynamic sites
//! abstain. The `address(...)` wrapper is scanned balanced (the inner
//! expression may nest arbitrarily after other stages); matches are processed
//! in find order with Python slice semantics at the splice, so a nested
//! wrapper inside an already-rewritten span contributes nothing.

use lazy_static::lazy_static;

use crate::prepare::{stages::helpers::mask, ParseError, Stage, StageEdit};

lazy_static! {
    static ref RE_HEAD: fancy_regex::Regex =
        fancy_regex::Regex::new(r"address\(").expect("failed to build regex");
    static ref RE_NAME: fancy_regex::Regex = fancy_regex::Regex::new(
        r"\.\s*(?P<name>Unresolved_[0-9a-fA-F]{8})\s*\{\s*value:\s*(?P<value>0x[0-9a-fA-F]+|\d+)\s*\}\(",
    )
    .expect("failed to build regex");
    static ref RE_ATOM: fancy_regex::Regex =
        fancy_regex::Regex::new(r"[A-Za-z_][A-Za-z0-9_]*|0x[0-9a-fA-F]+|\d+").expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    let bytes = masked.as_bytes();

    let mut edits: Vec<StageEdit> = Vec::new();
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;

    for head in RE_HEAD.find_iter(&masked).flatten() {
        let open_paren = head.end() - 1;
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
        let inner = masked[open_paren + 1..close].trim();
        // Python slices a 199-char window and uses re.match: the name must
        // start EXACTLY at the close paren (anchored), else the site abstains
        let tail_end = (close + 200).min(masked.len());
        let tail = &masked[close + 1..tail_end];
        let Some(nm) = RE_NAME.find(tail).unwrap_or(None) else {
            continue;
        };
        if nm.start() != 0 {
            continue;
        }
        let Some(caps) = RE_NAME.captures(tail).unwrap_or(None) else {
            continue;
        };
        let name = (
            caps.name("name").expect("name").as_str().to_string(),
            caps.name("value").expect("value").as_str().to_string(),
        );
        let args_open = close + nm.end();
        let mut depth2 = 0usize;
        let mut j = args_open;
        let mut args_close = None;
        while j < bytes.len() {
            match bytes[j] {
                b'(' => depth2 += 1,
                b')' => {
                    depth2 -= 1;
                    if depth2 == 0 {
                        args_close = Some(j);
                        break;
                    }
                }
                _ => {}
            }
            j += 1;
        }
        let Some(args_close) = args_close else { continue };
        let args_raw = masked[args_open + 1..args_close].trim();
        let atoms: Vec<String> = if args_raw.is_empty() {
            Vec::new()
        } else {
            args_raw.split(',').map(|a| a.trim().to_string()).collect()
        };
        if !atoms
            .iter()
            .all(|a| RE_ATOM.find(a).unwrap_or(None).map(|m| m.as_str() == a).unwrap_or(false))
        {
            continue;
        }
        let selector = format!("0x{}", &name.0[name.0.len() - 8..]);
        let mut call_args = selector.clone();
        if !atoms.is_empty() {
            call_args.push_str(", ");
            call_args.push_str(&atoms.join(", "));
        }
        let lowered =
            format!("{inner}.call{{value: {}}}(abi.encodeWithSelector({call_args}))", name.1);
        let start = head.start();
        let end = args_close + 1;
        if start > last {
            pieces.push(source[last..start].to_string());
        }
        pieces.push(lowered);
        last = end;
        edits.push(StageEdit {
            kind: "external-call-lowered".to_string(),
            detail: "address(..).Unresolved_<h8>{value..}(..) -> call/encodeWithSelector"
                .to_string(),
            evidence: "undeclared external selector; identical selector and word args".to_string(),
        });
    }

    if pieces.is_empty() {
        return Ok(Stage {
            name: "lower-unknown-external-calls",
            description: "external call lowering",
            source: source.to_string(),
            edits,
            findings: Vec::new(),
        });
    }
    pieces.push(source[last..].to_string());
    Ok(Stage {
        name: "lower-unknown-external-calls",
        description: "external call lowering",
        source: pieces.concat(),
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn unresolved_member_call_is_lowered() {
        let staged = prepare(concat!(
            "contract C {\n",
            "    function f(address var_a) public {\n",
            "        (bool success, bytes memory ret0) = address(var_a).Unresolved_18178358{value: 0}(var_a);\n",
            "        success;\n",
            "        ret0;\n",
            "    }\n",
            "}\n",
        ))
        .unwrap()
        .source;
        assert!(staged.contains("var_a.call{value: 0}(abi.encodeWithSelector(0x18178358, var_a));"));
    }

    #[test]
    fn dynamic_arguments_abstain() {
        let source = concat!(
            "contract C {\n",
            "    function f(address var_a, bytes memory var_b) public {\n",
            "        (bool success, bytes memory ret0) = address(var_a).Unresolved_18178358{value: 0}(var_b.length);\n",
            "        success;\n",
            "        ret0;\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("Unresolved_18178358"));
    }
}
