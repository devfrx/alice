# Horizon — Second Pass (correttivo) — Design

**Data:** 2026-06-10
**Stato:** design approvato in conversazione (approccio C: medaglioni persistenti + palco che sale)
**Ambito:** solo frontend (`frontend/src/renderer/src/`), vista assistente (Horizon).

## 1. Problemi riportati (con causa verificata)

1. **Moduli irraggiungibili** (piano, grafici, 3D, lavagna): lo stage si apre SOLO
   in automatico durante lo streaming ([HorizonView.vue](frontend/src/renderer/src/views/HorizonView.vue)
   watch su `artifacts.length` gate-ato su `isStreamingCurrentConversation`) e il
   piano è visibile solo nello stato `working`. Nessuna affordance manuale.
2. **Dossier fuori stile**: `HorizonHistory` è un pannello piatto attaccato al
   bordo; il software usa card flottanti (cfr. `AppSidebar`: inset 12px,
   `border-radius: 20px`, `--panel-shadow`).
3. **Composer illeggibile su testi lunghi**: `HorizonComposer` usa
   `textarea rows="1"` senza auto-grow → tutto su una riga con scroll interno.
4. **Parità funzioni con la vecchia input bar**: in Horizon mancano allegati,
   tools, tier permessi, scope, selettore modello, mic-button, context bar
   (tutti presenti in `ChatInput.vue`).
5. **Linea poco leggibile**: gli stati (breathe/tense/pulse/timeline/flow) si
   distinguono poco; le task sulla linea (HorizonPlan) sono troncate a 2 parole
   e poco evidenti.

## 2. Principi

- **Riuso prima di tutto**: nessun fork dei componenti chat esistenti; la
  contestualizzazione visiva avviene SOLO nel contenitore Horizon. Logica
  condivisa si estrae in composable, non si duplica.
- **La macchina a stati non cambia**: `deriveSceneState`/`deriveLineMode`
  restano intatte. Mensola e piano fissato sono presentazione (`ref` nella
  view), non stati.
- Palette/typography: solo token esistenti (`--hz-*`, `--surface-*`, theme).

## 3. Componenti

### 3.1 `HorizonShelf.vue` (NUOVO, ~80 righe) — i moduli abitano la scena

Fila orizzontale di medaglioni in mono maiuscoletto appena sotto la linea
(primo elemento della lower zone), idioma identico a etichette piano/affordance
(9px, letterspacing 0.25em, `--hz-ink-faint`, hover `--hz-ink`, transizione
`--hz-fade`).

- Un medaglione per artefatto: `{toRoman(i+1)} · {label(kind)}` con mapping
  `chart→GRAFICO`, `cad→MODELLO`, `whiteboard→LAVAGNA`. Click →
  `emit('open-artifact', i)` → la view setta `stageOpen=true; stageIndex=i`.
- Un medaglione `PIANO {completed}/{total}` quando `planSteps.length > 0`:
  click → `emit('toggle-plan')` → la view alterna `planPinned`.
- Aspetto attivo: il medaglione dell'artefatto mostrato a palco aperto e il
  medaglione PIANO con `planPinned` usano `--hz-gold`.
- Props: `artifacts: HorizonArtifact[]`, `planTotal: number`,
  `planCompleted: number`, `activeArtifactIndex: number | null`,
  `planPinned: boolean`. Emits: `open-artifact[number]`, `toggle-plan[]`.
- Visibilità (decisa dalla view): `artifacts.length > 0 || planSteps.length > 0`,
  in OGNI stato — in `presenting` la mensola fa da indice delle opere (il
  medaglione attivo in oro è la posizione corrente; cliccarne un altro naviga
  il palco). Respira: opacità modulata da una classe (animazione CSS lenta
  legata a `--hz-breath`), disattivata con `prefers-reduced-motion`.
- Helper puro `artifactLabel(kind)` aggiunto a
  `composables/horizon/horizonArtifacts.ts` (testabile in vitest).

### 3.2 Palco che sale (`HorizonStage` + view)

Solo transizione: il blocco stage entra con `translateY(48px) → 0` + opacità,
durata `--hz-morph`, easing `--ease-out-expo` (Transition wrapper nella view,
nome `hz-rise`). Esc/✕ invariati (il leave riusa la stessa curva). Nessun
cambio a navigazione ‹ ›, didascalie, viewer lazy.

`planPinned` (ref nella view):
- `HorizonPlan` v-if diventa `(sceneState === 'working' || planPinned) && planSteps.length > 0`.
- `HorizonLine` `notch-count` diventa `sceneState === 'working' || planPinned ? planSteps.length : 0`;
  HorizonLine disegna le tacche quando `notchCount > 0` in QUALSIASI modalità
  (oggi solo timeline) — tacche tenui fuori da `working`.
- Esc chain (onGlobalKeydown): speaking → streaming → stage → history →
  **planPinned** → composer.
- Reset su cambio conversazione: `planPinned = false` nel watch esistente.

### 3.3 Composer: multilinea + cockpit

`HorizonComposer.vue`:
- Auto-grow col pattern `autoResize` di `ChatInput` (height = min(scrollHeight,
  ~5 righe)); oltre, scroll interno con `scrollbar-width: thin`.
- Allineamento: centrato su riga singola; quando il contenuto va a capo
  (scrollHeight > altezza monolinea) passa a `text-align: left` (classe
  `hz-composer__input--multi`).
