//! Stage `slot-aliases`: collapse same-slot storage views.
//!
//! Port of `prepare_candidate.unify_storage_views` with `_declared_slots`,
//! `_write_targets`, and the proven `_VIEW_CASTS` table: the variable with
//! writes becomes canonical; pure-read aliases are replaced at their use sites
//! by the proven widening cast. Written aliases and unproven conversions
//! abstain.

use lazy_static::lazy_static;
use std::collections::{BTreeMap, BTreeSet};

use crate::prepare::{parser::ParseError, stages::helpers::mask, Stage, StageEdit, StageFinding};

lazy_static! {
    static ref RE_SLOT: fancy_regex::Regex =
        fancy_regex::Regex::new(r"//\s*storage slot:\s*(0x[0-9a-fA-F]+)")
            .expect("failed to build regex");
    static ref RE_STATE_DECL: fancy_regex::Regex = fancy_regex::Regex::new(
        r"(?m)^\s*(address|uint\d+|int\d+|bytes\d+|bytes|string|bool)\s+([A-Za-z_]\w*)\s*;([^\n]*)$",
    )
    .expect("failed to build regex");
    static ref RE_WRITE_TARGET: fancy_regex::Regex =
        fancy_regex::Regex::new(r"\b([A-Za-z_]\w*)\b\s*(?:=(?!=)|\+=|-=|\*=|/=|\+\+|--)",)
            .expect("failed to build regex");
}

/// `(primary type, alias type) -> read expression`; `{v}` is the primary
/// variable. Only same-word representations are proven; anything else
/// abstains. Mirrors the read half of `prepare_candidate._VIEW_CASTS`.
fn view_cast(primary: &str, alias: &str) -> Option<&'static str> {
    match (primary, alias) {
        ("bytes32", "address") => Some("address(uint160(uint256({v})))"),
        ("bytes32", "uint256") => Some("uint256({v})"),
        ("uint256", "bytes32") => Some("bytes32({v})"),
        ("address", "uint256") => Some("uint256(uint160({v}))"),
        ("uint160", "address") => Some("address(uint160({v}))"),
        _ => None,
    }
}

/// State variables with slot provenance: name -> (type, lowercased slot).
///
/// Structure comes from the masked text; the slot comment itself is read from
/// the raw source at the same offsets. Mirrors
/// `prepare_candidate._declared_slots`.
fn declared_slots(masked: &str, source: &str) -> BTreeMap<String, (String, String)> {
    let mut declared = BTreeMap::new();
    for captures in RE_STATE_DECL.captures_iter(masked).flatten() {
        let name = match captures.get(2) {
            Some(m) => m.as_str().to_string(),
            None => continue,
        };
        let raw_tail = match captures.get(3) {
            Some(m) => &source[m.start()..m.end()],
            None => "",
        };
        let slot = RE_SLOT
            .captures(raw_tail)
            .ok()
            .flatten()
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().to_lowercase())
            .unwrap_or_default();
        let ty = captures.get(1).map(|m| m.as_str().to_string()).unwrap_or_default();
        declared.insert(name, (ty, slot));
    }
    declared
}

/// Identifiers assigned in the masked snippet (`=`, compound, inc/dec).
/// Mirrors `prepare_candidate._write_targets`.
fn write_targets(masked: &str) -> BTreeSet<String> {
    RE_WRITE_TARGET
        .captures_iter(masked)
        .flatten()
        .filter_map(|c| c.get(1).map(|m| m.as_str().to_string()))
        .collect()
}

