# creation-deployment v1: constructors are verdict-visible (roadmap lead 7)

The harness gains `deployment: {mode: "creation"}`: both sides deploy via their
creation code plus the spec's constructor arguments (unsigned transaction,
receipt-polled), so constructor state writes and immutables are real and the
existing probes exercise them. Runtime-only `anvil_setCode` deployment remains
the default; no recorded verdict changed.

Fixture support: `modern-simple` now carries `creation.bin` (upstream creation
code, ts-extracted; deployed-runtime cross-checked byte-identical to the
committed `runtime.hex`).

## Demonstration (`demo/`, spec `tests/modern-simple-creation.json`)

Both sides constructed with `initialValue = 7`; probes initial_get /
set_zero_get / set_123_get (fb) + set_42_get (wh), strict evidence.

- reference `initial_get` = **7**: constructor state is verdict-visible - the
  capability claim, measured.
- candidate: **3/3 fb + 1/1 wh** except `initial_get`, where the candidate
  returns 0: the decompiled constructor body does not store the initial value
  (constructor-body loss - the same loss class as the getter stubs lead 2
  fixed, now visible because the harness can see constructors).
- recorded follow-up: **constructor-body synthesis** (seed stage analog of
  lead 2 for `constructor(...) { ... }` stores) - appended to
  `../roadmap-deterministic.md`.

## Known limitation (reviewer-noted, documented)

The three deployments happen sequentially: sides get different contract
addresses and block contexts. A constructor reading `address(this)` or block
properties could initialize divergent state from harness context rather than
candidate behavior. The demonstration fixture is context-independent; context-
equivalent deployment (snapshot-restored same-address creation) is the
recorded follow-up before creation-mode verdicts are treated as primary
evidence for context-sensitive fixtures.

Suite 205/205 at introduction.
