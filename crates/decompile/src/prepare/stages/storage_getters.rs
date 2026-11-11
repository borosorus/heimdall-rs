//! Stage `storage-getters`: give slot-correlated stubs their getter bodies.
//!
//! Port of `prepare_candidate.synthesize_storage_getters`: a return-less stub
//! whose signature uniquely unifies with a mapping's key chain and value type
//! (per the storage-flow map) gains `return <mapping>[k0][k1...];`, `view`
//! mutability, and the value-typed returns clause - with the provenance
//! comment mirroring the declaration, as everywhere else.

use lazy_static::lazy_static;

use crate::prepare::{
    parser::ParseError,
    storage_flow::{build_storage_flow, canonical_type},
    Stage, StageEdit,
};

lazy_static! {
    static ref RE_PURE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\bpure\b").expect("failed to build regex");
    static ref RE_RETURNS_KW: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\breturns\b").expect("failed to build regex");
    static ref RE_REFERENCE_VALUE: fancy_regex::Regex =
        fancy_regex::Regex::new(r"^(?:string|bytes|[A-Za-z_]\w*\[\]|mapping)")
            .expect("failed to build regex");
    static ref RE_SIGNATURE_COMMENT: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?m)^(\s*///\s*@custom:signature\s+[A-Za-z_]\w*\([^)]*\))([^:\n]*)$",
    )
    .expect("failed to build regex");
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let flow = build_storage_flow(source)?;
    let mut edits: Vec<StageEdit> = Vec::new();
    // (start, end, replacement)
    let mut rewrites: Vec<(usize, usize, String)> = Vec::new();
    for candidate in &flow.correlations {
        let unit_text = &source[candidate.start..candidate.end];
        let header = &unit_text[..candidate.header_len.min(unit_text.len())];
        let body = &unit_text[candidate.header_len.min(unit_text.len())..];
        let mut new_header = RE_PURE.replace_all(header, "view").to_string();
        if !RE_RETURNS_KW.is_match(&new_header).unwrap_or(false) {
            let mut value = candidate.value_type.clone();
            if RE_REFERENCE_VALUE.is_match(&value).unwrap_or(false) && !value.contains(" memory") {
                // reference types need a data location in a returns clause
                value = format!("{value} memory");
            }
            let returns_clause = format!(" returns ({value})");
            new_header = format!("{}{}", new_header.trim_end(), returns_clause);
            // the provenance comment mirrors the declaration, when present
            if let Some(captures) = RE_SIGNATURE_COMMENT.captures(&new_header).ok().flatten() {
                if let Some(m) = captures.get(2) {
                    let (g2_start, g2_end) = (m.start(), m.end());
                    let g2_text = m.as_str();
                    new_header = format!(
                        "{}{}{}{}",
                        &new_header[..g2_start],
                        g2_text.trim_end(),
                        returns_clause,
                        &new_header[g2_end..]
                    );
                }
            }
        }
        let mut expression = candidate.storage.clone();
        let mut casts: Vec<String> = Vec::new();
        for (index, name) in candidate.param_names.iter().enumerate() {
            let key_type = canonical_type(&candidate.key_chain[index]);
            let param_type = &candidate.params[index];
            let index_expr =
                if param_type != &key_type && param_type == "uint" && key_type == "address" {
                    // generic-uint decompiled word indexing an address key: the
                    // explicit uint160 narrowing is the standard decompiler cast
                    casts.push(name.clone());
                    format!("[address(uint160({name}))]")
                } else {
                    format!("[{name}]")
                };
            expression.push_str(&index_expr);
        }
        let close = match body.rfind('}') {
            Some(close) => close,
            None => continue,
        };
        let new_body = format!(
            "{}{}{}",
            &body[..close],
            format!("\n        return {expression};"),
            &body[close..]
        );
        rewrites.push((candidate.start, candidate.end, new_header + &new_body));
        let mut detail = format!(
            "{} -> return {expression}; (storage {} slot {}, evidence {})",
            candidate.function,
            candidate.storage,
            candidate.slot.as_deref().unwrap_or("None"),
            candidate.evidence
        );
        if !casts.is_empty() {
            detail.push_str(&format!("; uint160 casts on {}", casts.join(", ")));
        }
        edits.push(StageEdit {
            kind: "storage-getter".to_string(),
            detail,
            evidence: "stub signature uniquely unifies with slot-annotated mapping".to_string(),
        });
    }

    if rewrites.is_empty() {
        return Ok(Stage {
            name: "storage-getters",
            description: "storage-getter synthesis",
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
        name: "storage-getters",
        description: "storage-getter synthesis",
        source: staged,
        edits,
        findings: Vec::new(),
    })
}

