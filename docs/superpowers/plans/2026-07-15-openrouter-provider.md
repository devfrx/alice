# OpenRouter Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OpenRouter come terzo provider LLM di pari rango (catalogo con prezzi, saldo crediti, preferiti, costo per conversazione), via API REST diretta — zero dipendenze nuove.

**Architecture:** `provider: "openrouter"` instrada il percorso OAI-compat già esistente di `LLMClient` verso `https://openrouter.ai/api/v1` con header Bearer; un nuovo `OpenRouterService` (httpx) espone catalogo `/v1/models` e crediti `/v1/key` via route `/api/openrouter/*`; il costo per generazione (usage accounting) fluisce client → `TurnProgress.cost` → `TurnResult.cost` → frame `turn.finished` → colonna JSON `messages.usage`. Il frontend aggiunge una sezione provider in SettingsView (switcher, API key, crediti, catalogo con ricerca/filtri/pin) e mostra il costo accanto alla ContextBar.

**Tech Stack:** FastAPI/httpx/pydantic-settings (backend), Vue 3 + Pinia + Vitest (frontend), contratti generati via `scripts/gen-contracts.ps1`.

**Spec di riferimento:** `docs/superpowers/specs/2026-07-15-openrouter-provider-design.md`

**Deviazioni deliberate dalla spec (motivate):**
1. I campi OpenRouter vivono su `LLMConfig` (`openrouter_api_key`, `openrouter_base_url`, `openrouter_model`, `openrouter_favorites`, env `ALICE_LLM__OPENROUTER_*`) invece che in una sezione `OpenRouterConfig` separata: `LLMService`/`LLMClient`/`ModelResolver` ricevono già solo `LLMConfig` — una sezione separata avrebbe richiesto di infilare un secondo oggetto config in 3 costruttori senza beneficio.
2. `openrouter_model` è separato da `model`: lo switch di provider preserva sia il modello locale sia quello cloud (UX paritaria), e il resolver locale resta intatto.
3. Persistenza di provider/key/favorites via `PreferencesService` (il canale di `PUT /api/config`, come `disabled_tools`) invece del layer YAML utente: è il pattern reale della settings UI.
4. Il rebuild del servizio a runtime (cambio provider/key) segue il pattern restart di STT/TTS in `api/routes/config.py`: gli header httpx e i flag derivati (`_is_ollama`, `_is_openrouter`) sono fissati alla costruzione, la mutazione in-place non basta.

**Fatti API OpenRouter verificati (doc ufficiale, 2026-07-15):**
- Chat: `POST {base}/v1/chat/completions`, OpenAI-compatible, SSE, tool calling. Auth: `Authorization: Bearer <key>`. Attribution opzionale: `HTTP-Referer`, `X-Title`.
- Usage accounting: `"usage": {"include": true}` nel payload → il chunk SSE finale contiene `usage.cost` (crediti USD) oltre a `prompt_tokens`/`completion_tokens`.
- Catalogo: `GET {base}/v1/models` (senza auth) → `data[]` con `id`, `name`, `description`, `context_length`, `pricing.{prompt,completion}` (stringhe, USD/token), `architecture.input_modalities` (`["text","image",...]`), `supported_parameters` (`["tools","reasoning",...]`), `top_provider.context_length`.
- Crediti: `GET {base}/v1/key` (con auth) → `data.{limit, limit_remaining, usage, is_free_tier, ...}`. 401 se key non valida.
- Base URL usata nel codice: `https://openrouter.ai/api` (il client appende `/v1/...`, stessa convenzione di LM Studio).

---

## Task 1: Config backend — campi OpenRouter su LLMConfig

**Files:**
- Modify: `backend/core/config.py` (classe `LLMConfig`, dopo il blocco Ollama ~riga 183)
- Modify: `config/default.yaml` (blocco `llm:`, dopo `num_ctx`/`keep_alive` ~riga 36)
- Modify: `docs/flag-registry.md` (nessun flag booleano nuovo — nota sotto)
- Test: `backend/tests/test_config.py` (append)

- [ ] **Step 1: Scrivi i test che falliscono**

Append a `backend/tests/test_config.py`:

```python
# ---------------------------------------------------------------------------
# OpenRouter provider config
# ---------------------------------------------------------------------------


def test_effective_base_url_openrouter() -> None:
    cfg = LLMConfig(provider="openrouter", base_url="http://localhost:1234")
    assert cfg.effective_base_url == "https://openrouter.ai/api"


def test_effective_base_url_local_providers() -> None:
    cfg = LLMConfig(provider="lmstudio", base_url="http://localhost:1234")
    assert cfg.effective_base_url == "http://localhost:1234"
    cfg = LLMConfig(provider="ollama", base_url="http://localhost:11434")
    assert cfg.effective_base_url == "http://localhost:11434"


def test_openrouter_defaults() -> None:
    cfg = LLMConfig()
    assert cfg.openrouter_api_key == ""
    assert cfg.openrouter_model == ""
    assert cfg.openrouter_favorites == []
```

Se `test_config.py` non importa già `LLMConfig`, aggiungi l'import in testa: `from backend.core.config import LLMConfig`.

- [ ] **Step 2: Verifica che falliscano**

Run (da `backend/`): `pytest tests/test_config.py -v -k openrouter or effective_base`
Expected: FAIL con `AttributeError: 'LLMConfig' object has no attribute 'effective_base_url'` (o simile).

- [ ] **Step 3: Implementa i campi in LLMConfig**

In `backend/core/config.py`, dentro `LLMConfig`, dopo il blocco Ollama (`keep_alive: str = "5m"`, ~riga 183), inserisci:

```python
    # -- OpenRouter-specific options (used when provider == "openrouter") --
    openrouter_api_key: str = ""
    """OpenRouter API key (Bearer). Empty = not configured."""
    openrouter_base_url: str = "https://openrouter.ai/api"
    """OpenRouter API origin. ``/v1/...`` paths are appended by the client."""
    openrouter_model: str = ""
    """Active OpenRouter model id (e.g. ``anthropic/claude-sonnet-5``).

    Kept separate from ``model`` so switching provider back and forth
    preserves both the local and the cloud selection."""
    openrouter_favorites: list[str] = Field(default_factory=list)
    """Pinned OpenRouter model ids, shown first in the model selector."""

    @property
    def effective_base_url(self) -> str:
        """Base URL for the active provider (OpenRouter or local server)."""
        if self.provider == "openrouter":
            return self.openrouter_base_url.rstrip("/")
        return self.base_url
```

Aggiorna la docstring del campo `provider` (riga 118) da `provider: str = "lmstudio"` aggiungendo sotto: `"""One of "lmstudio", "ollama", "openrouter"."""`.

- [ ] **Step 4: default.yaml**

In `config/default.yaml`, nel blocco `llm:` dopo le opzioni Ollama (`keep_alive`), aggiungi:

```yaml
  # OpenRouter (provider: "openrouter") — cloud provider di pari rango
  openrouter_base_url: "https://openrouter.ai/api"
  openrouter_api_key: ""       # impostata dalla UI; env: ALICE_LLM__OPENROUTER_API_KEY
  openrouter_model: ""         # es. "anthropic/claude-sonnet-5"
  openrouter_favorites: []
```

- [ ] **Step 5: flag-registry**

`docs/flag-registry.md` censisce solo flag booleani `enabled`: nessun flag nuovo nasce qui (il gate è `llm.provider`, non un booleano). Aggiungi però una riga nella sezione appropriata solo SE il file ha una sezione "non-enabled notevoli"; altrimenti nessuna modifica (verifica leggendo il file — non forzare).

- [ ] **Step 6: Verifica che passino**

Run: `pytest tests/test_config.py -v` → PASS. Poi `ruff check backend/core/config.py` e `mypy backend/core/config.py` (da repo root con venv attivo) → clean.

- [ ] **Step 7: Commit**

```bash
git add backend/core/config.py config/default.yaml backend/tests/test_config.py
git commit -m "feat(config): campi OpenRouter su LLMConfig con effective_base_url"
```

---

## Task 2: Routing provider nel layer LLM (headers, client, resolver, context window)

**Files:**
- Modify: `backend/services/llm_service.py` (costruttore ~riga 53; `get_cached_context_window` ~riga 217)
- Modify: `backend/services/llm/client.py` (costruttore ~riga 60; `chat` ~riga 120; `_chat_openai_compat` ~righe 516, 536; `complete_nonstreaming` ~riga 830)
- Modify: `backend/services/llm/model_resolution.py` (costruttore ~riga 49; `resolve` ~riga 179; `supports_vision` ~riga 154)
- Test: `backend/tests/test_llm_openrouter.py` (nuovo)

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `backend/tests/test_llm_openrouter.py`:

```python
"""AL\\CE — Tests for the OpenRouter provider path in the LLM layer."""

from __future__ import annotations

import json

import pytest

from backend.core.config import PROJECT_ROOT, LLMConfig
from backend.services.llm_service import LLMService

pytestmark = pytest.mark.asyncio


def _openrouter_config(**overrides) -> LLMConfig:
    base = dict(
        provider="openrouter",
        openrouter_api_key="sk-or-test-123",
        openrouter_model="anthropic/claude-sonnet-5",
        system_prompt_file=str(PROJECT_ROOT / "config" / "system_prompt.md"),
    )
    base.update(overrides)
    return LLMConfig(**base)


def _service(**overrides) -> LLMService:
    return LLMService(_openrouter_config(**overrides))


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


async def test_openrouter_sets_auth_headers() -> None:
    svc = _service()
    assert svc._client.headers["authorization"] == "Bearer sk-or-test-123"
    assert "x-title" in svc._client.headers
    await svc.close()


async def test_local_provider_has_no_auth_header() -> None:
    svc = LLMService(LLMConfig(
        provider="lmstudio",
        system_prompt_file=str(PROJECT_ROOT / "config" / "system_prompt.md"),
    ))
    assert "authorization" not in svc._client.headers
    await svc.close()


# ---------------------------------------------------------------------------
# Model resolution — no HTTP probe for OpenRouter
# ---------------------------------------------------------------------------


async def test_resolve_returns_openrouter_model_without_probe() -> None:
    svc = _service()

    async def _fail_get(*_a, **_k):
        raise AssertionError("resolve() must not probe /models for openrouter")

    svc._client.get = _fail_get  # type: ignore[method-assign]
    assert await svc._resolve_model() == "anthropic/claude-sonnet-5"
    await svc.close()


async def test_resolve_falls_back_to_openrouter_auto() -> None:
    svc = _service(openrouter_model="")
    assert await svc._resolve_model() == "openrouter/auto"
    await svc.close()


# ---------------------------------------------------------------------------
# Streaming — OAI-compat path, payload, cost in usage event
# ---------------------------------------------------------------------------


class _FakeResponse:
    status_code = 200

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def raise_for_status(self) -> None:
        pass

    async def aread(self) -> bytes:
        return b""

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCM:
    def __init__(self, resp: _FakeResponse) -> None:
        self._resp = resp

    async def __aenter__(self) -> _FakeResponse:
        return self._resp

    async def __aexit__(self, *exc) -> bool:
        return False


def _sse(lines: list[str], captured: dict):
    def _stream(method: str, url: str, json: dict | None = None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        return _FakeStreamCM(_FakeResponse(lines))

    return _stream


_STREAM_LINES = [
    'data: {"choices":[{"delta":{"content":"ciao"},"finish_reason":null}]}',
    'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
    '"usage":{"prompt_tokens":10,"completion_tokens":5,"cost":0.00042}}',
    "data: [DONE]",
]


async def test_openrouter_chat_uses_oai_path_with_usage_accounting() -> None:
    svc = _service()
    captured: dict = {}
    svc._client.stream = _sse(_STREAM_LINES, captured)  # type: ignore[method-assign]

    events = [
        e async for e in svc.chat(
            [{"role": "user", "content": "ciao"}],
            user_content="ciao",  # native path would be taken for lmstudio
        )
    ]

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["payload"]["usage"] == {"include": True}
    assert captured["payload"]["model"] == "anthropic/claude-sonnet-5"
    tokens = [e for e in events if e["type"] == "token"]
    assert tokens and tokens[0]["content"] == "ciao"
    usage = [e for e in events if e["type"] == "usage"]
    assert usage == [{
        "type": "usage", "input_tokens": 10, "output_tokens": 5,
        "cost": 0.00042,
    }]
    await svc.close()


# ---------------------------------------------------------------------------
# Context window from capability registry
# ---------------------------------------------------------------------------


async def test_context_window_from_registry_for_openrouter() -> None:
    from backend.services.model_capability_registry import (
        ModelCapabilityRegistry, ModelProfile,
    )

    registry = ModelCapabilityRegistry()
    registry._profiles["anthropic/claude-sonnet-5"] = ModelProfile(
        model_id="anthropic/claude-sonnet-5",
        context_length=200000,
        source="openrouter_api",
    )
    svc = LLMService(_openrouter_config(), model_registry=registry)
    assert svc.get_cached_context_window() == 200000
    await svc.close()
```

