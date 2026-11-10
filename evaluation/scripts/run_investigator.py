#!/usr/bin/env python3
"""Evaluation-only divide-and-conquer investigator for decompiled Solidity.

The input is an already-compilable whole-contract LLM candidate. The script splits the target
contract into complete function units, groups related units deterministically, runs a bounded
multi-step investigator against bytecode-derived observations, and merges complete rewrites back
into the candidate source.

Reference Solidity, reference ABI names, source diffs and withheld evaluation probes are never
sent to the model. The deterministic oracle exposes only opaque entrypoint IDs and raw observations.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
CONTEXT_PATH = ROOT / "evaluation" / "prompts" / "investigator_context.txt"
ROUND1_PATH = ROOT / "evaluation" / "prompts" / "investigator_round1.txt"
ROUND2_PATH = ROOT / "evaluation" / "prompts" / "investigator_round2.txt"
SYNTHESIS_PATH = ROOT / "evaluation" / "prompts" / "investigator_synthesis.txt"
MERGE_REPAIR_PATH = ROOT / "evaluation" / "prompts" / "investigator_merge_repair.txt"


def _load_run_behavior():
    path = SCRIPT_DIR / "run_behavior.py"
    spec = importlib.util.spec_from_file_location("run_behavior_for_investigator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load run_behavior.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rb = _load_run_behavior()

KEYWORDS = {
    "abi",
    "address",
    "assembly",
    "bool",
    "bytes",
    "calldata",
    "checked",
    "constructor",
    "contract",
    "delete",
    "else",
    "emit",
    "enum",
    "error",
    "event",
    "external",
    "false",
    "for",
    "function",
    "if",
    "int",
    "internal",
    "keccak256",
    "let",
    "library",
    "mapping",
    "memory",
    "modifier",
    "new",
    "payable",
    "private",
    "public",
    "pure",
    "receive",
    "require",
    "return",
    "returns",
    "revert",
    "storage",
    "string",
    "struct",
    "super",
    "this",
    "true",
    "type",
    "uint",
    "uint256",
    "unchecked",
    "using",
    "view",
    "while",
}
BUILTINS = {
    "assert",
    "decode",
    "encode",
    "encodePacked",
    "encodeWithSelector",
    "encodeWithSignature",
    "gasleft",
    "keccak256",
    "msg",
    "require",
    "revert",
    "sha256",
    "block",
    "tx",
}


class InvestigatorError(RuntimeError):
    pass


class ParseError(InvestigatorError):
    pass


@dataclass
class SourceUnit:
    kind: str
    opaque_id: str
    name: str
    header: str
    start: int
    end: int
    text: str
    dependencies: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class ParsedSource:
    source: str
    contract_name: str
    body_start: int
    body_end: int
    units: list[SourceUnit]

    @property
    def declarations(self) -> list[SourceUnit]:
        return [unit for unit in self.units if unit.kind == "declaration"]

    @property
    def functions(self) -> list[SourceUnit]:
        return [unit for unit in self.units if unit.kind == "function"]

    @property
    def frozen_units(self) -> list[SourceUnit]:
        return [unit for unit in self.units if unit.kind != "function"]

    @property
    def declarations_text(self) -> str:
        return "".join(unit.text for unit in self.declarations)


@dataclass
class Cluster:
    cluster_id: str
    functions: list[SourceUnit]
    context_functions: list[SourceUnit]


def _skip_string(source: str, index: int) -> int:
    quote = source[index]
    index += 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == quote:
            return index + 1
        index += 1
    raise ParseError("unterminated string literal")


def _skip_comment(source: str, index: int) -> int:
    if source.startswith("//", index):
        end = source.find("\n", index + 2)
        return len(source) if end == -1 else end + 1
    if source.startswith("/*", index):
        end = source.find("*/", index + 2)
        if end == -1:
            raise ParseError("unterminated block comment")
        return end + 2
    return index


def _find_next_structural(source: str, index: int, end: int) -> tuple[str, int]:
    while index < end:
        char = source[index]
        if char.isspace():
            index += 1
        elif source.startswith("//", index) or source.startswith("/*", index):
            index = _skip_comment(source, index)
        elif char in "\"'":
            index = _skip_string(source, index)
        elif char == ";":
            return "declaration", index + 1
        elif char == "{":
            close = _find_matching_brace(source, index)
            return "block", close + 1
        elif char == "}":
            return "end", index
        else:
            index += 1
    return "end", end


def _find_matching_brace(source: str, open_index: int) -> int:
    if source[open_index] != "{":
        raise ParseError("expected opening brace")
    depth = 1
    index = open_index + 1
    while index < len(source):
        char = source[index]
        if source.startswith("//", index) or source.startswith("/*", index):
            index = _skip_comment(source, index)
        elif char in "\"'":
            index = _skip_string(source, index)
        elif char == "{":
            depth += 1
            index += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
            index += 1
        else:
            index += 1
    raise ParseError("unmatched closing brace")


def _find_next_char(source: str, index: int, target: str, end: int) -> int:
    while index < end:
        char = source[index]
        if source.startswith("//", index) or source.startswith("/*", index):
            index = _skip_comment(source, index)
        elif char in "\"'":
            index = _skip_string(source, index)
        elif char == target:
            return index
        else:
            index += 1
    return -1


def _mask_strings_and_comments(source: str, start: int, end: int) -> str:
    chars = list(source[start:end])
    index = start
    while index < end:
        char = source[index]
        if source.startswith("//", index) or source.startswith("/*", index):
            stop = _skip_comment(source, index)
            for position in range(index, min(stop, end)):
                if chars[position - start] != "\n":
                    chars[position - start] = " "
            index = stop
        elif char in "\"'":
            stop = _skip_string(source, index)
            for position in range(index, min(stop, end)):
                chars[position - start] = " "
            index = stop
        else:
            index += 1
    return "".join(chars)


def _unit_kind(header: str) -> tuple[str, str]:
    masked = _mask_strings_and_comments(header, 0, len(header))
    if re.search(r"\bfunction\b", masked):
        match = re.search(r"\bfunction\s+([A-Za-z_]\w*)\s*\(", masked)
        if not match:
            raise ParseError("function header has no function name")
        return "function", match.group(1)
    if re.search(r"\bconstructor\b", masked):
        return "constructor", "constructor"
    if re.search(r"\bfallback\b", masked):
        return "fallback", "fallback"
    if re.search(r"\breceive\b", masked):
        return "receive", "receive"
    if re.search(r"\bmodifier\b", masked):
        return "modifier", "modifier"
    return "declaration", ""


def _find_contract(
    source: str, contract_name: str | None
) -> tuple[str, int, int, list[SourceUnit]]:
    candidates: list[tuple[str, int, int, list[SourceUnit]]] = []
    masked = _mask_strings_and_comments(source, 0, len(source))
    for match in re.finditer(r"\bcontract\s+([A-Za-z_]\w*)", masked):
        name = match.group(1)
        if contract_name and name != contract_name:
            continue
        brace = _find_next_char(source, match.end(), "{", len(source))
        if brace == -1:
            raise ParseError(f"contract {name} has no body")
        close = _find_matching_brace(source, brace)
        units = _parse_units(source, brace + 1, close)
        candidates.append((name, brace + 1, close, units))
    if not candidates:
        raise ParseError(f"contract {contract_name or '<auto>'} not found")
    if contract_name:
        return candidates[0]
    return max(candidates, key=lambda item: len([u for u in item[3] if u.kind == "function"]))


def _parse_units(source: str, start: int, end: int) -> list[SourceUnit]:
    units: list[SourceUnit] = []
    position = start
    function_index = 0
    while position < end:
        next_position = position
        while next_position < end and source[next_position].isspace():
            next_position += 1
        if next_position >= end:
            break
        position = next_position
        structural, stop = _find_next_structural(source, position, end)
        if structural == "end":
            break
        text = source[position:stop]
        if structural == "declaration":
            header = text.strip()
            kind, name = _unit_kind(header)
            if kind == "declaration":
                units.append(
                    SourceUnit(
                        kind="declaration",
                        opaque_id=f"decl_{len(units) + 1}",
                        name=name,
                        header=header,
                        start=position,
                        end=stop,
                        text=text,
                    )
                )
            else:
                raise ParseError("callable unit ended without a body")
        else:
            brace = _find_next_char(source, position, "{", stop)
            if brace == -1:
                raise ParseError("block unit has no opening brace")
            header = source[position:brace].strip()
            kind, name = _unit_kind(header)
            if kind == "function":
                opaque_id = f"fn_{function_index + 1}"
                function_index += 1
            else:
                opaque_id = f"{kind}_{len(units) + 1}"
            units.append(
                SourceUnit(
                    kind=kind,
                    opaque_id=opaque_id,
                    name=name,
                    header=header,
                    start=position,
                    end=stop,
                    text=text,
                )
            )
        position = stop
    return units


def _declared_storage(parsed: ParsedSource) -> set[str]:
    names: set[str] = set()
    for unit in parsed.declarations:
        header = unit.header
        if re.match(r"^(event|error|using|struct|enum|type|modifier|library)\b", header):
            continue
        match = re.search(r"([A-Za-z_]\w*)\s*(?:=|;)\s*$", header)
        if match:
            names.add(match.group(1))
    return names


def _contract_symbols(parsed: ParsedSource) -> tuple[set[str], set[str], set[str]]:
    storage = _declared_storage(parsed)
    events = set(re.findall(r"\bevent\s+([A-Za-z_]\w*)", parsed.source))
    errors = set(re.findall(r"\berror\s+([A-Za-z_]\w*)", parsed.source))
    return storage, events, errors


def _dependencies(
    parsed: ParsedSource, unit: SourceUnit, function_names: set[str]
) -> dict[str, list[str]]:
    storage, events, errors = _contract_symbols(parsed)
    masked = _mask_strings_and_comments(parsed.source, unit.start, unit.end)
    found_storage = sorted(name for name in storage if re.search(rf"\b{re.escape(name)}\b", masked))
    found_events = sorted(set(re.findall(r"\bemit\s+([A-Za-z_]\w*)", masked)))
    found_errors = sorted(set(re.findall(r"\brevert\s+([A-Za-z_]\w*)", masked)))
    calls = set()
    for match in re.finditer(r"\b([A-Za-z_]\w*)\s*\(", masked):
        name = match.group(1)
        if name in function_names or name in BUILTINS:
            calls.add(name)
    return {
        "storage": [name for name in found_storage if name in storage],
        "events": [name for name in found_events if name in events],
        "errors": [name for name in found_errors if name in errors],
        "calls": sorted(calls),
    }


def parse_contract(source: str, contract_name: str | None = None) -> ParsedSource:
    name, body_start, body_end, units = _find_contract(source, contract_name)
    parsed = ParsedSource(source, name, body_start, body_end, units)
    function_names = {unit.name for unit in parsed.functions}
    for unit in units:
        unit.dependencies = _dependencies(parsed, unit, function_names)
    return parsed


def cluster_functions(
    parsed: ParsedSource, max_clusters: int = 6, max_functions: int = 4
) -> tuple[list[Cluster], list[SourceUnit]]:
    functions = parsed.functions
    if not functions:
        return [], []
    parent = list(range(len(functions)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    by_name = {unit.name: index for index, unit in enumerate(functions)}
    by_dependency: dict[tuple[str, str], int] = {}
    for index, unit in enumerate(functions):
        for kind, names in unit.dependencies.items():
            for name in names:
                if kind == "calls":
                    if name not in by_name:
                        continue
                    union(index, by_name[name])
                    continue
                key = (kind, name)
                if key in by_dependency:
                    union(index, by_dependency[key])
                else:
                    by_dependency[key] = index

    components: dict[int, list[int]] = {}
    for index in range(len(functions)):
        components.setdefault(find(index), []).append(index)
    chunks: list[list[int]] = []
    for component in components.values():
        ordered = sorted(component)
        for offset in range(0, len(ordered), max_functions):
            chunks.append(ordered[offset : offset + max_functions])
    chunks.sort(key=lambda chunk: (-len(chunk), chunk[0]))
    selected = chunks[:max_clusters]
    selected_ids = {index for chunk in selected for index in chunk}
    clusters: list[Cluster] = []
    for cluster_number, chunk in enumerate(selected, start=1):
        cluster_units = [functions[index] for index in chunk]
        context_names: set[str] = set()
        lookup = {unit.opaque_id: unit for unit in functions}
        for unit in cluster_units:
            for call in unit.dependencies.get("calls", []):
                if call in by_name and by_name[call] not in chunk:
                    context_names.add(call)
        context_units = [
            lookup[unit.opaque_id] for unit in functions if unit.name in context_names
        ]
        clusters.append(Cluster(f"cluster_{cluster_number}", cluster_units, context_units))
    unclustered = [functions[index] for index in range(len(functions)) if index not in selected_ids]
    # Coverage first: a leftover unit (no shared storage/events/calls with anything)
    # still needs a synthesis pass, so fold it into the least-loaded cluster,
    # deterministically by (size, cluster_id).
    for unit in list(unclustered):
        candidates = [cluster for cluster in clusters if len(cluster.functions) < max_functions]
        if not candidates:
            break
        target = min(candidates, key=lambda cluster: (len(cluster.functions), cluster.cluster_id))
        target.functions.append(unit)
        unclustered.remove(unit)
    return clusters, unclustered


_TYPE_ALIASES = {"uint": "uint256", "int": "int256", "byte": "bytes1"}


def dispatch_signature(header: str) -> tuple[str, tuple[str, ...]]:
    """Return (name, parameter types) for a function header, ignoring modifiers and returns.

    Return types and mutability are free to change in a rewrite because the evaluation binds
    entrypoints by name and parameter types only. Name or parameter changes would silently
    redirect calls, so the merge gate rejects them.
    """
    masked = _mask_strings_and_comments(header, 0, len(header))
    match = re.search(r"\bfunction\s+([A-Za-z_]\w*)\s*\(", masked)
    if not match:
        raise ParseError("function header has no function name")
    name = match.group(1)
    start = match.end()
    index = start
    depth = 1
    while index < len(masked):
        char = masked[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        index += 1
    if depth != 0:
        raise ParseError("function header has unbalanced parameters")
    # Split the masked parameter list so comments cannot contribute commas or parens.
    parts: list[str] = []
    depth = 0
    part_start = start
    for offset in range(start, index):
        char = masked[offset]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(masked[part_start:offset])
            part_start = offset + 1
    parts.append(masked[part_start:index])
    types: list[str] = []
    for part in parts:
        type_text = re.sub(r"\b(memory|calldata|storage|payable)\b", " ", part)
        type_text = re.sub(r"\s+", " ", type_text).strip()
        words = type_text.split()
        if len(words) > 1 and re.fullmatch(r"[A-Za-z_]\w*", words[-1]):
            words = words[:-1]
        type_text = " ".join(words)
        type_text = re.sub(r"\s*\[\s*", "[", type_text)
        type_text = re.sub(r"\s*\]\s*", "]", type_text)
        if not type_text:
            continue
        types.append(_TYPE_ALIASES.get(type_text, type_text))
    return name, tuple(types)


def parse_single_function(text: str) -> SourceUnit:
    stripped = text.strip()
    if not stripped:
        raise ParseError("rewrite is empty")
    masked = _mask_strings_and_comments(stripped, 0, len(stripped))
    first = len(masked) - len(masked.lstrip())
    if not re.match(r"function\b", masked[first:]):
        raise ParseError("rewrite must contain exactly one function and no leading declaration")
    brace = _find_next_char(stripped, 0, "{", len(stripped))
    if brace == -1:
        raise ParseError("rewrite has no function body")
    close = _find_matching_brace(stripped, brace)
    if stripped[close + 1 :].strip():
        raise ParseError("rewrite contains more than one unit")
    header = stripped[:brace].strip()
    kind, name = _unit_kind(header)
    if kind != "function":
        raise ParseError("rewrite must be a complete function unit")
    return SourceUnit(kind, "rewrite", name, header, 0, len(stripped), stripped)


def merge_rewrites(
    parsed: ParsedSource, rewrites: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    by_id = {unit.opaque_id: unit for unit in parsed.functions}
    replacements: list[tuple[int, int, str]] = []
    records: dict[str, Any] = {}
    for opaque_id, text in rewrites.items():
        unit = by_id.get(opaque_id)
        if unit is None:
            records[opaque_id] = {"applied": False, "error": "unknown function id"}
            continue
        try:
            rewrite = parse_single_function(text)
            original_signature = dispatch_signature(unit.header)
            rewrite_signature = dispatch_signature(rewrite.header)
        except ParseError as error:
            records[opaque_id] = {"applied": False, "error": str(error)}
            continue
        if rewrite_signature != original_signature:
            records[opaque_id] = {
                "applied": False,
                "error": "dispatch signature changed: "
                f"{original_signature[0]}({','.join(original_signature[1])}) -> "
                f"{rewrite_signature[0]}({','.join(rewrite_signature[1])})",
            }
            continue
        replacements.append((unit.start, unit.end, text))
        records[opaque_id] = {
            "applied": True,
            "old_name": unit.name,
            "new_name": rewrite.name,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    merged = parsed.source
    for start, end, text in sorted(replacements, reverse=True):
        merged = merged[:start] + text + merged[end:]
    try:
        reparsed = parse_contract(merged, parsed.contract_name)
    except ParseError as error:
        return parsed.source, {"records": records, "error": str(error), "applied": False}
    names = [unit.name for unit in reparsed.functions]
    if len(names) != len(set(names)):
        return parsed.source, {"records": records, "error": "duplicate function name", "applied": False}
    return merged, {
        "records": records,
        "error": None,
        "applied": bool(replacements),
    }


@dataclass
class Budget:
    max_calls: int = 20
    max_completion_tokens: int = 256_000
    calls: int = 0
    completion_tokens: int = 0
    prompt_chars: int = 0
    started_at: float = field(default_factory=time.time)

    def can_call(self) -> bool:
        return (
            self.calls < self.max_calls
            and self.completion_tokens < self.max_completion_tokens
        )

    def remaining_tokens(self) -> int:
        return max(0, self.max_completion_tokens - self.completion_tokens)

    def charge(self, prompt: str, usage: dict[str, Any] | None, content: str | None) -> None:
        """Charge one HTTP attempt, including empty, invalid or error responses."""
        self.calls += 1
        self.prompt_chars += len(prompt)
        completion = (usage or {}).get("completion_tokens")
        if isinstance(completion, int):
            self.completion_tokens += completion
        elif content:
            self.completion_tokens += max(1, len(content) // 4)


class ChatClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout: int,
        max_tokens: int,
        temperature: float,
        seed: int,
        response_format: str,
        output_dir: Path,
        budget: Budget,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.seed = seed
        self.response_format = response_format
        self.output_dir = output_dir
        self.budget = budget
        self.calls_dir = output_dir / "calls"
        self.calls_dir.mkdir(parents=True, exist_ok=True)

    def _request_body(
        self,
        messages: list[dict[str, str]],
        mode: str,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "seed": self.seed,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if mode == "json-schema":
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            }
        elif mode == "json-object":
            body["response_format"] = {"type": "json_object"}
        return body

    def request_json(
        self,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        label: str,
        system: str,
        max_attempts: int | None = None,
    ) -> tuple[dict[str, Any] | None, str | None, dict[str, Any] | None]:
        modes = ["json-schema", "json-object", "text"]
        if self.response_format != "auto":
            modes = [self.response_format]
        if max_attempts is not None:
            modes = modes[: max(0, max_attempts)]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        last_error = ""
        for mode in modes:
            if not self.budget.can_call():
                return None, "budget exhausted", None
            remaining_tokens = self.budget.remaining_tokens()
            if remaining_tokens <= 0:
                return None, "token budget exhausted", None
            body = self._request_body(
                messages,
                mode,
                schema_name,
                schema,
                min(self.max_tokens, remaining_tokens),
            )
            request_path = self.calls_dir / f"{label}-{mode}-request.json"
            request_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            started = time.time()
            try:
                request = urllib.request.Request(
                    self.base_url + "/chat/completions",
                    data=json.dumps(body).encode("utf-8"),
                    headers=headers,
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    response_text = response.read().decode("utf-8")
            except urllib.error.HTTPError as error:
                try:
                    detail = error.read().decode("utf-8", errors="replace")
                except (OSError, http.client.HTTPException):
                    detail = ""
                self.budget.charge(prompt, None, None)
                last_error = f"HTTP {error.code}: {detail}"
                if error.code not in (400, 422) or self.response_format != "auto":
                    return None, last_error, None
                continue
            except (OSError, http.client.HTTPException) as error:
                self.budget.charge(prompt, None, None)
                return None, str(error), None
            (self.calls_dir / f"{label}-{mode}-response.json").write_text(
                response_text + "\n", encoding="utf-8"
            )
            usage = None
            content = None
            try:
                parsed_response = json.loads(response_text)
                usage = parsed_response.get("usage")
                content = parsed_response["choices"][0]["message"].get("content")
            except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
                self.budget.charge(prompt, usage, response_text)
                last_error = f"malformed response: {error}"
                continue
            self.budget.charge(prompt, usage, content)
            if not content:
                last_error = "response had no content"
                continue
            record = {
                "mode": mode,
                "prompt": prompt,
                "content": content,
                "usage": usage,
                "latency_ms": int((time.time() - started) * 1000),
            }
            try:
                data = _extract_json(content)
            except json.JSONDecodeError as error:
                last_error = f"response was not valid JSON: {error}"
                continue
            record["parsed"] = data
            return data, None, record
        return None, last_error or "request failed", None


def _extract_json(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("no JSON object found", stripped, 0)
    value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise json.JSONDecodeError("JSON value is not an object", stripped, start)
    return value


def validate_probe_request(
    request: dict[str, Any],
    entrypoints: dict[str, dict[str, Any]],
    account_count: int,
    max_steps: int = 12,
) -> list[dict[str, Any]]:
    """Validate one probe request and return its resolved steps.

    A request is either a single call or a ``steps`` array. Steps execute in order
    from one fresh snapshot after the spec's setup, so a request can establish
    state and then observe a dependent call.
    """
    if not isinstance(request, dict):
        raise InvestigatorError("probe request must be an object")
    raw_steps = request.get("steps")
    if raw_steps is None:
        raw_steps = [request]
    if not isinstance(raw_steps, list) or not raw_steps:
        raise InvestigatorError("steps must be a nonempty list")
    if len(raw_steps) > max_steps:
        raise InvestigatorError(f"steps must contain at most {max_steps} calls")
    resolved: list[dict[str, Any]] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise InvestigatorError("each step must be an object")
        if "steps" in raw:
            raise InvestigatorError("nested steps are not supported")
        call = raw.get("call")
        if call not in entrypoints:
            raise InvestigatorError(f"unknown entrypoint {call!r}")
        if not isinstance(raw.get("send", False), bool):
            raise InvestigatorError("send must be boolean")
        caller = raw.get("caller", 0)
        if not isinstance(caller, int) or caller < 0 or caller >= account_count:
            raise InvestigatorError("caller index is out of range")
        value = raw.get("value", "0")
        try:
            value_int = int(value, 0)
        except (TypeError, ValueError) as error:
            raise InvestigatorError("value is not an integer") from error
        if value_int < 0 or value_int >= 2**256:
            raise InvestigatorError("value is out of uint256 range")
        args = raw.get("args", [])
        if not isinstance(args, list) or len(args) > 8:
            raise InvestigatorError("args must be a list of at most 8 values")
        for arg in args:
            if not isinstance(arg, str):
                raise InvestigatorError("each arg must be an integer string")
            try:
                int(arg, 0)
            except ValueError as error:
                raise InvestigatorError("arg is not an integer") from error
        tail = raw.get("args_tail")
        if tail is not None:
            if not isinstance(tail, str) or not re.fullmatch(r"0x[0-9a-fA-F]*", tail):
                raise InvestigatorError("args_tail must be a 0x-prefixed hex string")
            if len(tail) > 8192:
                raise InvestigatorError("args_tail is too large")
        resolved.append(
            {
                "entrypoint": call,
                "args": args,
                "args_tail": tail,
                "send": raw.get("send", False),
                "caller": caller,
                "value": value,
            }
        )
    return resolved


class ReferenceOracle:
    def __init__(self, spec: dict[str, Any], bindings: dict[str, Any]) -> None:
        self.spec = spec
        self.bindings = bindings
        self.entrypoints: dict[str, dict[str, Any]] = {}
        self.observations: list[dict[str, Any]] = []
        self.counter = 0
        self.anvil = rb.Anvil()
        runtime = (ROOT / spec["reference_runtime"]).read_text(encoding="utf-8").strip()
        if not runtime.startswith("0x"):
            runtime = "0x" + runtime
        self.rpc = self.anvil.rpc
        self.rpc.call("anvil_setCode", [rb.REF_ADDR, runtime])
        self.rpc.call("anvil_setBalance", [rb.REF_ADDR, "0x0"])
        self.accounts = self.rpc.call("eth_accounts")
        for index, (name, binding) in enumerate(bindings.items(), start=1):
            self.entrypoints[f"entrypoint_{index}"] = {
                "name": name,
                "binding": binding,
            }

    def close(self) -> None:
        self.anvil.stop()

    def public_entrypoints(self) -> list[dict[str, Any]]:
        return [
            {
                "opaque_id": opaque_id,
                "selector": entry["binding"]["reference_selector"],
            }
            for opaque_id, entry in self.entrypoints.items()
        ]

    def _validate_request(self, request: dict[str, Any]) -> list[dict[str, Any]]:
        return validate_probe_request(request, self.entrypoints, len(self.accounts))

    def run(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for request in requests:
            try:
                steps = self._validate_request(request)
            except InvestigatorError as error:
                results.append({"request": request, "error": str(error)})
                continue
            sequence = []
            for step in steps:
                entry = self.entrypoints[step["entrypoint"]]
                sequence.append(
                    {
                        "call": entry["name"],
                        "args": step["args"],
                        "args_tail": step["args_tail"],
                        "send": step["send"],
                        "caller": step["caller"],
                        "value": step["value"],
                    }
                )
            snapshot = self.rpc.call("evm_snapshot")
            try:
                setup = self.spec.get("setup", [])
                if setup:
                    setup_observations = rb.run_sequence(
                        self.rpc,
                        rb.REF_ADDR,
                        setup,
                        self.bindings,
                        "reference",
                        self.accounts,
                    )
                    if any(not observation.get("ok") for observation in setup_observations):
                        results.append({"request": request, "error": "setup observation failed"})
                        continue
                observations = rb.run_sequence(
                    self.rpc,
                    rb.REF_ADDR,
                    sequence,
                    self.bindings,
                    "reference",
                    self.accounts,
                )
                safe = []
                for index, observation in enumerate(observations):
                    view = rb.prompt_view(observation, False)
                    view["step"] = index
                    view["entrypoint"] = steps[index]["entrypoint"]
                    return_data = view.get("return_data") or ""
                    words = abi_words(return_data)
                    if words is not None:
                        view["return_data_words"] = words
                        view["return_data_bytes"] = len(
                            return_data.removeprefix("0x")
                        ) // 2
                    safe.append(view)
                self.counter += 1
                observation_id = f"obs_{self.counter}"
                result = {
                    "observation_id": observation_id,
                    "entrypoint": steps[0]["entrypoint"],
                    "request": request,
                    "steps": safe,
                }
                self.observations.append(result)
                results.append(result)
            except (rb.HarnessError, rb.RpcError, InvestigatorError) as error:
                results.append({"request": request, "error": str(error)})
            finally:
                self.rpc.call("evm_revert", [snapshot])
        return results


def _check_hypothesis_response(data: dict[str, Any], function_ids: set[str]) -> None:
    hypotheses = data.get("hypotheses")
    if not isinstance(hypotheses, list):
        raise ValueError("hypotheses must be a list")
    for hypothesis in hypotheses:
        if not isinstance(hypothesis, dict):
            raise ValueError("each hypothesis must be an object")
        if hypothesis.get("function") not in function_ids:
            raise ValueError("hypothesis references an unknown function id")
        confidence = hypothesis.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not isinstance(hypothesis.get("claim", ""), str):
            raise ValueError("claim must be a string")
    if not isinstance(data.get("ready_to_synthesize", False), bool):
        raise ValueError("ready_to_synthesize must be boolean")
    requests = data.get("probe_requests", [])
    if not isinstance(requests, list):
        raise ValueError("probe_requests must be a list")
    for request in requests:
        _check_probe_shape(request)
    for hypothesis in hypotheses:
        for request in hypothesis.get("probe_requests", []):
            _check_probe_shape(request)


def _check_probe_shape(request: Any) -> None:
    if not isinstance(request, dict):
        raise ValueError("each probe request must be an object")
    if "steps" in request:
        steps = request.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("probe steps must be a nonempty list")
        for step in steps:
            if not isinstance(step, dict) or "call" not in step:
                raise ValueError("each probe step must contain a call")
        return
    if "call" not in request:
        raise ValueError("each probe request must contain a call or steps")


def _check_synthesis_response(data: dict[str, Any], function_ids: set[str], evidence_ids: set[str]) -> None:
    if "functions" not in data or "claims" not in data or "unresolved" not in data:
        raise ValueError("functions, claims and unresolved are required")
    functions = data.get("functions")
    if not isinstance(functions, list):
        raise ValueError("functions must be a list")
    for function in functions:
        if not isinstance(function, dict):
            raise ValueError("each function must be an object")
        if function.get("opaque_id") not in function_ids:
            raise ValueError("synthesis references an unknown function id")
        source = function.get("source")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("function source must be nonempty")
        parse_single_function(source)
    claims = data.get("claims")
    if not isinstance(claims, list):
        raise ValueError("claims must be a list")
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("each claim must be an object")
        for evidence in claim.get("evidence", []):
            if evidence not in evidence_ids:
                raise ValueError(f"unknown evidence id {evidence!r}")
    if not isinstance(data.get("unresolved"), list):
        raise ValueError("unresolved must be a list")


def abi_words(return_data: str | None, limit: int = 16) -> list[str] | None:
    """Split raw ABI returndata into 32-byte words for model-readable layouts."""
    if not return_data:
        return None
    body = return_data[2:] if return_data.startswith("0x") else return_data
    if len(body) % 64 != 0:
        return None
    words = [f"0x{body[offset : offset + 64]}" for offset in range(0, len(body), 64)]
    return words[:limit]


def state_writes(unit_text: str, storage: set[str]) -> set[str]:
    """State variables assigned anywhere in the unit (``=``, compound, ``++``).

    The base identifier of the assignment target must be a declared state
    variable; ``==`` comparisons and plain declarations are not writes.
    """
    masked = _mask_strings_and_comments(unit_text, 0, len(unit_text))
    writes: set[str] = set()
    # The target is the identifier immediately before the operator: a member or
    # index suffix may follow, but no other token may sit between (otherwise
    # ``if (ok) supply = 1`` credits ``ok`` and ``supply + local++`` credits both).
    for match in re.finditer(
        r"\b([A-Za-z_]\w*)(?:\.[A-Za-z_]\w*|\[[^\]]*\])*\s*(?:=(?!=)|\+=|-=|\*=|/=|\|=&|&=|\^=|<<=|>>=|\+\+|--)",
        masked,
    ):
        base = re.match(r"[A-Za-z_]\w*", match.group(1)).group(0)
        if base in storage:
            writes.add(base)
    return writes


def footprint_report(seed: ParsedSource, candidate: ParsedSource) -> dict[str, dict[str, list[str]]]:
    """Per-function state-write differences between the seed and a merge.

    A rewrite that writes a variable the seed never wrote, or stops writing
    one the seed wrote, has changed cross-unit state behavior; that defect
    class produced the recorded getter/setter and supply mismatches.
    """
    seed_symbols = _contract_symbols(seed)[0]
    seed_writes = {unit.name: state_writes(unit.text, seed_symbols) for unit in seed.functions}
    candidate_symbols = _contract_symbols(candidate)[0]
    report: dict[str, dict[str, list[str]]] = {}
    for unit in candidate.functions:
        expected = seed_writes.get(unit.name)
        if expected is None:
            continue
        actual = state_writes(unit.text, candidate_symbols)
        added = sorted(actual - expected)
        missing = sorted(expected - actual)
        if added or missing:
            report[unit.name] = {"added_writes": added, "missing_writes": missing}
    return dict(sorted(report.items()))


def _prompt_context(
    parsed: ParsedSource,
    cluster: Cluster,
    entrypoints: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "contract": parsed.contract_name,
        "contract_declarations": parsed.declarations_text,
        "cluster_functions": [
            {
                "opaque_id": unit.opaque_id,
                "name": unit.name,
                "header": unit.header,
                "source": unit.text,
                "dependency_hints": unit.dependencies,
                "state_writes": sorted(state_writes(unit.text, _contract_symbols(parsed)[0])),
            }
            for unit in cluster.functions
        ],
        "cross_cluster_context": [
            {
                "opaque_id": unit.opaque_id,
                "name": unit.name,
                "header": unit.header,
                "source": unit.text,
            }
            for unit in cluster.context_functions
        ],
        "entrypoints": entrypoints,
        "rules": [
            "You are reverse-engineering an EVM contract from decompiled candidate source.",
            "You may request only opaque entrypoints listed here.",
            "Reference source, reference ABI names and evaluation probes are unavailable.",
            "Evidence is raw runtime observation, not a semantic oracle.",
            "Confidence is a prioritization hint, never proof of correctness.",
            "return_data_words splits raw return data into 32-byte words; use it to infer tuple "
            "layouts, dynamic-type offsets and length words.",
            "Rewrites must keep each function's name and parameter types; return types, "
            "mutability and bodies may change.",
            "state_writes lists the storage variables the decompiled function assigns; a "
            "rewrite must still write every one of them (other functions read them and the "
            "seed's pairing is bytecode evidence). Extra state writes are allowed only when "
            "the observations support them",
            "Only mark a function payable when a send with nonzero value succeeded.",
            "Return only JSON matching the requested schema.",
        ],
    }


def _read_prompt(path: Path) -> str:
    if not path.exists():
        raise InvestigatorError(f"missing prompt template: {path}")
    return path.read_text(encoding="utf-8")


@dataclass
class InvestigatorConfig:
    mode: str = "chunked-investigator"
    max_clusters: int = 6
    max_functions: int = 4
    max_investigation_rounds: int = 2
    max_probes_per_round: int = 8
    max_probes_per_cluster: int = 16
    max_total_probes: int = 64
    max_steps: int = 12
    max_merge_repairs: int = 3


@dataclass
class ClusterResult:
    cluster_id: str
    functions: list[str]
    calls: int = 0
    probe_requests: int = 0
    observations: list[str] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    synthesis: dict[str, Any] | None = None
    rewrites: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    merge: str = "not_attempted"
    applied: int = 0
    rejected: int = 0
    error: str | None = None
    records: list[dict[str, Any]] = field(default_factory=list)


class Investigator:
    def __init__(
        self,
        parsed: ParsedSource,
        client: ChatClient,
        oracle: ReferenceOracle | None,
        config: InvestigatorConfig,
        output_dir: Path,
    ) -> None:
        self.parsed = parsed
        self.client = client
        self.oracle = oracle
        self.config = config
        self.output_dir = output_dir
        self.evidence: list[dict[str, Any]] = []
        self.total_probes = 0
        self._cluster_call_start = 0
        self._merge_repairs_used = 0
        self._merge_repair_attempted: set[str] = set()
        self._merge_repair_seq = 0
        self.system = _read_prompt(CONTEXT_PATH)
        self.round1 = _read_prompt(ROUND1_PATH)
        self.round2 = _read_prompt(ROUND2_PATH)
        self.synthesis = _read_prompt(SYNTHESIS_PATH)
        self.merge_repair_prompt = _read_prompt(MERGE_REPAIR_PATH)

    def merge_repair_hook(self, config: InvestigatorConfig):
        """Gate hook: re-synthesize compile-broken units from merge diagnostics."""

        def hook(merged: str, compile_record: dict[str, Any], attempt: int) -> dict[str, str] | None:
            if self._merge_repairs_used >= config.max_merge_repairs:
                return None
            try:
                merged_parsed = parse_contract(merged, self.parsed.contract_name)
            except ParseError:
                return None
            lines = set()
            for match in re.findall(r"--> src/[A-Za-z0-9_.-]+\.sol:(\d+):", (compile_record.get("stderr") or "")):
                lines.add(int(match))
            if not lines:
                return None
            units_by_name = {unit.name: unit for unit in self.parsed.functions}
            cluster_of: dict[str, ClusterResult] = {}
            for result in getattr(self, "results", []):
                for unit_id in result.rewrites:
                    cluster_of[unit_id] = result
            merged_units = {}
            for unit in merged_parsed.functions:
                start_line = merged[: unit.start].count("\n") + 1
                end_line = merged[: unit.end].count("\n") + 1
                if lines & set(range(start_line, end_line + 1)):
                    merged_units[unit.name] = unit
            targets: dict[str, tuple] = {}  # cluster_id -> (result, units)
            for name, unit in merged_units.items():
                original = units_by_name.get(name)
                if original is None:
                    continue
                result = cluster_of.get(original.opaque_id)
                if result is None:
                    continue
                targets.setdefault(result.cluster_id, (result, []))[1].append(original)
            diagnostics = compile_record.get("stderr") or ""
            repaired: dict[str, str] = {}
            # One bounded call per broken unit: multi-unit repairs asked the
            # model to fix several functions correctly in one response and
            # repeatedly failed to converge on the recorded run.
            for cluster_id, (result, originals) in sorted(targets.items()):
                for original in originals:
                    if self._merge_repairs_used >= config.max_merge_repairs:
                        break
                    if original.opaque_id in self._merge_repair_attempted:
                        continue
                    if not self.client.budget.can_call():
                        break
                    unit_block = (
                        f"### {original.opaque_id} ({original.name})\n\n"
                        + self._merged_text(merged, original)
                    )
                    prompt = (
                        self.merge_repair_prompt
                        + "\n\nDiagnostics:\n"
                        + diagnostics[:4000]
                        + "\n\nUnits to fix:\n\n"
                        + unit_block
                    )
                    self._merge_repairs_used += 1
                    self._merge_repair_attempted.add(original.opaque_id)
                    self._merge_repair_seq += 1
                    probe_result = ClusterResult(cluster_id, [])
                    self._cluster_call_start = self.client.budget.calls
                    data = self._call_json(
                        prompt,
                        "investigator_merge_repair",
                        {
                            "type": "object",
                            "properties": {
                                "functions": {"type": "array"},
                                "claims": {"type": "array"},
                                "unresolved": {"type": "array"},
                            },
                            "required": ["functions", "claims", "unresolved"],
                            "additionalProperties": False,
                        },
                        lambda data, ids={original.opaque_id}: (
                            _check_merge_repair_response(data, ids, self.parsed, merged)
                        ),
                        f"merge-repair-{self._merge_repair_seq:03d}-{attempt}-{original.opaque_id}",
                        probe_result,
                        max_cluster_calls=1,
                    )
                    for record in probe_result.records:
                        result.records.append(record)
                    if data is None:
                        continue
                    for item in data.get("functions", []):
                        unit_id = item.get("opaque_id")
                        source = item.get("source")
                        if unit_id == original.opaque_id and isinstance(source, str):
                            repaired[unit_id] = source
            return repaired or None

        return hook

    @staticmethod
    def _merged_text(merged: str, original) -> str:
        """Current text of ``original``'s unit inside the merged source."""
        try:
            target = None
            for unit in parse_contract(merged, None).functions:
                if unit.name == original.name:
                    target = unit
                    break
            return target.text.strip() if target is not None else original.text.strip()
        except ParseError:
            return original.text.strip()

    def _call_json(
        self,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        validator: Callable[[dict[str, Any]], None],
        label: str,
        result: ClusterResult,
        max_cluster_calls: int = 3,
    ) -> dict[str, Any] | None:
        attempt_prompt = prompt
        for attempt in range(2):
            used = self.client.budget.calls - self._cluster_call_start
            if used >= max_cluster_calls or not self.client.budget.can_call():
                result.error = "call budget exhausted"
                return None
            data, error, record = self.client.request_json(
                attempt_prompt,
                schema_name,
                schema,
                label,
                self.system,
                max_attempts=max_cluster_calls - used,
            )
            if record:
                result.records.append(record)
            if error or data is None:
                result.error = error or "model returned no JSON"
                continue
            try:
                validator(data)
                return data
            except (ValueError, ParseError) as validation_error:
                result.error = f"invalid response: {validation_error}"
                attempt_prompt = (
                    prompt
                    + "\n\nYour previous response was invalid: "
                    + str(validation_error)
                    + "\nReturn corrected JSON only."
                )
        return None

    def _requests_from(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        requests = list(data.get("probe_requests", []))
        for hypothesis in data.get("hypotheses", []):
            requests.extend(hypothesis.get("probe_requests", []))
        seen = set()
        unique = []
        for request in requests:
            key = json.dumps(request, sort_keys=True)
            if key not in seen:
                seen.add(key)
                unique.append(request)
        return unique[: self.config.max_probes_per_round]

    def _run_probes(
        self, requests: list[dict[str, Any]], result: ClusterResult
    ) -> list[dict[str, Any]]:
        if self.oracle is None or not requests:
            return []
        remaining_cluster = self.config.max_probes_per_cluster - result.probe_requests
        remaining_total = self.config.max_total_probes - self.total_probes
        allowed = max(0, min(len(requests), remaining_cluster, remaining_total))
        if allowed == 0:
            result.error = "probe budget exhausted"
            return []
        batch = requests[:allowed]
        result.probe_requests += len(batch)
        self.total_probes += len(batch)
        observations = self.oracle.run(batch)
        for observation in observations:
            if "observation_id" in observation:
                result.observations.append(observation["observation_id"])
                self.evidence.append(observation)
        return observations

    def _synthesize(
        self,
        cluster: Cluster,
        result: ClusterResult,
        context: dict[str, Any],
        hypotheses: list[dict[str, Any]],
        observations: list[dict[str, Any]],
    ) -> None:
        prompt = (
            self.synthesis.replace("<<CONTEXT>>", json.dumps(context, indent=2))
            .replace("<<HYPOTHESES>>", json.dumps(hypotheses, indent=2))
            .replace("<<OBSERVATIONS>>", json.dumps(observations, indent=2))
        )
        self.output_dir.joinpath("prompts").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "prompts" / f"{cluster.cluster_id}-synthesis.txt").write_text(
            prompt, encoding="utf-8"
        )
        function_ids = {unit.opaque_id for unit in cluster.functions}
        evidence_ids = {observation["observation_id"] for observation in self.evidence}

        def validator(data: dict[str, Any]) -> None:
            _check_synthesis_response(data, function_ids, evidence_ids)

        data = self._call_json(
            prompt,
            "investigator_synthesis",
            {
                "type": "object",
                "properties": {
                    "functions": {"type": "array"},
                    "claims": {"type": "array"},
                    "unresolved": {"type": "array"},
                },
                "required": ["functions", "claims", "unresolved"],
                "additionalProperties": False,
            },
            validator,
            f"{cluster.cluster_id}-synthesis",
            result,
        )
        if data is None:
            return
        result.synthesis = data
        for item in data.get("functions", []):
            result.rewrites[item["opaque_id"]] = item["source"]
        confidences = [
            claim.get("confidence")
            for claim in data.get("claims", [])
            if isinstance(claim.get("confidence"), (int, float))
        ]
        result.confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )

    def investigate_cluster(self, cluster: Cluster, entrypoints: list[dict[str, Any]]) -> ClusterResult:
        self._cluster_call_start = self.client.budget.calls
        result = ClusterResult(cluster.cluster_id, [unit.opaque_id for unit in cluster.functions])
        context = _prompt_context(self.parsed, cluster, entrypoints)
        function_ids = {unit.opaque_id for unit in cluster.functions}
        hypotheses: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        round1_data: dict[str, Any] | None = None

        if self.config.mode != "chunked-one-shot":
            prompt = self.round1.replace("<<CONTEXT>>", json.dumps(context, indent=2))
            self.output_dir.joinpath("prompts").mkdir(parents=True, exist_ok=True)
            (self.output_dir / "prompts" / f"{cluster.cluster_id}-round1.txt").write_text(
                prompt, encoding="utf-8"
            )

            def hypothesis_validator(data: dict[str, Any]) -> None:
                _check_hypothesis_response(data, function_ids)

            data = self._call_json(
                prompt,
                "investigator_hypotheses",
                {
                    "type": "object",
                    "properties": {
                        "hypotheses": {"type": "array"},
                        "probe_requests": {"type": "array"},
                        "ready_to_synthesize": {"type": "boolean"},
                    },
                    "required": ["hypotheses", "probe_requests", "ready_to_synthesize"],
                    "additionalProperties": False,
                },
                hypothesis_validator,
                f"{cluster.cluster_id}-round1",
                result,
            )
            if data is not None:
                round1_data = data
                hypotheses = data.get("hypotheses", [])
                result.hypotheses.extend(hypotheses)
                observations.extend(self._run_probes(self._requests_from(data), result))
                if not data.get("ready_to_synthesize", False) and self.config.max_investigation_rounds > 1:
                    round2_prompt = (
                        self.round2.replace("<<CONTEXT>>", json.dumps(context, indent=2))
                        .replace("<<HYPOTHESES>>", json.dumps(hypotheses, indent=2))
                        .replace("<<OBSERVATIONS>>", json.dumps(observations, indent=2))
                    )
                    (self.output_dir / "prompts" / f"{cluster.cluster_id}-round2.txt").write_text(
                        round2_prompt, encoding="utf-8"
                    )
                    round2 = self._call_json(
                        round2_prompt,
                        "investigator_hypotheses",
                        {
                            "type": "object",
                            "properties": {
                                "hypotheses": {"type": "array"},
                                "probe_requests": {"type": "array"},
                                "ready_to_synthesize": {"type": "boolean"},
                            },
                            "required": ["hypotheses", "probe_requests", "ready_to_synthesize"],
                            "additionalProperties": False,
                        },
                        hypothesis_validator,
                        f"{cluster.cluster_id}-round2",
                        result,
                    )
                    if round2 is not None:
                        hypotheses = round2.get("hypotheses", hypotheses)
                        result.hypotheses.extend(hypotheses)
                        observations.extend(self._run_probes(self._requests_from(round2), result))

        if (
            self.config.mode != "chunked-one-shot"
            and not observations
            and round1_data is None
        ):
            result.error = result.error or "no valid investigation response; synthesis skipped"
            result.calls = self.client.budget.calls - self._cluster_call_start
            return result

        self._synthesize(cluster, result, context, hypotheses, observations)
        result.calls = self.client.budget.calls - self._cluster_call_start
        return result


