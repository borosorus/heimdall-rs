# Recorded evaluation results

Committed runs are evidence snapshots. They are not CI inputs, and a single run does not establish
general model quality. Do not reuse a run directory; the harness rejects nonempty output
directories so saved evidence cannot be silently overwritten. Scratch `work/` directories are
ignored.

## `modern-advanced-*` — multi-step investigator prototype

Evaluation-only prototype for divide-and-conquer behavioral rewrites driven by black-box probes.
`evaluation/scripts/run_investigator.py` splits a compilable LLM candidate into complete function
units, deterministically clusters them by shared storage/events/errors and internal calls, asks a
model to state hypotheses and request opaque-entrypoint probes against the reference runtime, then
rewrites one cluster at a time from raw observations. `whole-investigator` and `chunked-one-shot`
are controls.

Model `dsv41`, temperature `0`, seed `1`, 1,200-second timeout, one investigation round per
cluster, at most 8 probes per cluster. `r1`/`r2` used a 32,768-token completion budget and an
eight-call cap; `r3` used 49,152 tokens and a twelve-call cap after the accounting fix. Each run
started from the same compilable whole-contract candidate
(`modern-advanced-whole-v1/modern-advanced/llm1.sol`) and used the same spec, setup and withheld
sets.

| Run | Mode | Calls | Completion tokens | Wall time | Feedback | Withheld | Merge |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `modern-advanced-whole-v1` | existing whole pass | 1 | not reported (65,536 cap) | ~412 s | 5/10 | 2/4 | — |
| `modern-advanced-chunked-one-shot-v1` | 3 clusters, no probes | 3 | 4,815 | ~65 s | 5/10 | 2/4 | all applied |
| `modern-advanced-investigator-r1` | 3 clusters, probes, first prompts | 8 | 129,893 | ~1,363 s | 5/10 | 2/4 | cluster 1 dropped on compile failure |
| `modern-advanced-investigator-r2` | same, prompts with ABI-word and mutability guidance | 9 | 169,008 | ~1,934 s | **10/10** | **4/4** | all 3 clusters compiled |
| `modern-advanced-investigator-r3` | same prompts, fixed accounting, larger budget | 6 | 61,551 | ~847 s | **10/10** | **4/4** | all 11 units applied, compiled ABI dispatch verified |

The `llm_calls` and `completion_tokens` values in the saved investigator `metrics.json` files for
`r1` and `r2` undercount HTTP attempts: the client charged a fallback attempt only when it returned
parseable content, so truncated `finish_reason=length` attempts were free. Recounting every saved
`*-response.json` gives the table numbers and is preserved in
`investigator-accounting.json`; `r2` therefore exceeded its configured eight-call limit. The
accounting bug is fixed: every attempt is charged, requested tokens are capped to the remaining
budget, and the per-cluster limit bounds HTTP attempts rather than logical calls. `r3` was run with
the fixed accounting and its saved metrics are the authoritative counts.

`r1` and `r2` share the same source, spec, model settings and probe budget. `r2` adds ABI-word
observation fields and prompt guidance (return-shape decoding, payable evidence, dispatch-identity
rule), plus merge-gate guards that reject dispatch-signature changes and record compile
diagnostics. The gate also checks that every applied rewrite still exposes its original ABI
signature in the compiled artifact; `r3` was launched before that check existed, and a post-hoc
check of its compile record found all 11 signatures present. `r1` dropped one cluster because its
rewrite used an invalid `uint256(int-literal)` address mask; the gate preserved the original
functions and recorded the failure. `r3` repeats `r2`'s prompt set with the fixed accounting and
applied all 11 proposed units. `r2`/`r3` fixed the three observed failure families:

- setters were `payable`, so a value-bearing call succeeded where the reference reverted; rewrites
  made them non-payable after seeing that evidence;
