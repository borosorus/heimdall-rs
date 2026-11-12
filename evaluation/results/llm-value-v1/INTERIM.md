# llm-value-v1 interim state (2026-11-12, arms A/B fixture 1 + tooling)

Recorded before the remaining fixtures; every number from run dirs in this tree.

## Arm A (legacy pass-1, hdwallet)
- effort max: single-shot 1200s TIMEOUT, honest fallback (armA/hdwallet, llm-report).
- effort low: APPLIED in 15.2s json-schema; candidate = structurally sound rewrite
  (unit names/selector comments preserved, helper factoring) but COMPILE-FAIL:
  yul `if/else` (no else in yul) (armA/hdwallet-low/armA-verdict.json).

## Effort sweep verdict (fixture 1)
low dominates: same-or-better results at 1/8th the latency; max adds timeout risk.
high (armB/hdwallet-compile-high): 0/3 compile at 2-4x latency - effort does NOT buy
compile correctness here.

## Arm B (bounded compile-repair, hdwallet)
- low/3 calls: 0/3 (armB/hdwallet-compile) - gate bug masked round-1 success.
- low/5 calls: 0/5 (armB/hdwallet-compile-r5); the FINAL residue is solc 7279 bare
  literal in packed encoding - verbatim the ladder's typed-packed-literals stage.
- high/3 calls: 0/3 (armB/hdwallet-compile-high).
The model diagnoses correctly (notes accurate) but emits one residual slip per round.

## Hybrid (LLM propose, ladder dispose) - THE convergence result
One ladder pass over the best repair output fires typed-packed-literals x2 and COMPILES
(hybrid/hdwallet-hybrid.sol). Harness verdict llm-hyb1: compile True, probes 0/8+0/2 -
the model's helper hallucinated a two-slot string layout (fixture is single-slot):
structure yes, semantics no. The ladder's own seed remains 8/8+2/2.

## Tooling fixed en route (committed)
- 09d9542 client: strip fences from the EMBEDDED source (envelope-only before).
- 5e50e9c repair gate: dispatch signatures = non-internal/private units; internal
  helpers are legal repairs (was: structurally unpassable with model helpers).

## NEW FINDING - latent ladder bug (pass2 truthiness rendering)
The bare branch emits `if((X) == 0))` - one close over (solc 6933, paren count 2/3,
minimal solc truth test green for `if((X) == 0)`). BLAST RADIUS: hdwallet/auditlog/ipfs
seeds each carry 1-2 such lines and FAIL standalone compile (verified); their batch
verdicts STAND (the rebuild-tool candidates rewrote the affected units, masking it);
lighthouse unaffected (0 occurrences). Comma branch likewise swaps `)`,`order (`0,)`
vs the correct `0),`). Correct forms pinned by the solc truth test above.
REMEDATION = standard freeze discipline: fix the Python f-string + Rust mirror,
re-derive parity fixtures + 3 seeds, re-run the verdict matrix + hybrid. NOT YET DONE
- recorded as the next unit; earlier eras remain valid history under the discipline.

## Re-freeze EXECUTED (2026-11-12, later same day) - pass2 rendering fix

The base-hygiene fix landed end to end per the freeze discipline:
- Python f-string + Rust mirror: `kw((X) == 0)` with the comma OUTSIDE the kw-paren
  (solc truth test pinned; both suites updated to the correct forms);
- parity fixtures re-derived (10 stage files across the 4 corpora) - Rust parity green;
- seeds re-derived: hdwallet `9b90533b…`, auditlog `ba81cd43…`, ipfs `58006406…`;
  lighthouse byte-UNCHANGED (`444d4083…`, zero pass2 sites);
- candidates re-derived with the RECORDED tools/args (hdw: string-slot setter+2 getters
  0x00; al: struct-array --auto; ipfs: pair-getter 6d4ce63c 0x00/0x01 + append
  IpfsHash/0x01 Description/0x00) into `refreeze2026-11-12/`;
- verdict matrix RE-RUN, IDENTICAL: hdw-refr4 8/8+2/2, al-refr4 8/8+2/2,
  ipfs-refr4 6/6+2/2, lighthouse stands as-is; hybrid re-derived under the fixed
  ladder (llm-hyb2): 0/8+0/2 - the two-slot-hallucination verdict unchanged.

CORRECTION to the interim wording above: standalone seed compile was never the
batch-2 acceptance (the rebuild candidates carry it, then and now). Under the fixed
pass2 the seeds STILL fail standalone on the NEXT pre-existing wart layer
(e.g. hdwallet 7407 `bytes storage` assignment) - unchanged historical state,
recorded as ladder leads, NOT part of this fix.

## Arm B-behavioral RESULT (deviation 2) - first positive LLM behavioral delta

Patient: the hybrid (0/8 fb). Tool: repair_behavior_units, black-box failing-probe
differentials only, acceptance = measured whole-probe progress + no regression.
Effort low. Outcome (armB/hdwallet-behavior, harness-confirmed llm-hyb3):

- fb 0/8 -> 1/8 (initial_empty flipped), wh 0/2 unchanged, 8 calls,
  202,214 completion tokens, ~35 min wall.
- The accepted txn-1 rewrite of the getter unit is the CANONICAL single-slot
  long-string read (keccak256(slot) leaf iteration, word loop, rounded
  free-pointer) - derived from probe I/O plus the source's own slot comments.
  ARM-C INTENT EVIDENCE: the model reconstructs storage-layout semantics from
  black-box observations, not just syntax.
- It did NOT repair the setter side: `count = 0x01 + (arg0 + arg0)` (the
  hybrid's own wrong update arithmetic) stands - the +1 is reader-only.
  Remaining 7 fb failures live in the setter/packing path.
- Operational: 2+ calls burned on empty responses ("response had no content");
  retry-order is where bounded budgets die.

ARM-C verdict on the lead-1 question: YES with measured cost - behavioral
intent is partially recoverable from pure I/O differentials (structure: strong;
arithmetic: weak). The ladder remains the 8/8 zero-call baseline; the LLM layer
is a bonus oracle as directed. Leads updated: (a) setter-packing repair class
(the residual is ONE arithmetic expression - a deterministic stage-19 candidate
via the gate); (b) empty-response retry hardening in the repair clients.

## Composition experiment (scout-checked) - the division-of-labor answer

Scout verdict on my "one arithmetic expression" stage-19 framing: existing-tool-covers -
the general setter repair IS rebuild_string_slot_accessors.SETTER (whole-unit replacement);
adopted, framing corrected in the ledger.

Composed candidate (LLM-repaired getter + tool-rebuilt setter, hybrid/hdwallet-hybrid-
final.sol): compiles; harness llm-hyb4 = 1/8 - NO further gain. Root cause: the LLM
getter reads `count`, shadow state the hybrid introduced and the tool's setter template
does not maintain - the two repairs interlock through LLM-introduced state, so
composition is NOT mechanical. The clean 8/8 path remains the pure deterministic
pipeline, which never needed shadow state.

FINAL arm-C synthesis for the llm-value question:
- LLM structural repair from black-box I/O: REAL (canonical layout reconstruction).
- LLM as composable pre-pass for deterministic semantic tools: NO as-is (shadow-state
  coupling); would require a whole-unit contract (tool owns every unit it touches).
- Efficiency: ladder 8/8 at zero calls remains the product; LLM layer = bonus oracle,
  confined to structure/intent hints, exactly as directed.
Residual leads: empty-response retry hardening; wh-informed (harness-side) probe
prioritization for repair targeting; nothing new deterministic - the stage-19 ledger
entry for this class is CLOSED (tool covers it).
