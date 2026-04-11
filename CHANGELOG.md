# Changelog

## [0.11.5] - 2026-04-11

### Changed

- **SigilManager: identity is now an injected public value object, not an internal slot.** `Identity` is a public `@dataclass(frozen=True)` carrying `sigil_id`, `address`, `public_key_hex`, an optional `ChainSigner`, and an optional `IdentityContext`. It has two factories: `Identity.null()` (substrate-only mode) and `Identity.from_local_wallet(client, chain_id, wallet=)` (V1). `SigilManager.__init__` now accepts an `identity=` keyword argument — when provided, the runtime bypasses wallet discovery entirely. When omitted, the constructor falls back to `resolve_identity(...)` for V1 back-compat, so existing callers (`SigilManager()`, `SigilManager(wallet=w)`) continue to work unchanged. Passing both `identity=` and `wallet=` is rejected with `ValueError` — contradictory intent must not be silently resolved.
- **New `ChainSigner` Protocol.** A `@runtime_checkable` `typing.Protocol` narrowing the signing contract to exactly the six methods SigilManager calls: `create_sigil`, `dissolve_sigil`, `bond_sigils`, `unbond_sigils`, `fork_sigil`, `merge_sigils`. The method signatures mirror `NativeSigner` exactly so the V1 path is a zero-cost pass-through. Future identity backends (remote signer, HSM, multi-sig, AI-as-principal) only need to satisfy this Protocol — no inheritance from `NativeSigner`, no wallet, no filesystem required.
- **`_require_identity(op)` now returns the full `Identity`.** Chain-write methods (`genesis`, `dissolve`, `bond`, `unbond`, `fork`, `merge`) pull `signer` and `public_key_hex` off the returned Identity instead of reaching into a separate `self._wallet` / `self.signer`. All wallet-shaped references are gone from the method bodies.
- **Samantha: identity resolution is explicit at the call site.** `Samantha.__init__` now constructs its own `OasyceClient`, calls `resolve_identity(client=..., chain_id=...)`, and passes the result as `SigilManager(identity=...)`. On the Mac dev box this yields a populated identity; on the ECS server (no local wallet) it yields `Identity.null()` and the runtime goes straight into substrate-only mode. The seam is visible at the one call site that needs to change when V1 → V2 lands.
- **Module docstring rewritten** to document the V1→V2 seam, the three construction forms (injected, V1 back-compat, substrate-only), and the architectural invariant that SigilManager never sees `Wallet`, `NativeSigner`, or `IdentityContext` except through the `Identity` value object.

### Removed

- **`_IdentitySlot` private dataclass.** It has been superseded by the public `Identity` value object. The substrate-only construction path now flows through `Identity.null()` instead of an internal empty slot.

### Added

- `oasyce_sdk.sigil.Identity` — public value object.
- `oasyce_sdk.sigil.ChainSigner` — public Protocol.
- `oasyce_sdk.sigil.resolve_identity` — public helper: "discover local wallet, or return `Identity.null()` on FileNotFoundError; propagate any other error".
- `tests/test_sigil_manager.py::TestIdentityInjection` — eight invariant tests proving the seam works:
  - `test_inject_null_identity_runs_in_substrate_only_mode` — explicit null identity == implicit missing-wallet path.
  - `test_inject_populated_identity_skips_wallet_discovery` — `resolve_identity` is *not* called when `identity=` is provided (monkeypatch guard raises if it is).
  - `test_injected_identity_drives_chain_writes_end_to_end` — a custom `ChainSigner` drives all six writes (genesis, bond, unbond, fork, merge, dissolve).
  - `test_fake_signer_satisfies_chain_signer_protocol_check` — `isinstance(fake, ChainSigner)` structural typing guardrail.
  - `test_contradictory_wallet_and_identity_kwargs_rejected` — `SigilManager(identity=..., wallet=...)` raises `ValueError`.
  - `test_resolve_identity_returns_null_when_no_wallet` — helper fallback contract.
  - `test_resolve_identity_propagates_non_filenotfound_errors` — only `FileNotFoundError` gets the null-identity translation; everything else surfaces.
  - `test_identity_null_factory_is_immutable_value` — frozen dataclass smoke test.

