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

## synthetic-large: the first full large-contract pipeline run (2026-11-09)

End-to-end record for the 25-function, 7,864-byte `synthetic-large` fixture, one model
(`GLM-5.3-Flash` via the local OpenAI-compatible endpoint), one sample per stage. Every stage is
bounded and its artifacts are committed under `synthetic-large-*`.

| Stage | Mechanism | Outcome |
| --- | --- | --- |
| Deterministic baseline | `heimdall 0.9.2 --include-sol --skip-resolving --default` | uncompilable; 1 visible error (`uint0`), 21 hidden behind it |
| Seed preparation (`prepare_candidate.py`, 0 model calls) | placeholder rewrite, undeclared error/event declarations, usage-derived event retyping, `var_*` declarations, guard-derived arity alignment | 8 residual type errors in 3 units, 0 unproven edits; 3 arity corrections with per-edit evidence (`23b872dd` 1→3, `c47f0027` 2→1, `dd62ed3e` 1→2) |
| Unit repair (`repair_units.py`, ~30 calls, <10k completion tokens) | diagnostics→unit mapping, signature-frozen rewrites, monotone acceptance | compiling 25-function seed, all 25 dispatch signatures present (`synthetic-large-seed-v1`) |
| Seed behavior (`run_behavior.py`) | differential probes | 0/11 feedback, 0/4 withheld; bodies are decompiler-faithful (`revert()` tails, missing returns) |
| Investigator + merge-repair (`run_investigator.py`, 20 calls) | cluster hypotheses + 64 probes, merge-failure re-synthesis | 22/22 units rewritten, merged candidate compiles; transfer/balance path matches the reference exactly |
| Investigator-candidate behavior | differential probes | 0/11 feedback, 0/4 withheld; residual defects are cross-unit state inconsistencies (setFee/`fee()` variable mismatch, mint skips `totalSupply`, short-string assembly slot) |
| Harness behavior repair (1 round, whole-source) | observation-diff repair | rewrite did not compile; rejected, no regression (`synthetic-large-inv-r3-repair`) |
| Control: `chunked-one-shot`, no probes (6 calls) | same seed, clusters, no observations | 22/22 rewritten, compiles, 0/11 and 0/4 (`synthetic-large-onehot-v1`) |

### What this run establishes

- The blocked goal from the previous session is cleared: an uncompilable 272-line baseline is now
  converted into a compiling, dispatch-complete 25-function candidate by a bounded, fully recorded
  pipeline (`prepare_candidate.py` → `repair_units.py`), with per-edit evidence and no reference
  Solidity, ABI names, or withheld observations in any prompt.
- Merge-failure feedback raises applied rewrites from 9/22 to 22/22 at the cost of one extra call,
  without dropping cluster coverage.
- At this scale the probe-informed and one-shot synthesizes are behaviorally comparable (both 0/11
  after the same seed); the recorded probe advantage on 3-function fixtures does not yet extend to
  a 22-function contract in one shot.

### What this run does NOT establish

- No behavioral-fidelity claim for `synthetic-large`: 0/11 equals the seed, so the pipeline's
  behavioral gain on this fixture is unproven. The observed failure mode is concrete and saved:
  per-unit rewrites are locally correct but cross-unit state consistency (which variable a getter
  reads vs a setter writes) is not enforced by any stage.
- The harness's whole-source behavior repair does not compile at this size; a unit-scoped behavior
  repair fed by per-probe observation diffs is the identified next mechanism, not a tested one.
- One model, one seed per stage; no event gating (`compare_events` false); baseline stage is
  compile-blocked, so no baseline comparison exists for this fixture.

### Reproduce

