#!/usr/bin/env python3
"""Verdict audit: preregistered mutants against the behavioral harness.

The harness verdicts (combined_semantic_match over per-step observations) had only
ever been validated positively - green candidates stayed green. This audit proves
the verdicts DISCRIMINATE: deterministic source mutations of a recorded-perfect
candidate must change exactly the preregistered probe verdicts and no others, and
the unmutated candidate must reproduce its recorded perfect run.

Zero-LLM, zero-network: the harness runs without --repair; the only subprocess is
run_behavior.py itself (the acceptance path under test, driven as a black box).

Mutants (synthetic-large, positive control = candidate-FINAL, label seed-v2):
  ispaused-flip      isPaused truth value flipped        -> initial_config, pause_blocks_deposit,
                                                             unpause_allows_deposit change
  owner-xor          owner() return value off by one bit -> initial_config changes
  supply-drift       deposit credits supply +1 extra     -> deposit_100, withdraw_50 change
  setup-revert       setLimits reverts: setup gate fires -> every feedback probe changes
  owner-rename       owner binding lost (unbound)        -> initial_config changes (unbound)
  limits-revert      limits() reverts on a READ path    -> initial_config changes (revert payload
                                                             vs tuple: read-mode payload discrimination)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "evaluation" / "scripts"
TESTS = ROOT / "evaluation" / "tests"

DEFAULT_POSITIVE = ROOT / "evaluation/results/synthetic-large-enum-final/synthetic-large/candidate-FINAL.sol"
DEFAULT_SPEC = TESTS / "synthetic-large.json"
DEFAULT_LABEL = "seed-v2"
BASELINE_METRICS = (
    ROOT / "evaluation/results/synthetic-large-enum-final/synthetic-large/harness-final-perfect/synthetic-large/metrics.json"
)


def function_block(source: str, name: str) -> tuple[int, int, str]:
    """Span of `function <name>(...) { ... }` (brace-balanced), or raise."""
    opener = re.search(r"function %s\(" % re.escape(name), source)
    if not opener:
        raise SystemExit(f"audit bug: function {name} not found in candidate")
    body_open = source.index("{", opener.end())
    depth = 0
    for i in range(body_open, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return opener.start(), i + 1, source[opener.start() : i + 1]
    raise SystemExit(f"audit bug: unbalanced braces in {name}")


def replace_once(haystack: str, old: str, new: str) -> str:
    if haystack.count(old) != 1:
        raise SystemExit(f"audit bug: pattern {old!r} appears {haystack.count(old)}x, expected 1")
    return haystack.replace(old, new)


def mutate(source: str, name: str) -> str:
    if name == "ispaused-flip":
        _, _, block = function_block(source, "Unresolved_b187bd26")
        return replace_once(source, block, replace_once(block, "== 1;", "!= 1;"))
    if name == "owner-xor":
        _, _, block = function_block(source, "Unresolved_8da5cb5b")
        return replace_once(
            source,
            block,
            replace_once(
                block,
                "return address(uint160(uint256(store_f)));",
                "return address(uint160(uint256(store_f) ^ 0x01));",
            ),
        )
    if name == "supply-drift":
        _, _, block = function_block(source, "Unresolved_b6b55f25")
        return replace_once(source, block, replace_once(block, "var_c += net;", "var_c += net + 1;"))
    if name == "setup-revert":
        _, _, block = function_block(source, "Unresolved_c4590d3f")
        mutated = block.replace("{\n", "{\n        revert CustomError_3261c792();\n", 1)
        return replace_once(source, block, mutated)
    if name == "owner-rename":
        return replace_once(
            source, "function Unresolved_8da5cb5b(", "function Unresolved_8da5cb5bX("
        )
    if name == "limits-revert":
        _, _, block = function_block(source, "Unresolved_860aefcf")
        return replace_once(
            source, block, replace_once(block, "return (store_c, store_d);", "revert CustomError_3261c792();")
        )
    raise SystemExit(f"audit bug: unknown mutant {name}")


# preregistered feedback-probe verdict changes per mutant (see module docstring)
EXPECTED_CHANGED = {
    "ispaused-flip": ["initial_config", "pause_blocks_deposit", "unpause_allows_deposit"],
    "owner-xor": ["initial_config"],
    "supply-drift": ["deposit_100", "withdraw_50"],
    "setup-revert": "*",  # every feedback probe: the shared setup fails on the candidate
    "owner-rename": ["initial_config"],
    "limits-revert": ["initial_config"],
}
MUTANT_ORDER = [
    "ispaused-flip",
    "owner-xor",
    "supply-drift",
    "setup-revert",
    "owner-rename",
    "limits-revert",
]


def run_harness(spec: Path, positive: Path, candidate: Path, label: str, run_id: str) -> dict:
    cmd = [
        sys.executable,
        str(SCRIPTS / "run_behavior.py"),
        "--spec",
        str(spec),
        "--baseline",
        str(positive),
        "--candidate",
        str(candidate),
        "--candidate-label",
        label,
        "--run-id",
        run_id,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, cwd=str(ROOT))
    if proc.returncode != 0:
        raise SystemExit(f"harness run {run_id} failed rc={proc.returncode}:\n{proc.stderr[-2000:]}")
    fixture = json.loads(spec.read_text(encoding="utf-8"))["fixture"]
    result_dir = ROOT / "evaluation" / "results" / run_id / fixture
    probe_results = json.loads((result_dir / "probe-results-llm1.json").read_text(encoding="utf-8"))
    compile_record = json.loads((result_dir / "compile-llm1.json").read_text(encoding="utf-8"))
    metrics = json.loads((result_dir / "metrics.json").read_text(encoding="utf-8"))
    return {
        "probe_results": probe_results,
        "compile_ok": bool(compile_record.get("ok")),
        "metrics": metrics,
        "result_dir": str(result_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive", type=Path, default=DEFAULT_POSITIVE)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--audit-dir", type=Path, default=ROOT / "evaluation/results/verdict-audit-v1")
    args = parser.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    withheld = set(spec.get("withheld", []))
    feedback = [p["name"] for p in spec["probes"] if p["name"] not in withheld]
    positive_source = args.positive.read_text(encoding="utf-8")

    # clear previous RUN outputs but keep curated files (README.md) intact
    if args.audit_dir.exists():
        for child in args.audit_dir.iterdir():
            if child.name == "README.md":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    args.audit_dir.mkdir(parents=True, exist_ok=True)
    mutants_dir = args.audit_dir / "mutants"
    mutants_dir.mkdir(exist_ok=True)

    matrix: dict = {
        "spec": str(args.spec),
        "positive": str(args.positive),
        "label": args.label,
        "recorded_baseline_metrics": str(BASELINE_METRICS),
        "runs": {},
        "expectations": EXPECTED_CHANGED,
    }

    def verdict(run: dict) -> dict[str, bool]:
        return {name: bool(entry.get("semantic_match")) for name, entry in run["probe_results"].items()}

    # positive control: must be green across feedback AND withheld
    positive_run = run_harness(args.spec, args.positive, args.positive, args.label, "verdict-audit-v1/positive")
    pos_verdict = verdict(positive_run)
    positive_ok = (
        positive_run["compile_ok"]
        and all(pos_verdict.get(n, False) for n in feedback)
        and all(pos_verdict.get(n, False) for n in withheld)
    )
    matrix["runs"]["positive"] = {
        "result_dir": positive_run["result_dir"],
        "compile_ok": positive_run["compile_ok"],
        "feedback_passes": sum(pos_verdict.get(n, False) for n in feedback),
        "withheld_passes": sum(pos_verdict.get(n, False) for n in withheld),
        "feedback_total": len(feedback),
    }
    if not positive_ok:
        print(json.dumps(matrix["runs"]["positive"], indent=2))
        raise SystemExit("positive control failed to reproduce a green run; audit infrastructure broken")

    all_ok = True
    for name in MUTANT_ORDER:
        mutated = mutate(positive_source, name)
        mutant_path = mutants_dir / f"{name}.sol"
        mutant_path.write_text(mutated, encoding="utf-8")
        run = run_harness(args.spec, args.positive, mutant_path, args.label, f"verdict-audit-v1/{name}")
        run_verdict = verdict(run)
        expected_changed = feedback if EXPECTED_CHANGED[name] == "*" else EXPECTED_CHANGED[name]
        mismatches = []
        for probe in feedback:
            actual_changed = not run_verdict.get(probe, False)
            preregistered = probe in expected_changed
            if actual_changed != preregistered:
                mismatches.append(
                    {"probe": probe, "expected_changed": preregistered, "actual_changed": actual_changed}
                )
        entry = {
            "mutant": name,
            "result_dir": run["result_dir"],
            "compile_ok": run["compile_ok"],
            "verdict": run_verdict,
            "expectation_violations": mismatches,
            "ok": run["compile_ok"] and not mismatches,
        }
        if not entry["ok"]:
            all_ok = False
        matrix["runs"][name] = entry
        print(f"[{name}] ok={entry['ok']} violations={len(mismatches)}")

    matrix["all_ok"] = all_ok
    out = args.audit_dir / "matrix.json"
    out.write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"audit {'PASS' if all_ok else 'FAIL'} -> {out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
