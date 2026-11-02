import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "evaluation" / "scripts" / "run_behavior.py"
SPEC = importlib.util.spec_from_file_location("run_behavior", SCRIPT)
assert SPEC and SPEC.loader
run_behavior = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_behavior)


def observation(**overrides):
    value = {
        "mode": "read",
        "sender": "0x01",
        "value": "0",
        "calldata": "0x1234",
        "ok": True,
        "return_data": "0x01",
        "revert_data": None,
        "contract_balance": "0x0",
        "logs": [],
    }
    value.update(overrides)
    return value


class EncodingTests(unittest.TestCase):
    def test_truncated_call_has_only_selector(self):
        self.assertEqual(
            run_behavior.encode_step("0x60fe47b1", {"truncated": True}),
            "0x60fe47b1",
        )

    def test_integer_arguments_are_word_encoded(self):
        self.assertEqual(
            run_behavior.encode_step("0x60fe47b1", {"args": ["0x0", "1"]}),
            "0x60fe47b1" + ("0" * 64) + ("0" * 63 + "1"),
        )

    def test_preencoded_tail_is_preserved(self):
        self.assertEqual(
            run_behavior.encode_step("0x1234", {"args_tail": "0xdeadbeef"}),
            "0x1234deadbeef",
        )


class ComparisonTests(unittest.TestCase):
    def test_length_mismatch_is_not_a_match(self):
        self.assertFalse(
            run_behavior.sequence_matches([observation()], [observation(), observation()])
        )

    def test_unbound_candidate_step_is_not_a_match(self):
        candidate = [{"unbound": True, "unbound_reason": "missing selector"}]
        self.assertFalse(run_behavior.sequence_matches([observation()], candidate))

    def test_setup_mismatch_invalidates_otherwise_matching_steps(self):
        self.assertFalse(
            run_behavior.combined_semantic_match(
                [observation()],
                [observation(ok=False)],
                [observation()],
                [observation()],
            )
        )
        self.assertTrue(
            run_behavior.combined_semantic_match(
                [observation()],
                [observation()],
                [observation()],
                [observation()],
            )
        )

    def test_configured_match_only_checks_events_when_enabled(self):
        result = {"semantic_match": True, "event_match": False}
        self.assertTrue(run_behavior.configured_match(result, False))
        self.assertFalse(run_behavior.configured_match(result, True))


class BindingSelectionTests(unittest.TestCase):
    def test_candidate_label_selects_matching_signature(self):
        binding = {
            "reference_signature": "get()",
            "candidate_signature": "legacy()",
            "candidate_signatures": {
                "whole": "wholeGetter()",
                "chunked": "chunkedGetter()",
            },
        }
        self.assertEqual(
            run_behavior.select_candidate_signature(binding, "chunked"),
            "chunkedGetter()",
        )

    def test_candidate_label_falls_back_to_legacy_signature(self):
        binding = {
            "reference_signature": "get()",
            "candidate_signature": "legacy()",
            "candidate_signatures": {"whole": "wholeGetter()"},
        }
        self.assertEqual(
            run_behavior.select_candidate_signature(binding, "missing"),
            "legacy()",
        )

    def test_candidate_label_without_any_signature_is_rejected(self):
        with self.assertRaises(run_behavior.HarnessError):
            run_behavior.select_candidate_signature(
                {"reference_signature": "get()", "candidate_signatures": {"whole": "g()"}},
                "missing",
            )


class StageTests(unittest.TestCase):
    def test_compile_blocked_stage_is_not_reported_as_behavioral_failure(self):
        spec = {"probes": [{"name": "a"}, {"name": "b"}], "withheld": ["b"]}
        stage = {"label": "baseline", "compile": False, "probe_results": {}}
        summary = run_behavior.summarize_stage(stage, spec)
        self.assertIsNone(summary["feedback_matched"])
        self.assertEqual(summary["feedback_failing"], [])
        self.assertEqual(summary["withheld_failing"], [])
        self.assertEqual(summary["blocked_reason"], "candidate did not compile")

    def test_withheld_results_are_not_counted_as_feedback(self):
        spec = {"probes": [{"name": "a"}, {"name": "b"}], "withheld": ["b"]}
        stage = {
            "label": "llm1",
            "compile": True,
            "probe_results": {
                "a": {
                    "reference": [observation()],
                    "candidate": [observation()],
                    "semantic_match": True,
                    "event_match": True,
                },
                "b": {
                    "reference": [observation()],
                    "candidate": [observation(ok=False)],
                    "semantic_match": False,
                    "event_match": True,
                },
            },
        }
        summary = run_behavior.summarize_stage(stage, spec)
        self.assertEqual(summary["feedback_matched"], 1)
        self.assertEqual(summary["feedback_failing"], [])
        self.assertEqual(summary["withheld_matched"], 0)
        self.assertEqual(summary["withheld_failing"], ["b"])

    def test_stage_bindings_mark_missing_candidate_selector(self):
        bindings = {
            "entry": {
                "reference_selector": "0x01",
                "baseline_selector": "0x01",
                "candidate_selector": "0x02",
                "candidate_signature": "f()",
            }
        }
        available = run_behavior.bindings_for_stage(bindings, "candidate", {"0x02"})
        missing = run_behavior.bindings_for_stage(bindings, "candidate", {"0x03"})
        self.assertTrue(available["entry"]["available"])
        self.assertFalse(missing["entry"]["available"])
        self.assertIn("0x02", missing["entry"]["unavailable_reason"])


class PromptTests(unittest.TestCase):
    def test_prompt_contains_feedback_only_and_no_withheld_probe(self):
        template = (
            "BINDINGS:<<BINDINGS>>\n"
            "PASS:<<PASSING_OBSERVATIONS>>\n"
            "FAIL:<<FAILING_OBSERVATIONS>>\n"
            "CANDIDATE:<<CANDIDATE_SOURCE>>"
        )
        bindings = {
            "f": {
                "reference_selector": "0x01",
                "candidate_selector": "0x02",
                "candidate_signature": "f(uint256)",
            }
        }
        probe_results = {
            "passed": {
                "candidate": [observation()],
                "reference": [observation()],
                "setup_candidate": [observation(calldata="0xsetup")],
                "setup_reference": [observation(calldata="0xsetup")],
            },
            "failed": {
                "candidate": [observation(ok=False)],
                "reference": [observation()],
                "setup_candidate": [observation(calldata="0xsetup")],
                "setup_reference": [observation(calldata="0xsetup")],
            },
            "withheld_probe": {
                "candidate": [observation(ok=False)],
                "reference": [observation()],
            },
        }
        prompt = run_behavior.build_repair_prompt(
            template,
            "baseline source",
            "candidate source",
            bindings,
            probe_results,
            ["passed"],
            ["failed"],
            {"f": "entrypoint_1"},
            {"passed": "probe_1", "failed": "probe_2", "withheld_probe": "probe_3"},
            False,
        )
        self.assertIn("probe_1", prompt)
        self.assertIn("probe_2", prompt)
        self.assertIn("0xsetup", prompt)
        self.assertNotIn("probe_3", prompt)
        self.assertNotIn("withheld_probe", prompt)


if __name__ == "__main__":
    unittest.main()
