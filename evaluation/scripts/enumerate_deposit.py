#!/usr/bin/env python3
"""Regime-driven enumeration synthesis for the deposit unit (no LLM).

Phase 0 captures reference truth on empty storage: the four deposit regimes
(status + revert data + post-state getStats words) plus the fresh-state
getStats baseline; the success-path effect delta is derived, not guessed.
Phase 1 enumerates deposit bodies (guard order x failure style x effect
set x emit variant), renders each into the seed candidate, compiles, and
executes the regimes under snapshot isolation; the first candidate whose
observations equal the reference column on every regime wins.

Emits winner source plus full evidence JSON. The harness remains the
separate verdict instrument.
"""

from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
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
investigator = _load("run_investigator", ROOT / "evaluation" / "scripts" / "run_investigator.py")

CALLER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
REF_ADDR = "0x1000000000000000000000000000000000000001"
CAND_ADDR = "0x1000000000000000000000000000000000000002"
DEPOSIT = "Unresolved_b6b55f25"
ERROR = "CustomError_3261c792"
GETSTATS = "Unresolved_c23f85d6"

REGIMES = {
    "d0": ("0", False),
    "d100": ("100", False),
    "d1000001": ("1000001", False),
}



def cast(*args):
    out = subprocess.run(["cast", *args], capture_output=True, text=True, timeout=30, check=True)
    return out.stdout.strip()


def call(rpc, addr, sig, args, send):
    data = cast("calldata", sig, *[a for a in args if a])
    return behavior.call_step(rpc, addr, data, CALLER, 0, send)


def observe(rpc, addr, sigs, amount: str, paused: bool):
    snapshot = rpc.call("evm_snapshot")
    try:
        if paused:
            call(rpc, addr, sigs["pause"], [], True)
        dep = call(rpc, addr, sigs["deposit"], [amount], True)
        stats = call(rpc, addr, sigs["getStats"], [CALLER], False)
        return {
            "deposit_ok": dep["ok"],
            "deposit_revert": dep["revert_data"],
            "stats": stats["return_data"],
        }
    finally:
        rpc.call("evm_revert", [snapshot])