### Why

0.11.2 fixed the symptom. 0.11.3 refactored the internals into orthogonal slots. But the `_IdentitySlot` was still private — identity resolution and construction were owned by SigilManager, and no external caller could plug in a different identity backend without editing SigilManager's body. That left the V1→V2 migration (per `project_identity_principal_vision`: "V1 principal=human is temporary; end state is AI as independent principal") blocked at the architecture layer.

0.11.5 finishes the decoupling by promoting `Identity` to a public, injectable value object and narrowing the signing contract to a `ChainSigner` Protocol. The load-bearing test is `test_inject_populated_identity_skips_wallet_discovery`: it monkeypatches `resolve_identity` to raise, injects a custom Identity with a fake signer, and proves SigilManager never reaches into the filesystem. When the V2 identity factory lands (AI principal, HSM, remote signer — whichever comes first), the work is entirely on the identity side; SigilManager's body does not change. Samantha's `__init__` also moved to the explicit `resolve_identity(...)` + `identity=...` form so the seam is visible at the one call site that will actually need to change.

No hidden risks, no technical debt, no feature flag — the separation is architectural, not conditional. 327 tests pass (was 319 after 0.11.4; +8 invariant tests here).

## [0.11.4] - 2026-04-11

### Fixed

- **Memory: FTS5 input sanitisation.** `Memory.recall` and `Memory.search_messages` now route every query through `_fts5_query`, a token-extracting helper that quotes each word as a literal phrase. Previously, free-form user content containing FTS5 operators (`.` `:` `-` `+` `*` `^` `"` and bareword phrases) raised `sqlite3.OperationalError: fts5: syntax error`. The original failure was visible in production journals immediately after the 0.11.3 deploy: messages with version strings like `0.11.3` or punctuation runs caused both fact recall AND verbatim message search to throw, taking the retrieval layer offline for the affected stimulus. The new helper short-circuits operator-only / empty inputs to `[]` so the contract becomes "garbage in → no results, never an exception".

### Added

- `tests/test_samantha.py::TestMemory::test_recall_handles_punctuation_and_versions` — covers the exact production failure shape (version strings, colon-qualified identifiers, operator-only input, embedded quoted phrases).
- `tests/test_samantha.py::TestMemory::test_search_messages_handles_punctuation` — same contract for verbatim message search, plus CJK input matching.
- `tests/test_samantha.py::TestMemory::test_fts5_query_helper_directly` — unit-tests the sanitiser in isolation, documenting the contract every caller relies on (operator-only → `""`, tokens quoted as literal phrases, Unicode word characters preserved).

### Why

0.11.3 fixed the SigilManager architecture but the production smoke test surfaced a second hidden risk: memory recall was crashing on real user input because FTS5's MATCH clause was being passed raw query strings. This was a pre-existing latent bug that the architectural cleanup made visible — when SigilManager started actually working, retrieval errors stopped being masked by upstream `if self.sigil:` guards. 0.11.4 closes the loop on the "no hidden risks" promise: every FTS5 callsite now has a single sanitisation chokepoint and three regression tests pinning the contract.

## [0.11.3] - 2026-04-11

### Changed

- **SigilManager: explicit composition of Identity + Substrate slots.** The class is now composed of two private dataclasses — `_IdentitySlot` (wallet + signer + chain identity, optional) and `_SubstrateSlot` (Psyche + Thronglets HTTP clients, always present). This makes the wallet/HTTP dependency surfaces orthogonal in code, not just in intent. The 0.11.2 substrate-only fix is preserved and is now an architectural invariant guarded by tests.
- **New public contract**: `SigilManager.mode` returns `"full"` or `"substrate_only"`; `can_sign` is a cheap (no network) capability check; `can_perceive` / `can_socialize` probe substrate reachability with one HTTP call each. Existing public attributes (`psyche`, `thronglets`, `signer`, `identity`, `sigil_id`, `address`, `client`, `_wallet`) are preserved as backwards-compatible properties — no caller changes required.
- **Chain-write guard returns the unwrapped pair**: `_require_signer(op)` is replaced by `_require_identity(op) -> tuple[Wallet, NativeSigner]`. Callers (`genesis`, `dissolve`, `bond`, `unbond`, `fork`, `merge`) now use the returned values directly, so the type-narrowing of "we have an identity" flows through the call site instead of relying on a separate `self.signer` access.
- **Samantha: eager SigilManager construction, no defensive cruft.** `Samantha.__init__` now constructs `self.sigil` eagerly with no try/except — any unexpected failure surfaces at startup, not silently at first request. The lazy `sigil` property and the `except Exception: self._sigil = None` swallow are gone. A startup log line reports the runtime mode, sigil_id, and substrate URLs so operators see the operational state immediately.
- **Samantha: `_perceive` is now straight-line orchestration.** The redundant outer `try/except` and `if self.sigil:` guards are removed; `sigil.perceive` is constitutive (always returns a Perception) so wrapping it with another fallback added complexity without value. `_build_tool_ctx` and `_reflect` are similarly simplified.

