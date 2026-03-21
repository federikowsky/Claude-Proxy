Il progetto assume Python 3.14 come target principale. Python 3.14 è la release stabile corrente, mentre le API Anthropic Messages usano POST /v1/messages e per lo streaming espongono eventi SSE come message_start, content_block_start, content_block_delta, content_block_stop, message_delta e message_stop. La documentazione Anthropic specifica anche che possono comparire nuovi tipi di evento, quindi il parser deve gestire in modo robusto gli eventi sconosciuti. OpenRouter espone inoltre un input compatibile con l’Anthropic Messages API.  ￼

⸻

docs/specs.md

1. Overview

1.1 Nome progetto

anthropic-bridge

1.2 Obiettivo

Costruire un proxy locale Anthropic-compatible che:
	•	esponga POST /v1/messages
	•	riceva richieste in formato Anthropic Messages API
	•	inoltri la richiesta a provider esterni, inizialmente OpenRouter
	•	supporti streaming SSE
	•	normalizzi lo stream del provider in un flusso sicuro e compatibile con client Anthropic-like
	•	rimuova o trasformi blocchi problematici come:
	•	thinking
	•	redacted_thinking
	•	reasoning
	•	signature_delta
	•	altri chunk vendor-specific non supportati dal client

1.3 Motivazione

Alcuni client Anthropic-like o integrazioni editor/UI possono ricevere correttamente lo stream iniziale ma rompersi sul rendering finale quando arrivano blocchi reasoning/thinking non compatibili. Anthropic documenta eventi di streaming distinti per testo e thinking, e OpenRouter dichiara il pass-through delle feature Anthropic-like, incluso thinking. Il proxy deve quindi fare da normalization boundary tra provider e client.  ￼

⸻

2. Obiettivi e non-obiettivi

2.1 Obiettivi MVP

Implementare:
	•	POST /v1/messages
	•	GET /health
	•	solo richieste testuali
	•	stream=true obbligatorio nel MVP
	•	routing su un insieme ristretto di modelli whitelisted
	•	provider iniziale: OpenRouter
	•	output SSE compatibile con client Anthropic-like
	•	filtro/normalizzazione dei blocchi thinking/reasoning
	•	configurazione dichiarativa
	•	logging strutturato
	•	test unitari e integration test del parser/normalizer

2.2 Non-obiettivi MVP

Non implementare inizialmente:
	•	tool calling
	•	image input / multimodal
	•	prompt caching esplicito
	•	batch
	•	embeddings
	•	audio
	•	auth multi-tenant
	•	persistence DB
	•	bilanciamento avanzato multi-provider
	•	retries sofisticati per capability diverse
	•	dashboard UI

⸻

3. Requisiti tecnici

3.1 Runtime
	•	Python 3.14
	•	compatibilità desiderata con 3.15, ma non richiesta per MVP

3.2 Dipendenze minime

Ammesse solo se motivate:
	•	fastapi
	•	uvicorn
	•	httpx
	•	pydantic
	•	pydantic-settings
	•	orjson facoltativo ma consigliato
	•	pytest
	•	pytest-asyncio
	•	respx o equivalente per mocking HTTP

3.3 Principi obbligatori
	•	SOLID
	•	DRY
	•	KISS
	•	SRP
	•	design model-agnostic
	•	provider-agnostic
	•	streaming end-to-end
	•	evitare allocazioni e buffering inutili
	•	dominio interno indipendente dal provider

⸻

4. Architettura

4.1 Architettura a strati

Usare una struttura Ports and Adapters.

Strati:
	1.	API layer
	•	parsing richieste HTTP
	•	validazione schema di ingresso
	•	conversione risposta SSE verso il client
	2.	Application layer
	•	orchestration del caso d’uso
	•	model resolution
	•	invocation provider
	•	application delle policy stream
	3.	Domain layer
	•	modelli interni neutrali
	•	porte/interfacce
	•	eventi dominio
	•	errori di dominio
	•	policy astratte
	4.	Infrastructure layer
	•	adapter provider
	•	config loader
	•	parser SSE provider
	•	normalizer provider-specific
	•	HTTP client

4.2 Principio chiave