NOTA: il test `usage` con `cost` appartiene concettualmente al Task 3, ma il fake SSE è unico — il test viene scritto qui e passa solo al termine del Task 3 (vedi Step 6).

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_llm_openrouter.py -v`
Expected: FAIL (header assenti, resolve fa probe HTTP, URL sbagliato).

- [ ] **Step 3: Implementa — llm_service.py**

Nel costruttore di `LLMService` (riga 53), sostituisci la creazione del client:

```python
        headers: dict[str, str] = {}
        if config.provider == "openrouter" and config.openrouter_api_key:
            headers = {
                "Authorization": f"Bearer {config.openrouter_api_key}",
                # Attribution opzionale OpenRouter (rankings).
                "HTTP-Referer": "https://github.com/devfrx/alice",
                "X-Title": "ALICE",
            }
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=config.connect_timeout,
                read=config.timeout,
                write=10.0,
                pool=10.0,
            ),
            headers=headers,
        )
```

In `get_cached_context_window` (riga 217), PRIMA del check sulla cache aggiungi:

```python
        # OpenRouter: il context window viene dal catalogo (capability
        # registry), non da un probe LM Studio.
        if self._config.provider == "openrouter":
            if self._model_registry is not None:
                profile = self._model_registry.get_profile(
                    self._config.openrouter_model or "openrouter/auto",
                )
                if profile.context_length > 0:
                    return profile.context_length
            return self._default_ctx_window
```

- [ ] **Step 4: Implementa — client.py**

Costruttore (dopo riga 60 `self._is_ollama = ...`):

```python
        self._is_openrouter = config.provider == "openrouter"
```

`chat()` (riga 120), aggiorna il gate del percorso nativo:

```python
        use_native = (
            not self._is_ollama
            and not self._is_openrouter
            and tools is None
            and user_content is not None
        )
```

`_chat_openai_compat` (riga 516): `url = f"{self._config.effective_base_url}/v1/chat/completions"`.

Nel payload (dopo il blocco `stream_options`, riga 544) aggiungi:

```python
        if self._is_openrouter:
            # OpenRouter usage accounting: il chunk SSE finale porta i
            # token reali e il costo in crediti della generazione.
            payload["usage"] = {"include": True}
```

Anche il folding del system prompt deve restare attivo solo per LM Studio: la riga 528 `should_fold = not self._is_ollama and not tools` diventa:

```python
        should_fold = not self._is_ollama and not self._is_openrouter and not tools
```

`complete_nonstreaming` (riga 830): `url = f"{self._config.effective_base_url}/v1/chat/completions"`.

- [ ] **Step 5: Implementa — model_resolution.py**

Costruttore (dopo riga 49):

```python
        self._is_openrouter = config.provider == "openrouter"
```

`resolve()` (riga 179), PRIMA del check `if self._config.model != "auto"`:

```python
        if self._is_openrouter:
            # Nessun concetto di "modello caricato" per un provider cloud:
            # il modello attivo è la scelta esplicita dell'utente.
            return self._config.openrouter_model or "openrouter/auto"
```

`supports_vision` (riga 154), PRIMA del ramo esistente:

```python
        if self._is_openrouter and self._model_registry is not None:
            return self._model_registry.get_profile(
                self._config.openrouter_model or "openrouter/auto",
            ).supports_vision
```

- [ ] **Step 6: Verifica**

Run: `pytest tests/test_llm_openrouter.py -v`
Expected: tutti PASS TRANNE `test_openrouter_chat_uses_oai_path_with_usage_accounting` che fallisce SOLO sull'assert del campo `cost` nell'evento usage (implementato nel Task 3). Se fallisce su altro, correggi qui.

Run anche: `pytest tests/test_llm_model_resolution.py tests/test_llm_service.py tests/test_context_window_cache.py -v` → PASS (nessuna regressione locale).

- [ ] **Step 7: Commit**

```bash
git add backend/services/llm_service.py backend/services/llm/client.py backend/services/llm/model_resolution.py backend/tests/test_llm_openrouter.py
git commit -m "feat(llm): routing provider openrouter - header auth, percorso OAI-compat, resolve senza probe, context window da registry"
```

---

## Task 3: Costo per generazione — client → TurnProgress → TurnResult → turn.finished

**Files:**
- Modify: `backend/services/llm/client.py` (yield usage nel handler `[DONE]`, ~riga 684)
- Modify: `backend/services/turn/models.py` (`TurnResult` ~riga 112, `TurnProgress` ~riga 136)
- Modify: `backend/services/turn/direct_executor.py` (`_stream_initial` firma+usage ~righe 346, 411; `_finish` ~riga 309; call site ~riga 114)
- Modify: `backend/services/turn/tool_loop.py` (usage handler ~riga 914)
- Modify: `backend/services/turn/events.py` (`turn_finished` ~riga 251)
- Modify: `backend/api/ws_schema/chat.py` (`WsTurnFinished` ~riga 315)
- Test: `backend/tests/test_llm_openrouter.py` (già scritto al Task 2) + `backend/tests/test_turn_cost.py` (nuovo)

- [ ] **Step 1: Scrivi il test che fallisce**

Crea `backend/tests/test_turn_cost.py`:

```python
"""AL\\CE — Cost accounting through the turn pipeline."""

from __future__ import annotations

import pytest

from backend.services.turn.direct_executor import DirectTurnExecutor
from backend.services.turn.models import TurnProgress, TurnResult

pytestmark = pytest.mark.asyncio


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[dict] = []
        self.is_connected = True

    async def send(self, event: dict) -> None:
        self.events.append(event)


async def test_finish_stamps_cost_on_result_and_frame() -> None:
    executor = DirectTurnExecutor.__new__(DirectTurnExecutor)
    sink = _RecordingSink()
    progress = TurnProgress(turn_id="t1", steps=2, cost=0.0015)
    result = TurnResult(
        content="ok", thinking="", input_tokens=10, output_tokens=5,
        finish_reason="stop",
    )

    out = await executor._finish(sink, progress, result)

    assert out.cost == pytest.approx(0.0015)
    finished = [e for e in sink.events if e["type"] == "turn.finished"]
    assert finished and finished[0]["cost"] == pytest.approx(0.0015)


async def test_finish_omits_cost_when_zero() -> None:
    executor = DirectTurnExecutor.__new__(DirectTurnExecutor)
    sink = _RecordingSink()
    progress = TurnProgress(turn_id="t1", steps=1)
    result = TurnResult(
        content="ok", thinking="", input_tokens=10, output_tokens=5,
        finish_reason="stop",
    )

    out = await executor._finish(sink, progress, result)

    assert out.cost == 0.0
    finished = [e for e in sink.events if e["type"] == "turn.finished"]
    assert finished and finished[0]["cost"] is None
```

- [ ] **Step 2: Verifica che fallisca**

Run: `pytest tests/test_turn_cost.py -v`
Expected: FAIL (`TurnProgress` non ha `cost`, frame senza campo).

- [ ] **Step 3: Implementa — client.py**

Nel handler `[DONE]` di `_chat_openai_compat` (riga 684), estendi lo yield usage:

```python
                        if _last_usage:
                            yield {
                                "type": "usage",
                                "input_tokens": _last_usage.get("prompt_tokens", 0),
                                "output_tokens": _last_usage.get("completion_tokens", 0),
                                "cost": _last_usage.get("cost"),
                            }
```

(Il percorso nativo LM Studio non riporta costi: i consumatori usano `event.get("cost")`.)

- [ ] **Step 4: Implementa — turn/models.py**

`TurnResult`: aggiungi dopo `finish_reason` (i campi con default devono seguire quelli senza):

```python
    finish_reason: str
    cost: float = 0.0
    """Total generation cost in provider credits (0.0 = not reported)."""
```

e aggiorna la docstring Args con: `cost: Costo totale del turno in crediti provider (OpenRouter usage accounting); 0.0 quando il provider non lo riporta.`

`TurnProgress`: aggiungi dopo `tool_calls`:

```python
    cost: float = 0.0
    """Accumulated generation cost across all LLM steps of the turn."""
```

- [ ] **Step 5: Implementa — direct_executor.py**

Import in testa al file (vicino agli altri import): `from dataclasses import replace`.

Cambia la firma di `_stream_initial` aggiungendo `progress`:

```python
    async def _stream_initial(
        self,
        turn: TurnInput,
        sink: WSEventSink,
        cancel_event: asyncio.Event,
        progress: TurnProgress,
    ) -> tuple[str, str, list[dict[str, Any]], str, int, int]:
```

e il call site (riga 114): `= await self._stream_initial(turn, sink, cancel_event, progress)`.

Nel handler `elif etype == "usage":` (riga 411) aggiungi l'accumulo:

```python
                elif etype == "usage":
                    in_tok = int(event.get("input_tokens", 0) or 0)
                    out_tok = int(event.get("output_tokens", 0) or 0)
                    progress.cost += float(event.get("cost") or 0.0)