- `getAllValues` returned packed bytes, while observation showed a five-word ABI layout; the rewrite
  returned `(uint256, uint256, uint256, address, uint256)` reproducing the observed words;
- `setNumber`/`setBool` emitted the reference-visible events again.

### Measurement details and limitations

- Matched means every compared field agrees: status, read return/revert data, contract balance, and
  setup. `compare_events` is disabled, so event mismatches are reported but not gated; `r2` and
  `r3` still show event mismatches and are not evidence of event fidelity.
- The compiled candidates match 0/14 reference selectors. Behavioral binding is per-function: the
  spec supplies the candidate signature and the harness calls the candidate through its own
  selector, so interface compatibility is not claimed.
- The `getAllValues` rewrite reproduces the observed word layout for the measured probes, which all
  have an empty stored string. It returns a static five-word tuple rather than a true
  `(uint256, bool, string, address)`; non-empty string tail bytes are unmeasured and not claimed.
- `r2` and `r3` are model samples on one fixture, and the improved prompts were chosen after seeing
  `r1` failures. They are a measured improvement over the saved runs, not a general or unbiased
  estimate. Replays can differ even with the same seed and temperature.

### Synthetic-large: why there is no investigator score

`synthetic-large` has an exact pinned build, a 7,864-byte runtime, and 25 reference functions, but
no starting candidate suitable for the investigator. Three independent blockers were observed:

- The deterministic source does not compile (`uint0` parameters, storage declared as `bytes` or
  `bytes32` where the logic needs `uint256`, undeclared diagnostics), and its ABI inference drops or
  adds parameters: `setLimits` has one parameter instead of two, `setName` has two instead of one,
  and `allowance`/`transferFrom` are missing parameters. A compliant repair cannot recover the
  missing parameters because the reference ABI and source are withheld from the model.
- The whole-contract LLM pass returned the literal string `"..."`. The response passed the old
  nonempty check and was reported as applied. `AnnotatedContractResponse::validate` now also
  requires a `contract` declaration, so this response is recorded as a failure and the deterministic
  baseline is retained.
- Two bounded whole-source compile-repair attempts consumed their entire completion budgets
  (49,152 and 131,072 tokens) on reasoning and returned no source content. Whole-contract repair is
  therefore not a viable bootstrap at this scale with this model; cluster-scoped work is.

The investigator still requires a compilable, dispatch-valid seed. No synthetic-large score is
claimed. The next useful step is a cluster-level repair path (or a decompiler fix for parameter
inference), not another whole-contract prompt.

### Supported claim

On `modern-advanced`, starting from a compilable whole-contract candidate, a bounded three-cluster
investigator (`r3`, fixed accounting) requested 24 raw probes and rewrote all 11 functions. It fixed
all seven previously failing sequences (five feedback, two withheld) without feedback or withheld
regression, at six HTTP attempts and 61,551 completion tokens in ~847 seconds. The unchanged whole
pass and a no-probe one-shot chunking control both scored 5/10 feedback and 2/4 withheld.

It does **not** establish general improvement across contracts, event fidelity, non-empty dynamic
returns, interface compatibility, or that probes are necessary versus prompt changes alone. The
prompt changes and the probe evidence are confounded, and the single fixture and single model
sample remain the main limitations.

### Reproduce