def compile_error_summary(record: dict[str, Any]) -> str | None:
    """Return a short, honest reason for a failed compile record."""
    if record.get("ok"):
        return None
    error = record.get("error")
    if error:
        return str(error)[:400]
    output = (record.get("stderr") or "") + "\n" + (record.get("stdout") or "")
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Error") or stripped.startswith("SyntaxError"):
            return stripped[:400]
    first = next((line.strip() for line in output.splitlines() if line.strip()), "")
    if first:
        return first[:400]
    return f"compiler exited with code {record.get('returncode')}"


def dispatch_signature_text(header: str) -> str:
    name, types = dispatch_signature(header)
    return f"{name}({','.join(types)})"


def abi_signatures(abi: list[dict[str, Any]]) -> set[str]:
    return {
        f"{entry['name']}({','.join(item['type'] for item in entry.get('inputs', []))})"
        for entry in abi
        if entry.get("type") == "function"
    }


def expected_dispatch_signatures(
    parsed: ParsedSource, records: dict[str, Any]
) -> dict[str, str]:
    """Map applied opaque IDs to the ABI signature their rewrite must still expose."""
    by_id = {unit.opaque_id: unit for unit in parsed.functions}
    expected: dict[str, str] = {}
    for opaque_id, entry in records.items():
        if not entry.get("applied"):
            continue
        unit = by_id.get(opaque_id)
        if unit is None:
            continue
        masked = _mask_strings_and_comments(unit.header, 0, len(unit.header))
        if re.search(r"\b(private|internal)\b", masked):
            continue
        expected[opaque_id] = dispatch_signature_text(unit.header)
    return expected


