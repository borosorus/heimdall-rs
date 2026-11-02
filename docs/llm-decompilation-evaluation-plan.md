# Local-LLM EVM decompilation: implementation and evaluation plan

**Status:** implementation specification, not yet implemented  
**Repository:** `borosorus/heimdall-rs`  
**Goal:** make Heimdall's LLM integration work with any sufficiently OpenAI-compatible chat-completions server (especially a local LLM), measure its decompilation quality against a reproducible bytecode/source benchmark, and introduce an *optional* second, evidence-guided LLM repair pass only if experiments justify it.

Read the root [AGENTS.md](../AGENTS.md) before making changes.

## Product intent and success definition

We want an entirely local-capable, repeatable pipeline:

```text
Known Solidity source --(pinned solc settings)--> deployed/runtime EVM bytecode
                                                   |
                                                   v
                                     Heimdall deterministic decompiler
                                                   | baseline source
                                                   +---------------------------> baseline evaluation
                                                   |
                                                   v
                                      LLM pass 1 (existing annotation)
                                                   | generated source
                                                   +---------------------------> pass-1 evaluation
                                                   |
                        [only after measurement shows shortcomings]
                                                   v
                                 LLM pass 2 (compile/behavior-guided repair)
                                                   |
                                                   +---------------------------> pass-2 evaluation

Evaluation uses reference source and observable behavior as the oracle,
but **reference source/ABI implementation must not be included in LLM prompts**.
```

Three separate notions of quality:
1. **Compilability:** candidate Solidity compiles with a documented, pinned compiler configuration.
2. **Structural recovery:** externally callable function selectors/signatures, types where recoverable, event signatures, and access-control/storage assumptions.
3. **Behavioral fidelity:** with the same initial conditions and call sequences, candidate and reference agree on return values, reverts, event payloads (with emitter addresses normalized), balances and externally observable storage effects. Behavioral fidelity is the main success metric. Exact text similarity, variable names and comments are secondary diagnostics, *not* correctness proofs.

Do not claim formal equivalence based on a limited test suite. Mark untested paths explicitly.

## Verified starting state (as inspected in this fork)

- `crates/common/src/resources/openrouter.rs` uses `async_openai::config::OpenAIConfig` but hardcodes `OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"` in both `complete_chat` and `complete_chat_structured`.
- `crates/decompile/src/interfaces/args.rs` exposes `--llm-postprocess`, `--openrouter-api-key`, `--model`, and `--include-sol`; there is no LLM base-URL option.
- `crates/cli/src/main.rs` loads OpenRouter defaults from `crates/config/src/lib.rs` (`~/.bifrost/config.toml`).
- `crates/decompile/src/core/out/source.rs` calls `complete_chat_structured` to annotate Solidity. If it fails, it silently preserves the baseline output at debug level; this must become visible in evaluation status.
- The structured response currently requests a JSON Schema object with one required `source: string` field. Many OpenAI-compatible servers do *not* fully support this feature.
- `crates/decompile/src/utils/constants.rs` contains the original annotation prompt (mostly readability changes).
- `crates/core/tests/test_decompile.rs` contains integration checks relying on `RPC_URL`; do not treat them as a standalone local evaluation suite.
- `.github/workflows/eval.yml` invokes a separate `Jon-Becker/heimdall-eval` checkout and repository secrets. **Do not make local evaluation or ordinary CI depend on that external suite or its secrets.**
- The repo is a Rust workspace; `heimdall` is the binary (`cargo build --release --bin heimdall`).

## Phase 1 — OpenAI-compatible provider (implement first)

### Required CLI and config behavior

Implement a provider-neutral LLM configuration shared by all relevant LLM call sites (including decode explanations if they use the same helper). Prefer typed configuration passed explicitly over hidden global mutable state.

