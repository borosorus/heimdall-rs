import importlib.util
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
prepare = _load("prepare_candidate", ROOT / "evaluation" / "scripts" / "prepare_candidate.py")


def _functions(source):
    return investigator.parse_contract(source, None).functions


class PlaceholderTest(unittest.TestCase):
    def test_rewrites_code_tokens_only(self):
        source = (
            "contract C {\n"
            "    function f(uint0 a, bytes0 b) public { string memory s = \"uint0\"; } // int0 note\n"
            "    uint0 x;\n"
            "}\n"
        )
        stage = prepare.normalize_placeholders(source)
        self.assertIn("uint256 a, bytes b", stage.source)
        self.assertIn('"uint0"', stage.source)
        self.assertIn("// int0 note", stage.source)
        self.assertIn("uint256 x;", stage.source)
        self.assertNotIn("uint0 ", stage.source.split('"')[2])
        self.assertEqual(len(stage.edits), 3)

    def test_idempotent(self):
        source = "contract C { function f(uint256 a) public {} }\n"
        again = prepare.normalize_placeholders(prepare.normalize_placeholders(source).source)
        self.assertEqual(again.source, source)
        self.assertEqual(again.edits, [])


class DeclarationTest(unittest.TestCase):
    SOURCE = (
        "contract C {\n"
        "    error Known();\n"
        "    function f(uint256 a) public { require(a > 0, CustomError_1234abcd(a)); }\n"
        "    function g() public { emit Event_beefcafe(1, 2); }\n"
        "}\n"
    )

    def test_declares_missing_error_and_event_with_site_arity(self):
        stage = prepare.declare_missing_symbols(self.SOURCE)
        self.assertIn("error CustomError_1234abcd(uint256);", stage.source)
        self.assertIn("event Event_beefcafe(uint256, uint256);", stage.source)
        self.assertIn("error Known();", stage.source)

    def test_inserts_after_existing_declaration_block(self):
        stage = prepare.declare_missing_symbols(self.SOURCE)
        error_pos = stage.source.index("error Known();")
        new_pos = stage.source.index("error CustomError_1234abcd")
        self.assertGreater(new_pos, error_pos)
        self.assertGreater(stage.source.index("function f"), new_pos)

    def test_retypes_declared_event_from_usage(self):
        source = (
            "contract C {\n"
            "    event Empty();\n"
            "    function f(uint256 a) public { emit Empty(a, 2); }\n"
            "}\n"
        )
        stage = prepare.declare_missing_symbols(source)
        self.assertIn("event Empty(uint256, uint256);", stage.source)
        self.assertEqual(stage.edits[0]["kind"], "event-arity-retype")

    def test_conflicting_usage_types_remain_a_finding(self):
        source = (
            "contract C {\n"
            "    event Empty();\n"
            "    function f(uint256 a) public {\n"
            "        if (a > 0) { emit Empty(a); } else { emit Empty(msg.sender); }\n"
            "    }\n"
            "}\n"
        )
        stage = prepare.declare_missing_symbols(source)
        self.assertIn("event Empty();", stage.source)
        self.assertTrue(any(i["kind"] == "event-arity-mismatch" for i in stage.findings))

    def test_ambiguous_call_arity_is_a_finding(self):
        source = (
            "contract C {\n"
            "    function f(uint256 a) public {\n"
            "        if (a > 0) { require(a, CustomError_11223344(a)); }\n"
            "        require(a, CustomError_11223344(a, a));\n"
            "    }\n"
            "}\n"
        )
        stage = prepare.declare_missing_symbols(source)
        self.assertNotIn("error CustomError_11223344", stage.source)
        self.assertTrue(any(i["kind"] == "undeclared-error" for i in stage.findings))


class UndefinedVarsTest(unittest.TestCase):
    def test_declares_var_identifiers_once(self):
        source = (
            "contract C {\n"
            "    function f() public returns (uint256) { return var_a + var_a; }\n"
            "}\n"
        )
        stage = prepare.declare_undefined_vars(source)
        self.assertEqual(stage.source.count("uint256 var_a;"), 1)
        self.assertEqual(len(stage.edits), 1)

    def test_leaves_declared_vars_alone(self):
        source = (
            "contract C {\n"
            "    uint256 var_a;\n"
            "    function f() public returns (uint256) { var_a = 1; return var_a; }\n"
            "}\n"
        )
        stage = prepare.declare_undefined_vars(source)
        self.assertEqual(stage.source, source)
        self.assertEqual(stage.edits, [])