```bash
# 1. Compilable starting candidate: an existing Heimdall LLM pass.
./target/release/heimdall --no-update-check decompile evaluation/fixtures/modern-advanced/runtime.hex \
  --include-sol --skip-resolving --default \
  --llm-postprocess --llm-base-url http://127.0.0.1:8000/v1 --model dsv41 \
  --llm-response-format auto --llm-max-tokens 65536 --llm-timeout 1200 \
  --output /tmp/heimdall-eval-whole/modern-advanced

# 2. Investigator run (writes prompts, calls, merge compiles, metrics, candidate.sol).
python3 evaluation/scripts/run_investigator.py \
  --source /tmp/heimdall-eval-whole/modern-advanced/decompiled.sol \
  --spec evaluation/tests/modern-advanced.json \
  --output-dir /tmp/heimdall-investigator/modern-advanced-investigator-r3 \
  --mode chunked-investigator --candidate-label whole \
  --llm-base-url http://127.0.0.1:8000/v1 --model dsv41 \
  --max-tokens 49152 --timeout 1200 \
  --max-calls 12 --max-investigation-rounds 1 --response-format auto

# 3. Behavioral differential against the reference runtime.
python3 evaluation/scripts/run_behavior.py \
  --spec evaluation/tests/modern-advanced.json \
  --baseline /tmp/heimdall-eval-whole/modern-advanced/decompiled.baseline.sol \
  --candidate /tmp/heimdall-investigator/modern-advanced-investigator-r3/candidate.sol \
  --candidate-label chunked-investigator \
  --run-id modern-advanced-investigator-r3
```

The saved run directories retain the candidate, investigator metrics, and accounting recount as
`investigator-candidate.sol`, `investigator-metrics.json`, and `investigator-accounting.json`.
Raw prompts and model responses are intentionally not included.

## `modern-math-helper-investigator-v6` — second fixture, stateful probes

Independent replication on a second fixture. Model `dsv41`, temperature `0`, seed `1`, 49,152
completion tokens, 1,800-second timeout, one investigation round, at most 8 HTTP attempts. The
starting candidate is the saved `behavior-multi-v2/modern-math-helper/llm1.sol`, which scores 7/10
feedback and 4/5 withheld: its setter is `payable` and its multiplication returns `0` on overflow
where the reference reverts with an arithmetic panic.

| Stage | Feedback | Withheld | Calls | Completion tokens | Wall time |
| --- | --- | --- | --- | --- | --- |
| `llm1` (start) | 7/10 | 4/5 | — | — | — |
| `investigator-v6` | **10/10** | **5/5** | 5 | 26,641 | ~346 s |

The investigator formed two clusters for three functions, requested 16 probes (some multi-step), and
applied all three rewrites. The merged source compiled and all dispatch signatures were preserved.
It removed `payable` from the setter after a value-bearing send reverted, and changed multiplication
to checked `value * storedValue`, which reverts on overflow. No semantic feedback or withheld
regression was observed. The rewrite also dropped the multiplication event; `compare_events` is
disabled and the harness does not capture logs for these read calls, so event fidelity is unmeasured
and not claimed.

The saved run predates the no-evidence synthesis guard: cluster 2 returned an invalid round-1
response and its third unit was synthesized unchanged. A current replay skips synthesis for a
cluster with no valid investigation response, so it may report two applied units with the same
behavioral result.

### Stateful probes and the iterations that exposed them

A probe request is either one call or a `steps` array executed in order from one fresh snapshot
after the fixture setup. The overflow case requires `setMultiplier(max)` and `multiply(2)` in one
sequence, and the setter step must set `send: true` so its storage write persists; a static call
does not. Earlier exploratory runs that used single calls, or multi-step probes with a static
setter, scored 9/10 feedback and 4/5 withheld: they fixed the payable defect but never observed the
overflow revert. Those iterations are not retained as committed runs. `v6` is the measured result;
the safeguard is encoded in the prompt context and covered by unit tests for multi-step validation.

### Measurement details

- Events are not gated (`compare_events` is disabled), and the compiled candidate does not match
  the reference selectors; binding is per-function through the candidate signature, as in the other
  investigator runs.
- The withheld set has five sequences and is fixture-local. It checks that the rewrite did not only
  fit the feedback observations, but it is not an unbiased generalization test.
- This is one model sample on a small second fixture. The prompt and probe-sequence changes were
  made after observing earlier failures, so they are part of the method rather than an independent
  variable. The `modern-advanced` `r3` result remains the primary evidence; this run shows the same
  approach can remove two different defect families on another fixture.

