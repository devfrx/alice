# AL\CE — UI Revamp in stile Claude Desktop · Design

**Data:** 2026-06-05
**Branch:** `refactor/ui-claude-revamp`
**Stato:** approvato (brainstorming) — pronto per il piano della Fase 1

---

## 1. Obiettivo

Revamp completo dello stile e del layout dell'applicazione desktop AL\CE, adottando
l'**estetica di Claude Desktop** e un **layout modulare a pannelli** ispirato alla
sezione Claude Code dell'app desktop (pannelli laterali resizabili e togglabili).

Il refactor **deve coprire l'intera app**: ogni vista e ogni componente del
frontend (`frontend/src/renderer/src/`). Per gestirlo in sicurezza il lavoro è
decomposto in **tre fasi sequenziali**, ognuna con il proprio ciclo
spec → piano → esecuzione. **Questo documento è lo spec della Fase 1**; le Fasi 2 e 3
sono delineate in §9 e avranno spec propri.

Non-obiettivi: nessuna modifica al backend, ai contratti WebSocket/REST, alle store
Pinia o alla logica applicativa, se non lo stretto necessario per supportare il nuovo
guscio a pannelli (toggle/persistenza layout via store UI). Nessuna nuova feature
funzionale: è un refactor di **forma**, non di comportamento.

---

## 2. Decisioni di design (validate nel brainstorming)

| Tema | Decisione |
|---|---|
| Direzione | Estetica Claude **completa** + layout modulare a pannelli |
| Temi | light + dark, **default light**; riusa l'infrastruttura `data-theme` esistente |
| Accent (dark) | crema **`#E8DCC8`** — identità AL\CE attuale, invariata |
| Accent (light) | **Taupe Mocha `#8C6A4A`** — versione professionale leggibile su avorio (tonalità rifinibile) |
| Tipografia | **titoli/display serif** (font libero, es. Newsreader/Source Serif); **corpo sans Geist**; Kaluar solo per wordmark/brand |
| Densità | più generosa dell'attuale: corpo chat ~15px, colonna leggibile ~720–760px, spaziature ampie |
| Shell | sidebar sinistra unica e collassabile (sezioni *Chat* + *Moduli*) |
| Pannelli | **zone fisse resizabili + toggle** (no drag-docking libero) |

### Palette di riferimento

**Light (default)**
- `--surface-0` carta `#FAF9F5` · `--surface-1` `#F3EFE9` · `--surface-2` `#EAE4DB`
- testo `#1F1E1B` / `#5C5349` / `#9E9890`
- accent `#8C6A4A` (Taupe Mocha) + scala di opacità derivata

**Dark**
- `--surface-0` `#262624` · `--surface-1` `#2D2C29` · `--surface-2` `#34322D`
- testo `#ECEAE3` / muted derivati
- accent `#E8DCC8` (crema) + scala di opacità derivata

> Le scale complete (hover/dim/border/glow per ogni accent, surface elevation,
> semantic state colors) vengono derivate sistematicamente in implementazione,
> mantenendo i **nomi dei token già esistenti** in `theme.css` per non rompere i
> consumatori. Le tonalità esatte sono rifinibili durante l'implementazione.

---

## 3. Architettura del guscio a pannelli

### Zone

```
┌────────┬───────────────────────┬──────────────┐
│        │                       │  COLONNA     │
│ SIDE   │      CHAT             │  DESTRA      │
│ BAR    │      (centrale)       │  (stack      │
│        │                       │   moduli)    │
│        ├───────────────────────┴──────────────┤
│        │        DOCK INFERIORE (moduli)        │
└────────┴──────────────────────────────────────┘
```

- **Sidebar** (sinistra): collassabile. Sezioni *Chat recenti* e *Moduli*.
- **Chat** (centrale): zona principale, sempre presente.
- **Colonna destra**: impila uno o più moduli verticalmente; apribile/chiudibile.
- **Dock inferiore**: ospita moduli "orizzontali" (log, terminale, anteprime); apribile/chiudibile.

### Proprietà

- Tutti i divisori tra zone sono **trascinabili** (resize). Le zone hanno min/max sensati.
- **Niente drag libero** per riposizionare i pannelli tra zone (esplicitamente fuori scope).
- Il **layout è persistito**: dimensioni delle zone + quali moduli sono aperti e in quale zona.
  Persistenza nello store UI (`stores/ui.ts`) → `localStorage` (o backend settings se già usato per la UI).
- Libreria resize proposta: **`splitpanes`** (Vue 3) — **da validare nel piano** (alternativa: implementazione custom con pointer events). La scelta non deve trapelare oltre un wrapper interno.

### Contratto di un modulo

Ogni modulo è un componente Vue autonomo che espone:
- **header**: titolo, azioni opzionali, pulsante chiudi;
- **content**: il contenuto del modulo;
- **empty state**: stato vuoto curato (icona + testo) quando non c'è contenuto.

