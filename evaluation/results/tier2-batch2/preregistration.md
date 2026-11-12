# tier-2 generalization batch 2 — preregistration (hdwallet, ipfs, lighthouse)

Written BEFORE any harness verdict on these fixtures. Continuation of
`auditlog-tier2-v1` (the recorded one-fixture probe); same discipline, now the
remaining three pristine fixtures, in ascending complexity.

## Per-fixture register

| fixture | surface | tier-2 interest |
|---|---|---|
| `hdwallet` | `set(string)`; `get()`, `storedData()` (two names, same `(string)` shape -> distinct selectors, same storage) | string storage round-trip incl. empty string and the 31/32 boundary; alias-getter dispatch |
| `ipfs` | `get() -> (string,string)`; `Description()`, `IpfsHash()` | two independent string slots; multi-value ABI return in the candidate |
| `lighthouse` | owner/auth/searcher admin, packed `uint32/uint128` views, `bytes32` read, time validity, external callback | modifiers inlined by the decompiler; bit-packing; the largest fixture yet (4.6 kB runtime) |

All three: constructor-initialized storage is NOT reproduced by runtime-only
`anvil_setCode` deployment — the harness deploys reference and candidate
identically, so parity verdicts stay valid; initial state reads compare the
shared empty-storage baseline (recorded as a property of these fixtures, not
worked around).

## Procedure (per fixture, in order)

1. Spec first: fb/wh split recorded here; every probe parity-vs-reference; the
   auditlog arg-encoder pattern (explicit ABI encoding, committed in the spec).
2. Arm-neutral decompile (release binary, `--skip-resolving --include-sol
   --default`), sha256 recorded.
3. `prepare_candidate.py` seed; compile verdict from its evidence JSON.
4. If the seed compiles: the seed IS the first candidate (the pipeline-works-
   as-is outcome). Only on failure/verdict gaps: the recorded zero-LLM tools
   (`rebuild_struct_array_accessors.py --auto` when the struct-array signature
   fires; otherwise a new evidence-driven pass under the same rules — layout
   algebra first, selftest-pinned, harness as sole judge).
5. Results `evaluation/results/<fixture>-tier2-v1/` per fixture; one batch
   chronicle entry at close. Deviations appended here as they occur.

## Probe plans

### hdwallet — fb: `initial_empty`, `set_then_get`, `alias_stored_data`,
`overwrite_twice`, `empty_string`, `short_31`, `boundary_32`, `long_40`;
wh: `short_then_long` (storage-mode transition on one slot), `alias_interleave`
(set/read alias alternated).

### ipfs — fb: `initial_both_empty`, `set_description_read_both`,
`set_hash_read_both`, `set_both_independent`, `empty_then_value`,
`long_description_48`, `boundary_32_hash`, `swap_order`; wh:
`description_only_long`, `revert_shape` (none expected — no revert paths in the
ABI; replaced below if the seed shows one).

### lighthouse — probes fixed AFTER reading the seed's actual dispatch/roles
(the ABI has 13 entries; the prereg commit is the intent, the per-probe list
lands in the spec before its first run and is committed with it).

## Success criterion (unchanged)

Per fixture: the pipeline completes mechanically; the fb/wh lineage is recorded
however it lands. A fixture the tooling passes untouched on the first seed is a
positive tier-2 result, not a lesser one. New repair classes feed the same
record (layout algebra, selftest, harness-judged) as auditlog's.

## Deviations

(appended below as they occur, before verdicts are drawn)