Il dominio non deve conoscere OpenRouter né specifici nomi di chunk provider.
Il dominio lavora solo con:
	•	ChatRequest
	•	ChatMessage
	•	DomainEvent
	•	StreamPolicy
	•	ModelProvider
	•	ModelResolver

⸻

5. Struttura cartelle

app/
  api/
    routes/
      messages.py
      health.py
    schemas/
      anthropic_request.py
      anthropic_response.py
      errors.py
    dependencies.py

  application/
    services/
      message_service.py
      routing_service.py
    encoders/
      anthropic_sse_encoder.py
    policies/
      stream_policy.py

  domain/
    enums/
      roles.py
      event_types.py
      provider_capabilities.py
    models/
      chat_request.py
      chat_message.py
      content.py
      domain_event.py
      usage.py
      model_info.py
    ports/
      model_provider.py
      model_resolver.py
      stream_normalizer.py
      sse_encoder.py
    errors/
      base.py
      protocol.py
      provider.py
      routing.py

  infrastructure/
    config/
      settings.py
    providers/
      openrouter/
        provider.py
        translator.py
        sse_parser.py
        normalizer.py
        error_mapper.py
    resolvers/
      static_model_resolver.py
    http/
      client.py
    logging/
      setup.py

  main.py

tests/
  unit/
  integration/
  golden/

docs/
  specs.md
  architecture.md
  contracts.md
  testing.md
  providers/
    openrouter.md


⸻

6. API contract esterno

6.1 Endpoint

POST /v1/messages
Compatibile con Anthropic Messages API nel perimetro MVP.

GET /health
Risponde 200 con payload minimo:

{"status":"ok"}

6.2 Request supportata nel MVP

Supportare solo questo subset:

{
  "model": "string",
  "messages": [
    {
      "role": "user",
      "content": "string | array"
    }
  ],
  "system": "string | array | null",
  "max_tokens": 1024,
  "temperature": 0.0,
  "stream": true,
  "metadata": {}
}

6.3 Vincoli request
	•	stream deve essere true
	•	messages non vuoto
	•	supportare solo contenuto testuale:
	•	stringa semplice
	•	oppure array di blocchi con type == "text"
	•	rifiutare in MVP:
	•	image blocks
	•	tool definitions
	•	thinking config in ingresso
	•	attachments non testuali
	•	model deve appartenere alla whitelist configurata

6.4 Response SSE verso il client

Il proxy deve emettere solo eventi Anthropic-safe.

Eventi ammessi nel MVP:
	•	message_start
	•	content_block_start
	•	content_block_delta
	•	content_block_stop
	•	message_delta
	•	message_stop
	•	opzionalmente error

Anthropic documenta questi eventi come base del flusso streaming dei messaggi; per il testo incrementale il delta rilevante è text_delta. La documentazione segnala inoltre che possono comparire nuovi event types, quindi il parser interno deve essere tollerante.  ￼

6.5 Eventi vietati in uscita

Il proxy non deve mai emettere verso il client:
	•	thinking
	•	redacted_thinking
	•	thinking_delta
	•	signature_delta
	•	reasoning
	•	vendor-specific unsupported content blocks

Anthropic documenta che lo streaming extended thinking può emettere thinking_delta; il proxy deve evitarlo in modalità strict per mantenere la compatibilità del client.  ￼

⸻

7. Dominio interno

7.1 ChatRequest

Rappresentazione interna indipendente dal provider.

Campi:
	•	model: str
	•	messages: tuple[ChatMessage, ...]
	•	system: str | None
	•	max_tokens: int
	•	temperature: float | None
	•	stream: bool
	•	metadata: Mapping[str, str] | None

7.2 ChatMessage

Campi:
	•	role: Role
	•	text: str

Ruoli ammessi MVP:
	•	system
	•	user
	•	assistant

7.3 DomainEvent

Gerarchia chiusa e minimale.

Tipi:
	•	MessageStartEvent
	•	TextStartEvent
	•	TextDeltaEvent
	•	TextStopEvent
	•	UsageEvent
	•	MessageStopEvent
	•	ProviderWarningEvent
	•	ErrorEvent

7.4 ProviderEvent

Eventi grezzi normalizzati a metà strada tra parser e dominio.

