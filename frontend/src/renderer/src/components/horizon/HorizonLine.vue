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
    /** State microlabel at the line's right end ('' = hidden). */
    label?: string
    /** Flatten + fade the line (stage presenting). */
    attenuated?: boolean
    /** Notches drawn as completed (first N). */
    completedCount?: number
  }>(),
  {
    audioLevel: 0,
    notchCount: 0,
    activeIndex: -1,
    dimmed: false,
    label: '',
    attenuated: false,
    completedCount: 0
  }
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
/** Mode rendered on the previous frame (detects timeline entry). */
let lastMode: HorizonLineMode | null = null
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
  const alpha = (props.dimmed ? 0.35 : 1) * (props.attenuated ? 0.55 : 1)

  // Clamp to [0.06, 1]: a NaN or out-of-range level would poison the
  // exponential smoother permanently (NaN never decays back).
  const safeLevel = Number.isFinite(props.audioLevel) ? props.audioLevel : 0
  const targetLevel = props.mode === 'tense' ? Math.min(1, Math.max(safeLevel, 0.06)) : 0
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
        y = cy + Math.sin(t * 0.7 + f * Math.PI) * (props.attenuated ? 0.5 : 1.5) * env
      } else if (props.mode === 'tense') {
        // Stronger audio response, biased upward: the crest visibly lifts.
        y =
          cy +
          env *
            levelSmooth *
            28 *
            (Math.sin(f * 26 + t * 9) * 0.6 + Math.sin(f * 53 - t * 13) * 0.4) -
          env * levelSmooth * 8
      } else if (props.mode === 'pulse') {
        y = cy + Math.sin(t * 2.2 + f * Math.PI * 2) * 1.2 * env
      }
    }
    if (s === 0) ctx.moveTo(x, y)
    else ctx.lineTo(x, y)
  }
  ctx.stroke()
  ctx.restore()

  /* ── pulse: one crest travelling left→right with trailing echoes (TTS) ── */
  if (props.mode === 'pulse' && !reducedMotion) {
    const phase = (t * 0.45) % 1
    const x = margin + phase * span
    ctx.save()
    ctx.fillStyle = `rgba(${lineRgb}, 0.95)`
    ctx.shadowColor = `rgba(${lineRgb}, 0.8)`
    ctx.shadowBlur = 10
    for (let e = 0; e < 3; e++) {
      const ex = x - e * 14
      if (ex < margin) continue
      ctx.globalAlpha = alpha * (0.8 - e * 0.28)
      ctx.fillRect(ex - 1.5, cy - 1.1, 3, 2.2)
    }
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

  /* ── notches (any mode) + spark (timeline only) ── */
  if (props.notchCount > 0) {
    const fractions = notchPositions(props.notchCount)
    const offMode = props.mode !== 'timeline'
    ctx.save()
    // Outside the working timeline (pinned plan) the ticks stay faint.
    ctx.globalAlpha = alpha * (offMode ? 0.5 : 1)
    fractions.forEach((p, i) => {
      const x = margin + p * span
      const active = i === props.activeIndex
      const done = !active && i < props.completedCount
      const a = active ? 1 : done ? 0.9 : 0.25
      const h = active ? 9 : done ? 8 : 5
      ctx!.strokeStyle = `rgba(${lineRgb}, ${a})`
      ctx!.lineWidth = active ? 1.4 : 1
      ctx!.beginPath()
      ctx!.moveTo(x, cy - h)
      ctx!.lineTo(x, cy + h)
      ctx!.stroke()
    })
    if (props.mode === 'timeline') {
      const clamped = Math.max(0, Math.min(props.activeIndex, fractions.length - 1))
      const target = fractions[clamped] ?? 0.5
      // Entering timeline (a NEW plan): snap to the active step — easing is
      // for within-plan motion, not for gliding from a previous plan's notch.
      if (lastMode !== 'timeline') sparkX = target
      sparkX += (target - sparkX) * (reducedMotion ? 1 : 0.06)
      const sx = margin + sparkX * span
      const breathe = reducedMotion ? 1 : 0.75 + Math.sin(t * 3) * 0.25
      const g = ctx.createRadialGradient(sx, cy, 0, sx, cy, 11)
      g.addColorStop(0, `rgba(${lineRgb}, ${0.95 * breathe})`)
      g.addColorStop(1, `rgba(${lineRgb}, 0)`)
      ctx.fillStyle = g
      ctx.fillRect(sx - 11, cy - 11, 22, 22)
    }
    ctx.restore()
  }

  lastMode = props.mode
}

/* TODO(spec §6): suspend the rAF loop once the breathe mode has settled
   (on-demand redraw, zero idle work) — tracked for the final-review pass. */
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

/* Reduced-motion: redraw once whenever any visual input changes. */
watch(
  () => [
    props.mode,
    props.audioLevel,
    props.notchCount,
    props.activeIndex,
    props.dimmed,
    props.label,
    props.attenuated,
    props.completedCount
  ],
  () => {
    if (reducedMotion) draw(performance.now())
  }
)
</script>

<template>
  <div class="hz-line" aria-hidden="true">
    <canvas ref="canvasRef" class="hz-line__canvas" />
    <Transition name="hz-line-fade">
      <span v-if="label" :key="label" class="hz-line__label">{{ label }}</span>
    </Transition>
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

/* State microlabel at the right end of the line. */
.hz-line__label {
  position: absolute;
  right: 6%;
  bottom: calc(50% + 10px);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: var(--hz-ink-faint);
  user-select: none;
}

.hz-line-fade-enter-active,
.hz-line-fade-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-line-fade-enter-from,
.hz-line-fade-leave-to {
  opacity: 0;
}
</style>
