# auditlog tier-2 generalization probe — results

## Question (preregistration.md)

Does the deterministic pipeline transfer to a never-touched fixture with a different codegen
era (Solidity 0.4.17) and a storage shape no prior fixture exercised (dynamic array of
`(address,string)` structs)?

## Answer: yes — perfect card, zero-LLM

Final: **8/8 feedback + 2/2 withheld**, strict evidence, no model call at any stage
(`runs` below; every candidate produced by `rebuild_struct_array_accessors.py`, the recorded
zero-LLM enumeration tool; every verdict by `run_behavior.py`).

## Score lineage (all runs under `evaluation/results/`, candidate-label `seed-v1`)

| run | fb | wh | delta vs prior |
|---|---|---|---|
| `al-p1-plain-old` (first rebuilt variant) | 3/8 | 0/2 | the seed baseline is compile-blocked under 0.8.30 (0.4 struct-array mis-typed roots, `field_N` chains) and scores no verdicts — the row is the first scored candidate, not a seed delta |
| `al-p1-canonical-old` | 6/8 | 1/2 | length-algebra canonicalization (see lessons 1–2) |
| `al-p1-canonical2-old` | 6/8 | 2/2 | ceil word-count + `invalid()` OOB parity (lessons 3–4); wh sweep clean |
| `al-p1-canonical3-old` | **8/8** | **2/2** | getter scratch/payload separation (lesson 5) — perfect |

The `push-ret new` (post-increment return) variant was generated but not needed: the harness
`push_return_index` probe fixed the return semantics empirically (pre-increment, matching the
0.4 reference) on the first passing run.

## What transferred unchanged

- The harness itself (spec → parity verdicts, strict evidence, withheld discipline): first-try.
- The seed-ladder output as the substrate (5 edits applied; compile repair via unit rebuild).
- The rebuild pattern: layout algebra → bounded template → enumerated variants →
  harness-parity acceptance. One pass, three template revisions, done.

## Recorded lessons (the generalizable content)

1. **Short-string length lives in the low byte**: `len = shr(1, and(v, 0xff))`; the raw
   `shr(1, v)` leaks payload bits into the length (huge n → negative shift → Panic). This was
   the cause of every short-path readback failure.
2. **Long-string length is `v >> 1`** (slot stores `len*2`, bit0 = short/long flag) — the
   "plain vs half" variant axis was a wrong hypothesis; one canonical encoding exists.
3. **Word counts are ceil**: `shr(5, add(n, 31))`; `shr(5, n-1)` floors and drops the boundary
   word (n=32 copied zero words).
4. **0.4-era OOB reverts are bare `invalid()`** (no data); an 0.8-style `Panic(0x32)` payload
   fails strict revert-data parity. OOB template branch emits `invalid()`.
5. **In assembly getters, the keccak scratch must not be the payload pointer**: the long-path
   `mstore(scratch, dslot)` clobbered the already-written length word (scratch ==
   `mload(0x40)` == payload). The spare reserved tail word is the scratch.

Lessons 1–5 are storage-layout facts, not fixture facts — they are the phase-2 promotion
candidates (a `struct-array accessor rebuild` ladder stage keyed on the
count-slot/stride/keccak signature).

## Diagnostics discipline (deviation from the original plan, recorded)

The planned EVM-trace debugging loop was replaced after repeated agent-session instability:
the storage algebra is now pinned by an **offline selftest** (`--selftest`: a pure-Python
model of both units' sstore/sload semantics, round-trip over n = 0..40, 63..128, adjacency,
OOB) — zero processes, milliseconds. Lessons 1–3 were found by the selftest plus
artifact congruence (passing short path vs failing long path), not by tracing; the harness
remained the sole verdict authority throughout. The final template's model and yul were
verified congruent by the 8/8 + 2/2 sweep across both storage regimes.

## Artifacts

- `preregistration.md` — written before any verdict; deviations section above supersedes its
  step 3/5 wording (trace loop → selftest; probe smoke folded into the recorded runs).
- `decompile/` — arm-neutral decompile (cmd in prereg; sha256 of raw output recorded at
  `seed/`ing time), `seed/prepared.sol` + `prep-evidence.json` (immutable baseline).
- `pass1-rebuild/candidate-*.sol` — full variant lineage.
- runs: `../al-p1-plain-old/`, `../al-p1-canonical-old/`, `../al-p1-canonical2-old/`,
  `../al-p1-canonical3-old/` (harness artifacts: per-probe results, compile records, metrics,
  selector bindings; `deployment_context` per stage).
- tool: `evaluation/scripts/rebuild_struct_array_accessors.py` (selftest included).

Suite status at close: python evaluation suite untouched by the probe (new standalone tool);
re-run recorded in the session log alongside the final commit.

## Phase 2: the manual parameters are gone (auto-detection)

`rebuild_struct_array_accessors.py --auto <prepared.sol>` now derives every parameter from
in-source evidence and emits the units in one shot:

- **count** — the plain-literal-slot declaration that is both bounds-compared
  (`x < store_a`) and incremented (`store_a += 0x01`) in the bodies;
- **stride / base / offsets** — the decompiler's own slot comments
  (`0x02 * arg0 + keccak256(0) + 0x01`, `store_a * 0x02 + 0x290dec…563`,
  `0x…564 + store_a * 0x02`): coefficient of the index term, keccak base in either its
  symbolic or resolved-constant form (const offsets normalized to the smallest family
  constant, since the decompiler bakes the addend into the literal), and the {0,1} word/data
  pair;
- **word vs data** — the `address(…) | mask &` write idiom names the word slot; the
  `& 0x01` / `0x0100 **` length-decode names the data slot;
- **roles** — getter = bounds compare + decode shapes; push = count increment + address
  write; lens = bare `return <count>;`.

Evidence:

- detector on the auditlog seed reproduces the manually derived parameters exactly
  (`"auto-detected: {count_slot 0x00, stride 2, addr 0, str 1, the three unit names}"`);
- the `--auto` candidate is **byte-identical** to the hand-parameterized
  `candidate-canonical3-old.sol` (`diff` empty), and the harness re-run on it
  (`../al-p2-auto/`) repeats **8/8 + 2/2**;
- abstention matrix: the detector returns `null` on the erc20, blockreader, and
  modern-errors prepared seeds — no struct-array signature, no edit. One fixture fires, the
  rest abstain: the honest generalization claim for this stage.

The manual CLI arguments remain for lineage and for override; `--auto` is the recorded
pipeline path. With this, the auditlog class is a repeatable pipeline stage:
decompile -> prepare-ladder -> auto-rebuild -> harness verdict, zero manual parameters,
zero model calls.

### Post-review hardening (codex, both findings adopted)

The detector now requires one SHARED keccak base across the element family: resolved
constants may span at most one slot; a symbolic term must resolve (via `cast keccak`) onto
the constant base when both forms appear, and an all-symbolic family must use identical
arguments — two unrelated storage families can no longer masquerade as the `{0,1}` pair. The
role matchers additionally require a UNIQUE getter/push/lens match and abstain on ambiguity
instead of silently rebuilding the parser-first unit. Both behaviors are pinned in the
selftest by synthetic sources (a minimal positive firing with the exact layout, and a
two-bases negative that must abstain); the auditlog detection, the three-fixture abstention
matrix, and the byte-identical `--auto` candidate were re-verified after the change.
