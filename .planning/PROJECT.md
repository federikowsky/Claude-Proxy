# PROJECT.md

## Name
claude-proxy

## Vision
Local Python 3.14 proxy that presents an Anthropic Messages API surface while normalizing heterogeneous upstream providers (Anthropic, OpenAI, OpenRouter) into a canonical Anthropic-compatible output. Dual-protocol ingress (Anthropic Messages + OpenAI Chat Completions) so both Claude Code and Codex-compatible clients work through the same proxy.

## Principles
- **Protocol fidelity**: every adapter must produce bit-correct Anthropic-compatible output; no implicit transformations or hacks
- **Explicit typing**: all protocol differences are modeled as typed adapters, not conditionals scattered in the pipeline
- **Ports and Adapters**: domain layer is provider-agnostic; new providers plug in without touching core
- **Local-first**: designed for single-user local operation; no auth, no multi-tenancy
- **Minimal surface**: MVP delivers streaming + non-streaming completions and token counting; no tool-calling server-side, no multimodal, no waterfall protocols

## Python Quality Standards

### Design
- SOLID, DRY, KISS, SRP — strictly enforced
- Compact, readable, elegant; clear responsibility boundaries per file/class/function

### Performance & Optimization
- Algorithmic design first (Big-O); no premature micro-optimization
- Right data structure for the job: `list` (indexed access), `deque` (head ops), `dict`/`set` (O(1) lookup), `heapq` (priority), `bisect` (sorted search), `array` (memory density)
- No redundant work: memoize where justified, avoid gratuitous copies/conversions, single-pass iteration preferred
- Minimize allocations: generator expressions over materialized lists when result stays ephemeral; stream I/O (file, network) when possible
- Batch I/O operations; adequate buffering for file reads/writes
- Exploit short-circuiting: `and`, `or`, `any`, `all`
- Concurrency where appropriate: `asyncio` for I/O-bound, `concurrent.futures`/`multiprocessing` for CPU-bound, `asyncio.to_thread` for lightweight blocking calls

### Idiomatic Python
- Leverage C-level builtins: `map`, `any`, `all`, `filter`, `sum`, `min`, `max`, `sorted`, `enumerate`, `zip`, `reversed`
- Leverage C-optimized stdlib: `itertools`, `functools`, `collections`, `operator`, `math`, `statistics`, `heapq`, `bisect`
- Prefer comprehensions and generator expressions for compact, fast code
- Use native string/list methods (`str.join`, `list.extend`, `list.sort`) over hand-rolled equivalents

### Dependencies
- Minimal external deps; prefer C/Rust-optimized libraries when pure-Python alternatives are slower
- External library usage must be correct, idiomatic, and aligned with official documentation

## Stack
- Python 3.14, FastAPI, httpx, Pydantic 2, uvicorn
- SQLite for optional runtime session persistence
- YAML config with env overrides

## Current State
Working single-provider proxy (OpenRouter only) with Anthropic-compatible ingress/egress. Runtime orchestration subsystem (optional). Full test suite (~5200 LOC, unit + integration + golden).
