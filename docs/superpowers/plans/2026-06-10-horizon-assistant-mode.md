# Horizon Assistant Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the orb-centric assistant view with **Horizon** — a single morphing editorial scene whose axis is a canvas-rendered line of light that is AL\CE's presence (spec: `docs/superpowers/specs/2026-06-10-horizon-assistant-mode-design.md`).

**Architecture:** A pure state-derivation module (`horizonScene.ts`) maps store snapshots to one of five scene states (`quiet | listening | responding | working | presenting`); `HorizonView` is orchestration-only and feeds small single-responsibility components under `components/horizon/`. The line is one 2D canvas with a declarative props API. No new runtime dependencies; fonts bundled locally.

**Tech Stack:** Vue 3 `<script setup>` + TypeScript, Pinia (existing stores only), vitest (node env — pure-module tests only, NO component mounts), canvas 2D.

**Working directory:** all paths below are relative to `frontend/` unless noted. Run all commands from `frontend/`.

**Conventions that bind every task:**
- `npm run typecheck` must pass at the end of every task (it is part of each task's verify step).
- Vitest runs in the **node environment with no Vue SFC plugin** — never import a `.vue` file from a spec. Test pure `.ts` modules only.
- All UI strings are Italian; code comments/docs English.
- No literal colors in components — only `--hz-*` / theme tokens (single documented exception: the RGB triplet tokens in `horizon.css`, which mirror `--accent` because canvas needs decomposed RGB).

---

### Task 1: Fonts + horizon.css tokens

**Files:**
- Create: `src/renderer/src/assets/fonts/Fraunces-Variable.ttf` (downloaded)
- Create: `src/renderer/src/assets/fonts/Fraunces-Italic-Variable.ttf` (downloaded)
- Create: `src/renderer/src/assets/styles/horizon.css`

- [ ] **Step 1: Download the Fraunces variable fonts (OFL-licensed) into the new fonts dir**

```powershell
New-Item -ItemType Directory -Force src/renderer/src/assets/fonts
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/google/fonts/main/ofl/fraunces/Fraunces%5BSOFT%2CWONK%2Copsz%2Cwght%5D.ttf" -OutFile "src/renderer/src/assets/fonts/Fraunces-Variable.ttf"
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/google/fonts/main/ofl/fraunces/Fraunces-Italic%5BSOFT%2CWONK%2Copsz%2Cwght%5D.ttf" -OutFile "src/renderer/src/assets/fonts/Fraunces-Italic-Variable.ttf"
```

Expected: both files exist and are ~300–500 KB each (`Get-Item src/renderer/src/assets/fonts/*.ttf`).

- [ ] **Step 2: Create `src/renderer/src/assets/styles/horizon.css`**

```css
/**
 * horizon.css — Tokens + fonts for the Horizon assistant scene.
 *
 * Every color is an ALIAS of the app theme (the scene follows the active
 * theme; no new palette). The only literals are the RGB-triplet mirrors of
 * --accent, required because the canvas renderer composes rgba() strings.
 * Keep them in sync with --accent in theme.css.
 */

@font-face {
  font-family: 'Fraunces';
  src: url('../fonts/Fraunces-Variable.ttf') format('truetype-variations');
  font-weight: 100 900;
  font-style: normal;
  font-display: swap;
}

@font-face {
  font-family: 'Fraunces';
  src: url('../fonts/Fraunces-Italic-Variable.ttf') format('truetype-variations');
  font-weight: 100 900;
  font-style: italic;
  font-display: swap;
}

:root {
  /* type */
  --hz-serif: 'Fraunces', Georgia, 'Times New Roman', serif;

  /* ink — aliases */
  --hz-ink: var(--text-primary);
  --hz-ink-dim: var(--text-secondary);
  --hz-ink-faint: var(--text-muted);
  --hz-gold: var(--accent);

  /* canvas line color — --accent (#E8DCC8) decomposed to an RGB triplet */
  --hz-line-rgb: 232, 220, 200;

  /* motion */
  --hz-morph: 600ms;
  --hz-fade: 280ms;
  --hz-breath: 6s;
}

[data-theme='light'] {
  /* --accent (#8C6A4A) decomposed */
  --hz-line-rgb: 140, 106, 74;
}
```

- [ ] **Step 3: Verify typecheck is unaffected and commit**

Run: `npm run typecheck` — Expected: PASS (no source imports the css yet).

```bash
git add src/renderer/src/assets/fonts src/renderer/src/assets/styles/horizon.css
git commit -m "feat(horizon): bundle Fraunces fonts + horizon scene tokens"
```

---

### Task 2: `horizonScene.ts` — pure scene derivation (TDD)

**Files:**
- Create: `src/renderer/src/composables/horizon/horizonScene.ts`
- Test: `src/renderer/src/composables/horizon/horizonScene.spec.ts`

- [ ] **Step 1: Write the failing tests**

```ts
/**
 * Unit tests for the pure Horizon scene derivation module.
 * Pure functions only — no Vue, no Pinia, runnable in the node env.
 */
import { describe, it, expect } from 'vitest'

import {
  deriveSceneState,
  deriveLineMode,
  notchPositions,
  planView,
  toRoman,
  type HorizonSceneInputs,
} from './horizonScene'
import type { TaskStep } from '../../types/tasks'

function inputs(over: Partial<HorizonSceneInputs> = {}): HorizonSceneInputs {
  return {
    isListening: false,
    isSttProcessing: false,
    isSpeaking: false,
    isStreaming: false,
    activeToolCount: 0,
    planSteps: [],
    stageOpen: false,
    artifactCount: 0,
    composerActive: false,
    ...over,
  }
}

const step = (s: string, status = 'pending'): TaskStep => ({ step: s, status })

describe('deriveSceneState', () => {
  it('is quiet when nothing is happening', () => {
    expect(deriveSceneState(inputs())).toBe('quiet')
  })

  it('listening on mic / STT / composer', () => {
    expect(deriveSceneState(inputs({ isListening: true }))).toBe('listening')
    expect(deriveSceneState(inputs({ isSttProcessing: true }))).toBe('listening')
    expect(deriveSceneState(inputs({ composerActive: true }))).toBe('listening')
  })

  it('responding while streaming plain text or speaking', () => {
    expect(deriveSceneState(inputs({ isStreaming: true }))).toBe('responding')
    expect(deriveSceneState(inputs({ isSpeaking: true }))).toBe('responding')
  })

  it('working while streaming with active tools or an unfinished plan', () => {
    expect(deriveSceneState(inputs({ isStreaming: true, activeToolCount: 1 }))).toBe('working')
    expect(
      deriveSceneState(inputs({ isStreaming: true, planSteps: [step('a', 'in_progress')] })),
    ).toBe('working')
  })

  it('a fully completed plan no longer forces working', () => {
    expect(
      deriveSceneState(inputs({ isStreaming: true, planSteps: [step('a', 'completed')] })),
    ).toBe('responding')
  })

  it('presenting wins over everything when the stage is open with artifacts', () => {
    expect(
      deriveSceneState(
        inputs({ stageOpen: true, artifactCount: 1, isStreaming: true, activeToolCount: 2 }),
      ),
    ).toBe('presenting')
  })

  it('stage open without artifacts does NOT present', () => {
    expect(deriveSceneState(inputs({ stageOpen: true }))).toBe('quiet')
  })
})

describe('deriveLineMode', () => {
  it('maps states to line mechanics', () => {
    expect(deriveLineMode('quiet', inputs())).toBe('breathe')
    expect(deriveLineMode('listening', inputs({ isListening: true }))).toBe('tense')
    expect(deriveLineMode('responding', inputs({ isSpeaking: true }))).toBe('pulse')
    expect(deriveLineMode('responding', inputs({ isStreaming: true }))).toBe('breathe')
    expect(deriveLineMode('working', inputs({ planSteps: [step('a')] }))).toBe('timeline')
    expect(deriveLineMode('working', inputs({ activeToolCount: 1 }))).toBe('flow')
    expect(deriveLineMode('presenting', inputs())).toBe('breathe')
  })
})

describe('notchPositions', () => {
  it('returns centered fractions across the span', () => {
    expect(notchPositions(0)).toEqual([])
    expect(notchPositions(1)).toEqual([0.5])
    expect(notchPositions(3)).toEqual([0.15, 0.5, 0.85])
  })
})

describe('planView', () => {
  it('summarises a plan: active = first in_progress, else first pending', () => {
    const v = planView([step('uno', 'completed'), step('due', 'in_progress'), step('tre')])
    expect(v).toEqual({ total: 3, completed: 1, activeIndex: 1, statusSentence: 'due' })
  })
  it('falls back to the first pending, then the last step', () => {
    expect(planView([step('uno', 'completed'), step('due')]).activeIndex).toBe(1)
    expect(planView([step('uno', 'completed')]).activeIndex).toBe(0)
    expect(planView([]).statusSentence).toBe('')
  })
})

describe('toRoman', () => {
  it('formats stage captions', () => {
    expect(toRoman(1)).toBe('I')
    expect(toRoman(4)).toBe('IV')
    expect(toRoman(9)).toBe('IX')
    expect(toRoman(14)).toBe('XIV')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/renderer/src/composables/horizon/horizonScene.spec.ts`
Expected: FAIL — cannot resolve `./horizonScene`.

- [ ] **Step 3: Implement `src/renderer/src/composables/horizon/horizonScene.ts`**

```ts
/**
 * horizonScene.ts — Pure derivation for the Horizon assistant scene.
 *
 * Maps plain snapshots of the voice/chat/tasks stores to a single scene state
 * and the line's visual mechanic. One state active at a time, with explicit
 * priority: presenting ▸ working ▸ responding ▸ listening ▸ quiet.
 *
 * Pure functions only (no Vue imports) so the whole scene brain is unit
 * testable in the node environment.
 */
import type { TaskStep } from '../../types/tasks'

/** The five scene states (spec §3). */
export type HorizonState = 'quiet' | 'listening' | 'responding' | 'working' | 'presenting'

/** The line's visual mechanic (HorizonLine modes). */
export type HorizonLineMode = 'breathe' | 'tense' | 'pulse' | 'timeline' | 'flow'

/** Plain-value snapshot of everything the scene depends on. */
export interface HorizonSceneInputs {
  isListening: boolean
  isSttProcessing: boolean
  isSpeaking: boolean
  isStreaming: boolean
  activeToolCount: number
  planSteps: TaskStep[]
  stageOpen: boolean
  artifactCount: number
  composerActive: boolean
}

/** Whether the plan exists and is not yet fully completed. */
function planActive(steps: TaskStep[]): boolean {
  return steps.length > 0 && steps.some((s) => s.status !== 'completed')
}

/** Derive the single active scene state (priority ordered). */
export function deriveSceneState(i: HorizonSceneInputs): HorizonState {
  if (i.stageOpen && i.artifactCount > 0) return 'presenting'
  if (i.isStreaming && (planActive(i.planSteps) || i.activeToolCount > 0)) return 'working'
  if (i.isStreaming || i.isSpeaking) return 'responding'
  if (i.isListening || i.isSttProcessing || i.composerActive) return 'listening'
  return 'quiet'
}

/** Derive the line mechanic for a scene state. */
export function deriveLineMode(state: HorizonState, i: HorizonSceneInputs): HorizonLineMode {
  switch (state) {
    case 'listening':
      return 'tense'
    case 'responding':
      return i.isSpeaking ? 'pulse' : 'breathe'
    case 'working':
      return i.planSteps.length > 0 ? 'timeline' : 'flow'
    default:
      return 'breathe'
  }
}

/**
 * Notch x-positions for the timeline mode as fractions (0..1) of the line
 * span, centered over the middle 70% so end fades stay clean. Shared by the
 * canvas (ticks/spark) and the DOM labels so they always agree.
 */
export function notchPositions(count: number): number[] {
  if (count <= 0) return []
  if (count === 1) return [0.5]
  return Array.from({ length: count }, (_, i) => 0.15 + (i * 0.7) / (count - 1))
}

/** Plan summary for the working state. */
export interface HorizonPlanView {
  total: number
  completed: number
  activeIndex: number
  statusSentence: string
}

/** Summarise plan steps: active = first in_progress, else first pending, else last. */
export function planView(steps: TaskStep[]): HorizonPlanView {
  const total = steps.length
  const completed = steps.filter((s) => s.status === 'completed').length
  let activeIndex = steps.findIndex((s) => s.status === 'in_progress')
  if (activeIndex < 0) activeIndex = steps.findIndex((s) => s.status === 'pending')
  if (activeIndex < 0) activeIndex = total - 1
  return { total, completed, activeIndex, statusSentence: steps[activeIndex]?.step ?? '' }
}

/** Roman numeral for stage captions (Fig. I, II, …). Supports 1..3999. */
export function toRoman(n: number): string {
  const table: Array<[number, string]> = [
    [1000, 'M'], [900, 'CM'], [500, 'D'], [400, 'CD'], [100, 'C'], [90, 'XC'],
    [50, 'L'], [40, 'XL'], [10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I'],
  ]
  let out = ''
  for (const [v, s] of table) {
    while (n >= v) {
      out += s
      n -= v
    }
  }
  return out
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `npx vitest run src/renderer/src/composables/horizon/horizonScene.spec.ts`
Expected: PASS (all suites).

- [ ] **Step 5: Typecheck + commit**

Run: `npm run typecheck` — Expected: PASS.

```bash
git add src/renderer/src/composables/horizon
git commit -m "feat(horizon): pure scene-state derivation module (TDD)"
```

---

### Task 3: `HorizonLine.vue` — the canvas line renderer

**Files:**
- Create: `src/renderer/src/components/horizon/HorizonLine.vue`

No unit test (component; vitest cannot mount SFCs in this repo). Gate = typecheck + visual check in Task 4.

- [ ] **Step 1: Create `src/renderer/src/components/horizon/HorizonLine.vue`**

```vue
<script setup lang="ts">
/**
 * HorizonLine — the horizon: a thin line of light on a 2D canvas.
 *
 * Fully declarative (props only, no exposed methods). Modes:
 *  - breathe  : near-imperceptible sine drift (quiet / plain response)
 *  - tense    : audio-reactive membrane (listening), driven by audioLevel
 *  - pulse    : luminance travelling out from center (TTS speaking)
 *  - timeline : straight line + plan notches + spark easing to the active step
 *  - flow     : a light packet travelling left→right (indeterminate work)
 *
 * One rAF loop, paused on document.hidden; static single draw under
 * prefers-reduced-motion. Colors come from --hz-line-rgb (re-read on theme
 * change via a data-theme MutationObserver). All draw calls no-op when the
 * 2D context is unavailable (test environments).
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { notchPositions, type HorizonLineMode } from '../../composables/horizon/horizonScene'

const props = withDefaults(
  defineProps<{
    mode: HorizonLineMode
    /** Mic level 0–1 (tense mode). */
    audioLevel?: number
    /** Timeline notch count. */
    notchCount?: number
    /** Active notch index (spark target). */
    activeIndex?: number
    /** Dim the line (disconnected / dialog open behind). */
    dimmed?: boolean
  }>(),
  { audioLevel: 0, notchCount: 0, activeIndex: -1, dimmed: false },
)