def _mark_accepted(
    active: list[ClusterResult],
    merge_record: dict[str, Any],
) -> None:
    """Record per-cluster accepted and rejected unit counts from the final merge."""
    records = merge_record.get("records") or {}
    for result in active:
        accepted = sum(
            1
            for opaque_id in result.rewrites
            if records.get(opaque_id, {}).get("applied")
        )
        result.applied = accepted
        result.rejected = len(result.rewrites) - accepted
        if accepted == 0:
            result.merge = "rejected"
        elif result.rejected:
            result.merge = "partially_applied"
        else:
            result.merge = "applied"


def _check_merge_repair_response(
    data: dict[str, Any], allowed_ids: set[str], parsed: ParsedSource, merged: str
) -> None:
    """Validate a merge-repair response: known ids, parseable, signature-preserving."""
    items = data.get("functions")
    if not isinstance(items, list) or not items:
        raise ValueError("response has no functions")
    by_id = {unit.opaque_id: unit for unit in parsed.functions}
    merged_names = set()
    try:
        merged_names = {unit.name for unit in parse_contract(merged, None).functions}
    except ParseError:
        pass
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("functions entries must be objects")
        unit_id = item.get("opaque_id")
        source = item.get("source")
        if unit_id not in allowed_ids:
            raise ValueError(f"rewrite for unknown unit {unit_id!r}")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"rewrite for {unit_id} is empty")
        try:
            rewrite = parse_single_function(source)
        except ParseError as error:
            raise ValueError(f"rewrite for {unit_id} does not parse: {error}") from error
        original = by_id.get(unit_id)
        if original is not None:
            if rewrite.name != original.name:
                raise ValueError(f"rewrite for {unit_id} renamed the function")
            if dispatch_signature(rewrite.header) != dispatch_signature(original.header):
                raise ValueError(f"rewrite for {unit_id} changed the dispatch signature")
        if original is not None and rewrite.name not in merged_names:
            raise ValueError(f"rewrite for {unit_id} is not part of the merged contract")


