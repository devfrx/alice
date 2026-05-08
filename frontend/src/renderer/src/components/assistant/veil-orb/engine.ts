/**
 * VeilEngine — silk-veil canvas renderer for AL\CE.
 *
 * Conceptually replaces a glowing orb with a restrained glass lens: a stable
 * Continuum aperture containing a faint silk fold signature and a pearl core.
 * Each AL\CE state owns its own *mechanic*:
 *
 *   idle        slow architectural drift, almost no ambient debris
 *   listening   restrained red edge pressure + audio membrane
 *   thinking    slow perimeter orbits + fold tightening
 *   speaking    warm radial bloom + motes rising from the core
 *   processing  milky prism caustics + soft refraction
 *
 * Transitions are layered:
 *   1. exponentially smoothed config interpolation (no snapping),
 *   2. a destination-specific "flourish" enqueued on every state change.
 *
 * External hooks:
 *   triggerClick()    → radial shock through the veils
 *   triggerToolCall() → stitched glyph traverses one sheet
 *   triggerToken()    → spawns a single rising mote (streaming heartbeat)
 *   triggerDone()     → quiet completion seal
 *
 * Pure 2D canvas. ~60fps with 3-4 sheets, sparse accents.
 */
import type {
    Flourish,
    FlourishKind,
    Mote,
    OrbState,
    RGB,
    VeilStateConfig,
} from './types'
import { STATE_CONFIGS, TRANSITION_CONFIGS } from './config'

const TAU = Math.PI * 2

/* ── Smoothing helpers ────────────────────────────────────── */

function smoothFactor(dt: number, halfLife: number): number {
    if (halfLife <= 0) return 1
    return 1 - Math.exp((-Math.LN2 * dt) / halfLife)
}
function smoothNum(current: number, target: number, k: number): number {
    return current + (target - current) * k
}
function smoothRGB(current: RGB, target: RGB, k: number): RGB {
    return [
        smoothNum(current[0], target[0], k),
        smoothNum(current[1], target[1], k),
        smoothNum(current[2], target[2], k),
    ]
}
function smoothConfig(
    current: VeilStateConfig,
    target: VeilStateConfig,
    k: number,
): VeilStateConfig {
    const s = (a: number, b: number): number => smoothNum(a, b, k)
    const c = (a: RGB, b: RGB): RGB => smoothRGB(a, b, k)
    return {
        silkPrimary: c(current.silkPrimary, target.silkPrimary),
        silkAccent: c(current.silkAccent, target.silkAccent),
        warmLight: c(current.warmLight, target.warmLight),
        coolLight: c(current.coolLight, target.coolLight),
        driftAmp: s(current.driftAmp, target.driftAmp),
        driftSpeed: s(current.driftSpeed, target.driftSpeed),
        warpAmp: s(current.warpAmp, target.warpAmp),
        warpFreq: s(current.warpFreq, target.warpFreq),
        warpSpeed: s(current.warpSpeed, target.warpSpeed),
        twistAmount: s(current.twistAmount, target.twistAmount),
        breath: s(current.breath, target.breath),
        breathSpeed: s(current.breathSpeed, target.breathSpeed),
        sheetCount: s(current.sheetCount, target.sheetCount),
        sheetOpacity: s(current.sheetOpacity, target.sheetOpacity),
        rimLight: s(current.rimLight, target.rimLight),
        coreIntensity: s(current.coreIntensity, target.coreIntensity),
        coreSize: s(current.coreSize, target.coreSize),
        shaftIntensity: s(current.shaftIntensity, target.shaftIntensity),
        shaftWidth: s(current.shaftWidth, target.shaftWidth),
        haloIntensity: s(current.haloIntensity, target.haloIntensity),
        moteCount: s(current.moteCount, target.moteCount),
        moteDirection: target.moteDirection,
        moteSpeed: s(current.moteSpeed, target.moteSpeed),
        audioWave: s(current.audioWave, target.audioWave),
        weave: s(current.weave, target.weave),
        prism: s(current.prism, target.prism),
        bloom: s(current.bloom, target.bloom),
        audioReactivity: s(current.audioReactivity, target.audioReactivity),
        energy: s(current.energy, target.energy),
        veilSpread: s(current.veilSpread, target.veilSpread),
    }
}

function rgba(c: RGB, a: number): string {
    return `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`
}
function clamp01(v: number): number {
    return v < 0 ? 0 : v > 1 ? 1 : v
}
function easeOutCubic(t: number): number {
    const u = 1 - t
    return 1 - u * u * u
}
function easeInOut(t: number): number {
    return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2
}
function gaussian(x: number, center: number, width: number): number {
    const d = (x - center) / width
    return Math.exp(-d * d)
}

/** Maps hue t ∈ [0,1) to a full-spectrum RGB tuple. */
function hueRGB(t: number): RGB {
    const h6 = ((t % 1 + 1) % 1) * 6
    const f = h6 % 1
    switch (Math.floor(h6)) {
        case 0: return [255, Math.round(255 * f), 0]
        case 1: return [Math.round(255 * (1 - f)), 255, 0]
        case 2: return [0, 255, Math.round(255 * f)]
        case 3: return [0, Math.round(255 * (1 - f)), 255]
        case 4: return [Math.round(255 * f), 0, 255]
        default: return [255, 0, Math.round(255 * (1 - f))]
    }
}

/* Small deterministic hash so per-sheet randomness stays stable across frames. */
function hashPhase(i: number): number {
    const s = Math.sin(i * 12.9898 + 78.233) * 43758.5453
    return (s - Math.floor(s)) * TAU
}

/* ── Engine ──────────────────────────────────────────────── */

const TRANSITION_FLOURISH: Record<OrbState, FlourishKind> = {
    idle: 'settle',
    listening: 'ripple',
    thinking: 'twist',
    speaking: 'bloom',
    processing: 'prism',
}

export class VeilEngine {
    private canvas!: HTMLCanvasElement
    private ctx!: CanvasRenderingContext2D
    private dpr = 1
    private width = 0
    private height = 0
    private cx = 0
    private cy = 0

    private state: OrbState = 'idle'
    private targetConfig: VeilStateConfig = { ...STATE_CONFIGS.idle }
    private currentConfig: VeilStateConfig = { ...STATE_CONFIGS.idle }
    private transitionHalfLife = 0.35

    private hoverTarget = 0
    private hoverT = 0

    private audioLevel = 0
    private smoothAudio = 0

    private compact: boolean
    private time = 0
    private warpPhase = 0
    private breathPhase = 0
    private driftPhase = 0
    private animId = 0
    private lastFrame = 0
    private resizeObs: ResizeObserver | null = null

    private motes: Mote[] = []
    private flourishes: Flourish[] = []
    /** Pending mote spawns from triggerToken; flushed in update. */
    private pendingTokenMotes = 0
    /** Tool-call flag — pulses a glyph through the veils. */
    private pendingGlyphs = 0

    constructor(compact: boolean) {
        this.compact = compact
    }

    /* ── Public API ────────────────────────────────────────── */

    init(canvas: HTMLCanvasElement): void {
        this.canvas = canvas
        this.ctx = canvas.getContext('2d')!
        this.dpr = Math.min(window.devicePixelRatio || 1, 2)
        this.resize()
        this.lastFrame = performance.now()

        const parent = canvas.parentElement
        if (parent) {
            this.resizeObs = new ResizeObserver(() => this.resize())
            this.resizeObs.observe(parent)
        }
        this.loop()
    }

    destroy(): void {
        if (this.animId) cancelAnimationFrame(this.animId)
        this.resizeObs?.disconnect()
        this.resizeObs = null
        this.animId = 0
    }

    setState(newState: OrbState): void {
        if (newState === this.state) return
        this.state = newState
        this.targetConfig = STATE_CONFIGS[newState]
        const tc = TRANSITION_CONFIGS[newState]
        this.transitionHalfLife = tc.duration * 0.32
        this.enqueueFlourish(TRANSITION_FLOURISH[newState], tc.duration, 1)
    }

    setAudioLevel(level: number): void {
        this.audioLevel = level
    }

    setHover(hovered: boolean): void {
        this.hoverTarget = hovered ? 1 : 0
    }

    triggerClick(): void {
        this.enqueueFlourish('shock', 0.9, 1)
    }

    triggerToolCall(): void {
        this.pendingGlyphs += 1
    }

    triggerToken(): void {
        this.pendingTokenMotes += 1
    }

    triggerDone(): void {
        this.enqueueFlourish('settle', 1.05, 0.9)
        this.enqueueFlourish('bloom', 0.72, 0.35)
    }

    /* ── Lifecycle ─────────────────────────────────────────── */

    private resize(): void {
        const parent = this.canvas.parentElement
        if (!parent) return
        const rect = this.canvas.getBoundingClientRect()
        this.width = rect.width
        this.height = rect.height
        this.canvas.width = this.width * this.dpr
        this.canvas.height = this.height * this.dpr
        this.cx = this.width / 2
        this.cy = this.height / 2
    }