### Supported claim

On `modern-math-helper`, starting from the saved 7/10 feedback and 4/5 withheld `llm1` candidate,
the investigator removed the payable-setter and unchecked-overflow defects and reached 10/10
feedback and 5/5 withheld at five HTTP attempts and 26,641 completion tokens, with no semantic
regression on the measured sequences. It does not establish event fidelity, interface
compatibility, or general improvement across contracts.

### Reproduce

```bash
python3 evaluation/scripts/run_investigator.py \
  --source evaluation/results/behavior-multi-v2/modern-math-helper/llm1.sol \
  --spec evaluation/tests/modern-math-helper.json \
  --output-dir /tmp/heimdall-investigator/modern-math-helper-investigator-v6 \
  --mode chunked-investigator --candidate-label llm1 \
  --llm-base-url http://127.0.0.1:8000/v1 --model dsv41 \
  --max-tokens 49152 --timeout 1800 \
  --max-calls 8 --max-investigation-rounds 1 --response-format auto

python3 evaluation/scripts/run_behavior.py \
  --spec evaluation/tests/modern-math-helper.json \
  --baseline evaluation/results/behavior-multi-v2/modern-math-helper/baseline.sol \
  --candidate /tmp/heimdall-investigator/modern-math-helper-investigator-v6/candidate.sol \
  --candidate-label chunked-investigator \
  --run-id modern-math-helper-investigator-v6
```

The saved run directory retains the investigator candidate and metrics as
`investigator-candidate.sol` and `investigator-metrics.json`. Raw prompts and responses are not
included.

## `behavior-multi-v2` and `behavior-multi-simple-v2` — multi-defect repair with withheld probes

Model `dsv41`, temperature `0`, seed `1`, 32,768 completion tokens, 600-second timeout. Both runs
used one repair request (`repair-1`); the second allowed round was not needed. Reference runtime and
ABI came from the committed fixtures; candidate sources were separate Heimdall LLM passes over the
same runtimes.

| Fixture | Solc | Feedback sequences | Withheld sequences | Baseline | `llm1` | `repair-1` |
| --- | --- | --- | --- | --- | --- | --- |
| `modern-simple` | 0.8.22 | 8 | 5 | compile blocked | 7/8 feedback, 4/5 withheld | 8/8 feedback, 5/5 withheld |
| `modern-math-helper` | 0.8.30 | 10 | 5 | compile blocked | 7/10 feedback, 4/5 withheld | 10/10 feedback, 5/5 withheld |
| **Total** | | **18** | **10** | **0 executable** | **22/28** | **28/28** |

The accepted repairs fixed six `llm1` failures across the two fixtures: four feedback failures and
two withheld failures. No feedback regression and no withheld regression was observed.

- `modern-simple`: the setter was payable, so a value-bearing call succeeded and stored the value
  where the reference reverted. The repair removed `payable`.
- `modern-math-helper`: the setter was payable, and `multiply` used unchecked arithmetic and
  returned `0` on overflow where the reference reverted. The repair removed `payable` and restored
  checked multiplication. This also fixed the withheld overflow case without seeing it in the
  prompt.
- `modern-math-helper` uses a `setup` trace (`setMultiplier(2)`) before every probe, because the
  published runtime is deployed with empty storage. Setup calls are executed and compared on both
  sides; they are included in repair prompts and are not free state.

### Measurement details

- A matched sequence means every compared field agrees: success/revert status, read return data,
  read revert data, contract balance, and setup behavior. Events are compared only when
  `compare_events` is enabled; it is disabled in both specs.
- Both baseline sources failed Solidity compilation, so they have no behavioral score. The change
  from baseline to `llm1` is therefore unmeasured.
- Interface compatibility remains unrelated to selection: compiled candidates match 0/6 reference
  selectors. `modern-math-helper` also has no bound two-argument `add(uint256,uint256)`, so that
  reference function is not behaviorally tested; its selector appears in the interface report as
  missing.
