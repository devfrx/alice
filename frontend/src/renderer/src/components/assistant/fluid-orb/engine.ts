/**
 * FluidEngine — Aurora orb canvas renderer (v2).
 *
 * A living, breathing gradient orb with:
 *  - Organic noise-displaced boundary (smooth bezier curves)
 *  - Screen-blended internal light pools that orbit and mix
 *  - Subtle conic sweep highlight
 *  - Luminous edge glow and ambient halo
 *  - Canvas-driven hover (glow amplification, radius bloom, particle boost)
 *  - Canvas-driven click (impulse pulse, radiate ripple, momentary flash)
 *  - Exponentially smoothed config interpolation (no jank, no snapping)
 *
 * Aesthetic: Anthropic x Supabase — minimal, dark, softly glowing, alive.
 */
import type {
    OrbState,
    RGB,
    StateConfig,
    Particle,
    PulseRing,
} from './types'
import { STATE_CONFIGS, TRANSITION_CONFIGS } from './config'

const TAU = Math.PI * 2

/* ── Exponential smoothing ────────────────────────────────── */

/**
 * Frame-rate-independent exponential smoothing factor.
 * Returns how much to blend toward the target per frame.
 * `halfLife` is in seconds — the time to close half the gap.
 */
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

function smoothConfig(current: StateConfig, target: StateConfig, k: number): StateConfig {
    const s = (a: number, b: number): number => smoothNum(a, b, k)
    const c = (a: RGB, b: RGB): RGB => smoothRGB(a, b, k)
    return {
        primary: c(current.primary, target.primary),
        secondary: c(current.secondary, target.secondary),
        tertiary: c(current.tertiary, target.tertiary),
        glow: c(current.glow, target.glow),
        morphSpeed: s(current.morphSpeed, target.morphSpeed),
        turbulence: s(current.turbulence, target.turbulence),
        breathSpeed: s(current.breathSpeed, target.breathSpeed),
        breathAmount: s(current.breathAmount, target.breathAmount),
        orbitRadius: s(current.orbitRadius, target.orbitRadius),
        orbitSpeed: s(current.orbitSpeed, target.orbitSpeed),
        blobOpacity: s(current.blobOpacity, target.blobOpacity),
        glowIntensity: s(current.glowIntensity, target.glowIntensity),
        glowSize: s(current.glowSize, target.glowSize),
        coreIntensity: s(current.coreIntensity, target.coreIntensity),
        coreSize: s(current.coreSize, target.coreSize),
        particleCount: Math.round(s(current.particleCount, target.particleCount)),
        particleSpeed: s(current.particleSpeed, target.particleSpeed),
        particleSize: s(current.particleSize, target.particleSize),
        pulseRate: s(current.pulseRate, target.pulseRate),
        audioReactivity: s(current.audioReactivity, target.audioReactivity),
        energy: s(current.energy, target.energy),
    }
}

/* ── Helpers ──────────────────────────────────────────────── */

function rgba(color: RGB, alpha: number): string {
    return `rgba(${color[0] | 0},${color[1] | 0},${color[2] | 0},${alpha})`
}

function clamp01(v: number): number {
    return v < 0 ? 0 : v > 1 ? 1 : v
}

/* ── Engine ───────────────────────────────────────────────── */

export class FluidEngine {
    private canvas!: HTMLCanvasElement
    private ctx!: CanvasRenderingContext2D
    private dpr = 1
    private width = 0
    private height = 0
    private cx = 0
    private cy = 0

    /* State transition */
    private state: OrbState = 'idle'
    private targetConfig: StateConfig = { ...STATE_CONFIGS.idle }
    private currentConfig: StateConfig = { ...STATE_CONFIGS.idle }
    private transitionHalfLife = 0.25

    /* Hover: smooth 0→1 */
    private hoverTarget = 0
    private hoverT = 0

    /* Click impulse: decays to 0 */
    private clickImpulse = 0

    private audioLevel = 0
    private smoothAudio = 0
    private compact: boolean
    private time = 0
    /* Phase accumulators — increment at smoothed speed each frame so that
     * speed changes during state transitions never cause a phase-position
     * discontinuity (the root cause of the "trembling" artefact). */
    private breathPhase = 0
    private morphPhase = 0
    private orbitPhase = 0
    private animId = 0
    private lastFrame = 0
    private resizeObs: ResizeObserver | null = null

