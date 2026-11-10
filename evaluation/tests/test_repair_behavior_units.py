import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


investigator = _load("run_investigator", ROOT / "evaluation" / "scripts" / "run_investigator.py")
behavior = _load("run_behavior", ROOT / "evaluation" / "scripts" / "run_behavior.py")
rbu = _load("repair_behavior_units", ROOT / "evaluation" / "scripts" / "repair_behavior_units.py")

SOURCE = """// SPDX-License-Identifier: MIT
contract C {
    uint256 public supply;
    address public owner;
    uint256 public feeValue;

    function initialize(address o) public {
        owner = o;
    }

    function mint(uint256 amount) public {
        supply += amount;
    }
}
"""


def _obs(ok=True, ret="0x", rev=None, call="f", sender=None):
    return {
        "call": call,
        "call_ok": ok,
        "ok": ok,
        "return_data": ret,
        "revert_data": rev,
        "sender": sender,
    }


def _stage(matches, failing=(), bindings=None, results=None):
    return {
        "compile": True,
        "matches": {name: name not in failing for name in matches},
        "bindings": bindings or {"a": {"available": True}, "b": {"available": True}},
        "probe_results": results or {},
    }


def _probe_result(ref, cand):
    return {
        "setup_reference": [],
        "setup_candidate": [],
        "reference": ref,
        "candidate": cand,
        "semantic_match": behavior.combined_semantic_match([], [], ref, cand),
        "event_match": True,
    }


class AttemptVerdictTest(unittest.TestCase):
    P1 = [_obs(ret="0x11")]
    P1B = [_obs(ret="0x11")]

    def test_acceptsWholeProbeWinWithoutSideEffects(self):
        prior = _stage(["t", "other"], failing=["t"])
        prior["probe_results"]["t"] = _probe_result(self.P1, [_obs(ret="0x00")])
        prior["probe_results"]["other"] = _probe_result(self.P1, self.P1B)
        new = _stage(["t", "other"])
        new["probe_results"]["t"] = _probe_result(self.P1, self.P1B)
        new["probe_results"]["other"] = _probe_result(self.P1, self.P1B)
        accepted, pending, reasons = rbu.attempt_verdict(prior, new, "t", ["t", "other"])
        self.assertTrue(accepted)
        self.assertFalse(pending)
        self.assertEqual(reasons, [])

    def test_pending_whenDivergenceShrinksButProbeStillFails(self):
        prior = _stage(["t"], failing=["t"])
        prior["probe_results"]["t"] = _probe_result(
            self.P1, [_obs(ret="0x00"), _obs(ret="0x00")]
        )
        new = _stage(["t"], failing=["t"])
        new["probe_results"]["t"] = _probe_result(self.P1, [_obs(ret="0x11"), _obs(ret="0x00")])
        accepted, pending, _ = rbu.attempt_verdict(prior, new, "t", ["t"])
        self.assertFalse(accepted)
        self.assertTrue(pending)

    def test_rejectsRegressionOnAnotherProbe(self):
        prior = _stage(["t", "other"], failing=["t"])
        prior["probe_results"]["t"] = _probe_result(self.P1, [_obs(ret="0x00")])
        prior["probe_results"]["other"] = _probe_result(self.P1, self.P1B)
        new = _stage(["t", "other"], failing=["other"])
        new["probe_results"]["t"] = _probe_result(self.P1, self.P1B)
        new["probe_results"]["other"] = _probe_result(self.P1, [_obs(ret="0x00")])
        accepted, pending, reasons = rbu.attempt_verdict(prior, new, "t", ["t", "other"])
        self.assertFalse(accepted)
        self.assertFalse(pending)
        self.assertTrue(any("regression" in reason for reason in reasons))

    def test_rejectsLostBinding(self):
        prior = _stage(["t"], failing=["t"])
        prior["probe_results"]["t"] = _probe_result(self.P1, [_obs(ret="0x00")])
        new = _stage(["t"], failing=["t"])
        new["bindings"] = {"a": {"available": True}, "b": {"available": False}}
        new["probe_results"]["t"] = _probe_result(self.P1, self.P1B)
        accepted, _, reasons = rbu.attempt_verdict(prior, new, "t", ["t"])
        self.assertFalse(accepted)
        self.assertTrue(any("lost bindings" in reason for reason in reasons))

    def test_rejectsChangedPreviouslyExactObservation(self):
        prior = _stage(["t", "other"], failing=["t"])
        prior["probe_results"]["t"] = _probe_result(self.P1, [_obs(ret="0x00")])
        prior["probe_results"]["other"] = _probe_result(self.P1, self.P1B)
        new = _stage(["t", "other"])
        new["probe_results"]["t"] = _probe_result(self.P1, self.P1B)
        # `other` still matches as a whole but a step's balance changed.
        changed = dict(self.P1B[0])
        changed["contract_balance"] = "0x1"
        new["probe_results"]["other"] = _probe_result(self.P1, [changed])
        accepted, _, reasons = rbu.attempt_verdict(prior, new, "t", ["t", "other"])
        self.assertFalse(accepted)
        self.assertTrue(any("previously-exact" in reason for reason in reasons))

    def test_locationlessAndCompileFailuresRejected(self):
        prior = _stage(["t"], failing=["t"])
        new = _stage(["t"], failing=["t"])
        new["compile"] = False
        accepted, pending, _ = rbu.attempt_verdict(prior, new, "t", ["t"])
        self.assertFalse(accepted)
        self.assertFalse(pending)