Tipi possibili:
	•	RawTextDelta
	•	RawReasoningDelta
	•	RawUsage
	•	RawStop
	•	RawUnknown
	•	RawError

Il RawUnknown serve per garantire forward-compatibility del parser senza crash.

⸻

8. Ports e contratti

8.1 ModelProvider

Responsabilità: eseguire la richiesta verso un provider.

Contratto concettuale:

class ModelProvider(Protocol):
    async def stream(self, request: ChatRequest) -> AsyncIterator[ProviderEvent]: ...

8.2 StreamNormalizer

Responsabilità: convertire ProviderEvent in DomainEvent applicando una policy.

class StreamNormalizer(Protocol):
    async def normalize(
        self,
        events: AsyncIterator[ProviderEvent],
        policy: StreamPolicy,
    ) -> AsyncIterator[DomainEvent]: ...

8.3 ModelResolver

Responsabilità: risolvere il modello richiesto e il provider da usare.

class ModelResolver(Protocol):
    def resolve(self, requested_model: str | None) -> ModelInfo: ...

8.4 SseEncoder

Responsabilità: convertire DomainEvent in bytes SSE Anthropic-compatible.

class SseEncoder(Protocol):
    async def encode(self, events: AsyncIterator[DomainEvent]) -> AsyncIterator[bytes]: ...


⸻

9. Stream policy

9.1 Modalità supportate

Definire almeno due policy:

strict
	•	scarta tutti gli eventi di reasoning/thinking
	•	emette solo testo finale

promote_if_empty
	•	scarta il reasoning durante lo stream normale
	•	se a fine stream non è arrivato alcun testo finale
	•	ma è arrivato solo reasoning testuale
	•	promuove il reasoning accumulato a text

9.2 Policy default

Default: strict

9.3 Regola fondamentale

Mai esporre al client eventi che non siano dichiaratamente supportati dalla semantica Anthropic-safe del proxy.

⸻

10. Model abstraction

10.1 Obiettivo

Il sistema deve essere modello-agnostico.
Aggiungere un modello nuovo deve richiedere solo:
	•	modifica config
	•	eventuale dichiarazione capability
	•	nessuna modifica al dominio
	•	nessuna modifica all’encoder SSE

10.2 ModelInfo

Campi:
	•	name: str
	•	provider: str
	•	supports_streaming: bool
	•	supports_text: bool
	•	supports_tools: bool
	•	supports_multimodal: bool
	•	reasoning_mode: Literal["drop", "promote_if_empty"]
	•	enabled: bool

10.3 Regola

La logica di compatibilità del modello va in config, non hardcoded nel core.

⸻

11. Provider OpenRouter

11.1 Ruolo

Adapter iniziale per provider OpenRouter.

OpenRouter documenta un endpoint compatibile con Anthropic Messages API e supporta anche integrazioni Claude Code. Inoltre documenta header opzionali come referer/title e opzioni di debug che permettono di ispezionare il body upstream trasformato.  ￼

11.2 Traduzione request

Il translator OpenRouter deve:
	•	ricevere ChatRequest
	•	produrre payload provider-specific coerente
	•	includere model
	•	mappare messages
	•	mappare system
	•	mappare max_tokens
	•	mappare temperature
	•	forzare streaming

11.3 Comportamento thinking

Se la request contiene configurazioni di thinking in ingresso, il MVP deve:
	•	ignorarle
	•	oppure rifiutarle con errore 400 chiaro

11.4 Parser SSE provider

Implementare parser incrementale line-based:
	•	legge data: line per line
	•	accumula fino a evento completo
	•	parse JSON con orjson se disponibile
	•	non bufferizza l’intero stream
	•	tollera:
	•	keepalive
	•	linee vuote
	•	eventi sconosciuti
	•	chunk frammentati

11.5 Normalizer provider

Responsabilità:
	•	classificare ogni evento provider
	•	estrarre testo finale
	•	classificare reasoning separatamente
	•	scartare unknown non utili
	•	emettere ProviderEvent puliti

⸻

12. Encoder SSE Anthropic

12.1 Output target