class GuardArityTest(unittest.TestCase):
    def test_head_guard_words_parses_word_count(self):
        body = "require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);"
        self.assertEqual(prepare.head_guard_words(body), 3)
        self.assertIsNone(prepare.head_guard_words("require(true);"))
        self.assertIsNone(prepare.head_guard_words("require(msg.data.length >= 0x21);"))

    def test_extends_arity_when_guard_proves_more_params(self):
        source = (
            "contract C {\n"
            "    function Unresolved_23b872dd(uint256 arg0) public payable {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);\n"
            "        storage_map[arg0][msg.sender] = 1;\n"
            "    }\n"
            "}\n"
        )
        stage = prepare.align_arities(source)
        self.assertIn(
            "function Unresolved_23b872dd(uint256 arg0, uint256 arg1, uint256 arg2) public payable",
            stage.source,
        )
        self.assertEqual(stage.edits[0]["kind"], "arity-extend")

    def test_trims_unused_params_when_guard_proves_fewer(self):
        source = (
            "contract C {\n"
            "    function Unresolved_c47f0027(uint256 arg0, uint256 arg1) public payable {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n"
            "        store[arg0] = 1;\n"
            "    }\n"
            "}\n"
        )
        stage = prepare.align_arities(source)
        self.assertIn(
            "function Unresolved_c47f0027(uint256 arg0) public payable",
            stage.source,
        )
        self.assertEqual(stage.edits[0]["kind"], "arity-trim")

    def test_abstains_when_excess_param_is_referenced(self):
        source = (
            "contract C {\n"
            "    function f(uint256 arg0, uint256 arg1) public view {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n"
            "        g(arg1);\n"
            "    }\n"
            "    function g(uint256 a) internal {}\n"
            "}\n"
        )
        stage = prepare.align_arities(source)
        self.assertIn("function f(uint256 arg0, uint256 arg1)", stage.source)
        self.assertTrue(any(i["kind"] == "arity-trim" for i in stage.findings))

    def test_functions_without_guards_are_untouched(self):
        source = "contract C { function f(uint256 a) public pure { revert(); } }\n"
        stage = prepare.align_arities(source)
        self.assertEqual(stage.source, source)
        self.assertEqual(stage.edits, [])


class SlotAliasTest(unittest.TestCase):
    SEED = (
        "contract D {\n"
        "    address ownerAlias; // storage slot: 0x00\n"
        "    bytes32 cell; // storage slot: 0x00\n"
        "    uint256 other; // storage slot: 0x01\n"
        "\n"
        "    function write(address a) public {\n"
        "        cell = bytes32(uint256(uint160(a)));\n"
        "    }\n"
        "\n"
        "    function who() public view returns (address) {\n"
        "        return ownerAlias;\n"
        "    }\n"
        "}\n"
    )

    def test_read_alias_becomes_cast_of_the_written_view(self):
        stage = prepare.unify_storage_views(self.SEED)
        self.assertEqual(stage.edits[0]["kind"], "slot-alias")
        # The alias declaration is removed; the written view stays canonical.
        self.assertNotIn("address ownerAlias;", stage.source)
        self.assertIn("bytes32 cell; // storage slot: 0x00", stage.source)
        self.assertIn("return address(uint160(uint256(cell)));", stage.source)
        self.assertIn("cell = bytes32(uint256(uint160(a)));", stage.source)

    def test_written_alias_abstains(self):
        source = self.SEED.replace(
            "        cell = bytes32(uint256(uint160(a)));\n    }",
            "        cell = bytes32(uint256(uint160(a)));\n        ownerAlias = a;\n    }",
        )
        self.assertIn("ownerAlias = a;", source)  # the variant was actually built
        stage = prepare.unify_storage_views(source)
        self.assertEqual(stage.source, source)
        self.assertTrue(any(f["kind"] == "slot-alias" for f in stage.findings))

    def test_unknown_type_pair_abstains(self):
        source = self.SEED.replace("    address ownerAlias;", "    string ownerAlias;")
        stage = prepare.unify_storage_views(source)
        self.assertEqual(stage.source, source)
        self.assertTrue(any("no proven conversion" in f["reason"] for f in stage.findings))

    def test_no_slot_comments_is_a_noop(self):
        source = "contract D {\n    uint256 a;\n    uint256 b;\n}\n"
        stage = prepare.unify_storage_views(source)
        self.assertEqual(stage.source, source)
        self.assertEqual(stage.edits, [])