```

In `_finish` (riga 309), timbra il costo sul result e sul frame:

```python
    async def _finish(
        self,
        sink: WSEventSink,
        progress: TurnProgress,
        result: TurnResult,
    ) -> TurnResult:
        result = replace(result, cost=progress.cost)
        with contextlib.suppress(Exception):
            await sink.send(events.turn_finished(
                turn_id=progress.turn_id,
                finish_reason=result.finish_reason,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                steps=progress.steps,
                cost=result.cost if result.cost > 0 else None,
            ))
        return result
```

(aggiorna la docstring di `_finish`: il costo accumulato in `progress.cost` viene timbrato sul result con `dataclasses.replace` — unico punto).

- [ ] **Step 6: Implementa — tool_loop.py**

Nel handler usage della re-query (riga 914):

```python
                    elif event["type"] == "usage":
                        _loop_last_input_tokens = event.get(
                            "input_tokens", 0,
                        )
                        _loop_last_output_tokens = event.get(
                            "output_tokens", 0,
                        )
                        progress.cost += float(event.get("cost") or 0.0)
```

- [ ] **Step 7: Implementa — events.py e ws_schema/chat.py**

`turn_finished` (riga 251):

```python
def turn_finished(
    *,
    turn_id: str,
    finish_reason: str | None,
    input_tokens: int,
    output_tokens: int,
    steps: int,
    cost: float | None = None,
) -> dict[str, Any]:
```

e nel dict di ritorno aggiungi `"cost": cost,` (docstring Args: `cost: Costo totale del turno in crediti provider, o None quando non riportato.`).

`WsTurnFinished` (ws_schema/chat.py riga 315):

```python
class WsTurnFinished(ChatServerFrame):
    """The turn has finished; summary statistics follow."""

    type: Literal["turn.finished"]
    turn_id: str
    finish_reason: str | None = None
    input_tokens: int
    output_tokens: int
    steps: int
    cost: float | None = None