    private isLightTheme(): boolean {
        return document.documentElement.getAttribute('data-theme') === 'light'
    }

    private loop = (): void => {
        const now = performance.now()
        const dt = Math.min((now - this.lastFrame) / 1000, 0.1)
        this.lastFrame = now
        this.time += dt

        this.update(dt)
        this.render()

        this.animId = requestAnimationFrame(this.loop)
    }

    /* ── Update ────────────────────────────────────────────── */

    private update(dt: number): void {
        this.smoothAudio = smoothNum(
            this.smoothAudio,
            this.audioLevel,
            smoothFactor(dt, 0.06),
        )
        this.hoverT = smoothNum(
            this.hoverT,
            this.hoverTarget,
            smoothFactor(dt, 0.12),
        )
        this.currentConfig = smoothConfig(
            this.currentConfig,
            this.targetConfig,
            smoothFactor(dt, this.transitionHalfLife),
        )

        this.warpPhase += this.currentConfig.warpSpeed * dt
        this.breathPhase += this.currentConfig.breathSpeed * dt
        this.driftPhase += this.currentConfig.driftSpeed * dt

        /* Flush queued tool-call glyphs. */
        while (this.pendingGlyphs > 0) {
            this.pendingGlyphs -= 1
            this.enqueueFlourish('glyph', 1.6, 1, 0.35 + Math.random() * 0.3)
        }

        /* Flush queued streaming-token motes. */
        while (this.pendingTokenMotes > 0) {
            this.pendingTokenMotes -= 1
            this.spawnMote(1, true)
        }

        this.updateFlourishes(dt)
        this.updateMotes(dt)
    }

    private enqueueFlourish(
        kind: FlourishKind,
        duration: number,
        intensity: number,
        anchorY?: number,
    ): void {
        this.flourishes.push({
            kind,
            progress: 0,
            duration,
            intensity,
            anchorY,
        })
    }

    private updateFlourishes(dt: number): void {
        for (let i = this.flourishes.length - 1; i >= 0; i--) {
            const f = this.flourishes[i]
            f.progress += dt / f.duration
            if (f.progress >= 1) this.flourishes.splice(i, 1)
        }
    }

    private updateMotes(dt: number): void {
        const cfg = this.currentConfig
        const compactMul = this.compact ? 0.6 : 1
        const target = Math.round(cfg.moteCount * compactMul)

        while (this.motes.length < target) this.spawnMote(cfg.moteDirection, false)
        if (this.motes.length > target + 4) {
            this.motes.splice(0, this.motes.length - target)
        }

        const vScale = cfg.moteSpeed * (1 + this.hoverT * 0.4)
        const r = this.bodyRadius()
        const h = this.bodyHeight()

        for (let i = this.motes.length - 1; i >= 0; i--) {
            const m = this.motes[i]
            m.life += dt
            const sway = Math.sin(this.time * 0.7 + m.phase) * 0.22
            m.x += (m.vx + sway * 4) * vScale * dt
            m.y += m.vy * vScale * dt

            const outOfBounds =
                m.x < this.cx - r * 0.95 ||
                m.x > this.cx + r * 0.95 ||
                m.y < this.cy - h * 0.58 ||
                m.y > this.cy + h * 0.58 ||
                m.life > m.maxLife
            if (outOfBounds) this.motes.splice(i, 1)
        }
    }

    private spawnMote(direction: -1 | 0 | 1, fromCore: boolean): void {
        const r = this.bodyRadius()
        const h = this.bodyHeight()
        const angle = Math.random() * TAU
        const radius = fromCore ? r * 0.04 : r * (0.20 + Math.random() * 0.42)
        const x = fromCore ? this.cx + Math.cos(angle) * radius : this.cx + (Math.random() - 0.5) * r * 1.15
        let y: number
        let vy: number
        if (direction === -1) {
            y = this.cy - h * 0.42 + Math.random() * 4
            vy = 10 + Math.random() * 12
        } else if (direction === 1) {
            y = fromCore ? this.cy : this.cy + h * 0.42 - Math.random() * 4
            vy = -(18 + Math.random() * 24)
        } else {
            y = this.cy + (Math.random() - 0.5) * h * 0.58
            vy = (Math.random() - 0.5) * 16
        }
        this.motes.push({
            x,
            y,
            vx: (Math.random() - 0.5) * 6,
            vy,
            size: 0.45 + Math.random() * 0.85,
            phase: Math.random() * TAU,
            life: 0,
            maxLife: 3.2 + Math.random() * 3.2,
        })
    }

    /* ── Geometry helpers ──────────────────────────────────── */

    private bodyRadius(): number {
        return Math.min(this.width, this.height) * (this.compact ? 0.265 : 0.292)
    }
    private bodyHeight(): number {
        return this.bodyRadius() * 1.28
    }

    private lensBounds(scale = 1): { rx: number; ry: number } {
        const radius = this.bodyRadius()
        return {
            rx: radius * 0.94 * scale,
            ry: radius * 0.64 * scale,
        }
    }

    private createLensPath(scale = 1): Path2D {
        const { rx, ry } = this.lensBounds(scale)
        const path = new Path2D()
        const exponent = 3.8
        const pointCount = 96

        for (let pointIndex = 0; pointIndex <= pointCount; pointIndex++) {
            const angle = (pointIndex / pointCount) * TAU
            const cosine = Math.cos(angle)
            const sine = Math.sin(angle)
            const x = this.cx + Math.sign(cosine) * Math.pow(Math.abs(cosine), 2 / exponent) * rx
            const y = this.cy + Math.sign(sine) * Math.pow(Math.abs(sine), 2 / exponent) * ry
            if (pointIndex === 0) path.moveTo(x, y)
            else path.lineTo(x, y)
        }
        path.closePath()
        return path
    }

    private lensPoint(progress: number, scale = 1): { x: number; y: number } {
        const { rx, ry } = this.lensBounds(scale)
        const exponent = 3.8
        const angle = progress * TAU
        const cosine = Math.cos(angle)
        const sine = Math.sin(angle)
        return {
            x: this.cx + Math.sign(cosine) * Math.pow(Math.abs(cosine), 2 / exponent) * rx,
            y: this.cy + Math.sign(sine) * Math.pow(Math.abs(sine), 2 / exponent) * ry,
        }
    }

    private strokeLensArc(
        start: number,
        length: number,
        scale: number,
        strokeStyle: string,
        lineWidth: number,
    ): void {
        const ctx = this.ctx
        const segmentCount = 36
        ctx.strokeStyle = strokeStyle
        ctx.lineWidth = lineWidth
        ctx.beginPath()
        for (let segmentIndex = 0; segmentIndex <= segmentCount; segmentIndex++) {
            const progress = start + (length * segmentIndex) / segmentCount
            const point = this.lensPoint(progress, scale)
            if (segmentIndex === 0) ctx.moveTo(point.x, point.y)
            else ctx.lineTo(point.x, point.y)
        }
        ctx.stroke()
    }

    /* ── Rendering ─────────────────────────────────────────── */

    private render(): void {
        const ctx = this.ctx
        ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
        ctx.clearRect(0, 0, this.width, this.height)

        const cfg = this.currentConfig
        const breathScale = 1 + cfg.breath * Math.sin(this.breathPhase) +
            this.smoothAudio * cfg.audioReactivity * 0.08

        this.drawHalo(cfg, breathScale)
        this.drawLightShaft(cfg)
        this.drawCore(cfg, breathScale)
        this.drawBloomFlourish(cfg)
        this.drawLens(cfg, breathScale)
        this.drawAudioRipple(cfg)
        this.drawWeave(cfg)
        this.drawPrismRefraction(cfg)
        this.drawOscillogram(cfg, breathScale)
        this.drawTransitionRipple(cfg)
        this.drawTransitionTwist(cfg)
        this.drawSettleFlourish(cfg)
        this.drawGlyphFlourish(cfg)
        this.drawShockFlourish(cfg)
        this.drawMotes(cfg)
    }

    /* Listening entry: the glass frame inhales with a short warm edge glint. */
    private drawTransitionRipple(cfg: VeilStateConfig): void {
        const ripples = this.flourishes.filter((f) => f.kind === 'ripple')
        if (ripples.length === 0) return
        const ctx = this.ctx

        for (const f of ripples) {
            const env = Math.sin(f.progress * Math.PI)

            ctx.save()
            ctx.globalCompositeOperation = 'screen'
            ctx.shadowBlur = 12
            ctx.shadowColor = rgba(cfg.silkAccent, 0.14 * env)
            this.strokeLensArc(0.30 - f.progress * 0.035, 0.10, 1.018, rgba(cfg.silkAccent, 0.22 * env), 1)
            this.strokeLensArc(0.57 + f.progress * 0.035, 0.10, 1.018, rgba([255, 250, 240], 0.16 * env), 0.9)
            ctx.restore()
        }
    }