const canvasRef = ref<HTMLCanvasElement | null>(null)

let ctx: CanvasRenderingContext2D | null = null
let raf = 0
let running = false
let width = 0
let height = 0
/** Smoothed audio level (avoids snapping). */
let levelSmooth = 0
/** Spark position as a fraction of the span (eases toward the active notch). */
let sparkX = 0.5
/** "r, g, b" triplet resolved from --hz-line-rgb. */
let lineRgb = '232, 220, 200'
let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true

function readThemeColor(): void {
  const el = canvasRef.value
  if (!el) return
  const raw = getComputedStyle(el).getPropertyValue('--hz-line-rgb').trim()
  if (raw) lineRgb = raw
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
  ctx.clearRect(0, 0, width, height)
  const cy = height / 2
  const margin = width * 0.06
  const span = width - margin * 2
  const alpha = props.dimmed ? 0.35 : 1

  const targetLevel = props.mode === 'tense' ? Math.max(props.audioLevel, 0.06) : 0
  levelSmooth += (targetLevel - levelSmooth) * 0.18

  /* ── the line ── */
  ctx.save()
  ctx.globalAlpha = alpha
  const grad = ctx.createLinearGradient(margin, 0, margin + span, 0)
  grad.addColorStop(0, `rgba(${lineRgb}, 0)`)
  grad.addColorStop(0.3, `rgba(${lineRgb}, 0.55)`)
  grad.addColorStop(0.5, `rgba(${lineRgb}, 1)`)
  grad.addColorStop(0.7, `rgba(${lineRgb}, 0.55)`)
  grad.addColorStop(1, `rgba(${lineRgb}, 0)`)
  ctx.strokeStyle = grad
  ctx.lineWidth = 1
  ctx.shadowColor = `rgba(${lineRgb}, 0.5)`
  ctx.shadowBlur = 12

  ctx.beginPath()
  const steps = 96
  for (let s = 0; s <= steps; s++) {
    const f = s / steps
    const x = margin + f * span
    const env = Math.sin(f * Math.PI) // pins both ends to the baseline
    let y = cy
    if (!reducedMotion) {
      if (props.mode === 'breathe') {
        y = cy + Math.sin(t * 0.7 + f * Math.PI) * 1.5 * env
      } else if (props.mode === 'tense') {
        y =
          cy +
          env * levelSmooth * 18 *
            (Math.sin(f * 26 + t * 9) * 0.6 + Math.sin(f * 53 - t * 13) * 0.4)
      } else if (props.mode === 'pulse') {
        y = cy + Math.sin(t * 2.2 + f * Math.PI * 2) * 1.2 * env
      }
    }
    if (s === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.stroke()
  ctx.restore()

  /* ── pulse: twin luminance packets travelling out from center (TTS) ── */
  if (props.mode === 'pulse' && !reducedMotion) {
    const phase = (t * 0.6) % 1
    const r = phase * span * 0.5
    ctx.save()
    ctx.globalAlpha = alpha * (1 - phase) * 0.5
    ctx.fillStyle = `rgba(${lineRgb}, 0.9)`
    ctx.shadowColor = `rgba(${lineRgb}, 0.8)`
    ctx.shadowBlur = 10
    ctx.fillRect(width / 2 - r - 1, cy - 0.8, 2, 1.6)
    ctx.fillRect(width / 2 + r - 1, cy - 0.8, 2, 1.6)
    ctx.restore()
  }

  /* ── flow: indeterminate work packet, left→right ── */
  if (props.mode === 'flow' && !reducedMotion) {
    const f = (t * 0.22) % 1
    const x = margin + f * span
    ctx.save()
    ctx.globalAlpha = alpha
    const g = ctx.createRadialGradient(x, cy, 0, x, cy, 26)
    g.addColorStop(0, `rgba(${lineRgb}, 0.85)`)
    g.addColorStop(1, `rgba(${lineRgb}, 0)`)
    ctx.fillStyle = g
    ctx.fillRect(x - 26, cy - 4, 52, 8)
    ctx.restore()
  }

  /* ── timeline: notches + spark ── */
  if (props.mode === 'timeline' && props.notchCount > 0) {
    const fractions = notchPositions(props.notchCount)
    ctx.save()
    ctx.globalAlpha = alpha
    fractions.forEach((p, i) => {
      const x = margin + p * span
      const active = i === props.activeIndex
      ctx!.strokeStyle = `rgba(${lineRgb}, ${active ? 1 : 0.55})`
      ctx!.lineWidth = 1
      ctx!.beginPath()
      ctx!.moveTo(x, cy - (active ? 6 : 4))
      ctx!.lineTo(x, cy + (active ? 6 : 4))
      ctx!.stroke()
    })
    const clamped = Math.max(0, Math.min(props.activeIndex, fractions.length - 1))
    const target = fractions[clamped] ?? 0.5
    sparkX += (target - sparkX) * (reducedMotion ? 1 : 0.06)
    const sx = margin + sparkX * span
    const breathe = reducedMotion ? 1 : 0.75 + Math.sin(t * 3) * 0.25
    const g = ctx.createRadialGradient(sx, cy, 0, sx, cy, 9)
    g.addColorStop(0, `rgba(${lineRgb}, ${0.95 * breathe})`)
    g.addColorStop(1, `rgba(${lineRgb}, 0)`)
    ctx.fillStyle = g
    ctx.fillRect(sx - 9, cy - 9, 18, 18)
    ctx.restore()
  }
}

function loop(now: number): void {
  if (!running) return
  draw(now)
  raf = requestAnimationFrame(loop)
}

function start(): void {
  if (running || reducedMotion || !ctx) return
  running = true
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
  readThemeColor()
  resize()
  if (typeof ResizeObserver !== 'undefined' && el.parentElement) {
    resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(el.parentElement)
  }
  if (typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(() => {
      readThemeColor()
      if (reducedMotion) draw(performance.now())
    })
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
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

/* Reduced-motion: redraw once whenever any visual input changes. */
watch(
  () => [props.mode, props.audioLevel, props.notchCount, props.activeIndex, props.dimmed],
  () => {
    if (reducedMotion) draw(performance.now())
  },
)
</script>

<template>
  <div class="hz-line" aria-hidden="true">
    <canvas ref="canvasRef" class="hz-line__canvas" />
  </div>
</template>

<style scoped>
.hz-line {
  position: relative;
  width: 100%;
  height: 64px; /* vertical overscan around the 1px line for glow/waveform */
  pointer-events: none;
}

.hz-line__canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}
</style>
```

- [ ] **Step 2: Typecheck + commit**

Run: `npm run typecheck` — Expected: PASS.

```bash
git add src/renderer/src/components/horizon/HorizonLine.vue
git commit -m "feat(horizon): canvas horizon-line renderer (5 modes, reduced-motion safe)"
```

---

### Task 4: Scene shell — HorizonScene/Masthead/Quiet/Colophon + view skeleton + dev route

**Files:**
- Create: `src/renderer/src/composables/horizon/useClock.ts`
- Create: `src/renderer/src/components/horizon/HorizonScene.vue`
- Create: `src/renderer/src/components/horizon/HorizonMasthead.vue`
- Create: `src/renderer/src/components/horizon/HorizonQuiet.vue`
- Create: `src/renderer/src/components/horizon/HorizonColophon.vue`
- Create: `src/renderer/src/views/HorizonView.vue`
- Modify: `src/renderer/src/router/index.ts` (add `/horizon` dev route after the `'assistant'` route entry)

- [ ] **Step 1: Create `src/renderer/src/composables/horizon/useClock.ts`**

```ts
/**
 * useClock — a Date ref that ticks on an interval (default 30 s).
 * Shared by the greeting and the colophon so they agree on "now".
 */
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export function useClock(intervalMs = 30_000): Ref<Date> {
  const now = ref(new Date())
  let timer: ReturnType<typeof setInterval> | null = null
  onMounted(() => {
    timer = setInterval(() => {
      now.value = new Date()
    }, intervalMs)
  })
  onBeforeUnmount(() => {
    if (timer) clearInterval(timer)
  })
  return now
}
```

- [ ] **Step 2: Create `src/renderer/src/components/horizon/HorizonScene.vue`**

```vue
<script setup lang="ts">
/**
 * HorizonScene — the stage. Owns the vertical zoning (masthead / upper /
 * line / lower) and animates the line's vertical quota between scene states:
 * that movement IS the visible morph. Pure layout: no stores.
 */
import { computed } from 'vue'
import type { HorizonState } from '../../composables/horizon/horizonScene'

const props = withDefaults(
  defineProps<{
    state: HorizonState
    /** Long-response magazine layout (overrides the state quota). */
    magazine?: boolean
    /** Dim the whole scene (a dialog is in front). */
    dimmed?: boolean
  }>(),
  { magazine: false, dimmed: false },
)

/** Line vertical quota per state (fraction of scene height). */
const QUOTAS: Record<HorizonState, number> = {
  quiet: 0.58,
  listening: 0.6,
  responding: 0.64,
  working: 0.5,
  presenting: 0.26,
}

const quota = computed(() => (props.magazine ? 0.18 : QUOTAS[props.state]))
</script>

<template>
  <div
    class="hz-scene"
    :class="[`hz-scene--${state}`, { 'hz-scene--dimmed': dimmed }]"
    :style="{ '--quota': `${quota * 100}%` }"
  >
    <header class="hz-scene__masthead"><slot name="masthead" /></header>
    <div class="hz-scene__upper"><slot name="upper" /></div>
    <div class="hz-scene__line"><slot name="line" /></div>
    <div class="hz-scene__lower"><slot name="lower" /></div>
  </div>
</template>

<style scoped>
.hz-scene {
  position: relative;
  width: 100%;
  height: 100%;
  background: var(--surface-0);
  overflow: hidden;
  transition: opacity var(--hz-fade) ease;
}

.hz-scene--dimmed {
  opacity: 0.4;
  pointer-events: none;
}

.hz-scene__masthead {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  z-index: 3;
}

.hz-scene__upper {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: var(--quota);
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  z-index: 2;
  transition: height var(--hz-morph) var(--ease-out-expo);
}

.hz-scene__line {
  position: absolute;
  left: 0;
  right: 0;
  top: var(--quota);
  transform: translateY(-50%);
  z-index: 1;
  transition: top var(--hz-morph) var(--ease-out-expo);
}

.hz-scene__lower {
  position: absolute;
  left: 0;
  right: 0;
  top: var(--quota);
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  z-index: 2;
  padding-top: 44px;
  transition: top var(--hz-morph) var(--ease-out-expo);
}

@media (prefers-reduced-motion: reduce) {
  .hz-scene__upper,
  .hz-scene__line,
  .hz-scene__lower {
    transition: none;
  }
}
</style>
```

- [ ] **Step 3: Create `src/renderer/src/components/horizon/HorizonMasthead.vue`**

```vue
<script setup lang="ts">
/** HorizonMasthead — the folio: AL\CE wordmark + connection glyph. */
defineProps<{ connected: boolean }>()
</script>

<template>
  <div class="hz-masthead">
    <span class="hz-masthead__folio">AL\CE</span>
    <span
      class="hz-masthead__status"
      :class="{ 'hz-masthead__status--off': !connected }"
      :title="connected ? 'Connessa' : 'Disconnessa'"
    />
  </div>
</template>

<style scoped>
.hz-masthead {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding-top: clamp(20px, 4vh, 44px);
  user-select: none;
}

.hz-masthead__folio {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.42em;
  text-indent: 0.42em; /* optically recenters the tracked text */
  color: var(--hz-ink-faint);
}

.hz-masthead__status {
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  background: var(--success);
  opacity: 0.7;
}

.hz-masthead__status--off {
  background: var(--danger);
  animation: hz-blink 2s ease-in-out infinite;
}

@keyframes hz-blink {
  50% {
    opacity: 0.25;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hz-masthead__status--off {
    animation: none;
  }
}
</style>
```

- [ ] **Step 4: Create `src/renderer/src/components/horizon/HorizonQuiet.vue`**

```vue
<script setup lang="ts">
/** HorizonQuiet — the time-of-day greeting shown in the quiet state. */
import { computed } from 'vue'
import { useClock } from '../../composables/horizon/useClock'

const now = useClock()

const greeting = computed(() => {
  const h = now.value.getHours()
  if (h < 6) return 'Buonanotte.'
  if (h < 13) return 'Buongiorno.'
  if (h < 18) return 'Buon pomeriggio.'
  return 'Buonasera.'
})
</script>

<template>
  <p class="hz-quiet">{{ greeting }}</p>
</template>

<style scoped>
.hz-quiet {
  margin: 0 0 clamp(28px, 6vh, 64px);
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: clamp(28px, 4.6vmin, 52px);
  letter-spacing: 0.01em;
  color: var(--hz-ink);
  user-select: none;
}
</style>
```

- [ ] **Step 5: Create `src/renderer/src/components/horizon/HorizonColophon.vue`**

```vue
<script setup lang="ts">
/**
 * HorizonColophon — the masthead-style ground line at the bottom of the
 * scene: date · time · next calendar event, plus the disconnected marker.
 * Segments degrade gracefully when a source is unavailable.
 */
import { computed } from 'vue'
import { useClock } from '../../composables/horizon/useClock'
import type { CalendarEvent } from '../../types/calendar'

const props = defineProps<{
  nextEvent: CalendarEvent | null
  connected: boolean
}>()

const now = useClock()

const parts = computed(() => {
  const list: string[] = [
    now.value.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' }),
    now.value.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }),
  ]
  if (props.nextEvent) {
    const hm = new Date(props.nextEvent.start_time).toLocaleTimeString('it-IT', {
      hour: '2-digit',
      minute: '2-digit',
    })
    list.push(`${props.nextEvent.title} alle ${hm}`)
  }
  if (!props.connected) list.push('DISCONNESSA')
  return list
})
</script>

<template>
  <p class="hz-colophon" :class="{ 'hz-colophon--off': !connected }">
    {{ parts.join(' · ') }}
  </p>
</template>

<style scoped>
.hz-colophon {
  margin: auto 0 clamp(20px, 4vh, 40px);
  font-family: var(--font-sans);
  font-weight: 400;
  font-size: 10px;
  letter-spacing: 0.32em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
  text-align: center;
  user-select: none;
}

.hz-colophon--off {
  color: var(--danger);
}
</style>
```

- [ ] **Step 6: Create `src/renderer/src/views/HorizonView.vue` (skeleton — anchors are load-bearing for later tasks)**

```vue
<script setup lang="ts">
/**
 * HorizonView — the assistant surface: one morphing editorial scene whose
 * axis is the horizon line (AL\CE's presence). Orchestration only: this file
 * wires stores/composables into props for components/horizon/*; it owns no
 * scene markup beyond composition.
 */
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import HorizonScene from '../components/horizon/HorizonScene.vue'
import HorizonLine from '../components/horizon/HorizonLine.vue'
import HorizonMasthead from '../components/horizon/HorizonMasthead.vue'
import HorizonQuiet from '../components/horizon/HorizonQuiet.vue'
import HorizonColophon from '../components/horizon/HorizonColophon.vue'
import { ChatApiKey } from '../composables/useChat'
import { useVoice } from '../composables/useVoice'
import {
  deriveSceneState,
  deriveLineMode,
  type HorizonSceneInputs,
} from '../composables/horizon/horizonScene'
import { useChatStore } from '../stores/chat'
import { useVoiceStore } from '../stores/voice'
import { useTasksStore } from '../stores/tasks'
import { useCalendarStore } from '../stores/calendar'
import '../assets/styles/horizon.css'

const chatStore = useChatStore()
const voiceStore = useVoiceStore()
const tasksStore = useTasksStore()
const calendarStore = useCalendarStore()

const chatApi = inject(ChatApiKey, null)
const _noop = (): void => {}
const _asyncNoop = async (): Promise<void> => {}
const send = chatApi?.sendMessage ?? _asyncNoop
const stopGeneration = chatApi?.stopGeneration ?? _noop
const respondToConfirmation = chatApi?.respondToConfirmation ?? _noop
const answerAskUser = chatApi?.answerAskUser ?? _noop
const isConnected = chatApi?.isConnected ?? ref(false)

const {
  startListening,
  stopListening,
  cancelProcessing,
  connect: connectVoice,
  transcript,
  speak,
  cancelSpeak,
} = useVoice()

/* ── ANCHOR: local-state ── */
const composerActive = ref(false)
const stageOpen = ref(false)

/* ── ANCHOR: derived ── */
const planSteps = computed(() => {
  const id = chatStore.currentConversation?.id
  return id ? tasksStore.tasksFor(id) : []
})

/** Replaced by the artifact extraction in the Stage task. */
const artifactCount = computed(() => 0)

const sceneInputs = computed<HorizonSceneInputs>(() => ({
  isListening: voiceStore.isListening,
  isSttProcessing: voiceStore.isProcessing,
  isSpeaking: voiceStore.isSpeaking,
  isStreaming: chatStore.isStreamingCurrentConversation,
  activeToolCount: chatStore.activeToolExecutions.length,
  planSteps: planSteps.value,
  stageOpen: stageOpen.value,
  artifactCount: artifactCount.value,
  composerActive: composerActive.value,
}))

const sceneState = computed(() => deriveSceneState(sceneInputs.value))
const lineMode = computed(() => deriveLineMode(sceneState.value, sceneInputs.value))

const pendingConfirmationsList = computed(() => Object.values(chatStore.pendingConfirmations))
const pendingAskUserList = computed(() => Object.values(chatStore.pendingAskUser))
const sceneDimmed = computed(
  () => pendingConfirmationsList.value.length > 0 || pendingAskUserList.value.length > 0,
)

/* ── ANCHOR: interactions ── */
/** Clicking empty scene space toggles voice (mirrors the old orb click). */
function handleSceneClick(event: MouseEvent): void {
  const tgt = event.target as HTMLElement | null
  if (tgt?.closest('button, a, input, textarea, [contenteditable], .hz-stage, .hz-history')) return
  if (voiceStore.isSpeaking) {
    cancelSpeak()
  } else if (chatStore.isStreamingCurrentConversation) {
    stopGeneration()
    cancelSpeak()
  } else if (voiceStore.isListening) {
    stopListening()
  } else if (voiceStore.isProcessing) {
    cancelProcessing()
  } else {
    startListening()
  }
}

/* ── ANCHOR: voice-wiring ── */
// Auto-send the STT transcript when confirmation is disabled.
watch(
  () => voiceStore.transcript,
  (text) => {
    if (!text.trim() || voiceStore.confirmTranscript) return
    const toSend = text.trim()
    voiceStore.clearTranscript()
    send(toSend).catch(console.error)
  },
)

/* ── ANCHOR: lifecycle ── */
onMounted(() => {
  connectVoice()
  chatStore.restoreConversation().catch(console.error)
  calendarStore.refresh().catch(() => {
    /* colophon degrades to date · time */
  })
  const id = chatStore.currentConversation?.id
  if (id) {
    tasksStore.ensureForConversation(id).catch(() => {
      /* timeline simply stays empty */
    })
  }
})
</script>

<template>
  <div class="horizon-view" aria-label="Assistente" @click="handleSceneClick">
    <HorizonScene :state="sceneState" :dimmed="sceneDimmed">
      <template #masthead>
        <HorizonMasthead :connected="isConnected" />
      </template>

      <template #upper>
        <!-- ANCHOR: upper-zone -->
        <Transition name="hz-soft">
          <HorizonQuiet v-if="sceneState === 'quiet'" />
        </Transition>
      </template>

      <template #line>
        <!-- dimmed → "embers" when the chat socket is down (spec §3.6) -->
        <HorizonLine :mode="lineMode" :audio-level="voiceStore.audioLevel" :dimmed="!isConnected" />
      </template>

      <template #lower>
        <!-- ANCHOR: lower-zone -->
        <HorizonColophon
          v-if="sceneState !== 'presenting'"
          :next-event="calendarStore.nextEvent"
          :connected="isConnected"
        />
      </template>
    </HorizonScene>

    <!-- ANCHOR: overlays -->
  </div>
</template>

<style scoped>
.horizon-view {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

/* Shared soft fade for scene content swaps. */
.hz-soft-enter-active,
.hz-soft-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-soft-enter-from,
.hz-soft-leave-to {
  opacity: 0;
}
</style>
```

- [ ] **Step 7: Add the dev route in `src/renderer/src/router/index.ts`**

Insert directly after the existing `'assistant'` route object (the one with `path: '/assistant'`):

```ts
    {
      // TEMPORARY dev route for the Horizon rebuild — removed when the
      // 'assistant' route flips to HorizonView (see the Horizon plan, Task 12).
      path: '/horizon',
      name: 'horizon-dev',
      component: () => import('../views/HorizonView.vue'),
      meta: { title: 'Orizzonte (dev)', transition: DEFAULT_PAGE_TRANSITION }
    },
```

- [ ] **Step 8: Verify**

Run: `npm run typecheck` — Expected: PASS.
Run: `npm run dev`, navigate to `#/horizon`. Expected: folio AL\CE at top, greeting in Fraunces, the breathing line at 58%, colophon with date · time (and the next event when the calendar plugin is on). Click an empty area: line tenses (listening); click again: returns. Switch the app theme: the line color follows.

- [ ] **Step 9: Commit**

```bash
git add src/renderer/src/components/horizon src/renderer/src/views/HorizonView.vue src/renderer/src/composables/horizon/useClock.ts src/renderer/src/router/index.ts
git commit -m "feat(horizon): scene shell (quiet/listening) + /horizon dev route"
```

---

### Task 5: `useSentencePacer` (TDD)

**Files:**
- Create: `src/renderer/src/composables/horizon/useSentencePacer.ts`
- Test: `src/renderer/src/composables/horizon/useSentencePacer.spec.ts`

- [ ] **Step 1: Write the failing tests**

```ts
/**
 * Tests for the sentence pacer: token stream → sentences committed at a
 * reading rhythm. Pure Vue reactivity + timers; no DOM.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { effectScope, ref, type EffectScope } from 'vue'

import { segmentSentences, useSentencePacer } from './useSentencePacer'

describe('segmentSentences', () => {
  it('splits complete sentences and keeps the unterminated rest', () => {
    expect(segmentSentences('Prima frase. Seconda frase! E poi')).toMatchObject({
      sentences: ['Prima frase.', 'Seconda frase!'],
      rest: 'E poi',
    })
  })

  it('treats ellipsis and ? as terminators', () => {
    expect(segmentSentences('Vediamo… Sicuro? ok').sentences).toEqual(['Vediamo…', 'Sicuro?'])
  })

  it('returns everything as rest when nothing terminates', () => {
    expect(segmentSentences('streaming senza fine')).toMatchObject({
      sentences: [],
      rest: 'streaming senza fine',
    })
  })
})

describe('useSentencePacer', () => {
  let scope: EffectScope

  beforeEach(() => {
    vi.useFakeTimers()
    scope = effectScope()
  })

  afterEach(() => {
    scope.stop()
    vi.useRealTimers()
  })

  it('commits one sentence per interval while streaming', async () => {
    const source = ref('')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    source.value = 'Una. Due. Tre.'
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Una.')
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Una. Due.')
  })

  it('flushes everything (including the rest) when streaming ends', async () => {
    const source = ref('Una. Due. E mezzo')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    await vi.advanceTimersByTimeAsync(300)
    streaming.value = false
    await vi.advanceTimersByTimeAsync(0)
    expect(pacer.displayed.value).toBe('Una. Due. E mezzo')
  })

  it('immediate mode mirrors the source (reduced motion)', async () => {
    const source = ref('Tutto. Subito.')
    const streaming = ref(true)
    const pacer = scope.run(() =>
      useSentencePacer(source, streaming, { intervalMs: 300, immediate: true }),
    )!
    await vi.advanceTimersByTimeAsync(0)
    expect(pacer.displayed.value).toBe('Tutto. Subito.')
  })

  it('reset() clears the display for a new turn', async () => {
    const source = ref('Vecchia frase.')
    const streaming = ref(false)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!
    await vi.advanceTimersByTimeAsync(0)
    pacer.reset()
    expect(pacer.displayed.value).toBe('')
  })

  it('never drops the prefix before a non-terminating period (decimals)', async () => {
    const source = ref('')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    source.value = 'Il valore è 3.14 circa. Fine.'
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Il valore è 3.14 circa.')
  })

  it('preserves newlines/markdown structure in the paced display', async () => {
    const source = ref('')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    source.value = 'Prima riga.\n\nSeconda frase. Coda'
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Prima riga.')
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Prima riga.\n\nSeconda frase.')
  })

  it('turn boundary: source reset to empty clears and re-paces from one', async () => {
    const source = ref('Vecchia. Fine.')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    await vi.advanceTimersByTimeAsync(600)
    streaming.value = false
    await vi.advanceTimersByTimeAsync(0)
    expect(pacer.displayed.value).toBe('Vecchia. Fine.')

    source.value = ''
    await vi.advanceTimersByTimeAsync(0)
    expect(pacer.displayed.value).toBe('')

    streaming.value = true
    source.value = 'Nuova. Seconda.'
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Nuova.')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/renderer/src/composables/horizon/useSentencePacer.spec.ts`
Expected: FAIL — cannot resolve `./useSentencePacer`.

- [ ] **Step 3: Implement `src/renderer/src/composables/horizon/useSentencePacer.ts`**

```ts
/**
 * useSentencePacer — turns a raw streaming text ref into sentence-paced
 * display text: while `streaming` is true, complete sentences are committed
 * one per interval (reading rhythm); when streaming flips false everything
 * (including any unterminated tail) is flushed at once.
 *
 * `immediate: true` (reduced motion) mirrors the source verbatim.
 *
 * Contract: `source` must only append within a turn, or reset to '' at a turn
 * boundary.
 */
import { onScopeDispose, ref, watch, type Ref } from 'vue'

/** Split text into terminated sentences + the unterminated rest. */
export function segmentSentences(text: string): {
  sentences: string[]
  rest: string
  /** End offset (exclusive) of each sentence in the ORIGINAL string. */
  ends: number[]
} {
  const sentences: string[] = []
  const ends: number[] = []
  const re = /[^.!?…]*[.!?…]+(?:\s+|$)/g
  let consumed = 0
  for (const m of text.matchAll(re)) {
    sentences.push(m[0].trim())
    consumed = (m.index ?? 0) + m[0].length
    ends.push(consumed)
  }
  return { sentences, rest: text.slice(consumed).trim(), ends }
}

export interface SentencePacerOptions {
  /** Gap between committed sentences (ms). Default 350. */
  intervalMs?: number
  /** Mirror the source verbatim (prefers-reduced-motion). Default false. */
  immediate?: boolean
}

export interface SentencePacer {
  /** The paced text to display. */
  displayed: Ref<string>
  /** Clear for a new turn. */
  reset: () => void
}

export function useSentencePacer(
  source: Ref<string>,
  streaming: Ref<boolean>,
  options: SentencePacerOptions = {},
): SentencePacer {
  const intervalMs = options.intervalMs ?? 350
  const displayed = ref('')
  /** Number of sentences currently shown. */
  let shown = 0
  let timer: ReturnType<typeof setInterval> | null = null

  function stopTimer(): void {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function flush(): void {
    stopTimer()
    displayed.value = source.value
    shown = segmentSentences(source.value).sentences.length
  }

  function commitNext(): void {
    const { ends } = segmentSentences(source.value)
    if (shown < ends.length) {
      shown += 1
      displayed.value = source.value.slice(0, ends[shown - 1]).trimEnd()
    }
    if (!streaming.value) flush()
  }

  /**
   * Starts the interval on first call; subsequent calls are no-ops.
   * The first sentence appears after one full interval — an intentional
   * reading "breath" before text materializes.
   */
  function ensureTimer(): void {
    if (!timer) timer = setInterval(commitNext, intervalMs)
  }

  watch(
    [source, streaming],
    ([text, isStreaming]) => {
      if (options.immediate) {
        displayed.value = text
        return
      }
      if (text === '') {
        // New turn begins with an empty stream.
        stopTimer()
        displayed.value = ''
        shown = 0
        return
      }
      if (isStreaming) ensureTimer()
      else flush()
    },
    { immediate: true },
  )

  function reset(): void {
    stopTimer()
    displayed.value = ''
    shown = 0
  }

  onScopeDispose(stopTimer)

  return { displayed, reset }
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `npx vitest run src/renderer/src/composables/horizon/useSentencePacer.spec.ts`
Expected: PASS.

- [ ] **Step 5: Typecheck + commit**

Run: `npm run typecheck` — Expected: PASS.

```bash
git add src/renderer/src/composables/horizon/useSentencePacer.ts src/renderer/src/composables/horizon/useSentencePacer.spec.ts
git commit -m "feat(horizon): sentence pacer for reading-rhythm responses (TDD)"
```

---

### Task 6: `HorizonComposer` + keyboard/voice entry wiring

**Files:**
- Create: `src/renderer/src/components/horizon/HorizonComposer.vue`
- Modify: `src/renderer/src/views/HorizonView.vue` (at the marked ANCHOR comments)

- [ ] **Step 1: Create `src/renderer/src/components/horizon/HorizonComposer.vue`**

```vue
<script setup lang="ts">
/**
 * HorizonComposer — the materializing input: a boxless serif line above the
 * horizon. Shows the live STT transcript while listening/processing;
 * otherwise an editable line seeded with the first globally-typed character.
 */
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  /** Typed-composition mode is active. */
  active: boolean
  listening: boolean
  sttProcessing: boolean
  transcript: string
  disabled: boolean
}>()

const emit = defineEmits<{
  send: [text: string]
  close: []
}>()

const text = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)

watch(
  () => props.active,
  async (active) => {
    if (active) {
      await nextTick()
      inputRef.value?.focus()
    } else {
      text.value = ''
    }
  },
)

/** Seed the first character captured by the view's global keydown. */
function seed(ch: string): void {
  text.value += ch
  void nextTick(() => inputRef.value?.focus())
}

defineExpose({ seed })

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    const t = text.value.trim()
    if (t && !props.disabled) {
      emit('send', t)
      text.value = ''
    }
  } else if (e.key === 'Escape') {
    emit('close')
  }
}
</script>

