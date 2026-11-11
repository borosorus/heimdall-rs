# Preregistration: paired V0-vs-V1 bake-off on untouched fixtures

Written BEFORE any touch of the holdout fixtures, after `seed-rules-v1` froze.
Steps 1-2 are complete at `0ec250a` (+ the seed-rules commit). Nothing below may
be changed after the first holdout command runs; deviations get recorded as
deviations, not silently.

## Frozen procedure

- **V0 tool** = git `413ad23` (worktree export), **V1** = HEAD at run time; both
  recorded by commit sha in the result JSON.
- **Holdout fixtures**: two external source+deployed-runtime pairs never touched
  by any earlier campaign, imported through the standard provenance check
  (`check_fixtures.py`), solc >= 0.8, contract compiled by its publisher.
  Candidate pool and import record land in `fresh-holdout-v1/import/` BEFORE the
  first prepare run; no substitution after the first run.
- **Per fixture, per version, identical commands**:
  1. `heimdall decompile <runtime> --include-sol --skip-resolving --default`
     (release build pinned at run time; sha256 of the binary recorded)
  2. `prepare_candidate.py --contract <parsed> --solc <fixture>`
  3. compile check via the standard forge path; if the seed fails, the recorded
     V0-era fallback applies unchanged: bounded compile repair through the
     same stage list, no manual edits, no new rules mid-run
  4. harness on a spec built by the standard spec template with
     `strict_evidence: true`, read-mode probes, bindings resolved only from
     name-embedded selectors / structural fallbacks - spec written once, before
     any candidate run, from the reference ABI alone
- **Budgets**: prep and compile as shipped; harness single pass, no repair
  rounds, no iteration on failing probes. One (1) V0 run and one (1) V1 run per
  fixture, then the sealed reveal of both.
- **Metrics**: seed compiles (y/n), harness fb/wh matched, per-probe verdicts,
  wall clock, all hashes. Denominators include non-compiling and timed-out runs.
- **Success criterion (planner-set)**: at least one fixture improves compile
  status or matched-probe count under V1 with no previously passing observation
  lost anywhere; otherwise the recorded outcome is "no improvement" and that is
  a valid result.

## Deviation log

(appended below as deviations happen; none at freeze time)

## Deviations / clarifications (recorded BEFORE first candidate run)

1. "read-mode probes" clarified: probes follow the standard template per-step mode -
   send steps for state transitions, read steps for observations and revert-payload
   checks (verdict-audit-v1 contract); `strict_evidence: true` unchanged.
2. compile-repair fallback dropped for this bake-off: seed-or-bust, identically for
   both versions. A version whose seed does not compile scores zero matched probes;
   that is a recorded outcome, not an error. Removes a discretionary asymmetry.
3. The reference decompile (arm input) is produced once by the pinned release binary
   and shared by both arms; candidate bindings are derived mechanically from its
   @custom:selector provenance before any prepare/harness run.

4. Binding derivation refinement (still pre-verdict): candidate signatures are
   extracted mechanically from EACH ARM'S post-prepare source (@custom:selector
   comments for explicit functions; `unresolved_<sel>` public-var getters mapped to
   their own declared-name signatures; the block-reader fallback bound to the
   reference signature, justified by the decompiled fallback's own embedded
   `0x819439` check). Both arms' signatures enter the spec's
   `candidate_signatures` as labels `v0`/`v1`; no verdict is observed beforehand.

5. V1 toolchain completion (pre-verdict): arming the holdout prep exposed two more
   arm-symmetric wart classes via solc diagnostics only - truthiness guards
   (`require(<addr>/<uint>)`, `if(<const>/<addr>/<uint>)`) and the single-dispatch
   fallback shape (bytes/int selector compare; value-returning fallback signature).
   Rules added; NO candidate or reference verdict observed during this work. Final
   frozen pair for all runs: V0 = 413ad23, V1 = HEAD at first harness run (sha
   recorded in the result JSON). Both arms re-prepped from the shared decompile.