```bash
python3 evaluation/scripts/prepare_candidate.py \
  --source evaluation/results/synthetic-large-baseline-v1/synthetic-large/baseline.sol \
  --output-dir /tmp/prep --spec evaluation/tests/synthetic-large.json
python3 evaluation/scripts/repair_units.py \
  --source /tmp/prep/prepared.sol --spec evaluation/tests/synthetic-large.json \
  --output-dir /tmp/repair --llm-base-url http://127.0.0.1:8000/v1 --model GLM-5.3-Flash \
  --max-tokens 49152 --max-calls 6 --max-rounds 6
python3 evaluation/scripts/run_investigator.py \
  --source /tmp/repair/candidate.sol --spec evaluation/tests/synthetic-large.json \
  --output-dir /tmp/inv --mode chunked-investigator --candidate-label seed-v1 \
  --llm-base-url http://127.0.0.1:8000/v1 --model GLM-5.3-Flash --max-tokens 49152 \
  --max-calls 30 --max-merge-repairs 6
python3 evaluation/scripts/run_behavior.py \
  --spec evaluation/tests/synthetic-large.json \
  --baseline evaluation/results/synthetic-large-baseline-v1/synthetic-large/baseline.sol \
  --candidate /tmp/inv/candidate.sol --candidate-label inv-r1 --run-id replay
```

The committed per-stage artifacts (prep evidence, unit-repair ledger, investigator metrics, probe
results, merge compile records) are the primary evidence; a replay is a new sample, not a
bit-for-bit reproduction.

### Follow-up: state-write footprint gate and A/B (2026-11-09, same day)

`state_writes`/`footprint_report` compare per-function storage writes between the seed and a merge;
the synthesis context now lists each function's seed-derived writes with an at-least rule, and run
metrics carry `state_write_migrations`.

| Arm (seed 5, same budgets) | rewrites | missing-write migrations | behavior |
| --- | --- | --- | --- |
| r5 investigator (pre-gate) | 22/22 | 2 units (`initialize`, `transferOwnership` lose `store_f`) | 0/11, 0/4 |
| A/B one-shot (footprint-aware prompt) | 21/22 | 0 | 0/11, 0/4 |
| A/B investigator (footprint-aware prompt) | 15/22 | 0 | 0/11, 0/4 |

The prompt rule eliminated the missing-write class in both arms, but behavior stayed 0/11: the
binding constraint moved. Per-step diffs locate it in the seed itself - the decompiler emits two
views of storage slot 0 (`address store_h` and `bytes32 store_f`, both commented `slot 0x00`);
recompiled they become distinct slots, so `initialize` records the owner through `store_f` while
`owner()` reads `store_h` and returns zero. Candidate-space repair cannot merge two compiled slots;
the fix belongs in slot-aware variable grouping (prefer the single variable whose declared slot
matches, or rewrite the paired accessor), to be measured by the same A/B. Cross-unit consistency
remains the unsolved constraint; the whole-source behavior repair path still fails to compile at
this size.

Artifacts: `synthetic-large-ab-onehot`, `synthetic-large-ab-inv` (probe results and metrics with
`state_write_migrations`).

### Follow-up: slot unification A/B and merge-gate hardening (2026-11-09, later)

Seed-v2 (slot views unified) changes the measured picture on `synthetic-large`:

| Candidate (label `seed-v2`) | rewrites | behavior |
| --- | --- | --- |
| seed-v2 itself (LLM-repaired seed plus deterministic slot unification; no investigator calls) | – | `owner`, `isPaused`, `fee` byte-exact; rest blocked by seed stubs |
| one-shot investigator on seed-v2 | 18/22 | 0/11, 0/4; `owner/isPaused/fee/totalSupply` exact |
| investigator on seed-v2, take 1 | merge collapsed (gate spun on repairs, 0 applied) | measured the seed |
| investigator on seed-v2, take 2 (gate fixed) | 18/22, `cluster_2` dropped after one repair round | 0/11, 0/4; 3 getters exact, transfer/mint path still seed bodies |

