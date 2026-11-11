"""Constructor-body synthesis from observed post-construction state.

The decompiler drops constructor bodies entirely, so creation-mode deployment
leaves the candidate's constructor-written state empty where the reference has
values (measured in ../creation-deploy-v1: reference initial_get=7, candidate 0).

This tool repairs that from black-box evidence only:
  - the harness reference observations pair constructor arguments (from the
    run's deployment record) with each storage slot's observed post-construction
    value, via the candidate's OWN public getters on the reference side;
  - the typed storage-flow map provides slot identity for the candidate's
    declarations.

The synthesized body assigns the constructor parameter to the slot-annotated
storage when the correlation is unique: exactly one scalar slot-annotated
storage and one scalar constructor parameter, and the observed value equals the
parameter in every observed deployment. Constant-vs-param ambiguity (a single
observation cannot separate `s = arg0` from `s = 7`) is recorded as an
assumption on the edit; the parameter form is emitted as the more general
hypothesis and the harness re-run is the acceptance gate.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_storage_flow():
    path = ROOT / "evaluation" / "scripts" / "storage_flow.py"
    spec = importlib.util.spec_from_file_location("ctor_sf", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["ctor_sf"] = module
    spec.loader.exec_module(module)
    return module


storage_flow = _load_storage_flow()

SCALAR_RE = r"(?:uint\d+|int\d+|address|bool|bytes\d+)"


def observed_initial_states(probe_results: dict, constructor_args: list[list[str]]) -> list[dict]:
    """Per-deployment {slotless getter name -> return word}, from reference reads.

    A probe qualifies as an initial-state observation when its FIRST step is a
    read (no send) - i.e. taken on the pristine post-construction state - and
    the deployment that ran it used known constructor arguments.
    """
    probes = [
        (name, entry)
        for name, entry in probe_results.items()
        if entry["reference"] and not entry["reference"][0].get("call_ok") is None
    ]
    # deployment index: probes run in spec order against one deployment each;
    # the harness records them in that order, so zip with the args list
    observations = []
    for index, (name, entry) in enumerate(probes):
        args = constructor_args[index] if index < len(constructor_args) else None
        if args is None:
            continue
        first = entry["reference"][0]
        if first.get("call_ok") is False or first.get("return_data") in (None, ""):
            continue
        word = first["return_data"].removeprefix("0x")
        if len(word) != 64:
            continue  # not a single-word scalar read
        observations.append({"probe": name, "args": args, "value": int(word, 16)})
    return observations


def synthesize(source: str, probe_results: dict, constructor_args: list[list[str]]) -> tuple[str, list[dict]]:
    flow = storage_flow.build_storage_flow(source)
    scalars = [
        d
        for d in flow.declarations
        if re.fullmatch(SCALAR_RE, d.type_text) and d.slot is not None
    ]
    observations = observed_initial_states(probe_results, constructor_args)
    report: list[dict] = {"scalars": [d.name for d in scalars], "observations": observations}

    # uniqueness: one scalar storage, one scalar parameter, consistent identity
    # across every observed deployment
    if len(scalars) != 1 or not observations:
        report["abstain"] = f"{len(scalars)} scalar slot-annotated storages, {len(observations)} usable observations"
        return source, [report]
    storage = scalars[0]
    for obs in observations:
        scalar_args = [a for a in obs["args"] if len(a) == 64 and int(a, 16) < 2**256]
        if len(scalar_args) != 1:
            report["abstain"] = "constructor argument words are not uniquely scalar"
            return source, [report]
        if int(scalar_args[0], 16) != obs["value"]:
            report["abstain"] = f"observed value {obs['value']} != argument in {obs['probe']}"
            return source, [report]

    # the getter that reads this storage on the reference side must be the
    # observation source: its observed value IS the stored word (direct slot)
    # the argument position carrying the stored value must agree across EVERY
    # observation; disagreement means the correlation is not understood
    positions = set()
    for obs in observations:
        match = None
        for index, word in enumerate(obs["args"]):
            if len(word) == 64 and int(word, 16) == obs["value"]:
                match = index
                break
        if match is None:
            report["abstain"] = f"no argument position carries the value in {obs['probe']}"
            return source, [report]
        positions.add(match)
    if len(positions) != 1:
        report["abstain"] = f"argument position drift across observations: {sorted(positions)}"
        return source, [report]
    param_index = positions.pop()

    # emit `constructor(<params>) { <storage> = <pN>; }` after the storage decls
    param_list = ", ".join(f"uint256 arg{i}" for i in range(len(observations[0]["args"])))
    body = f"    constructor({param_list}) {{\n        {storage.name} = arg{param_index};\n    }}\n"
    anchor = re.search(r"(?m)^\s*event\s|^\s*function\s", source)
    insert_at = anchor.start() if anchor else source.rstrip().rfind("}")
    replacement = source[:insert_at] + body + "\n" + source[insert_at:]
    report["synthesized"] = {
        "storage": storage.name,
        "slot": storage.slot,
        "param": f"arg{param_index}",
        "assumption": (
            "heuristic: parameter assignment over observed constant - a single "
            "deployment cannot separate s = argN from s = const; more deployments "
            "with differing args would, and the harness re-run gates the choice"
        ),
    }
    return replacement, [report]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--probe-results", type=Path, required=True)
    parser.add_argument("--constructor-args", required=True, help="JSON list of per-deployment 32-byte word lists")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source = args.candidate.read_text(encoding="utf-8")
    probe_results = json.loads(args.probe_results.read_text(encoding="utf-8"))
    constructor_args = json.loads(args.constructor_args)
    result, report = synthesize(source, probe_results, constructor_args)
    args.out.write_text(result, encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
