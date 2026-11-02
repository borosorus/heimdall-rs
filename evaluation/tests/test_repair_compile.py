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
repair = _load("repair_compile", ROOT / "evaluation" / "scripts" / "repair_compile.py")

SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

contract DecompiledContract {
    uint256 private slot0;

    function Unresolved_aaaaaaaa(uint256 v) public {
        slot0 = v;
    }

    function Unresolved_bbbbbbbb() public view returns (uint256) {
        return slot0;
    }
}
"""


def _prepared(source=SOURCE):
    parsed = investigator.parse_contract(source, "DecompiledContract")
    signatures = repair.dispatch_signatures(parsed)
    return parsed, signatures, set(signatures)


class RepairValidationTest(unittest.TestCase):
    def test_dispatch_signatures_normalize_aliases(self):
        parsed = investigator.parse_contract(
            """pragma solidity 0.8.30;
contract D {
  function f(uint a, byte b, address[] calldata c) public {}
}
""",
            "D",
        )
        self.assertEqual(
            repair.dispatch_signatures(parsed),
            ["f(uint256,bytes1,address[])"],
        )

    def test_dispatch_signatures_normalize_placeholder_widths(self):
        parsed = investigator.parse_contract(
            """pragma solidity 0.8.30;
contract D {
  function f(uint256 a, uint0 b, bytes0 c) public {}
}
""",
            "D",
        )
        self.assertEqual(repair.dispatch_signatures(parsed), ["f(uint256,uint256,bytes)"])

    def test_accepts_body_and_param_name_changes(self):
        _, signatures, supported = _prepared()
        proposed = SOURCE.replace("uint256 v", "uint256 value").replace(
            "slot0 = v;", "slot0 = value + 1;"
        )
        parsed = repair.validate_repair(
            signatures, supported, "DecompiledContract", proposed, "DecompiledContract"
        )
        self.assertEqual(parsed.contract_name, "DecompiledContract")

    def test_rejects_contract_rename(self):
        _, signatures, supported = _prepared()
        proposed = SOURCE.replace("contract DecompiledContract", "contract Other")
        with self.assertRaises(repair.RepairError):
            repair.validate_repair(
                signatures, supported, "DecompiledContract", proposed, "DecompiledContract"
            )

    def test_rejects_removed_function(self):
        _, signatures, supported = _prepared()
        proposed = SOURCE.split("    function Unresolved_bbbbbbbb")[0] + "}\n"
        with self.assertRaises(repair.RepairError):
            repair.validate_repair(
                signatures, supported, "DecompiledContract", proposed, "DecompiledContract"
            )

    def test_rejects_parameter_type_change(self):
        _, signatures, supported = _prepared()
        proposed = SOURCE.replace("uint256 v", "bytes32 v")
        with self.assertRaises(repair.RepairError):
            repair.validate_repair(
                signatures, supported, "DecompiledContract", proposed, "DecompiledContract"
            )

    def test_rejects_added_function(self):
        _, signatures, supported = _prepared()
        proposed = SOURCE.replace(
            "    function Unresolved_bbbbbbbb",
            "    function helper() internal {}\n\n    function Unresolved_bbbbbbbb",
        )
        with self.assertRaises(repair.RepairError):
            repair.validate_repair(
                signatures, supported, "DecompiledContract", proposed, "DecompiledContract"
            )

    def test_rejects_unparseable_source(self):
        _, signatures, supported = _prepared()
        with self.assertRaises(repair.RepairError):
            repair.validate_repair(
                signatures, supported, "DecompiledContract", "not solidity", "DecompiledContract"
            )

    def test_diagnostics_text_keeps_compiler_error(self):
        record = {"ok": False, "stderr": "Error: weird type\n  --> src/X.sol:3:5\n", "stdout": ""}
        text = repair.diagnostics_text(record)
        self.assertIn("Error: weird type", text)
        self.assertIn("src/X.sol", text)

    def test_diagnostics_text_truncates_long_output(self):
        record = {"ok": False, "stderr": "x" * 9000, "stdout": ""}
        self.assertEqual(len(repair.diagnostics_text(record)), 4000)


if __name__ == "__main__":
    unittest.main()
