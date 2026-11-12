# lighthouse read-guard repair — preregistration

Written BEFORE any harness verdict on the repaired candidate. Repairs the recorded batch-2
residual (`read_zero` fb failure; `peek_mixed` wh failure on the same path) by the established
rebuild family: layout-guarded unit rebuild, zero model calls, harness as sole judge.

## The residual (evidence, `lh-final3`)

Reference `read()` on the harness-reachable (empty-storage) state reverts with
`Error(string) "Invalid data stored"`; the candidate returns a zero word with status 1.

Root cause (decompiler structuring, not the ladder — the seed is the untouched ladder output):
the source require

    require(notTooLongSinceUpdated() && value != 0, "Invalid data stored");   // fixtures/lighthouse/lighthouse.sol:97

compiles to a two-edge revert join; the decompiler rendered the conjunct chain as nested
if/else (`if (A < d) { if (A >= d) {require(A < d, m);} else {require(c, m);} return e; }`),
dropped the outer revert edge, and the unit fall-through now returns the default word.
No deterministic ladder stage can resurrect the lost else-edge revert from the rendered text
alone; the else-path behavior is absent from the candidate. Repair class: rebuild the unit
body over the recorded storage layout (the `rebuild_*` family precedent), composing ONLY
atoms the harness has already proven on this fixture.

## Repair declaration (exact, before the run)

New tool `evaluation/scripts/rebuild_guarded_view.py` (explicit-parameter v1, the recorded
precedent: struct-array rebuild shipped manual first, auto-detection only after the class
proved out). It replaces one zero-arg `view` unit body with

    require(<guard>, "<msg>");
    return <value-expr>;

preserving name, selector comments, and declared return type verbatim.

Lighthouse invocation:

    --unit       Unresolved_57de26a4
    --guard      "Unresolved_e2f90632() && store_e != 0"
    --msg        "Invalid data stored"
    --value-expr "address(uint160(store_e))"

Atom provenance (all harness-green on this fixture):

- `Unresolved_e2f90632()` — the notTooLong unit, `notTooLong_zero` fb-green; renders
  `if (A < d) return A < d; else return (d == 0);` with `A = block.timestamp - uint64(store_c / 2**128)`, `d = store_d`.
- `store_e` — declared `uint128` @ slot 3 (ladder slot-comment); the value half. Triangulated:
  `write()` stores the (value,nonce) pair into the packed word whose high half is the
  timestamp, and `peek`/`peekData`/`read` render `store_e` as the value. Aliases recorded, not
  re-derived.
- `address(uint160(store_e))` — the seed's own compiling return expression, reused verbatim;
  declared return stays `address` (wire-identical to the ABI `bytes32` for one static word;
  selector and bindings untouched; candidate label stays `seed-v1`).

## Probe-coverage analysis (why no new probe)

Planner directive: add a `write_then_read` probe with a nonzero maxAge "if the authorized
path permits it". It does not permit, structurally:

- Runtime-only deployment (`anvil_setCode`) leaves ALL storage zero, including `owner` and
  `auth` (recorded batch-2 deviation, both sides alike).
- The guards are `require(owner == msg.sender)` / `require(auth == msg.sender)`
  (`lighthouse.sol:37-52`); sender must be address zero.
- The harness sender set is `eth_accounts` (`run_behavior.py:541`), the ten funded anvil keys —
  `0x000...0` is not among them. `admin_sequence` confirms: both sends reverted on BOTH sides
  (status 0, probe green), final `owner()` = 0.

Therefore every admin/write path is unreachable for any harness caller, the reachable behavior
space of this fixture under this harness is exactly the empty-storage class, and on it `read()`
can only revert (notTooLong true via the `d == 0` arm, `value == 0` forces the revert). The
existing `read_zero` + `peek_mixed` probes consequently cover the ENTIRE reachable `read()`
contract. The never-exercised success path (nonzero value, fresh timestamp) is untestable
here; its correctness rests on the rebuild's structural fidelity to the fixture source and is
recorded as such, not claimed.

## Acceptance (declared before the run)

- `read_zero` fb flips green (status 0 + identical revert data both sides);
- `peek_mixed` wh flips green;
- the 9 fb greens and `admin_sequence` stay green (no-regression);
- predicted outcome 10/10 fb + 2/2 wh — recorded however it lands.

## Tool gates (planner-hardened)

Single target match (overloads rejected); zero params; `view` mutability; single (non-tuple)
return; guard/value are single expressions (balanced parens/brackets, no `;{}"`); the exact
`--msg` string literal must occur inside a `require(...)` of the old body; rebuilt header
byte-identical to the original; idempotence (`rebuild(rebuild(x)) == rebuild(x)`); suite-pinned
gate matrix. A plain-solc compile check of the rebuilt source precedes the harness run; the
run's own compile artifacts remain the formal compile evidence.

## Planner record

codex-planner, revise-first, 5 findings: guard call-form adopted; alias-consistency recorded
(above); probe directive adopted-then-resolved (condition false, evidence above); tool gates
hardened as listed; verdict scoping kept to the reachable probes with the success-path caveat
explicit.

## Deviations (post-review, before the lh-repair2 verdict)

2026-11-12, codex review of the sealed state, two findings adopted:

1. Guard conjunction second term `store_e != 0` -> `store_c != 0`. The fixture guard is the
   WHOLE packed word (`value != 0`, lighthouse.sol:97, value = timestamp<<128 | data), and the
   decompiler's own rendering used `store_c`; `store_e != 0` (low half only) diverges at
   nonzero-packed/zero-low states. The divergence class is harness-unreachable (see the
   reachable-space analysis above), so the sealed lh-repair1 verdict is unaffected; the
   candidate is regenerated and re-judged as `lh-repair2` regardless - prose proofs do not
   replace the harness.
2. Tool msg-gate now locates require spans on comment/string-masked text (investigator masker,
   offsets preserved; literal checked on the raw span) - a commented-out require no longer
   satisfies the gate, and string parens cannot skew the span scan. Suite 213/213.

The reviewer's remaining suggestion (a behavioral probe at nonzero-packed/zero-low) is
unreachable under this harness (no authorized sender exists; analysis above) and is superseded
by fix 1: the guard now matches the fixture semantics by construction plus two independent
attestations (fixture source line; decompiler rendering), recorded - not claimed.
