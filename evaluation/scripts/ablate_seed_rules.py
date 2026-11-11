#!/usr/bin/env python3
"""Stage-ablation evidence for the deterministic seed ladder.

Runs the full PREPARE_STAGES ladder and every leave-one-out variant on a source
file, compiling each variant's final source. The resulting matrix attributes the
seed's compilability to specific stages: a stage whose removal breaks the compile
is carrying a necessary repair; a stage whose removal changes nothing is spare
weight on that fixture. Read-only over the ladder; no fixture-name logic.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


prepare = _load("ablate_prepare", ROOT / "evaluation" / "scripts" / "prepare_candidate.py")
behavior = _load("ablate_behavior", ROOT / "evaluation" / "scripts" / "run_behavior.py")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run_variant(source: str, transforms, tag: str, work_root: Path, contract: str, solc: str) -> dict:
    try:
        stages = prepare.prepare_stages(source, transforms)
    except prepare.PreparationError as error:
        return {"variant": tag, "prep_error": str(error)}
    final = stages[-1].source
    record = behavior.compile_candidate(final, solc, work_root / tag, f"ablate-{tag}", contract)
    return {
        "variant": tag,
        "stages": [stage.name for stage in stages],
        "edits": {stage.name: len(stage.edits) for stage in stages},
        "candidate_sha256": sha256_text(final),
        "compiled": bool(record.get("ok")),
        "compile_returncode": record.get("returncode"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--solc", default="0.8.30")
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    work_root = args.work_dir
    work_root.mkdir(parents=True, exist_ok=True)

    full = list(prepare.PREPARE_STAGES)
    names = [fn.__name__ for fn in full]
    matrix = {
        "source_sha256": sha256_text(source),
        "solc": args.solc,
        "stage_order": names,
        "variants": [],
    }
    matrix["variants"].append(run_variant(source, tuple(full), "full", work_root, args.contract, args.solc))
    for index, name in enumerate(names):
        reduced = tuple(fn for i, fn in enumerate(full) if i != index)
        matrix["variants"].append(
            run_variant(source, reduced, f"minus-{name}", work_root, args.contract, args.solc)
        )

    args.out.write_text(json.dumps(matrix, indent=1) + "\n", encoding="utf-8")
    for variant in matrix["variants"]:
        print(f"{variant['variant']:28s} compiled={variant.get('compiled')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
