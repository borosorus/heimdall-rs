# results archive (2026-11-12 prune)

Superseded exploratory eras, moved here by the reference audit (every archived
directory had ZERO references from any active ledger, spec, parity manifest, or
test fixture). Full contents and history: `git log --follow evaluation/results/archive/<name>`.
Nothing here is consumed by the current pipeline, the llm-value arms, or the parity
locks; revive by `git mv` back if a lead needs one.

| directory | era | what it was |
|---|---|---|
| `2026-11-02-dsv41/` | first LLM era | dsv41 endpoint pass-1/behavior exploration (predates the deterministic ladder) |
| `hh-mintdbg/`, `hh-tuple/` | honeycomb probes | one-off mint/tuple debugging artifacts |
| `sender-seed-check2/` | seed era | superseded sender-creator seed check |
| `synthetic-large-ab-inv/`, `-ab-onehot/`, `-onehot-v1/` | inv era | A/B and one-hot investigator variants on the synthetic fixture |
| `synthetic-large-behavior-unit-v1/` | inv era | superseded by `-v2` (referenced, kept at top level) |
| `synthetic-large-inv-r1/`, `-r2/` | inv era | early investigator rounds (r3 lineage kept) |
| `synthetic-large-inv-v2-full/`, `-full2/`, `-solo/`, `-solo-12probe/` | inv era | full/solo invocation variants of the v2 investigator loop |
| `synthetic-large-seed-v1/`, `-v2/` | seed era | superseded by `-v3` (referenced, kept) |
| `synthetic-large-specfix-check/` | spec era | one-off spec validation check |
