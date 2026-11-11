#!/usr/bin/env python3
"""Event-layout repair: restore `indexed` from observed reference events.

The decompiler emits event declarations without the ``indexed`` modifier, so
compiled candidates pack every argument into the data area while the reference
indexes parameters into topics. This tool reads the harness probe results of the
reference side (black-box observations only), counts the indexed parameters per
event identity (topics minus the signature topic), and rewrites the matching
alias declaration with ``indexed`` on the first k parameters - consistent counts
only, abstentions recorded. Emission order follows the declaration; the harness
re-run is the acceptance gate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def event_id(name: str) -> str | None:
    match = re.search(r"([0-9a-fA-F]{8})$", name)
    return match.group(1).lower() if match else None


def observed_indexed_counts(probe_results: dict) -> dict[str, tuple[int, str]]:
    """event id -> (indexed param count, consistency), from reference observations."""
    counts: dict[str, set[int]] = {}
    for entry in probe_results.values():
        for step_events in entry.get("events_reference", []):
            for event in step_events:
                identity = event.get("event")
                if identity:
                    counts.setdefault(identity, set()).add(len(event.get("topics", [])))
    return {
        identity: (next(iter(seen)), "consistent" if len(seen) == 1 else "ambiguous")
        for identity, seen in counts.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--probe-results", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source = args.candidate.read_text(encoding="utf-8")
    probe_results = json.loads(args.probe_results.read_text(encoding="utf-8"))
    counts = observed_indexed_counts(probe_results)

    edits = []
    for match in list(re.finditer(r"event\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*;", source)):
        name = match.group(1)
        identity = event_id(name)
        if identity not in counts:
            continue
        indexed_count, consistency = counts[identity]
        if consistency != "consistent":
            edits.append({"event": name, "abstain": f"ambiguous indexed counts {counts[identity]}"})
            continue
        params = [p.strip() for p in match.group(2).split(",") if p.strip()]
        if indexed_count == 0 or indexed_count > len(params):
            continue
        new_params = [
            f"{p} indexed" if i < indexed_count and " indexed" not in p else p
            for i, p in enumerate(params)
        ]
        if new_params == params:
            continue
        old_decl = f"event {name}({match.group(2)});"
        new_decl = f"event {name}({', '.join(new_params)});"
        if source.count(old_decl) != 1:
            edits.append({"event": name, "abstain": "declaration not unique"})
            continue
        source = source.replace(old_decl, new_decl)
        edits.append(
            {
                "event": name,
                "indexed": indexed_count,
                "evidence": "reference-side observed topic counts, consistent across probes",
                "assumption": (
                    "heuristic: the first k parameters are the indexed ones; "
                    "per-parameter positions are not derivable from counts alone"
                ),
            }
        )

    args.out.write_text(source, encoding="utf-8")
    print(json.dumps({"out": str(args.out), "edits": edits}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
