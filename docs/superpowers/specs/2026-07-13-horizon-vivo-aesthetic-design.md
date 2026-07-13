# Horizon «Vivo» — redesign estetico della scena assistente

**Data:** 2026-07-13
**Stato:** approvato (brainstorming con l'utente, decisioni confermate sezione per sezione)
**Ambito:** SOLO frontend, SOLO estetico/presentazionale. Nessun cambiamento a backend, contratti WS/REST, desk store, comandi `window.*`, geometrie, wiring keyboard/voice. Il Workspace resta intatto.
**Base:** branch `rework/horizon-atelier` (atelier desk scene completa, task 0–10 del piano precedente).

---

## 1. Perché

Diagnosi condivisa con l'utente sulla scena attuale:

1. **Il pensiero è invisibile.** Non si distingue quando il modello sta *ragionando* (e su cosa) da quando sta *generando* la risposta. Il segnale esiste già (`currentThinkingContent` nello store chat, frame WS `thinking`) ma la scena non lo mostra.
2. **Il piano è brutto, criptico e poco vivo.** Oggi: puntini sulla linea + solo il passo attivo leggibile + contatore. Non si capisce il piano nel suo insieme e il progresso non «si sente».
3. **Il colofone è illeggibile.** Il dock flottante (bottom `clamp(40px,6vh,56px)`) copre il colofone centrato in basso.
4. **Scena troppo piatta / anonima; effetti migliorabili.** Bella ma incompiuta: manca materia, atmosfera, profondità.

## 2. Direzione estetica (decisa dall'utente)

**«Filamento vivo + costellazione sinaptica», su base atelier materico con bagliore caldo.**
Fusione confermata dei mockup A2+B2 del brainstorming:

- **Materia dell'atelier (A):** carta con grana, inchiostro caldo, ombre morbide e profonde, filo d'oro.
- **Luce (B):** l'orizzonte *emette* luce vera — glow caldo, profondo, che respira.
- **Vita (A2):** la linea d'orizzonte è il sistema nervoso di Alice — noduli sinaptici che respirano, **impulsi di luce che viaggiano lungo il filamento** quando pensa/lavora, spore di luce che salgono, dendriti verso il pensiero.
- **Vita (B2):** nel cielo sopra l'orizzonte una **costellazione sinaptica** (nodi collegati) quasi invisibile in quiete, che **si accende in sequenza durante il ragionamento profondo**.

Invarianti: Fraunces, linea d'orizzonte come centro, entrambi i temi, token esistenti (i nuovi `--hz-*` sono alias/derivati di `theme.css`).

## 3. Architettura: scena a strati (decisa dall'utente)

Nessun canvas monolitico, nessuna dipendenza nuova (no WebGL). Strati dal fondo:

```
z0  sfondo materico          (CSS: gradiente radiale caldo + grana + vignettatura — HorizonScene)
z1  HorizonSky (NUOVO)       (canvas a tutta scena: costellazione + spore)
z2  HorizonLine (esteso)     (canvas striscia 64px: linea + noduli + impulsi + glow caldo)
z3  contenuti scena          (masthead, saluto, marginalia pensiero, composer, risposta, piano)
z4  DeskSurface / finestre   (invariato strutturalmente, chrome rivestito)
z5  banco (dock + colofone)  (fascia in basso ricomposta)
```

### 3.1 Stato `thinking` nel brain puro

`horizonScene.ts` — modifiche:

- `HorizonState` diventa `'quiet' | 'listening' | 'thinking' | 'responding' | 'working'`.
- `HorizonSceneInputs` guadagna `isThinking: boolean`. Lo fornisce un piccolo composable
  NUOVO `useThinkingSignal` (in `composables/horizon/`): diventa `true` quando
  `currentThinkingContent` cresce, torna `false` quando cresce `currentStreamContent` o lo
  streaming termina. Così funziona anche nei turni multi-iterazione (tool loop: il modello
  ri-ragiona dopo aver già prodotto contenuto). Logica di soglia pura estratta e testata
  (`thinkingSignalReducer` in `horizonScene.ts` o nel composable stesso, unit-testabile).
- Priorità aggiornata: **working ▸ thinking ▸ responding ▸ listening ▸ quiet**.
  (Tool attivi o piano vivo vincono sul thinking: il lavoro resta lo stato dominante; la costellazione può comunque accendersi — vedi 3.2.)
- `deriveLineMode`: `thinking → 'breathe'` (la vita del thinking la fanno impulsi e costellazione, non una nuova meccanica d'onda).
- NUOVO `deriveSkyMode(state, i): 'idle' | 'thinking' | 'working'` — pure function:
  `thinking` se `i.isThinking` (anche dentro working), altrimenti `working` se state è working, altrimenti `idle`.
- NUOVO `manuscriptView(steps, maxVisible = 7)` — pure function per il piano manoscritto (vedi §5): se `total > maxVisible`, i completati più vecchi collassano in una riga contatore («N completati ✓»), restando sempre visibili gli ultimi 2 completati, l'attivo e tutti i pendenti (con eventuale coda «+M») entro il tetto.
- `QUOTAS` in HorizonScene: `thinking: 0.6`.
- `planView`, `notchPositions` invariati.

Tutte le modifiche al brain hanno test in `horizonScene.spec.ts` (derivazione thinking, precedenze, skyMode, manuscriptView con piani corti/lunghi/tutti-completati).

### 3.2 `HorizonSky.vue` (NUOVO)

Canvas 2D a tutta scena dietro ai contenuti. Stessa disciplina di HorizonLine:

- Props dichiarative: `mode: 'idle' | 'thinking' | 'working'`, `dimmed: boolean`.
- **Costellazione:** ~20 nodi con posizioni pseudo-casuali generate al mount (seed fisso per stabilità visiva tra i frame; sopra la linea, mai nella fascia contenuti centrale), collegati da segmenti sottili. In `idle`: alpha quasi zero (presenza subliminale). In `thinking`: i nodi si accendono in sequenza (wake progressivo, luce d'accento calda), i segmenti si illuminano al passaggio. In `working`: costellazione tenue + **spore** (≤6 punti di luce che salgono lentamente dalla quota della linea e svaniscono).
- Un solo rAF, **sospeso** quando `mode === 'idle'` (dopo il fade-out) e su `document.hidden`; `prefers-reduced-motion` = disegno statico singolo (costellazione fissa tenue, niente spore).
- Colori da `--hz-line-rgb`/`--hz-gold-rgb` via MutationObserver su `data-theme` (pattern identico a HorizonLine). Nessuna allocazione per frame (buffer di nodi/spore pre-allocati).
- Nel tema chiaro: inchiostro tenue su carta (alpha ridotte via token, non altro codice).

### 3.3 `HorizonLine.vue` (esteso, non riscritto)

- **Noduli sinaptici:** 3–4 punti fissi sulla linea (frazioni costanti dello span) che respirano in ogni modalità; nel timeline non competono con le tacche del piano (i noduli si spengono quando `notchCount > 0`).
- **Impulsi:** nuova prop `impulses: boolean` — pacchetti di luce che viaggiano lungo il filamento (2 in volo, sfasati). La vista la attiva per `thinking` e `working`. Componibile con ogni mode (overlay, come oggi il pulse).
- **Glow caldo:** shadowBlur/alpha della linea rivisti (più profondo, respiro lento 5s in breathe), secondo strato di glow sfocato. Valori dai token.
- Reduced-motion: come oggi — disegno statico, niente impulsi.

### 3.4 Marginalia del pensiero — `HorizonThinking.vue` (NUOVO)

- Mostra l'**ultima riga significativa** di `currentThinkingContent` (ultima riga non vuota, troncata a ~120ch), in Fraunces corsivo, colore `--hz-ink-dim`, sopra la linea (zona upper), preceduta da «sta ragionando — ».
- Cross-fade morbido quando la riga cambia (niente scatti a ogni token: aggiornamento throttled ~600ms).
- Compare solo negli stati `thinking` e `working` (se c'è thinking attivo); si dissolve quando inizia la risposta.
- Label della linea: `RAGIONO` in thinking (si aggiunge a ASCOLTO/ELABORO/RISPONDO/LAVORO).
- Dendriti: 2–3 tratti SVG sottili che «crescono» dalla linea verso la marginalia quando appare (stroke-dashoffset, CSS-only, disattivati con reduced-motion).

## 4. Stati visibili (contratto UX)

| Stato | Linea | Cielo | Contenuto |
|---|---|---|---|
| quiet | breathe + noduli + glow lento | costellazione subliminale | saluto (respiro 6s), ultima risposta |
| listening | tense (membrana audio) | subliminale | composer/transcript |
| **thinking** | breathe + **impulsi** | **costellazione che si accende** | **marginalia del pensiero + RAGIONO** |
| responding | breathe (pulse se TTS) | ritorno graduale a subliminale | risposta paced (marginalia si dissolve) |
| working | timeline/flow + impulsi | tenue + **spore** | piano manoscritto + annotazione tool (+ marginalia se thinking attivo) |

La distinzione pensare/generare è strutturale nella scena: stati diversi, non un badge.

## 5. Piano «Manoscritto» (deciso dall'utente: variante A)

`HorizonPlan.vue` riscritto (solo presentazione; dati invariati da `tasksStore`):

- **Lista verticale centrata** sotto la linea, collegata da un **dendrite** (1px sfumato) al centro della linea.
- **Reveal scaglionato:** alla creazione del piano i passi appaiono uno a uno (fade+rise 80ms di stagger, animation-delay per indice; solo al primo apparire di quel piano, non a ogni update; reduced-motion = tutti subito).
- **Passo attivo:** avorio pieno (`--hz-ink`), corpo maggiore, nodulo dorato che respira a sinistra.
- **Completato:** barrato con inchiostro dorato sottile (`text-decoration` con colore accent, spunta ✓ dorata), ridotto e attenuato.
- **Pendente:** `--hz-ink-faint`, anellino vuoto.
- **Piani lunghi:** `manuscriptView` (§3.1) collassa i completati più vecchi in «N completati ✓»; il piano resta leggibile senza scroll nella scena.
- Contatore `X DI Y` e **annotazione tool effimera** restano (registro mono spaziato attuale).
- Le tacche sulla linea (timeline mode) restano come eco geometrica del manoscritto; le label orizzontali sui notch spariscono (erano la parte criptica).

## 6. Banco: dock + colofone (deciso dall'utente: B con scritte SOTTO)

Un solo oggetto «terra» centrato in basso, composto verticalmente: **vassoio sopra, colofone inciso sotto**.

- NUOVO contenitore di layout in `HorizonView` (`.horizon-view__ground`): absolute bottom center, colonna, gap piccolo. Ospita `DeskDock` e `HorizonColophon`.
- `DeskDock` **perde il proprio posizionamento assoluto** (position: static nel banco; il posizionamento è responsabilità del contenitore). Resta surface-agnostic: nessun import horizon. Vestito materico: gradiente legno scuro/carta scura da token, bordo caldo, ombra profonda, highlight interno; punto dorato che respira sul modulo aperto (animazione CSS), punto spento su minimizzato; chip `PIANO n/m` integrata nel vassoio dopo un divisore verticale; badge Attività invariato.
- `HorizonColophon`: sotto il vassoio, mai coperto; registro attuale (piccole maiuscole spaziate) rifinito; `DISCONNESSA` resta nel colofone; titoli evento lunghi ellissizzati (max ~48ch).
- La nav d'angolo (CONVERSAZIONE · WORKSPACE) resta in basso a destra, invariata.
- Su viewport bassi il banco comprime i gap (clamp), mai sovrapposizioni.

## 7. Superfici e micro-interazioni

- **DeskWindow (solo chrome/CSS + transizioni):** fondo carta con grana appena percettibile, bordo caldo, ombra doppia (contatto + diffusa). Finestra a fuoco: **filo dorato sul bordo superiore** (pseudo-elemento sfumato) al posto del semplice cambio bordo. Apertura: il foglio *si posa* (scale .96→1 + fade, ~250ms, `--ease-out`). Minimizzazione: scivola verso il basso-centro (verso il banco) con fade ~200ms (Vue `<Transition>` su `v-show`; niente coordinate esatte del dock — YAGNI). Nessuna animazione su drag/resize. Reduced-motion: solo fade.
- **Composer/Cockpit:** al materializzarsi del composer il bagliore della linea **si concentra sotto il campo di testo** (gradiente/ombra dorata che segue lo stato attivo); bottoni kit invariati, dress compound sui token materici.
- **HorizonResponse:** misura tipografica controllata (max ~62ch), **capolettera leggero** in Fraunces sulla prima riga in modalità magazine, filetti separatori dorati sottili al posto dei bordi neutri. Pacing invariato.
- **Masthead/Quiete:** masthead allineato al registro del colofone; saluto in quiete con respiro d'opacità 6s (disattivato con reduced-motion).

## 8. Token e temi

- Nuovi token in `horizon.css`, tutti alias/derivati di `theme.css`:
  `--hz-gold-rgb` (triplet accent per canvas — dark: `232,220,200`-warm; light override come già per `--hz-line-rgb`), `--hz-glow-strength`, `--hz-grain-opacity`, `--hz-sky-alpha`, `--hz-shadow-sheet` (ombra doppia finestre), `--hz-vignette`.
- Grana: pattern CSS puro (repeating-conic, 3px) su pseudo-elemento di HorizonScene; nessun asset esterno; opacità da token (più visibile nel tema chiaro).
- `[data-theme='light']`: costellazione = inchiostro tenue, glow discreto, grana +, ombre −. Nessun colore hardcoded nei componenti (regola kit).

## 9. Accessibilità, motion, performance

- `prefers-reduced-motion: reduce`: nessuna animazione continua — costellazione statica tenue, niente impulsi/spore/dendriti/respiri, reveal del piano istantaneo, transizioni finestre = solo fade. Stessa disciplina già in HorizonLine.
- Focus ring sempre visibile (mai `outline: none` senza ripristino) su banco, finestre, composer.
- Gli stati sono sempre anche **testuali** (label RAGIONO/RISPONDO/LAVORO, marginalia, contatore piano): mai solo colore/motion.
- HorizonSky: 1 rAF sospeso in idle e su hidden; ≤20 nodi, ≤6 spore, zero allocazioni per frame. HorizonLine: invariato il TODO esistente sull'idle (fuori scope).
- Canvas `aria-hidden`; la marginalia è testo reale (leggibile da screen reader).

## 10. Cosa NON cambia (esplicito)

- Backend, contratti WS/REST, tipi generati.
- `desk` store, `deskGeometry`, `useWindowInteractions`, comandi `window.*`, `DeskSurface`.
- `useHorizonKeyboard`, `useHorizonVoiceBridge`, `useSentencePacer`, `horizonArtifacts`.
- I **contenuti** dei moduli (ChatModule, Terminale, Attività, …): condivisi col Workspace, solo il chrome finestra cambia veste.
- Il Workspace e ogni altra vista.

## 11. File toccati (riassunto)

| Azione | File |
|---|---|
| Modify | `assets/styles/horizon.css` (token), `composables/horizon/horizonScene.ts` (+spec), `components/horizon/HorizonScene.vue`, `HorizonLine.vue`, `HorizonPlan.vue`, `HorizonColophon.vue`, `HorizonMasthead.vue`, `HorizonQuiet.vue`, `HorizonComposer.vue`, `HorizonCockpit.vue`, `HorizonResponse.vue`, `views/HorizonView.vue`, `components/desk/DeskWindow.vue`, `components/desk/DeskDock.vue` |
| Create | `components/horizon/HorizonSky.vue`, `components/horizon/HorizonThinking.vue`, `composables/horizon/useThinkingSignal.ts` (+ test sulla logica pura) |
| Nessun file eliminato; nessun modulo/route/store nuovo. | |

## 12. Edge case e decisioni

1. **Thinking dentro working** (tool + reasoning interleaved): stato resta `working`; costellazione si accende comunque (`deriveSkyMode` guarda `isThinking`), marginalia visibile sopra il piano.
2. **Thinking poi risposta:** al primo token di contenuto `useThinkingSignal` scatta a false → transizione a `responding`, marginalia cross-fade out. Se il modello ri-ragiona in un'iterazione successiva, il segnale torna true.
3. **Modelli senza extended thinking:** `currentThinkingContent` resta vuoto → mai stato thinking, scena identica a oggi (degradazione pulita).
4. **Thinking multi-iterazione** (accumulato con `---`): la marginalia mostra solo l'ultima riga significativa; i separatori sono filtrati.
5. **Piano aggiornato in corsa** (passi aggiunti/rimossi da `update_plan`): i passi nuovi entrano col fade singolo (non ri-scaglionare tutto); `manuscriptView` ricalcola il collasso.
6. **Piano > 7 passi:** collasso «N completati ✓» (§5); il piano non spinge mai il colofone/banco fuori scena (max-height con fade, niente scroll interno).
7. **Tutti i passi completati** (`planActive` false): il manoscritto si dissolve dopo un beat (com'è oggi per lo stato working che decade).
8. **Viewport basso (<600px):** banco compattato (gap clamp), quota linea invariata, marginalia max 1 riga.
9. **Finestre sopra la costellazione:** il cielo è dietro (z1 vs z4) e attenuato; nessuna interferenza di leggibilità. Con `dimmed` (dialogo davanti) il cielo si spegne insieme alla scena.
10. **Doppio rAF (line + sky):** budget trascurabile (canvas 2D, pochi elementi); sky si sospende in idle; entrambi si fermano su hidden.
11. **Tema cambiato a runtime:** entrambi i canvas rileggono i token via MutationObserver (pattern esistente).
12. **`prefers-reduced-motion`:** tutte le vite si congelano ma le informazioni restano (costellazione statica, label testuali, piano completo subito).
13. **Reveal del piano dopo reload/switch conversazione:** il piano ripristinato appare senza cerimonia (stagger solo su piano *nuovo* nel turno vivo: guardia su `isStreaming`).
14. **Colofone con evento lungo:** ellissi ~48ch; con `DISCONNESSA` il registro resta su una riga (ordine: data · ora · evento · stato).
15. **Chip PIANO nel banco** quando il piano non esiste: assente (come oggi, `plan.total > 0`).
16. **Minimizzazione con reduced-motion:** solo fade, nessuno slide.
17. **Impulsi in timeline mode:** viaggiano sotto le tacche senza oscurarle (alpha ridotta quando `notchCount > 0`).
18. **Idle totale** (quiet, nessuna finestra): unico motion = respiro lento di linea/saluto — la scena non deve mai sembrare un salvaschermo.

## 13. Testing e gate

- **Unit (vitest):** `horizonScene.spec.ts` esteso — stato thinking e precedenze, `deriveSkyMode`, `manuscriptView` (corto/lungo/collasso/tutti completati/vuoto), reducer di `useThinkingSignal` (cresce thinking → true; cresce contenuto/fine stream → false; ri-ragionamento → true). Gli altri pezzi sono canvas/CSS: niente unit test (coerente con la cultura del repo: spec solo sui moduli puri).
- **Gate:** `npx vitest run`, `npm run typecheck`, `npm run lint` — tutti verdi a ogni task.
- **Verifica manuale (skill verify/run):** checklist stati (quiet/listening/thinking/responding/working), piano manoscritto (reveal, progresso, collasso), banco (leggibilità colofone), finestre (fuoco, apertura, minimizzazione), entrambi i temi, reduced-motion, viewport basso.
