#!/usr/bin/env python3
"""Deterministic behavior-driven body synthesis for error-path units.

The seed repair (prepare_candidate) makes the decompiled candidate compile, but
the decompiler loses body-level behavior: reverting units come out empty or with
alias-selector reverts (keccak of the declared alias name instead of the embedded
selector). This tool re-synthesizes unit bodies from BLACK-BOX reference
observations only (no reference Solidity, no LLM):

  class "revert-payload":  the reference observation carries revert bytes ->
                           a constant-payload revert (assembly mstore words +
                           revert(p, len)) reproducing the observed bytes exactly.
  class "silent-failure":  the observation is a failure with no payload -> the
                           unit is an exceptional halt; variants (gas-burn loop,
                           invalid opcode) are tried in a fixed order and accepted
                           only on harness parity.

Unit resolution is selector-based: the probe's reference selector must appear in
the candidate unit's own @custom:selector provenance. Only failing units are
rewritten; passing units are untouched. Every rewrite is acceptance-gated by the
harness run performed by the caller.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVESTIGATOR = ROOT / "evaluation" / "scripts" / "run_investigator.py"


def _load_investigator():
    spec = importlib.util.spec_from_file_location("_inv_syn", INVESTIGATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_inv_syn"] = module
    spec.loader.exec_module(module)
    return module


investigator = _load_investigator()


def payload_words(payload_hex: str) -> tuple[list[str], int]:
    """Split payload bytes into left-aligned 32-byte words for mstore codegen."""
    data = payload_hex.lower().removeprefix("0x")
    if len(data) % 2:
        raise SystemExit(f"odd-length payload hex: {payload_hex}")
    words = []
    for i in range(0, len(data), 64):
        chunk = data[i : i + 64]
        words.append(chunk.ljust(64, "0"))
    return ["0x" + w for w in words], len(data) // 2


def raw_revert_body(payload_hex: str, indent: str = "        ") -> str:
    """Assembly reverting with the exact constant payload."""
    words, length = payload_words(payload_hex)
    lines = [f"{indent}assembly {{"]
    lines.append(f"{indent}    let p := mload(0x40)")
    for offset, word in enumerate(words):
        lines.append(f"{indent}    mstore(add(p, 0x{offset * 32:02x}), {word})")
    lines.append(f"{indent}    revert(p, 0x{length:x})")
    lines.append(f"{indent}}}")
    return "\n".join(lines)


GAS_BURN_BODY = '        while (true) {\n            keccak256("consume gas");\n        }'
INVALID_OPBODY = "        assembly {\n            invalid()\n        }"

SILENT_FAILURE_VARIANTS = {"gas-burn": GAS_BURN_BODY, "invalid-opcode": INVALID_OPBODY}


def classify(observation: dict) -> tuple[str, dict]:
    """Observation class -> (template, template args). Observation-driven only."""
    if observation.get("ok"):
        raise SystemExit("synthesis refused: unit observation is successful; nothing to synthesize")
    payload = observation.get("revert_data")
    if payload:
        return "revert-payload", {"payload": payload}
    return "silent-failure", {}


def unit_for_selector(source: str, selector: str):
    """The parsed function whose @custom:selector provenance carries `selector`."""
    parsed = investigator.parse_contract(source, None)
    token = selector.lower().removeprefix("0x")
    for unit in parsed.functions:
        if token in unit.text[: unit.text.find("function") if "function" in unit.text else 0] or re.search(
            r"@custom:selector\s+0x%s\b" % token, unit.text
        ):
            return unit
    return None


def replace_unit_body(source: str, unit, new_body: str) -> str:
    """Replace the brace block of `unit` in `source`, keeping comment and header."""
    text = source[unit.start : unit.end]
    fpos = text.find("function")
    if fpos < 0:
        raise SystemExit("unit text has no declaration; parse drift")
    brace = text.find("{", fpos)
    close = text.rfind("}")
    if brace < 0 or close <= brace:
        raise SystemExit("unit brace structure not found; parse drift")
    return source[: unit.start] + text[: brace + 1] + "\n" + new_body + "\n    " + text[close:] + source[unit.end :]


def variant_order(observation: dict) -> list[tuple[str, str]]:
    """Fixed variant order for silent failures; the caller accepts on parity."""
    kind, args = classify(observation)
    if kind == "revert-payload":
        return [("revert-payload", raw_revert_body(args["payload"]))]
    return list(SILENT_FAILURE_VARIANTS.items())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--probe-results", type=Path, required=True, help="harness probe results identifying failing units")
    parser.add_argument("--variant", default=None, help="silent-failure variant to apply (default: first)")
    parser.add_argument("--label", default=None, help="only rewrite units for this probe subset file (JSON list)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    source = args.candidate.read_text(encoding="utf-8")
    observations = json.loads(args.observations.read_text(encoding="utf-8"))["observations"]
    probe_results = json.loads(args.probe_results.read_text(encoding="utf-8"))

    if args.label:
        targets = set(json.loads(Path(args.label).read_text(encoding="utf-8")))
    else:
        targets = {name for name, entry in probe_results.items() if not entry.get("semantic_match")}

    rewrites: dict[int, tuple[str, str]] = {}  # unit span start -> (unit name, body)
    plan: list[dict] = []
    for name in sorted(targets):
        entry = probe_results.get(name)
        if entry is None or entry.get("semantic_match"):
            continue  # passing units are never rewritten
        obs = observations[name]
        unit = unit_for_selector(source, obs["reference_selector"])
        if unit is None:
            plan.append({"probe": name, "error": "no candidate unit carries the reference selector"})
            continue
        variants = variant_order(obs)
        if args.variant and obs["revert_data"] is None:
            variants = [(args.variant, SILENT_FAILURE_VARIANTS[args.variant])]
        kind, body = variants[0]
        # keyed by span offset, not name: overloaded names must not collide
        existing = rewrites.get(unit.start)
        if existing not in (None, (unit.name, body)):
            raise SystemExit(f"unit at {unit.start} targeted by conflicting rewrites")
        rewrites[unit.start] = (unit.name, body)
        plan.append({"probe": name, "unit": unit.name, "template": kind})

    # descending span order: each replacement only shifts positions after it, so
    # the remaining (smaller) starts from the original parse stay valid
    for start in sorted(rewrites, reverse=True):
        _, body = rewrites[start]
        parsed = investigator.parse_contract(source, None)
        unit = next(u for u in parsed.functions if u.start == start)
        source = replace_unit_body(source, unit, body)

    args.out.write_text(source, encoding="utf-8")
    print(json.dumps({"out": str(args.out), "rewrites": plan}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