<template>
  <div v-if="active || listening || sttProcessing" class="hz-composer">
    <p v-if="listening || sttProcessing" class="hz-composer__transcript">
      <em>{{ transcript || (listening ? 'Ti ascolto…' : 'Elaboro…') }}</em>
    </p>
    <textarea
      v-else
      ref="inputRef"
      v-model="text"
      class="hz-composer__input"
      rows="1"
      :disabled="disabled"
      aria-label="Scrivi ad AL\CE"
      placeholder=""
      @keydown="onKeydown"
    />
  </div>
</template>

<style scoped>
.hz-composer {
  width: min(72%, 720px);
  margin-bottom: clamp(20px, 4vh, 48px);
  text-align: center;
}

.hz-composer__transcript {
  margin: 0;
  font-family: var(--hz-serif);
  font-style: italic;
  font-weight: 300;
  font-size: clamp(18px, 2.6vmin, 26px);
  line-height: 1.5;
  color: var(--hz-ink-dim);
}

.hz-composer__input {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  text-align: center;
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: clamp(18px, 2.6vmin, 26px);
  line-height: 1.5;
  color: var(--hz-ink);
  caret-color: var(--hz-gold);
}
</style>
```

- [ ] **Step 2: Wire it into `HorizonView.vue`**

a) Add the import next to the other horizon component imports:

```ts
import HorizonComposer from '../components/horizon/HorizonComposer.vue'
```

b) Under `/* ── ANCHOR: local-state ── */`, add:

```ts
const composerRef = ref<InstanceType<typeof HorizonComposer> | null>(null)
```

c) Under `/* ── ANCHOR: interactions ── */`, add:

```ts
/** Sends typed text; collapses the composer. */
async function handleComposerSend(content: string): Promise<void> {
  composerActive.value = false
  await send(content).catch(console.error)
}

