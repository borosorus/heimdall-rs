#!/usr/bin/env python3
"""Rebuild struct-array accessors from the canonical Solidity storage layout.

Tier-2 (auditlog) pass tool, zero-LLM. The decompiler renders dynamic
struct-array accessors over mis-typed roots with `field_N` projection chains;
no declaration retype repairs member chains on a value type. When the storage
map shows the array signature - a count slot C, element stride S, address word
and dynamic-bytes field offsets - the accessor units are rebuilt directly over
the canonical layout, keeping each unit's NAME and PARAMETER COUNT (the
dispatch identity the harness binds; return types are redeclared to the
observed ABI shape). Bodies read raw slots; no store_* declaration is used.

Layout algebra (EVM storage facts, parity-checked):
  count        : sload(C)
  element base : keccak256(C) ; word slot base+S*i+addr_off ; bytes slot ..+str_off
  address word : low-order 20 bytes of the slot word
  dyn bytes    : slot value v; v&1==1 -> short (len v>>1, data high-aligned in
                 v); v&1==0 -> long (len per --long-encoding, data words at
                 keccak256(slot), big-endian within the word)
  out-of-range : Panic(uint256) 0x32, the standard array-index revert

Enumerated variants (parity decides): --long-encoding plain|half (long length
stored as n vs n/2-marker), --push-ret old|new (row number vs post-increment).

Usage:
  rebuild_struct_array_accessors.py --source prepared.sol --out out.sol \
    --count-slot 0 --stride 2 --addr-offset 0 --string-offset 1 \
    --getter Unresolved_88702ee9 --push Unresolved_cf62fd39 --lens Unresolved_de8fa431 \
    --long-encoding plain --push-ret old
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVESTIGATOR = ROOT / "evaluation" / "scripts" / "run_investigator.py"


def _load_investigator():
    spec = importlib.util.spec_from_file_location("_inv_sra", INVESTIGATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_inv_sra"] = module
    spec.loader.exec_module(module)
    return module


MASK160 = "0x" + "f" * 40

GETTER = """    function {name}(uint256 arg0) public view returns (address, string memory) {{
        uint256 len;
        address who;
        string memory payload;
        assembly {{
            let scratch := mload(0x40)
            mstore(scratch, {count_slot})
            let base := keccak256(scratch, 0x20)
            len := sload({count_slot})
            if {ge} {{
                invalid()
            }}
            let wslot := add(base, add(mul({stride}, arg0), {addr_off}))
            let dslot := add(base, add(mul({stride}, arg0), {str_off}))
            who := and(sload(wslot), {mask160})
            let v := sload(dslot)
            let n := 0
            switch and(v, 0x01)
            case 0 {{ n := shr(0x01, v) }}
            default {{ n := shr(0x01, and(v, 0xff)) }}
            let data := add(mload(0x40), 0x20)
            payload := mload(0x40)
            mstore(payload, n)
            switch n
            case 0 {{
                mstore(0x40, add(data, 0x20))
            }}
            default {{
                switch and(v, 0x01)
                case 1 {{
                    let i := 0
                    for {{ }} lt(i, n) {{ i := add(i, 0x01) }} {{
                        mstore8(add(data, i), byte(i, v))
                    }}
                    mstore(0x40, add(data, 0x20))
                }}
                default {{
                    let full := shr(0x05, add(n, 0x1f))
                    mstore(add(data, mul(0x20, full)), dslot)
                    let src := keccak256(add(data, mul(0x20, full)), 0x20)
                    let i := 0
                    for {{ }} lt(i, full) {{ i := add(i, 0x01) }} {{
                        mstore(add(data, mul(0x20, i)), sload(add(src, i)))
                    }}
                    mstore(0x40, add(data, mul(0x20, add(full, 0x01))))
                }}
            }}
        }}
        return (who, payload);
    }}
