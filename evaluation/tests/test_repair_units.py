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
repair = _load("repair_units", ROOT / "evaluation" / "scripts" / "repair_units.py")

SOURCE = """// SPDX-License-Identifier: MIT
contract C {
    uint256 stored;

    function first(uint256 a) public returns (uint256) {
        return undeclared_a + a;
    }

    function second(bytes32 b) public view returns (uint256) {
        return uint256(b) / undeclared_b;
    }
}
"""

COMPILE_RECORD = {
    "ok": False,
    "stderr": (
        "Error (7576): Undeclared identifier.\n"
        "  --> src/Candidate.sol:7:16:\n"
        "   |\n"
        "7 |         return undeclared_a + a;\n"
        "Error (7576): Undeclared identifier.\n"
        "  --> src/Candidate.sol:10:28:\n"
        "   |\n"
        "10 |         return uint256(b) / undeclared_b;\n"
    ),
    "stdout": "",
}


def _parsed():
    return investigator.parse_contract(SOURCE, "C")


class AffectedUnitsTest(unittest.TestCase):
    def test_maps_diagnostics_to_units(self):
        parsed = _parsed()
        affected = repair.affected_units(parsed, COMPILE_RECORD)
        self.assertEqual([unit.name for unit in affected], ["first", "second"])

    def test_ignores_foreign_lines(self):
        record = {"ok": False, "stderr": "--> src/Candidate.sol:200:1:\n", "stdout": ""}
        self.assertEqual(repair.affected_units(_parsed(), record), [])

    def test_record_without_locations_affects_nothing(self):
        self.assertEqual(repair.affected_units(_parsed(), {"ok": False, "stderr": "boom"}), [])


class DiagnosticsTest(unittest.TestCase):
    def test_scopes_diagnostics_to_the_unit(self):
        parsed = _parsed()
        unit = parsed.functions[0]
        text = repair.diagnostics_for(COMPILE_RECORD, parsed, unit)
        self.assertIn("undeclared_a", text)
        self.assertNotIn("undeclared_b", text)

    def test_deduplicates_blocks(self):
        parsed = _parsed()
        unit = parsed.functions[0]
        doubled = dict(COMPILE_RECORD)
        doubled["stderr"] = COMPILE_RECORD["stderr"] + COMPILE_RECORD["stderr"].split("Error (7576)")[0]
        text = repair.diagnostics_for(doubled, parsed, unit)
        self.assertEqual(text.count("undeclared_a"), 1)


class RewriteTest(unittest.TestCase):
    def test_accepts_same_signature_body_fix(self):
        parsed = _parsed()
        unit = parsed.functions[0]
        text = repair.validate_rewrite(
            unit,
            "function first(uint256 a) public returns (uint256) {\n"
            "        return a + 1;\n"
            "    }",
        )
        self.assertTrue(text.startswith("function first"))

    def test_rejects_renames(self):
        unit = _parsed().functions[0]
        with self.assertRaises(repair.RepairUnitsError):
            repair.validate_rewrite(unit, "function renamed(uint256 a) public {}")

    def test_rejects_signature_change(self):
        unit = _parsed().functions[0]
        with self.assertRaises(repair.RepairUnitsError):
            repair.validate_rewrite(unit, "function first(bytes32 a) public {}")

    def test_rejects_extra_units(self):
        unit = _parsed().functions[0]
        with self.assertRaises(repair.RepairUnitsError):
            repair.validate_rewrite(
                unit,
                "function first(uint256 a) public {} function helper() {}",
            )

    def test_rejects_garbage(self):
        unit = _parsed().functions[0]
        with self.assertRaises(repair.RepairUnitsError):
            repair.validate_rewrite(unit, "   ")


