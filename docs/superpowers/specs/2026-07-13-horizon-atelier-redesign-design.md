# Horizon "Atelier" — redesign della vista assistente con sistema a finestre

Data: 2026-07-13 · Stato: bozza approvata a sezioni in brainstorming, in attesa di review finale

## 1. Contesto e obiettivo

La vista assistente (`/assistant`, `HorizonView.vue`) viene riprogettata da zero attorno alla
metafora della **scrivania ambientale** ("atelier"): l'assistente è l'ambiente, la conversazione
è un layer effimero al centro della scena, i contenuti di lavoro sono **finestre liberamente
trascinabili in stile OS** e gli strumenti vivono in un **dock**. Le finestre sono pilotabili
sia dalla UI sia dall'agente tramite il Command Bridge esistente.

Vincoli di fondo:

- Il **Workspace resta intatto** (superficie di prodotto, mai rimossa): tiling suo, finestre
  flottanti di Horizon. Due presentazioni, **un solo catalogo moduli** (`MODULE_REGISTRY`).
- Estetica **atelier materico adattata ai token esistenti**: nessuna palette nuova, nessun
  font nuovo. Chrome in Geist (kit), voce dell'assistente in Fraunces (`--hz-serif`, già
  scoped a Horizon). Dual-theme garantito dai token.
- Qualità del codice: `HorizonView.vue` (680 righe) viene scomposto; la logica pura esistente
  (scene state machine, sentence pacer, estrazione artifacts, clock) è **salvata, non riscritta**.

## 2. Decisioni di prodotto (prese in brainstorming)

1. **Architettura**: catalogo moduli condiviso col Workspace; layer di presentazione a finestre
   flottanti proprio di Horizon (z-order, focus, drag, resize). Workspace non toccato.
2. **Paradigma**: scrivania ambientale (assistente = ambiente, finestre libere, dock).
3. **Conversazione**: ambientale (risposta frase-per-frase al centro, poi si dissolve) e
   **materializzabile** in una finestra chat (modulo `chat` del catalogo, singleton).
4. **Attività agentica**: segni ambientali discreti in scena (tool corrente, piano compatto,
   badge subagent nel dock) + nuova finestra **Attività** con il dettaglio completo, alimentata
   dagli store `agentRun` e `backgroundTasks` (oggi mai consumati da Horizon).
5. **Estetica**: atelier materico espresso interamente con i token/kit attuali.
6. **Comandi agente `window.*`**: implementati subito (l'infrastruttura esiste già tutta).

Approccio tecnico scelto: **chrome nuovo, catalogo condiviso** — nuovo store `desk` +
`DeskWindow` disegnato per l'atelier; `ModulePanel` resta il chrome del Workspace (niente
cascate di `:deep` per piegarlo a un altro design). Lo store `desk` è **surface-agnostic**
(zero import da Horizon): la promozione futura ad app-wide è un cambio di mount point.

## 3. Design UX

### 3.1 Layer della scena (dal basso verso l'alto)

1. **Il piano** — sfondo `--surface-0`. La linea d'orizzonte sopravvive come *bordo del tavolo*:
   si riusa il motore canvas di `HorizonLine.vue` (modi breathe/tense/pulse/timeline/flow,
   già theme-aware via MutationObserver) con resa adattata all'atelier.
2. **Layer ambientale** — saluto per fascia oraria (quiet), composer boxless con entrata Jarvis
   (qualsiasi carattere stampabile lo materializza), risposta frase-per-frase (pacer esistente),
   cockpit con i controlli kit condivisi (ModelSelector, ScopeIndicator, ChatToolControls,
   PermissionTierSelector, ContextBar, MicrophoneButton). Sotto la risposta, l'affordance
   "materializza la conversazione" apre la finestra chat.
3. **Le finestre** — fogli `--surface-1`/`--surface-2`, bordo `--border` (`--border-hover`
   o accent sul focus), `--radius-lg`, ombra `--shadow-floating`. Header: icona modulo,
   titolo, minimizza, chiudi (UiIconButton).
4. **Il vassoio (dock)** — in basso al centro: un lanciatore per ogni modulo `available`,
   punto-stato sotto i moduli con finestre aperte (distinzione aperta/minimizzata), badge
   numerico sull'Attività (subagent + background task attivi), chip avanzamento piano.
5. **Overlay** — `ToolConfirmationDialog` e `AskUserPrompt` esistenti sopra la scena attenuata;
   modal/toast/popover globali invariati.

### 3.2 Stati coperti