    /* Thinking entry: two opposing perimeter glints tighten around the lens. */
    private drawTransitionTwist(cfg: VeilStateConfig): void {
        const twists = this.flourishes.filter((f) => f.kind === 'twist')
        if (twists.length === 0) return
        const ctx = this.ctx

        for (const f of twists) {
            const env = Math.sin(f.progress * Math.PI)
            ctx.save()
            ctx.globalCompositeOperation = 'screen'
            ctx.shadowBlur = 10
            ctx.shadowColor = rgba(cfg.silkAccent, 0.12 * env)
            this.strokeLensArc(0.12 + f.progress * 0.16, 0.16, 1.012, rgba(cfg.silkAccent, 0.22 * env), 1)
            this.strokeLensArc(0.62 + f.progress * 0.16, 0.16, 1.012, rgba([255, 250, 240], 0.18 * env), 0.9)
            ctx.restore()
        }
    }

    /* Idle entry: a quiet vertical iris settles inside the glass. */
    private drawSettleFlourish(cfg: VeilStateConfig): void {
        const settles = this.flourishes.filter((f) => f.kind === 'settle')
        if (settles.length === 0) return
        const ctx = this.ctx
        const { rx, ry } = this.lensBounds()
        const lensPath = this.createLensPath()

        for (const f of settles) {
            const e = easeOutCubic(f.progress)
            const a = (1 - f.progress) * 0.13
            const wipeWidth = rx * (0.18 + e * 0.78)

            ctx.save()
            ctx.clip(lensPath)
            ctx.globalCompositeOperation = 'screen'
            const grad = ctx.createLinearGradient(this.cx - wipeWidth, 0, this.cx + wipeWidth, 0)
            grad.addColorStop(0, rgba(cfg.silkPrimary, 0))
            grad.addColorStop(0.5, rgba(cfg.silkPrimary, a))
            grad.addColorStop(1, rgba(cfg.silkPrimary, 0))
            ctx.fillStyle = grad
            ctx.fillRect(this.cx - wipeWidth, this.cy - ry, wipeWidth * 2, ry * 2)
            ctx.restore()
        }
    }

    /* Wide diffuse halo behind everything — anchors the lens without washing
       the page in ambient noise. */
    private drawHalo(cfg: VeilStateConfig, scale: number): void {
        const ctx = this.ctx
        const lightMode = this.isLightTheme()
        const { rx, ry } = this.lensBounds(scale)
        const driftX = Math.sin(this.driftPhase * 0.42) * rx * 0.05
        const driftY = Math.cos(this.breathPhase * 0.36) * ry * 0.05
        const grad = ctx.createRadialGradient(
            this.cx + driftX,
            this.cy + driftY,
            rx * 0.20,
            this.cx,
            this.cy,
            rx * 2.15,
        )
        const a = cfg.haloIntensity * (1 + this.hoverT * 0.4)
        const coolHalo: RGB = lightMode ? [122, 106, 90] : cfg.coolLight
        grad.addColorStop(0, rgba(coolHalo, a * (lightMode ? 0.42 : 0.56)))
        grad.addColorStop(0.42, rgba(coolHalo, a * (lightMode ? 0.16 : 0.22)))
        grad.addColorStop(1, rgba(coolHalo, 0))

        ctx.save()
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.ellipse(this.cx, this.cy + ry * 0.12, rx * 2.16, ry * 1.78, 0, 0, TAU)
        ctx.fill()

        const warmBack = ctx.createRadialGradient(
            this.cx - rx * 0.28,
            this.cy - ry * 0.10,
            0,
            this.cx - rx * 0.12,
            this.cy,
            rx * 1.18,
        )
        const warmHalo: RGB = lightMode ? [150, 110, 78] : cfg.warmLight
        warmBack.addColorStop(0, rgba(warmHalo, a * (lightMode ? 0.10 : 0.16)))
        warmBack.addColorStop(0.55, rgba(warmHalo, a * (lightMode ? 0.035 : 0.055)))
        warmBack.addColorStop(1, rgba(warmHalo, 0))
        ctx.fillStyle = warmBack
        ctx.beginPath()
        ctx.ellipse(this.cx - rx * 0.10, this.cy + ry * 0.02, rx * 1.22, ry * 1.12, 0, 0, TAU)
        ctx.fill()
        ctx.restore()
    }

    /* Soft vertical light coming from above — directly references the
       backlit drape of the brand portrait. */
    private drawLightShaft(cfg: VeilStateConfig): void {
        const ctx = this.ctx
        const lightMode = this.isLightTheme()
        const { rx, ry } = this.lensBounds()
        const w = rx * cfg.shaftWidth * (1 + this.hoverT * 0.08)
        const h = ry * 2.55
        const cx = this.cx + Math.sin(this.time * 0.18) * w * 0.05
        const top = this.cy - h * 0.64

        const grad = ctx.createLinearGradient(cx, top, cx, top + h)
        const a = cfg.shaftIntensity
        const shaftColor: RGB = lightMode ? [132, 92, 66] : cfg.warmLight
        grad.addColorStop(0, rgba(shaftColor, a * (lightMode ? 0.13 : 0.62)))
        grad.addColorStop(0.44, rgba(shaftColor, a * (lightMode ? 0.07 : 0.38)))
        grad.addColorStop(1, rgba(shaftColor, 0))

        ctx.save()
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        ctx.filter = 'blur(10px)'
        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.ellipse(cx, top + h * 0.45, w * 0.8, h * 0.50, 0, 0, TAU)
        ctx.fill()
        ctx.filter = 'none'
        ctx.restore()
    }

    /* Pearl core behind the veils. Pulses with breath + audio. */
    private drawCore(cfg: VeilStateConfig, scale: number): void {
        const ctx = this.ctx
        const lightMode = this.isLightTheme()
        const { rx } = this.lensBounds(scale)
        const r = rx * cfg.coreSize * 0.9
        const intensity = cfg.coreIntensity *
            (1 + this.hoverT * 0.25 + this.smoothAudio * cfg.audioReactivity * 0.6)

        const grad = ctx.createRadialGradient(this.cx, this.cy, 0, this.cx, this.cy, r * 4.3)
        grad.addColorStop(0, rgba([255, 250, 240], clamp01(intensity * (lightMode ? 0.22 : 0.95))))
        grad.addColorStop(0.18, rgba(cfg.silkPrimary, clamp01(intensity * (lightMode ? 0.16 : 0.55))))
        grad.addColorStop(0.5, rgba(lightMode ? [118, 86, 64] : cfg.silkAccent, intensity * (lightMode ? 0.055 : 0.18)))
        grad.addColorStop(1, rgba(cfg.silkAccent, 0))

        ctx.save()
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.arc(this.cx, this.cy, r * 5, 0, TAU)
        ctx.fill()
        ctx.restore()
    }