Produrre stream conforme a questa sequenza logica:
	1.	message_start
	2.	content_block_start
	3.	zero o più content_block_delta
	4.	content_block_stop
	5.	uno o più message_delta
	6.	message_stop

Questa sequenza è quella descritta dalla documentazione Anthropic per Messages streaming.  ￼

12.2 Formato del blocco testo

Per il testo, i delta devono essere di tipo text_delta, come descritto dalla documentazione Anthropic per il testo incrementale.  ￼

12.3 Regole encoder
	•	aprire un solo text block per messaggio nel MVP
	•	inviare delta testuali incrementali
	•	chiudere il block sempre, anche se vuoto
	•	inviare usage in message_delta finale se disponibile
	•	terminare sempre con message_stop
	•	in caso di eccezione controllata, emettere error e chiudere

⸻

13. Configurazione

13.1 Formato

Usare yaml o toml.
Preferenza: yaml per leggibilità operativa.

13.2 Esempio

server:
  host: 127.0.0.1
  port: 8082
  log_level: info
  request_timeout_seconds: 120

routing:
  default_model: nvidia/nemotron-3-super-120b-a12b:free
  fallback_model: google/gemini-2.5-flash:free

stream:
  policy: strict
  emit_usage: true
  max_reasoning_buffer_chars: 32768

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
    app_name: anthropic-bridge
    app_url: null
    debug_echo_upstream_body: false

models:
  nvidia/nemotron-3-super-120b-a12b:free:
    provider: openrouter
    enabled: true
    supports_streaming: true
    supports_text: true
    supports_tools: false
    supports_multimodal: false
    reasoning_mode: drop

  google/gemini-2.5-flash:free:
    provider: openrouter
    enabled: true
    supports_streaming: true
    supports_text: true
    supports_tools: false
    supports_multimodal: false
    reasoning_mode: drop

13.3 Validazione config

La config deve essere validata all’avvio:
	•	provider esistente
	•	modello referenzia provider valido
	•	modello default esiste
	•	env var API key presente
	•	timeout > 0
	•	policy valida

⸻

14. Error model

14.1 Errori di validazione request

HTTP 400:
	•	stream != true
	•	modello non supportato
	•	messaggi vuoti
	•	contenuto non testuale
	•	campi non supportati nel MVP

14.2 Errori routing

HTTP 422 o 400:
	•	modello sconosciuto
	•	modello disabilitato
	•	provider non configurato

14.3 Errori provider

HTTP 502 o 504:
	•	timeout upstream
	•	body provider invalido
	•	stream troncato
	•	auth upstream fallita
	•	rate limit provider

14.4 Errori interni

HTTP 500:
	•	bug di serializzazione
	•	violazione invarianti dominio
	•	eccezioni non attese

14.5 Mappatura errore

Definire classi distinte:
	•	RequestValidationError
	•	RoutingError
	•	ProviderProtocolError
	•	ProviderAuthError
	•	UpstreamTimeoutError
	•	InternalBridgeError

⸻

15. Performance requirements

15.1 Vincoli
	•	streaming end-to-end, senza accumulare l’intera risposta
	•	un solo passaggio per chunk
	•	parsing incrementale
	•	connection pooling condiviso
	•	nessuna conversione JSON ripetuta sullo stesso payload
	•	evitare copie superflue di stringhe
	•	usare generator/async generator per pipeline stream

15.2 Strutture dati
	•	dict per registri provider/modelli
	•	set per whitelist lookup
	•	tuple per strutture immutabili piccole
	•	deque solo se serve buffering FIFO
	•	dataclass(slots=True) nel dominio per ridurre overhead

15.3 HTTP client

Un solo httpx.AsyncClient condiviso per processo con pool configurabile.

⸻

16. Logging e osservabilità

16.1 Logging

Logging strutturato JSON o key-value.

Campi minimi:
	•	request_id
	•	provider
	•	model
	•	path
	•	latency_ms
	•	status_code
	•	error_type
	•	stream_policy

16.2 Redaction

Mai loggare:
	•	API keys
	•	prompt completi in chiaro di default
	•	intere risposte provider di default

16.3 Debug mode

Quando debug=true:
	•	consentito loggare metadata aggiuntivi
	•	opzionale dump eventi provider classificati
	•	mai loggare segreti

