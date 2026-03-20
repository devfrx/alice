# OMNIA — Nuove Idee di Espansione

> Brainstorming di idee nuove (non presenti nel backlog originale).
> Organizzate per categoria con stima ROI.

---

## Produttività & Automazione

### Wake Word Always-On ⭐⭐⭐⭐⭐

Wake word detection locale (openWakeWord, tiny model CPU-only) sempre attiva in background.
L'utente dice "Omnia..." e l'app si attiva senza toccare nulla — trasforma il sistema da app
a assistente ambientale.

#### Architettura proposta

- **`WakeWordService`** — gira in thread daemon, usa `openWakeWord` (ONNX, ~5MB modello)
- Quando attivato: pubblica `EventBus("wake_word_detected")` → `STTService` avvia ascolto
- Config: `wake_word_model: str`, `sensitivity: float = 0.5`, `enabled: bool = false`
- Frontend: indicatore visivo nello status bar quando la funzione è attiva

#### Dipendenze

- `openwakeword >= 0.6` (ONNX, CPU-only, cross-platform)
- `sounddevice >= 0.4` (già potenzialmente presente per STT)

---

### Local Macro Scheduler (Cron interno) ⭐⭐⭐⭐

Sistema per schedulare "routine" OMNIA: ogni lunedì 8:00 genera briefing
(Weather + News + Calendar), ogni venerdì sera backup note, ogni sera report giornaliero.
Diverso dal Calendar plugin: agisce, non ricorda.

#### Architettura proposta

- **`SchedulerService`** — wrapper attorno ad `APScheduler` (AsyncIOScheduler), avviato
  nel lifespan FastAPI
- Una `scheduled_tasks` table in SQLite: `id, cron_expr, prompt, enabled, last_run, next_run`
- Il job esegue il `prompt` configurato attraverso il tool loop LLM interno
- **Plugin `scheduler`** con tool: `add_task`, `list_tasks`, `update_task`, `delete_task`,
  `run_now`
- Frontend: vista `SchedulerView.vue` con lista task e editor cron (con helper human-readable)

#### Dipendenze

- `apscheduler >= 3.10` (async-native, già comune in ecosistema FastAPI)

---

### Automated File Organizer ⭐⭐⭐⭐

Monitora cartelle (es. `Downloads`, `Desktop`) via `watchdog`, classifica i nuovi file
con LLM (o regole utente), li sposta/rinomina secondo policy configurabili.
Costruito sopra il `file_search` plugin esistente.

#### Architettura proposta

- **`FileOrganizerService`** — `watchdog.Observer` + handler async via `asyncio.Queue`
- Classificazione: prima tenta pattern-matching (estensione + nome), poi LLM come fallback
- Tutte le azioni sono **staged** (pending confirmation) prima di essere eseguite —
  mai movimenti automatici senza approvazione esplicita
- Tool: `add_watch_folder`, `remove_watch_folder`, `set_rule`, `list_pending_actions`,
  `approve_action`, `reject_action`
- Schema DB: `watch_folders(id, path, enabled)`, `organizer_rules(id, pattern, destination)`,
  `pending_actions(id, action_type, source, destination, created_at)`

#### Dipendenze

- `watchdog >= 4.0` (file system events, cross-platform)

---

### Clipboard History con Semantic Search ⭐⭐⭐⭐

