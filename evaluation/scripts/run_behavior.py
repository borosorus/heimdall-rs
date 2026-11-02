#!/usr/bin/env python3
"""Run a bounded behavioral repair experiment for a decompiled contract.

The harness is intentionally evaluation-only. It compiles a candidate, executes deterministic
raw-calldata probes against the original runtime bytecode and the candidate on a local Anvil node,
then optionally asks a model for one repair based on the failing observation.

Reference Solidity is never read by this script or sent to the model. Reference ABI is used only to
verify selector bindings and to report interface compatibility.
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
    source: str, solc_version: str, work_dir: Path, label: str
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

    if len(artifacts) != 1:
        compile_record["ok"] = False
        compile_record["error"] = (
            f"expected exactly one compiled contract artifact, found {len(artifacts)}"
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
    bindings: dict[str, dict[str, str]],
    side: str,
    accounts: list[str],
) -> list[dict[str, Any]]:
    results = []
    for step in steps:
        call_name = step["call"]
        binding = bindings[call_name]
        selector = binding[f"{side}_selector"]
        calldata = encode_step(selector, step)
        sender = accounts[int(step.get("caller", 0))]
        value = int(step.get("value", "0"), 0)
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
        observation["mode"] = "send" if step.get("send", False) else "read"
        results.append(observation)
    return results


def semantic_view(observation: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": observation.get("ok"),
        "return_data": (observation.get("return_data") or "").lower() or None,
        "revert_data": (observation.get("revert_data") or "").lower() or None,
        "contract_balance": observation.get("contract_balance"),
    }


def sequence_matches(reference: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> bool:
    return all(
        semantic_view(left) == semantic_view(right)
        for left, right in zip(reference, candidate)
    )


def prompt_view(observation: dict[str, Any], include_logs: bool) -> dict[str, Any]:
    return {
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


def configured_match(result: dict[str, Any], compare_events: bool) -> bool:
    return result["semantic_match"] and (not compare_events or result["event_match"])


def event_matches(reference: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> bool:
    return all(
        left.get("logs", []) == right.get("logs", [])
        for left, right in zip(reference, candidate)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--repair", action="store_true", help="send one repair request")
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--llm-api-key", default="")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--llm-timeout", type=int, default=600)
    args = parser.parse_args()

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

    reference_selector_set = abi_selectors(reference_abi)
    bindings = json.loads(json.dumps(spec["bindings"]))
    for name, binding in bindings.items():
        reference_selector = cast_selector(binding["reference_signature"])
        candidate_selector = cast_selector(binding["candidate_signature"])
        if reference_selector not in reference_selector_set:
            raise HarnessError(
                f"reference signature not in reference ABI: {binding['reference_signature']}"
            )
        binding["reference_selector"] = reference_selector
        binding["candidate_selector"] = candidate_selector

    work_root = result_dir / "work"
    compile1 = compile_candidate(candidate_source, spec["solc_version"], work_root / "llm1", "llm1")
    write_json(result_dir / "compile-llm1.json", compile1)
    if not compile1.get("ok"):
        write_json(
            result_dir / "metrics.json",
            {
                "schema_version": 1,
                "fixture": fixture,
                "run_id": run_id,
                "llm1_compile": False,
                "selected": "none",
                "selected_reason": "llm1 did not compile",
            },
        )
        print("llm1 did not compile; no behavioral probes were executed", file=sys.stderr)
        return 2

    candidate_selector_set = abi_selectors(compile1["abi"])
    for name, binding in bindings.items():
        if binding["candidate_selector"] not in candidate_selector_set:
            raise HarnessError(
                f"candidate signature {binding['candidate_signature']!r} is not in the compiled ABI"
            )

    compiled_interface = {
        "reference_selector_count": len(reference_selector_set),
        "candidate_selector_count": len(candidate_selector_set),
        "matched": len(reference_selector_set & candidate_selector_set),
        "missing": sorted(reference_selector_set - candidate_selector_set),
        "candidate_only": sorted(candidate_selector_set - reference_selector_set),
    }
    write_json(
        result_dir / "selector-bindings.json",
        {"bindings": bindings, "interface": compiled_interface},
    )

    anvil = Anvil()
    try:
        rpc = anvil.rpc
        accounts = rpc.call("eth_accounts")
        rpc.call("anvil_setCode", [REF_ADDR, reference_runtime])
        rpc.call("anvil_setCode", [CAND_ADDR, compile1["deployed_bytecode"]])
        rpc.call("anvil_setBalance", [REF_ADDR, "0x0"])
        rpc.call("anvil_setBalance", [CAND_ADDR, "0x0"])

        probe_results: dict[str, Any] = {}
        base_snapshot = rpc.call("evm_snapshot")
        for probe in spec["probes"]:
            name = probe["name"]
            rpc.call("evm_revert", [base_snapshot])
            base_snapshot = rpc.call("evm_snapshot")
            reference = run_sequence(rpc, REF_ADDR, probe["steps"], bindings, "reference", accounts)

            rpc.call("evm_revert", [base_snapshot])
            base_snapshot = rpc.call("evm_snapshot")
            candidate = run_sequence(
                rpc, CAND_ADDR, probe["steps"], bindings, "candidate", accounts
            )

            probe_results[name] = {
                "reference": reference,
                "candidate": candidate,
                "semantic_match": sequence_matches(reference, candidate),
                "event_match": event_matches(reference, candidate),
            }
        rpc.call("evm_revert", [base_snapshot])
    finally:
        anvil.stop()

    write_json(result_dir / "probe-results.json", probe_results)
    compare_events = bool(spec.get("compare_events", False))
    semantic_failing = [
        name for name, result in probe_results.items() if not result["semantic_match"]
    ]
    event_mismatches = [
        name for name, result in probe_results.items() if not result["event_match"]
    ]
    failing = [
        name
        for name, result in probe_results.items()
        if not configured_match(result, compare_events)
    ]
    print(f"semantic failures: {semantic_failing}")
    print(f"event mismatches: {event_mismatches}")

    metrics: dict[str, Any] = {
        "schema_version": 1,
        "fixture": fixture,
        "run_id": run_id,
        "model": args.model if args.repair else None,
        "temperature": args.temperature if args.repair else None,
        "seed": args.seed if args.repair else None,
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
        "llm1_compile": compile1.get("ok"),
        "interface": compiled_interface,
        "semantic_failing_probes": semantic_failing,
        "event_mismatches": event_mismatches,
        "failing_probes": failing,
        "selected": "llm1",
        "selected_reason": "no repair requested" if not args.repair else None,
    }
    write_json(result_dir / "metrics.json", metrics)

    if args.repair:
        if not args.llm_base_url or not args.model:
            metrics["selected_reason"] = "repair configuration missing"
            metrics["repair_error"] = "--repair requires --llm-base-url and --model"
            write_json(result_dir / "metrics.json", metrics)
            return 1
        targets = [name for name in spec.get("repair_targets", []) if name in failing]
        if not targets:
            metrics["selected_reason"] = "no configured repair target failed"
            write_json(result_dir / "metrics.json", metrics)
            return 0

        target = targets[0]
        passing = [
            name
            for name, result in probe_results.items()
            if configured_match(result, compare_events)
        ]
        opaque_entries = {
            name: f"entrypoint_{index + 1}" for index, name in enumerate(bindings)
        }
        opaque_probes = {
            name: f"probe_{index + 1}" for index, name in enumerate(probe_results)
        }
        prompt_template = (root / "evaluation" / "prompts" / "behavior_repair.txt").read_text(
            encoding="utf-8"
        )
        prompt = (
            prompt_template.replace("<<BASELINE_SOURCE>>", baseline_source)
            .replace("<<CANDIDATE_SOURCE>>", candidate_source)
            .replace(
                "<<BINDINGS>>",
                json.dumps(
                    [
                        {
                            "entrypoint": opaque_entries[name],
                            "reference_selector": binding["reference_selector"],
                            "candidate_selector": binding["candidate_selector"],
                            "candidate_signature": binding["candidate_signature"],
                        }
                        for name, binding in bindings.items()
                    ],
                    indent=2,
                ),
            )
            .replace(
                "<<PASSING_OBSERVATIONS>>",
                json.dumps(
                    {
                        opaque_probes[name]: [
                            {**prompt_view(observation, compare_events), "step": index}
                            for index, observation in enumerate(probe_results[name]["candidate"])
                        ]
                        for name in passing
                    },
                    indent=2,
                ),
            )
            .replace(
                "<<FAILING_OBSERVATION>>",
                json.dumps(
                    {
                        "probe": opaque_probes[target],
                        "reference": [
                            {**prompt_view(observation, compare_events), "step": index}
                            for index, observation in enumerate(probe_results[target]["reference"])
                        ],
                        "candidate": [
                            {**prompt_view(observation, compare_events), "step": index}
                            for index, observation in enumerate(probe_results[target]["candidate"])
                        ],
                    },
                    indent=2,
                ),
            )
        )
        (result_dir / "repair-prompt.txt").write_text(prompt, encoding="utf-8")

        body: dict[str, Any] = {
            "model": args.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": args.temperature,
            "seed": args.seed,
            "max_tokens": args.max_tokens,
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
        (result_dir / "repair-request.json").write_text(
            json.dumps(body, indent=2) + "\n", encoding="utf-8"
        )
        headers = {"Content-Type": "application/json"}
        if args.llm_api_key:
            headers["Authorization"] = f"Bearer {args.llm_api_key}"
        request = urllib.request.Request(
            args.llm_base_url.rstrip("/") + "/chat/completions",
            data=request_body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=args.llm_timeout) as response:
                response_body = response.read().decode("utf-8")
            (result_dir / "repair-response.json").write_text(
                response_body + "\n", encoding="utf-8"
            )
            parsed = json.loads(response_body)
            content = parsed["choices"][0]["message"].get("content")
            if not content:
                raise HarnessError("repair response had no content")
            repaired_response = json.loads(content)
            repaired_source = repaired_response["source"]
            if not isinstance(repaired_source, str) or not repaired_source.strip():
                raise HarnessError("repair response source must be a nonempty string")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            metrics["repair_error"] = f"LLM HTTP error {exc.code}: {detail}"
            metrics["selected_reason"] = "repair request failed; retained llm1"
            write_json(result_dir / "metrics.json", metrics)
            return 1
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
            metrics["repair_error"] = str(error)
            metrics["selected_reason"] = "repair request failed; retained llm1"
            write_json(result_dir / "metrics.json", metrics)
            return 1
        (result_dir / "llm2.sol").write_text(repaired_source, encoding="utf-8")

        compile2 = compile_candidate(
            repaired_source, spec["solc_version"], work_root / "llm2", "llm2"
        )
        write_json(result_dir / "compile-llm2.json", compile2)
        metrics["llm2_sha256"] = sha256_text(repaired_source)
        metrics["llm2_compile"] = compile2.get("ok")
        if not compile2.get("ok"):
            metrics["selected_reason"] = "repair candidate did not compile"
            write_json(result_dir / "metrics.json", metrics)
            return 0

        candidate_selector_set2 = abi_selectors(compile2["abi"])
        interface2 = {
            "reference_selector_count": len(reference_selector_set),
            "candidate_selector_count": len(candidate_selector_set2),
            "matched": len(reference_selector_set & candidate_selector_set2),
            "missing": sorted(reference_selector_set - candidate_selector_set2),
            "candidate_only": sorted(candidate_selector_set2 - reference_selector_set),
        }
        metrics["llm2_interface"] = interface2
        for name, binding in bindings.items():
            if binding["candidate_selector"] not in candidate_selector_set2:
                metrics["selected_reason"] = (
                    f"repair changed or removed entrypoint {name} "
                    f"({binding['candidate_signature']})"
                )
                write_json(result_dir / "metrics.json", metrics)
                return 0

        anvil = Anvil()
        try:
            rpc = anvil.rpc
            accounts = rpc.call("eth_accounts")
            rpc.call("anvil_setCode", [REF_ADDR, reference_runtime])
            rpc.call("anvil_setCode", [CAND_ADDR, compile2["deployed_bytecode"]])
            rpc.call("anvil_setBalance", [REF_ADDR, "0x0"])
            rpc.call("anvil_setBalance", [CAND_ADDR, "0x0"])

            repaired_results: dict[str, Any] = {}
            base_snapshot = rpc.call("evm_snapshot")
            for probe in spec["probes"]:
                name = probe["name"]
                rpc.call("evm_revert", [base_snapshot])
                base_snapshot = rpc.call("evm_snapshot")
                reference = run_sequence(
                    rpc, REF_ADDR, probe["steps"], bindings, "reference", accounts
                )
                rpc.call("evm_revert", [base_snapshot])
                base_snapshot = rpc.call("evm_snapshot")
                candidate = run_sequence(
                    rpc, CAND_ADDR, probe["steps"], bindings, "candidate", accounts
                )
                repaired_results[name] = {
                    "reference": reference,
                    "candidate": candidate,
                    "semantic_match": sequence_matches(reference, candidate),
                    "event_match": event_matches(reference, candidate),
                }
            rpc.call("evm_revert", [base_snapshot])
        finally:
            anvil.stop()

        write_json(result_dir / "probe-results-llm2.json", repaired_results)
        llm1_semantic = {
            name: result["semantic_match"] for name, result in probe_results.items()
        }
        llm2_semantic = {
            name: result["semantic_match"] for name, result in repaired_results.items()
        }
        semantic_regressions = [
            name
            for name in llm1_semantic
            if llm1_semantic[name] and not llm2_semantic[name]
        ]
        llm1_events = {
            name: result["event_match"] for name, result in probe_results.items()
        }
        llm2_events = {
            name: result["event_match"] for name, result in repaired_results.items()
        }
        event_regressions = [
            name
            for name in llm1_events
            if compare_events and llm1_events[name] and not llm2_events[name]
        ]
        regressions = list(dict.fromkeys(semantic_regressions + event_regressions))
        target_fixed = configured_match(repaired_results[target], compare_events)
        metrics["repair_target"] = target
        metrics["target_fixed"] = target_fixed
        metrics["semantic_regressions"] = semantic_regressions
        metrics["event_regressions"] = event_regressions
        metrics["regressions"] = regressions
        metrics["llm2_semantic_failing_probes"] = [
            name for name, result in repaired_results.items() if not result["semantic_match"]
        ]
        metrics["llm2_failing_probes"] = [
            name
            for name, result in repaired_results.items()
            if not configured_match(result, compare_events)
        ]
        metrics["llm2_event_mismatches"] = [
            name for name, result in repaired_results.items() if not result["event_match"]
        ]
        metrics["selected"] = (
            "llm2"
            if target_fixed and not semantic_regressions and not event_regressions
            else "llm1"
        )
        metrics["selected_reason"] = (
            "repair fixed target without semantic or configured event regressions"
            if target_fixed and not semantic_regressions and not event_regressions
            else "repair did not fix target without semantic or configured event regressions"
        )

    write_json(result_dir / "metrics.json", metrics)
    print(f"results: {result_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HarnessError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