/**
 * Global key capture: Esc walks the interrupt chain; any printable first
 * character materializes the composer (Jarvis entry — no visible input box).
 */
function onGlobalKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    if (voiceStore.isSpeaking) cancelSpeak()
    else if (chatStore.isStreamingCurrentConversation) stopGeneration()
    else if (stageOpen.value) stageOpen.value = false
    else composerActive.value = false
    return
  }
  if (composerActive.value) return
  const tgt = e.target as HTMLElement | null
  if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.isContentEditable))
    return
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
    e.preventDefault()
    composerActive.value = true
    composerRef.value?.seed(e.key)
  }
}
```

d) Under `/* ── ANCHOR: lifecycle ── */`, extend `onMounted` and add the teardown:

```ts
  window.addEventListener('keydown', onGlobalKeydown)
```

```ts
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})
```

e) In the template, replace the `<!-- ANCHOR: upper-zone -->` block content with:

```vue
        <!-- ANCHOR: upper-zone -->
        <Transition name="hz-soft">
          <HorizonQuiet v-if="sceneState === 'quiet' && !composerActive" />
        </Transition>
        <HorizonComposer
          ref="composerRef"
          :active="composerActive"
          :listening="voiceStore.isListening"
          :stt-processing="voiceStore.isProcessing"
          :transcript="transcript"
          :disabled="chatStore.isStreamingCurrentConversation"
          @send="handleComposerSend"
          @close="composerActive = false"
        />