- `--llm-base-url URL`: full API base including `/v1`, e.g. `http://127.0.0.1:11434/v1`, `http://127.0.0.1:1234/v1`, or an HTTPS hosted endpoint.
- `--llm-api-key VALUE`: optional for local, unauthenticated servers; supported for hosted providers. Accept environment variables `HEIMDALL_LLM_BASE_URL` and `HEIMDALL_LLM_API_KEY` so users do not need to put credentials in the shell history. If a supplied server requires an Authorization header, send one; do not unconditionally require a key for localhost.
- Keep `--model`; accept local model IDs *verbatim*, including unprefixed names. If a custom endpoint is selected, require an explicit model rather than silently using the OpenRouter default model ID.
- Preserve existing `--openrouter-api-key`, `openrouter_api_key`, `openrouter_model`, and OpenRouter default behavior for backwards compatibility; document any deprecation rather than breaking old scripts.
- Persist non-secret defaults in `~/.bifrost/config.toml` with backwards-compatible `#[serde(default)]` fields. Support a documented precedence policy: explicit CLI > environment > stored config > built-in defaults. Avoid logging API keys, auth headers or raw prompts by default. Handle `heimdall config` output so it does not reveal stored secrets.
- If no custom endpoint is selected, keep existing default OpenRouter URL and model. For a local endpoint, nothing should be sent to OpenRouter or other network services by the LLM client.
- The CLI should give actionable errors for bad base URL, unavailable model, HTTP status, timeout, malformed response, and unsupported `response_format`.
- Consider localhost HTTP acceptable; document any policy for nonlocal HTTP and never silently send secrets over plaintext connections.
- Do not couple LLM URL configuration to `--rpc-url`; Ethereum JSON-RPC and OpenAI chat completion are unrelated services.

### OpenAI compatibility and response formatting

Both `complete_chat` and `complete_chat_structured` currently create the client with a hardcoded base URL. Centralize URL and authentication configuration.

- Primary path: `POST {base_url}/chat/completions` using OpenAI-compatible `messages`, `model`, and structured `response_format: {type: "json_schema", ...}` for `{"source": "..."}`.
- Add a well-tested compatibility mode for local providers that reject strict `json_schema`. Ideally expose `--llm-response-format auto|json-schema|json-object|text`. In `auto`, downgrade *only when the server explicitly rejects the requested response format*, using JSON-object mode or prompt-based JSON with strict local parsing and validation. Never downgrade silently for unrelated failures such as 401, 404, 429, or 500.
- Plain-text fallback, if allowed, must still produce a nonempty `source` value, validate the response, and be clearly labeled in the run report. Strip Markdown fences only if unambiguous. Guard against malformed or truncated output; do not pretend success.
- Preserve existing `source` schema where feasible. Response format, model, request timeout, and failure reason should be recorded in evaluation artifacts (redact credentials).
- Expose whether the LLM pass succeeded, failed, or fell back to deterministic output. Keep the pre-LLM source separately; never overwrite it irreversibly.

### Phase-1 tests (must run without internet, LLM or RPC)

Implement a local HTTP mock server in Rust integration tests (or equivalent) that records incoming requests and provides controlled responses.

Test:
1. Custom base URL is actually used; no OpenRouter traffic.
2. Exact model ID reaches the request; authenticated and unauthenticated local modes both work.
3. JSON Schema success; unsupported-schema response triggers only documented compatibility fallback; valid JSON is parsed.
4. 401/404/429/500, malformed response, empty content and timeout are reported faithfully.
5. Config precedence, existing OpenRouter flag compatibility, and secret redaction.
6. Decode/explain usage, if provider changes touch it; no regression to ordinary no-LLM decompilation.
7. All documented CLI examples parse; unit and integration tests do not require real services.

**Phase-1 acceptance:** local Ollama/LM Studio/vLLM-compatible server *can* be selected by URL and model, a mock-server test proves it, and existing OpenRouter commands remain functional. A provider's chat-completions compatibility is a prerequisite; "any OpenAI API" does not mean every vendor-specific or Responses-only API works.

## Phase 2 — Self-contained golden fixtures

Create a small but nontrivial evaluation dataset inside this fork, such as:

```text
evaluation/
  README.md
  foundry.toml                   # or an equivalent pinned solc config
  fixtures/
    counter/
      Counter.sol
      runtime.hex
      abi.json
      manifest.json
    guarded-vault/
      GuardedVault.sol
      runtime.hex
      abi.json
      manifest.json
    token-ledger/
      TokenLedger.sol
      runtime.hex
      abi.json
      manifest.json
    nested-mapping/
      NestedMapping.sol
      runtime.hex
      abi.json
      manifest.json
    branching-loops/
      BranchingLoops.sol
      runtime.hex
      abi.json
      manifest.json
  scripts/
    regenerate_fixtures.py       # or Rust equivalent
    run_eval.py
  tests/
    ...                          # deterministic behavior/differential probes
  results/                       # ignored outputs; no keys
```

The folder names and harness language can change if a simpler implementation suits the existing project. **Commit both source and *actual compiled deployed/runtime bytecode*** for each fixture. Do not substitute creation bytecode for runtime bytecode; record both only when useful, with unambiguous filenames.