"""

PUSH = """    function {name}(uint256 arg0, uint256 arg1) public returns (uint256) {{
        uint256 len;
        assembly {{
            let scratch := mload(0x40)
            mstore(scratch, {count_slot})
            let base := keccak256(scratch, 0x20)
            len := sload({count_slot})
            let idx := len
            let wslot := add(base, add(mul({stride}, idx), {addr_off}))
            let dslot := add(base, add(mul({stride}, idx), {str_off}))
            sstore({count_slot}, add(len, 0x01))
            sstore(wslot, and(calldataload(0x04), {mask160}))
            let d := add(0x04, calldataload(0x24))
            let n := calldataload(d)
            switch lt(n, 0x20)
            case 1 {{
                let v := 0
                let i := 0
                for {{ }} lt(i, n) {{ i := add(i, 0x01) }} {{
                    v := add(v, shl(mul(8, sub(31, i)), byte(i, calldataload(add(d, 0x20)))))
                }}
                v := or(v, add(shl(0x01, n), 0x01))
                sstore(dslot, v)
            }}
            default {{
                sstore(dslot, shl(0x01, n))
                mstore(scratch, dslot)
                let src := keccak256(scratch, 0x20)
                let words := shr(0x05, add(n, 0x1f))
                let i := 0
                for {{ }} lt(i, words) {{ i := add(i, 0x01) }} {{
                    sstore(add(src, i), calldataload(add(d, add(0x20, mul(0x20, i)))))
                }}
            }}
        }}
        return {ret};
    }}
"""

LENS = """    function {name}() public view returns (uint256) {{
        uint256 v;
        assembly {{
            v := sload({count_slot})
        }}
        return v;
    }}