```

- [ ] **Step 3: Verify**

Run: `npm run typecheck` — Expected: PASS.
Run: `npm run dev` → `#/horizon`: typing any letter from the quiet scene materializes the serif input seeded with that letter; Enter sends (response streams via WS); Esc dismisses; clicking the scene starts listening and the spoken transcript appears in italics above the line.

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/components/horizon/HorizonComposer.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): materializing composer + global key/voice entry"
```

---

### Task 7: `HorizonResponse` + magazine fallback + TTS

**Files:**
- Create: `src/renderer/src/components/horizon/HorizonResponse.vue`
- Modify: `src/renderer/src/views/HorizonView.vue`

- [ ] **Step 1: Create `src/renderer/src/components/horizon/HorizonResponse.vue`**

```vue
<script setup lang="ts">
/**
 * HorizonResponse — the serif response above the line.
 *
 * Two layouts: "stage" (large centered serif, a few sentences) and
 * "magazine" (a scrollable reading column with a drop cap) for long answers.
 * The component only *reports* when the magazine threshold is crossed —
 * the parent owns the flag (it also drives the scene's line quota).
 */
import { computed, watch } from 'vue'
import { renderMarkdown } from '../../composables/useMarkdown'

const props = defineProps<{
  text: string
  userQuery: string
  magazine: boolean
  /** Compact mode while the stage (presenting) is open. */
  compact?: boolean
}>()

const emit = defineEmits<{ 'update:magazine': [v: boolean] }>()

const MAGAZINE_THRESHOLD = 5

const sentenceCount = computed(() => (props.text.match(/[.!?…]+(\s|$)/g) ?? []).length)

watch(
  sentenceCount,
  (n) => {
    if (n > MAGAZINE_THRESHOLD && !props.magazine) emit('update:magazine', true)
  },
  { immediate: true },
)

const html = computed(() => renderMarkdown(props.text))
</script>

<template>
  <div
    class="hz-response"
    :class="{ 'hz-response--magazine': magazine, 'hz-response--compact': compact }"
  >
    <!-- eslint-disable-next-line vue/no-v-html -->
    <div class="hz-response__body" v-html="html" />
  </div>
</template>

<style scoped>
.hz-response {
  width: min(78%, 760px);
  margin-bottom: clamp(16px, 3vh, 40px);
  overflow: hidden;
}

.hz-response__body {
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: clamp(17px, 2.4vmin, 24px);
  line-height: 1.6;
  color: var(--hz-ink);
  text-align: center;
}

.hz-response__body :deep(p) {
  margin: 0 0 0.6em;
}

.hz-response__body :deep(code),
.hz-response__body :deep(pre) {
  font-family: var(--font-mono);
  font-size: 0.78em;
  text-align: left;
}

/* ── magazine: long answers become a reading column ── */
.hz-response--magazine {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: thin;
}

.hz-response--magazine .hz-response__body {
  text-align: left;
  font-size: clamp(15px, 1.9vmin, 19px);
  max-width: 64ch;
  margin: 0 auto;
  padding-bottom: var(--space-4);
}

.hz-response--magazine .hz-response__body :deep(> p:first-child)::first-letter {
  font-size: 2.6em;
  float: left;
  line-height: 0.85;
  margin: 0.04em 0.12em 0 0;
  color: var(--hz-gold);
}

/* ── compact: text recedes while the stage presents ── */
.hz-response--compact {
  margin-bottom: var(--space-2);
}

.hz-response--compact .hz-response__body {
  font-size: clamp(13px, 1.5vmin, 16px);
  color: var(--hz-ink-dim);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
```

- [ ] **Step 2: Wire response + pacer + echo + TTS into `HorizonView.vue`**

a) Imports:

```ts
import HorizonResponse from '../components/horizon/HorizonResponse.vue'
import { useSentencePacer } from '../composables/horizon/useSentencePacer'
```

b) Under `/* ── ANCHOR: local-state ── */`, add:

```ts
const magazine = ref(false)

const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
```

c) Under `/* ── ANCHOR: derived ── */`, add:

```ts
const { displayed: pacedStream, reset: resetPacer } = useSentencePacer(
  computed(() => chatStore.currentStreamContent),
  computed(() => chatStore.isStreamingCurrentConversation),
  { immediate: reducedMotion },
)

/** Last completed assistant message (shown in quiet until a new turn). */
const lastResponse = computed(() => {
  const msgs = chatStore.messages
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'assistant' && msgs[i].content?.trim()) return msgs[i].content ?? ''
  }
  return ''
})

/** Last user message, echoed in small caps below the line. */
const lastUserQuery = computed(() => {
  const msgs = chatStore.messages
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'user' && msgs[i].content?.trim()) return msgs[i].content ?? ''
  }
  return ''
})

/** What the response component shows per state. */
const responseText = computed(() => {
  if (sceneState.value === 'responding') {
    // While streaming: only the paced stream (the previous answer must not
    // flash at turn start). Responding via TTS after the stream: the
    // committed message is the source of truth.
    return chatStore.isStreamingCurrentConversation ? pacedStream.value : lastResponse.value
  }
  if (sceneState.value === 'quiet' || sceneState.value === 'presenting') return lastResponse.value
  return ''
})

const showResponse = computed(
  () =>
    responseText.value !== '' &&
    (sceneState.value === 'responding' ||
      sceneState.value === 'presenting' ||
      (sceneState.value === 'quiet' && !composerActive.value)),
)
```

d) Under `/* ── ANCHOR: voice-wiring ── */`, add the lifted TTS auto-speak + new-turn reset:

```ts
// New turn: reset pacing + magazine when a fresh stream starts.
watch(
  () => chatStore.isStreamingCurrentConversation,
  (streaming, was) => {
    if (streaming && !was) {
      resetPacer()
      magazine.value = false
    }
  },
)

// Conversation switch: pacing and layout never leak across conversations.
watch(
  () => chatStore.currentConversation?.id,
  () => {
    resetPacer()
    magazine.value = false
  },
)

// TTS auto-speak when streaming completes (lifted from the legacy view).
let wasStreamingHere = false
watch(
  () => chatStore.isStreamingCurrentConversation,
  (streaming) => {
    if (streaming) {
      wasStreamingHere = true
      return
    }
    if (!wasStreamingHere) return
    wasStreamingHere = false
    if (!voiceStore.autoTtsResponse || !voiceStore.ttsAvailable || !voiceStore.connected) return
    const msgs = chatStore.messages
    let lastUserIdx = -1
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'user') {
        lastUserIdx = i
        break
      }
    }
    const allContent = msgs
      .slice(lastUserIdx + 1)
      .filter((m) => m.role === 'assistant' && m.content?.trim())
      .map((m) => m.content!.trim())
      .join('\n')
    if (allContent) speak(allContent)
  },
)
```

e) Template — in the upper zone, after the `HorizonComposer` element, add the stage-layout instance (magazine flows below the line instead — see step f):

```vue
        <HorizonResponse
          v-if="showResponse && !magazine"
          v-model:magazine="magazine"
          :text="responseText"
          :user-query="lastUserQuery"
          :compact="sceneState === 'presenting'"
        />
