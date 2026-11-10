#!/usr/bin/env python3
"""State-distinguishability diagnostic (evaluation-only, offline).

Does the candidate retain enough state information to implement the
required behavior, and which write destroyed it?

Raw (ok, return_data, revert_data) triples throughout; no ABI files, no
reference Solidity, no withheld expectations. Per-side selectors come from
each side's own declared signature (candidate: its source; reference: its
published two-word setLimits dispatch).

1. Paired histories: two setLimits setups differing in the second calldata
   word, then one identical continuation; a side whose continuation is
   byte-identical across configs has collapsed that distinction.
2. Regime map on empty storage: deposit 0/100/1000001 and paused, plus a
   stats read - the reference column is the exact behavior any candidate
   deposit rewrite must reproduce.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


behavior = _load("run_behavior", ROOT / "evaluation" / "scripts" / "run_behavior.py")

CALLER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
REF_ADDR = "0x1000000000000000000000000000000000000001"
CAND_ADDR = "0x1000000000000000000000000000000000000002"

SETUPS = ["setLimits(uint256,uint256):10:5", "setLimits(uint256,uint256):10:50"]

CONTINUATION = [
    "limits()::",
    "isWithinLimits(uint256):100:",
    "isWithinLimits(uint256):1000001:",
    "deposit(uint256):100:send",
    "getStats(address):0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266:",
]

REGIMES = {
    "empty-deposit-0": ["deposit(uint256):0:", "getStats(address):0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266:"],
    "empty-deposit-100": [
        "deposit(uint256):100:",
        "getStats(address):0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266:",
    ],
    "empty-deposit-1000001": [
        "deposit(uint256):1000001:",
        "getStats(address):0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266:",
    ],
    "paused-deposit-100": [
        "pause()::send",
        "deposit(uint256):100:",
        "getStats(address):0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266:",
    ],
}

REFERENCE_SIGS = {
    "setLimits": "setLimits(uint256,uint256)",
    "deposit": "deposit(uint256)",
    "getStats": "getStats(address)",
    "pause": "pause()",
    "limits": "limits()",
    "isWithinLimits": "isWithinLimits(uint256)",
}


def candidate_sigs(source):
    sigs = {}
    for match in re.finditer(r"function\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", source):
        name, params = match.group(1), match.group(2)
        types = ",".join(p.strip().split()[0] for p in params.split(",") if p.strip())
        sigs[name] = f"{name}({types})"
    return sigs


def step_once(rpc, addr, sigs, spec):
    body = spec.removesuffix(":send")
    send = spec.endswith(":send")
    name_full, _, argstr = body.partition(":")
    name = name_full.split("(")[0]
    args = [a for a in argstr.split(":") if a]
    # a side's setter may accept fewer words than the reference call carries
    # (the surplus-word story is the point): truncate until cast accepts
    calldata = None
    for k in range(len(args), -1, -1):
        probe = subprocess.run(
            ["cast", "calldata", sigs[name], *args[:k]], capture_output=True, text=True, timeout=30
        )
        if probe.returncode == 0:
            calldata = probe.stdout.strip()
            break
    if calldata is None:
        raise SystemExit(f"cast calldata failed for {sigs[name]} {args}")
    result = behavior.call_step(rpc, addr, calldata, CALLER, 0, send)
    return {"spec": spec, "ok": result["ok"], "return_data": result["return_data"], "revert_data": result["revert_data"]}


def run_sequence(rpc, addr, sigs, steps, setup=None):
    snapshot = rpc.call("evm_snapshot")
    try:
        setup_outcomes = [step_once(rpc, addr, sigs, s) for s in (setup or [])]
        return [step_once(rpc, addr, sigs, s) for s in steps], setup_outcomes
    finally:
        rpc.call("evm_revert", [snapshot])


def fingerprint(steps):
    return json.dumps(
        [{k: s[k] for k in ("ok", "return_data", "revert_data")} for s in steps], sort_keys=True
    )


def main():
    parser = argparse.ArgumentParser(description="state-distinguishability diagnostic")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--candidate-src", type=Path, required=True)
    parser.add_argument("--solc", default="0.8.30")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.candidate_src.read_text(encoding="utf-8")
    record = behavior.compile_candidate(source, args.solc, Path(str(args.output) + ".work"), "candidate")
    if not record.get("ok"):
        print((record.get("stderr") or "compile failed")[-1500:])
        return 2
    ref_hex = args.reference.read_text(encoding="utf-8").strip()
    if not ref_hex.startswith("0x"):
        ref_hex = "0x" + ref_hex

    cand = candidate_sigs(source)
    # decompiler unresolved names embed the real selector: Unresolved_8456cb59
    # IS keccak("pause()")[0:4]; resolve reference names by that hex
    by_selector = {}
    for name, sig in cand.items():
        token = name.split("_")[-1]
        if re.fullmatch(r"[0-9a-fA-F]{8}", token):
            by_selector.setdefault("0x" + token.lower(), []).append(sig)
    resolved = {}
    for name, ref_sig in REFERENCE_SIGS.items():
        sel = subprocess.run(
            ["cast", "sig", ref_sig], capture_output=True, text=True, timeout=30, check=True
        ).stdout.strip().lower()
        matches = by_selector.get(sel) or []
        if len(matches) == 1:
            resolved[name] = matches[0]
    resolved.setdefault("setLimits", cand.get("Unresolved_c4590d3f") or "")
    missing = set(REFERENCE_SIGS) - {k for k, v in resolved.items() if v}
    if missing:
        raise SystemExit(f"unresolved candidate selectors for {sorted(missing)}; have {cand}")
    side_sigs = {"reference": dict(REFERENCE_SIGS), "candidate": resolved}
    anvil = behavior.Anvil()
    try:
        rpc = anvil.rpc
        rpc.call("anvil_setCode", [REF_ADDR, ref_hex])
        rpc.call("anvil_setCode", [CAND_ADDR, record["deployed_bytecode"]])

        evidence = {"paired histories": {}, "regime map": {}, "side sigs": side_sigs}
        for side, addr in (("reference", REF_ADDR), ("candidate", CAND_ADDR)):
            sigs = side_sigs[side]
            histories = {}
            for setup in SETUPS:
                steps, setup_outcomes = run_sequence(rpc, addr, sigs, CONTINUATION, [setup])
                histories[setup] = {"steps": steps, "setup": setup_outcomes}
            evidence["paired histories"][side] = {
                "runs": histories,
                "identical_across_configs": fingerprint(histories[SETUPS[0]]["steps"])
                == fingerprint(histories[SETUPS[1]]["steps"]),
            }
        for regime, specs in REGIMES.items():
            setup = [s for s in specs if s.endswith(":send") and s.startswith("pause(")]
            steps = [s for s in specs if not s.startswith("pause(")]
            per_side = {}
            for side, addr in (("reference", REF_ADDR), ("candidate", CAND_ADDR)):
                seq, _ = run_sequence(rpc, addr, side_sigs[side], steps, setup)
                per_side[side] = seq
            evidence["regime map"][regime] = per_side

        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        for side in ("reference", "candidate"):
            print(f"[{side}] paired-history identical: {evidence['paired histories'][side]['identical_across_configs']}")
            for setup in SETUPS:
                ok = evidence["paired histories"][side]["runs"][setup]["setup"][0]["ok"]
                print(f"  setup {setup} ok={ok}")
        for regime, per_side in evidence["regime map"].items():
            same = fingerprint(per_side["reference"]) == fingerprint(per_side["candidate"])
            print(f"[{regime}] reference==candidate: {same}")
            if not same:
                for side in ("reference", "candidate"):
                    print(f"  {side}: {fingerprint(per_side[side])[:190]}")
        return 0
    finally:
        anvil.stop()


if __name__ == "__main__":
    raise SystemExit(main())