```

- [ ] **Step 8: Verifica**

Run: `pytest tests/test_turn_cost.py tests/test_llm_openrouter.py -v` → PASS (ora anche il test usage+cost del Task 2).
Run: `pytest tests/test_direct_executor_streaming.py tests/test_direct_executor_tool_loop.py tests/test_tool_loop.py tests/contracts/test_ws_schema_chat.py -v` → PASS (campo opzionale: il vocabolario congelato non cambia).

- [ ] **Step 9: Commit**

```bash
git add backend/services/llm/client.py backend/services/turn/ backend/api/ws_schema/chat.py backend/tests/test_turn_cost.py backend/tests/test_llm_openrouter.py
git commit -m "feat(turn): costo per generazione da usage accounting - accumulo su TurnProgress, TurnResult.cost, frame turn.finished esteso"
```

---

## Task 4: Persistenza — Message.usage, migration, _persist, total_cost

**Files:**
- Modify: `backend/db/models.py` (classe `Message`, dopo `token_count` ~riga 122)
- Modify: `backend/db/database.py` (`_COLUMN_MIGRATIONS` ~riga 105)
- Modify: `backend/api/routes/chat/_persist.py` (~riga 220)
- Modify: `backend/api/routes/chat/conversations.py` (`get_conversation`, helper + return ~riga 381)
- Test: `backend/tests/test_turn_cost.py` (append)

- [ ] **Step 1: Scrivi i test che falliscono**

Append a `backend/tests/test_turn_cost.py`:

```python
def test_sum_usage_cost_ignores_malformed_entries() -> None:
    from backend.api.routes.chat.conversations import _sum_usage_cost

    class _Msg:
        def __init__(self, usage) -> None:
            self.usage = usage

    msgs = [
        _Msg({"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001}),
        _Msg({"cost": "0.002"}),      # stringa valida
        _Msg({"cost": "n/a"}),        # malformata → ignorata
        _Msg(None),                    # nessuna usage
        _Msg({"prompt_tokens": 3}),    # senza cost
    ]
    assert _sum_usage_cost(msgs) == pytest.approx(0.003)


def test_message_model_has_usage_column() -> None:
    from backend.db.models import Message

    msg = Message(conversation_id=__import__("uuid").uuid4(), role="assistant")
    assert msg.usage is None
    msg.usage = {"prompt_tokens": 1, "completion_tokens": 2, "cost": 0.5}
    assert msg.usage["cost"] == 0.5
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_turn_cost.py -v -k "usage"` → FAIL (import/attributo mancanti).

- [ ] **Step 3: Implementa — db/models.py**

In `Message`, dopo `token_count` (riga 122-125):

```python
    usage: Optional[Any] = Field(
        default=None,
        sa_column=sa.Column(sa.JSON, nullable=True),
        description=(
            "Per-turn usage from the LLM API: "
            "{prompt_tokens, completion_tokens, cost} — cost in provider "
            "credits (OpenRouter usage accounting)."
        ),
    )
```

- [ ] **Step 4: Implementa — db/database.py**

In `_COLUMN_MIGRATIONS` (riga 105) aggiungi in coda:

```python
        ("messages", "usage", "TEXT"),
```

- [ ] **Step 5: Implementa — _persist.py**

In `_persist.py`, dopo il blocco `token_count` (righe 216-220, dopo `await session.flush()`), allo stesso livello del `if` esterno su `result.input_tokens`, aggiungi un blocco indipendente:

```python
        # Usage accounting (OpenRouter): persisti il costo del turno sul
        # messaggio assistant finale. La SUM per conversazione è on-read.
        if asst_msg is not None and result.cost > 0:
            asst_msg.usage = {
                "prompt_tokens": result.input_tokens,
                "completion_tokens": result.output_tokens,
                "cost": round(result.cost, 8),
            }
            session.add(asst_msg)
```

(posizionalo PRIMA di `conv.updated_at = _utcnow()` a riga 222, così entra nello stesso commit).

- [ ] **Step 6: Implementa — conversations.py**

Aggiungi il modulo-level helper (vicino agli altri helper privati del file):

```python
def _sum_usage_cost(messages: Sequence[Any]) -> float:
    """Somma i costi (crediti provider) dalle usage persistite sui messaggi."""
    total = 0.0
    for m in messages:
        usage = getattr(m, "usage", None)
        if not isinstance(usage, dict):
            continue
        try:
            total += float(usage.get("cost") or 0.0)
        except (TypeError, ValueError):
            continue
    return total
```

(aggiungi `from collections.abc import Sequence` agli import se assente; `Any` è già importato o aggiungilo).

In `get_conversation`, nel dict di ritorno (riga 381) aggiungi dopo `"context_info": context_info,`:

```python
            "total_cost": (
                round(_sum_usage_cost(messages), 6)
                if _sum_usage_cost(messages) > 0 else None
            ),
```

ATTENZIONE: chiama l'helper una volta sola — usa una variabile locale prima del return:

```python
        total_cost = _sum_usage_cost(messages)
```

e nel dict: `"total_cost": round(total_cost, 6) if total_cost > 0 else None,`.

Nel dict per-messaggio (riga 389+) aggiungi dopo `"tool_call_id": m.tool_call_id,`:

```python
                    "usage": m.usage,
```

- [ ] **Step 7: Verifica**

Run: `pytest tests/test_turn_cost.py -v` → PASS.
Run: `pytest tests/test_branch_conversation.py tests/test_message_editing.py tests/test_conversation_export.py -v` → PASS (nessuna regressione su Message).

- [ ] **Step 8: Commit**

```bash
git add backend/db/models.py backend/db/database.py backend/api/routes/chat/_persist.py backend/api/routes/chat/conversations.py backend/tests/test_turn_cost.py
git commit -m "feat(db): colonna messages.usage con costo per turno e total_cost per conversazione"
```

---

## Task 5: Catalogo — registry refresh_from_openrouter + OpenRouterService

**Files:**
- Modify: `backend/services/model_capability_registry.py` (dopo `refresh_from_api`, ~riga 151)
- Create: `backend/services/openrouter_service.py`
- Modify: `backend/core/service_groups.py` (`InferenceServices` ~riga 55)
- Modify: `backend/core/context.py` (`FLAT_FIELDS` ~riga 62 + property nel gruppo inference ~riga 101)
- Modify: `backend/core/bootstrap/inference.py` (~riga 33)
- Modify: `backend/core/bootstrap/shutdown.py` (vicino a llm_service ~riga 55)
- Test: `backend/tests/test_openrouter_service.py` (nuovo)

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `backend/tests/test_openrouter_service.py`:

```python
"""AL\\CE — Tests for the OpenRouter catalog/credits service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.config import LLMConfig
from backend.services.model_capability_registry import ModelCapabilityRegistry
from backend.services.openrouter_service import OpenRouterService

pytestmark = pytest.mark.asyncio

_CATALOG = [
    {
        "id": "anthropic/claude-sonnet-5",
        "name": "Anthropic: Claude Sonnet 5",
        "description": "A very good model",
        "context_length": 200000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "architecture": {"input_modalities": ["text", "image"]},
        "supported_parameters": ["tools", "reasoning", "temperature"],
        "top_provider": {"context_length": 200000},
    },
    {
        "id": "qwen/qwen3.5-72b",
        "name": "Qwen 3.5 72B",
        "context_length": 32768,
        "pricing": {"prompt": "0.0000004", "completion": "0.0000012"},
        "architecture": {"input_modalities": ["text"]},
        "supported_parameters": ["tools", "temperature"],
    },
]


def _config() -> LLMConfig:
    return LLMConfig(provider="openrouter", openrouter_api_key="sk-or-x")


def _json_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=payload)
    return resp


async def test_list_models_caches_and_seeds_registry() -> None:
    registry = ModelCapabilityRegistry()
    svc = OpenRouterService(_config(), model_registry=registry)
    svc._http.get = AsyncMock(return_value=_json_response({"data": _CATALOG}))

    models = await svc.list_models()
    assert len(models) == 2
    # Seconda chiamata: cache, nessun secondo GET.
    await svc.list_models()
    assert svc._http.get.await_count == 1

    profile = registry.get_profile("anthropic/claude-sonnet-5")
    assert profile.supports_tool_use is True
    assert profile.supports_vision is True
    assert profile.supports_thinking is True
    assert profile.context_length == 200000
    assert profile.source == "openrouter_api"

    text_only = registry.get_profile("qwen/qwen3.5-72b")
    assert text_only.supports_vision is False
    assert text_only.supports_thinking is False
    await svc.close()


async def test_list_models_force_refresh_bypasses_cache() -> None:
    svc = OpenRouterService(_config())
    svc._http.get = AsyncMock(return_value=_json_response({"data": _CATALOG}))
    await svc.list_models()
    await svc.list_models(force_refresh=True)
    assert svc._http.get.await_count == 2
    await svc.close()


async def test_get_credits_sends_auth_header() -> None:
    svc = OpenRouterService(_config())
    svc._http.get = AsyncMock(return_value=_json_response({
        "data": {"limit": 10.0, "limit_remaining": 7.5, "usage": 2.5},
    }))

    data = await svc.get_credits()
    assert data["limit_remaining"] == 7.5
    _, kwargs = svc._http.get.await_args
    assert kwargs["headers"]["Authorization"] == "Bearer sk-or-x"
    await svc.close()
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_openrouter_service.py -v` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implementa — registry**

In `model_capability_registry.py`, dopo `refresh_from_api` (riga 150), aggiungi:

```python
    async def refresh_from_openrouter(
        self, models_data: list[dict[str, Any]],
    ) -> int:
        """Update profiles from the OpenRouter ``GET /v1/models`` response.

        Capabilities are derived from ``supported_parameters`` (tools,
        reasoning) and ``architecture.input_modalities`` (vision).

        Args:
            models_data: The ``data`` list from the OpenRouter response.

        Returns:
            Number of profiles created or updated.
        """
        updated = 0
        async with self._lock:
            for m in models_data:
                model_id = m.get("id", "")
                if not model_id:
                    continue
                params = m.get("supported_parameters") or []
                arch = m.get("architecture") or {}
                modalities = arch.get("input_modalities") or []
                top = m.get("top_provider") or {}
                self._profiles[model_id] = ModelProfile(
                    model_id=model_id,
                    supports_thinking="reasoning" in params,
                    supports_vision="image" in modalities,
                    supports_tool_use="tools" in params,
                    context_length=int(
                        m.get("context_length")
                        or top.get("context_length")
                        or 0
                    ),
                    source="openrouter_api",
                )
                updated += 1
            self._last_refresh = time.monotonic()
        if updated:
            logger.debug(
                "Model registry refreshed from OpenRouter: {} profile(s)",
                updated,
            )
        return updated
```

- [ ] **Step 4: Implementa — openrouter_service.py**

Crea `backend/services/openrouter_service.py`:

```python
"""AL\\CE — OpenRouter catalog and credits service.

Thin httpx wrapper over the two ancillary OpenRouter endpoints:
``GET /v1/models`` (public catalog, cached in-process) and
``GET /v1/key`` (key limits/usage, authenticated). Chat streaming does
NOT go through this service — it lives in ``services/llm/client.py``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from loguru import logger

from backend.core.config import LLMConfig
from backend.services.model_capability_registry import ModelCapabilityRegistry


class OpenRouterService:
    """Catalog + credits access for OpenRouter.

    Args:
        config: The shared ``LLMConfig`` (reads ``openrouter_base_url`` /
            ``openrouter_api_key`` at call time, so runtime key changes
            are picked up without a rebuild).
        model_registry: Optional capability registry seeded from the
            catalog on every successful fetch.
    """

    def __init__(
        self,
        config: LLMConfig,
        model_registry: ModelCapabilityRegistry | None = None,
    ) -> None:
        self._config = config
        self._registry = model_registry
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0, read=30.0, write=10.0, pool=10.0,
            ),
        )
        self._catalog_cache: list[dict[str, Any]] | None = None
        self._catalog_fetched_at: float = 0.0
        self._catalog_ttl: float = 3600.0
        self._lock = asyncio.Lock()

    def _base(self) -> str:
        return self._config.openrouter_base_url.rstrip("/")

    def _auth_headers(self) -> dict[str, str]:
        if not self._config.openrouter_api_key:
            return {}
        return {
            "Authorization": f"Bearer {self._config.openrouter_api_key}",
        }

    async def list_models(
        self, force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Return the OpenRouter model catalog (cached, TTL 1h).

        Args:
            force_refresh: Bypass the cache and re-fetch.

        Returns:
            The raw ``data`` list from the OpenRouter response.
        """
        now = time.monotonic()
        if (
            not force_refresh
            and self._catalog_cache is not None
            and now - self._catalog_fetched_at < self._catalog_ttl
        ):
            return self._catalog_cache
        async with self._lock:
            now = time.monotonic()
            if (
                not force_refresh
                and self._catalog_cache is not None
                and now - self._catalog_fetched_at < self._catalog_ttl
            ):
                return self._catalog_cache
            resp = await self._http.get(f"{self._base()}/v1/models")
            resp.raise_for_status()
            models: list[dict[str, Any]] = resp.json().get("data", [])
            if self._registry is not None and models:
                await self._registry.refresh_from_openrouter(models)
            self._catalog_cache = models
            self._catalog_fetched_at = now
            logger.info("OpenRouter catalog fetched: {} models", len(models))
            return models

    async def get_credits(self) -> dict[str, Any]:
        """Return key limits/usage from ``GET /v1/key``.

        Raises:
            httpx.HTTPStatusError: On 401 (invalid key) or other HTTP errors.
            httpx.HTTPError: When OpenRouter is unreachable.
        """
        resp = await self._http.get(
            f"{self._base()}/v1/key", headers=self._auth_headers(),
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json().get("data", {})
        return data

    def invalidate_catalog(self) -> None:
        """Drop the cached catalog (next call re-fetches)."""
        self._catalog_cache = None
        self._catalog_fetched_at = 0.0

    async def close(self) -> None:
        """Release the underlying httpx client."""
        await self._http.aclose()
```

- [ ] **Step 5: Wiring — service group, context, bootstrap, shutdown**

`backend/core/service_groups.py`, in `InferenceServices` dopo `model_downloader`:

```python
    openrouter_service: Any = None
    """OpenRouter catalog/credits service (always constructed, cheap)."""
```

`backend/core/context.py`: aggiungi `"openrouter_service",` alla tupla `FLAT_FIELDS` (riga 62, dopo `"model_registry",`) e la coppia property/setter nel blocco inference (dopo `model_registry`, ~riga 147):

```python
    @property
    def openrouter_service(self) -> Any:
        return self.inference.openrouter_service

    @openrouter_service.setter
    def openrouter_service(self, value: Any) -> None:
        self.inference.openrouter_service = value
```

`backend/core/bootstrap/inference.py`, dopo `ctx.llm_service = llm_service` (riga 33):

```python
    from backend.services.openrouter_service import OpenRouterService
    ctx.openrouter_service = OpenRouterService(
        config.llm, model_registry=model_registry,
    )
```

`backend/core/bootstrap/shutdown.py`, dopo il blocco `llm_service` (riga 59):

```python
    if ctx.openrouter_service is not None:
        try:
            await ctx.openrouter_service.close()
        except Exception as exc:
            logger.error("OpenRouter service shutdown error: {}", exc)
```

- [ ] **Step 6: Verifica**

Run: `pytest tests/test_openrouter_service.py tests/test_context.py tests/test_context_groups.py tests/test_bootstrap.py -v` → PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/services/openrouter_service.py backend/services/model_capability_registry.py backend/core/service_groups.py backend/core/context.py backend/core/bootstrap/inference.py backend/core/bootstrap/shutdown.py backend/tests/test_openrouter_service.py
git commit -m "feat(openrouter): servizio catalogo/crediti con cache e seeding del capability registry"
```

---

## Task 6: Route REST /api/openrouter

**Files:**
- Create: `backend/api/routes/openrouter.py`
- Modify: `backend/api/routes/__init__.py` (import + include_router)
- Test: `backend/tests/test_openrouter_route.py` (nuovo)

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `backend/tests/test_openrouter_route.py` (serializzazione pura, senza app):

```python
"""AL\\CE — Tests for the OpenRouter REST route serialisers."""

from __future__ import annotations

from backend.api.routes.openrouter import (
    OpenRouterCreditsResponse,
    _serialise_model,
)


def test_serialise_model_maps_capabilities_and_pricing() -> None:
    out = _serialise_model({
        "id": "anthropic/claude-sonnet-5",
        "name": "Anthropic: Claude Sonnet 5",
        "description": "x" * 900,
        "context_length": 200000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
        "architecture": {"input_modalities": ["text", "image"]},
        "supported_parameters": ["tools", "reasoning"],
    })
    assert out.id == "anthropic/claude-sonnet-5"
    assert out.context_length == 200000
    assert out.pricing.prompt == 0.000003
    assert out.pricing.completion == 0.000015
    assert out.supports_tools and out.supports_vision and out.supports_reasoning
    assert len(out.description) == 500  # troncata


def test_serialise_model_tolerates_missing_fields() -> None:
    out = _serialise_model({"id": "x/y"})
    assert out.name == "x/y"
    assert out.pricing.prompt is None
    assert out.supports_tools is False


def test_credits_response_from_key_payload() -> None:
    resp = OpenRouterCreditsResponse.from_key_data({
        "limit": 10.0, "limit_remaining": 7.5, "usage": 2.5,
        "is_free_tier": False,
    })
    assert resp.limit_remaining == 7.5
    assert resp.usage == 2.5
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_openrouter_route.py -v` → FAIL (modulo mancante).

- [ ] **Step 3: Implementa la route**

Crea `backend/api/routes/openrouter.py`:

```python
"""AL\\CE — OpenRouter endpoints (model catalog, credits)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.core.context import AppContext

router = APIRouter(tags=["openrouter"])


def _ctx(request: Request) -> AppContext:
    return request.app.state.context


# ---------------------------------------------------------------------------
# Response models (contract-first: ratchet test richiede response_model)
# ---------------------------------------------------------------------------


class OpenRouterPricing(BaseModel):
    """Prezzo per token (USD), None quando non riportato."""

    prompt: float | None = None
    completion: float | None = None


class OpenRouterModelOut(BaseModel):
    """Un modello del catalogo OpenRouter, ridotto ai campi usati dalla UI."""

    id: str
    name: str
    description: str = ""
    context_length: int = 0
    pricing: OpenRouterPricing
    supports_tools: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False


class OpenRouterModelsResponse(BaseModel):
    """Catalogo modelli OpenRouter."""

    models: list[OpenRouterModelOut]


class OpenRouterCreditsResponse(BaseModel):
    """Stato crediti/limiti della API key (da ``GET /v1/key``)."""

    limit: float | None = None
    limit_remaining: float | None = None
    usage: float = 0.0
    is_free_tier: bool | None = None

    @classmethod
    def from_key_data(cls, data: dict[str, Any]) -> "OpenRouterCreditsResponse":
        """Build from the raw ``data`` object of the /v1/key response."""
        def _num(value: Any) -> float | None:
            try:
                return float(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        return cls(
            limit=_num(data.get("limit")),
            limit_remaining=_num(data.get("limit_remaining")),
            usage=_num(data.get("usage")) or 0.0,
            is_free_tier=data.get("is_free_tier"),
        )


# ---------------------------------------------------------------------------
# Serialisers
# ---------------------------------------------------------------------------


def _serialise_model(m: dict[str, Any]) -> OpenRouterModelOut:
    """Map a raw OpenRouter catalog entry to the UI shape."""
    params = m.get("supported_parameters") or []
    arch = m.get("architecture") or {}
    pricing = m.get("pricing") or {}

    def _price(key: str) -> float | None:
        raw = pricing.get(key)
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    model_id = m.get("id", "")
    return OpenRouterModelOut(
        id=model_id,
        name=m.get("name") or model_id,
        description=(m.get("description") or "")[:500],
        context_length=int(
            m.get("context_length")
            or (m.get("top_provider") or {}).get("context_length")
            or 0
        ),
        pricing=OpenRouterPricing(
            prompt=_price("prompt"), completion=_price("completion"),
        ),
        supports_tools="tools" in params,
        supports_vision="image" in (arch.get("input_modalities") or []),
        supports_reasoning="reasoning" in params,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/openrouter/models", response_model=OpenRouterModelsResponse)
async def list_openrouter_models(
    request: Request, force_refresh: bool = False,
) -> OpenRouterModelsResponse:
    """Return the OpenRouter model catalog (cached server-side, TTL 1h)."""
    ctx = _ctx(request)
    svc = ctx.openrouter_service
    if svc is None:
        raise HTTPException(503, "OpenRouter service unavailable")
    try:
        models = await svc.list_models(force_refresh=force_refresh)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            502, f"OpenRouter returned {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "OpenRouter unreachable") from exc
    return OpenRouterModelsResponse(
        models=[_serialise_model(m) for m in models],
    )


@router.get("/openrouter/credits", response_model=OpenRouterCreditsResponse)
async def get_openrouter_credits(request: Request) -> OpenRouterCreditsResponse:
    """Return credits/limits for the configured OpenRouter API key."""
    ctx = _ctx(request)
    svc = ctx.openrouter_service
    if svc is None:
        raise HTTPException(503, "OpenRouter service unavailable")
    if not ctx.config.llm.openrouter_api_key:
        raise HTTPException(400, "OpenRouter API key not configured")
    try:
        data = await svc.get_credits()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 401:
            raise HTTPException(401, "OpenRouter API key invalid") from exc
        raise HTTPException(
            502, f"OpenRouter returned {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "OpenRouter unreachable") from exc
    return OpenRouterCreditsResponse.from_key_data(data)
```

- [ ] **Step 4: Registra la route**

In `backend/api/routes/__init__.py`: aggiungi `openrouter` alla riga di import (in ordine alfabetico) e `router.include_router(openrouter.router)` dopo `models.router`.

- [ ] **Step 5: Verifica**

Run: `pytest tests/test_openrouter_route.py tests/contracts/test_response_models.py tests/test_app.py -v` → PASS (il ratchet vede i `response_model`).

- [ ] **Step 6: Commit**

```bash
git add backend/api/routes/openrouter.py backend/api/routes/__init__.py backend/tests/test_openrouter_route.py
git commit -m "feat(api): route /api/openrouter/models e /credits con response model tipizzati"
```

---

## Task 7: PUT/GET /api/config — provider switch, API key, rebuild, preferenze

**Files:**
- Modify: `backend/api/routes/config.py` (`_REDACT_KEYS` ~riga 33; `get_config` ~riga 262; `update_config` blocco llm ~riga 385; nuovo helper `_apply_llm_provider_change`)
- Modify: `backend/services/preferences_service.py` (`PERSISTABLE_LLM_KEYS` ~riga 31)
- Test: `backend/tests/test_openrouter_config.py` (nuovo)

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `backend/tests/test_openrouter_config.py`:

```python
"""AL\\CE — Config route behaviour for the OpenRouter provider."""

from __future__ import annotations

from backend.api.routes.config import _REDACT_KEYS, _redact
from backend.services.preferences_service import PERSISTABLE_LLM_KEYS


def test_redact_masks_openrouter_api_key() -> None:
    assert "openrouter_api_key" in _REDACT_KEYS
    node = {"llm": {"openrouter_api_key": "sk-or-secret", "model": "auto"}}
    redacted = _redact(node)
    assert redacted["llm"]["openrouter_api_key"] == "***"
    assert redacted["llm"]["model"] == "auto"


def test_openrouter_keys_are_persistable_preferences() -> None:
    for key in (
        "provider",
        "openrouter_api_key",
        "openrouter_model",
        "openrouter_favorites",
    ):
        assert key in PERSISTABLE_LLM_KEYS
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_openrouter_config.py -v` → FAIL.

- [ ] **Step 3: Implementa — masking e preferenze**

`config.py` riga 33:

```python
_REDACT_KEYS: frozenset[str] = frozenset({
    "api_token", "token", "password", "secret",
    "api_key", "openrouter_api_key",
})
```

`preferences_service.py` riga 31, aggiungi a `PERSISTABLE_LLM_KEYS`:

```python
    "provider",
    "openrouter_api_key",
    "openrouter_model",
    "openrouter_favorites",
```

(NOTA dichiarata: la key viene persistita in chiaro nel DB locale, stessa politica dell'`api_token` — decisione presa in brainstorming. `SENSITIVE_PREFERENCE_KEYS` blocca solo `password` e resta invariato.)

- [ ] **Step 4: Implementa — GET /api/config**

In `get_config` (riga 262), nel dict `"llm"` aggiungi dopo `"user_preferred_name"`:

```python
            "openrouter_api_key_configured": bool(cfg.llm.openrouter_api_key),
            "openrouter_model": cfg.llm.openrouter_model,
            "openrouter_favorites": list(cfg.llm.openrouter_favorites),
```

(il campo `provider` è già presente in `get_config`.)

- [ ] **Step 5: Implementa — update_config blocco llm**

In `update_config`, all'inizio del blocco `if "llm" in body:` (riga 385) aggiungi `llm_service_rebuild_needed = False` e in coda al blocco (dopo `user_preferred_name`, riga 485):

```python
        if "provider" in llm_updates:
            prov = str(llm_updates["provider"]).strip().lower()
            if prov not in ("lmstudio", "ollama", "openrouter"):
                raise HTTPException(
                    400, "provider must be one of: lmstudio, ollama, openrouter",
                )
            if prov != cfg.llm.provider:
                object.__setattr__(cfg.llm, "provider", prov)
                llm_service_rebuild_needed = True
        if "openrouter_api_key" in llm_updates:
            raw_key = str(llm_updates["openrouter_api_key"] or "").strip()
            # "***" è la maschera che il GET restituisce: mai sovrascrivere
            # la chiave reale con la maschera.
            if raw_key and raw_key != "***":
                if len(raw_key) > 256:
                    raise HTTPException(400, "openrouter_api_key max 256 chars")
                object.__setattr__(cfg.llm, "openrouter_api_key", raw_key)
                llm_service_rebuild_needed = True
        if "openrouter_model" in llm_updates:
            om = str(llm_updates["openrouter_model"] or "").strip()
            if len(om) > 256:
                raise HTTPException(400, "openrouter_model max 256 chars")
            object.__setattr__(cfg.llm, "openrouter_model", om)
            if ctx.llm_service is not None:
                ctx.llm_service.invalidate_model_cache()
                ctx.llm_service.invalidate_context_window_cache()
        if "openrouter_favorites" in llm_updates:
            favs = llm_updates["openrouter_favorites"]
            if not isinstance(favs, list) or not all(
                isinstance(f, str) for f in favs
            ):
                raise HTTPException(
                    400, "openrouter_favorites must be a list of strings",
                )
            object.__setattr__(cfg.llm, "openrouter_favorites", favs[:200])
```

ATTENZIONE: `llm_service_rebuild_needed` va inizializzato PRIMA di `if "llm" in body:` (es. subito dopo `email_password_changed = False`, riga 382) perché è letto dopo il blocco.

Poi, dopo il blocco email/persistenza preferenze (dopo riga 723 `await _apply_email_changes(ctx)`), aggiungi:

```python
    if llm_service_rebuild_needed:
        await _apply_llm_provider_change(ctx)
```

E il nuovo helper (vicino a `_apply_stt_changes`):

```python
async def _apply_llm_provider_change(ctx: AppContext) -> None:
    """Rebuild the LLM service after a provider or API-key change.

    Auth headers on the shared httpx client and the provider-derived
    flags in LLMClient/ModelResolver are fixed at construction time, so
    an in-place config mutation is not enough — recreate the service,
    mirroring the STT/TTS restart pattern.
    """
    from backend.services.llm_service import LLMService

    old = ctx.llm_service
    new_service = LLMService(ctx.config.llm, model_registry=ctx.model_registry)
    ctx.llm_service = new_service
    if ctx.lmstudio_manager is not None:
        ctx.lmstudio_manager.add_models_changed_listener(
            new_service.invalidate_context_window_cache
        )
    if old is not None:
        try:
            await old.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to close previous LLM service: {}", exc)
    logger.info("LLM service rebuilt (provider={})", ctx.config.llm.provider)
```

- [ ] **Step 6: Verifica**

Run: `pytest tests/test_openrouter_config.py tests/test_settings.py tests/test_app.py -v` → PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/api/routes/config.py backend/services/preferences_service.py backend/tests/test_openrouter_config.py
git commit -m "feat(config): switch provider a runtime con rebuild LLMService, API key mascherata e preferenze persistite"
```

---

## Task 8: Guardia embedding — la memoria resta locale

**Files:**
- Modify: `backend/services/embedding_client.py` (costruttore facade ~riga 265; `encode`/`encode_batch`/`probe_dimensions` ~righe 298, 356, 364)
- Modify: `backend/core/bootstrap/knowledge.py` (~riga 26)
- Test: `backend/tests/test_embedding_client.py` (append)

- [ ] **Step 1: Scrivi i test che falliscono**

Append a `backend/tests/test_embedding_client.py` (adatta gli import a quelli già presenti nel file):

```python
@pytest.mark.asyncio
async def test_api_disabled_goes_straight_to_fastembed(monkeypatch) -> None:
    """Con api_enabled=False il backend OpenAI non viene MAI chiamato."""
    client = EmbeddingClient(
        base_url="http://localhost:1234",
        model="text-embedding-x",
        dimensions=384,
        fallback_enabled=True,
        api_enabled=False,
    )

    async def _fail(*_a, **_k):
        raise AssertionError("OpenAI backend must not be called")

    monkeypatch.setattr(client._openai, "encode", _fail)
    monkeypatch.setattr(client._openai, "encode_batch", _fail)

    fake_vec = [0.0] * 384

    async def _fake_encode(_text: str) -> list[float]:
        return fake_vec

    async def _fake_encode_batch(texts: list[str]) -> list[list[float]]:
        return [fake_vec for _ in texts]

    monkeypatch.setattr(client._fastembed, "encode", _fake_encode)
    monkeypatch.setattr(client._fastembed, "encode_batch", _fake_encode_batch)

    assert await client.encode("ciao") == fake_vec
    assert await client.encode_batch(["a", "b"]) == [fake_vec, fake_vec]


@pytest.mark.asyncio
async def test_api_disabled_probe_returns_fallback_dims() -> None:
    client = EmbeddingClient(
        base_url="http://localhost:1234",
        model="text-embedding-x",
        dimensions=384,
        fallback_enabled=True,
        api_enabled=False,
    )
    assert await client.probe_dimensions() == 384
```

- [ ] **Step 2: Verifica che falliscano**

Run: `pytest tests/test_embedding_client.py -v -k api_disabled` → FAIL (`unexpected keyword argument 'api_enabled'`).

- [ ] **Step 3: Implementa — embedding_client.py**

Costruttore della facade `EmbeddingClient` (riga 265): aggiungi il parametro e salvalo:

```python
    def __init__(
        self,
        base_url: str,
        model: str,
        dimensions: int,
        fallback_enabled: bool = True,
        api_enabled: bool = True,
    ) -> None:
        self._api_enabled = api_enabled
```

(aggiorna la docstring Args: `api_enabled: quando False il backend API remoto viene saltato del tutto — usato con provider LLM cloud (OpenRouter) per tenere gli embedding rigorosamente locali.`)

`encode` (riga 356) e `encode_batch` (riga 364): early-exit prima del try:

```python
        if not self._api_enabled:
            return await self._fallback_encode(text)
```

```python
        if not self._api_enabled:
            return await self._fallback_encode_batch(texts)
```

NOTA: `_fallback_encode` logga `logger.warning("Embedding API unreachable...")` — con `api_enabled=False` quel warning è fuorviante. Sposta il warning nei chiamanti try/except (i due `except` di `encode`/`encode_batch`) e rimuovilo dai `_fallback_*`, così il percorso api-disabled resta silenzioso.

`probe_dimensions` (riga 298): subito dopo la docstring:

```python
        if not self._api_enabled:
            return (
                self._fastembed.dimensions
                if self._fastembed is not None
                else self._openai.dimensions
            )
```

(verifica che `FastEmbedClient` esponga `dimensions`; se la property si chiama diversamente usa quella reale.)

- [ ] **Step 4: Implementa — bootstrap knowledge.py**

Riga 26:

```python
    embedding_client = EmbeddingClient(
        base_url=config.llm.base_url,
        model=config.qdrant.embedding_model,
        dimensions=config.qdrant.embedding_dim,
        fallback_enabled=config.qdrant.embedding_fallback,
        api_enabled=config.llm.provider != "openrouter",
    )
```

- [ ] **Step 5: Verifica**

Run: `pytest tests/test_embedding_client.py tests/test_memory_service.py -v` → PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/embedding_client.py backend/core/bootstrap/knowledge.py backend/tests/test_embedding_client.py
git commit -m "feat(knowledge): guardia embedding - con provider openrouter la memoria usa solo fastembed locale"
```

---

## Task 9: Rigenerazione contratti

**Files:**
- Generated: `backend/openapi.json` (o percorso equivalente dello script), `frontend/src/renderer/src/types/generated/api.d.ts`, `frontend/src/renderer/src/types/generated/openapi.json`

- [ ] **Step 1: Rigenera**

Da repo root (PowerShell, venv attivo): `.\scripts\gen-contracts.ps1`
Expected: exit 0, file generati aggiornati con `OpenRouterModelsResponse`, `OpenRouterModelOut`, `OpenRouterCreditsResponse`, `WsTurnFinished.cost`.

- [ ] **Step 2: Verifica**

Run: `.\scripts\check-contracts.ps1` → exit 0.
Run (da `backend/`): `pytest tests/contracts/ -v` → PASS.

- [ ] **Step 3: Commit**

```bash
git add -A frontend/src/renderer/src/types/generated backend/
git commit -m "chore(contracts): rigenerazione contratti per route openrouter e frame turn.finished esteso"
```

---

## Task 10: FE — tipi, modulo API, settings store

**Files:**
- Create: `frontend/src/renderer/src/types/openrouter.ts`
- Create: `frontend/src/renderer/src/services/api/openrouter.ts`
- Modify: `frontend/src/renderer/src/services/api/index.ts` (barrel export)
- Modify: `frontend/src/renderer/src/stores/settings.ts` (interfaccia llm ~riga 17; load ~riga 302; save ~riga 379; nuova action)

- [ ] **Step 1: Tipi**

Crea `types/openrouter.ts`:

```ts
import type { ApiSchema } from './generated'

export type OpenRouterModel = ApiSchema<'OpenRouterModelOut'>
export type OpenRouterModelsResponse = ApiSchema<'OpenRouterModelsResponse'>
export type OpenRouterCredits = ApiSchema<'OpenRouterCreditsResponse'>

export type LlmProvider = 'lmstudio' | 'ollama' | 'openrouter'
```

- [ ] **Step 2: Modulo API**

Crea `services/api/openrouter.ts`:

```ts
import { request } from './http'
import type { OpenRouterCredits, OpenRouterModelsResponse } from '../../types/openrouter'

export const openrouterApi = {
  getModels: (forceRefresh = false): Promise<OpenRouterModelsResponse> =>
    request<OpenRouterModelsResponse>(
      `/openrouter/models${forceRefresh ? '?force_refresh=true' : ''}`
    ),
  getCredits: (): Promise<OpenRouterCredits> =>
    request<OpenRouterCredits>('/openrouter/credits')
}
```

In `services/api/index.ts` aggiungi (ordine alfabetico): `export { openrouterApi } from './openrouter'`.

- [ ] **Step 3: Settings store**

In `stores/settings.ts`:

1. Interfaccia `AliceSettings.llm` (riga 17): aggiungi

```ts
    provider: LlmProvider
    openrouterModel: string
    openrouterFavorites: string[]
```

con import `import type { LlmProvider } from '../types/openrouter'`. Default nello stato iniziale (riga 63): `provider: 'lmstudio'`, `openrouterModel: ''`, `openrouterFavorites: []`.

2. Stato extra (vicino agli altri ref top-level): `const openrouterKeyConfigured = ref(false)` — esportalo nel return dello store.

3. Blocco load (riga 302+), aggiungi:

```ts
        settings.value.llm.provider =
          (llm.provider as LlmProvider) ?? settings.value.llm.provider
        settings.value.llm.openrouterModel =
          (llm.openrouter_model as string) ?? settings.value.llm.openrouterModel
        settings.value.llm.openrouterFavorites =
          (llm.openrouter_favorites as string[]) ?? settings.value.llm.openrouterFavorites
        openrouterKeyConfigured.value = Boolean(llm.openrouter_api_key_configured)
```

4. Body di save (riga 379+), aggiungi al blocco `llm`:

```ts
        provider: settings.value.llm.provider,
        openrouter_model: settings.value.llm.openrouterModel,
        openrouter_favorites: settings.value.llm.openrouterFavorites,
```

5. Nuova action (la API key NON vive nello stato deep-watched — va inviata una tantum):

```ts
  async function setOpenrouterApiKey(key: string): Promise<void> {
    const trimmed = key.trim()
    if (!trimmed) return
    await configApi.updateConfig({ llm: { openrouter_api_key: trimmed } })
    openrouterKeyConfigured.value = true
  }
```

Esporta `setOpenrouterApiKey` e `openrouterKeyConfigured` dal return dello store.

- [ ] **Step 4: Verifica**

Run (da `frontend/`): `npm run typecheck` → exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/types/openrouter.ts frontend/src/renderer/src/services/api/openrouter.ts frontend/src/renderer/src/services/api/index.ts frontend/src/renderer/src/stores/settings.ts
git commit -m "feat(fe): tipi openrouter, modulo api e provider/key nel settings store"
```

---

## Task 11: FE — store openrouter (catalogo, crediti, preferiti) + spec

**Files:**
- Create: `frontend/src/renderer/src/stores/openrouter.ts`
- Test: `frontend/src/renderer/src/stores/openrouter.spec.ts`

- [ ] **Step 1: Scrivi lo spec che fallisce**

Crea `stores/openrouter.spec.ts`:

```ts
import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { useOpenrouterStore } from './openrouter'
import { useSettingsStore } from './settings'
import type { OpenRouterModel } from '../types/openrouter'

const MODELS: OpenRouterModel[] = [
  {
    id: 'anthropic/claude-sonnet-5',
    name: 'Claude Sonnet 5',
    description: '',
    context_length: 200000,
    pricing: { prompt: 0.000003, completion: 0.000015 },
    supports_tools: true,
    supports_vision: true,
    supports_reasoning: true
  },
  {
    id: 'qwen/qwen3.5-72b',
    name: 'Qwen 3.5 72B',
    description: '',
    context_length: 32768,
    pricing: { prompt: 4e-7, completion: 1.2e-6 },
    supports_tools: true,
    supports_vision: false,
    supports_reasoning: false
  }
]

describe('openrouter store — filtering and favorites', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('filters by search query on id and name', () => {
    const store = useOpenrouterStore()
    store.models = MODELS
    store.searchQuery = 'qwen'
    expect(store.filteredModels.map((m) => m.id)).toEqual(['qwen/qwen3.5-72b'])
  })

  it('filters by capability', () => {
    const store = useOpenrouterStore()
    store.models = MODELS
    store.capabilityFilter = 'vision'
    expect(store.filteredModels.map((m) => m.id)).toEqual(['anthropic/claude-sonnet-5'])
  })

  it('puts favorites first', () => {
    const settings = useSettingsStore()
    settings.settings.llm.openrouterFavorites = ['qwen/qwen3.5-72b']
    const store = useOpenrouterStore()
    store.models = MODELS
    expect(store.filteredModels[0].id).toBe('qwen/qwen3.5-72b')
    expect(store.isFavorite('qwen/qwen3.5-72b')).toBe(true)
  })
})
```

- [ ] **Step 2: Verifica che fallisca**

Run (da `frontend/`): `npx vitest run src/renderer/src/stores/openrouter.spec.ts`
Expected: FAIL (modulo mancante).

- [ ] **Step 3: Implementa lo store**

Crea `stores/openrouter.ts`:

```ts
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { openrouterApi } from '../services/api'
import type { OpenRouterCredits, OpenRouterModel } from '../types/openrouter'
import { useSettingsStore } from './settings'

export type CapabilityFilter = 'all' | 'tools' | 'vision' | 'reasoning'

export const useOpenrouterStore = defineStore('openrouter', () => {
  const settingsStore = useSettingsStore()

  const models = ref<OpenRouterModel[]>([])
  const credits = ref<OpenRouterCredits | null>(null)
  const loadingCatalog = ref(false)
  const loadingCredits = ref(false)
  const error = ref<string | null>(null)

  const searchQuery = ref('')
  const capabilityFilter = ref<CapabilityFilter>('all')

  const favorites = computed(() => settingsStore.settings.llm.openrouterFavorites)

  function isFavorite(id: string): boolean {
    return favorites.value.includes(id)
  }

  const filteredModels = computed<OpenRouterModel[]>(() => {
    const q = searchQuery.value.trim().toLowerCase()
    let list = models.value
    if (q) {
      list = list.filter(
        (m) => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)
      )
    }
    if (capabilityFilter.value !== 'all') {
      const key = `supports_${capabilityFilter.value}` as
        | 'supports_tools'
        | 'supports_vision'
        | 'supports_reasoning'
      list = list.filter((m) => m[key])
    }
    // Preferiti in testa, ordine originale (catalogo) per il resto.
    return [...list].sort(
      (a, b) => Number(isFavorite(b.id)) - Number(isFavorite(a.id))
    )
  })

  async function loadCatalog(force = false): Promise<void> {
    loadingCatalog.value = true
    error.value = null
    try {
      const resp = await openrouterApi.getModels(force)
      models.value = resp.models
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loadingCatalog.value = false
    }
  }

  async function loadCredits(): Promise<void> {
    loadingCredits.value = true
    try {
      credits.value = await openrouterApi.getCredits()
    } catch {
      credits.value = null
    } finally {
      loadingCredits.value = false
    }
  }

  function toggleFavorite(id: string): void {
    const favs = settingsStore.settings.llm.openrouterFavorites
    const idx = favs.indexOf(id)
    if (idx >= 0) favs.splice(idx, 1)
    else favs.push(id)
    // Persistenza: l'autosave (deep watch) del settings store fa il PUT.
  }

  function selectModel(id: string): void {
    settingsStore.settings.llm.openrouterModel = id
  }

  return {
    models,
    credits,
    loadingCatalog,
    loadingCredits,
    error,
    searchQuery,
    capabilityFilter,
    favorites,
    filteredModels,
    isFavorite,
    loadCatalog,
    loadCredits,
    toggleFavorite,
    selectModel
  }
})
```

- [ ] **Step 4: Verifica**

Run: `npx vitest run src/renderer/src/stores/openrouter.spec.ts` → PASS.
Run: `npm run typecheck` → exit 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/stores/openrouter.ts frontend/src/renderer/src/stores/openrouter.spec.ts
git commit -m "feat(fe): store openrouter con catalogo, crediti, filtri e preferiti"
```

---

## Task 12: FE — OpenRouterManager (switcher provider, API key, crediti) + sezione in SettingsView

**Files:**
- Create: `frontend/src/renderer/src/components/settings/OpenRouterManager.vue`
- Modify: `frontend/src/renderer/src/views/SettingsView.vue` (`SectionId`, `navItems` ~riga 287, markup sezione dopo "model")

- [ ] **Step 1: Componente**

Crea `components/settings/OpenRouterManager.vue`. Struttura richiesta (segui l'idioma `settings-section` di `McpManager.vue`; stile SOLO con token del tema — `--surface-*`, `--accent*`, `--border*`, `--text-*`, `--radius-*`, `--space-*`; nessun colore hardcoded):

```vue
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useOpenrouterStore } from '../../stores/openrouter'
import { useSettingsStore } from '../../stores/settings'
import type { LlmProvider } from '../../types/openrouter'
import UiButton from '../ui/UiButton.vue'
import UiInput from '../ui/UiInput.vue'
import UiSegmented from '../ui/UiSegmented.vue'
import OpenRouterCatalog from './OpenRouterCatalog.vue'

const settingsStore = useSettingsStore()
const openrouterStore = useOpenrouterStore()

const apiKeyDraft = ref('')
const savingKey = ref(false)

const provider = computed({
  get: () => settingsStore.settings.llm.provider,
  set: (value: LlmProvider) => {
    settingsStore.settings.llm.provider = value
  }
})

const providerOptions = [
  { label: 'LM Studio', value: 'lmstudio' },
  { label: 'Ollama', value: 'ollama' },
  { label: 'OpenRouter', value: 'openrouter' }
]

const isOpenrouter = computed(() => provider.value === 'openrouter')

async function saveApiKey(): Promise<void> {
  if (!apiKeyDraft.value.trim()) return
  savingKey.value = true
  try {
    await settingsStore.setOpenrouterApiKey(apiKeyDraft.value)
    apiKeyDraft.value = ''
    await openrouterStore.loadCredits()
  } finally {
    savingKey.value = false
  }
}

watch(isOpenrouter, (active) => {
  if (active) {
    void openrouterStore.loadCatalog()
    if (settingsStore.openrouterKeyConfigured) void openrouterStore.loadCredits()
  }
})

onMounted(() => {
  if (isOpenrouter.value) {
    void openrouterStore.loadCatalog()
    if (settingsStore.openrouterKeyConfigured) void openrouterStore.loadCredits()
  }
})

const creditsLabel = computed(() => {
  const c = openrouterStore.credits
  if (!c) return null
  if (c.limit_remaining != null) return `$${c.limit_remaining.toFixed(2)} residui`
  return `$${c.usage.toFixed(2)} usati`
})
</script>

<template>
  <section class="settings-section">
    <h3 class="settings-section__title">Provider LLM</h3>
    <p class="provider-hint">
      LM Studio e Ollama girano in locale; OpenRouter è un provider cloud a
      consumo (richiede API key).
    </p>

    <UiSegmented v-model="provider" :options="providerOptions" />

    <template v-if="isOpenrouter">
      <div class="openrouter-key-row">
        <UiInput
          v-model="apiKeyDraft"
          type="password"
          :placeholder="
            settingsStore.openrouterKeyConfigured
              ? 'API key configurata — incolla per sostituirla'
              : 'sk-or-...'
          "
          autocomplete="off"
        />
        <UiButton :disabled="savingKey || !apiKeyDraft.trim()" @click="saveApiKey">
          Salva chiave
        </UiButton>
      </div>

      <div v-if="creditsLabel" class="openrouter-credits">
        <span class="openrouter-credits__value">{{ creditsLabel }}</span>
        <UiButton size="sm" variant="ghost" @click="openrouterStore.loadCredits()">
          Aggiorna
        </UiButton>
      </div>

      <OpenRouterCatalog />
    </template>
  </section>
</template>

<style scoped>
.provider-hint {
  margin: 0 0 var(--space-4);
  color: var(--text-secondary);
  font-size: var(--text-sm);
}
.openrouter-key-row {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
.openrouter-key-row > :first-child {
  flex: 1;
}
.openrouter-credits {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-top: var(--space-3);
  color: var(--text-primary);
  font-size: var(--text-sm);
}
.openrouter-credits__value {
  font-variant-numeric: tabular-nums;
  color: var(--accent);
}
</style>
```

NOTE per l'esecutore:
- Verifica le prop reali di `UiSegmented`/`UiInput`/`UiButton` leggendo i componenti kit prima di usarle (i nomi `options`/`size`/`variant` vanno adattati all'API effettiva del kit).
- `OpenRouterCatalog.vue` è creato nel Task 13: per far compilare questo task crea PRIMA un file stub minimale `<template><div /></template>` con `<script setup lang="ts"></script>`, che il Task 13 sostituisce.

- [ ] **Step 2: SettingsView wiring**

In `views/SettingsView.vue`:
1. Aggiungi `'provider'` alla union `SectionId` (cerca la definizione del tipo).
2. In `navItems` (riga ~287) aggiungi dopo la voce `model`: `{ id: 'provider', label: 'Provider' }` (adatta la forma reale delle voci esistenti — icona inclusa se prevista).
3. Nel template, dopo la `<section>` del model manager, aggiungi la sezione con lo stesso pattern ref/observer delle altre:

```vue
      <section :ref="(el) => registerSection('provider', el)">
        <OpenRouterManager />
      </section>
```

(adatta il meccanismo di registrazione ref a quello REALE del file — leggi come fa la sezione `model`).
4. Import: `import OpenRouterManager from '../components/settings/OpenRouterManager.vue'`.

- [ ] **Step 3: Verifica**

Run: `npm run typecheck` → exit 0. `npm run lint` → clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/renderer/src/components/settings/OpenRouterManager.vue frontend/src/renderer/src/components/settings/OpenRouterCatalog.vue frontend/src/renderer/src/views/SettingsView.vue
git commit -m "feat(fe): sezione provider nelle impostazioni - switcher, api key, crediti openrouter"
```

---

## Task 13: FE — OpenRouterCatalog (ricerca, filtri, prezzi, pin, selezione)

**Files:**
- Modify: `frontend/src/renderer/src/components/settings/OpenRouterCatalog.vue` (sostituisce lo stub del Task 12)

- [ ] **Step 1: Implementa il catalogo**

Sostituisci lo stub con il componente completo. Direzione estetica (skill frontend-design, dentro il linguaggio Horizon): superficie editoriale — righe di catalogo asciutte separate da hairline (`--border-subtle`), id modello in `--font-mono`, prezzi in cifre tabulari con `--text-muted`, badge capacità come piccoli chip testuali, stella preferito che usa `--accent` solo quando attiva. Nessun card-grid rumoroso: una lista densa e leggibile, coerente col resto dei settings.

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { useOpenrouterStore, type CapabilityFilter } from '../../stores/openrouter'
import { useSettingsStore } from '../../stores/settings'
import AliceSpinner from '../ui/AliceSpinner.vue'
import UiEmptyState from '../ui/UiEmptyState.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiSearchInput from '../ui/UiSearchInput.vue'
import UiSegmented from '../ui/UiSegmented.vue'

const store = useOpenrouterStore()
const settingsStore = useSettingsStore()

const capabilityOptions: { label: string; value: CapabilityFilter }[] = [
  { label: 'Tutti', value: 'all' },
  { label: 'Tools', value: 'tools' },
  { label: 'Vision', value: 'vision' },
  { label: 'Reasoning', value: 'reasoning' }
]

const activeModelId = computed(() => settingsStore.settings.llm.openrouterModel)

function pricePerMtok(perToken: number | null | undefined): string {
  if (perToken == null) return '—'
  return `$${(perToken * 1_000_000).toFixed(2)}`
}

function contextLabel(len: number): string {
  if (!len) return '—'
  return len >= 1000 ? `${Math.round(len / 1000)}k` : String(len)
}
</script>

<template>
  <div class="or-catalog">
    <div class="or-catalog__toolbar">
      <UiSearchInput v-model="store.searchQuery" placeholder="Cerca modello…" />
      <UiSegmented v-model="store.capabilityFilter" :options="capabilityOptions" />
      <UiIconButton
        icon="refresh"
        title="Ricarica catalogo"
        @click="store.loadCatalog(true)"
      />
    </div>

    <div v-if="store.loadingCatalog" class="or-catalog__loading">
      <AliceSpinner /> Caricamento catalogo…
    </div>
    <UiEmptyState
      v-else-if="store.error"
      title="Catalogo non disponibile"
      :description="store.error"
    />
    <UiEmptyState
      v-else-if="store.filteredModels.length === 0"
      title="Nessun modello"
      description="Nessun modello corrisponde ai filtri."
    />

    <ul v-else class="or-catalog__list">
      <li
        v-for="model in store.filteredModels"
        :key="model.id"
        class="or-row"
        :class="{ 'or-row--active': model.id === activeModelId }"
      >
        <button class="or-row__main" type="button" @click="store.selectModel(model.id)">
          <span class="or-row__name">{{ model.name }}</span>
          <span class="or-row__id">{{ model.id }}</span>
          <span class="or-row__caps">
            <span v-if="model.supports_tools" class="or-cap">tools</span>
            <span v-if="model.supports_vision" class="or-cap">vision</span>
            <span v-if="model.supports_reasoning" class="or-cap">reasoning</span>
          </span>
        </button>
        <span class="or-row__meta">
          <span class="or-row__ctx">{{ contextLabel(model.context_length) }} ctx</span>
          <span class="or-row__price">
            {{ pricePerMtok(model.pricing.prompt) }} /
            {{ pricePerMtok(model.pricing.completion) }} Mtok
          </span>
        </span>
        <UiIconButton
          :icon="store.isFavorite(model.id) ? 'star-filled' : 'star'"
          :title="store.isFavorite(model.id) ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti'"
          :class="{ 'or-row__pin--active': store.isFavorite(model.id) }"
          @click="store.toggleFavorite(model.id)"
        />
      </li>
    </ul>
  </div>
</template>

<style scoped>
.or-catalog {
  margin-top: var(--space-5);
}
.or-catalog__toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}
.or-catalog__toolbar > :first-child {
  flex: 1;
}
.or-catalog__loading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-muted);
  padding: var(--space-4) 0;
}
.or-catalog__list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 420px;
  overflow-y: auto;
}
.or-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-1);
  border-bottom: 1px solid var(--border-subtle);
}
.or-row--active {
  background: var(--surface-selected, var(--surface-2));
}
.or-row__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: left;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  color: var(--text-primary);
}
.or-row__name {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
}
.or-row__id {
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.or-row__caps {
  display: flex;
  gap: var(--space-1);
}
.or-cap {
  font-size: var(--text-2xs);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-pill);
  padding: 0 var(--space-2);
}
.or-row__meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-variant-numeric: tabular-nums;
  font-size: var(--text-2xs);
  color: var(--text-muted);
  white-space: nowrap;
}
.or-row__pin--active {
  color: var(--accent);
}
</style>
```

NOTE per l'esecutore:
- I nomi icona (`refresh`, `star`, `star-filled`) vanno verificati contro `assets/icons.ts` / `AppIcon`; usa quelli reali.
- Verifica le prop del kit come nel Task 12.

- [ ] **Step 2: Verifica**

Run: `npm run typecheck && npm run lint` → clean.
Verifica visiva (skill /run o `npm run dev` via preview): apri Impostazioni → Provider, seleziona OpenRouter, controlla catalogo/ricerca/pin in ENTRAMBI i temi (dark e light).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/settings/OpenRouterCatalog.vue
git commit -m "feat(fe): catalogo openrouter editoriale con ricerca, filtri capacita, prezzi e preferiti"
```

