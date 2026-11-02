#!/usr/bin/env python3
"""Try reproducing a modern fixture with a locally installed, matching solc.

No network is used. Original published runtime.hex is never modified.
This tool can demonstrate compilation success and (when settings match) byte-for-byte
identity. Without original compiler settings an exact match is not guaranteed.
"""

import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def run(args):
    folder = ROOT / args.fixture
    if not folder.is_dir():
        raise ValueError(f"Unknown fixture: {args.fixture}")
    manifest = json.loads((folder / "manifest.json").read_text())
    source_files = list(folder.glob("*.sol"))
    if len(source_files) != 1:
        raise ValueError("Expected exactly one Solidity source file")
    source = source_files[0]
    if not args.fixture.startswith("modern-"):
        raise ValueError("Recompile helper currently targets modern-* fixtures only")

    command = shlex.split(args.solc)
    if not command:
        raise ValueError("Empty --solc command")
    version = subprocess.run(command + ["--version"], capture_output=True, text=True,
                             check=True, timeout=args.timeout)
    expected = manifest["compilation"]["compiler_version_from_bytecode_metadata"]
    observed = re.search(r"\b(\d+\.\d+\.\d+)\b", version.stdout + version.stderr)
    if not observed or observed.group(1) != expected:
        raise ValueError(
            f"{args.solc} reports {observed.group(1) if observed else 'unknown'}; "
            f"fixture requires solc {expected} inferred from runtime metadata. "
            "Install that exact version and rerun."
        )

    # Preserve the source key used in the upstream project where known, because
    # the key contributes to Solidity's metadata hash.
    key = manifest["source_provenance"]["source_path"]
    settings = {
        "outputSelection": {"*": {"*": ["abi", "evm.deployedBytecode.object"]}}
    }
    if args.optimize:
        settings["optimizer"] = {"enabled": True, "runs": args.runs}
    if args.via_ir:
        settings["viaIR"] = True
    if args.evm_version:
        settings["evmVersion"] = args.evm_version
    if args.metadata_hash:
        settings["metadata"] = {"bytecodeHash": args.metadata_hash}

    std_input = {
        "language": "Solidity",
        "sources": {key: {"content": source.read_text(encoding="utf-8")}},
        "settings": settings,
    }
    result = subprocess.run(command + ["--standard-json"], input=json.dumps(std_input),
                            capture_output=True, text=True, timeout=args.timeout)
    if result.returncode:
        raise RuntimeError(f"Compiler exited {result.returncode}: {result.stderr[-2000:]}")
    # solcjs can print a non-JSON diagnostic prefix to stdout.
    pos = result.stdout.find("{")
    if pos == -1:
        raise RuntimeError(f"Compiler did not return JSON: {result.stdout[-1000:]}")
    output = json.loads(result.stdout[pos:])
    errors = [e.get("formattedMessage", e.get("message", str(e))) for e in
              output.get("errors", []) if e.get("severity") == "error"]
    if errors:
        raise RuntimeError("Compilation errors:\n" + "\n".join(errors))

    contract = output.get("contracts", {}).get(key, {}).get(manifest["contract"])
    if not contract:
        raise RuntimeError("Target contract missing from Solidity compiler output")
    compiled = contract["evm"]["deployedBytecode"]["object"].removeprefix("0x")
    if not compiled or re.fullmatch(r"[0-9a-fA-F]+", compiled) is None:
        raise RuntimeError("Missing, linked, or invalid runtime bytecode")

    saved = (folder / "runtime.hex").read_text().strip().removeprefix("0x")
    identical = compiled.lower() == saved.lower()
    result_data = {
        "fixture": args.fixture, "contract": manifest["contract"],
        "compiler": observed.group(1), "compiles": True,
        "byte_identical": identical,
        "compiled_runtime_bytes": len(compiled) // 2,
        "published_runtime_bytes": len(saved) // 2,
        "compiled_sha256": hashlib.sha256(bytes.fromhex(compiled)).hexdigest(),
        "published_sha256": hashlib.sha256(bytes.fromhex(saved)).hexdigest(),
        "settings_attempted": settings,
        "caveat": None if identical else (
            "Compilation succeeded, but output differs from the published fixture. "
            "Investigate upstream optimization, viaIR, source keys and metadata flags; "
            "do not overwrite the benchmark runtime without documenting provenance."
        ),
    }
    print(json.dumps(result_data, indent=2))
    return 0 if identical or not args.require_byte_match else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", help="E.g. modern-errors")
    parser.add_argument("--solc", default="solc", help="Exact compiler command (e.g. solc or solcjs)")
    parser.add_argument("--optimize", action="store_true")
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--via-ir", action="store_true")
    parser.add_argument("--evm-version", default=None)
    parser.add_argument("--metadata-hash", choices=["ipfs", "bzzr1", "none"])
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--require-byte-match", action="store_true")
    args = parser.parse_args()
    try:
        return run(args)
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