Versione evoluta del `clipboard` plugin: intercetta i cambiamenti degli appunti, mantiene
uno storico persistente, permette ricerca semantica ("trovami quella cosa sulle API che
avevo copiato ieri"). Usa `sqlite-vec` già presente.

#### Architettura proposta

- **`ClipboardHistoryService`** — polling ogni 500ms su `pyperclip`, dedup hash SHA-256
- Schema DB: `clipboard_entries(id, content, content_hash, source_app, created_at)` +
  `clip_vectors` (sqlite-vec)
- Max N entry configurabile (default 500), FIFO eviction
- Tool: `search_clipboard_history`, `get_recent_clips`, `pin_clip`, `delete_clip`
- Opt-in per sicurezza: disabilitato di default, attivabile dalle impostazioni

#### Dipendenze

- `pyperclip >= 1.8` (già usato dal clipboard plugin)
- `sqlite-vec` + `fastembed` (già presenti)

---

### Script Generator + Task Scheduler Windows ⭐⭐⭐

L'utente descrive in linguaggio naturale cosa vuole automatizzare → OMNIA genera lo script
PowerShell con LLM → lo schedula in Windows Task Scheduler via `schtasks.exe`.

#### Architettura proposta

- **Plugin `win_automation`** — wrappa `subprocess` con `schtasks /create` / `schtasks /query`
- Generazione script: LLM con system prompt specializzato su PowerShell sicuro
- Tutti gli script generati mostrati all'utente per review prima dello scheduling
  (`requires_confirmation=True`, `risk_level="dangerous"`)
- Tool: `create_scheduled_script`, `list_scheduled_scripts`, `delete_scheduled_script`,
  `run_script_now`

#### Dipendenze

- Nessuna nuova — `subprocess` stdlib + LLM già presente

---

## Comunicazione & Integrazione

### Voice Cloning Wizard ⭐⭐⭐

Wizard UI per creare un profilo vocale personalizzato con XTTS v2 (già supportato).
OMNIA parlerà con la voce dell'utente.

#### Architettura proposta

- **`VoiceCloningWizard.vue`** — stepper a 3 passi: registra 15s audio, preview sintesi,
  salva profilo in `models/tts/clones/{name}/`
- Backend: endpoint `/api/tts/clone` che riceve audio WAV, lo normalizza, lo salva come
  reference audio per XTTS
- `TTSService` esteso: `speaker_wav` parameter per XTTS quando un clone è selezionato
- Le voci clone appaiono nel selettore TTS nelle impostazioni

#### Dipendenze

- XTTS v2 già presente come opzione TTS
- `soundfile >= 0.12` (già potenzialmente presente)

---

### Meeting Transcription & Summary ⭐⭐⭐⭐

Registra un meeting (file audio o microfono live), trascrive con `faster-whisper`,
estrae: action items, decisioni, follow-up, partecipanti citati. Diverso da Voice Journal:
focus sul lavoro strutturato con output strutturato.

#### Architettura proposta

- **`MeetingService`** — orchestratore: STT → chunking → LLM extraction strutturata
- Output strutturato: `MeetingReport(title, date, participants, summary, action_items,
  decisions, transcript_path)`
- I report salvati automaticamente nelle Note (se Note System attivo) o come file Markdown
  in `data/meetings/`
- Tool: `transcribe_meeting(file_path)`, `transcribe_live_meeting()`, `get_meeting_report(id)`,
  `list_meetings()`
- Frontend: `MeetingView.vue` con drag-and-drop file + report formattato

#### Dipendenze

- `faster-whisper` (già presente per STT)
- `sounddevice` (già presente)

---

## Conoscenza & Apprendimento

### Personal Knowledge Graph ⭐⭐⭐⭐

Visualizzazione grafica dei wikilinks/backlinks fra le Note (Note System Fase 13).
Vista separata stile Obsidian Graph View.

#### Architettura proposta

- **`GraphView.vue`** — vista standalone, usa `vis-network` o `d3-force`
- I dati del grafo vengono da un endpoint REST `/api/notes/graph` che restituisce
  `{nodes: [{id, title, tags}], edges: [{source, target, type}]}`
- Nodi colorati per tag, dimensione proporzionale al numero di connessioni
- Click su nodo → apre la nota nell'editor
- Filtri: per tag, per folder, per data creazione

#### Dipendenze

- `vis-network >= 9.0` (npm) o `d3 >= 7.0` (già potenzialmente presente)
- Zero dipendenze backend nuove

---

### Flashcard System (Spaced Repetition) ⭐⭐⭐

L'LLM genera flashcard da qualsiasi contenuto (note, documenti, messaggi di chat).
Algoritmo SM-2 per schedulare le revisioni.

#### Architettura proposta

- **`FlashcardService`** — gestisce `data/flashcards.db`
- Schema: `decks(id, name, source_note_id)`, `cards(id, deck_id, front, back, ease_factor,
  interval_days, due_date, reps)`
- Algoritmo SM-2 puro in Python (no dipendenze esterne)
- Tool: `generate_flashcards(source)`, `start_review_session()`, `rate_card(id, quality)`,
  `get_due_cards()`, `list_decks()`
- Frontend: `FlashcardView.vue` — modalità studio (flip card animata) + statistiche

#### Dipendenze

- Nessuna nuova — SM-2 implementato in Python, SQLite già presente

---

### RSS Aggregator con LLM Curation ⭐⭐⭐

Abbonamento a feed RSS; l'LLM filtra per rilevanza personale e genera briefing mattutino.
Diverso dal `news` plugin (abbonamento continuo, non ricerca on-demand).

#### Architettura proposta

- **`RSSService`** — fetch periodico (configurable interval) via `feedparser` + `httpx`
- Schema DB: `rss_feeds(id, url, name, category, last_fetched)`,
  `rss_items(id, feed_id, title, url, summary, published_at, relevance_score, read)`
- Scoring rilevanza: embedding similarity rispetto a un "profilo interessi" dell'utente
  (vettore medio dei contenuti che ha letto/approvato)
- Tool: `add_feed`, `remove_feed`, `get_unread`, `mark_read`, `get_briefing`
- Scheduler integrato: aggiorna feed ogni ora, genera briefing su richiesta o su schedule

#### Dipendenze

- `feedparser >= 6.0` (parsing RSS/Atom)
- `sqlite-vec` + `fastembed` (già presenti per scoring)

---

### Podcast & Lecture Digester ⭐⭐⭐

Carica un file audio lungo (podcast, lezione, talk) → trascrizione `faster-whisper`
long-form → riassunto, concetti chiave, timeline con timestamp, domande di ripasso.

#### Architettura proposta

- Basato su `MeetingService` ma ottimizzato per contenuti monologici lunghi (1-3 ore)
- Chunking intelligente: divide per silenzio naturale, mantiene contesto tra chunk
- Output: `PodcastDigest(title, duration, summary, key_concepts[], timeline[], review_questions[])`
- Integrazione con Flashcard System: può generare un deck da un podcast automaticamente
- Salva in `data/digests/` + opzionalmente nelle Note

#### Dipendenze

- `faster-whisper` (già presente)
- Nessuna altra dipendenza nuova

---

## Monitoring & Analytics

### Personal Time Tracker ⭐⭐⭐⭐

Monitora il processo in foreground (finestra attiva) via `win32gui` + `psutil`,
aggrega tempo per applicazione/categoria, genera report via Chart plugin.
Completamente opt-in, dati 100% locali.

#### Architettura proposta

- **`TimeTrackerService`** — polling ogni 5s sul foreground window, aggrega in sessioni
- Schema DB: `app_sessions(id, app_name, window_title, category, start_at, end_at, duration_s)`
- Categorizzazione: regole utente (es. "chrome → Browsing", "vscode → Development") +
  LLM come fallback opzionale
- Tool: `get_time_report(period)`, `get_top_apps(n)`, `set_category(app, category)`,
  `get_focus_score()` (% tempo su app "produttive" vs distrazioni)
- Frontend: widget nelle impostazioni + chart integrato

#### Dipendenze

- `pywin32 >= 306` (win32gui — solo Windows, già nella stack pc_automation)
- `psutil` (già presente per system_info)

---

### Local Model Performance Dashboard ⭐⭐⭐

Benchmark automatico dei modelli LLM in LM Studio: velocità (tok/s), VRAM, latenza
primo token, qualità su prompt campione. Confronto fra modelli nel Chart plugin.

#### Architettura proposta

- **`ModelBenchmarkService`** — suite di test standard (prompt fissi, temperatura 0)
- Metriche raccolte: `tokens_per_second`, `ttft_ms` (time to first token), `vram_peak_mb`,
  `context_length_tested`, `model_name`, `benchmark_date`
- Schema DB: `model_benchmarks(id, model_name, ...metriche..., created_at)`
- Integrazione con `lmstudio_service.py` (usa API esistente) e `vram_monitor.py`
- Route REST `/api/models/benchmark/{model_id}` — esegue benchmark in background task
- Frontend: tabella comparativa + radar chart (tok/s, VRAM, latenza)

#### Dipendenze

- Nessuna nuova

---

### Personal Finance Intelligence ⭐⭐⭐

Importa estratti conto (CSV/OFX/QIF), categorizza le transazioni con LLM, visualizza
trend di spesa nel Chart plugin. Zero API esterne.

#### Architettura proposta

- **`FinanceService`** — parser multi-formato (`ofxparse` per OFX, stdlib csv per CSV)
- Schema DB: `accounts(id, name, type, currency)`,
  `transactions(id, account_id, date, amount, description, category, tags)`
- Categorizzazione: prima fuzzy-match su descrizione (regole statiche), poi LLM
- Tool: `import_statement`, `get_spending_by_category`, `get_monthly_summary`,
  `search_transactions`, `set_category_rule`
- Nessun dato finanziario mai inviato all'LLM senza consenso esplicito dell'utente

#### Dipendenze

- `ofxparse >= 0.21` (parsing OFX/QFX)
- `csv` stdlib

---

## UI/UX & Esperienza

### Persona System ⭐⭐⭐⭐⭐

L'utente definisce "persona" diverse per OMNIA con contesti d'uso differenti.
Ogni persona ha: system prompt dedicato, voce TTS, set di plugin attivi, temperatura LLM.
Switching istantaneo dalla barra superiore.

#### Architettura proposta

- **`PersonaService`** — gestisce `data/personas.db`: `personas(id, name, description,
  system_prompt, tts_voice, temperature, active_plugins[], color_theme, icon)`
- Persona di default: "Assistente Generale" (comportamento attuale)
- Al cambio persona: `EventBus("persona_changed", persona_id)` → ricarica config runtime
  senza restart
- Tool: `create_persona`, `update_persona`, `switch_persona`, `list_personas`,
  `get_current_persona`
- Frontend: `PersonaSwitcher.vue` in header — avatar colorato + dropdown rapido
- Le persona sono esportabili/importabili come JSON (condivisibili)

#### Dipendenze

- Nessuna nuova

---

### Proactive Assistant Mode ⭐⭐⭐⭐

OMNIA osserva i pattern dell'utente e interviene proattivamente: avvisi, suggerimenti
contestuali, reminder intelligenti. Architettura event-driven sul `EventBus` esistente.

#### Architettura proposta

- **`ProactiveEngine`** — subscriber `EventBus`, valuta regole configurabili
- Regole esempi: "riunione tra 10 min → notifica + prepara briefing partecipante",
  "stesso documento aperto da >2h → suggerisci pausa", "nessuna attività da 30min → salva stato"
- Ogni suggerimento appare come "proactive message" nella chat (tipo messaggio distinto)
- Opt-in per categoria di regola, con controllo granulare dell'utente
- `ProactiveConfig`: `enabled: bool`, regole attive per categoria

#### Dipendenze

- Riusa `EventBus`, `CalendarPlugin`, `TimeTrackerService`, `MemoryService` esistenti

---

### Desktop Widget Overlay ⭐⭐⭐

Finestra Electron secondaria, semi-trasparente, always-on-top, miniaturizzata.
Mostra status OMNIA, orologio, prossimo evento, meteo. Click per aprire app principale.

#### Architettura proposta

- Secondo `BrowserWindow` in `src/main/index.ts`: `frame: false`, `transparent: true`,
  `alwaysOnTop: true`, `skipTaskbar: true`
- Posizione salvata e ripristinata (angolo schermo, drag per riposizionare)
- Componente Vue `WidgetOverlay.vue` — mini-UI con: avatar status, orologio, next event,
  meteo corrente, pulsante mute
- IPC channels: main window → widget per sync stato

#### Dipendenze

- Nessuna nuova (Electron già presente)

---

### Conversation Export ⭐⭐⭐

Esporta conversazioni in PDF formattato, HTML con syntax highlighting, o Markdown.
Le tool call possono essere incluse o escluse.

#### Architettura proposta

- Route REST: `GET /api/conversations/{id}/export?format=pdf|html|md&include_tools=bool`
- PDF: `weasyprint` con template HTML/CSS dedicato
- HTML: template Jinja2 con Prism.js per syntax highlighting dei code block
- Markdown: serializzazione diretta dei messaggi con frontmatter YAML (title, date, model)
- Frontend: pulsante "Esporta" nella toolbar della conversazione con selettore formato

#### Dipendenze

- `weasyprint >= 62.0` (PDF rendering via HTML/CSS)
- `jinja2` (già presente in FastAPI)

---

## Creatività & Sperimentale

### Auto-Journaling Serale ⭐⭐⭐

Ogni sera OMNIA genera automaticamente un diario sintetizzando: eventi Calendar,
conversazioni avute, task completati, app più usate. Zero input utente.

#### Architettura proposta

- Job schedulato (via `SchedulerService`) ore 22:30 ogni giorno
- Raccoglie dati da: Calendar (eventi giornata), `ConversationFileManager` (messaggi del giorno),
  `TimeTrackerService` (top app), completamenti task dallo Scheduler
- LLM sintetizza in narrazione fluente in prima persona
- Salva nelle Note come `Journal/YYYY-MM-DD.md` con tag `#journal`
- Configurabile: ora esecuzione, sezioni incluse, tono (formale/informale)

#### Dipendenze

- Riusa `SchedulerService`, Note System, Calendar, TimeTracker esistenti

---

### Real-Time Tone Analyzer ⭐⭐⭐

Analizza in tempo reale il tono dei testi scritti dall'utente (formale/informale,
assertivo/passivo, positivo/negativo) e suggerisce riformulazioni.