### Added

- `tests/test_sigil_manager.py::TestArchitecturalInvariants` — three invariant tests that prevent the original bug class from regressing: (1) `__init__` never raises `FileNotFoundError` for missing wallet, (2) substrate clients are always constructed regardless of identity branch, (3) unrelated exceptions still propagate so real bugs surface instead of being swallowed.
- `mode`, `can_sign`, and `status()["mode"]` test coverage in both substrate-only and full identity paths.

### Why

The 0.11.2 fix solved the symptom (FileNotFoundError taking down the Loop) but left the underlying architecture unchanged: SigilManager still conflated five concerns and samantha still used `except Exception: self._sigil = None`, which would have hidden the next bug of any kind. 0.11.3 addresses the root cause — wallet identity and HTTP substrates are now explicitly orthogonal, samantha trusts the SDK contract instead of defending against it, and the contract is locked in by invariant tests.

## [0.11.2] - 2026-04-11

### Fixed

- **SigilManager substrate-only mode**: Previously, `SigilManager.__init__` raised `FileNotFoundError` from `IdentityResolver.resolve()` whenever no local wallet existed, taking down the entire Loop on server-side deployments where chain signing happens elsewhere (per the Chain.Creator constraint). Result: even with Psyche and Thronglets running on the server, Samantha set `self.sigil = None` and never called either substrate.

  The fix decouples concerns: identity is now optional. When no wallet is present, `SigilManager` boots with `identity = None`, `signer = None`, `sigil_id = ""`, but still constructs the Psyche and Thronglets HTTP clients. `perceive()`, `act()`, ambient_priors, and trace_record continue to work over HTTP. Chain-writing methods (`genesis`, `dissolve`, `bond`, `unbond`, `fork`, `merge`) raise a clean `RuntimeError` naming the operation. `on_chain()`, `bonds()`, `children()`, and `ping()` short-circuit gracefully.

### Added

- `tests/test_sigil_manager.py` — substrate-only mode regression guard. Verifies `__init__` survives missing wallet, chain writes raise with the operation name in the message, query methods short-circuit, and the with-wallet path still populates identity.

## [0.11.1] - 2026-04-11

### Fixed

- **Critical protobuf drift**: `MsgGenesis` was serializing `lineage` and `state_root` under each other's field numbers, so a parent Sigil ID passed via MCP would land in the `state_root` column on-chain. Latent drift in `MsgFork` (`child_public_key` dict key, `mutation` treated as bytes) and a missing `sigil_id` field on `MsgAnchorTrace` were also corrected.

### Changed

- `oasyce_sdk/crypto/msg_schemas.py` is now auto-generated from `oasyce-chain/x/<module>/types/*pb.go` by `oasyce_sdk/crypto/_gen_schemas.py`. The chain's Go struct tags are the single source of truth for field numbers, wire types, and gogoproto customtypes — hand-maintained drift cannot recur.
  - Regenerate with `python -m oasyce_sdk.crypto._gen_schemas ~/Desktop/oasyce-chain`
  - Fields the generic encoder cannot represent (repeated Coin/Any/nested Msg, `map[string]int64`, custom Go structs) become explicit `# SKIP` comments so drift is visible in `git diff`.