| Stato | Resa |
|---|---|
| Quiete | saluto + linea in respiro + colophon (data · ora · prossimo evento) |
| Composizione | composer attivo + cockpit |
| Ascolto voce | transcript live nel composer, linea tesa; toggle voce con click sul fondo scena |
| Risposta | testo frase-per-frase al centro (Fraunces), pulse TTS sulla linea |
| Lavoro | linea timeline con tacche piano, piano compatto sotto la linea, annotazione tool corrente |
| Subagent / background | badge nel dock; dettaglio nella finestra Attività |
| Artefatti | auto-apertura come finestra (stesso intent-bus del Workspace) |
| Errore di turno | segno ambientale sulla linea + toast globale |
| Disconnessione | punto masthead, "DISCONNESSA" nel colophon, linea a braci |
| Conferma permessi / ask_user | dialog esistenti, scena attenuata |

Sostituzioni: `HorizonStage`→finestre · `HorizonShelf`→dock · `HorizonHistory`→finestra chat ·
annotazione tool 2,5 s→segni ambientali + finestra Attività.

### 3.3 Meccanica finestre

- **Drag** dall'header, **resize** da bordi e angoli, minimi per modulo, massimo = viewport.
- **Click-to-front** (contatore di focus, z locali alla scena).
- **Minimizza** nel vassoio (rect preservato); **chiudi** = solo visibilità: lo stato di
  dominio (sessioni terminale, piano, conversazione) vive negli store dedicati e non viene
  mai distrutto (stessa regola del Workspace).
- **Piazzamento a cascata** per le nuove finestre; **clamp** al viewport.
- **Persistenza** in localStorage con schema versionato e migrazione (pattern `workspace.ts`).

## 4. Architettura

### 4.1 File nuovi (sotto `frontend/src/renderer/src/`)

| File | Responsabilità |
|---|---|
| `stores/desk.ts` | Stato finestre: `{ id, moduleId, params, rect{x,y,w,h}, z, minimized }`. Azioni: `openWindow`, `closeWindow`, `focusWindow`, `moveWindow`, `resizeWindow`, `minimizeWindow`, `restoreWindow`, `arrangeWindows`, `listWindows`. Rispetta `ModuleDef.singleton` (open su singleton già aperto ⇒ focus + restore). Persistenza `alice_desk_layout_v1` con migrazione. **Zero import da Horizon.** |
| `composables/desk/deskGeometry.ts` | Funzioni pure: clamp, cascata, minimi, normalizzazione al restore/resize del viewport, preset di arrange. Con `deskGeometry.spec.ts`. |
| `composables/desk/useWindowInteractions.ts` | Drag/resize con pointer events (`setPointerCapture`), delega la matematica a `deskGeometry`. |
| `components/desk/DeskSurface.vue` | Layer finestre: `v-for` sullo store, sottoscrive `onOpenModule` **solo quando montato** (mai in parallelo con `PanelWorkspace`: superfici su route diverse). |
| `components/desk/DeskWindow.vue` | Chrome "foglio": header + corpo (componente lazy dal `MODULE_REGISTRY`, `params` passati come nel `PanelLeaf`), stato focus, `role="region"` + `aria-label`, focus ring globale. |
| `components/desk/DeskDock.vue` | Vassoio: lanciatori, punti-stato, badge Attività, chip piano. |
| `commands/desk.ts` | `installDeskCommands()` idempotente (pattern `installCoreCommands`). |
| `components/workspace/modules/ActivityModule.vue` | Nuovo modulo del catalogo (singleton): timeline tool da `agentRun` (nome, sintesi argomenti, esito), subagent/background da `backgroundTasks`, token del turno. Disponibile anche nel Workspace. Richiede una voce icona in `assets/icons.ts` se assente. |

### 4.2 Horizon ricostruita

- `HorizonView.vue` → pura composizione, target ≤ ~200 righe. Estrazioni: `useHorizonKeyboard.ts`
  (Esc-chain, entrata Jarvis), `useHorizonVoiceBridge.ts` (routing transcript, TTS auto-speak,
  reset a nuovo turno) — logica salvata dall'attuale file monolitico.
- Vivi e intatti: `horizonScene.ts` (perde lo stato `presenting`: le finestre sono ortogonali
  alla scena), `useSentencePacer`, `horizonArtifacts`, `useClock`, `HorizonLine` (rivestita),
  masthead/colophon/quiet/composer/cockpit aggiornati all'atelier.
- **Rimossi**: `HorizonStage.vue`, `HorizonShelf.vue`, `HorizonHistory.vue` e relativi stili;
  l'icona legacy `orb` in `assets/icons.ts` (sostituendo i due usi residui in `AppSidebar.vue`
  e `ChatInput.vue` con icone attuali).
