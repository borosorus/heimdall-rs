#!/usr/bin/env python3
"""Verify committed EVM decompilation fixture integrity without network access.

This checks the stored publisher artifact / runtime / manifest / ABI consistency.
It does not prove source-to-bytecode recompilation or behavioral equivalence.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
HEX = re.compile(r"(?:0x)?[0-9a-fA-F]+\Z")


def error(name: str, message: str) -> None:
    raise ValueError(f"{name}: {message}")


def verify_one(directory: Path) -> tuple[str, int, str]:
    name = directory.name
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["fixture_id"] != name:
        error(name, "manifest fixture_id mismatches directory")
    data = (directory / manifest["runtime"]["filename"]).read_text(encoding="ascii").strip()
    if not HEX.fullmatch(data):
        error(name, "runtime bytecode is not hexadecimal")
    code = data.removeprefix("0x")
    if not code or len(code) % 2:
        error(name, "runtime bytecode is empty or has odd-length hex")
    raw = bytes.fromhex(code)
    digest = hashlib.sha256(raw).hexdigest()
    if len(raw) != manifest["runtime"]["byte_length"]:
        error(name, "byte count differs from manifest")
    if digest != manifest["runtime"]["sha256"]:
        error(name, "SHA-256 differs from manifest")
    abi = json.loads((directory / manifest["abi"]["filename"]).read_text(encoding="utf-8"))
    if not isinstance(abi, list):
        error(name, "ABI must be a JSON array")
    fn_count = sum(item.get("type") == "function" for item in abi)
    if fn_count != manifest["abi"]["function_count"]:
        error(name, "ABI function count differs from manifest")
    source_paths = list(directory.glob("*.sol"))
    if len(source_paths) != 1 or not source_paths[0].read_text(encoding="utf-8").strip():
        error(name, "expected exactly one nonempty Solidity source")
    pragma = re.search(r"pragma\s+solidity\s+([^;]+);", source_paths[0].read_text(encoding="utf-8"))
    if not pragma or pragma.group(1).strip() != manifest["compilation"]["pragma"]:
        error(name, "source pragma mismatches manifest")

    artifact = directory / "upstream-artifact.json"
    if artifact.exists():
        published = json.loads(artifact.read_text(encoding="utf-8"))
        published_hex = published["runtimeBytecode"].removeprefix("0x")
        if published_hex.lower() != code.lower():
            error(name, "runtime.hex differs from upstream published runtimeBytecode")
        published_abi = published["abi"]
        if isinstance(published_abi, str):
            published_abi = json.loads(published_abi)
        if published_abi != abi:
            error(name, "abi.json differs from upstream published ABI")
    elif name == "sender-creator":
        if "570e1a36" not in code.lower():
            error(name, "expected createSender(bytes) selector missing from runtime")
        if not (directory / "LICENSE").exists():
            error(name, "GPL-3.0 license text must accompany source")
    else:
        error(name, "no publisher artifact available for integrity verification")
    return name, len(raw), digest


def main() -> int:
    roots = sorted(p for p in FIXTURES.iterdir() if p.is_dir())
    if not roots:
        print("No fixtures found", file=sys.stderr)
        return 1
    try:
        for root in roots:
            name, length, digest = verify_one(root)
            print(f"PASS {name:16s} runtime={length:5d} bytes sha256={digest}")
    except (KeyError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print(f"Verified integrity of {len(roots)} published source/runtime fixture bundles.")
    print("NOTE: This does not independently recompile sources or establish behavioral equivalence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