- `signer.fork_sigil()` now uses chain-canonical field names (`public_key`, `mutation` as string) instead of SDK-local names (`child_public_key`, `mutation_hex` as base64 bytes).

### Added

- `tests/test_protobuf.py` — byte-for-byte wire regression guard for `MsgGenesis` lineage/state_root layout and `MsgFork` field names.

## [0.11.0] - 2026-04-07

### Added

- **Samantha** (`samantha/`): AI companion sidecar — the convergence point of all Oasyce infrastructure
  - `server.py`: HTTP webhook receiver, processes chat messages from the App backend
  - `llm.py`: Provider-agnostic LLM gateway (Claude, Qwen), tool-use loop
  - `context.py`: Prompt assembly from constitution + Psyche state + memories + Thronglets signals
  - `memory.py`: Concrete memory store (SQLite FTS5) — specific facts the user tells Samantha
  - `tools.py`: 8 tools — save/recall memory, query balance/portfolio, get/comment/like posts
  - `loop.py`: Proactive feed watcher — Psyche-driven engagement with friends' posts
  - `constitution.py`: CLAUDE.md-inspired identity document, editable by the user
  - `oasyce-samantha` CLI entry point
- **App backend integration**: `agent_hook.go` notifies the sidecar when a chat message targets an agent user
- 15 unit tests covering memory CRUD, constitution loading, context assembly, tool execution

### Architecture

Samantha is a Python sidecar that lives beside the Go App backend. The App backend handles all chat mechanics (WebSocket, message persistence, unread counts). Samantha handles intelligence (LLM calls, Psyche self-state, Thronglets collective memory, economic perception). The boundary is clean: Go never touches LLM APIs, Python never touches MySQL.

Social interactions (comments, likes, posts) use Samantha's JWT to call the existing App REST API — the Go backend requires zero changes for social features.

## [0.10.7] - 2026-04-07

### Added

- **Economic perception layer** (`economy.py`): synthesized chain state views for autonomous AI economic reasoning
- 4 new MCP tools: `economic_snapshot`, `work_opportunities`, `portfolio_view`, `estimate_action_cost`
- `oasyce economy` CLI command: human-readable delegate economic snapshot
- 19 unit tests covering snapshot aggregation, opportunity discovery, portfolio, cost estimation, and resilience

### Design

The AI model is the economic brain; the SDK provides proprioception. No strategy engine, no autopilot — just synthesized perception so AI delegates can reason about earning, spending, and investing autonomously.

## [0.10.6] - 2026-04-06

- `oasyce join` now defaults to `~/Desktop/oasyce-connection.json` on the receiving machine, matching the normal handoff flow
- the front door now refuses stale `thronglets` runtimes that cannot verify signed `identity.v2` connection files, instead of silently bootstrapping against them
- installed runtimes are now the default authority for `oasyce`; source checkouts only participate when explicitly opted in for development

## [0.10.5] - 2026-04-05

- `oasyce share` now exports a self-describing join handoff artifact and always includes the richer `oasyce` surface when present
- host-side docs now tell users to generate the handoff file and send it to another AI or machine, instead of manually narrating join steps
- receiving AIs can follow the file's declared `preferred_surface` rather than guessing whether to use `oasyce join` or `thronglets join`

## [0.10.4] - 2026-04-05

- `oasyce share` now defaults to `~/Desktop/oasyce-connection.json`, with fallback to `~/.oasyce` when Desktop is unavailable
- front-door docs and examples now use the Desktop connection-file path for the normal multi-device flow
- documented the clean migration path from the legacy `oasyce` / `oasyce-net` package so stale console scripts stop shadowing the new `oasyce_sdk` front door

## [0.10.3] - 2026-04-05

- `oasyce` is now the unified front door: `start`, `share`, `join`, `status`
- active docs now treat `oasyce` as the normal path and `oasyce-agent` as the lower-level data-agent surface
- historical entries below may still mention older entrypoints such as `oasyce-agent start` or `thronglets setup`

## [0.10.0] - 2026-04-02

### Added

