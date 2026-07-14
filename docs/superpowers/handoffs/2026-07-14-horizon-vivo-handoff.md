# Handoff — Horizon Vivo (stato al 2026-07-14) e pivot «Rete Neurale»

> Per la sessione che continua questo lavoro a contesto fresco. Contiene SOLO ciò che non è
> ricostruibile dal repo: stato, decisioni, gotchas pagati sul campo, pending, e il mandato per
> il prossimo lavoro. Fonti di verità nel repo: spec e piani citati sotto.

## Stato: HORIZON VIVO COMPLETO su `rework/horizon-atelier` (NON mergiato)

- Branch `rework/horizon-atelier` @ `82cabb2` contiene DUE strati completi:
  1. **Atelier desk scene** (finestre flottanti, store `desk`, comandi `window.*`, dock, modulo
     Attività) — piano `docs/superpowers/plans/2026-07-13-horizon-atelier-redesign.md`, task 0-10.
  2. **Horizon Vivo** (redesign estetico: stato `thinking` visibile, costellazione sinaptica,
     filamento vivo, piano manoscritto, banco, chrome foglio) — spec
     `docs/superpowers/specs/2026-07-13-horizon-vivo-aesthetic-design.md`, piano
     `docs/superpowers/plans/2026-07-13-horizon-vivo-aesthetic.md`, 11 task, ~20 commit
     (`f4f4100..82cabb2`).
- **Review finale olistica: «Approved for merge»** (subagent-driven: ogni task con doppia review
  spec+qualità; i fix di review sono commit dedicati, annotati anche nel piano). Gates verdi:
  **350 vitest, typecheck node+web, lint zero warning**.
- Il codice committato PREVALE sui blocchi di codice del piano (i fix di review sono elencati
  nella sezione self-review del piano Vivo).

## Pending (da fare alla prossima occasione)

1. **Verifica manuale nell'app viva MAI eseguita** (T11.2 del piano Vivo, checklist in spec §13):
   stati quiet/listening/thinking/responding/working, marginalia con modello in extended
   thinking, piano manoscritto (reveal, collasso >7 passi), banco leggibile a ogni altezza,
   finestre (posarsi/scivolare/filo dorato), entrambi i temi, `prefers-reduced-motion`,
   viewport basso. Due punti estetici segnalati dalle review da giudicare A OCCHIO:
   noduli che si staccano dalla membrana in `tense` a volume alto; `flow` + impulsi insieme
   (working senza piano) potrebbe risultare affollato.
2. **Merge in main**: il branch è pronto; decidere se mergiare PRIMA del pivot (consigliato:
   main riceve uno stato buono e il pivot riparte pulito) o dopo.

## Prossimo lavoro (mandato dell'utente, 2026-07-14): pivot «Rete Neurale»

**Eliminare del tutto la linea d'orizzonte e rendere la rete neurale la protagonista della
scena.** Studio consapevolmente lasciato alla prossima sessione. Assessment già condiviso con
l'utente (non ancora validato da brainstorming):

- La linea oggi fa TRE lavori da ricollocare sulla rete: membrana audio-reattiva (`tense`),
  timeline del piano (tacche+scintilla), label di stato (ASCOLTO/RAGIONO/…).
- Il layout a quota (upper/line/lower in `HorizonScene`) può restare come macchina invisibile —
  sparisce solo il disegno; niente stravolgimento di zoning.
- `HorizonSky` si promuove a tutta scena con coreografie di stato (audio-reattività inclusa);
  `HorizonLine` si elimina o si svuota; dendrite del piano e dendriti della marginalia si
  riancorano alla rete; glow del composer resta.
- Il brain (`horizonScene.ts`) e i suoi test sopravvivono quasi interamente (gli stati non
  cambiano; cambia la coreografia). Stima: 4-5 task, ~1/3 dell'effort del piano Vivo.
- **Processo richiesto dall'utente**: brainstorming (mockup animati nel visual companion hanno
  funzionato molto bene — le decisioni A2+B2/manoscritto/banco vengono da lì) → spec → piano →
  subagent-driven con doppia review. **Skill OBBLIGATORIE: dev-discipline, dev-communication,
  frontend-design.** Le scelte estetiche sono dell'utente: proporre 2-3 direzioni, mai decidere
  al suo posto.

## Gotchas pagati sul campo (non ricostruibili dal diff)