- `assets/styles/horizon.css` resta il file token della scena (Fraunces + alias `--hz-*`);
  nuovi stili solo scoped nei componenti, con soli token del tema.

### 4.3 Flusso dati e stacking

- Eventi WS → store di dominio (invariato). Lo store `desk` contiene **solo presentazione**.
- Auto-apertura artefatti: `useArtifactAutoOpen`/intents esistenti; quando nessuna superficie
  è montata gli intents cadono nel vuoto (semantica attuale, preservata).
- Le finestre vivono **dentro** il contenitore della scena (non teleportate): z-order con
  interi locali; dropdown/modal/toast globali restano sopra senza toccare la scala `--z-*`.

## 5. Comandi agente `window.*`

Registrati nel Command Registry frontend con `exposeToAgent: true`; handler = azioni dello
store `desk`. Nessuna modifica backend (manifest dinamico, matrice permessi §7 già attiva;
`window` non è dominio guardrail).

| Comando | Capability | Argomenti | Note |
|---|---|---|---|
| `window.open` | navigation | `{ module: enum registry, params?: object }` | se la vista attiva non è `assistant`, naviga prima (riusa `view.switch`); singleton ⇒ focus |
| `window.focus` | navigation | `{ window_id }` | restore se minimizzata |
| `window.list` | read | `{}` | ritorna `{ id, module, title, rect, minimized, focused }[]` |
| `window.close` | mutate | `{ window_id }` | in tier `plan` è negato dalla matrice (solo navigation/read) |
| `window.arrange` | navigation | `{ preset: 'cascade' \| 'tile' }` | agisce solo sulle non minimizzate |

`window.move`/`window.resize` per singola finestra: **fuori scope v1** (l'agente dispone con
`arrange`; granularità fine solo se emerge un bisogno reale).

## 6. Edge cases e decisioni

**Geometria e persistenza**
1. Restore con geometrie fuori viewport (risoluzione cambiata, monitor diverso) ⇒
   normalizzazione pura in `deskGeometry` al load **e** su resize della finestra Electron.
2. Layout persistito che referenzia un modulo non registrato ⇒ la migrazione lo scarta
   (stessa failure mode di `migrateLayout` del Workspace).
3. localStorage corrotto o quota superata ⇒ `try/catch`, reset a layout vuoto, log warn.
4. Versione schema sconosciuta ⇒ reset a vuoto (mai crash).
5. Z-order: compattazione degli z a `0..n` in fase di persist (niente overflow del contatore).
6. Drag oltre i bordi ⇒ clamp che garantisce header sempre raggiungibile (margine minimo
   visibile); resize sotto i minimi per modulo ⇒ bloccato.

**Interazione**
7. Entrata Jarvis vs digitazione nelle finestre (terminale!, input chat, whiteboard):
   il keydown globale si attiva **solo** se `document.activeElement` è il body o la radice
   della scena — mai se il focus è dentro una finestra, un input, o contenteditable.
8. Toggle voce col click sulla scena: solo se `event.target` è il fondo scena (mai finestre,
   dock, overlay).
9. Esc-chain (ordine): dialog aperti → composer attivo (dissolve) → finestra focalizzata
   (rilascia il focus alla scena; **mai** chiusura implicita di finestre con Esc).
10. Drag utente in corso + comando agente `move`/`arrange` sulla stessa finestra ⇒ vince
    l'interazione utente: durante una sessione di drag attiva le mutazioni di geometria
    esterne su quella finestra sono ignorate.
11. Drag sopra moduli con canvas (whiteboard/3D) ⇒ il drag parte solo dall'header, mai dal
    corpo; il resize notifica i moduli (i viewer canvas usano già ResizeObserver/fit — da
    verificare per xterm `fit` nel TerminalModule).
12. Testo: durante drag/resize `user-select` disabilitato e pointer capture attivo (release
    fuori finestra app gestito da `pointercancel`).

**Moduli e comandi**
13. `window.open` con modulo sconosciuto o `params` non validi ⇒ errore pulito nel
    `command.result` (la validazione args del bridge già rifiuta chiavi extra).
14. `window.close`/`focus` con `window_id` inesistente ⇒ `{ ok: false, error }` pulito,
    mai eccezione.
15. Modulo registrato ma `available()` diventa false a runtime (es. plugin disattivato) ⇒
    la finestra resta con corpo in empty-state "Modulo non disponibile" (UiEmptyState) +
    azione chiudi; il lanciatore sparisce dal dock.