class ApplyTest(unittest.TestCase):
    def test_splice_preserves_doc_header_and_rest(self):
        source = (
            "contract C {\n"
            "    /// @custom:selector 0xabcdef01\n"
            "    /// @param a [\"uint256\"]\n"
            "    function first(uint256 a) public view returns (uint256) {\n"
            "        return weird + 1;\n"
            "    }\n"
            "}\n"
        )
        parsed = investigator.parse_contract(source, "C")
        unit = parsed.functions[0]
        merged = repair.apply_rewrites(
            parsed, {unit.opaque_id: "function first(uint256 a) public view returns (uint256) {\n        return a;\n    }"}
        )
        self.assertIn("/// @custom:selector 0xabcdef01", merged)
        self.assertIn("return a;", merged)
        self.assertNotIn("weird", merged)
        self.assertIn("contract C {", merged.split("///")[0])
        reparsed = investigator.parse_contract(merged, "C")
        self.assertEqual([u.name for u in reparsed.functions], ["first"])

    def test_two_splices_compose(self):
        parsed = _parsed()
        first, second = parsed.functions
        merged = repair.apply_rewrites(
            parsed,
            {
                first.opaque_id: "function first(uint256 a) public returns (uint256) { return a; }",
                second.opaque_id: "function second(bytes32 b) public view returns (uint256) { return 1; }",
            },
        )
        reparsed = investigator.parse_contract(merged, "C")
        self.assertEqual([u.name for u in reparsed.functions], ["first", "second"])
        self.assertNotIn("undeclared_a", merged)
        self.assertNotIn("undeclared_b", merged)


class ReviewRegressionTest(unittest.TestCase):
    SOURCE = (
        "contract C {\n"
        "    uint256 s;\n"
        "    function f(uint256 a) public view returns (uint256) {\n"
        "        return a;\n"
        "    }\n"
        "    function g() internal view returns (uint256) { return s; }\n"
        "}\n"
    )

    def _parsed(self):
        return investigator.parse_contract(self.SOURCE, "C")

    def test_public_to_internal_is_rejected(self):
        unit = self._parsed().functions[0]
        with self.assertRaises(repair.RepairUnitsError):
            repair.validate_rewrite(unit, "function f(uint256 a) internal view returns (uint256) { return a; }")

    def test_internal_stays_internal(self):
        unit = self._parsed().functions[1]
        out = repair.validate_rewrite(unit, "function g() internal view returns (uint256) { return 1; }")
        self.assertTrue(out.startswith("function g"))

    def test_unit_error_codes_ignore_pure_line_shifts(self):
        parsed = self._parsed()
        record_a = {"ok": False, "stderr": "Error (7576): x\n --> src/C.sol:4:1:\n", "stdout": ""}
        record_b = {"ok": False, "stderr": "Error (7576): x\n --> src/C.sol:5:1:\n", "stdout": ""}
        name = parsed.functions[0].name
        self.assertEqual(
            repair._unit_error_codes(record_a, parsed, name),
            repair._unit_error_codes(record_b, parsed, name),
        )

    def test_unit_error_codes_scope_to_the_named_unit(self):
        parsed = self._parsed()
        record = {
            "ok": False,
            "stderr": "Error (7576): a\n --> src/C.sol:4:1:\nError (2271): b\n --> src/C.sol:7:1:\n",
            "stdout": "",
        }
        codes = repair._unit_error_codes(record, parsed, parsed.functions[0].name)
        self.assertEqual(dict(codes), {"7576": 1})


class PromptTest(unittest.TestCase):
    def test_prompt_carries_unit_diagnostics_and_declarations_only(self):
        parsed = _parsed()
        unit = parsed.functions[1]
        prompt = repair.repair_prompt(
            unit,
            repair.unit_prefix(unit),
            repair.diagnostics_for(COMPILE_RECORD, parsed, unit),
            parsed.declarations_text,
            None,
        )
        self.assertIn("function second", prompt)
        self.assertIn("undeclared_b", prompt)
        self.assertNotIn("undeclared_a", prompt)
        self.assertIn("uint256 stored;", prompt)


if __name__ == "__main__":
    unittest.main()
