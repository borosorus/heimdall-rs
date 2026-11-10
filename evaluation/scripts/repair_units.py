#!/usr/bin/env python3
"""Diagnostic-targeted unit repair for a prepared, still-uncompilable candidate.

Whole-source repair spends its completion budget reasoning about the
entire contract; this tool gives the model one failing function unit at a
time, with exactly the compiler diagnostics that point into it. The
contract's declarations are provided as read-only context. A rewrite is
accepted only when it parses as a single function with the original name
and parameter types (the dispatch identity the behavioral harness binds);
accepted rewrites are spliced with their original doc-comment header and
the merged source must compile.

Run prepare_candidate.py first: this tool assumes placeholder types,
declarations and arities are already source-derived and frozen.

No reference Solidity, reference ABI names, or probe observations are
sent; the model sees only prepared source fragments and compiler output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from collections import Counter
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_investigator import (  # noqa: E402
    Budget,
    ChatClient,
    ParseError,
    _mask_strings_and_comments,
    abi_signatures,
    dispatch_signature,
    dispatch_signature_text,
    parse_contract,
    parse_single_function,
    rb,
)

SYSTEM = (
    "You repair one Solidity function unit so it compiles. No reference "
    "implementation exists; infer intent only from the provided unit, the "
    "contract's declarations, and the compiler diagnostics. Respond with the "
    "complete replacement function: `source` must be the full Solidity code "
    "of that one function from the `function` keyword to its closing brace, "
    "with exactly the same name and the same parameter types; `notes` "
    "explains the fixes. Do not add declarations, imports, helpers, or "
    "comments. Fix the reported type errors with minimal, explicit changes; "
    "never apply an explicit conversion the diagnostics reject, and prefer "
    "the expression the compiler accepts (for example a storage bytes or "
    "string value compared with a number wants `.length`, not a cast) over "
    "assembly or masking tricks. Inline assembly cannot reference "
    "msg.data: hoist it into a local `bytes calldata` variable first and "
    "use `.offset`/`.length`, or use calldatacopy."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": ["source", "notes"],
    "additionalProperties": False,
}

MAX_REPAIRED_UNITS = 6


class RepairUnitsError(RuntimeError):
    pass


def _compile_text(record: dict[str, Any]) -> str:
    return (record.get("stderr") or "") + "\n" + (record.get("stdout") or "")


def _error_lines(record: dict[str, Any]) -> list[int]:
    """Source line numbers referenced by compiler diagnostics."""
    return sorted(
        {
            int(match)
            for match in re.findall(r"--> src/[A-Za-z0-9_.-]+\.sol:(\d+):", _compile_text(record))
        }
    )


def _unit_line_span(parsed, unit) -> tuple[int, int]:
    start_line = parsed.source[: unit.start].count("\n") + 1
    end_line = parsed.source[: unit.end].count("\n") + 1
    return start_line, end_line


def _unit_error_codes(record: dict[str, Any], parsed, unit_name: str) -> Counter:
    """Multiset of compiler error codes whose location is inside the named unit."""
    unit = next((u for u in parsed.functions if u.name == unit_name), None)
    if unit is None:
        return Counter()
    codes: Counter = Counter()
    for block in re.split(r"(?=Error \(\d+\))", _compile_text(record)):
        match = re.search(r"--> src/[A-Za-z0-9_.-]+\.sol:(\d+):", block)
        code = re.match(r"Error \((\d+)\)", block.strip())
        if match and code:
            start_line, end_line = _unit_line_span(parsed, unit)
            if start_line <= int(match.group(1)) <= end_line:
                codes[code.group(1)] += 1
    return codes


def affected_units(parsed, record: dict[str, Any]) -> list[Any]:
    """Function units containing at least one diagnostic line, in file order."""
    lines = set(_error_lines(record))
    selected = []
    for unit in parsed.functions:
        start_line, end_line = _unit_line_span(parsed, unit)
        if lines & set(range(start_line, end_line + 1)):
            selected.append(unit)
    return selected


def diagnostics_for(record: dict[str, Any], parsed, unit) -> str:
    """The subset of compiler diagnostics whose location is inside ``unit``."""
    start_line, end_line = _unit_line_span(parsed, unit)
    selected = []
    for block in re.split(r"(?=Error \(\d+\))", _compile_text(record)):
        match = re.search(r"--> src/[A-Za-z0-9_.-]+\.sol:(\d+):", block)
        if match and start_line <= int(match.group(1)) <= end_line:
            selected.append(block.strip())
    return "\n\n".join(dict.fromkeys(selected)).strip()


def unit_prefix(unit) -> str:
    """Leading comment block of a unit, preserved across rewrites."""
    masked = _mask_strings_and_comments(unit.text, 0, len(unit.text))
    match = re.search(r"\bfunction\b", masked)
    if not match:
        return ""
    return unit.text[: match.start()]


def validate_rewrite(original, function_text: str) -> str:
    """Validate one function rewrite; returns the normalized function text."""
    if not isinstance(function_text, str) or not function_text.strip():
        raise RepairUnitsError("rewrite is empty")
    try:
        rewrite = parse_single_function(function_text)
    except ParseError as error:
        raise RepairUnitsError(f"rewrite does not parse as one function: {error}") from error
    if rewrite.name != original.name:
        raise RepairUnitsError(f"rewrite renamed {original.name} to {rewrite.name}")
    expected = dispatch_signature(original.header)
    actual = dispatch_signature(rewrite.header)
    if expected != actual:
        raise RepairUnitsError(
            "rewrite changed the dispatch signature: "
            f"{expected[0]}({','.join(expected[1])}) -> {actual[0]}({','.join(actual[1])})"
        )
    external = ("public", "external")
    original_masked = _mask_strings_and_comments(original.header, 0, len(original.header))
    rewrite_masked = _mask_strings_and_comments(rewrite.header, 0, len(rewrite.header))
    was_external = any(
        re.search(rf"\b{word}\b", original_masked) for word in external
    )
    is_external = any(re.search(rf"\b{word}\b", rewrite_masked) for word in external)
    if was_external and not is_external:
        raise RepairUnitsError(
            f"rewrite dropped the external visibility of {original.name}"
        )
    return rewrite.text.rstrip()


def apply_rewrites(parsed, rewrites: dict[str, str]) -> str:
    """Splice validated function bodies under their original comment headers.

    Rewrites address disjoint spans of the original parse, so applying in
    descending start order keeps every pending offset valid.
    """
    by_id = {unit.opaque_id: unit for unit in parsed.functions}
    splices = sorted(
        (
            (unit.start + len(unit_prefix(unit)), unit.end, function_text)
            for unit_id, function_text in rewrites.items()
            if (unit := by_id.get(unit_id)) is not None
        ),
        key=lambda item: -item[0],
    )
    source = parsed.source
    for start, end, text in splices:
        source = source[:start] + text + source[end:]
    return source


def repair_prompt(unit, prefix: str, diagnostics: str, declarations: str, previous_error: str | None) -> str:
    parts = [
        "Contract declarations (read-only context; do not repeat them):",
        declarations.strip() or "(none)",
        "",
        "Function unit to repair, including its comment header:",
        (prefix + unit.text[len(prefix) :]).strip(),
    ]
    if previous_error:
        parts.extend(["", f"Your previous rewrite was rejected: {previous_error}"])
    parts.extend(["", "Compiler diagnostics for this unit:", diagnostics or "(none)"])
    return "\n".join(parts)


def run(args: argparse.Namespace) -> int:
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise RepairUnitsError(f"output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text(encoding="utf-8")
    spec = json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else {}
    contract = spec.get("contract") or args.contract
    solc_version = spec.get("solc_version") or args.solc
    if not contract or not solc_version:
        raise RepairUnitsError("--spec must provide contract and solc_version, or pass --contract/--solc")

    try:
        parsed = parse_contract(source, contract)
    except ParseError as error:
        raise RepairUnitsError(f"input source does not parse: {error}") from error

    baseline = rb.compile_candidate(
        source, solc_version, args.output_dir / "work" / "prepared", "prepared", contract
    )
    (args.output_dir / "prepared-compile.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")

    attempts: list[dict[str, Any]] = []
    current = source
    current_parsed = parsed
    compile_record = baseline

    if baseline.get("ok"):
        metrics = _metrics(source, source, attempts, None, baseline, True, 0, 0)
        (args.output_dir / "candidate.sol").write_text(source, encoding="utf-8")
        (args.output_dir / "repair-units.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        print("prepared source already compiles; no repair needed")
        return 0

    affected = affected_units(current_parsed, baseline)
    if not affected:
        print("no compiler diagnostic maps into a function unit; nothing to repair", file=sys.stderr)
        return 2

    budget = Budget(args.max_calls, args.max_completion_tokens)
    client = ChatClient(
        args.llm_base_url,
        args.model,
        args.api_key,
        args.timeout,
        args.max_tokens,
        args.temperature,
        args.seed,
        args.response_format,
        args.output_dir,
        budget,
    )
    declarations = current_parsed.declarations_text
    accepted: dict[str, str] = {}
    unit_attempts: dict[str, int] = {}

    # Rounds re-derive the affected set from the latest compile: fixing one
    # unit surfaces errors in units that were clean before. Per-unit attempt
    # caps and the call budget bound the loop.
    for round_index in range(1, args.max_rounds + 1):
        if compile_record.get("ok"):
            break
        affected = affected_units(current_parsed, compile_record)
        affected = [
            unit for unit in affected if unit_attempts.get(unit.opaque_id, 0) < 2
        ]
        affected = affected[:MAX_REPAIRED_UNITS]
        if not affected:
            attempts.append({"round": round_index, "error": "no repairable unit remains"})
            break
        progress = False
        for unit in affected:
            if compile_record.get("ok") or not budget.can_call():
                break
            unit_attempts[unit.opaque_id] = unit_attempts.get(unit.opaque_id, 0) + 1
            diagnostics = diagnostics_for(compile_record, current_parsed, unit)
            prompt = repair_prompt(unit, unit_prefix(unit), diagnostics, declarations, None)
            started = time.time()
            data, error, call_record = client.request_json(
                prompt, "unit_repair", SCHEMA, f"{unit.opaque_id}-r{round_index}", SYSTEM
            )
            attempt: dict[str, Any] = {
                "round": round_index,
                "unit": unit.opaque_id,
                "name": unit.name,
                "call_mode": None if call_record is None else call_record["mode"],
                "latency_ms": int((time.time() - started) * 1000),
                "request_error": error,
            }
            attempts.append(attempt)
            if data is None:
                continue
            notes = data.get("notes")
            if isinstance(notes, str):
                attempt["notes"] = notes[:400]
            try:
                function_text = validate_rewrite(unit, data.get("source"))
            except RepairUnitsError as validation_error:
                attempt["accepted"] = False
                attempt["error"] = str(validation_error)
                continue

            old_parsed = current_parsed
            merged = apply_rewrites(current_parsed, {unit.opaque_id: function_text})
            compile_attempt = rb.compile_candidate(
                merged,
                solc_version,
                args.output_dir / "work" / f"{unit.opaque_id}-r{round_index}",
                f"{unit.opaque_id}-r{round_index}",
                contract,
            )
            attempt["function_sha256"] = hashlib.sha256(function_text.encode("utf-8")).hexdigest()
            # Progress is judged per unit by diagnostic identity, not by global
            # line sets: fixing one error unmasks the next layer elsewhere, and
            # a formatting-only rewrite that merely shifts lines is not progress.
            # A failed compile without locations proves nothing and is rolled back.
            new_parsed = parse_contract(merged, contract)
            old_codes = _unit_error_codes(compile_record, old_parsed, unit.name)
            new_codes = _unit_error_codes(compile_attempt, new_parsed, unit.name)
            # A failed compile with no located diagnostics for this unit proves
            # nothing about the rewrite; accept only located, strictly resolved
            # evidence or a full pass.
            improved = bool(compile_attempt.get("ok")) or (
                bool(old_codes)
                and bool(new_codes)
                and new_codes != old_codes
                and not (Counter(new_codes) - Counter(old_codes))
            )
            if improved:
                attempt["accepted"] = True
                attempt["compiled"] = bool(compile_attempt.get("ok"))
                current, current_parsed = merged, parse_contract(merged, contract)
                compile_record = compile_attempt
                accepted[unit.opaque_id] = function_text
                progress = True
            else:
                # Keep the better-known source; a rewrite that does not reduce
                # the diagnostic footprint is recorded and rolled back.
                attempt["accepted"] = False
                attempt["compiled"] = bool(compile_attempt.get("ok"))
                attempt["rolled_back"] = True
                attempt["error"] = (
                    f"unit diagnostics not resolved: "
                    f"{dict(new_codes) or 'locationless failure'} vs {dict(old_codes)}; rolled back"
                )
            if compile_attempt.get("ok"):
                break
        if not progress and not compile_record.get("ok"):
            break

    compiled = bool(compile_record.get("ok"))
    # Mirror the whole-source repair gate: a compiling candidate whose ABI
    # lost one of the original external signatures has shrunk the callable
    # surface; that is a failed repair, not a success.
    if compiled:
        observed = abi_signatures(compile_record.get("abi") or [])
        expected = [
            dispatch_signature_text(unit.header) for unit in parse_contract(source, contract).functions
        ]
        missing = [signature for signature in expected if signature not in observed]
        if missing:
            compiled = False
            compile_record = dict(compile_record)
            compile_record["ok"] = False
            compile_record["abi_loss"] = missing

    candidate_path = args.output_dir / "candidate.sol"
    candidate_path.write_text(current, encoding="utf-8")
    metrics = _metrics(
        source,
        current,
        attempts,
        accepted,
        compile_record,
        compiled,
        budget.calls,
        budget.completion_tokens,
    )
    (args.output_dir / "repair-units.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    if metrics["compiled"]:
        print(f"repaired source compiles: {candidate_path}")
        return 0
    print("unit repair did not produce a compilable candidate; see repair-units.json", file=sys.stderr)
    return 2


def _metrics(
    source: str,
    candidate: str,
    attempts: list[dict[str, Any]],
    accepted: dict[str, str] | None,
    compile_record: dict[str, Any],
    compiled: bool,
    calls: int,
    completion_tokens: int,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool": "repair_units",
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
        "compiled": compiled,
        "accepted_units": sorted(accepted) if accepted else [],
        "attempts": attempts,
        "llm_calls": calls,
        "completion_tokens": completion_tokens,
        "final_compile": {
            "ok": bool(compile_record.get("ok")),
            "returncode": compile_record.get("returncode"),
        },
    }


def build_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--contract", default=None)
    parser.add_argument("--solc", default=None)
    parser.add_argument("--llm-base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument(
        "--response-format",
        choices=["auto", "json-schema", "json-object", "text"],
        default="auto",
    )
    parser.add_argument("--max-tokens", type=int, default=49152)
    parser.add_argument("--max-completion-tokens", type=int, default=131072)
    parser.add_argument("--max-calls", type=int, default=6)
    parser.add_argument("--max-rounds", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = build_args(argv)
    try:
        return run(args)
    except RepairUnitsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
