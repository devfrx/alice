# Settings Core Rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Una sola fonte di verità per la config (layer `preferences` formale nel `LayeredConfigService`), un solo percorso di scrittura (PUT/PATCH sullo stesso motore), tutti i segreti nel keyring di Windows via `SecretStore` — mai su disco in chiaro.

**Architecture:** Cinque layer (`defaults < system < user < preferences < runtime`); il layer `preferences` è persistito nella tabella `user_preferences` esistente. I sei segreti diventano `SecretStr`, vivono nel Credential Manager e vengono idratati nella resolved config a ogni rebuild da una cache in-memory. La PUT `/api/config` mantiene il contratto esterno ma internamente partiziona il body (segreti → SecretStore; preferenze → `set_many`; sconosciuti → 400) e delega i side-effect a un registry dichiarativo di reazioni.

**Tech Stack:** Python 3.11+/FastAPI/pydantic-settings v2, `keyring` (WinVaultKeyring), SQLModel/aiosqlite, Vue 3/Pinia/vitest.

**Spec:** `docs/superpowers/specs/2026-07-16-settings-core-rework-design.md`

## Global Constraints

- **Prerequisito:** `feat/openrouter-provider` mergiato in `main` (task 16 del suo piano chiuso). Branch di lavoro: `rework/settings-core` da `main`. Primo commit del branch: lo spec + questo piano.
- Convenzioni repo: type hints ovunque, `async def` per I/O, `loguru.logger`, `pathlib.Path`, `httpx`, docstring Google, line length 100, mypy strict, niente `any` nel FE.
- Ogni endpoint nuovo/modificato dichiara `response_model` (ratchet in `backend/tests/contracts/`); ogni modifica ai contratti richiede `.\scripts\gen-contracts.ps1` e MAI editare a mano `frontend/src/renderer/src/types/generated/` (tranne `index.ts`).
- Import-linter: plugins indipendenti, api ↛ plugins, services ↛ api, core ↛ services. Il registry reazioni sta in `api/` perché chiama helper di route; `config_policy`/`secret_store` stanno in `services/`.
- Frame WS `config.changed` invariato: `{type, path, value|"***", layer}` (vocabolario congelato, test in `backend/tests/contracts/`).
- Semantica scrittura segreti (uniforme, sei path): stringa non vuota ≠ `"***"` → set; `""` o `"***"` → no-op; `null` → delete. Path segreti: `llm.api_token`, `llm.openrouter_api_key`, `home_assistant.token`, `mqtt.password`, `continuum.api_token`, `email.password`.
- Test backend dal folder `backend/`: `pytest tests/<file> -v` (MAI la suite intera in foreground: 15–20+ min).
- Gotcha noti (handoff OpenRouter): header/flag provider fissati alla costruzione ⇒ ogni cambio passa dal rebuild di `LLMService`; un Edit su file LF può produrre CRLF — controllare il diff prima di committare.

---

## Fase F1 — SecretStore e segreti

### Task 1: SecretStore (protocol + backend in-memory + keyring)

**Files:**
- Create: `backend/services/secret_store.py`
- Modify: `backend/core/protocols.py` (aggiungi `SecretStoreProtocol` accanto agli altri protocol di servizio)
- Test: `backend/tests/test_secret_store.py`

**Interfaces:**
- Produces: `SecretStoreProtocol` con `async get(name) -> str | None`, `async set(name, value) -> None`, `async delete(name) -> None`, `async load_cache() -> dict[str, str]`, `cached() -> dict[str, str]` (sincrono, copia della cache). `InMemorySecretStore(initial: dict[str, str] | None = None)`, `KeyringSecretStore()`, factory `create_secret_store(prefer_memory: bool = False) -> SecretStoreProtocol`.
- Consumes: `SECRET_PATHS` da Task 2 (per `KeyringSecretStore.load_cache`) — Task 1 e 2 si committano insieme se preferisci un ordine strettamente verde; in alternativa esegui prima Task 2.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_secret_store.py
"""Tests for the SecretStore backends."""

from __future__ import annotations

import pytest

from backend.services.secret_store import (
    InMemorySecretStore,
    KeyringSecretStore,
    create_secret_store,
)


@pytest.mark.asyncio
async def test_inmemory_roundtrip() -> None:
    store = InMemorySecretStore()
    assert await store.get("llm.openrouter_api_key") is None
    await store.set("llm.openrouter_api_key", "sk-or-abc")
    assert await store.get("llm.openrouter_api_key") == "sk-or-abc"
    assert store.cached() == {"llm.openrouter_api_key": "sk-or-abc"}
    await store.delete("llm.openrouter_api_key")
    assert await store.get("llm.openrouter_api_key") is None
    assert store.cached() == {}


@pytest.mark.asyncio
async def test_inmemory_load_cache_returns_copy() -> None:
    store = InMemorySecretStore({"email.password": "pw"})
    cache = await store.load_cache()
    assert cache == {"email.password": "pw"}
    cache["email.password"] = "tampered"
    assert store.cached() == {"email.password": "pw"}


@pytest.mark.asyncio
async def test_keyring_store_uses_service_alice(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, tuple[str, ...]] = {}

    class FakeKeyring:
        @staticmethod
        def get_password(service: str, name: str) -> str | None:
            calls["get"] = (service, name)
            return "stored-value"

        @staticmethod
        def set_password(service: str, name: str, value: str) -> None:
            calls["set"] = (service, name, value)

        @staticmethod
        def delete_password(service: str, name: str) -> None:
            calls["delete"] = (service, name)

    store = KeyringSecretStore(keyring_module=FakeKeyring())
    await store.set("mqtt.password", "hunter2")
    assert calls["set"] == ("alice", "mqtt.password", "hunter2")
    assert store.cached()["mqtt.password"] == "hunter2"
    await store.delete("mqtt.password")
    assert calls["delete"] == ("alice", "mqtt.password")
    assert "mqtt.password" not in store.cached()


@pytest.mark.asyncio
async def test_keyring_load_cache_scans_secret_paths() -> None:
    class FakeKeyring:
        @staticmethod
        def get_password(service: str, name: str) -> str | None:
            return "tok" if name == "llm.api_token" else None

    store = KeyringSecretStore(keyring_module=FakeKeyring())
    cache = await store.load_cache()
    assert cache == {"llm.api_token": "tok"}


def test_factory_prefer_memory() -> None:
    store = create_secret_store(prefer_memory=True)
    assert isinstance(store, InMemorySecretStore)
```

- [ ] **Step 2: Run tests to verify they fail**

Run (da `backend/`): `pytest tests/test_secret_store.py -v`
Expected: FAIL / errore di import (`backend.services.secret_store` non esiste).

- [ ] **Step 3: Implement `secret_store.py`**

```python
# backend/services/secret_store.py
"""AL\\CE — Secret storage backed by the OS keyring.

Secrets NEVER live in config layers (YAML/DB): they are written to the
Windows Credential Manager (service ``alice``, credential name = dotted
config path, e.g. ``llm.openrouter_api_key``) and hydrated into the
resolved config from an in-memory cache (see LayeredConfigService).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from loguru import logger

from backend.services.config_policy import SECRET_PATHS

_SERVICE_NAME = "alice"


class InMemorySecretStore:
    """Volatile secret store for tests and keyring-less fallback."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self._data: dict[str, str] = dict(initial or {})

    async def get(self, name: str) -> str | None:
        return self._data.get(name)

    async def set(self, name: str, value: str) -> None:
        self._data[name] = value

    async def delete(self, name: str) -> None:
        self._data.pop(name, None)

    async def load_cache(self) -> dict[str, str]:
        return dict(self._data)

    def cached(self) -> dict[str, str]:
        return dict(self._data)


class KeyringSecretStore:
    """Keyring-backed store with a synchronous read cache.

    The cache is loaded once at bootstrap (``load_cache``) and kept in
    sync on every ``set``/``delete`` — reads never hit the keyring on
    the hot path (config rebuild is synchronous).
    """

    def __init__(self, keyring_module: Any | None = None) -> None:
        if keyring_module is None:
            import keyring as keyring_module  # noqa: PLC0415 — optional dep

            if os.name == "nt":
                # Pin the backend explicitly: entry_points discovery is
                # fragile under PyInstaller.
                from keyring.backends.Windows import WinVaultKeyring

                keyring_module.set_keyring(WinVaultKeyring())
        self._keyring = keyring_module
        self._cache: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self._cache.get(name)

    async def set(self, name: str, value: str) -> None:
        await asyncio.to_thread(
            self._keyring.set_password, _SERVICE_NAME, name, value,
        )
        self._cache[name] = value

    async def delete(self, name: str) -> None:
        try:
            await asyncio.to_thread(
                self._keyring.delete_password, _SERVICE_NAME, name,
            )
        except Exception as exc:  # noqa: BLE001 — missing credential is fine
            logger.debug("Keyring delete for '{}' raised: {}", name, exc)
        self._cache.pop(name, None)

    async def load_cache(self) -> dict[str, str]:
        cache: dict[str, str] = {}
        for path in sorted(SECRET_PATHS):
            value = await asyncio.to_thread(
                self._keyring.get_password, _SERVICE_NAME, path,
            )
            if value:
                cache[path] = value
        self._cache = cache
        return dict(cache)

    def cached(self) -> dict[str, str]:
        return dict(self._cache)


def create_secret_store(prefer_memory: bool = False):
    """Build the production store, falling back to in-memory.

    Args:
        prefer_memory: Force the volatile backend (test lifespans).
    """
    if prefer_memory:
        return InMemorySecretStore()
    try:
        return KeyringSecretStore()
    except Exception as exc:  # noqa: BLE001 — keyring missing/broken
        logger.warning(
            "Keyring unavailable ({}) — secrets will NOT survive restarts",
            exc,
        )
        return InMemorySecretStore()
```

- [ ] **Step 4: Add `SecretStoreProtocol` to `backend/core/protocols.py`**

Accanto agli altri protocol (stesso stile `Protocol` runtime-checkable del file):

```python
class SecretStoreProtocol(Protocol):
    """OS-keyring-backed secret storage with a synchronous read cache."""

    async def get(self, name: str) -> str | None: ...

    async def set(self, name: str, value: str) -> None: ...

    async def delete(self, name: str) -> None: ...

    async def load_cache(self) -> dict[str, str]: ...

    def cached(self) -> dict[str, str]: ...
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_secret_store.py -v` → Expected: 5 passed (dopo che Task 2 fornisce `config_policy`; se esegui T1 prima di T2, i test falliranno sull'import: esegui T2 e rilancia).

- [ ] **Step 6: Lint/type-check e commit**

```powershell
ruff check backend/services/secret_store.py backend/core/protocols.py backend/tests/test_secret_store.py
mypy backend/services/secret_store.py
git add backend/services/secret_store.py backend/core/protocols.py backend/tests/test_secret_store.py
git commit -m "feat(secrets): SecretStore con backend keyring (WinVault pinned) e in-memory"
```

---

### Task 2: config_policy — censimento segreti e policy di scrivibilità

**Files:**
- Create: `backend/services/config_policy.py`
- Test: `backend/tests/test_config_policy.py`

**Interfaces:**
- Produces: `SECRET_PATHS: frozenset[str]`, `is_secret_path(path: str) -> bool`, `is_preference_writable(path: str) -> bool`, `PREFERENCE_EXACT_PATHS: frozenset[str]`, `PREFERENCE_PREFIXES: tuple[str, ...]`.
- Consumed by: Task 1 (`load_cache`), Task 7/9 (guardie nel config service e partizione PUT), Task 6 (migrazione).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_config_policy.py
"""Tests for the config writability/secret policy."""

from __future__ import annotations

from backend.services.config_policy import (
    SECRET_PATHS,
    is_preference_writable,
    is_secret_path,
)


def test_secret_paths_census_is_closed() -> None:
    assert SECRET_PATHS == frozenset({
        "llm.api_token",
        "llm.openrouter_api_key",
        "home_assistant.token",
        "mqtt.password",
        "continuum.api_token",
        "email.password",
    })


def test_secret_paths_are_never_preference_writable() -> None:
    for path in SECRET_PATHS:
        assert is_secret_path(path)
        assert not is_preference_writable(path)


def test_known_preference_paths_are_writable() -> None:
    for path in (
        "tts.engine", "stt.model", "voice.wake_word", "ui.theme",
        "email.username", "email.imap_port", "agent.prompts.persona",
        "permissions.confirmations_enabled", "llm.provider",
        "llm.openrouter_model", "llm.openrouter_favorites",
        "llm.temperature", "llm.max_tokens", "llm.model",
        "llm.supports_thinking", "llm.supports_vision",
        "llm.user_preferred_name", "llm.disabled_tools",
        "llm.tools_enabled", "llm.system_prompt_enabled",
        "llm.max_tool_iterations", "llm.context_compression_enabled",
        "llm.context_compression_threshold",
        "llm.context_compression_reserve",
        "llm.tool_rag_enabled", "llm.tool_rag_top_k",
    ):
        assert is_preference_writable(path), path


def test_out_of_policy_paths_are_rejected() -> None:
    for path in (
        "server.port",            # non è una preferenza utente
        "llm.base_url",           # infrastruttura, layer user/system
        "email.use_keyring",      # campo eliminato
        "database.url",
        "bogus.section",
    ):
        assert not is_preference_writable(path), path
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config_policy.py -v` → Expected: FAIL (modulo inesistente).

