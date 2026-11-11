# fresh-holdout-v1: paired V0-vs-V1 bake-off on untouched fixtures (sealed result)

Step 3 of the 2026-11-11 plan. Procedure frozen in
`../seed-rules-v1/preregistration-holdout.md` BEFORE any holdout touch; deviations
1-9 logged there as they arose (none post-verdict). Arms: V0 = `413ad23`, V1 =
`6d89c7d`; shared arm-neutral decompile; per-arm mechanical signature derivation;
one harness pass per arm; sealed reveal after all four runs.

## Sealed result

| fixture | arm | seed compiles | feedback | withheld |
|---|---|---|---|---|
| modern-oz-erc20 | v0 | no  | 0/4 | 0/2 |
| modern-oz-erc20 | **v1** | **yes** | **2/4** | 0/2 |
| modern-block-reader | v0 | no  | 0/1 | 0/0 |
| modern-block-reader | **v1** | **yes** | 0/1 | - |

**Preregistered success criterion MET**: modern-oz-erc20 improves under V1
(compile + 2/4 feedback vs 0/4) with no previously passing observation lost
anywhere. block-reader: structural win only (V1 seed compiles; verdict tie 0/1).

## What the holdouts taught (post-reveal learnings, NOT folded back into this run)

1. **erc20 residual divergences** (`allowance_overwrite`, `approve_then_allowance`,
   `transferFrom_self_approved`, `transfer_insufficient`): the decompiler declares
   `allowance(address)` / `transferFrom(address)` with one parameter where the
   reference surface takes two - the arity stage did not extend them, so candidate
   calldata and storage reads are shaped differently. Next toolchain rev: guard
   proven multi-word reads should extend declared params (the arity rule's own
   evidence was present but its threshold conservative).
2. **block-reader encoding**: the fallback-shape rule kept `abi.encodePacked` on the
   grounds that static args encode identically - false for `address` (20-byte
   packed vs 32-byte word). The value-returning fallback rule should emit
   `abi.encode` (ABI-canonical) when it adds `returns (bytes memory)`.
3. **Harness capability gap fixed during arming** (deviation 9): fallback-only
   contracts previously always ran unbound; `bindings_for_stage` now accepts a
   compiled ABI whose payable fallback receives every selector. This was weak
   area "fallback coverage" surfacing exactly as predicted.
4. V0's seeds fail to compile on BOTH holdouts for the exact wart classes the V1
   rules address (truthiness guards, fallback shape, selfref/mutability) - the
   rule generalization claim now has out-of-sample evidence.

## Reproduction

```bash
for f in modern-block-reader modern-oz-erc20; do for arm in v0 v1; do
  python3 evaluation/scripts/run_behavior.py --spec evaluation/tests/$f.json \
    --baseline <decompiled.sol> \
    --candidate <prepared-$arm.sol> --candidate-label $arm \
    --run-id fresh-holdout-v1/$f-$arm
done; done
```
Arm prep commands and the exact frozen versions are in the preregistration.

## Post-freeze follow-up candidates (explicitly NOT part of the sealed result)

- fallback-shape v2: emit `abi.encode` for value-returning fallbacks (learning 2)
- arity v2: extend declared params when the body's own guard proves more words (learning 1)
- both re-run through the SAME paired protocol as a labeled v2, never merged into v1 numbers
