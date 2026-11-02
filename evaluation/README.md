# Published Solidity + runtime-bytecode seed fixtures

This directory contains **nine committed, externally sourced Solidity / EVM runtime-bytecode pairs** for the local-LLM decompilation project. The reference Solidity is an evaluation oracle; the model under test must receive **only runtime bytecode and bytecode-derived observations**, never the reference source or source diffs.

## Selected cases

| Fixture | Solidity era | Stress test | Provenance |
| --- | --- | --- | --- |
| [`auditlog`](fixtures/auditlog/) | 0.4.x | Array of structs, dynamic strings, generated getters, storage changes | Kaleido Samples Gallery |
| [`hdwallet`](fixtures/hdwallet/) | 0.4.x | Constructor state, dynamic strings, setter/getter | Kaleido Samples Gallery |
| [`ipfs`](fixtures/ipfs/) | 0.4.x | Two dynamic strings and multi-value return | Kaleido Samples Gallery |
| [`lighthouse`](fixtures/lighthouse/) | 0.4.x | Access modifiers, packed bit fields, timestamp logic, external calls | Kaleido Samples Gallery |
| [`sender-creator`](fixtures/sender-creator/) | 0.8.23 | ABI decoding, bytes slicing, low-level factory call, assembly and optimizer | ERC-4337 EntryPoint / Ethereum mainnet |
| [`modern-simple`](fixtures/modern-simple/) | 0.8.22 | Modern `PUSH0`, state setter/getter and event emission | Tevm |
| [`modern-errors`](fixtures/modern-errors/) | 0.8.30 | Custom errors, multiple revert and panic encodings, invalid opcode | Tevm |
| [`modern-advanced`](fixtures/modern-advanced/) | 0.8.30 | Dynamic strings, booleans, events, external calls, delegatecall | Tevm |
| [`modern-math-helper`](fixtures/modern-math-helper/) | 0.8.30 | Arithmetic overflow, event emission, variable storage | Tevm |

### Licenses and attribution

