# modern-errors end-to-end (v1): deterministic pipeline, verdict-perfect

Fixture `modern-errors` (13 zero-arg error-path functions; 11/13 probes revert).
The decompile blocker was lifted in `40198f5`; this directory holds the first
complete deterministic pass over the staged behavior spec, per the plan agreed
2026-11-11 (verdict audit -> tune-side run -> generalization -> holdout bake-off).

## Result

**11/11 feedback + 2/2 withheld, `strict_evidence` on, zero LLM calls at any
stage** (`final/metrics.json`, reproduced in `synth-r2/`).

## Pipeline stages (all deterministic; evidence per stage)

1. **decompile** - heimdall release build, `--include-sol --skip-resolving`
   (`../modern-errors-decompile-unblocked/`, sub-second post-fix).
2. **seed** - `prepare_candidate.py` (`candidate-seed.sol`): alias-error
   declarations, `var_*` hoisting, selfref-initializer split, pure->view
   mutability alignment. Compiles under solc 0.8.30; verdict `seed-h1/`:
   4/11 fb, 0/2 wh.
3. **observation** - `reference-observations.json`: per-unit reference behavior
   captured by the seed harness run (black-box; provenance in-file).
4. **synthesis** - `synthesize_error_units.py` round 1
   (`candidate-synth-final.sol`): 7 units -> constant-payload reverts (assembly
   mstore/revert reproducing the observed bytes: 4 panic codes, 3 custom-error
   payloads); 2 evidence-less units (out-of-gas, invalid-opcode) -> gas-burn
   loop variant accepted on feedback parity. Passing units untouched.
5. **harness** - `seed-h1/`, `synth-r1/` (9/11+2/2), `synth-r2/` and `final/`
   (11/11+2/2) after the gas-evidence harness upgrade below.

## Harness upgrade forced by this fixture (run_behavior.py)

The two exceptional-halt units (OOG, invalid) are evidence-less on BOTH sides
under `eth_call` (anvil returns no payload), so `strict_evidence` rightly marked
them unverified. Fix: failed calls now record `gas_used` from
`debug_traceCall` (callTracer) - proof the halt executed - as evidence only;
gas is excluded from equality (implementation detail, not behavior), so no
historical verdict moved. Suite 178/178; `verdict-audit-v1` re-run PASS under
the new observation schema.

## Honest scope notes

- Panic/custom-error fidelity is payload-exact (byte-identical revert data).
- OOG vs invalid are observation-equivalent at this probe depth (both
  `ok=False`, no payload); both units carry the gas-burn body and pass on
  measured parity. Distinguishing them would need gas-budget probes (queued,
  not claimed).
- Constant-payload reverts embed observed constants; the acceptance harness
  bounds that choice. Multi-input synthesis across varying calldata remains
  future work (the generalization step of the plan).
