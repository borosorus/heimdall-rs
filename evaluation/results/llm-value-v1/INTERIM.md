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

## Stuck-breaker trial 1 (deviation 3) - THE LOOP, PROVEN END TO END (2026-11-13)

Fixture: modern-math-helper; patient: the 18-stage seed (compile-fail 2271, gates abstain).

1. RESCUE: repair_compile, effort low - compiling candidate in 2 of 4 budgeted calls
   (`stuck1-math-helper/rescue/`; the schema needs explicit --contract/--solc, recorded).
2. VERDICT: harness stuck1-v1 - **7/10 fb + 5/5 wh** from a fully stuck seed (criterion
   exceeded; wh 5/5 = generalization signal).
3. DISTILLATION: the semantic diff is TWO rules -
   a. comparison-parens: the seed's `(X == 0) | Y == Z` misparses (solc binds == tighter
      than |); the faithful form wraps the rhs comparison AND doubles the operator
      (0.8 refuses bool|bool) -> `((X == 0) || (Y == Z))` - the model's exact fix;
   b. view-emit-relaxation: `view` unit whose body emits -> drop `view` (8961); the
      reverse of the recorded mutability stage.
   Both implemented as candidate stages OUTSIDE PREPARE_STAGES (freeze deferred, batch
   precedent); parser-span based after the masked-regex splice took two corrected
   attempts (double-tail bookkeeping; comment `view` false match - both recorded).
4. GATE: replay on seed PASS; idempotent both stages and composed, order-independent
   PASS; suite green with 5 new pins (StageCandidateTests) PASS.
5. REPLICATION: the pure deterministic composition (candidate-stages-only.sol) scores
   **7/10 fb + 5/5 wh - IDENTICAL to the model's rescue** (stuck1-v2). Zero calls
   forever after.

VERDICT: the abstention-boundary thesis holds on a real wart - the LLM's value was the
SPECIFICATION of two new deterministic rules, delivered at 2-call cost, then replaced
by them entirely. The stage candidates (+ their future Rust mirrors) await the batch
freeze with the parity discipline. This is the standing playbook for every subsequent
stuck case: rescue once, distill, gate, freeze in batch.

## Stuck-breaker trial 2 (deviation 4) - doctrine run, partial break (2026-11-13)

Fixture: modern-advanced; base: re-frozen seed 36704d95... (compile 6933; trial-1 stages
0 edits - distinct wart, as designed).

1. RESCUE: ONE call (of 4). The model resolved the runtime-memory-slice member call
   (`address(store_f).Unresolved_(memory[..])`) to the contract's own annotated unit -
   `store_f.call(abi.encodeWithSignature("Unresolved_c6888fa1(uint256)", arg0))`. The
   selector occurs exactly ONCE in the seed; the binding is semantic inference, the
   strongest intent evidence yet (it used the decompiler's own annotations + call-site
   context, no oracle).
2. COMPOSE (doctrine): the trial-1 finisher stages fire 2 NEW edits on the rescue output
   (comparison-parens finds sites the rewrite exposed) - composition is live, candidate
   of record = composed artifact. First compose attempt broke a for-header (the stage's
   rhs scan missed `;` as a clause terminator) - fixed in the stage, trial-1 gate
   re-verified green, suite green.
3. VERDICT (stuck2-v1): compile True, **1/10 fb + 0/4 wh** - stuck broken (criterion
   met), far from trial-1's sweep. Residue shape: the seed comment marks the site
   `// delegatecall`; the rescue used `.call` - the call/delegatecall storage-context
   distinction is the prime suspect for the remaining 9.
4. DISTILLATION: candidate rule "dynamic-selector member call -> resolution against the
   contract's own annotated units", OBSERVATION-grade: the deterministic selector-source
   (slice-prep constant vs unit table) is NOT yet pinned, and the call/delegatecall
   choice needs the opcode trace the seed already carries as comments. Promotion gate
   deferred until both are pinned - honest per the gate rules.

