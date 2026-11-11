# fresh-holdout-v5/v6: events into the verdict, then repaired - erc20 perfect under full scrutiny

Leads 3 (typed calldata inference) and 4 (events) of `../roadmap-deterministic.md`,
labeled protocol. v5 = param-retyping stage + `compare_events: true` (first ever
event-covered verdicts); v6 = v5 + observation-driven event-layout repair.

## Sealed results

| run | arms | erc20 fb/wh | block-reader |
|---|---|---|---|
| v5 (events ON, first exposure) | v4 / v5 | 1/4 + 1/2 **both arms** | 1/1 both |
| v6 (layout-repaired) | v5 / v6 | **4/4 + 2/2** | - |

The v5 dip is the honest measurement the roadmap predicted: with events in the
verdict the candidate's event layout diverges (the decompiler emits alias events
WITHOUT `indexed`, so arguments land in data where the reference indexes them
into topics). v6 closes it: `repair_event_layout.py` reads the reference side's
observed per-event topic counts (consistent across probes) and restores
`indexed` on the alias declarations; the harness re-run is the gate.

## What each lead contributed

- **Lead 3** (`infer_param_types_from_storage` stage): the storage-map's key
  classes re-type generic-uint parameters (allowance's second arg is now
  truthfully `address`); declaration and provenance comment sync; the
  synthesized getter indexes directly without the widening cast. Verdict-neutral
  by design (v5 == v4 arm), structural truth for future body synthesis.
  A binding-staleness lesson was enforced live: per-arm signatures MUST be
  mechanically re-derived after any signature change - a stale v3 binding in the
  spec was caught and fixed by derivation, not by hand.
- **Lead 4**: harness event-identity layer - each side's logs resolve against
  their OWN event table (candidate: declared alias events; reference: the
  published fixture ABI, since the reference side is the true fixture runtime);
  comparison by canonical id (alias names carry `Event_<hex8>`) plus indexed
  args and data; unresolved topics fall back to raw comparison. Both tables are
  built for every stage because `run_probes` always collects both sides - the
  single-table version left reference events unresolved (found live via a
  debug run, fixed, all affected runs re-executed).

## Reviewer round (codex) - 3 findings, all adopted

1. P1 length check restored in `event_matches` (zip could ignore trailing steps).
2. P2 alias-id extraction scoped to the real `Event_<hex8>` convention.
3. P2 the first-k-indexed heuristic is now recorded per edit as an assumption
   (positions are not derivable from counts alone).

Post-fix code reproduces the sealed v6 verdict (4/4+2/2 re-verified). Suite
201/201. With this, every recorded fixture is verdict-perfect with events,
strict evidence, and mutant-audited checks - zero LLM at any stage.