def _solo_merge_filter(
    source: str,
    parsed: ParsedSource,
    results: list[ClusterResult],
    spec: dict[str, Any] | None,
    output_dir: Path,
    repair_hook: Any = None,
) -> list[dict[str, Any]]:
    """Validate each cluster's rewrites against the seed in isolation.

    The all-or-nothing gate turns one broken unit into dropped coverage for
    its whole cluster and entangles diagnostics from unrelated clusters.
    Compiling each cluster's rewrites alone gives per-cluster accept/drop
    with unambiguous diagnostics, and one bounded repair round in that
    solo context before the cluster is sacrificed. The union gate still
    runs afterwards: independently-compiling clusters can still conflict.
    """
    reports: list[dict[str, Any]] = []
    if spec is None:
        return reports
    for result in [r for r in results if r.rewrites]:
        solo_merged, solo_merge_record = merge_rewrites(parsed, dict(result.rewrites))
        if not solo_merge_record["applied"]:
            result.merge = "solo_rejected"
            result.error = "solo merge rejected: " + "; ".join(
                str(entry.get("error"))
                for entry in solo_merge_record["records"].values()
                if entry.get("error")
            )[:200]
            reports.append(
                {
                    "cluster": result.cluster_id,
                    "units": sorted(result.rewrites),
                    "solo_compiled": False,
                    "solo_repair": False,
                    "error": result.error,
                }
            )
            continue
        solo_record = rb.compile_candidate(
            solo_merged,
            spec["solc_version"],
            output_dir / "work" / f"solo-{result.cluster_id}",
            f"solo-{result.cluster_id}",
            spec.get("contract"),
        )
        repaired = False
        if not solo_record.get("ok") and repair_hook is not None:
            hook_result = repair_hook(solo_merged, solo_record, 0)
            if hook_result:
                fresh = {
                    unit_id: text
                    for unit_id, text in hook_result.items()
                    if unit_id in result.rewrites
                }
                if fresh:
                    result.rewrites.update(fresh)
                    repaired = True
                    solo_merged, solo_merge_record = merge_rewrites(parsed, dict(result.rewrites))
                    if solo_merge_record["applied"]:
                        solo_record = rb.compile_candidate(
                            solo_merged,
                            spec["solc_version"],
                            output_dir / "work" / f"solo-{result.cluster_id}-repair",
                            f"solo-{result.cluster_id}-repair",
                            spec.get("contract"),
                        )
        kept = bool(solo_record.get("ok"))
        result.merge = "solo_applied" if kept else "solo_dropped"
        if not kept:
            result.error = "solo merge does not compile after repair"
        reports.append(
            {
                "cluster": result.cluster_id,
                "units": sorted(result.rewrites),
                "solo_compiled": kept,
                "solo_repair": repaired,
                "error": None if kept else "solo merge does not compile",
            }
        )
    return reports