16. Fallimento del lazy-load del componente modulo ⇒ stato d'errore nel corpo finestra con
    retry; la scena non crasha.
17. Singleton (chat, plan, terminal, attività): `open` ripetuto ⇒ focus + restore, mai
    duplicato — identico per dock, intents e comando agente (una sola implementazione).
18. Multi-istanza (chart, whiteboard, cad3d): più finestre stesso modulo con `params`
    diversi; id generati `crypto.randomUUID()`; il punto-stato nel dock riflette "≥1 aperta".
19. Comando `window.*` mentre l'utente è su un'altra vista ⇒ `window.open` naviga ad
    `assistant` prima di aprire; gli altri agiscono comunque sullo store (le finestre si
    trovano coerenti al rientro).
20. Nessun frontend connesso ⇒ già gestito dal bridge backend ("UI not available").
21. HMR: `installDeskCommands` unregister+register (nessun `DuplicateCommandError`).

**Scena e stati**
22. Risposta in streaming + finestra trascinata sopra il testo ⇒ ammesso (layer ambientale
    sotto le finestre); l'affordance di materializzazione resta raggiungibile.
23. Turno voce e turni autonomi/headless: nessun cambiamento dei flussi backend; i frame
    già esistenti alimentano gli store, la scena reagisce.
24. `arrange` con finestre minimizzate ⇒ le salta (restano nel vassoio).
25. ActivityModule senza turno attivo ⇒ UiEmptyState; liste lunghe ⇒ scroll interno
    (nessuna virtualizzazione v1: i dati per turno sono già bounded nello store).
26. Reduced motion: animazioni decorative (apertura finestra, dissolve) dietro
    `[data-reduce-motion='true']`; drag/resize e spinner mai bloccati (regola del tema).
27. Dual-theme: solo token; il terminale in finestra mantiene i token non-flipping
    `--terminal-*` (già gestito dal modulo).

## 7. Gestione errori

Coerente con lo stile del repo: errori dei comandi sempre come risultato pulito (mai throw
verso il bridge), guard-empty-state nei moduli, log via console dev con parsimonia, toast
globali per gli errori di turno. Nessun nuovo pattern di error handling introdotto.

## 8. Testing

- **Nuove spec** (Vitest, come le spec esistenti di `horizonScene`/`tilingTree`):
  `deskGeometry.spec.ts` (clamp/cascata/normalizzazione/arrange), `desk.spec.ts` (azioni store:
  singleton, z-order, persistenza/migrazione, edge 1-6), `commands/desk.spec.ts` (handler:
  argomenti invalidi, id inesistenti, capability corrette nel manifest).
- **Aggiornate**: `horizonScene.spec.ts` (rimozione `presenting`).
- **Gate**: `npm run typecheck` (obbligatorio prima di considerare chiuso il FE) + `npm run lint`.
- **Contratti**: nessuna modifica backend ⇒ nessuna rigenerazione; il dispatcher
  `useEventsWebSocket.ts` non cambia (nessun frame nuovo).
- **Verifica manuale** end-to-end a fine implementazione: aprire/trascinare/ridimensionare
  finestre, comandi agente via chat, tutti gli stati della matrice §3.2, entrambi i temi.

## 9. Fuori scope (v1) e rischi

Fuori scope: mount app-wide del desk (lo store è già pronto), snapping magnetico ai bordi,
`window.move`/`resize` puntuali per l'agente, layout per-conversazione, multi-monitor
awareness, virtualizzazione liste Attività.

Rischi principali: (a) conflitti pointer con i moduli canvas — mitigato da drag solo-header
e verifica xterm fit; (b) regressioni sull'Esc-chain/voice wiring durante l'estrazione dei
composable — mitigato salvando la logica per blocchi con le spec della scena; (c) crescita
del chrome `DeskWindow` — tenerlo sotto ~200 righe, la matematica sta nei composable puri.

## 10. Criteri di accettazione

1. Tutti gli stati della matrice §3.2 visibili e corretti in **entrambi i temi**.
2. Finestre: drag, resize, focus, minimizza, chiudi, cascata, clamp, persistenza tra riavvii.
3. L'agente apre/chiude/dispone finestre via `app_command` rispettando i tier
   (in `plan`: open/focus/list sì, close no).
4. Il Workspace è invariato (nessun file suo modificato salvo il registry con il nuovo
   modulo Attività, che vi appare funzionante).
5. `HorizonView.vue` ≤ ~200 righe; nessun residuo `orb`; nessun colore/valore hardcoded
   fuori dai token; focus ring keyboard funzionante su finestre e dock.
6. Spec nuove verdi, typecheck e lint puliti.