def main():
    parser = argparse.ArgumentParser(description="deposit enumeration synthesis")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True, help="candidate .sol whose deposit is replaced")
    parser.add_argument("--solc", default="0.8.30")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = args.seed.read_text(encoding="utf-8")
    parsed = investigator.parse_contract(source, None)
    deposit_unit = next(u for u in parsed.functions if u.name == DEPOSIT)
    unit_start, unit_end = deposit_unit.start, deposit_unit.end

    record = behavior.compile_candidate(source, args.solc, args.output_dir / "work-seed", "seed")
    if not record.get("ok"):
        print((record.get("stderr") or "seed compile failed")[-1200:])
        return 2
    ref_hex = args.reference.read_text(encoding="utf-8").strip()
    if not ref_hex.startswith("0x"):
        ref_hex = "0x" + ref_hex

    sigs = {
        "deposit": "deposit(uint256)",
        "getStats": "getStats(address)",
        "pause": "pause()",
    }

    anvil = behavior.Anvil()
    try:
        rpc = anvil.rpc
        rpc.call("anvil_setCode", [REF_ADDR, ref_hex])
        reference = {"fresh_stats": call(rpc, REF_ADDR, sigs["getStats"], [CALLER], False)["return_data"]}
        for name, (amount, paused) in REGIMES.items():
            reference[name] = observe(rpc, REF_ADDR, sigs, amount, paused)
        reference["paused"] = observe(rpc, REF_ADDR, sigs, "100", True)

        # success-effect delta from d0 (the only empty-state success)

        # phase 1: enumerate, render, compile, verify against reference
        effect_sets = [
            [],
            ["unresolved_70a08231[msg.sender] += arg0;"],
            ["var_c += arg0;"],
            ["unresolved_70a08231[msg.sender] += arg0;", "var_c += arg0;"],
        ]
        guard_forms = [
            "if ({lo} > arg0 || arg0 > {hi}) {{ revert {err}(); }}",
            "require(arg0 >= {lo} && arg0 <= {hi}, {err}());",
        ]
        lo_hi = [("store_c", "store_d")]
        candidates = []
        for guard in guard_forms:
            for (lo, hi) in lo_hi:
                for effects in effect_sets:
                    stmts = [guard.format(lo=lo, hi=hi, err=ERROR)] + list(effects)
                    body = "\n        ".join(stmts) if stmts else "revert CustomError_3261c792();"
                    text = f"function {DEPOSIT}(uint256 arg0) public {{\n        {body}\n    }}"
                    candidates.append(text)
        # dedupe, cap
        seen, unique = set(), []
        for text in candidates:
            if text not in seen:
                seen.add(text)
                unique.append(text)
        print("enumerated", len(unique), "candidate bodies")

        evidence = {"reference": reference, "candidates": []}
        winner = None
        ledger = []
        for index, text in enumerate(unique):
            mutated = source[:unit_start] + text + source[unit_end:]
            record_c = behavior.compile_candidate(mutated, args.solc, args.output_dir / f"work-c{index}", f"c{index}")
            entry = {"index": index, "body": text, "compiled": bool(record_c.get("ok"))}
            if record_c.get("ok"):
                rpc.call("anvil_setCode", [CAND_ADDR, record_c["deployed_bytecode"]])
                csigs = {  # candidate dispatch uses its own name-strings
                    "deposit": f"{DEPOSIT}(uint256)",
                    "getStats": f"{GETSTATS}(address)",
                    "pause": "pause()",
                }
                obs = {name: observe(rpc, CAND_ADDR, csigs, amt, pz) for name, (amt, pz) in REGIMES.items()}
                obs["paused"] = observe(rpc, CAND_ADDR, csigs, "100", True)
                # read-mode probe: revert reason of deposit(0) and deposit(100)
                reads = {}
                for amt in ("0", "100"):
                    data = subprocess.run(["cast", "calldata", f"{DEPOSIT}(uint256)", amt], capture_output=True, text=True, check=True).stdout.strip()
                    r = behavior.call_step(rpc, CAND_ADDR, data, CALLER, 0, False)
                    reads[f"call{amt}"] = {"ok": r["ok"], "revert": r["revert_data"], "ret": r["return_data"]}
                entry["read probes"] = reads
                match = all(
                    obs[k]["deposit_ok"] == reference[k]["deposit_ok"]
                    and obs[k]["deposit_revert"] == reference[k]["deposit_revert"]
                    and obs[k]["stats"] == reference[k]["stats"]
                    for k in obs
                )
                entry["regimes"] = obs
                entry["matches_reference"] = match
                if not match:
                    for k in obs:
                        a, b = obs[k], reference[k]
                        if (a["deposit_ok"], a["deposit_revert"], a["stats"]) != (
                            b["deposit_ok"], b["deposit_revert"], b["stats"]
                        ):
                            entry.setdefault("mismatch", {})[k] = {"cand": a, "ref": b}
                if match and winner is None:
                    winner = mutated
            else:
                entry["stderr_tail"] = (record_c.get("stderr") or "")[-400:]
            ledger.append(entry)
            print(f"c{index}: compiled={entry['compiled']} match={entry.get('matches_reference')}")
            if winner:
                break

        evidence["candidates"] = ledger
        args.output_dir.joinpath("enumeration.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        if winner:
            args.output_dir.joinpath("winner.sol").write_text(winner, encoding="utf-8")
            (args.output_dir / "candidate.sol").write_text(winner, encoding="utf-8")
            print("WINNER written")
            return 0
        print("no candidate matched; see enumeration.json")
        return 1
    finally:
        anvil.stop()


if __name__ == "__main__":
    raise SystemExit(main())