    /* Premium aperture: a stable glass lens with a restrained silk signature
       inside. The state motion lives inside this frame instead of deforming
       the overall silhouette. */
    private drawLens(cfg: VeilStateConfig, scale: number): void {
        const ctx = this.ctx
        const lightMode = this.isLightTheme()
        const lensPath = this.createLensPath(scale)
        const { rx, ry } = this.lensBounds(scale)
        const sampleCount = 64

        ctx.save()
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'

        if (lightMode) {
            ctx.save()
            ctx.globalCompositeOperation = 'source-over'
            ctx.shadowBlur = 30
            ctx.shadowColor = rgba([74, 58, 44], 0.17)
            ctx.fillStyle = rgba([88, 68, 52], 0.065)
            ctx.beginPath()
            ctx.ellipse(this.cx, this.cy + ry * 0.12, rx * 1.04, ry * 0.88, 0, 0, TAU)
            ctx.fill()
            ctx.restore()
        }

        const shadow = ctx.createRadialGradient(this.cx, this.cy + ry * 0.12, 0, this.cx, this.cy, rx * 1.48)
        const shadowColor: RGB = lightMode ? [92, 72, 56] : cfg.coolLight
        shadow.addColorStop(0, rgba(shadowColor, (lightMode ? 0.055 : 0.055) + cfg.energy * (lightMode ? 0.018 : 0.022)))
        shadow.addColorStop(1, rgba(shadowColor, 0))
        ctx.fillStyle = shadow
        ctx.beginPath()
        ctx.ellipse(this.cx, this.cy + ry * 0.08, rx * 1.44, ry * 1.42, 0, 0, TAU)
        ctx.fill()

        const body = ctx.createLinearGradient(this.cx - rx, this.cy - ry, this.cx + rx, this.cy + ry)
        if (lightMode) {
            body.addColorStop(0, rgba([90, 70, 54], 0.030))
            body.addColorStop(0.22, rgba(cfg.silkPrimary, cfg.sheetOpacity * 0.14))
            body.addColorStop(0.52, rgba([255, 252, 244], cfg.sheetOpacity * 0.20))
            body.addColorStop(0.78, rgba([128, 100, 78], cfg.sheetOpacity * 0.12))
            body.addColorStop(1, rgba([66, 52, 42], cfg.sheetOpacity * 0.075))
        } else {
            body.addColorStop(0, rgba([255, 250, 240], 0.026))
            body.addColorStop(0.24, rgba(cfg.silkPrimary, cfg.sheetOpacity * 0.34))
            body.addColorStop(0.56, rgba(cfg.silkPrimary, cfg.sheetOpacity * 0.68))
            body.addColorStop(0.82, rgba(cfg.coolLight, cfg.sheetOpacity * 0.25))
            body.addColorStop(1, rgba(cfg.coolLight, cfg.sheetOpacity * 0.10))
        }

        ctx.fillStyle = body
        ctx.fill(lensPath)

        ctx.save()
        ctx.clip(lensPath)

        const innerShade = ctx.createLinearGradient(this.cx - rx, this.cy, this.cx + rx, this.cy)
        innerShade.addColorStop(0, rgba([0, 0, 0], lightMode ? 0.14 : 0.24))
        innerShade.addColorStop(0.48, rgba([0, 0, 0], 0))
        innerShade.addColorStop(1, rgba([0, 0, 0], lightMode ? 0.11 : 0.18))
        ctx.globalCompositeOperation = 'source-over'
        ctx.fillStyle = innerShade
        ctx.fillRect(this.cx - rx, this.cy - ry, rx * 2, ry * 2)

        const glassBloom = ctx.createRadialGradient(
            this.cx - rx * 0.18,
            this.cy - ry * 0.08,
            0,
            this.cx,
            this.cy,
            rx * 1.18,
        )
        glassBloom.addColorStop(0, rgba([255, 250, 240], (lightMode ? 0.07 : 0.030) + cfg.energy * (lightMode ? 0.010 : 0.012)))
        glassBloom.addColorStop(0.56, rgba(cfg.silkPrimary, (lightMode ? 0.026 : 0.018) + cfg.energy * (lightMode ? 0.006 : 0.008)))
        glassBloom.addColorStop(1, rgba(cfg.silkPrimary, 0))
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        ctx.fillStyle = glassBloom
        ctx.beginPath()
        ctx.ellipse(this.cx, this.cy, rx * 0.96, ry * 0.94, 0, 0, TAU)
        ctx.fill()

        this.drawSilkVeil(cfg, rx, ry, sampleCount)

        const specularShift = Math.sin(this.breathPhase * 0.55 + this.driftPhase * 0.2) * rx * 0.08
        const specular = ctx.createLinearGradient(
            this.cx - rx * 0.40 + specularShift,
            this.cy - ry,
            this.cx + rx * 0.18 + specularShift,
            this.cy,
        )
        specular.addColorStop(0, rgba([255, 255, 250], 0))
        specular.addColorStop(0.52, rgba([255, 255, 250], (lightMode ? 0.18 : 0.10) + cfg.energy * (lightMode ? 0.018 : 0.028)))
        specular.addColorStop(1, rgba([255, 255, 250], 0))
        ctx.fillStyle = specular
        ctx.fillRect(this.cx - rx, this.cy - ry, rx * 2, ry * 2)
        ctx.restore()

        ctx.lineJoin = 'round'
        ctx.strokeStyle = lightMode
            ? rgba([72, 56, 44], 0.22 + cfg.rimLight * 0.22)
            : rgba([255, 250, 240], 0.13 + cfg.rimLight * 0.20)
        ctx.lineWidth = lightMode ? 1.35 : 1.2
        ctx.stroke(lensPath)

        ctx.strokeStyle = rgba(lightMode ? [118, 88, 66] : cfg.silkAccent, 0.07 + cfg.rimLight * (lightMode ? 0.14 : 0.10))
        ctx.lineWidth = lightMode ? 0.95 : 0.8
        ctx.stroke(this.createLensPath(scale * 0.965))

        this.strokeLensArc(0.72, 0.12, scale * 1.01, rgba(lightMode ? [96, 74, 56] : [255, 250, 240], 0.16 + cfg.energy * (lightMode ? 0.035 : 0.05)), 1)
        this.strokeLensArc(0.06, 0.08, scale * 1.006, rgba(lightMode ? [126, 92, 66] : cfg.silkAccent, 0.08 + cfg.energy * (lightMode ? 0.04 : 0.035)), 0.8)

        ctx.restore()
    }

    private drawSilkVeil(
        cfg: VeilStateConfig,
        rx: number,
        ry: number,
        sampleCount: number,
    ): void {
        const ctx = this.ctx
        const lightMode = this.isLightTheme()
        const layerCount = Math.max(2, Math.round(cfg.sheetCount))

        for (let layerIndex = 0; layerIndex < layerCount; layerIndex++) {
            const depth = 1 - layerIndex / Math.max(1, layerCount - 1)
            const layerPhase = hashPhase(layerIndex + 3)
            const layerOffset = (layerIndex - (layerCount - 1) / 2) / Math.max(1, layerCount - 1)
            const baseCenter = this.cx - rx * 0.05 + layerOffset * rx * 0.33
            const baseHalfWidth = rx * (0.30 + depth * 0.11) * cfg.veilSpread
            const points: Array<{
                center: number
                y: number
                left: number
                right: number
                cap: number
            }> = []

            for (let sampleIndex = 0; sampleIndex <= sampleCount; sampleIndex++) {
                const yn = -1 + (2 * sampleIndex) / sampleCount
                const verticalPresence = Math.pow(
                    Math.max(0, Math.sin(((yn + 1) * Math.PI) / 2)),
                    0.72,
                )
                const cap = 0.68 + verticalPresence * 0.32
                const shoulder = 1 + 0.10 * gaussian(yn, -0.42, 0.36)
                const fall = 1 - 0.05 * gaussian(yn, 0.44, 0.32)
                const drift = Math.sin(this.driftPhase + layerPhase) * cfg.driftAmp * rx * 0.7
                const wave = Math.sin(yn * Math.PI * cfg.warpFreq + this.warpPhase + layerPhase) * cfg.warpAmp * rx * 0.7
                const counterWave = Math.sin(yn * Math.PI * 0.7 - this.warpPhase * 0.42 + layerPhase * 1.2) * cfg.twistAmount * rx * 0.26
                const center = baseCenter + (drift + wave + counterWave * yn) * cap
                const halfWidth = baseHalfWidth * cap * shoulder * fall *
                    (0.98 + 0.035 * Math.cos(yn * Math.PI * 1.5 + layerPhase + this.warpPhase * 0.22))
                const asymmetry = Math.sin(yn * Math.PI * 0.85 + layerPhase) * 0.06
                points.push({
                    center,
                    y: this.cy + yn * ry * 1.12,
                    left: center - halfWidth * (0.78 + asymmetry),
                    right: center + halfWidth * (0.88 - asymmetry),
                    cap,
                })
            }

            const veilPath = new Path2D()
            veilPath.moveTo(points[0].right, points[0].y)
            for (let sampleIndex = 1; sampleIndex <= sampleCount; sampleIndex++) {
                veilPath.lineTo(points[sampleIndex].right, points[sampleIndex].y)
            }
            for (let sampleIndex = sampleCount; sampleIndex >= 0; sampleIndex--) {
                veilPath.lineTo(points[sampleIndex].left, points[sampleIndex].y)
            }
            veilPath.closePath()

            const silkAlpha = cfg.sheetOpacity * (0.24 + depth * 0.22)
            const fill = ctx.createLinearGradient(this.cx - rx * 0.62, 0, this.cx + rx * 0.62, 0)
            if (lightMode) {
                fill.addColorStop(0, rgba([106, 82, 62], silkAlpha * 0.060))
                fill.addColorStop(0.34, rgba([128, 98, 72], silkAlpha * 0.22))
                fill.addColorStop(0.55, rgba([255, 252, 244], silkAlpha * 0.22))
                fill.addColorStop(0.78, rgba([120, 90, 66], silkAlpha * 0.16))
                fill.addColorStop(1, rgba([70, 54, 42], silkAlpha * 0.050))
            } else {
                fill.addColorStop(0, rgba(cfg.silkPrimary, silkAlpha * 0.04))
                fill.addColorStop(0.34, rgba(cfg.silkPrimary, silkAlpha * 0.36))
                fill.addColorStop(0.55, rgba([255, 250, 240], silkAlpha * 0.50))
                fill.addColorStop(0.78, rgba(cfg.silkPrimary, silkAlpha * 0.18))
                fill.addColorStop(1, rgba(cfg.silkPrimary, silkAlpha * 0.03))
            }
            ctx.fillStyle = fill
            ctx.fill(veilPath)

            ctx.lineWidth = depth > 0.8 ? 0.7 : 0.55
            ctx.strokeStyle = rgba(lightMode ? [92, 68, 50] : cfg.silkPrimary, cfg.rimLight * (0.055 + depth * (lightMode ? 0.090 : 0.045)))
            ctx.beginPath()
            for (let sampleIndex = 0; sampleIndex <= sampleCount; sampleIndex++) {
                const point = points[sampleIndex]
                if (sampleIndex === 0) ctx.moveTo(point.left, point.y)
                else ctx.lineTo(point.left, point.y)
            }
            ctx.stroke()

            ctx.strokeStyle = rgba(lightMode ? [255, 252, 244] : [255, 250, 240], cfg.rimLight * (0.06 + depth * 0.05))
            ctx.beginPath()
            for (let sampleIndex = 0; sampleIndex <= sampleCount; sampleIndex++) {
                const point = points[sampleIndex]
                if (sampleIndex === 0) ctx.moveTo(point.right, point.y)
                else ctx.lineTo(point.right, point.y)
            }
            ctx.stroke()

            const foldOffsets = [-0.42, -0.12, 0.22, 0.50]
            for (const foldOffset of foldOffsets) {
                const foldAlpha = cfg.rimLight * (0.08 + depth * 0.11) * (1 - Math.abs(foldOffset) * 0.55)
                ctx.strokeStyle = rgba(lightMode ? [92, 68, 50] : [255, 250, 240], lightMode ? foldAlpha * 1.08 : foldAlpha)
                ctx.lineWidth = foldOffset > 0.3 ? 0.55 : 0.75
                ctx.beginPath()
                for (let sampleIndex = 0; sampleIndex <= sampleCount; sampleIndex++) {
                    const point = points[sampleIndex]
                    const width = (point.right - point.left) * 0.5
                    const x = point.center + width * foldOffset +
                        Math.sin(sampleIndex * 0.16 + layerPhase) * rx * 0.006 * point.cap
                    if (sampleIndex === 0) ctx.moveTo(x, point.y)
                    else ctx.lineTo(x, point.y)
                }
                ctx.stroke()
            }
        }
    }

