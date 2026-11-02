# Recorded evaluation results

Committed runs are evidence snapshots. They are not CI inputs, and a single run does not establish
general model quality. Do not reuse a run directory; the harness rejects nonempty output
directories so saved evidence cannot be silently overwritten. Scratch `work/` directories are
ignored.

## `behavior-repair-v4` — one bounded behavioral repair

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
