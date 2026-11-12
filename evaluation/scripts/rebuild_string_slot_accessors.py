#!/usr/bin/env python3
"""Rebuild single dynamic-byte-slot accessors (string/bytes state) from layout.

Tier-2 companion to rebuild_struct_array_accessors.py, for the no-array case:
the decompiler renders string/bytes accessors over phantom variables (the
bodies never load the slot), which no declaration repair can fix. When a unit
is the accessor of a slot-annotated ``bytes``/``string`` state variable, its
body is rebuilt over the canonical single-slot layout, keeping the unit's NAME
and signature shape:

  getter: v = sload(S); short (v&1): n=v>>1, data = high bytes of v;
          long: n=v>>1, data words at keccak256(S), partial tail raw.
          Returns the ABI-canonical dynamic tail ``abi.encodePacked(
          uint256(0x20), n, data...)`` declared ``returns (bytes memory)`` -
          byte-identical to the string ABI for a single dynamic return.
  setter: calldata ``<offset><len><data...>`` after the 4-byte selector is
          decoded and stored with the same duality; the length word is
          ``n<<1 | short`` / ``n<<1``.

Proven invariants live in rebuild_struct_array_accessors._selftest (the word
algebra is shared); this tool's selftest pins the single-slot round trip and
the returned byte layout.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVESTIGATOR = ROOT / "evaluation" / "scripts" / "run_investigator.py"


def _load_investigator():
    spec = importlib.util.spec_from_file_location("_inv_ssl", INVESTIGATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_inv_ssl"] = module
    spec.loader.exec_module(module)
    return module


GETTER = """    function {name}() public view returns (bytes memory) {{
        uint256 len;
        bytes memory payload;
        assembly {{
            let v := sload({slot})
            switch and(v, 0x01)
            case 1 {{ len := shr(0x01, and(v, 0xff)) }}
            default {{ len := shr(0x01, v) }}
            let data := add(mload(0x40), 0x20)
            payload := mload(0x40)
            mstore(payload, len)
            switch len
            case 0 {{
                mstore(0x40, add(data, 0x20))
            }}
            default {{
                switch and(v, 0x01)
                case 1 {{
                    let i := 0
                    for {{ }} lt(i, len) {{ i := add(i, 0x01) }} {{
                        mstore8(add(data, i), byte(i, v))
                    }}
                }}
                default {{
                    mstore(0x00, {slot})
                    let src := keccak256(0x00, 0x20)
                    let full := shr(0x05, add(len, 0x1f))
                    let i := 0
                    for {{ }} lt(i, full) {{ i := add(i, 0x01) }} {{
                        mstore(add(data, mul(0x20, i)), sload(add(src, i)))
                    }}
                }}
                mstore(0x40, add(data, mul(0x20, shr(0x05, add(len, 0x1f)))))
            }}
        }}
        return payload;
    }}
"""

SETTER = """    function {name}(uint256 arg0) public {{
        assembly {{
            let offset := calldataload(0x04)
            let loc := add(0x04, offset)
            let n := calldataload(loc)
            switch lt(n, 0x20)
            case 1 {{
                let v := 0
                let i := 0
                for {{ }} lt(i, n) {{ i := add(i, 0x01) }} {{
                    v := add(v, shl(mul(8, sub(31, i)), byte(i, calldataload(add(loc, 0x20)))))
                }}
                sstore({slot}, or(v, add(shl(0x01, n), 0x01)))
            }}
            default {{
                sstore({slot}, shl(0x01, n))
                mstore(0x00, {slot})
                let dst := keccak256(0x00, 0x20)
                let words := shr(0x05, add(n, 0x1f))
                let i := 0
                for {{ }} lt(i, words) {{ i := add(i, 0x01) }} {{
                    sstore(add(dst, i), calldataload(add(loc, add(0x20, mul(0x20, i)))))
                }}
            }}
        }}
    }}
