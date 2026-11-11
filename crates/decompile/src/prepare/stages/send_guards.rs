//! Stage `send-guards`: transplant balance-guard precedents onto send stubs.
//!
//! Port of `prepare_candidate.synthesize_send_guards`: a send-path stub (body
//! = `require(...)` lines only) gains the guard its sibling functions apply to
//! the SAME storage: a precedent sibling both guard-checks a mapping
//! (`M[x] >= y`) and mutates it by indexed compound assignment (`M[x] -=/+=`).
//! When exactly one mapping has such a precedent, a stub whose signature can
//! address it (an address-class and a scalar param) receives
//! `require(M[<first address param>] >= <last scalar param>);`. Role mapping
//! is positional and recorded; the plain-require form claims nothing about
//! revert payloads; mutability is relaxed via the header span only.

use lazy_static::lazy_static;
use std::collections::{BTreeMap, BTreeSet};

use crate::prepare::{
    parser::{parse_contract, ParseError},
    stages::helpers::{header_params, mask},
    storage_flow::build_storage_flow,
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_GUARD_PRECEDENT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b([A-Za-z_]\w*)\[([^\]]+)\] >= ([A-Za-z_]\w*)")
            .expect("failed to build regex");
    static ref RE_MUTATION: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b([A-Za-z_]\w*)\[[^\]]+\] [-+]=")
            .expect("failed to build regex");
    static ref RE_REQUIRE_LINE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^[ \t]*require\([^;]*;[ \t]*$").expect("failed to build regex");
    static ref RE_REQUIRE_LINE_END: fancy_regex::Regex =
        fancy_regex::Regex::new(r"(?m)^[ \t]*require\([^;]*;\n?").expect("failed to build regex");
    static ref RE_PURE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bpure\b").expect("failed to build regex");
    static ref RE_UINT_KIND: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^uint\d*$").expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let flow = build_storage_flow(source)?;
    let mappings: BTreeSet<String> = flow
        .declarations
        .iter()
        .filter(|d| d.nesting_depth() == 1)
        .map(|d| d.name.clone())
        .collect();
    let parsed = parse_contract(source, None)?;

    // sibling precedent: same function guards AND mutates the same mapping
    let mut guarded_by: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for unit in parsed.functions() {
        let unit_masked = mask(&source[unit.start..unit.end])?;
        let guards: BTreeSet<String> = RE_GUARD_PRECEDENT
            .captures_iter(&unit_masked)
            .flatten()
            .filter_map(|c| c.get(1))
            .map(|m| m.as_str().to_string())
            .collect();
        let mutations: BTreeSet<String> = RE_MUTATION
            .captures_iter(&unit_masked)
            .flatten()
            .filter_map(|c| c.get(1))
            .map(|m| m.as_str().to_string())
            .collect();
        for name in guards.intersection(&mutations) {
            if mappings.contains(name) {
                guarded_by.entry(name.clone()).or_default().insert(unit.name.clone());
            }
        }
    }

    // resolve once for all stubs: the guarded-and-mutated mappings with a
    // unique precedent sibling
    let unique_precedents: BTreeMap<String, String> = guarded_by
        .iter()
        .filter(|(_, siblings)| siblings.len() == 1)
        .map(|(name, siblings)| (name.clone(), siblings.iter().next().unwrap().clone()))
        .collect();

    let mut edits: Vec<StageEdit> = Vec::new();
    let mut rewrites: Vec<(usize, usize, String)> = Vec::new();
    for unit in parsed.functions() {
        let unit_text = &source[unit.start..unit.end];
        let unit_masked = mask(unit_text)?;
        let header_len = unit.header.len().min(unit_masked.len());
        let body = &unit_text[header_len..];
        let body_masked = &unit_masked[header_len..];

        // allowlist grammar: the body interior (between the braces) is
        // require-lines only; brace span from the masked text so one-line
        // `...;}` tails are handled
        let open_brace = match body_masked.find('{') {
            Some(open) => open,
            None => continue,
        };
        let close_brace = match body_masked.rfind('}') {
            Some(close) => close,
            None => continue,
        };
        if close_brace <= open_brace {
            continue;
        }
        let interior = &body_masked[open_brace + 1..close_brace];
        let body_lines: Vec<&str> = interior.lines().filter(|l| !l.trim().is_empty()).collect();
        if body_lines.is_empty() ||
            !body_lines.iter().all(|line| RE_REQUIRE_LINE.is_match(line).unwrap_or(false))
        {
            continue;
        }
        let header_masked = mask(&unit.header)?;
        let params = header_params(&header_masked);
        let address_params: Vec<String> = params
            .iter()
            .filter(|(type_text, _)| type_text.starts_with("address"))
            .map(|(_, name)| name.clone())
            .collect();
        let scalar_params: Vec<String> = params
            .iter()
            .filter(|(type_text, _)| RE_UINT_KIND.is_match(type_text).unwrap_or(false))
            .map(|(_, name)| name.clone())
            .collect();
        if address_params.is_empty() || scalar_params.is_empty() {
            continue;
        }
        if unique_precedents.len() != 1 {
            edits.push(StageEdit {
                kind: "send-guard-abstain".to_string(),
                detail: format!(
                    "{}: {} guarded-and-mutated mappings",
                    unit.name,
                    unique_precedents.len()
                ),
                evidence: "guard precedent must be unique".to_string(),
            });
            continue;
        }
        let (mapping_name, precedent) = unique_precedents.iter().next().unwrap();
        let guard = format!(
            "require({mapping_name}[{}] >= {});",
            address_params[0],
            scalar_params[scalar_params.len() - 1]
        );
        if body_masked.contains(&guard) {
            continue;
        }
        // insert after the last existing require line in the stub prologue
        let mut require_end = None;
        for m in RE_REQUIRE_LINE_END.find_iter(body_masked).flatten() {
            require_end = Some(m.end());
        }
        let require_end = match require_end {
            Some(end) => end,
            None => continue,
        };
        let new_body = format!("{}        {guard}\n{}", &body[..require_end], &body[require_end..]);
        // the injected guard reads state: relax pure->view in the header, whose
        // span covers the declaration AND its provenance comment and contains
        // no string literals; the body's tokens are untouched by construction
        let new_header = RE_PURE.replace_all(&unit_text[..header_len], "view").to_string();
        rewrites.push((unit.start, unit.end, new_header + &new_body));
        edits.push(StageEdit {
            kind: "send-guard".to_string(),
            detail: format!("{} += {guard} (precedent {precedent} on {mapping_name})", unit.name),
            evidence: "sibling guards and mutates the same mapping; role mapping positional"
                .to_string(),
        });
    }

    if rewrites.is_empty() {
        return Ok(Stage {
            name: "send-guards",
            description: "send-guard transplantation",
            source: source.to_string(),
            edits,
            findings: Vec::new(),
        });
    }
    let mut staged = source.to_string();
    rewrites.sort_by(|a, b| b.0.cmp(&a.0));
    for (start, end, replacement) in rewrites {
        staged = format!("{}{}{}", &staged[..start], replacement, &staged[end..]);
    }
    Ok(Stage {
        name: "send-guards",
        description: "send-guard transplantation",
        source: staged,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn send_guard_transplanted_from_guarding_sibling() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => uint256) public balances; // storage slot: 0x00\n",
            "    function transfer(address arg0, uint256 arg1) public payable returns (bool) {\n",
            "        require(balances[msg.sender] >= arg1);\n",
            "        balances[msg.sender] -= arg1;\n",
            "        return true;\n",
            "    }\n",
            "    function transferFrom(address arg0, address arg1, uint256 arg2) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);\n",
            "        require(true);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap();
        assert!(staged.source.contains("require(balances[arg0] >= arg2);"));
        let send_stage = staged.stages.iter().find(|s| s.name == "send-guards").unwrap();
        let record = send_stage.edits.iter().find(|e| e.kind == "send-guard").unwrap();
        // recorded precedent names the sibling and the mapping
        assert!(record.detail.contains("precedent transfer on balances"));
    }

    #[test]
    fn send_guard_abstains_without_guarding_sibling() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => uint256) public balances; // storage slot: 0x00\n",
            "    function transferFrom(address arg0, address arg1, uint256 arg2) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);\n",
            "        require(true);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap();
        // no sibling guards+mutates balances: the stub stays untouched
        assert!(!staged.source.contains("require(balances[arg0] >= arg2);"));
        let send_stage = staged.stages.iter().find(|s| s.name == "send-guards").unwrap();
        let record = send_stage.edits.iter().find(|e| e.kind == "send-guard-abstain").unwrap();
        assert!(record.detail.contains("0 guarded-and-mutated mappings"));
    }

    #[test]
    fn send_guard_skips_functions_with_bodies() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => uint256) public balances; // storage slot: 0x00\n",
            "    function transfer(address arg0, uint256 arg1) public payable returns (bool) {\n",
            "        require(balances[msg.sender] >= arg1);\n",
            "        balances[msg.sender] -= arg1;\n",
            "        return true;\n",
            "    }\n",
            "    function sweep(address arg0) public payable returns (bool) {\n",
            "        require(balances[arg0] >= 1);\n",
            "        balances[arg0] -= 1;\n",
            "        return true;\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        // both functions already carry guards; nothing qualifies as a stub
        assert!(!staged.contains("precedent"));
    }
}
