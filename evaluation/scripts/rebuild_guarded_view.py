#!/usr/bin/env python3
"""Rebuild one zero-arg view unit as a guarded single return (layout-guarded accessor repair).

Batch-3 repair class, sibling of the struct-array and string-slot rebuilders: when the
decompiler's structuring of a require-guarded accessor loses a revert edge (e.g. a conjunct
chain rendered as nested if/else whose outer else path falls through to the default return),
the unit body is rebuilt over the recorded storage layout as

    require(<guard>, "<msg>");
    return <value-expr>;

keeping the name, the preceding comment block, and the signature BYTE-IDENTICAL (the parser's
unit span includes the preceding comments; they are re-emitted verbatim).

Division of labor (the recorded pattern): the layout algebra lives in the caller-supplied
guard/value expressions, which must be atoms already proven on the fixture (probe-green units,
ladder-recorded slot aliases); this tool performs the gated splice only. The harness is the
sole semantic judge. Gates abstain with a nonzero exit and a message on stderr - a wrong
invocation fails loudly, never silently.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVESTIGATOR = ROOT / "evaluation" / "scripts" / "run_investigator.py"


def _load_investigator():
    spec = importlib.util.spec_from_file_location("_inv_rgv", INVESTIGATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["_inv_rgv"] = module
    spec.loader.exec_module(module)
    return module


class GateError(Exception):
    pass


def check_single_expression(expr: str, what: str) -> None:
    """A Solidity expression: balanced parens/brackets, no statement or literal delimiters."""
    text = expr.strip()
    if not text:
        raise GateError(f"{what}: empty expression")
    for ch in ';{}"':
        if ch in text:
            raise GateError(f"{what}: {ch!r} not allowed in a single expression")
    depth = 0
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
            if depth < 0:
                raise GateError(f"{what}: unbalanced brackets")
    if depth != 0:
        raise GateError(f"{what}: unbalanced brackets")


def _skip_block(source: str, open_index: int) -> int:
    depth = 0
    index = open_index
    while index < len(source):
        ch = source[index]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise GateError("unbalanced parens in signature")


def _signature_facts(header: str, name: str) -> tuple[str, str]:
    """Return (params_group, returns_group) from a function header's signature text."""
    call = re.search(r"\bfunction\s+%s\s*\(" % re.escape(name), header)
    if call is None:
        raise GateError("unit header does not start with a function declaration")
    open_paren = header.index("(", call.end() - 1)
    close_paren = _skip_block(header, open_paren)
    params = header[open_paren + 1 : close_paren].strip()
    returns_match = re.search(r"\breturns\s*\(", header[close_paren:])
    if returns_match is None:
        raise GateError("unit has no returns clause")
    ret_open = close_paren + returns_match.end() - 1
    ret_close = _skip_block(header, ret_open)
    returns = header[ret_open + 1 : ret_close].strip()
    return params, returns


def _require_spans(body: str) -> list[str]:
    """require(...) argument spans, located on comment/string-masked text (offsets preserved),
    sliced from the raw body so string literals remain intact for the message check."""
    masked = _load_investigator()._mask_strings_and_comments(body, 0, len(body))
    spans = []
    for match in re.finditer(r"\brequire\s*\(", masked):
        open_paren = match.end() - 1
        try:
            close_paren = _skip_block(masked, open_paren)
        except GateError:
            continue
        spans.append(body[open_paren + 1 : close_paren])
    return spans


def build_replacement(old_text: str, name: str, guard: str, msg: str, value_expr: str) -> str:
    """The gated transform: returns the replacement span text (comments + signature + new body)."""
    check_single_expression(guard, "guard")
    check_single_expression(value_expr, "value expression")

    sig_match = re.search(r"\bfunction\s+%s\s*\(" % re.escape(name), old_text)
    if sig_match is None:
        raise GateError("unit span has no function declaration")
    brace = None
    depth = 0
    for offset in range(sig_match.start(), len(old_text)):
        ch = old_text[offset]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "{" and depth == 0:
            brace = offset
            break
    if brace is None:
        raise GateError("unit span has no body brace")
    signature = old_text[sig_match.start() : brace + 1].rstrip()
    body = old_text[brace + 1 :]

    params, returns = _signature_facts(signature, name)
    if params:
        raise GateError("unit has parameters; the class is zero-arg view units")
    if not re.search(r"\bview\b", signature):
        raise GateError("unit is not declared view")
    top_level_commas = 0
    depth = 0
    for ch in returns:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif ch == "," and depth == 0:
            top_level_commas += 1
    if top_level_commas:
        raise GateError("unit returns a tuple; the class is single-return units")

    literal = '"%s"' % msg
    if not any(literal in span for span in _require_spans(body)):
        raise GateError("message literal not found inside a require(...) of the old body")

    # comment prefix: everything before the signature's first line (`function NAME(`)
    prefix = old_text[: sig_match.start()].rstrip("\n")
    if prefix:
        prefix += "\n"
    indentation = "        "
    return (
        prefix
        + signature
        + "\n"
        + indentation
        + "require(%s, \"%s\");\n" % (guard, msg)
        + indentation
        + "return %s;\n    " % value_expr
        + "}"
    )


