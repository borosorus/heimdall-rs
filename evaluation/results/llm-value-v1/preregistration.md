# llm-value-v1 — preregistration

Written BEFORE any arm runs. Goal: measure what the LLM surface adds on top of the now
fully-green deterministic ladder (4/4 tier-2 fixtures at full marks, zero model calls), and
mine the comparison for the next ladder stages. Planner-reviewed (revise-first, 6 findings,
all adopted; the adoption map is recorded at the bottom).

## Global pins (all arms)

- Heimdall revision: recorded at first run (git rev-parse HEAD); raw-source sha256 per fixture
  recorded in every metrics artifact.
- Endpoint: local OpenAI-compatible server. Preflight 2026-11-12: `127.0.0.1:8000` NOT
  LISTENING — the model-bearing arms are gated on the server being up (historical models:
  `dsv41`, `GLM-5.3-Flash`; whatever `/v1/models` reports at run time is recorded and used;
  one model, one configuration, results reported as that run — never as model capability).
- Feedback legality: candidate source + compiler diagnostics + black-box observations only;
  reference Solidity, reference ABI names, and withheld-probe observations never enter a
  prompt (spot-check recorded per arm).
- Accounting: per-request provider usage + latency retained; provider-reported usage
  distinguished from estimates/missing; round/call counts per artifact.
- Labels: LLM-produced and no-LLM artifacts carry distinct candidate labels in bindings; a
  no-LLM fallback is never recorded as an LLM success.
- All verdicts from `run_behavior.py` paired runs; results under `evaluation/results/llm-value-v1/`;
  suite stays green; chronicle at close. Conclusions labeled benchmark-relative (these fixtures
  informed ladder development; scores do not establish generalization).

## Arm A — legacy pass-1 value (model-gated)

Per tier-2 fixture (auditlog, hdwallet, ipfs, lighthouse): the fixture's RAW decompile →
`heimdall decompile --llm-postprocess` (one call, the existing prompt/pipeline UNCHANGED —
this measures the legacy surface, not an LLM parity ceiling; planner finding 1 adopted) →
compile → `run_behavior` paired verdict with the LLM output as the candidate.

Records per fixture: fb/wh, compile, tokens, latency, the diff vs raw (Arm C input), and the
ladder's full-marks result alongside. H1: legacy pass-1 reaches compile but not full parity;
the gap decomposition quantifies the ladder's value. NOT combined with any other arm into a
single headline number.

## Arm B — rescue value on the ladder's remaining failures (model-gated), stage 0 first

Stage 0 (deterministic, runs BEFORE the model arms): re-verify the three tune fixtures whose
seed-only compile failed in the seed-rules era — `modern-advanced`, `modern-math-helper`,
`synthetic-large` — under the CURRENT 18-stage ladder, on the canonical raw inputs of record
(`seed-rules-v1/v0-v1-comparison.json` `cases[*].source`, sha-pinned there). Compile verdict
per fixture (forge 0.8.30); if compile passes, the harness decides behavior on the fixture's
existing spec. A fixture the ladder now FULLY passes leaves Arm B (its data still feeds Arm C
and the paired report; planner finding 2 adopted).

Arm B proper, on whatever failure surface remains, with both repair surfaces pinned
separately (planner finding 2): (B-compile) `repair_compile.py`, bounded, compiler
diagnostics only; (B-behavior) `run_behavior --repair`, bounded rounds, feedback fb failures
only. Withheld probes are never repair targets — their outcome is a generalization check.

Rescue denominators, defined before any run (planner finding 3):
- compile-rescue rate = fixtures compilable after the bounded rounds / fixtures whose ladder
  seed does not compile;
- behavior-rescue rate = fb probes passing after bounded repair / fb probes failing on the
  repaired-compilable seed.
Per-unit attempt/acceptance outcomes retained where the surface provides them; otherwise only
aggregate fixture cost is reported (no per-unit efficiency implied).

## Arm C — convergence mining (the deliverable), seed-relative by construction

Corpus: every Arm A/B output + the ladder seeds, per fixture, against the SAME pinned raw.

Diff discipline (planner findings 4-5 adopted):
1. Subtract shared inheritance: only lines CHANGED vs the raw enter the comparison
   (`diff(raw, ladder)` vs `diff(raw, llm)`); boilerplate excluded by the same rule.
2. Matching reported at two levels, always separately: exact-line and normalized
   (whitespace/comment-insensitive token streams). Alpha-renaming is NOT applied in v1
   (scope-aware renaming deferred; recorded as a limitation, not silently skipped).
3. Agreement is a review lead, never evidence of an invariant.
4. Promotion gate for the stage-19-candidate label: minimal trigger + proposed rule, REPLAYED
   on the ladder seed, idempotent (`prepare(prepare(x)) == prepare(x)`), and no-regression on
   the full fixture/probe suite. Anything less is recorded as an observation; a null is
   recorded honestly if no lead clears the gate.

Deliverable: the leads ledger (`llm-value-v1/leads.md`), ranked by cross-fixture recurrence,
every entry with fixture, error class, minimal before/after, reproduction command, and gate
status.

## Acceptance summary

A: per-fixture legacy-pass-1 table + gap decomposition vs the ladder. B: stage-0 re-verification
table, then rescue cards at the defined denominators. C: the gated leads ledger. Suite green;
chronicle entry; no reference-source rule violations (spot-check log).

## Planner adoption map (revise-first, 2026-11-12)

1 -> A relabeled legacy pass-1, pinned run, no combined headline; 2 -> B stage-0 re-verification,
fixtures-leave-when-green, surfaces pinned, withheld = generalization only; 3 -> denominators
and per-request accounting as above; 4 -> seed-subtracted two-level matching, renaming deferred;
5 -> promotion gate before the stage-19-candidate label; 6 -> prompt spot-check log and
benchmark-relative labeling throughout.
