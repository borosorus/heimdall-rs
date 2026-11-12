import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "evaluation" / "scripts" / "rebuild_guarded_view.py"
SPEC = importlib.util.spec_from_file_location("rebuild_guarded_view", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

FIXTURE = (
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
    "}\n"
)

# siblings the gate tests need: a parameterized, a pure, and a tuple-return unit
WIDER = FIXTURE.replace(
    "}\n",
    (
        "    function bar(uint256 a) public view returns (uint256) { return a; }\n"
        "    function pureone() public pure returns (uint256) { return 1; }\n"
        "    function tworet() public view returns (uint256, uint256) { return (v, v); }\n"
        "}\n"
    ),
)


class RebuildGuardedViewTests(unittest.TestCase):
    def test_rebuild_is_gated_clean(self):
        out = module.rebuild(FIXTURE, "foo", "v != 0", "nope", "v")
        self.assertIn('require(v != 0, "nope");', out)
        self.assertIn("        return v;", out)
        # name, selector comments, and signature survive verbatim
        self.assertIn("/// @custom:selector    0x11111111", out)
        self.assertIn("function foo() public view returns (uint256) {", out)
        self.assertNotIn("if (v > 0)", out)

    def test_rebuild_preserves_sibling_units(self):
        out = module.rebuild(WIDER, "foo", "v != 0", "nope", "v")
        self.assertIn("function bar(uint256 a) public view returns (uint256) { return a; }", out)
        self.assertIn("function tworet() public view returns (uint256, uint256)", out)

    def test_rebuild_is_idempotent(self):
        once = module.rebuild(FIXTURE, "foo", "v != 0", "nope", "v")
        twice = module.rebuild(once, "foo", "v != 0", "nope", "v")
        self.assertEqual(once, twice)

    def test_commented_require_does_not_satisfy_msg_gate(self):
        commented = (
            "contract C {\n"
            "    uint256 v;\n"
            "    function foo() public view returns (uint256) {\n"
            '        // require(v != 1, "nope");\n'
            "        return v;\n"
            "    }\n"
            "}\n"
        )
        with self.assertRaises(module.GateError) as caught:
            module.rebuild(commented, "foo", "v != 0", "nope", "v")
        self.assertIn("require", str(caught.exception))

    def test_string_parens_do_not_skew_span_scan(self):
        tricky = (
            "contract C {\n"
            "    uint256 v;\n"
            "    function foo() public view returns (uint256) {\n"
            '        require(v != 1, "no)pe");\n'
            "        return v;\n"
            "    }\n"
            "}\n"
        )
        out = module.rebuild(tricky, "foo", "v != 0", "no)pe", "v")
        self.assertIn('require(v != 0, "no)pe");', out)

    def test_gates_reject(self):
        # (case, expected fragment of the gate error or None, rebuild kwargs)
        cases = [
            ("missing-unit", "not found", (FIXTURE, "zzz", "v", "nope", "v")),
            ("has-params", "parameters", (WIDER, "bar", "v", "nope", "v")),
            ("not-view", "not declared view", (WIDER, "pureone", "v", "nope", "v")),
            ("tuple-return", "tuple", (WIDER, "tworet", "v", "nope", "v")),
            ("msg-gate", "require", (FIXTURE, "foo", "v", "absent", "v")),
            ("statement-in-expr", ";", (FIXTURE, "foo", "v; v", "nope", "v")),
            ("unbalanced-expr", "unbalanced", (FIXTURE, "foo", "(v", "nope", "v")),
            ("empty-expr", "empty", (FIXTURE, "foo", " ", "nope", "v")),
        ]
        for name, expected, args in cases:
            with self.subTest(case=name):
                with self.assertRaises(module.GateError) as caught:
                    module.rebuild(*args)
                self.assertIn(expected, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