class ReviewRegressionTest(unittest.TestCase):
    def test_placeholder_rewrite_keeps_identifier_suffixes(self):
        source = "contract D { function mint0(uint256 x) public {} uint0 y; }\n"
        stage = prepare.normalize_placeholders(source)
        self.assertIn("function mint0(uint256 x)", stage.source)
        self.assertIn("uint256 y;", stage.source)

    def test_slot_alias_requires_writer_narrowing_evidence(self):
        source = (
            "contract D {\n"
            "    address ownerAlias; // storage slot: 0x00\n"
            "    bytes32 cell; // storage slot: 0x00\n"
            "    function write(address a) public { cell = bytes32(a); }\n"
            "    function who() public view returns (address) { return ownerAlias; }\n"
            "}\n"
        )
        stage = prepare.unify_storage_views(source)
        self.assertEqual(stage.source, source)
        self.assertTrue(any("uint160" in f["reason"] for f in stage.findings))

    def test_slot_alias_abstains_on_member_or_indexed_reads(self):
        source = (
            "contract D {\n"
            "    address ownerAlias; // storage slot: 0x00\n"
            "    bytes32 cell; // storage slot: 0x00\n"
            "    function write(address a) public { cell = bytes32(uint256(uint160(a))); }\n"
            "    function who() public view returns (bytes1) { return ownerAlias[0]; }\n"
            "}\n"
        )
        stage = prepare.unify_storage_views(source)
        self.assertEqual(stage.source, source)
        self.assertTrue(any("non-whole-word" in f["reason"] for f in stage.findings))

    def test_arity_alignment_abstains_on_dynamic_params(self):
        source = (
            "contract D {\n"
            "    function f(bytes calldata b) public pure {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);\n"
            "        require(b.length > 0);\n"
            "    }\n"
            "}\n"
        )
        stage = prepare.align_arities(source)
        self.assertIn("function f(bytes calldata b)", stage.source)
        self.assertTrue(any("dynamic or composite" in f["reason"] for f in stage.findings))