def rebuild(source: str, unit_name: str, guard: str, msg: str, value_expr: str) -> str:
    investigator = _load_investigator()
    parsed = investigator.parse_contract(source, None)
    matches = [unit for unit in parsed.functions if unit.name == unit_name]
    if not matches:
        raise GateError("unit %s not found" % unit_name)
    if len(matches) > 1:
        raise GateError("unit %s matches %d units; overloads are ambiguous" % (unit_name, len(matches)))
    unit = matches[0]
    new_text = build_replacement(source[unit.start : unit.end], unit_name, guard, msg, value_expr)
    return source[: unit.start] + new_text + "\n" + source[unit.end :].lstrip("\n")


def _selftest() -> int:
    failures = []

    def check(name, condition):
        if not condition:
            failures.append(name)

    template = (
        "contract C {\n"
        "    uint256 v; // slot 0x00\n"
        "    /// @custom:selector    0x11111111\n"
        "    /// @custom:signature   foo() public view returns (uint256)\n"
        "    function foo() public view returns (uint256) {\n"
        "        if (v > 0) {\n"
        '            require(v != 1, "nope");\n'
        "        }\n"
        "        return v;\n"
        "    }\n"
        "    function bar(uint256 a) public view returns (uint256) { return a; }\n"
        "    function pureone() public pure returns (uint256) { return 1; }\n"
        "    function tworet() public view returns (uint256, uint256) { return (v, v); }\n"
        "    function nomsg() public view returns (uint256) { return v; }\n"
        "}\n"
    )

    ok = rebuild(template, "foo", "v != 0", "nope", "v")
    check("ok-require-first", 'require(v != 0, "nope");' in ok)
    check("ok-return", "        return v;" in ok)
    check("ok-comments-kept", "/// @custom:selector    0x11111111" in ok)
    check("ok-signature-kept", "function foo() public view returns (uint256) {" in ok)
    check("ok-old-body-gone", "if (v > 0)" not in ok)
    check("ok-idempotent", rebuild(ok, "foo", "v != 0", "nope", "v") == ok)
    check("ok-others-intact", "function bar(uint256 a)" in ok and "function tworet()" in ok)

    def expect_gate(label, exc, *args):
        try:
            rebuild(*args)
        except GateError as caught:
            check(label, exc in str(caught))
        else:
            check(label + "-no-error", False)

    expect_gate("missing-unit", "not found", template, "zzz", "v", "nope", "v")
    foo_unit = (
        "    function foo() public view returns (uint256) {\n"
        '            require(v != 1, "nope");\n'
        "        return v;\n"
        "    }\n"
    )
    expect_gate("overload", "ambiguous", template.replace("    function bar", foo_unit + "    function bar"),
                "foo", "v", "nope", "v")
    expect_gate("has-params", "parameters", template, "bar", "v", "nope", "v")
    expect_gate("not-view", "not declared view", template, "pureone", "v", "nope", "v")
    expect_gate("tuple-return", "tuple", template, "tworet", "v", "nope", "v")
    expect_gate("msg-missing", "require", template, "nomsg", "v", "absent", "v")
    expect_gate("bad-separator", ";", template, "foo", "v; v", "nope", "v")
    expect_gate("unbalanced", "unbalanced", template, "foo", "(v", "nope", "v")
    expect_gate("empty-expr", "empty", template, "foo", " ", "nope", "v")

    print("selftest:", "OK" if not failures else "FAIL " + ", ".join(failures))
    return 1 if failures else 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return _selftest()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--unit", required=True, help="zero-arg view unit to rebuild")
    parser.add_argument("--guard", required=True, help="require(...) guard expression")
    parser.add_argument("--msg", required=True, help='revert message, must occur in a require of the old body')
    parser.add_argument("--value-expr", dest="value_expr", required=True, help="returned expression")
    args = parser.parse_args()

    source = args.source.read_text(encoding="utf-8")
    try:
        rebuilt = rebuild(source, args.unit, args.guard, args.msg, args.value_expr)
    except GateError as exc:
        print("gate: %s" % exc, file=sys.stderr)
        return 1
    args.out.write_text(rebuilt, encoding="utf-8")
    print("wrote %s (unit %s rebuilt as guarded return)" % (args.out, args.unit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