    /* listening — red edge pressure with rounded inward audio brackets. */
    private drawAudioRipple(cfg: VeilStateConfig): void {
        if (cfg.audioWave < 0.02) return
        const ctx = this.ctx
        const { rx, ry } = this.lensBounds()
        const lensPath = this.createLensPath()
        const lightMode = this.isLightTheme()
        const amp = cfg.audioWave * (0.28 + this.smoothAudio * 0.72)
        const pressureColor: RGB = lightMode ? [168, 66, 62] : cfg.silkAccent
        const ember: RGB = lightMode ? [124, 36, 36] : [255, 186, 176]

        ctx.save()
        ctx.clip(lensPath)
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        for (let side = -1; side <= 1; side += 2) {
            const pressure = ctx.createRadialGradient(
                this.cx + side * rx * 0.72,
                this.cy,
                rx * 0.05,
                this.cx + side * rx * 0.88,
                this.cy,
                rx * 0.76,
            )
            pressure.addColorStop(0, rgba(pressureColor, 0.135 * amp))
            pressure.addColorStop(0.48, rgba(pressureColor, 0.055 * amp))
            pressure.addColorStop(1, rgba(pressureColor, 0))
            ctx.fillStyle = pressure
            ctx.fillRect(this.cx - rx, this.cy - ry, rx * 2, ry * 2)
        }

        const centerWarmth = ctx.createLinearGradient(this.cx - rx, this.cy, this.cx + rx, this.cy)
        centerWarmth.addColorStop(0, rgba(pressureColor, 0.050 * amp))
        centerWarmth.addColorStop(0.34, rgba(pressureColor, 0.018 * amp))
        centerWarmth.addColorStop(0.50, rgba(ember, 0.026 * amp))
        centerWarmth.addColorStop(0.66, rgba(pressureColor, 0.018 * amp))
        centerWarmth.addColorStop(1, rgba(pressureColor, 0.050 * amp))
        ctx.fillStyle = centerWarmth
        ctx.fillRect(this.cx - rx, this.cy - ry, rx * 2, ry * 2)
        ctx.restore()

        ctx.save()
        ctx.clip(lensPath)
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        const pulse = 0.52 + 0.48 * Math.sin(this.time * 1.55)
        const membrane = ctx.createRadialGradient(
            this.cx,
            this.cy,
            rx * 0.12,
            this.cx,
            this.cy,
            rx * (0.78 + this.smoothAudio * 0.06),
        )
        membrane.addColorStop(0, rgba(ember, 0.040 * amp * pulse))
        membrane.addColorStop(0.42, rgba(pressureColor, 0.022 * amp))
        membrane.addColorStop(0.72, rgba(pressureColor, 0.034 * amp * (1 - pulse * 0.25)))
        membrane.addColorStop(1, rgba(pressureColor, 0))
        ctx.fillStyle = membrane
        ctx.beginPath()
        ctx.ellipse(this.cx, this.cy, rx * 0.88, ry * 0.74, 0, 0, TAU)
        ctx.fill()

        ctx.shadowBlur = 8
        ctx.shadowColor = rgba(pressureColor, 0.10 * amp)
        ctx.lineCap = 'round'
        for (let side = -1; side <= 1; side += 2) {
            for (let bracketIndex = 0; bracketIndex < 4; bracketIndex++) {
                const phase = this.time * 3.0 + bracketIndex * 0.74 + (side > 0 ? 0.34 : 0)
                const rhythm = 0.5 + 0.5 * Math.sin(phase)
                const lift = Math.sin(phase * 0.62) * ry * 0.006
                const inwardPulse = rhythm * rx * (0.034 + this.smoothAudio * 0.026)
                const heightPulse = rhythm * ry * 0.020
                const inset = bracketIndex * 0.050
                const xOuter = this.cx + side * rx * (0.78 - inset)
                const xBelly = this.cx + side * rx * (0.58 - inset * 0.76) - side * inwardPulse
                const top = this.cy - ry * (0.43 - bracketIndex * 0.050) - heightPulse + lift
                const bottom = this.cy + ry * (0.43 - bracketIndex * 0.050) + heightPulse + lift
                const bracketAlpha = (0.094 + rhythm * 0.052 - bracketIndex * 0.018) * amp

                ctx.strokeStyle = rgba(bracketIndex === 0 ? ember : pressureColor, bracketAlpha)
                ctx.lineWidth = bracketIndex === 0 ? 1.05 + rhythm * 0.18 : 0.78
                ctx.beginPath()
                ctx.moveTo(xOuter, top)
                ctx.bezierCurveTo(
                    xBelly,
                    this.cy - ry * 0.24 + lift,
                    xBelly,
                    this.cy + ry * 0.24 + lift,
                    xOuter,
                    bottom,
                )
                ctx.stroke()
            }
        }

        ctx.strokeStyle = rgba(pressureColor, 0.090 * amp)
        ctx.lineWidth = 1
        ctx.stroke(lensPath)
        ctx.restore()
    }

