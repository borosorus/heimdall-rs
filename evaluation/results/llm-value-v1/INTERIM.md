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
