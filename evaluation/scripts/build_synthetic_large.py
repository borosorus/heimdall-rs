#!/usr/bin/env python3
"""Build or verify the synthetic-large fixture with a pinned Solidity compiler.

The fixture is intentionally local and synthetic. `build.json` records the exact source,
compiler selection and settings so the runtime/ABI can be checked without pretending this is an
upstream-published artifact. `--verify` recompiles and requires byte-identical runtime output.

No network access is required by --verify when the compiler is already cached by Foundry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "synthetic-large"
SOURCE_NAME = "SyntheticVault.sol"
CONTRACT = "SyntheticVault"
SOLC_VERSION = "0.8.30"
SOURCE_KEY = f"src/{SOURCE_NAME}"
HEX = re.compile(r"(?:0x)?[0-9a-fA-F]+\Z")


class BuildError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def compiler_version(output: str) -> str:
    match = re.search(r"\b(\d+\.\d+\.\d+)\b", output)
    if not match:
        raise BuildError("could not determine compiler version")
    return match.group(1)


def normalize_runtime(value: str) -> str:
    code = value.removeprefix("0x")
    if not code or not HEX.fullmatch(code) or len(code) % 2:
        raise BuildError("compiler returned empty, linked, or malformed runtime bytecode")
    return code.lower()


def compile_with_solc(source: str, command: str) -> dict[str, Any]:
    argv = shlex.split(command)
    if not argv:
        raise BuildError("empty --solc command")
    version_output = subprocess.run(
        argv + ["--version"], capture_output=True, text=True, timeout=60
    )
    if version_output.returncode != 0:
        raise BuildError(
            f"compiler version command failed: {version_output.stderr[-1000:]}"
        )
    version = compiler_version(version_output.stdout + version_output.stderr)
    if version != SOLC_VERSION:
        raise BuildError(f"compiler reports {version}; fixture requires {SOLC_VERSION}")

    std_input = {
        "language": "Solidity",
        "sources": {SOURCE_KEY: {"content": source}},
        "settings": {
            "optimizer": {"enabled": False, "runs": 200},
            "viaIR": False,
            "outputSelection": {
                "*": {
                    "*": ["abi", "evm.deployedBytecode.object", "metadata"]
                }
            },
        },
    }
    result = subprocess.run(
        argv + ["--standard-json"],
        input=json.dumps(std_input),
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        raise BuildError(f"compiler exited {result.returncode}: {result.stderr[-2000:]}")
    pos = result.stdout.find("{")
    if pos == -1:
        raise BuildError(f"compiler did not return JSON: {result.stdout[-1000:]}")
    output = json.loads(result.stdout[pos:])
    errors = [
        e.get("formattedMessage", e.get("message", str(e)))
        for e in output.get("errors", [])
        if e.get("severity") == "error"
    ]
    if errors:
        raise BuildError("compilation errors:\n" + "\n".join(errors))
    contract = output.get("contracts", {}).get(SOURCE_KEY, {}).get(CONTRACT)
    if not contract:
        raise BuildError("target contract missing from compiler output")
    metadata = contract.get("metadata")
    long_version = version
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
            long_version = parsed_metadata.get("compiler", {}).get("version", version)
        except json.JSONDecodeError:
            pass
    return {
        "compiler": {
            "kind": "solc",
            "command": command,
            "version": version,
            "long_version": long_version,
        },
        "runtime": normalize_runtime(contract["evm"]["deployedBytecode"]["object"]),
        "abi": contract["abi"],
    }


def compile_with_forge(source: str, forge_command: str, offline: bool) -> dict[str, Any]:
    argv = shlex.split(forge_command)
    if not argv:
        raise BuildError("empty --forge command")
    version_output = subprocess.run(
        argv + ["--version"], capture_output=True, text=True, timeout=60
    )
    if version_output.returncode != 0:
        raise BuildError(f"forge version command failed: {version_output.stderr[-1000:]}")
    with tempfile.TemporaryDirectory(prefix="heimdall-synthetic-") as temporary:
        work = Path(temporary)
        (work / "src").mkdir()
        (work / "src" / SOURCE_NAME).write_text(source, encoding="utf-8")
        (work / "foundry.toml").write_text(
            "\n".join(
                [
                    "[profile.default]",
                    'src = "src"',
                    'out = "out"',
                    "libs = []",
                    f'solc_version = "{SOLC_VERSION}"',
                    "optimizer = false",
                    "via_ir = false",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        command = argv + [
            "build",
            "--force",
            "--no-cache",
            "--no-lint",
            "--use",
            SOLC_VERSION,
            "--optimize",
            "false",
        ]
        if offline:
            command.append("--offline")
        result = subprocess.run(
            command, cwd=work, capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            raise BuildError(
                f"forge build failed ({result.returncode}):\n{result.stderr[-3000:]}"
            )
        artifacts = [
            path
            for path in (work / "out").rglob("*.json")
            if "build-info" not in path.parts
        ]
        target = None
        for path in artifacts:
            try:
                artifact = read_json(path)
            except json.JSONDecodeError:
                continue
            if artifact.get("contractName") == CONTRACT or path.name == f"{CONTRACT}.json":
                target = artifact
                break
        if target is None:
            raise BuildError("forge did not produce the target contract artifact")
        deployed = target.get("deployedBytecode")
        if isinstance(deployed, dict):
            deployed = deployed.get("object")
        if not isinstance(deployed, str):
            raise BuildError("forge artifact has no deployed bytecode")
        metadata_text = target.get("metadata")
        if metadata_text is None and isinstance(target.get("raw"), dict):
            metadata_text = target["raw"].get("metadata")
        version = SOLC_VERSION
        long_version = SOLC_VERSION
        if isinstance(metadata_text, str):
            try:
                metadata = json.loads(metadata_text)
                compiler = metadata.get("compiler", {})
                version = compiler.get("version", version)
                long_version = compiler.get("version", long_version)
            except json.JSONDecodeError:
                pass
        if version != SOLC_VERSION:
            raise BuildError(
                f"forge artifact reports solc {version}; fixture requires {SOLC_VERSION}"
            )
        abi = target.get("abi")
        if not isinstance(abi, list):
            raise BuildError("forge artifact has no ABI array")
        return {
            "compiler": {
                "kind": "forge",
                "command": forge_command,
                "version": version,
                "long_version": long_version,
                "forge_version": (version_output.stdout or version_output.stderr).strip(),
            },
            "runtime": normalize_runtime(deployed),
            "abi": abi,
        }


def compile_fixture(source: str, args: argparse.Namespace) -> dict[str, Any]:
    if args.compiler == "solc" or (args.compiler == "auto" and shutil.which("solc")):
        return compile_with_solc(source, args.solc)
    return compile_with_forge(source, args.forge, args.offline)


def build_record(source: str, result: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    runtime_bytes = bytes.fromhex(result["runtime"])
    abi_bytes = (json.dumps(result["abi"], indent=2, sort_keys=True) + "\n").encode("utf-8")
    return {
        "schema_version": 1,
        "kind": "synthetic-local",
        "fixture_id": "synthetic-large",
        "contract": CONTRACT,
        "source_path": f"evaluation/fixtures/synthetic-large/{SOURCE_NAME}",
        "source_sha256": sha256_text(source),
        "source_key": SOURCE_KEY,
        "compiler": result["compiler"],
        "settings": {
            "optimizer": {"enabled": False, "runs": 200},
            "viaIR": False,
            "evm_version": "default",
            "metadata": {"bytecode_hash": "ipfs"},
        },
        "runtime": {
            "byte_length": len(runtime_bytes),
            "sha256": sha256_bytes(runtime_bytes),
        },
        "abi": {
            "function_count": sum(item.get("type") == "function" for item in result["abi"]),
            "sha256": sha256_bytes(abi_bytes),
        },
        "build_command": {
            "compiler": args.compiler,
            "solc": args.solc,
            "forge": args.forge,
            "offline": args.offline,
        },
    }


def manifest_record(build: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fixture_id": "synthetic-large",
        "contract": CONTRACT,
        "summary": "Synthetic large vault with interacting ledger, configuration and aggregate clusters",
        "source_provenance": {
            "kind": "synthetic-local",
            "generator": "evaluation/scripts/build_synthetic_large.py",
            "license": "MIT",
        },
        "compilation": {
            "pragma": SOLC_VERSION,
            "compiler_version_from_bytecode_metadata": SOLC_VERSION,
            "exact_solc_version": SOLC_VERSION,
            "optimizer": False,
            "via_ir": False,
            "reproducible_compilation_verified": True,
        },
        "runtime": {
            "kind": "deployed_runtime_bytecode",
            "filename": "runtime.hex",
            "byte_length": build["runtime"]["byte_length"],
            "sha256": build["runtime"]["sha256"],
        },
        "abi": {
            "filename": "abi.json",
            "function_count": build["abi"]["function_count"],
        },
        "provenance_status": "synthetic-local",
        "evaluation_warning": (
            "Synthetic fixture generated and recompiled locally. It exercises the evaluation "
            "pipeline; it is not evidence of real-world generalization."
        ),
    }


def write_fixture(source: str, result: dict[str, Any], args: argparse.Namespace) -> None:
    build = build_record(source, result, args)
    (FIXTURE / "runtime.hex").write_text(result["runtime"] + "\n", encoding="ascii")
    (FIXTURE / "abi.json").write_text(
        json.dumps(result["abi"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (FIXTURE / "build.json").write_text(
        json.dumps(build, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (FIXTURE / "manifest.json").write_text(
        json.dumps(manifest_record(build), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "fixture": "synthetic-large",
                "runtime_bytes": build["runtime"]["byte_length"],
                "runtime_sha256": build["runtime"]["sha256"],
                "abi_function_count": build["abi"]["function_count"],
                "compiler": build["compiler"]["version"],
            },
            indent=2,
        )
    )


def verify_fixture(source: str, args: argparse.Namespace) -> int:
    build_path = FIXTURE / "build.json"
    manifest_path = FIXTURE / "manifest.json"
    runtime_path = FIXTURE / "runtime.hex"
    abi_path = FIXTURE / "abi.json"
    for path in (build_path, manifest_path, runtime_path, abi_path):
        if not path.exists():
            raise BuildError(f"missing fixture file: {path}")
    saved_build = read_json(build_path)
    saved_manifest = read_json(manifest_path)
    saved_runtime = runtime_path.read_text(encoding="ascii").strip().removeprefix("0x").lower()
    saved_abi = read_json(abi_path)
    saved_source_hash = sha256_text(source)
    if saved_build.get("source_sha256") != saved_source_hash:
        raise BuildError("saved source hash does not match build.json")
    if saved_build.get("runtime", {}).get("sha256") != sha256_bytes(
        bytes.fromhex(saved_runtime)
    ):
        raise BuildError("saved runtime hash does not match build.json")
    if saved_build.get("abi", {}).get("function_count") != sum(
        item.get("type") == "function" for item in saved_abi
    ):
        raise BuildError("saved ABI function count does not match build.json")
    if saved_manifest.get("runtime", {}).get("sha256") != saved_build["runtime"]["sha256"]:
        raise BuildError("manifest and build runtime hashes differ")

    result = compile_fixture(source, args)
    compiled = result["runtime"]
    compiled_abi = result["abi"]
    identical = compiled == saved_runtime and compiled_abi == saved_abi
    report = {
        "fixture": "synthetic-large",
        "compiler": result["compiler"],
        "byte_identical": identical,
        "compiled_runtime_bytes": len(compiled) // 2,
        "saved_runtime_bytes": len(saved_runtime) // 2,
        "compiled_sha256": sha256_bytes(bytes.fromhex(compiled)),
        "saved_sha256": sha256_bytes(bytes.fromhex(saved_runtime)),
        "compiled_abi_function_count": sum(
            item.get("type") == "function" for item in compiled_abi
        ),
        "saved_abi_function_count": sum(
            item.get("type") == "function" for item in saved_abi
        ),
    }
    print(json.dumps(report, indent=2))
    if not identical:
        raise BuildError(
            "recompiled runtime or ABI differs from the committed fixture; do not overwrite it"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compiler",
        choices=["auto", "solc", "forge"],
        default="auto",
        help="Compiler backend. auto prefers solc on PATH, then forge.",
    )
    parser.add_argument("--solc", default="solc", help="solc command, e.g. solc or solcjs")
    parser.add_argument("--forge", default="forge", help="forge command")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not let Foundry fetch a missing compiler; useful for --verify",
    )
    parser.add_argument("--build", action="store_true", help="Write fixture files")
    parser.add_argument("--verify", action="store_true", help="Recompile and verify bytes")
    args = parser.parse_args()
    if args.build == args.verify:
        parser.error("choose exactly one of --build or --verify")
    source_path = FIXTURE / SOURCE_NAME
    if not source_path.exists():
        raise BuildError(f"missing source: {source_path}")
    source = source_path.read_text(encoding="utf-8")
    if args.build:
        result = compile_fixture(source, args)
        write_fixture(source, result, args)
        return 0
    return verify_fixture(source, args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BuildError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