```

Replace the `HorizonQuiet` condition so the greeting only shows on a virgin scene:

```vue
          <HorizonQuiet v-if="sceneState === 'quiet' && !composerActive && !lastResponse" />
```

f) Template — in the lower zone, the magazine instance first (long answers read below the risen line, filling the lower zone), then the query echo, before the colophon:

```vue
        <HorizonResponse
          v-if="showResponse && magazine"
          v-model:magazine="magazine"
          :text="responseText"
          :user-query="lastUserQuery"
          :compact="sceneState === 'presenting'"
        />
        <p v-if="sceneState === 'responding' && lastUserQuery" class="horizon-view__echo">
          {{ lastUserQuery }}
        </p>
```

And pass `:magazine="magazine"` to `HorizonScene`:

```vue
    <HorizonScene :state="sceneState" :magazine="magazine" :dimmed="sceneDimmed">
```

g) Styles — add to the scoped style block:

```css
.horizon-view__echo {
  margin: var(--space-3) 0 0;
  font-family: var(--font-sans);
  font-size: 10px;
  letter-spacing: 0.3em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
  max-width: 70%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
```

- [ ] **Step 3: Verify**

Run: `npm run typecheck` — Expected: PASS.
Run: `npm run dev` → `#/horizon`: send a short question — sentences appear one at a time above the line, query echo below in small caps; with TTS available the line pulses while speaking. Send a long question ("scrivi 10 frasi su…") — the scene slides into the magazine column with a drop cap and internal scroll.

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/components/horizon/HorizonResponse.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): sentence-paced response, magazine fallback, TTS pulse"
```

---

### Task 8: `HorizonPlan` — the plan on the line

**Files:**
- Create: `src/renderer/src/components/horizon/HorizonPlan.vue`
- Modify: `src/renderer/src/views/HorizonView.vue`

- [ ] **Step 1: Create `src/renderer/src/components/horizon/HorizonPlan.vue`**

```vue
<script setup lang="ts">
/**
 * HorizonPlan — the below-line half of the mission-control: notch labels
 * aligned with the canvas ticks (shared notchPositions), the step counter,
 * and the ephemeral tool annotation. The above-line status sentence is
 * rendered by the view (it lives in the upper zone).
 */
import { computed } from 'vue'
import { notchPositions } from '../../composables/horizon/horizonScene'
import type { TaskStep } from '../../types/tasks'

const props = defineProps<{
  steps: TaskStep[]
  activeIndex: number
  completed: number
  /** Ephemeral tool-call annotation ('' = hidden). */
  annotation: string
}>()

const positions = computed(() => notchPositions(props.steps.length))

/** Short label per notch (first 2 words, ellipsized). */
function shortLabel(step: TaskStep): string {
  const words = step.step.split(/\s+/)
  return words.length <= 2 ? step.step : `${words.slice(0, 2).join(' ')}…`
}
</script>

<template>
  <div class="hz-plan">
    <div class="hz-plan__labels">
      <span
        v-for="(s, i) in steps"
        :key="i"
        class="hz-plan__label"
        :class="{
          'hz-plan__label--active': i === activeIndex,
          'hz-plan__label--done': s.status === 'completed',
        }"
        :style="{ left: `${positions[i] * 100}%` }"
        :title="s.step"
      >
        {{ shortLabel(s) }}
      </span>
    </div>
    <p class="hz-plan__counter">{{ completed }} DI {{ steps.length }}</p>
    <Transition name="hz-soft">
      <p v-if="annotation" class="hz-plan__annotation">{{ annotation }}</p>
    </Transition>
  </div>
</template>

<style scoped>
.hz-plan {
  width: 100%;
  text-align: center;
}

/* Labels share the canvas geometry: same 6% horizontal margin. */
.hz-plan__labels {
  position: relative;
  height: 18px;
  margin: 6px 6% 0;
}

.hz-plan__label {
  position: absolute;
  transform: translateX(-50%);
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
  white-space: nowrap;
  transition: color var(--hz-fade) ease;
}

.hz-plan__label--active {
  color: var(--hz-gold);
}

.hz-plan__label--done {
  opacity: 0.45;
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
</style>
```

- [ ] **Step 2: Wire it into `HorizonView.vue`**

a) Imports:

```ts
import HorizonPlan from '../components/horizon/HorizonPlan.vue'
import { planView } from '../composables/horizon/horizonScene'
```

(extend the existing `horizonScene` import instead of adding a duplicate import line)

b) Under `/* ── ANCHOR: derived ── */`, add:

```ts
const plan = computed(() => planView(planSteps.value))

/* Ephemeral tool annotation: latest active tool name, faded after 2.5 s. */
const toolAnnotation = ref('')
let annotationTimer: ReturnType<typeof setTimeout> | null = null
watch(
  () => chatStore.activeToolExecutions.map((t) => t.toolName).join(','),
  () => {
    const tools = chatStore.activeToolExecutions
    const last = tools[tools.length - 1]
    if (!last) return
    toolAnnotation.value = last.toolName
    if (annotationTimer) clearTimeout(annotationTimer)
    annotationTimer = setTimeout(() => {
      toolAnnotation.value = ''
    }, 2500)
  },
)
```

c) Pass the plan geometry to the line — replace the `<HorizonLine …/>` element with:

```vue
        <HorizonLine
          :mode="lineMode"
          :audio-level="voiceStore.audioLevel"
          :notch-count="sceneState === 'working' ? planSteps.length : 0"
          :active-index="plan.activeIndex"
          :dimmed="!isConnected"
        />
```

d) Template, upper zone — add the working status sentence after the `HorizonResponse` element:

```vue
        <p v-if="sceneState === 'working' && plan.statusSentence" class="horizon-view__status">
          <em>{{ plan.statusSentence }}</em>
        </p>
```

e) Template, lower zone — before the echo, add:

```vue
        <HorizonPlan
          v-if="sceneState === 'working' && planSteps.length > 0"
          :steps="planSteps"
          :active-index="plan.activeIndex"
          :completed="plan.completed"
          :annotation="toolAnnotation"
        />
```

f) Keep the task list fresh on conversation switches — under `/* ── ANCHOR: voice-wiring ── */` add:

```ts
watch(
  () => chatStore.currentConversation?.id,
  (id) => {
    if (id)
      tasksStore.ensureForConversation(id).catch(() => {
        /* timeline stays empty */
      })
  },
)
```

g) Styles:

```css
.horizon-view__status {
  margin: 0 0 clamp(20px, 4vh, 48px);
  font-family: var(--hz-serif);
  font-style: italic;
  font-weight: 300;
  font-size: clamp(17px, 2.4vmin, 24px);
  color: var(--hz-ink);
}
```

- [ ] **Step 3: Verify**

Run: `npm run typecheck` — Expected: PASS.
Run: `npm run dev` → `#/horizon`: ask something that triggers the agent's plan (e.g. a multi-step task with the agent plugin on). While it works: the line shows notches with mono labels, the spark eases to the active step, `N DI M` ticks under it, tool names blink in and fade. With no plan but tools running, the line shows the travelling flow packet.

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/components/horizon/HorizonPlan.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): plan timeline on the line (notches, spark, annotations)"
```

---

### Task 9: `horizonArtifacts.ts` — artifact extraction (TDD)

**Files:**
- Create: `src/renderer/src/composables/horizon/horizonArtifacts.ts`
- Test: `src/renderer/src/composables/horizon/horizonArtifacts.spec.ts`

The logic is lifted from the legacy `AssistantView.vue` computeds (`cadModels`, `chartPayloads`, `whiteboardPayloads`) into one pure, chronological, flat list. Detection rules (unchanged): CAD = JSON with `model_name` + `export_url`; chart = `chart_id` + `chart_url` + `chart_type`; whiteboard = `isWhiteboardPayload()` from `types/chat`, deduped by `board_id` keeping the **latest** payload in the **earliest** position of that board.

- [ ] **Step 1: Write the failing tests**

```ts
/** Tests for the pure artifact extraction (tool-message JSON → flat list). */
import { describe, it, expect } from 'vitest'

import { extractArtifacts } from './horizonArtifacts'

type Msg = { role: string; content: string }

const cad = (name: string): Msg => ({
  role: 'tool',
  content: JSON.stringify({ model_name: name, export_url: `/x/${name}.glb` }),
})
const chart = (id: string): Msg => ({
  role: 'tool',
  content: JSON.stringify({ chart_id: id, chart_url: `/c/${id}.json`, chart_type: 'bar' }),
})
const board = (id: string, rev: number): Msg => ({
  role: 'tool',
  content: JSON.stringify({ board_id: id, board_url: `/b/${id}`, rev }),
})

describe('extractArtifacts', () => {
  it('collects artifacts chronologically across kinds', () => {
    const out = extractArtifacts([cad('a'), chart('c1'), cad('b')])
    expect(out.map((a) => a.kind)).toEqual(['3d', 'chart', '3d'])
    expect(out[0].cad?.model_name).toBe('a')
    expect(out[1].chart?.chart_id).toBe('c1')
  })

  it('ignores non-tool roles and non-JSON content', () => {
    const out = extractArtifacts([
      { role: 'assistant', content: JSON.stringify({ model_name: 'x', export_url: 'u' }) },
      { role: 'tool', content: 'plain text' },
    ])
    expect(out).toEqual([])
  })

  it('dedupes whiteboards by board_id keeping the latest payload', () => {
    const out = extractArtifacts([board('w1', 1), chart('c1'), board('w1', 2)])
    expect(out).toHaveLength(2)
    expect(out[0].kind).toBe('whiteboard')
    expect((out[0].board as { rev?: number }).rev).toBe(2)
  })
})
```

> Note: if `isWhiteboardPayload` requires more fields than `board_id`, mirror the
> real payload shape from `types/chat.ts` in the `board()` fixture when writing
> the test — the assertion structure stays the same.

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/renderer/src/composables/horizon/horizonArtifacts.spec.ts`
Expected: FAIL — cannot resolve `./horizonArtifacts`.

- [ ] **Step 3: Implement `src/renderer/src/composables/horizon/horizonArtifacts.ts`**