Gate hardening (committed with these runs): a unit whose merge-repair already failed once is not
retried - the next pass drops the cluster instead of spinning; repairs are one call per unit
(multi-unit repairs repeatedly failed to converge). Take 1's collapse is retained as
`synthetic-large-inv-v2-full` evidence; the Codex review's confirmed defects (placeholder
boundary, visibility drop, write-extractor prefixes, repair acceptance by line shift, packed-slot
assumptions, dynamic-arity over-trigger) are fixed with regression tests; the committed seed-v2
regenerates byte-identically under the guards.

State of the claim: on this fixture the pipeline now reliably produces compiling, partially
behavior-correct candidates, but 0/11 stands - the dropped-cluster lottery decides which units
improve.

Follow-up (same day): per-cluster solo merge is built and measured (`synthetic-large-inv-v2-solo`).
Each cluster is compiled against the seed in isolation with one bounded repair round in that solo
context; only survivors enter the union gate. 5/6 clusters pass solo untouched, cluster_2 fails,
is repaired once, still fails and is dropped with a per-cluster record, and the union compiles on
the first attempt (22 calls versus 26). Behavior is unchanged (0/11; three getters exact): the
binding constraint is now synthesis quality for the dropped cluster, which is the unit-scoped
behavior-repair target - still not built. The investigator metrics and candidate sources for the
solo and gate-hardened runs are committed alongside their behavioral artifacts
(`investigator-metrics.json` / `investigator-candidate.sol` per run directory), closing the
evidence gap noted in review; the seed-v2 control label above is corrected to credit the LLM
repair stage that produced its input.

Review pass (same day) also fixed, with the harness: repair acceptance now requires the
previously bound entrypoints to remain available and treats a probe whose reference setup
reverts as invalid rather than passable; unit repair rolls back on locationless compile
failures, masks comments when checking visibility, and verifies the final compiled ABI keeps
every original signature; merge-repair units are attempted once across solo and union phases
with unique artifact labels. The `approve_transfer_from` probe approved a spender that never
called `transferFrom`; it now approves the actual caller and the former sequence is kept as
`transfer_from_unapproved_spender`, so the feedback set is 12 probes from here on
(`synthetic-large-specfix-check` records the re-measured reference).

### Behavior-unit repair: first proven behavioral improvement (2026-11-09, latest)

`repair_behavior_units.py` closes the loop the planner specified: failing-probe observation ->
owning unit -> single-unit rewrite -> full re-probe, with transactional acceptance (whole-probe
win, or strict divergence decrease committed as pending; regressions, lost bindings, changed
formerly-exact observations, ABI loss and locationless compile failures all roll back; every
rejection reason recorded; retry prompts carry the compile diagnostics or verdict).

Campaign record on synthetic-large, input = the solo-gate candidate (0/12 feedback, 0/4 withheld):

| Run | change | outcome |
| --- | --- | --- |
| run1/2 | null-observation prompts (renderer double-view bug) | no-op rewrites, 0/12 |
| run3-6 | pending-commit bug, then roster-less prompts | setLimits fixed (7->6 divergence); mint rewrites invented identifiers (`paused()`, `unresolved_70a08231`) and failed to compile |
| run7 (final) | entrypoint roster + state-variable list in prompt, real observation values | **3/12 feedback, 1/4 withheld at 5 calls / 827 completion tokens** |

Independent harness verification (`synthetic-large-behavior-unit-v1`, seed-v2 label, identical
probes): `deposit_below_min`, `deposit_above_max` and the complete stateful `transfer_100`
sequence pass; withheld `transfer_insufficient` passes and was never shown to the model.

Supported claim: this saved candidate matches more predefined observations than the seed-v2
control on identical probes (3/12 vs 0/12 feedback, 1/4 vs 0/4 withheld), including one withheld
probe, at single-sample scale. Not claimed: robustness across seeds/models, the remaining 9
feedback probes (initial_config reads, deposit_100, withdraw/pause paths, approve path), event
fidelity, and any comparison against the deterministic baseline (compile-blocked, no score).