- `Shift+Enter` inserisce newline (già così: il branch send è solo
  `Enter && !shiftKey`); `spellcheck` invariato.

`HorizonCockpit.vue` (NUOVO, ~120 righe): barra controlli sotto la riga serif,
visibile solo con `composerActive`, dissolvenza `hz-soft`. Contiene, RIUSATI
così come sono: `ChatToolControls`, `PermissionTierSelector`, `ScopeIndicator`,
`ModelSelector`, `MicrophoneButton`, bottone allegati + thumbnails, bottone
invia/stop, `ContextBar` (riga sottile sopra il rail). Guscio: colonna larga
come il composer, hairline `--border` superiore, riga flex con gap, sfondi
trasparenti; NESSUN override `:deep` dei componenti ospitati oltre a margini.
- Allegati gate-ati su `supportsVision` (come in ChatInput).
- Mic: wiring agli stessi handler `useVoice` già presenti nella view.
- Invia: `emit('send')` delegato al composer (testo) + allegati pendenti;
  stop visibile durante streaming (`stopGeneration`).

`useChatAttachments.ts` (NUOVO composable, estratto da `ChatInput.vue`):
`pendingFiles`, `thumbnailUrls`, validazione immagini, `addFiles`,
`removeFile`, `clear`, handler drag&drop e paste, revoke dei blob-URL in
unmount. `ChatInput.vue` viene rifattorizzato per consumarlo (comportamento
identico, nessun cambio di template/emits); `HorizonCockpit` lo consuma per la
parte allegati. `HorizonView.handleComposerSend` passa gli allegati a
`chatApi.sendMessage` (stessa firma usata dal workspace).

### 3.4 Dossier a card (`HorizonHistory`)

Solo guscio: `left: 12px`, `top: calc(var(--titlebar-height, 38px) + 8px)`,
`bottom: 8px`, `border-radius: 20px`, `border: 1px solid var(--border)`,
`box-shadow: var(--panel-shadow, var(--shadow-md))`, sfondo `var(--surface-1)`.
Slide-in conservata (translateX(-100%) → 0, si aggiunge fade). Tipografia
interna (rubriche mono, corpi serif, filetti, azioni) invariata.

### 3.5 Linea: microetichetta + firme di moto (`HorizonLine`)

- **Microetichetta**: nuova prop `label: string` ('' = nascosta), resa come
  `<span>` DOM nel wrapper del canvas, ancorata al capo destro della linea,
  mono 9px, letterspacing 0.3em, `--hz-ink-faint`, fade `--hz-fade`. La view
  la calcola: `ASCOLTO` (listening), `ELABORO` (sttProcessing), `RISPONDO`
  (responding), `LAVORO {n} DI {m}` (working), `OPERE` (presenting), ''
  (quiet — la quiete resta muta).
- **Firme** (ritocchi nel draw esistente, nessuna nuova modalità):
  - tense (ascolto): scala dell'ampiezza audio ×1.6, increspatura asimmetrica
    verso l'alto;
  - pulse (risposta): cresta viaggiante sinistra→destra con coda in
    dissolvenza, contrasto della cresta aumentato;
  - timeline (lavoro): tacche più alte (~9px), completate piene (alpha 1),
    future accennate (alpha 0.25), attiva con alone oro della scintilla;
  - flow (presentazione): ampiezza e alpha ridotte (linea quasi piatta);
  - breathe (quiete): invariata.
- `prefers-reduced-motion` continua a disattivare le animazioni non
  essenziali (già gestito).

### 3.6 Piano sulla linea (`HorizonPlan`)

- Etichetta ATTIVA: testo completo fino a ~40ch (ellissi oltre), `--hz-gold`,
  10px — non più troncata a 2 parole.
- Step non attivi: nessuna etichetta testuale; resta il marcatore (tacca sul
  canvas) + `title` tooltip sull'area cliccabile del label layer (marcatore
  `·` posizionato come oggi). Completate attenuate.
- Contatore `N DI M` e annotazione tool effimera invariati.
- La regola "≤6 mostra tutte" viene rimossa (sostituita dal modello
  attiva-in-evidenza + tooltip), eliminando il problema delle collisioni.

## 4. Cosa NON cambia

Macchina a stati e relative spec vitest; pacer; rivista (magazine); flussi
voce; dialoghi sopra la scena attenuata; `extractArtifacts`; TaskStrip del
workspace; backend.

## 5. Test e verifica

- Vitest (moduli puri soltanto, come da convenzione): `artifactLabel` in
  `horizonArtifacts.spec.ts`; eventuali helper nuovi in `horizonScene` se
  emergono nel piano. Nessuna spec per componenti (.vue non importabili).
- `npm run typecheck` + `npm run lint` puliti.
- Smoke manuale: (a) conversazione con grafico → medaglione visibile in
  quiete, click apre il palco, Esc lo chiude, medaglione resta; (b) testo
  lungo nel composer → multilinea leggibile; (c) cockpit: allegato immagine +
  cambio tier + tools visibili; (d) drawer STORIA a card; (e) etichette di
  stato durante ascolto/risposta/lavoro; (f) piano fissato da medaglione PIANO
  fuori dallo stato lavoro.

## 6. Fuori ambito

Backend; intent della home; TaskStrip/ChatPanel del workspace (salvo il
refactor trasparente di `ChatInput.vue` → `useChatAttachments`); persistenza
di `planPinned`/`stageOpen` tra sessioni.
