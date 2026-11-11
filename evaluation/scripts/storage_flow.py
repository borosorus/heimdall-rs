#!/usr/bin/env python3
"""Typed storage-flow evidence map (deterministic, structure-only).

Correlates decompiled function stubs with slot-annotated storage declarations by
TYPE UNIFICATION alone - never by fixture, name similarity, or reference knowledge:

  a function whose declared parameter types and (missing) return match a mapping's
  key chain and value type is a storage getter candidate; the mapping's slot
  comment anchors the storage identity.

Evidence classes recorded per correlation:
  unique    exactly one storage declaration unifies with the signature
  ambiguous several do (abstain - recorded, never guessed)
  none      no candidate (abstain)

The map is consumed by the storage-getter synthesis stage and exported as
evidence JSON; the map itself asserts nothing about behavior - the harness does.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

INVESTIGATOR = ROOT / "evaluation" / "scripts" / "run_investigator"


def _load_investigator():
    spec = importlib.util.spec_from_file_location("storage_flow_inv", str(INVESTIGATOR) + ".py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["storage_flow_inv"] = module
    spec.loader.exec_module(module)
    return module


investigator = _load_investigator()

MAPPING_RE = re.compile(r"^(?P<decl>mapping\s*\((?P<inner>.*)\))(?P<tail>.*)$")
PUBLIC_RE = re.compile(r"\bpublic\b")
SLOT_RE = re.compile(r"//\s*storage slot:\s*(0x[0-9a-fA-F]+)")


@dataclass
class StorageDecl:
    name: str
    type_text: str
    slot: str | None
    public: bool

    def key_chain(self) -> list[str] | None:
        """Flattened key types of the mapping chain, outermost first; None if not a mapping."""
        inner = self._mapping_inner()
        if inner is None:
            return None
        keys, _value = _flatten_mapping(inner)
        return keys

    def value_type(self) -> str | None:
        """Innermost value type: the type indexed by the full key chain."""
        inner = self._mapping_inner()
        if inner is None:
            return None
        _keys, value = _flatten_mapping(inner)
        return value

    def _mapping_inner(self) -> str | None:
        match = MAPPING_RE.match(self.type_text.strip())
        return match.group("inner").strip() if match else None

    def nesting_depth(self) -> int:
        keys = self.key_chain()
        return len(keys) if keys else 0


def _flatten_mapping(inner: str) -> tuple[list[str], str]:
    """``address => mapping(address => uint256)`` -> ``([address, address], uint256)``."""
    split = _top_level_arrow(inner)
    if split is None:
        return [], inner.strip()
    key = inner[:split].strip()
    rest = inner[split + 2 :].strip()
    nested = MAPPING_RE.match(rest)
    if nested:
        nested_keys, value = _flatten_mapping(nested.group("inner").strip())
        return [key, *nested_keys], value
    return [key], rest


def _top_level_arrow(text: str) -> int | None:
    """Index of the first ``=>`` at parenthesis/bracket depth zero, else None."""
    depth = 0
    for i in range(len(text) - 1):
        ch = text[i]
        if ch in "(<":
            depth += 1
        elif ch in ")>":
            depth -= 1
        elif depth == 0 and text[i : i + 2] == "=>":
            return i
    return None


@dataclass
class GetterCandidate:
    function: str
    params: list[str]
    param_names: list[str]
    storage: str
    key_chain: list[str]
    value_type: str
    slot: str | None
    evidence: str  # exact | hinted
    start: int  # unit span in the analyzed source, for consumers
    end: int
    header_len: int


@dataclass
class StorageFlow:
    declarations: list[StorageDecl] = field(default_factory=list)
    correlations: list[GetterCandidate] = field(default_factory=list)
    abstentions: list[dict] = field(default_factory=list)


def parse_storage_declarations(source: str) -> list[StorageDecl]:
    """Contract-level state-variable declarations with their slot comments.

    Line-structured scan, no cross-field regex: head token, then a
    paren-balanced span for mappings (they nest), then modifiers, name and an
    optional initializer, anchored at the ';'. Matching runs on the
    comment-masked text; the mask is length-preserving, so the same offsets
    address the real source - the slot comment is read from the real line
    because the mask blanks comments.
    """
    masked = _mask(source)
    decls = []
    for line_match in re.finditer(r"(?m)^[ \t]*(?P<head>[A-Za-z_][\w]*)[ \t]*(?P<rest>[^;\n]*);", masked):
        head = line_match.group("head")
        rest = line_match.group("rest") or ""
        if head == "mapping":
            paren = rest.find("(")
            if paren < 0:
                continue
            abs_open = line_match.start("rest") + paren
            depth = 0
            abs_close = None
            for i in range(abs_open, len(masked)):
                if masked[i] == "(":
                    depth += 1
                elif masked[i] == ")":
                    depth -= 1
                    if depth == 0:
                        abs_close = i + 1
                        break
            if abs_close is None:
                continue
            type_text = re.sub(r"[ \t]+", " ", masked[line_match.start() : abs_close]).strip()
            after = masked[abs_close : line_match.end()]
        elif re.fullmatch(r"(?:uint\d+|int\d+|address|bool|bytes\d*|string)(?:\[\d*\])*", head):
            array_suffix = ""
            array_match = re.match(r"^[ \t]*(\[\d*\])", rest)
            if array_match:
                array_suffix = array_match.group(1)
            type_text = head + array_suffix
            after = masked[line_match.end("head") + len(array_suffix) : line_match.end()]
        else:
            continue  # not a state-variable type head (e.g. 'function', 'event')

        # the name is the last non-keyword identifier before ';' or '='
        identifiers = re.findall(r"([A-Za-z_][\w]*)", after.split("=")[0])
        keywords = {"public", "private", "internal", "constant", "immutable"}
        names = [x for x in identifiers if x not in keywords]
        if not names:
            continue
        name = names[-1]
        line_start = source.rfind("\n", 0, line_match.start()) + 1
        line_end = source.find("\n", line_match.end())
        real_line = source[line_start : line_end if line_end >= 0 else len(source)]
        slot_match = SLOT_RE.search(real_line)
        decls.append(
            StorageDecl(
                name=name,
                type_text=type_text,
                slot=slot_match.group(1).lower() if slot_match else None,
                public=bool(PUBLIC_RE.search(after)) or bool(PUBLIC_RE.search(head)),
            )
        )
    return decls


def _mask(source: str) -> str:
    if hasattr(investigator, "_mask_strings_and_comments"):
        return investigator._mask_strings_and_comments(source, 0, len(source))
    raise RuntimeError("mask helper unavailable")


def canonical_type(type_text: str) -> int | str:
    """Canonical key for structural unification.

    Integer widths collapse to their signedness class: the decompiler's width
    evidence is not reliable at stub stage, and storage keys are compared
    structurally (``uintN``/``intN`` unify within their class).
    """
    text = re.sub(r"\s+", "", type_text)
    text = re.sub(r"\buint\d+\b", "uint", text)
    return re.sub(r"\bint\d+\b", "int", text)


def build_storage_flow(source: str) -> StorageFlow:
    flow = StorageFlow()
    flow.declarations = parse_storage_declarations(source)
    parsed = investigator.parse_contract(source, None)
    mapping_decls = [d for d in flow.declarations if d.nesting_depth() > 0]

    for unit in parsed.functions:
        params = _function_params(source, unit)
        if not params:
            continue
        param_types = [canonical_type(t) for t, _name in params]
        hints = _param_type_hints(unit)  # name -> [types], decompiler evidence
        returns = _declared_returns(source, unit)
        body_masked = _mask(source[unit.start : unit.end])[len(unit.header) :]
        if re.search(r"\breturn\b", body_masked):
            continue  # not a stub: a body with returns carries its own evidence

        ret_canon = canonical_type(returns) if returns else None
        matches = []
        for decl in mapping_decls:
            keys = [canonical_type(k) for k in decl.key_chain()]
            if len(keys) != len(param_types):
                continue
            value = canonical_type(decl.value_type() or "")
            if ret_canon is not None and ret_canon != value:
                continue
            exact = True
            hinted = True
            for (_type_text, name), param_canon, key_canon in zip(params, param_types, keys):
                if param_canon == key_canon:
                    continue
                exact = False  # any mismatch demotes the match from exact
                hinted_types = {canonical_type(t) for t in hints.get(name, [])}
                if param_canon in hinted_types or key_canon in hinted_types:
                    continue
                # the decompiler's generic uintN default is weak evidence, and it
                # only bridges keys the synthesis stage can convert (uint->address
                # via uint160); other key classes need their own evidence
                if re.fullmatch(r"uint\d*", param_canon) and key_canon == "address":
                    continue
                hinted = False
            if exact or hinted:
                matches.append((decl, "exact" if exact else "hinted"))
        if len(matches) == 1:
            decl, tier = matches[0]
            flow.correlations.append(
                GetterCandidate(
                    function=unit.name,
                    params=param_types,
                    param_names=[name for _t, name in params],
                    storage=decl.name,
                    key_chain=decl.key_chain(),
                    value_type=decl.value_type() or "",
                    slot=decl.slot,
                    evidence=tier,
                    start=unit.start,
                    end=unit.end,
                    header_len=len(unit.header),
                )
            )
        elif len(matches) > 1:
            flow.abstentions.append(
                {
                    "function": unit.name,
                    "reason": "ambiguous",
                    "tiers": sorted(t for _d, t in matches),
                    "candidates": sorted(d.name for d, _t in matches),
                }
            )
    return flow


def _param_type_hints(unit) -> dict[str, list[str]]:
    """``/// @param name ["t1", "t2"]`` candidate lists from the unit's own provenance."""
    hints: dict[str, list[str]] = {}
    for match in re.finditer(r"///\s*@param\s+([A-Za-z_]\w*)\s+\[([^\]]*)\]", unit.text):
        types = re.findall(r"[A-Za-z_][\w\[\]]*", match.group(2))
        if types:
            hints[match.group(1)] = types
    return hints