The decisive prompt ingredients, in measured order: real observation values (the double-view bug
masked every divergence), the callable-name roster with candidate signatures (ended invented
identifiers), and compile diagnostics in retries. Next lever when resuming: raise
max-attempts-per-unit for body-invention units (mint needed its second attempt), then point the
same loop at the remaining failing probes' first divergences.

### Loop hardening and the fn_11 plateau (2026-11-09, latest)

Campaigns 8-9 attacked the remaining 9 failing probes from the 3/12 state. Run8 (old loop, 24-call
budget) starved: four attempts on one unit, full stop, 3/12 unchanged. The planner-prescribed
fixes landed in `152d04e`: stalled-target rotation, atomic <=3-unit group repair with whole-group
rollback, bidirectional writer/reader context, observation summarization, origin-metric snapshot.

Campaign 9 (11 calls) exercised every new path; the score held at 3/12 + 1/4. The residual is now
precisely localized: rewrites of `Unresolved_860aefcf` (solo, and grouped with its related unit)
leave the target probe's divergence unchanged - the loop is sound, the rewrite quality for that
unit is the binding constraint. Next attack, in order: inspect that unit's body against the
persisting divergence (suspected: the name/short-string slot pair or a getter reading a
never-written var), then a seed-guard-derived body sketch in the prompt for it, then the
pause/approve probe groups.

Honest standing claim unchanged: 3/12 + 1/4 verified on identical probes vs the 0/12 + 0/4
seed-v2 control; everything else is diagnostic progress, not behavioral fact.


### Campaigns 10-14: the limits value-flow blocker (2026-11-09, latest)

Five further loop/prompt upgrades (return-shape hint, state map, sibling-visible group edits,
calldata-coverage table; commits e19effb..262f093 and the coverage commit) were each measured from
the 3/12 state; the aggregate held at 3/12 + 1/4 throughout. Byte-exact residual, verified on
Anvil: the candidate `limits()` now returns the right SHAPE (flat uint pair; the shape hint works)
but the wrong second value (100, the fee) where the reference holds 100000 - and no candidate unit
stores 100000 anywhere, because the candidate `setLimits` signature declares one parameter while
the reference call carries two. The value is present in the observed calldata and reachable as the
msg.data suffix; six prompt variants have not yet produced a rewrite that captures it.

Standing blocker, precisely: one cross-unit inference (setter must capture its surplus calldata
word; getter/predicate/stats read the storage it fills). The loop, acceptance and evidence
machinery are sound and tested (133 tests); the plateau is a synthesis-quality limit of the
one-unit-per-call prompt family on this aliasing-heavy seed. Candidate next mechanisms, unranked
and unbuilt: a deliberately seeded hand-verified pair as a measured ablation (isolates model vs
mechanism), a two-unit joint prompt (both units in one response), or decompiler-comment-derived
per-unit logic sketches in the prompt.

Honest claim unchanged: 3/12 + 1/4 verified vs 0/12 + 0/4; the transfer/deposit path works
end-to-end; everything past it is diagnostic.


Campaign 15 (seventh prompt variant: explicit counter-placement rule over the state map) also held
3/12 + 1/4; a group attempt failed compilation and rolled back cleanly. The prompt-variant series
is closed: seven mechanisms, each individually tested, none moved the aggregate past 3/12. The
plateau is attributed to single-unit synthesis quality on the aliasing-heavy limits/name pair
(candidate setLimits sees one of two calldata words; the surplus-word capture requires a rewrite
quality the served model did not produce in any variant). Next session should start from the
recorded levers: hand-verified-pair ablation, two-unit joint response, or decompiler-comment
logic sketches - and the standing 3/12 + 1/4 verified result.


### Iteration round 2: joint mode and the corrected battle map (2026-11-09, latest)