OpenRouter documenta un’opzione di debug per ispezionare il body upstream trasformato; il bridge può supportare una modalità analoga, ma non deve abilitarla di default.  ￼

⸻

17. Sicurezza

17.1 Segreti

Le API key vanno solo via env var.

17.2 Bind locale

Default host: 127.0.0.1

17.3 Hardening
	•	limitare dimensione massima request body
	•	timeout stretti ma configurabili
	•	validazione schema rigorosa
	•	nessun eval
	•	nessun caricamento dinamico non controllato

⸻

18. Testing strategy

18.1 Unit tests

Copertura per:
	•	request validation
	•	model resolver
	•	translator OpenRouter
	•	parser SSE
	•	normalizer reasoning/text
	•	encoder Anthropic SSE
	•	config validation
	•	error mapper

18.2 Golden tests

Essenziali.

Dato un input stream provider fixture, verificare output SSE byte-per-byte.

Casi minimi:
	1.	solo testo
	2.	testo + reasoning
	3.	solo reasoning
	4.	stream con unknown events
	5.	errore midway
	6.	stream troncato
	7.	empty text
	8.	usage finale presente

18.3 Integration tests

Con mocking HTTP:
	•	upstream 200 streaming valido
	•	upstream 401
	•	upstream 429
	•	upstream timeout
	•	upstream JSON invalido
	•	upstream chunk frammentati

18.4 Acceptance tests

Testare con client reale Anthropic-like locale:
	•	richiesta semplice
	•	stream visibile
	•	nessun redacted_thinking
	•	nessun testo mostrato nel blocco thinking

⸻

19. Acceptance criteria MVP

Il MVP è accettato se:
	1.	POST /v1/messages con stream=true produce SSE consumabile da client Anthropic-like.
	2.	Un upstream che invia reasoning/thinking non causa crash UI lato client.
	3.	Il client riceve solo blocchi text_delta in uscita.
	4.	Modelli non in whitelist vengono rifiutati.
	5.	Il sistema supporta almeno 2 modelli configurati senza modifiche codice.
	6.	Il parser tollera eventi sconosciuti senza terminare lo stream.
	7.	I test golden passano.
	8.	Il bridge usa un solo AsyncClient condiviso.
	9.	Nessun buffering dell’intera risposta in modalità normale.
	10.	GET /health risponde sempre senza contattare il provider.

⸻

20. Sequenza elaborativa

20.1 Flusso request
	1.	Ricezione HTTP request
	2.	Validazione schema Anthropic subset
	3.	Conversione a ChatRequest
	4.	Risoluzione modello via ModelResolver
	5.	Scelta ModelProvider
	6.	Avvio stream provider
	7.	Parsing SSE provider
	8.	Normalizzazione ProviderEvent -> DomainEvent
	9.	Encoding DomainEvent -> Anthropic SSE
	10.	Invio streaming al client

20.2 Invarianti
	•	il dominio non deve dipendere dal provider
	•	il provider non deve emettere SSE client direttamente
	•	l’encoder non deve conoscere OpenRouter
	•	il normalizer applica sempre una policy
	•	l’output finale è sempre Anthropic-safe

⸻

21. Piano implementativo suggerito

Fase 1
	•	config
	•	dominio
	•	endpoint health
	•	validator request
	•	static resolver

Fase 2
	•	OpenRouter translator
	•	HTTP client condiviso
	•	SSE parser incrementale

Fase 3
	•	normalizer strict
	•	encoder Anthropic SSE
	•	streaming end-to-end

Fase 4
	•	test unitari
	•	golden tests
	•	integration tests

Fase 5
	•	policy promote_if_empty
	•	logging strutturato
	•	hardening error handling


22. Nota finale su compatibilità protocollo

Anthropic documenta che nel protocollo streaming possono essere aggiunti nuovi event types e che extended thinking introduce eventi dedicati come thinking_delta. Questo rende necessario progettare parser e normalizer come componenti separati e tolleranti, anziché fare mapping rigido one-shot. OpenRouter dichiara compatibilità Anthropic e pass-through delle feature correlate, quindi il bridge deve essere la barriera che converte il flusso in una forma più stretta e sicura per il client.  ￼