#### Architettura proposta

- Endpoint WebSocket o REST: `POST /api/analyze/tone` con `{text: string}`
- LLM con prompt specializzato: risponde con `{tone, scores, suggestions[]}`
- Integrazione nell'Email Assistant: analisi automatica prima dell'invio
- Frontend: `ToneIndicator.vue` — badge colorato nel composer con tooltip suggerimenti
- Debounce 1s per non saturare LLM durante la digitazione

#### Dipendenze

- Nessuna nuova

---

### Local Fine-tune Dataset Collector ⭐⭐

L'utente segnala risposte scorrette (thumbs down + correzione) → accumulate in JSONL
per fine-tuning futuro (LoRA). Export tool genera dataset pronto per training.

#### Architettura proposta

- Schema DB: `feedback_entries(id, conversation_id, message_id, original_response,
  corrected_response, feedback_type, created_at)`
- Tool: `export_finetune_dataset(format)` — genera JSONL in formato Alpaca/ShareGPT
- Frontend: pulsante thumbs down su ogni messaggio → modal per inserire correzione
- I dati restano locali, export esplicito solo su richiesta

#### Dipendenze

- Nessuna nuova

---

### Ambient Sound Engine ⭐⭐

OMNIA gestisce suoni ambientali (white noise, pioggia, lo-fi) con duck automatico
quando il TTS parla.