    private particles: Particle[] = []
    private rings: PulseRing[] = []
    private lastPulseTime = 0

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
        this.transitionHalfLife = tc.duration * 0.35
    }

    setAudioLevel(level: number): void {
        this.audioLevel = level
    }

    setHover(hovered: boolean): void {
        this.hoverTarget = hovered ? 1 : 0
    }

    triggerClick(): void {
        this.clickImpulse = 1
        this.rings.push({ progress: 0, speed: 1.8, opacity: 0.35 })
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

    private loop = (): void => {
        const now = performance.now()
        const dt = Math.min((now - this.lastFrame) / 1000, 0.1)
        this.lastFrame = now
        this.time += dt

        this.update(dt)
        this.render()

        this.animId = requestAnimationFrame(this.loop)
    }

    /* ── Updates ────────────────────────────────────────────── */

    private update(dt: number): void {
        /* Smooth audio level (half-life ~60ms for snappy but non-jerky) */
        const audioK = smoothFactor(dt, 0.06)
        this.smoothAudio = smoothNum(this.smoothAudio, this.audioLevel, audioK)

        /* Smooth hover (half-life 120ms — fast but silky) */
        const hoverK = smoothFactor(dt, 0.12)
        this.hoverT = smoothNum(this.hoverT, this.hoverTarget, hoverK)

        /* Decay click impulse (half-life 80ms — quick flash) */
        const clickK = smoothFactor(dt, 0.08)
        this.clickImpulse = smoothNum(this.clickImpulse, 0, clickK)
        if (this.clickImpulse < 0.001) this.clickImpulse = 0

        /* Smooth state config transition */
        const cfgK = smoothFactor(dt, this.transitionHalfLife)
        this.currentConfig = smoothConfig(this.currentConfig, this.targetConfig, cfgK)

        /* Accumulate phases at the already-smoothed rates so any speed change
         * during a transition is absorbed gradually with no phase jump. */
        this.breathPhase += this.currentConfig.breathSpeed * dt
        this.morphPhase  += this.currentConfig.morphSpeed  * dt
        this.orbitPhase  += this.currentConfig.orbitSpeed  * dt

        this.updateParticles(dt)
        this.updateRings(dt)
    }

    private updateParticles(dt: number): void {
        const target = Math.floor(
            this.currentConfig.particleCount * (this.compact ? 0.5 : 1),
        )

        while (this.particles.length < target) {
            this.particles.push({
                angle: Math.random() * TAU,
                radiusFactor: 0.72 + Math.random() * 0.22,
                speed: 0.12 + Math.random() * 0.28,
                size: 0.8 + Math.random() * 1.2,
                baseOpacity: 0.25 + Math.random() * 0.45,
                phase: Math.random() * TAU,
            })
        }
        while (this.particles.length > target) this.particles.pop()

        const speed = this.currentConfig.particleSpeed * (1 + this.hoverT * 0.5)
        for (const p of this.particles) {
            p.angle += p.speed * speed * dt
        }
    }

    private updateRings(dt: number): void {
        const cfg = this.currentConfig
        if (
            cfg.pulseRate > 0 &&
            this.time - this.lastPulseTime > 1 / cfg.pulseRate
        ) {
            this.rings.push({
                progress: 0,
                speed: 0.6 + cfg.energy * 0.8,
                opacity: 0.18 * cfg.energy,
            })
            this.lastPulseTime = this.time
        }

        for (let i = this.rings.length - 1; i >= 0; i--) {
            this.rings[i].progress += this.rings[i].speed * dt
            if (this.rings[i].progress >= 1) this.rings.splice(i, 1)
        }
    }

    /* ── Rendering ─────────────────────────────────────────── */

    private getBaseRadius(): number {
        return Math.min(this.width, this.height) * 0.22
    }

    /**
     * Current orb radius — combines breath + audio + hover bloom + click impulse.
     * Everything is multiplicative for smooth compounding.
     */
    private getCurrentRadius(): number {
        const cfg = this.currentConfig
        const breath = 1 + cfg.breathAmount * Math.sin(this.breathPhase)
        const audio = 1 + this.smoothAudio * cfg.audioReactivity * 0.2
        const hover = 1 + this.hoverT * 0.035
        const click = 1 + this.clickImpulse * 0.06
        return this.getBaseRadius() * breath * audio * hover * click
    }

    private buildOrbPath(radius: number): Path2D {
        const N = 80
        const path = new Path2D()
        const { cx, cy } = this
        const mp = this.morphPhase
        const turb = this.currentConfig.turbulence

        const points: Array<{ x: number; y: number }> = []

        for (let i = 0; i < N; i++) {
            const a = (i / N) * TAU
            const d =
                Math.sin(a * 3 + mp * 0.5) * 0.035 +
                Math.sin(a * 5 - mp * 0.72) * 0.022 +
                Math.sin(a * 7 + mp * 0.33) * 0.014 +
                Math.sin(a * 2 + mp * 0.91) * 0.028
            const r = radius * (1 + d * turb)
            points.push({ x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) })
        }

        const last = points[N - 1]
        const first = points[0]
        path.moveTo((first.x + last.x) / 2, (first.y + last.y) / 2)

        for (let i = 0; i < N; i++) {
            const p = points[i]
            const next = points[(i + 1) % N]
            path.quadraticCurveTo(p.x, p.y, (p.x + next.x) / 2, (p.y + next.y) / 2)
        }
        path.closePath()
        return path
    }

    private render(): void {
        const ctx = this.ctx
        ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0)
        ctx.clearRect(0, 0, this.width, this.height)

        const radius = this.getCurrentRadius()
        const orbPath = this.buildOrbPath(radius)

        this.drawAmbientGlow(radius)
        this.drawOrbFill(orbPath, radius)
        this.drawInternalLights(orbPath, radius)
        this.drawConicSweep(orbPath)
        this.drawEdgeGlow(orbPath)
        this.drawCore(radius)
        this.drawPulseRings(radius)
        this.drawParticles(radius)
        this.drawClickFlash(radius)
    }

    /** Large soft halo behind the orb — amplified on hover. */
    private drawAmbientGlow(radius: number): void {
        const ctx = this.ctx
        const cfg = this.currentConfig
        const hoverBoost = 1 + this.hoverT * 0.6
        const clickBoost = 1 + this.clickImpulse * 0.4
        const intensity = cfg.glowIntensity * hoverBoost * clickBoost
        const glowRadius = radius * cfg.glowSize * (1 + this.hoverT * 0.12)

        const grad = ctx.createRadialGradient(
            this.cx, this.cy, radius * 0.2,
            this.cx, this.cy, glowRadius,
        )
        grad.addColorStop(0, rgba(cfg.glow, intensity * 0.7))
        grad.addColorStop(0.35, rgba(cfg.glow, intensity * 0.35))
        grad.addColorStop(0.7, rgba(cfg.glow, intensity * 0.08))
        grad.addColorStop(1, rgba(cfg.glow, 0))

        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.arc(this.cx, this.cy, glowRadius, 0, TAU)
        ctx.fill()
    }

    /** Main orb body — organic boundary filled with radial gradient. */
    private drawOrbFill(orbPath: Path2D, radius: number): void {
        const ctx = this.ctx
        const cfg = this.currentConfig

        const ox = Math.sin(this.time * 0.28) * radius * 0.1
        const oy = Math.cos(this.time * 0.19) * radius * 0.07

        const hb = 1 + this.hoverT * 0.12
        const grad = ctx.createRadialGradient(
            this.cx + ox, this.cy + oy, 0,
            this.cx, this.cy, radius,
        )
        grad.addColorStop(0, rgba(cfg.primary, clamp01(0.88 * hb)))
        grad.addColorStop(0.3, rgba(cfg.primary, clamp01(0.6 * hb)))
        grad.addColorStop(0.58, rgba(cfg.secondary, clamp01(0.38 * hb)))
        grad.addColorStop(0.82, rgba(cfg.tertiary, 0.18))
        grad.addColorStop(1, rgba(cfg.tertiary, 0.03))

        ctx.fillStyle = grad
        ctx.fill(orbPath)
    }

    /** Screen-blended color light pools orbiting inside the orb. */
    private drawInternalLights(orbPath: Path2D, radius: number): void {
        const ctx = this.ctx
        const cfg = this.currentConfig

        ctx.save()
        ctx.clip(orbPath)
        ctx.globalCompositeOperation = 'screen'

        const hbOp = 1 + this.hoverT * 0.3
        const hbSpeed = 1 + this.hoverT * 0.25

        const op = this.orbitPhase
        this.drawLightBlob(
            cfg.primary, radius * 0.52,
            cfg.orbitRadius * radius,
            op * hbSpeed, 0,
            cfg.blobOpacity * 0.4 * hbOp,
        )
        this.drawLightBlob(
            cfg.secondary, radius * 0.42,
            cfg.orbitRadius * radius * 1.1,
            -op * 0.7 * hbSpeed, TAU * 0.33,
            cfg.blobOpacity * 0.35 * hbOp,
        )
        this.drawLightBlob(
            cfg.tertiary, radius * 0.34,
            cfg.orbitRadius * radius * 0.85,
            op * 1.3 * hbSpeed, TAU * 0.66,
            cfg.blobOpacity * 0.3 * hbOp,
        )

        ctx.restore()
    }

    /** Single soft radial-gradient blob at an orbiting position. */
    private drawLightBlob(
        color: RGB,
        size: number,
        orbitDist: number,
        angle: number,
        phase: number,
        alpha: number,
    ): void {
        const bx = this.cx + Math.cos(angle + phase) * orbitDist
        const by = this.cy + Math.sin(angle + phase) * orbitDist

        const grad = this.ctx.createRadialGradient(bx, by, 0, bx, by, size)
        grad.addColorStop(0, rgba(color, alpha))
        grad.addColorStop(0.45, rgba(color, alpha * 0.45))
        grad.addColorStop(1, rgba(color, 0))

        this.ctx.fillStyle = grad
        this.ctx.beginPath()
        this.ctx.arc(bx, by, size, 0, TAU)
        this.ctx.fill()
    }

    /** Rotating conic highlight — subtle radar-sweep feel. */
    private drawConicSweep(orbPath: Path2D): void {
        const ctx = this.ctx
        const cfg = this.currentConfig
        const energy = cfg.energy + this.hoverT * 0.15
        if (energy < 0.05) return

        ctx.save()
        ctx.clip(orbPath)
        ctx.globalCompositeOperation = 'screen'

        const a = this.morphPhase * 0.35
        const intensity = 0.04 * energy

        const conic = ctx.createConicGradient(a, this.cx, this.cy)
        conic.addColorStop(0, `rgba(255,255,255,0)`)
        conic.addColorStop(0.04, rgba([255, 255, 255], intensity))
        conic.addColorStop(0.09, `rgba(255,255,255,0)`)
        conic.addColorStop(0.45, `rgba(255,255,255,0)`)
        conic.addColorStop(0.49, rgba([255, 255, 255], intensity * 0.6))
        conic.addColorStop(0.54, `rgba(255,255,255,0)`)
        conic.addColorStop(1, `rgba(255,255,255,0)`)

        ctx.fillStyle = conic
        ctx.fill(orbPath)
        ctx.restore()
    }

    /** Soft luminous stroke around the organic boundary — intensifies on hover. */
    private drawEdgeGlow(orbPath: Path2D): void {
        const ctx = this.ctx
        const cfg = this.currentConfig
        const energy = cfg.energy + this.hoverT * 0.2
        const a = 0.06 + energy * 0.12 + this.clickImpulse * 0.15

        ctx.save()
        ctx.shadowBlur = 18 + energy * 14 + this.hoverT * 8
        ctx.shadowColor = rgba(cfg.glow, 0.25 + energy * 0.18 + this.hoverT * 0.12)

        ctx.lineWidth = 1.5 + this.hoverT * 0.8
        ctx.strokeStyle = rgba(cfg.glow, a)
        ctx.stroke(orbPath)

        /* Second pass: inner glow on hover */
        if (this.hoverT > 0.01) {
            ctx.shadowBlur = 6 + this.hoverT * 10
            ctx.shadowColor = rgba(cfg.primary, this.hoverT * 0.15)
            ctx.lineWidth = 0.5
            ctx.strokeStyle = rgba(cfg.primary, this.hoverT * 0.08)
            ctx.stroke(orbPath)
        }

        ctx.restore()
    }

    /** Bright highlight at the center — pulses with click. */
    private drawCore(radius: number): void {
        const ctx = this.ctx
        const cfg = this.currentConfig
        const coreR = radius * cfg.coreSize
        const pulse = 1 + Math.sin(this.breathPhase * 1.5) * 0.2
        const hoverPulse = 1 + this.hoverT * 0.4
        const clickFlare = 1 + this.clickImpulse * 1.5
        const r = coreR * pulse * hoverPulse * clickFlare

        const intensity = cfg.coreIntensity * (1 + this.hoverT * 0.25)

        const grad = ctx.createRadialGradient(
            this.cx, this.cy, 0,
            this.cx, this.cy, r * 4,
        )
        grad.addColorStop(0, rgba([255, 252, 245], clamp01(intensity * 0.9)))
        grad.addColorStop(0.15, rgba(cfg.primary, clamp01(intensity * 0.5)))
        grad.addColorStop(0.5, rgba(cfg.primary, intensity * 0.12))
        grad.addColorStop(1, rgba(cfg.primary, 0))

        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.arc(this.cx, this.cy, r * 4, 0, TAU)
        ctx.fill()
    }

    /** Expanding ring emanations. */
    private drawPulseRings(radius: number): void {
        const ctx = this.ctx

        for (const ring of this.rings) {
            const p = ring.progress
            const r = radius * (0.15 + p * 1.2)
            const alpha = (1 - p * p) * ring.opacity

            ctx.beginPath()
            ctx.arc(this.cx, this.cy, r, 0, TAU)
            ctx.lineWidth = (1.5 - p * 0.8) * (1 + this.hoverT * 0.3)
            ctx.strokeStyle = rgba(this.currentConfig.glow, alpha)
            ctx.stroke()
        }
    }

    /** Tiny sparkle dots orbiting near the orb edge. */
    private drawParticles(radius: number): void {
        const ctx = this.ctx
        const cfg = this.currentConfig
        const energyMod = cfg.energy + this.hoverT * 0.25

        for (const p of this.particles) {
            const r = radius * p.radiusFactor * (1 + this.hoverT * 0.06)
            const x = this.cx + r * Math.cos(p.angle)
            const y = this.cy + r * Math.sin(p.angle)
            const twinkle = 0.5 + 0.5 * Math.sin(this.time * 2.5 + p.phase)
            const alpha = p.baseOpacity * twinkle * energyMod

            const sz = p.size * cfg.particleSize * 0.5 * (1 + this.hoverT * 0.2)

            const grad = ctx.createRadialGradient(x, y, 0, x, y, sz * 2)
            grad.addColorStop(0, rgba(cfg.primary, alpha * 0.8))
            grad.addColorStop(0.5, rgba(cfg.primary, alpha * 0.2))
            grad.addColorStop(1, rgba(cfg.primary, 0))

            ctx.fillStyle = grad
            ctx.beginPath()
            ctx.arc(x, y, sz * 2, 0, TAU)
            ctx.fill()
        }
    }

    /** Momentary white flash overlay on click. */
    private drawClickFlash(radius: number): void {
        if (this.clickImpulse < 0.01) return
        const ctx = this.ctx
        const cfg = this.currentConfig

        const grad = ctx.createRadialGradient(
            this.cx, this.cy, 0,
            this.cx, this.cy, radius * 0.8,
        )
        const a = this.clickImpulse * 0.12
        grad.addColorStop(0, rgba([255, 252, 245], a))
        grad.addColorStop(0.4, rgba(cfg.primary, a * 0.4))
        grad.addColorStop(1, rgba(cfg.primary, 0))

        ctx.globalCompositeOperation = 'screen'
        ctx.fillStyle = grad
        ctx.beginPath()
        ctx.arc(this.cx, this.cy, radius * 0.8, 0, TAU)
        ctx.fill()
        ctx.globalCompositeOperation = 'source-over'
    }
}
