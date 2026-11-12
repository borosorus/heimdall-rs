# stage 0 - ladder re-verification (model-free; prereg section "Arm B stage 0")

The three tune fixtures whose seed-only compile failed in the seed-rules era, re-prepared
under the CURRENT 18-stage ladder on the canonical raw inputs (`seed-rules-v1/
v0-v1-comparison.json cases[*].source`, sha256 in `stage0-ladder.json`), compile-checked with
forge 0.8.30 (`Candidate.sol` = the bare ladder seed, the harness compile path).

Verdict: 3/3 STILL FAIL. The Arm B surface stands as preregistered; first-error classes:

- modern-advanced - 6933: `address(store_f).Unresolved_(memory[var_c:var_c + ...])` - a
  dynamic-slice member call the ladder's lower-unknown-external-calls cannot parse (its gate
  requires a literal selector).
- modern-math-helper - 2271: `((arg0) == 0) | unresolved_...` - bool/uint bitwise mixing, the
  truthiness stage's adjacent residue.
- synthetic-large - width/coercion family: bytes32->uint8, `!` on uint8, bytes32 returned as
  uint256, `>=` against a bytes storage ref.

These classes seed Arm C's LLM-FIXES comparison: does the model repair exactly them, and do
the repairs generalize to ladder stages (the promotion gate decides)?