"""


GETTER2 = """    function {name}() public view returns (bytes memory, bytes memory) {{
        uint256 lenA;
        uint256 lenB;
        bytes memory payloadA;
        bytes memory payloadB;
        assembly {{
            let vA := sload({slot_a})
            switch and(vA, 0x01)
            case 1 {{ lenA := shr(0x01, and(vA, 0xff)) }}
            default {{ lenA := shr(0x01, vA) }}
            let vB := sload({slot_b})
            switch and(vB, 0x01)
            case 1 {{ lenB := shr(0x01, and(vB, 0xff)) }}
            default {{ lenB := shr(0x01, vB) }}
            let base := mload(0x40)
            let wordsA := shr(0x05, add(lenA, 0x1f))
            let offB := add(0x60, mul(0x20, wordsA))
            mstore(base, 0x40)
            mstore(add(base, 0x20), offB)
            payloadA := add(base, 0x40)
            mstore(payloadA, lenA)
            let dataA := add(payloadA, 0x20)
            switch lenA
            case 0 {{ }}
            default {{
                switch and(vA, 0x01)
                case 1 {{
                    let i := 0
                    for {{ }} lt(i, lenA) {{ i := add(i, 0x01) }} {{
                        mstore8(add(dataA, i), byte(i, vA))
                    }}
                }}
                default {{
                    mstore(0x00, {slot_a})
                    let src := keccak256(0x00, 0x20)
                    let i := 0
                    for {{ }} lt(i, wordsA) {{ i := add(i, 0x01) }} {{
                        mstore(add(dataA, mul(0x20, i)), sload(add(src, i)))
                    }}
                }}
            }}
            payloadB := add(base, offB)
            mstore(payloadB, lenB)
            let dataB := add(payloadB, 0x20)
            switch lenB
            case 0 {{ }}
            default {{
                switch and(vB, 0x01)
                case 1 {{
                    let i := 0
                    for {{ }} lt(i, lenB) {{ i := add(i, 0x01) }} {{
                        mstore8(add(dataB, i), byte(i, vB))
                    }}
                }}
                default {{
                    mstore(0x00, {slot_b})
                    let src := keccak256(0x00, 0x20)
                    let wordsB := shr(0x05, add(lenB, 0x1f))
                    let i := 0
                    for {{ }} lt(i, wordsB) {{ i := add(i, 0x01) }} {{
                        mstore(add(dataB, mul(0x20, i)), sload(add(src, i)))
                    }}
                }}
            }}
            mstore(0x40, add(add(payloadB, 0x20), mul(0x20, shr(0x05, add(lenB, 0x1f)))))
        }}
        return (payloadA, payloadB);
    }}
"""

SETTER0 = """    function {name}() public pure {{
        // no storage setter exists for this fixture; placeholder removed
    }}
