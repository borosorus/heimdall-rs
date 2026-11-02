import http.client
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "evaluation" / "scripts" / "run_investigator.py"
SPEC = importlib.util.spec_from_file_location("run_investigator", SCRIPT)
assert SPEC and SPEC.loader
investigator = importlib.util.module_from_spec(SPEC)
sys.modules["run_investigator"] = investigator
SPEC.loader.exec_module(investigator)

DUMMY = """// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

contract Dummy {
    uint256 private counter;
    event Changed(uint256 value);
    error Bad();

    // A comment with } and a string with { must not confuse the splitter.
    function set(uint256 value) public payable {
        counter = value;
        emit Changed(value);
    }

    function get() public view returns (uint256) {
        return counter;
    }

    function other() public {
        require(counter != 0, Bad());
    }
}
"""


class FakeClient:
    def __init__(self, functions):
        self.budget = investigator.Budget()
        self.functions = functions
        self.call_count = 0

    def request_json(self, prompt, schema_name, schema, label, system, max_attempts=None):
        self.call_count += 1
        record = {"mode": "fake", "prompt": prompt, "content": "{}", "usage": {"completion_tokens": 1}}
        self.budget.charge(prompt, record["usage"], record["content"])
        if schema_name == "investigator_hypotheses":
            if self.call_count == 1:
                return (
                    {
                        "hypotheses": [
                            {
                                "function": "fn_1",
                                "claim": "setter stores value",
                                "confidence": 0.5,
                                "uncertainties": [],
                                "probe_requests": [
                                    {"call": "entrypoint_1", "args": ["7"], "send": True}
                                ],
                            }
                        ],
                        "probe_requests": [],
                        "ready_to_synthesize": False,
                    },
                    None,
                    record,
                )
            return (
                {
                    "hypotheses": [
                        {
                            "function": "fn_1",
                            "claim": "setter stores value and emits",
                            "confidence": 0.8,
                            "uncertainties": [],
                            "probe_requests": [],
                        }
                    ],
                    "probe_requests": [],
                    "ready_to_synthesize": True,
                },
                None,
                record,
            )
        if schema_name == "investigator_synthesis":
            return (
                {
                    "functions": [
                        {"opaque_id": opaque_id, "source": source}
                        for opaque_id, source in self.functions.items()
                    ],
                    "claims": [
                        {
                            "opaque_id": "fn_1",
                            "claim": "setter stores value",
                            "confidence": 0.8,
                            "evidence": ["obs_1"],
                        }
                    ],
                    "unresolved": [],
                },
                None,
                record,
            )
        return None, f"unexpected schema {schema_name}", record


class FakeOracle:
    def __init__(self):
        self.requests = []

    def run(self, requests):
        self.requests.extend(requests)
        return [
            {
                "observation_id": f"obs_{index + 1}",
                "entrypoint": request["call"],
                "request": request,
                "steps": [{"step": 0, "ok": True}],
            }
            for index, request in enumerate(requests)
        ]


