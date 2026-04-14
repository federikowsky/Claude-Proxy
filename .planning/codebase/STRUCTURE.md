# STRUCTURE.md — Directory Layout & Organization

## Repository Root

```
Claude-Proxy/
├── claude_proxy/          # Main package
├── tests/                 # Test suite
├── config/                # YAML configuration files
├── data/                  # Runtime SQLite DB (generated)
├── docs/                  # Specs, design docs, migration notes
├── pyproject.toml         # Build system & project metadata
├── README.md
├── DECISIONS.md           # Architecture decision records
├── TASKS.md               # Development task tracking
└── .planning/             # GSD planning artifacts (this directory)
```

## `claude_proxy/` Package Structure

```
claude_proxy/
├── __init__.py
├── __main__.py            # CLI entry point: uvicorn.run(create_app())
├── main.py                # create_app() factory — wires all layers
├── jsonutil.py            # orjson/stdlib json shim
│
├── domain/                # Pure domain: models, enums, errors, ports, serialization
│   ├── enums.py           # Role, CompatibilityMode, ToolCategory, ActionPolicy, …
│   ├── errors.py          # BridgeError hierarchy (all with HTTP status + error_type)
│   ├── models.py          # Frozen dataclasses: ChatRequest, Message, ContentBlock variants, Events, …
│   ├── ports.py           # Protocols: ModelProvider, ModelResolver, SseEncoder, …
│   └── serialization.py   # dict ↔ domain object conversion; normalize_tool_schema()
│
├── application/           # Use cases and transformations (no HTTP, no infra)
│   ├── policies.py        # CompatibilityNormalizer, StreamEventSequencer
│   ├── request_preparer.py # ModelAwareRequestPreparer: field strip, schema norm, classify
│   ├── runtime_actions.py # RuntimeActionClassifier: tool-use → RuntimeActionType
│   ├── runtime_contract.py # RuntimeContractEnforcer: pre-flight checks
│   ├── services.py        # MessageService: stream(), complete(), count_tokens()
│   ├── sse.py             # AnthropicSseEncoder, AnthropicResponseEncoder
│   ├── tool_classifier.py # ToolClassifier: thin wrapper over CapabilityRegistry
│   └── tool_contracts/    # Per-tool SDK contract definitions
│
├── capabilities/          # Registry-driven tool knowledge / semantic contracts
│   ├── builtins.py        # ~50 CapabilityRecord rows (the frozen inventory)
│   ├── coverage_matrix.py # Coverage reporting utilities
│   ├── enums.py           # CapabilityInventoryClass, BridgeImplementationStatus, SchemaContractKind, …
│   ├── families.py        # Capability grouping by family
│   ├── generic_tool_misuse.py # Generic tool misuse detection heuristics
│   ├── ordinary_tool_emulation.py # Emulation detection
│   ├── bash_emulation.py  # Bash-specific emulation detection
│   ├── record.py          # CapabilityRecord dataclass
│   ├── registry.py        # CapabilityRegistry (lru_cache singleton), is_mcp_style_tool_name()
│   ├── signals.py         # ToolUseSignalContext (delivery, origin, session_state)
│   ├── text_control.py    # apply_text_control_policy() — model plain-text detection
│   ├── tool_use_normalize.py # apply_schema_contract() per SchemaContractKind
│   └── tool_use_prepare.py   # normalize_tool_use_for_runtime(), repair_stream_tool_blocks()
│
├── api/                   # FastAPI layer: routing, schemas, error handling
│   ├── dependencies.py    # Depends(get_message_service), Depends(get_runtime_orchestrator)
│   ├── errors.py          # install_error_handlers(): BridgeError → JSONResponse
│   ├── http_debug.py      # install_http_debug_middleware(): body preview (debug only)
│   ├── schemas.py         # Pydantic request models with .to_domain()
│   └── routes/
│       ├── health.py      # GET /health
│       ├── messages.py    # POST /v1/messages, POST /v1/messages/count_tokens
│       └── runtime_control.py  # GET/POST /v1/runtime/sessions/…
│
├── infrastructure/        # Concrete implementations: config, HTTP, providers, logging
│   ├── config.py          # Settings hierarchy, load_settings(), env overrides
│   ├── http.py            # SharedAsyncClientManager (shared httpx.AsyncClient)
│   ├── logging.py         # JsonFormatter, setup_logging()
│   ├── resolvers.py       # StaticModelResolver: model name → ModelInfo
│   └── providers/
│       ├── __init__.py    # build_provider_registry()
│       └── openrouter.py  # OpenRouterProvider, OpenRouterTranslator, IncrementalSseParser
│
└── runtime/               # Optional stateful orchestration engine
    ├── actions.py          # NormalizedRuntimeAction dataclass
    ├── classifier.py       # RuntimeModelClassifier: tool block → ModelClassification
    ├── errors.py           # Runtime-specific errors (InvalidRuntimeTransitionError, etc.)
    ├── event_log.py        # RuntimeEventLog protocol + InMemoryRuntimeEventLog
    ├── events.py           # RuntimeEventKind StrEnum, RuntimeEvent dataclass
    ├── invariants.py       # assert_runtime_invariants()
    ├── orchestrator.py     # RuntimeOrchestrator: load/persist/apply/process
    ├── policies.py         # RuntimeOrchestrationPolicies dataclass + resolution StrEnums
    ├── policy_binding.py   # policies_from_settings()
    ├── recovery.py         # replay_events(), restore_checkpoint_then_replay_tail()
    ├── session_codec.py    # session_to_dict / session_from_dict serialization
    ├── session_store.py    # RuntimeSessionStore protocol + InMemoryRuntimeSessionStore
    ├── state.py            # RuntimeState, ModeQualifiers, SessionRuntimeState
    ├── state_machine.py    # apply_runtime_transition() — deterministic FSM (~580 lines)
    ├── stream.py           # runtime_orchestrate_stream() async generator
    └── persistence/
        └── sqlite_backend.py  # SqliteRuntimeStores, SqliteRuntimeSessionStore, SqliteRuntimeEventLog
```