"""


def replace_unit_body(source: str, unit, new_text: str) -> str:
    return source[: unit.start] + new_text + "\n" + source[unit.end :].lstrip("\n")


def _selftest() -> int:
    """Round-trip the single-slot algebra and the returned byte layout."""
    import hashlib

    MASK256 = (1 << 256) - 1
    notes = []

    def _keccak(word: int) -> int:
        out = subprocess.run(["cast", "keccak", "0x" + f"{word:064x}"],
                             capture_output=True, text=True)
        if out.returncode == 0 and out.stdout.strip().startswith("0x"):
            return int(out.stdout.strip(), 16)
        import hashlib as _h
        if "sha3-fallback" not in notes:
            notes.append("sha3-fallback: cast keccak unavailable")
        return int.from_bytes(_h.sha3_256(word.to_bytes(32, "big")).digest(), "big")

    SLOT = 3
    store: dict[int, int] = {}

    def setter(data: bytes) -> None:
        n = len(data)
        if n < 0x20:
            v = 0
            for i in range(n):
                v |= data[i] << (8 * (31 - i))
            store[SLOT] = (v | (n << 1) | 1) & MASK256
        else:
            store[SLOT] = (n << 1) & MASK256
            base = _keccak(SLOT)
            for i in range(((n - 1) >> 5) + 1):
                chunk = data[32 * i:32 * i + 32]
                store[(base + i) & MASK256] = int.from_bytes(chunk.ljust(32, b"\x00"), "big")

    def getter() -> bytes:
        v = store.get(SLOT, 0)
        if v & 1:
            n = (v & 0xFF) >> 1
            return bytes((v >> (8 * (31 - i))) & 0xFF for i in range(n))
        n = v >> 1
        if n == 0:
            return b""
        base = _keccak(SLOT)
        full = ((n - 1) >> 5) + 1
        raw = b"".join(store.get((base + i) & MASK256, 0).to_bytes(32, "big") for i in range(full))
        return raw[:n]

    def abi_bytes_mem(data: bytes) -> bytes:
        # what the yul getter materializes: 0x20, len, data padded to words
        pad = (-len(data)) % 32
        return (32).to_bytes(32, "big") + len(data).to_bytes(32, "big") + data + b"\x00" * pad

    failures = 0
    for n in list(range(0, 70)) + [95, 96, 97, 128]:
        store.clear()
        payload = bytes(0x61 + (i % 26) for i in range(n))
        setter(payload)
        got = getter()
        if got != payload:
            failures += 1
            print(f"FAIL round-trip n={n}")
    # overwrite: long after short on the same slot, and vice versa
    store.clear()
    setter(b"short")
    setter(bytes(range(64)))
    if getter() != bytes(range(64)):
        failures += 1
        print("FAIL short->long overwrite")
    setter(b"tiny")
    if getter() != b"tiny":
        failures += 1
        print("FAIL long->short overwrite")
    # the getter's declared bytes-memory return must ABI-match a string return
    store.clear()
    setter(b"abc")
    if abi_bytes_mem(b"abc") != (32).to_bytes(32, "big") + (3).to_bytes(32, "big") + b"abc" + b"\x00" * 29:
        failures += 1
        print("FAIL abi layout")
    # two-value return layout: ret[0]=0x40, ret[1]=0x40+0x20+words0*32
    def abi_pair(b0: bytes, b1: bytes) -> bytes:
        w0 = (len(b0) + 31) // 32
        off1 = 0x40 + 0x20 + 0x20 * w0
        pad = lambda x: x + b"\x00" * ((-len(x)) % 32)
        return ((0x40).to_bytes(32, "big") + off1.to_bytes(32, "big")
                + len(b0).to_bytes(32, "big") + pad(b0)
                + len(b1).to_bytes(32, "big") + pad(b1))
    want_empty = abi_pair(b"", b"")
    if want_empty != (0x40).to_bytes(32, "big") + (0x60).to_bytes(32, "big") + \
            (0).to_bytes(32, "big") + (0).to_bytes(32, "big"):
        failures += 1
        print("FAIL pair-empty layout")
    want_mixed = abi_pair(b"abc", b"")
    if len(want_mixed) != 32 * 5 or want_mixed[64:96] != (3).to_bytes(32, "big"):
        failures += 1
        print("FAIL pair-mixed layout")
    print("selftest:", "OK" if failures == 0 else f"{failures} failure(s)")
    if notes:
        print("notes:", "; ".join(notes))
    return 1 if failures else 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return _selftest()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--slot", help="storage slot word of the bytes value, e.g. 0x00")
    parser.add_argument("--getter", action="append", default=[],
                        help="zero-arg view unit to rebuild as the slot getter (repeatable)")
    parser.add_argument("--pair-getter", action="append", default=[],
                        help="zero-arg view returning two slots: NAME,SLOT_A,SLOT_B")
    parser.add_argument("--remove-unit", action="append", default=[],
                        help="unit to replace with an empty pure no-op (repeatable)")
    parser.add_argument("--append-getter", action="append", default=[],
                        help="NEW zero-arg getter unit appended to the contract: NAME,SLOT")
    parser.add_argument("--setter", help="single-arg unit to rebuild as the slot setter")
    args = parser.parse_args()

    investigator = _load_investigator()
    source = args.source.read_text(encoding="utf-8")
    parsed = investigator.parse_contract(source, None)
    units = {u.name: u for u in parsed.functions}

    plans = []
    for spec_item in args.pair_getter:
        name, slot_a, slot_b = (x.strip() for x in spec_item.split(","))
        unit = units.get(name)
        if unit is None:
            print(f"unit {name} not found", file=sys.stderr)
            return 1
        plans.append((unit.start, unit.end,
                      GETTER2.format(name=name, slot_a=slot_a, slot_b=slot_b)))
    for name in args.remove_unit:
        unit = units.get(name)
        if unit is None:
            print(f"unit {name} not found", file=sys.stderr)
            return 1
        plans.append((unit.start, unit.end,
                      SETTER0.format(name=name)))
    for name in args.getter:
        unit = units.get(name)
        if unit is None:
            print(f"unit {name} not found", file=sys.stderr)
            return 1
        plans.append((unit.start, unit.end, GETTER.format(name=name, slot=args.slot)))
    for spec_item in args.append_getter:
        name, slot = (x.strip() for x in spec_item.split(","))
        if name in units:
            print(f"append-getter: unit {name} already exists", file=sys.stderr)
            return 1
        # insertion point: just before the contract body's closing brace
        parsed_all = parsed
        body_end = parsed_all.body_end
        plans.append((body_end, body_end, "\n" + GETTER.format(name=name, slot=slot)))

    if args.setter and not args.slot:
        parser.error("--slot is required with --setter")
    if args.setter:
        unit = units.get(args.setter)
        if unit is None:
            print(f"unit {args.setter} not found", file=sys.stderr)
            return 1
        plans.append((unit.start, unit.end, SETTER.format(name=args.setter, slot=args.slot)))

    # span-first planning: one parse, descending splice (the recorded discipline)
    for start, end, body in sorted(plans, key=lambda plan: -plan[0]):
        source = source[:start] + body + "\n" + source[end:].lstrip("\n")

    args.out.write_text(source, encoding="utf-8")
    print(f"wrote {args.out} ({len(plans)} units rebuilt on slot {args.slot})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
