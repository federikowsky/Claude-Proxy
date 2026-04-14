# TESTING.md — Test Structure & Practices

## Framework & Configuration

| Tool | Role |
|------|------|
| `pytest` `>=8.4` | Test runner |
| `pytest-asyncio` `>=1.1` | Async test support |
| `respx` `>=0.22` | HTTPX request mocking |
| `asyncio_mode = "auto"` | All async tests auto-detected (in `pyproject.toml`) |

**Run all tests**:
```sh
pytest
```

**Run specific group**:
```sh
pytest tests/unit/
pytest tests/integration/
pytest tests/golden/
```

## Test Layout

```
tests/
├── conftest.py              # Shared fixtures and helpers
├── fixtures/                # SSE wire-format + expected output pairs
├── golden/                  # Golden file comparison tests
├── integration/             # Full HTTP stack tests (TestClient)
└── unit/
    ├── *.py                 # Module-level unit tests
    └── runtime/             # Runtime subsystem unit tests
```

**Total LOC**: ~5,200 lines across ~30 test files (excluding fixtures)

## Shared Fixtures (`tests/conftest.py`)

### `base_config() -> dict`
Returns a complete in-code config dict suitable for `load_settings()`. Avoids YAML file dependency in most tests.

### `MockAsyncByteStream`
`httpx.AsyncByteStream` implementation that yields bytes from a pre-defined list. Used to simulate upstream SSE responses without real HTTP calls.

## Mocking Strategy

### HTTPX Transport Injection
The `create_app()` factory accepts `transport=` parameter. Tests inject `respx.MockTransport` or `httpx.MockTransport` to intercept provider calls:

```python
transport = respx.MockTransport()
transport.route("POST", "https://openrouter.ai/api/v1/chat/completions").mock(
    return_value=httpx.Response(
        200,
        stream=MockAsyncByteStream([b"event: ...", ...]),
    )
)
app = create_app(settings=settings, transport=transport)
```

### Config Construction
Tests build `Settings` from in-memory dicts written to `tmp_path`:
```python
config_path = tmp_path / "config.yaml"
with config_path.open("w") as f:
    yaml.safe_dump(base_config(), f)
settings = load_settings(config_path)
```

### Environment Variables
Monkey-patched via `monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")`.

Global default in `conftest.py`: `os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")`.

## Test Categories

### Unit Tests (`tests/unit/`)

Pure isolated tests of individual modules:

| File | Covers |
|------|--------|
| `test_api_schema.py` | Pydantic request schemas, `.to_domain()` conversion |
| `test_capability_registry.py` | CapabilityRegistry aliasing, classification, MCP detection |
| `test_config.py` | Settings loading, env overrides, validation |
| `test_encoder.py` | AnthropicSseEncoder, AnthropicResponseEncoder |
| `test_http_client.py` | SharedAsyncClientManager limits calculation |
| `test_http_debug_middleware.py` | Debug middleware body preview |
| `test_normalizer.py` | CompatibilityNormalizer stream/response normalization |
| `test_openrouter_adapter.py` | OpenRouterTranslator payload mapping, SSE parsing |
| `test_request_preparer.py` | ModelAwareRequestPreparer field stripping, schema norm |
| `test_resolver.py` | StaticModelResolver model lookup |
| `test_runtime_action_classifier.py` | RuntimeActionClassifier type classification |
| `test_runtime_contract.py` | RuntimeContractEnforcer pre-flight checks |
| `test_runtime_contract_stream.py` | Contract enforcer on streamed tool blocks |
| `test_runtime_policy_config.py` | Policy YAML → RuntimeOrchestrationPolicies binding |
| `test_runtime_sqlite.py` | SQLite session store + event log CRUD |
| `test_schema_normalizer.py` | `normalize_tool_schema()` all repair branches |
| `test_stream_sequencer.py` | StreamEventSequencer ordering |
| `test_text_control.py` | TextControl policy detection |
| `test_tool_classifier.py` | ToolClassifier category assignment |
| `test_tool_input_normalize.py` | Per-contract schema repair |
| `test_validation_debug_log.py` | Validation error debug logging |
| **`runtime/`** | Full runtime subsystem: state machine, invariants, classifier, orchestrator, recovery, stream |

### Integration Tests (`tests/integration/`)

Full HTTP endpoint tests using FastAPI `TestClient` (sync wrapper over ASGI):

| File | Covers |
|------|--------|
| `test_messages_endpoint.py` | `/v1/messages` stream/non-stream, tool repair, policy enforcement (~790 lines) |
| `test_outbound_tool_repair_claude_code.py` | Outbound repair for Claude Code tool contracts |
| `test_runtime_bridge.py` | Runtime orchestrator + HTTP endpoint integration |
| `test_runtime_control_http.py` | `/v1/runtime/sessions/*` control plane endpoints |
| `test_runtime_e2e_flows.py` | End-to-end state machine flows through SSE stream |
| `test_runtime_orchestration.py` | RuntimeOrchestrator orchestration scenarios |

### Golden Tests (`tests/golden/test_sse_golden.py`)

Compare full SSE output against fixture files:
- Input: `tests/fixtures/*.sse` (raw upstream SSE bytes)
- Expected: `tests/fixtures/*.expected` (expected client-facing SSE output)
- Cases: `text`, `tool_use`, `reasoning_only`, `text_reasoning`, `unknown`

## Common Test Patterns

### Async Test
```python
@pytest.mark.asyncio  # or omit with asyncio_mode=auto
async def test_stream():
    ...
```

### Parametrize
`@pytest.mark.parametrize` used extensively in state machine tests to cover all transition cases.

### Assert SSE Sequence
Tests decode SSE frames line-by-line and assert on parsed JSON data fields in order.

### State Machine Test Pattern
```python
session = idle_session("sid")
session, _ = apply_runtime_transition(session, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=policies)
assert session.state == RuntimeState.EXECUTING
```

## Coverage Notes

- No coverage tooling configured in `pyproject.toml` (no `pytest-cov` in dev deps)
- `# pragma: no cover` appears on 2 lines: unreachable import fallback in `jsonutil.py` and exception handler in `config.py`
- The state machine (`state_machine.py`) has comprehensive parametrized unit tests in `tests/unit/runtime/test_state_machine.py`
- SQLite backend tested in `test_runtime_sqlite.py` using `tmp_path` fixture
