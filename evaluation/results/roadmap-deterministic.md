# Deterministic-quality roadmap (leads backlog, 2026-11-11)

Ranked working backlog for the deterministic decompilation-quality line. Every
entry is tied to recorded evidence; gains are targets to falsify, not projections.
Compiled from the sealed holdout v1/v2 divergences and a codex strategy pass
(2026-11-11); re-rank as evidence lands. Protocol for any lead taken: labeled
paired run, sealed reveal, numbers never merged across labels.

## Ranked

0. **Stateful guard synthesis - DONE (v4, `fresh-holdout-v4/`)**: guard
   transplantation from guarding-and-mutating siblings; erc20 withheld now
   2/2 - the fixture is fully perfect (4/4 + 2/2, zero LLM). Reviewer-hardened
   (precedent pairing, body allowlist, header-scoped mutability).
1. **Typed storage-flow evidence map - DONE as infrastructure (v3)**; now the
   shared substrate: one inferred model connecting calldata words -> mapping
   keys -> slot-annotated storage, consumed by synthesis (2), guard synthesis
   (0) and type inference (3) instead of per-rule regex evidence. Remaining
   extension: key-type inference from casts/hints for non-address keys.
2. **Mapping-getter body synthesis - DONE (v3, `fresh-holdout-v3/`)**: erc20
   fb 2/4 -> 4/4 via the audited map+synthesis; the transferFrom wh clause went
   partial (its residual is a stateful send body, not a getter) and spawned 0.
3. **DONE (v5/v6, `fresh-holdout-v6/`)**: map-key classes re-type generic-uint
   params (declaration + provenance); verdict-neutral, structurally truthful.
   Enforced lesson: per-arm bindings re-derived mechanically after any
   signature change.
4. **DONE (v5/v6, `fresh-holdout-v6/`)**: events in the verdict via per-side
   identity tables (candidate decls / reference fixture ABI) with raw
   fallback; the exposed layout defect (missing `indexed`) repaired
   observation-side; erc20 4/4+2/2 WITH events. Remaining event nicety
   (alias renaming) is cosmetic - LLM-era territory.
5. **Gas-budget probes for exceptional halts.** modern-errors OOG vs invalid are
   observation-equivalent at current depth (recorded in its README). A
   deterministic gas-limit ladder separates them and tightens synthesis acceptance.
6. **Bound `resolve_entry_point`'s walk** (crates/vm/src/ext/selectors.rs). Same
   latent class as the fixed constant-extraction hang; termination guarantee, no
   verdict points claimed.
7. **Constructor / immutable coverage.** Runtime-only deployment leaves
    constructor state unexercised (recorded limitation). New fixture class with
    creation-code deployment; broadest generality, unestimable gain.
8. **Rust port of the hardened deterministic pipeline** (production contribution;
    upstreamable slice: bounded execution already landed as `40198f5`).

## Explicit non-goals for now

- synthetic-large / math-helper re-perfection: 12/12+4/4 and 10/10+5/5 are
  recorded; further gains there need harder probes, not patches.
- LLM-value comparison: deferred by decision until the deterministic line
  saturates; the hardened harness + audits are the ready-made baseline for it.