- `modern-simple` sends are mined transactions; their return/revert payloads are not captured.
  `modern-math-helper` uses `eth_call` for multiply so return/revert data is captured, but event
  logs from those calls are not.
- The withheld sets are small and fixture-local. They check that the repair did not only memorize
  the feedback examples; they are not an unbiased generalization test.

### Supported claim

On two fixtures and 28 predefined sequences, one bounded repair request per fixture removed all six
observed `llm1` behavioral mismatches, including two withheld cases, with no regression on the
measured feedback or withheld sequences. This is evidence that black-box counterexamples can
repair localized logic and mutability defects in decompiled Solidity.

It does **not** establish general behavioral improvement, baseline-to-LLM improvement, full
function coverage, event fidelity, constructor correctness, or interface compatibility. The
`add` mismatch and small fixture-local withheld sets remain explicit gaps.

### Reproduce

```bash
python3 evaluation/scripts/run_behavior.py \
  --spec evaluation/tests/modern-math-helper.json \
  --baseline evaluation/results/behavior-multi-v2/modern-math-helper/baseline.sol \
  --candidate evaluation/results/behavior-multi-v2/modern-math-helper/llm1.sol \
  --run-id behavior-multi-replay \
  --repair --repair-rounds 2 \
  --llm-base-url http://127.0.0.1:8000/v1 \
  --model dsv41 --seed 1 --temperature 0 --llm-timeout 600

python3 evaluation/scripts/run_behavior.py \
  --spec evaluation/tests/modern-simple.json \
  --baseline evaluation/results/behavior-multi-simple-v2/modern-simple/baseline.sol \
  --candidate evaluation/results/behavior-multi-simple-v2/modern-simple/llm1.sol \
  --run-id behavior-multi-simple-replay \
  --repair --repair-rounds 2 \
  --llm-base-url http://127.0.0.1:8000/v1 \
  --model dsv41 --seed 1 --temperature 0 --llm-timeout 600
```

Sampling and server behavior can differ even with the same seed and temperature. Treat a replay as
a new result, not as proof that the saved run reproduces bit-for-bit.

## `behavior-repair-v4` — earlier single-defect pilot

This run predates baseline evaluation, withheld probes, and multi-failure repair. It remains as a
pilot record; the two runs above supersede it for measurement claims.

Fixture `modern-simple`, model `dsv41`, temperature `0`, seed `1`, 32,768 completion tokens,
600-second timeout, Solidity 0.8.22. The reference runtime and ABI came from the committed fixture;
the candidate was an earlier Heimdall LLM pass over the same runtime.

Files in [`behavior-repair-v4/modern-simple/`](behavior-repair-v4/modern-simple/) include the
deterministic baseline, the original `llm1.sol`, the repaired `llm2.sol`, compile and selector
reports, per-step probes, the exact repair prompt/request/response, and `metrics.json`.

### What happened

`llm1` compiled and passed seven of eight semantic probes. The only failure was `set_with_value`:
the reference `set(uint256)` is nonpayable and reverts when called with 1 wei, while the candidate's
setter was declared `payable`, accepted the value, and stored it.

The single repair request changed exactly that:

```diff
-    function Unresolved_60fe47b1(uint256 arg0) public payable {
+    function Unresolved_60fe47b1(uint256 arg0) public {
```

`llm2` compiled, fixed the target, introduced no semantic regression, and passed all eight
semantic probes. The harness selected `llm2`.

| Check | `llm1` | `llm2` |
| --- | --- | --- |
| Candidate compiled | yes | yes |
| Semantic probes matched | 7/8 | 8/8 |
| Semantic regressions | — | none |
| Configured repair target fixed | — | yes |
| Reference selectors matched by compiled candidate | 0/2 | 0/2 |
| Event mismatches (events not gated) | 6/8 probes | 5/8 probes |