- [ ] **Step 3: Implement `config_policy.py`**

```python
# backend/services/config_policy.py
"""AL\\CE — Config writability policy and secret-path census.

Single registry for (a) which dotted paths the UI may persist into the
``preferences`` layer and (b) which paths are secrets (keyring-only,
never in any layer). Successor of the old ``PERSISTABLE_SECTIONS`` /
``PERSISTABLE_LLM_KEYS`` / ``SENSITIVE_PREFERENCE_KEYS`` allowlists.
"""

from __future__ import annotations

SECRET_PATHS: frozenset[str] = frozenset({
    "llm.api_token",
    "llm.openrouter_api_key",
    "home_assistant.token",
    "mqtt.password",
    "continuum.api_token",
    "email.password",
})

# Sections whose every (non-secret) key is a user preference.
PREFERENCE_PREFIXES: tuple[str, ...] = (
    "tts.", "stt.", "voice.", "ui.", "plugins.", "web_search.",
    "calendar.", "weather.", "clipboard.", "notifications.",
    "media_control.", "file_search.", "news.", "agent.",
)

# Individual preference keys in sections that are NOT wholly writable.
PREFERENCE_EXACT_PATHS: frozenset[str] = frozenset({
    "permissions.confirmations_enabled",
    "llm.system_prompt_enabled",
    "llm.tools_enabled",
    "llm.max_tool_iterations",
    "llm.context_compression_enabled",
    "llm.context_compression_threshold",
    "llm.context_compression_reserve",
    "llm.tool_rag_enabled",
    "llm.tool_rag_top_k",
    "llm.disabled_tools",
    "llm.user_preferred_name",
    "llm.provider",
    "llm.model",
    "llm.temperature",
    "llm.max_tokens",
    "llm.supports_thinking",
    "llm.supports_vision",
    "llm.openrouter_model",
    "llm.openrouter_favorites",
    "email.enabled",
    "email.imap_host",
    "email.imap_port",
    "email.imap_ssl",
    "email.smtp_host",
    "email.smtp_port",
    "email.smtp_ssl",
    "email.username",
    "email.fetch_last_n",
    "email.max_fetch",
    "email.imap_idle_enabled",
    "email.archive_folder",
})


def is_secret_path(path: str) -> bool:
    """Return whether ``path`` designates a keyring-only secret."""
    return path in SECRET_PATHS


def is_preference_writable(path: str) -> bool:
    """Return whether the UI may persist ``path`` in the preferences layer."""
    if is_secret_path(path):
        return False
    if path in PREFERENCE_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PREFERENCE_PREFIXES)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_config_policy.py tests/test_secret_store.py -v` → Expected: tutti passed (T1 incluso, ora che l'import esiste).

- [ ] **Step 5: Commit**

```powershell
git add backend/services/config_policy.py backend/tests/test_config_policy.py
git commit -m "feat(config): policy unica di scrivibilita' preferences + censimento path segreti"
```

---

### Task 3: SecretStr sui sei campi + consumer aggiornati

**Files:**
- Modify: `backend/core/config.py` (righe ~124, ~186, ~326, ~337, ~699 — `email.password` a 813 è già `SecretStr`)
- Modify: `backend/services/llm_service.py:54-56`
- Modify: `backend/services/openrouter_service.py:54-57`
- Modify: `backend/core/bootstrap/inference.py:53`
- Modify: `backend/core/bootstrap/knowledge.py:90`
- Modify: `backend/api/routes/config.py` (riga ~277 flag configured; riga ~509 assegnazione key)
- Modify: `backend/tests/test_openrouter_config.py` (asserzioni `== "sk-..."` → `.get_secret_value()`), altri test che confrontano i campi (cerca con `grep -rn "openrouter_api_key" backend/tests/`)
- Test: `backend/tests/test_config.py` (aggiunta)

**Interfaces:**
- Produces: i sei campi tipati `SecretStr` (`continuum.api_token: SecretStr | None`); ogni consumer usa `.get_secret_value()`.

- [ ] **Step 1: Write the failing test**

```python
# aggiunta a backend/tests/test_config.py
from pydantic import SecretStr

from backend.core.config import AliceConfig


def test_secret_fields_are_secretstr_and_redacted_in_dump() -> None:
    cfg = AliceConfig(
        llm={"api_token": "tok", "openrouter_api_key": "sk-or-x"},
        home_assistant={"token": "ha"},
        mqtt={"password": "mq"},
        continuum={"api_token": "ct"},
        email={"password": "pw"},
    )
    assert isinstance(cfg.llm.api_token, SecretStr)
    assert cfg.llm.openrouter_api_key.get_secret_value() == "sk-or-x"
    assert cfg.continuum.api_token is not None
    assert cfg.continuum.api_token.get_secret_value() == "ct"
    dumped = cfg.model_dump(mode="json")
    assert "sk-or-x" not in str(dumped)
    assert "pw" not in str(dumped)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config.py -v -k secret_fields` → Expected: FAIL (`isinstance` su `str`).

- [ ] **Step 3: Change the field types in `core/config.py`**

```python
# LLMConfig
api_token: SecretStr = Field(default=SecretStr(""))
"""LM Studio API authentication token (optional)."""
...
openrouter_api_key: SecretStr = Field(default=SecretStr(""))
"""OpenRouter API key (Bearer). Empty = not configured."""

# HomeAssistantConfig
token: SecretStr = Field(default=SecretStr(""))

# MQTTConfig
password: SecretStr = Field(default=SecretStr(""))

# ContinuumConfig
api_token: SecretStr | None = None
"""Bearer token sent on every request; ``None`` for token-less servers."""
```

- [ ] **Step 4: Update the consumers**

`backend/services/llm_service.py:54-56`:
```python
api_key = config.openrouter_api_key.get_secret_value()
if config.provider == "openrouter" and api_key:
    headers = {
        "Authorization": f"Bearer {api_key}",
        ...
```

`backend/services/openrouter_service.py:54-57` (stesso pattern: leggi `self._config.openrouter_api_key.get_secret_value()` in una variabile locale, usala per il check "not configured" e per l'header).

`backend/core/bootstrap/inference.py:53`:
```python
api_token=config.llm.api_token.get_secret_value(),
```

`backend/core/bootstrap/knowledge.py:90`:
```python
api_token=(
    config.continuum.api_token.get_secret_value()
    if config.continuum.api_token
    else None
),
```

`backend/api/routes/config.py`:
- riga ~277: `"openrouter_api_key_configured": bool(cfg.llm.openrouter_api_key.get_secret_value()),`
- riga ~509: `object.__setattr__(cfg.llm, "openrouter_api_key", SecretStr(raw_key))` (ponte temporaneo: muore nel Task 5).

- [ ] **Step 5: Update the tests that compare raw values**

In `backend/tests/test_openrouter_config.py` (righe 87, 93, 129): `ctx.config.llm.openrouter_api_key.get_secret_value() == "sk-or-real-secret"`. Cerca altri confronti: `grep -rn "openrouter_api_key\|api_token" backend/tests/` e adegua allo stesso pattern.

- [ ] **Step 6: Run the touched suites + mypy**

```powershell
pytest tests/test_config.py tests/test_openrouter_config.py tests/test_llm_openrouter.py tests/test_openrouter_service.py -v
mypy backend/core/config.py backend/services/llm_service.py backend/services/openrouter_service.py
```
Expected: passed; mypy segnala ogni call-site dimenticato (`str` vs `SecretStr`) — correggili tutti.

- [ ] **Step 7: Commit**

```powershell
git add -A backend
git commit -m "refactor(secrets): i sei segreti di config diventano SecretStr, consumer su get_secret_value()"
```

---

### Task 4: Idratazione segreti nel LayeredConfigService + wiring bootstrap

**Files:**
- Modify: `backend/services/config_service.py` (`__init__`, `_rebuild`, nuovo `rebuild()`)
- Modify: `backend/core/bootstrap/platform.py` (crea SecretStore prima del config service)
- Modify: `backend/core/context.py` + `backend/core/service_groups.py` (campo `secret_store` nel gruppo platform)
- Modify: `backend/core/app.py` (passa `testing` a `stage_platform` — già avviene — e verifica che il fixture di test usi il backend in-memory)
- Test: `backend/tests/test_config_service.py` (aggiunte)

**Interfaces:**
- Produces: `LayeredConfigService(event_bus=..., secrets_provider: Callable[[], dict[str, str]] | None = None)`; `async rebuild() -> AliceConfig` (rilocka e rigenera la resolved, per uso post-scrittura segreti); `ctx.secret_store: SecretStoreProtocol`.

- [ ] **Step 1: Write the failing tests**

```python
# aggiunta a backend/tests/test_config_service.py
import pytest

from backend.services.config_service import LayeredConfigService


def test_rebuild_hydrates_secrets_from_provider(tmp_path) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "missing.yaml",
        system_path=tmp_path / "system.yaml",
        user_path=tmp_path / "user.yaml",
        secrets_provider=lambda: {"llm.openrouter_api_key": "sk-or-hydrated"},
    )
    resolved = svc.get_resolved()
    assert resolved.llm.openrouter_api_key.get_secret_value() == "sk-or-hydrated"


@pytest.mark.asyncio
async def test_rebuild_method_picks_up_new_secrets(tmp_path) -> None:
    secrets: dict[str, str] = {}
    svc = LayeredConfigService(
        defaults_path=tmp_path / "missing.yaml",
        system_path=tmp_path / "system.yaml",
        user_path=tmp_path / "user.yaml",
        secrets_provider=lambda: dict(secrets),
    )
    assert svc.get_resolved().llm.api_token.get_secret_value() == ""
    secrets["llm.api_token"] = "tok-live"
    resolved = await svc.rebuild()
    assert resolved.llm.api_token.get_secret_value() == "tok-live"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config_service.py -v -k "hydrat or rebuild_method"` → Expected: FAIL (`unexpected keyword argument 'secrets_provider'`).

- [ ] **Step 3: Implement in `config_service.py`**

`__init__` — nuovo parametro e attributo (dopo `self._user_path`):
```python
from collections.abc import Callable

def __init__(
    self,
    event_bus: EventBus | None = None,
    defaults_path: Path | None = None,
    system_path: Path | None = None,
    user_path: Path | None = None,
    secrets_provider: Callable[[], dict[str, str]] | None = None,
) -> None:
    ...
    self._secrets_provider = secrets_provider
```

`_rebuild` — idrata DOPO il merge, PRIMA della validazione (le env var `ALICE_*` vincono comunque via `settings_customise_sources`):
```python
def _rebuild(self) -> None:
    merged = self._merged_dict()
    if self._secrets_provider is not None:
        for path, value in self._secrets_provider().items():
            _set_dotted(merged, path, value)
    self._resolved = AliceConfig(**merged)
```

Nuovo metodo pubblico (sotto `reset_runtime`):
```python
async def rebuild(self) -> AliceConfig:
    """Re-validate the merged config (e.g. after a secret write)."""
    async with self._lock:
        self._rebuild()
        assert self._resolved is not None
        return self._resolved
```

- [ ] **Step 4: Wire in `bootstrap/platform.py`**

Sostituisci il blocco "Layered configuration service" (righe 41-46) con:

```python
from backend.services.config_service import LayeredConfigService
from backend.services.secret_store import create_secret_store

secret_store = create_secret_store(prefer_memory=testing)
if not testing:
    try:
        await secret_store.load_cache()
    except Exception as exc:  # noqa: BLE001 — keyring failure must not kill boot
        logger.warning("Secret cache load failed: {}", exc)
ctx.secret_store = secret_store

config_service = LayeredConfigService(
    event_bus=ctx.event_bus,
    secrets_provider=secret_store.cached,
)
ctx.config_service = config_service
ctx.config = config_service.get_resolved()
config = ctx.config  # keep local alias in sync for the rest of this stage
```

In `core/service_groups.py` aggiungi `secret_store: SecretStoreProtocol | None = None` al gruppo `platform` e in `core/context.py` la delegating property `secret_store` (stesso pattern degli altri campi del gruppo — copia lo stile di `config_service`).

- [ ] **Step 5: Run tests**

```powershell
pytest tests/test_config_service.py tests/test_app.py -v
```
Expected: passed (il lifespan di test usa `prefer_memory=True`, nessun accesso al keyring).

- [ ] **Step 6: Commit**

```powershell
git add -A backend
git commit -m "feat(config): idratazione segreti nel rebuild via SecretStore (cache sincrona)"
```

---

### Task 5: PUT /config scrive i segreti nel SecretStore; use_keyring eliminato

**Files:**
- Modify: `backend/api/routes/config.py` (branch `openrouter_api_key` ~502-515, blocco email password ~725-732, `_store_email_password` e `_email_password_configured` MUOIONO, GET /config email block ~314-330, `old_email` snapshot ~370-384)
- Modify: `backend/core/config.py` (`EmailConfig`: rimuovi `use_keyring`; `migrate_legacy_config_keys`: droppa `email.use_keyring`)
- Modify: `backend/services/email_service.py` (righe 63-96, 463-487: `_resolve_password` MUORE)
- Modify: `frontend` NO (F3)
- Test: `backend/tests/test_openrouter_config.py` (aggiunte), `backend/tests/test_config.py` (email)

**Interfaces:**
- Produces: helper `async _apply_secret_updates(ctx, updates: dict[str, Any]) -> set[str]` in `api/routes/config.py` — applica la semantica set/mask/empty/null per QUALSIASI path segreto, aggiorna la cache, fa `await ctx.config_service.rebuild()` e riallinea `ctx.config`; ritorna i path cambiati. Riusato dal Task 11 (PUT riscritta).

- [ ] **Step 1: Write the failing tests**

```python
# aggiunte a backend/tests/test_openrouter_config.py (classe TestProviderSwitch)
async def test_api_key_lands_in_secret_store_not_in_db(self, client, app) -> None:
    ctx = app.state.context
    resp = await client.put(
        "/api/config",
        json={"llm": {"openrouter_api_key": "sk-or-secret-store"}},
    )
    assert resp.status_code == 200
    assert ctx.secret_store.cached()["llm.openrouter_api_key"] == "sk-or-secret-store"
    assert ctx.config.llm.openrouter_api_key.get_secret_value() == "sk-or-secret-store"
    prefs = await ctx.preferences_service.load_all()
    assert "openrouter_api_key" not in prefs.get("llm", {})

async def test_null_api_key_deletes_secret(self, client, app) -> None:
    ctx = app.state.context
    await client.put(
        "/api/config", json={"llm": {"openrouter_api_key": "sk-or-todelete"}},
    )
    resp = await client.put(
        "/api/config", json={"llm": {"openrouter_api_key": None}},
    )
    assert resp.status_code == 200
    assert "llm.openrouter_api_key" not in ctx.secret_store.cached()
    assert ctx.config.llm.openrouter_api_key.get_secret_value() == ""
    assert resp.json()["llm"]["openrouter_api_key_configured"] is False
```

```python
# aggiunta a backend/tests/test_config.py
import pytest


@pytest.mark.asyncio
async def test_email_password_lands_in_secret_store(client, app) -> None:
    ctx = app.state.context
    resp = await client.put(
        "/api/config",
        json={"email": {"username": "u@example.com", "password": "s3cret"}},
    )
    assert resp.status_code == 200
    assert ctx.secret_store.cached()["email.password"] == "s3cret"
    assert resp.json()["email"]["password_configured"] is True
    assert "use_keyring" not in resp.json()["email"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_openrouter_config.py tests/test_config.py -v -k "secret_store or null_api_key or email_password_lands"`
Expected: FAIL (la key finisce ancora nelle prefs DB; `use_keyring` ancora nella risposta).

- [ ] **Step 3: Implement `_apply_secret_updates` in `api/routes/config.py`**

```python
from backend.services.config_policy import is_secret_path  # in testa al file

_SECRET_MAX_LEN = 512


async def _apply_secret_updates(
    ctx: AppContext, updates: dict[str, Any],
) -> set[str]:
    """Apply secret writes (keyring semantics) and rehydrate the config.

    Semantics per path: non-empty string != "***" -> set; "" or "***"
    -> no-op; None -> delete. Returns the set of changed dotted paths.
    """
    changed: set[str] = set()
    for path, raw in updates.items():
        if raw is None:
            if ctx.secret_store.cached().get(path):
                await ctx.secret_store.delete(path)
                changed.add(path)
            continue
        value = str(raw).strip()
        if not value or value == "***":
            continue
        if len(value) > _SECRET_MAX_LEN:
            raise HTTPException(400, f"{path} max {_SECRET_MAX_LEN} chars")
        if value != ctx.secret_store.cached().get(path):
            await ctx.secret_store.set(path, value)
            changed.add(path)
    if changed and ctx.config_service is not None:
        ctx.config = await ctx.config_service.rebuild()
    return changed
```

- [ ] **Step 4: Rewire the two secret branches in the PUT handler**

Branch OpenRouter (righe ~502-515) diventa:
```python
if "openrouter_api_key" in llm_updates:
    changed = await _apply_secret_updates(
        ctx, {"llm.openrouter_api_key": llm_updates.pop("openrouter_api_key")},
    )
    if changed:
        llm_service_rebuild_needed = True
```
(nota: `pop` SEMPRE — il valore non deve mai raggiungere `persist_from_update`.)

Blocco email password (righe ~725-732) diventa (il `pop` è obbligatorio: il valore non deve MAI raggiungere `persist_from_update`; passare `""` all'helper è un no-op per costruzione):
```python
email_password_changed = bool(
    await _apply_secret_updates(
        ctx, {"email.password": email_updates.pop("password", "")},
    )
)
```

Elimina: `_store_email_password`, `_email_password_configured` (e i loro import `asyncio`/`SecretStr` se restano orfani). In `GET /config`: `"password_configured": bool(cfg.email.password.get_secret_value())`, rimuovi `"use_keyring"` e la chiamata a `_email_password_configured`. In `old_email` (righe ~370-384) rimuovi la voce `"use_keyring"`. Rimuovi il loop bool `use_keyring` a riga ~695.

- [ ] **Step 5: Remove `use_keyring` from `EmailConfig` and `EmailService`**

`core/config.py` — `EmailConfig`: elimina la riga `use_keyring: bool = True`. In `migrate_legacy_config_keys` aggiungi (stile del resto della funzione):
```python
email_block = data.get("email")
if isinstance(email_block, dict):
    email_block.pop("use_keyring", None)
```

`services/email_service.py`: elimina `_resolve_password` (463-487) e sostituisci il call-site (riga 96):
```python
self._password_resolved = self._config.password.get_secret_value()
```
Aggiorna il docstring del modulo (righe 63-66): la password arriva idratata dal SecretStore via config; niente più import `keyring`.

- [ ] **Step 6: Run the suites**

```powershell
pytest tests/test_openrouter_config.py tests/test_config.py tests/test_email_service.py -v
```
Expected: passed (se `test_email_service.py` usa `use_keyring`, aggiorna i fixture: il campo non esiste più).

- [ ] **Step 7: Commit**

```powershell
git add -A backend
git commit -m "feat(secrets): PUT /config scrive i segreti nel keyring; use_keyring eliminato"
```

---

### Task 6: Migrazione one-shot (DB/YAML/keyring legacy → SecretStore)

**Files:**
- Create: `backend/services/config_migration.py`
- Modify: `backend/core/bootstrap/platform.py` (chiamata dopo il load prefs)
- Modify: `backend/services/config_service.py` (nuovo `strip_paths_from_disk_layer`)
- Test: `backend/tests/test_config_migration.py`

**Interfaces:**
- Produces: `async run_secret_migrations(secret_store, session_factory, config_service, email_username: str, keyring_module: Any | None = None) -> None` — idempotente, non-fatale.
- Produces (config_service): `async strip_paths_from_disk_layer(layer: ConfigLayer, paths: Iterable[str]) -> list[str]` — rimuove i path dal layer disco, riscrive il file atomicamente, ritorna i path rimossi.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_config_migration.py
"""Tests for the one-shot secret migration."""

from __future__ import annotations

import json

import pytest
import yaml
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from backend.db.models import UserPreference
from backend.services.config_migration import run_secret_migrations
from backend.services.config_service import ConfigLayer, LayeredConfigService
from backend.services.secret_store import InMemorySecretStore


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed_pref(factory, key: str, value: object) -> None:
    async with factory() as session:
        session.add(UserPreference(key=key, value=json.dumps(value)))
        await session.commit()


@pytest.mark.asyncio
async def test_db_secret_row_moves_to_store_and_row_deleted(
    session_factory, tmp_path,
) -> None:
    await _seed_pref(session_factory, "llm.openrouter_api_key", "sk-or-legacy")
    await _seed_pref(session_factory, "email.use_keyring", False)
    await _seed_pref(session_factory, "ui.theme", "dark")
    store = InMemorySecretStore()
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )

    await run_secret_migrations(store, session_factory, svc, email_username="")

    assert store.cached()["llm.openrouter_api_key"] == "sk-or-legacy"
    from sqlmodel import select
    async with session_factory() as session:
        rows = (await session.exec(select(UserPreference))).all()
    keys = {r.key for r in rows}
    assert "llm.openrouter_api_key" not in keys       # migrata
    assert "email.use_keyring" not in keys            # chiave morta eliminata
    assert "ui.theme" in keys                         # preferenza valida intatta


@pytest.mark.asyncio
async def test_yaml_secret_is_stripped_and_stored(session_factory, tmp_path) -> None:
    user_yaml = tmp_path / "u.yaml"
    user_yaml.write_text(
        yaml.safe_dump({"continuum": {"api_token": "ct-legacy"}, "ui": {"theme": "dark"}}),
        encoding="utf-8",
    )
    store = InMemorySecretStore()
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=user_yaml,
    )

    await run_secret_migrations(store, session_factory, svc, email_username="")

    assert store.cached()["continuum.api_token"] == "ct-legacy"
    on_disk = yaml.safe_load(user_yaml.read_text(encoding="utf-8"))
    assert "api_token" not in on_disk.get("continuum", {})
    assert on_disk["ui"]["theme"] == "dark"


@pytest.mark.asyncio
async def test_migration_is_idempotent(session_factory, tmp_path) -> None:
    await _seed_pref(session_factory, "llm.openrouter_api_key", "sk-once")
    store = InMemorySecretStore()
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    await run_secret_migrations(store, session_factory, svc, email_username="")
    await run_secret_migrations(store, session_factory, svc, email_username="")
    assert store.cached()["llm.openrouter_api_key"] == "sk-once"


@pytest.mark.asyncio
async def test_legacy_email_keyring_credential_migrates(
    session_factory, tmp_path,
) -> None:
    class FakeKeyring:
        store = {("alice", "user@example.com"): "legacy-pw"}

        @classmethod
        def get_password(cls, service: str, name: str) -> str | None:
            return cls.store.get((service, name))

        @classmethod
        def delete_password(cls, service: str, name: str) -> None:
            cls.store.pop((service, name), None)

    store = InMemorySecretStore()
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    await run_secret_migrations(
        store, session_factory, svc,
        email_username="user@example.com", keyring_module=FakeKeyring,
    )
    assert store.cached()["email.password"] == "legacy-pw"
    assert ("alice", "user@example.com") not in FakeKeyring.store
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config_migration.py -v` → Expected: FAIL (modulo inesistente).

- [ ] **Step 3: Implement `strip_paths_from_disk_layer` in `config_service.py`**

```python
async def strip_paths_from_disk_layer(
    self, layer: ConfigLayer, paths: Iterable[str],
) -> list[str]:
    """Remove dotted ``paths`` from a disk layer and rewrite its file.

    Returns the paths actually removed. No-op for paths not present.
    """
    if layer not in (ConfigLayer.SYSTEM, ConfigLayer.USER):
        raise ValueError("only disk layers can be stripped")
    removed: list[str] = []
    async with self._lock:
        data = copy.deepcopy(self._layers[layer])
        for path in paths:
            try:
                _get_dotted(data, path)
            except KeyError:
                continue
            parts = path.split(".")
            node = data
            for part in parts[:-1]:
                node = node[part]
            del node[parts[-1]]
            removed.append(path)
        if not removed:
            return []
        self._layers[layer] = data
        self._rebuild()
        target = self._system_path if layer is ConfigLayer.SYSTEM else self._user_path
        await asyncio.to_thread(_write_yaml_atomic, target, data)
    return removed
```

(aggiungi `from collections.abc import Iterable` agli import se manca.)

- [ ] **Step 4: Implement `config_migration.py`**

```python
# backend/services/config_migration.py
"""AL\\CE — One-shot, idempotent migration of legacy secrets.

Moves secrets out of the preferences DB and the YAML layers into the
SecretStore, migrates the legacy email keyring credential, and deletes
dead preference rows. Every step is a no-op when there is nothing to
migrate; failures are logged and non-fatal (retried at next boot).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from backend.db.models import UserPreference
from backend.services.config_policy import SECRET_PATHS, is_preference_writable
from backend.services.config_service import ConfigLayer, LayeredConfigService

_LEGACY_KEYRING_SERVICE = "alice"


async def run_secret_migrations(
    secret_store: Any,
    session_factory: async_sessionmaker,
    config_service: LayeredConfigService,
    email_username: str,
    keyring_module: Any | None = None,
) -> None:
    """Run all legacy-secret migrations (idempotent, non-fatal)."""
    try:
        await _migrate_db_rows(secret_store, session_factory)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Secret DB migration failed (will retry next boot): {}", exc)
    try:
        await _migrate_yaml_layers(secret_store, config_service)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Secret YAML migration failed: {}", exc)
    try:
        await _migrate_legacy_email_credential(
            secret_store, email_username, keyring_module,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Legacy email keyring migration failed: {}", exc)


async def _migrate_db_rows(
    secret_store: Any, session_factory: async_sessionmaker,
) -> None:
    """Secret rows -> store; out-of-policy rows -> deleted."""
    async with session_factory() as session:
        rows = (await session.exec(select(UserPreference))).all()
        dead_keys: list[str] = []
        for row in rows:
            if row.key in SECRET_PATHS:
                try:
                    value = json.loads(row.value)
                except (json.JSONDecodeError, TypeError):
                    value = None
                if isinstance(value, str) and value:
                    await secret_store.set(row.key, value)
                    logger.info("Migrated secret '{}' from DB to keyring", row.key)
                dead_keys.append(row.key)
            elif not is_preference_writable(row.key):
                dead_keys.append(row.key)
        if dead_keys:
            await session.execute(
                sa.delete(UserPreference).where(
                    UserPreference.key.in_(dead_keys)  # type: ignore[attr-defined]
                )
            )
            await session.commit()
            logger.info("Pruned {} legacy preference rows: {}", len(dead_keys), dead_keys)


async def _migrate_yaml_layers(
    secret_store: Any, config_service: LayeredConfigService,
) -> None:
    """Secrets found in system/user YAML -> store + file rewritten."""
    for layer in (ConfigLayer.SYSTEM, ConfigLayer.USER):
        data = config_service.get_layer(layer)
        found: dict[str, str] = {}
        for path in SECRET_PATHS:
            node: Any = data
            for part in path.split("."):
                if not isinstance(node, dict) or part not in node:
                    node = None
                    break
                node = node[part]
            if isinstance(node, str) and node:
                found[path] = node
        if not found:
            continue
        for path, value in found.items():
            await secret_store.set(path, value)
        removed = await config_service.strip_paths_from_disk_layer(
            layer, found.keys(),
        )
        logger.info("Migrated {} secrets out of {} layer: {}", len(removed), layer, removed)


async def _migrate_legacy_email_credential(
    secret_store: Any, email_username: str, keyring_module: Any | None,
) -> None:
    """Legacy ('alice', <username>) credential -> 'email.password'."""
    username = email_username.strip()
    if not username or secret_store.cached().get("email.password"):
        return
    if keyring_module is None:
        try:
            import keyring as keyring_module  # noqa: PLC0415
        except ImportError:
            return
    legacy = await asyncio.to_thread(
        keyring_module.get_password, _LEGACY_KEYRING_SERVICE, username,
    )
    if not legacy:
        return
    await secret_store.set("email.password", legacy)
    await asyncio.to_thread(
        keyring_module.delete_password, _LEGACY_KEYRING_SERVICE, username,
    )
    logger.info("Migrated legacy email keyring credential for '{}'", username)
```

- [ ] **Step 5: Wire in `bootstrap/platform.py`**

Dopo il blocco "Load persisted user preferences" (e PRIMA del blocco plugin state), dentro `if not testing:`:

```python
from backend.services.config_migration import run_secret_migrations

try:
    await run_secret_migrations(
        secret_store, session_factory, config_service,
        email_username=config.email.username,
    )
    ctx.config = await config_service.rebuild()
    config = ctx.config
except Exception as exc:  # noqa: BLE001
    logger.warning("Secret migration failed: {}", exc)
```

- [ ] **Step 6: Run tests**

```powershell
pytest tests/test_config_migration.py tests/test_config_service.py -v
```
Expected: passed.

- [ ] **Step 7: Commit**

```powershell
git add -A backend
git commit -m "feat(secrets): migrazione one-shot DB/YAML/keyring-legacy verso SecretStore"
```

**Fine F1.** Verifica di fase: `pytest tests/test_secret_store.py tests/test_config_policy.py tests/test_config.py tests/test_config_service.py tests/test_config_migration.py tests/test_openrouter_config.py -v` tutti verdi; `ruff check backend/`; `mypy backend/` (zero errori nuovi); smoke manuale: avvia il backend, `PUT /api/config` con una key di test, verifica con `python -c "import keyring; print(keyring.get_password('alice','llm.openrouter_api_key'))"`, riavvia, `GET /api/config` → `openrouter_api_key_configured: true`, e la tabella `user_preferences` NON contiene la key.

---

## Fase F2 — Layer preferences e write path unificato

### Task 7: layer PREFERENCES formale + PreferencesLayerStore

**Files:**
- Modify: `backend/services/config_service.py` (`ConfigLayer.PREFERENCES`, `_LAYER_ORDER`, `load_preferences_layer`, persistenza in `set`)
- Modify: `backend/services/preferences_service.py` (riscrittura: `PreferencesLayerStore`)
- Modify: `backend/core/protocols.py` (protocol dello store; il vecchio `PreferencesServiceProtocol` con `apply_to_config`/`persist_from_update` si aggiorna QUI, i chiamanti legacy muoiono nel Task 11)
- Modify: `backend/core/bootstrap/platform.py` (carica il layer al boot; l'overlay `apply_to_config` resta fino al Task 11 — doppia applicazione innocua: stessi valori)
- Modify: `backend/core/context.py` + `backend/core/service_groups.py` (campo `preferences_store`; il campo legacy `preferences_service` resta fino al Task 11)
- Modify: `backend/api/routes/settings.py` (GET/DELETE preferenze usano lo store nuovo)
- Test: `backend/tests/test_config_service.py`, `backend/tests/test_preferences_layer.py`

**Interfaces:**
- Produces: `ConfigLayer.PREFERENCES = "preferences"` (tra USER e RUNTIME in `_LAYER_ORDER`); `PreferencesLayerStore(session_factory)` con `async load() -> dict[str, Any]` (dict ANNIDATO dalle righe `key -> json`), `async save_paths(changes: dict[str, Any]) -> None`, `async delete_paths(paths: Iterable[str]) -> int`, `async delete_all() -> int`; `LayeredConfigService.load_preferences_layer(store) -> AliceConfig` (async: carica, monta il layer, tiene il riferimento allo store per persistere le scritture future).
- Consumes: tabella `user_preferences` esistente (`backend/db/models.py::UserPreference`) — formato righe invariato.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_preferences_layer.py
"""Tests for the preferences layer store + LayeredConfigService integration."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from backend.db.models import UserPreference
from backend.services.config_service import ConfigLayer, LayeredConfigService
from backend.services.preferences_service import PreferencesLayerStore


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_store_load_builds_nested_dict(session_factory) -> None:
    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"llm.provider": "openrouter", "ui.theme": "dark"})
    loaded = await store.load()
    assert loaded == {"llm": {"provider": "openrouter"}, "ui": {"theme": "dark"}}