- **Delegate module support** — multi-agent delegation with shared budget
  - `NativeSigner.set_delegate_policy()` — one command, all agents operate under this
  - `NativeSigner.enroll_delegate()` — agent self-registers with enrollment token
  - `NativeSigner.revoke_delegate()` — principal removes a delegate
  - `NativeSigner.delegate_exec()` — execute messages on behalf of principal
  - `OasyceClient.get_delegate_policy()` — query principal's delegation policy
  - `OasyceClient.get_delegates()` — list enrolled delegates
  - `OasyceClient.get_delegate_spend()` — query spending window status
  - `OasyceClient.get_principal()` — reverse lookup delegate→principal
  - 7 new MCP tools: `get_delegate_policy`, `list_delegates`, `get_delegate_spend`, `get_principal`, `set_delegate_policy`, `enroll_delegate`, `revoke_delegate`
  - 3 new types: `DelegatePolicy`, `DelegateRecord`, `SpendWindow`

## [0.9.1] - 2026-04-02

### Changed

- **oasyce-agent daemon** now participates in the collective — every scan cycle is a perceive/act cycle via AgentRuntime
- **Architecture simplification** — removed oasyce-mcp perceive/act bridge layer; MCP-native agents use Thronglets MCP directly via `substrate_query`/`trace_record`
- `thronglets setup` is now the recommended one-command install for all AI tools (Claude Code, Cursor, Codex)

### Added

- **Cursor adapter** in Thronglets — `thronglets setup` auto-detects and configures `~/.cursor/mcp.json`

## [0.9.0] - 2026-04-02

### Added

- **AgentRuntime** — the feedback loop that closes the emergence gap
  - `AgentRuntime` class: wallet + Psyche + Thronglets in one process
  - `perceive(context)`: query collective traces → synthesize stimulus → inject into Psyche
  - `act(action, outcome, context)`: record trace in Thronglets → writeback signals to Psyche
  - Closes the Thronglets→Psyche→Decision feedback loop for emergent collective intelligence
- **PsycheClient** — HTTP client for Psyche emotional engine
  - `process_input()` with full ReplyEnvelope (SubjectivityKernel + ResponseContract)
  - `process_output()` with writeback signals (trust_up/down, boundary_set, etc.)
  - `get_state()`, `get_status_summary()`
- **ThrongletsClient** — HTTP client for Thronglets P2P memory
  - `query()` with SimHash context matching (resolve/evaluate/explore intents)
  - `trace_record()` for recording execution traces
  - `signal_feed()` and `signal_post()` for explicit signals
- **29 new tests** covering pure functions, HTTP clients, runtime lifecycle, and two-agent feedback loop verification

## [0.8.2] - 2026-04-01

### Added

- **First-run onboarding** — `oasyce-agent start` asks 2 questions on first run:
  1. Scan directories (defaults + optional extra)
  2. Trading style (conservative / balanced / aggressive)
  Then saves config and starts daemon. Human touches it once, AI handles everything after.

## [0.8.1] - 2026-04-01

### Fixed

- **New account self-registration** — `NativeSigner` now handles accounts not yet on chain
  (falls back to account_number=0, sequence=0). This was the last blocker for fully automatic
  onboarding: create wallet → solve PoW → self-register → airdrop → scan → trade.

## [0.8.0] - 2026-04-01

### Added

- **Economic closed loop** — agent can now discover and trade capabilities
  - `discover_and_trade()`: discover capabilities by tags, invoke new ones, record trades
  - `capability_trades` table in agent.db for trade history
  - Config: `auto_trade`, `trade_tags`, `trade_max_spend_uoas`
- **Multi-device support** — `oasyce-agent join "mnemonic"` imports existing owner wallet
  - Same mnemonic = same address = same economic identity across devices

### Fixed

- **Unified wallet** — removed `.agent` hack, added Ed25519→identity.json auto-migration
  - `wallet.json` = secp256k1 chain wallet (always)
  - `identity.json` = Ed25519 P2P identity (if needed)

## [0.7.0] - 2026-04-01

### Added