The two compiled candidate selectors are `0x2aed481d` and `0x6d619daa`; the reference selectors are
`0x60fe47b1` and `0x6d4ce63c`. This is expected: generated names such as
`Unresolved_60fe47b1(uint256)` and `storedValue()` hash to different selectors than `set(uint256)`
and `get()`. The harness therefore executes each candidate through its own selector instead of
pretending the two interfaces are interchangeable. Interface compatibility is reported separately
and remains zero.

Event topics also still differ on five probes. That was outside the configured repair gate, so the
run does not claim event-level fidelity. Return and revert payloads from mined transactions are not
captured; send steps are compared by status, balance, and optionally logs.

### Controls exercised during development

These checks used the same harness and were not all retained as committed run directories:

| Control | Observed outcome |
| --- | --- |
| Repaired candidate | zero semantic failures |
| Deliberately wrong write behavior | five semantic failures |
| Setup mismatch followed by matching reads | probe rejected (unit test) |
| Multi-defect repair | fixed three feedback failures in one request |
| Non-Solidity candidate | compile rejection, exit code 2 |
| Event comparison enabled on the repaired candidate | five event mismatches reported |
| Reusing a nonempty run ID | rejected, exit code 1 |
| Repair configuration missing | `repair_error` recorded, `llm1` retained |
| Mock response with empty `choices` | `repair_error` recorded instead of a crash |
| Mock response with non-string `source` | `repair_error` recorded instead of accepting it |
| Mock event regression | original candidate retained, regression reported |

### Supported claim

On one fixture, one model sample, one localized behavioral defect was diagnosed from raw-calldata
probes and repaired by a single bounded LLM request without semantic regression. The repair also
left interface and event compatibility unchanged.

This does **not** show that LLM repair generally improves behavioral fidelity, that compiled
candidates are interface-compatible, or that compile success implies correctness. The sample is one
fixture and one model run; broader fixtures, repeated seeds, event gating, and constructor-aware
deployment are required before making a general claim.

### Reproduce

The committed `repair-request.json` contains the exact prompt-independent request body, and
`repair-prompt.txt` contains the exact prompt. Re-running requires Foundry, the committed fixture,
a deterministic baseline source, the saved `llm1.sol`, and an OpenAI-compatible endpoint serving
the same model. Use a new run ID:

```bash
python3 evaluation/scripts/run_behavior.py \
  --spec evaluation/tests/modern-simple.json \
  --baseline evaluation/results/behavior-repair-v4/modern-simple/baseline.sol \
  --candidate evaluation/results/behavior-repair-v4/modern-simple/llm1.sol \
  --run-id behavior-repair-replay \
  --repair \
  --llm-base-url http://127.0.0.1:8000/v1 \
  --model dsv41 --seed 1 --temperature 0 --llm-timeout 600
```

Sampling and server behavior can still differ even with the same seed and temperature. Treat a
replay as a new result, not as proof that the saved run reproduces bit-for-bit.


---

# State of the evaluation (condensed 2026-11-11)

Single model throughout (`GLM-5.3-Flash`, local OpenAI-compatible endpoint), one sample per stage,
every claim grounded in committed artifacts under `evaluation/results/`. The per-run directories
(ledgers, prompts, responses, per-attempt probe results, harness metrics) are the audit trail; the
day-by-day campaign narrative that used to live here is distilled below - each closed question
keeps its one-line verdict and its evidence pointer.

## Standing verified results

| Fixture / candidate | Feedback | Withheld | Evidence |
| --- | --- | --- | --- |
| `modern-math-helper` unit-loop (`modern-math-helper-unitloop-v1`) | **10/10** | **5/5** | loop ledger + independent harness `verify/` |
| `modern-math-helper` pre-loop (`behavior-multi-v2`) | 7/10 | 4/5 | harness metrics in run dir |
| `synthetic-large` behavior-unit v2 (`synthetic-large-behavior-unit-v2`) | **4/12** | **1/4** | harness metrics; candidate sha `4562a565...` |
| `synthetic-large` seed-v2 control | 0/12 | 0/4 | same harness, same probes |
| `synthetic-large` seed-v3 (packed-scalar recovery) | 4/12 | 1/4 | `synthetic-large-seed-v3/alone`, passing set byte-identical to v2 |