#[cfg(test)]
mod tests {
    use super::run;
    use crate::prepare::prepare;

    #[test]
    fn storage_getter_synthesized_from_unique_mapping_match() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => mapping(address => uint256)) storage_map_b; // storage slot: 0x01\n",
            "    /// @custom:signature   Unresolved_dd62ed3e(address arg0, uint256 arg1) public pure\n",
            "    function Unresolved_dd62ed3e(address arg0, uint256 arg1) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains(
            "function Unresolved_dd62ed3e(address arg0, address arg1) public view returns (uint256) {"
        ));
        // arg1 is a generic-uint word; the address key gets the explicit narrowing
        assert!(staged.contains("return storage_map_b[arg0][arg1];"));
        // provenance comment stays in sync with the new mutability/returns
        assert!(staged.contains(
            "Unresolved_dd62ed3e(address arg0, address arg1) public view returns (uint256)"
        ));
    }

    #[test]
    fn uint160_narrowing_cast_is_emitted_for_generic_uint_keys() {
        // direct stage test: the param stays generic-uint here (no retyped
        // declaration), so the getter's own uint160 narrowing must fire
        let source = concat!(
            "contract C {\n",
            "    mapping(address => uint256) balances; // storage slot: 0x00\n",
            "    /// @custom:signature   balanceOf(uint256 arg0) public pure\n",
            "    /// @param              arg0 [\"address\"]\n",
            "    function balanceOf(uint256 arg0) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n",
            "    }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert_eq!(stage.edits.len(), 1);
        assert!(
            stage.edits[0].detail.contains("uint160 casts on arg0"),
            "{}",
            stage.edits[0].detail
        );
        assert!(
            stage.source.contains("return balances[address(uint160(arg0))];"),
            "{}",
            stage.source
        );
    }

    #[test]
    fn storage_getter_abstains_when_return_type_differs() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => uint256) storage_map_a; // storage slot: 0x00\n",
            "    /// @custom:signature   f(address arg0) public view returns (string memory)\n",
            "    function f(address arg0) public view returns (string memory) {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        // value uint256 != declared string return: no synthesis, body untouched
        assert!(!staged.contains("return storage_map_a[arg0];"));
    }

    #[test]
    fn storage_getter_needs_no_declared_return() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => uint256) balances; // storage slot: 0x00\n",
            "    /// @custom:signature   balanceOf(address arg0) public pure\n",
            "    function balanceOf(address arg0) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(staged.contains("function balanceOf(address arg0) public view returns (uint256) {"));
        assert!(staged.contains("return balances[arg0];"));
        // provenance comment mirrors mutability AND returns on this path too
        assert!(staged.contains(
            "/// @custom:signature   balanceOf(address arg0) public view returns (uint256)"
        ));
    }

    #[test]
    fn storage_getter_reference_value_gets_memory_location() {
        let source = concat!(
            "contract C {\n",
            "    mapping(address => string) names; // storage slot: 0x00\n",
            "    function nameOf(address arg0) public pure {\n",
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n",
            "    }\n",
            "}\n",
        );
        let staged = prepare(source).unwrap().source;
        assert!(
            staged.contains("function nameOf(address arg0) public view returns (string memory) {"),
            "{staged}"
        );
    }
}
