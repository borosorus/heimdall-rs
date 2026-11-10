#!/usr/bin/env python3
"""Unit-scoped behavior repair driven by failing-probe observations.

The whole-source behavior repair path fails to compile on large candidates
(recorded), and the merge gate can leave a cluster's units with their seed
bodies. This pass operates on the compiled gate output: it maps the first
differing observation of a failing feedback probe to the candidate function
unit behind it, asks the model to repair that one unit against the raw
observation traces, and accepts a bounded transaction of edits only on
measured whole-probe progress.

Acceptance is evidence-based and conservative:

- the target probe (setup included) must match completely, or the
  transaction may stay pending while its failing-step count strictly
  decreases with no other change;
- every previously passing feedback probe still passes, and its per-step
  observations remain exactly as they were;
- no previously available binding or compiled dispatch signature may
  disappear;
- anything else rolls the transaction back to the last accepted source.

Exactly one repair attempt per unit per transaction; every rejected attempt
is recorded with its reason. Withheld-probe observations never enter a
prompt: prompts carry feedback probes only, with opaque probe/entrypoint
identifiers, the candidate's own source, and raw observation views.

No reference Solidity and no reference ABI names are sent; observation
calldata and the candidate source are the only contract-derived inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_behavior as hb  # noqa: E402
from run_investigator import (  # noqa: E402
    Budget,
    ChatClient,
    ParseError,
    _mask_strings_and_comments,
    _contract_symbols,
    parse_contract,
    state_writes,
    dispatch_signature_text,
)

ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "evaluation" / "prompts" / "behavior_unit_repair.txt"

MAX_UNITS_PER_TRANSACTION = 3
MAX_TRANSACTIONS = 3


class BehaviorRepairError(RuntimeError):
    pass


# ----------------------------------------------------------------纯 functions

def differing_step(
    result: dict[str, Any], compare_events: bool
) -> tuple[str, int] | None:
    """First (phase, index) whose semantic views disagree, for diagnostics."""
    for phase in ("setup_reference", "setup_candidate"), ("reference", "candidate"):
        ref, cand = result.get(phase[0], []), result.get(phase[1], [])
        for index, (left, right) in enumerate(zip(ref, cand)):
            if hb.semantic_view(left) != hb.semantic_view(right):
                return "setup" if phase[0].startswith("setup") else "step", index
    return None


def unit_for_call(parsed, call_name: str, bindings: dict[str, Any]):
    """Candidate unit behind a probe step's `call` (a binding name), if any."""
    binding = bindings.get(call_name)
    if not binding:
        return None
    signature = binding.get("candidate_signature") or ""
    name = signature.split("(", 1)[0]
    for unit in parsed.functions:
        if unit.name == name:
            return unit
    return None


def _resolve_target(stage: dict[str, Any], probe: str, parsed, bindings: dict[str, Any], compare_events: bool):
    """First diverging observation of a failing probe and its owning unit.

    Returns `(location, unit)`; either may be None when the divergence is
    unattributable (no differing step, or no candidate unit behind the call).
    """
    result = stage["probe_results"].get(probe)
    if result is None:
        return None, None
    location = differing_step(result, compare_events)
    if location is None:
        return None, None
    phase, index = location
    pool = result.get("setup_candidate" if phase == "setup" else "candidate") or result.get(
        "setup_reference" if phase == "setup" else "reference"
    ) or []
    call_name = (pool[index] or {}).get("call") if index < len(pool) else None
    if not call_name:
        return location, None
    return location, unit_for_call(parsed, call_name, bindings)


def _next_target(failing: list[str], no_progress: dict[str, int]) -> str | None:
    """Stalled-target rotation over `failing`.

    Targets with two fruitless transactions rotate away; the map is cleared
    only once every failing target has stalled (a full pass), so a single
    stall is never erased and rotation actually alternates targets.
    """
    stalled = {name for name, count in no_progress.items() if count >= 2}
    candidates = [name for name in failing if name not in stalled]
    if not candidates:
        no_progress.clear()
        candidates = list(failing)
    return candidates[0] if candidates else None


def _focus_allows(unit, focus: set[str] | None) -> bool:
    """Focused-campaign membership by candidate name or opaque id."""
    return focus is None or unit is None or unit.name in focus or getattr(unit, "opaque_id", None) in focus


def _focus_pool(stage, failing, parsed, bindings, compare_events, focus):
    """Focused eligibility for repair targets.

    A failing probe is repairable under the focus when its first diverging
    unit is in the focus, when its divergence is unattributable (unit None),
    or when a focused related unit (writer/reader pair) stands behind it - a
    focused writer must stay repairable even when the divergence surfaces in
    a reader outside the focus. In the related case the probe maps to an
    override unit: the focused related unit is rewritten instead of the
    attributed one, with the same observations and acceptance gate.

    Returns `(eligible, overrides)`.
    """
    if focus is None:
        return list(failing), {}
    eligible: list[str] = []
    overrides: dict[str, object] = {}
    for name in failing:
        _, resolved = _resolve_target(stage, name, parsed, bindings, compare_events)
        if _focus_allows(resolved, focus):
            eligible.append(name)
            continue
        related = related_units(parsed, resolved) if resolved else []
        focused = [rel for rel in related if _focus_allows(rel, focus)]
        if focused:
            eligible.append(name)
            overrides[name] = focused[0]
    return eligible, overrides


def _joint_members(parsed, anchor, cap: int) -> list:
    """Coordinated-rewrite group: the anchor plus its related units.

    Membership is graph-driven on purpose: the focus filter narrows which
    failing probes are repairable, not which units a stalled target may be
    jointly rewritten with - a single-unit focus must still reach the
    writer/reader context that joint repair exists for. The whole-probe
    acceptance verdict guards every member's side effects.
    """
    members = [anchor] + (related_units(parsed, anchor) if anchor else [])
    return [member for member in members if member is not None][:cap]


SINGLE_ACCEPTANCE_SUMMARY = (
    "compiled; dispatch preserved; one feedback probe became matching; "
    "previously passing feedback observations preserved"
)
GROUP_ACCEPTANCE_SUMMARY = (
    "compiled as one coordinated rewrite; dispatch preserved for every member; "
    "feedback acceptance improved for the probe"
)


