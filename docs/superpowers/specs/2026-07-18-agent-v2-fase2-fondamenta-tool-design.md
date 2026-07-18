# Agent v2 — Fase 2: Fondamenta tool — Design

**Data:** 2026-07-18
**Stato:** approvato dall'utente (brainstorming breve in sessione; criterio delegato: "le opzioni
più professionali, prive di debiti, meno pigre e coerenti — stessi behaviour di Claude Code")
**Branch:** `feat/agent-tools-fase2` (creato dal HEAD smokato di Fase 1 `72d5a5c`; discendente,
quindi il merge di Fase 1 in `main` resta pulito e questa fase vi si appoggia)
**Programma:** `docs/superpowers/specs/2026-07-16-agent-v2-program-design.md` (Fase 2 di 9, sezione
estesa 2026-07-18 col perimetro permessi MCP)
**Predecessore:** Fase 1 — motore greenfield (`docs/superpowers/specs/2026-07-17-agent-engine-fase1-design.md`
+ handoff fix-session `docs/superpowers/handoffs/2026-07-18-fix-session-post-smoke-handoff.md`)

---

## 1. Obiettivo e contesto

Portare i tool di base al livello di Read/Edit/Grep/Glob/Bash di Claude Code e chiudere il
perimetro permessi dei tool MCP (gap dimostrato live nello smoke di Fase 1: scrittura su Desktop
via `mcp_filesystem_write_file` senza conferma in strict). Fotografia del divario (Explore
2026-07-18, citazioni nel ledger):

- `read_text_file`: niente line numbers, niente offset/limit (solo `max_chars`), niente immagini
  (`plugins/file_search/readers.py`).
- **Edit exact-string inesistente**: l'unica mutazione è `write_text_file` = overwrite totale.
- **Glob e grep contenuti inesistenti**: `search_files` cerca solo substring sul *nome* file
  (`plugins/file_search/searcher.py:157`).
- **Exec duplicato**: `terminal.run_terminal_command` (shell-free, scope via `scope_service`) e
  `pc_automation.execute_command` (whitelist, confinamento diverso via `workspace_root`, cap
  output 500 char) sono due vie concorrenti con guardie e formati diversi.
- Path-validation replicata deliberatamente in ~4 copie (`file_search/searcher.py`,
  `terminal/security.py`, `permission_service.py:520`, `pc_automation/security.py`); troncamento
  su due livelli non coordinati.
- **Tool MCP fuori dal gate**: nascono `capabilities=()`, `risk="safe"`,
  `requires_confirmation=False` (`plugins/mcp_client/plugin.py:210-215`) ⇒ ALLOW incondizionato
  in ogni tier, incluso plan (e in plan restano pure nell'offerta, perché il drop è
  per-capability). La libreria `mcp` 1.26.0 espone già `Tool.annotations`
  (`readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`, `mcp/types.py:1247-1339`)
  ma la conversione le scarta (`services/mcp_session.py:495-508`).
- Layer grant in-memory (`PermissionService.grant`/`is_granted`) **senza scrittori di
  produzione**: il remember delle conferme passa dalle `PermissionRule` su DB (fix post-smoke
  Fase 1).

## 2. Decisioni prese (brainstorming 2026-07-18)