---

## Task 14: FE — ModelSelector provider-aware

**Files:**
- Modify: `frontend/src/renderer/src/components/settings/ModelSelector.vue`

- [ ] **Step 1: Implementa**

`ModelSelector.vue` (usato in ChatInput e HorizonCockpit) deve, quando `settingsStore.settings.llm.provider === 'openrouter'` e `modelType === 'llm'`:
- mostrare come etichetta trigger `settingsStore.settings.llm.openrouterModel` (o "Scegli modello" se vuoto);
- nel popover, listare `openrouterStore.filteredModels` (preferiti in testa, ricerca via `openrouterStore.searchQuery` legata alla `UiSearchInput` esistente) invece dei modelli LM Studio;
- al click su un modello: `openrouterStore.selectModel(model.id)` e chiudere il popover;
- caricare il catalogo on-open se vuoto: `if (openrouterStore.models.length === 0) void openrouterStore.loadCatalog()`.

Implementazione: aggiungi in `<script setup>`:

```ts
import { useOpenrouterStore } from '../../stores/openrouter'

const openrouterStore = useOpenrouterStore()
const isOpenrouterProvider = computed(
  () => settingsStore.settings.llm.provider === 'openrouter' && props.modelType === 'llm'
)
```

e nel template un ramo `v-if="isOpenrouterProvider"` per la lista OpenRouter (righe: nome + id mono + stella preferito riusando le classi del selettore esistente), `v-else` per il flusso LM Studio attuale. NON toccare il ramo embedding.

