# Phase 1: Direct Anthropic Provider Adapter - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-14
**Phase:** 01-direct-anthropic-provider-adapter
**Areas discussed:** SSE Parser & Normalizer Architecture

---

## SSE Parser & Normalizer Architecture

### Q1: Collocazione del codice condiviso

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Modulo condiviso sse.py | Parser + normalizer estratti in infrastructure/providers/sse.py | ✓ |
| (b) Solo parser condiviso | Parser in modulo condiviso, normalizer separati per provider | |
| (c) Import diretto da openrouter | Nessun refactor, Anthropic importa da openrouter.py | |

**User's choice:** (a) Modulo condiviso sse.py
**Notes:** IncrementalSseParser e SseMessage dataclass vanno nel modulo condiviso. Entrambi i provider importano da lì.

### Q2: Strategia di specializzazione del normalizer

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Unico normalizer configurabile | Un solo normalizer con parametri per le differenze | |
| (b) Classe base + override | Ereditarietà per i punti di variazione | |
| (c) Fork separati | Normalizer indipendenti, inizialmente identici, divergono se serve | ✓ |

**User's choice:** (c) Fork separati
**Notes:** Normalizer separati per massima libertà di divergenza. Nessun accoppiamento tra provider a livello di normalizzazione.

### Q3: Gestione del sentinel [DONE]

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Nel parser SSE | Il parser astrae il sentinel — i normalizer non lo vedono | |
| (b) Nel normalizer | Ogni normalizer gestisce il proprio sentinel pattern | ✓ |

**User's choice:** (b) Nel normalizer
**Notes:** Il sentinel è semantica provider-specific, non protocollo SSE generico.

---

## Agent's Discretion

- Provider Settings structure (fields specifici Anthropic)
- Count Tokens strategy (endpoint nativo vs probe)
- Auth & Headers Anthropic (x-api-key, anthropic-version, anthropic-beta)

## Deferred Ideas

None.
