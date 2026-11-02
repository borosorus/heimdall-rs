#!/usr/bin/env python3
"""Bounded compile-repair bootstrap for an uncompilable decompiler candidate.

The multi-step investigator requires a compilable starting source. Deterministic
Heimdall output often is not: it can declare storage with placeholder types, emit
invalid casts, or reference undeclared errors/events. This script feeds the
candidate source and the compiler diagnostics back to a model for at most N
attempts and accepts a result only when it compiles and preserves every original
function's name and parameter types.

No reference Solidity, reference ABI names, source diffs, or withheld probes are
sent to the model. The only inputs are the decompiler source, the contract name,
the solc version, and compiler output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_investigator import (  # noqa: E402
    Budget,
    ChatClient,
    ParseError,
    abi_signatures,
    compile_error_summary,
    dispatch_signature_text,
    parse_contract,
    rb,
)

SYSTEM = (
    "You repair decompiled Solidity so it compiles. No reference implementation is "
    "available; infer intent only from the provided source and compiler diagnostics. "
    "Return the complete corrected contract, not a diff. Keep the contract name and "
    "every function's name and parameter types unchanged, and keep every function. "
    "Fix invalid types, undeclared custom errors/events, malformed casts and "
    "expressions, and missing declarations. Prefer minimal changes and plain typed "
    "assignments over assembly or address/integer masking tricks. Do not add imports "
    "or external contract calls."
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


class RepairError(Exception):
    pass


def dispatch_signatures(parsed) -> list[str]:
    return [_normalize_placeholder_types(dispatch_signature_text(unit.header)) for unit in parsed.functions]


def _normalize_placeholder_types(signature: str) -> str:
    """Map decompiler placeholder widths to valid Solidity types.

    Heimdall emits ``uint0``/``int0``/``bytes0`` when it cannot infer a width.
    These are not valid types and cannot compile; treating them as their widest
    counterparts keeps the parameter count and lets the repair focus on bodies.
    """
    for placeholder, replacement in (
        ("uint0", "uint256"),
        ("int0", "int256"),
        ("bytes0", "bytes"),
    ):
        signature = re.sub(rf"\b{placeholder}\b", replacement, signature)
    return signature


def diagnostics_text(record: dict[str, Any], limit: int = 4000) -> str:
    output = (record.get("stderr") or "") + "\n" + (record.get("stdout") or "")
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    text = "\n".join(lines)
    return text[-limit:] if len(text) > limit else text


def validate_repair(
    original_signatures: list[str],
    supported: set[str],
    original_contract: str,
    source: str,
    contract_name: str | None,
) -> Any:
    """Parse and dispatch-check a proposed repair. Raises RepairError with a reason."""
    if not source.strip():
        raise RepairError("proposed source is empty")
    try:
        parsed = parse_contract(source, contract_name)
    except ParseError as error:
        raise RepairError(f"proposed source does not parse: {error}") from error
    if parsed.contract_name != original_contract:
        raise RepairError(
            f"contract name changed from {original_contract!r} to {parsed.contract_name!r}"
        )
    names = [unit.name for unit in parsed.functions]
    if len(names) != len(set(names)):
        raise RepairError("proposed source contains duplicate function names")
    actual = dispatch_signatures(parsed)
    missing = [signature for signature in original_signatures if signature not in actual]
    if missing:
        shown = ", ".join(missing[:6])
        raise RepairError(f"proposed source removed or changed dispatch signatures: {shown}")
    unsupported = [signature for signature in actual if signature not in supported]
    if unsupported:
        shown = ", ".join(unsupported[:6])
        raise RepairError(f"proposed source declares unsupported signatures: {shown}")
    return parsed


def repair_prompt(
    source: str,
    contract: str,
    solc_version: str,
    diagnostics: str,
    previous_error: str | None,
) -> str:
    parts = [
        f"Contract name: {contract}",
        f"Required compiler: solc {solc_version}",
        "",
        "Compiler diagnostics for the current source:",
        diagnostics or "(none)",
    ]
    if previous_error:
        parts.extend(["", f"Previous attempt was rejected: {previous_error}"])
    parts.extend(["", "Current source:", source])
    return "\n".join(parts)


def run(args: argparse.Namespace) -> int:
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise RepairError(f"output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text(encoding="utf-8")
    spec = json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else {}
    contract = spec.get("contract") or args.contract
    solc_version = spec.get("solc_version") or args.solc
    if not contract or not solc_version:
        raise RepairError("--spec must provide contract and solc_version, or pass --contract/--solc")

    try:
        parsed = parse_contract(source, contract)
    except ParseError as error:
        raise RepairError(f"input source does not parse: {error}") from error
    original_signatures = dispatch_signatures(parsed)
    if not original_signatures:
        raise RepairError("input source declares no functions")

    baseline_compile = rb.compile_candidate(
        source, solc_version, args.output_dir / "work" / "baseline", "baseline", contract
    )
    (args.output_dir / "baseline-compile.json").write_text(
        json.dumps(baseline_compile, indent=2), encoding="utf-8"
    )
    diagnostics = diagnostics_text(baseline_compile)
    if baseline_compile.get("ok"):
        # Nothing to repair; keep an explicit record instead of a no-op LLM call.
        metrics = {
            "schema_version": 1,
            "contract": contract,
            "solc_version": solc_version,
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "candidate_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "compiled": True,
            "already_compiled": True,
            "attempts": [],
            "llm_calls": 0,
            "completion_tokens": 0,
        }
        (args.output_dir / "candidate.sol").write_text(source, encoding="utf-8")
        (args.output_dir / "metrics.json").write_text(
            json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
        )
        print("input already compiles; no repair requested")
        return 0

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
    attempts: list[dict[str, Any]] = []
    current = source
    previous_error: str | None = None
    compiled = False
    accepted_parsed = parsed
    accepted_source = source

    for attempt in range(1, args.max_attempts + 1):
        if not budget.can_call():
            attempts.append({"attempt": attempt, "error": "budget exhausted"})
            break
        prompt = repair_prompt(current, contract, solc_version, diagnostics, previous_error)
        label = f"repair-{attempt}"
        started = time.time()
        data, error, record = client.request_json(prompt, "compile_repair", SCHEMA, label, SYSTEM)
        attempt_record: dict[str, Any] = {
            "attempt": attempt,
            "call_mode": None if record is None else record["mode"],
            "latency_ms": int((time.time() - started) * 1000),
            "error": error,
        }
        attempts.append(attempt_record)
        if data is None:
            previous_error = error or "no response"
            continue

        proposed = data.get("source")
        attempt_record["notes"] = data.get("notes")
        if not isinstance(proposed, str):
            previous_error = "response missing a string 'source'"
            continue
        attempt_record["source_sha256"] = hashlib.sha256(proposed.encode("utf-8")).hexdigest()

        try:
            validate_repair(
                original_signatures,
                set(original_signatures),
                parsed.contract_name,
                proposed,
                contract,
            )
        except RepairError as validation_error:
            attempt_record["dispatch_ok"] = False
            attempt_record["error"] = str(validation_error)
            previous_error = str(validation_error)
            continue

        compile_record = rb.compile_candidate(
            proposed, solc_version, args.output_dir / "work" / f"{label}-build", label, contract
        )
        attempt_record["compiled"] = bool(compile_record.get("ok"))
        attempt_record["compile_summary"] = compile_error_summary(compile_record)
        attempt_record["compiler_returncode"] = compile_record.get("returncode")
        if not compile_record.get("ok"):
            previous_error = None
            diagnostics = diagnostics_text(compile_record)
            continue

        observed = abi_signatures(compile_record.get("abi") or [])
        missing = [signature for signature in original_signatures if signature not in observed]
        if missing:
            attempt_record["compiled"] = False
            attempt_record["error"] = (
                "compiled ABI lost dispatch signatures: " + ", ".join(missing[:6])
            )
            previous_error = attempt_record["error"]
            diagnostics = diagnostics_text(compile_record)
            continue

        attempt_record["dispatch_ok"] = True
        compiled = True
        accepted_source = proposed
        accepted_parsed = parse_contract(proposed, contract)
        break

    candidate_path = args.output_dir / "candidate.sol"
    candidate_path.write_text(accepted_source, encoding="utf-8")
    metrics = {
        "schema_version": 1,
        "contract": contract,
        "solc_version": solc_version,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "candidate_sha256": hashlib.sha256(accepted_source.encode("utf-8")).hexdigest(),
        "compiled": compiled,
        "already_compiled": False,
        "attempts": attempts,
        "dispatch_signatures": dispatch_signatures(accepted_parsed),
        "llm_calls": budget.calls,
        "completion_tokens": budget.completion_tokens,
        "prompt_chars": budget.prompt_chars,
        "elapsed_ms": int((time.time() - budget.started_at) * 1000),
    }
    (args.output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    if compiled:
        print(f"repaired source compiles: {candidate_path}")
        return 0
    print("repair did not produce a compilable candidate; see metrics.json", file=sys.stderr)
    return 2


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
    parser.add_argument("--max-completion-tokens", type=int, default=200_000)
    parser.add_argument("--max-calls", type=int, default=9)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = build_args(argv)
    if args.max_attempts < 1:
        raise RepairError("--max-attempts must be at least 1")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
