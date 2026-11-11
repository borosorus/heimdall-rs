//! Stage `selfref`: split self-referential `var_*` initializers.
//!
//! Port of `prepare_candidate._split_self_referential_initializers` /
//! `split_selfref_initializers`: `T var_x = <expr referencing var_x>;` with no
//! earlier `var_x` binding becomes a default-initialized declaration plus an
//! assignment, preserving the decompiled expression verbatim.

use lazy_static::lazy_static;

use crate::prepare::{parser::ParseError, stages::helpers::mask, Stage, StageEdit};

lazy_static! {
    static ref RE_SELFREF: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?P<indent>[ \t]*)\b(?P<type>uint\d+|int\d+|address|bytes\d+|bool)\s+(?P<name>var_[a-z]+)\s*=\s*(?P<expr>[^;\n]+);",
    )
    .expect("failed to build regex");
    static ref RE_OUTER_ASSIGNMENT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bvar_[a-z]+\s*=[^=]").expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    let mut edits: Vec<StageEdit> = Vec::new();
    let mut pieces: Vec<String> = Vec::new();
    let mut last = 0usize;

    for captures in RE_SELFREF.captures_iter(&masked).flatten() {
        let whole = match captures.get(0) {
            Some(m) => m,
            None => continue,
        };
        let name = match captures.name("name") {
            Some(m) => m.as_str().to_string(),
            None => continue,
        };
        let before = &masked[..whole.start()];
        let assignment =
            fancy_regex::Regex::new(&format!(r"\b{name}\s*=[^=]")).expect("failed to build regex");
        let declaration = fancy_regex::Regex::new(&format!(
            r"\b(?:uint\d+|int\d+|address|bytes\d+|bool)\s+{name}\b"
        ))
        .expect("failed to build regex");
        let earlier_binding = assignment.is_match(before).unwrap_or(false) ||
            declaration.is_match(before).unwrap_or(false);
        let expr = match captures.name("expr") {
            Some(m) => m.as_str(),
            None => continue,
        };
        let uses_self =
            fancy_regex::Regex::new(&format!(r"\b{name}\b")).expect("failed to build regex");
        if earlier_binding || !uses_self.is_match(expr).unwrap_or(false) {
            continue;
        }
        // the mask is length-preserving, so group spans address `source` too;
        // rebuild from source text to keep string literals intact
        let span = |key: &str| -> (usize, usize) {
            let m = captures.name(key).expect("named group");
            (m.start(), m.end())
        };
        let (is_, ie) = span("indent");
        let indent = &source[is_..ie];
        let src_type = &source[span("type").0..span("type").1];
        let src_name = &source[span("name").0..span("name").1];
        let src_expr = &source[span("expr").0..span("expr").1];
        let replacement =
            format!("{indent}{src_type} {src_name};\n{indent}{src_name} = {src_expr};");
        let (start, end) = (whole.start(), whole.end());
        pieces.push(source[last..start].to_string());
        pieces.push(replacement);
        last = end;
        edits.push(StageEdit {
            kind: "selfref-initializer".to_string(),
            detail: format!("{src_type} {src_name} = ...; -> {src_name}; {src_name} = ...;"),
            evidence: "self-referential initializer without an earlier binding".to_string(),
        });
    }

    let staged = if edits.is_empty() {
        source.to_string()
    } else {
        pieces.push(source[last..].to_string());
        pieces.concat()
    };
    Ok(Stage {
        name: "selfref",
        description: "self-referential initializers",
        source: staged,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn selfreferential_initializer_is_split() {
        let source = concat!(
            "contract C {\n",
            "    function f() public pure {\n",
            "        uint256 var_b = var_b + 0x60;\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("uint256 var_b;\n"));
        assert!(staged.contains("var_b = var_b + 0x60;"));
        assert!(!staged.contains("uint256 var_b = var_b"));
    }

    #[test]
    fn selfreferential_split_respects_outer_binding() {
        let source = concat!(
            "contract C {\n",
            "    uint256 var_b;\n",
            "    function f() public view {\n",
            "        uint256 var_b = var_b + 0x60;\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        // an outer binding exists: the local shadowing declaration is legal, keep it
        assert!(staged.contains("uint256 var_b = var_b + 0x60;"));
    }
}