- **Canvas con loop sospendibile**: se il rAF si sospende (idle settled), `resize()` e il
  MutationObserver del tema DEVONO ridisegnare esplicitamente (`if (reducedMotion || !running)
  draw(...)`) — assegnare `el.width` cancella il bitmap anche a valore invariato, e l'observer
  iniziale del ResizeObserver arriva DOPO il primo frame → cielo bianco al mount. In `loop()`
  serve il doppio guard `if (!running) return` attorno a `draw()` o un restart crea due catene
  rAF. `start()` non deve armarsi con `document.hidden`. Tutto già implementato in `HorizonSky`
  — riusare quel pattern, non quello di `HorizonLine` (che non si sospende mai; il suo TODO di
  sospensione erediterebbe questi buchi).
- **TransitionGroup stagger**: `transition-delay` su `enter-active` colpisce anche gli enter
  successivi (passi aggiunti mid-run con ~0.5-1s di lag). Lo stagger va su classi APPEAR-only
  (`appear-active-class`), e la classe appear va anche nel blocco reduced-motion.
- **`leave-active` con `position: absolute` in colonna flex**: la riga salta in cima (regola
  static-position del sole-flex-item) e perde il vincolo di larghezza → `position: relative`
  sul contenitore + `max-width: 100%` sulla leave class.
- **`aria-live` su nodo ricreato da `mode="out-in"`** è inaffidabile per gli screen reader:
  va sul wrapper stabile. E il contenuto derivato da stream può essere vuoto all'inizio
  (`lastThinkingLine` filtra blank/`---`) → guard `v-if` o si renderizza «».
- **Box-shadow con numero di layer diverso tra stati non interpola** (il glow "poppa"): pareggia
  i layer con alpha 0 nello stato di riposo.
- **Ground bench**: `.hz-scene__lower` riserva la fascia col `padding-bottom: clamp(78px,13vh,112px)`
  (senza, magazine e piani lunghi scivolano sotto il banco); ground `pointer-events: none`
  (niente dead-zone per le finestre), dock e colofone `auto`, entrambi nella exclusion list di
  `handleSceneClick`.
- **`thinkingSignalNext` è edge-triggered, non level-based** (thinking cresce→true, contenuto
  cresce→false, reset buffer→re-baseline): regge i tool loop multi-iterazione dove "contenuto
  vuoto" fallirebbe. Non sostituirlo con un check di stato.
- **`manuscriptView` pinna il passo attivo** attraverso il collasso «+N» (param `activeIndex`).
- **Grana SOLO sul chrome** (scena, header finestre), MAI sul contenuto dei moduli — il
  terminale resta pulito/dark (lezione storica del repo).
- **Componenti `desk/` surface-agnostic**: token `--hz-*` SOLO con fallback su token tema
  (`var(--hz-x, var(--fallback))`); nessun import horizon.
- **Convenzioni di branch**: commit single-line convenzionali SENZA Co-Authored-By; lint a ZERO
  warning (`npx eslint --fix` per i nit prettier, verificando diff formatting-only); gates da
  `frontend/` in PowerShell 5.1 (`;` non `&&`): `npx vitest run; npm run typecheck; npm run lint`.
- **Solo token, dual-theme**: pattern sanzionato `rgba(var(--hz-line-rgb), α)`; i letterali
  vivono solo nelle definizioni token di `horizon.css` (light override incluso).
  `prefers-reduced-motion` su OGNI animazione continua; stati sempre anche testuali; mai
  `outline: none` senza sostituto di focus.
- **Workspace = superficie di prodotto, INTOCCABILE**; i moduli sono condivisi: solo il chrome
  finestra cambia veste, mai gli interni.

## Mappa dei file (strato Vivo)

- `composables/horizon/horizonScene.ts` (+spec): brain puro — stati (incl. `thinking`),
  `deriveSkyMode`, `manuscriptView` (pin attivo), `thinkingSignalNext`, `lastThinkingLine`.
- `composables/horizon/useThinkingSignal.ts`: wrapper Vue del reducer (store chat → boolean).
- `components/horizon/HorizonSky.vue`: costellazione+spore, canvas dichiarativo col pattern di
  sospensione COMPLETO (il riferimento per il pivot).
- `components/horizon/HorizonLine.vue`: linea (breathe/tense/pulse/timeline/flow) + noduli +
  impulsi — il pezzo che il pivot elimina/svuota.
- `components/horizon/HorizonThinking.vue`: marginalia (throttle 600ms, cross-fade, dendriti).
- `components/horizon/HorizonPlan.vue`: manoscritto (TransitionGroup, appear-only stagger).
- `components/horizon/HorizonScene.vue`: zoning a quota + sfondo materico + host del cielo.
- `views/HorizonView.vue`: orchestrazione (sceneInputs, label, ground bench, wiring).
- `components/desk/DeskDock.vue`, `DeskWindow.vue`: banco e foglio (chrome only).
- Token: `assets/styles/horizon.css` (materia: warmth/grain/vignette/sky-alpha/highlight/
  shadow-sheet, dual-theme).
