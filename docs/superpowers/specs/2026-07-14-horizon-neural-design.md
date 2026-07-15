# Horizon «Rete Neurale» — pivot estetico: la rete al posto della linea

Data: 2026-07-14 · Stato: approvata dall'utente (brainstorming con mockup animati 3D nel visual
companion; direzione «a strati, 3D interattiva, flusso randomico» scelta dall'utente).
Base: `rework/horizon-atelier` @ Horizon Vivo completo (spec 2026-07-13).
Mockup di riferimento: `.superpowers/brainstorm/203-1784049699/content/stati-3d.html`
(+ correzione utente: flusso randomico, non solo ingresso→uscita).

## 1. Perché

La linea d'orizzonte ha esaurito il suo ruolo di protagonista: la costellazione sinaptica di
`HorizonSky` è l'elemento con più carattere della scena e l'utente vuole promuoverla a
protagonista assoluta — una **rete neurale 3D interattiva** a tutta scena, sul modello della
costellazione della landing page `alice-continuum-lp` (proiezione prospettica, profondità,
parallasse del cursore). La linea sparisce del tutto; i suoi cinque lavori si ricollocano
sulla rete.

## 2. Direzione estetica (decisa dall'utente)

- **Rete «a strati»**: cinque dischi di nodi lungo l'asse orizzontale — la silhouette di una
  rete neurale leggibile al primo sguardo, disegnata a inchiostro sulla carta dell'atelier.
- **3D vera**: prospettiva (nodi lontani piccoli e fiochi), ordinamento back-to-front,
  rotazione lenta **attorno all'asse degli strati** (i nodi orbitano nel proprio disco: la
  struttura ingresso→uscita resta sempre leggibile).
- **Interattiva**: parallasse del cursore smorzata (modello `useParallax` della LP) — la
  nuvola oscilla verso il mouse e torna a riposo.
- **Segnali causali**: i segnali viaggiano lungo gli archi come pacchetti di luce e i nodi
  lampeggiano **quando il segnale arriva**. Niente twinkle decorativo.
