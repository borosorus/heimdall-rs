# fresh-holdout-v2: labeled re-run of the paired bake-off (v1 vs v2 toolchain)

Follow-up to `../fresh-holdout-v1/` under the same freeze discipline: paired arms,
same fixtures/spec shape, sealed reveal; numbers are LABEL v2 and are never merged
into the v1 sealed result.

## Arms

- v1 = `6d89c7d` (the sealed v1 toolchain, worktree-reproduced)
- v2 = the v2 delta: signature-comment sync in `_replace_params` (arity rewrites
  no longer desynchronize selector identity), `abi.encode` in rule-added
  value-fallback returns, and the harness send-path evidence fix (receipt gas).

## Result (same harness for both arms)

| fixture | arm | fb | wh | delta vs v1 |
|---|---|---|---|---|
| modern-block-reader | v1 | 0/1 | - | (sealed: 0/1) |
| modern-block-reader | **v2** | **1/1** | - | **+1 fb** - the abi.encode fix flips the packed/ABI length mismatch |
| modern-oz-erc20 | v1 | 2/4 | 1/2 | (wh gain here is the shared send-evidence harness fix) |
| modern-oz-erc20 | **v2** | 2/4 | 1/2 | no verdict delta; signatures/bindings now provably correct |

No regression anywhere; tune-set compile parity PASS
(`/tmp` sweep recorded in the commit message); modern-errors seed byte-identical
(its sealed 11/11+2/2 evidence is untouched). Both v2 seeds bit-reproduce from
the committed toolchain.

## What v2 fixed, precisely

1. **Stale `@custom:signature` comments** (root cause of the v1 erc20 binding
   misses): arity rewrites now sync the provenance comment; selector identity,
   compiled ABI and bindings agree by construction. The v1 erc20 "1-arg
   declaration" story was wrong in one detail - declarations WERE extended; the
   comment lied. Provenance is contract.
2. **Packed-vs-ABI fallback returns**: rule-added `returns (bytes memory)` now
   emits `abi.encode` (address packs to 20 bytes; block-reader 116B vs 128B).
3. **Send-mode evidence gap**: reverted sends previously carried no evidence
   field at all; receipt gas now fills it (both arms, harness-level).

## Residual erc20 divergences => next leads

The two remaining fb fails + one wh fail all reduce to: the decompiler emits
pure-stub bodies for the double-mapping `allowance` getter (no return at all).
That is body loss, not declaration loss - outside seed-rule scope. Recorded in
`../roadmap-deterministic.md` (leads 1-2) with falsifiable done-whens.

Reviewer round (codex) on this delta: 3 P2s - comment suffix preservation
(adopted: only the paren list is rewritten), encode-rule evidence basis
(documented in-code), send-path test now drives the real `call_step` path via
fake RPC (adopted). Suite 188/188.