def _accepted_record(origin: str, transaction: int, attempt: int, unit, source: str, summary: str) -> dict[str, Any]:
    """Audit record for one strictly accepted unit rewrite (never pending)."""
    return {
        "id": f"{origin.split(':')[0][:3]}-t{transaction:02d}a{attempt:03d}-{unit.opaque_id}",
        "origin": origin,
        "transaction": transaction,
        "attempt": attempt,
        "opaque_id": unit.opaque_id,
        "name": unit.name,
        "dispatch": dispatch_signature_text(unit.header),
        "source": source,
        "sha256": hashlib.sha256(source.encode()).hexdigest(),
        "summary": summary,
    }


def _eligible_examples(history, parsed, exclude_ids: set[str], limit: int = 2, per_limit: int = 2048, total_limit: int = 4096) -> list[dict[str, Any]]:
    """Newest-first bounded accepted examples, still valid for this source.

    An example is dropped when its unit was rewritten again (source no longer
    matches the current parse), when it is one of the units under repair, or
    when it exceeds the size bounds; oversized units are skipped, not
    truncated.
    """
    by_id = {unit.opaque_id: unit for unit in parsed.functions}
    eligible: list[dict[str, Any]] = []
    total = 0
    for record in reversed(history):
        if record["opaque_id"] in exclude_ids:
            continue
        current = by_id.get(record["opaque_id"])
        if current is None or dispatch_signature_text(current.header) != record["dispatch"]:
            continue
        if current.text.rstrip() != record["source"]:
            continue
        if len(record["source"]) > per_limit:
            continue
        if total + len(record["source"]) > total_limit:
            break
        eligible.append(record)
        total += len(record["source"])
        if len(eligible) == limit:
            break
    return eligible


def _accepted_examples_block(examples) -> list[str]:
    if not examples:
        return []
    lines = [
        "",
        "Accepted rewrites of sibling units in this contract for similar feedback probes:",
        "These are candidate-derived examples with limited feedback acceptance.",
        "They do not establish correctness on other paths. Repair only the requested",
        "unit(s); derive their behavior from the current observations.",
    ]
    for index, record in enumerate(examples, start=1):
        lines.extend(
            [f"Example {index} - {record['dispatch']}", f"Acceptance: {record['summary']}.", record["source"]]
        )
    return lines


def _bootstrap_history(args, origin_source: str, parsed, contract_name: str | None) -> list[dict[str, Any]]:
    """Import strict single-unit acceptances from a prior run on the same seed.

    Provenance gate: the prior run's saved selected hash, its candidate bytes
    and the current origin bytes must agree, and every imported example's
    dispatch identity must still exist in the origin. Any mismatch fails
    before the first model call.
    """
    if not args.accepted_example_run:
        return []
    run_dir: Path = args.accepted_example_run
    metrics_path = run_dir / "behavior-repair.json"
    candidate_path = run_dir / "candidate.sol"
    if not metrics_path.exists() or not candidate_path.exists():
        raise BehaviorRepairError(f"accepted-example run is missing behavior-repair.json/candidate.sol: {run_dir}")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    prior_source = candidate_path.read_text(encoding="utf-8")
    saved = metrics.get("selected_sha256")
    prior_hash = hashlib.sha256(prior_source.encode()).hexdigest()
    origin_hash = hashlib.sha256(origin_source.encode()).hexdigest()
    if saved != prior_hash or saved != origin_hash:
        raise BehaviorRepairError(
            "accepted-example run does not match this seed: "
            f"selected={saved} candidate={prior_hash} origin={origin_hash}"
        )
    prior_parsed = parse_contract(prior_source, contract_name)
    origin_by_name = {unit.name: unit for unit in parsed.functions}
    history: list[dict[str, Any]] = []
    for entry in metrics.get("ledger", []):
        if not entry.get("accepted") or entry.get("mode"):
            continue  # strict single-unit acceptances only
        unit = next((u for u in prior_parsed.functions if u.opaque_id == entry.get("unit")), None)
        origin_unit = origin_by_name.get(unit.name) if unit else None
        if unit is None or origin_unit is None:
            raise BehaviorRepairError(f"accepted-example ledger entry not reproducible: {entry!r}")
        if dispatch_signature_text(origin_unit.header) != dispatch_signature_text(unit.header):
            raise BehaviorRepairError(f"accepted-example dispatch changed against this seed: {unit.name}")
        history.append(
            _accepted_record(f"bootstrap:{run_dir.name}", int(entry.get("transaction", 0)), int(entry.get("attempt", 0)), unit, unit.text.rstrip(), SINGLE_ACCEPTANCE_SUMMARY)
        )
    return history


def _declared_returns(masked_header: str) -> list[str] | None:
    """Top-level declared return types, or None when the header declares none."""
    match = re.search(r"\breturns\s*\(", masked_header)
    if not match:
        return []
    start = match.end()
    depth = 1
    index = start
    while index < len(masked_header) and depth > 0:
        if masked_header[index] == "(":
            depth += 1
        elif masked_header[index] == ")":
            depth -= 1
        index += 1
    if depth != 0:
        return None
    inner = masked_header[start : index - 1].strip()
    if not inner:
        return []
    types: list[str] = []
    depth = 0
    current: list[str] = []
    for char in inner:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            types.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    tail = "".join(current).strip()
    if tail:
        types.append(tail)
    return types


_QUALIFIERS = {"memory", "calldata", "storage"}


def _is_static_return(type_text: str) -> bool:
    words = [w for w in type_text.replace("[", " [").split() if w]
    words = [w for w in words if w not in _QUALIFIERS]
    if not words:
        return False
    base = words[0].split("[")[0]
    if base in ("bytes", "string") or "[" in words[0]:
        return False
    return bool(re.fullmatch(r"(uint\d+|int\d+|address|bool|bytes[1-9]|bytes3[0-2]|function)", base)) and len(words) == 1


