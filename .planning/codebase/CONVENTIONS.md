# CONVENTIONS.md — Code Style, Patterns & Error Handling

## Language Conventions

### Module Header
Every module opens with `from __future__ import annotations`. This is a hard convention across the entire codebase.

### Imports
- Grouped: stdlib → third-party → local
- Local imports always use full package paths from `claude_proxy.*`
- Type-only imports use `from __future__ import annotations` (not `TYPE_CHECKING` guards)

### Type Annotations
- All public functions/methods are fully annotated
- Return types always explicit, including `None`
- `TypeAlias` used for complex union types (`JsonMap`, `ContentBlock`, `CanonicalEvent`)
- `Mapping[str, Any]` preferred over `dict[str, Any]` for read-only parameters

### Data Model Pattern
Domain objects use `@dataclass(slots=True, frozen=True)`:
```python
@dataclass(slots=True, frozen=True)
class TextBlock:
    text: str
    extras: JsonMap = field(default_factory=dict)
    type: str = field(init=False, default="text")
```
- `slots=True`: memory efficiency + accidental attribute prevention
- `frozen=True`: immutability, hashable
- `type` field pattern: `field(init=False, default="...")` for discriminator fields

### Enum Pattern
All enums use `StrEnum` (never `IntEnum` or plain `Enum`):
```python
class RuntimeState(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
```
Prefer comparison via `is` (identity) for StrEnum values where possible.

### Protocol Pattern
Port interfaces defined as `Protocol` in `domain/ports.py`:
```python
class ModelProvider(Protocol):
    async def stream(self, request: ChatRequest, ...) -> AsyncIterator[CanonicalEvent]: ...
```
`@runtime_checkable` where needed. Concrete implementations never inherit from Protocol directly.

## Naming Conventions

| Category | Convention | Example |
|----------|-----------|---------|
| Classes | PascalCase | `MessageService`, `CapabilityRegistry` |
| Functions/methods | snake_case | `apply_runtime_transition()` |
| Private methods | `_snake_case` | `_resolve()`, `_validate_request()` |
| Constants | `_UPPER_SNAKE_CASE` | `_FALLBACK_OBJECT_SCHEMA`, `_TERMINAL` |
| Module-level loggers | `_logger` | `_logger = logging.getLogger(...)` |
| Logger names | `claude_proxy.<subsystem>` | `claude_proxy.stream`, `claude_proxy.request` |
| Config env overrides | `CLAUDE_PROXY__<SECTION>__<KEY>` | `CLAUDE_PROXY__SERVER__DEBUG` |

## Structured Logging Pattern

Always use `extra={"extra_fields": {...}}` for structured context:
```python
_logger.info(
    "stream_start model=%s provider=%s",
    model.name, model.provider,
    extra={"extra_fields": {"model": model.name, "provider": model.provider}},
)
```
This feeds `JsonFormatter` which merges `extra_fields` into the JSON log payload.

## Error Handling Pattern

### Domain Errors
All errors are `BridgeError` subclasses with `status_code` and `error_type`:
```python
class ProviderAuthError(BridgeError):
    status_code = 502
    error_type = "provider_auth_error"
```
Concrete errors raised in domain/infrastructure, caught once in FastAPI error handlers.

### Error Construction
Use `details=` for structured error context:
```python
raise ProviderBoundaryError(
    "tool has invalid schema",
    details={"tool": tool.name, "schema": repr(schema)},
)
```

### Never Swallow Exceptions
`except Exception` only at boundary layers (FastAPI handlers, lifespan cleanup). All other catches re-raise or wrap in `BridgeError`.

## Immutability & Mutation Pattern

Mutations use `dataclasses.replace()`:
```python
s = replace(base, state=RuntimeState.PLANNING, ...)
```
Original objects are never mutated. The state machine returns new `SessionRuntimeState` instances on every transition.

**Identity preservation**: request preparer returns the original `ChatRequest` unchanged if no mutations apply:
```python
if not stripped_fields and not tools_changed:
    return request  # same object
```

## Async Pattern

- All I/O is `async def`; no `asyncio.run()` inside library code
- Async generators used for streaming: `async def ... -> AsyncIterator[T]`
- `asynccontextmanager` for lifespan in FastAPI
- No `asyncio.gather()` calls — requests are processed sequentially per connection
- Lock: `asyncio.Lock()` for shared client initialization; `threading.Lock()` for SQLite (thread-safe, not async-safe)

## Configuration Validation

Pydantic models with `extra="forbid"` everywhere:
```python
class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
```
Cross-field validation via `@model_validator(mode="after")` in `Settings`.

## Feature Flags Pattern

Capabilities are gated via `ActionPolicy` (ALLOW / WARN / BLOCK) per model in config:
```python
schema_normalization_policy: ActionPolicy = ActionPolicy.ALLOW
control_action_policy: ActionPolicy = ActionPolicy.WARN
```
Runtime orchestration gated by `bridge.runtime_orchestration_enabled`.

## Singleton Registry Pattern

`CapabilityRegistry` is constructed once and cached:
```python
@lru_cache(maxsize=1)
def get_capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry(builtin_capability_records())
```

## Test Infrastructure Pattern

Test fixtures build config dicts in code (not files):
```python
def base_config() -> dict[str, Any]:
    return {"server": {...}, "routing": {...}, ...}
```
Config dicts written to `tmp_path` YAML files, then loaded via `load_settings()`. HTTPX transport injected via `create_app(settings=..., transport=mock_transport)`.

## Documentation Synchronization

The `capabilities/builtins.py` registry rows must stay in sync with `docs/runtime/capability-inventory-freeze.md`. Changes to either require updating both (cross-file contract).