def _merge_with_gate(
    source: str,
    parsed: ParsedSource,
    results: list[ClusterResult],
    spec: dict[str, Any] | None,
    output_dir: Path,
    max_attempts: int = 3,
    repair_hook: Any = None,
) -> tuple[str, dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    active = [result for result in results if result.rewrites]
    active.sort(key=lambda result: result.confidence)
    full_record: dict[str, Any] | None = None
    repaired_once: set[str] = set()
    for attempt in range(max_attempts + 1):
        rewrites: dict[str, str] = {}
        for result in active:
            rewrites.update(result.rewrites)
        merged, merge_record = merge_rewrites(parsed, rewrites)
        attempt_record: dict[str, Any] = {
            "attempt": attempt,
            "clusters": [result.cluster_id for result in active],
            "merge": merge_record,
            "compile": None,
        }
        if not merge_record["applied"]:
            reasons = [
                str(entry["error"])
                for entry in merge_record["records"].values()
                if entry.get("error")
            ]
            for result in active:
                result.merge = "rejected"
                result.applied = 0
                result.rejected = len(result.rewrites)
                result.error = reasons[0] if reasons else "no rewrite was applied"
            attempts.append(attempt_record)
            break
        if spec is not None and merge_record["applied"]:
            work_dir = output_dir / "work" / f"merge-{attempt}"
            full_record = rb.compile_candidate(
                merged, spec["solc_version"], work_dir, f"merge-{attempt}", spec.get("contract")
            )
            record = full_record
            (output_dir / f"compile-merge-{attempt}.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8"
            )
            attempt_record["compile"] = {
                "ok": bool(record.get("ok")),
                "error": compile_error_summary(record),
            }
            compiled_ok = bool(record.get("ok"))
            if compiled_ok:
                expected = expected_dispatch_signatures(
                    parsed, merge_record["records"]
                )
                compiled = abi_signatures(record.get("abi") or [])
                missing = sorted(set(expected.values()) - compiled)
                attempt_record["dispatch"] = {
                    "expected": expected,
                    "missing": missing,
                }
                if missing:
                    compiled_ok = False
                    attempt_record["compile"] = {
                        "ok": False,
                        "error": "dispatch signature missing from compiled ABI: "
                        + ", ".join(missing),
                    }
            if compiled_ok:
                _mark_accepted(active, merge_record)
                attempts.append(attempt_record)
                return merged, {
                    "attempts": attempts,
                    "applied": True,
                    "records": merge_record["records"],
                }
        elif merge_record["applied"]:
            _mark_accepted(active, merge_record)
            attempts.append(attempt_record)
            return merged, {
                "attempts": attempts,
                "applied": True,
                "records": merge_record["records"],
            }
        attempts.append(attempt_record)
        if repair_hook is not None and merged.strip():
            # Feed the merge failure back into a bounded re-synthesis of the
            # affected clusters before sacrificing their coverage. Units whose
            # repair already failed once are not retried: the next pass drops
            # instead of spinning.
            hook_record = full_record or {
                "stderr": (attempt_record.get("compile") or {}).get("error") or ""
            }
            replacements = repair_hook(merged, hook_record, attempt)
            fresh = {
                unit_id: text for unit_id, text in (replacements or {}).items()
                if unit_id not in repaired_once
            }
            if fresh:
                repaired_once |= set(fresh)
                touched: list[str] = []
                for unit_id, rewritten in fresh.items():
                    for result in active:
                        if unit_id in result.rewrites:
                            result.rewrites[unit_id] = rewritten
                            touched.append(result.cluster_id)
                            break
                if touched:
                    attempt_record["merge_repair"] = {
                        "units": sorted(fresh),
                        "clusters": sorted(set(touched)),
                    }
                    continue
        if not active:
            break
        dropped = active.pop(0)
        dropped.merge = "dropped_after_compile_failure"
        dropped.applied = 0
        dropped.rejected = len(dropped.rewrites)
        compile_record = attempt_record.get("compile")
        summary = compile_error_summary(compile_record) if compile_record else None
        dropped.error = (
            f"dropped after compile failure: {summary}"
            if summary
            else "dropped after compile failure"
        )
    for result in results:
        result.merge = result.merge if result.merge != "not_attempted" else "fallback"
    return source, {
        "attempts": attempts,
        "applied": False,
        "records": attempts[-1]["merge"]["records"] if attempts else {},
    }


def _schema_hypotheses() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "hypotheses": {"type": "array"},
            "probe_requests": {"type": "array"},
            "ready_to_synthesize": {"type": "boolean"},
        },
        "required": ["hypotheses", "probe_requests", "ready_to_synthesize"],
        "additionalProperties": False,
    }


