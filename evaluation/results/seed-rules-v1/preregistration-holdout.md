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