@pytest.mark.asyncio
async def test_store_save_paths_upserts(session_factory) -> None:
    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"ui.theme": "dark"})
    await store.save_paths({"ui.theme": "light"})
    async with session_factory() as session:
        rows = (await session.exec(select(UserPreference))).all()
    assert len(rows) == 1
    assert json.loads(rows[0].value) == "light"


@pytest.mark.asyncio
async def test_preferences_layer_wins_over_user_yaml(
    session_factory, tmp_path,
) -> None:
    import yaml
    user_yaml = tmp_path / "u.yaml"
    user_yaml.write_text(yaml.safe_dump({"ui": {"theme": "light"}}), encoding="utf-8")
    store = PreferencesLayerStore(session_factory)
    await store.save_paths({"ui.theme": "dark"})
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=user_yaml,
    )
    resolved = await svc.load_preferences_layer(store)
    assert resolved.ui.theme == "dark"          # preferences > user
    assert svc.get_layer(ConfigLayer.PREFERENCES) == {"ui": {"theme": "dark"}}


@pytest.mark.asyncio
async def test_set_on_preferences_layer_persists_to_db(
    session_factory, tmp_path,
) -> None:
    store = PreferencesLayerStore(session_factory)
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    await svc.load_preferences_layer(store)
    await svc.set("ui.theme", "dark", layer=ConfigLayer.PREFERENCES)
    assert (await store.load()) == {"ui": {"theme": "dark"}}
    # e il reload da disco NON perde il layer preferences
    svc.reload()
    assert svc.get_resolved().ui.theme == "dark"