    /* thinking — perimeter orbits with tapered trails and a faint inner thought field. */
    private drawWeave(cfg: VeilStateConfig): void {
        if (cfg.weave < 0.02) return
        const ctx = this.ctx
        const lightMode = this.isLightTheme()
        const orbit = (this.warpPhase * 0.062) % 1
        const counterOrbit = 1 - (this.warpPhase * 0.040) % 1
        const amount = cfg.weave
        const breath = 0.76 + 0.24 * Math.sin(this.breathPhase * 0.82)
        const orbitColor: RGB = lightMode ? [82, 98, 124] : cfg.silkAccent
        const pearl: RGB = lightMode ? [42, 50, 62] : [255, 250, 240]
        const cool: RGB = lightMode ? [88, 108, 130] : cfg.coolLight
        const { rx, ry } = this.lensBounds()
        const lensPath = this.createLensPath()

        ctx.save()
        ctx.clip(lensPath)
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        const field = ctx.createRadialGradient(
            this.cx - rx * 0.12,
            this.cy - ry * 0.04,
            rx * 0.08,
            this.cx,
            this.cy,
            rx * 0.96,
        )
        field.addColorStop(0, rgba(pearl, (lightMode ? 0.048 : 0.082) * amount * breath))
        field.addColorStop(0.42, rgba(cool, (lightMode ? 0.034 : 0.058) * amount))
        field.addColorStop(1, rgba(cool, 0))
        ctx.fillStyle = field
        ctx.beginPath()
        ctx.ellipse(this.cx, this.cy, rx * 0.86, ry * 0.74, 0, 0, TAU)
        ctx.fill()

        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'
        for (let threadIndex = 0; threadIndex < 3; threadIndex++) {
            const phase = this.time * (0.38 + threadIndex * 0.08) + threadIndex * 1.8
            const yBase = this.cy + ry * (-0.24 + threadIndex * 0.24)
            const threadAlpha = (0.052 + threadIndex * 0.016) * amount * breath
            const gradient = ctx.createLinearGradient(this.cx - rx * 0.72, yBase, this.cx + rx * 0.72, yBase)
            gradient.addColorStop(0, rgba(cool, 0))
            gradient.addColorStop(0.42, rgba(threadIndex === 1 ? pearl : cool, threadAlpha))
            gradient.addColorStop(1, rgba(cool, 0))
            ctx.strokeStyle = gradient
            ctx.lineWidth = threadIndex === 1 ? 1.05 : 0.78
            ctx.beginPath()
            ctx.moveTo(this.cx - rx * 0.66, yBase + Math.sin(phase) * ry * 0.018)
            ctx.bezierCurveTo(
                this.cx - rx * 0.26,
                yBase - ry * (0.20 + 0.03 * Math.sin(phase * 0.7)),
                this.cx + rx * 0.24,
                yBase + ry * (0.18 + 0.03 * Math.cos(phase * 0.8)),
                this.cx + rx * 0.66,
                yBase + Math.cos(phase) * ry * 0.018,
            )
            ctx.stroke()
        }

        ctx.shadowBlur = 8
        ctx.shadowColor = rgba(pearl, 0.10 * amount)
        for (let loopIndex = 0; loopIndex < 2; loopIndex++) {
            const loopPhase = this.time * (0.34 + loopIndex * 0.11) + loopIndex * 1.74
            const loopAlpha = (0.045 + loopIndex * 0.018) * amount * breath
            const loopY = this.cy + ry * (-0.07 + loopIndex * 0.15)
            const loopGradient = ctx.createLinearGradient(this.cx - rx * 0.62, loopY, this.cx + rx * 0.62, loopY)
            loopGradient.addColorStop(0, rgba(cool, 0))
            loopGradient.addColorStop(0.36, rgba(cool, loopAlpha * 0.72))
            loopGradient.addColorStop(0.55, rgba(pearl, loopAlpha))
            loopGradient.addColorStop(1, rgba(cool, 0))
            ctx.strokeStyle = loopGradient
            ctx.lineWidth = loopIndex === 0 ? 0.92 : 0.74
            ctx.beginPath()
            ctx.ellipse(
                this.cx + Math.sin(loopPhase) * rx * 0.035,
                loopY,
                rx * (0.52 + loopIndex * 0.07),
                ry * (0.15 + loopIndex * 0.035),
                Math.sin(loopPhase * 0.8) * 0.12,
                Math.PI * (0.08 + loopIndex * 0.06),
                Math.PI * (1.12 + loopIndex * 0.10),
            )
            ctx.stroke()
        }
        ctx.restore()

        const drawTrail = (
            start: number,
            length: number,
            scale: number,
            color: RGB,
            alpha: number,
            lineWidth: number,
            reverse = false,
        ): void => {
            const segments = 8
            for (let segment = 0; segment < segments; segment++) {
                const t = segment / segments
                const taper = reverse ? Math.pow(t, 1.4) : Math.pow(1 - t, 1.4)
                const segmentStart = start + length * (segment / segments)
                const segmentLength = length / segments * 0.88
                this.strokeLensArc(
                    segmentStart,
                    segmentLength,
                    scale,
                    rgba(color, alpha * taper * amount * breath),
                    lineWidth * (0.48 + 0.52 * taper),
                )
            }
        }

        ctx.save()
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        ctx.lineCap = 'round'

        ctx.shadowBlur = 16
        ctx.shadowColor = rgba(orbitColor, 0.16 * amount)
        const ringDefs: Array<{ off: number; length: number; scale: number; color: RGB; alpha: number; lw: number }> = [
            { off: 0.00, length: 0.27, scale: 1.016, color: orbitColor, alpha: 0.34, lw: 1.24 },
            { off: 0.31, length: 0.21, scale: 1.032, color: pearl,      alpha: 0.27, lw: 1.12 },
            { off: 0.62, length: 0.16, scale: 1.048, color: cool,       alpha: 0.20, lw: 0.88 },
            { off: 0.79, length: 0.10, scale: 1.008, color: pearl,      alpha: 0.17, lw: 0.74 },
        ]
        for (const ring of ringDefs) {
            drawTrail(orbit + ring.off, ring.length, ring.scale, ring.color, ring.alpha, ring.lw)
        }

        ctx.shadowBlur = 10
        ctx.shadowColor = rgba(cool, 0.10 * amount)
        const counterDefs: Array<{ off: number; length: number; scale: number; color: RGB; alpha: number; lw: number }> = [
            { off: 0.08, length: 0.13, scale: 1.010, color: cool,       alpha: 0.18, lw: 0.82 },
            { off: 0.48, length: 0.11, scale: 1.024, color: orbitColor, alpha: 0.15, lw: 0.72 },
            { off: 0.71, length: 0.08, scale: 1.038, color: pearl,      alpha: 0.12, lw: 0.64 },
        ]
        for (const ring of counterDefs) {
            drawTrail(counterOrbit + ring.off, ring.length, ring.scale, ring.color, ring.alpha, ring.lw, true)
        }

        ctx.shadowBlur = 8
        ctx.shadowColor = rgba(pearl, 0.20 * amount)
        for (let ni = 0; ni < 4; ni++) {
            const nodePos = orbit + ni * 0.25
            const pulse = 0.62 + 0.38 * Math.sin(this.time * 1.85 + ni * 1.57)
            const nodeAlpha = (0.26 + 0.16 * pulse) * amount * breath
            this.strokeLensArc(
                nodePos - 0.018,
                0.036,
                1.026,
                rgba(ni % 2 === 0 ? pearl : orbitColor, nodeAlpha),
                ni % 2 === 0 ? 1.48 : 1.20,
            )
            const point = this.lensPoint(nodePos, 1.012)
            const dot = ctx.createRadialGradient(point.x, point.y, 0, point.x, point.y, 5)
            dot.addColorStop(0, rgba(ni % 2 === 0 ? pearl : orbitColor, nodeAlpha * 0.70))
            dot.addColorStop(1, rgba(ni % 2 === 0 ? pearl : orbitColor, 0))
            ctx.fillStyle = dot
            ctx.beginPath()
            ctx.arc(point.x, point.y, 4.2 + 1.2 * pulse, 0, TAU)
            ctx.fill()
        }
        ctx.restore()
    }

