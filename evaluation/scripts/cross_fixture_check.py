#!/usr/bin/env python3
"""Generalization check: run the observation/parity machinery on any spec.

Drives reference runtime and a compiled candidate through the fixture's own
setup and probes (from the spec), resolving candidate callforms via the
same fallback chain the loop uses (binding sig -> Unresolved_<sel> in
source -> lowercase var getter -> reference signature). Reports per-probe
semantic parity and, on divergence, the first differing step with values.

No fixture-specific logic; any tests/*.json with a compiled candidate.

Output: JSON evidence + summary on stdout.
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
ACCOUNT1 = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
REF, CAND = "0x1000000000000000000000000000000000001001", "0x2000000000000000000000000000000000002002"


def decl_sigs(source):
    out = {}
    for m in re.finditer(r"function\s+([A-Za-z_]\w*)\s*\(([^)]*)\)", source):
        name, params = m.group(1), m.group(2)
        types = ",".join(p.strip().split()[0] for p in params.split(",") if p.strip())
        out[name] = f"{name}({types})"
    for m in re.finditer(r"\bpublic\s+([A-Za-z_][\w\[\]]*)\s+([A-Za-z_]\w*)\s*;", source):
        typ, name = m.group(1), m.group(2)
        key = "()" if "mapping" not in typ else "(address)"
        out[name] = f"{name}{key}"
    return out


def resolve_all(source, spec_bindings):
    """reference name -> candidate callform, via the standard fallbacks."""
    decl = decl_sigs(source)
    lower = {n.lower(): s for n, s in decl.items()}
    resolved = {}
    for refname, binding in spec_bindings.items():
        refsig = binding["reference_signature"]
        want = binding.get("candidate_signatures", {}).get("seed-v2") or binding.get("candidate_signature")
        if want and want in decl:
            resolved[refname] = want
            continue
        sel = subprocess.run(["cast", "sig", refsig], capture_output=True, text=True, timeout=30).stdout.strip().lower()
        token = sel[2:] if sel.startswith("0x") else sel
        for prefix in ("Unresolved_", "unresolved_"):
            if prefix + token in decl:
                resolved[refname] = decl[prefix + token]
                break
            if prefix + token in lower:  # public var getter
                resolved[refname] = lower[prefix + token]
                break
        else:
            resolved[refname] = refsig
    return resolved


def calldata(sig, args):
    args = [a for a in (args if args is not None else []) if a != ""]
    if "bool" in sig:
        args = [{"1": "true", "0": "false"}.get(a, a) for a in args]
    fixed = []
    for a in args:
        if ((a.isdigit() and len(a) <= 40) or (a.startswith("0x") and 3 <= len(a) <= 42)):
            fixed.append("0x" + (a[2:] if a.startswith("0x") else a).rjust(40, "0"))
        else:
            fixed.append(a)
    args = fixed
    argv = ["cast", "calldata", sig] + args
    out = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=True)
    return out.stdout.strip()


def encode_raw(sig, tail):
    sel = subprocess.run(["cast", "sig", sig], capture_output=True, text=True, timeout=30, check=True).stdout.strip()
    return sel + tail[2:].lower()


def run_side(rpc, addr, callform, spec, side):
    """setup + every probe; returns per-probe step tuples."""
    snap = rpc.call("evm_snapshot")
    try:
        setup_ok = True
        for step in spec.get("setup", []):
            data = encode_raw(callform[step["call"]], step["args_tail"]) if "args_tail" in step else calldata(callform[step["call"]], step.get("args"))
            r = behavior.call_step(rpc, addr, data, CALLER, 0, step.get("send", False))
            setup_ok = setup_ok and r["ok"]
        probes = {}
        for probe in spec["probes"]:
            steps = []
            for step in probe["steps"]:
                sender = CALLER
                if "caller" in step:
                    sender = ACCOUNT1 if step["caller"] == 1 else CALLER
                if step.get("truncated"):
                    sig0 = callform[step["call"]]
                    sel0 = subprocess.run(["cast", "sig", sig0], capture_output=True, text=True, timeout=30, check=True).stdout.strip()
                    data = sel0 + "00" * 2  # truncated arguments: two bytes only
                else:
                    data = encode_raw(callform[step["call"]], step["args_tail"]) if "args_tail" in step else calldata(callform[step["call"]], step.get("args"))
                r = behavior.call_step(rpc, addr, data, sender, int(step.get("value") or 0), step.get("send", False))
                steps.append((r["ok"], (r["return_data"] or "").lower(), (r["revert_data"] or "").lower(), r.get("contract_balance")))
            probes[probe["name"]] = steps
        return {"setup_ok": setup_ok, "probes": probes}
    finally:
        rpc.call("evm_revert", [snap])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--reference", type=Path, required=True)
    ap.add_argument("--candidate-src", type=Path, required=True)
    ap.add_argument("--solc", default="0.8.30")
    ap.add_argument("--bindings", type=Path, default=None, help="selector-bindings.json from the candidate's harness run")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    source = args.candidate_src.read_text(encoding="utf-8")
    rec = behavior.compile_candidate(source, args.solc, Path(str(args.output) + ".work"), "candidate")
    if not rec.get("ok"):
        print((rec.get("stderr") or "compile failed")[-1200:])
        return 2
    refhex = args.reference.read_text(encoding="utf-8").strip()
    if not refhex.startswith("0x"):
        refhex = "0x" + refhex

    callform = resolve_all(source, spec["bindings"])
    if args.bindings and args.bindings.exists():
        saved = json.loads(args.bindings.read_text(encoding="utf-8")).get("bindings", {})
        for refname, entry in saved.items():
            if entry.get("available") and entry.get("candidate_signature"):
                callform[refname] = entry["candidate_signature"]
    anvil = behavior.Anvil()
    try:
        rpc = anvil.rpc
        rpc.call("anvil_setCode", [REF, refhex])
        rpc.call("anvil_setCode", [CAND, rec["deployed_bytecode"]])
        R = run_side(rpc, REF, refmap(spec), spec, "ref")
        K = run_side(rpc, CAND, callform, spec, "cand")
        evidence = {"callform": callform, "setup_ok": {"ref": R["setup_ok"], "cand": K["setup_ok"]}, "probes": {}}
        perfect = 0
        for name in R["probes"]:
            rs, ks = R["probes"][name], K["probes"][name]
            eq = len(rs) == len(ks) and all(
                a[0] == b[0] and a[1] == b[1] and a[2] == b[2] for a, b in zip(rs, ks)
            )
            evidence["probes"][name] = {"parity": eq}
            if not eq:
                for i, (a, b) in enumerate(zip(rs, ks)):
                    if a != b:
                        evidence["probes"][name]["first_diff"] = {"step": i, "ref": a[:3], "cand": b[:3]}
                        break
            else:
                perfect += 1
        evidence["summary"] = {"probes": len(R["probes"]), "parity": perfect}
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(f"setup ok ref={R['setup_ok']} cand={K['setup_ok']}; parity {perfect}/{len(R['probes'])}")
        for name, e in evidence["probes"].items():
            if not e["parity"]:
                fd = e.get("first_diff", {})
                print(f"  DIFF {name} step {fd.get('step')} ref={fd.get('ref')} cand={fd.get('cand')}")
        return 0
    finally:
        anvil.stop()


def refmap(spec):
    return {k: v["reference_signature"] for k, v in spec["bindings"].items()}


if __name__ == "__main__":
    raise SystemExit(main())