@pytest.mark.asyncio
async def test_secret_paths_rejected_on_every_layer(
    session_factory, tmp_path,
) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    for layer in (ConfigLayer.USER, ConfigLayer.PREFERENCES, ConfigLayer.RUNTIME):
        with pytest.raises(ValueError, match="secret"):
            await svc.set("llm.openrouter_api_key", "sk-nope", layer=layer)


@pytest.mark.asyncio
async def test_out_of_policy_path_rejected_on_preferences(
    session_factory, tmp_path,
) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    with pytest.raises(ValueError, match="policy"):
        await svc.set("server.port", 9999, layer=ConfigLayer.PREFERENCES)
    # ...ma sul layer user resta legittimo (power-user via PATCH)
    await svc.set("server.port", 9999, layer=ConfigLayer.USER)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_preferences_layer.py -v` → Expected: FAIL (`PreferencesLayerStore` inesistente, `ConfigLayer.PREFERENCES` inesistente).

- [ ] **Step 3: Rewrite `preferences_service.py` as `PreferencesLayerStore`**

Sostituisci l'intero contenuto (le vecchie API restano temporaneamente come metodi di compatibilità SOLO se i test legacy li usano; verranno eliminate nel Task 11):

```python
# backend/services/preferences_service.py
"""AL\\CE — DB-backed store for the ``preferences`` config layer.

Rows in ``user_preferences`` are ``dotted.path -> JSON value``; the
store materialises them as the nested dict the LayeredConfigService
merges as the ``preferences`` layer. Writability policy lives in
``config_policy`` and is enforced by the config service, not here.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from backend.db.models import UserPreference, _utcnow


class PreferencesLayerStore:
    """Load/persist the preferences layer (dotted-path rows)."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def load(self) -> dict[str, Any]:
        """Return all rows as a nested dict (invalid JSON rows skipped)."""
        async with self._session_factory() as session:
            rows = (await session.exec(select(UserPreference))).all()
        nested: dict[str, Any] = {}
        for row in rows:
            try:
                value = json.loads(row.value)
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid preference value for '{}', skipping", row.key)
                continue
            node = nested
            parts = row.key.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
                if not isinstance(node, dict):
                    logger.warning("Preference key '{}' collides, skipping", row.key)
                    break
            else:
                node[parts[-1]] = value
        return nested

    async def save_paths(self, changes: dict[str, Any]) -> None:
        """Upsert one row per dotted path (single transaction)."""
        now = _utcnow()
        async with self._session_factory() as session:
            for path, value in changes.items():
                await session.merge(
                    UserPreference(key=path, value=json.dumps(value), updated_at=now)
                )
            await session.commit()

    async def delete_paths(self, paths: Iterable[str]) -> int:
        """Delete the given dotted paths; returns the number removed."""
        keys = list(paths)
        if not keys:
            return 0
        async with self._session_factory() as session:
            result = await session.execute(
                sa.delete(UserPreference).where(
                    UserPreference.key.in_(keys)  # type: ignore[attr-defined]
                )
            )
            await session.commit()
        return int(result.rowcount or 0)

    async def delete_all(self) -> int:
        """Delete every preference row (reset to defaults)."""
        async with self._session_factory() as session:
            rows = (await session.exec(select(UserPreference))).all()
            count = len(rows)
            await session.execute(sa.delete(UserPreference))  # type: ignore[arg-type]
            await session.commit()
        logger.info("Deleted {} persisted preferences", count)
        return count