    /* processing — irregular full-lens facet texture with animated prismatic shades. */
    private drawPrismRefraction(cfg: VeilStateConfig): void {
        if (cfg.prism < 0.02) return
        const ctx = this.ctx
        const lightMode = this.isLightTheme()
        const prismEntry = this.flourishes.find((f) => f.kind === 'prism')
        const entry = prismEntry ? Math.sin(prismEntry.progress * Math.PI) * prismEntry.intensity : 0
        const a = cfg.prism * (0.78 + entry * 0.32)
        const { rx, ry } = this.lensBounds()
        const lensPath = this.createLensPath()
        const white: RGB = lightMode ? [252, 248, 238] : [255, 252, 242]
        const cyan: RGB = lightMode ? [112, 180, 196] : [182, 244, 255]
        const seamPhase = this.time * 0.68

        ctx.save()
        ctx.clip(lensPath)
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'

        // ── Milky base wash ───────────────────────────────────────────────────────
        const milk = ctx.createRadialGradient(
            this.cx - rx * 0.08, this.cy - ry * 0.05, rx * 0.04,
            this.cx, this.cy, rx * 0.96,
        )
        milk.addColorStop(0, rgba(white, (lightMode ? 0.040 : 0.045) * a))
        milk.addColorStop(0.48, rgba(cfg.silkAccent, (lightMode ? 0.018 : 0.022) * a))
        milk.addColorStop(1, rgba(white, 0))
        ctx.fillStyle = milk
        ctx.beginPath()
        ctx.ellipse(this.cx, this.cy, rx * 0.88, ry * 0.78, -0.08, 0, TAU)
        ctx.fill()

        ctx.globalCompositeOperation = 'source-over'

        const ringRadii = [0, 0.25, 0.52, 0.82, 1.10, 1.30]
        const segmentCount = 12
        const facetPoint = (ringIndex: number, segmentIndex: number): [number, number] => {
            const radius = ringRadii[ringIndex]
            if (radius === 0) return [this.cx, this.cy]

            const seedRaw = Math.sin(ringIndex * 53.17 + segmentIndex * 21.91) * 43758.5453
            const seed = seedRaw - Math.floor(seedRaw)
            const jitter = ringIndex === ringRadii.length - 1 ? 0 : (seed - 0.5) * 0.145
            const angle = (segmentIndex / segmentCount) * TAU + ringIndex * 0.065 + jitter
            const boundary = this.lensPoint(((angle / TAU) % 1 + 1) % 1, 1.12)
            const radialJitter = ringIndex === ringRadii.length - 1 ? 1 : 1 + (seed - 0.5) * 0.115
            return [
                this.cx + (boundary.x - this.cx) * radius * radialJitter,
                this.cy + (boundary.y - this.cy) * radius * radialJitter,
            ]
        }

        ctx.lineJoin = 'round'
        ctx.lineCap = 'round'
        for (let ringIndex = 0; ringIndex < ringRadii.length - 1; ringIndex++) {
            for (let segmentIndex = 0; segmentIndex < segmentCount; segmentIndex++) {
                const nextSegment = (segmentIndex + 1) % segmentCount
                const p00 = facetPoint(ringIndex, segmentIndex)
                const p01 = facetPoint(ringIndex, nextSegment)
                const p10 = facetPoint(ringIndex + 1, segmentIndex)
                const p11 = facetPoint(ringIndex + 1, nextSegment)
                const flip = Math.sin(ringIndex * 2.77 + segmentIndex * 1.31) > 0
                const triangles: Array<[[number, number], [number, number], [number, number]]> = flip
                    ? [[p00, p10, p01], [p10, p11, p01]]
                    : [[p00, p10, p11], [p00, p11, p01]]

                for (let facetIndex = 0; facetIndex < triangles.length; facetIndex++) {
                    const tri = triangles[facetIndex]
                    const centX = (tri[0][0] + tri[1][0] + tri[2][0]) / 3
                    const centY = (tri[0][1] + tri[1][1] + tri[2][1]) / 3
                    const nx = (centX - this.cx) / rx
                    const ny = (centY - this.cy) / ry
                    const angle = Math.atan2(ny, nx)
                    const seed = Math.sin(ringIndex * 11.13 + segmentIndex * 17.71 + facetIndex * 5.31)
                    const processingWave = 0.50 + 0.50 * Math.sin(
                        this.time * 1.75 + nx * 6.4 - ny * 4.8 + seed * TAU,
                    )
                    const chromaWave = 0.50 + 0.50 * Math.sin(
                        this.time * 1.05 - nx * 3.3 + ny * 7.1 + ringIndex * 0.9,
                    )
                    const hue = ((angle / TAU + 0.55 + this.time * 0.22 + chromaWave * 0.12 + seed * 0.05) % 1 + 1) % 1
                    const prismColor = hueRGB(hue)
                    const prismColorNext = hueRGB(hue + 0.11 + processingWave * 0.035)
                    const prismColorPrev = hueRGB(hue - 0.075 - chromaWave * 0.025)
                    const lensColor: RGB = [
                        Math.round(cfg.silkAccent[0] * 0.80 + white[0] * 0.20),
                        Math.round(cfg.silkAccent[1] * 0.80 + white[1] * 0.20),
                        Math.round(cfg.silkAccent[2] * 0.80 + white[2] * 0.20),
                    ]
                    const softColor: RGB = [
                        Math.round(lensColor[0] * 0.54 + prismColor[0] * 0.46),
                        Math.round(lensColor[1] * 0.54 + prismColor[1] * 0.46),
                        Math.round(lensColor[2] * 0.54 + prismColor[2] * 0.46),
                    ]
                    const shadeA: RGB = [
                        Math.round(lensColor[0] * 0.46 + prismColorPrev[0] * 0.54),
                        Math.round(lensColor[1] * 0.46 + prismColorPrev[1] * 0.54),
                        Math.round(lensColor[2] * 0.46 + prismColorPrev[2] * 0.54),
                    ]
                    const shadeB: RGB = [
                        Math.round(lensColor[0] * 0.46 + prismColorNext[0] * 0.54),
                        Math.round(lensColor[1] * 0.46 + prismColorNext[1] * 0.54),
                        Math.round(lensColor[2] * 0.46 + prismColorNext[2] * 0.54),
                    ]
                    const radiusFalloff = 0.62 + 0.38 * (1 - clamp01(Math.sqrt(nx * nx + ny * ny) * 0.72))
                    const angledLight = 0.30 + 0.70 * Math.abs(
                        Math.sin(angle * 1.35 + seed * 2.7 + this.time * 0.42),
                    )
                    const faceAlpha = (lightMode ? 0.022 : 0.030) * a * angledLight * radiusFalloff
                    const prismAlpha = (lightMode ? 0.135 : 0.245) * a * (0.24 + processingWave * 0.76) * radiusFalloff

                    const faceGrad = ctx.createLinearGradient(tri[0][0], tri[0][1], tri[2][0], tri[2][1])
                    faceGrad.addColorStop(0, rgba(white, faceAlpha * 0.20))
                    faceGrad.addColorStop(0.52, rgba(white, faceAlpha))
                    faceGrad.addColorStop(1, rgba(cyan, faceAlpha * 0.36))

                    ctx.beginPath()
                    ctx.moveTo(tri[0][0], tri[0][1])
                    ctx.lineTo(tri[1][0], tri[1][1])
                    ctx.lineTo(tri[2][0], tri[2][1])
                    ctx.closePath()
                    ctx.fillStyle = faceGrad
                    ctx.fill()
                    const prismGrad = ctx.createLinearGradient(
                        tri[(facetIndex + 0) % 3][0],
                        tri[(facetIndex + 0) % 3][1],
                        tri[(facetIndex + 2) % 3][0],
                        tri[(facetIndex + 2) % 3][1],
                    )
                    prismGrad.addColorStop(0, rgba(shadeA, prismAlpha * 0.85))
                    prismGrad.addColorStop(0.48, rgba(softColor, prismAlpha * 0.42))
                    prismGrad.addColorStop(1, rgba(shadeB, prismAlpha))
                    ctx.fillStyle = prismGrad
                    ctx.fill()
                    ctx.save()
                    ctx.clip()
                    const splitA = tri[(facetIndex + 1) % 3]
                    const splitB = tri[(facetIndex + 2) % 3]
                    const spectralSplit = ctx.createLinearGradient(splitA[0], splitA[1], splitB[0], splitB[1])
                    spectralSplit.addColorStop(0, rgba(prismColorPrev, 0))
                    spectralSplit.addColorStop(0.38, rgba(shadeA, prismAlpha * 0.92))
                    spectralSplit.addColorStop(0.54, rgba(white, prismAlpha * 0.38))
                    spectralSplit.addColorStop(0.72, rgba(shadeB, prismAlpha))
                    spectralSplit.addColorStop(1, rgba(prismColorNext, 0))
                    ctx.strokeStyle = spectralSplit
                    ctx.lineWidth = 1.05 + 0.58 * processingWave
                    ctx.beginPath()
                    ctx.moveTo((tri[0][0] + tri[1][0]) * 0.5, (tri[0][1] + tri[1][1]) * 0.5)
                    ctx.lineTo((tri[1][0] + tri[2][0]) * 0.5, (tri[1][1] + tri[2][1]) * 0.5)
                    ctx.stroke()
                    ctx.restore()
                    ctx.strokeStyle = rgba(lensColor, (lightMode ? 0.052 : 0.080) * a * radiusFalloff)
                    ctx.lineWidth = 0.52 + 0.16 * processingWave
                    ctx.stroke()
                }
            }
        }

        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        const surfaceSheen = ctx.createLinearGradient(
            this.cx - rx * 0.84,
            this.cy - ry * 0.54,
            this.cx + rx * 0.72,
            this.cy + ry * 0.48,
        )
        surfaceSheen.addColorStop(0, rgba(cyan, 0))
        surfaceSheen.addColorStop(0.44, rgba(white, (lightMode ? 0.026 : 0.038) * a))
        surfaceSheen.addColorStop(0.62, rgba(cfg.silkAccent, (lightMode ? 0.014 : 0.020) * a))
        surfaceSheen.addColorStop(1, rgba(cyan, 0))
        ctx.fillStyle = surfaceSheen
        ctx.fillRect(this.cx - rx * 1.05, this.cy - ry * 1.06, rx * 2.10, ry * 2.12)

        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'

        // Structural refractive seams, kept subtle so they read as texture.
        ctx.lineCap = 'round'
        const seams: Array<{ color: RGB; alpha: number; start: [number, number]; c1: [number, number]; c2: [number, number]; end: [number, number] }> = [
            { color: white, alpha: 0.070, start: [-0.64, 0.26], c1: [-0.22, -0.42], c2: [0.08, 0.20], end: [0.58, -0.30] },
            { color: cyan,  alpha: 0.042, start: [-0.42, -0.40], c1: [-0.05, -0.12], c2: [0.24, -0.30], end: [0.68, 0.15] },
        ]
        for (let si = 0; si < seams.length; si++) {
            const seam = seams[si]
            const drift = Math.sin(seamPhase + si * 0.9) * 0.025
            const gradient = ctx.createLinearGradient(
                this.cx + seam.start[0] * rx, this.cy + (seam.start[1] + drift) * ry,
                this.cx + seam.end[0] * rx,   this.cy + (seam.end[1] - drift) * ry,
            )
            gradient.addColorStop(0,    rgba(seam.color, 0))
            gradient.addColorStop(0.46, rgba(seam.color, seam.alpha * a))
            gradient.addColorStop(1,    rgba(seam.color, 0))
            ctx.strokeStyle = gradient
            ctx.lineWidth = si === 0 ? 1.05 : 0.70
            ctx.beginPath()
            ctx.moveTo(this.cx + seam.start[0] * rx, this.cy + (seam.start[1] + drift) * ry)
            ctx.bezierCurveTo(
                this.cx + seam.c1[0] * rx, this.cy + (seam.c1[1] - drift) * ry,
                this.cx + seam.c2[0] * rx, this.cy + (seam.c2[1] + drift) * ry,
                this.cx + seam.end[0] * rx, this.cy + (seam.end[1] - drift) * ry,
            )
            ctx.stroke()
        }

        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        ctx.shadowBlur = 12
        ctx.shadowColor = rgba(white, 0.08 * a)
        this.strokeLensArc(0.78 + Math.sin(seamPhase) * 0.008, 0.10, 0.990, rgba(white, 0.085 * a), 0.8)
        this.strokeLensArc(0.09 - Math.sin(seamPhase * 0.9) * 0.008, 0.075, 0.982, rgba(cyan, 0.045 * a), 0.65)
        ctx.restore()
    }

