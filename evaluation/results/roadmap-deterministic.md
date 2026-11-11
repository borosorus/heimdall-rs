# Deterministic-quality roadmap (leads backlog, 2026-11-11)

Ranked working backlog for the deterministic decompilation-quality line. Every
entry is tied to recorded evidence; gains are targets to falsify, not projections.
Compiled from the sealed holdout v1/v2 divergences and a codex strategy pass
(2026-11-11); re-rank as evidence lands. Protocol for any lead taken: labeled
paired run, sealed reveal, numbers never merged across labels.

## Ranked

0. **Stateful guard synthesis (2a, spun out of the v3 residual)**: the erc20
   transferFrom withheld divergence is a stateful send body (reference reverts on
   zero-balance transfer; candidate stub succeeds). Synthesize the guard
   condition from the same map (balance/allowance checks over the slot-annotated
   mappings); acceptance unchanged: harness parity on a labeled re-run.
1. **Typed storage-flow evidence map - DONE as infrastructure (v3)**; now the
   shared substrate: one inferred model connecting calldata words -> mapping
   keys -> slot-annotated storage, consumed by synthesis (2), guard synthesis
   (0) and type inference (3) instead of per-rule regex evidence. Remaining
   extension: key-type inference from casts/hints for non-address keys.
2. **Mapping-getter body synthesis - DONE (v3, `fresh-holdout-v3/`)**: erc20
   fb 2/4 -> 4/4 via the audited map+synthesis; the transferFrom wh clause went
   partial (its residual is a stateful send body, not a getter) and spawned 0.
3. **Calldata-word type inference** (consumer of 1). Fill arity-extended params
   from casts / mapping-key positions / storage access types instead of generic
   `uint256`; infer only on agreeing evidence. Done-when: targeted entrypoints bind
   with reference-matching selectors and their probes pass on a labeled replay.
4. **Events into the verdict, then event repair.** `compare_events=false`
   everywhere; erc20 v2 metrics already record event mismatches on approval /
   transfer paths. Enable on a controlled spec first (scores may drop - that is
   measurement improving, and it must be labeled), then deterministic event
   synthesis from declared topics + observed argument flow.
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