```

NOTA compatibilità intra-fase: `load_all()` legacy è usato da `api/routes/settings.py:286` e dai test F1 — in questo task aggiorna quei call-site a `load()` (shape identica: dict annidato). `persist_from_update`/`apply_to_config`/allowlist vengono eliminati nel Task 11 insieme ai loro chiamanti in `config.py`/`platform.py`; fino ad allora, mantieni in fondo al file questi shim deprecati:

```python
    # -- Legacy shims (rimossi nel Task 11 col rewiring di PUT/bootstrap) --

    async def load_all(self) -> dict[str, Any]:
        return await self.load()
```

e in `platform.py`/`config.py` NON cambiare nulla in questo task (gli import `PreferencesService` vanno rinominati in `PreferencesLayerStore`; `apply_to_config`/`persist_from_update` sono metodi che DEVONO restare funzionanti fino al Task 11 — quindi mantieni anche questi due come shim, copiando i corpi attuali dal file pre-rewrite).

- [ ] **Step 4: Add the PREFERENCES layer to `config_service.py`**

```python
class ConfigLayer(StrEnum):
    DEFAULTS = "defaults"
    SYSTEM = "system"
    USER = "user"
    PREFERENCES = "preferences"
    RUNTIME = "runtime"


_LAYER_ORDER: tuple[ConfigLayer, ...] = (
    ConfigLayer.DEFAULTS,
    ConfigLayer.SYSTEM,
    ConfigLayer.USER,
    ConfigLayer.PREFERENCES,
    ConfigLayer.RUNTIME,
)
```

In `__init__`: aggiungi `ConfigLayer.PREFERENCES: {}` a `self._layers` e `self._preferences_store: Any | None = None`.

Nuovo metodo:

```python
async def load_preferences_layer(self, store: Any) -> AliceConfig:
    """Load the DB-backed preferences layer and keep the store for writes."""
    data = await store.load()
    async with self._lock:
        self._preferences_store = store
        self._layers[ConfigLayer.PREFERENCES] = migrate_legacy_config_keys(data)
        self._rebuild()
        assert self._resolved is not None
        return self._resolved
```

In `set()` (e in `set_many` del Task 9): guardie policy in testa e persistenza del layer preferences accanto a quella disco:

```python
from backend.services.config_policy import is_preference_writable, is_secret_path

# in cima a set(), prima del lock:
if is_secret_path(path):
    raise ValueError(f"secret path '{path}' cannot be written to config layers")
if layer is ConfigLayer.PREFERENCES and not is_preference_writable(path):
    raise ValueError(f"path '{path}' is not preference-writable (policy)")

# nel blocco di persistenza (dopo il commit in-memory):
elif layer is ConfigLayer.PREFERENCES and self._preferences_store is not None:
    await self._preferences_store.save_paths({path: value})
    logger.info("Persisted preference change ({} = {!r})", path, value)
```

`reload()` NON tocca il layer preferences (già così: rilegge solo i tre layer disco).

- [ ] **Step 5: Wire bootstrap + settings route**

`bootstrap/platform.py` — nel blocco preferenze, PRIMA del vecchio overlay (che resta fino al Task 11):

```python
from backend.services.preferences_service import PreferencesLayerStore

preferences_store = PreferencesLayerStore(session_factory)
ctx.preferences_store = preferences_store
ctx.preferences_service = preferences_store  # alias legacy, muore nel Task 11

if not testing:
    try:
        ctx.config = await config_service.load_preferences_layer(preferences_store)
        config = ctx.config
    except Exception as exc:
        logger.warning("Failed to load preferences layer: {}", exc)
```

`core/service_groups.py`/`core/context.py`: aggiungi `preferences_store` al gruppo platform (delegating property, stile degli altri).

`api/routes/settings.py`: sostituisci `ctx.preferences_service.load_all()` → `ctx.preferences_store.load()` e l'eventuale `delete_all()` → `ctx.preferences_store.delete_all()`.

- [ ] **Step 6: Run tests**

```powershell
pytest tests/test_preferences_layer.py tests/test_config_service.py tests/test_app.py tests/test_settings_routes.py -v
```
Expected: passed (se `tests/test_settings_routes.py` non esiste, salta; cerca i test della route con `grep -rln "preferences" backend/tests/`).

- [ ] **Step 7: Commit**

```powershell
git add -A backend
git commit -m "feat(config): layer preferences formale persistito in DB con policy di scrivibilita'"
```

---

### Task 8: vincoli pydantic sui modelli (sostituiscono la validazione a mano)

**Files:**
- Modify: `backend/core/config.py` (LLMConfig, STTConfig, TTSConfig, UIConfig, VoiceConfig, EmailConfig)
- Test: `backend/tests/test_config.py` (aggiunte)

**Interfaces:**
- Produces: vincoli dichiarativi equivalenti alle regole oggi hard-coded in `api/routes/config.py` (censite qui sotto). Il Task 11 cancella i check a mano contando su QUESTI vincoli.

- [ ] **Step 1: Write the failing tests**

```python
# aggiunte a backend/tests/test_config.py
import pytest
from pydantic import ValidationError

from backend.core.config import (
    EmailConfig,
    LLMConfig,
    STTConfig,
    TTSConfig,
    UIConfig,
    VoiceConfig,
)


@pytest.mark.parametrize(
    ("model_cls", "field", "bad"),
    [
        (LLMConfig, "temperature", 2.5),
        (LLMConfig, "temperature", -0.1),
        (LLMConfig, "max_tokens", 0),
        (LLMConfig, "max_tokens", -2),
        (LLMConfig, "max_tool_iterations", 0),
        (LLMConfig, "max_tool_iterations", 101),
        (LLMConfig, "context_compression_threshold", 0.4),
        (LLMConfig, "context_compression_threshold", 0.96),
        (LLMConfig, "context_compression_reserve", 511),
        (LLMConfig, "context_compression_reserve", 8193),
        (LLMConfig, "tool_rag_top_k", 0),
        (LLMConfig, "tool_rag_top_k", 101),
        (LLMConfig, "user_preferred_name", "x" * 81),
        (LLMConfig, "model", ""),
        (LLMConfig, "model", "x" * 257),
        (LLMConfig, "openrouter_model", "x" * 257),
        (LLMConfig, "provider", "bogus"),
        (STTConfig, "device", "tpu"),
        (STTConfig, "model", ""),
        (STTConfig, "language", "x" * 11),
        (TTSConfig, "engine", "espeak"),
        (TTSConfig, "speed", 0.4),
        (TTSConfig, "speed", 2.1),
        (TTSConfig, "sample_rate", 12345),
        (TTSConfig, "voice", ""),
        (UIConfig, "theme", "sepia"),
        (UIConfig, "language", ""),
        (VoiceConfig, "activation_mode", "telepathy"),
        (VoiceConfig, "wake_word", ""),
        (EmailConfig, "imap_port", 0),
        (EmailConfig, "imap_port", 65536),
        (EmailConfig, "fetch_last_n", 0),
        (EmailConfig, "fetch_last_n", 501),
        (EmailConfig, "max_fetch", 501),
        (EmailConfig, "imap_host", "x" * 256),
    ],
)
def test_field_constraints_reject_bad_values(model_cls, field, bad) -> None:
    with pytest.raises(ValidationError):
        model_cls(**{field: bad})


def test_provider_is_normalized_lowercase() -> None:
    assert LLMConfig(provider="OpenRouter").provider == "openrouter"


def test_openrouter_favorites_capped_at_200() -> None:
    with pytest.raises(ValidationError):
        LLMConfig(openrouter_favorites=[f"m{i}" for i in range(201)])
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config.py -v -k "constraints or normalized or capped"` → Expected: molte FAIL (nessun vincolo sui campi oggi).

- [ ] **Step 3: Add the constraints in `core/config.py`**

Censimento regole (fonte: hand-rolled checks in `api/routes/config.py:389-723`) → dichiarale così:

```python
from typing import Literal

# LLMConfig
provider: str = "lmstudio"           # + validator sotto
model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=256)
temperature: float = Field(default=0.7, ge=0.0, le=2.0)
max_tokens: int = -1                 # + validator sotto (>=1 oppure -1)
max_tool_iterations: int = Field(default=25, ge=1, le=100)
context_compression_threshold: float = Field(default=0.75, ge=0.50, le=0.95)
context_compression_reserve: int = Field(default=4096, ge=512, le=8192)
tool_rag_top_k: int = Field(default=20, ge=1, le=100)
user_preferred_name: str = Field(default="", max_length=80)
openrouter_model: str = Field(default="", max_length=256)
openrouter_favorites: list[str] = Field(default_factory=list, max_length=200)

@field_validator("provider", mode="before")
@classmethod
def _normalize_provider(cls, v: object) -> str:
    prov = str(v).strip().lower()
    if prov not in ("lmstudio", "ollama", "openrouter"):
        raise ValueError("provider must be one of: lmstudio, ollama, openrouter")
    return prov

@field_validator("max_tokens")
@classmethod
def _validate_max_tokens(cls, v: int) -> int:
    if v < -1 or v == 0:
        raise ValueError("max_tokens must be a positive integer or -1 (unlimited)")
    return v

# STTConfig
model: str = Field(default="large-v3", min_length=1, max_length=64)
language: str | None = Field(default=None, max_length=10)
device: Literal["cpu", "cuda"] = "cpu"     # verifica il default attuale nel file

# TTSConfig
engine: Literal["piper", "xtts", "kokoro"] = "piper"   # default attuale dal file
voice: str = Field(default=..., min_length=1, max_length=256)  # default attuale dal file
speed: float = Field(default=1.0, ge=0.5, le=2.0)
sample_rate: Literal[16000, 22050, 24000, 44100, 48000] = 22050  # default attuale
kokoro_model: str = Field(default=..., min_length=1, max_length=256)
kokoro_voices: str = Field(default=..., min_length=1, max_length=256)
kokoro_voice: str = Field(default=..., min_length=1, max_length=100)
kokoro_language: str = Field(default=..., min_length=1, max_length=10)

# UIConfig
theme: Literal["dark", "light"] = "dark"   # default attuale dal file
language: str = Field(default="it", min_length=1, max_length=10)

# VoiceConfig
activation_mode: Literal["push_to_talk", "wake_word", "always_on"] = "push_to_talk"
wake_word: str = Field(default="alice", min_length=1, max_length=50)