pub(crate) fn run(source: &str) -> Result<Stage, ParseError> {
    let masked = mask(source)?;
    let declared = declared_slots(&masked, source);
    let mut by_slot: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    for (name, (_ty, slot)) in &declared {
        if !slot.is_empty() {
            by_slot.entry(slot).or_default().push(name.clone());
        }
    }

    let mut edits: Vec<StageEdit> = Vec::new();
    let mut findings: Vec<StageFinding> = Vec::new();
    // alias identifier -> read expression
    let mut renames: BTreeMap<String, String> = BTreeMap::new();
    let mut alias_slots: BTreeMap<String, String> = BTreeMap::new();

    for (slot, names) in &by_slot {
        if names.len() < 2 {
            continue;
        }
        // order by declaration position, as the Python key sort does
        let mut ordered = names.clone();
        ordered.sort_by_key(|name| {
            let pattern = fancy_regex::Regex::new(&format!(
                r"(?m)^\s*\S+\s+{}\s*;",
                fancy_regex::escape(name)
            ))
            .expect("failed to build regex");
            pattern.find_iter(&masked).flatten().map(|m| m.start()).min().unwrap_or(usize::MAX)
        });
        let types: BTreeMap<&str, &str> =
            ordered.iter().map(|n| (n.as_str(), declared[n].0.as_str())).collect();
        let targets = write_targets(&masked);
        let written: Vec<&String> = ordered.iter().filter(|n| targets.contains(*n)).collect();
        if written.len() > 1 {
            findings.push(StageFinding {
                kind: "slot-alias".to_string(),
                detail: ordered.join(", "),
                reason: format!("slot {slot} has multiple written views; pairing is ambiguous"),
            });
            continue;
        }
        let primary = match written.first() {
            Some(name) => (*name).clone(),
            None => ordered[0].clone(),
        };
        for alias in &ordered {
            if *alias == primary {
                continue;
            }
            if targets.contains(alias) {
                findings.push(StageFinding {
                    kind: "slot-alias".to_string(),
                    detail: alias.clone(),
                    reason: format!(
                        "alias {alias} on slot {slot} is written; left for unit repair"
                    ),
                });
                continue;
            }
            let cast = match view_cast(types[primary.as_str()], types[alias.as_str()]) {
                Some(cast) => cast,
                None => {
                    findings.push(StageFinding {
                        kind: "slot-alias".to_string(),
                        detail: alias.clone(),
                        reason: format!(
                            "no proven conversion {} -> {} on slot {}",
                            types[primary.as_str()],
                            types[alias.as_str()],
                            slot
                        ),
                    });
                    continue;
                }
            };
            // a narrower view additionally needs evidence that the writer
            // stores the value in the low bits: a uint160 cast in the
            // primary's own write expressions
            let pair = [types[primary.as_str()], types[alias.as_str()]];
            if pair.iter().any(|t| *t == "address" || *t == "uint160") {
                let writes = fancy_regex::Regex::new(&format!(
                    r"\b{}\s*=[^;]+;",
                    fancy_regex::escape(&primary)
                ))
                .expect("failed to build regex");
                let snippets: String = writes
                    .find_iter(&masked)
                    .flatten()
                    .map(|m| m.as_str())
                    .collect::<Vec<_>>()
                    .join(" ");
                if !snippets.contains("uint160(") {
                    findings.push(StageFinding {
                        kind: "slot-alias".to_string(),
                        detail: alias.clone(),
                        reason: format!(
                            "writer of {primary} never narrows through uint160; \
                                 packed layout unproven"
                        ),
                    });
                    continue;
                }
            }
            let uses =
                fancy_regex::Regex::new(&format!(r"\b{}\s*[\[].", fancy_regex::escape(alias)))
                    .expect("failed to build regex");
            let use_count = uses.find_iter(&masked).flatten().count();
            if use_count > 0 {
                findings.push(StageFinding {
                    kind: "slot-alias".to_string(),
                    detail: alias.clone(),
                    reason: format!(
                        "{use_count} non-whole-word use(s) of {alias}; packing unproven"
                    ),
                });
                continue;
            }
            renames.insert(alias.clone(), cast.replace("{v}", &primary));
            alias_slots.insert(alias.clone(), declared[alias].1.clone());
        }
    }

    if renames.is_empty() {
        return Ok(Stage {
            name: "slot-aliases",
            description: "storage-view aliases",
            source: source.to_string(),
            edits,
            findings,
        });
    }

    let mut staged = source.to_string();
    for (alias, expression) in &renames {
        // declaration line first (offsets stay valid: later edits are to the left)
        let pattern = fancy_regex::Regex::new(&format!(
            r"(?m)^\s*(?:address|uint\d+|int\d+|bytes\d+|bytes|string|bool)\s+{}\s*;[^\n]*\n",
            fancy_regex::escape(alias)
        ))
        .expect("failed to build regex");
        if let Some(captures) = pattern.captures(&staged).ok().flatten() {
            let whole = captures.get(0).expect("whole match");
            staged = format!("{}{}", &staged[..whole.start()], &staged[whole.end()..]);
        }
        let masked_rest = mask(&staged)?;
        let occurrences: Vec<(usize, usize)> =
            fancy_regex::Regex::new(&format!(r"\b{}\b", fancy_regex::escape(alias)))
                .expect("failed to build regex")
                .find_iter(&masked_rest)
                .flatten()
                .map(|m| (m.start(), m.end()))
                .collect();
        for (start, end) in occurrences.into_iter().rev() {
            staged = format!("{}{}{}", &staged[..start], expression, &staged[end..]);
        }
        edits.push(StageEdit {
            kind: "slot-alias".to_string(),
            detail: format!("{alias} -> {expression}"),
            evidence: format!(
                "same-slot view ({}); canonical variable carries the writes",
                alias_slots[alias]
            ),
        });
    }

    Ok(Stage {
        name: "slot-aliases",
        description: "storage-view aliases",
        source: staged,
        edits,
        findings,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const SEED: &str = concat!(
        "contract D {\n",
        "    address ownerAlias; // storage slot: 0x00\n",
        "    bytes32 cell; // storage slot: 0x00\n",
        "    uint256 other; // storage slot: 0x01\n",
        "\n",
        "    function write(address a) public {\n",
        "        cell = bytes32(uint256(uint160(a)));\n",
        "    }\n",
        "\n",
        "    function who() public view returns (address) {\n",
        "        return ownerAlias;\n",
        "    }\n",
        "}\n",
    );

    #[test]
    fn read_alias_becomes_cast_of_the_written_view() {
        let stage = run(SEED).unwrap();
        assert_eq!(stage.edits[0].kind, "slot-alias");
        // the alias declaration is removed; the written view stays canonical
        assert!(!stage.source.contains("address ownerAlias;"));
        assert!(stage.source.contains("bytes32 cell; // storage slot: 0x00"));
        assert!(stage.source.contains("return address(uint160(uint256(cell)));"));
        assert!(stage.source.contains("cell = bytes32(uint256(uint160(a)));"));
    }

    #[test]
    fn written_alias_abstains() {
        let source = SEED.replace(
            "        cell = bytes32(uint256(uint160(a)));\n    }",
            "        cell = bytes32(uint256(uint160(a)));\n        ownerAlias = a;\n    }",
        );
        assert!(source.contains("ownerAlias = a;")); // the variant was built
        let stage = run(&source).unwrap();
        assert_eq!(stage.source, source);
        assert!(stage.findings.iter().any(|f| f.kind == "slot-alias"));
    }

    #[test]
    fn unknown_type_pair_abstains() {
        let source = SEED.replace("    address ownerAlias;", "    string ownerAlias;");
        let stage = run(&source).unwrap();
        assert_eq!(stage.source, source);
        assert!(stage.findings.iter().any(|f| f.reason.contains("no proven conversion")));
    }

    #[test]
    fn no_slot_comments_is_a_noop() {
        let source = "contract D {\n    uint256 a;\n    uint256 b;\n}\n";
        let stage = run(source).unwrap();
        assert_eq!(stage.source, source);
        assert!(stage.edits.is_empty());
    }

    #[test]
    fn slot_alias_requires_writer_narrowing_evidence() {
        let source = concat!(
            "contract D {\n",
            "    address ownerAlias; // storage slot: 0x00\n",
            "    bytes32 cell; // storage slot: 0x00\n",
            "    function write(address a) public { cell = bytes32(a); }\n",
            "    function who() public view returns (address) { return ownerAlias; }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert_eq!(stage.source, source);
        assert!(stage.findings.iter().any(|f| f.reason.contains("uint160")));
    }

    #[test]
    fn slot_alias_abstains_on_member_or_indexed_reads() {
        let source = concat!(
            "contract D {\n",
            "    address ownerAlias; // storage slot: 0x00\n",
            "    bytes32 cell; // storage slot: 0x00\n",
            "    function write(address a) public { cell = bytes32(uint256(uint160(a))); }\n",
            "    function who() public view returns (bytes1) { return ownerAlias[0]; }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert_eq!(stage.source, source);
        assert!(stage.findings.iter().any(|f| f.reason.contains("non-whole-word")));
    }

    #[test]
    fn pair_scoped_narrowing_ignores_unrelated_views() {
        // a third address view on the slot must not influence the
        // bytes32/uint256 pair (review regression: slot-wide check)
        let source = concat!(
            "contract D {\n",
            "    bytes32 cell; // storage slot: 0x00\n",
            "    uint256 view_a; // storage slot: 0x00\n",
            "    address spare; // storage slot: 0x00\n",
            "    function write(uint256 a) public { cell = bytes32(a); }\n",
            "    function who() public view returns (uint256) { return view_a; }\n",
            "}\n",
        );
        let stage = run(source).unwrap();
        assert!(stage.source.contains("return uint256(cell);"), "{}", stage.source);
        // the address pair still needs its own narrowing evidence
        assert!(stage.findings.iter().any(|f| f.detail == "spare"));
    }
}
