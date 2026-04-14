# Phase 3 Context: Project Rename

## Phase Description
Rename the entire project from claude-proxy to llm-proxy. This reflects the project's evolution from a Claude Code-specific proxy to a multi-protocol, multi-provider LLM reverse proxy.

## Decisions

### D-01: Project name → llm-proxy [LOCKED]
Package: `llm_proxy`, CLI entry point: `llm-proxy`, config files: `llm-proxy*.yaml`.

### D-02: Env var prefix → LLM_PROXY__ [LOCKED]
Matches the new project name. `LLM_PROXY_CONFIG` for config path override.

### D-03: Rename scope is comprehensive [LOCKED]
All source, tests, config, README, pyproject.toml, logging identifiers. No partial rename.

## Deferred Ideas
None.

## Claude's Discretion
- Logger names: use `llm_proxy` module paths (natural from package rename)
- Planning artifacts: historical phase plans keep their original references (don't rewrite history)