# EmailConfig
imap_host: str = Field(default="", max_length=255)
smtp_host: str = Field(default="", max_length=255)
username: str = Field(default="", max_length=255)
archive_folder: str = Field(default="Archive", max_length=255)
imap_port: int = Field(default=993, ge=1, le=65535)
smtp_port: int = Field(default=587, ge=1, le=65535)
fetch_last_n: int = Field(default=20, ge=1, le=500)
max_fetch: int = Field(default=50, ge=1, le=500)
```

IMPORTANTE: per ogni campo, MANTIENI il default attuale del file (i valori `default=...` sopra vanno letti dal codice esistente, non inventati). I docstring dei campi restano. `stt.language` accetta anche `""` → normalizza a `None` con un `field_validator(mode="before")` che mappa stringa vuota a `None` (comportamento oggi nella route, righe 560-572).

- [ ] **Step 4: Run tests**

```powershell
pytest tests/test_config.py tests/test_app.py tests/contracts/ -v
```
Expected: passed. Se un default di `config/default.yaml` viola un vincolo, il lifespan di test esplode: correggi il VINCOLO (la fonte di verità è il comportamento attuale), non il default.

- [ ] **Step 5: Commit**

```powershell
git add backend/core/config.py backend/tests/test_config.py
git commit -m "feat(config): vincoli dichiarativi sui modelli al posto della validazione a mano"
```

---

### Task 9: `set_many` batch sul LayeredConfigService

**Files:**
- Modify: `backend/services/config_service.py`
- Test: `backend/tests/test_config_service.py` (aggiunte)

**Interfaces:**
- Produces: `async set_many(changes: dict[str, Any], layer: ConfigLayer = ConfigLayer.PREFERENCES) -> AliceConfig` — policy check su ogni path, UNA validazione, UN commit, UNA persistenza batch, un evento `config.changed` per path (post-lock). `set(path, value, layer)` delega a `set_many({path: value}, layer)`.

- [ ] **Step 1: Write the failing tests**

```python
# aggiunte a backend/tests/test_config_service.py
@pytest.mark.asyncio
async def test_set_many_is_atomic_on_validation_failure(tmp_path) -> None:
    svc = LayeredConfigService(
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        await svc.set_many(
            {"ui.theme": "dark", "llm.temperature": 99.0},  # il secondo è invalido
            layer=ConfigLayer.RUNTIME,
        )
    # niente commit parziale: il layer runtime è rimasto intatto
    assert svc.get_layer(ConfigLayer.RUNTIME) == {}


@pytest.mark.asyncio
async def test_set_many_emits_one_event_per_path(tmp_path) -> None:
    from backend.core.event_bus import EventBus
    bus = EventBus()
    events: list[dict] = []

    async def _capture(**kwargs) -> None:
        events.append(kwargs)

    bus.subscribe("config.changed", _capture)
    svc = LayeredConfigService(
        event_bus=bus,
        defaults_path=tmp_path / "d.yaml",
        system_path=tmp_path / "s.yaml",
        user_path=tmp_path / "u.yaml",
    )
    await svc.set_many(
        {"ui.theme": "dark", "ui.language": "en"}, layer=ConfigLayer.RUNTIME,
    )
    paths = {e["path"] for e in events}
    assert paths == {"ui.theme", "ui.language"}
```

(se la firma di `EventBus.subscribe`/`emit` differisce, copia lo stile dai test esistenti in `tests/test_config_service.py`.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config_service.py -v -k set_many` → Expected: FAIL (`set_many` non esiste).

- [ ] **Step 3: Implement `set_many` and re-base `set` on it**

```python
async def set_many(
    self,
    changes: dict[str, Any],
    layer: ConfigLayer = ConfigLayer.PREFERENCES,
) -> AliceConfig:
    """Set several dotted paths in ``layer`` atomically.

    One validation, one commit, one batched persistence; emits one
    ``config.changed`` event per path after the lock is released.

    Raises:
        ValueError: path fuori policy / segreto / non-dict traversal.
        pydantic.ValidationError: merge risultante invalido — nessun
            commit parziale (disk e memoria intatti).
    """
    if not changes:
        return self.get_resolved()
    for path in changes:
        if is_secret_path(path):
            raise ValueError(
                f"secret path '{path}' cannot be written to config layers"
            )
        if layer is ConfigLayer.PREFERENCES and not is_preference_writable(path):
            raise ValueError(f"path '{path}' is not preference-writable (policy)")

    async with self._lock:
        tentative = copy.deepcopy(self._layers[layer])
        for path, value in changes.items():
            _set_dotted(tentative, path, value)

        merged: dict[str, Any] = {}
        for lyr in _LAYER_ORDER:
            src = tentative if lyr is layer else self._layers[lyr]
            _deep_merge(merged, src)
        if self._secrets_provider is not None:
            for spath, svalue in self._secrets_provider().items():
                _set_dotted(merged, spath, svalue)
        new_resolved = AliceConfig(**merged)

        self._layers[layer] = tentative
        self._resolved = new_resolved

        if layer in (ConfigLayer.SYSTEM, ConfigLayer.USER):
            target_path = (
                self._system_path if layer is ConfigLayer.SYSTEM else self._user_path
            )
            await asyncio.to_thread(_write_yaml_atomic, target_path, tentative)
            logger.info("Persisted {} config changes to {}", len(changes), target_path)
        elif layer is ConfigLayer.PREFERENCES and self._preferences_store is not None:
            await self._preferences_store.save_paths(changes)
            logger.info("Persisted {} preference changes", len(changes))
        else:
            logger.debug("Runtime config changes: {}", list(changes))

    if self._event_bus is not None:
        for path, value in changes.items():
            try:
                await self._event_bus.emit(
                    "config.changed", path=path, value=value, layer=layer.value,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("config.changed handler raised: {}", exc)

    return new_resolved
```

`set()` diventa:

```python
async def set(
    self, path: str, value: Any, layer: ConfigLayer = ConfigLayer.USER,
) -> AliceConfig:
    """Set a single dotted path (see :meth:`set_many`)."""
    return await self.set_many({path: value}, layer=layer)
```

NOTA: `_rebuild()` e `set_many` ora duplicano l'iniezione segreti — estrai un helper privato `_hydrate(merged: dict) -> None` usato da entrambi.

- [ ] **Step 4: Run tests**

```powershell
pytest tests/test_config_service.py tests/test_preferences_layer.py -v
```
Expected: passed (inclusi i test policy del Task 7, ora esercitati anche via `set_many`).

- [ ] **Step 5: Commit**

```powershell
git add backend/services/config_service.py backend/tests/test_config_service.py
git commit -m "feat(config): set_many batch atomico con eventi per-path"
```

---

### Task 10: registry dichiarativo delle reazioni

**Files:**
- Create: `backend/api/routes/config_reactions.py` (gli helper `_apply_stt_changes`, `_apply_tts_changes`, `_apply_email_changes`, `_apply_llm_provider_change` SI SPOSTANO qui da `config.py`, invariati nel corpo)
- Modify: `backend/api/routes/config.py` (import aggiornati; le chiamate dirette restano fino al Task 11)
- Test: `backend/tests/test_config_reactions.py`

**Interfaces:**
- Produces: `async apply_reactions(ctx: AppContext, changed: set[str]) -> None`; `diff_paths(old: AliceConfig, new: AliceConfig, candidates: Iterable[str]) -> set[str]` (confronto per path puntato via `_get_dotted`, `SecretStr` confrontati sul `get_secret_value()`).
- Consumes: gli `_apply_*` esistenti (`config.py:783-969`), `push_voice_ready` da `api/routes/voice.py`, i metodi `invalidate_*` di `LLMService`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_config_reactions.py
"""Tests for the declarative config-change reaction registry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.api.routes.config_reactions import REACTIONS, apply_reactions


def _reaction_names() -> set[str]:
    return {handler.__name__ for _, handler in REACTIONS}


def test_registry_covers_the_known_reactive_paths() -> None:
    assert {
        "_react_stt", "_react_tts", "_react_email", "_react_llm_rebuild",
        "_react_model_cache", "_react_openrouter_model", "_react_system_prompt",
    } <= _reaction_names()


@pytest.mark.asyncio
async def test_llm_rebuild_fires_on_provider_change() -> None:
    ctx = MagicMock()
    ctx.llm_service = MagicMock()
    rebuild = AsyncMock()
    # monkeypatch del modulo: la reazione delega a _apply_llm_provider_change
    import backend.api.routes.config_reactions as cr
    original = cr._apply_llm_provider_change
    cr._apply_llm_provider_change = rebuild
    try:
        await apply_reactions(ctx, {"llm.provider"})
    finally:
        cr._apply_llm_provider_change = original
    rebuild.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_reaction_on_unrelated_paths() -> None:
    ctx = MagicMock()
    ctx.llm_service = MagicMock()
    await apply_reactions(ctx, {"ui.theme", "voice.wake_word"})
    ctx.llm_service.invalidate_model_cache.assert_not_called()


@pytest.mark.asyncio
async def test_model_change_invalidates_cache() -> None:
    ctx = MagicMock()
    ctx.llm_service = MagicMock()
    await apply_reactions(ctx, {"llm.model"})
    ctx.llm_service.invalidate_model_cache.assert_called_once()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config_reactions.py -v` → Expected: FAIL (modulo inesistente).

- [ ] **Step 3: Implement `config_reactions.py`**

```python
# backend/api/routes/config_reactions.py
"""AL\\CE — Declarative reactions to config changes.

Maps sets of dotted config paths to side-effect handlers (service
restarts, cache invalidation). Invoked once per PUT/PATCH request with
the set of paths whose RESOLVED value actually changed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from loguru import logger
from pydantic import SecretStr

from backend.core.context import AppContext

# --- handlers spostati (corpo INVARIATO) da config.py ---------------------
# _apply_stt_changes, _apply_tts_changes, _apply_email_changes,
# _apply_llm_provider_change, più gli import che li servono
# (STTService, TTSService, EmailService, LLMService, push_voice_ready).
# NB: _apply_stt_changes/_apply_tts_changes oggi ricevono gli update del
# body; qui derivali dai changed path (vedi wrapper sotto).


_STT_RESTART_PATHS = frozenset({"stt.enabled", "stt.model", "stt.device"})
_TTS_RESTART_PATHS = frozenset({
    "tts.enabled", "tts.engine", "tts.voice", "tts.speed",
    "tts.kokoro_model", "tts.kokoro_voices", "tts.kokoro_voice",
    "tts.kokoro_language",
})
_LLM_REBUILD_PATHS = frozenset({
    "llm.provider", "llm.openrouter_api_key", "llm.api_token",
})


async def _react_stt(ctx: AppContext, changed: set[str]) -> None:
    updates = {p.removeprefix("stt."): True for p in changed if p in _STT_RESTART_PATHS}
    if updates:
        await _apply_stt_changes(ctx, updates)
        from backend.api.routes.voice import push_voice_ready
        await push_voice_ready(ctx)


async def _react_tts(ctx: AppContext, changed: set[str]) -> None:
    updates = {p.removeprefix("tts."): True for p in changed if p in _TTS_RESTART_PATHS}
    if updates:
        await _apply_tts_changes(ctx, updates)
        from backend.api.routes.voice import push_voice_ready
        await push_voice_ready(ctx)


async def _react_email(ctx: AppContext, changed: set[str]) -> None:
    if any(p.startswith("email.") for p in changed):
        await _apply_email_changes(ctx)


async def _react_llm_rebuild(ctx: AppContext, changed: set[str]) -> None:
    if changed & _LLM_REBUILD_PATHS:
        await _apply_llm_provider_change(ctx)


async def _react_model_cache(ctx: AppContext, changed: set[str]) -> None:
    if "llm.model" in changed and ctx.llm_service is not None:
        ctx.llm_service.invalidate_model_cache()


async def _react_openrouter_model(ctx: AppContext, changed: set[str]) -> None:
    if "llm.openrouter_model" in changed and ctx.llm_service is not None:
        ctx.llm_service.invalidate_model_cache()
        ctx.llm_service.invalidate_context_window_cache()


async def _react_system_prompt(ctx: AppContext, changed: set[str]) -> None:
    if "llm.user_preferred_name" in changed and ctx.llm_service is not None:
        ctx.llm_service.invalidate_system_prompt_cache()


Reaction = Callable[[AppContext, set[str]], Awaitable[None]]

# Ordine deliberato: il rebuild LLM per ULTIMO tra le reazioni llm.* così
# le invalidazioni di cache toccano il servizio NUOVO quando coincidono.
REACTIONS: tuple[tuple[frozenset[str] | str, Reaction], ...] = (
    ("stt.", _react_stt),
    ("tts.", _react_tts),
    ("email.", _react_email),
    (frozenset({"llm.model"}), _react_model_cache),
    (frozenset({"llm.openrouter_model"}), _react_openrouter_model),
    (frozenset({"llm.user_preferred_name"}), _react_system_prompt),
    (_LLM_REBUILD_PATHS, _react_llm_rebuild),
)


def _matches(trigger: frozenset[str] | str, changed: set[str]) -> bool:
    if isinstance(trigger, str):
        return any(p.startswith(trigger) for p in changed)
    return bool(trigger & changed)


async def apply_reactions(ctx: AppContext, changed: set[str]) -> None:
    """Run every matching reaction; failures are logged, not raised."""
    for trigger, handler in REACTIONS:
        if not _matches(trigger, changed):
            continue
        try:
            await handler(ctx, changed)
        except Exception as exc:  # noqa: BLE001 — una reazione non blocca le altre
            logger.warning("Config reaction {} failed: {}", handler.__name__, exc)


def diff_paths(old: Any, new: Any, candidates: Iterable[str]) -> set[str]:
    """Return the candidate dotted paths whose resolved value changed."""
    from backend.services.config_service import _get_dotted

    changed: set[str] = set()
    for path in candidates:
        try:
            old_v = _get_dotted(old, path)
        except KeyError:
            old_v = None
        try:
            new_v = _get_dotted(new, path)
        except KeyError:
            new_v = None
        if isinstance(old_v, SecretStr):
            old_v = old_v.get_secret_value()
        if isinstance(new_v, SecretStr):
            new_v = new_v.get_secret_value()
        if old_v != new_v:
            changed.add(path)
    return changed
```

ATTENZIONE ai wrapper `_react_stt`/`_react_tts`: gli `_apply_*` originali ispezionano le CHIAVI degli update (`"enabled" in stt_updates`) — passare `{campo: True}` preserva quel contratto (usano i valori da `cfg.*`, non dal dict). Verificalo rileggendo i corpi mentre li sposti.

- [ ] **Step 4: Run tests**

```powershell
pytest tests/test_config_reactions.py tests/test_config.py tests/test_openrouter_config.py -v
```
Expected: passed (config.py importa ora gli `_apply_*` da `config_reactions`).

- [ ] **Step 5: Commit**

```powershell
git add -A backend
git commit -m "feat(config): registry dichiarativo delle reazioni ai cambi di config"
```

---

### Task 11: riscrittura PUT /config + morte del doppio sistema

**Files:**
- Modify: `backend/api/routes/config.py` (`update_config` riscritta ~334-780; `patch_config` default layer; morte dei check a mano)
- Modify: `backend/core/bootstrap/platform.py` (via l'overlay legacy `apply_to_config`)
- Modify: `backend/services/preferences_service.py` (via gli shim legacy: `load_all`, `persist_from_update`, `apply_to_config`, allowlist)
- Modify: `backend/core/protocols.py`, `backend/core/context.py`, `backend/core/service_groups.py` (via l'alias `preferences_service`)
- Test: `backend/tests/test_config.py`, `backend/tests/test_openrouter_config.py` (riusa le suite esistenti; aggiunte sotto)

**Interfaces:**
- Consumes: `_apply_secret_updates` (Task 5), `set_many` (Task 9), `apply_reactions`/`diff_paths` (Task 10), policy (Task 2), vincoli (Task 8).
- Produces: `_flatten_update_body(body: dict) -> dict[str, Any]` (dotted paths; alias `pc_automation.confirmations_enabled` → `permissions.confirmations_enabled`).

- [ ] **Step 1: Write the failing tests**

```python
# aggiunte a backend/tests/test_config.py
@pytest.mark.asyncio
async def test_unknown_path_returns_400_with_the_paths(client) -> None:
    resp = await client.put(
        "/api/config", json={"llm": {"bogus_key": 1}, "nonsense": {"x": 2}},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "llm.bogus_key" in str(detail)
    assert "nonsense.x" in str(detail)


@pytest.mark.asyncio
async def test_invalid_value_returns_422(client) -> None:
    resp = await client.put("/api/config", json={"llm": {"temperature": 99}})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_put_persists_only_sent_paths(client, app) -> None:
    ctx = app.state.context
    resp = await client.put("/api/config", json={"ui": {"theme": "light"}})
    assert resp.status_code == 200
    prefs = await ctx.preferences_store.load()
    assert prefs == {"ui": {"theme": "light"}}


@pytest.mark.asyncio
async def test_patch_persona_does_not_clobber_preferences(client, app) -> None:
    """Il test di regressione split-brain: oggi sarebbe rosso su main."""
    ctx = app.state.context
    seed = await client.put(
        "/api/config", json={"llm": {"provider": "openrouter"}},
    )
    assert seed.status_code == 200
    patch = await client.patch(
        "/api/config",
        json={"path": "agent.prompts.persona", "value": "Sii conciso."},
    )
    assert patch.status_code == 200
    # la resolved config conserva la preferenza DB dopo il rebuild da PATCH
    assert ctx.config.llm.provider == "openrouter"


@pytest.mark.asyncio
async def test_patch_defaults_to_preferences_layer(client, app) -> None:
    ctx = app.state.context
    resp = await client.patch(
        "/api/config", json={"path": "ui.theme", "value": "light"},
    )
    assert resp.status_code == 200
    prefs = await ctx.preferences_store.load()
    assert prefs["ui"]["theme"] == "light"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config.py -v -k "unknown_path or invalid_value or only_sent or clobber or defaults_to"`
Expected: FAIL (la PUT attuale ignora i path sconosciuti; la PATCH scrive su user.yaml; il clobber esiste).

- [ ] **Step 3: Rewrite `update_config`**

Il nuovo handler SOSTITUISCE integralmente `update_config` (~334-780). I blocchi di validazione a mano muoiono; snapshot `old_stt`/`old_tts`/`old_email` muoiono (rimpiazzati da `diff_paths`).

```python
def _flatten_update_body(body: dict[str, Any]) -> dict[str, Any]:
    """Flatten a nested update body into dotted paths (legacy aliases folded)."""
    flat: dict[str, Any] = {}
    for section, updates in body.items():
        if not isinstance(updates, dict):
            raise HTTPException(400, f"'{section}' must be a JSON object")
        for key, value in updates.items():
            flat[f"{section}.{key}"] = value
    # Alias storico (la UI invia ancora la forma pc_automation).
    if "pc_automation.confirmations_enabled" in flat:
        flat["permissions.confirmations_enabled"] = flat.pop(
            "pc_automation.confirmations_enabled"
        )
    return flat


# Path reattivi da confrontare old/new dopo il commit (unione dei trigger
# del registry: tienila importata da config_reactions per non duplicare).
from backend.api.routes.config_reactions import (
    ALL_REACTIVE_PATHS,  # aggiungi in config_reactions: unione dei trigger
    apply_reactions,
    diff_paths,
)


@router.put("/config")
async def update_config(request: Request) -> dict[str, Any]:
    """Update configuration values (preferences layer + secrets).

    Body: partial nested config dict. Unknown/out-of-policy paths -> 400,
    invalid values -> 422, secrets routed to the SecretStore.
    """
    ctx = _ctx(request)
    if ctx.config_service is None:
        raise HTTPException(503, "Config service unavailable")
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "Request body must be a JSON object")

    flat = _flatten_update_body(body)

    secret_updates: dict[str, Any] = {}
    pref_updates: dict[str, Any] = {}
    rejected: list[str] = []
    for path, value in flat.items():
        if is_secret_path(path):
            secret_updates[path] = value
        elif is_preference_writable(path):
            pref_updates[path] = value
        else:
            rejected.append(path)
    if rejected:
        raise HTTPException(
            400, f"Unknown or non-writable config paths: {sorted(rejected)}",
        )

    old_config = ctx.config

    secret_changed = await _apply_secret_updates(ctx, secret_updates)

    if pref_updates:
        try:
            await ctx.config_service.set_many(
                pref_updates, layer=ConfigLayer.PREFERENCES,
            )
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_url=False)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        ctx.config = ctx.config_service.get_resolved()

    changed = diff_paths(
        old_config, ctx.config, set(pref_updates) | ALL_REACTIVE_PATHS,
    ) | secret_changed
    await apply_reactions(ctx, changed)

    return await get_config(request)
