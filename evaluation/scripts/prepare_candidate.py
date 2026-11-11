#!/usr/bin/env python3
"""Deterministic seed preparation for an uncompilable decompiler candidate.

The investigator needs a compilable candidate with a stable dispatch
identity; whole-source LLM repair wastes its completion budget on
reasoning before it can provide one. This script applies the cheap,
source-derived transforms first, without any model call:

1. rewrite placeholder width tokens (``uint0``/``int0``/``bytes0``) to
   their concrete types, outside comments and string literals;
2. declare custom errors and events that are referenced but never
   declared, with the arity observed at their call sites, and record
   declared-but-misused arities as findings;
3. declare ``var_*`` identifiers that are used but never declared as
   contract-level ``uint256`` state;
4. align declared parameter counts with the function's own
   ``msg.data.length`` calldata-head guard, trimming declared params the
   body never references and appending ``uint256`` placeholders the guard
   proves missing.

Every edit is recorded with its evidence; every case the source does not
cover is recorded as an abstention instead of being guessed. The output
is a staged candidate plus a per-tier compile ledger, so residual
diagnostics localize exactly which function units a bounded repair pass
must touch.

No reference Solidity, reference ABI, or probe observations are read;
the model later sees only this prepared source and compiler diagnostics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_investigator import (  # noqa: E402
    ParseError,
    _mask_strings_and_comments,
    parse_contract,
    rb,
)

PLACEHOLDER_TYPES = (("uint0", "uint256"), ("int0", "int256"), ("bytes0", "bytes"))

_SLOT_RE = re.compile(r"//\s*storage slot:\s*(0x[0-9a-fA-F]+)")


class PreparationError(RuntimeError):
    pass


@dataclass
class Stage:
    name: str
    description: str
    source: str
    edits: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)


def _record(kind: str, detail: str, evidence: str) -> dict[str, Any]:
    return {"kind": kind, "detail": detail, "evidence": evidence}


def _finding(kind: str, detail: str, reason: str) -> dict[str, Any]:
    return {"kind": kind, "detail": detail, "reason": reason}


def _call_arity(masked: str, name: str, skip: tuple[int, int] | None = None) -> int | None:
    """Argument count at call/emit sites of ``name``; None if none or ambiguous.

    ``skip`` excludes one span (e.g. the declaration itself) from the scan.
    """
    arities: set[int] = set()
    for match in re.finditer(rf"\b{name}\s*\(", masked):
        if skip and match.start() >= skip[0] and match.end() <= skip[1]:
            continue
        depth = 1
        index = match.end()
        commas = 0
        seen_token = False
        while index < len(masked) and depth > 0:
            char = masked[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 1:
                commas += 1
                seen_token = True
            elif not char.isspace():
                seen_token = True
            index += 1
        if depth != 0:
            return None
        arities.add(commas + 1 if seen_token else 0)
    if len(arities) != 1:
        return None
    return next(iter(arities))


def _body_open_line_end(source: str, body_start: int) -> int:
    newline = source.find("\n", max(0, body_start - 1))
    return (newline + 1) if newline != -1 else len(source)


def _insertion_offset(source: str, masked: str, pattern: str, fallback: int) -> int:
    """Offset past the end of the last mask-confirmed ``pattern`` line match."""
    offset = fallback
    for match in re.finditer(pattern, masked, re.M):
        line_end = source.find("\n", match.start())
        offset = (line_end + 1) if line_end != -1 else len(source)
    return offset


def normalize_placeholders(source: str) -> Stage:
    """Tier 1: rewrite placeholder width tokens outside comments and strings."""
    masked = _mask_strings_and_comments(source, 0, len(source))
    edits: list[dict[str, Any]] = []
    replacement = source
    for placeholder, concrete in PLACEHOLDER_TYPES:
        for match in reversed(list(re.finditer(rf"(?<![A-Za-z0-9_]){placeholder}(?![A-Za-z0-9_])", masked))):
            start, end = match.span()
            replacement = replacement[:start] + concrete + replacement[end:]
            masked = masked[:start] + concrete + masked[end:]
            edits.append(
                _record(
                    "placeholder-type",
                    f"{placeholder} -> {concrete}",
                    re.sub(r"\s+", " ", source[max(0, start - 48) : end + 8]).strip(),
                )
            )
    return Stage("placeholders", "placeholder width tokens", replacement, edits)


def declare_missing_symbols(source: str) -> Stage:
    """Tier 3: declare/reconcile error and event declarations from usage sites.

    Two independent passes on fresh coordinates: first retype declared
    symbols whose usage disagrees, then insert declarations for symbols
    referenced but never declared.
    """
    edits: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    current = source
    for name in sorted(set(re.findall(r"\bevent\s+([A-Za-z_]\w*)\b", _mask_strings_and_comments(current, 0, len(current))))):
        masked = _mask_strings_and_comments(current, 0, len(current))
        parsed = parse_contract(current, None)
        current = _reconcile_declaration(current, masked, parsed, name, "event", edits, findings)
    for name in sorted(set(re.findall(r"\berror\s+([A-Za-z_]\w*)\b", _mask_strings_and_comments(current, 0, len(current))))):
        masked = _mask_strings_and_comments(current, 0, len(current))
        parsed = parse_contract(current, None)
        current = _reconcile_declaration(current, masked, parsed, name, "error", edits, findings)

    masked = _mask_strings_and_comments(current, 0, len(current))
    parsed = parse_contract(current, None)
    body_start = _body_open_line_end(current, parsed.body_start)
    declared_errors = set(re.findall(r"\berror\s+([A-Za-z_]\w*)\s*\(", masked))
    declared_events = set(re.findall(r"\bevent\s+([A-Za-z_]\w*)\s*\(", masked))
    used_errors = set(re.findall(r"\b(CustomError_[0-9a-fA-F]{8})\s*\(", masked))
    used_events = set(re.findall(r"\b(Event_[0-9a-fA-F]{8})\s*\(", masked))

    insertions: list[tuple[int, str]] = []

    for name in sorted(used_errors - declared_errors):
        arity = _call_arity(masked, name)
        if arity is None:
            findings.append(_finding("undeclared-error", name, "call sites disagree on arity"))
            continue
        params = ", ".join(["uint256"] * arity)
        line = f"    error {name}({params});\n"
        offset = _insertion_offset(current, masked, r"^\s*error\s+\w+\([^;]*;\s*$", body_start)
        insertions.append((offset, line))
        edits.append(_record("undeclared-error", f"error {name}({params})", "referenced before declaration"))

    for name in sorted(used_events - declared_events):
        arity = _call_arity(masked, name)
        if arity is None:
            findings.append(_finding("undeclared-event", name, "emit sites disagree on arity"))
            continue
        params = ", ".join(["uint256"] * arity)
        line = f"    event {name}({params});\n"
        offset = _insertion_offset(current, masked, r"^\s*event\s+\w+\([^;]*;\s*$", body_start)
        insertions.append((offset, line))
        edits.append(_record("undeclared-event", f"event {name}({params})", "referenced before declaration"))

    replacement = current
    for offset, line in sorted(insertions, key=lambda item: -item[0]):
        replacement = replacement[:offset] + line + replacement[offset:]

    return Stage("declarations", "error/event declarations", replacement, edits, findings)


def _reconcile_declaration(
    source: str,
    masked: str,
    parsed,
    name: str,
    kind: str,
    edits: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> str:
    """Retype a declared symbol whose usage arity disagrees, when types are provable.

    Per-position types come from the usage sites only: ``msg.sender``, names
    declared as parameters or state, and ``uint256`` for every other
    expression. Sites must agree on arity and on every inferred position;
    anything weaker is left as a finding for unit repair.
    """
    declaration = re.search(rf"\b{kind}\s+{name}\s*\([^;]*;", masked)
    if not declaration:
        return source
    inner = declaration.group(0)
    inner = inner[inner.index("(") : inner.rindex(")")]
    inner = inner[1:-1].strip()
    declared = len([part for part in inner.split(",") if part.strip()]) if inner else 0
    use_arity = _call_arity(masked, name, skip=(declaration.start(), declaration.end()))
    if use_arity is None or use_arity == declared:
        return source

    sites = [
        match
        for match in re.finditer(rf"\b{name}\s*\(", masked)
        if not (declaration.start() <= match.start() < declaration.end())
    ]
    param_types: list[set[str]] = [set() for _ in range(use_arity)]
    for site in sites:
        args = _split_top_level(masked, site.end() - 1)
        if args is None or len(args) != use_arity:
            return source
        for position, arg in enumerate(args):
            inferred = _infer_type(arg.strip(), parsed, source, masked, site.start())
            if inferred is None:
                return source
            param_types[position].add(inferred)
    if any(len(options) != 1 for options in param_types):
        findings.append(
            _finding(
                f"{kind}-arity-mismatch",
                name,
                f"declared with {declared} argument(s) but used with {use_arity} with "
                "conflicting inferred types; left for unit repair",
            )
        )
        return source

    rendered = ", ".join(next(iter(options)) for options in param_types)
    open_offset = declaration.start() + declaration.group(0).index("(")
    close_offset = declaration.start() + declaration.group(0).rindex(")")
    updated = source[:open_offset + 1] + rendered + source[close_offset:]
    edits.append(
        _record(
            f"{kind}-arity-retype",
            f"{name}: ({inner or ''}) -> ({rendered})",
            "usage-site arity and argument types",
        )
    )
    return updated


def _split_top_level(masked: str, open_paren: int) -> list[str] | None:
    """Top-level comma-separated arguments between ``open_paren`` and its match."""
    depth = 1
    index = open_paren + 1
    parts: list[str] = []
    start = index
    while index < len(masked) and depth > 0:
        char = masked[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        elif char == "," and depth == 1:
            parts.append(masked[start:index])
            start = index + 1
        index += 1
    if depth != 0:
        return None
    parts.append(masked[start:index])
    return parts


def _infer_type(expression: str, parsed, source: str, masked: str, site_offset: int) -> str | None:
    """Source-derived type of a call argument, or None when not provable.

    Provable means a literal, ``msg.sender``/``msg.value``, or a bare name
    declared as a function parameter in the enclosing unit or as contract
    state. Every other expression defaults to ``uint256``.
    """
    if expression in ("msg.sender",):
        return "address"
    if expression in ("msg.value",):
        return "uint256"
    if re.fullmatch(r"0x[0-9a-fA-F]+|\d+(\.\d+)?e?\d*|\d+", expression):
        return "uint256"
    if expression in ("true", "false"):
        return "bool"
    if re.fullmatch(r"[A-Za-z_]\w*", expression):
        for unit in parsed.functions:
            if unit.start <= site_offset < unit.end:
                for type_text, name in _header_params(_mask_strings_and_comments(unit.header, 0, len(unit.header))):
                    if name == expression:
                        return type_text
                break
        for unit in parsed.declarations:
            match = re.match(r"^(address|uint\d+|int\d+|bytes\d+|bytes|string|bool)\s+([A-Za-z_]\w*)\s*(?:=|;)", unit.header)
            if match and match.group(2) == expression:
                return match.group(1)
        if re.match(r"^var_[a-z]+$", expression):
            return "uint256"
    return "uint256"


def _split_self_referential_initializers(source: str, masked: str) -> tuple[str, list[dict[str, Any]]]:
    """Split ``T var_x = <expr referencing var_x>;`` when no earlier ``var_x`` binding exists.

    The decompiler emits self-referential local initializers (e.g.
    ``uint256 var_b = var_b + 0x60;``) for loop-carried accumulators; with no outer
    binding the initializer reads an identifier that is not in scope yet. Splitting
    into a default-initialized declaration plus an assignment preserves the
    decompiled expression verbatim while making the definition order explicit.
    """
    edits: list[dict[str, Any]] = []
    pattern = re.compile(
        r"(?P<indent>[ \t]*)\b(?P<type>uint\d+|int\d+|address|bytes\d+|bool)\s+"
        r"(?P<name>var_[a-z]+)\s*=\s*(?P<expr>[^;\n]+);"
    )
    out = []
    last = 0
    for match in pattern.finditer(masked):
        name = match.group("name")
        before = masked[: match.start()]
        earlier_binding = (
            re.search(r"\b%s\s*=[^=]" % re.escape(name), before)
            or re.search(r"\b(?:uint\d+|int\d+|address|bytes\d+|bool)\s+%s\b" % re.escape(name), before)
        )
        uses_self = re.search(r"\b%s\b" % re.escape(name), match.group("expr"))
        if not earlier_binding and uses_self:
            # the mask is length-preserving, so group spans address `source` directly;
            # rebuild from source text to keep string literals intact
            start, end = match.span()
            indent = source[match.start("indent") : match.end("indent")]
            src_type = source[match.start("type") : match.end("type")]
            src_name = source[match.start("name") : match.end("name")]
            src_expr = source[match.start("expr") : match.end("expr")]
            replacement = f"{indent}{src_type} {src_name};\n{indent}{src_name} = {src_expr};"
            out.append(source[last:start])
            out.append(replacement)
            last = end
            edits.append(
                _record(
                    "selfref-initializer",
                    f"{src_type} {src_name} = ...; -> {src_name}; {src_name} = ...;",
                    "self-referential initializer without an earlier binding",
                )
            )
    if not out:
        return source, edits
    out.append(source[last:])
    return "".join(out), edits


def split_selfref_initializers(source: str) -> Stage:
    """Stage: split self-referential ``var_*`` initializers (see helper above)."""
    masked = _mask_strings_and_comments(source, 0, len(source))
    source, edits = _split_self_referential_initializers(source, masked)
    return Stage("selfref", "self-referential initializers", source, edits)


def declare_undefined_vars(source: str) -> Stage:
    """Tier: declare ``var_*`` identifiers used but never declared."""
    masked = _mask_strings_and_comments(source, 0, len(source))
    used = set(re.findall(r"\b(var_[a-z]+)\b", masked))
    declared = set(re.findall(r"\buint\d*\s+(var_[a-z]+)\b", masked))
    declared |= {
        m.group(2)
        for m in re.finditer(r"\b(uint\d*|address|bool|bytes\d*)\s+(var_[a-z]+)\s*=[^=]", masked)
    }  # typed local definitions declare; bare assignment targets do not
    undeclared = sorted(used - declared)
    edits: list[dict[str, Any]] = []
    if not undeclared:
        return Stage("vars", "undefined var_* state", source, edits)
    parsed = parse_contract(source, None)
    offset = _body_open_line_end(source, parsed.body_start)
    block = "".join(f"    uint256 {name};\n" for name in undeclared)
    replacement = source[:offset] + block + source[offset:]
    for name in undeclared:
        edits.append(_record("undefined-var", f"uint256 {name}", "used before any declaration"))
    return Stage("vars", "undefined var_* state", replacement, edits)


def align_function_mutability(source: str) -> Stage:
    """Tier 3b: relax ``pure`` to ``view`` when the function body reads contract state.

    The decompiler stamps mutability from its own pre-repair view of the contract;
    once state variables exist (declared here or by earlier tiers), a ``pure``
    function whose body references one no longer compiles. Parameter shadowing is
    respected: a name bound in the header is not a state read.
    """
    parsed = parse_contract(source, None)
    # declaration name after the type, skipping visibility/mutability modifiers;
    # covers plain, mapping(...), and fixed-array state declarations
    declaration_name = re.compile(
        r"^(?:mapping\s*\([^)]*\)|(?:address|uint\d+|int\d+|bytes\d*|bytes|string|bool)(?:\[[^\]]*\])*)"
        r"(?:\s+(?:public|private|internal|constant|immutable|override))*"
        r"\s+([A-Za-z_]\w*)"
    )
    state_names = set()
    for unit in parsed.declarations:
        declared = declaration_name.match(unit.header)
        if declared:
            state_names.add(declared.group(1))
    edits: list[dict[str, Any]] = []
    pieces: list[str] = []
    last = 0
    for unit in parsed.functions:
        header_masked = _mask_strings_and_comments(unit.header, 0, len(unit.header))
        if not re.search(r"\bpure\b", header_masked):
            continue
        header_len = len(unit.header)
        body_masked = _mask_strings_and_comments(unit.text, header_len, len(unit.text))
        param_names = {name for _, name in _header_params(header_masked)}
        readable = sorted(state_names - param_names)
        if not any(re.search(r"\b%s\b" % re.escape(name), body_masked) for name in readable):
            continue
        start = unit.start
        end = unit.start + header_len
        # the header span covers the @custom:signature comment and the declaration;
        # relax every `pure` in it so the provenance comment stays in sync
        relaxed = re.sub(r"\bpure\b", "view", source[start:end])
        pieces.append(source[last:start])
        pieces.append(relaxed)
        last = end
        edits.append(
            _record("mutability-relaxed", "pure -> view", "pure function body reads contract state")
        )
    if not pieces:
        return Stage("mutability", "pure vs state reads", source, edits)
    pieces.append(source[last:])
    return Stage("mutability", "pure vs state reads", "".join(pieces), edits)


def _header_params(masked_header: str) -> list[tuple[str, str]]:
    """(type, name) pairs for a function header's parameter list."""
    match = re.search(r"\bfunction\s+[A-Za-z_]\w*\s*\(", masked_header)
    if not match:
        return []
    start = match.end()
    depth = 1
    index = start
    while index < len(masked_header) and depth > 0:
        char = masked_header[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        index += 1
    if depth != 0:
        return []
    inner = masked_header[start : index - 1]
    params: list[tuple[str, str]] = []
    for part in inner.split(","):
        words = part.split()
        if not words:
            continue
        if len(words) > 1:
            params.append((" ".join(words[:-1]), words[-1]))
        else:
            params.append((words[0], ""))
    return params


def head_guard_words(masked_body: str) -> int | None:
    """Calldata head size in words from the function's own msg.data guards.

    Considers every ``require(...)`` mentioning ``msg.data.length`` and takes
    the largest ``>= constant`` divisible by 32. Returns None when no such
    guard exists, so callers can abstain instead of guessing.
    """
    words: list[int] = []
    for require in re.finditer(r"require\([^;]*msg\.data\.length[^;]*\)", masked_body):
        for match in re.finditer(r">=\s*(0x[0-9a-fA-F]+|\d+)", require.group(0)):
            value = int(match.group(1), 0)
            if value % 32 == 0:
                words.append(value // 32)
    return max(words) if words else None


def align_arities(source: str) -> Stage:
    """Tier 4: reconcile declared parameter counts with calldata-head guards."""
    parsed = parse_contract(source, None)
    edits: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    replacements: list[tuple[int, int, str]] = []  # (start, end, replacement text)

    for unit in parsed.functions:
        masked_unit = _mask_strings_and_comments(unit.text, 0, len(unit.text))
        params = _header_params(_mask_strings_and_comments(unit.header, 0, len(unit.header)))
        named = [(type_text, name) for type_text, name in params if name]
        if len(named) != len(params):
            findings.append(_finding("arity", unit.name, "a parameter has no name; left unchanged"))
            continue
        declared = len(params)
        value_type = re.compile(r"^(uint\d+|int\d+|address|bool|bytes\d+)$")
        if not all(value_type.match(type_text) for type_text, _name in params):
            findings.append(
                _finding(
                    "arity",
                    unit.name,
                    "dynamic or composite parameter types; calldata-head arity "
                    "alignment unsupported",
                )
            )
            continue
        guard = head_guard_words(masked_unit)
        if guard is None or guard == declared:
            continue
        body_open = unit.text.index("{")
        body_masked = masked_unit[body_open:]
        if guard < declared:
            excess = params[guard:]
            referenced = [name for _t, name in excess if re.search(rf"\b{name}\b", body_masked)]
            if referenced:
                findings.append(
                    _finding(
                        "arity-trim",
                        unit.name,
                        f"guard proves {guard} head word(s) but referenced parameter(s) "
                        + ", ".join(referenced)
                        + " would be dropped; left for unit repair",
                    )
                )
                continue
            new_text = _prune_param_docs(_replace_params(unit.text, params[:guard]), [name for _t, name in params[guard:]])
            replacements.append((unit.start, unit.end, new_text))
            edits.append(
                _record(
                    "arity-trim",
                    f"{unit.name}: {declared} -> {guard} parameter(s)",
                    "calldata-head guard; removed parameters unreferenced in body; pruned matching @param docs",
                )
            )
        else:
            next_index = 0
            for _t, name in params:
                match = re.fullmatch(r"arg(\d+)", name)
                if match:
                    next_index = max(next_index, int(match.group(1)) + 1)
            added = [
                ("uint256", f"arg{next_index + offset}") for offset in range(guard - declared)
            ]
            new_text = _replace_params(unit.text, params + added)
            replacements.append((unit.start, unit.end, new_text))
            edits.append(
                _record(
                    "arity-extend",
                    f"{unit.name}: {declared} -> {guard} parameter(s)",
                    "calldata-head guard proves additional head word(s); uint256 assumed",
                )
            )

    # Units are disjoint, so descending start order keeps every pending span
    # valid even when a replacement changes the unit's length.
    replacement = source
    for start, end, text in sorted(replacements, key=lambda item: -item[0]):
        replacement = replacement[:start] + text + replacement[end:]

    return Stage("arity", "calldata-head arity alignment", replacement, edits, findings)


def _prune_param_docs(unit_text: str, dropped: list[str]) -> str:
    """Drop ``/// @param <name>`` lines from a unit's own doc block.

    The parsed unit text includes the leading ``///`` comment block, and
    solc rejects natspec documenting parameters the signature no longer
    has (error 3881); prune those lines in the same replacement that
    changes the signature.
    """
    if not dropped:
        return unit_text
    lines = unit_text.splitlines(keepends=True)
    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        matched = False
        if stripped.startswith("///"):
            for name in dropped:
                if re.match(rf"^///\s*@param\s+{re.escape(name)}\b", stripped):
                    matched = True
                    break
        if not matched:
            kept.append(line)
    return "".join(kept)


def _replace_params(unit_text: str, params: list[tuple[str, str]]) -> str:
    """Return ``unit_text`` with the header's parameter list replaced."""
    masked = _mask_strings_and_comments(unit_text, 0, len(unit_text))
    open_match = re.search(r"\bfunction\s+[A-Za-z_]\w*\s*\(", masked)
    if not open_match:
        raise PreparationError(f"cannot locate parameter list in: {unit_text[:80]!r}")
    start = open_match.end()
    depth = 1
    index = start
    while index < len(masked) and depth > 0:
        char = masked[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        index += 1
    if depth != 0:
        raise PreparationError(f"unbalanced parameter list in: {unit_text[:80]!r}")
    rendered = ", ".join(
        f"{type_text} {name}".strip() if name else type_text for type_text, name in params
    )
    return unit_text[:start] + rendered + unit_text[index - 1 :]


_VIEW_CASTS = {
    # (primary type, alias type) -> (read expr template, write expr template); {v} is the
    # primary variable. Only same-word representations are proven; anything else abstains.
    ("bytes32", "address"): ("address(uint160(uint256({v})))", "bytes32(uint256(uint160({x})))"),
    ("bytes32", "uint256"): ("uint256({v})", "bytes32({x})"),
    ("uint256", "bytes32"): ("bytes32({v})", "uint256({x})"),
    ("address", "uint256"): ("uint256(uint160({v}))", "address(uint256({x}))"),
    ("uint160", "address"): ("address(uint160({v}))", "uint160(uint256({x}))"),
}


def _declared_slots(source: str, masked: str) -> dict[str, tuple[str, str]]:
    """State variables with slot provenance.

    Structure comes from the masked text (commented-out declarations are
    spaces there and never match); the slot comment itself is read from the
    raw source at the same offsets.
    """
    declared: dict[str, tuple[str, str]] = {}
    for match in re.finditer(
        r"^\s*(address|uint\d+|int\d+|bytes\d+|bytes|string|bool)\s+([A-Za-z_]\w*)\s*;([^\n]*)",
        masked,
        re.M,
    ):
        raw_tail = source[match.start(3) : match.end(3)] if match.group(3) else ""
        slot = re.search(r"//\s*storage slot:\s*(0x[0-9a-fA-F]+)", raw_tail)
        declared[match.group(2)] = (match.group(1), (slot.group(1) if slot else "").lower())
    return declared


def _write_targets(masked_body: str) -> set[str]:
    """Identifiers assigned in the masked snippet (``=``, compound, inc/dec)."""
    return {
        match.group(1)
        for match in re.finditer(r"\b([A-Za-z_]\w*)\b\s*(?:=(?!=)|\+=|-=|\*=|/=|\+\+|--)", masked_body)
    }


def unify_storage_views(source: str) -> Stage:
    """Collapse same-slot storage declarations into one canonical variable.

    The decompiler can emit several views of one storage slot (for
    synthetic-large: ``address store_h`` and ``bytes32 store_f``, both
    ``slot 0x00``). Recompiled, they become distinct slots, so a writer
    through one view and a reader through the other silently disagree. The
    variable with writes becomes canonical; pure-read aliases are replaced
    at their use sites by a proven widening/narrowing cast pair. Aliases
    that are written, or type pairs without a proven conversion, abstain.
    """
    masked = _mask_strings_and_comments(source, 0, len(source))
    declared = _declared_slots(source, masked)
    by_slot: dict[str, list[str]] = {}
    for name, (_type, slot) in declared.items():
        if slot:
            by_slot.setdefault(slot, []).append(name)

    edits: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    renames: dict[str, str] = {}  # alias identifier -> read expression

    for slot, names in sorted(by_slot.items()):
        if len(names) < 2:
            continue
        names = sorted(names, key=lambda name: re.search(
            rf"^\s*\S+\s+{re.escape(name)}\s*;", masked, re.M
        ).start())
        types = {name: declared[name][0] for name in names}
        writers = {name: (name in _write_targets(masked)) for name in names}
        written = [name for name in names if writers[name]]
        if len(written) > 1:
            findings.append(
                _finding(
                    "slot-alias",
                    ", ".join(names),
                    f"slot {slot} has multiple written views; pairing is ambiguous",
                )
            )
            continue
        primary = written[0] if written else names[0]
        for alias in names:
            if alias == primary:
                continue
            if writers[alias]:
                findings.append(
                    _finding("slot-alias", alias, f"alias {alias} on slot {slot} is written; left for unit repair")
                )
                continue
            cast = _VIEW_CASTS.get((types[primary], types[alias]))
            if cast is None:
                findings.append(
                    _finding(
                        "slot-alias",
                        alias,
                        f"no proven conversion {types[primary]} -> {types[alias]} on slot {slot}",
                    )
                )
                continue
            # Whole-word pairs (bytes32/uint256) are proven by the slot width. A
            # narrower view (address/uintN) additionally needs evidence that the
            # writer stores the value in the low bits: a uint160 cast in the
            # primary's own write expressions.
            if {"address", "uint160"} & {types[primary], types[alias]}:
                write_snippets = " ".join(
                    match.group(0)
                    for match in re.finditer(
                        rf"\b{primary}\s*=[^;]+;", masked
                    )
                )
                if "uint160(" not in write_snippets:
                    findings.append(
                        _finding(
                            "slot-alias",
                            alias,
                            f"writer of {primary} never narrows through uint160; "
                            "packed layout unproven",
                        )
                    )
                    continue
            uses = re.findall(rf"\b{alias}\s*[[.]", masked)
            if uses:
                findings.append(
                    _finding(
                        "slot-alias",
                        alias,
                        f"{len(uses)} non-whole-word use(s) of {alias}; packing unproven",
                    )
                )
                continue
            renames[alias] = cast[0].format(v=primary)

    if not renames:
        return Stage("slot-aliases", "storage-view aliases", source, edits, findings)

    replacement = source
    for alias, expression in sorted(renames.items()):
        # Declaration line first (offsets stay valid: later edits are to the left).
        declaration = re.search(rf"^\s*(?:address|uint\d+|int\d+|bytes\d+|bytes|string|bool)\s+{alias}\s*;[^\n]*\n", replacement, re.M)
        if declaration:
            replacement = replacement[: declaration.start()] + replacement[declaration.end() :]
        masked_rest = _mask_strings_and_comments(replacement, 0, len(replacement))
        for match in reversed(list(re.finditer(rf"\b{alias}\b", masked_rest))):
            start, end = match.span()
            replacement = replacement[:start] + expression + replacement[end:]
        edits.append(
            _record(
                "slot-alias",
                f"{alias} -> {expression}",
                f"same-slot view ({declared[alias][1]}); canonical variable carries the writes",
            )
        )

    return Stage("slot-aliases", "storage-view aliases", replacement, edits, findings)


def _packed_close(masked: str, open_paren: int) -> int | None:
    """Offset just past the parenthesis matching ``open_paren``, or None."""
    depth, index = 1, open_paren + 1
    while index < len(masked) and depth > 0:
        if masked[index] == "(":
            depth += 1
        elif masked[index] == ")":
            depth -= 1
        index += 1
    return index if depth == 0 else None


def _packed_uint_kind(ident: str, position: int, params_by_unit) -> bool:
    for start, end, params in params_by_unit:
        if start <= position < end:
            return params.get(ident) in ("uint", "uint256")
    return False


def _packed_length_read(masked: str, name: str, start: int, end: int, params_by_unit) -> bool:
    """True when this ``X.length`` is a comparison operand against a
    proven-unsigned identifier or an integer literal."""
    window_start = max(0, start - 160)
    window_end = min(len(masked), end + 160)
    window = masked[window_start:window_end]
    token = re.escape(name)
    occ = re.escape(masked[start:end])
    for pattern in (
        rf"(?P<other>[A-Za-z_]\w*|\d+|0x[0-9a-fA-F]+)\s*(?:<=|>=|<|>)\s*uint256\s*\(\s*{occ}\s*\)",
        rf"(?P<other>[A-Za-z_]\w*|\d+|0x[0-9a-fA-F]+)\s*(?:<=|>=|<|>)\s*{occ}\b",
        rf"{occ}\s*\)?\s*(?:<=|>=|<|>)\s*(?:uint256\s*\(\s*(?P<wrapped>[A-Za-z_]\w*)\s*\)|(?P<other2>[A-Za-z_]\w*|\d+|0x[0-9a-fA-F]+))",
    ):
        match = re.search(pattern, window)
        if not match:
            continue
        other = match.groupdict().get("other") or match.groupdict().get("other2") or match.groupdict().get("wrapped")
        if other is None or other.isdigit() or other.startswith("0x"):
            return True
        gname = "other" if match.groupdict().get("other") else ("wrapped" if match.groupdict().get("wrapped") else "other2")
        absolute = window_start + match.start(gname)
        return _packed_uint_kind(other, absolute, params_by_unit)
    return False


def recover_packed_scalar_storage(source: str) -> Stage:
    """Retype ``bytes`` slots whose single writer packs one uint scalar.

    ``abi.encodePacked(uint256)`` always emits 32 bytes, so guards keyed on
    ``X.length`` read the constant 32 instead of the stored value. When a
    slot-commented ``bytes`` declaration has exactly one writer of the form
    ``X = abi.encodePacked(<bare uint param>)`` and every other occurrence is
    a comparison operand of ``X.length`` or a direct ``abi.encodePacked``
    argument, the slot is treated as a mis-typed scalar: retype it, store the
    scalar directly, and drop the ``.length`` reads. Any unclassified
    occurrence abstains the whole variable - the pass never guesses past its
    evidence. Recovery heuristic, not a source-level proof: a contract may
    legitimately inspect a packed array's length.
    """
    edits: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    masked = _mask_strings_and_comments(source, 0, len(source))
    try:
        parsed = parse_contract(source, None)
    except ParseError as error:
        return Stage(
            "packed-scalars",
            "packed scalar storage recovery",
            source,
            edits,
            [_finding("packed-scalar-storage", "<source>", f"source does not parse: {error}")],
        )
    params_by_unit = [
        (
            unit.start,
            unit.end,
            {name: kind for kind, name in _header_params(_mask_strings_and_comments(unit.header, 0, len(unit.header)))},
        )
        for unit in parsed.functions
    ]
    packed_spans: list[tuple[int, int, list[tuple[int, int]]]] = []
    for call in re.finditer(r"\babi\s*\.\s*encodePacked\s*\(", masked):
        close = _packed_close(masked, call.end() - 1)
        if close is None:
            continue
        args = _split_top_level(masked, call.end() - 1) or []
        cursor, spans = call.end(), []
        for arg in args:
            offset = masked.find(arg, cursor, close)
            if offset >= 0:
                spans.append((offset, offset + len(arg)))
                cursor = offset + len(arg)
        packed_spans.append((call.start(), close, spans))

    def _decl_ok(match: re.Match) -> str | None:
        slot = _SLOT_RE.search(source[match.start() : match.end()])
        if not slot:
            return None
        name = match.group(1)
        others = [
            other
            for other in re.finditer(rf"(?m)^[ \t]*bytes[ \t]+{re.escape(name)}[ \t]*;", masked)
            if other.start() != match.start()
        ]
        if others:
            return None
        for other_name, other_match in _all_slot_decls(masked, source).items():
            if other_name != name and other_match[1] == slot.group(1):
                return None
        return name

    declarations: dict[str, tuple[re.Match, str]] = {}
    for match in re.finditer(r"(?m)^[ \t]*bytes[ \t]+([A-Za-z_]\w*)[ \t]*;(?P<rest>[^\n]*)$", masked):
        name = _decl_ok(match)
        if name:
            declarations[name] = (match, _SLOT_RE.search(source[match.start() : match.end()]).group(1))

    replacement = source
    planned: list[tuple[str, str, str, list[tuple[int, int, str]], int]] = []
    for name, (decl, slot) in sorted(declarations.items()):
        writers = list(re.finditer(rf"\b{re.escape(name)}\b\s*=(?!=)\s*abi\s*\.\s*encodePacked\s*\(", masked))
        if len(writers) != 1:
            findings.append(_finding("packed-scalar-storage", name, f"{len(writers)} packed writer(s), need exactly 1"))
            continue
        writer = writers[0]
        close = _packed_close(masked, writer.end() - 1)
        if close is None or not masked[close:].lstrip().startswith(";"):
            findings.append(_finding("packed-scalar-storage", name, "writer statement shape"))
            continue
        args = _split_top_level(masked, writer.end() - 1) or []
        if len(args) != 1:
            findings.append(_finding("packed-scalar-storage", name, f"{len(args)} packed argument(s), need exactly 1"))
            continue
        arg = args[0].strip()
        if not re.fullmatch(r"[A-Za-z_]\w*", arg):
            findings.append(_finding("packed-scalar-storage", name, f"packed argument {arg!r} is not a bare identifier"))
            continue
        if not _packed_uint_kind(arg, writer.start(), params_by_unit):
            findings.append(_finding("packed-scalar-storage", name, f"writer input {arg!r} is not a uint parameter"))
            continue
        if not re.search(rf"\b{re.escape(name)}\s*\.\s*length\b", masked):
            findings.append(_finding("packed-scalar-storage", name, "no length reader to recover"))
            continue

        writer_span = (writer.start(), close)
        decl_span = (decl.start(), decl.end())
        plan: list[tuple[int, int, str]] = []
        readers = 0
        ok = True
        for occurrence in re.finditer(rf"\b{re.escape(name)}\b", masked):
            start, end = occurrence.span()
            if decl_span[0] <= start < decl_span[1] or writer_span[0] <= start < writer_span[1]:
                continue
            dot = re.match(r"\s*\.\s*length\b", masked[end:])
            if dot:
                if _packed_length_read(masked, name, start, occurrence.end(), params_by_unit):
                    plan.append((start, end + dot.end(), name))
                    readers += 1
                    continue
                findings.append(_finding("packed-scalar-storage", name, "length read is not a guarded comparison"))
                ok = False
                break
            packed_arg = any(
                call_start <= start < call_end
                and any(masked[a:b].strip() == name for a, b in spans)
                for call_start, call_end, spans in packed_spans
            )
            if not packed_arg:
                findings.append(_finding("packed-scalar-storage", name, f"unclassified occurrence at offset {start}"))
                ok = False
                break
        if not ok:
            continue

        decl_bytes = re.search(r"\bbytes\b", masked[decl.start() : decl.end()])
        plan.append((decl.start() + decl_bytes.start(), decl.start() + decl_bytes.end(), "uint256"))
        writer_rhs = re.search(r"abi\s*\.\s*encodePacked", masked[writer.start() : writer.end()])
        plan.append((writer.start() + writer_rhs.start(), close, arg))
        planned.append((name, slot, arg, plan, readers))

    # All spans are computed against the untouched source; splice once, in
    # descending order, after verifying the variables never overlap.
    merged = sorted((span for _, _, _, plan, _ in planned for span in plan), key=lambda item: item[0])
    for left, right in zip(merged, merged[1:]):
        if right[0] < left[1]:
            findings.append(_finding("packed-scalar-storage", "<overlap>", "edits overlap; abstaining"))
            merged = []
            planned = []
            break
    if merged:
        for start, end, text in sorted(merged, key=lambda item: item[0], reverse=True):
            replacement = replacement[:start] + text + replacement[end:]
    for name, slot, arg, _, readers in planned:
        edits.append(
            _record(
                "packed-scalar-storage",
                f"{name}: bytes -> uint256 (slot {slot})",
                f"single writer '{name} = abi.encodePacked({arg})'; {readers} length-read(s) unwrapped; "
                "assumption: packed single scalar, dynamic length semantics not intended",
            )
        )

    return Stage("packed-scalars", "packed scalar storage recovery", replacement, edits, findings)


def relax_truthiness_requires(source: str) -> Stage:
    """Stage: rewrite ``require(<addr expr>...)`` truthiness tests into explicit compares.

    The decompiler renders ``x != 0`` style guards as ``require(x, ...)`` when the
    truthiness context is lost; Solidity has no implicit address/uint-to-bool
    conversion. Only unambiguous shapes are rewritten: ``msg.sender`` compares
    against ``address(0)``, declared uint/int locals against ``0``; everything
    else is an abstention.
    """
    masked = _mask_strings_and_comments(source, 0, len(source))
    edits: list[dict[str, Any]] = []
    pieces: list[str] = []
    last = 0
    declared_uint = set(re.findall(r"\buint\d*\s+(var_[a-z]+)\b", masked))
    parsed = parse_contract(source, None)

    def param_kind(offset: int, name: str) -> str | None:
        """(address|uint|int)-ness of `name` in the function enclosing `offset`."""
        for unit in parsed.functions:
            if unit.start <= offset < unit.end:
                for type_text, param in _header_params(
                    _mask_strings_and_comments(unit.header, 0, len(unit.header))
                ):
                    if param == name:
                        if type_text.startswith("address"):
                            return "address"
                        if re.fullmatch(r"u?int\d*", type_text):
                            return "uint"
                return None
        return None

    # one combined pass over both truthiness shapes (require(...expr..., and
    # if(...expr...)): separate passes would emit overlapping replacements.
    # Nonzero int constants 0/1 fold to false/true; address/uint-typed
    # expressions get explicit compares; everything else abstains.
    for match in re.finditer(
        r"(?P<kw>\brequire\b|\bif\b)\s*\(\s*"
        r"(?P<expr>[A-Za-z_][\w.]*|0x[0-9a-fA-F]+|\d+)\s*"
        r"(?P<comma>,|\))",
        masked,
    ):
        keyword = match.group("kw")
        expr = match.group("expr")
        comma = match.group("comma") == ","
        if re.fullmatch(r"0x[0-9a-fA-F]+|\d+", expr) and keyword == "if":
            value = int(expr, 0)
            if value == 0:
                cmp_ = "false"
            elif value == 1:
                cmp_ = "true"
            else:
                continue  # keep larger constants visible rather than folding them
        elif expr == "msg.sender":
            cmp_ = "msg.sender != address(0)"
        elif re.fullmatch(r"var_[a-z]+", expr) and expr in declared_uint:
            cmp_ = f"{expr} != 0"
        elif re.fullmatch(r"[A-Za-z_]\w*", expr):
            kind = param_kind(match.start(), expr)
            if kind == "address":
                cmp_ = f"{expr} != address(0)"
            elif kind == "uint":
                cmp_ = f"{expr} != 0"
            else:
                continue
        else:
            continue
        start, end = match.span()
        replacement = f"{keyword}({cmp_}{',' if comma else ')'}"
        pieces.append(source[last:start])
        pieces.append(replacement)
        last = end
        edits.append(
            _record(
                "truthiness-guard",
                f"{keyword}({expr}...) -> {keyword}({cmp_}...)",
                "truthiness condition without implicit bool conversion",
            )
        )
    if not pieces:
        return Stage("truthiness", "truthiness require guards", source, edits)
    pieces.append(source[last:])
    return Stage("truthiness", "truthiness require guards", "".join(pieces), edits)


def repair_fallback_shape(source: str) -> Stage:
    """Stage: make decompiled fallback dispatch compile.

    Two shapes, both accepted only where unambiguous: the selector self-check
    ``<int const> == msg.data[0] >> 0xe0`` (a bytes/int compare the decompiler
    emits for single-function dispatchers) becomes a words-wide selector compare;
    a value-returning fallback gains ``returns (bytes memory)``. For static
    arguments abi.encodePacked output equals abi.encode output, so the packed
    return is kept verbatim. The contract parser does not emit fallback units,
    so spans are located here directly.
    """
    edits: list[dict[str, Any]] = []
    pieces: list[str] = []
    last = 0
    for match in re.finditer(r"fallback\(\)\s*external\s*payable", source):
        body_open = source.find("{", match.end())
        depth = 0
        end = None
        for i in range(body_open, len(source)):
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            continue
        text = source[match.start() : end]
        new_text, n_sel = re.subn(
            r"require\((0x[0-9a-fA-F]+) == msg\.data\[0\] >> 0xe0\)",
            r"require(uint32(bytes4(msg.data[0:4])) == \1)",
            text,
        )
        added_returns = "returns" not in match.group(0) and bool(
            re.search(r"return\s+abi\.encodePacked\(", new_text)
        )
        if added_returns:
            # solc 5570: a value-returning fallback must take the calldata argument
            new_text = new_text.replace(
                match.group(0),
                "fallback(bytes calldata) external payable returns (bytes memory)",
                1,
            )
        if new_text == text:
            continue
        pieces.append(source[last : match.start()])
        pieces.append(new_text)
        last = end
        if n_sel:
            edits.append(_record("fallback-selector-compare", "bytes/int compare -> words selector compare", "single-dispatch fallback selector check"))
        if added_returns:
            edits.append(_record("fallback-returns", "fallback gains returns (bytes memory)", "value-returning fallback"))
    if not pieces:
        return Stage("fallback-shape", "fallback dispatch shape", source, edits)
    pieces.append(source[last:])
    return Stage("fallback-shape", "fallback dispatch shape", "".join(pieces), edits)


def _all_slot_decls(masked: str, source: str | None = None) -> dict[str, tuple[str, str]]:
    """Every slot-commented state declaration as name -> (type, slot).

    Structure comes from the masked text; the slot comment itself lives in
    a comment, so it is read from the raw source at the same offsets.
    """
    raw = source if source is not None else masked
    found: dict[str, tuple[str, str]] = {}
    for match in re.finditer(
        r"(?m)^[ \t]*(?P<type>[A-Za-z_][\w\[\]]*)[ \t]+(?P<name>[A-Za-z_]\w*)[ \t]*;[^\n]*$", masked
    ):
        slot = _SLOT_RE.search(raw[match.start() : match.end()])
        if slot:
            found[match.group("name")] = (match.group("type"), slot.group(1))
    return found


PREPARE_STAGES = (
    normalize_placeholders,
    declare_missing_symbols,
    split_selfref_initializers,
    declare_undefined_vars,
    align_function_mutability,
    align_arities,
    unify_storage_views,
    recover_packed_scalar_storage,
    relax_truthiness_requires,
    repair_fallback_shape,
)


def prepare_stages(source: str, transforms: tuple | None = None) -> list[Stage]:
    """Run every deterministic tier; returns the cumulative stage ladder.

    `transforms` subset override exists for ablation runs; production callers use
    the full default ladder.
    """
    stages: list[Stage] = []
    current = source
    for transform in transforms if transforms is not None else PREPARE_STAGES:
        try:
            stage = transform(current)
        except ParseError as error:
            raise PreparationError(f"source does not parse before {transform.__name__}: {error}") from error
        stages.append(stage)
        current = stage.source
    return stages


def build_metrics(source: str, stages: list[Stage], final: dict[str, Any] | None) -> dict[str, Any]:
    edits = [edit for stage in stages for edit in stage.edits]
    findings = [item for stage in stages for item in stage.findings]
    candidate = stages[-1].source if stages else source
    return {
        "schema_version": 1,
        "tool": "prepare_candidate",
        "llm_calls": 0,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate.encode("utf-8")).hexdigest(),
        "edited": candidate != source,
        "edit_count": len(edits),
        "finding_count": len(findings),
        "edits": edits,
        "findings": findings,
        "stages": [
            {"stage": stage.name, "description": stage.description, "edits": len(stage.edits)}
            for stage in stages
        ],
        "final_compiled": None if final is None else bool(final.get("ok")),
        "final_compile": final,
    }


def run(args: argparse.Namespace) -> int:
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise PreparationError(f"output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text(encoding="utf-8")
    spec = json.loads(args.spec.read_text(encoding="utf-8")) if args.spec else {}
    contract = spec.get("contract") or args.contract
    solc_version = spec.get("solc_version") or args.solc
    if not solc_version:
        raise PreparationError("--spec must provide solc_version, or pass --solc")

    try:
        stages = prepare_stages(source)
    except ParseError as error:
        raise PreparationError(f"input source does not parse: {error}") from error
    candidate = stages[-1].source

    if not contract:
        try:
            contract = parse_contract(candidate, None).contract_name
        except ParseError as error:
            raise PreparationError(
                f"cannot infer contract name; pass --contract or --spec ({error})"
            ) from error

    tier_reports: list[dict[str, Any]] = []
    final_record: dict[str, Any] | None = None
    for index, stage in enumerate(stages, start=1):
        record = rb.compile_candidate(
            stage.source,
            solc_version,
            args.output_dir / "work" / f"tier{index}-{stage.name}",
            f"tier{index}-{stage.name}",
            contract,
        )
        summary = {
            "stage": stage.name,
            "ok": bool(record.get("ok")),
            "returncode": record.get("returncode"),
        }
        tier_reports.append(summary)
        print(f"tier {index} ({stage.name}): compiled={summary['ok']}")
        final_record = record

    metrics = build_metrics(source, stages, final_record)
    metrics["tier_compiles"] = tier_reports
    (args.output_dir / "prepared.sol").write_text(candidate, encoding="utf-8")
    (args.output_dir / "prep-evidence.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    if metrics["final_compiled"]:
        print(f"prepared source compiles: {args.output_dir / 'prepared.sol'}")
        return 0
    print("prepared source still does not compile; see prep-evidence.json", file=sys.stderr)
    return 2


def build_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--spec", type=Path, default=None)
    parser.add_argument("--contract", default=None)
    parser.add_argument("--solc", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = build_args(argv)
    try:
        return run(args)
    except PreparationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