| Decisione | Scelta |
|---|---|
| Fallback MCP senza annotations | **Conservativo forte**: trattato come distruttivo — conferma in strict E auto_edits, escluso dall'offerta e negato in plan (comportamento Claude Code: i tool MCP chiedono permesso di default) |
| Trust delle annotations | Flag per-server `trust_annotations`, **default ON** (server configurati a mano = fiducia implicita); OFF declassa il server al fallback conservativo |
| Confinement per-conversazione MCP | Config per-server opzionale `path_args` → i tool dichiarati ricevono capability fs vere + `path_args` → confinement per-conversazione **esistente** del gate; i roots process-global restano come difesa in profondità |
| Grant in-memory | **Rimosso** (YAGNI dimostrato: zero scrittori; le `PermissionRule` coprono il remember) |
| Exec | **Unificato su `terminal.run_terminal_command`**; `pc_automation.execute_command` ritirato |
| Grep contenuti | **Pure-Python bounded**, niente binario ripgrep (bundling PyInstaller non giustificato; unica deviazione dichiarata da Claude Code, upgrade isolato dentro il tool se l'eval la smentisse) |
| Superficie file | Plugin `file_search` **evoluto in place** (namespace `file_search_*` stabile: regole permessi e offer policy non si invalidano) |
| Guardia edit/write | **Read-tracking per-conversazione con mtime** (edit/overwrite solo su file letto e non modificato nel frattempo — modello Claude Code) |
| UI | Copertura completa (sezione 6): dialogo conferma arricchito (origine MCP, diff per gli edit), picker regole, pannello MCP |

## 3. Perimetro permessi MCP (backend)

### 3.1 Mapping annotations → gate

Alla conversione in `ToolDefinition` (in `services/mcp_session.py`, dove oggi le annotations sono
scartate), con `trust_annotations` attivo per il server:

| Annotations | capabilities | risk_level | requires_confirmation |
|---|---|---|---|
| `readOnlyHint=true` | `("mcp_read",)` | `safe` | `False` |
| `readOnlyHint=false, destructiveHint=false` | `("mcp_write",)` | `medium` | `True` |
| `readOnlyHint=false, destructiveHint=true` (default MCP quando annotations presenti) | `("mcp_write",)` | `dangerous` | `True` |
| **Annotations assenti** o `trust_annotations: false` | `("mcp_write",)` | `dangerous` | `True` |

Capability nuove `mcp_read`/`mcp_write` nel vocabolario del gate — NON si riusano `fs_read`/
`fs_write`: tengono i tool MCP dentro la matrice tier senza attivare il ramo di confinement fs su
tool che non dichiarano path. `idempotentHint`/`openWorldHint` non entrano nel gate in questa fase
(nessun consumatore; si censiscono come non usate).

### 3.2 Estensioni del gate

- `PermissionService.decide`: il blocco plan (`permission_service.py:329-331`) si estende da
  `is_write or is_exec` a includere `"mcp_write" in caps`. Nessun altro ramo nuovo: `mcp_write`
  con `requires_confirmation=True` cade nella coda esistente (strict → confirm; auto_edits →
  confirm via `risk=dangerous` a riga 347 o via `requires_confirmation` a riga 351; autopilot →
  allow, coerente con i tool nativi dangerous).
- Offer policy: `_READ_ONLY_BLOCKED_CAPABILITIES` (`permission_mode_policy.py:36-38`) si estende
  con `mcp_write` → in plan i tool MCP non read-only spariscono dall'offerta, come già
  `fs_write`/`process_exec`.
- **Rimozione grant layer**: `grant`/`revoke`/`is_granted`/`clear_grants` + il ramo `granted` in
  `decide` (righe 289, 313, 338) e in `_check_scope`. I test che usano `.grant(` migrano su
  `PermissionRule`. Se `evaluate`/`_check_scope` (path legacy binario) risultano senza chiamanti
  di produzione, si rimuovono nella stessa passata (verifica nel piano).

### 3.3 Config per-server (`McpServerConfig`, `core/config.py:788`)

Campi nuovi, entrambi opzionali e censiti in `docs/flag-registry.md`:

```yaml
mcp:
  servers:
    - name: filesystem
      command: [npx, "@modelcontextprotocol/server-filesystem", "~"]
      trust_annotations: true        # default: true
      path_args:                     # default: {} — mappa tool → arg che portano path
        write_file: [path]
        edit_file: [path]
        move_file: [source, destination]
        read_text_file: [path]
        # ...
```

Un tool elencato in `path_args` riceve alla conversione: capability fs coerente con le annotations
(`fs_read` se read-only, `fs_write` altrimenti) al posto di `mcp_*`, più `path_args` nel
`ToolDefinition` → il confinement per-conversazione del gate (`decide` snodo 3-4) si applica
così com'è, zero codice nuovo nel gate. Il `default.yaml` spedisce la mappa compilata per il
server `filesystem` builtin.

### 3.4 Cosa NON cambia

I roots MCP restano process-global (unione scope + static dirs, limite documentato in
`services/mcp_session.py:25-28`); il ponte di Fase 1 è invariato. Nessuna persistenza DB della
config MCP.

## 4. Tool file nativi (plugin `file_search`, backend)

Tutti i tool restano `path_args=("path",)` (o equivalente) + capability fs → gate e scope
invariati per costruzione.

### 4.1 `read_text_file` potenziato
- Output testo con **line numbers** formato `cat -n` e parametri **`offset`/`limit` a righe**
  (default limit 2000 righe, cap per riga lunga con troncamento dichiarato); il payload JSON
  mantiene i metadati (`truncated`, `lines_read`, `total_lines`, `path`, `next_offset`).
- **Immagini** (`.png/.jpg/.jpeg/.gif/.webp`): ritorna `binary_base64` con `content_type`
  `image/*` (stessa pipeline di `pc_automation.take_screenshot`, già esente dal troncamento
  centrale in `core/tools/execution.py:385-388`), size cap dedicato.
- PDF/DOCX restano come oggi.

### 4.2 `edit_text_file` NUOVO
- Exact-string replace: `path`, `old_string`, `new_string`, `replace_all=false`.
- **Fallisce** se `old_string` è assente o non-unico (con conteggio occorrenze nell'errore);
  `replace_all=true` sostituisce tutte le occorrenze.
- Richiede **read-tracking** (4.4): file mai letto nella conversazione o modificato dopo la
  lettura → errore chiaro che istruisce a rileggere.
- `capabilities=("fs_write",)`, `requires_confirmation=True`, risk `medium`.

### 4.3 `write_text_file` con guardie
- Overwrite di file **esistente** solo se letto prima (read-tracking); creazione di file nuovo
  libera. Restano cap 1 MiB e blocco estensioni eseguibili.

### 4.4 Read-tracking per-conversazione
Stato in-memory del plugin: `conversation_id → {path risolto: mtime alla lettura}`, alimentato da
`read_text_file`, consultato da `edit_text_file`/`write_text_file` (chiave da
`ExecutionContext.conversation_id`). Cap LRU per conversazione; vita = processo (dopo un restart
l'agente rilegge — stesso comportamento di Claude Code a nuova sessione). Nessuna persistenza.

### 4.5 `glob_files` NUOVO
Pattern glob veri (`**/*.py`), radicato in un `path`, risultati ordinati per mtime discendente,
bounded (`max_results`), rispetto di forbidden/allowed roots. `capabilities=("fs_read",)`.

### 4.6 `grep_content` NUOVO
Ricerca regex nei **contenuti**: `pattern` (regex Python), `path`, filtri `glob`/`extensions`,
`context_lines`, modalità output (`files_with_matches` default | `content` | `count`),
case-insensitive opzionale. Implementazione pure-Python su `os.walk` con bounds rigidi: max file
visitati, max match, timeout in thread (stesso pattern di `searcher.py`), skip binari
(euristica NUL nel primo blocco), cap dimensione file. `capabilities=("fs_read",)`.

### 4.7 `search_files` resta
Ricerca per nome file: capability distinta dal grep contenuti, nessuna sovrapposizione.

## 5. Exec unificato + path-safety + shaping (backend)

### 5.1 Exec
`terminal.run_terminal_command` è **l'unica** via di esecuzione comandi (shell-free, scope via
`scope_service` + `validate_cwd_within_scope`, env allowlist, output bounded, echo nel PTY,
screenshot lockout). **`pc_automation.execute_command` viene ritirato**: tool, executor dedicato
(`exec_command`), config `max_command_output_chars`, test relativi. `open_application` resta
(lancio app ≠ exec comandi; capability `process_exec` invariata). Il ritiro si censisce in
`docs/flag-registry.md`.

### 5.2 Path-safety consolidata
Le ~4 copie di resolve/containment/forbidden convergono su **un modulo unico**
(`backend/core/path_safety.py`, importabile da core/services/plugins senza violare
import-linter): `safe_resolve`, `is_relative_to`, `is_forbidden`, `within_roots`, guardie UNC/
symlink. Consumatori: `file_search/searcher.py`, `terminal/security.py`,
`permission_service.py`, `pc_automation/security.py`, `scope_service.validate_folder`. I commenti
"replicate rather than import" decadono: la replica era debito censito, la fase lo salda. La
semantica del gate NON cambia (stessi check, una sola implementazione; pin di regressione sui
casi limite già coperti dai test esistenti).

### 5.3 Shaping dei risultati
- Troncamento a due livelli **coordinati**: policy per-tool (righe per read/grep, byte per exec)
  + `max_result_chars` centrale come backstop; messaggi di troncamento uniformi che dicono come
  riprendere (`next_offset`, restringere il pattern, ecc.).
- `usage_guidance` compilata per ogni tool nuovo o modificato (meccanismo `[ORCHESTRAZIONE]`
  esistente, `core/tool_registry.py:296-324`): quando usare edit vs write, grep vs search,
  offset/limit sul read, preferire il tool nativo all'equivalente MCP quando entrambi offerti.

## 6. Frontend (copertura completa)

Ogni tocco al wire segue il rituale contratti: `ws_schema` → frozen test → `gen-contracts.ps1` →
`ChatHandlerMap`/tipi generati. MAI tipi TS a mano.

### 6.1 Dialogo di conferma arricchito (`interaction.requested`)
Estensione **additiva** di `WsInteractionRequested` (`api/ws_schema/chat.py:169-179`) con un
oggetto opzionale:

```
tool_meta: { origin: "native" | "mcp", server: str | null,
             annotated: bool | null, read_only: bool | null,
             destructive: bool | null, trusted: bool | null } | null
```

Popolato dal motore via payload della `InteractionRequestedEvent` (il campo viaggia accanto ad
`args`/`risk_level`/`description` già presenti). Il dialogo Horizon mostra: badge origine
(server MCP o plugin nativo), livello di rischio derivato, e — punto chiave di trasparenza — la
dicitura esplicita "tool non annotato: trattato come distruttivo" quando `annotated=false`.

### 6.2 Diff preview per gli edit
Per le conferme di `file_search_edit_text_file` il dialogo rende `old_string`/`new_string` (già
dentro `args`) come **diff visivo** (rosso/verde, monospace) invece del JSON grezzo — parità con
l'esperienza Claude Code. Per `write_text_file` su file esistente: anteprima contenuto (troncata).
Solo presentazione FE: nessun campo wire nuovo oltre a 6.1.

### 6.3 Picker dei tool nelle regole permessi
`PermissionRulesManager.vue` sostituisce la stringa libera con un **picker/autocomplete** dal
catalogo. Endpoint REST nuovo `GET /api/tools/catalog` con `response_model` (ratchet): elenco
`{name, plugin, description, capabilities, risk_level, requires_confirmation, mcp_server?}`.
Serve anche come base per superfici future (offerta tool per-chat già esistente).

### 6.4 Pannello MCP in Impostazioni
La vista server MCP (store `mcp.ts`) si arricchisce: per-server `trust_annotations` (read-only,
riflette la config) e per-tool il livello derivato (read-only / write / **non annotato →
fallback**). Le route `/api/mcp/*` oggi ritornano `dict[str, Any]`: al primo tocco si
tipizzano con `response_model` (ratchet) e i tipi FE si rigenerano.

### 6.5 Superfici invariate
Il fold tool di `agentRun` rende già nome/args/risultato/progress dei tool nuovi senza modifiche
strutturali (frame `tool.*` invariati). `permissionMode.ts`, scope UI, context bar: invariati.

## 7. Config e migrazioni

- Chiavi nuove: `mcp.servers[].trust_annotations` (default `true`), `mcp.servers[].path_args`
  (default `{}`); `file_search.*` per i tool nuovi (limiti grep/glob/read); tutte censite in
  `docs/flag-registry.md`.
- Chiavi rimosse: `pc_automation.max_command_output_chars` (con strip dalle config persistite via
  `_REMOVED_LEGACY_KEYS`, stesso meccanismo del flag `agent.engine` di Fase 1, se la chiave
  risulta nei layer utente).
- Nessuna migrazione DB.

## 8. Test e TDD

- **TDD col rosso verificato prima** su ogni tool e ogni ramo nuovo del gate.
- Mapping annotations: test unit sulla conversione (server MCP finto che espone annotations
  combinatorie + server senza annotations + `trust_annotations: false`).
- Matrice gate: test per tier × {mcp_read, mcp_write, fs-mappato via path_args} incluso plan
  (offerta E decisione), autopilot, remember su tool MCP.
- Path-safety: la suite esistente dei 4 consumatori diventa il pin di regressione del modulo
  unico (casi UNC, symlink, `..`, forbidden, drive Windows).
- Read-tracking: unit su read→edit ok, edit senza read, mtime cambiato, restart (stato vuoto).
- FE: vitest su dialogo (tool_meta, diff preview), picker, pannello MCP; typecheck/lint 0.
- Eval: scenari nuovi `fs-edit`/`fs-glob`/`fs-grep` (+ scenario mock del perimetro MCP) nel
  subset mock CI; run a pagamento SOLO con OK esplicito dell'utente, risultato ≥ baseline
  (che al merge di Fase 1 diventa la baseline corrente).

## 9. Gate di chiusura fase

1. `pytest` mirato (agent + evals + contracts + file_search/terminal/permission) verde;
   MAI suite integrale (AUD-008), mai pytest concorrenti.
2. `ruff check .` = 0; mypy a parità sui file toccati; `lint-imports` 6/6 kept.
3. `check-contracts.ps1` verde; artifacts committati freschi.
4. FE `typecheck`/`lint`/vitest verdi.
5. Eval ≥ baseline (con OK utente al run).
6. Smoke manuale su Horizon: un edit con diff preview + conferma, un tool MCP annotato e uno
   non annotato in strict, un grep/glob, exec unificato.
7. CLAUDE.md, flag-registry, handoff di fase aggiornati; debito deliberato censito.

## 10. Non-obiettivi

- Prompting/guidance comportamentale e guardie anti-degenerazione (Fase 3); watchdog first-token
  (Fase 3/4).
- Confinement per-conversazione dei **roots** MCP (restano process-global, documentato).
- Persistenza DB della config MCP; UI di authoring/aggiunta server MCP.
- Binario ripgrep bundled (deviazione dichiarata, sezione 4.6).
- Convergenza del PTY interattivo utente col tool exec (il PTY resta superficie utente; il tool
  già vi fa echo).
- Risanamento infra test WS/REST Windows (debito #1 del backlog, ticket separato).

## 11. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Regressione semantica nel consolidamento path-safety | Suite esistente dei 4 consumatori come pin; nessun cambio di semantica dichiarato |
| Fallback conservativo forte = attrito su server non annotati molto usati | `path_args`/`trust_annotations` per-server; il costo è una conferma, non un deny |
| Line numbers nel read cambiano l'input al modello (eval) | Scenari `fs-*` aggiornati nella stessa fase; eval di chiusura contro baseline |
| Ritiro `execute_command` usato da flussi esistenti | Grep dei chiamanti nel piano; `run_terminal_command` copre il caso d'uso con guardie superiori |
| Pure-Python grep lento su alberi enormi | Bounds rigidi (max file/match/timeout) + messaggio di troncamento con come restringere |

## 12. Docs da aggiornare in fase

CLAUDE.md ("Tools & the AgentEngine", "Scope & permission modes"), `docs/flag-registry.md`,
handoff di fase in `docs/superpowers/handoffs/`, sezione Fase 2 del programma se il perimetro
consegnato devia dalla pianificazione.