def return_shape_hint(header: str, reference_return: str | None) -> str | None:
    """Mechanical mismatch hint: declared return shape vs observed bare words.

    Derived only from the candidate's own signature and the raw observation,
    both allowable inputs. Returns None when the shape is compatible or not
    decodable - hints never invent the correct type.
    """
    if not reference_return or not reference_return.startswith("0x"):
        return None
    data = reference_return[2:]
    if len(data) % 64:
        return None
    words = len(data) // 64
    masked = _mask_strings_and_comments(header, 0, len(header))
    declared = _declared_returns(masked)
    if declared is None:
        return None
    if not declared:
        if words:
            return (
                f"the reference return data carries {words} bare 32-byte word(s) but the "
                "current signature declares no return value; adding a return whose "
                "top-level encoding is exactly those words is allowed (the dispatch "
                "identity that must stay unchanged is the name and parameter types)"
            )
        return None
    if all(_is_static_return(item) for item in declared):
        expected = len(declared)
        if words != expected:
            return (
                f"the signature declares {expected} static return value(s) but the reference "
                f"return data carries {words} bare 32-byte word(s); the reference shape is "
                "the ground truth - declare and return the matching tuple of values "
                "(changing the declared return types is allowed)"
            )
        return None
    # dynamic declaration (bytes/string/tuples): a dynamic top-level encoding
    # starts with a 0x20 offset word for a single dynamic return; bare value
    # words mean the observed shape is a flat tuple, not the declared dynamic.
    first = int(data[:64], 16) if data[:64] else -1
    if first != 0x20:
        return (
            "the reference return data does not begin with a dynamic-typed offset word "
            "(0x20), so the observed shape is a flat tuple of values while the signature "
            "declares a dynamic return; return plain values matching the observed words "
            "instead (changing declared return types is allowed)"
        )
    return None


def state_map(parsed) -> str:
    """Per-variable slot/writers/readers table, from the candidate alone.

    The decompiler can alias several logical variables onto one declared
    slot or phantom (the recorded var_c collision: min-limit, supply and a
    predicate all touched it). The map makes the collision visible so the
    rewrite can pick an unused variable instead of compounding it.
    """
    storage = _contract_symbols(parsed)[0]
    if not storage:
        return "(no state variables)"
    writers: dict[str, set[str]] = {name: set() for name in storage}
    readers: dict[str, set[str]] = {name: set() for name in storage}
    for unit in parsed.functions:
        for name in state_writes(unit.text, storage):
            writers[name].add(unit.name)
        masked = _mask_strings_and_comments(unit.text, 0, len(unit.text))
        for name in storage:
            if re.search(rf"\b{name}\b", masked):
                readers[name].add(unit.name)
    slots: dict[str, str] = {}
    for match in re.finditer(
        r"^\s*(?:address|uint\d+|int\d+|bytes\d*|string|bool|mapping\([^)]*\))\s+"
        r"(?:(?:public|private|internal|constant|immutable)\s+)*([A-Za-z_]\w*)\s*;"
        r"[^\n]*?slot:\s*(0x[0-9a-fA-F]+)",
        parsed.source,
        re.M,
    ):
        slots[match.group(1)] = match.group(2).lower()
    lines = []
    for name in sorted(storage):
        slot_text = slots.get(name, "auto")
        w = ", ".join(sorted(writers[name])) or "-"
        r = ", ".join(sorted(readers[name] - writers[name])) or "-"
        lines.append(f"{name} (slot {slot_text}): written by {w}; read by {r}")
    return "\n".join(lines) or "(no state variables)"


