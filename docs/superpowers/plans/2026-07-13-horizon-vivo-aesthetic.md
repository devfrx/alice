# Horizon «Vivo» Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign puramente estetico/presentazionale della scena assistente Horizon: stato `thinking` visibile (marginalia + costellazione), piano «manoscritto», banco unico dock+colofone, materia e vita (grana, glow, noduli, impulsi, spore), chrome finestre rivestito.

**Architecture:** Scena a strati — nuovo canvas `HorizonSky` (costellazione + spore) dentro `HorizonScene`, `HorizonLine` esteso (noduli + impulsi), nuovo stato `thinking` nel brain puro `horizonScene.ts` alimentato dal composable `useThinkingSignal`; piano ridisegnato in `HorizonPlan`; banco in `HorizonView`. Solo frontend, zero dipendenze nuove, zero cambi a store desk/comandi/backend.

**Tech Stack:** Vue 3 `<script setup lang="ts">`, canvas 2D, Vitest, token CSS `theme.css`/`horizon.css`.

**Spec:** `docs/superpowers/specs/2026-07-13-horizon-vivo-aesthetic-design.md` (leggerla prima: contiene direzione, contratto UX e 18 edge case decisi).

**Convenzioni vincolanti** (CLAUDE.md + regole kit):
- Solo token, mai colori hardcoded (le uniche eccezioni ammesse: alpha dentro `rgba(var(--hz-line-rgb), α)` e i letterali *dentro* le definizioni token di `horizon.css`).
- Entrambi i temi devono funzionare; `prefers-reduced-motion` rispettato ovunque.
- Kit first; override solo compound. Mai `outline: none` senza alternativa di focus visibile.
- Comandi da `frontend/` in PowerShell. `npm run typecheck` è il gate obbligatorio.
- I componenti `desk/` restano surface-agnostic: se usano token `--hz-*` devono avere fallback su token tema (`var(--hz-x, var(--fallback))`).

---

### Task 0: Branch di lavoro

- [ ] **Step 0.1:** Verificare di essere su `rework/horizon-atelier` con albero pulito:

```powershell
git status --short; git branch --show-current
```