Five suggested cases: stateful counter (arithmetic), guarded/payable vault (auth, reverts, transfers, events), ERC20-like token ledger (allowances/events), nested mappings (storage), branching/loops (control flow). Prefer small, original MIT-licensed fixtures created for this repo over unrelated verified contracts, to avoid licensing and reproducibility problems. Include constructor and initializer semantics in test setup; do not assume deployment bytecode and deployed bytecode are equivalent.

Each `manifest.json` must identify source file and contract name, solc exact version/hash if possible, optimizer enabled/runs, via-IR setting, EVM version, metadata settings, bytecode SHA-256, and expected runtime bytecode length. Pin dependencies and deterministic build configuration.

Required test: run fixture regeneration/check in a clean environment, then assert each committed `runtime.hex` reproduces exactly (or fail with a clear explanation of compiler nondeterminism). Avoid network calls at test execution time; pin toolchain provisioning separately.

**Data-leakage rule:** the reference Solidity source is strictly evaluation-only. Do not pass it to LLM pass 1, pass 2, prompt templates, retrieved context, or LLM-as-judge scoring. The agent building the harness can read it; the model under test cannot.

## Phase 3 — Repeatable evaluation and baseline measurements

Build a command (the following syntax is a **planned interface to implement**, not an existing command):

```bash
# Deterministic decompiler, no LLM:
python3 evaluation/scripts/run_eval.py --mode baseline --fixtures all

# First LLM pass through a local OpenAI-compatible endpoint:
HEIMDALL_LLM_BASE_URL=http://127.0.0.1:11434/v1 \
python3 evaluation/scripts/run_eval.py \
  --mode llm1 --fixtures all --model qwen2.5-coder:14b

# Compare previous results:
python3 evaluation/scripts/run_eval.py --compare evaluation/results/<run-a> evaluation/results/<run-b>
```

Use Rust if it makes the harness more reliable; the exact CLI is less important than automated, documented, end-to-end execution. It must accept an externally running local model; CI uses mocks only.

For each fixture, save separately:
- original `runtime.hex` hash and manifest reference;
- Heimdall raw source (`baseline.sol`);
- first-pass output (`llm1.sol`), preserving even unsuccessful candidate text where useful;
- generated ABI/selectors (if available), compiler warnings/errors, and separate outcome for model request and local parsing;
- `metrics.json` with schema version, tool git commit, fixture hash, compiler/options, model ID, endpoint label (not credential), response mode, latency, pass count, seed and each metric's denominator;
- normalized per-test diffs, plus a summary table/report across fixtures. Ignore large or sensitive raw traces by default.

Build validation in increasing strength:
1. **Does it parse and compile?** Use pinned solc; compile failures are failures, not missing data.
2. **ABI recovery:** report selector precision/recall (and type/signature agreement when available). Account for fallback/receive and signature collisions.
3. **Behavioral differential tests:** deploy reference and candidate into independent, equivalently initialized local EVM instances (e.g., Foundry/Anvil or revm); execute deterministic *stateful sequences* of calls with the same caller addresses, ether balances, block environment, gas limits and calldatas. Compare success/revert status, returndata/revert payloads, normalized event topics/data, ether transfers/balances, and the observable post-state via getter/continuation calls. Normalize deployment-specific addresses; do not compare raw storage layouts where equivalent contracts could use different slots.
4. **Adversarial probes:** boundaries (0, 1, max values), unauthorized callers, repeated calls, under/overflow, insufficient balances, missing keys, nested maps and loop limits. Fix seed and publish it.
5. Optional human review or semantic LLM judgment is *diagnostic only*; string distance/BLEU is not the fidelity score.

Benchmark should report at minimum `compile_rate`, `selector_precision`, `selector_recall`, `behavioral_test_pass_rate`, and `runtime_sec` plus raw numerators/denominators; break down by fixture and mode. Reverted execution and event data are correctness-relevant. Clearly mark `not_compilable`, `no_tests`, `llm_error`, and `unverified` rather than treating them as zero-error success. An incomplete differential suite is not proof of equivalence.

Run identical fixture/test seeds against no-LLM and one-pass output. Record the raw deterministic output before any model postprocessing, to isolate gains and regressions. Establish baseline metrics **before** changing prompts or adding pass 2.

**Phase-3 acceptance:** one command evaluates all committed fixtures, produces machine-readable results and a human summary, and runs fully offline with deterministic mode; local LLM mode is repeatable against a running configured server. CI verifies fixture integrity, mock API behavior, and deterministic harness behavior without local GPU or cloud credentials.

## Phase 4 — Optional second-pass, feedback-guided LLM repair

**Do not start this phase until phases 1–3 produce reports** and show at least one meaningful failure in the first pass. Keep it behind an explicit flag/mode so default Heimdall output and single-pass behavior remain unchanged.