```ts
/**
 * horizonArtifacts.ts — Pure extraction of presentable artifacts (3D models,
 * charts, whiteboards) from conversation tool messages. Lifted from the
 * legacy AssistantView computeds into one chronological flat list that
 * drives the Horizon stage carousel.
 */
import type { CadModelPayload, ChartPayload, WhiteboardPayload } from '../../types/chat'
import { isWhiteboardPayload } from '../../types/chat'

export type HorizonArtifactKind = '3d' | 'chart' | 'whiteboard'

export interface HorizonArtifact {
  kind: HorizonArtifactKind
  cad?: CadModelPayload
  chart?: ChartPayload
  board?: WhiteboardPayload
}

/** Minimal message shape needed for extraction (store-agnostic). */
export interface ArtifactSourceMessage {
  role: string
  content: string
}

/** Extract all artifacts in chronological order; whiteboards dedupe by board_id. */
export function extractArtifacts(messages: ArtifactSourceMessage[]): HorizonArtifact[] {
  const out: HorizonArtifact[] = []
  const boardSlots = new Map<string, number>()

  for (const msg of messages) {
    if (msg.role !== 'tool') continue
    let p: unknown
    try {
      p = JSON.parse(msg.content)
    } catch {
      continue
    }
    if (typeof p !== 'object' || p === null) continue
    const obj = p as Record<string, unknown>

    if (typeof obj.model_name === 'string' && typeof obj.export_url === 'string') {
      out.push({ kind: '3d', cad: p as CadModelPayload })
    } else if (obj.chart_id && obj.chart_url && obj.chart_type) {
      out.push({ kind: 'chart', chart: p as ChartPayload })
    } else if (isWhiteboardPayload(p)) {
      const existing = boardSlots.get(p.board_id)
      if (existing !== undefined) {
        out[existing] = { kind: 'whiteboard', board: p }
      } else {
        boardSlots.set(p.board_id, out.length)
        out.push({ kind: 'whiteboard', board: p })
      }
    }
  }
  return out
}
```

- [ ] **Step 4: Run tests to verify pass**

Run: `npx vitest run src/renderer/src/composables/horizon/horizonArtifacts.spec.ts`
Expected: PASS.

- [ ] **Step 5: Typecheck + commit**

Run: `npm run typecheck` — Expected: PASS.

```bash
git add src/renderer/src/composables/horizon/horizonArtifacts.ts src/renderer/src/composables/horizon/horizonArtifacts.spec.ts
git commit -m "feat(horizon): pure artifact extraction for the stage (TDD)"
```

---

### Task 10: `HorizonStage` — artifacts take the stage

**Files:**
- Create: `src/renderer/src/components/horizon/HorizonStage.vue`
- Modify: `src/renderer/src/views/HorizonView.vue`

- [ ] **Step 1: Create `src/renderer/src/components/horizon/HorizonStage.vue`**

```vue
<script setup lang="ts">
/**
 * HorizonStage — the presentation stage below the line: one artifact at a
 * time (3D / chart / whiteboard) with a museum caption and roman-numeral
 * navigation. Heavy viewers are lazy-loaded.
 */
import { computed, defineAsyncComponent } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import CADGenerationPlaceholder from '../chat/CADGenerationPlaceholder.vue'
import { toRoman } from '../../composables/horizon/horizonScene'
import type { HorizonArtifact } from '../../composables/horizon/horizonArtifacts'
import { api } from '../../services/api'

const ImmersiveCADCanvas = defineAsyncComponent(
  () => import('../assistant/ImmersiveCADCanvas.vue'),
)
const ChartViewer = defineAsyncComponent(() => import('../chat/ChartViewer.vue'))
const TldrawCanvas = defineAsyncComponent(() => import('../whiteboard/TldrawCanvas.vue'))

const props = defineProps<{
  artifacts: HorizonArtifact[]
  activeIndex: number
  /** Live CAD generation info (placeholder while the model bakes). */
  cadGeneration: object | null
}>()

const emit = defineEmits<{
  'update:activeIndex': [i: number]
  close: []
}>()

const active = computed(() => props.artifacts[props.activeIndex] ?? null)

const caption = computed(() => {
  if (!active.value) return ''
  const fig = `Fig. ${toRoman(props.activeIndex + 1)}`
  switch (active.value.kind) {
    case '3d':
      return `${fig} — ${active.value.cad?.model_name ?? 'modello 3D'} · trascina per ruotare`
    case 'chart':
      return `${fig} — grafico ${active.value.chart?.chart_type ?? ''}`.trim()
    case 'whiteboard':
      return `${fig} — lavagna`
  }
  return fig
})

function prev(): void {
  emit('update:activeIndex', Math.max(0, props.activeIndex - 1))
}

function next(): void {
  emit('update:activeIndex', Math.min(props.artifacts.length - 1, props.activeIndex + 1))
}

function saveBoard(boardId: string, snapshot: Record<string, unknown>): void {
  api.saveWhiteboardSnapshot(boardId, snapshot).catch(() => {
    /* best-effort, mirrors the legacy behaviour */
  })
}
</script>

<template>
  <section class="hz-stage" aria-label="Risultato">
    <div class="hz-stage__frame">
      <CADGenerationPlaceholder v-if="cadGeneration" :generation="cadGeneration" />

      <ImmersiveCADCanvas
        v-else-if="active?.kind === '3d' && active.cad"
        :models="[active.cad]"
        :active-index="0"
        @close="emit('close')"
      />

      <ChartViewer
        v-else-if="active?.kind === 'chart' && active.chart"
        :key="active.chart.chart_id"
        :payload="active.chart"
      />

      <TldrawCanvas
        v-else-if="active?.kind === 'whiteboard' && active.board"
        :key="active.board.board_id"
        :board-id="active.board.board_id"
        @change="(snap) => saveBoard(active!.board!.board_id, snap)"
      />
    </div>

    <footer class="hz-stage__footer">
      <button
        v-if="artifacts.length > 1"
        class="hz-stage__nav"
        :disabled="activeIndex <= 0"
        aria-label="Precedente"
        @click="prev"
      >
        <AppIcon name="chevron-left" :size="12" />
      </button>

      <p class="hz-stage__caption">{{ caption }}</p>

      <button
        v-if="artifacts.length > 1"
        class="hz-stage__nav"
        :disabled="activeIndex >= artifacts.length - 1"
        aria-label="Successivo"
        @click="next"
      >
        <AppIcon name="chevron-right" :size="12" />
      </button>

      <span v-if="artifacts.length > 1" class="hz-stage__counter">
        {{ toRoman(activeIndex + 1) }} / {{ toRoman(artifacts.length) }}
      </span>

      <button class="hz-stage__close" aria-label="Chiudi il palco" @click="emit('close')">
        <AppIcon name="x" :size="12" />
      </button>
    </footer>
  </section>
</template>

<style scoped>
.hz-stage {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  width: min(88%, 980px);
  padding-bottom: clamp(14px, 3vh, 28px);
}

.hz-stage__frame {
  position: relative;
  flex: 1;
  min-height: 0;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  background: var(--surface-1);
}

.hz-stage__footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding-top: var(--space-2);
}

.hz-stage__caption {
  margin: 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: var(--hz-ink-faint);
}

.hz-stage__counter {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.2em;
  color: var(--hz-ink-faint);
}

.hz-stage__nav,
.hz-stage__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--hz-ink-dim);
  cursor: pointer;
}

.hz-stage__nav:hover:not(:disabled),
.hz-stage__close:hover {
  color: var(--hz-ink);
  background: var(--surface-2);
}

.hz-stage__nav:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}
</style>
```

- [ ] **Step 2: Wire the stage into `HorizonView.vue`**

a) Imports:

```ts
import HorizonStage from '../components/horizon/HorizonStage.vue'
import { extractArtifacts } from '../composables/horizon/horizonArtifacts'
import { useGenerationState } from '../composables/useGenerationState'
```

b) After the `useVoice()` destructuring, add:

```ts
const { cadGenerationInProgress } = useGenerationState()
```

c) Under `/* ── ANCHOR: local-state ── */`, add:

```ts
const stageIndex = ref(0)
```

d) Under `/* ── ANCHOR: derived ── */`, REPLACE the placeholder `artifactCount` computed with:

```ts
const artifacts = computed(() => extractArtifacts(chatStore.messages))
const artifactCount = computed(
  () => artifacts.value.length + (cadGenerationInProgress.value ? 1 : 0),
)

// Auto-open the stage on a new artifact; jump to it.
watch(
  () => artifacts.value.length,
  (len, was) => {
    if (len > (was ?? 0)) {
      stageOpen.value = true
      stageIndex.value = len - 1
    } else if (stageIndex.value >= len) {
      stageIndex.value = Math.max(0, len - 1)
    }
  },
)

// CAD generation surfaces the stage immediately (placeholder).
watch(cadGenerationInProgress, (info) => {
  if (info) stageOpen.value = true
})
```

e) Template, lower zone — add the stage before the colophon:

```vue
        <HorizonStage
          v-if="sceneState === 'presenting'"
          v-model:active-index="stageIndex"
          :artifacts="artifacts"
          :cad-generation="cadGenerationInProgress"
          @close="stageOpen = false"
        />
```

(The presenting state requires `artifactCount > 0`; the cad placeholder counts via `artifactCount`. When only the generation is in flight, `artifacts` is empty and the stage renders the placeholder alone.)

- [ ] **Step 3: Verify**

Run: `npm run typecheck` — Expected: PASS.
Run: `npm run dev` → `#/horizon`: ask for a chart ("disegna un grafico a barre di…"). When the payload lands, the scene morphs: line rises to 26%, text recedes compact, the chart takes the stage with `Fig. I — grafico bar`. Esc (or ✕) closes the stage and the scene settles back. Multiple artifacts navigate with ‹ › and roman numerals.

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/components/horizon/HorizonStage.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): presentation stage for 3D/chart/whiteboard artifacts"
```

---

### Task 11: `HorizonHistory`, corner affordances, dialogs

**Files:**
- Create: `src/renderer/src/components/horizon/HorizonHistory.vue`
- Modify: `src/renderer/src/views/HorizonView.vue`

- [ ] **Step 1: Create `src/renderer/src/components/horizon/HorizonHistory.vue`**

```vue
<script setup lang="ts">
/**
 * HorizonHistory — the conversation record as an editorial dossier: a left
 * drawer with role rubrics in mono, serif bodies, hairline rules. Mirrors
 * the legacy ConversationDrawer contract (same props/emits) so the view
 * wiring is a drop-in.
 */
import { renderMarkdown } from '../../composables/useMarkdown'
import MessageVersionNav from '../chat/MessageVersionNav.vue'
import AppIcon from '../ui/AppIcon.vue'
import type { Message } from '../../types/chat'

defineProps<{
  open: boolean
  messages: Message[]
  isStreaming: boolean
  branchDisabled: boolean
  getVersionCount: (groupId: string) => number
  getActiveVersionIndex: (groupId: string) => number
}>()

const emit = defineEmits<{
  close: []
  edit: [messageId: string]
  switchVersion: [groupId: string, index: number]
  branch: [messageId: string]
}>()

const ROLE_LABELS: Record<string, string> = {
  user: 'TU',
  assistant: 'AL\\CE',
  tool: 'STRUMENTO',
  system: 'SISTEMA',
}
</script>