    /* speaking — warm radial bloom around the core. */
    private drawBloomFlourish(cfg: VeilStateConfig): void {
        const fActive = this.flourishes.find((f) => f.kind === 'bloom')
        const steady = cfg.bloom
        const flo = fActive ? Math.sin(fActive.progress * Math.PI) * fActive.intensity : 0
        const total = steady * (0.55 + 0.25 * Math.sin(this.breathPhase * 1.4)) + flo * 0.6
        if (total < 0.02) return

        const ctx = this.ctx
        const lightMode = this.isLightTheme()
        const { rx, ry } = this.lensBounds(1 + flo * 0.10)
        const lensPath = this.createLensPath(1 + flo * 0.04)
        const grad = ctx.createRadialGradient(this.cx, this.cy, 0, this.cx, this.cy, rx)
        grad.addColorStop(0, rgba(cfg.silkAccent, (lightMode ? 0.12 : 0.28) * total))
        grad.addColorStop(0.5, rgba(cfg.silkAccent, (lightMode ? 0.045 : 0.10) * total))
        grad.addColorStop(1, rgba(cfg.silkAccent, 0))

        ctx.save()
        ctx.clip(lensPath)
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.ellipse(this.cx, this.cy, rx, ry, 0, 0, TAU)
        ctx.fill()
        ctx.restore()
    }

    /* speaking — organic oscillogram traces layered inside the lens. */
    private drawOscillogram(cfg: VeilStateConfig, scale: number): void {
        if (cfg.bloom < 0.02) return
        const ctx = this.ctx
        const lightMode = this.isLightTheme()
        const { rx, ry } = this.lensBounds(scale)
        const lensPath = this.createLensPath(scale)
        const breathMod = 0.68 + 0.32 * Math.sin(this.breathPhase * 1.2)
        const a = cfg.bloom * breathMod
        const warm: RGB = lightMode ? [190, 138, 78] : cfg.silkAccent
        const cream: RGB = lightMode ? [228, 208, 168] : [255, 248, 228]

        ctx.save()
        ctx.clip(lensPath)
        ctx.globalCompositeOperation = lightMode ? 'source-over' : 'screen'
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'

        // Three traces staggered vertically — outer pair warm amber, center cream
        const traces: Array<{ yn: number; freq: number; color: RGB; alpha: number; lw: number; phaseOff: number }> = [
            { yn: -0.26, freq: 2.05, color: warm,  alpha: 0.15, lw: 0.78, phaseOff: 0.00 },
            { yn:  0.00, freq: 1.55, color: cream, alpha: 0.23, lw: 1.05, phaseOff: 0.68 },
            { yn:  0.26, freq: 2.40, color: warm,  alpha: 0.12, lw: 0.68, phaseOff: 1.36 },
        ]
        for (const tr of traces) {
            const baseY = this.cy + tr.yn * ry
            const audioAmp = ry * (0.044 + this.smoothAudio * 0.065)
            const breathAmp = ry * 0.024 * breathMod
            const phaseNow = this.time * 0.65 + tr.phaseOff
            ctx.strokeStyle = rgba(tr.color, tr.alpha * a)
            ctx.lineWidth = tr.lw
            ctx.beginPath()
            const steps = 96
            for (let si = 0; si <= steps; si++) {
                const t = si / steps
                const x = this.cx - rx * 0.91 + t * rx * 1.82
                // Fundamental + harmonic for organic feel, plus slow breath drift
                const w1 = Math.sin(t * TAU * tr.freq + phaseNow) * audioAmp
                const w2 = Math.sin(t * TAU * tr.freq * 1.63 + phaseNow * 1.28) * audioAmp * 0.28
                const w3 = Math.sin(t * TAU * 0.82 + phaseNow * 0.52) * breathAmp
                const y = baseY + w1 + w2 + w3
                if (si === 0) ctx.moveTo(x, y)
                else ctx.lineTo(x, y)
            }
            ctx.stroke()
        }
        ctx.restore()
    }

    /* tool-call glyph — small square outline stitches across one sheet,
       scale grows then fades. */
    private drawGlyphFlourish(cfg: VeilStateConfig): void {
        const glyphs = this.flourishes.filter((f) => f.kind === 'glyph')
        if (glyphs.length === 0) return
        const ctx = this.ctx
        const { rx, ry } = this.lensBounds()
        const lensPath = this.createLensPath()

        for (const g of glyphs) {
            const t = g.progress
            const ease = easeInOut(t)
            const yn = ((g.anchorY ?? 0.5) * 2 - 1) * 0.58
            const y = this.cy + yn * ry
            const x = this.cx - rx * 0.70 + ease * rx * 1.40
            const size = rx * 0.045 * Math.max(0, 1 - Math.pow(t * 2 - 1, 2))
            const a = (1 - t) * 0.36

            ctx.save()
            ctx.clip(lensPath)
            ctx.globalCompositeOperation = 'screen'
            ctx.translate(x, y)
            ctx.rotate(t * Math.PI * 0.5)
            ctx.strokeStyle = rgba(cfg.silkAccent, a)
            ctx.lineWidth = 1
            ctx.strokeRect(-size, -size, size * 2, size * 2)
            ctx.restore()
        }
    }

    /* click — a frame pulse, restrained and contained. */
    private drawShockFlourish(cfg: VeilStateConfig): void {
        const shocks = this.flourishes.filter((f) => f.kind === 'shock')
        if (shocks.length === 0) return
        const ctx = this.ctx

        for (const s of shocks) {
            const e = easeOutCubic(s.progress)
            const a = (1 - s.progress) * 0.28

            ctx.save()
            ctx.globalCompositeOperation = 'screen'
            ctx.shadowBlur = 14
            ctx.shadowColor = rgba(cfg.silkAccent, a * 0.55)
            ctx.strokeStyle = rgba(cfg.silkAccent, a)
            ctx.lineWidth = 1.2
            ctx.stroke(this.createLensPath(1 + e * 0.055))

            ctx.strokeStyle = rgba([255, 250, 240], a * 0.45)
            ctx.lineWidth = 0.8
            ctx.stroke(this.createLensPath(0.96 + e * 0.035))
            ctx.restore()
        }
    }

    /* Drifting motes. Direction/speed driven by state config. */
    private drawMotes(cfg: VeilStateConfig): void {
        const ctx = this.ctx
        const lensPath = this.createLensPath(0.98)
        ctx.save()
        ctx.clip(lensPath)
        ctx.globalCompositeOperation = 'screen'
        for (const m of this.motes) {
            const lifeT = clamp01(m.life / m.maxLife)
            const env = Math.sin(lifeT * Math.PI)
            const twinkle = 0.6 + 0.4 * Math.sin(this.time * 2.4 + m.phase)
            const a = env * twinkle * 0.18
            const sz = m.size * 1.05
            const grad = ctx.createRadialGradient(m.x, m.y, 0, m.x, m.y, sz * 2.5)
            grad.addColorStop(0, rgba(cfg.silkAccent, a))
            grad.addColorStop(0.5, rgba(cfg.silkAccent, a * 0.35))
            grad.addColorStop(1, rgba(cfg.silkAccent, 0))
            ctx.fillStyle = grad
            ctx.beginPath()
            ctx.arc(m.x, m.y, sz * 2.5, 0, TAU)
            ctx.fill()
        }
        ctx.restore()
    }
}