Registrazione moduli centralizzata (id, label, icona, zona di default, componente),
così la sidebar *Moduli* e il sistema di toggle li scoprono in modo uniforme.

### Componenti nuovi (Fase 1)

- `PanelWorkspace.vue` — orchestratore delle zone + divisori resizabili.
- `PanelZone.vue` — contenitore di una zona (stack di moduli, gestione apri/chiudi).
- `ModulePanel.vue` — wrapper header/content/empty-state per un modulo.
- `ModuleEmptyState.vue` — empty state riusabile.
- registro moduli (`composables/usePanelModules.ts` o simile) + estensione `stores/ui.ts` per stato layout.

---

## 4. Sistema di token (`assets/styles/theme.css`)

- Riscrittura della palette light **e** dark mantenendo **gli stessi nomi di token**
  già consumati in tutta la app (vedi inventario §8) per un refactor non-breaking.
- Aggiunta font stack serif display: `--font-display` → serif (con `@font-face` del
  font libero scelto, self-hosted in `assets/`).
- Revisione densità: scala tipografica del corpo verso ~15px in lettura chat;
  spaziature/altezze rivalutate.
- Verifica che **entrambi** i temi superino un contrasto AA sui testi principali.

---

## 5. Primitive UI condivise (`components/ui/`)

Restyle al nuovo linguaggio, **senza cambiarne le API/prop pubbliche** dove possibile:
bottoni, input/textarea, select/dropdown, modali (`ModalContainer.vue`), toast
(`UiToast`), loader (`AliceLoader`), `AppIcon`, tooltip, badge, e gli altri primitivi
presenti in `components/ui/`. Inventario completo da estrarre all'inizio del piano.

`TitleBar.vue` e `App.vue` (guscio) adattati al nuovo layout a pannelli.

---

## 6. Moduli pilota (Fase 1)

Per validare il sistema end-to-end senza entrare nelle Fasi 2/3:
- **Artifact / Grafici** (riusa `components/board` / `canvas` come contenuto) con empty state.
- Almeno **un secondo modulo segnaposto** (es. *Piano* o *Terminale/Log*) per provare colonna destra **e** dock inferiore.

Gli altri moduli (Whiteboard, Calendario, Email, 3D, Services) sono **agganciati ma
restilizzati nelle fasi successive** — in Fase 1 basta che il guscio li ospiti.

---

## 7. Testing & verifica (Fase 1)

- `npm run typecheck` (node + vue-tsc) e `npm run lint` puliti.
- Test esistenti dei componenti non devono regredire.
- Nuovi test unitari per la logica del workspace: toggle modulo, persistenza/ripristino
  layout, vincoli di resize (min/max), apertura/chiusura zone.
- Verifica manuale: switch light/dark, collasso sidebar, resize di ogni divisore,
  apertura/chiusura moduli in colonna destra e dock, ricarica con layout ripristinato.

---

## 8. Inventario di copertura (tutta l'app)

Per garantire che il refactor copra **tutto**, ogni vista/cartella va portata al
nuovo sistema entro la fine della Fase 3. Mappatura fase ↔ superficie:

**Viste (`views/`):** HomeView, AssistantView (voce), HybridView (chat),
CalendarPageView, EmailPageView, WhiteboardPageView, ServicesView, SettingsView,
ArtifactBoardView.

**Cartelle componenti (`components/`):** assistant, board, branding, calendar,
canvas, chat, email, input, plugins, services, settings, sidebar, ui, voice,
whiteboard, + root (TitleBar, ModalContainer, ErrorBoundary, Versions).

- **Fase 1**: `assets/styles/*` (token), `components/ui/*` (primitive), `sidebar/*`,
  TitleBar, App.vue, nuovi componenti pannelli, board/canvas come modulo pilota.
- **Fase 2**: `components/chat/*`, `components/input/*`, HybridView, ConversationList,
  selettore modello, code-blocks/markdown.
- **Fase 3**: assistant/voice, calendar, email, whiteboard, services, settings,
  plugins, branding, Home, le restanti viste e i moduli relativi.

---

## 9. Roadmap fasi successive (spec propri)

- **Fase 2 — Chat**: superficie conversazione completa nel nuovo linguaggio
  (messaggi utente/assistente, input, selettore modello, code blocks, markdown, lista
  conversazioni).
- **Fase 3 — Moduli & superfici**: Whiteboard, Calendario, Email, Services, 3D,
  Settings, Home, Voce portati nei moduli/nuovo sistema, con i rispettivi empty state.

---

## 10. Da validare in fase di piano

- Libreria di resize (`splitpanes` vs custom) — prova rapida di idoneità.
- Scelta del font serif display libero (Newsreader / Source Serif / altro) + licenza.
- Dove persistere il layout (store UI → localStorage vs backend settings UI esistente).
- Tonalità esatte finali degli accent e delle scale di opacità.
