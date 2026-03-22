# claude-proxy

`claude-proxy` e un proxy locale Python 3.14 compatibile con l'API Anthropic Messages, pensato per far usare Claude Code attraverso OpenRouter senza appiattire il protocollo a testo semplice.

Il proxy riceve richieste Anthropic-compatible su:

- `POST /v1/messages`
- `POST /v1/messages/count_tokens`

Risolve il modello target, prepara la request in modo model-aware, inoltra la chiamata al provider e restituisce una risposta Anthropic-compatible in JSON o SSE.

## Obiettivo

Il progetto serve a fare da bridge trasparente tra client Anthropic-style e provider upstream con differenze di protocollo, mantenendo:

- streaming end-to-end
- contenuti strutturati
- semantica tool
- usage e stop reasons
- compatibilita con Claude Code

Quando il provider o il modello non supportano un campo o un comportamento specifico, il proxy applica adattamenti espliciti e tipizzati invece di trasformazioni implicite o hack nel punto sbagliato della pipeline.

## Stato attuale

Funzionalita implementate:

- `GET /health`
- `POST /v1/messages`
- `POST /v1/messages/count_tokens`
- supporto `stream=true`
- supporto `stream=false`
- FastAPI + `httpx.AsyncClient` condiviso per processo
- parsing SSE incrementale
- normalizzazione dello stream in output Anthropic-compatible
- normalizzazione strutturata di contenuti e delta
- request preparation model-aware prima del provider handoff
- policy di compatibilita `transparent`, `compat`, `debug`
- thinking passthrough policy per modello
- stripping per-modello di request fields non supportati upstream

## Architettura

Il codice segue una struttura Ports and Adapters.

Livelli principali:

- `claude_proxy/api`
  espone gli endpoint HTTP e converte request/response tra FastAPI e dominio
- `claude_proxy/application`
  orchestra il request flow, applica request preparation, normalizzazione compat e encoding SSE/JSON
- `claude_proxy/domain`
  contiene modelli canonici, enum, errori e porte astratte
- `claude_proxy/infrastructure`
  contiene config, resolver, client HTTP condiviso e adapter provider

Flow della request:

1. FastAPI valida e converte la request Anthropic in `ChatRequest`
2. il service risolve il modello target
3. il `request_preparer` valida gli extension fields ammessi e adatta la request per il modello scelto
4. il service applica le validazioni dipendenti dal modello
5. il provider adapter costruisce il payload upstream e invia la richiesta
6. la risposta upstream viene normalizzata nel modello canonico
7. il layer applicativo produce JSON Anthropic-compatible o SSE Anthropic-compatible

## Compatibilita protocollo

Il bridge e provider-agnostic e model-agnostic nel core, ma oggi il primo adapter implementato e OpenRouter.

Contenuti supportati nel modello canonico:

- `text`
- `tool_use`
- `tool_result`
- `thinking`

Eventi/semantiche supportati:

- `message_start`
- `content_block_start`
- `content_block_delta`
- `content_block_stop`
- `message_delta`
- `message_stop`
- `ping`
- `error`
- usage
- stop reason
- stop sequence
- forwarding dei request header `anthropic-beta` e `anthropic-version`

Il sequencer SSE garantisce che in output non esistano blocchi annidati: al massimo un content block aperto alla volta.

## Gateway Anthropic per Claude Code

Per usare `claude-proxy` come `ANTHROPIC_BASE_URL` con Claude Code, il proxy espone la surface minima richiesta dal formato Anthropic Messages:

- `POST /v1/messages`
- `POST /v1/messages/count_tokens`

Inoltre inoltra upstream:

- header `anthropic-beta`
- header `anthropic-version`
- query string originale, inclusi casi come `?beta=true`

Questo evita che Claude Code perda funzionalita legate a beta/header negotiation quando parla con il gateway invece che con Anthropic direttamente.

## Limitazione OpenRouter su `count_tokens`

Alla data del 2026-03-22 l'API pubblica OpenRouter espone `POST /messages`, ma non un endpoint nativo `POST /messages/count_tokens`.

Anthropic documenta invece `POST /v1/messages/count_tokens` come endpoint nativo di token counting e mostra esempi con extended thinking, dove il conteggio include il thinking del turno assistant corrente.

Per mantenere compatibilita con Claude Code, il proxy implementa comunque `POST /v1/messages/count_tokens` come shim OpenRouter-specifico:

- invia upstream una richiesta `POST /messages` non-stream
- forza `max_tokens=1`
- restituisce al client solo `usage.input_tokens`
- preserva `tools` e `tool_choice`, che fanno parte dell'input strutturato da contare
- rimuove il top-level `thinking` dal probe: su OpenRouter il probe passa da un vero `/messages`, quindi extended thinking sarebbe soggetto ai normali vincoli di reasoning budget rispetto a `max_tokens`; con `max_tokens=1` questo rende il probe fragile o invalido

Limite noto:

- il conteggio passa comunque da una request reale verso OpenRouter, quindi introduce un round-trip upstream aggiuntivo e puo comportare billing minimo lato completion
- quando la request client include extended thinking, il valore restituito dal proxy e una stima best-effort e puo divergere dal `count_tokens` nativo Anthropic, che conta anche i casi con thinking

## Modalita di compatibilita

`bridge.compatibility_mode` controlla il livello di conservativita dell'output:

- `transparent`
  preserva il piu possibile cio che e rappresentabile in modo sicuro
- `compat`
  sopprime strutture che rischiano di rompere client Anthropic-style
- `debug`
  stesso comportamento funzionale di `transparent`, con logging extra

## Thinking passthrough

Ogni modello puo impostare `thinking_passthrough_mode`:

- `full`
  preserva tutto il thinking normalizzato