class PipelineTest(unittest.TestCase):
    BASELINE = (
        "contract DecompiledContract {\n"
        "    error CustomError_00000000();\n"
        "    event Event_8c5be1e5();\n"
        "    address store_h;\n"
        "    mapping(address => uint256) public balances;\n"
        "\n"
        "    function Unresolved_095ea7b3(address arg0, uint0 arg1) public payable returns (bool) {\n"
        "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);\n"
        "        balances[msg.sender] = arg1;\n"
        "        require(msg.sender == store_h, CustomError_30cd7471());\n"
        "        return true;\n"
        "    }\n"
        "}\n"
    )

    def test_full_ladder_applies_every_tier(self):
        stages = prepare.prepare_stages(self.BASELINE)
        self.assertEqual(
            [stage.name for stage in stages],
            [
                "placeholders",
                "declarations",
                "selfref",
                "vars",
                "mutability",
                "arity",
                "slot-aliases",
                "packed-scalars",
                "truthiness",
                "fallback-shape",
                "param-types",
                "storage-getters",
                "send-guards",
                "typed-packed-literals",
                "wordify-address-mask",
                "widen-packed-pair-returns",
                "coerce-word-returns",
                "lower-unknown-external-calls",
            ],
        )
        final = stages[-1].source
        self.assertIn("uint256 arg1", final)
        self.assertIn("error CustomError_30cd7471();", final)

    def test_widen_skips_bytes_memory_returns(self):
        # reviewer: a valid bytes-memory packed-pair return must NOT be widened
        # (its returndata is the dynamic-value encoding, not two head words)
        source = (
            "contract C {\n"
            "    uint256 a; uint256 b;\n"
            "    function f() public view returns (bytes memory) {\n"
            "        return abi.encodePacked(a, b);\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)
        widen = next(st for st in staged if st.name == "widen-packed-pair-returns")
        assert widen.edits == [], "bytes-memory return was widened"

    def test_ladder_is_idempotent(self):
        once = prepare.prepare_stages(self.BASELINE)[-1].source
        twice = prepare.prepare_stages(once)[-1].source
        self.assertEqual(once, twice)

    def test_parse_error_is_reported(self):
        with self.assertRaises(prepare.PreparationError):
            prepare.prepare_stages("not solidity")


class SeedRuleTests(unittest.TestCase):
    def test_selfreferential_initializer_is_split(self):
        source = (
            "contract C {\n"
            "    function f() public pure {\n"
            "        uint256 var_b = var_b + 0x60;\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("uint256 var_b;\n", staged)
        self.assertIn("var_b = var_b + 0x60;", staged)
        self.assertNotIn("uint256 var_b = var_b", staged)

    def test_selfreferential_split_respects_outer_binding(self):
        source = (
            "contract C {\n"
            "    uint256 var_b;\n"
            "    function f() public view {\n"
            "        uint256 var_b = var_b + 0x60;\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        # an outer binding exists: the local shadowing declaration is legal, keep it
        self.assertIn("uint256 var_b = var_b + 0x60;", staged)

    def test_pure_reading_state_is_relaxed_to_view(self):
        source = (
            "contract C {\n"
            "    uint256 var_c;\n"
            "    function f() public pure {\n"
            "        if (0 < var_c) {\n"
            "            return;\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("function f() public view {", staged)

    def test_pure_with_only_shadowed_state_name_stays_pure(self):
        source = (
            "contract C {\n"
            "    uint256 var_c;\n"
            "    function f(uint256 var_c) public pure returns (uint256) {\n"
            "        return var_c + 1;\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("function f(uint256 var_c) public pure returns (uint256) {", staged)

    def test_mutability_reads_modified_and_mapping_state(self):
        source = (
            "contract C {\n"
            "    uint256 public var_c;\n"
            "    mapping(address => uint256) public balances;\n"
            "    uint256[] var_a;\n"
            "    function f() public pure returns (uint256) {\n"
            "        return var_c + balances(address(0)) + var_a.length;\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("function f() public view returns (uint256) {", staged)

    def test_truthiness_require_on_msg_sender_is_rewritten(self):
        source = (
            "contract C {\n"
            "    error E();\n"
            "    function f() public view {\n"
            "        require(msg.sender, E());\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("require(msg.sender != address(0), E());", staged)

    def test_truthiness_require_abstains_on_unknown_expr(self):
        source = (
            "contract C {\n"
            "    error E();\n"
            "    function f(string memory s) public pure {\n"
            "        require(s, E());\n"
            "        return;\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("require(s, E());", staged)

    def test_fallback_selector_check_and_return_shape(self):
        source = (
            "contract C {\n"
            "    fallback() external payable {\n"
            "        require(msg.data.length >= 0x04);\n"
            "        require(0x819439 == msg.data[0] >> 0xe0);\n"
            "        return abi.encodePacked(block.number, block.timestamp);\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("fallback(bytes calldata) external payable returns (bytes memory)", staged)
        self.assertIn("require(uint32(bytes4(msg.data[0:4])) == 0x819439);", staged)

    def test_truthiness_require_on_address_param_is_rewritten(self):
        source = (
            "contract C {\n"
            "    error E();\n"
            "    function f(address arg0) public pure {\n"
            "        require(arg0, E());\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("require(arg0 != address(0), E());", staged)

    def test_arity_extend_syncs_signature_comment(self):
        source = (
            "contract C {\n"
            "    /// @custom:selector    0x23b872dd\n"
            "    /// @custom:signature   Unresolved_23b872dd(address arg0) public pure\n"
            "    /// @param              arg0 [\"address\", \"uint160\"]\n"
            "    function Unresolved_23b872dd(address arg0) public pure {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn(
            "function Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public pure {",
            staged,
        )
        # provenance must name the same canonical signature as the declaration
        self.assertIn(
            "/// @custom:signature   Unresolved_23b872dd(address arg0, uint256 arg1, uint256 arg2) public pure",
            staged,
        )
        self.assertNotIn(
            "/// @custom:signature   Unresolved_23b872dd(address arg0) public pure", staged
        )

    def test_arity_trim_syncs_signature_comment(self):
        source = (
            "contract C {\n"
            "    /// @custom:signature   f(uint256 arg0, uint256 arg1) public pure\n"
            "    function f(uint256 arg0, uint256 arg1) public pure returns (uint256) {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n"
            "        return arg0;\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("function f(uint256 arg0) public pure returns (uint256) {", staged)
        self.assertIn("/// @custom:signature   f(uint256 arg0) public pure", staged)

    def test_fallback_value_return_encodes_not_packs(self):
        source = (
            "contract C {\n"
            "    fallback() external payable {\n"
            "        require(msg.data.length >= 0x04);\n"
            "        require(0x819439 == msg.data[0] >> 0xe0);\n"
            "        return abi.encodePacked(block.number, address(block.coinbase));\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("fallback(bytes calldata) external payable returns (bytes memory)", staged)
        self.assertIn("return abi.encode(block.number, address(block.coinbase));", staged)
        self.assertNotIn("abi.encodePacked", staged)

    def test_fallback_without_return_value_is_untouched(self):
        source = (
            "contract C {\n"
            "    event Done();\n"
            "    fallback() external payable {\n"
            "        emit Done();\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("fallback() external payable {", staged)

    def test_storage_getter_synthesized_from_unique_mapping_match(self):
        source = (
            "contract C {\n"
            "    mapping(address => mapping(address => uint256)) storage_map_b; // storage slot: 0x01\n"
            "    /// @custom:signature   Unresolved_dd62ed3e(address arg0, uint256 arg1) public pure\n"
            "    function Unresolved_dd62ed3e(address arg0, uint256 arg1) public pure {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn(
            "function Unresolved_dd62ed3e(address arg0, address arg1) public view returns (uint256) {",
            staged,
        )
        # arg1 is a generic-uint word; the address key gets the explicit narrowing
        self.assertIn("return storage_map_b[arg0][arg1];", staged)
        # provenance comment stays in sync with the new mutability/returns
        self.assertIn(
            "Unresolved_dd62ed3e(address arg0, address arg1) public view returns (uint256)",
            staged,
        )

    def test_storage_getter_abstains_when_return_type_differs(self):
        source = (
            "contract C {\n"
            "    mapping(address => uint256) storage_map_a; // storage slot: 0x00\n"
            "    /// @custom:signature   f(address arg0) public view returns (string memory)\n"
            "    function f(address arg0) public view returns (string memory) {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        # value uint256 != declared string return: no synthesis, body untouched
        self.assertNotIn("return storage_map_a[arg0];", staged)

    def test_storage_getter_needs_no_declared_return(self):
        source = (
            "contract C {\n"
            "    mapping(address => uint256) balances; // storage slot: 0x00\n"
            "    /// @custom:signature   balanceOf(address arg0) public pure\n"
            "    function balanceOf(address arg0) public pure {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("function balanceOf(address arg0) public view returns (uint256) {", staged)
        self.assertIn("return balances[arg0];", staged)
        # provenance comment mirrors mutability AND returns on this path too
        self.assertIn(
            "/// @custom:signature   balanceOf(address arg0) public view returns (uint256)",
            staged,
        )

    def test_storage_getter_reference_value_gets_memory_location(self):
        source = (
            "contract C {\n"
            "    mapping(address => string) names; // storage slot: 0x00\n"
            "    function nameOf(address arg0) public pure {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("function nameOf(address arg0) public view returns (string memory) {", staged)

    def test_send_guard_transplanted_from_guarding_sibling(self):
        source = (
            "contract C {\n"
            "    mapping(address => uint256) public balances; // storage slot: 0x00\n"
            "    function transfer(address arg0, uint256 arg1) public payable returns (bool) {\n"
            "        require(balances[msg.sender] >= arg1);\n"
            "        balances[msg.sender] -= arg1;\n"
            "        return true;\n"
            "    }\n"
            "    function transferFrom(address arg0, address arg1, uint256 arg2) public pure {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);\n"
            "        require(true);\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        self.assertIn("require(balances[arg0] >= arg2);", staged)
        stages = prepare.prepare_stages(source)
        sg = next(st for st in stages if st.name == "send-guards")
        record = next(e for e in sg.edits if e["kind"] == "send-guard")
        # recorded precedent names the sibling and the mapping
        self.assertIn("precedent transfer on balances", record["detail"])

    def test_param_retyped_from_storage_map_key(self):
        source = (
            "contract C {\n"
            "    mapping(address => mapping(address => uint256)) storage_map_b; // storage slot: 0x01\n"
            "    /// @custom:signature   allowance(address arg0, uint256 arg1) public pure\n"
            "    function allowance(address arg0, uint256 arg1) public pure {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x40);\n"
            "    }\n"
            "}\n"
        )
        stages = prepare.prepare_stages(source)
        final = stages[-1].source
        # arg1 re-typed to the map's second address key, declaration AND comment
        self.assertIn("function allowance(address arg0, address arg1) public view returns (uint256) {", final)
        self.assertIn(
            "/// @custom:signature   allowance(address arg0, address arg1) public view returns (uint256)", final
        )
        self.assertIn("return storage_map_b[arg0][arg1];", final)
        param_stage = next(s for s in stages if s.name == "param-types")
        record = next(e for e in param_stage.edits if e["kind"] == "param-retyped")
        self.assertIn("map keys", record["detail"])

    def test_param_retype_abstains_without_map_evidence(self):
        source = (
            "contract C {\n"
            "    function f(uint256 arg0) public pure {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x20);\n"
            "    }\n"
            "}\n"
        )
        final = prepare.prepare_stages(source)[-1].source
        self.assertIn("function f(uint256 arg0) public pure {", final)

    def test_send_guard_abstains_without_guarding_sibling(self):
        source = (
            "contract C {\n"
            "    mapping(address => uint256) public balances; // storage slot: 0x00\n"
            "    function transferFrom(address arg0, address arg1, uint256 arg2) public pure {\n"
            "        require(0x04 + (msg.data.length - 0x04) - 0x04 >= 0x60);\n"
            "        require(true);\n"
            "    }\n"
            "}\n"
        )
        stages = prepare.prepare_stages(source)
        staged = stages[-1].source
        # no sibling guards+mutates balances: the stub stays untouched
        self.assertNotIn("require(balances[arg0] >= arg2);", staged)
        sg = next(st for st in stages if st.name == "send-guards")
        record = next(e for e in sg.edits if e["kind"] == "send-guard-abstain")
        self.assertIn("0 guarded-and-mutated mappings", record["detail"])

    def test_send_guard_skips_functions_with_bodies(self):
        source = (
            "contract C {\n"
            "    mapping(address => uint256) public balances; // storage slot: 0x00\n"
            "    function transfer(address arg0, uint256 arg1) public payable returns (bool) {\n"
            "        require(balances[msg.sender] >= arg1);\n"
            "        balances[msg.sender] -= arg1;\n"
            "        return true;\n"
            "    }\n"
            "    function sweep(address arg0) public payable returns (bool) {\n"
            "        require(balances[arg0] >= 1);\n"
            "        balances[arg0] -= 1;\n"
            "        return true;\n"
            "    }\n"
            "}\n"
        )
        staged = prepare.prepare_stages(source)[-1].source
        # both functions already carry guards; nothing qualifies as a stub
        self.assertNotIn("precedent", staged)


class PackedScalarTest(unittest.TestCase):
    BASE = (
        "contract C {\n"
        "    bytes c; // storage slot: 0x02\n"
        "    bytes d; // storage slot: 0x03\n"
        "    error E();\n"
        "    function set(uint256 a) public { c = abi.encodePacked(a); }\n"
        "    function setD(uint256 a) public { d = abi.encodePacked(a); }\n"
        "    function chk(uint256 x) public view returns (bool) { return x < c.length; }\n"
        "    function guard(uint256 x) public view { require(x >= uint256(c.length), E()); }\n"
        "    function pair() public view returns (bytes memory) { return abi.encodePacked(c, d); }\n"
        "}\n"
    )

    def test_recovers_uint256_packed_storage(self):
        stage = prepare.recover_packed_scalar_storage(self.BASE)
        self.assertEqual(stage.name, "packed-scalars")
        self.assertEqual([edit["detail"] for edit in stage.edits], ["c: bytes -> uint256 (slot 0x02)"])
        self.assertIn("uint256 c; // storage slot: 0x02", stage.source)
        self.assertIn("c = a;", stage.source)
        self.assertIn("x < c;", stage.source)
        self.assertIn("require(x >= uint256(c), E());", stage.source)
        self.assertIn("abi.encodePacked(c, d)", stage.source)  # legal: two packed words
        self.assertIn("bytes d; // storage slot: 0x03", stage.source)  # no length reader: untouched

    def test_multiple_writes_abstain(self):
        source = self.BASE.replace(
            "    function setD(uint256 a) public { d = abi.encodePacked(a); }",
            "    function set2(uint256 a) public { if (a > 0) { c = abi.encodePacked(a); } }",
        )
        stage = prepare.recover_packed_scalar_storage(source)
        self.assertEqual(stage.edits, [])
        self.assertTrue(any("packed writer" in finding["reason"] for finding in stage.findings))
        self.assertIn("bytes c;", stage.source)

    def test_dynamic_or_non_uint256_input_abstains(self):
        bytes_arg = self.BASE.replace(
            "function set(uint256 a) public { c = abi.encodePacked(a); }",
            "function set(bytes memory b) public { c = abi.encodePacked(b); }",
        )
        two_args = self.BASE.replace(
            "c = abi.encodePacked(a);",
            "c = abi.encodePacked(a, a);",
        )
        narrow = self.BASE.replace("function set(uint256 a)", "function set(uint128 a)")
        for source in (bytes_arg, two_args, narrow):
            stage = prepare.recover_packed_scalar_storage(source)
            self.assertEqual(stage.edits, [], source[:60])
            self.assertTrue(stage.findings)

    def test_unclassified_storage_use_abstains(self):
        source = self.BASE.replace(
            "    function pair() public view returns (bytes memory) { return abi.encodePacked(c, d); }",
            "    function zap() public { delete c; }",
        )
        stage = prepare.recover_packed_scalar_storage(source)
        self.assertEqual(stage.edits, [])
        self.assertTrue(any("unclassified occurrence" in finding["reason"] for finding in stage.findings))

    def test_masks_comments_and_strings(self):
        commented = self.BASE.replace(
            "    error E();",
            "    // bytes zz; zz = abi.encodePacked(q); if (q < zz.length) {}\n"
            '    string memory note = "bytes zz;";\n'
            "    error E();",
        )
        stage = prepare.recover_packed_scalar_storage(commented)
        self.assertEqual([edit["detail"] for edit in stage.edits], ["c: bytes -> uint256 (slot 0x02)"])
        self.assertIn("// bytes zz; zz = abi.encodePacked(q); if (q < zz.length) {}", stage.source)
        self.assertNotIn("uint256 zz", stage.source)

    def test_recovery_is_idempotent(self):
        once = prepare.recover_packed_scalar_storage(self.BASE)
        twice = prepare.recover_packed_scalar_storage(once.source)
        self.assertEqual(twice.edits, [])
        self.assertEqual(once.source, twice.source)

    def test_fixture_sources_are_unchanged(self):
        fixtures = sorted((ROOT / "evaluation" / "fixtures").glob("*/*.sol"))
        self.assertGreaterEqual(len(fixtures), 9)
        for path in fixtures:
            source = path.read_text(encoding="utf-8")
            try:
                stage = prepare.recover_packed_scalar_storage(source)
            except Exception as error:  # parse differences in legacy fixtures
                raise AssertionError(f"{path}: {error}")
            self.assertEqual(stage.source, source, str(path))

    def test_stage_runs_after_slot_aliases_in_pipeline(self):
        stages = prepare.prepare_stages(self.BASE)
        names = [stage.name for stage in stages]
        self.assertGreater(names.index("packed-scalars"), names.index("slot-aliases"))
        self.assertIn("uint256 c;", stages[-1].source)


if __name__ == "__main__":
    unittest.main()