- [ ] **Step 2: Verifica**

Run: `npm run typecheck && npm run lint` → clean. Verifica visiva nel cockpit Horizon con provider openrouter e lmstudio.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/settings/ModelSelector.vue
git commit -m "feat(fe): model selector provider-aware - catalogo openrouter nel selettore rapido"
```

---

## Task 15: FE — costo per conversazione

**Files:**
- Modify: `frontend/src/renderer/src/stores/chat.ts` (nuovo ref `conversationCost` + azioni)
- Modify: `frontend/src/renderer/src/composables/useChat.ts` (handler `turn.finished`)
- Modify: `frontend/src/renderer/src/stores/agentRun.ts` (`applyTurnFinished` salva `cost`)
- Modify: `frontend/src/renderer/src/components/chat/ChatInput.vue` (chip costo accanto a ContextBar)
- Modify: `frontend/src/renderer/src/components/horizon/HorizonCockpit.vue` (idem)
- Test: `frontend/src/renderer/src/stores/chat-cost.spec.ts` (nuovo)

- [ ] **Step 1: Scrivi lo spec che fallisce**

Crea `stores/chat-cost.spec.ts`:

```ts
import { setActivePinia, createPinia } from 'pinia'
import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore } from './chat'

describe('conversation cost accounting', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('accumulates live turn costs on top of the persisted total', () => {
    const store = useChatStore()
    store.setConversationCost(0.01)
    store.addTurnCost(0.002)
    store.addTurnCost(null) // turno senza costo → no-op
    expect(store.conversationCost).toBeCloseTo(0.012)
  })

  it('starts from null and ignores null totals', () => {
    const store = useChatStore()
    expect(store.conversationCost).toBeNull()
    store.addTurnCost(0.005)
    expect(store.conversationCost).toBeCloseTo(0.005)
  })
})
```

- [ ] **Step 2: Verifica che fallisca**

Run: `npx vitest run src/renderer/src/stores/chat-cost.spec.ts` → FAIL.

- [ ] **Step 3: Implementa — chat store**

In `stores/chat.ts`, vicino a `contextInfo` (riga ~160):

```ts
  const conversationCost = ref<number | null>(null)

  function setConversationCost(total: number | null): void {
    conversationCost.value = total
  }

  function addTurnCost(cost: number | null | undefined): void {
    if (cost == null || cost <= 0) return
    conversationCost.value = (conversationCost.value ?? 0) + cost
  }
