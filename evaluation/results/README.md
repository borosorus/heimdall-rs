# Recorded evaluation results

Committed runs are evidence snapshots. They are not CI inputs, and a single run does not establish
general model quality. Do not reuse a run directory; the harness rejects nonempty output
directories so saved evidence cannot be silently overwritten. Scratch `work/` directories are
ignored.

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
