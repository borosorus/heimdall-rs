# Local-LLM decompilation: implementation checklist

This checklist is for coding agents working on this fork. **Read [the full specification](llm-decompilation-evaluation-plan.md) and [AGENTS.md](../AGENTS.md) first.** The scope is to implement and test the plan, not merely update documents.

## Phase 1 — configurable OpenAI-compatible LLM client

- [x] Add provider-neutral configurable base URL, model and auth to decompile and shared LLM consumers, preserving existing OpenRouter defaults and flags.
- [x] Support unauthenticated localhost APIs; ensure custom local model names and local HTTP work; document config precedence and secret handling.
- [x] Implement structured JSON response compatibility/fallback with explicit outcomes and errors rather than a hidden silent fallback.
- [x] Add offline local mock-server tests for success and error paths, model/base URL/auth forwarding and backward compatibility.
- [ ] Document and actually test a local Ollama/LM Studio/vLLM-compatible usage command. The CLI path is verified against an offline OpenAI-compatible mock; a real local model smoke test remains manual.

**Gate:** mock-driven tests pass without internet, API keys or local GPU. Existing OpenRouter CLI remains usable. Provider flags, precedence, artifacts and limitations are documented in [`llm-provider-configuration.md`](llm-provider-configuration.md).

## Phase 2 — reproducible bytecode and source fixtures

**Seed data already committed:** Nine public source/runtime pairs (five original plus four modern Tevm examples, including 0.8.22 and 0.8.30), with ABIs, provenance and SHA-256 manifests, in [evaluation/README.md](../evaluation/README.md). Run `python3 evaluation/scripts/check_fixtures.py` for an offline integrity check; use `evaluation/scripts/recompile_modern.py` with the matching locally installed solc version to attempt independent byte-for-byte reproduction. This does **not** satisfy the compilation-reproduction or behavioral-testing gates below; legacy compiler settings still need to be recovered.

- [ ] Add at least five small original Solidity cases for storage, authorization, events, token allowances, nested mappings and control flow.
- [ ] Commit runtime (not creation) EVM bytecode, original source, ABI and pin exact compiler/options in manifests.
- [ ] Add a clean regeneration/verification command and checksum tests; avoid requiring internet once toolchains are installed.
- [ ] Enforce oracle source isolation: original Solidity is never passed to an LLM under evaluation.

**Gate:** committed fixture bytecode can be reproduced exactly and its provenance is verified.

## Phase 3 — decompilation accuracy experiment

- [ ] Implement repeatable `baseline` (no LLM) and `llm1` modes with identical fixtures and deterministic seed.
- [ ] Save baseline and candidate Solidity separately, plus request status, compile diagnostics and machine-readable metadata.
- [ ] Compute compile success and ABI/selector precision and recall with explicit denominators.
- [ ] Execute stateful differential EVM tests: success/revert, returndata, events, ether and observable post-state.
- [ ] Produce readable per-fixture and aggregate reports; mark unevaluated paths, LLM failures and noncompilable candidates clearly.
- [ ] Add CI tests that do not depend on `RPC_URL`, hosted models, upstream `heimdall-eval` or GPU.
- [ ] Write a factual findings note: which fixtures fail, why, whether llm1 beats baseline, and confidence limits.

**Gate:** reproducible reports exist for baseline versus one-pass local LLM. Do not claim behavioral correctness from code similarity alone.

## Phase 4 — optional feedback-guided second LLM pass

- [ ] Decide whether phase 3 reveals a meaningful deficit worth improving; document go/no-go.
- [ ] If go, feed compiler errors, recovered bytecode metadata and minimized failing black-box call traces, but never oracle source.
- [ ] Make pass 2 explicitly optional and bounded; preserve all generated intermediate outputs.
- [ ] Compare baseline, llm1 and llm2 under identical tests; report improvements and regressions, retaining best verified candidate.

**Gate:** a measured improvement justifies the feature; otherwise leave it disabled/experimental and publish the negative result.

## Completion evidence required from the implementation agent

- Exact commit/PR references and CLI flags; successful local-server commands.
- Offline test commands and results; documented CI behavior.
- Fixture manifest/compiler lock details and checksums.
- Links/paths to machine-readable reports and side-by-side behavioral results.
- Honest list of failures, untested behaviors, secrets/privacy considerations, and any remaining provider limitations.

**Current status:** planning complete; implementation and benchmarking not yet performed. GitHub Issues are disabled in this fork, so this checked-in checklist is the task tracker.