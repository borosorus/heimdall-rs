//! Stage `param-types`: re-type generic-uint parameters from storage keys.
//!
//! Port of `prepare_candidate.infer_param_types_from_storage`: for a stub the
//! storage-flow map correlated with a mapping, a parameter typed as the
//! decompiler's generic `uintN` is re-declared with the mapped key's class
//! (today: `address`). The declaration AND its `@custom:signature` provenance
//! comment are rewritten together, so dispatch selector and calldata stay
//! self-consistent. Non-mapping key classes are future evidence, not guesses.

use lazy_static::lazy_static;

use crate::prepare::{parser::ParseError, storage_flow::build_storage_flow, Stage, StageEdit};

lazy_static! {
    static ref RE_UINT_TYPE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^uint\d+$").expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let flow = build_storage_flow(source)?;
    let mut edits: Vec<StageEdit> = Vec::new();
    let mut rewrites: Vec<(usize, usize, String)> = Vec::new();
    for candidate in &flow.correlations {
        if candidate.evidence == "exact" {
            continue; // every position already agrees; nothing to infer
        }
        let keys: Vec<String> = candidate
            .key_chain
            .iter()
            .map(|k| crate::prepare::storage_flow::canonical_type(k))
            .collect();
        let unit_text = &source[candidate.start..candidate.end];
        let header = &unit_text[..candidate.header_len.min(unit_text.len())];

        // re-type only THIS function's declared parameter list
        let fpos = match header.find("function") {
            Some(fpos) => fpos,
            None => continue,
        };
        let open = match header[fpos..].find('(') {
            Some(rel) => fpos + rel,
            None => continue,
        };
        let close = match header[open..].find(')') {
            Some(rel) => open + rel,
            None => continue,
        };
        let param_span = &header[open + 1..close];
        let params: Vec<String> = param_span.split(',').map(|p| p.trim().to_string()).collect();
        let mut new_params: Vec<String> = Vec::new();
        let mut changed = false;
        for (index, part) in params.iter().enumerate() {
            let tokens: Vec<&str> = part.split_whitespace().collect();
            if index < keys.len() &&
                keys[index] == "address" &&
                tokens.len() == 2 &&
                RE_UINT_TYPE.is_match(tokens[0]).unwrap_or(false) &&
                candidate.param_names.iter().any(|n| n == tokens[1])
            {
                new_params.push(format!("address {}", tokens[1]));
                changed = true;
            } else {
                // Python normalizes every unchanged parameter the same way
                new_params.push(tokens.join(" "));
            }
        }
        if !changed {
            continue;
        }
        let joined = new_params.join(", ");
        let mut new_header = format!("{}{}{}", &header[..open + 1], joined, &header[close..]);
        // the provenance comment carries the same signature: sync its parameter
        // list for this function name (the comment lives in the header span)
        let pattern = fancy_regex::Regex::new(&format!(
            r"(@custom:signature\s+{}\()([^)]*)(\))",
            fancy_regex::escape(&candidate.function)
        ))
        .expect("failed to build regex");
        let mut consumed = 0usize;
        let mut rebuilt = String::new();
        for captures in pattern.captures_iter(&new_header).flatten() {
            let (g1, g3) = match (captures.get(1), captures.get(3)) {
                (Some(g1), Some(g3)) => (g1, g3),
                _ => continue,
            };
            rebuilt.push_str(&new_header[consumed..g1.end()]);
            rebuilt.push_str(&joined);
            consumed = g3.start();
        }
        rebuilt.push_str(&new_header[consumed..]);
        new_header = rebuilt;
        rewrites.push((
            candidate.start,
            candidate.end,
            new_header + &unit_text[candidate.header_len.min(unit_text.len())..],
        ));
        edits.push(StageEdit {
            kind: "param-retyped".to_string(),
            detail: format!(
                "{}: {} -> {} (map keys {:?}, evidence {})",
                candidate.function, param_span, joined, candidate.key_chain, candidate.evidence
            ),
            evidence: "storage-map key class proves the parameter type".to_string(),
        });
    }

    if rewrites.is_empty() {
        return unchanged(source);
    }
    let mut staged = source.to_string();
    rewrites.sort_by(|a, b| b.0.cmp(&a.0));
    for (start, end, text) in rewrites {
        staged = format!("{}{}{}", &staged[..start], text, &staged[end..]);
    }
    Ok(Stage {
        name: "param-types",
        description: "calldata-word type inference",
        source: staged,
        edits,
        findings: Vec::new(),
    })
}

fn unchanged(source: &str) -> Result<Stage, ParseError> {
    Ok(Stage {
        name: "param-types",
        description: "calldata-word type inference",
        source: source.to_string(),
        edits: Vec::new(),
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use crate::prepare::prepare;

    #[test]
    fn param_retyped_from_storage_map_key() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => mapping(address => uint256)) storage_map_b; // storage slot: 0x01\n",
            "    /// @custom:signature   allowance(address arg0, uint256 arg1) public pure\n",
            "    function allowance(address arg0, uint256 arg1) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap();
        let staged_final = staged.source;
        // arg1 re-typed to the map's second address key, declaration AND comment
        assert!(staged_final.contains(
            "function allowance(address arg0, address arg1) public view returns (uint256) {"
        ));
        assert!(staged_final.contains(
            "/// @custom:signature   allowance(address arg0, address arg1) public view returns (uint256)"
        ));
        assert!(staged_final.contains("return storage_map_b[arg0][arg1];"));
        let param_stage = staged.stages.iter().find(|s| s.name == "param-types").unwrap();
        assert!(param_stage.edits.iter().any(|e| e.detail.contains("map keys")));
    }

    #[test]
    fn param_retype_abstains_without_map_evidence() {
        let source = concat!(
            "contract C {\n",
            "    function f(uint256 arg0) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n",
            "    }\n",
            "}\n",
        );
        let staged_final = prepare(source).unwrap().source;
        assert!(staged_final.contains("function f(uint256 arg0) public pure {"));
    }
}
