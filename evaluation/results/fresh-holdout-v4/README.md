# fresh-holdout-v4: send-guard transplantation - erc20 fully perfect (sealed)

Roadmap lead 0 (stateful guard synthesis), labeled protocol. Arms: v3 =
`d1c6343` (worktree-reproduced), v4 = the send-guards stage
(`synthesize_send_guards` in prepare_candidate).

## Sealed result

| fixture | arm | fb | wh |
|---|---|---|---|
| modern-oz-erc20 | v3 | 4/4 | 1/2 |
| modern-oz-erc20 | **v4** | **4/4** | **2/2** |
| modern-block-reader | v3 | 1/1 | - |
| modern-block-reader | v4 | 1/1 | - |

**erc20 is now fully perfect: 4/4 feedback + 2/2 withheld, zero LLM anywhere.**
The transferFrom withheld probe passes: the transplanted guard
(`require(unresolved_70a08231[arg0] >= arg2)` - the balance check its sibling
`transfer` applies to the same slot-annotated mapping) fires exactly where the
reference reverts. block-reader v4 seed is byte-identical to v3 (stage
abstains - no mappings); modern-errors byte-neutral; tune parity PASS
(`v3v4-tunesweep`, synthetic-large text-only delta as before).

## Mechanism (deterministic, no reference knowledge)

Precedent = a sibling function that BOTH guard-checks a mapping
(`M[x] >= y`) AND mutates that same mapping by indexed assignment - paired per
mapping, not proximity. Stub = body allowlist-grammar (require-lines only,
brace-span-extracted so one-line `...;}` tails count). Guard =
`require(M[firstAddressParam] >= lastScalarParam)` (positional role rule,
recorded); plain require claims nothing about revert payloads. Mutability
pure->view scoped to the header (declaration + provenance comment; no string
exposure). Uniqueness everywhere; abstentions recorded.

## Reviewer round (codex) - 4 findings, all adopted

1. P1 precedent pairing: mutation must touch the SAME mapping the guard checks
   (was: any `-=` anywhere) - docstring now matches behavior.
2. P2 stub grammar: explicit require-line allowlist over the brace-span
   interior (was: exclusion list that a one-line `}` tail could confuse - found
   and fixed live during seed-stability verification).
3. P2 precedent uniqueness per distinct sibling (repeated guards in one
   function no longer look like two precedents).
4. P2 mutability rewrite scoped to the header (string literals untouched;
   comment keeps syncing because the header span covers it).

Post-fix seeds are byte-identical to the sealed-run seeds - the recorded
verdicts correspond to the shipped code. Suite 195/195.