TRIAL PAIR VERDICT: the loop reproduces (2/2 stuck cases broken at 1-2 calls); the
distillate quality varies with wart class - arithmetic/typing warts distill cleanly
(trial 1), control-flow/semantic warts leave a longer tail (trial 2). Doctrine holds:
both trials' value is now candidate-stage material; the LLM layer exits each fixture
after the rescue.

## Stuck-breaker trial 3 (deviation 5) - partial: compile yes, behavior budget-bound (2026-11-13)

Fixture: synthetic-large (16 probes, ERC20-shape storage semantics). Base seed+cand
77b2d61e.../1 edit; 8-diagnostic coercion family.

1. RESCUE: 2 calls -> compiling. The diff is the predicted coercion family PLUS bolder
   moves: storage REDECLARATION (bytes->uint256 for slots the seed typed as dynamic),
   a return-shape change (bool->bytes memory on c23f85d6), address-in-integer wraps
   (uint256(uint160(..)) x4 sites), conversion-wrapped truthiness (!T(x)->T(x)==0,
   return T(x)->!=0), require(true) elisions.
2. COMPOSE: finishers 0 new edits (the rescue already emits parenthesized forms -
   the stages and the model CONVERGE on form). Composed candidate compiles.
3. VERDICT stuck3-v1: compile True, 0/12 fb + 0/4 wh. Behavior round (3 calls, 2 txn
   budget): NO accepted transaction, 0/12 holds. Criterion (>=1 fb) NOT met at the
   4+4 budget - recorded as the trial's result, not polished over.
4. Root-cause shape: the fixture's ENTIRE storage semantic layer (init flow, mapping
   accounting, packed flags) diverges; single-unit probe repair cannot bridge
   whole-contract state semantics at this budget.
