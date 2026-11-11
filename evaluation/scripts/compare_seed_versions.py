#!/usr/bin/env python3
"""Paired seed-version comparison (V0 baseline tool vs current tree).

Runs this tree's prepare_candidate and a reference version's (a git worktree
path) on the same decompiled sources, in isolated subprocesses, and records
compile status plus output hashes for both. The point is a no-regression matrix:
wherever V0 produced a compilable seed, V1 must too; sha differences localize
which fixtures the new rules actually touched.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREPARE = ROOT / "evaluation" / "scripts" / "prepare_candidate.py"


def run_prepare(prepare_path: Path, source: Path, contract: str, solc: str, out: Path) -> dict:
    if out.exists():
        shutil.rmtree(out)
    proc = subprocess.run(
        [
            sys.executable,
            str(prepare_path),
            "--source",
            str(source),
            "--output-dir",
            str(out),
            "--contract",
            contract,
            "--solc",
            solc,
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(ROOT),
    )
    evidence_path = out / "prep-evidence.json"
    # rc 0 = compiled, rc 2 = ran fine but seed does not compile (evidence written);
    # both are valid outcomes. A missing evidence file is the only run failure.
    if not evidence_path.exists():
        return {
            "ok": False,
            "rc": proc.returncode,
            "stderr_tail": proc.stderr[-400:],
            "error": "prepare run produced no evidence",
        }
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    return {
        "ok": True,
        "rc": proc.returncode,
        "compiled": evidence.get("final_compiled"),
        "candidate_sha256": evidence.get("candidate_sha256"),
        "edit_count": evidence.get("edit_count"),
        "evidence": str(evidence_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v0-root", type=Path, required=True, help="worktree with the baseline tool")
    parser.add_argument("--case", action="append", required=True, help="name:baseline.sol (repeatable)")
    parser.add_argument("--contract", action="append", default=[], help="name:Contract (repeatable, optional per case)")
    parser.add_argument("--solc", default="0.8.30")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    contracts = dict(c.split(":", 1) for c in args.contract)
    v0_prepare_root = args.v0_root / "evaluation" / "scripts" / "prepare_candidate.py"
    matrix = {"v0_root": str(args.v0_root), "solc": args.solc, "cases": {}}
    for case in args.case:
        name, source = case.split(":", 1)
        source_path = Path(source)
        if not source_path.exists():  # relative to repo root
            source_path = ROOT / source
        contract = contracts.get(name)
        if not contract:
            from run_investigator import parse_contract  # noqa: PLC0415

            contract = parse_contract(source_path.read_text(encoding="utf-8"), None).contract_name
        work = args.work_dir / name
        v0 = run_prepare(v0_prepare_root, source_path, contract, args.solc, work / "v0")
        v1 = run_prepare(PREPARE, source_path, contract, args.solc, work / "v1")
        both_ok = bool(v0.get("ok")) and bool(v1.get("ok"))
        matrix["cases"][name] = {
            "source": str(source_path),
            "contract": contract,
            "v0": v0,
            "v1": v1,
            "both_versions_ran": both_ok,
            # regression only counts where BOTH versions produced valid evidence;
            # a failed run is an error, never an implicit pass
            "compile_no_regression": both_ok
            and ((v0.get("compiled") is not True) or (v1.get("compiled") is True)),
            "output_changed": both_ok and v0.get("candidate_sha256") != v1.get("candidate_sha256"),
        }
        print(
            f"{name:22s} v0_compiled={v0.get('compiled')} v1_compiled={v1.get('compiled')} "
            f"changed={matrix['cases'][name]['output_changed']}"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(matrix, indent=1) + "\n", encoding="utf-8")
    all_ok = all(
        c["both_versions_ran"] and c["compile_no_regression"] for c in matrix["cases"].values()
    )
    print(f"no-regression: {'PASS' if all_ok else 'FAIL'} -> {args.out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
