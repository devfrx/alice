# Handoff — Fase 2 (Fondamenta tool), Mossa 1 COMPLETA (feat/agent-tools-fase2)

**Data:** 2026-07-20
**Branch:** `feat/agent-tools-fase2`, HEAD di chiusura vedi ultimo commit del branch (la
sessione chiude con l'handoff; il branch parte da `72d5a5c`, HEAD congelato di Fase 1 —
**discendente**, quindi il merge di Fase 1 resta pulito). ~40 commit di mossa.
**Stato programma:** Fase 2 di 9 — Mossa 1 (backend) COMPLETA, gate tutti verdi.
La fase chiude con la **Mossa 2** (wire/FE/vision/eval, piano da scrivere).
**MERGE DI FASE 1 ANCORA PENDENTE:** `feat/agent-engine-fase1` congelato @ `72d5a5c`
in attesa dello smoke 2 dell'utente (errori/Stop con provider saturo) e del suo OK
esplicito (skill `finishing-a-development-branch`; la baseline eval si aggiorna al merge).
**Spec di fase:** `docs/superpowers/specs/2026-07-18-agent-v2-fase2-fondamenta-tool-design.md`
**Piano Mossa 1:** `docs/superpowers/plans/2026-07-18-agent-v2-fase2-mossa1.md` (18 task,
tutti eseguiti; la sezione "Cosa NON fa questa mossa" è il perimetro della Mossa 2)
**Programma:** `docs/superpowers/specs/2026-07-16-agent-v2-program-design.md`
**Ledger locale:** `.superpowers/sdd/progress.md` (gitignored, su questa macchina) —
sezione "FASE 2 - FONDAMENTA TOOL, MOSSA 1" con i "perché" di ogni scelta.

## Come si è svolta la sessione

Apertura fase su istruzione esplicita dell'utente (prima del merge di F1 — deviazione
consapevole dall'ordine di programma, sanata dal branch discendente). Brainstorming breve
con criterio delegato dall'utente per OGNI decisione: *"le opzioni più professionali,
prive di debiti, meno pigre e coerenti — stessi behaviour di Claude Code"*. Spec → piano
→ esecuzione **subagent-driven**: per OGNI task un implementer + spec-review + quality
review indipendenti, TDD col rosso verificato prima. Le review NON sono state decorative
— hanno trovato e fatto correggere difetti reali (elenco sotto); trattarle così anche in
Mossa 2.

## Cosa è stato costruito (per blocco, con le scoperte di review)

### A — Perimetro permessi MCP (T1-T5)
- `McpServerConfig.trust_annotations` (default ON) + `path_args` (T1, `3e5b4d4`).
- `services/mcp_tool_mapping.py::map_mcp_tool` (T2, `7b53cac`+fix): annotations → gate.
  readOnly→`mcp_read`/safe/no-confirm; write→`mcp_write` (destructiveHint ⇒ dangerous,
  altrimenti medium), sempre confermato; senza annotations o untrusted → fallback
  conservativo dangerous+confirm. **Review fix**: promozione a `fs_read`/`fs_write` via
  `path_args` SOLO se tutti gli arg dichiarati esistono in `inputSchema.properties`
  (fail-closed con warning — un typo di config non deve MAI dare scope-check vacuo), e
  guard su `properties` malformate (None/stringa). `mcp_client/plugin.py::get_tools` ora
  preserva i campi via `dataclasses.replace` (prima li perdeva nel re-namespacing).
