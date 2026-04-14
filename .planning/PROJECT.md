# PROJECT.md

## Name
llm-proxy

## Vision
Local Python 3.14 reverse proxy that accepts both Anthropic Messages API and OpenAI Chat Completions API requests, routes them to any supported upstream provider (Anthropic, OpenAI, OpenRouter, NVIDIA NIM, Gemini), and returns responses in the client's native protocol format. Dual-protocol ingress enables both Claude Code and Codex CLI (or any OpenAI-compatible client) to work through the same proxy.

## Principles
- **Protocol fidelity**: every adapter must produce bit-correct output for its protocol; no implicit transformations or hacks
- **Explicit typing**: all protocol differences are modeled as typed adapters, not conditionals scattered in the pipeline
- **Ports and Adapters**: domain layer is provider-agnostic; new providers plug in without touching core
- **Local-first**: designed for single-user local operation; no auth, no multi-tenancy
- **Bidirectional translation**: internal canonical model is Anthropic-based; ingress and egress encoders handle protocol-specific wire formats independently

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
Multi-provider proxy with Anthropic-compatible ingress/egress. Five upstream adapters: OpenRouter, Anthropic direct, NVIDIA NIM, Gemini (via OpenAI-compatible framework). Runtime orchestration subsystem (optional). Full test suite (~312 tests, unit + integration + golden). Pending: project rename to llm-proxy, OpenAI direct provider registration, OpenAI Chat Completions ingress/egress, production hardening.