Objective: improve semantic fidelity rather than merely readability. A useful second pass sees:
- deterministic Heimdall output;
- first-pass candidate source;
- recovered selector/ABI metadata, CFG/storage hints where available *from bytecode*;
- compiler diagnostics from compiling the first-pass candidate;
- optionally, minimal failing black-box test counterexamples derived from original-bytecode execution (call sequence, inputs and observed output), with no oracle source or hints about its internal variable names.

Pass-2 prompt should request **the smallest justified fix**, maintain observed behavior, preserve function selectors/NatSpec information, avoid inventing semantics, and return complete source in the agreed structured format. Treat candidate as untrusted; compile and re-run identical tests after generation.

Important: reference contract source, ground-truth internal structure and source diff must **never** enter the repair prompt. You may use reference *observable behavior* from differential tests, because bytecode itself is the object being reconstructed; track this distinction in reports. If a candidate doesn't compile, feed compiler errors; if it compiles but differs, feed minimal failing trace(s) not the reference implementation.

Store `llm2.sol` and `llm2` metrics next to `baseline` and `llm1`; use same fixture set, toolchain and seed. Configurable `--llm-max-passes 1|2` or evaluation-only `--mode llm2` is acceptable; cap retries and context, store errors, never trigger indefinite loops or hidden paid requests. If pass 2 regresses behavioral fidelity, retain the best verified candidate and report the regression. A successful compile without behavioral improvement does not justify claiming better decompilation.

**Phase-4 acceptance:** compared against pass 1 on identical test cases, pass 2 measurably improves at least one previously failing fixture or criterion without hiding regressions. If no improvement, report that and keep the feature experimental/disabled; do not optimize only for visual plausibility.

## Commands and UX expected at the end (illustrative)

```bash
cargo build --release --bin heimdall

# Local server running separately (e.g. Ollama):
heimdall decompile evaluation/fixtures/counter/runtime.hex \
  --include-sol --skip-resolving --llm-postprocess \
  --llm-base-url http://127.0.0.1:11434/v1 \
  --model qwen2.5-coder:14b \
  --output evaluation/results/manual-counter

# Existing OpenRouter workflow should remain usable:
heimdall decompile evaluation/fixtures/counter/runtime.hex \
  --include-sol --llm-postprocess \
  --openrouter-api-key YOUR_KEY --model openai/gpt-4o-mini
```

These are target commands; adapt arguments to implemented interface and test them. `--skip-resolving` is useful when benchmark fixtures should not make remote signature lookups.

## Agent implementation order and deliverables

1. **Provider PR:** configurable base URL/auth/model/response-format, backward compatibility, doc updates, mock HTTP tests. Include successful test command output and explain any known local-provider limitations.
2. **Fixtures PR:** 5 golden source/runtime bytecode pairs, reproducible compiler settings, hash/integrity checks, offline regeneration instructions, license information.
3. **Evaluation PR:** baseline and llm1 modes; deterministic differential tests; JSON and readable reports; example report in docs with exact provenance and clearly labeled conditions.
4. **Conditional repair PR:** second-pass prompting/feedback only after analyzing llm1 metrics; rerun identical benchmark and publish pass-by-pass comparison.

Prefer small commits/PRs with tests over a monolithic change. At every stage:
- run `cargo fmt --all -- --check`, relevant `cargo test` / `cargo nextest` suites, `cargo clippy` as consistent with repo CI;
- verify **no-network tests** without `RPC_URL`, OpenRouter secrets or GPU;
- provide exact steps to run a local LLM benchmark manually;
- list untested assumptions, compilation failures, changed interfaces, and known security/privacy limitations;
- do not assert an improvement without recorded before/after results.

### Final definition of done

- Working and documented configurable OpenAI-compatible chat-completions URL (including localhost), model, optional local auth, sensible structured-response fallback, tests; old OpenRouter invocation preserved.
- At least five committed, reproducible runtime-bytecode + Solidity fixtures, with provenance.
- End-to-end reproducible baseline/llm1 evaluation report with compile, ABI and behavioral metrics, including failures and confidence limits.
- An explicit go/no-go decision for optional second pass supported by data; if implemented, a recorded pass-1/pass-2 comparison and regression checks.

### Non-goals for this work

Exact restoration of original source formatting, comments or variable names; proof of whole-program equivalence; reverse engineering proprietary deployed contracts; hosting a GPU/model in CI; changing the EVM decompiler's underlying symbolic execution algorithm before measuring it; silently using a remote model when local mode is requested.
