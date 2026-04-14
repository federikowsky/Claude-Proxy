# CONCERNS.md — Technical Debt, Issues & Fragile Areas

## Summary

The codebase is well-structured and clean. Most concerns are intentional trade-offs from scope decisions (MVP/brownfield), not code quality problems. The highest-risk areas are the runtime state machine complexity and the single-provider architecture.

---

## 1. Single-Provider Architecture (Design Scope)

**Severity**: Medium (future extensibility)
**File**: `infrastructure/providers/openrouter.py`, `infrastructure/providers/__init__.py`

Only one provider (`OpenRouterProvider`) is implemented. `build_provider_registry()` returns a single-entry dict. The `ModelProvider` port exists and can be extended, but:
- Provider selection is implicit in `MessageService._resolve()` via `ModelInfo.provider`
- Adding a second provider (e.g. direct Anthropic) requires a new `*Provider` class but no structural changes
- No concern if only OpenRouter is ever needed; notable if multi-provider is planned

---

## 2. Runtime State Machine Complexity

**Severity**: Medium (maintenance burden)
**File**: `runtime/state_machine.py` (~580 lines)

`apply_runtime_transition()` is a monolithic match/if-chain covering 14 states × ~20 event kinds. It is:
- Correct and well-tested (`test_state_machine.py`)
- Difficult to extend without introducing edge cases
- Hard to read holistically; requires following all branches to understand full transition table

**Risk**: New event kinds or states require careful integration; missing cases in the chain are not compiler-enforced.

---

## 3. SQLite Backend is Synchronous in an Async App

**Severity**: Medium (potential latency spike under load)
**File**: `runtime/persistence/sqlite_backend.py`

`sqlite3` is synchronous; it is called under `threading.Lock()` but **not** wrapped in `asyncio.run_in_executor()`. All SQLite operations block the event loop thread momentarily.

**Impact**: Under low to moderate concurrency (expected for a local proxy), this is negligible. Under high concurrency the event loop can stall during session reads/writes.

**Mitigation**: `asyncio.run_in_executor` wrapping or replacing with `aiosqlite` would resolve this. No current workaround.

---

## 4. No Authentication / Authorization on Control Plane

**Severity**: Medium (security — intentional for local use)
**File**: `api/routes/runtime_control.py`

All `/v1/runtime/sessions/…` endpoints are unauthenticated. Any process that can reach the server can read/modify session state, approve actions, trigger aborts, etc.

**Stated intent**: Designed for local use. This is documented in `DECISIONS.md`.
**Risk**: If the proxy is ever exposed on a network interface, this becomes a real threat surface (SSRF, session hijacking via control plane, unauthorized approval of model actions).

---

## 5. `CapabilityRegistry` Singleton via `lru_cache`

**Severity**: Low (test isolation)
**File**: `capabilities/registry.py`

`get_capability_registry()` is `@lru_cache(maxsize=1)`. Tests that need custom registries must either use the singleton directly or construct `CapabilityRegistry(...)` manually (not calling `get_capability_registry()`). A modified singleton leaks between tests if not cleared.

**Observation**: Current tests appear to construct their own `CapabilityRegistry` instances where needed, avoiding the issue. Worth watching if new tests use the global.

---

## 6. `builtins.py` / `capability-inventory-freeze.md` Dual Source of Truth

**Severity**: Low-Medium (maintenance discipline)
**Files**: `capabilities/builtins.py`, `docs/runtime/capability-inventory-freeze.md`

The capability inventory exists in two places:
- `builtins.py`: executable Python registry rows (tests enforce it)
- `docs/runtime/capability-inventory-freeze.md`: human-readable freeze document (not machine-validated)

If a capability is added to one but not the other, the documentation drifts silently. There is no automated sync check between them.

---

## 7. `pragma: no cover` on Valid Code Paths

**Severity**: Low (coverage accuracy)
**Files**: `infrastructure/config.py` line 157, `jsonutil.py` line 7

Two `# pragma: no cover` annotations suppress coverage on:
1. `orjson` import fallback in `jsonutil.py` — acceptable (import-time branch)
2. `Settings.model_validate(raw)` exception handler in `config.py` — marked as "no cover" but the error path is reachable; the comment says `# pragma: no cover` presumably because it's hard to trigger in normal tests

No coverage tooling is configured (`pytest-cov` not in deps), so these are advisory only.

---

## 8. `MessageService` Constructor Has Many Parameters

**Severity**: Low (code smell)
**File**: `application/services.py`

`MessageService.__init__` takes 11 keyword-only parameters. All are wired in `create_app()`. This is a direct consequence of the hexagonal architecture (all ports injected). It works but can make reading `create_app()` harder.

---

## 9. `StreamEventSequencer` Implementation Unknown

**Severity**: Low (documentation gap)
**File**: `application/policies.py`

`StreamEventSequencer` is constructed and passed to `MessageService` but its implementation is part of `application/policies.py`. The sequencer's exact buffering/ordering behavior is worth documenting if the stream ordering contract matters for clients.

---

## 10. No Rate Limiting or Request Queuing

**Severity**: Low (operational gap for production use)

There is no per-client or global rate limiting. If deployed beyond local use, all provider API quotas are shared with no backpressure. Mitigation would require middleware or a queue layer.

---

## Low-Risk / Intentional Constraints

| Item | Status |
|------|--------|
| No multimodal support | Intentional (MVP scope, per `DECISIONS.md`) |
| Non-stream requests are implemented but `supports_nonstream` rarely used | Noted in model config |
| `orjson` optional, stdlib fallback | Works correctly; `orjson` is not listed as a required dep |
| `debug_echo_upstream_body` on provider config | Dev flag; disabled by default |
| Single shared `httpx.AsyncClient` per process | Intentional (`DECISIONS.md`) |