```

Esporta `conversationCost`, `setConversationCost`, `addTurnCost` dal return. Nel punto in cui il GET conversazione applica `detail.context_info` (riga ~306-317), aggiungi `setConversationCost((detail as { total_cost?: number | null }).total_cost ?? null)` (adatta al tipo reale del detail). Azzera il costo dove si azzera `contextInfo` al cambio conversazione (cerca il reset esistente e affianca `conversationCost.value = null`).

- [ ] **Step 4: Implementa — handler e agentRun**

`composables/useChat.ts`, entry `'turn.finished'` (riga ~298):

```ts
  'turn.finished': (msg) => {
    agentRunStore.applyTurnFinished(msg)
    store.addTurnCost(msg.cost ?? null)
  },
```

`stores/agentRun.ts`, in `applyTurnFinished` aggiungi `run.cost = msg.cost ?? null` e il membro `cost: number | null` all'interfaccia del run (segui la forma esistente dei campi).

- [ ] **Step 5: Implementa — UI**

In `ChatInput.vue`, accanto a `<ContextBar …>` (riga ~251):

```vue
      <span
        v-if="chatStore.conversationCost != null"
        class="conversation-cost"
        title="Costo della conversazione (crediti OpenRouter)"
      >
        ${{ chatStore.conversationCost.toFixed(4) }}
      </span>
