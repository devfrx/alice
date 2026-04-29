# FASE 1 — Finalizzazione Alice (prodotto desktop)

> Obiettivo: Alice diventa un applicativo desktop installabile e usabile da utente non-tecnico.
> Tutti i servizi (LLM, STT, TTS, generazione, ecc.) sono orchestrati dall'app, con startup/
> shutdown/healthcheck robusti. La memoria episodica viene formalizzata; quella long-term viene
> **isolata dietro un'astrazione** in vista della Fase 3 (NON rimossa ora).

## 1. Scope esplicito

### IN scope
- Packaging Electron (installer Windows MSI/NSIS) con backend Python embedded.
- **Service Orchestrator**: gestisce LM Studio (rilevamento + opzionale autostart), STT, TTS, Trellis, Qdrant locale (se usato), VRAM monitor.
- **Lifecycle manager**: startup ordinato, healthcheck, shutdown pulito, restart automatico dei servizi caduti.
- **Configurazione centralizzata** unificata (oggi sparsa tra `config/default.yaml`, `.env`, settings runtime).
- **Memoria episodica formalizzata**: chat history (esistente), working memory di sessione, tool state, cancel events.
- **Astrazione `KnowledgeBackend`** introdotta (implementazione `QdrantBackend` che wrappa l'attuale `MemoryService` + `NoteService` su Qdrant).
- Build CI riproducibile.

### OUT of scope (rinviato a fasi successive)
- Integrazione con Continuum (Fase 3).
- Rimozione `NoteService`/`MemoryService` long-term (Fase 3, dopo validazione).
- Multi-user, sync cloud, mobile.

## 2. Packaging desktop

### Stack
- **Electron** (già presente) — wrapper UI Vue 3.
- **Backend Python embedded**: scelta da fare tra:
  - **(A) `pyinstaller --onedir`** — semplice, debuggabile, ~250-400MB. **Raccomandato per v1**.
  - **(B) `python-build-standalone` + venv shipato** — più flessibile per update modelli, più complesso.
  - **(C) WinPython embedded** — leggero ma fragile su update.

> **Attenzione native deps** (impattano la spec PyInstaller):
> - `qdrant_client` → pure Python, nessun problema.
> - `faster-whisper` → richiede `ctranslate2` (DLL native + modelli a runtime). Serve `--add-binary` esplicito.
> - `piper-tts` → binari nativi + voci `.onnx` a runtime.
> - `fastembed` (fallback) → richiede `onnxruntime` (DLL).
> - **Plugin discovery è statico per design** ([backend/core/plugin_manager.py](backend/core/plugin_manager.py)): ogni plugin si auto-registra nel `PLUGIN_REGISTRY` a import time, e `PluginManager.startup()` importa esplicitamente i moduli elencati in `config.plugins.enabled`. Quindi PyInstaller deve solo includerli come `hiddenimports`, non scansionare cartelle. La modalità dinamica (`ALICE_PLUGIN_DISCOVERY=dynamic`) è limitata al `development` e non rileva nel build.
>
> Mitigazione: smoke test in CI che importa esplicitamente ogni plugin abilitato dopo il packaging.

### Layout installato
```
%LOCALAPPDATA%\Alice\
├── app\                       # Electron + frontend bundle
├── backend\                   # PyInstaller dist (python.exe + .pyd + libs)
├── config\                    # default.yaml + user.yaml override
├── models\                    # llm/stt/tts/  (download on-demand)
└── data\                      # conversations/, alice.db, episodic.db
```

### Modelli AI
- **Non bundlati** nell'installer (troppo pesanti).
- **First-run wizard**: scarica modelli minimi (Whisper-tiny, Piper voice, embedding model) con progress bar.
- LLM: l'utente sceglie tra "usa LM Studio già installato" o "scarica build embedded".

### Auto-update
- `electron-updater` per il guscio (frontend + backend Python).
- Modelli: update separato gestito dall'app (manifest versionato in `models/MANIFEST.json`).

## 3. Service Orchestrator

Componente nuovo: `backend/core/service_orchestrator.py`.

### Responsabilità
- Conoscere la lista dei **servizi gestiti** (LM Studio, STT, TTS, Trellis, …) e il loro stato.
- Avviarli in ordine corretto (rispettando dipendenze).
- Polling di health (`/health` HTTP, processi vivi, porte aperte).
- Restart con backoff esponenziale se cadono.
- Notificare il frontend via WebSocket (`service.status` event).

### Modello dei servizi

```python
class ManagedService(Protocol):
    name: str
    kind: Literal["external_process", "http_endpoint", "internal"]
    depends_on: list[str]

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self) -> ServiceHealth: ...

@dataclass
class ServiceHealth:
    status: Literal["up", "degraded", "down", "starting"]
    detail: str | None
    last_check: datetime
```

### Servizi previsti

| Service | Kind | Note |
|---|---|---|
| `lmstudio` | `http_endpoint` | Solo health check; user-managed (non avviato da Alice) |
| `stt_whisper` | `internal` | Già caricato in-process |
| `tts_piper` | `internal` | Già in-process |
| `trellis` | `external_process` | Avviato via `start-trellis.ps1` esistente |
| `vram_monitor` | `internal` | Già esistente |
| `qdrant` | `external_process` o `embedded` | Oggi: `data/qdrant/` come storage embedded. In packaging: usare modalità embedded di `qdrant_client` o avviare binary Qdrant come child process |
| `knowledge_backend` | `internal` | Wrapper Qdrant (Fase 1) o Continuum HTTP (Fase 3) |

### Lifecycle
- **Startup**: `service_orchestrator.start_all()` in topological order (depends_on).
- **Shutdown**: reverse order, timeout per service, force-kill solo come ultima risorsa.
- **Restart policy**: per-service config (`always`, `on-failure`, `never`).

## 4. Configurazione centralizzata

### Problema attuale
Settings sparse: `config/default.yaml`, env vars, `preferences_service`, runtime overrides nel frontend.

### Soluzione: layered config con precedenza chiara

```
defaults (config/default.yaml)
  ↓ override
system  (%LOCALAPPDATA%\Alice\config\system.yaml)   # admin/install-time
  ↓ override
user    (%LOCALAPPDATA%\Alice\config\user.yaml)     # UI settings page
  ↓ override
runtime (in-memory, da WebSocket events)            # toggle effimeri
```

### Implementazione
- Estendere [backend/core/config.py](backend/core/config.py) con `ConfigLayer` enum + merge ordinato.
- Esporre `ConfigService.get(path)` e `ConfigService.set(path, value, layer=USER)`.
- Frontend store `settings` legge sempre la versione *risolta* (merged), scrive su layer `user`.
- Hot-reload: emit `config.changed` event; servizi interessati si re-inizializzano.

> **Caveat su `pydantic-settings`**: la struttura attuale usa `BaseSettings` con env prefix `ALICE_*` e nesting `__`. Il merge layered va costruito **sopra** pydantic-settings (caricando manualmente i 4 livelli e passandoli come `dict` a `BaseSettings(**merged)`), oppure introducendo un wrapper `LayeredConfigService` che mantiene i 4 layer separati e ricostruisce un `Config` validato a ogni `set`. Questa è una scelta di design da prendere all'inizio della Fase 1.

## 5. Memoria episodica formalizzata

### Cosa rientra qui (resta in Alice, NON va in Continuum)
| Dato | Storage attuale | Storage target |
|---|---|---|
| Conversation history | SQLModel (`alice.db`) | **Invariato** |
| Tool execution state | in-memory + DB messages | **Invariato** |
| Cancel events | in-memory (`asyncio.Event`) | **Invariato** |
| Working memory di sessione | `MemoryService` con scope=`session` | **Invariato** |
| User preferences runtime | `preferences_service` | Spostato sotto `ConfigService.user` |
| Audit log | `audit` route | **Invariato** |

### Cosa esce dalla memoria episodica (target Fase 3)
| Dato | Da | A |
|---|---|---|
| Note utente | `NoteService` | Continuum |
| Memorie long-term | `MemoryService` scope=`long_term` | Continuum |
| User facts persistenti | `MemoryService` scope=`user_fact` | Continuum |

## 6. Astrazione `KnowledgeBackend` (preparazione Fase 3)

> **In Fase 1 si introduce solo l'interfaccia + l'adapter sull'esistente.** Non si tocca ancora Continuum.

```python
# backend/services/knowledge/protocol.py
class KnowledgeBackend(Protocol):
    name: str

    async def search(
        self, query: str, *, k: int = 5, filters: dict | None = None
    ) -> list[KnowledgeHit]: ...

    async def get(self, doc_id: str) -> KnowledgeDoc | None: ...
    async def create(self, doc: KnowledgeDocCreate) -> KnowledgeDoc: ...
    async def update(self, doc_id: str, patch: KnowledgeDocPatch) -> KnowledgeDoc: ...
    async def delete(self, doc_id: str) -> None: ...

    async def health(self) -> ServiceHealth: ...
```

### Adapter esistente: `QdrantBackend`
- Path nuovo: `backend/services/knowledge/qdrant_backend.py`.
- **Wrappa** (non duplica) `MemoryService` + `NoteService` esistenti dietro l'interfaccia.
- Le collezioni Qdrant attuali (`COLLECTION_MEMORY`, `COLLECTION_NOTES` in [qdrant_service.py](backend/services/qdrant_service.py)) restano invariate.
- I plugin `notes` e `memory` chiamano `KnowledgeBackend`, non più i service direttamente.
- Risultato: in Fase 3, swap dell'implementazione = una riga di config.

### Mappatura `KnowledgeDoc.kind` → service esistente
| `kind` | Service Alice attuale | Collezione Qdrant |
|---|---|---|
| `note` | `NoteService` | `COLLECTION_NOTES` |
| `memory`, `fact` | `MemoryService` (scope=long_term/user_fact) | `COLLECTION_MEMORY` |
| `session_memory` | `MemoryService` (scope=session) | `COLLECTION_MEMORY` (TTL) |

Il `QdrantBackend` instrada al service giusto in base a `kind`. **Niente migrazione dati** in Fase 1: si lavora sui dati esistenti.

### Convenzione documenti
```python
@dataclass
class KnowledgeDoc:
    id: str
    kind: Literal["note", "memory", "fact"]
    title: str | None
    content: str
    tags: list[str]
    metadata: dict[str, Any]   # source=alice|user, conversation_id=..., etc.
    created_at: datetime
    updated_at: datetime
```

## 7. Build & distribuzione

### Pipeline (CI/CD locale o GitHub Actions)
1. `pnpm/npm install` frontend → `npm run build` (Electron).
2. `uv pip install` backend → `pyinstaller backend.spec`.
3. Copia `config/default.yaml` + `system_prompt.md`.
4. `electron-builder` confeziona MSI/NSIS.
5. Sign code (eventuale, certificato self-signed in dev).
6. Pubblica release GitHub con manifest auto-update.

### Smoke test
- Headless: avvia backend, chiama `/health`, esegui chat di test, shutdown.
- E2E (Playwright via Electron): apre app, manda messaggio, verifica risposta.

## 8. Observability (base, sarà estesa in Fase 3)

- **Logging**: loguru già in uso. Aggiungere:
  - File rotante in `%LOCALAPPDATA%\Alice\logs\`.
  - Livello configurabile via UI Settings.
  - Format strutturato (JSON opzionale per debug avanzato).
- **Crash reporting**: dump non-uploaded, solo locale (privacy by design).
- **Service status panel** nel frontend: lista servizi con LED verde/giallo/rosso, ultimo health check, tasto restart.

## 9. Definition of Done — Fase 1

- [ ] Installer Windows generabile da CLI con un comando.
- [ ] Utente non-tecnico può: installare, avviare, chattare, usare voice, senza terminale.
- [ ] Tutti i servizi gestiti hanno health endpoint e compaiono nel panel.
- [ ] `KnowledgeBackend` Protocol esiste, `QdrantBackend` lo implementa wrappando `MemoryService`+`NoteService`, plugin `notes`/`memory` lo consumano.
- [ ] Config layered funzionante con UI Settings che scrive in `user.yaml`.
- [ ] Backend riavvio pulito ≤ 5 secondi.
- [ ] Crash di un servizio esterno (es. Trellis) non abbatte Alice.
- [ ] Smoke test E2E in CI.

## 10. Trade-off espliciti

| Scelta | Pro | Contro |
|---|---|---|
| PyInstaller `--onedir` | Semplice, debuggabile | Installer ~300MB |
| Modelli non bundlati | Installer leggero | First-run lento (download) |
| LM Studio non auto-avviato | Rispetta scelta utente | UX richiede passaggio manuale |
| `KnowledgeBackend` introdotto subito | Zero refactor in Fase 3 | Astrazione "vuota" finché c'è 1 sola impl |
| Config layered | Pulito, testabile | Refactor di tutti i call site di settings |

## 11. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| PyInstaller rompe import dinamici (plugin) | Hidden imports espliciti + test plugin loading in smoke test post-build |
| `ctranslate2` / `onnxruntime` DLL non risolte dopo packaging | `--collect-all` o `--add-binary` espliciti nello spec; smoke test che esegue una trascrizione di prova |
| Storage Qdrant locale incompatibile tra versioni del client | Pin versione `qdrant_client` + test di apertura collezione esistente in CI |
| Modelli pesanti spaventano l'utente | Wizard con preset "minimal/balanced/full" |
| Config refactor rompe regressioni | Migration script che legge vecchio formato → nuovo |
| Restart loop di un servizio mal configurato | Backoff + max retry + notifica UI |
| `KnowledgeBackend` astratto sembra over-engineering con 1 sola impl | Documentare esplicitamente che è preparatorio Fase 3; mantenere thin (no logica di business nell'adapter) |
