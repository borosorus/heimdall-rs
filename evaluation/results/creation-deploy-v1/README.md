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

## Follow-ups delivered (7a + 7b)

**7a - constructor-body synthesis** (`../..//scripts/synthesize_constructor.py`,
seed `seeds/constructor-synth.sol`): from creation-mode probe results plus the
per-deployment constructor arguments, the tool synthesizes
`constructor(uint256 arg0) { <slot-annotated scalar storage> = argN; }` when a
unique scalar slot-annotated storage exists, every usable initial-state
observation (first probe step = successful single-word read on pristine state)
matches, and the value-carrying argument position agrees across ALL
observations (drift abstains). The constant-vs-parameter ambiguity is recorded
as an assumption on the edit; the harness rerun is the gate. Result: the demo
candidate gains a working constructor - **4/4 fb + 1/1 wh under creation
deployment** (`synth-a..f` runs; `initial_get` now passes).

**7b - context-equivalent deployment**: the harness anchors a snapshot right
after the reference creation-deployment and rewinds to it (taking a FRESH
anchor each time - snapshot semantics invalidate later snapshots, reviewer
finding) before every stage. Every stage therefore deploys from the identical
chain state: same sender nonce (address) and block. Evidence
(`deployment_context` in each run's metrics; synth-e vs synth-f): address and
block identical across independent runs; verdict unchanged. `null` context
semantics: the stage did not deploy (creation mode off, or the stage's source
does not compile - the case for this fixture's raw-decompilation baseline).

Reviewer round (codex) on 7a+7b: 1 High + 1 Medium + 1 Low, all adopted
(fresh-anchor rewind with checked revert result; cross-observation position
agreement; null-semantics documentation). Suite 205/205.
