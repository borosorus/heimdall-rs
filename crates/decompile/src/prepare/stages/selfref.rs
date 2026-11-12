//! Stage `selfref`: split self-referential `var_*` initializers (unit-scoped).
//!
//! Port of `prepare_candidate.split_selfref_initializers`:
//! `T var_x = <expr referencing var_x>;` with no earlier `var_x` binding
//! becomes a default-initialized declaration plus an assignment, preserving
//! the decompiled expression verbatim. Scope-honest (the lighthouse lesson):
//! an earlier binding counts only within the SAME function unit, plus
//! contract-level state declarations (visibility qualifiers accepted); a
//! like-named local of a DIFFERENT unit does not make the use visible. On a
//! parse failure the fallback is the historical file-prefix scan.

use lazy_static::lazy_static;

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::mask,
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_SELFREF: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?P<indent>[ \t]*)\b(?P<type>uint\d+|int\d+|address|bytes\d+|bool)\s+(?P<name>var_[a-z]+)\s*=\s*(?P<expr>[^;\n]+);",
    )
    .expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    // Python wraps the parse in try/except: on failure unit_spans stays empty,
    // every position is "outside any unit" and the enclosing-unit prefix
    // degrades to the whole file prefix (the historical scan).
    let parsed = parse_contract(source, None).ok();
    let unit_spans: Vec<(usize, usize)> = parsed
        .as_ref()
        .map(|parsed| parsed.functions().map(|unit| (unit.start, unit.end)).collect())
        .unwrap_or_default();
    let in_unit = |offset: usize| unit_spans.iter().any(|(a, b)| *a <= offset && offset < *b);
    let enclosing_unit_start = |offset: usize| {
        unit_spans.iter().filter(|(a, _)| *a <= offset).map(|(a, _)| *a).max().unwrap_or(0)
    };

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
        let unit_start = enclosing_unit_start(whole.start());
        // visible-before bindings: same-unit locals preceding the match, plus
        // contract-level state declarations anywhere outside function units
        let unit_local_prefix = &masked[unit_start..whole.start()];
        let assignment =
            fancy_regex::Regex::new(&format!(r"\b{name}\s*=[^=]")).expect("failed to build regex");
        let state_declaration = fancy_regex::Regex::new(&format!(
            r"\b(?:uint\d+|int\d+|address|bytes\d+|bool)\s+(?:public|private|internal|constant|immutable|[ \t])*{name}\b"
        ))
        .expect("failed to build regex");
        let state_match = state_declaration
            .captures_iter(&masked)
            .flatten()
            .any(|c| c.get(0).map(|m| !in_unit(m.start())).unwrap_or(false));
        let earlier_binding =
            assignment.is_match(unit_local_prefix).unwrap_or(false) || state_match;
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
        // a state declaration is in scope inside every unit: keep the local
        assert!(staged.contains("uint256 var_b = var_b + 0x60;"));
    }

    #[test]
    fn like_named_local_in_other_unit_does_not_hide_the_use() {
        // the lighthouse lesson: unit A's `var_b` must not cover unit B's use
        let source = concat!(
            "contract C {\n",
            "    function a() public pure {\n",
            "        uint256 var_b = 0x1;\n",
            "        var_b = var_b + 0x1;\n",
            "    }\n",
            "\n",
            "    function b() public pure {\n",
            "        uint256 var_b = var_b + 0x60;\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        let unit_b = staged.split("function b()").nth(1).expect("unit b");
        assert!(unit_b.contains("uint256 var_b;\n"));
        assert!(unit_b.contains("var_b = var_b + 0x60;"));
    }
}