## `tests/` Structure

```
tests/
├── conftest.py             # Shared fixtures: base_config(), MockAsyncByteStream
├── fixtures/               # SSE wire-format fixture files (.sse) + expected outputs (.expected)
│   ├── provider_text.sse / .expected
│   ├── provider_tool_use.sse / .expected
│   ├── provider_reasoning_only.sse / .expected
│   ├── provider_text_reasoning.sse / .expected
│   └── provider_unknown.sse / .expected
├── golden/
│   └── test_sse_golden.py  # End-to-end SSE fixture golden tests
├── integration/
│   ├── test_messages_endpoint.py        # Full HTTP endpoint tests via TestClient
│   ├── test_outbound_tool_repair_claude_code.py
│   ├── test_runtime_bridge.py           # Runtime orchestration bridge tests
│   ├── test_runtime_control_http.py     # /v1/runtime control API tests
│   ├── test_runtime_e2e_flows.py        # End-to-end state machine flow tests
│   └── test_runtime_orchestration.py
└── unit/
    ├── test_api_schema.py
    ├── test_capability_registry.py
    ├── test_config.py
    ├── test_encoder.py
    ├── test_http_client.py
    ├── test_http_debug_middleware.py
    ├── test_normalizer.py
    ├── test_openrouter_adapter.py
    ├── test_request_preparer.py
    ├── test_resolver.py
    ├── test_runtime_action_classifier.py
    ├── test_runtime_contract.py
    ├── test_runtime_contract_stream.py
    ├── test_runtime_policy_config.py
    ├── test_runtime_sqlite.py
    ├── test_schema_normalizer.py
    ├── test_stream_sequencer.py
    ├── test_text_control.py
    ├── test_tool_classifier.py
    ├── test_tool_input_normalize.py
    ├── test_validation_debug_log.py
    └── runtime/
        ├── test_classifier.py
        ├── test_invariants.py
        ├── test_orchestrator.py
        ├── test_recovery.py
        ├── test_state_machine.py
        └── test_stream_runtime.py
```

## `config/` Structure

```
config/
├── claude-proxy.example.yaml   # Full reference config with all options documented
├── claude-proxy.yaml           # Active config (gitignored or local override)
└── claude-proxy-test.yaml      # Test configuration
```

## `docs/` Structure

```
docs/
├── spec.md, spec2.md           # Protocol/bridge specification documents
├── toolin2.md, tooling_ir.md   # Tooling IR / intermediate representation docs
├── migration-v2.md             # v1 → v2 migration guide
└── runtime/
    ├── capability-coverage.json        # Machine-readable coverage matrix
    ├── capability-inventory-freeze.md  # Frozen capability inventory (source of truth for builtins.py)
    └── semantic-contract-matrix.md     # Schema contract matrix per tool
```

## Key Naming Conventions

| Pattern | Meaning |
|---------|---------|
| `*Provider` | Implements `ModelProvider` protocol (upstream adapter) |
| `*Resolver` | Implements `ModelResolver` protocol |
| `*Normalizer` | Stream/response transformation |
| `*Encoder` | Serialization to wire format (SSE bytes or JSON dict) |
| `*Preparer` | Pre-flight request mutation pipeline |
| `*Classifier` | Classification/categorization without mutation |
| `*Orchestrator` | Stateful session lifecycle owner |
| `*Store` | State persistence protocol/implementation |
| `*Log` | Append-only event log protocol/implementation |
| `CanonicalEvent` | Internal normalized event type (traverses the whole pipeline) |
| `ChatRequest` / `ChatResponse` | Domain-level request/response (not HTTP, not provider) |