def calldata_coverage(call: str, calldata: str | None, signatures: dict[str, str]) -> dict[str, Any] | None:
    """Align a call's calldata words with its candidate signature's params.

    Surplus words are reachable inside the unit via ``msg.data`` even though
    no named parameter carries them - the fact the repair loop kept missing
    when the candidate signature declares fewer parameters than the reference
    ABI accepts.
    """
    if not calldata or not calldata.startswith("0x") or len(calldata) < 10:
        return None
    signature = signatures.get(call)
    if not signature or "(" not in signature:
        return None
    inner = signature[signature.index("(") + 1 : signature.rindex(")")]
    declared = len([part for part in inner.split(",") if part.strip()]) if inner.strip() else 0
    body = calldata[10:]
    if len(body) % 64:
        return None
    words = [body[index * 64 : (index + 1) * 64] for index in range(len(body) // 64)]
    labelled = []
    for index, word in enumerate(words):
        labelled.append(
            {
                "index": index,
                "word": "0x" + word,
                "role": f"param_{index}" if index < declared else "surplus (reachable as msg.data suffix)",
            }
        )
    return {"call": call, "declared_params": declared, "calldata_words": labelled}


def _probe_coverage(result: dict[str, Any], signatures: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for phase_c, tag in (("setup_candidate", "setup"), ("candidate", "step")):
        for observation in result.get(phase_c, []):
            entry = calldata_coverage(
                observation.get("call") or "", observation.get("calldata"), signatures
            )
            if entry is not None:
                entry["phase"] = tag
                rows.append(entry)
    return rows[:12]


JOINT_SCHEMA = {
    "type": "object",
    "properties": {
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"opaque_id": {"type": "string"}, "source": {"type": "string"}},
                "required": ["opaque_id", "source"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["units", "notes"],
    "additionalProperties": False,
}


def validate_joint_rewrite(members: list, data: dict[str, Any]) -> dict[str, str]:
    """Validate a multi-unit response; returns {opaque_id: function_text}.

    Every returned unit must be one of the requested members and pass the
    single-unit checks; at least one valid rewrite is required.
    """
    items = data.get("units")
    if not isinstance(items, list) or not items:
        raise BehaviorRepairError("response has no units")
    by_id = {unit.opaque_id: unit for unit in members}
    rewrites: dict[str, str] = {}
    errors: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            errors.append("unit entry is not an object")
            continue
        unit_id = item.get("opaque_id")
        unit = by_id.get(unit_id) if isinstance(unit_id, str) else None
        if unit is None:
            errors.append(f"unknown unit {unit_id!r}")
            continue
        try:
            rewrites[unit_id] = _validate_unit_rewrite(None, unit, item.get("source"))
        except BehaviorRepairError as validation_error:
            errors.append(f"{unit_id}: {validation_error}")
    if not rewrites:
        raise BehaviorRepairError("; ".join(errors) or "no valid unit rewrites")
    return rewrites


def joint_prompt(members: list, declarations: str, probe_name: str, entries, signatures, storage, observations, compare_events: bool, previous_error: str | None, state_map_text: str, coverage_rows, accepted_examples=None) -> str:
    blocks = []
    for index, unit in enumerate(members, start=1):
        blocks.append(f"### unit_{index} opaque_id={unit.opaque_id}\n{unit.text.strip()}")
    parts = [
        f"Target probe: {probe_name}",
        "",
        "Repair ALL of the units below in one coordinated response: their bodies"
        " must agree on which state variable carries which value and who writes"
        " or reads it. Return one entry per unit under its given opaque_id.",
        "",
        "Callable entrypoints of this contract (use these exact names):",
        "\n".join(
            f"{entry}: {signatures[name]}"
            for name, entry in sorted(entries.items())
            if name in signatures
        ) or "(none)",
        "",
        "Declared state variables (use these exact names): "
        + (", ".join(sorted(storage)) or "(none)"),
        "",
        "State map (slot / writers / readers - keep distinct logical values on "
        "distinct variables; a value with no changing variable needs a new home "
        "plus consistent writer and reader updates):",
        state_map_text or "(unavailable)",
        "",
        "Calldata coverage - surplus words beyond declared parameters stay readable"
        " as the msg.data suffix inside the unit:",
        json.dumps(coverage_rows) if coverage_rows else "(none)",
        "",
        "Contract declarations (read-only context):",
        declarations.strip() or "(none)",
        "",
        "Units to repair coherently:",
        "\n\n".join(blocks),
    ]
    parts.extend(_accepted_examples_block(accepted_examples))
    if previous_error:
        parts.extend(["", f"The previous coordinated attempt was rejected: {previous_error}"])
    parts.extend(["", "Observed behavior for this probe (candidate vs reference):"])
    parts.append(json.dumps(_summarize_rows(_render_rows(observations, entries)), indent=1)[:16000])
    return "\n".join(parts)


def _render_rows(rows, entries):
    rendered = []
    for row in rows:
        call = row.get("call")
        rendered.append(
            {
                "phase": row.get("phase"),
                "index": row.get("index"),
                "entrypoint": entries.get(call, call),
                "candidate": dict(row.get("candidate") or {}),
                "reference": dict(row.get("reference") or {}),
            }
        )
    return rendered


def related_units(parsed, target) -> list:
    """Units coupled to the target's state, bounded: writers of what it reads
    and readers of what it writes. A wrong-slot getter pairs with its writer
    only when both directions are considered."""
    storage = _contract_symbols(parsed)[0]
    target_masked = _mask_strings_and_comments(target.text, 0, len(target.text))
    target_writes = state_writes(target.text, storage)
    reads = {
        name
        for name in storage
        if name in target_masked and name not in target_writes
    }
    related: list = []
    seen: set[str] = set()
    for unit in parsed.functions:
        if unit.name == target.name or unit.name in seen:
            continue
        writes = state_writes(unit.text, storage)
        unit_masked = _mask_strings_and_comments(unit.text, 0, len(unit.text))
        reads_of_mine = any(name in unit_masked for name in target_writes)
        if (writes & reads) or reads_of_mine:
            related.append(unit)
            seen.add(unit.name)
        if len(related) >= 3:
            break
    return related


def attempt_verdict(
    prior_stage: dict[str, Any],
    new_stage: dict[str, Any],
    target: str,
    feedback_names: list[str],
    compare_events: bool = False,
) -> tuple[bool, bool, list[str]]:
    """(accepted, pending_progress, reasons) for one staged transaction state.

    Accepted  : target now matches, no feedback regression, every previously
                passing probe keeps its exact per-step observations, and the
                available-binding set did not shrink.
    Pending   : target still failing but its differing-step count strictly
                decreased, with the same no-regression/no-binding-loss rules.
    """
    reasons: list[str] = []
    if not new_stage.get("compile"):
        return False, False, ["candidate does not compile"]

    prior_matches = prior_stage.get("matches", {})
    new_matches = new_stage.get("matches", {})
    prior_results = prior_stage.get("probe_results", {})
    new_results = new_stage.get("probe_results", {})

    regressions = [
        name
        for name in feedback_names
        if prior_matches.get(name) and not new_matches.get(name)
    ]
    if regressions:
        reasons.append(f"feedback regressions: {', '.join(regressions)}")

    prior_bound = {
        name for name, entry in prior_stage.get("bindings", {}).items() if entry.get("available")
    }
    new_bound = {
        name for name, entry in new_stage.get("bindings", {}).items() if entry.get("available")
    }
    lost = sorted(prior_bound - new_bound)
    if lost:
        reasons.append(f"lost bindings: {', '.join(lost)}")

    exact_broken = []
    for name in feedback_names:
        if not prior_matches.get(name):
            continue
        old = prior_results.get(name, {})
        new = new_results.get(name, {})
        for phase in ("setup_reference", "setup_candidate"), ("reference", "candidate"):
            old_obs, new_obs = old.get(phase[0], []), new.get(phase[1], [])
            if len(old_obs) != len(new_obs):
                exact_broken.append(name)
                break
            for left, right in zip(old_obs, new_obs):
                if hb.semantic_view(left) != hb.semantic_view(right):
                    exact_broken.append(name)
                    break
    if exact_broken:
        reasons.append(f"previously-exact observations changed: {', '.join(sorted(set(exact_broken)))}")

    clean = not reasons
    target_now = bool(new_matches.get(target))

    if clean and target_now:
        return True, False, []
    if clean:
        old_diffs = _divergence_count(prior_results.get(target, {}))
        new_diffs = _divergence_count(new_results.get(target, {}))
        if new_diffs < old_diffs:
            return False, True, [f"target divergence {old_diffs} -> {new_diffs}"]
        reasons.append("target divergence unchanged")
    return False, False, reasons


def _divergence_count(result: dict[str, Any]) -> int:
    count = 0
    for phase in ("setup_reference", "setup_candidate"), ("reference", "candidate"):
        ref, cand = result.get(phase[0], []), result.get(phase[1], [])
        count += sum(
            1
            for left, right in zip(ref, cand)
            if hb.semantic_view(left) != hb.semantic_view(right)
        )
        count += abs(len(ref) - len(cand))
    return count


def repair_prompt(
    unit_text: str,
    unit_signature: str,
    declarations: str,
    related: list,
    probe_name: str,
    entries: dict[str, str],
    signatures: dict[str, str],
    storage: set[str],
    observations: list[dict[str, Any]],
    compare_events: bool,
    previous_error: str | None = None,
    shape_hint: str | None = None,
    state_map_text: str = "",
    coverage_rows: list[dict[str, Any]] | None = None,
    accepted_examples: list[dict[str, Any]] | None = None,
    constraint_sections: list[str] | None = None,
) -> str:
    # Rows from _feedback_observations are already prompt_view-rendered and
    # logs-sanitized; re-viewing them would read the row envelope and null
    # every field.
    rendered = []
    for row in observations:
        view = dict(row.get("candidate") or {})
        reference_view = row.get("reference") or {}
        call = row.get("call")
        entry = entries.get(call, call)
        rendered.append(
            {
                "phase": row.get("phase"),
                "index": row.get("index"),
                "entrypoint": entry,
                "candidate": view,
                "reference": reference_view,
            }
        )
    parts = [
        f"Target probe: {probe_name}",
        "",
        "Callable entrypoints of this contract (use these exact names):",
        "\n".join(
            f"{entry}: {signatures[name]}"
            for name, entry in sorted(entries.items())
            if name in signatures
        ) or "(none)",
        "",
        "Declared state variables (use these exact names): "
        + (", ".join(sorted(storage)) or "(none)"),
        "",
        "Contract declarations (read-only context):",
        declarations.strip() or "(none)",
        "",
        "State map (slot / writers / readers per variable - keep distinct logical "
        "values on distinct variables). When an observed value has no variable that "
        "changes by the observed delta, a counter or accumulated value is missing: "
        "route it through a variable with no writers yet and update every unit that "
        "must stay consistent with it (the incrementing writer and the reading "
        "getter), never through a variable another duty already owns:",
        state_map_text or "(unavailable)",
        "",
        "Calldata coverage for this probe's calls - surplus words beyond the declared "
        "parameters are still readable inside the unit as the msg.data suffix; a value "
        "that appears in no variable may need its writer to capture such a word:",
        json.dumps(coverage_rows) if coverage_rows else "(none)",
        "",
        f"Function unit to repair ({unit_signature}):",
        unit_text.strip(),
    ]
    for unit in related:
        parts.extend(
            [
                "",
                f"Related unit {dispatch_signature_text(unit.header)} (context only):",
                unit.text.strip()[:1200],
            ]
        )
    parts.extend(_accepted_examples_block(accepted_examples or []))
    if shape_hint:
        parts.extend(["", f"Return-shape note: {shape_hint}"])
    if previous_error:
        parts.extend(["", f"The previous attempt was rejected: {previous_error}"])
    parts.extend(["", "Observed behavior for this probe (candidate vs reference):"])
    shown = _summarize_rows(rendered)
    parts.append(json.dumps(shown, indent=1)[:16000])
    for section in constraint_sections or []:
        parts.extend(["", f"Constraint from other feedback probes - {section}"])
    return "\n".join(parts)


def _summarize_rows(rows: list[dict[str, Any]], keep_matching: int = 2) -> list[dict[str, Any]]:
    """Drop trailing identical pairs; keep the head and every differing row."""
    if len(rows) <= keep_matching + 2:
        return rows
    differing = [
        row
        for row in rows
        if (row.get("candidate") or {}) != (row.get("reference") or {})
    ]
    head = rows[:keep_matching]
    selected = head + [row for row in differing if row not in head]
    if len(selected) < len(rows):
        selected.append({"omitted_matching_rows": len(rows) - len(selected)})
    return selected


def _feedback_observations(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Interleaved candidate/reference observations of one probe, feedback-only."""
    rows: list[dict[str, Any]] = []
    for ref_phase, cand_phase, tag in (
        ("setup_reference", "setup_candidate", "setup"),
        ("reference", "candidate", "step"),
    ):
        ref = result.get(ref_phase, [])
        cand = result.get(cand_phase, [])
        for index in range(max(len(ref), len(cand))):
            rows.append(
                {
                    "phase": tag,
                    "index": index,
                    "reference": hb.prompt_view(ref[index], include_logs=False)
                    if index < len(ref)
                    else None,
                    "candidate": hb.prompt_view(cand[index], include_logs=False)
                    if index < len(cand)
                    else None,
                    "call": (cand[index] or ref[index]).get("call")
                    if (index < len(cand) or index < len(ref))
                    else None,
                }
            )
    return rows


CONSTRAINT_PROBE_CAP = 3
CONSTRAINT_ROWS_PER_PROBE = 2
CONSTRAINT_SECTION_CHARS = 1400


def _constraint_sections(
    stage: dict[str, Any],
    target: str,
    unit,
    feedback_names: list[str],
    parsed,
    bindings: dict[str, Any],
    compare_events: bool,
) -> list[str]:
    """Evidence from sibling feedback probes the rewrite must respect.

    The acceptance verdict checks every feedback probe, but the repair prompt
    carried only the target's rows - rewrites flew blind against the exact
    observations they were required to preserve. Sections: for passing probes
    whose steps touch this unit, the matching candidate/reference pairs
    ("preserve exactly"); for other failing probes, the rows around their
    first divergence. Rendered through the same sanitized view as the target
    rows; hard-capped; the target probe itself never appears.
    """
    matches = stage.get("matches", {})
    sections: list[str] = []
    budget = CONSTRAINT_SECTION_CHARS

    def rendered(probe: str):
        result = stage["probe_results"].get(probe)
        if result is None:
            return None, None
        rows = _feedback_or_setup_rows(result)
        return result, rows

    def unit_row_indices(rows, limit):
        picked = []
        for index, row in enumerate(rows or []):
            call = row.get("call")
            resolved = unit_for_call(parsed, call or "", bindings) if call else None
            if unit is not None and resolved is not None and resolved.opaque_id == unit.opaque_id:
                picked.append(index)
                if len(picked) == limit:
                    break
        return picked

    def divergence_row_index(result, rows):
        location = differing_step(result, compare_events)
        if location is None:
            return None
        phase, index = location
        offset = 0 if phase == "setup" else len(result.get("setup_reference") or result.get("setup_candidate") or [])
        rendered_index = offset + index
        return rendered_index if 0 <= rendered_index < len(rows or []) else None

    candidates: list[tuple[str, str, list[int]]] = []
    for probe in feedback_names:
        if probe == target:
            continue
        result, rows = rendered(probe)
        if result is None or not rows:
            continue
        if matches.get(probe):
            indices = unit_row_indices(rows, CONSTRAINT_ROWS_PER_PROBE)
            if indices:
                candidates.append((probe, "preserve exactly (currently matching)", indices))
        else:
            index = divergence_row_index(result, rows)
            if index is not None:
                window = [i for i in (index - 1, index, index + 1) if 0 <= i < len(rows)]
                candidates.append((probe, "also failing, around first divergence", window[:CONSTRAINT_ROWS_PER_PROBE]))

    passing = [item for item in candidates if item[1].startswith("preserve")]
    failing = [item for item in candidates if not item[1].startswith("preserve")]
    for probe, label, indices in (passing + failing)[: 2 * CONSTRAINT_PROBE_CAP]:
        _result, rendered_rows = rendered(probe)
        picked = [rendered_rows[i] for i in indices]
        block = json.dumps(picked, indent=1)[:1200]
        section = f"{label} - probe {probe}:\n{block}"
        if len(section) > budget:
            break
        budget -= len(section) + 1
        sections.append(section)
    return sections


def _feedback_or_setup_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Sanitized interleaved rows (alias kept for call-site clarity)."""
    return _feedback_observations(result)


def _abi_surface(compile_record: dict[str, Any]) -> set[str]:
    return set(hb.abi_selectors(compile_record.get("abi") or []))


def run(args: argparse.Namespace) -> int:
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise BehaviorRepairError(f"output directory is not empty: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    root = hb.repo_root()
    spec = hb.read_json(args.spec)
    reference_abi = hb.read_json(root / spec["reference_abi"])
    reference_runtime = (root / spec["reference_runtime"]).read_text(encoding="utf-8").strip()
    if not reference_runtime.startswith("0x"):
        reference_runtime = "0x" + reference_runtime
    reference_selectors = hb.abi_selectors(reference_abi)
    bindings = hb.load_bindings(spec, reference_abi, args.candidate_label)
    compare_events = bool(spec.get("compare_events", False))
    withheld = set(spec.get("withheld", []))
    feedback_names = [p["name"] for p in spec["probes"] if p["name"] not in withheld]

    origin_source = args.candidate.read_text(encoding="utf-8")
    (args.output_dir / "origin.sol").write_text(origin_source, encoding="utf-8")
    parsed = parse_contract(origin_source, spec.get("contract"))
    declarations = parsed.declarations_text
    entries = {name: f"entrypoint_{index + 1}" for index, name in enumerate(bindings)}
    candidate_signatures = {
        name: binding["candidate_signature"] for name, binding in bindings.items()
    }
    storage_names = _contract_symbols(parsed)[0]

    focus: set[str] | None = None
    if args.only.strip():
        focus = {name.strip() for name in args.only.split(",") if name.strip()}
        known = {unit.name for unit in parsed.functions} | {unit.opaque_id for unit in parsed.functions}
        unknown = focus - known
        if unknown:
            raise BehaviorRepairError(
                "unknown --only unit(s): "
                + ", ".join(sorted(unknown))
                + "; known units: "
                + ", ".join(sorted(known))
            )

    accepted_history: list[dict[str, Any]] = []
    if args.accepted_example_run and not args.accepted_rewrite_context:
        raise BehaviorRepairError("--accepted-example-run requires --accepted-rewrite-context")
    if args.accepted_rewrite_context:
        accepted_history = _bootstrap_history(args, origin_source, parsed, spec.get("contract"))

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
    system = PROMPT_PATH.read_text(encoding="utf-8").strip()

    anvil = hb.Anvil()
    accepted_source = origin_source
    accepted_stage: dict[str, Any] | None = None
    ledger: list[dict[str, Any]] = []
    attempt_index = 0
    no_progress: dict[str, int] = {}
    group_tried: set[str] = set()
    origin_stage_snapshot: dict[str, Any] | None = None
    try:
        rpc = anvil.rpc
        rpc.call("anvil_setCode", [hb.REF_ADDR, reference_runtime])
        rpc.call("anvil_setBalance", [hb.REF_ADDR, "0x0"])

        def evaluate(source: str, label: str) -> dict[str, Any]:
            return hb.evaluate_stage(
                rpc, spec, bindings, reference_selectors, source, label, "candidate", 2 + attempt_index, args.output_dir
            )

        current_source = origin_source
        current_stage = evaluate(current_source, "origin")
        if not current_stage.get("compile"):
            raise BehaviorRepairError("input candidate does not compile; run the compile repair first")
        accepted_stage = current_stage
        accepted_source = current_source
        origin_stage_snapshot = dict(current_stage)

        for transaction in range(1, args.max_transactions + 1):
            failing = [
                name
                for name in feedback_names
                if not current_stage["matches"].get(name)
            ]
            if not failing:
                break
            if not budget.can_call():
                ledger.append({"transaction": transaction, "error": "call budget exhausted"})
                break
            pool = failing
            focus_override: dict[str, object] = {}
            if focus is not None:
                eligible, focus_override = _focus_pool(
                    current_stage, failing, parsed, bindings, compare_events, focus
                )
                if not eligible:
                    ledger.append(
                        {
                            "transaction": transaction,
                            "error": "focus exhausted: no failing probe resolves to a focused unit",
                        }
                    )
                    break
                pool = eligible
            target = _next_target(pool, no_progress)
            result = current_stage["probe_results"][target]
            location, unit = _resolve_target(current_stage, target, parsed, bindings, compare_events)
            if target in focus_override:
                unit = focus_override[target]
            if location is None:
                no_progress[target] = no_progress.get(target, 0) + 1
                ledger.append({"transaction": transaction, "target": target, "error": "no differing observation located"})
                continue
            phase, index = location
            if unit is None:
                ledger.append(
                    {
                        "transaction": transaction,
                        "target": target,
                        "error": f"no candidate unit behind differing {phase}[{index}]",
                    }
                )
                no_progress[target] = no_progress.get(target, 0) + 1
                continue

            repaired_units: dict[str, int] = {}
            staged_source = current_source
            staged_parsed = parsed
            staged_stage = current_stage
            transaction_accepted = False
            pending_seen = False
            last_error: str | None = None
            for _unit_attempt in range(1, args.max_attempts_per_unit + 1):
                if not budget.can_call():
                    break
                attempt_index += 1
                related = related_units(staged_parsed, unit)
                observations = _feedback_observations(result)
                error_reason: str | None = last_error
                ref_pool = result.get("reference") or []
                map_text = state_map(staged_parsed)
                coverage_rows = _probe_coverage(result, candidate_signatures)
                ref_obs = ref_pool[index] if index < len(ref_pool) else {}
                shape = return_shape_hint(unit.header, ref_obs.get("return_data")) if phase != "setup" else None
                solo_examples = _eligible_examples(accepted_history, staged_parsed, {unit.opaque_id})
                constraints = _constraint_sections(
                    current_stage, target, unit, feedback_names, staged_parsed, bindings, compare_events
                )
                prompt = repair_prompt(
                    unit.text,
                    dispatch_signature_text(unit.header),
                    declarations,
                    related,
                    f"probe_{target}",
                    entries,
                    candidate_signatures,
                    storage_names,
                    observations,
                    compare_events,
                    error_reason,
                    shape,
                    map_text,
                    coverage_rows,
                    solo_examples,
                    constraints,
                )
                data, request_error, _record = client.request_json(
                    prompt,
                    "behavior_unit_repair",
                    {
                        "type": "object",
                        "properties": {"source": {"type": "string"}, "notes": {"type": "string"}},
                        "required": ["source", "notes"],
                        "additionalProperties": False,
                    },
                    f"txn{transaction:02d}-{unit.opaque_id}-a{attempt_index:03d}",
                    system,
                )
                entry: dict[str, Any] = {
                    "transaction": transaction,
                    "attempt": attempt_index,
                    "target": target,
                    "unit": unit.opaque_id,
                    "name": unit.name,
                    "examples": [record["id"] for record in solo_examples],
                    "request_error": request_error,
                }
                ledger.append(entry)
                if data is None:
                    continue
                try:
                    function_text = _validate_unit_rewrite(staged_parsed, unit, data.get("source"))
                except BehaviorRepairError as validation_error:
                    entry["error"] = str(validation_error)
                    continue
                repaired_units[unit.opaque_id] = repaired_units.get(unit.opaque_id, 0) + 1
                merged = _apply_one(staged_parsed, unit, function_text)
                merged_parsed = parse_contract(merged, spec.get("contract"))
                compile_record = hb.compile_candidate(
                    merged,
                    spec["solc_version"],
                    args.output_dir / "work" / f"txn{transaction:02d}-a{attempt_index:03d}",
                    f"txn{transaction:02d}-a{attempt_index:03d}",
                    spec.get("contract"),
                )
                entry["compiled"] = bool(compile_record.get("ok"))
                surface = _abi_surface(compile_record) if compile_record.get("ok") else set()
                expected = {
                    hb.cast_selector(dispatch_signature_text(u.header))
                    for u in parsed.functions
                }
                entry["abi_loss"] = sorted(expected - surface) if compile_record.get("ok") else None
                if not compile_record.get("ok") or (expected - surface):
                    if compile_record.get("ok"):
                        entry["error"] = "compiled ABI lost signatures"
                        last_error = "compiled ABI lost signatures: " + ", ".join(entry["abi_loss"][:4])
                    else:
                        entry["error"] = "compile failed"
                        diagnostics = ((compile_record.get("stderr") or "") + (compile_record.get("stdout") or "")).strip()
                        last_error = "your previous rewrite failed to compile with: " + diagnostics[:900]
                    continue

                trial_stage = evaluate(merged, f"txn{transaction:02d}-a{attempt_index:03d}")
                accepted, pending, verdict_reasons = attempt_verdict(
                    current_stage, trial_stage, target, feedback_names, compare_events
                )
                entry["accepted"] = accepted
                entry["pending"] = pending
                entry["verdict"] = verdict_reasons
                if accepted or pending:
                    staged_source, staged_parsed = merged, merged_parsed
                    staged_stage = trial_stage
                    error_reason = None
                    repaired_units[unit.opaque_id] = 0  # fresh unit, fresh attempts
                    if accepted:
                        accepted_history.append(
                            _accepted_record("run", transaction, attempt_index, unit, function_text, SINGLE_ACCEPTANCE_SUMMARY)
                        )
                    unit = None
                    if accepted:
                        transaction_accepted = True
                    else:
                        pending_seen = True
                    break
                entry["rolled_back"] = True
                last_error = "your previous rewrite was rejected: " + "; ".join(
                    str(reason) for reason in verdict_reasons[:2]
                )

            if transaction_accepted or (pending_seen and staged_source != current_source):
                current_source, parsed = staged_source, staged_parsed
                current_stage = staged_stage
                accepted_source, accepted_stage = current_source, current_stage
                no_progress.pop(target, None)
            else:
                no_progress[target] = no_progress.get(target, 0) + 1
                ledger.append(
                    {
                        "transaction": transaction,
                        "target": target,
                        "error": "no admissible edit; target deferred",
                        "no_progress": no_progress[target],
                    }
                )
            # Atomic group fallback: when single-unit attempts stalled, some
            # probes need coupled edits (writer+reader, setter+getter). Rewrite
            # up to MAX_UNITS_PER_TRANSACTION related units privately, then
            # compile/evaluate the combination once against this transaction's
            # anchor; the whole group rolls back unless the net verdict is a
            # whole-probe win or a strict divergence decrease.
            if (
                not transaction_accepted
                and not pending_seen
                and no_progress.get(target, 0) >= 1
                and target not in group_tried
                and budget.can_call()
            ):
                group_tried.add(target)
                group_result = current_stage["probe_results"][target]
                _group_location, group_unit = _resolve_target(current_stage, target, parsed, bindings, compare_events)
                members = _joint_members(parsed, group_unit, MAX_UNITS_PER_TRANSACTION)
                if len(members) >= 2:
                    # Joint coordinated rewrite: one call returns every member,
                    # so coupled units agree on variable roles in a single
                    # response instead of negotiating through prompt prose.
                    anchor_source, anchor_stage = current_source, current_stage
                    group_source = anchor_source
                    rewritten_any = False
                    if not budget.can_call():
                        pass
                    else:
                        attempt_index += 1
                        map_text_g = state_map(parsed)
                        cov_g = _probe_coverage(group_result, candidate_signatures)
                        joint_examples = _eligible_examples(accepted_history, parsed, {m.opaque_id for m in members})
                        j_data, j_error, _rec = client.request_json(
                            joint_prompt(
                                members,
                                declarations,
                                f"probe_{target}",
                                entries,
                                candidate_signatures,
                                storage_names,
                                _feedback_observations(group_result),
                                compare_events,
                                "the single-unit repairs for this probe stalled; produce one coherent set",
                                map_text_g,
                                cov_g,
                                joint_examples,
                            ),
                            "behavior_unit_repair_joint",
                            JOINT_SCHEMA,
                            f"txn{transaction:02d}-joint-a{attempt_index:03d}",
                            system,
                        )
                        j_entry: dict[str, Any] = {
                            "transaction": transaction,
                            "attempt": attempt_index,
                            "target": target,
                            "mode": "joint",
                            "members": [m.opaque_id for m in members],
                            "examples": [record["id"] for record in joint_examples],
                            "request_error": j_error,
                        }
                        ledger.append(j_entry)
                        rewrites: dict[str, str] = {}
                        if j_data is not None:
                            try:
                                rewrites = validate_joint_rewrite(members, j_data)
                            except BehaviorRepairError as validation_error:
                                j_entry["error"] = str(validation_error)
                        if rewrites:
                            group_source = _apply_many(parsed, rewrites)
                            rewritten_any = True
                    if rewritten_any:
                        g_compile = hb.compile_candidate(
                            group_source,
                            spec["solc_version"],
                            args.output_dir / "work" / f"txn{transaction:02d}-grp",
                            f"txn{transaction:02d}-grp",
                            spec.get("contract"),
                        )
                        surface = _abi_surface(g_compile) if g_compile.get("ok") else set()
                        expected_surface = {
                            hb.cast_selector(dispatch_signature_text(u.header)) for u in parsed.functions
                        }
                        g_ok = bool(g_compile.get("ok")) and not (expected_surface - surface)
                        g_stage = (
                            evaluate(group_source, f"txn{transaction:02d}-grp")
                            if g_ok
                            else {"compile": False}
                        )
                        g_accepted, g_pending, g_reasons = attempt_verdict(
                            anchor_stage, g_stage, target, feedback_names, compare_events
                        )
                        ledger.append(
                            {
                                "transaction": transaction,
                                "target": target,
                                "mode": "group-verdict",
                                "accepted": g_accepted,
                                "pending": g_pending,
                                "verdict": g_reasons,
                            }
                        )
                        if g_accepted or g_pending:
                            if g_accepted:
                                for member in members:
                                    rewritten = rewrites.get(member.opaque_id)
                                    if rewritten:
                                        accepted_history.append(
                                            _accepted_record("run", transaction, attempt_index, member, rewritten, GROUP_ACCEPTANCE_SUMMARY)
                                        )
                            current_source, parsed = group_source, parse_contract(
                                group_source, spec.get("contract")
                            )
                            current_stage = g_stage
                            accepted_source, accepted_stage = current_source, current_stage
                            no_progress.pop(target, None)
                            continue
            # Starvation guard: a stalled target rotates away; the loop only
            # ends on budget exhaustion, full success, or unattributable
            # probes - never on a single unit's failure.
    finally:
        anvil.stop()

    final_stage = accepted_stage or {}
    metrics = {
        "schema_version": 1,
        "tool": "repair_behavior_units",
        "candidate_label": args.candidate_label,
        "focused_units": sorted(focus) if focus else None,
        "max_transactions": args.max_transactions,
        "origin_sha256": hashlib.sha256(origin_source.encode()).hexdigest(),
        "selected_sha256": hashlib.sha256(accepted_source.encode()).hexdigest(),
        "origin_feedback_matched": None
        if origin_stage_snapshot is None
        else origin_stage_snapshot.get("feedback_matched"),
        "selected_feedback_matched": final_stage.get("feedback_matched"),
        "selected_feedback_total": final_stage.get("feedback_total"),
        "selected_withheld_matched": final_stage.get("withheld_matched"),
        "selected_withheld_total": final_stage.get("withheld_total"),
        "selected_feedback_failing": final_stage.get("feedback_failing", []),
        "selected_withheld_failing": final_stage.get("withheld_failing", []),
        "attempts": len(ledger),
        "llm_calls": budget.calls,
        "completion_tokens": budget.completion_tokens,
        "ledger": ledger,
        "elapsed_ms": int((time.time() - budget.started_at) * 1000),
    }
    if accepted_history:
        metrics["accepted_examples"] = [
            {key: record[key] for key in ("id", "origin", "transaction", "attempt", "opaque_id", "name", "sha256")}
            for record in accepted_history
        ]
        (args.output_dir / "accepted-examples.json").write_text(json.dumps(accepted_history, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "behavior-repair.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "candidate.sol").write_text(accepted_source, encoding="utf-8")
    improved = (final_stage.get("feedback_matched") or 0) > (
        (accepted_stage or {}).get("feedback_matched") if accepted_stage else 0
    )
    print(
        f"feedback {final_stage.get('feedback_matched')}/{final_stage.get('feedback_total')} "
        f"withheld {final_stage.get('withheld_matched')}/{final_stage.get('withheld_total')} "
        f"calls={budget.calls}",
    )
    return 0 if final_stage.get("feedback_matched") else 2


def _validate_unit_rewrite(parsed, unit, source: str) -> str:
    """Dispatch identity, single function, external visibility preserved."""
    import repair_units as ru

    if not isinstance(source, str) or not source.strip():
        raise BehaviorRepairError("rewrite is empty")
    try:
        rewrite = ru.parse_single_function(source)
    except ParseError as error:
        raise BehaviorRepairError(f"rewrite does not parse: {error}") from error
    if rewrite.name != unit.name:
        raise BehaviorRepairError(f"rewrite renamed {unit.name} to {rewrite.name}")
    from run_investigator import dispatch_signature

    if dispatch_signature(rewrite.header) != dispatch_signature(unit.header):
        raise BehaviorRepairError("rewrite changed the dispatch signature")
    masked = _mask_strings_and_comments(rewrite.header, 0, len(rewrite.header))
    unit_masked = _mask_strings_and_comments(unit.header, 0, len(unit.header))
    external = ("public", "external")
    was = any(__import__("re").search(rf"\b{word}\b", unit_masked) for word in external)
    now = any(__import__("re").search(rf"\b{word}\b", masked) for word in external)
    if was and not now:
        raise BehaviorRepairError("rewrite dropped the external visibility")
    return rewrite.text.rstrip()


def _apply_many(parsed, rewrites: dict[str, str]) -> str:
    import repair_units as ru

    return ru.apply_rewrites(parsed, rewrites)


def _apply_one(parsed, unit, function_text: str) -> str:
    import repair_units as ru

    return ru.apply_rewrites(parsed, {unit.opaque_id: function_text})


def build_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--baseline", type=Path, default=None)
    parser.add_argument("--candidate-label", default="seed-v2")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--llm-base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument(
        "--response-format",
        choices=["auto", "json-schema", "json-object", "text"],
        default="auto",
    )
    parser.add_argument("--max-tokens", type=int, default=32768)
    parser.add_argument("--max-completion-tokens", type=int, default=262144)
    parser.add_argument("--max-calls", type=int, default=8)
    parser.add_argument("--max-attempts-per-unit", type=int, default=2)
    parser.add_argument("--max-transactions", type=int, default=MAX_TRANSACTIONS)
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated candidate function names or opaque ids to focus repair on",
    )
    parser.add_argument(
        "--accepted-rewrite-context",
        action="store_true",
        help="include bounded accepted-rewrite examples in repair prompts",
    )
    parser.add_argument(
        "--accepted-example-run",
        type=Path,
        default=None,
        help="prior behavior-repair run dir whose strict acceptances bootstrap the examples",
    )
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = build_args(argv)
    try:
        return run(args)
    except BehaviorRepairError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except hb.HarnessError as error:
        print(f"harness error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