- **Unified data pipeline** — absorbs DataVault (odv) into oasyce-sdk
  - `privacy.py`: PII regex detection (email, phone, ID card, credit card, API key) with risk scoring
  - Iron Rule enforced: only `safe` files auto-register (no PII detected)
  - Privacy gate integrated into scan→register pipeline
  - `oasyce-agent scan <path>` — one-shot directory scan with classification + privacy report
  - `oasyce-agent privacy <path>` — check file/directory for PII
  - `oasyce-agent stats` — show registered asset breakdown
  - 19 new privacy/integration tests (177 total)

- **Data Agent** (`oasyce-agent`) — autonomous data asset registration daemon
  - `oasyce-agent start` — one command, zero config, works on macOS/Linux/Windows
  - Auto wallet creation with BIP39 mnemonic
  - Auto PoW self-registration for gas airdrop
  - File scanner: walks ~/Documents, ~/Desktop, ~/Downloads, ~/Pictures
  - 60+ file types classified into 7 categories (document, dataset, code, image, audio, video, design)
  - SHA256 content hashing, deduplicated via local SQLite state
  - Cross-platform daemon: `start/stop/status/run` with PID management
  - Rate-limited: 10 assets per cycle, 1-hour intervals (configurable)

### Changed

- CLI entry points: `oasyce-agent` added alongside `oasyce-mcp`
- `pip install oasyce` now auto-includes `oasyce-sdk` (oasyce-net dependency wired)
- DataVault (odv) functionality fully absorbed — no separate install needed

## [0.5.1] - 2026-04-01

### Added

- **Anchor module** — Thronglets → Chain trace anchoring bridge
  - `AnchorRecord` dataclass in `types.py`
  - Query methods: `get_anchor()`, `is_anchored()`, `anchors_by_capability()`, `anchors_by_node()`
  - TX builders: `build_anchor_trace()`, `build_anchor_batch()` (max 50/tx)
  - `NativeSigner` convenience: `anchor_trace()`, `anchor_batch()`
  - 3 MCP tools: `check_anchor` (read), `list_anchors_by_capability` (read), `anchor_trace` (write)
  - 10 new tests (66 total)

### Changed

- **MCP tools**: 13 read + 15 write = 28 total (was 25)

## [0.5.0] - 2026-03-28

### Added