#### Architettura proposta

- **`AmbientSoundService`** — `sounddevice` per playback di file audio in loop
- Duck automatico: volume -70% quando `EventBus("tts_started")`, ripristino su
  `EventBus("tts_finished")`
- Libreria di suoni built-in (file audio bundlati nell'app, ~5MB totali)
- Tool: `play_ambient(sound_name)`, `stop_ambient()`, `set_volume(level)`,
  `list_ambient_sounds()`
- Frontend: controllo rapido nel widget overlay

#### Dipendenze

- `sounddevice >= 0.4`
- `soundfile >= 0.12`

---

### LAN P2P Sync ⭐⭐

Sincronizzazione locale via LAN di Note, Conversazioni e Preferenze tra più PC.
Nessun cloud, nessun server esterno.

#### Architettura proposta

- Discovery via mDNS (`zeroconf`) — ogni istanza OMNIA si annuncia sulla LAN
- Sync protocol: client pull-based, confronto hash per ogni entità, trasferimento delta
- Crittografia: TLS con certificato self-signed generato al primo avvio (TOFU — trust on
  first use, come SSH)
- Scope sync configurabile: solo Note, solo Preferenze, o tutto
- Tool: `list_discovered_instances`, `start_sync(instance_id)`, `get_sync_status`

#### Dipendenze

- `zeroconf >= 0.131`
- `cryptography >= 42.0` (già potenzialmente presente)

---

## Plugin Integrazioni Specifiche

| Plugin | Integrazione | Dipendenze | ROI |
|--------|-------------|------------|-----|
| **Obsidian Vault Sync** | Legge/scrive vault Obsidian esistente via file system | Nessuna nuova | ⭐⭐⭐⭐ |
| **Bitwarden Local** | Legge credenziali da Bitwarden CLI locale (no cloud API) | `subprocess` (già presente) | ⭐⭐⭐⭐ |
| **GitHub Copilot via MCP** | Espone tool OMNIA a GitHub Copilot tramite MCP server | MCP client già presente | ⭐⭐⭐ |
| **Spotify Local** | Controllo Spotify via API locale (estende `media_control`) | `spotipy` | ⭐⭐⭐ |
| **Radarr/Sonarr** | Gestione media server locale via REST API | `httpx` (già presente) | ⭐⭐ |
| **Notion Import** | Importa pagine Notion via export locale (HTML/Markdown) | `beautifulsoup4` (già presente) | ⭐⭐ |
| **Home Assistant Extended** | Estende `home_automation` con automazioni complesse e scene | `httpx` (già presente) | ⭐⭐⭐ |

---

## Riepilogo Priorità

| Idea | Categoria | ROI | Dipendenze nuove |
|------|-----------|-----|-----------------|
| Wake Word Always-On | Produttività | ⭐⭐⭐⭐⭐ | openwakeword |
| Persona System | UX | ⭐⭐⭐⭐⭐ | nessuna |
| Personal Time Tracker | Monitoring | ⭐⭐⭐⭐ | pywin32 (già presente) |
| Macro Scheduler | Automazione | ⭐⭐⭐⭐ | apscheduler |
| Automated File Organizer | Produttività | ⭐⭐⭐⭐ | watchdog |
| Clipboard History Semantico | Produttività | ⭐⭐⭐⭐ | nessuna nuova |
| Meeting Transcription | Comunicazione | ⭐⭐⭐⭐ | nessuna nuova |
| Personal Knowledge Graph | Conoscenza | ⭐⭐⭐⭐ | vis-network (npm) |
| Proactive Assistant Mode | UX | ⭐⭐⭐⭐ | nessuna |
| Flashcard System | Apprendimento | ⭐⭐⭐ | nessuna |
| RSS Aggregator | Conoscenza | ⭐⭐⭐ | feedparser |
| Podcast Digester | Conoscenza | ⭐⭐⭐ | nessuna nuova |
| Personal Finance | Monitoring | ⭐⭐⭐ | ofxparse |
| Desktop Widget Overlay | UX | ⭐⭐⭐ | nessuna |
| Conversation Export | UX | ⭐⭐⭐ | weasyprint |
| Voice Cloning Wizard | Comunicazione | ⭐⭐⭐ | soundfile |
| Auto-Journaling Serale | Creatività | ⭐⭐⭐ | riusa esistenti |
| Real-Time Tone Analyzer | Comunicazione | ⭐⭐⭐ | nessuna |
| Model Performance Dashboard | Monitoring | ⭐⭐⭐ | nessuna |
| Script Generator Win | Automazione | ⭐⭐⭐ | nessuna |
| Fine-tune Dataset Collector | Sperimentale | ⭐⭐ | nessuna |
| Ambient Sound Engine | UX | ⭐⭐ | sounddevice, soundfile |
| LAN P2P Sync | Infrastruttura | ⭐⭐ | zeroconf |
