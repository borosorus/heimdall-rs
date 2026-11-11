# modern-errors: decompile unblocked (bounded constant extraction)

Evidence for the fix recorded in `evaluation/results/README.md` ("Decompile hang
root-caused and fixed"). The fixture previously made `heimdall decompile` hang forever
(rc=124 at 900s); the spin was in unbounded constant-value extraction
(`VM::call` -> `VM::execute`, no step/gas/deadline bound) on `errorOutOfGas()`'s
`while (true)` self-loop (pc 0x369), not in symbolic execution (all 13 selectors <250 us).

## Reproduction (post-fix, release build)

```bash
# 0.3s, rc=0 (was: no termination at 900s)
time ./target/release/heimdall --no-update-check decompile \
  evaluation/fixtures/modern-errors/runtime.hex \
  --skip-resolving --include-sol --default \
  --name modern-errors --output <outdir>
# plain (no --include-sol): same, 0.3s rc=0
```

WARN line on the exhausted function is expected and by design:
`constant extraction for selector b641db83 exceeded its step budget (1000000)`.

## Artifacts

- `modern-errors-decompiled.sol` / `modern-errors-abi.json` - decompiler output
  (`--include-sol --skip-resolving`), byte-identical across repeated runs.
- 13/13 functions in the ABI; `Unresolved_b641db83` (= `errorOutOfGas()`) retained with
  an analyzed body and no fabricated constant decl.
- Body-level solidity warts (undeclared `CustomError_*` aliases, `uint256 v = v + ..`
  self-reference) are the raw decompilation's normal state and the input of the
  deterministic repair stages; the known-good fixtures' raw outputs have the same class.

## Verification matrix (all green at fix time)

- heimdall-vm: 163 lib + 34 integration tests; 4 new (step-budget parity, infinite-loop
  exhaustion, exact boundary incl. zero budget, revert-data surface contract).
- heimdall-core `test_decompile`: 15 pass, 1 ignored (RPC-gated), offline.
- nightly `cargo fmt --check` clean on all touched files; clippy: no new warnings.
- Determinism: two full `--include-sol` runs diff-identical.
- Regression: `modern-simple` outputs byte-identical pre/post fix
  (abi plain `b2fefa66..`, abi sol `b2fefa66..`, sol `9ca40782..`).