The unit-repair loop is 2-for-2 across fixtures and produced the two largest gains recorded
(synthetic 0/12->4/12 across its campaign series; math-helper 7/10->10/10 + 4/5->5/5 in one
3-call run, first cross-fixture demonstration).

## Proven mechanisms (kept, part of the tooling)

- **Unit-scoped behavior repair** (`repair_behavior_units.py`): failing-probe first-differing-
  observation -> owning unit -> rewrite -> full re-probe, transactional acceptance (whole-probe
  win or strict divergence decrease; rollback on regression / lost binding / changed exact
  observation / ABI loss / locationless compile failure), stalled-target rotation, `--only`
  focus, joint multi-unit rewrites, `--max-transactions` sizing (must cover the failing count).
- **Prompt ingredients with measured value**: real per-step observations, entrypoint roster with
  candidate signatures, compile diagnostics + verdict reasons on retry, state map, return-shape
  hints, calldata-coverage table, sibling-probe constraint rows (preserve-exactly / first
  divergence), accepted-rewrite examples (`--accepted-rewrite-context`, provenance-gated).
- **Deterministic seed prep** (`prepare_candidate.py`): placeholders, declarations, arity,
  slot-view unification, packed-scalar recovery - zero-LLM, conservative, idempotent, fully
  recorded; plus `repair_units.py` diagnostics-driven compile repair.
- Suite: 166 tests (`python3 -B -m unittest discover -s evaluation/tests`).

## Closed questions (kill list - do not retry without a new preregistered mechanism)

- Whole-source harness repair at synthetic-large scale does not compile; unit-scoping is the
  answer (`synthetic-large-inv-r3-repair`).
- Investigator merge lottery: gate hardening + per-cluster solo merge made merges reliable but
  behavior-neutral; dropped-cluster quality was the constraint (`synthetic-large-inv-v2-*`).
- Seven prompt variants (incl. counter-placement, coverage table, shape hints) each failed to
  move 3/12: plateau was unit synthesis, not prompt phrasing (campaigns 8-15 dirs).
- Joint mode, focus filter, rotation: mechanically verified, three null campaigns on the deposit
  stub (18-20; `behavior-repair-{deposit-solo,deposit-joint,unfocused}`).
- Sibling-conditioning (worked-example transfer): mechanism verified end-to-end, null on
  synthetic at 12 calls (`behavior-repair-sibling-conditioned`); part of the winning math-helper
  run, so retained as tooling.
- Constraint evidence rows: fired in 21/24 prompts, rejection anatomy unchanged on synthetic
  (`synthetic-large-seed-v3/behavior-repair-constraints`); observation visibility is not the
  binding constraint there.
- Packed-scalar seed recovery: score-neutral alone, shifted the rejection mode
  (`synthetic-large-seed-v3`); ships as prep tooling, not a behavioral win.

## The one open synthetic blocker, precisely

`deposit` must pass below-min, valid, and above-max in one body. Its current above-max pass is
the always-reverting stub matching by accident; every measured rewrite breaks it while adding the
success path (or leaves divergence unchanged). Five campaign families (~130 attempts) converge on
this single synthesis: guard bound + pause interplay + success path, with the max bound living in
the aliased limits slot pair. The loop, acceptance, and evidence machinery are sound and tested;
what remains is one hard multi-regime unit synthesis on one fixture.

## Reproduce

