# seed-rules-v1: deterministic seed-repair catalog, ablations, V0/V1 freeze

Step 2 of the 2026-11-11 plan (verdict audit -> tune run -> generalize -> frozen
bake-off). Tune-fixture-only evidence; the paired holdout run is preregistered in
`preregistration-holdout.md` and must not be influenced by any result recorded here
after its freeze.

## Version pins

- **V0** = `413ad23` (verdict audit; seed ladder before the new rules)
- **V1** = `0ec250a` + the stage-split refactor recorded here (selfref promoted to
  its own stage; `PREPARE_STAGES` made injectable for ablations; byte-neutral on
  the modern-errors seed - verified by diff)

## Rule catalog (taxonomy per planner review; no fixture-name conditionals)

| stage | category | key / gate |
|---|---|---|
| `placeholders` | representation | decompiler placeholder tokens -> concrete types |
| `declarations` | declaration | undeclared error/event symbols, arity from call sites; ABI-independent |
| `selfref` | declaration | `T var_x = <expr using var_x>;` with no earlier binding -> decl+split; masked-source scan, source-slice rebuild |
| `vars` | declaration | `var_*` used-but-undeclared -> contract-level `uint256` |
| `mutability` | representation | `pure` -> `view` when the body references non-shadowed state; modifier/mapping/array-aware name parse |
| `arity` | representation | calldata-head guard vs declared param count |
| `slot-aliases`, `packed-scalars` | declaration/storage | slot-comment provenance; packed recovery gated on occurrence-anchored evidence |

Behavioral hypotheses (CALL-result recovery, elided transfers, constant-payload
reverts) are NOT seed rules - they live in the bounded synthesis layer
(`synthesize_error_units.py`) and are harness-accepted, per the planner's
taxonomy.

## Ablation (`ablation-modern-errors.json`, leave-one-out, solc 0.8.30)

On the modern-errors raw decompilation, removing any of `declarations`,
`selfref`, `vars`, or `mutability` breaks the compile; `placeholders`, `arity`,
`slot-aliases`, `packed-scalars` abstain on this fixture (spare there, load-bearing
elsewhere by earlier evidence). The two new rules are thereby proven necessary,
not decorative.

## V0 vs V1 (`v0-v1-comparison.json`, six tune-fixture baselines)

| fixture | V0 compiled | V1 compiled | output changed |
|---|---|---|---|
| modern-simple | yes | yes | no |
| sender-creator | yes | yes | no |
| modern-errors | no | **yes** | yes (the fix) |
| modern-advanced | no | no | yes (2 selfref splits fire; residual diagnostics pre-date V1) |
| modern-math-helper | no | no | no |
| synthetic-large | no | no | no |

No-regression: PASS (every V0-compile remains a V1-compile; unchanged where V1
is uninvolved). The two fixtures whose seeds still do not compile alone are the
historical case - their chains always used the compile-repair stage.

## Idempotence

`prepare(prepare(x)) == prepare(x)` on the modern-errors seed (byte-diff empty)
and by unit test on the ladder fixture. Repeated preparation is deterministic.

## Scope notes (honest)

- `var_*` rules are name-shape keyed (`var_[a-z]+`): the decompiler's canonical
  locals. Renamed sources degrade to abstention, never to wrong edits.
- The selfref earlier-binding scan is file-global prefix, not scope-perfect:
  false negatives (missed splits) are possible; the ablation gates false
  positives on this fixture class. Scope-perfect def-use is future work and is
  the known limit of the declaration category.
- V0/V1 comparison covers the seed stage only; recorded candidates from earlier
  eras stand as artifacts and were not re-derived.