```

con stile scoped:

```css
.conversation-cost {
  font-size: var(--text-2xs);
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
}
```

Stessa aggiunta in `HorizonCockpit.vue` accanto alla sua ContextBar (riga ~114), adattata alle classi del cockpit.

- [ ] **Step 6: Verifica**

Run: `npx vitest run src/renderer/src` → PASS. `npm run typecheck && npm run lint` → clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/renderer/src/stores/chat.ts frontend/src/renderer/src/stores/chat-cost.spec.ts frontend/src/renderer/src/stores/agentRun.ts frontend/src/renderer/src/composables/useChat.ts frontend/src/renderer/src/components/chat/ChatInput.vue frontend/src/renderer/src/components/horizon/HorizonCockpit.vue
git commit -m "feat(fe): costo conversazione live da turn.finished e totale persistito dal backend"
```

---

## Task 16: Docs — identità di prodotto + verifica finale

**Files:**
- Modify: `CLAUDE.md` (sezione "What this is")
- Modify: `README.md` (se descrive il posizionamento "100% local")

- [ ] **Step 1: Aggiorna l'identità**

In `CLAUDE.md`, sezione "What this is", cambia la prima frase in:

> **AL\CE** (a.k.a. *Omnia*) — a local-first personal AI assistant. Everything (LLM, STT, TTS, vector store, 3D generation) runs on the user's machine by default; **OpenRouter** is supported as an optional cloud LLM provider of equal rank (API key required, per-token billing). Memory/embeddings stay strictly local regardless of provider. **Windows is the primary target.**

Aggiorna `README.md` in modo coerente se contiene il claim "100% local" (verifica prima).

- [ ] **Step 2: Gate completi backend**

Da repo root (venv attivo):

```powershell
cd backend; pytest tests/ -v          # Expected: tutti PASS
ruff check .                           # Expected: clean
ruff format --check .                  # Expected: clean
mypy .                                 # Expected: clean
cd ..; lint-imports --config backend/pyproject.toml   # Expected: Contracts: N kept, 0 broken
.\scripts\check-contracts.ps1          # Expected: exit 0
```

- [ ] **Step 3: Gate completi frontend**

```powershell
cd frontend
npx vitest run
npm run typecheck
npm run lint
```

Expected: tutti clean.

- [ ] **Step 4: Verifica end-to-end**

Usa la skill `verify` (o `/run`): avvia backend + frontend, poi:
1. Impostazioni → Provider → OpenRouter, inserisci una API key reale, verifica crediti visibili.
2. Catalogo: ricerca, filtro vision, pin di un preferito, selezione modello.
3. Manda un messaggio in chat: risposta in streaming, chip costo che appare accanto alla ContextBar.
4. Ricarica la conversazione: `total_cost` persiste.
5. Torna a LM Studio: la chat locale funziona come prima, il modello locale è preservato.
6. Con provider OpenRouter, verifica nei log che la memoria usi fastembed (nessuna chiamata embeddings verso openrouter.ai).

- [ ] **Step 5: Commit finale**

```bash
git add CLAUDE.md README.md
git commit -m "docs: identita local-first con provider cloud openrouter di pari rango"
```

---

## Self-review (eseguita in fase di stesura)

- **Copertura spec:** §SDK (decisione, nessun task — è architetturale) ✓; §1 backend provider/streaming → Task 1-2; capacità auto-derivate → Task 5; guardia embedding → Task 8; §2 catalogo/crediti/preferiti → Task 5-7, 10-13; §3 costo → Task 3-4, 15; §4 UX paritaria → Task 12-15; §5 sicurezza chiave → Task 7 (masking, "***" guard); §6 test e gate → in ogni task + Task 16.
- **Tipi coerenti:** `TurnProgress.cost`/`TurnResult.cost` (float), frame `cost: float | None`, FE `cost?: number | null` via codegen; `openrouter_model` usato ovunque (mai `model` per il ramo cloud).
- **Punti che l'esecutore DEVE verificare sul codice reale (dichiarati, non placeholder):** prop del kit UI (Task 12-13), nomi icona (Task 13), meccanismo di registrazione sezioni in SettingsView (Task 12), firma property `dimensions` di FastEmbedClient (Task 8), presenza import esistenti nei file di test estesi.