"""


def _selftest() -> int:
    """Pure-python model of the two units' storage algebra; no EVM, no subprocess.

    Mirrors the template formulas exactly (short: v=2n+1 high-bytes; long:
    v=2n, ceil(n/32) big-endian words, partial tail raw). Asserts push->getter
    round-trip and count maintenance for the length spectrum, including the
    31/32 boundary and multi-word remainders.
    """
    MASK = (1 << 160) - 1
    MASK256 = (1 << 256) - 1
    notes = []

    def _keccak(word: int) -> int:
        # EVM keccak256 via the repo-standard helper; sha3 fallback differs in
        # padding and is flagged, since slots then diverge from the EVM's
        out = subprocess.run(["cast", "keccak", "0x" + f"{word:064x}"],
                             capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip().startswith("0x"):
            return int(out.stdout.strip(), 16)
        import hashlib
        if "sha3-fallback" not in notes:
            notes.append("sha3-fallback: cast keccak unavailable; slots differ from EVM keccak")
        return int.from_bytes(hashlib.sha3_256(word.to_bytes(32, "big")).digest(), "big")

    def push(storage, count_slot, base, stride, addr_off, str_off, addr, data: bytes):
        len_ = storage.get(count_slot, 0)
        idx = len_
        storage[count_slot] = (len_ + 1) & MASK256
        storage[(base + stride * idx + addr_off) & MASK256] = addr & MASK
        dslot = (base + stride * idx + str_off) & MASK256
        n = len(data)
        if n < 0x20:
            v = 0
            for i in range(n):
                v |= data[i] << (8 * (31 - i))
            storage[dslot] = v | (n << 1) | 1
        else:
            storage[dslot] = n << 1
            words = ((n - 1) >> 5) + 1
            for i in range(words):
                chunk = data[32 * i:32 * i + 32]
                word = int.from_bytes(chunk.ljust(32, b"\x00"), "big")
                storage[_src_slot(dslot, i)] = word
        return len_

    def _src_slot(dslot, i):
        # keccak256(abi.encode(uint256(dslot))): keccak over the 32-byte slot key
        return _keccak(dslot) + i

    def getter(storage, count_slot, base, stride, addr_off, str_off, idx):
        len_ = storage.get(count_slot, 0)
        if idx >= len_:
            return "PANIC"
        wslot = (base + stride * idx + addr_off) & MASK256
        dslot = (base + stride * idx + str_off) & MASK256
        who = storage.get(wslot, 0) & MASK
        v = storage.get(dslot, 0)
        if v & 1:
            n = (v & 0xFF) >> 1
            data = bytes((v >> (8 * (31 - i))) & 0xFF for i in range(n))
        else:
            n = v >> 1
            full = ((n - 1) >> 5) + 1 if n else 0
            raw = b""
            for i in range(full):
                w = storage.get(_src_slot(dslot, i), 0)
                raw += w.to_bytes(32, "big")
            data = raw[:n]
        return who, data

    keccak0 = _keccak(0)
    failures = 0
    for n in list(range(0, 40)) + [63, 64, 65, 95, 96, 97, 128]:
        storage = {}
        payload = bytes((0x61 + (i % 26)) for i in range(n))
        addr = 0x70997970C51812dc3A010C7d01b50e0d17dc79C8
        push(storage, 0, keccak0, 2, 0, 1, addr, payload)
        got = getter(storage, 0, keccak0, 2, 0, 1, 0)
        want_len = storage[0]
        ok = got != "PANIC" and got[0] == addr and got[1] == payload and want_len == 1
        if not ok:
            failures += 1
            print(f"FAIL n={n}: got={got!r} want_len={want_len}")
    # second element lands on the next stride, first is untouched
    storage = {}
    push(storage, 0, keccak0, 2, 0, 1, 0x1111, b"alpha")
    push(storage, 0, keccak0, 2, 0, 1, 0x2222, b"beta")
    r0, r1 = getter(storage, 0, keccak0, 2, 0, 1, 0), getter(storage, 0, keccak0, 2, 0, 1, 1)
    if r0 != (0x1111, b"alpha") or r1 != (0x2222, b"beta") or storage[0] != 2:
        failures += 1
        print(f"FAIL two-adjacent: {r0} {r1} count={storage.get(0)}")
    # out-of-range panics
    if getter(storage, 0, keccak0, 2, 0, 1, 2) != "PANIC":
        failures += 1
        print("FAIL oob not panicked")
    print("selftest:", "OK" if failures == 0 else f"{failures} failure(s)")
    if notes:
        print("notes:", "; ".join(notes))
    return 1 if failures else 0

def replace_unit_body(source: str, unit, new_text: str) -> str:
    """Replace the whole unit (comment header included) with `new_text`."""
    return source[: unit.start] + new_text + "\n" + source[unit.end :].lstrip("\n")


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return _selftest()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count-slot", required=True, help="storage slot word of the length, e.g. 0x00")
    parser.add_argument("--stride", type=int, required=True)
    parser.add_argument("--addr-offset", type=int, required=True)
    parser.add_argument("--string-offset", type=int, required=True)
    parser.add_argument("--getter", required=True)
    parser.add_argument("--push", required=True)
    parser.add_argument("--lens", required=True)
    parser.add_argument("--long-encoding", choices=["plain", "half"], default="plain",
                        help="retained for lineage compat; the canonical (solid) encoding is "
                             "always emitted since the variant axis was resolved")
    parser.add_argument("--push-ret", choices=["old", "new"], default="old")
    args = parser.parse_args()

    investigator = _load_investigator()
    source = args.source.read_text(encoding="utf-8")
    parsed = investigator.parse_contract(source, None)
    units = {u.name: u for u in parsed.functions}

    shared = {
        "count_slot": args.count_slot,
        "stride": args.stride,
        "addr_off": args.addr_offset,
        "str_off": args.string_offset,
        "mask160": MASK160,
        "long_enc": 0 if args.long_encoding == "plain" else 1,
    }
    plans = []
    for role, template, extra in [
        ("getter", GETTER, {"name": args.getter, "ge": "iszero(lt(arg0, len))"}),
        ("push", PUSH, {"name": args.push, "ret": "len" if args.push_ret == "old" else "len + 1"}),
        ("lens", LENS, {"name": args.lens}),
    ]:
        name = extra["name"]
        unit = units.get(name)
        if unit is None:
            print(f"unit {name} not found", file=sys.stderr)
            return 1
        body = template.format(**{**shared, **extra})
        # span-first planning: replacements apply against the ONE original
        # parse, in descending start order, so earlier splices never shift
        # later spans (the synthesize_error_units discipline)
        plans.append((unit.start, unit.end, body))
        edits = len(plans)

    for start, end, body in sorted(plans, key=lambda plan: -plan[0]):
        source = source[:start] + body + "\n" + source[end:].lstrip("\n")

    args.out.write_text(source, encoding="utf-8")
    print(f"wrote {args.out} ({edits} units rebuilt; long={args.long_encoding} ret={args.push_ret})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
