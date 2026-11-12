# lighthouse read-guard repair (batch-3 lead a)

Repairs the recorded batch-2 residual — candidate `read()` returning a default word where the
reference reverts — by a layout-guarded unit rebuild. Preregistration (written and committed
before any verdict, with the reachable-space analysis and the planner record):
`preregistration.md`. Zero model calls; harness the sole judge.

## Result

Paired runs (same spec, same seeds discipline as batch-2; the un-repaired seed ran as each
run's baseline stage, the repaired candidate as `llm1`):

| run | candidate | fb | wh |
|---|---|---|---|
| `lh-repair1` | `store_e != 0` guard (preregistered form) | 10/10 | 2/2 |
| `lh-repair2` | `store_c != 0` guard (post-review, **sealed**) | **10/10** | **2/2** |

Baseline (batch-2 seed, re-derived in-run): 9/10 + 1/2 both times.

- `read_zero`: both sides status 0, revert data BYTE-IDENTICAL
  (`Error(string) "Invalid data stored"`), both runs.
- `peek_mixed` (wh): green — it failed only on its `read` step.
- The 9 fb greens and `admin_sequence`: unchanged (no-regression).
- Matches the preregistered prediction; the post-review guard change (see the prereg's
  deviation record: the fixture tests the WHOLE packed word, and the decompiler's own rendering
  used `store_c`) is verdict-neutral on the harness-reachable class — confirmed by the paired
  runs, not assumed.

## The repair

`evaluation/scripts/rebuild_guarded_view.py` (new tool, gates per prereg + review hardening)
replaced the body of `Unresolved_57de26a4` in the batch-2 seed with

    require(Unresolved_e2f90632() && store_c != 0, "Invalid data stored");
    return address(uint160(store_e));

Every atom harness-proven on this fixture (notTooLong unit fb-green; `store_c` the packed
word whose guard semantics the fixture source and the decompiler's own rendering both
attest; the return expression the seed's own compiling line). Name, selector comments, and the
declared return are byte-preserved; bindings and the `seed-v1` label are untouched.

Sealed candidate sha256 `9a1167db61f31420…`; seed `444d408373d84539…` (chains in the run dirs;
`lh-repair1` kept as history). Pre-run compile gate: `forge build --use 0.8.30` successful
(warnings only, the seed's pre-existing set); the run's `compile-llm1.json` is the formal
compile evidence.

## Scope and honesty

- The harness-reachable behavior space of this fixture is the empty-storage class (runtime-only
  deployment: `owner`/`auth` == 0; `eth_accounts` has no zero address — analysis in the
  prereg). `read_zero` + `peek_mixed` therefore cover the ENTIRE reachable `read()` contract,
  and this repair is judged on exactly that contract.
- The never-exercised success path (nonzero value, fresh timestamp) is unreachable under this
  harness; its correctness rests on the rebuild's structural fidelity to the fixture source
  (`fixtures/lighthouse/lighthouse.sol:96-99`, evaluation-only) — recorded, not claimed.
- The batch-2 matrix stands: auditlog 8/8+2/2, hdwallet 8/8+2/2, ipfs 6/6+2/2 (no ladder
  change, no re-freeze); lighthouse now 10/10+2/2. Four-for-four fixtures at full marks, fb
  and wh, on the deterministic pipeline, zero LLM.
- Suite 211/211 at close (207 + 4 new tool tests).

## Residuals / next leads

- None recorded for lighthouse. Standing leads unchanged: Rust-port parity debt (stages 14-18 +
  scope fixes), LLM-value comparison (now unblocked with a fully green deterministic baseline on
  all four fixtures).