class AttributionTest(unittest.TestCase):
    def test_differing_step_finds_first_divergence(self):
        result = _probe_result([_obs(ret="0x11")], [_obs(ret="0x11")])
        self.assertIsNone(rbu.differing_step(result, False))
        result = _probe_result([_obs(ret="0x11")], [_obs(ret="0x00")])
        self.assertEqual(rbu.differing_step(result, False), ("step", 0))

    def test_unit_for_call_resolves_candidate_signature(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        bindings = {"initialize": {"candidate_signature": "initialize(address)"}}
        unit = rbu.unit_for_call(parsed, "initialize", bindings)
        self.assertEqual(unit.name, "initialize")

    def test_related_writers_bounded_and_excludes_self(self):
        source = SOURCE.replace(
            "    function mint(uint256 amount) public {",
            "    function supplyView() public view returns (uint256) {\n"
            "        return supply;\n"
            "    }\n\n"
            "    function mint(uint256 amount) public {",
        )
        parsed = investigator.parse_contract(source, "C")
        by_name = {unit.name: unit for unit in parsed.functions}
        related = rbu.related_units(parsed, by_name["supplyView"])
        self.assertEqual([unit.name for unit in related], ["mint"])
        # Bidirectional: the writer pairs with its reader, too.
        self.assertEqual(
            [unit.name for unit in rbu.related_units(parsed, by_name["mint"])],
            ["supplyView"],
        )


class CalldataCoverageTest(unittest.TestCase):
    def test_surplus_words_labelled(self):
        row = rbu.calldata_coverage(
            "setLimits",
            "0x" + "50ce36ce" + "01".rjust(64, "0") + "a0".rjust(64, "0").replace("a0", "86a0", 0) + "f4240".rjust(64, "0"),
            {"setLimits": "Unresolved_c4590d3f(uint256)"},
        )
        self.assertEqual(row["declared_params"], 1)
        roles = [w["role"] for w in row["calldata_words"]]
        self.assertEqual(roles[0], "param_0")
        self.assertIn("surplus", roles[1])
        self.assertIn("msg.data", roles[1])

    def test_exact_arity_has_no_surplus(self):
        row = rbu.calldata_coverage(
            "mint", "0x" + "40c10f19" + "00" * 32 + "ff" * 32,
            {"mint": "Unresolved_40c10f19(address,uint256)"},
        )
        self.assertEqual([w["role"] for w in row["calldata_words"]], ["param_0", "param_1"])

    def test_malformed_calldata_is_none(self):
        self.assertIsNone(rbu.calldata_coverage("f", "0x123", {"f": "f()"}))
        self.assertIsNone(rbu.calldata_coverage("f", None, {"f": "f()"}))
        self.assertIsNone(rbu.calldata_coverage("f", "0x" + "00" * 64, {}))

    def test_probe_coverage_caps_rows(self):
        obs = {"call": "f", "calldata": "0x" + "00" * 4}
        rows = rbu._probe_coverage(
            {"setup_candidate": [obs] * 20, "candidate": []}, {"f": "f()"}
        )
        self.assertEqual(len(rows), 12)


class ReturnShapeHintTest(unittest.TestCase):
    H = "function Unresolved_860aefcf() public view returns (bytes memory)"

    def test_dynamic_declared_vs_two_bare_words(self):
        hint = rbu.return_shape_hint(
            self.H,
            "0x" + "%032x" % 1 + "%032x" % 100000,
        )
        self.assertIn("flat tuple", hint)

    def test_static_count_mismatch(self):
        hint = rbu.return_shape_hint(
            "function f() public view returns (uint256)",
            "0x" + "00" * 32 + "00" * 32,
        )
        self.assertIn("1 static return value(s)", hint)
        self.assertIn("2 bare 32-byte word(s)", hint)

    def test_compatible_shapes_are_silent(self):
        self.assertIsNone(
            rbu.return_shape_hint("function f() public view returns (uint256)", "0x" + "01" * 32)
        )
        self.assertIsNone(rbu.return_shape_hint(self.H, None))
        odd = "0x123"
        self.assertIsNone(rbu.return_shape_hint(self.H, odd))

    def test_prompt_carries_the_hint(self):
        parsed = investigator.parse_contract(
            "contract C { function f() public view returns (bytes memory) { return x; } }", "C"
        )
        unit = parsed.functions[0]
        hint = rbu.return_shape_hint(
            unit.header, "0x" + "00" * 64
        )
        prompt = rbu.repair_prompt(
            unit.text,
            "f()",
            "bytes x;",
            [],
            "probe_1",
            {},
            {"f": "f()"},
            set(),
            [],
            False,
            None,
            hint,
        )
        self.assertIn("Return-shape note:", prompt)


class PromptTest(unittest.TestCase):
    def test_prompt_uses_opaque_ids_and_hides_withheld(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        unit = parsed.functions[1]
        observations = [
            {"call": "mint", "ok": True, "return_data": "0x", "revert_data": None},
        ]
        prompt = rbu.repair_prompt(
            unit.text,
            "mint(uint256)",
            "uint256 supply;",
            [],
            "probe_transfer",
            {"mint": "entrypoint_7"},
            {"mint": "Unresolved_40c10f19(uint256)"},
            {"supply"},
            observations,
            False,
            None,
        )
        self.assertIn("entrypoint_7", prompt)
        self.assertNotIn("probe_transfer:", prompt)  # probe label stays opaque
        self.assertIn("mint(uint256)", prompt)

    def test_feedback_observations_never_include_logs(self):
        rows = rbu._feedback_observations(
            {
                "setup_reference": [],
                "setup_candidate": [],
                "reference": [_obs(call="mint", ret="0x1")],
                "candidate": [_obs(call="mint", ret="0x0")],
            }
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reference"]["logs"], [])  # sanitized, never populated
        self.assertEqual(rows[0]["reference"]["return_data"], "0x1")


class RotationTest(unittest.TestCase):
    def test_single_stall_preserved_and_second_stall_rotates(self):
        no_progress = {"a": 1}
        self.assertEqual(rbu._next_target(["a", "b"], no_progress), "a")
        self.assertEqual(no_progress, {"a": 1})  # single stall is not erased
        no_progress["a"] = 2
        self.assertEqual(rbu._next_target(["a", "b"], no_progress), "b")

    def test_full_rotation_clears_and_restarts(self):
        no_progress = {"a": 2, "b": 2}
        self.assertEqual(rbu._next_target(["a", "b"], no_progress), "a")
        self.assertEqual(no_progress, {})

    def test_stalled_target_excluded_while_others_remain(self):
        no_progress = {"a": 3}
        self.assertEqual(rbu._next_target(["a", "b", "c"], no_progress), "b")


class ResolveTargetTest(unittest.TestCase):
    def _stage_with_probe(self, call, cand_ret, ref_ret="0x11"):
        stage = _stage(["t"], failing=["t"])
        stage["probe_results"]["t"] = _probe_result(
            [_obs(call=call, ret=ref_ret)], [_obs(call=call, ret=cand_ret)]
        )
        return stage

    def test_resolves_owning_unit(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        stage = self._stage_with_probe("mint", "0x00")
        bindings = {"mint": {"candidate_signature": "mint(uint256)"}}
        location, unit = rbu._resolve_target(stage, "t", parsed, bindings, False)
        self.assertEqual(location, ("step", 0))
        self.assertEqual(unit.name, "mint")

    def test_identical_observations_resolve_none(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        stage = self._stage_with_probe("mint", "0x11")
        _, unit = rbu._resolve_target(stage, "t", parsed, {}, False)
        self.assertIsNone(unit)

    def test_unknown_call_keeps_location_drops_unit(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        stage = self._stage_with_probe("nope", "0x00")
        location, unit = rbu._resolve_target(stage, "t", parsed, {}, False)
        self.assertEqual(location, ("step", 0))
        self.assertIsNone(unit)

    def test_focus_gate(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        mint = [u for u in parsed.functions if u.name == "mint"][0]
        other = [u for u in parsed.functions if u.name != "mint"][0]
        self.assertTrue(rbu._focus_allows(mint, {"mint"}))
        self.assertFalse(rbu._focus_allows(other, {"mint"}))
        self.assertTrue(rbu._focus_allows(other, None))
        self.assertTrue(rbu._focus_allows(None, {"mint"}))


class FocusPoolTest(unittest.TestCase):
    READER_SOURCE = SOURCE.replace(
        "    function mint(uint256 amount) public {",
        "    function supplyView() public view returns (uint256) {\n"
        "        return supply;\n"
        "    }\n\n"
        "    function mint(uint256 amount) public {",
    )
    BINDINGS = {
        "supplyView": {"candidate_signature": "supplyView()"},
        "mint": {"candidate_signature": "mint(uint256)"},
    }

    def _diverged_stage(self, call):
        stage = _stage(["t"], failing=["t"])
        stage["probe_results"]["t"] = _probe_result(
            [_obs(call=call, ret="0x11")], [_obs(call=call, ret="0x00")]
        )
        return stage

    def test_no_focus_passes_everything_through(self):
        eligible, overrides = rbu._focus_pool({}, ["a", "b"], None, {}, False, None)
        self.assertEqual(eligible, ["a", "b"])
        self.assertEqual(overrides, {})

    def test_focused_writer_behind_outside_reader_is_repairable(self):
        parsed = investigator.parse_contract(self.READER_SOURCE, "C")
        eligible, overrides = rbu._focus_pool(
            self._diverged_stage("supplyView"), ["t"], parsed, self.BINDINGS, False, {"mint"}
        )
        self.assertEqual(eligible, ["t"])
        self.assertEqual([u.name for u in overrides.values()], ["mint"])

    def test_attribution_inside_focus_needs_no_override(self):
        parsed = investigator.parse_contract(self.READER_SOURCE, "C")
        eligible, overrides = rbu._focus_pool(
            self._diverged_stage("supplyView"), ["t"], parsed, self.BINDINGS, False, {"supplyView"}
        )
        self.assertEqual(eligible, ["t"])
        self.assertEqual(overrides, {})

    def test_unrelated_focus_exhausts(self):
        parsed = investigator.parse_contract(self.READER_SOURCE, "C")
        eligible, overrides = rbu._focus_pool(
            self._diverged_stage("supplyView"), ["t"], parsed, self.BINDINGS, False, {"initialize"}
        )
        self.assertEqual((eligible, overrides), ([], {}))

    def test_unattributable_probe_stays_eligible(self):
        parsed = investigator.parse_contract(self.READER_SOURCE, "C")
        eligible, overrides = rbu._focus_pool(
            self._diverged_stage("ghost"), ["t"], parsed, self.BINDINGS, False, {"mint"}
        )
        self.assertEqual(eligible, ["t"])
        self.assertEqual(overrides, {})


class JointMembersTest(unittest.TestCase):
    def test_anchor_first_related_next_respects_cap(self):
        parsed = investigator.parse_contract(FocusPoolTest.READER_SOURCE, "C")
        mint = [u for u in parsed.functions if u.name == "mint"][0]
        members = rbu._joint_members(parsed, mint, 3)
        self.assertEqual([u.name for u in members], ["mint", "supplyView"])
        self.assertEqual([u.name for u in rbu._joint_members(parsed, mint, 1)], ["mint"])

    def test_none_anchor_yields_empty_group(self):
        parsed = investigator.parse_contract(FocusPoolTest.READER_SOURCE, "C")
        self.assertEqual(rbu._joint_members(parsed, None, 3), [])

    def test_membership_is_independent_of_focus(self):
        # Regression: a single-unit focus must not shrink the joint group to
        # the anchor alone - the joint lane would become unreachable.
        parsed = investigator.parse_contract(FocusPoolTest.READER_SOURCE, "C")
        mint = [u for u in parsed.functions if u.name == "mint"][0]
        self.assertGreater(len(rbu._joint_members(parsed, mint, 3)), 1)


class AcceptedExamplesTest(unittest.TestCase):
    PARSED = investigator.parse_contract(FocusPoolTest.READER_SOURCE, "C")

    def _record(self, name):
        unit = [u for u in self.PARSED.functions if u.name == name][0]
        return rbu._accepted_record(
            "run", 1, 1, unit, unit.text.rstrip(), rbu.SINGLE_ACCEPTANCE_SUMMARY
        )

    def test_record_shape_is_audit_complete(self):
        record = self._record("mint")
        for key in ("id", "origin", "transaction", "attempt", "opaque_id", "name", "dispatch", "source", "sha256", "summary"):
            self.assertIn(key, record)
        self.assertNotIn("notes", record)

    def test_block_places_summary_and_full_body(self):
        block = "\n".join(rbu._accepted_examples_block([self._record("mint")]))
        self.assertIn("candidate-derived examples", block)
        self.assertIn("Acceptance:", block)
        self.assertIn("function mint(uint256 amount) public {", block)
        self.assertIn("}", block)

    def test_eligible_drops_target_stale_and_oversized(self):
        mint_record, view_record = self._record("mint"), self._record("supplyView")
        history = [mint_record, view_record]
        self.assertEqual(
            [r["name"] for r in rbu._eligible_examples(history, self.PARSED, {mint_record["opaque_id"]})],
            ["supplyView"],
        )
        history[0]["source"] = self.PARSED.functions[1].text.rstrip() + "\n"
        self.assertEqual(
            [r["name"] for r in rbu._eligible_examples(history, self.PARSED, set())],
            ["supplyView"],
        )
        big = self._record("mint")
        big["source"] = "x" * 3000
        self.assertEqual(rbu._eligible_examples([big], self.PARSED, set()), [])

    def test_solo_prompt_places_examples_between_target_and_observations(self):
        unit = [u for u in self.PARSED.functions if u.name == "mint"][0]
        prompt = rbu.repair_prompt(
            unit.text,
            "mint(uint256)",
            "uint256 supply;",
            [],
            "probe_x",
            {},
            {"mint": "mint(uint256)"},
            {"supply"},
            [],
            False,
            None,
            None,
            "",
            None,
            [self._record("supplyView")],
        )
        a, b, c = (
            prompt.index("Function unit to repair"),
            prompt.index("Accepted rewrites of sibling units"),
            prompt.index("Observed behavior for this probe"),
        )
        self.assertTrue(a < b < c)

    def test_joint_prompt_places_examples_after_units(self):
        unit = [u for u in self.PARSED.functions if u.name == "mint"][0]
        prompt = rbu.joint_prompt(
            [unit],
            "uint256 supply;",
            "probe_x",
            {},
            {"mint": "mint(uint256)"},
            {"supply"},
            [],
            False,
            None,
            "",
            None,
            [self._record("supplyView")],
        )
        a, b, c = (
            prompt.index("Units to repair coherently:"),
            prompt.index("Accepted rewrites of sibling units"),
            prompt.index("Observed behavior for this probe"),
        )
        self.assertTrue(a < b < c)

    def test_bootstrap_validates_seed_provenance(self):
        import hashlib
        import tempfile

        source = FocusPoolTest.READER_SOURCE
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "candidate.sol").write_text(source, encoding="utf-8")
            prior = investigator.parse_contract(source, "C")
            mint = [u for u in prior.functions if u.name == "mint"][0]
            (run / "behavior-repair.json").write_text(
                json.dumps(
                    {
                        "selected_sha256": hashlib.sha256(source.encode()).hexdigest(),
                        "ledger": [
                            {"transaction": 3, "attempt": 7, "unit": mint.opaque_id, "accepted": True}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            args = type("A", (), {"accepted_example_run": run})()
            history = rbu._bootstrap_history(args, source, self.PARSED, "C")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["name"], "mint")
            self.assertEqual(history[0]["origin"], f"bootstrap:{Path(tmp).name}")
            args2 = type("A", (), {"accepted_example_run": run})()
            with self.assertRaises(Exception):
                rbu._bootstrap_history(args2, source + "\n// drifted", self.PARSED, "C")


class ConstraintSectionsTest(unittest.TestCase):
    BINDINGS = {"mint": {"candidate_signature": "mint(uint256)"}}

    def _stage(self):
        # target `t` failing on mint; `keep` passing but touching mint; `t2` failing elsewhere
        stage = _stage(["t", "keep", "t2"], failing=["t", "t2"])
        stage["probe_results"]["t"] = _probe_result(
            [_obs(call="mint", ret="0x11")], [_obs(call="mint", ret="0x00")]
        )
        stage["probe_results"]["keep"] = _probe_result(
            [_obs(call="mint", ret="0x11")], [_obs(call="mint", ret="0x11")]
        )
        stage["probe_results"]["t2"] = _probe_result(
            [_obs(call="burn", ret="0x11")], [_obs(call="burn", ret="0x00")]
        )
        return stage

    def test_sections_cover_preserve_and_failing_never_target(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        mint = [u for u in parsed.functions if u.name == "mint"][0]
        sections = rbu._constraint_sections(
            self._stage(), "t", mint, ["t", "keep", "t2"], parsed, self.BINDINGS, False
        )
        text = "\n".join(sections)
        self.assertIn("preserve exactly", text)
        self.assertIn("probe keep", text)
        self.assertIn("also failing", text)
        self.assertIn("probe t2", text)
        self.assertNotIn("probe t:", text)
        self.assertIn('"return_data": "0x11"', text)  # sanitized rendered rows, real values

    def test_no_sibling_probes_yields_no_sections(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        mint = [u for u in parsed.functions if u.name == "mint"][0]
        self.assertEqual(
            rbu._constraint_sections(_stage(["t"], failing=["t"]), "t", mint, ["t"], parsed, self.BINDINGS, False),
            [],
        )

    def test_section_budget_caps_output(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        mint = [u for u in parsed.functions if u.name == "mint"][0]
        stage = self._stage()
        for index in range(20):
            name = f"p{index}"
            stage["matches"][name] = True
            stage["probe_results"][name] = stage["probe_results"]["keep"]
        names = ["t"] + [f"p{i}" for i in range(20)]
        text = "\n".join(
            rbu._constraint_sections(stage, "t", mint, names, parsed, self.BINDINGS, False)
        )
        self.assertLessEqual(len(text), rbu.CONSTRAINT_SECTION_CHARS + 2000)

    def test_prompt_places_constraints_last(self):
        parsed = investigator.parse_contract(SOURCE, "C")
        mint = [u for u in parsed.functions if u.name == "mint"][0]
        sections = rbu._constraint_sections(
            self._stage(), "t", mint, ["t", "keep", "t2"], parsed, self.BINDINGS, False
        )
        prompt = rbu.repair_prompt(
            mint.text,
            "mint(uint256)",
            "uint256 supply;",
            [],
            "probe_t",
            {},
            {"mint": "mint(uint256)"},
            set(),
            [],
            False,
            None,
            None,
            "",
            None,
            None,
            sections,
        )
        self.assertLess(
            prompt.index("Observed behavior for this probe"),
            prompt.index("Constraint from other feedback probes"),
        )
        self.assertIn("probe keep", prompt)


if __name__ == "__main__":
    unittest.main()