class SplitterTests(unittest.TestCase):
    def test_parse_separates_declarations_and_functions(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        self.assertEqual([unit.name for unit in parsed.functions], ["set", "get", "other"])
        self.assertEqual(len(parsed.declarations), 3)

    def test_comments_and_strings_do_not_break_braces(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        self.assertIn("comment with", parsed.functions[0].text)
        self.assertTrue(parsed.functions[0].text.rstrip().endswith("}"))

    def test_commented_declarations_mentioning_function_do_not_break_parsing(self):
        source = """pragma solidity 0.8.30;
contract D {
    uint256 private counter; // storage slot for every function in this contract
    // this comment mentions function without declaring one
    function f() public view returns (uint256) {
        return counter;
    }
}
"""
        parsed = investigator.parse_contract(source, "D")
        self.assertEqual([unit.name for unit in parsed.functions], ["f"])
        self.assertEqual(len(parsed.declarations), 1)

    def test_identity_merge_preserves_source(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        rewrites = {unit.opaque_id: unit.text for unit in parsed.functions}
        merged, record = investigator.merge_rewrites(parsed, rewrites)
        self.assertTrue(record["applied"])
        self.assertEqual(merged, DUMMY)

    def test_complete_function_rewrite_can_change_mutability(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        setter = parsed.functions[0]
        replacement = setter.text.replace("public payable", "public")
        merged, record = investigator.merge_rewrites(parsed, {setter.opaque_id: replacement})
        self.assertTrue(record["applied"])
        self.assertIn("function set(uint256 value) public {", merged)
        self.assertIn("function get() public view returns (uint256)", merged)

    def test_body_only_rewrite_is_rejected(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        merged, record = investigator.merge_rewrites(
            parsed, {parsed.functions[0].opaque_id: "{ counter = 1; }"}
        )
        self.assertFalse(record["applied"])
        self.assertEqual(merged, DUMMY)

    def test_return_type_change_is_allowed(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        getter = parsed.functions[1]
        replacement = getter.text.replace(
            "returns (uint256)", "returns (uint256, string)"
        ).replace("return counter;", 'return (counter, "");')
        merged, record = investigator.merge_rewrites(parsed, {getter.opaque_id: replacement})
        self.assertTrue(record["applied"])
        self.assertIn("returns (uint256, string)", merged)

    def test_dispatch_signature_change_is_rejected(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        setter = parsed.functions[0]
        renamed = setter.text.replace("function set(", "function setRenamed(")
        merged, record = investigator.merge_rewrites(parsed, {setter.opaque_id: renamed})
        self.assertFalse(record["applied"])
        self.assertEqual(merged, DUMMY)
        self.assertIn(
            "dispatch signature changed", record["records"][setter.opaque_id]["error"]
        )

        retyped = setter.text.replace("uint256 value", "uint8 value")
        merged, record = investigator.merge_rewrites(parsed, {setter.opaque_id: retyped})
        self.assertFalse(record["applied"])
        self.assertEqual(merged, DUMMY)

    def test_dispatch_signature_ignores_mutability_and_return_types(self):
        header = (
            "/// @notice docs with (parens)\n"
            "function set(uint256 value, bytes memory payload) public payable returns (bool)"
        )
        self.assertEqual(
            investigator.dispatch_signature(header),
            ("set", ("uint256", "bytes")),
        )

    def test_dispatch_signature_handles_comments_inside_parameters(self):
        header = (
            "function set(\n"
            "    uint256 /* comma, ( and ) */ value,\n"
            "    address payable who\n"
            ") public"
        )
        self.assertEqual(
            investigator.dispatch_signature(header),
            ("set", ("uint256", "address")),
        )

    def test_dispatch_signature_distinguishes_array_dimensions(self):
        two = investigator.dispatch_signature(
            "function f(uint256 [2] memory values) public"
        )
        three = investigator.dispatch_signature(
            "function f(uint256 [3] memory values) public"
        )
        self.assertEqual(two, ("f", ("uint256[2]",)))
        self.assertNotEqual(two, three)

    def test_leading_declaration_is_rejected(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        setter = parsed.functions[0]
        injected = "uint256 public injected;\n" + setter.text
        with self.assertRaises(investigator.ParseError):
            investigator.parse_single_function(injected)
        merged, record = investigator.merge_rewrites(parsed, {setter.opaque_id: injected})
        self.assertFalse(record["applied"])
        self.assertEqual(merged, DUMMY)

    def test_expected_dispatch_signatures_skip_private_and_rejected_units(self):
        source = DUMMY.replace(
            "function other() public",
            "function other() internal",
        )
        parsed = investigator.parse_contract(source, "Dummy")
        records = {
            "fn_1": {"applied": True},
            "fn_2": {"applied": True},
            "fn_3": {"applied": False},
        }
        expected = investigator.expected_dispatch_signatures(parsed, records)
        self.assertEqual(expected, {"fn_1": "set(uint256)", "fn_2": "get()"})
        self.assertEqual(
            investigator.abi_signatures(
                [
                    {"type": "function", "name": "set", "inputs": [{"type": "uint256"}]},
                    {"type": "event", "name": "Changed", "inputs": []},
                ]
            ),
            {"set(uint256)"},
        )


class MergeGateTests(unittest.TestCase):
    def test_rejected_rewrites_are_reported_without_a_compile_failure(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        clusters, _ = investigator.cluster_functions(parsed)
        result = investigator.ClusterResult(
            cluster_id=clusters[0].cluster_id,
            functions=[unit.opaque_id for unit in clusters[0].functions],
        )
        result.rewrites = {
            clusters[0].functions[0].opaque_id: "function setRenamed(uint256 value) public {}"
        }
        with tempfile.TemporaryDirectory() as temporary:
            merged, report = investigator._merge_with_gate(
                DUMMY, parsed, [result], None, Path(temporary)
            )
        self.assertFalse(report["applied"])
        self.assertEqual(merged, DUMMY)
        self.assertEqual(result.merge, "rejected")
        self.assertIn("dispatch signature changed", result.error)


class ClusteringTests(unittest.TestCase):
    def test_shared_storage_and_events_cluster_together(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        clusters, unclustered = investigator.cluster_functions(parsed, max_clusters=6, max_functions=4)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(unclustered, [])
        self.assertEqual(len(clusters[0].functions), 3)

    def test_oversized_components_are_partitioned_and_capped(self):
        functions = "\n".join(
            f"function f{i}() public {{ }}" for i in range(10)
        )
        source = f"contract Many {{\n{functions}\n}}"
        parsed = investigator.parse_contract(source, "Many")
        clusters, unclustered = investigator.cluster_functions(parsed, max_clusters=6, max_functions=4)
        self.assertEqual(len(clusters), 6)
        self.assertEqual(len(unclustered), 4)
        self.assertTrue(all(len(cluster.functions) <= 4 for cluster in clusters))

    def test_clustering_is_deterministic(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        first = investigator.cluster_functions(parsed, 6, 4)
        second = investigator.cluster_functions(parsed, 6, 4)
        self.assertEqual(
            [[unit.opaque_id for unit in cluster.functions] for cluster in first[0]],
            [[unit.opaque_id for unit in cluster.functions] for cluster in second[0]],
        )


class SafetyTests(unittest.TestCase):
    def test_unknown_entrypoint_is_rejected(self):
        with self.assertRaises(investigator.InvestigatorError):
            investigator.validate_probe_request(
                {"call": "entrypoint_99"}, {"entrypoint_1": {}}, 3
            )

    def test_single_call_request_resolves_to_one_step(self):
        steps = investigator.validate_probe_request(
            {"call": "entrypoint_1", "args": ["7"]}, {"entrypoint_1": {}}, 3
        )
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["entrypoint"], "entrypoint_1")
        self.assertEqual(steps[0]["args"], ["7"])

    def test_steps_array_resolves_in_order(self):
        steps = investigator.validate_probe_request(
            {
                "steps": [
                    {"call": "entrypoint_1", "args": ["10"], "send": True},
                    {"call": "entrypoint_2"},
                ]
            },
            {"entrypoint_1": {}, "entrypoint_2": {}},
            3,
        )
        self.assertEqual([step["entrypoint"] for step in steps], ["entrypoint_1", "entrypoint_2"])
        self.assertTrue(steps[0]["send"])
        self.assertFalse(steps[1]["send"])

    def test_nested_steps_are_rejected(self):
        with self.assertRaises(investigator.InvestigatorError):
            investigator.validate_probe_request(
                {"steps": [{"steps": [{"call": "entrypoint_1"}]}]},
                {"entrypoint_1": {}},
                3,
            )

    def test_step_count_is_bounded(self):
        with self.assertRaises(investigator.InvestigatorError):
            investigator.validate_probe_request(
                {"steps": [{"call": "entrypoint_1"}] * 13},
                {"entrypoint_1": {}},
                3,
            )

    def test_step_with_unknown_entrypoint_is_rejected(self):
        with self.assertRaises(investigator.InvestigatorError):
            investigator.validate_probe_request(
                {"steps": [{"call": "entrypoint_1"}, {"call": "entrypoint_99"}]},
                {"entrypoint_1": {}},
                3,
            )

    def test_hypothesis_response_accepts_steps_only_requests(self):
        investigator._check_hypothesis_response(
            {
                "hypotheses": [
                    {
                        "function": "fn_1",
                        "claim": "setter",
                        "confidence": 0.5,
                        "probe_requests": [{"steps": [{"call": "entrypoint_1"}]}],
                    }
                ],
                "probe_requests": [{"steps": [{"call": "entrypoint_2"}]}],
                "ready_to_synthesize": False,
            },
            {"fn_1"},
        )

    def test_hypothesis_response_rejects_request_without_call_or_steps(self):
        with self.assertRaises(ValueError):
            investigator._check_hypothesis_response(
                {
                    "hypotheses": [],
                    "probe_requests": [{"args": ["1"]}],
                    "ready_to_synthesize": False,
                },
                set(),
            )

    def test_bad_tail_is_rejected(self):
        with self.assertRaises(investigator.InvestigatorError):
            investigator.validate_probe_request(
                {"call": "entrypoint_1", "args_tail": "not-hex"},
                {"entrypoint_1": {}},
                3,
            )

    def test_prompt_context_does_not_include_reference_or_withheld_sentinels(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        clusters, _ = investigator.cluster_functions(parsed)
        context = investigator._prompt_context(
            parsed,
            clusters[0],
            [{"opaque_id": "entrypoint_1", "selector": "0x12345678"}],
        )
        rendered = __import__("json").dumps(context)
        self.assertNotIn("REFERENCE_ONLY_SIGNATURE", rendered)
        self.assertNotIn("WITHHELD_PROBE", rendered)

    def test_unknown_hypothesis_function_is_rejected(self):
        with self.assertRaises(ValueError):
            investigator._check_hypothesis_response(
                {
                    "hypotheses": [{"function": "fn_99", "claim": "x", "confidence": 0.5}],
                    "probe_requests": [],
                    "ready_to_synthesize": False,
                },
                {"fn_1"},
            )

    def test_unknown_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            investigator._check_synthesis_response(
                {
                    "functions": [],
                    "claims": [{"opaque_id": "fn_1", "evidence": ["obs_99"]}],
                    "unresolved": [],
                },
                {"fn_1"},
                {"obs_1"},
            )

    def test_abi_words_splits_returndata_and_rejects_ragged_input(self):
        words = investigator.abi_words("0x" + "00" * 32 + "80" + "00" * 31)
        self.assertEqual(words, ["0x" + "00" * 32, "0x80" + "00" * 31])
        self.assertIsNone(investigator.abi_words("0x1234"))
        self.assertIsNone(investigator.abi_words(None))
        self.assertEqual(len(investigator.abi_words("0x" + "00" * 32, limit=0)), 0)

    def test_compile_error_summary_prefers_explicit_error_then_stderr(self):
        self.assertIsNone(investigator.compile_error_summary({"ok": True}))
        self.assertEqual(
            investigator.compile_error_summary({"ok": False, "error": "no artifact"}),
            "no artifact",
        )
        summary = investigator.compile_error_summary(
            {
                "ok": False,
                "stderr": "Compiling 1 files\nError (7576): Undeclared identifier.\n  --> x",
            }
        )
        self.assertEqual(summary, "Error (7576): Undeclared identifier.")
        self.assertEqual(
            investigator.compile_error_summary({"ok": False, "stderr": "", "returncode": 7}),
            "compiler exited with code 7",
        )


class BudgetTests(unittest.TestCase):
    def test_charge_counts_every_attempt_and_reports_usage(self):
        budget = investigator.Budget(max_calls=2, max_completion_tokens=10)
        budget.charge("prompt", {"completion_tokens": 4}, "content")
        budget.charge("prompt", None, None)
        self.assertEqual(budget.calls, 2)
        self.assertEqual(budget.completion_tokens, 4)
        self.assertEqual(budget.remaining_tokens(), 6)
        self.assertFalse(budget.can_call())

    def test_charge_estimates_tokens_for_unreported_usage(self):
        budget = investigator.Budget(max_calls=1, max_completion_tokens=100)
        budget.charge("prompt", None, "x" * 40)
        self.assertEqual(budget.completion_tokens, 10)

    def test_incomplete_read_is_charged(self):
        class BrokenResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                raise http.client.IncompleteRead(b"partial")

        with tempfile.TemporaryDirectory() as temporary:
            budget = investigator.Budget()
            client = investigator.ChatClient(
                base_url="http://127.0.0.1:1",
                model="model",
                api_key="",
                timeout=1,
                max_tokens=8,
                temperature=0,
                seed=1,
                response_format="auto",
                output_dir=Path(temporary),
                budget=budget,
            )
            with mock.patch(
                "urllib.request.urlopen", return_value=BrokenResponse()
            ):
                data, error, record = client.request_json("p", "s", {}, "label", "system")
        self.assertIsNone(data)
        self.assertIsNone(record)
        self.assertIn("IncompleteRead", error)
        self.assertEqual(budget.calls, 1)

    def test_request_json_stops_before_http_when_budget_is_exhausted(self):
        with tempfile.TemporaryDirectory() as temporary:
            budget = investigator.Budget(max_calls=0)
            client = investigator.ChatClient(
                base_url="http://127.0.0.1:1",
                model="model",
                api_key="",
                timeout=1,
                max_tokens=8,
                temperature=0,
                seed=1,
                response_format="auto",
                output_dir=Path(temporary),
                budget=budget,
            )
            data, error, record = client.request_json("p", "s", {}, "label", "system")
        self.assertIsNone(data)
        self.assertIsNone(record)
        self.assertIn("budget exhausted", error)
        self.assertEqual(budget.calls, 0)


class LoopTests(unittest.TestCase):
    def test_investigator_skips_synthesis_without_a_valid_response(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        clusters, _ = investigator.cluster_functions(parsed)
        functions = {unit.opaque_id: unit.text for unit in clusters[0].functions}

        class NoDataClient(FakeClient):
            def request_json(self, prompt, schema_name, schema, label, system, max_attempts=None):
                self.call_count += 1
                self.budget.charge(prompt, {"completion_tokens": 1}, "{}")
                return None, "invalid", None

        with tempfile.TemporaryDirectory() as temporary:
            config = investigator.InvestigatorConfig(
                mode="chunked-investigator",
                max_investigation_rounds=1,
            )
            worker = investigator.Investigator(
                parsed, NoDataClient(functions), FakeOracle(), config, Path(temporary)
            )
            result = worker.investigate_cluster(
                clusters[0], [{"opaque_id": "entrypoint_1", "selector": "0x12345678"}]
            )
        self.assertEqual(result.calls, 2)
        self.assertEqual(result.rewrites, {})
        self.assertEqual(result.error, "invalid")

    def test_bounded_investigator_runs_two_probe_rounds_and_synthesis(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        clusters, _ = investigator.cluster_functions(parsed)
        functions = {unit.opaque_id: unit.text for unit in clusters[0].functions}
        client = FakeClient(functions)
        oracle = FakeOracle()
        with tempfile.TemporaryDirectory() as temporary:
            config = investigator.InvestigatorConfig(
                mode="chunked-investigator",
                max_investigation_rounds=2,
                max_probes_per_round=8,
                max_probes_per_cluster=16,
                max_total_probes=64,
            )
            worker = investigator.Investigator(
                parsed, client, oracle, config, Path(temporary)
            )
            result = worker.investigate_cluster(
                clusters[0], [{"opaque_id": "entrypoint_1", "selector": "0x12345678"}]
            )
        self.assertEqual(result.calls, 3)
        self.assertEqual(result.probe_requests, 1)
        self.assertEqual(len(result.rewrites), 3)
        self.assertEqual(result.observations, ["obs_1"])
        self.assertGreater(result.confidence, 0.0)

    def test_invalid_json_retry_is_bounded(self):
        parsed = investigator.parse_contract(DUMMY, "Dummy")
        clusters, _ = investigator.cluster_functions(parsed)

        class InvalidClient(FakeClient):
            def request_json(self, prompt, schema_name, schema, label, system, max_attempts=None):
                self.call_count += 1
                self.budget.charge(prompt, {"completion_tokens": 1}, "{}")
                return {"functions": []}, None, {"mode": "fake", "content": "{}"}

        client = InvalidClient({})
        with tempfile.TemporaryDirectory() as temporary:
            config = investigator.InvestigatorConfig(mode="chunked-one-shot")
            worker = investigator.Investigator(
                parsed, client, FakeOracle(), config, Path(temporary)
            )
            result = worker.investigate_cluster(
                clusters[0], [{"opaque_id": "entrypoint_1", "selector": "0x12345678"}]
            )
        self.assertLessEqual(result.calls, 3)
        self.assertEqual(result.rewrites, {})
        self.assertIsNotNone(result.error)

    def test_parse_failure_falls_back_to_original_source(self):
        client = FakeClient({})
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            source = "not a contract"
            merged, metrics = investigator.run_investigator(
                source, None, investigator.InvestigatorConfig(), client, output
            )
            self.assertEqual(merged, source)
            self.assertIn("parse_error", metrics)
            self.assertEqual((output / "candidate.sol").read_text(), source)


if __name__ == "__main__":
    unittest.main()
