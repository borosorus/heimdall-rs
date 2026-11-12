# auditlog tier-2 generalization probe - preregistration

Written BEFORE any harness verdict on this fixture.

## Question

Does the deterministic pipeline (decompile -> prepare seed -> harness parity -> zero-LLM
enumeration repair) transfer to a never-touched fixture whose codegen era (Solidity 0.4.17)
and storage shape (dynamic array of `(address,string)` structs) differ from every prior
fixture (all 0.8.x; mappings/scalars/strings-but-not-struct-arrays)?

## Fixtures under test

`evaluation/fixtures/auditlog` - publisher-paired source+runtime (NOT independently
recompiled; manifest warning respected: no compiler-reproducibility claim), 1080-byte
runtime, sha256 `ec57b18a422dce5f6f7e212b3f0df53de6df1ec41331fca1ba87c79cc70a6254`.
Functions: `push(address,string) -> uint256`, `getSize() -> uint256`,
`logEntries(uint256) -> (address,string)` (public getter, auto-generated).

## Procedure (planner-reviewed; findings adopted)

1. Preflight on the RAW decompilation: record decompile cmd+sha and the emitted pragma;
   run `prepare_candidate.py`; compile the prepared seed under the harness solc (0.8.30,
   the pipeline's standing candidate compiler - the 0.4.17 era lives in the reference
   bytecode, not the candidate toolchain). If compile fails, the failure itself is a
   recorded generalization datum (which 0.4-shaped construct the seed stages miss).
2. Spec smoke: 2-probe harness pass (string arg + multi-step + caller variation) before
   the full suite, to validate mechanics cheaply.
3. Full spec below; 8 feedback + 2 withheld, all parity-vs-reference (no expected blocks).
   String-length boundary pair (31/32 bytes) per planner: exercises the short/long string
   storage transition. Push return-value checked in READ mode (send mode does not capture
   return data - planner finding).
4. Immutable baseline: raw decompile + prepared seed hashes recorded here; every later
   source change lives in a pass dir with input/output hashes, the failing observation,
   the synthesized edit, and parity results. Final candidate diffs against the immutable
   seed; that ledger is the no-hand-repair evidence.
5. Harness invocations WITHOUT the repair loop (no model calls at any stage).
6. Verdicts only from `run_behavior.py` records; fb/withheld split fixed as below.

## Probes (feedback)

1. `initial_empty` - `getSize()` on fresh deploy (read)
2. `push_alpha_readback` - send `push(A,"alpha")`; read `logEntries(0)` (read; (address,string) tuple)
3. `push_two_ordering` - send push(A,"alpha"), push(B,"beta"); read `logEntries(0)`, `logEntries(1)`
4. `size_after_two` - send two pushes; read `getSize()` == parity of counts
5. `push_return_index` - READ-mode `push(A,"alpha")` raw return == 0 (row number), then `getSize()`
6. `short_string_31` - send push(A, 31-byte payload); read back (short-string storage path)
7. `boundary_string_32` - send push(A, 32-byte payload); read back (boundary)
8. `long_string_96` - send push(A, 96-byte payload); read back (multi-slot long-string)

## Probes (withheld)

9. `read_out_of_range` - send two pushes; read `logEntries(5)`: success/revert parity and
   revert-data shape (strict evidence in effect for failed-call comparisons)
10. `interleave_growth` - send push, read size, send push, read both entries, read size
    (order-sensitive growth under reads)

Addresses: `A = 0x70997970C51812dc3A010C7d01b50e0d17dc79C8`,
`B = 0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC` (distinct constants; the planned separate
smoke run was folded into the recorded harness runs and never archived as its own artifact —
see Deviations; all scored probes use the harness default caller).

## Success criterion (honest form)

The pipeline completes mechanically end-to-end; the fb score lineage is recorded however it
lands. Generalization claim = machinery transfer + which repair classes recur, NOT a perfect
card. Perfect card is a bonus, not the gate.

## Deviations

(appended below as they occur, before verdicts are drawn)

1. (recorded at close) The step-2 spec smoke and the step-5 "harness invocations WITHOUT the
   repair loop" phrasing: no separate smoke artifact exists; the first recorded run
   (`al-p1-plain-old`) served as the mechanics validation. The EVM-trace debugging loop of
   step 3 was replaced by the offline storage-algebra selftest; the harness remained the sole
   verdict authority. Caller variation was not exercised (default caller throughout); recorded
   as a limitation, not a claim.
2. (recorded at close) The seed baseline is compile-blocked and therefore has NO verdicts;
   score lineage starts at the first rebuilt candidate. The README lineage table is the
   authority on what was measured when.
