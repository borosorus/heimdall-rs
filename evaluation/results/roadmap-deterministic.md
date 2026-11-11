# Deterministic-quality roadmap (leads backlog, 2026-11-11)

Ranked working backlog for the deterministic decompilation-quality line. Every
entry is tied to recorded evidence; gains are targets to falsify, not projections.
Compiled from the sealed holdout v1/v2 divergences and a codex strategy pass
(2026-11-11); re-rank as evidence lands. Protocol for any lead taken: labeled
paired run, sealed reveal, numbers never merged across labels.

## Ranked

1. **Typed storage-flow evidence map** (compounding infrastructure). One inferred
   model connecting calldata words -> mapping keys -> slot-annotated storage, shared
   by every consumer below instead of per-rule regex evidence. The erc20 candidate
   already carries the raw material (slot comments, unresolved_<sel> mapping decls);
   the seed rules are deliberately conservative per-stage rewrites, which is exactly
   where the remaining erc20 class stalls. Local-optimum flag: the residual erc20
   failures (stub getter bodies, unknown key types) are NOT reachable by more
   regex patches - this is the structure change.
2. **Mapping-getter body synthesis** (consumer of 1). Stub view function + arity
   matching a slot-annotated (nested) mapping => emit the typed indexing expression
   (`mapping[a][b]` - the compiler computes keccak layout); abstain on ambiguity.
   Done-when: the two erc20 allowance fb probes and the `transferFrom_self_approved`
   wh probe match on return data, nothing regresses; narrower results recorded
   honestly if transferFrom needs more than the getter.
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