5. Tooling fixed en route: run_behavior evaluate_stage reference-event-table None
   crash (latent since the events feature; hdwallet's eventless probes masked it) -
   one-line coalesce, suite-green, this trial's event-emitting probes exercise it.

TRIAL TRIAD VERDICT: 2/3 full breaks (trial 1 sweep, trial 2 entry) + 1 honest partial.
The loop's economics hold on mechanical warts; whole-contract semantic gaps need either
a bigger budget or the deterministic semantic layers first. Candidate-stage ledger
gains three OBSERVATION-grade families (address-integer, bytes32-integer, !T(x)
truthiness) - promotion deferred; no freeze pressure.
COHERENCE AUDIT (user-directed) runs next against the full ledger.

## Coherence audit (codex, user-directed) - drift-detected, 3 corrections adopted (2026-11-13)

1. TRIAL-1 COST: ledger said 2 calls; rescue metrics say 3 (compiling on attempt 3).
   Corrected here; cost claims now quote metrics.json verbatim.
2. TRIAL-3 ROOT CAUSE - the audit's decisive catch: 0/12 was read as "whole-contract
   semantics too heavy" while the run's own artifacts showed 0/25 matched selectors with
   setup unbound. FIXED AND RE-RUN: the era-inherited bindings broke because the rescue
   RE-TYPED parameters (e.g. Unresolved_c4590d3f (uint256)->address); bindings rebuilt
   from the composed candidate's ACTUAL canonical declarations -> 25/25 available. The
   residual is now genuinely behavioral and NAMED: event data-shape divergence (the
   re-typed emits change indexed/data layout vs the reference ABI; visible in
   stuck3-v1 probe logs). Trial-3 verdict UPGRADED from semantic-null to
   interface-fixed-pending: the cheap explanation was real, half-consumed, and the
   rest has a concrete next target (event-shape rule: alias declarations must carry
   reference-equivalent indexing).
3. TRIAL-2 WORDING: "candidate-stage material" -> observation-grade until the gate
   passes; the rescue stands, the rule is not promoted.
4. Doctrine structure confirmed coherent (addition-first visible in all trials; arm-A
   legacy line no liability); interim ledger NOT a completion of the arm-A table or
   leads.md - those remain open preregistered deliverables.
5. Lead queue (audit-ranked, adopted): (a) trial-3 event-shape rule now FIRST;
   (b) trial-2 selector-source/delegate pin; (c) probe targeting after interface
   hygiene; (d) empty-response retry hardening (operational); (e) coercion families
   stay observation. Batch-freeze of trial-1's gate-green candidates awaits the
   Rust parity work, unchanged.

## Trial-3 round 2 + the unifying discovery (deviation 6) - closed for this cycle (2026-11-13)

DISCOVERY (the round's real product, deterministic, 0 calls): every decompiler alias id -
`Event_<hex8>` AND `Unresolved_<hex8>` - is keccak4 of the TRUE reference signature
(6/6 events verified via cast sig-event). Consequences:
- LEDGE-2 PIN RESOLVED: the selector source is the decompiler's own embedded id; the
  alias name is the candidate-dispatch identity (candidate space = keccak4(alias sig),
  reference space = true selector; the harness's dual-calldata is correct BY DESIGN -
  my earlier "calldata divergence" was a namespace misreading, corrected).
- NEW STAGE CANDIDATE event_shape_realign: alias event declarations re-indexed from the
  reference match where arity+types canon-match (5 realigned on synth; 2 typed/arity
  abstentions recorded). Gate green (replay/idempotence/pin test). Input-class note:
  consumes the fixture's published reference ABI as explicit sidecar (the same artifact
  the harness's reference side uses) - doctrine prune decision deferred.
Round-2 results, honest: event IDENTITY now matches both sides (v2 run), but behavior
round 2 (3 calls, 2-txn budget, correct bindings) finds NO accepted transaction - 0/12
stands. Trial-3 FINAL for this cycle: interface layer fully repaired (bindings 25/25,
event identity) via audit + deterministic stage; the residual is multi-call state
semantics (allowance/bookkeeping) that single-unit probe repair does not bridge at
~6 total behavior calls. Doctrine reading CONFIRMED with evidence: this fixture needs
its deterministic semantic layers (init/allowance invariants) before LLM rounds pay.
Suite 220. Leads after this cycle: trial-2 style pins DONE via the id discovery;
remaining: batch-freeze gate-green candidates (trial-1 pair + event-shape stage behind
the sidecar-input doctrine call), Rust mirrors, retry-hardening (operational).

## Batch freeze - trial-1 distillates promoted; program closed for this cycle (2026-11-13)

PROMOTED (planner go-with-fixes -> both fixes applied -> reviewer pass; single commit):
`comparison_parens` and `view_emit_relaxation` join PREPARE_STAGES as stages 19/20 in
both implementations (parity fixtures regenerated; suite 221 py / 196 decompiler rust).
Planner findings adopted BEFORE promotion: (1) overlapping-match skip - a rhs depth scan
swallows later chain links; each match now wraps at most once per sweep, residual inner
chains wrap on the next sweep to a stable fixpoint (3-chain pin both impls); (2) the
wrapped rhs is emitted from the ORIGINAL source slice, not the mask-blinded detection
copy (string-literal pin both impls).
- Positive control: 20-stage ladder over the recorded math-helper seed reproduces the
  accepted stuck1-v2 candidate BYTE-EXACT (sha16 c4516af7ced8c05e) - the pure-stage 7/10+5/5
  replicate is now the default pipeline behavior, zero model calls.
- No-regression proof by construction: both stages are zero-edit no-ops on all four parity
  corpora (erc20/blockreader/lighthouse/hdwallet) - promoted-ladder candidates there are
  byte-identical to the sealed 18-stage ones, so every recorded verdict stands; no matrix
  re-run owed.
NOT PROMOTED - event_shape_realign stays a candidate outside the ladder: no verdict delta
on any fixture (trial-3 null stands) and the reference-ABI sidecar input-class doctrine
call is parked. Promotion remains a mechanical step once a fixture proves the delta.
LLM PROGRAM STATE: the addition-on-top doctrine is fully banked - the ladder carries the
proven distillates; the LLM's remaining role is the abstention-boundary rescue on future
stuck fixtures (bounded, effort low, distill-and-exit). Negative results remain as the
trial sections above plus their receipt dirs; operational leads (retry hardening,
probe targeting) stay ledger-only until a stuck fixture needs them.
