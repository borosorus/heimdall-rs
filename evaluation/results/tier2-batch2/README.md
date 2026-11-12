# tier-2 batch 2 — hdwallet, ipfs, lighthouse (preregistration in this directory)

Continuation of `auditlog-tier2-v1`: the remaining three pristine fixtures through the
deterministic pipeline, zero model calls. Final numbers under the frozen 18-stage ladder
(one-ladder-consistent re-derivation; earlier-era runs preserved in git and in the
per-fixture `*-p1-*` run dirs):

| fixture | fb | wh | repair path | notes |
|---|---|---|---|---|
| `hdwallet` | **8/8** | **2/2** | `rebuild_string_slot_accessors.py` (setter + both alias getters, slot 0x00) | incl. empty string, 31/32 boundary, long, alias dispatch |
| `ipfs` | **6/6** | **2/2** | same tool: pair-getter `(bytes,bytes)` + two appended single getters | the two accessors had been lifted to `public` vars by the decompiler — no units existed for the ABI selectors (`--append-getter`) |
| `lighthouse` | **9/10** | **1/2** | none — the seed itself | 18-stage ladder output compiles and behaves on the largest fixture (4.6 kB, auth admin, packed views, external callback) |
| (`auditlog` re-run under the final ladder) | **8/8** | **2/2** | `--auto` struct-array rebuild | unchanged verdict |

## Ladder growth (all generalizable, all harness-gated)

The batch grew the seed ladder 13 -> 18 stages; every stage fired on real residue and is
pinned by the 206-test suite:

14. `typed-packed-literals` — bare ints in `abi.encodePacked` -> `uint256(...)` (solc 7279).
15. `wordify-address-mask` — the `A | MASK & S` address/bytes32 idiom, assignment AND
    `address(...)` expression forms, as pure uint256 word algebra.
16. `widen-packed-pair-returns` — all-packed-2-return view units under-declared as single
    returns -> `(uint256, uint256)` with bool terms via conditional (solc refuses
    `uint256(bool)`).
17. `coerce-word-returns` — cross-width single-word returns (`uint128` state from an
    `address`-returning unit) -> explicit `address(uint160(..))` / `bytes32(uint256(..))`.
18. `lower-unknown-external-calls` — `address(..).Unresolved_<h8>{value}(..)` member calls
    (no declaration can back them) -> `<inner>.call{value}(abi.encodeWithSelector(0x<h8>,..))`;
    balanced-scan target, word-atom args only.

Plus two scope corrections to existing stages (both lighthouse-forced, both now the
documented semantics): `selfref` earlier-binding = same-unit locals + contract-level state
(the file-global-prefix scan suppressed needed splits), and `vars` visibility = unit-local +
state (like-named locals of OTHER units do not cover a use). `truthiness` gained the
negation forms (`!(flat-uint)` guard and expression position incl. bare `!x`) and the
`.length` member-chain rule, restructured into sequential re-masked passes.

## Residuals (recorded, not hand-fixed)

- `lighthouse.read()` alone: the reference reverts (`require(store_c, "Invalid data stored")`
  path) where the candidate's reconstructed branch returns zero — decompiler if/else polarity
  on that unit; the interleaved form (`peek_mixed`) passes. Follow-up: branch-polarity repair
  pass or a read() rebuild; recorded in the next-batch leads.
- The Rust port covers ladder stages 1-13; stages 14-18 and the two scope corrections are
  Python-side parity-debt, recorded for the port sync.

## Deviations (per preregistration)

- ipfs probe plan realized as 6 fb + 2 wh: the fixture is read-only (constructor state not
  reproducible by runtime-only deployment; no setter in the ABI) — smaller surface, declared
  before its first run.
- lighthouse probe list landed with the spec as preregistered ("after reading the seed).
- The batch re-derived all fixtures under the final ladder after the ladder grew mid-batch;
  per-fixture lineage: first-era runs (`*-p1-*`, earlier seeds) + final runs
  (`al-final2`, `hdw-final2`, `ipfs-final2`, `lh-final`). The seeded-candidate hash chain is
  in each run dir; git holds every intermediate.

## Suite

Python evaluation suite 206/206 at close (three tests updated for the 18-stage reality:
pipeline stage list, send-guard stage lookup by name).