Two of the three recorded levers landed. Joint multi-unit response (one call rewrites all coupled
units consistently; partial valid subsets accepted) replaced the per-member group loop
(`2ddba7a`); campaign 16 exercised it - the limits pair again redesigned only the getter, 3/12
held. The hand-verified-pair ablation was superseded by a better finding: a cast-based replay
(`hh-mintdbg`, committed) proved the shared-setup mint failures were artifacts of stale
intermediate loop states. The authoritative per-step map on the current origin:

- initial_config: the five reads (limits shape now correct; values/name/supply/stats/predicate)
- deposit revert-stub gates deposit_100, withdraw_50, unpause_allows_deposit
- withdraw revert-stub gates withdraw_50/withdraw_too_much
- approve path: approve and transferFrom succeed; allowance/balance post-states diverge
- pause pair: isPaused read diverges; preview_fee: previewDeposit + isWithinLimits

The remaining blockers are concrete unit rewrites (two stubs, a handful of state-read mismatches)
under a proven acceptance/verification loop - no mechanism work outstanding. The third recorded
lever (decompiler-comment logic sketches) and a deposit/withdraw-focused campaign are the natural
next moves; the standing verified result is 3/12 + 1/4 vs 0/12 + 0/4.


### Campaign 17: focused repair breaks the plateau - 4/12 + 1/4 (2026-11-09, latest)

Two scheduler defects fixed first (`d8c36b9`, `22684a3`; suite now 145 tests): the stalled-target
rotation cleared `no_progress` before any count reached 2, so rotation never engaged (the run8
starvation root cause), and a new `--only` focus filter initially could not reach a focused writer
whose divergence surfaced in a related reader outside the focus (review-found; fixed by resolving
focused related units as repair targets under the unchanged acceptance gate).

Campaign 17 then ran the recorded lever: `--only Unresolved_b6b55f25,Unresolved_2e1a7d4d` (the
deposit and withdraw revert-stubs) against the v1 seed, 24-call budget. Consumed 22 calls, 29
attempts, 5 transactions, 7,295 completion tokens (~7 min). Exactly one rewrite was accepted
(txn05, target `withdraw_too_much`, unit `fn_5` = `Unresolved_2e1a7d4d`): the `view` revert-stub
became a real withdrawal - debit `unresolved_70a08231[msg.sender]` by the amount and emit the
Transfer-to-zero event - dropping `view`, which is outside the dispatch identity the validator
preserves. All prior passes held; no withheld change.