- `native_only`
  preserva solo thinking Anthropic-native affidabile
- `off`
  sopprime tutto il thinking in egress

Questo filtro e applicato nel normalizer prima del sequencer e prima dell'encoder SSE.

## Request preparation model-aware

Gli extra top-level della request client che non fanno parte dello schema Anthropic base entrano in `request.extensions`.

`bridge.passthrough_request_fields` definisce quali extension fields il proxy accetta in ingresso.

Dopo la model resolution, il `request_preparer` applica trasformazioni model-aware. Al momento supporta:

- rimozione di campi non supportati con `models.<name>.unsupported_request_fields`

Questo evita il pattern sbagliato:

- accetta qui
- rifiuta li
- prova a stripparlo piu tardi nel provider

Il provider adapter riceve gia una request preparata.

## Requisiti

- Python `>= 3.14`
- una chiave OpenRouter valida in env var

## Installazione

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp config/claude-proxy.example.yaml config/claude-proxy.yaml
export OPENROUTER_API_KEY=...
```

## Avvio

Metodo semplice, consigliato quando vuoi usare host/porta/log level presi dal file YAML:

```bash
python -m claude_proxy
```

Questo entrypoint legge la config e avvia Uvicorn con:

- `host` da `server.host`
- `port` da `server.port`
- `log_level` da `server.log_level`

Alternativa equivalente tramite script installato:

```bash
claude-proxy
```

Se invece vuoi passare opzioni extra di Uvicorn direttamente, usa Uvicorn in modo esplicito:

```bash
uvicorn claude_proxy.main:app --host 127.0.0.1 --port 8082 --reload
```

Esempi utili:

```bash
uvicorn claude_proxy.main:app --host 0.0.0.0 --port 8082 --workers 1
uvicorn claude_proxy.main:app --host 127.0.0.1 --port 8082 --reload --log-level debug
```

Nota pratica:

- `python -m claude_proxy` e comodo per l'avvio standard
- `uvicorn claude_proxy.main:app ...` e preferibile quando vuoi controllare flag aggiuntive come `--reload`, `--workers`, `--proxy-headers`, ecc.

## Configurazione

La configurazione viene letta da:

- path di default `config/claude-proxy.yaml`
- oppure env var `CLAUDE_PROXY_CONFIG`

I valori possono essere sovrascritti con env vars del tipo:

```bash
export CLAUDE_PROXY__SERVER__PORT=8090
export CLAUDE_PROXY__BRIDGE__COMPATIBILITY_MODE=compat
```

Esempio di configurazione:

```yaml
server:
  host: 127.0.0.1
  port: 8082
  log_level: info
  request_timeout_seconds: 120
  debug: false

routing:
  default_model: anthropic/claude-sonnet-4
  fallback_model: anthropic/claude-sonnet-4

bridge:
  compatibility_mode: transparent
  emit_usage: true
  passthrough_request_fields:
    - output_config

providers:
  openrouter:
    enabled: true
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    connect_timeout_seconds: 10
    read_timeout_seconds: 120
    write_timeout_seconds: 20
    pool_timeout_seconds: 10
    max_connections: 100
    max_keepalive_connections: 20
    app_name: claude-proxy
    app_url: null
    debug_echo_upstream_body: false

models:
  anthropic/claude-sonnet-4:
    provider: openrouter
    enabled: true
    supports_stream: true
    supports_nonstream: true
    supports_tools: true
    supports_thinking: true
    thinking_passthrough_mode: full

  stepfun/step-3.5-flash:free:
    provider: openrouter
    enabled: true
    supports_stream: true
    supports_nonstream: true
    supports_tools: true
    supports_thinking: true
    thinking_passthrough_mode: off
    unsupported_request_fields:
      - output_config
```

## Significato dei campi di config

`server`

- parametri di bind e logging del server FastAPI/Uvicorn

`routing`

- modello di default e fallback

`bridge.compatibility_mode`

- modalita di compatibilita dell'output

`bridge.passthrough_request_fields`

- extension fields top-level che il proxy accetta in ingresso

`models.<name>.thinking_passthrough_mode`

- politica di egress del thinking per quel modello

`models.<name>.unsupported_request_fields`

- campi di request da rimuovere prima della chiamata upstream per quel modello

## Endpoint

### `GET /health`

Health check minimale.

Esempio:

```bash
curl http://127.0.0.1:8082/health
```

### `POST /v1/messages`

Endpoint Anthropic-compatible principale.

Supporta:

- `stream=false`
- `stream=true`
- contenuti strutturati
- tool definitions e tool_choice
- metadata
- system
- stop sequences
- thinking config

## Logging e debug

Il progetto usa logging JSON.

Con `server.debug: true` ottieni piu visibilita su:

- validazione request
- start di stream/complete
- anteprima request/response HTTP

Quando un campo viene rimosso dal `request_preparer`, viene emesso un log debug strutturato con:

- modello target
- lista dei campi rimossi

## Test

Per eseguire la suite:

```bash
pytest -q
```

La suite copre:

- parsing request schema
- request preparation model-aware
- normalizzazione thinking
- sequenziamento SSE
- adapter OpenRouter
- endpoint stream e non-stream
- golden test SSE

## Sviluppo

Installazione ambiente di sviluppo:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Avvio in sviluppo con reload:

```bash
uvicorn claude_proxy.main:app --reload --host 127.0.0.1 --port 8082
```

## Note

- il proxy usa un solo `httpx.AsyncClient` condiviso per processo
- il parsing SSE e incrementale e non bufferizza l'intera risposta
- il provider parser resta il piu vicino possibile alla realta upstream
- le trasformazioni model-aware della request stanno nel layer applicativo, non nel provider adapter