- Gate (T3, `583ca90`+`a79f991`): plan-block esteso a `mcp_write` (deny + tolto
  dall'offerta via `permission_mode_policy`); pin che allow-rule NON riapre
  mcp_write/fs_write in plan; guardia ibrido `ui_command`+`mcp_write` nel ramo 2-bis;
  costanti capability consolidate nel gate (il mapper le importa).
- **Grant layer in-memory RIMOSSO** (T4, `4b32aaf`+`0ded875`): con `evaluate`/
  `_check_scope`/`PermissionDecision` (zero chiamanti di produzione). Le `PermissionRule`
  su DB sono l'unico override. Semantica pinnata: allow-rule bypassa SOLO il check
  out-of-scope, mai il no-scope breaker.
- `default.yaml` (T5, `c40a723`+`8098288`): `path_args` compilata per i 12 tool
  path-aware del filesystem server v2026.7.10 (`list_directory_with_sizes` incluso —
  lacuna trovata dalla review contro il sorgente npx). **`read_multiple_files` ESCLUSO
  e censito**: il gate fa `str(raw)` sugli arg → una lista diventa un path bogus →
  DENY sistematico (tool rotto), non check vacuo. Flag-registry aggiornato.

### B — Path-safety consolidata (T6-T7)
- `core/path_safety.py` (T6, `5afc624`+`d380302`): 5 primitive
  (`is_unc_path`/`safe_resolve`/`is_relative_to`/`within_any_root`/`is_forbidden`),
  23 pin dai casi limite delle 5 repliche. Contratto documentato: chi confronta path
  non risolti risolve prima; `safe_resolve` None = fail-closed, filtrare PRIMA delle
  liste root/forbidden.
- Migrazione dei 5 consumatori (T7, 6 commit fino a `1a2d94f`): pc_automation,
  file_search, terminal, scope_service, permission_service — ZERO test modificati,
  differenziale empirico su 23 edge input a zero mismatch. Delta dichiarato: path
  invalidi ora fail-closed (deny/skip con warning) dove prima propagavano eccezioni
  fuori dal gate.

### C — Tool file nativi a parità Claude Code (T8-T15, plugin `file_search`, 8 tool)
- `ReadTracker` (T8, `9e7dd70`+`2ce7df1`): per-conversazione, mtime_ns, LRU a DUE
  livelli (path E conversazioni). Vita = processo.
- `read_text_file` (T9, `7516982`+`1bb73ab`): line numbers cat-n, `offset`/`limit` a
  righe, `next_offset`. **Review fix cruciale**: il cap `max_chars` (8000) scatta prima
  della finestra su qualunque file oltre ~150 righe — ora taglia all'ultima riga COMPLETA
  e `next_offset` resta reale (mai il segnale morto `truncated=True/next_offset=0`);
  numerazione su `split("\n")` (non splitlines) + strip `\r` per-riga (file CRLF);
  note in-band per byte-cap wall, finestra vuota, file vuoto.
- Immagini (T10, `cc514fe`+`26b3820`): png/jpg/gif/webp via base64 con cap
  `max_image_bytes` 5 MiB. DUE fix di infrastruttura scoperti in review: (a) il pass di
  sanitise in `core/tools/execution.py` poteva corrompere i payload base64 (regex path
  Unix che divora la coda — colpiva anche take_screenshot da sempre); (b) **i tool
  result image/* NON hanno consumatori** (né vision parts nel prompting né FE) → il
  base64 sarebbe entrato come TESTO nella working history (context bomb). Guardia al
  choke point `ToolRegistryAdapter.execute`: placeholder compatto, mai base64 grezzo
  nel contesto. **Consegna vision = lavoro esplicito di Mossa 2.**
- `edit_text_file` (T11, `6980fb9`+`93d3954`): exact-string, unique-fail col conteggio,
  `replace_all`, guardia ReadTracker (UNREAD/STALE con messaggi distinti), decode UTF-8
  strict, **match in spazio normalizzato LF + write-back negli EOL nativi** (regola
  vincolante: su Windows quasi nessun edit multi-riga matcherebbe altrimenti), BOM
  strip/re-prepend + BOM-strip su old/new string, **abort su EOL misti** (fail-closed:
  mai riscrivere righe non toccate), write atomico mkstemp+os.replace.
- `write_text_file` (T12, `c20a117`+`3291b05`): overwrite solo su file letto e fresco
  (creazione libera), write atomico condiviso, record post-write (write→write e
  write→edit senza re-read funzionano).
- `glob_files` (T13, `70f0688`+`c298d33`): pattern `**` veri, newest-first, bounded,
  containment su candidato risolto (i pattern `../` non escono dal root), pattern
  assoluti → errore pulito, salvage parziali su timeout via sink, note oneste
  (partial vs slice — sotto early-break il newest-first vale solo sui file esaminati).
  Schema `max_results` veritiero (tolto il maximum 200 fantasma, anche su search_files).
- `grep_content` (T14, `eef1d20`+`874a853`): pure-Python (deviazione dichiarata: no
  binario ripgrep per PyInstaller), regex per-riga, 3 output mode, context lines,
  budget `max_matches` GLOBALE su tutti i mode, `partial_file` in count mode.
  **Review fix strutturale**: da `sorted(rglob)` (materializzava l'INTERO albero →
  salvage vuoto sui root grandi) a `os.walk` streaming con pruning in-place delle
  forbidden dir; cap `max_line_chars` per-riga PRIMA del match (anti-backtracking,
  `lines_capped` nel payload); `max_file_bytes` config-driven.
- `usage_guidance` su tutti i 9 tool (T15, `4e933c8`+`cd25d04`, incluso
  `run_terminal_command`) — composte nel blocco `[ORCHESTRAZIONE]`; `search_files`
  allineato al contratto di troncamento (SearchOutcome con `truncated`/`timed_out`,
  salvage su timeout).

### D — Exec unificato (T16, `89aee46`)
`pc_automation.execute_command` RITIRATO con tutta la catena (whitelist comandi,
validator, ~48 test morti); `run_terminal_command` unica via exec. Lockout
anti-esfiltrazione VERIFICATO vivo end-to-end (`LOCKOUT_TOOLS={"run_terminal_command"}`
è load-bearing, pinnato); DEGRADED-da-lockout rimosso (adjudicato in review: nessun
consumatore reale, solo flapping di status). Chiave config strippata via
`_REMOVED_LEGACY_KEYS`.

### E — Eval (T17, `7d00ff5`+`fab5c2b`)
Scenari `fs-edit-exact-01` (disambiguazione VERA: due righe identiche, il naive
old_string fallisce con "non è unica" — review fix), `fs-glob-01` (check negativi
ancorati al path-listing, robusti per i run reali), `fs-grep-01`; `mcp-gate` SOLO nel
subset mock (in `scenarios/` darebbe un pass vacuo nei run a pagamento) — pinna l'intera
trace del gate: tool.call pre-gate, interaction confirm, auto-decline, tool.result
rejected, zero side-effect. Nuovo check `response_not_matches`; `SandboxScriptedLLM`
(convenzione "Cartella di lavoro: <path>" nei prompt, fail-fast se assente).

## Stato dei gate (verificati a fine sessione, output letto)

- `pytest tests/agent/ tests/evals/ tests/contracts/` → **303 passed** (4m13s)
- 18 suite mirate (file_search/grep/tracker/path_safety/mcp×3/permission×7/terminal×2/
  config/tool_registry) → **524 passed, 2 skipped** (censiti: symlink-privilege, docx)
- pc_automation/scope/screenshot → **99 passed**
- `ruff check .` → 0; `lint-imports` → 6 kept, 0 broken; `check-contracts.ps1` → verde
  (questa mossa NON tocca il wire; il primo run dava exit 1 per il NativeCommandError
  PS5.1 sullo stderr DEBUG — NON era un drift, vedi gotcha)
- mypy: parità verificata PER TASK via stash round-trip (baseline invariata; T15 -2)
- FE: NON toccato in questa mossa (gate FE rimandati alla Mossa 2)
- **Eval a pagamento NON eseguita** (regola di programma: solo con OK esplicito
  dell'utente — va fatta alla chiusura di fase, in Mossa 2)

## DEBITO CENSITO (nuovo di mossa — si somma ai handoff di Fase 1)

1. **Consegna vision immagini + rendering FE** → Mossa 2 (piano, sezione "Cosa NON fa
   questa mossa"): oggi placeholder fail-safe; il `ToolResult.raw_content` di
   piattaforma resta la fonte integra per la futura reidratazione.
2. **Arg-lista nel confinement del gate**: `decide` fa `str(raw)` sui path_args — le
   liste non sono iterate. `read_multiple_files` resta fuori da `path_args` (censito
   nel default.yaml) finché il gate non itera i valori lista.
3. **Executor dedicato cancellabile per search/glob/grep**: su timeout il thread
   abbandonato occupa uno slot del pool default e continua il walk — dichiarato nei
   docstring, raffinamento futuro.
4. **pc_automation**: `screenshot_lockout_s` e `command_timeout_s` esposti in config ma
   NON cablati al runtime (pre-esistente, scoperto in review T16).
5. I debiti di Fase 1 restano invariati (infra test WS/REST Windows in testa; vedi
   handoff fix-session 2026-07-18).

## Gotcha di sessione (i vecchi di Fase 1 RESTANO validi; nuovi:)

1. **EOL per-file, non per-repo** (il gotcha "EOL misti" in memoria è reale): nel
   package file_search `plugin.py`/`searcher.py` sono CRLF, `readers.py`/
   `read_tracker.py`/`grep.py` LF; `terminal/plugin.py` LF. Prima di editare un file
   verificane gli EOL e preservali (uno script di patch ha convertito plugin.py per
   sbaglio — ripristinato byte-a-byte).
2. **Il layer Bash de-escapa `﻿` negli heredoc**: mai BOM letterali nel sorgente —
   usare l'escape ASCII (`"﻿"` in Python) e verificare i byte scritti.
3. **PS 5.1 + stderr**: `check-contracts.ps1` (e qualunque script che logga su stderr)
   può dare exit 1 fantasma per NativeCommandError sul DEBUG log — rilanciare con
   `powershell -File` pulito e leggere l'output vero prima di diagnosticare un drift.
4. **Here-string PowerShell con certi pattern** (es. glob `image/*`) possono far
   scattare hook di protezione del harness: per scrivere file di testo lunghi usare i
   tool file (Write/Edit), non Add-Content.
5. **Review = trova-difetti, non timbro**: in questa mossa le review hanno trovato
   fail-open reali (path_args typo), context bomb (immagini), contratti morti
   (next_offset), trappole CRLF (read↔edit), materializzazione dell'albero (grep).
   Budget-are le review come lavoro vero anche in Mossa 2.
6. Macchina (VITALI, invariati): venv SEMPRE con path assoluto
   (`& "C:\Users\Jays\Desktop\alice\alice\.venv\Scripts\Activate.ps1"`); pytest SEMPRE
   da `backend/`, foreground, MAI concorrenti, MAI suite integrale (AUD-008);
   `-o faulthandler_timeout=N` per gli hang.

## Prossima sessione (delega)

1. **Leggere PRIMA, nell'ordine**: questo handoff INTERO; la spec di fase (§6 Frontend
   è il perimetro Mossa 2); il piano Mossa 1 (sezione "Cosa NON fa questa mossa");
   CLAUDE.md aggiornato ("Scope & permission modes" riflette già il nuovo perimetro
   MCP). Il ledger locale ha i "perché".
2. **Mossa 2** (piano proprio via writing-plans, esecuzione subagent-driven):
   - `tool_meta` su `interaction.requested` (rituale contratti COMPLETO: ws_schema →
     frozen test → gen-contracts → ChatHandlerMap; MAI tipi TS a mano) + badge origine
     MCP/fallback nel dialogo di conferma;
   - diff preview per gli edit nel dialogo (old/new string già negli args del frame);
   - `GET /api/tools/catalog` con response_model (ratchet) + picker/autocomplete in
     `PermissionRulesManager.vue`;
   - pannello MCP in Impostazioni (trust/annotations per-server, livello derivato
     per-tool) + `response_model` sulle route `/api/mcp/*` al primo tocco;
   - **consegna vision immagini** (debito #1: progettarla — dipende dal supporto
     provider; reidratazione da raw_content) + rendering FE del contentType;
   - eval a pagamento di chiusura fase (SOLO con OK utente; scenari fs-* nuovi inclusi,
     risultato ≥ baseline `20260718-121940-baseline-fase1`), aggiornamento
     CLAUDE.md/flag-registry finali, handoff di fase.
3. **Merge di Fase 1**: resta pendente (smoke 2 + OK utente). Se l'utente dà l'OK
   durante la sessione: `finishing-a-development-branch` su `feat/agent-engine-fase1`,
   poi la Fase 2 si rebasa/merga di conseguenza (è discendente: fast-forward pulito).
4. **Principi NON negoziabili invariati**: pilastro (soluzione meno pigra, zero debiti
   non censiti), contratti generati, TDD col rosso verificato, review indipendente
   doppia per task, eval a pagamento solo con OK esplicito, un solo implementer alla
   volta sul working tree.