- **Flusso randomico** (correzione esplicita dell'utente): le propagazioni non sono vincolate
  alla direzione ingresso→uscita; i segnali saltano su qualunque arco. Restano semantici solo
  i capi: la voce **entra** dal disco-membrana (primo), la parola **esce** dal disco che parla
  (ultimo).
- Materia invariata: inchiostro `--hz-line-rgb` su carta, grana solo sul chrome, dual-theme.

## 3. Architettura

### 3.1 `neuralGraph.ts` (NUOVO — modulo puro)

`composables/horizon/neuralGraph.ts`: nessun import Vue/DOM, unit-testabile in node env
(stessa disciplina di `horizonScene.ts`). Contiene:

- `buildNeuralGraph(seed)`: 5 dischi lungo x (−1..1), ~6/8/9/8/6 nodi per disco su raggio
  0.52/0.74/0.88/0.74/0.52 (jitter x ±0.07), PRNG mulberry32 deterministico; archi = 2 vicini
  più prossimi (distanza y/z) nel disco adiacente, dedup, `edges` indicizzati per nodo;
  derivati: `byCol`, `plan` (per disco il nodo più vicino al centro del disco), `polar`
  (ancora della label: nodo più alto dell'ultimo disco).
- `projectNode(p, spin, swingY, viewport)`: rotazione attorno a x (spin del disco) poi
  oscillazione attorno a y (parallasse), camera prospettica a distanza `FOV = 3` raggi
  (fattore `persp = FOV / (FOV − z)`), mapping su viewport. Ritorna `{sx, sy, scale, z}`.
- `depthNorm(scale)`: normalizzazione della profondità per alpha/dimensione.
- `anyHop(graph, rand, from)` / helpers di simulazione puri usati dal componente
  (selezione arco casuale tra TUTTI gli archi del nodo — flusso randomico).

La matematica ricalca `src/lib/graph.ts` della LP ma è **riscritta e adattata qui** (dischi
invece di ellissoide, spin sull'asse x): nessun accoppiamento tra i repo.

### 3.2 `HorizonNeural.vue` (NUOVO — sostituisce `HorizonSky.vue`)

Canvas full-scene dichiarativo (solo props), `z-index: 0` sotto le zone contenuto,
`pointer-events: none` (il click-scena-per-voce non cambia). Props:

```ts
{
  state: HorizonState            // quiet | listening | thinking | responding | working
  audioLevel?: number            // 0–1 (membrana)
  speaking?: boolean             // TTS attivo (cadenza sillabica + anelli)
  planTotal?: number             // 0 = nessuna rotta
  planActiveIndex?: number
  planCompleted?: number
  planStepLabel?: string         // annotazione corsiva del passo attivo
  label?: string                 // microlabel di stato ('' = nascosta)
  dimmed?: boolean               // scena oscurata (dialog davanti)
}
```

Possiede: la simulazione (travelers/flash/anelli — vive nel componente, helpers puri nel
modulo), la camera (spin per stato + parallasse), il loop rAF **sospendibile col pattern
completo di `HorizonSky`** (riferimento indicato dall'handoff):

- resize e MutationObserver del tema ridisegnano esplicitamente se il loop è fermo
  (`if (reducedMotion || !running) draw(...)`);
- doppio guard `if (!running) return` attorno a `draw()` nel loop;
- `start()` non si arma con `document.hidden`;
- colori riletti da `--hz-line-rgb` / `--hz-sky-alpha` su cambio `data-theme`.

**Label DOM tracciata**: la microlabel di stato NON è disegnata nel canvas — è un elemento
DOM figlio (mono, letterspaced, con lineetta cartografica CSS) posizionato ogni frame sulla
proiezione del nodo `polar` (pattern `track`/`onTrack` della LP). Testo nitido e leggibile
dagli screen reader; il canvas resta `aria-hidden`. Quando il loop è sospeso la label resta
all'ultima posizione (coerente col frame statico).

### 3.3 Brain (`horizonScene.ts`) — modifiche minime

- Muoiono: `HorizonLineMode`, `deriveLineMode`, `notchPositions`, `deriveSkyMode`,
  `HorizonSkyMode`.
- Gli stati (`HorizonState`), `planView`, `manuscriptView`, `thinkingSignalNext`,
  `lastThinkingLine` restano intatti.
- La scelta della coreografia vive in `HorizonNeural` a partire da `state` + props: non serve
  una nuova funzione di derivazione nel brain (il mapping stato→coreografia è 1:1; `speaking`
  distingue la voce dentro `responding`).

### 3.4 `HorizonScene.vue` e `HorizonView.vue`

- `HorizonScene`: host di `HorizonNeural` al posto di `HorizonSky`; lo slot `#line` e la prop
  `sky` spariscono; **il zoning a quota resta identico** (upper/lower, transizioni di quota,
  `--quota`): sparisce solo il disegno della linea, non la macchina.
- `HorizonView`: rimuove `HorizonLine`, `lineMode`, `skyMode`; passa a `HorizonNeural` le
  props (audioLevel, speaking da `voiceStore.isSpeaking`, plan da `planView`, label attuale
  invariata nei testi). **`horizon-view__status` si elimina** (deciso in design review): la
  frase del passo attivo vive nell'annotazione corsiva sulla rotta + nel manoscritto.
- `HorizonLine.vue` si elimina dal repo.

## 4. Coreografie di stato (contratto UX, dal mockup approvato)

Cross-fade tra stati con intensità smorzate (mai tagli netti). Un solo set di segnali
(travelers) condiviso; le coreografie ne cambiano origine, ritmo e carattere.

| Stato | Coreografia | Camera |
|---|---|---|
| `quiet` | Scheletro fioco che respira; ogni ~4 s un **sogno**: un singolo segnale in passeggiata randomica attraverso la rete, senza diramarsi. | spin lentissimo |
| `listening` | Il primo disco È la membrana: i suoi nodi vibrano **radialmente** col waveform (`audioLevel`); il volume spinge attivazioni dentro la rete (1–2 salti randomici, poi muoiono). | spin lento |
| `thinking` | **Passaggi coerenti**: onde di attivazione attraversano i dischi in sequenza; direzione randomica per sweep (avanti/indietro/dal centro), ogni terzo più fioco (eco). | spin più svelto |
| `working` | La rete si attenua (~55%) e **si posa** (spin smorzato a zero, posa frontale); la **rotta** prende il proscenio: un ganglio per disco, segmenti accesi passo-passo, scintilla sul segmento attivo, annotazione corsiva (`planStepLabel`); sotto, brusio di segnali brevi randomici. Senza piano (`planTotal = 0`): solo il brusio (ex `flow`). | posa |
| `responding` | I segnali confluiscono verso il disco d'uscita (origini randomiche). Con `speaking`: cadenza sillabica del disco d'uscita + **anelli prospettici**; senza TTS: flusso quieto, niente anelli. | spin lento |

Label testuali invariate: ASCOLTO / ELABORO / RAGIONO / `LAVORO n DI m` / RISPONDO.

## 5. Interattività (parallasse)

- Mousemove su window → target −1..1, smorzamento esponenziale (`damp`, λ≈6);
  oscillazione attorno all'asse verticale (±~0.30 rad) + lieve inclinazione (±~0.22 rad).
- Solo pointer-fine; spenta sotto `prefers-reduced-motion`; a riposo (mouse fermo/uscito)
  converge a zero e NON tiene sveglio il loop (la sospensione della quiete vince: al settle
  del parallax il loop può fermarsi).
- Nessuna interazione a click sulla rete (il click-scena resta del toggle voce).

## 6. Sospensione e reduced-motion

- Quiete settled (intensità ≈ 0, nessun traveler, parallasse convergente) → **stop del loop**.
  Il sogno periodico è armato da un timer (`setTimeout ~4 s`) che risveglia il loop per la
  durata del sogno e lo lascia ri-sospendere. Zero lavoro idle tra i sogni.
- `document.hidden` → stop; visibile → start (come oggi).
- Reduced-motion: frame statico (rete in posa frontale, membrana/segnali/parallasse spenti,
  rotta con stato corrente), ridisegno esplicito a ogni cambio di props/tema/resize.
- Ogni animazione continua ha il suo ramo reduced-motion; stati sempre anche testuali.

## 7. Token e temi

Solo token esistenti: `--hz-line-rgb` (inchiostro), `--hz-sky-alpha` (presenza a riposo),
`--hz-ink-faint` (label DOM), `--font-mono`/`--hz-serif` (label/annotazione). Nessun nuovo
letterale; light theme gratis via override dei token in `horizon.css`. Se in implementazione
serve un'alpha dedicata alla rete (es. presenza in quiete diversa dal vecchio cielo), si
aggiunge UN token `--hz-neural-alpha` con override light, censito come gli altri.

## 8. Cosa NON cambia (esplicito)

- Gli stati del brain e la loro priorità; `thinkingSignalNext`; il piano manoscritto
  (`HorizonPlan`), la marginalia (`HorizonThinking`), composer/cockpit, banco (dock+colofone),
  finestre desk e i loro chrome; il click-scena-per-voce; il glow del composer.
- Il zoning a quota di `HorizonScene` (macchina invisibile).
- Workspace: intoccato (superficie di prodotto).

## 9. File toccati (riassunto)

- NUOVI: `composables/horizon/neuralGraph.ts` (+ `neuralGraph.spec.ts`),
  `components/horizon/HorizonNeural.vue`.
- MODIFICATI: `horizonScene.ts` (+spec — rimozione modi linea/sky), `HorizonScene.vue`,
  `HorizonView.vue`, `horizon.css` (eventuale token, pulizia stili `__status`).
- ELIMINATI: `components/horizon/HorizonLine.vue`, `components/horizon/HorizonSky.vue`.

## 10. Edge case e decisioni

- **Piano > 5 passi**: la rotta ha 5 gangli (uno per disco) ma il piano può averne N — la
  rotta mappa la *progressione* (`activeIndex/total` scalati sui 5 segmenti, riusando la
  logica proporzionale), il dettaglio resta al manoscritto. La scintilla non salta mai
  all'indietro se il piano cresce mid-run (si riancora come oggi al cambio piano).
- **Working senza piano**: solo brusio (nessuna rotta, nessuna annotazione); label `LAVORO`.
- **Dimmed** (dialog davanti): alpha globale ~0.35 come la linea oggi.
- **Disconnesso**: `dimmed` sulla rete (come la linea oggi con `dimmed`).
- **Viewport basso / resize**: la rete si riproietta (viewport nel projector); nessun minimo
  hard — la geometria è proporzionale.
- **`lineQuota`**: spariscono le spore legate alla quota; nessun accoppiamento residuo della
  rete con `--quota`.

## 11. Testing e gates

- `neuralGraph.spec.ts` (node env): determinismo del grafo (stesso seed → stessi nodi/archi),
  proprietà strutturali (5 dischi, archi solo tra dischi adiacenti, grado ≥ 1), proiezione
  (centro/estremi, monotonia della scala con z), `anyHop` vincolato agli archi del nodo,
  helpers di profondità.
- `horizonScene.spec.ts`: rimozione dei test dei modi linea/sky; il resto invariato.
- Component test esistenti che referenziano `HorizonLine`/`HorizonSky` aggiornati.
- Gates da `frontend/` (PowerShell 5.1, `;`): `npx vitest run; npm run typecheck; npm run lint`
  a **zero warning**. Commit single-line convenzionali senza Co-Authored-By.
- Esecuzione subagent-driven con doppia review (spec + qualità) per task.
- Verifica manuale nell'app viva a fine pivot (nuova checklist: 5 coreografie, parallasse,
  sospensione/sogno, entrambi i temi, reduced-motion, dimmed, viewport basso) — assorbe la
  parte superstite della checklist Vivo §13 (manoscritto, banco, finestre, temi).
