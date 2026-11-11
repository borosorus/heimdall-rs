# fresh-holdout-v3: storage-flow map + getter synthesis (leads 1-2, sealed)

Labeled re-run of the holdout pair under the standing protocol. Arms: v2 =
`8cc4d77` (worktree-verified against the v2-round seeds before any run), v3 =
the leads-1+2 toolchain (typed storage-flow map `storage_flow.py` + the
`storage-getters` prepare stage). Post-reviewer fixes left both v3 seeds
byte-identical, so the sealed runs correspond to the shipped code.

## Sealed result

| fixture | arm | fb | wh |
|---|---|---|---|
| modern-oz-erc20 | v2 | 2/4 | 1/2 |
| modern-oz-erc20 | **v3** | **4/4** | 1/2 |
| modern-block-reader | v2 | 1/1 | - |
| modern-block-reader | v3 | 1/1 | - |

**Both roadmap done-when clauses evaluated**:
- erc20 allowance feedback probes: MATCH (fb 4/4; the two former failures,
  `approve_then_allowance` + `allowance_overwrite`, now pass on return data).
- `transferFrom_self_approved` withheld: NOT met - honest partial. The residual
  divergence is the candidate's stateful send body (reference reverts on
  zero-balance transferFrom; the decompiled stub succeeds). Getter synthesis
  does not reach send-path state semantics; recorded as the refined lead
  "stateful guard synthesis" in `../roadmap-deterministic.md`.

No regression anywhere: block-reader steady; modern-errors seed byte-neutral;
tune-set compile parity PASS (`v2arm` as baseline; synthetic-large seed text
gains the new stage's edit - its recorded 12/12 artifacts are historical and
untouched).

## What the map did (evidence in the stage ledger of the v3 seeds)

`Unresolved_dd62ed3e` (allowance): unique structural unification with
`storage_map_b` (slot 0x01, keys address/address, value uint256, tier hinted -
second arg is the decompiler's generic uint, bridged by the audited
uint->address cast). The stub gained `view returns (uint256)` and
`return storage_map_b[arg0][address(uint160(arg1))];`, provenance comment
synced. Zero abstentions on this fixture.

## Reviewer round (codex) - 5 findings, all addressed

1. exact-tier mislabeling on type mismatch -> any mismatch demotes to hinted
2. generic-uint bridge restricted to keys with a proven conversion (address)
3. comment mutability sync on the no-returns path -> pinned by test (was
   already correct via the header-wide substitution; now guarded)
4. reference-valued mappings gain `memory` in the synthesized returns clause
5. intN canonicalization implemented to match the documented policy

Suite 192/192.