```

In `config_reactions.py` aggiungi (sotto `REACTIONS`):

```python
from backend.services.config_policy import PREFERENCE_EXACT_PATHS

_EMAIL_REACTIVE_PATHS: frozenset[str] = frozenset(
    p for p in PREFERENCE_EXACT_PATHS if p.startswith("email.")
)

ALL_REACTIVE_PATHS: frozenset[str] = (
    frozenset(
        p
        for trigger, _ in REACTIONS
        if isinstance(trigger, frozenset)
        for p in trigger
    )
    | _STT_RESTART_PATHS
    | _TTS_RESTART_PATHS
    | _EMAIL_REACTIVE_PATHS
)
```

`patch_config`: cambia SOLO il default del layer: `raw_layer = body.get("layer", ConfigLayer.PREFERENCES.value)` e aggiorna la docstring (le opzioni valide ora includono `preferences`). Aggiungi dopo il `set()` riuscito: `ctx.config = ctx.config_service.get_resolved()` seguito da `await apply_reactions(ctx, {path})` così anche la PATCH innesca le reazioni.

- [ ] **Step 4: Kill the legacy double system**

- `bootstrap/platform.py`: elimina il blocco `prefs = await preferences_service.load_all(); preferences_service.apply_to_config(config, prefs)` (righe 92-97 pre-rework) — resta solo `load_preferences_layer` (Task 7).
- `preferences_service.py`: elimina gli shim (`load_all`, `persist_from_update`, `apply_to_config`) e le allowlist rimaste.
- `context.py`/`service_groups.py`/`protocols.py`: elimina l'alias `preferences_service`; i call-site residui usano `preferences_store` (cerca con `grep -rn "preferences_service" backend/ --include="*.py"` e aggiorna anche i TEST che lo usano: `tests/test_openrouter_config.py` → `ctx.preferences_store.load()`).
- In `config.py` elimina: import ora orfani, `_flatten` duplicati, ogni riferimento a `persist_from_update`.

- [ ] **Step 5: Run the full config-related suites**

```powershell
pytest tests/test_config.py tests/test_openrouter_config.py tests/test_config_service.py tests/test_preferences_layer.py tests/test_config_reactions.py tests/test_app.py -v
```
Expected: passed. I test esistenti che inviavano campi oggi fuori policy (se ce ne sono) vanno adeguati: è un cambiamento VOLUTO (400 al posto del drop silenzioso).

- [ ] **Step 6: Commit**

```powershell
git add -A backend
git commit -m "feat(config): PUT/PATCH su motore unico set_many + reazioni; morte del doppio sistema"
```

---

### Task 12: response_model tipizzati + rigenerazione contratti

**Files:**
- Create: `backend/api/routes/config_schemas.py` (pydantic response models)
- Modify: `backend/api/routes/config.py` (decoratori `response_model=` su GET/PUT/PATCH/reload/resolved/layers)
- Modify: `backend/tests/contracts/` (ratchet: le route config escono dalla lista delle eccezioni, se censite)
- Test: `backend/tests/test_config.py` + contratti

**Interfaces:**
- Produces: `ConfigResponse` (shape ESATTA dell'attuale dict di `get_config` — sezioni `llm/stt/tts/ui/voice/pc_automation/email`, senza `use_keyring`), `ResolvedConfigResponse = dict[str, Any]` documentato redatto (resta dict: la shape è l'intero AliceConfig, non fissarla a mano), `PatchConfigRequest {path, value, layer}`.

- [ ] **Step 1: Write the failing test**

```python
# aggiunta a backend/tests/test_config.py
@pytest.mark.asyncio
async def test_get_config_matches_response_model(client) -> None:
    resp = await client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    from backend.api.routes.config_schemas import ConfigResponse
    parsed = ConfigResponse.model_validate(body)
    assert parsed.llm.provider in ("lmstudio", "ollama", "openrouter")
    assert not hasattr(parsed.email, "use_keyring")
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_config.py -v -k response_model` → Expected: FAIL (modulo schemas inesistente).

- [ ] **Step 3: Implement `config_schemas.py`**

Modella ESATTAMENTE il dict di `get_config` attuale (copia i campi dal corpo della funzione, tipi espliciti, un modello per sezione: `LLMSection`, `STTSection`, `TTSSection`, `UISection`, `VoiceSection`, `PCAutomationSection`, `EmailSection`, aggregati in `ConfigResponse`). Applica `response_model=ConfigResponse` a `get_config` e `update_config`; `response_model=dict[str, Any]` esplicito con docstring per `get_resolved_config`/`get_config_layers`/`reload_config`/`patch_config` (shape = AliceConfig redatta, deliberatamente non fissata).

- [ ] **Step 4: Regenerate contracts and run gates**

```powershell
pytest tests/test_config.py tests/contracts/ -v
cd ..; .\scripts\gen-contracts.ps1; .\scripts\check-contracts.ps1; cd backend
```
Expected: passed; contratti rigenerati SENZA modifiche a mano in `types/generated/`.

- [ ] **Step 5: Commit**

```powershell
git add -A backend frontend/src/renderer/src/types/generated
git commit -m "feat(contracts): response model tipizzati per le route config + regen"
```

**Fine F2.** Verifica di fase: le sei suite config + contratti verdi; `lint-imports --config backend/pyproject.toml` dal repo root (nessun nuovo contratto violato); `ruff check backend/`; `mypy backend/` zero errori nuovi; smoke manuale: PATCH persona con provider openrouter attivo → `GET /api/config` conserva provider e `configured=true` (il bug originale è morto).

---

## Fase F3 — Frontend: diff-save e flag derivati

### Task 13: diff-save nello store settings

**Files:**
- Modify: `frontend/src/renderer/src/stores/settings.ts` (deep-watch → diff; `useKeyring` rimosso da tipi/default/payload/load; flag da risposta)
- Test: `frontend/src/renderer/src/stores/settings-diff.spec.ts` (nuovo; stile di `stores/chat-cost.spec.ts` e `stores/openrouter.spec.ts`)

**Interfaces:**
- Produces: `buildConfigPayload(): ConfigUpdatePayload` (estratta e esportata per i test: il body nested COMPLETO che oggi costruisce `saveSettings`), `diffConfigPayload(prev, next): Partial<ConfigUpdatePayload>` (esportata: confronto per sezione+chiave, sezioni vuote omesse, ritorna `{}` se nulla è cambiato).
- Consumes: `configApi.updateConfig` invariata; risposta = shape `GET /config`.

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/renderer/src/stores/settings-diff.spec.ts
import { describe, expect, it } from 'vitest'
import { diffConfigPayload } from './settings'
import type { ConfigUpdatePayload } from './settings'

const base: ConfigUpdatePayload = {
  llm: { temperature: 0.7, max_tokens: -1, provider: 'lmstudio' },
  ui: { theme: 'dark', language: 'it' },
  email: { enabled: false, imap_port: 993 }
}

describe('diffConfigPayload', () => {
  it('returns only the changed keys, dropping untouched sections', () => {
    const next: ConfigUpdatePayload = {
      llm: { temperature: 0.9, max_tokens: -1, provider: 'lmstudio' },
      ui: { theme: 'dark', language: 'it' },
      email: { enabled: false, imap_port: 993 }
    }
    expect(diffConfigPayload(base, next)).toEqual({ llm: { temperature: 0.9 } })
  })

  it('returns an empty object when nothing changed', () => {
    expect(diffConfigPayload(base, structuredClone(base))).toEqual({})
  })

  it('compares arrays by value', () => {
    const prev: ConfigUpdatePayload = {
      llm: { openrouter_favorites: ['a/b'] }
    }
    const next: ConfigUpdatePayload = {
      llm: { openrouter_favorites: ['a/b', 'c/d'] }
    }
    expect(diffConfigPayload(prev, next)).toEqual({
      llm: { openrouter_favorites: ['a/b', 'c/d'] }
    })
  })

  it('never resurrects keys absent from the next payload', () => {
    const prev: ConfigUpdatePayload = { email: { enabled: true, imap_port: 1 } }
    const next: ConfigUpdatePayload = { email: { enabled: true } }
    expect(diffConfigPayload(prev, next)).toEqual({})
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run (da `frontend/`): `npx vitest run src/renderer/src/stores/settings-diff.spec.ts`
Expected: FAIL (`diffConfigPayload` non esportata).

- [ ] **Step 3: Implement diff-save in `settings.ts`**

1. Definisci ed esporta i tipi/helper (fuori dallo store, testabili puri):

```typescript
/** Nested partial body accepted by PUT /api/config (sections -> snake_case keys). */
export type ConfigUpdatePayload = Record<string, Record<string, unknown>>