def _function_params(source: str, unit):
    masked_unit = _mask(source[unit.start : unit.end])
    header = masked_unit[: len(unit.header)]
    open_match = re.search(r"\bfunction\s+[A-Za-z_]\w*\s*\(", header)
    if not open_match:
        return []
    depth = 1
    index = open_match.end()
    while index < len(header) and depth > 0:
        if header[index] == "(":
            depth += 1
        elif header[index] == ")":
            depth -= 1
        index += 1
    inner = header[open_match.end() : index - 1]
    params = []
    for part in inner.split(","):
        tokens = par.split() if (par := part.strip()) else []
        if not tokens:
            continue
        if tokens[0] in ("memory", "calldata", "storage"):
            tokens = tokens[1:]
        name = tokens[-1] if len(tokens) > 1 else ""
        type_text = " ".join(tokens[:-1]) if len(tokens) > 1 else tokens[0]
        params.append((type_text, name))
    return params


def _declared_returns(source: str, unit) -> str | None:
    masked_unit = _mask(source[unit.start : unit.end])
    header = masked_unit[: len(unit.header)]
    match = re.search(r"\breturns\s*\(([^)]*)\)", header)
    if not match:
        return None
    tokens = match.group(1).strip().split()
    if not tokens:
        return None
    if len(tokens) == 1:
        return tokens[0]
    return " ".join(tokens[:-1])


def evidence_record(flow: StorageFlow) -> dict:
    return {
        "schema_version": 1,
        "method": "structural type unification of stub signatures against slot-annotated storage",
        "declarations": [
            {"name": d.name, "type": d.type_text, "slot": d.slot, "public": d.public}
            for d in flow.declarations
        ],
        "correlations": [
            {
                "function": c.function,
                "params": c.params,
                "storage": c.storage,
                "key_chain": c.key_chain,
                "value_type": c.value_type,
                "slot": c.slot,
                "evidence": c.evidence,
            }
            for c in flow.correlations
        ],
        "abstentions": flow.abstentions,
    }
