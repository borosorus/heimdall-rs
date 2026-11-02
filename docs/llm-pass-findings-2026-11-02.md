# Local-LLM pass usefulness: dsv41, 2026-11-02

**Scope:** one `llm1` run per fixture against `http://192.168.88.253:8000/v1`, model `dsv41`,
using the existing annotation prompt. Reference Solidity was **not** sent to the model. All model
calls were run sequentially and allowed to finish; no call was made in parallel with another task.

**Machine-readable data:** [`evaluation/results/2026-11-02-dsv41/summary.json`](../evaluation/results/2026-11-02-dsv41/summary.json).

## Bottom line

The pass is **useful as an annotation/readability layer**, but **not yet useful as a behavioral
decompiler**.

- It raised source compileability from **0/7 baseline** to **5/7 llm1** on the fixtures evaluated.
- It added meaningful comments, names and types in several cases, especially `hdwallet`,
  `lighthouse`, `modern-simple` and `modern-advanced`.
- It did **not** preserve the original executable interface: across the five llm1 candidates that
  compiled, **0/25** compiled function selectors matched the reference ABI.
- Two of seven accepted candidates were not Solidity source at all: one refusal sentence and one
  prose-plus-Markdown response. The client accepted both because validation only requires a
  nonempty `source` string.

Compile success therefore does not mean the candidate is a correct or drop-in replacement. It
means the LLM produced syntactically valid Solidity that may encode different behavior.

## Measurements

| Fixture | Baseline compile | llm1 compile | llm1 request | Heimdall ABI selector recall | Compiled llm1 selector recall |
| --- | --- | --- | --- | --- | --- |
| `auditlog` | fail | pass | applied | 3/3 | 0/3 |
| `hdwallet` | fail | pass | applied | 3/3 | 0/3 |
| `ipfs` | fail | pass | applied | 3/3 | 0/3 |
| `lighthouse` | fail | fail | applied | 13/13 | 0/13 |
| `modern-advanced` | fail | pass | applied | 14/14 | 0/14 |
| `modern-errors` | not evaluated | not evaluated | not run | — | — |
| `modern-math-helper` | fail | fail | applied | 4/4 | 0/4 |
| `modern-simple` | fail | pass | applied | 2/2 | 0/2 |
| `sender-creator` | fail | fail | applied | 1/1 | 0/1 |

`Heimdall ABI selector recall` compares the selectors encoded in Heimdall's generated ABI with the
reference ABI; it is **1.0 (43/43)**. That is a property of bytecode selector discovery, not of the
LLM output.

`Compiled llm1 selector recall` compares the selectors of the compiled LLM candidate with the
reference ABI. It is **0.0**. The generated functions are named like
`Unresolved_60fe47b1(uint256)`, so Solidity hashes that whole name and produces a different selector
(for example `0x2aed481d` instead of the reference `0x60fe47b1`). Preserving the
`@custom:selector` comment does not preserve dispatch.

## What the LLM actually added

Good cases:

- **`hdwallet`**: inferred `string` storage and `set`/`get` semantics correctly enough to compile;
  the baseline emitted undeclared ABI-layout temporaries.
- **`lighthouse`**: reconstructed owner/auth/searcher roles, packed bid fields and expiry logic in a
  much more readable form. It still has wrong names in places (slot 1 is `auth`, not `searcher`) and
  a stale `@param arg0` that makes compilation fail.
- **`modern-simple`**: fixed the event declaration and gave the storage variable a meaningful name.
- **`modern-advanced`**: replaced invalid calldata expressions and produced readable functions.

Bad cases:

- **`modern-math-helper`**: returned only “I can’t provide a compiled contract, but here’s the
  cleaned source you requested.” The report says `applied: true`; the candidate does not compile.
- **`sender-creator`**: returned prose and a fenced Markdown code block. The inner code may be
  useful, but as emitted it does not compile. It also dropped the original bounds checks.
- **`auditlog`**: invented `struct Item { address account; uint256 value; }`, replacing the
  reference `address` + `string` log entry. It compiles, but the inferred type is wrong and the
  dynamic string payload is gone.
- **`ipfs`**: collapsed the reference's two-string `get()` result into one bytes getter.

## Behavioral spot check

`modern-simple` was deployed alongside the reference on a local Anvil node.

| Check | Reference | llm1 candidate |
| --- | --- | --- |
| Initial `get()` | 42 (constructor argument) | 0 (no constructor in candidate) |
| `get()` after `set(123)` | 123 | 123 |
| Setter selector | `0x60fe47b1` | `0x2aed481d` |
| Getter selector | `0x6d4ce63c` | `0x6d619daa` |
| Event | `ValueSet(uint256)` | `ValueUpdated(uint256)` |

The post-set state agrees for this simple case, which supports “some logic is preserved.” The
different selectors, missing constructor state and different event topic mean it is not
interface- or behavior-equivalent as a deployed contract.

## Other blockers and limits

- **`modern-errors`** baseline generation exceeded five minutes even with `--timeout 1000`; it is
  marked unevaluated rather than counted as a pass or failure.
- The client sends no temperature or seed, so a repeated llm1 run is not reproducible. One sample
  per fixture is not enough to estimate variance.
- Compilation used Solidity 0.8.22 for `modern-simple` and 0.8.30 for the rest. This is not the
  fixtures' original compiler configuration and only establishes syntax, not bytecode equivalence.
- No full stateful differential suite was run. That remains the required next evaluation step.

## Implications for the next design pass

The immediate gaps are not “make the model smarter” alone:

1. Reject non-source responses and fenced/prose wrappers before applying a candidate.
2. Enforce selector preservation, or explicitly treat the output as a non-deployable annotated
   reconstruction rather than a behavioral candidate.
3. Make runs reproducible with a fixed seed/temperature and save the raw request/response.
4. Add a real differential harness before claiming that any fixture improved behaviorally.

Until those exist, the pass should be described as a readability/annotation experiment, not as a
verified decompilation improvement.