The first four samples come from [`kaleido-io/kaleido-samples-gallery`](https://github.com/kaleido-io/kaleido-samples-gallery) at commit `ce380cef86b0eac9fc08f2f5a30f3e729877cb22`, under **Apache-2.0**; the full license is in [`fixtures/LICENSE-APACHE-2.0`](fixtures/LICENSE-APACHE-2.0). Each folder contains the unmodified upstream `.sol` file, extracted `runtime.hex`, normalized `abi.json`, and upstream published `upstream-artifact.json` (including its creation bytecode). See each `manifest.json` for individual paths and hashes.

`sender-creator` uses the unmodified `SenderCreator.sol` from [`eth-infinitism/account-abstraction`](https://github.com/eth-infinitism/account-abstraction) at commit `7af70c8993a6f42973f520ae0752386a5032abe7`. It is **GPL-3.0**, segregated as a test fixture with its [full license](fixtures/sender-creator/LICENSE); this license is different from Heimdall's MIT license. Runtime code is copied from [`ethereum/zkapi`](https://github.com/ethereum/zkapi/blob/main/protocol/contracts/test/fixtures/sender-creator-v0.7.0.runtime.hex), documented as mainnet code at address `0xEFC2c1444eBCC4Db75e7613d20C6a62fF67A167C`. Its ABI was reconstructed from the public source and known selector `0x570e1a36`; it is not a byte-for-byte export from a published Solidity artifact.

The four `modern-*` fixtures are from [`evmts/tevm`](https://github.com/evmts/tevm) commit `1785ae300bac2afe9209a20c536b20e24a58b36b`, under **MIT** ([full license](fixtures/LICENSE-TEVM-MIT)). Solidity sources are copied from `test/test-utils/src/*.s.sol`, and deployed runtime hex plus human-readable ABI are extracted from the corresponding `packages/contract/src/contract-lib/*.s.sol.ts` generated artifacts. Normalized `abi.json` and the extracted upstream `upstream-artifact.json` are both committed to each fixture directory for offline comparison. `modern-math-helper` and `modern-advanced` share the original multi-contract Solidity source, but benchmark different runtime bytecode. Compiler version is inferred from the bytecode's trailing `solc` metadata; exact optimizer and `viaIR` settings have not been confirmed.

## Integrity test (no network required)

From the repository root:

```bash
python3 evaluation/scripts/check_fixtures.py
```

The script checks manifest IDs, hex formatting, runtime byte count, SHA-256, compiler pragma, ABI function count, and—where provided—the upstream published artifact's runtime bytecode and ABI fields. **It does not recompile the Solidity or prove behavioral equivalence.**

## Optional local recompilation of modern fixtures

The original published runtime hex remains the benchmark input; recompilation never overwrites it. Install the matching `solc` version first (or point to a matching `solcjs` command).

```bash
# With solc 0.8.30 installed; use --optimize / --via-ir to explore
# settings from the upstream build if the initial bytes differ.
python3 evaluation/scripts/recompile_modern.py modern-errors --solc solc
python3 evaluation/scripts/recompile_modern.py modern-advanced --solc solc --optimize --runs 200

# With solc 0.8.22 installed:
python3 evaluation/scripts/recompile_modern.py modern-simple --solc solc
```

The script checks compiler version, attempts a standard-JSON compilation, and reports compiled runtime SHA-256 versus the saved publisher runtime SHA-256. **A compiler run that succeeds but produces different bytecode is not a bitwise reproduction.** It may be due to compiler settings or metadata, or a source/artifact pairing issue. The tool has an optional `--require-byte-match` exit gate. Exact upstream build settings still need to be established.

## Decompile a fixture without a model

```bash
cargo build --release --bin heimdall

./target/release/heimdall decompile evaluation/fixtures/auditlog/runtime.hex \
  --include-sol --skip-resolving --default \
  --output /tmp/heimdall-auditlog

./target/release/heimdall decompile evaluation/fixtures/sender-creator/runtime.hex \
  --include-sol --skip-resolving --default \
  --output /tmp/heimdall-sender-creator
```

The baseline is reproducible without RPC or LLM when using local bytecode and `--skip-resolving`. These commands are examples to run with a compiled Heimdall binary, **not results of a completed decompilation run**.

Once Phase 1 of the [plan](../docs/llm-decompilation-evaluation-plan.md) is implemented, add the configured local LLM flags and capture its output separately.

## Research limitations and next work

- **Compiler settings:** the Kaleido example project says the artifacts were compiled manually. The exact legacy `solc` versions, optimization settings, source filenames and metadata settings have **not** been established or independently reproduced. The source and bytecode are published together by the project, but have not been proven to compile into byte-identical deployed bytecode. These are **seed pairs** rather than fully compiler-verified goldens. Do not claim Phase 2 reproducible compilation is complete.
- **Modern pairs:** `SenderCreator` has independently published deployed code and source, but full compile context/settings still need reproduction. Its runtime is a *deployed* bytecode snapshot, not creation code. Four Tevm examples use modern published generated artifacts, but their exact compiler settings also need to be recovered.
- **Constructor state:** `hdwallet` and `ipfs` set storage in constructors. Runtime bytecode does not encode the initialized storage; differential tests must align initial state or perform equivalent deployments, not assume empty storage is representative.
- **Behavioral evaluation:** this commit includes fixture data and integrity checks **only**. It does not implement the LLM adapter, invoke any local model, test Heimdall's output, or compare observable semantics.
- **Coverage:** the set now includes four legacy 0.4-era contracts, one Solidity 0.8.23 contract and four Solidity 0.8.22/0.8.30 contracts. It still lacks dedicated ERC20, deep mapping and proxy fixtures, and separate confirmed viaIR/optimizer variants. Expand only with demonstrably paired source/bytecode or explicitly generated pinned builds.
- **Avoid data leakage:** keep reference source, source-derived identifiers and `abi.json` out of prompts unless explicitly running an ABI-assisted experiment (which must be reported separately). Baseline tests should decompile `runtime.hex` only.

For further agent steps and correctness gates, see [`docs/llm-decompilation-tasks.md`](../docs/llm-decompilation-tasks.md).