<template>
  <Transition name="hz-drawer">
    <aside v-if="open" class="hz-history" aria-label="Conversazione">
      <header class="hz-history__head">
        <span class="hz-history__title">Conversazione</span>
        <button class="hz-history__close" aria-label="Chiudi" @click="emit('close')">
          <AppIcon name="x" :size="13" />
        </button>
      </header>

      <div class="hz-history__scroll">
        <article v-for="msg in messages" :key="msg.id" class="hz-history__entry">
          <div class="hz-history__rubric">
            <span class="hz-history__role">{{ ROLE_LABELS[msg.role] ?? msg.role }}</span>
            <span class="hz-history__entry-actions">
              <button
                v-if="msg.role === 'user' && !isStreaming"
                class="hz-history__action"
                title="Modifica"
                @click="emit('edit', msg.id)"
              >
                <AppIcon name="edit" :size="11" />
              </button>
              <button
                v-if="msg.role === 'assistant' && !branchDisabled"
                class="hz-history__action"
                title="Crea ramo"
                @click="emit('branch', msg.id)"
              >
                <AppIcon name="branch" :size="11" />
              </button>
            </span>
          </div>

          <!-- eslint-disable-next-line vue/no-v-html -->
          <div class="hz-history__body" v-html="renderMarkdown(msg.content ?? '')" />

          <MessageVersionNav
            v-if="msg.version_group_id && getVersionCount(msg.version_group_id) > 1"
            :version-count="getVersionCount(msg.version_group_id)"
            :active-index="getActiveVersionIndex(msg.version_group_id)"
            @switch="(i) => emit('switchVersion', msg.version_group_id!, i)"
          />
        </article>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.hz-history {
  position: absolute;
  top: 0;
  left: 0;
  bottom: 0;
  width: min(420px, 86vw);
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  z-index: var(--z-overlay);
}

.hz-history__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border);
}

.hz-history__title {
  font-family: var(--hz-serif);
  font-size: var(--text-base);
  font-weight: 300;
  color: var(--hz-ink);
}

.hz-history__close {
  display: inline-flex;
  border: none;
  background: transparent;
  color: var(--hz-ink-dim);
  cursor: pointer;
}

.hz-history__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3) var(--space-4);
  scrollbar-width: thin;
}

.hz-history__entry {
  padding: var(--space-3) 0;
  border-bottom: 1px solid var(--border);
}

.hz-history__rubric {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-1-5);
}

.hz-history__role {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.3em;
  color: var(--hz-gold);
}

.hz-history__entry-actions {
  display: inline-flex;
  gap: var(--space-1);
}

.hz-history__action {
  display: inline-flex;
  border: none;
  background: transparent;
  color: var(--hz-ink-faint);
  cursor: pointer;
}

.hz-history__action:hover {
  color: var(--hz-ink);
}

.hz-history__body {
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: var(--text-sm);
  line-height: 1.65;
  color: var(--hz-ink-dim);
  overflow-wrap: anywhere;
}

.hz-history__body :deep(p) {
  margin: 0 0 0.5em;
}

.hz-history__body :deep(pre),
.hz-history__body :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.8em;
}

.hz-drawer-enter-active,
.hz-drawer-leave-active {
  transition: transform var(--hz-fade) var(--ease-out-expo);
}

.hz-drawer-enter-from,
.hz-drawer-leave-to {
  transform: translateX(-100%);
}
</style>
```

> If the icon names `edit` / `branch` are missing from `assets/icons.ts`, check the registry
> for the names used by `ConversationDrawer.vue` / `MessageBubble.vue` (e.g. `pencil`,
> `git-branch`) and use those instead — do not add new icons for this. Likewise, before
> deleting `ConversationDrawer.vue` mirror its exact `MessageVersionNav` prop/emit names
> here — the names above (`version-count`, `active-index`, `@switch`) must be corrected to
> whatever the legacy drawer actually passes.

- [ ] **Step 2: Wire history, corners and dialogs into `HorizonView.vue`**

a) Imports:

```ts
import HorizonHistory from '../components/horizon/HorizonHistory.vue'
import ToolConfirmationDialog from '../components/chat/ToolConfirmationDialog.vue'
import AskUserPrompt from '../components/chat/AskUserPrompt.vue'
import MessageEditDialog from '../components/chat/MessageEditDialog.vue'
import { useModal } from '../composables/useModal'
```

b) After the `chatApi` destructuring block, add:

```ts
const editMessage = chatApi?.editMessage ?? _asyncNoop
const { openCustom } = useModal()
```

c) Under `/* ── ANCHOR: local-state ── */`, add:

```ts
const historyOpen = ref(false)
```

d) Under `/* ── ANCHOR: interactions ── */`, add (lifted from the legacy view):

```ts
async function startEdit(messageId: string): Promise<void> {
  if (chatStore.isStreamingCurrentConversation) return
  const msg = chatStore.messages.find((m) => m.id === messageId)
  if (!msg || msg.role !== 'user') return
  await openCustom({
    component: MessageEditDialog,
    props: {
      originalContent: msg.content,
      onSubmit: async (newContent: string) => {
        await editMessage(messageId, newContent)
      },
    },
    width: '560px',
  })
}

function handleVersionSwitch(versionGroupId: string, versionIndex: number): void {
  chatStore.switchVersion(versionGroupId, versionIndex)
}

async function handleBranch(messageId: string): Promise<void> {
  if (chatStore.isStreamingCurrentConversation) return
  await chatStore.branchConversation(messageId)
}
```

e) Template — replace the `<!-- ANCHOR: overlays -->` comment with:

```vue
    <!-- ANCHOR: overlays -->
    <nav class="horizon-view__corner" aria-label="Navigazione">
      <button class="horizon-view__affordance" @click="historyOpen = !historyOpen">STORIA</button>
      <RouterLink class="horizon-view__affordance" :to="{ name: 'workspace' }">
        WORKSPACE
      </RouterLink>
    </nav>

    <HorizonHistory
      :open="historyOpen"
      :messages="chatStore.messages"
      :is-streaming="chatStore.isStreamingCurrentConversation"
      :branch-disabled="chatStore.isStreamingCurrentConversation"
      :get-version-count="chatStore.getVersionCount"
      :get-active-version-index="chatStore.getActiveVersionIndex"
      @close="historyOpen = false"
      @edit="startEdit"
      @switch-version="handleVersionSwitch"
      @branch="handleBranch"
    />

    <ToolConfirmationDialog
      v-if="pendingConfirmationsList.length > 0"
      :key="pendingConfirmationsList[0].executionId"
      :confirmation="pendingConfirmationsList[0]"
      @respond="respondToConfirmation"
    />
```

f) Template — in the lower zone, before the colophon, add the ask-user prompts:

```vue
        <AskUserPrompt
          v-for="r in pendingAskUserList"
          :key="r.executionId"
          :request="r"
          @answer="answerAskUser"
        />
```

g) `RouterLink` import:

```ts
import { RouterLink } from 'vue-router'
```

h) Styles:

```css
.horizon-view__corner {
  position: absolute;
  right: clamp(16px, 3vw, 32px);
  bottom: clamp(14px, 3vh, 28px);
  display: flex;
  gap: var(--space-4);
  z-index: var(--z-sticky);
}

.horizon-view__affordance {
  border: none;
  background: transparent;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: var(--hz-ink-faint);
  text-decoration: none;
  cursor: pointer;
  transition: color var(--hz-fade) ease;
}

.horizon-view__affordance:hover {
  color: var(--hz-ink);
}
```

- [ ] **Step 3: Verify**

Run: `npm run typecheck` — Expected: PASS.
Run: `npm run dev` → `#/horizon`: STORIA opens the dossier drawer (rubrics in mono gold, serif bodies; edit/branch work); WORKSPACE navigates back; a tool confirmation dims the scene behind the dialog; ask_user prompts render above the colophon.

- [ ] **Step 4: Commit**

```bash
git add src/renderer/src/components/horizon/HorizonHistory.vue src/renderer/src/views/HorizonView.vue
git commit -m "feat(horizon): dossier history drawer, corner affordances, dialog dimming"
```

---

### Task 12: Route flip + demolition

**Files:**
- Modify: `src/renderer/src/router/index.ts`
- Delete: `src/renderer/src/views/AssistantView.vue`
- Delete: `src/renderer/src/components/assistant/AliceOrb.vue`
- Delete: `src/renderer/src/components/assistant/veil-orb/` (whole directory)
- Delete: `src/renderer/src/components/assistant/AmbientBackground.vue`
- Delete: `src/renderer/src/components/assistant/AssistantFab.vue`
- Delete: `src/renderer/src/components/assistant/AssistantTranscript.vue`
- Delete: `src/renderer/src/components/assistant/AssistantResponse.vue`
- Delete: `src/renderer/src/components/assistant/ConversationDrawer.vue`

`ImmersiveCADCanvas.vue` **stays** in `components/assistant/` (reused by the stage).

- [ ] **Step 1: Flip the route**

In `router/index.ts`, change the `'assistant'` route to:

```ts
    {
      path: '/assistant',
      name: 'assistant',
      component: () => import('../views/HorizonView.vue'),
      meta: { title: 'Assistente', transition: DEFAULT_PAGE_TRANSITION }
    },
```

and DELETE the temporary `'/horizon'` route block entirely.

- [ ] **Step 2: Delete the legacy files**

```powershell
Remove-Item src/renderer/src/views/AssistantView.vue
Remove-Item -Recurse src/renderer/src/components/assistant/veil-orb
Remove-Item src/renderer/src/components/assistant/AliceOrb.vue, src/renderer/src/components/assistant/AmbientBackground.vue, src/renderer/src/components/assistant/AssistantFab.vue, src/renderer/src/components/assistant/AssistantTranscript.vue, src/renderer/src/components/assistant/AssistantResponse.vue, src/renderer/src/components/assistant/ConversationDrawer.vue
```

- [ ] **Step 3: Reference sweep — every name must come back with zero hits outside docs**

```powershell
Get-ChildItem src -Recurse -Include *.ts,*.vue | Select-String -Pattern "AssistantView|AliceOrb|veil-orb|AmbientBackground|AssistantFab|AssistantTranscript|AssistantResponse|ConversationDrawer|horizon-dev|OrbState"
```

Expected: no output. If anything matches (e.g. a stale import, a test, `ws.ts` typings), fix the reference — do not leave dead imports.

- [ ] **Step 4: Full gates**

Run: `npx vitest run` — Expected: PASS (all suites, including the three horizon specs).
Run: `npm run typecheck` — Expected: PASS.
Run: `npx eslint src/renderer/src/components/horizon src/renderer/src/views/HorizonView.vue src/renderer/src/composables/horizon` — Expected: 0 errors (warnings = repo CRLF baseline only).

- [ ] **Step 5: Manual smoke (the five states)**

`npm run dev` → `#/assistant`:
1. quiet (greeting/colophon), 2. click → listening (tense line), 3. send text → responding (paced serif), 4. agent task → working (timeline + spark), 5. chart/3D → presenting (stage). Esc chain works; theme switch keeps the scene native; `prefers-reduced-motion` (DevTools emulation) gives a static line with instant text.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(horizon)!: assistant route now renders Horizon; retire orb-era components"
```

---

### Task 13: Final review hand-back

- [ ] **Step 1:** Re-read the spec (`docs/superpowers/specs/2026-06-10-horizon-assistant-mode-design.md`) section by section and confirm each shipped: states §3 (all five + degradations), components §4 (all eleven modules), visual language §5 (tokens/aliases, bundled fonts), §6 performance (single rAF, visibility pause), §7 removal list (sweep clean), §8 tests (three specs green).
- [ ] **Step 2:** Run the full gate one last time: `npx vitest run && npm run typecheck` — Expected: PASS + PASS.
- [ ] **Step 3:** Use superpowers:requesting-code-review to dispatch a code review of the branch diff before merging.
