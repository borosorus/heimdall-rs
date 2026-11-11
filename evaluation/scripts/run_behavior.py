#!/usr/bin/env python3
"""Run a bounded behavioral repair experiment for a decompiled contract.

The harness is intentionally evaluation-only. It compiles a baseline source and an LLM candidate,
executes deterministic raw-calldata probes against the original runtime bytecode and each
candidate on a local Anvil node, then optionally asks a model for bounded repairs based on all
observed failures. Reference Solidity is never read by this script or sent to the model. Reference
ABI is used only to resolve selectors and to report interface compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REF_ADDR = "0x00000000000000000000000000000000000000a1"
CAND_ADDR = "0x00000000000000000000000000000000000000b2"
UINT256_MAX = 2**256 - 1


class HarnessError(RuntimeError):
    pass


class RpcError(HarnessError):
    def __init__(self, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.data = data


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_command(
    command: list[str], cwd: Path | None = None, timeout: int = 300
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise HarnessError(f"required command not found: {command[0]}") from exc


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class Rpc:
    def __init__(self, url: str) -> None:
        self.url = url

    def call(self, method: str, params: list[Any] | None = None) -> Any:
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise HarnessError(f"RPC HTTP error {exc.code}: {detail}") from exc
        if "error" in body:
            error = body["error"]
            raise RpcError(str(error.get("message", error)), data=error.get("data"))
        return body.get("result")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Anvil:
    def __init__(self) -> None:
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.process = subprocess.Popen(
            ["anvil", "--silent", "--port", str(self.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.rpc = Rpc(self.url)
        self.wait_ready()

    def wait_ready(self) -> None:
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise HarnessError("anvil exited during startup")
            try:
                self.rpc.call("eth_chainId")
                return
            except Exception:
                time.sleep(0.1)
        raise HarnessError("timed out waiting for anvil")

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


def cast_selector(signature: str) -> str:
    result = run_command(["cast", "sig", signature], timeout=30)
    if result.returncode != 0:
        raise HarnessError(f"cast sig failed for {signature!r}: {result.stderr}")
    return result.stdout.strip().lower()


def abi_selectors(abi: list[dict[str, Any]]) -> set[str]:
    selectors: set[str] = set()
    for entry in abi:
        if entry.get("type") != "function":
            continue
        signature = f"{entry['name']}({','.join(item['type'] for item in entry.get('inputs', []))})"
        selectors.add(cast_selector(signature))
    return selectors


def compile_candidate(
    source: str,
    solc_version: str,
    work_dir: Path,
    label: str,
    contract_name: str | None = None,
) -> dict[str, Any]:
    if work_dir.exists():
        shutil.rmtree(work_dir)
    (work_dir / "src").mkdir(parents=True)
    source_path = work_dir / "src" / "Candidate.sol"
    source_path.write_text(source, encoding="utf-8")
    (work_dir / "foundry.toml").write_text(
        f'[profile.default]\nsolc_version = "{solc_version}"\n', encoding="utf-8"
    )
    result = run_command(
        [
            "forge",
            "build",
            "--force",
            "--offline",
            "--no-cache",
            "--no-lint",
            "--use",
            solc_version,
            "--optimize",
            "false",
        ],
        cwd=work_dir,
        timeout=300,
    )
    compile_record = {
        "label": label,
        "solc_version": solc_version,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "source_sha256": sha256_text(source),
    }
    if result.returncode != 0:
        compile_record["ok"] = False
        return compile_record

    artifacts = []
    for path in (work_dir / "out").rglob("*.json"):
        if "build-info" in path.parts:
            continue
        try:
            artifact = read_json(path)
        except json.JSONDecodeError:
            continue
        deployed = artifact.get("deployedBytecode")
        if isinstance(deployed, dict) and deployed.get("object") and artifact.get("abi"):
            artifacts.append((path, artifact))
    if not artifacts:
        compile_record["ok"] = False
        compile_record["error"] = "no compiled artifact with ABI and deployed bytecode"
        return compile_record

    if contract_name:
        named = [
            (path, artifact)
            for path, artifact in artifacts
            if artifact.get("contractName") == contract_name or path.stem == contract_name
        ]
        if len(named) != 1:
            compile_record["ok"] = False
            compile_record["error"] = (
                f"expected exactly one artifact for contract {contract_name!r}, "
                f"found {len(named)} among {len(artifacts)} artifacts"
            )
            return compile_record
        artifacts = named

    if len(artifacts) != 1:
        compile_record["ok"] = False
        compile_record["error"] = (
            f"expected exactly one compiled contract artifact, found {len(artifacts)}; "
            "set spec.contract to select a target"
        )
        return compile_record

    artifact_path, artifact = artifacts[0]
    compile_record.update(
        {
            "ok": True,
            "artifact": str(artifact_path.relative_to(work_dir)),
            "abi": artifact["abi"],
            "deployed_bytecode": artifact["deployedBytecode"]["object"],
        }
    )
    return compile_record


def encode_step(selector: str, step: dict[str, Any]) -> str:
    if step.get("truncated"):
        return selector
    tail = step.get("args_tail")
    if tail:
        return selector + tail.removeprefix("0x")
    args = step.get("args", [])
    encoded = "".join(f"{int(value, 0):064x}" for value in args)
    return selector + encoded


def normalize_logs(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "topics": [topic.lower() for topic in log.get("topics", [])],
            "data": (log.get("data") or "0x").lower(),
        }
        for log in logs
    ]


def trace_failed_call_gas(rpc: Rpc, call_params: dict) -> str | None:
    """Gas used by a failed eth_call, via debug_traceCall; None when unavailable.

    A concrete gas figure is evidence that the exceptional halt really executed on
    this node. It is recorded for the evidence check only - gas consumption is an
    implementation detail and deliberately excluded from equality comparison.
    Tracing is optional: any failure to trace degrades to None, never aborts.
    """
    try:
        result = rpc.call("debug_traceCall", [call_params, "latest", {"tracer": "callTracer"}])
        gas = result.get("gasUsed") if isinstance(result, dict) else None
        return hex(int(gas, 16)) if isinstance(gas, str) else None
    except (HarnessError, RpcError, KeyError, TypeError, ValueError):
        return None


def call_step(
    rpc: Rpc,
    to: str,
    calldata: str,
    sender: str,
    value: int,
    apply: bool,
) -> dict[str, Any]:
    call_params = {
        "from": sender,
        "to": to,
        "data": calldata,
        "value": hex(value),
        "gas": hex(5_000_000),
    }
    if not apply:
        try:
            returned = rpc.call("eth_call", [call_params])
            call_ok = True
            return_data = returned
            revert_data = None
        except RpcError as error:
            call_ok = False
            return_data = None
            revert_data = error.data.get("data") if isinstance(error.data, dict) else error.data
        return {
            "calldata": calldata,
            "call_ok": call_ok,
            "ok": call_ok,
            "status": 1 if call_ok else 0,
            "return_data": return_data,
            "revert_data": revert_data,
            # evidence only for failed calls; successful calls carry their payload
            "gas_used": None if call_ok else trace_failed_call_gas(rpc, call_params),
            "logs": [],
            "contract_balance": rpc.call("eth_getBalance", [to, "latest"]),
        }

    observation: dict[str, Any] = {
        "calldata": calldata,
        "call_ok": False,
        "ok": False,
        "status": 0,
        "return_data": None,
        "revert_data": None,
        "logs": [],
    }
    try:
        tx_hash = rpc.call("eth_sendTransaction", [call_params])
    except RpcError as error:
        raise HarnessError(
            f"transaction submission failed for calldata {calldata}: {error}"
        ) from error

    deadline = time.time() + 15
    receipt = None
    while time.time() < deadline:
        receipt = rpc.call("eth_getTransactionReceipt", [tx_hash])
        if receipt is not None:
            break
        time.sleep(0.05)
    if receipt is None:
        raise HarnessError(f"timed out waiting for receipt {tx_hash}")

    status = int(receipt.get("status", "0x0"), 16)
    observation.update(
        {
            "call_ok": status == 1,
            "ok": status == 1,
            "status": status,
            "logs": normalize_logs(receipt.get("logs", [])),
            "contract_balance": rpc.call("eth_getBalance", [to, "latest"]),
            "tx_hash": tx_hash,
        }
    )
    return observation


def run_sequence(
    rpc: Rpc,
    to: str,
    steps: list[dict[str, Any]],
    bindings: dict[str, dict[str, Any]],
    side: str,
    accounts: list[str],
) -> list[dict[str, Any]]:
    results = []
    for step in steps:
        call_name = step["call"]
        binding = bindings[call_name]
        selector = binding[f"{side}_selector"]
        sender = accounts[int(step.get("caller", 0))]
        value = int(step.get("value", "0"), 0)
        mode = "send" if step.get("send", False) else "read"
        if side == "candidate" and binding.get("available") is False:
            results.append(
                {
                    "call": call_name,
                    "calldata": None,
                    "call_ok": False,
                    "ok": False,
                    "status": 0,
                    "return_data": None,
                    "revert_data": None,
                    "logs": [],
                    "contract_balance": rpc.call("eth_getBalance", [to, "latest"]),
                    "sender": sender,
                    "value": str(value),
                    "mode": mode,
                    "unbound": True,
                    "unbound_reason": binding.get("unavailable_reason"),
                }
            )
            continue
        calldata = encode_step(selector, step)
        observation = call_step(
            rpc,
            to,
            calldata,
            sender,
            value,
            apply=bool(step.get("send", False)),
        )
        observation["call"] = call_name
        observation["sender"] = sender
        observation["value"] = str(value)
        observation["mode"] = mode
        results.append(observation)
    return results


def semantic_view(observation: dict[str, Any]) -> dict[str, Any]:
    if observation.get("unbound"):
        return {"unbound": observation.get("unbound_reason") or "binding unavailable"}
    return {
        "ok": observation.get("ok"),
        "return_data": (observation.get("return_data") or "").lower() or None,
        "revert_data": (observation.get("revert_data") or "").lower() or None,
        "contract_balance": observation.get("contract_balance"),
    }


def _observation_evidence_complete(observation: dict[str, Any]) -> bool:
    """An observation carries evidence when it states an outcome, not absence of one.

    A failed observation with no return, no revert payload, and no execution trace
    proves nothing about the candidate (lost revert reason, RPC hiccup); under
    strict comparison such steps cannot earn parity. A recorded gas figure from
    the failed-call trace is evidence that the halt executed.
    """
    if observation.get("unbound"):
        return True
    return bool(
        observation.get("ok")
        or observation.get("return_data")
        or observation.get("revert_data")
        or observation.get("gas_used")
    )


def sequence_matches(
    reference: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    strict_evidence: bool = False,
) -> bool:
    equal = len(reference) == len(candidate) and all(
        semantic_view(left) == semantic_view(right)
        for left, right in zip(reference, candidate)
    )
    if not equal:
        return False
    if strict_evidence:
        return all(
            _observation_evidence_complete(observation)
            for observation in [*reference, *candidate]
        )
    return True


def setup_ok(observations: list[dict[str, Any]]) -> bool:
    """A setup sequence is valid only when every step succeeded on-chain."""
    return bool(observations) and all(
        observation.get("call_ok", observation.get("ok", False)) for observation in observations
    )


def combined_semantic_match(
    setup_reference: list[dict[str, Any]],
    setup_candidate: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
    strict_evidence: bool = False,
) -> bool:
    # A probe whose reference setup reverts proves nothing about the candidate:
    # both sides can fail identically from default state. Such probes are
    # reported with semantic_match false, never as passes.
    if setup_reference and not setup_ok(setup_reference):
        return False
    return sequence_matches(
        setup_reference, setup_candidate, strict_evidence
    ) and sequence_matches(reference, candidate, strict_evidence)


def prompt_view(observation: dict[str, Any], include_logs: bool) -> dict[str, Any]:
    view = {
        "step": None,
        "mode": observation.get("mode"),
        "sender": observation.get("sender"),
        "value": observation.get("value"),
        "calldata": observation.get("calldata"),
        "ok": observation.get("ok"),
        "return_data": (observation.get("return_data") or "").lower() or None,
        "revert_data": (observation.get("revert_data") or "").lower() or None,
        "contract_balance": observation.get("contract_balance"),
        "logs": observation.get("logs", []) if include_logs else [],
    }
    if observation.get("unbound"):
        view["unbound"] = True
        view["unbound_reason"] = observation.get("unbound_reason")
    return view


def configured_match(result: dict[str, Any], compare_events: bool) -> bool:
    return result["semantic_match"] and (not compare_events or result["event_match"])


def event_matches(reference: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> bool:
    return len(reference) == len(candidate) and all(
        left.get("logs", []) == right.get("logs", [])
        for left, right in zip(reference, candidate)
    )


def combined_event_match(
    setup_reference: list[dict[str, Any]],
    setup_candidate: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> bool:
    return event_matches(setup_reference, setup_candidate) and event_matches(
        reference, candidate
    )


def select_candidate_signature(binding: dict[str, Any], candidate_label: str) -> str:
    candidate_signatures = binding.get("candidate_signatures")
    if candidate_signatures is not None:
        if not isinstance(candidate_signatures, dict):
            raise HarnessError("candidate_signatures must be an object keyed by label")
        candidate_signature = candidate_signatures.get(candidate_label)
        if candidate_signature is None:
            candidate_signature = binding.get("candidate_signature")
        if candidate_signature is None:
            raise HarnessError(
                f"no candidate signature for label {candidate_label!r}"
            )
    else:
        candidate_signature = binding.get("candidate_signature")
        if candidate_signature is None:
            raise HarnessError("missing candidate_signature")
    if not isinstance(candidate_signature, str) or not candidate_signature.strip():
        raise HarnessError("candidate signature must be a nonempty string")
    return candidate_signature


def load_bindings(
    spec: dict[str, Any],
    reference_abi: list[dict[str, Any]],
    candidate_label: str = "llm1",
) -> dict[str, Any]:
    reference_selectors = abi_selectors(reference_abi)
    bindings = json.loads(json.dumps(spec["bindings"]))
    for name, binding in bindings.items():
        reference_signature = binding["reference_signature"]
        candidate_signature = select_candidate_signature(binding, candidate_label)
        baseline_signature = binding.get("baseline_signature", candidate_signature)
        reference_selector = cast_selector(reference_signature)
        if reference_selector not in reference_selectors:
            raise HarnessError(
                f"reference signature not in reference ABI: {reference_signature}"
            )
        binding["candidate_signature"] = candidate_signature
        binding["candidate_label"] = candidate_label
        binding["reference_selector"] = reference_selector
        binding["baseline_signature"] = baseline_signature
        binding["baseline_selector"] = cast_selector(baseline_signature)
        binding["candidate_selector"] = cast_selector(candidate_signature)
    return bindings


def stage_address(index: int) -> str:
    return "0x" + format(0xB2 + index, "040x")


def bindings_for_stage(
    bindings: dict[str, Any], selector_key: str, compiled_selectors: set[str]
) -> dict[str, Any]:
    result = {}
    for name, binding in bindings.items():
        selector = binding[f"{selector_key}_selector"]
        available = selector in compiled_selectors
        entry = dict(binding)
        entry["candidate_selector"] = selector
        entry["available"] = available
        entry["unavailable_reason"] = (
            None
            if available
            else f"{selector_key} selector {selector} is not in the compiled ABI"
        )
        result[name] = entry
    return result


def interface_report(
    reference_selectors: set[str], candidate_selectors: set[str]
) -> dict[str, Any]:
    return {
        "reference_selector_count": len(reference_selectors),
        "candidate_selector_count": len(candidate_selectors),
        "matched": len(reference_selectors & candidate_selectors),
        "missing": sorted(reference_selectors - candidate_selectors),
        "candidate_only": sorted(candidate_selectors - reference_selectors),
    }


def run_probes(
    rpc: Rpc,
    spec: dict[str, Any],
    bindings: dict[str, Any],
    reference_addr: str,
    candidate_addr: str,
    accounts: list[str],
) -> dict[str, Any]:
    setup = spec.get("setup", [])
    probe_results: dict[str, Any] = {}
    base_snapshot = rpc.call("evm_snapshot")
    for probe in spec["probes"]:
        name = probe["name"]
        rpc.call("evm_revert", [base_snapshot])
        base_snapshot = rpc.call("evm_snapshot")
        setup_reference = (
            run_sequence(rpc, reference_addr, setup, bindings, "reference", accounts)
            if setup
            else []
        )
        reference = run_sequence(
            rpc, reference_addr, probe["steps"], bindings, "reference", accounts
        )

        rpc.call("evm_revert", [base_snapshot])
        base_snapshot = rpc.call("evm_snapshot")
        setup_candidate = (
            run_sequence(rpc, candidate_addr, setup, bindings, "candidate", accounts)
            if setup
            else []
        )
        candidate = run_sequence(
            rpc, candidate_addr, probe["steps"], bindings, "candidate", accounts
        )
        probe_results[name] = {
            "reference": reference,
            "candidate": candidate,
            "setup_reference": setup_reference,
            "setup_candidate": setup_candidate,
            "semantic_match": combined_semantic_match(
                setup_reference,
                setup_candidate,
                reference,
                candidate,
                strict_evidence=bool(spec.get("strict_evidence", False)),
            ),
            "event_match": combined_event_match(
                setup_reference, setup_candidate, reference, candidate
            ),
        }
    rpc.call("evm_revert", [base_snapshot])
    return probe_results


def summarize_stage(stage: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    compare_events = bool(spec.get("compare_events", False))
    withheld = set(spec.get("withheld", []))
    feedback_names = [probe["name"] for probe in spec["probes"] if probe["name"] not in withheld]
    withheld_names = [probe["name"] for probe in spec["probes"] if probe["name"] in withheld]
    results = stage.get("probe_results", {})
    matches = {
        name: configured_match(result, compare_events) for name, result in results.items()
    }
    compiled = bool(stage.get("compile"))
    stage.update(
        {
            "feedback_total": len(feedback_names),
            "withheld_total": len(withheld_names),
            "feedback_matched": sum(1 for name in feedback_names if matches.get(name))
            if compiled
            else None,
            "withheld_matched": sum(1 for name in withheld_names if matches.get(name))
            if compiled
            else None,
            "feedback_failing": (
                [name for name in feedback_names if not matches.get(name)] if compiled else []
            ),
            "withheld_failing": (
                [name for name in withheld_names if not matches.get(name)] if compiled else []
            ),
            "semantic_failing": [
                name for name, result in results.items() if not result["semantic_match"]
            ],
            "event_mismatches": [
                name for name, result in results.items() if not result["event_match"]
            ],
            "matches": matches,
            "executed_steps": sum(len(result["reference"]) for result in results.values()),
            "setup_steps": sum(
                len(result.get("setup_reference", [])) for result in results.values()
            ),
            "unbound_calls": sorted(
                {
                    observation["call"]
                    for result in results.values()
                    for observation in result["candidate"] + result.get("setup_candidate", [])
                    if observation.get("unbound")
                }
            ),
            "unbound_probes": sorted(
                {
                    name
                    for name, result in results.items()
                    if any(
                        observation.get("unbound")
                        for observation in result["candidate"]
                        + result.get("setup_candidate", [])
                    )
                }
            ),
            "blocked_reason": None if compiled else "candidate did not compile",
        }
    )
    return stage


def stage_metrics(stage: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": stage["label"],
        "compile": stage["compile"],
        "source_sha256": stage.get("source_sha256"),
        "interface": stage.get("interface"),
        "feedback_matched": stage.get("feedback_matched"),
        "feedback_total": stage.get("feedback_total"),
        "withheld_matched": stage.get("withheld_matched"),
        "withheld_total": stage.get("withheld_total"),
        "feedback_failing": stage.get("feedback_failing", []),
        "withheld_failing": stage.get("withheld_failing", []),
        "semantic_failing": stage.get("semantic_failing", []),
        "event_mismatches": stage.get("event_mismatches", []),
        "unbound_calls": stage.get("unbound_calls", []),
        "unbound_probes": stage.get("unbound_probes", []),
        "executed_steps": stage.get("executed_steps", 0),
        "setup_steps": stage.get("setup_steps", 0),
        "blocked_reason": stage.get("blocked_reason"),
    }


def build_repair_prompt(
    template: str,
    baseline_source: str,
    candidate_source: str,
    bindings: dict[str, Any],
    probe_results: dict[str, Any],
    passing_names: list[str],
    failing_names: list[str],
    opaque_entries: dict[str, str],
    opaque_probes: dict[str, str],
    compare_events: bool,
) -> str:
    bindings_block = [
        {
            "entrypoint": opaque_entries[name],
            "reference_selector": binding["reference_selector"],
            "candidate_selector": binding["candidate_selector"],
            "candidate_signature": binding["candidate_signature"],
        }
        for name, binding in bindings.items()
    ]
    passing_block = {
        opaque_probes[name]: {
            "setup": [
                {**prompt_view(observation, compare_events), "step": index}
                for index, observation in enumerate(
                    probe_results[name].get("setup_candidate", [])
                )
            ],
            "steps": [
                {**prompt_view(observation, compare_events), "step": index}
                for index, observation in enumerate(probe_results[name]["candidate"])
            ],
        }
        for name in passing_names
    }
    failing_block = [
        {
            "probe": opaque_probes[name],
            "setup": {
                "reference": [
                    {**prompt_view(observation, compare_events), "step": index}
                    for index, observation in enumerate(
                        probe_results[name].get("setup_reference", [])
                    )
                ],
                "candidate": [
                    {**prompt_view(observation, compare_events), "step": index}
                    for index, observation in enumerate(
                        probe_results[name].get("setup_candidate", [])
                    )
                ],
            },
            "reference": [
                {**prompt_view(observation, compare_events), "step": index}
                for index, observation in enumerate(probe_results[name]["reference"])
            ],
            "candidate": [
                {**prompt_view(observation, compare_events), "step": index}
                for index, observation in enumerate(probe_results[name]["candidate"])
            ],
        }
        for name in failing_names
    ]
    return (
        template.replace("<<BASELINE_SOURCE>>", baseline_source)
        .replace("<<CANDIDATE_SOURCE>>", candidate_source)
        .replace("<<BINDINGS>>", json.dumps(bindings_block, indent=2))
        .replace("<<PASSING_OBSERVATIONS>>", json.dumps(passing_block, indent=2))
        .replace("<<FAILING_OBSERVATIONS>>", json.dumps(failing_block, indent=2))
    )


def request_repair(
    base_url: str,
    model: str,
    api_key: str,
    timeout: int,
    max_tokens: int,
    temperature: float,
    seed: int,
    prompt: str,
    result_dir: Path,
    label: str,
) -> tuple[str | None, str | None]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "seed": seed,
        "max_tokens": max_tokens,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "repaired_contract",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"source": {"type": "string"}},
                    "required": ["source"],
                    "additionalProperties": False,
                },
            },
        },
    }
    request_body = json.dumps(body).encode("utf-8")
    write_json(result_dir / f"{label}-request.json", body)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=request_body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
        (result_dir / f"{label}-response.json").write_text(
            response_body + "\n", encoding="utf-8"
        )
        parsed = json.loads(response_body)
        content = parsed["choices"][0]["message"].get("content")
        if not content:
            raise HarnessError("repair response had no content")
        repaired_response = json.loads(content) if isinstance(content, str) else content
        repaired_source = repaired_response["source"]
        if not isinstance(repaired_source, str) or not repaired_source.strip():
            raise HarnessError("repair response source must be a nonempty string")
        return repaired_source, None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return None, f"LLM HTTP error {exc.code}: {detail}"
    except (
        urllib.error.URLError,
        HarnessError,
        json.JSONDecodeError,
        IndexError,
        KeyError,
        TypeError,
        ValueError,
        AttributeError,
        TimeoutError,
    ) as error:
        return None, str(error)


def evaluate_stage(
    rpc: Rpc,
    spec: dict[str, Any],
    bindings: dict[str, Any],
    reference_selectors: set[str],
    source: str,
    label: str,
    selector_key: str,
    stage_index: int,
    result_dir: Path,
) -> dict[str, Any]:
    work_dir = result_dir / "work" / label
    compile_record = compile_candidate(
        source, spec["solc_version"], work_dir, label, spec.get("contract")
    )
    write_json(result_dir / f"compile-{label}.json", compile_record)
    stage: dict[str, Any] = {
        "label": label,
        "source_sha256": sha256_text(source),
        "compile": bool(compile_record.get("ok")),
        "probe_results": {},
    }
    if not stage["compile"]:
        return summarize_stage(stage, spec)

    candidate_selectors = abi_selectors(compile_record["abi"])
    stage_bindings = bindings_for_stage(bindings, selector_key, candidate_selectors)
    stage["bindings"] = stage_bindings
    stage["interface"] = interface_report(reference_selectors, candidate_selectors)

    candidate_addr = stage_address(stage_index)
    rpc.call("anvil_setCode", [candidate_addr, compile_record["deployed_bytecode"]])
    rpc.call("anvil_setBalance", [candidate_addr, "0x0"])
    stage["address"] = candidate_addr
    stage["probe_results"] = run_probes(
        rpc, spec, stage_bindings, REF_ADDR, candidate_addr, rpc.call("eth_accounts")
    )
    write_json(result_dir / f"probe-results-{label}.json", stage["probe_results"])
    write_json(
        result_dir / f"selector-bindings-{label}.json",
        {"bindings": stage_bindings, "interface": stage["interface"]},
    )
    return summarize_stage(stage, spec)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument(
        "--candidate-label",
        default="llm1",
        help="Label used to select per-candidate bindings and identify the source",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--repair", action="store_true", help="send bounded repair requests")
    parser.add_argument("--repair-rounds", type=int, default=1)
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--llm-api-key", default="")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--llm-timeout", type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.repair_rounds <= 5:
        raise HarnessError("--repair-rounds must be between 1 and 5")
    if not args.candidate_label or not args.candidate_label.strip():
        raise HarnessError("--candidate-label must be nonempty")

    root = repo_root()
    spec = read_json(args.spec)
    fixture = spec["fixture"]
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_dir = root / "evaluation" / "results" / run_id / fixture
    if result_dir.exists() and any(result_dir.iterdir()):
        raise HarnessError(f"run directory already exists and is not empty: {result_dir}")
    result_dir.mkdir(parents=True, exist_ok=True)

    baseline_source = args.baseline.read_text(encoding="utf-8")
    candidate_source = args.candidate.read_text(encoding="utf-8")
    (result_dir / "baseline.sol").write_text(baseline_source, encoding="utf-8")
    (result_dir / "llm1.sol").write_text(candidate_source, encoding="utf-8")

    reference_abi = read_json(root / spec["reference_abi"])
    reference_runtime = (root / spec["reference_runtime"]).read_text(encoding="utf-8").strip()
    if not reference_runtime.startswith("0x"):
        reference_runtime = "0x" + reference_runtime
    reference_selectors = abi_selectors(reference_abi)
    bindings = load_bindings(spec, reference_abi, args.candidate_label)
    compare_events = bool(spec.get("compare_events", False))
    withheld = set(spec.get("withheld", []))
    feedback_names = [probe["name"] for probe in spec["probes"] if probe["name"] not in withheld]
    withheld_names = [probe["name"] for probe in spec["probes"] if probe["name"] in withheld]
    opaque_entries = {name: f"entrypoint_{index + 1}" for index, name in enumerate(bindings)}
    opaque_probes = {
        probe["name"]: f"probe_{index + 1}" for index, probe in enumerate(spec["probes"])
    }

    stages: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    repair_error: str | None = None
    selected_stage: dict[str, Any] | None = None
    selected_label = "none"
    selected_reason = "llm1 did not compile"
    anvil = Anvil()
    try:
        rpc = anvil.rpc
        rpc.call("anvil_setCode", [REF_ADDR, reference_runtime])
        rpc.call("anvil_setBalance", [REF_ADDR, "0x0"])
        baseline_stage = evaluate_stage(
            rpc, spec, bindings, reference_selectors, baseline_source, "baseline", "baseline", 0, result_dir
        )
        stages.append(baseline_stage)
        llm1_stage = evaluate_stage(
            rpc, spec, bindings, reference_selectors, candidate_source, "llm1", "candidate", 1, result_dir
        )
        stages.append(llm1_stage)
        selected_stage = llm1_stage
        selected_label = "llm1"
        selected_reason = "no repair requested" if not args.repair else "llm1 did not compile"

        if args.repair and llm1_stage["compile"]:
            if not args.llm_base_url or not args.model:
                repair_error = "--repair requires --llm-base-url and --model"
                selected_reason = "repair configuration missing"
            else:
                current_stage = llm1_stage
                current_source = candidate_source
                for round_index in range(1, args.repair_rounds + 1):
                    allowed = set(spec.get("repair_targets", [])) or set(feedback_names)
                    targets = [
                        name
                        for name in current_stage["feedback_failing"]
                        if name in allowed
                    ]
                    if not targets:
                        selected_reason = "no repair targets remain"
                        break
                    passing = [
                        name
                        for name in feedback_names
                        if current_stage["matches"].get(name)
                    ]
                    prompt_template = (
                        root / "evaluation" / "prompts" / "behavior_repair.txt"
                    ).read_text(encoding="utf-8")
                    prompt = build_repair_prompt(
                        prompt_template,
                        baseline_source,
                        current_source,
                        current_stage["bindings"],
                        current_stage["probe_results"],
                        passing,
                        targets,
                        opaque_entries,
                        opaque_probes,
                        compare_events,
                    )
                    label = f"repair-{round_index}"
                    (result_dir / f"{label}-prompt.txt").write_text(prompt, encoding="utf-8")
                    repaired_source, request_error = request_repair(
                        args.llm_base_url,
                        args.model,
                        args.llm_api_key,
                        args.llm_timeout,
                        args.max_tokens,
                        args.temperature,
                        args.seed,
                        prompt,
                        result_dir,
                        label,
                    )
                    if request_error:
                        repair_error = request_error
                        selected_reason = "repair request failed; retained current candidate"
                        break
                    assert repaired_source is not None
                    (result_dir / f"{label}.sol").write_text(repaired_source, encoding="utf-8")
                    repaired_stage = evaluate_stage(
                        rpc,
                        spec,
                        bindings,
                        reference_selectors,
                        repaired_source,
                        label,
                        "candidate",
                        1 + round_index,
                        result_dir,
                    )
                    stages.append(repaired_stage)
                    prior_matches = current_stage["matches"]
                    new_matches = repaired_stage.get("matches", {})
                    prior_bindings = {
                        name: bool(entry.get("available"))
                        for name, entry in current_stage["bindings"].items()
                    }
                    repaired_bindings = {
                        name: bool(entry.get("available"))
                        for name, entry in repaired_stage["bindings"].items()
                    }
                    regressions = [
                        name
                        for name in feedback_names
                        if prior_matches.get(name) and not new_matches.get(name)
                    ]
                    fixed = [
                        name
                        for name in feedback_names
                        if not prior_matches.get(name) and new_matches.get(name)
                    ]
                    target_fixed = all(new_matches.get(name) for name in targets)
                    # A repair that drops a previously bound entrypoint shrinks
                    # the candidate's callable surface; that is a regression even
                    # when every remaining probe matches.
                    lost_bindings = [
                        name
                        for name, bound in prior_bindings.items()
                        if bound and not repaired_bindings.get(name)
                    ]
                    accepted = (
                        repaired_stage["compile"]
                        and not regressions
                        and not lost_bindings
                        and bool(fixed)
                    )
                    attempts.append(
                        {
                            "round": round_index,
                            "label": label,
                            "compile": repaired_stage["compile"],
                            "accepted": accepted,
                            "targets": targets,
                            "target_fixed": target_fixed,
                            "fixed": fixed,
                            "regressions": regressions,
                            "lost_bindings": lost_bindings,
                            "feedback_failing": repaired_stage["feedback_failing"],
                            "withheld_failing": repaired_stage["withheld_failing"],
                            "unbound_calls": repaired_stage["unbound_calls"],
                        }
                    )
                    if not accepted:
                        selected_reason = (
                            "repair rejected: "
                            f"compile={repaired_stage['compile']}, "
                            f"fixed={fixed}, regressions={regressions}"
                        )
                        break
                    current_stage = repaired_stage
                    current_source = repaired_source
                    selected_stage = repaired_stage
                    selected_label = label
                    selected_reason = (
                        f"repair fixed {len(fixed)} feedback probe(s) without regression"
                    )
                    if not repaired_stage["feedback_failing"]:
                        break
    finally:
        anvil.stop()

    if selected_stage is None:
        selected_stage = stages[-1] if stages else {"label": "none", "compile": False}

    metrics: dict[str, Any] = {
        "schema_version": 2,
        "fixture": fixture,
        "run_id": run_id,
        "model": args.model if args.repair else None,
        "temperature": args.temperature if args.repair else None,
        "seed": args.seed if args.repair else None,
        "max_tokens": args.max_tokens if args.repair else None,
        "timeout_seconds": args.llm_timeout if args.repair else None,
        "solc_version": spec["solc_version"],
        "compare_events": compare_events,
        "send_payload_capture": "not_captured",
        "compared_fields": [
            "success_or_revert_status",
            "return_data_for_read_steps",
            "revert_data_for_read_steps",
            "contract_balance",
            "event_logs_only_when_compare_events_is_true",
        ],
        "baseline_sha256": sha256_text(baseline_source),
        "llm1_sha256": sha256_text(candidate_source),
        "candidate_label": args.candidate_label,
        "candidate_sha256": sha256_text(candidate_source),
        "baseline_compile": stages[0]["compile"] if stages else False,
        "candidate_compile": stages[1]["compile"] if len(stages) > 1 else False,
        "llm1_compile": stages[1]["compile"] if len(stages) > 1 else False,
        "feedback_probes": feedback_names,
        "withheld_probes": withheld_names,
        "bound_reference_selectors": sorted(
            binding["reference_selector"] for binding in bindings.values()
        ),
        "unbound_reference_selectors": sorted(
            reference_selectors
            - {binding["reference_selector"] for binding in bindings.values()}
        ),
        "planned_probes": len(spec["probes"]),
        "executed_probes": len(selected_stage.get("probe_results", {})),
        "blocked_probes": len(spec["probes"]) - len(selected_stage.get("probe_results", {})),
        "stages": [stage_metrics(stage) for stage in stages],
        "selected": selected_label,
        "selected_reason": selected_reason,
        "selected_feedback_matched": selected_stage.get("feedback_matched"),
        "selected_feedback_total": selected_stage.get("feedback_total"),
        "selected_withheld_matched": selected_stage.get("withheld_matched"),
        "selected_withheld_total": selected_stage.get("withheld_total"),
        "selected_feedback_failing": selected_stage.get("feedback_failing", []),
        "selected_withheld_failing": selected_stage.get("withheld_failing", []),
        "selected_unbound_calls": selected_stage.get("unbound_calls", []),
        "repair_attempts": attempts,
        "repair_error": repair_error,
    }
    write_json(result_dir / "metrics.json", metrics)

    for stage in stages:
        print(
            f"{stage['label']}: compile={stage['compile']} "
            f"feedback={stage.get('feedback_matched')}/{stage.get('feedback_total')} "
            f"withheld={stage.get('withheld_matched')}/{stage.get('withheld_total')}"
        )
    print(f"selected: {selected_label} ({selected_reason})")
    if repair_error:
        print(f"repair error: {repair_error}", file=sys.stderr)
    if not stages or not stages[1]["compile"]:
        return 2
    if repair_error and args.repair:
        return 1
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HarnessError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
