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


class StrictEvidenceTests(unittest.TestCase):
    @staticmethod
    def failed_no_evidence():
        return observation(ok=False, return_data=None, revert_data=None)

    @staticmethod
    def failed_with_revert(data: str):
        return observation(ok=False, return_data=None, revert_data=data)

    def test_default_mode_keeps_history_compatible_failed_parity(self):
        # two evidence-less failures match unless strict evidence is requested
        self.assertTrue(
            run_behavior.sequence_matches([self.failed_no_evidence()], [self.failed_no_evidence()])
        )

    def test_strict_mode_demands_evidence_from_failed_steps(self):
        pair = [self.failed_no_evidence()]
        self.assertFalse(run_behavior.sequence_matches(pair, pair, strict_evidence=True))

    def test_strict_mode_accepts_equal_revert_payloads(self):
        pair = [self.failed_with_revert("0x4e487b71")]
        self.assertTrue(run_behavior.sequence_matches(pair, pair, strict_evidence=True))

    def test_strict_mode_accept_successful_empty_return(self):
        pair = [observation(return_data="0x")]
        self.assertTrue(run_behavior.sequence_matches(pair, pair, strict_evidence=True))

    def test_combined_threads_strict_flag(self):
        empty = [self.failed_no_evidence()]
        self.assertTrue(run_behavior.combined_semantic_match([], [], empty, empty))
        self.assertFalse(run_behavior.combined_semantic_match([], [], empty, empty, strict_evidence=True))

    def test_traced_gas_counts_as_evidence_for_silent_failures(self):
        traced = observation(ok=False, return_data=None, revert_data=None, gas_used="0x1e8480")
        pair = [traced]
        self.assertTrue(run_behavior.sequence_matches(pair, pair, strict_evidence=True))

    def test_gas_is_excluded_from_equality(self):
        # gas consumption is implementation detail: different gas, same verdict
        a = observation(ok=False, return_data=None, revert_data=None, gas_used="0x1")
        b = observation(ok=False, return_data=None, revert_data=None, gas_used="0x9999")
        self.assertTrue(run_behavior.sequence_matches([a], [b], strict_evidence=True))


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

    def test_candidate_label_without_map_entry_is_rejected(self):
        # a per-label map must not silently bind another label's signature:
        # wrong-selector verdicts would look like behavior failures
        with self.assertRaises(run_behavior.HarnessError):
            run_behavior.select_candidate_signature(
                {
                    "reference_signature": "get()",
                    "candidate_signature": "legacy()",
                    "candidate_signatures": {"whole": "wholeGetter()"},
                },
                "missing",
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

class SendPathEvidenceTest(unittest.TestCase):
    def test_failed_send_record_receipt_gas_as_evidence(self):
        receipts = iter([
            {
                "status": "0x0",
                "gasUsed": "0x5208",
                "logs": [],
            }
        ])

        class FakeRpc:
            def call(self, method, params=None):
                if method == "eth_sendTransaction":
                    return "0xhash"
                if method == "eth_getTransactionReceipt":
                    return next(receipts, None)
                if method == "eth_getBalance":
                    return "0x0"
                raise AssertionError(f"unexpected {method}")

        observation = run_behavior.call_step(
            FakeRpc(), "0x" + "11" * 20, "0xdeadbeef", "0x" + "22" * 20, 0, True
        )
        self.assertEqual(observation["gas_used"], "0x5208")
        self.assertFalse(observation["ok"])
        pair = [observation]
        self.assertTrue(run_behavior.sequence_matches(pair, pair, strict_evidence=True))

    def test_missing_receipt_gas_leaves_send_unverified(self):
        receipts = iter([{"status": "0x0", "gasUsed": None, "logs": []}])

        class FakeRpc:
            def call(self, method, params=None):
                if method == "eth_sendTransaction":
                    return "0xhash"
                if method == "eth_getTransactionReceipt":
                    return next(receipts, None)
                if method == "eth_getBalance":
                    return "0x0"
                raise AssertionError(f"unexpected {method}")

        observation = run_behavior.call_step(
            FakeRpc(), "0x" + "11" * 20, "0xdeadbeef", "0x" + "22" * 20, 0, True
        )
        self.assertIsNone(observation["gas_used"])
        pair = [observation]
        self.assertFalse(run_behavior.sequence_matches(pair, pair, strict_evidence=True))


if __name__ == "__main__":
    unittest.main()


class CanonicalEventTest(unittest.TestCase):
    TOPIC_TRANSFER = "0xddf252ad" + "00" * 28
    TOPIC_ALIAS = "0x1234abcd" + "00" * 28

    def test_declared_event_table_maps_own_keccaks(self):
        source = "contract C { event Event_ddf252ad(address, address, uint256); }"
        table = run_behavior.declared_event_topics(source)
        self.assertEqual(len(table), 1)
        (name,) = table.values()
        self.assertEqual(name, "Event_ddf252ad")
        # the alias name embeds the id used for cross-side identity
        logs = [{"topics": [next(iter(table)), "0x" + "aa" * 32], "data": "0x0"}]
        (event,) = run_behavior.canonical_events(logs, table)
        self.assertEqual(event["event"], "ddf252ad")

    def test_event_match_resolves_alias_topics_to_identity(self):
        table = {
            "reference": {self.TOPIC_TRANSFER: "Transfer"},
            "candidate": {self.TOPIC_ALIAS: "Event_ddf252ad"},
        }
        ref = [{"logs": [{"topics": [self.TOPIC_TRANSFER, "0x" + "aa" * 32], "data": "0x01"}]}]
        cand = [{"logs": [{"topics": [self.TOPIC_ALIAS, "0x" + "aa" * 32], "data": "0x01"}]}]
        self.assertTrue(run_behavior.event_matches(ref, cand, table))

    def test_event_match_rejects_different_payloads(self):
        table = {
            "reference": {self.TOPIC_TRANSFER: "Transfer"},
            "candidate": {self.TOPIC_ALIAS: "Event_ddf252ad"},
        }
        ref = [{"logs": [{"topics": [self.TOPIC_TRANSFER], "data": "0x01"}]}]
        cand = [{"logs": [{"topics": [self.TOPIC_ALIAS], "data": "0x02"}]}]
        self.assertFalse(run_behavior.event_matches(ref, cand, table))

    def test_event_match_without_table_compares_raw(self):
        logs = [{"logs": [{"topics": ["0xab"], "data": "0x1"}]}]
        self.assertTrue(run_behavior.event_matches(logs, [dict(logs[0])]))
        self.assertFalse(
            run_behavior.event_matches(logs, [{"logs": [{"topics": ["0xcd"], "data": "0x1"}]}])
        )


class GasClassTest(unittest.TestCase):
    def test_equal_consumption_is_determinate(self):
        self.assertEqual(
            run_behavior.classify_from_used(50_000, 50_000, 2_000_000, 1_000_000), "determinate"
        )

    def test_both_caps_exhausted_is_gas_bound(self):
        # a loop burns whatever budget exists: both caps hit
        self.assertEqual(
            run_behavior.classify_from_used(2_000_000, 990_000, 2_000_000, 1_000_000), "gas-bound"
        )

    def test_half_exhausted_with_full_headroom_is_unclassified(self):
        # expensive determinate halt looks identical to a loop at the half cap
        self.assertIsNone(
            run_behavior.classify_from_used(1_200_000, 990_000, 2_000_000, 1_000_000)
        )

    def test_class_is_part_of_the_compared_view(self):
        a = observation(ok=False, return_data=None, revert_data=None, gas_used="0x1", gas_class="gas-bound")
        b = observation(ok=False, return_data=None, revert_data=None, gas_used="0x9999", gas_class="gas-bound")
        c = observation(ok=False, return_data=None, revert_data=None, gas_used="0x1", gas_class="determinate")
        self.assertTrue(run_behavior.sequence_matches([a], [b], strict_evidence=True))
        self.assertFalse(run_behavior.sequence_matches([a], [c], strict_evidence=True))

    def test_class_only_for_silent_failures(self):
        # payload-bearing reverts compare by data; class absence matches
        payload = observation(ok=False, return_data=None, revert_data="0x08c379a0", gas_class=None)
        self.assertTrue(run_behavior.sequence_matches([payload], [payload], strict_evidence=True))