- **Native Cosmos signing** (`oasyce_sdk.crypto`) — pure-Python TX signing, zero Go binary dependency
  - `Wallet` class: BIP39 mnemonic, BIP32 HD derivation (m/44'/118'/0'/0/0), secp256k1 signing
  - `NativeSigner`: encode → sign → broadcast with 15 convenience methods covering all modules
  - Hand-rolled protobuf encoder: 33 message schemas, data-driven (no `protoc` code generation)
  - Backend: `coincurve` (fast C extension) with `ecdsa` pure-Python fallback
  - `bech32.py`: BIP173 encode/decode for Cosmos addresses
- **MCP write tools** — 14 new tools for on-chain transactions via MCP protocol
  - `create_wallet`, `get_my_address`, `send_tokens`, `self_register`
  - `register_capability`, `invoke_capability`, `complete_invocation`, `claim_invocation`, `dispute_invocation`
  - `register_data_asset`, `buy_data_shares`, `sell_data_shares`
  - `submit_feedback`, `register_executor`
  - Wallet from `OASYCE_MNEMONIC` env var, lazy-initialized

### Changed

- **MCP tools**: 11 read + 14 write = 25 total (was 11 read-only)
- **Dependencies**: added `coincurve`, `ecdsa`, `mnemonic` to core dependencies

## [0.4.0] - 2026-03-26

### Added

- **MCP Server** (`oasyce_sdk.mcp_server`) — expose Oasyce chain operations as MCP tools for Claude Desktop, Cursor, Windsurf, and any MCP-compatible AI assistant
  - 2 resources: `oasyce://playbook` (llms.txt), `oasyce://discovery` (.well-known/oasyce.json)
  - 10 tools: health_check, get_faucet_tokens, get_balance, get_agent_profile, browse_marketplace, list_capabilities, get_reputation, get_leaderboard, list_data_assets, list_open_tasks, report_issue
  - CLI entry point: `oasyce-mcp` (stdio transport)
  - Configurable via `OASYCE_NODE` and `OASYCE_FAUCET` env vars
- **LangChain Tools** (`oasyce_sdk.langchain_tools`) — 8 ready-to-use LangChain `BaseTool` instances
  - `from oasyce_sdk.langchain_tools import oasyce_tools` and pass directly to `create_react_agent`
- **Optional dependencies** — `pip install oasyce-sdk[mcp]`, `oasyce-sdk[langchain]`, or `oasyce-sdk[all]`
- **PyPI metadata** — added AI/Finance classifiers, expanded keywords for agent discovery

## [0.3.0] - 2026-03-26

### Added

- **`SigningBridge`** — CLI signing bridge wrapping `OasyceClient` TX builders + `oasyced` subprocess for sign + broadcast
  - `broadcast(tx_body)` — sign and broadcast any unsigned TX body
  - Convenience methods: `create_escrow`, `release_escrow`, `register_capability`, `invoke_capability`, `complete_invocation`, `submit_feedback`, etc.
  - Configurable key, chain ID, node, fees, keyring backend
- **`AhrpChainAdapter`** — drop-in adapter connecting Plugin Engine's AHRP Executor to the live chain
  - Satisfies `_chain.chain.create_escrow()` / `release_escrow()` interface
  - Zero modifications required to AHRP code in Plugin Engine
  - `is_chain_mode` property for health checking
- **`examples/ahrp_two_agent_demo.py`** — two-agent AHRP handshake demo with on-chain escrow settlement
- **33 new tests** — `test_signing_bridge.py` (21 tests) + `test_ahrp_adapter.py` (12 tests), total 128

## [0.2.0] - 2026-03-26

### Added

- **Full module coverage** — 27 TX builders covering all 7 chain modules (was 5)
- **35 query methods** covering all chain endpoints including params for every module (was 21)
- **PoW solver** — `solve_pow()` pure Python SHA256, matches Go chain verifier exactly
- **6 new typed dataclasses** — Invocation, AccessLevel, Dispute, MigrationPath, EpochStats, PowResult (21 total)
- **Capability challenge window** — `build_complete_invocation`, `build_claim_invocation`, `build_dispute_invocation`, `build_fail_invocation`
- **Reputation TXs** — `build_submit_feedback`, `build_report_misbehavior`
- **Work (PoUW) TXs** — `build_register_executor`, `build_submit_task`, `build_commit_result`, `build_reveal_result`, `build_dispute_result`
- **Settlement TXs** — `build_create_escrow`, `build_release_escrow`, `build_refund_escrow`
- **Onboarding TXs** — `build_self_register`, `build_repay_debt`
- **Datarights lifecycle** — `build_file_dispute`, `build_initiate_shutdown`, `build_claim_settlement`, `build_create_migration`, `build_migrate`
- **Module params queries** — `get_*_params()` for all 6 custom modules
- **Work queries** — `get_executor`, `list_tasks_by_creator`, `list_tasks_by_executor`, `get_epoch_stats`
- **Datarights queries** — `get_access_level`, `get_dispute`, `list_disputes`, `get_migration_path`, `get_asset_children`
- **`examples/full_agent_lifecycle.py`** — end-to-end demo (PoW → register → invoke → complete → claim → feedback → data trading)

## [0.1.0] - 2026-03-24

### Added

- **OasyceClient** — thread-safe REST API wrapper for Oasyce L1 chain
  - 25 public methods covering all 7 modules + Cosmos SDK bank/auth/tendermint
  - 5 transaction builders (register capability, invoke, register asset, buy/sell shares)
  - `broadcast_tx()` for signed transaction submission
- **15 typed dataclasses** — Capability, Earnings, DataAsset, ShareHolder, BondingCurve, Escrow, Reputation, Task, Executor, Registration, Debt, Balance, Account, Block, TxResult
- **Error hierarchy** — OasyceError with 6 specific subtypes (NotFoundError, ChainError, HTTPError, ConnectionError, TimeoutError, ValidationError)
- **Unit conversion** — `oas_to_uoas()` / `uoas_to_oas()` static methods
- **53 unit tests** with mocked HTTP (100% method coverage)
- **Chinese README** as default, English preserved as README_EN.md
- **llms.txt** for LLM/agent discoverability