def run_investigator(
    source: str,
    spec: dict[str, Any] | None,
    config: InvestigatorConfig,
    client: ChatClient,
    output_dir: Path,
    candidate_label: str = "llm1",
) -> tuple[str, dict[str, Any]]:
    try:
        parsed = parse_contract(source, spec.get("contract") if spec else None)
    except ParseError as error:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "candidate.sol").write_text(source, encoding="utf-8")
        metrics = {
            "schema_version": 1,
            "mode": config.mode,
            "fixture": spec.get("fixture") if spec else None,
            "contract": spec.get("contract") if spec else None,
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "candidate_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "parse_error": str(error),
            "clusters": 0,
            "functions_total": 0,
            "functions_rewritten": 0,
            "llm_calls": 0,
            "probe_requests": 0,
            "observations": 0,
            "merge": {"applied": False, "attempts": [], "error": str(error)},
        }
        (output_dir / "metrics.json").write_text(
            json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
        )
        return source, metrics
    clusters, unclustered = cluster_functions(parsed, config.max_clusters, config.max_functions)
    if config.mode == "whole-investigator":
        clusters = [Cluster("cluster_1", parsed.functions, [])]
        unclustered = []
    oracle = None
    if spec is not None:
        bindings = rb.load_bindings(
            spec,
            json.loads((ROOT / spec["reference_abi"]).read_text()),
            candidate_label,
        )
        oracle = ReferenceOracle(spec, bindings)
    investigator: Investigator | None = None
    try:
        investigator = Investigator(parsed, client, oracle, config, output_dir)
        entrypoints = oracle.public_entrypoints() if oracle else []
        results = [
            investigator.investigate_cluster(cluster, entrypoints) for cluster in clusters
        ]
        investigator.results = results
    finally:
        if oracle is not None:
            oracle.close()

    hook = investigator.merge_repair_hook(config) if investigator is not None else None
    solo_report = _solo_merge_filter(source, parsed, results, spec, output_dir, repair_hook=hook)
    survivors = [
        result
        for result in results
        if result.rewrites and result.merge in (None, "pending", "solo_applied")
    ]
    if not survivors:
        # Every cluster failed solo: let the union gate record the attempts
        # anyway instead of publishing an unmodified candidate silently.
        survivors = [result for result in results if result.rewrites]
    merged, merge_report = _merge_with_gate(
        source,
        parsed,
        survivors,
        spec,
        output_dir,
        repair_hook=hook,
    )
    if not merged.strip():
        merged = source
    (output_dir / "candidate.sol").write_text(merged, encoding="utf-8")
    try:
        merged_parsed = parse_contract(merged, parsed.contract_name)
        state_migrations = footprint_report(parsed, merged_parsed)
    except ParseError:
        state_migrations = {}
    proposed = sum(len(result.rewrites) for result in results)
    accepted = sum(result.applied for result in results)
    dropped = sum(
        len(result.rewrites)
        for result in results
        if result.merge.startswith("dropped")
    )
    metrics = {
        "schema_version": 1,
        "mode": config.mode,
        "fixture": spec.get("fixture") if spec else None,
        "contract": parsed.contract_name,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "candidate_sha256": hashlib.sha256(merged.encode("utf-8")).hexdigest(),
        "clusters": len(clusters),
        "unclustered_functions": [unit.opaque_id for unit in unclustered],
        "state_write_migrations": state_migrations,
        "functions_total": len(parsed.functions),
        "functions_proposed": proposed,
        "functions_rewritten": accepted,
        "functions_rejected": proposed - accepted - dropped,
        "functions_dropped": dropped,
        "llm_calls": client.budget.calls,
        "completion_tokens": client.budget.completion_tokens,
        "prompt_chars": client.budget.prompt_chars,
        "elapsed_ms": int((time.time() - client.budget.started_at) * 1000),
        "probe_requests": sum(result.probe_requests for result in results),
        "observations": len(investigator.evidence),
        "merge": merge_report,
        "solo_merge": solo_report,
        "cluster_results": [
            {
                "cluster_id": result.cluster_id,
                "functions": result.functions,
                "calls": result.calls,
                "probe_requests": result.probe_requests,
                "observations": result.observations,
                "confidence": result.confidence,
                "merge": result.merge,
                "applied": result.applied,
                "rejected": result.rejected,
                "error": result.error,
                "proposed": sorted(result.rewrites),
                "records": [
                    {
                        "mode": record.get("mode"),
                        "latency_ms": record.get("latency_ms"),
                        "usage": record.get("usage"),
                        "content_sha256": hashlib.sha256(
                            (record.get("content") or "").encode("utf-8")
                        ).hexdigest(),
                    }
                    for record in result.records
                ],
            }
            for result in results
        ],
    }
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    return merged, metrics


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--spec", type=Path, default=None)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--mode",
        choices=["whole-investigator", "chunked-investigator", "chunked-one-shot"],
        default="chunked-investigator",
    )
    parser.add_argument("--llm-base-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument(
        "--candidate-label",
        default="llm1",
        help="Label used to resolve per-candidate binding signatures",
    )
    parser.add_argument("--response-format", choices=["auto", "json-schema", "json-object", "text"], default="auto")
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-clusters", type=int, default=6)
    parser.add_argument("--max-functions", type=int, default=4)
    parser.add_argument("--max-investigation-rounds", type=int, default=2)
    parser.add_argument("--max-probes-per-round", type=int, default=8)
    parser.add_argument("--max-probes-per-cluster", type=int, default=16)
    parser.add_argument("--max-total-probes", type=int, default=64)
    parser.add_argument("--max-calls", type=int, default=20)
    parser.add_argument("--max-completion-tokens", type=int, default=256_000)
    parser.add_argument("--max-merge-repairs", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.max_investigation_rounds < 1 or args.max_investigation_rounds > 2:
        raise InvestigatorError("--max-investigation-rounds must be 1 or 2")
    if not args.llm_base_url or not args.model:
        raise InvestigatorError("--llm-base-url and --model are required")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise InvestigatorError(f"output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text(encoding="utf-8")
    spec = json.loads(args.spec.read_text()) if args.spec else None
    config = InvestigatorConfig(
        mode=args.mode,
        max_clusters=args.max_clusters,
        max_functions=args.max_functions,
        max_investigation_rounds=args.max_investigation_rounds,
        max_probes_per_round=args.max_probes_per_round,
        max_probes_per_cluster=args.max_probes_per_cluster,
        max_total_probes=args.max_total_probes,
        max_merge_repairs=args.max_merge_repairs,
    )
    budget = Budget(args.max_calls, args.max_completion_tokens)
    client = ChatClient(
        args.llm_base_url,
        args.model,
        args.api_key,
        args.timeout,
        args.max_tokens,
        args.temperature,
        args.seed,
        args.response_format,
        args.output_dir,
        budget,
    )
    _, metrics = run_investigator(
        source, spec, config, client, args.output_dir, args.candidate_label
    )
    print(
        json.dumps(
            {
                k: metrics.get(k)
                for k in (
                    "mode",
                    "clusters",
                    "functions_total",
                    "functions_rewritten",
                    "llm_calls",
                    "probe_requests",
                    "observations",
                    "merge",
                )
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (InvestigatorError, ParseError, OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