```bash
# behavior loop on the recorded synthetic seed
python3 evaluation/scripts/repair_behavior_units.py \
  --spec evaluation/tests/synthetic-large.json \
  --candidate evaluation/results/synthetic-large-behavior-unit-v2/synthetic-large/llm1.sol \
  --baseline evaluation/results/synthetic-large-baseline-v1/synthetic-large/baseline.sol \
  --candidate-label seed-v2 --output-dir /tmp/rbu \
  --llm-base-url http://127.0.0.1:8000/v1 --model GLM-5.3-Flash \
  --only Unresolved_b6b55f25 --max-calls 24 --max-transactions 24
# independent verdict
python3 evaluation/scripts/run_behavior.py \
  --spec evaluation/tests/synthetic-large.json \
  --baseline evaluation/results/synthetic-large-baseline-v1/synthetic-large/baseline.sol \
  --candidate /tmp/rbu/candidate.sol --candidate-label seed-v2 --run-id verify
```

Replays are new samples, not bit-for-bit reproductions; committed per-stage artifacts are the
primary evidence. Full campaign history lives in this directory's per-run artifacts and in git
history.

## Fresh levers after consolidation (2026-11-11, later)

History squashed to two commits; chronicle condensed above. Two new zero-LLM decision mechanisms:

1. **State-distinguishability diagnostic** (`state_distinguishability.py`, evidence
   `synthetic-large-seed-v3/synthetic-large/state-diagnostics/paired-histories.json`): paired
   setup histories differing in one calldata word, per-side selectors resolved from the
   decompiler's name-embedded selector suffixes, plus a deposit regime map. Reference truth on
   empty limits `(0,0)`: `deposit(0)` succeeds; `100`, `1000001` and paused-deposit revert with
   `CustomError_3261c792` (never bare). Reference `setLimits(10,x)` itself reverts in the empty
   state.
2. **Enumeration synthesis** (`enumerate_deposit.py`, evidence
   `synthetic-large-seed-v3/synthetic-large/enum-synthesis/`): enumerate deposit bodies (guard
   form x bound source x effect set), compile, execute under snapshot isolation, accept the first
   matching the reference column on all four regimes. Winner = candidate 0 of 8:
   `if (store_c > arg0 || arg0 > store_d) { revert CustomError_3261c792(); }` - no effect path
   needed; the measured reference success delta on reachable states is zero.

Harness verdict on the synthesized deposit (`enum-synthesis/harness-verify`): compiles; aggregate
4/12 + 1/4 unchanged - the deposit unit is regime-exact, but those probes also read sibling units
(supply/stats aliases) inside the same sequences. Recorded next step: point the same enumerator at
the sibling readers (`totalSupply`/`var_c`, `getStats` composition) - the machinery extends as-is,
still zero-LLM until bodies exist for repair. Standing results unchanged: synthetic 4/12+1/4,
math-helper 10/10+5/5.

### Writer-first chain, numerically closed (2026-11-11, latest)

The harness applies the spec's global setup (`initialize; setLimits(1,1000000); setFee; setName;
mint`) per side. The candidate setter (`Unresolved_c4590d3f`, one declared param) truncates that
call to `setLimits(1)`: candidate state lands `(store_c=1, store_d=1)` vs reference
`(1, 1000000)` - verified in `enum-synthesis/harness-verify` probe records (candidate deposit
calldata `0x1af2760b...64`, ok=False at step0 while reference ok=True). Consequence: no deposit
guard can pass 100 and revert 1000001 against `store_d=1`; the regime-exact deposit body from the
enumeration is necessary but cannot score until the setter captures the surplus calldata word.

Recorded next enumeration (deterministic, no LLM): writer variants for `Unresolved_c4590d3f` that
read the second word as a `msg.data` suffix (`uint256(bytes32(msg.data[0x24:0x44]))` family),
verified by the same regime machinery with per-side setup applied; the deposit enumeration then
re-runs on the repaired state. Only after both, the LLM loop re-enters for whatever remains.