Expected: nessun file modificato, branch `rework/horizon-atelier`. Il lavoro continua su questo branch (il redesign estetico è lo strato successivo dell'atelier).

---

### Task 1: Brain puro — stato `thinking`, sky mode, manoscritto, reducer

**Files:**
- Modify: `frontend/src/renderer/src/composables/horizon/horizonScene.ts`
- Test: `frontend/src/renderer/src/composables/horizon/horizonScene.spec.ts`
- Modify (compilazione): `frontend/src/renderer/src/components/horizon/HorizonScene.vue` (QUOTAS), `frontend/src/renderer/src/views/HorizonView.vue` (input `isThinking: false`, sostituito nella Task 2)

- [ ] **Step 1.1: Estendere la spec esistente (test che falliscono)**

In `horizonScene.spec.ts`: aggiornare l'import e la factory `inputs()` (aggiungere `isThinking: false`), poi AGGIUNGERE i blocchi sotto. Il test esistente «never returns presenting» usa un literal completo: aggiungere `isThinking: false` anche lì.

```ts
// import esteso (sostituisce l'attuale):
import {
  deriveSceneState,
  deriveLineMode,
  deriveSkyMode,
  manuscriptView,
  thinkingSignalNext,
  THINKING_SIGNAL_IDLE,
  lastThinkingLine,
  notchPositions,
  planView,
  type HorizonSceneInputs
} from './horizonScene'
```

```ts
describe('deriveSceneState — thinking', () => {
  it('thinking while streaming with a live reasoning signal and no work', () => {
    expect(deriveSceneState(inputs({ isStreaming: true, isThinking: true }))).toBe('thinking')
  })

  it('working wins over thinking (tools or live plan)', () => {
    expect(
      deriveSceneState(inputs({ isStreaming: true, isThinking: true, activeToolCount: 1 }))
    ).toBe('working')
    expect(
      deriveSceneState(
        inputs({ isStreaming: true, isThinking: true, planSteps: [step('a', 'in_progress')] })
      )
    ).toBe('working')
  })

  it('thinking requires streaming (stale signal after cancel is inert)', () => {
    expect(deriveSceneState(inputs({ isThinking: true }))).toBe('quiet')
  })
})

describe('deriveLineMode — thinking', () => {
  it('thinking keeps the breathing line (life comes from impulses/sky)', () => {
    expect(deriveLineMode('thinking', inputs({ isStreaming: true, isThinking: true }))).toBe(
      'breathe'
    )
  })
})

describe('deriveSkyMode', () => {
  it('wakes the constellation whenever reasoning is live, even inside working', () => {
    expect(deriveSkyMode('thinking', inputs({ isThinking: true }))).toBe('thinking')
    expect(deriveSkyMode('working', inputs({ isThinking: true }))).toBe('thinking')
  })

  it('working without reasoning drives the spores', () => {
    expect(deriveSkyMode('working', inputs())).toBe('working')
  })

  it('everything else is idle', () => {
    expect(deriveSkyMode('quiet', inputs())).toBe('idle')
    expect(deriveSkyMode('responding', inputs())).toBe('idle')
    expect(deriveSkyMode('listening', inputs())).toBe('idle')
  })
})

describe('thinkingSignalNext', () => {
  it('turns on when thinking grows, off when content grows', () => {
    let s = thinkingSignalNext(THINKING_SIGNAL_IDLE, {
      thinkingLen: 10,
      contentLen: 0,
      isStreaming: true
    })
    expect(s.active).toBe(true)
    s = thinkingSignalNext(s, { thinkingLen: 10, contentLen: 5, isStreaming: true })
    expect(s.active).toBe(false)
  })

  it('re-activates when the model reasons again mid-turn (tool loop)', () => {
    let s = thinkingSignalNext(THINKING_SIGNAL_IDLE, {
      thinkingLen: 10,
      contentLen: 0,
      isStreaming: true
    })
    s = thinkingSignalNext(s, { thinkingLen: 10, contentLen: 20, isStreaming: true })
    expect(s.active).toBe(false)
    s = thinkingSignalNext(s, { thinkingLen: 25, contentLen: 20, isStreaming: true })
    expect(s.active).toBe(true)
  })

  it('content growth wins when both grow in the same tick', () => {
    const s = thinkingSignalNext(
      { thinkingLen: 5, contentLen: 5, active: true },
      { thinkingLen: 9, contentLen: 9, isStreaming: true }
    )
    expect(s.active).toBe(false)
  })

  it('stream end and buffer resets deactivate cleanly', () => {
    let s = thinkingSignalNext(THINKING_SIGNAL_IDLE, {
      thinkingLen: 10,
      contentLen: 0,
      isStreaming: true
    })
    s = thinkingSignalNext(s, { thinkingLen: 10, contentLen: 0, isStreaming: false })
    expect(s.active).toBe(false)
    // nuovo turno: gli accumulatori ripartono da zero, poi il thinking cresce
    s = thinkingSignalNext(s, { thinkingLen: 3, contentLen: 0, isStreaming: true })
    expect(s.active).toBe(true)
  })
})

describe('lastThinkingLine', () => {
  it('returns the last meaningful line, skipping blanks and iteration separators', () => {
    expect(lastThinkingLine('prima\n\nseconda\n---\n\n')).toBe('seconda')
    expect(lastThinkingLine('')).toBe('')
  })

  it('truncates long lines with an ellipsis', () => {
    const long = 'x'.repeat(200)
    const out = lastThinkingLine(long)
    expect(out.length).toBe(120)
    expect(out.endsWith('…')).toBe(true)
  })
})

describe('manuscriptView', () => {
  const plan = (n: number, completed: number): ReturnType<typeof step>[] =>
    Array.from({ length: n }, (_, i) =>
      step(`passo ${i + 1}`, i < completed ? 'completed' : i === completed ? 'in_progress' : 'pending')
    )

  it('short plans pass through untouched', () => {
    const items = manuscriptView(plan(5, 2))
    expect(items).toHaveLength(5)
    expect(items.every((it) => it.kind === 'step')).toBe(true)
  })

  it('long plans collapse the oldest completed steps, keeping the last 2', () => {
    const items = manuscriptView(plan(10, 6))
    expect(items[0]).toEqual({ kind: 'collapsed', count: 4 })
    const stepRows = items.filter((it) => it.kind === 'step')
    expect(stepRows.filter((it) => it.kind === 'step' && it.step.status === 'completed')).toHaveLength(2)
  })

  it('still-too-long plans get a "+N" tail within the cap', () => {
    const items = manuscriptView(plan(15, 2))
    const last = items[items.length - 1]
    expect(last.kind).toBe('more')
    expect(items.length).toBeLessThanOrEqual(8) // maxVisible 7 + eventuale riga collassata
  })

  it('an all-completed plan collapses to the counter + last two', () => {
    const items = manuscriptView(plan(9, 9))
    expect(items[0]).toEqual({ kind: 'collapsed', count: 7 })
    expect(items).toHaveLength(3)
  })

  it('empty plan → empty manuscript', () => {
    expect(manuscriptView([])).toEqual([])
  })
})
```

- [ ] **Step 1.2: Verificare che fallisca**

```powershell
npx vitest run src/renderer/src/composables/horizon/horizonScene.spec.ts
```
Expected: FAIL (export mancanti / tipi).

- [ ] **Step 1.3: Implementazione in `horizonScene.ts`**

Modifiche puntuali (il resto del file resta invariato):

```ts
/** The five scene states (spec Horizon Vivo §3.1). */
export type HorizonState = 'quiet' | 'listening' | 'thinking' | 'responding' | 'working'

/** The living backdrop's mode (HorizonSky). */
export type HorizonSkyMode = 'idle' | 'thinking' | 'working'
```

In `HorizonSceneInputs` aggiungere il campo:

```ts
  /** Live reasoning signal (useThinkingSignal): thinking tokens are flowing. */
  isThinking: boolean
```

`deriveSceneState` diventa:

```ts
/** Derive the single active scene state (priority ordered). */
export function deriveSceneState(i: HorizonSceneInputs): HorizonState {
  if (i.isStreaming && (planActive(i.planSteps) || i.activeToolCount > 0)) return 'working'
  if (i.isStreaming && i.isThinking) return 'thinking'
  if (i.isStreaming || i.isSpeaking) return 'responding'
  if (i.isListening || i.isSttProcessing || i.composerActive) return 'listening'
  return 'quiet'
}
```

In `deriveLineMode` aggiungere il caso (prima di `default`):

```ts
    case 'thinking':
      return 'breathe'
```

Aggiungere in coda al file:

```ts
/** Sky mode: the constellation wakes on live reasoning, spores on work. */
export function deriveSkyMode(state: HorizonState, i: HorizonSceneInputs): HorizonSkyMode {
  if (i.isThinking && (state === 'thinking' || state === 'working')) return 'thinking'
  if (state === 'working') return 'working'
  return 'idle'
}

/* ── thinking signal (edge-triggered, non level-based: works in tool loops) ── */

export interface ThinkingSignalSnapshot {
  thinkingLen: number
  contentLen: number
  isStreaming: boolean
}

export interface ThinkingSignalState {
  thinkingLen: number
  contentLen: number
  active: boolean
}

export const THINKING_SIGNAL_IDLE: ThinkingSignalState = {
  thinkingLen: 0,
  contentLen: 0,
  active: false
}

/**
 * Pure reducer for the "is Alice reasoning right now" signal: thinking growth
 * activates it, visible-content growth deactivates it (content wins when both
 * grow in one tick), stream end and buffer resets deactivate/re-baseline.
 */
export function thinkingSignalNext(
  prev: ThinkingSignalState,
  snap: ThinkingSignalSnapshot
): ThinkingSignalState {
  if (!snap.isStreaming) {
    return { thinkingLen: snap.thinkingLen, contentLen: snap.contentLen, active: false }
  }
  let active = prev.active
  if (snap.thinkingLen < prev.thinkingLen || snap.contentLen < prev.contentLen) {
    // Buffers were reset (new turn): re-baseline on what is present now.
    active = snap.thinkingLen > 0 && snap.contentLen === 0
  } else if (snap.contentLen > prev.contentLen) {
    active = false
  } else if (snap.thinkingLen > prev.thinkingLen) {
    active = true
  }
  return { thinkingLen: snap.thinkingLen, contentLen: snap.contentLen, active }
}

/** Last meaningful line of the thinking stream (marginalia text). */
export function lastThinkingLine(content: string, maxChars = 120): string {
  const lines = content.split('\n')
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].trim()
    if (line === '' || line === '---') continue
    return line.length > maxChars ? `${line.slice(0, maxChars - 1)}…` : line
  }
  return ''
}

/* ── manuscript plan (Horizon Vivo §5) ── */

export type HorizonManuscriptItem =
  | { kind: 'step'; index: number; step: TaskStep }
  | { kind: 'collapsed'; count: number }
  | { kind: 'more'; count: number }

/**
 * Rows for the manuscript plan. Long plans collapse their oldest completed
 * steps into a counter row (always keeping the last 2 completed) and, if
 * still over budget, tail-collapse the far future into a "+N" row.
 */
export function manuscriptView(steps: TaskStep[], maxVisible = 7): HorizonManuscriptItem[] {
  const all: HorizonManuscriptItem[] = steps.map((step, index) => ({ kind: 'step', index, step }))
  if (all.length <= maxVisible) return all

  const completedIdx = steps
    .map((s, index) => ({ s, index }))
    .filter(({ s }) => s.status === 'completed')
    .map(({ index }) => index)
  const keepCompleted = new Set(completedIdx.slice(-2))
  const collapsedCount = completedIdx.length - keepCompleted.size

  let items = all.filter(
    (it) => it.kind !== 'step' || it.step.status !== 'completed' || keepCompleted.has(it.index)
  )
  if (collapsedCount > 0) items = [{ kind: 'collapsed', count: collapsedCount }, ...items]

  const budget = maxVisible + (collapsedCount > 0 ? 1 : 0)
  if (items.length > budget) {
    const hiddenSteps = items.slice(budget - 1).filter((it) => it.kind === 'step').length
    items = [...items.slice(0, budget - 1), { kind: 'more', count: hiddenSteps }]
  }
  return items
}
```

- [ ] **Step 1.4: Consumatori minimi per la compilazione**

`HorizonScene.vue`, oggetto `QUOTAS` (riga ~22): aggiungere la chiave

```ts
  thinking: 0.6,
```

`HorizonView.vue`, computed `sceneInputs` (riga ~95): aggiungere il campo letterale (la Task 2 lo sostituisce col segnale vero):

```ts
  isThinking: false,
```

- [ ] **Step 1.5: Verificare che passi + typecheck**

```powershell
npx vitest run src/renderer/src/composables/horizon/horizonScene.spec.ts
npm run typecheck
```
Expected: PASS, typecheck pulito.

- [ ] **Step 1.6: Commit**

```powershell
git add src/renderer/src/composables/horizon/horizonScene.ts src/renderer/src/composables/horizon/horizonScene.spec.ts src/renderer/src/components/horizon/HorizonScene.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): thinking state, sky mode, manuscript view in the pure scene brain"
```

---

### Task 2: `useThinkingSignal` + wiring dello stato thinking nella vista

**Files:**
- Create: `frontend/src/renderer/src/composables/horizon/useThinkingSignal.ts`
- Modify: `frontend/src/renderer/src/views/HorizonView.vue`

- [ ] **Step 2.1: Il composable**

```ts
// composables/horizon/useThinkingSignal.ts
/**
 * useThinkingSignal — bridges the chat store's raw streaming buffers to the
 * scene's "Alice is reasoning right now" boolean. All the edge logic lives in
 * the pure, unit-tested thinkingSignalNext reducer; this wrapper only feeds
 * it store snapshots.
 */
import { ref, watch } from 'vue'
import type { Ref } from 'vue'
import { THINKING_SIGNAL_IDLE, thinkingSignalNext } from './horizonScene'
import type { ThinkingSignalState } from './horizonScene'
import { useChatStore } from '../../stores/chat'

export function useThinkingSignal(): Ref<boolean> {
  const chatStore = useChatStore()
  const active = ref(false)
  let state: ThinkingSignalState = THINKING_SIGNAL_IDLE

  watch(
    () =>
      [
        chatStore.currentThinkingContent.length,
        chatStore.currentStreamContent.length,
        chatStore.isStreamingCurrentConversation
      ] as const,
    ([thinkingLen, contentLen, isStreaming]) => {
      state = thinkingSignalNext(state, { thinkingLen, contentLen, isStreaming })
      active.value = state.active
    },
    { immediate: true }
  )

  return active
}
```

- [ ] **Step 2.2: Wiring in `HorizonView.vue`**

Import (accanto agli altri composable horizon):

```ts
import { useThinkingSignal } from '../composables/horizon/useThinkingSignal'
```

Dopo `const { state: modalState } = useModal()`:

```ts
const isThinking = useThinkingSignal()
```

In `sceneInputs` sostituire `isThinking: false,` con:

```ts
  isThinking: isThinking.value,
```

In `lineLabel`, prima del ramo `responding`:

```ts
  if (sceneState.value === 'thinking') return 'RAGIONO'
```

- [ ] **Step 2.3: Gate + commit**

```powershell
npx vitest run
npm run typecheck
git add src/renderer/src/composables/horizon/useThinkingSignal.ts src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): live thinking signal wired into the scene (RAGIONO)"
```

---

### Task 3: Token materia + sfondo stratificato della scena

**Files:**
- Modify: `frontend/src/renderer/src/assets/styles/horizon.css`
- Modify: `frontend/src/renderer/src/components/horizon/HorizonScene.vue`

- [ ] **Step 3.1: Token in `horizon.css`**

Nel blocco `:root`, dopo `--hz-line-rgb`:

```css
  /* materia — alias/derivati del tema (Horizon Vivo §8) */
  --hz-warmth: 0.05; /* alpha del gradiente caldo che sale dall'orizzonte */
  --hz-grain-ink: rgba(255, 255, 255, 0.012); /* colore della grana carta */
  --hz-grain-opacity: 0.5;
  --hz-vignette: 0.3; /* alpha della vignettatura ai bordi */
  --hz-sky-alpha: 0.1; /* alpha base della costellazione in quiete */
  --hz-highlight: rgba(255, 255, 255, 0.05); /* highlight interno superfici */
  --hz-shadow-sheet:
    0 1px 0 rgba(0, 0, 0, 0.35),
    0 18px 40px rgba(0, 0, 0, 0.45); /* ombra doppia (contatto + diffusa) */
```

Nel blocco `[data-theme='light']`:

```css
  --hz-warmth: 0.07;
  --hz-grain-ink: rgba(60, 50, 40, 0.02);
  --hz-grain-opacity: 0.8;
  --hz-vignette: 0.07;
  --hz-sky-alpha: 0.16;
  --hz-highlight: rgba(255, 255, 255, 0.55);
  --hz-shadow-sheet:
    0 1px 0 rgba(0, 0, 0, 0.05),
    0 14px 30px rgba(0, 0, 0, 0.1);
```

Nota: la spec §8 citava anche `--hz-gold-rgb`, ma sarebbe un duplicato esatto di `--hz-line-rgb` (già il triplet dell'accent): si riusa `--hz-line-rgb` ovunque. Annotarlo nel commit.

- [ ] **Step 3.2: Sfondo stratificato in `HorizonScene.vue`**

Sostituire la regola `.hz-scene` e aggiungere i due pseudo-elementi:

```css
.hz-scene {
  position: relative;
  width: 100%;
  height: 100%;
  background:
    radial-gradient(120% 85% at 50% 115%, rgba(var(--hz-line-rgb), var(--hz-warmth)), transparent 60%),
    var(--surface-0);
  overflow: hidden;
  transition: opacity var(--hz-fade) ease;
}

/* Grana carta: pattern CSS puro, nessun asset esterno. */
.hz-scene::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  opacity: var(--hz-grain-opacity);
  background-image: repeating-conic-gradient(var(--hz-grain-ink) 0 25%, transparent 0 50%);
  background-size: 3px 3px;
}

/* Vignettatura: chiude la scena ai bordi. */
.hz-scene::after {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: radial-gradient(
    120% 100% at 50% 45%,
    transparent 60%,
    rgba(0, 0, 0, var(--hz-vignette)) 100%
  );
}
```

- [ ] **Step 3.3: Verifica visiva veloce + gate + commit**

Con l'app dev aperta (`/assistant`): fondo con gradiente caldo e grana percettibile in entrambi i temi, zone e testo intatti sopra.

```powershell
npm run typecheck
npm run lint
git add src/renderer/src/assets/styles/horizon.css src/renderer/src/components/horizon/HorizonScene.vue
git commit -m "feat(horizon): material backdrop - warm gradient, paper grain, vignette tokens"
```

---

### Task 4: `HorizonLine` esteso — noduli, impulsi, glow che respira

**Files:**
- Modify: `frontend/src/renderer/src/components/horizon/HorizonLine.vue`
- Modify: `frontend/src/renderer/src/views/HorizonView.vue` (prop `:impulses`)

- [ ] **Step 4.1: Props e costanti**

Nel blocco props di `HorizonLine.vue` aggiungere (con default):

```ts
    /** Travelling light packets along the filament (thinking/working). */
    impulses?: boolean
```

e nel `withDefaults`: `impulses: false,`. Aggiornare il doc-comment in testa: aggiungere la riga `- impulses  : overlay, light packets travelling the filament (thinking/working)`.

Dopo la dichiarazione `const canvasRef …`, tra le costanti module-level:

```ts
/** Fixed synaptic nodes on the filament (fractions of the span). */
const NODE_FRACTIONS = [0.28, 0.47, 0.63, 0.8]
```

- [ ] **Step 4.2: Glow che respira (linea)**

In `draw()`, la riga `ctx.shadowBlur = 12` diventa:

```ts
  ctx.shadowBlur = reducedMotion ? 12 : 12 + Math.sin((t * Math.PI * 2) / 5) * 4
```

- [ ] **Step 4.3: Noduli + impulsi**

In `draw()`, subito DOPO il blocco `/* ── the line ── */ … ctx.restore()` e PRIMA del blocco `pulse`:

```ts
  /* ── synaptic nodes: fixed points breathing on the filament ── */
  if (props.notchCount === 0) {
    ctx.save()
    ctx.fillStyle = `rgba(${lineRgb}, 0.95)`
    ctx.shadowColor = `rgba(${lineRgb}, 0.8)`
    ctx.shadowBlur = 6
    for (let i = 0; i < NODE_FRACTIONS.length; i++) {
      const x = margin + NODE_FRACTIONS[i] * span
      const breath = reducedMotion ? 0.6 : 0.35 + 0.65 * (0.5 + Math.sin(t * 1.1 + i * 1.7) / 2)
      ctx.globalAlpha = alpha * 0.85 * breath
      ctx.beginPath()
      ctx.arc(x, cy, 1.4, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.restore()
  }

  /* ── impulses: light packets travelling the filament ── */
  if (props.impulses && !reducedMotion) {
    ctx.save()
    // Under the plan timeline the impulses recede so the ticks stay readable.
    const dim = props.notchCount > 0 ? 0.5 : 1
    for (let i = 0; i < 2; i++) {
      const f = (t * 0.16 + i * 0.5) % 1
      const x = margin + f * span
      const fade = Math.sin(f * Math.PI) // born and dies at the line's ends
      const g = ctx.createRadialGradient(x, cy, 0, x, cy, 16)
      g.addColorStop(0, `rgba(${lineRgb}, ${0.9 * fade * dim})`)
      g.addColorStop(1, `rgba(${lineRgb}, 0)`)
      ctx.globalAlpha = alpha
      ctx.fillStyle = g
      ctx.fillRect(x - 16, cy - 3, 32, 6)
    }
    ctx.restore()
  }
```

Nel `watch` finale (lista reduced-motion) aggiungere `props.impulses,` alla lista.

- [ ] **Step 4.4: La vista attiva gli impulsi**

`HorizonView.vue`, template `<HorizonLine …>`: aggiungere la prop

```
          :impulses="sceneState === 'thinking' || sceneState === 'working'"
```

- [ ] **Step 4.5: Gate + verifica visiva + commit**

Verifica nell'app: in quiete noduli che respirano sulla linea; durante un turno con reasoning gli impulsi viaggiano; nel timeline i noduli spariscono e gli impulsi si attenuano.

```powershell
npm run typecheck
npm run lint
git add src/renderer/src/components/horizon/HorizonLine.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): living filament - synaptic nodes, travelling impulses, breathing glow"
```

---

### Task 5: `HorizonSky` — costellazione sinaptica + spore

**Files:**
- Create: `frontend/src/renderer/src/components/horizon/HorizonSky.vue`
- Modify: `frontend/src/renderer/src/components/horizon/HorizonScene.vue` (host)
- Modify: `frontend/src/renderer/src/views/HorizonView.vue` (prop `:sky`)

- [ ] **Step 5.1: Il componente**

```vue
<!-- components/horizon/HorizonSky.vue -->
<script setup lang="ts">
/**
 * HorizonSky — the living backdrop: a synaptic constellation in the sky band
 * (waking in sequence while Alice reasons) and light spores rising from the
 * horizon while she works. Declarative (props only). One rAF loop that
 * suspends once idle has fully faded and on document.hidden; a single static
 * draw under prefers-reduced-motion. Colors come from --hz-line-rgb and
 * --hz-sky-alpha (re-read on data-theme changes) — same discipline as
 * HorizonLine.
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { HorizonSkyMode } from '../../composables/horizon/horizonScene'

const props = withDefaults(
  defineProps<{
    mode?: HorizonSkyMode
    /** Line vertical position as a fraction of the scene height (spore origin). */
    lineQuota?: number
  }>(),
  { mode: 'idle', lineQuota: 0.58 }
)

interface SkyNode {
  x: number // fraction of width
  y: number // fraction of height (sky band)
  r: number
  phase: number
}
interface SkyEdge {
  a: number
  b: number
}
interface Spore {
  x: number
  speed: number
  phase: number
}

const NODE_COUNT = 20
const EDGE_NEIGHBORS = 2
const SPORE_COUNT = 6
/** Cross-fade speed (per second) between idle/awake/working intensities. */
const EASE_RATE = 0.8

const canvasRef = ref<HTMLCanvasElement | null>(null)

let ctx: CanvasRenderingContext2D | null = null
let raf = 0
let running = false
let width = 0
let height = 0
let lineRgb = '232, 220, 200'
let baseAlpha = 0.1
/** 0 = asleep, 1 = fully awake (reasoning). Eases toward its target. */
let wake = 0
/** 0 = no spores, 1 = full working activity. Eases toward its target. */
let sporeLevel = 0
let lastNow = 0
let nodes: SkyNode[] = []
let edges: SkyEdge[] = []
let sporePool: Spore[] = []
let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

/** Deterministic PRNG: the constellation is stable across frames and mounts. */
function mulberry32(seed: number): () => number {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let z = Math.imul(a ^ (a >>> 15), 1 | a)
    z = (z + Math.imul(z ^ (z >>> 7), 61 | z)) ^ z
    return ((z ^ (z >>> 14)) >>> 0) / 4294967296
  }
}

function buildConstellation(): void {
  const rand = mulberry32(197)
  nodes = Array.from({ length: NODE_COUNT }, () => ({
    x: 0.06 + rand() * 0.88,
    y: 0.08 + rand() * 0.34, // sky band: above the central content
    r: 0.8 + rand() * 1.4,
    phase: rand() * Math.PI * 2
  }))
  edges = []
  nodes.forEach((n, i) => {
    const nearest = nodes
      .map((m, j) => ({ j, d: (n.x - m.x) ** 2 + (n.y - m.y) ** 2 }))
      .filter((e) => e.j !== i)
      .sort((a, b) => a.d - b.d)
      .slice(0, EDGE_NEIGHBORS)
    for (const e of nearest) {
      const dup = edges.some((ed) => (ed.a === e.j && ed.b === i) || (ed.a === i && ed.b === e.j))
      if (!dup) edges.push({ a: i, b: e.j })
    }
  })
  const srand = mulberry32(41)
  sporePool = Array.from({ length: SPORE_COUNT }, () => ({
    x: 0.15 + srand() * 0.7,
    speed: 0.05 + srand() * 0.05,
    phase: srand()
  }))
}

function readTheme(): void {
  const el = canvasRef.value
  if (!el) return
  const style = getComputedStyle(el)
  const rgb = style.getPropertyValue('--hz-line-rgb').trim()
  if (rgb) lineRgb = rgb
  const alpha = parseFloat(style.getPropertyValue('--hz-sky-alpha'))
  if (Number.isFinite(alpha)) baseAlpha = alpha
}

function resize(): void {
  const el = canvasRef.value
  if (!el || !el.parentElement) return
  const dpr = window.devicePixelRatio || 1
  width = el.parentElement.clientWidth
  height = el.parentElement.clientHeight
  el.width = Math.round(width * dpr)
  el.height = Math.round(height * dpr)
  ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
  if (reducedMotion) draw(performance.now())
}

function draw(now: number): void {
  if (!ctx || width === 0) return
  const t = now / 1000
  const dt = lastNow === 0 ? 0 : Math.min(0.1, (now - lastNow) / 1000)
  lastNow = now

  const wakeTarget = props.mode === 'thinking' ? 1 : 0
  const sporeTarget = props.mode === 'working' ? 1 : 0
  if (!reducedMotion) {
    wake += (wakeTarget - wake) * Math.min(1, EASE_RATE * dt * 3)
    sporeLevel += (sporeTarget - sporeLevel) * Math.min(1, EASE_RATE * dt * 3)
  } else {
    wake = wakeTarget
    sporeLevel = sporeTarget
  }

  ctx.clearRect(0, 0, width, height)

  /* ── constellation ── */
  ctx.save()
  ctx.lineWidth = 0.5
  for (const e of edges) {
    const a = nodes[e.a]
    const b = nodes[e.b]
    const surge = reducedMotion
      ? 0
      : wake * (0.5 + Math.sin(t * 2 - (e.a + e.b) * 0.35) / 2) * 0.35
    ctx.strokeStyle = `rgba(${lineRgb}, ${baseAlpha * 0.6 + surge})`
    ctx.beginPath()
    ctx.moveTo(a.x * width, a.y * height)
    ctx.lineTo(b.x * width, b.y * height)
    ctx.stroke()
  }
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i]
    const twinkle = reducedMotion ? 0.5 : 0.5 + Math.sin(t * 0.9 + n.phase) / 2
    const surge = reducedMotion ? 0 : wake * (0.5 + Math.sin(t * 2.2 - i * 0.5) / 2)
    const a = baseAlpha * (0.6 + twinkle * 0.4) + surge * 0.6
    ctx.fillStyle = `rgba(${lineRgb}, ${Math.min(1, a)})`
    ctx.shadowColor = `rgba(${lineRgb}, 0.6)`
    ctx.shadowBlur = 4 + surge * 8
    ctx.beginPath()
    ctx.arc(n.x * width, n.y * height, n.r + surge * 0.8, 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()

  /* ── spores rising from the horizon ── */
  if (sporeLevel > 0.01 && !reducedMotion) {
    ctx.save()
    const originY = props.lineQuota * height
    for (const s of sporePool) {
      const progress = (t * s.speed + s.phase) % 1
      const y = originY - progress * height * 0.28
      const a = sporeLevel * Math.sin(progress * Math.PI) * 0.7
      ctx.fillStyle = `rgba(${lineRgb}, ${a})`
      ctx.shadowColor = `rgba(${lineRgb}, 0.5)`
      ctx.shadowBlur = 3
      ctx.beginPath()
      ctx.arc(s.x * width, y, 1.1, 0, Math.PI * 2)
      ctx.fill()
    }
    ctx.restore()
  }

  // Fully settled and idle → suspend the loop (zero idle work).
  if (
    props.mode === 'idle' &&
    wake < 0.01 &&
    sporeLevel < 0.01 &&
    !reducedMotion &&
    running
  ) {
    // One last faint frame is already painted; stop until inputs change.
    stop()
  }
}

function loop(now: number): void {
  if (!running) return
  draw(now)
  // draw() may have suspended the loop (idle settled): never re-schedule then,
  // or a later start() would end up with two concurrent rAF chains.
  if (!running) return
  raf = requestAnimationFrame(loop)
}

function start(): void {
  if (running || reducedMotion || !ctx) return
  running = true
  lastNow = 0
  raf = requestAnimationFrame(loop)
}

function stop(): void {
  running = false
  cancelAnimationFrame(raf)
}

function onVisibility(): void {
  if (document.hidden) stop()
  else start()
}

onMounted(() => {
  const el = canvasRef.value
  if (!el) return
  ctx = el.getContext('2d')
  buildConstellation()
  readTheme()
  resize()
  if (typeof ResizeObserver !== 'undefined' && el.parentElement) {
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(el.parentElement)
  }
  if (typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(() => {
      readTheme()
      if (reducedMotion) draw(performance.now())
    })
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    })
  }
  document.addEventListener('visibilitychange', onVisibility)
  if (reducedMotion) draw(performance.now())
  else start()
})

onBeforeUnmount(() => {
  stop()
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  document.removeEventListener('visibilitychange', onVisibility)
})

// Mode changes must resume a suspended loop (or redraw statically).
watch(
  () => [props.mode, props.lineQuota],
  () => {
    if (reducedMotion) draw(performance.now())
    else start()
  }
)
</script>

<template>
  <div class="hz-sky" aria-hidden="true">
    <canvas ref="canvasRef" class="hz-sky__canvas" />
  </div>
</template>

<style scoped>
.hz-sky {
  position: absolute;
  inset: 0;
  z-index: 0; /* above the scene's grain, below the content zones (1-3) */
  pointer-events: none;
}

.hz-sky__canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
</style>
```

- [ ] **Step 5.2: Host in `HorizonScene.vue`**

Script: aggiungere import e prop.

```ts
import HorizonSky from './HorizonSky.vue'
import type { HorizonState, HorizonSkyMode } from '../../composables/horizon/horizonScene'
```

Nel `defineProps` aggiungere:

```ts
    /** Living backdrop mode (HorizonSky). */
    sky?: HorizonSkyMode
```

e nel `withDefaults`: `sky: 'idle',`.

Template: come PRIMO figlio di `.hz-scene` (prima del masthead):

```vue
    <HorizonSky :mode="sky" :line-quota="quota" />
```

- [ ] **Step 5.3: La vista passa lo sky mode**

`HorizonView.vue`: estendere l'import da `horizonScene` con `deriveSkyMode`; dopo `lineMode`:

```ts
const skyMode = computed(() => deriveSkyMode(sceneState.value, sceneInputs.value))
```

Template: `<HorizonScene :state="sceneState" :sky="skyMode" :magazine="magazine" :dimmed="sceneDimmed">`.

- [ ] **Step 5.4: Gate + verifica visiva + commit**

Verifica: quiete = costellazione appena percettibile ferma (loop sospeso: nessun lavoro in idle — controllare con devtools performance se in dubbio); turno con reasoning = nodi che si accendono in sequenza; turno con tool = spore che salgono; tema chiaro = inchiostro tenue.

```powershell
npm run typecheck
npm run lint
git add src/renderer/src/components/horizon/HorizonSky.vue src/renderer/src/components/horizon/HorizonScene.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): synaptic constellation sky with rising work spores"
```

---

### Task 6: Marginalia del pensiero — `HorizonThinking`

**Files:**
- Create: `frontend/src/renderer/src/components/horizon/HorizonThinking.vue`
- Modify: `frontend/src/renderer/src/views/HorizonView.vue`

- [ ] **Step 6.1: Il componente**

```vue
<!-- components/horizon/HorizonThinking.vue -->
<script setup lang="ts">
/**
 * HorizonThinking — the reasoning marginalia above the line: the last
 * meaningful line of the thinking stream, throttled (~600ms) and cross-faded
 * so tokens never flicker. Real text (aria-live); the dendrites growing from
 * the line toward the text are decorative SVG only.
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import { lastThinkingLine } from '../../composables/horizon/horizonScene'

const props = defineProps<{
  /** Raw accumulated thinking stream (chat store). */
  content: string
}>()

const THROTTLE_MS = 600

const shown = ref(lastThinkingLine(props.content))
let timer: ReturnType<typeof setTimeout> | null = null
let lastFlip = 0

watch(
  () => props.content,
  (content) => {
    const line = lastThinkingLine(content)
    if (line === '' || line === shown.value) return
    const wait = Math.max(0, THROTTLE_MS - (Date.now() - lastFlip))
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      shown.value = lastThinkingLine(props.content)
      lastFlip = Date.now()
    }, wait)
  }
)

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="hz-thinking">
    <Transition name="hz-think" mode="out-in">
      <p :key="shown" class="hz-thinking__line" aria-live="polite">
        sta ragionando — <em>«{{ shown }}»</em>
      </p>
    </Transition>
    <svg class="hz-thinking__dendrites" viewBox="0 0 120 24" aria-hidden="true">
      <path d="M60,24 C58,15 52,12 49,4" />
      <path d="M60,24 C63,16 69,13 73,7" />
      <path d="M60,24 C60,18 57,16 55,13" />
    </svg>
  </div>
</template>

<style scoped>
.hz-thinking {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  margin-bottom: clamp(8px, 1.6vh, 18px);
  max-width: min(70ch, 84%);
}

.hz-thinking__line {
  margin: 0;
  font-family: var(--hz-serif);
  font-style: italic;
  font-weight: 300;
  font-size: clamp(13px, 1.6vmin, 16px);
  color: var(--hz-ink-dim);
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

.hz-thinking__line em {
  color: var(--hz-ink-faint);
}

/* Dendrites growing from the line toward the thought. */
.hz-thinking__dendrites {
  width: 120px;
  height: 24px;
}

.hz-thinking__dendrites path {
  fill: none;
  stroke: rgba(var(--hz-line-rgb), 0.4);
  stroke-width: 0.7;
  stroke-dasharray: 40;
  stroke-dashoffset: 40;
  animation: hz-dendrite 2.4s var(--ease-out) forwards;
}

.hz-thinking__dendrites path:nth-child(2) {
  animation-delay: 0.5s;
}

.hz-thinking__dendrites path:nth-child(3) {
  animation-delay: 1s;
}

@keyframes hz-dendrite {
  to {
    stroke-dashoffset: 0;
  }
}

.hz-think-enter-active,
.hz-think-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-think-enter-from,
.hz-think-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .hz-thinking__dendrites path {
    animation: none;
    stroke-dashoffset: 0;
  }

  .hz-think-enter-active,
  .hz-think-leave-active {
    transition: none;
  }
}
</style>
```

- [ ] **Step 6.2: Mount nella vista**

`HorizonView.vue` — import:

```ts
import HorizonThinking from '../components/horizon/HorizonThinking.vue'
```

Template, nello slot `#upper`, subito PRIMA di `<HorizonResponse …>` (la marginalia sta sopra la linea, sotto composer/cockpit):

```vue
        <Transition name="hz-soft">
          <HorizonThinking
            v-if="
              (sceneState === 'thinking' || (sceneState === 'working' && isThinking)) &&
              chatStore.currentThinkingContent !== ''
            "
            :content="chatStore.currentThinkingContent"
          />
        </Transition>
```

- [ ] **Step 6.3: Gate + verifica + commit**

Verifica: con un modello in extended thinking, durante il ragionamento appare la marginalia col pensiero vivo che si aggiorna morbido; alla prima frase di risposta si dissolve; label linea RAGIONO.

```powershell
npm run typecheck
npm run lint
git add src/renderer/src/components/horizon/HorizonThinking.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): reasoning marginalia above the line (thinking made visible)"
```

---

### Task 7: Piano «Manoscritto» — riscrittura di `HorizonPlan`

**Files:**
- Rewrite: `frontend/src/renderer/src/components/horizon/HorizonPlan.vue`

Le props restano identiche (nessun cambiamento in `HorizonView`). Le label orizzontali sui notch spariscono (erano la parte criptica); le tacche canvas sulla linea restano come eco geometrica.

- [ ] **Step 7.1: Riscrittura completa**

```vue
<script setup lang="ts">
/**
 * HorizonPlan — the manuscript: the whole plan as a readable vertical list
 * under the line, tethered to it by a dendrite. Steps reveal one by one when
 * the plan is born (staggered via --row), the active step carries a breathing
 * gold node, completed ones are struck through in gold ink. Long plans
 * collapse via the pure manuscriptView (oldest completed → counter row,
 * far future → "+N" tail).
 */
import { computed } from 'vue'
import { manuscriptView } from '../../composables/horizon/horizonScene'
import type { TaskStep } from '../../types/tasks'

const props = defineProps<{
  steps: TaskStep[]
  activeIndex: number
  completed: number
  /** Ephemeral tool-call annotation ('' = hidden). */
  annotation: string
}>()

const items = computed(() => manuscriptView(props.steps))
</script>

<template>
  <div class="hz-plan">
    <span class="hz-plan__tether" aria-hidden="true" />
    <TransitionGroup tag="ol" name="hz-plan-step" class="hz-plan__list" appear>
      <li
        v-for="(it, row) in items"
        :key="it.kind === 'step' ? `s-${it.index}` : it.kind"
        class="hz-plan__row"
        :class="{
          'hz-plan__row--active': it.kind === 'step' && it.index === activeIndex,
          'hz-plan__row--done': it.kind === 'step' && it.step.status === 'completed',
          'hz-plan__row--meta': it.kind !== 'step'
        }"
        :style="{ '--row': row }"
      >
        <template v-if="it.kind === 'step'">
          <span class="hz-plan__marker" aria-hidden="true" />
          <span class="hz-plan__text">{{ it.step.step }}</span>
          <span v-if="it.step.status === 'completed'" class="hz-plan__check" aria-hidden="true">
            ✓
          </span>
        </template>
        <template v-else-if="it.kind === 'collapsed'">{{ it.count }} completati ✓</template>
        <template v-else>+{{ it.count }} passi</template>
      </li>
    </TransitionGroup>
    <p class="hz-plan__counter">{{ completed }} DI {{ steps.length }}</p>
    <Transition name="hz-soft">
      <p v-if="annotation" class="hz-plan__annotation">{{ annotation }}</p>
    </Transition>
  </div>
</template>

<style scoped>
.hz-plan {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  text-align: center;
}

/* Dendrite tethering the manuscript to the horizon line above. */
.hz-plan__tether {
  width: 1px;
  height: clamp(12px, 2.4vh, 22px);
  background: linear-gradient(rgba(var(--hz-line-rgb), 0.5), transparent);
}

.hz-plan__list {
  list-style: none;
  margin: clamp(4px, 1vh, 10px) 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: clamp(5px, 1vh, 9px);
  max-width: min(64ch, 86%);
}

.hz-plan__row {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: clamp(13px, 1.7vmin, 17px);
  color: var(--hz-ink-faint);
  transition: color var(--hz-fade) ease, opacity var(--hz-fade) ease;
}

.hz-plan__marker {
  flex: none;
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  border: 1px solid var(--hz-ink-faint);
  background: transparent;
  align-self: center;
  transition: background var(--hz-fade) ease, border-color var(--hz-fade) ease;
}

.hz-plan__text {
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.hz-plan__row--active {
  color: var(--hz-ink);
  font-size: clamp(15px, 2vmin, 19px);
}

.hz-plan__row--active .hz-plan__marker {
  border-color: transparent;
  background: var(--hz-gold);
  animation: hz-plan-node 2.4s ease-in-out infinite;
}

.hz-plan__row--done {
  opacity: 0.55;
}

.hz-plan__row--done .hz-plan__text {
  font-style: italic;
  text-decoration: line-through;
  text-decoration-color: rgba(var(--hz-line-rgb), 0.6);
  text-decoration-thickness: 0.5px;
}

.hz-plan__row--done .hz-plan__marker {
  border-color: transparent;
  background: rgba(var(--hz-line-rgb), 0.55);
}

.hz-plan__check {
  flex: none;
  font-family: var(--hz-serif);
  font-size: 0.8em;
  color: var(--hz-gold);
}

.hz-plan__row--meta {
  font-style: italic;
  font-size: clamp(11px, 1.4vmin, 14px);
  color: var(--hz-ink-faint);
}

@keyframes hz-plan-node {
  0%,
  100% {
    box-shadow: 0 0 4px rgba(var(--hz-line-rgb), 0.4);
  }
  50% {
    box-shadow: 0 0 10px rgba(var(--hz-line-rgb), 0.9);
  }
}

/* Staggered reveal: each row waits for the previous one (80ms). */
.hz-plan-step-enter-active {
  transition: opacity 480ms var(--ease-out), transform 480ms var(--ease-out);
  transition-delay: calc(var(--row) * 80ms);
}

.hz-plan-step-leave-active {
  transition: opacity 200ms var(--ease-out);
  position: absolute; /* leaving rows don't push the list around */
}

.hz-plan-step-move {
  transition: transform 320ms var(--ease-out);
}

.hz-plan-step-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.hz-plan-step-leave-to {
  opacity: 0;
}

.hz-plan__counter {
  margin: var(--space-2) 0 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: var(--hz-ink-faint);
}

.hz-plan__annotation {
  margin: var(--space-1) 0 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.18em;
  color: var(--hz-ink-dim);
}

.hz-soft-enter-active,
.hz-soft-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-soft-enter-from,
.hz-soft-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .hz-plan__row--active .hz-plan__marker {
    animation: none;
  }

  .hz-plan-step-enter-active,
  .hz-plan-step-leave-active,
  .hz-plan-step-move {
    transition: none;
  }
}
</style>
```

- [ ] **Step 7.2: Gate + verifica + commit**

Verifica: chiedere un compito con piano → i passi si scrivono uno a uno sotto la linea, l'attivo respira in oro, i completati si barrano; con >7 passi compare la riga «N completati ✓»; il contatore e l'annotazione tool restano.

```powershell
npx vitest run
npm run typecheck
npm run lint
git add src/renderer/src/components/horizon/HorizonPlan.vue
git commit -m "feat(horizon): manuscript plan - readable staggered list with living progress"
```

---

### Task 8: Il banco — dock materico + colofone sotto, mai coperto

**Files:**
- Modify: `frontend/src/renderer/src/views/HorizonView.vue`
- Modify: `frontend/src/renderer/src/components/desk/DeskDock.vue`
- Modify: `frontend/src/renderer/src/components/horizon/HorizonColophon.vue`

- [ ] **Step 8.1: `HorizonView` — il contenitore ground**

Nel template: RIMUOVERE `<HorizonColophon … />` dallo slot `#lower` e sostituire `<DeskDock />` (dopo `<DeskSurface />`) con:

```vue
    <!-- The ground bench: tray on top, colophon engraved below (never covered). -->
    <div class="horizon-view__ground">
      <DeskDock />
      <HorizonColophon :next-event="calendarStore.nextEvent" :connected="isConnected" />
    </div>
```

In `handleSceneClick`, aggiungere `.horizon-view__ground` alla lista `closest(…)` degli esclusi (click sul banco ≠ toggle voce):

```ts
      'button, a, input, textarea, [contenteditable], .desk-window, .desk-dock, .hz-response, .horizon-view__ground'
```

Stili scoped, accanto a `.horizon-view__corner`:

```css
.horizon-view__ground {
  position: absolute;
  bottom: clamp(12px, 2.6vh, 26px);
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: clamp(5px, 1.1vh, 9px);
  z-index: 5;
}
```

- [ ] **Step 8.2: `DeskDock` — posizionamento al genitore + vestito materico**

Il dock resta surface-agnostic: i token `--hz-*` compaiono SOLO con fallback su token tema. Sostituire la regola `.desk-dock` e `.desk-dock__dot`:

```css
.desk-dock {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-1-5) var(--space-2);
  background: linear-gradient(180deg, var(--surface-2), var(--surface-1));
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-lg);
  box-shadow:
    var(--hz-shadow-sheet, var(--shadow-floating)),
    inset 0 1px 0 var(--hz-highlight, transparent);
}
```

```css
.desk-dock__dot {
  position: absolute;
  bottom: -4px;
  left: 50%;
  transform: translateX(-50%);
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--accent);
  animation: desk-dock-breath 3s ease-in-out infinite;
}

@keyframes desk-dock-breath {
  0%,
  100% {
    box-shadow: 0 0 3px var(--accent-medium);
  }
  50% {
    box-shadow: 0 0 8px var(--accent-vivid);
  }
}

@media (prefers-reduced-motion: reduce) {
  .desk-dock__dot {
    animation: none;
  }
}
```

(`.desk-dock__dot--minimized` invariato — il punto spento non respira: aggiungere `animation: none;` alla sua regola.)

- [ ] **Step 8.3: `HorizonColophon` — sotto il banco, ellissi**

Script — troncare i titoli evento lunghi (~48ch): nel computed `parts`, la riga `list.push(…)` diventa:

```ts
    const title =
      props.nextEvent.title.length > 48
        ? `${props.nextEvent.title.slice(0, 47)}…`
        : props.nextEvent.title
    list.push(`${title} alle ${hm}`)
```

Stile — il posizionamento passa al ground (via gap), il testo non va mai a capo:

```css
.hz-colophon {
  margin: 0;
  max-width: min(72vw, 680px);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--font-sans);
  font-weight: 400;
  font-size: 10px;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
  text-align: center;
  user-select: none;
}
```

- [ ] **Step 8.4: Gate + verifica + commit**

Verifica: colofone sempre leggibile SOTTO il vassoio a ogni altezza finestra (ridimensionare!); punto dorato che respira sul modulo aperto; chip PIANO presente; niente sovrapposizioni con la nav d'angolo.

```powershell
npm run typecheck
npm run lint
git add src/renderer/src/views/HorizonView.vue src/renderer/src/components/desk/DeskDock.vue src/renderer/src/components/horizon/HorizonColophon.vue
git commit -m "feat(horizon): ground bench - material tray with the colophon engraved below"
```

---

### Task 9: Finestre — chrome foglio, filo dorato, posarsi/scivolare

**Files:**
- Modify: `frontend/src/renderer/src/components/desk/DeskWindow.vue`

- [ ] **Step 9.1: Transizioni (template)**

Avvolgere l'intera `<section …>` in una `<Transition>` (dentro il template root). `v-show` resta sulla section: `Transition` anima sia il mount (`appear` = apertura) sia i toggle di `v-show` (minimizza/ripristina):

```vue
<template>
  <Transition name="desk-sheet" appear>
    <section
      v-show="!win.minimized"
      …tutto invariato…
    </section>
  </Transition>
</template>
```

- [ ] **Step 9.2: Chrome materico (style)**

Sostituire `.desk-window` e `.desk-window--focused`; aggiungere il filo dorato e la grana dell'header (i token `--hz-*` sempre con fallback — il componente resta surface-agnostic):

```css
.desk-window {
  position: absolute;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--hz-shadow-sheet, var(--shadow-floating));
  overflow: hidden;
  pointer-events: auto;
}

.desk-window--focused {
  border-color: var(--accent-border);
  box-shadow:
    var(--hz-shadow-sheet, var(--shadow-elevated)),
    0 0 24px -8px var(--accent-vivid);
}

/* The gold thread: the filament "enters" the focused sheet. */
.desk-window--focused::before {
  content: '';
  position: absolute;
  top: 0;
  left: 10%;
  right: 10%;
  height: 1px;
  z-index: 1;
  pointer-events: none;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  box-shadow: 0 0 8px var(--accent-vivid);
}
```

Grana solo sul chrome (mai sul contenuto dei moduli — il terminale resta pulito):

```css
.desk-window__header {
  position: relative;
  /* …resto della regola invariato… */
}

.desk-window__header::after {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: calc(var(--hz-grain-opacity, 0.5) * 0.6);
  background-image: repeating-conic-gradient(
    var(--hz-grain-ink, transparent) 0 25%,
    transparent 0 50%
  );
  background-size: 3px 3px;
}
```

Transizioni del foglio:

```css
/* Opening: the sheet settles down. Minimizing: it slides toward the bench. */
.desk-sheet-enter-active {
  transition: opacity 250ms var(--ease-out), transform 250ms var(--ease-out);
}

.desk-sheet-leave-active {
  transition: opacity 200ms var(--ease-out), transform 200ms var(--ease-out);
}

.desk-sheet-enter-from {
  opacity: 0;
  transform: scale(0.96);
}

.desk-sheet-leave-to {
  opacity: 0;
  transform: scale(0.92) translateY(24px);
}

@media (prefers-reduced-motion: reduce) {
  .desk-sheet-enter-from,
  .desk-sheet-leave-to {
    transform: none;
  }
}
```

- [ ] **Step 9.3: Gate + verifica + commit**

Verifica: aprire finestre dal dock (si posano), minimizzarle (scivolano verso il banco), ripristinarle; la finestra a fuoco ha il filo dorato in alto e l'alone caldo; drag/resize NON animati; xterm nel terminale intatto.

```powershell
npm run typecheck
npm run lint
git add src/renderer/src/components/desk/DeskWindow.vue
git commit -m "feat(desk): sheet chrome - gold thread focus, settle/slide transitions, header grain"
```

---

### Task 10: Rifiniture — composer, cockpit, risposta, masthead, quiete

**Files:**
- Modify: `frontend/src/renderer/src/components/horizon/HorizonComposer.vue`
- Modify: `frontend/src/renderer/src/components/horizon/HorizonCockpit.vue`
- Modify: `frontend/src/renderer/src/components/horizon/HorizonResponse.vue`
- Modify: `frontend/src/renderer/src/components/horizon/HorizonMasthead.vue`
- Modify: `frontend/src/renderer/src/components/horizon/HorizonQuiet.vue`

- [ ] **Step 10.1: Composer — il bagliore si concentra sotto il testo**

In `HorizonComposer.vue`, sostituire la regola `:focus`:

```css
.hz-composer__input:focus {
  box-shadow:
    0 1px 0 rgba(var(--hz-line-rgb), 0.45),
    0 16px 32px -20px rgba(var(--hz-line-rgb), 0.55);
}
```

- [ ] **Step 10.2: Cockpit — filetto dorato**

In `HorizonCockpit.vue`, nella regola `.hz-cockpit__rail` sostituire `border-top: 1px solid var(--border);` con:

```css
  border-top: 1px solid rgba(var(--hz-line-rgb), 0.18);
```

- [ ] **Step 10.3: Risposta — filetti dorati**

In `HorizonResponse.vue`, aggiungere dopo le regole `:deep(code)`/`:deep(pre)`:

```css
.hz-response__body :deep(hr) {
  border: none;
  height: 1px;
  width: 60%;
  margin: 1.2em auto;
  background: linear-gradient(90deg, transparent, rgba(var(--hz-line-rgb), 0.4), transparent);
}

.hz-response__body :deep(blockquote) {
  margin: 0.6em 0;
  padding-left: var(--space-3);
  border-left: 2px solid rgba(var(--hz-line-rgb), 0.35);
  color: var(--hz-ink-dim);
  font-style: italic;
}
```

(Il capolettera in magazine esiste già — nessun cambiamento.)

- [ ] **Step 10.4: Masthead — registro del colofone**

In `HorizonMasthead.vue`, la regola `.hz-masthead__folio` diventa:

```css
.hz-masthead__folio {
  font-family: var(--font-sans);
  font-size: 10px;
  letter-spacing: 0.32em;
  text-indent: 0.32em; /* optically recenters the tracked text */
  text-transform: uppercase;
  color: var(--hz-ink-faint);
}
```

- [ ] **Step 10.5: Quiete — il saluto respira**

In `HorizonQuiet.vue`, aggiungere alla regola `.hz-quiet` e in coda allo style:

```css
.hz-quiet {
  /* …regola esistente invariata… */
  animation: hz-quiet-breath 6s ease-in-out infinite;
}

@keyframes hz-quiet-breath {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.82;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hz-quiet {
    animation: none;
  }
}
```

- [ ] **Step 10.6: Gate + commit**

```powershell
npm run typecheck
npm run lint
git add src/renderer/src/components/horizon/HorizonComposer.vue src/renderer/src/components/horizon/HorizonCockpit.vue src/renderer/src/components/horizon/HorizonResponse.vue src/renderer/src/components/horizon/HorizonMasthead.vue src/renderer/src/components/horizon/HorizonQuiet.vue
git commit -m "style(horizon): gold hairlines, focused composer glow, breathing greeting"
```

---

### Task 11: Verifica finale end-to-end

- [ ] **Step 11.1: Gate completi**

```powershell
npx vitest run
npm run typecheck
npm run lint
```

Expected: tutti verdi.

- [ ] **Step 11.2: Verifica manuale nell'app viva** (skill verify/run; backend + frontend con `.\scripts\start-dev.ps1` dalla root — o riusare i server già attivi)

Checklist (spec §13, entrambe le voci tema dove sensato):
1. Quiete: gradiente caldo + grana + vignetta; saluto che respira; noduli sulla linea; costellazione appena percettibile e FERMA (loop sospeso).
2. Turno con reasoning: marginalia «sta ragionando — …» che si aggiorna morbida, label RAGIONO, impulsi sul filamento, costellazione che si accende in sequenza.
3. Prima frase di risposta: marginalia si dissolve, RISPONDO, risposta paced.
4. Turno con piano: manoscritto con reveal scaglionato, passo attivo che respira in oro, barrature al completamento, spore che salgono; piano >7 passi → riga «N completati ✓».
5. Banco: colofone sempre leggibile sotto il vassoio (ridimensionare la finestra!); punto dorato che respira; chip PIANO.
6. Finestre: si posano all'apertura, scivolano alla minimizzazione, filo dorato sul fuoco; digitare nel terminale in finestra resta pulito (nessuna grana sul contenuto).
7. Composer: bagliore concentrato sotto il campo al focus; Esc/Jarvis-entry invariati.
8. Tema chiaro: tutto leggibile — costellazione a inchiostro, grana più visibile, ombre più leggere.
9. `prefers-reduced-motion` (attivarlo nelle impostazioni di Windows o via devtools rendering): nessuna animazione continua, informazioni intatte.
10. Workspace: INVARIATO (nessuna regressione da DeskDock/DeskWindow — usati solo su /assistant, ma verificare i moduli nel workspace).
11. Riavvio app: layout finestre ripristinato, scena integra.

- [ ] **Step 11.3: Chiusura**

Commit di eventuali fix dalla verifica, poi usare la skill superpowers:finishing-a-development-branch per merge/PR di `rework/horizon-atelier` (che a questo punto contiene atelier + Horizon Vivo).

---

## Self-review del piano (eseguita)

- **Copertura spec:** §3.1 brain → T1/T2; §3.2 sky → T5; §3.3 linea → T4; §3.4 marginalia → T6; §4 stati → T1/T2/T4/T5/T6; §5 manoscritto → T1 (pure) + T7 (vista); §6 banco → T8; §7 superfici → T9/T10; §8 token → T3 (con nota su `--hz-gold-rgb` riusato come `--hz-line-rgb`); §9 a11y/motion/perf → in ogni task (reduced-motion) + T5 (sospensione loop); §13 testing → T1 (unit) + gate ovunque + T11 (manuale).
- **Tipi coerenti:** `HorizonState` con `'thinking'` (T1) consumato da QUOTAS (T1) e label (T2); `HorizonSkyMode`/`deriveSkyMode` (T1) → props HorizonSky/HorizonScene (T5); `manuscriptView`/`HorizonManuscriptItem` (T1) → HorizonPlan (T7); `thinkingSignalNext`/`THINKING_SIGNAL_IDLE`/`ThinkingSignalState` (T1) → useThinkingSignal (T2); `lastThinkingLine` (T1) → HorizonThinking (T6); prop `impulses` (T4) passata dalla vista (T4).
- **Nessun placeholder:** ogni step con codice mostra il codice completo; le uniche istruzioni "modifica puntuale" citano riga e testo esatto da sostituire.
- **Fix emersi dalle code review in esecuzione (il codice committato prevale sui blocchi qui sopra):** HorizonSky ridisegna esplicitamente su resize/tema quando il loop è sospeso e non si arma con documento nascosto (`aef9b5e`); la marginalia non renderizza mai vuota e l'aria-live sta sul wrapper stabile (`a1af969`); lo stagger del piano è appear-only (`appear-active-class`, spec §5/edge 5), leave con max-width e lista relative, move-class con color/opacity, font-size in transizione, `aria-current` sul passo attivo (`af5d3b2`).
- **Note di scostamento dalla spec (dichiarate):** niente `--hz-gold-rgb` (duplicato di `--hz-line-rgb`); grana finestre solo sull'header (mai sul contenuto moduli, lezione terminale-sempre-dark); minimizzazione = scivolata verso il basso-centro senza coordinate esatte del dock (la spec stessa lo marcava YAGNI); reveal scaglionato applicato a ogni inserimento riga (la guardia isStreaming è superflua: il manoscritto è visibile solo in working, che implica streaming).
