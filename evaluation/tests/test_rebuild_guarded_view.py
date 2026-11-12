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


class RebuildGuardedViewTests(unittest.TestCase):
    def test_rebuild_is_gated_clean(self):
        out = module.rebuild(FIXTURE, "foo", "v != 0", "nope", "v")
        self.assertIn('require(v != 0, "nope");', out)
        self.assertIn("        return v;", out)
        self.assertIn("/// @custom:selector    0x11111111", out)
        self.assertIn("function foo() public view returns (uint256) {", out)
        self.assertNotIn("if (v > 0)", out)
        self.assertIn("}\n", out)

    def test_rebuild_preserves_sibling_units(self):
        wider = FIXTURE.replace("}\n", "    function bar2() public pure returns (uint256) { return 2; }\n}\n")
        out = module.rebuild(wider, "foo", "v != 0", "nope", "v")
        self.assertIn("function bar2() public pure returns (uint256)", out)

    def test_rebuild_is_idempotent(self):
        once = module.rebuild(FIXTURE, "foo", "v != 0", "nope", "v")
        twice = module.rebuild(once, "foo", "v != 0", "nope", "v")
        self.assertEqual(once, twice)

    def test_gates_reject(self):
        cases = [
            ("missing", dict(source=FIXTURE, unit_name="zzz", guard="v", msg="nope", value_expr="v"), "not found"),
            ("params", dict(source=FIXTURE, unit_name="bar", guard="v", msg="nope", value_expr="v"), None),
            ("not-view", dict(source=FIXTURE, unit_name="pureone", guard="v", msg="nope", value_expr="v"), None),
            ("tuple", dict(source=FIXTURE, unit_name="tworet", guard="v", msg="nope", value_expr="v"), None),
            ("msg-gate", dict(source=FIXTURE, unit_name="foo", guard="v", msg="absent", value_expr="v"), "require"),
            ("separator", dict(source=FIXTURE, unit_name="foo", guard="v; v", msg="nope", value_expr="v"), ";"),
            ("unbalanced", dict(source=FIXTURE, unit_name="foo", guard="(v", msg="nope", value_expr="v"), "unbalanced"),
        ]
        # bar/pureone/tworet do not exist in the minimal FIXTURE; build a wider one for them
        wider = FIXTURE.replace(
            "}\n",
            (
                "    function bar(uint256 a) public view returns (uint256) { return a; }\n"
                "    function pureone() public pure returns (uint256) { return 1; }\n"
                "    function tworet() public view returns (uint256, uint256) { return (v, v); }\n"
                "}\n"
            ),
        )
        expected = {
            "params": "parameters",
            "not-view": "not declared view",
            "tuple": "tuple",
        }
        for name, kwargs, needle in cases:
            kwargs = dict(kwargs)
            if kwargs["unit_name"] != "zzz" and kwargs["unit_name"] != "foo":
                kwargs["source"] = wider
            with self.subTest(case=name):
                with self.assertRaises(module.GateError) as caught:
                    module.rebuild(**kwargs)
                if needle:
                    self.assertIn(needle, str(caught.exception))
                if name in expected:
                    self.assertIn(expected[name], str(caught.exception))


if __name__ == "__main__":
    unittest.main()