Independently verified (`synthetic-large-behavior-unit-v2`, harness `run_behavior.py`, candidate
sha256 `4562a565...`, identical bytes to the loop's selection): **feedback 4/12, withheld 1/4,
candidate compiles** vs the 0/12 + 0/4 seed control. Newly passing: `deposit_above_max` and
`withdraw_too_much`. Still failing (8): approve_transfer_from, deposit_100, initial_config,
pause_blocks_deposit, preview_fee, transfer_from_unapproved_spender, unpause_allows_deposit,
withdraw_50. The deposit stub attempts compiled but produced no admissible edit; `withdraw_50`
needs both stubs correct in one probe, so the natural next campaign is a joint deposit+withdraw
rewrite under the now-working rotation, or an unfocused run.

Scope honesty: single fixture, feedback-guided focused search; not a claim about unfocused or
multi-fixture performance. Repair evidence in
`synthetic-large-behavior-unit-v2/synthetic-large/behavior-repair-run/` (ledger, prompts,
responses, per-attempt probe results).

Campaign 18 (deposit solo, 24 calls from the v2 seed): null result, 4/12 + 1/4 unchanged - the
deposit stub resisted 24 solo attempts (8 compile failures, 8 deferred transactions, no admissible
edit). The audit also exposed a real defect: the joint lane never fired in campaigns 17-18 because
the focus filter was applied to joint members, collapsing a single-unit focus to the anchor alone
(fixed in `e7ba0b9`; membership graph-driven again). Evidence:
`behavior-repair-deposit-solo/`.

Campaign 19 (deposit solo+joint, 24 calls, post-fix): null result, 4/12 + 1/4 unchanged. The joint
lane now fires and works mechanically (3 coordinated attempts, all compiled and verdict-gated); the
rejections are substantive. Failure anatomy across all three deposit campaigns: every candidate
deposit rewrite either leaves the target divergence unchanged or regresses `deposit_above_max`,
whose current pass is accidental - the always-reverting stub matches the expected above-max revert.
A correct deposit must succeed on valid amounts while enforcing the max bound, and the bound's
value is the same aliased-constant inference (`store_c.length` vs the true limit word) that stalled
the limits pair. Attribution: three full-budget campaigns (~70 attempts, solo and joint families)
converge on synthesis quality for alias-heavy guard constants in the served model, not on loop,
acceptance, or prompt mechanics. Per the stop rule, no further prompt/loop variants on this unit
family. Next quality levers (unstarted, recorded for the next session): deterministic
guard-constant recovery in `prepare_candidate.py` (bytecode-derived constant propagation into
placeholder bounds), or evidence batching (multiple failing-probe observations per call), or a
second fixture to test generalization. Evidence: `behavior-repair-deposit-joint/`.

Campaign 20 (unfocused control, 24 calls from the v2 seed, all machinery fixed): null result,
4/12 + 1/4 unchanged, no accepted rewrite in 35 attempts (joint fired 3x). Rotation behaved
correctly but a full pass over 8 failing probes consumes the whole transaction budget, so only the
first four spec-order probes were ever attempted - later campaigns need `--max-transactions >=
failing-count` or budget-per-target accounting. The control confirms the campaign-17 gain is
attributable to the focused search, not ambient machinery, and that the aggregate is bound by the
same synthesis-quality attribution above. Evidence: `behavior-repair-unfocused/`. Campaign series
closed at five; the recorded next levers are deterministic-prep work, not loop variants.

Stop-rule exception, preregistered before execution (`e936e0e`): one bounded sibling-conditioning
experiment transfers campaign 17's accepted withdrawal rewrite - absent from every saved request
in campaigns 18-20 - as a candidate-derived worked example (`--accepted-rewrite-context` with
`--accepted-example-run` bootstrap; provenance gate on seed bytes and dispatch identity; strictly
accepted rewrites only; 2-example/4KB caps). This is a new conditioning input, not evidence
against the synthesis-quality attribution. Budget: 12 calls, deposit focus only. Promotion:
>=5/12 feedback including a genuinely passing valid-deposit sequence, no withheld loss,
harness-verified per-probe. Kill: at 12 calls this lever closes regardless of outcome; no
further sibling-conditioning variants without a separately preregistered mechanism.

Campaign 21 (sibling-conditioned, executed per the preregistration): null result, 4/12 + 1/4
unchanged at exactly 12 calls - lever closed per the kill rule. The mechanism itself is verified
end to end (provenance gate accepted the v2 seed; the campaign-17 withdraw rewrite rendered in
every repair prompt between target and observations; `accepted-examples.json` audit artifact
written; per-request example ids in the ledger), but zero in-run acceptances followed: all
rejections repeat the established signature (`deposit_above_max` regression or unchanged target
divergence), now with the worked example in prompt. Conclusion: the binding constraint is not
example availability; the deposit rewrite requires the aliased bound/pause interplay the served
model does not synthesize under any tested conditioning. Evidence:
`behavior-repair-sibling-conditioned/`. Remaining recorded levers, unchanged: deterministic
guard-constant recovery in `prepare_candidate.py`, evidence batching, second-fixture
generalization.

### Seed-v3: deterministic packed-scalar recovery - A/B null, diagnostic gain (2026-11-10, latest)

New zero-LLM prep stage `packed-scalars` (`7de6149`; suite 162): a slot-commented `bytes` var whose
single writer is `abi.encodePacked(<one uint param>)` and whose every other occurrence is a guarded
`.length` comparison or a direct packed argument is retyped `uint256`, stored bare, and its length
reads dropped - with conservative per-occurrence classification and single-shot splicing. On the
frozen 4/12 candidate it recovers exactly the two limit slots (`store_c`, `store_d`), compiled.

A/B, all arms harness- or ledger-verified (`synthetic-large-seed-v3/`): seed-v3 alone scores
**4/12 + 1/4 with a byte-identical passing set to v2** (score-neutral, strictly-safe base); the
bounded deposit campaign on it (24 calls / 24 transactions, conditioning off) ended **4/12 + 1/4,
zero accepted rewrites** - promotion criteria missed, kill rule applied to the score claim. The
heuristic ships as tooling, not as a proven behavioral win.

The diagnostic picture did move: on v2 the dominant solo rejection was `target divergence
unchanged`; on v3 it is `deposit_above_max regression / previously-exact observations changed` -
rewrites now alter deposit behavior in the right direction but none yet preserves the accidental
above-max pass while adding the success path. The remaining deposit blocker is exactly one body
passing below-min, valid, and above-max together. Standing verified result unchanged: 4/12 + 1/4.

Preregistered probes, recorded before execution (`9ff565d` and follow-on):

1. Constraint evidence (`9ff565d`): solo repair prompts now carry capped sanitized rows from
sibling feedback probes - preserve-exactly pairs from passing probes touching the rewritten unit,
first-divergence rows from other failing probes - because the verdict graded observations the
prompt never showed. Campaign 23 (seed-v3, deposit focus, 24 calls / 24 transactions) is the
bounded test. Promotion: >=5/12 feedback including a genuinely passing valid-deposit sequence,
withheld >=1/4, harness-verified per-probe. Kill: one campaign; a null closes this mechanism too.
2. Cross-fixture generalization: the behavior-unit loop has only ever run on synthetic-large. One
bounded run (12 calls, unfocused, max-transactions 8) on `modern-math-helper` from the recorded
7/10 + 4/5 `behavior-multi-v2` candidate. Success: loop completes with >=1 accepted rewrite and no
regression below 7/10 (>=8/10 = strong transfer); regression or machinery failure = defect to fix
and record. This probe tests the loop, not the fixture.

Generalization probe result (2026-11-11, latest): **strong transfer, verified**. One unfocused
12-call-budget run on `modern-math-helper` from the recorded 7/10 + 4/5 `behavior-multi-v2`
candidate closed at **10/10 feedback + 5/5 withheld in 3 calls / 2 accepted rewrites / 0
rollbacks** (`Unresolved_c6888fa1` for multiply_overflow, `Unresolved_641579a6` for
set_multiplier_with_value; the third failing probe `multiply_after_rejected_value` passed as a
side effect). Independently harness-verified (`modern-math-helper-unitloop-v1/`, loop ledger +
`verify/` metrics: 10/10 + 5/5, compiled). First demonstration that the unit-repair loop, its
verdict gate, and the new constraint evidence transfer beyond the fixture they were built on -
and the largest single-run gain recorded (3 probes, withheld included, at 3 calls).

Constraint-evidence probe result (2026-11-11): null on synthetic-large - campaign 23 (seed-v3,
deposit focus, 24/24) closed 4/12 + 1/4 with zero accepted rewrites; kill rule applied. The
mechanism demonstrably fired (constraint rows rendered in 21/24 prompts) and the rejection
anatomy is unchanged from the pre-evidence runs (above-max regression dominant), so on this
fixture the missing ingredient is not observation visibility either; the one-body-passing-all-
three-regimes synthesis remains the precise blocker. The same mechanism is part of the verified
math-helper result above (both acceptances ran with constraint evidence in prompt), so it stands
as shipped tooling with a fixture-scoped null, not a dead end. Evidence:
`synthetic-large-seed-v3/synthetic-large/behavior-repair-constraints/`.
