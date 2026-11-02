# Repository agent instructions

## Current project: local-LLM EVM decompilation and quality evaluation

**Primary specification:** [docs/llm-decompilation-evaluation-plan.md](docs/llm-decompilation-evaluation-plan.md).

**Task tracker (issues are disabled):** [docs/llm-decompilation-tasks.md](docs/llm-decompilation-tasks.md).

**Imported benchmark seed fixtures:** [evaluation/README.md](evaluation/README.md) (nine publicly sourced Solidity/runtime pairs, including 0.8.22 and 0.8.30; offline integrity verifier, provenance and licenses; **not yet recompiled or behaviorally validated**).

This project is an extension of Heimdall, not a rewrite. An implementation agent should read the full specification before editing code and work in the following order:

1. Add configurable OpenAI-compatible chat-completions base URL/model/authentication with backward-compatible OpenRouter behavior; test with a local HTTP mock.
2. Commit reproducible Solidity source + compiled deployed-runtime EVM bytecode fixtures using a pinned solc configuration.
3. Implement offline baseline evaluation and optional local-LLM pass 1, with compile checks, selector comparisons, and executable behavioral differential tests.
4. Only after studying the recorded baseline vs pass-1 failures, experimentally add an optional pass 2 with compiler/test feedback; compare on identical fixtures and seeds.

### Nonnegotiable rules

- Ground every quality claim in saved, reproducible metrics. Solidity text similarity is not behavioral fidelity.
- The reference Solidity source is **evaluation-only**. Never send reference Solidity, source diffs, or implementation-oracle hints to an LLM under test. Black-box bytecode-derived observations and compiler errors are permitted feedback.
- Preserve deterministic Heimdall output and each LLM candidate separately; never silently label a no-LLM fallback as LLM success.
- No cloud credentials, external RPC, GPUs, or OpenRouter calls in required unit/integration CI tests. Use local mock HTTP for API compatibility and deterministic local EVM execution for behavioral checks.
- Do not alter the default OpenRouter workflow, existing CLI flags or standard non-LLM decompilation unexpectedly.
- Do not start phase 4 until phase-3 reports justify a repair attempt. A second LLM pass is optional, bounded and must be benchmarked for regressions.
- Do not commit API keys, local inference logs containing secrets, or large ephemeral evaluation results. Document provider-compatibility limitations honestly.

### Relevant existing code

- crates/common/src/resources/openrouter.rs — OpenAI-compatible LLM client, currently hardcoded to OpenRouter.
- crates/decompile/src/interfaces/args.rs — decompile command flags.
- crates/cli/src/main.rs and crates/config/src/lib.rs — configuration and default resolution.
- crates/decompile/src/core/out/source.rs — existing LLM postprocessing and fallback.
- crates/decompile/src/utils/constants.rs — current LLM prompt.
- crates/core/tests/test_decompile.rs — existing mostly RPC-dependent decompilation tests.
- .github/workflows/eval.yml — upstream external evaluation workflow; do not depend on it for new offline evaluation.

### Working agreement

Prefer small, independently testable changes/PRs. Give the user runnable commands, exact test results, artifact/report paths, and clearly stated blockers at each phase. The linked specification defines detailed acceptance criteria and proposed fixture/report schemas.
