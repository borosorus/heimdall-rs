# verdict-audit-v1: the behavioral verdict layer, discriminatively tested

First negative-control audit of the harness verdicts (`run_behavior.py`
`combined_semantic_match`). Until now every green number had only positive
controls; this establishes that the verdicts change for the right reasons.

## Result

**PASS** - positive control reproduced the recorded perfect run
(12/12 feedback + 4/4 withheld, `synthetic-large`, candidate-FINAL, label
`seed-v2`), and all six preregistered mutants changed exactly the
preregistered probe verdicts and no others (`matrix.json`, `violations=0`).

## Mutants (deterministic source transforms, `mutants/*.sol`)

| mutant | perturbation | preregistered verdict changes |
|---|---|---|
| ispaused-flip | `isPaused()` truth flipped | initial_config, pause_blocks_deposit, unpause_allows_deposit |
| owner-xor | `owner()` return off by one bit | initial_config |
| supply-drift | deposit credits supply `+1` extra | deposit_100, withdraw_50 |
| setup-revert | `setLimits` reverts in shared setup | every feedback probe (setup gate) |
| owner-rename | owner binding lost | initial_config (unbound) |
| limits-revert | `limits()` reverts on a READ path | initial_config (revert payload vs tuple) |

Each run's full harness artifacts are kept under this directory
(`positive/`, `<mutant>/`), plus the mutant sources (`mutants/`).

## Evidence contract established alongside

- **Read-path payload comparison is sound**: `eth_call` failures carry the
  revert payload; equal payloads match, different payloads reject
  (`limits-revert` end-to-end).
- **Send-path verdicts are reason-blind by construction**: transaction
  receipts carry no revert payload; send-mode parity covers status + state +
  logs only. Payload-fidelity probes MUST use read mode at an equivalent
  state. (Drives the modern-errors spec redesign.)
- **Missing evidence no longer earns parity silently**: specs may set
  `"strict_evidence": true`; then a failed observation with neither return
  nor revert payload is `unverified` and cannot match (unit-tested in
  `tests/test_run_behavior.py::StrictEvidenceTests`). Default is unchanged
  for history compatibility.

## Re-run

```bash
python3 evaluation/scripts/verdict_audit.py
# exit 0 = PASS; writes matrix.json and per-mutant harness runs (idempotent)
```