/** Value-equality for JSON-ish leaves (arrays compared by content). */
function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/** Return only the keys of `next` that differ from `prev` (empty sections dropped). */
export function diffConfigPayload(
  prev: ConfigUpdatePayload,
  next: ConfigUpdatePayload
): ConfigUpdatePayload {
  const out: ConfigUpdatePayload = {}
  for (const [section, nextKeys] of Object.entries(next)) {
    const prevKeys = prev[section] ?? {}
    const changed: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(nextKeys)) {
      if (!sameValue(prevKeys[key], value)) changed[key] = value
    }
    if (Object.keys(changed).length > 0) out[section] = changed
  }
  return out
}
```

2. Estrai da `saveSettings` la costruzione del body in `buildConfigPayload()` (stesso contenuto attuale, righe ~395-437, MENO `use_keyring` e MENO la password email — la password resta gestita a parte). Tieni una `let lastConfirmedPayload: ConfigUpdatePayload | null = null` nello store.

3. Riscrivi `saveSettings`:

```typescript
async function saveSettings(): Promise<void> {
  const emailPassword = settings.value.email.password.trim()
  const payload = buildConfigPayload()
  const diff =
    lastConfirmedPayload === null
      ? payload
      : diffConfigPayload(lastConfirmedPayload, payload)
  if (emailPassword) {
    diff.email = { ...(diff.email ?? {}), password: emailPassword }
  }
  if (Object.keys(diff).length === 0) return
  try {
    const updated = await configApi.updateConfig(diff)
    lastConfirmedPayload = payload
    applyConfigResponse(updated)   // vedi punto 4
    if (emailPassword) {
      _loadingSettings = true
      settings.value.email.password = ''
      await nextTick()
      _loadingSettings = false
    }
  } catch (err) {
    console.warn('[settings store] saveSettings failed:', err)
  }
}
```

4. Estrai da `loadSettings` la parte che copia la risposta nello stato in `applyConfigResponse(config)` (righe ~312-379, senza il blocco `useKeyring`), e chiamala sia da `loadSettings` (che poi setta `lastConfirmedPayload = buildConfigPayload()` dentro il guard `_loadingSettings`) sia da `saveSettings` — così i flag (`openrouterKeyConfigured`, `passwordConfigured`, `serviceRunning`) vengono SEMPRE dalla risposta del backend.

5. `setOpenrouterApiKey` (righe ~462-467): via l'ottimismo:

```typescript
async function setOpenrouterApiKey(key: string): Promise<void> {
  const trimmed = key.trim()
  if (!trimmed) return
  const updated = await configApi.updateConfig({
    llm: { openrouter_api_key: trimmed }
  })
  applyConfigResponse(updated)
}
```

6. Rimuovi `useKeyring` da: interfaccia settings (riga ~55), default (riga ~104), `applyConfigResponse` (ex righe 367-368), `buildConfigPayload` (ex riga 431).

- [ ] **Step 4: Run FE tests + typecheck**

```powershell
npx vitest run src/renderer/src
npm run typecheck
```
Expected: vitest verde (369+4 nuovi); typecheck pulito. Se un componente referenzia `useKeyring` il typecheck lo trova: rimuovi il riferimento (il grep in sessione non ne ha trovati nei componenti).

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/renderer/src/stores/settings.ts frontend/src/renderer/src/stores/settings-diff.spec.ts
git commit -m "feat(fe): diff-save nello store settings, flag derivati dal backend, via use_keyring"
```

---

### Task 14: persona su layer preferences + patchConfig con layer

**Files:**
- Modify: `frontend/src/renderer/src/services/api/config.ts` (righe ~37-45: parametro `layer`)
- Modify: `frontend/src/renderer/src/stores/settings.ts` (righe ~280, ~292: passa `'preferences'`)
- Test: typecheck + vitest esistenti (nessun nuovo spec: la funzione è un passthrough HTTP)

**Interfaces:**
- Produces: `patchConfig(path: string, value: unknown, layer: 'preferences' | 'user' | 'system' | 'runtime' = 'preferences')`.

- [ ] **Step 1: Update `services/api/config.ts`**

```typescript
patchConfig: (
  path: string,
  value: unknown,
  layer: 'preferences' | 'user' | 'system' | 'runtime' = 'preferences'
): Promise<Record<string, unknown>> =>
  request('/config', {
    method: 'PATCH',
    body: JSON.stringify({ path, value, layer })
  }),
```

(adatta la chiamata `request` allo stile reale del file — rileggilo prima di editare.)

- [ ] **Step 2: Update the two call-sites in `settings.ts`**

`saveAgentPersona` (riga ~280) e `saveAgentTierGuidance` (riga ~292): il default `'preferences'` basta — nessun argomento extra necessario; verifica solo che il typecheck passi.

- [ ] **Step 3: Typecheck + run + commit**

```powershell
npm run typecheck; npm run lint
git add frontend/src/renderer/src/services/api/config.ts frontend/src/renderer/src/stores/settings.ts
git commit -m "feat(fe): patchConfig con layer esplicito, persona agente su preferences"
```

---

### Task 15: verifica finale end-to-end e gate completi

**Files:**
- Nessun file nuovo (fix eventuali emersi dai gate)

- [ ] **Step 1: Full backend gates**

```powershell
# da backend/ (background, la suite dura 15-20+ min — MAI in foreground da subagent)
pytest tests/ -q
ruff check .
mypy .
# dal repo root
lint-imports --config backend/pyproject.toml
.\scripts\check-contracts.ps1
```
Expected: pytest tutto verde tranne il debito censito preesistente (`test_plugins_enabled_list` se ancora presente); ruff/mypy zero errori NUOVI.

- [ ] **Step 2: Full frontend gates**

```powershell
# da frontend/
npm run typecheck; npm run lint; npx vitest run
```
Expected: tutti verdi.

- [ ] **Step 3: E2E manuale con l'utente (checklist)**

1. Avvia backend+frontend (`.\scripts\start-dev.ps1`).
2. Settings → Provider: incolla la API key OpenRouter reale → il badge crediti appare; `python -c "import keyring; print(bool(keyring.get_password('alice','llm.openrouter_api_key')))"` → `True`; la tabella `user_preferences` NON contiene la key.
3. Riavvia il backend → `GET /api/config` → `openrouter_api_key_configured: true`; chat OpenRouter funziona senza reinserire nulla.
4. Settings → Email: inserisci la password → Credential Manager contiene `alice / email.password`; riavvia → email service parte da solo (`service_running: true`).
5. Modifica la persona dell'agente → riavvia → persona conservata; provider ancora openrouter (regressione split-brain).
6. Cambia SOLO il tema → nella tabella `user_preferences` si aggiorna SOLO `ui.theme` (verifica `updated_at` delle altre righe invariato).
7. Torna a `lmstudio` → chat locale intatta.

- [ ] **Step 4: Commit finale + handoff**

```powershell
git add -A
git commit -m "chore(settings-core): gate finali verdi, e2e verificato"
```
Scrivi l'handoff in `docs/superpowers/handoffs/2026-07-XX-settings-core-handoff.md` (stato, deviazioni dal piano, gotcha nuovi) prima di proporre il merge.

---

## Note per l'esecutore

- **Ordine vincolante:** T1→T15 (T1/T2 committabili insieme). Ogni task lascia il repo verde: se un passo rompe una suite non elencata, fermati e capisci il perché prima di procedere (systematic-debugging).
- **Righe indicative:** i numeri di riga si riferiscono allo stato del repo al merge di `feat/openrouter-provider`; verifica sempre col file reale prima di editare.
- **Doppio sistema in vita tra T7 e T11:** è deliberato (overlay legacy + layer nuovo applicano gli stessi valori). Non "ripulire in anticipo": la morte del legacy è il Task 11, atomico.
- **Mai committare segreti nei test:** solo valori fake (`sk-or-test-...`); i test non toccano MAI il keyring reale (sempre `InMemorySecretStore` o fake module).
- **Line endings:** file LF — verifica il diff prima di ogni commit (gotcha noto degli Edit su Windows).
