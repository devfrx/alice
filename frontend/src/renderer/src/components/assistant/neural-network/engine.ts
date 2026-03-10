/**
 * NeuralEngine  3D neural network orchestrator.
 *
 * Manages the animation loop with:
 * - Per-state transition easing (elastic, bounce, sharp, etc.)
 * - Smooth 3D rotation accumulation
 * - Data packet lifecycle for thinking state
 * - Perspective projection parameters
 */
import type {
    OrbState,
    NeuralNode,
    Connection,
    FlowParticle,
    DataPacket,
    EnergyRing,
    StateConfig,
    RGB,
    TransitionConfig,
} from './types'
import { STATE_CONFIGS, TRANSITION_CONFIGS } from './config'
import { createNodes, createConnections } from './layout'
import {
    updateNodes,
    updateActivations,
    updateParticles,
    updateDataPackets,
    updateRings,
} from './physics'
import { renderFrame } from './draw'

/*  Config interpolation  */

function lerpConfig(a: StateConfig, b: StateConfig, t: number): StateConfig {
    const l = (x: number, y: number): number => x + (y - x) * t
    const lc = (x: RGB, y: RGB): RGB => [l(x[0], y[0]), l(x[1], y[1]), l(x[2], y[2])]
    return {
        primary: lc(a.primary, b.primary),
        secondary: lc(a.secondary, b.secondary),
        tertiary: lc(a.tertiary, b.tertiary),
        glow: lc(a.glow, b.glow),
        nodeFloat: l(a.nodeFloat, b.nodeFloat),
        nodeFloatSpeed: l(a.nodeFloatSpeed, b.nodeFloatSpeed),
        activationSpeed: l(a.activationSpeed, b.activationSpeed),
        activationMin: l(a.activationMin, b.activationMin),
        activationMax: l(a.activationMax, b.activationMax),
        activationPattern: t < 0.5 ? a.activationPattern : b.activationPattern,
        connectionAlpha: l(a.connectionAlpha, b.connectionAlpha),
        pulseSpeed: l(a.pulseSpeed, b.pulseSpeed),
        particleCount: Math.round(l(a.particleCount, b.particleCount)),
        particleSpeed: l(a.particleSpeed, b.particleSpeed),
        particleSize: l(a.particleSize, b.particleSize),
        glowIntensity: l(a.glowIntensity, b.glowIntensity),
        energy: l(a.energy, b.energy),
        nodeSpread: l(a.nodeSpread, b.nodeSpread),
        ringFrequency: l(a.ringFrequency, b.ringFrequency),
        rotationSpeedX: l(a.rotationSpeedX, b.rotationSpeedX),
        rotationSpeedY: l(a.rotationSpeedY, b.rotationSpeedY),
        rotationSpeedZ: l(a.rotationSpeedZ, b.rotationSpeedZ),
        depthOfField: l(a.depthOfField, b.depthOfField),
        dataPacketCount: Math.round(l(a.dataPacketCount, b.dataPacketCount)),
        dataPacketSpeed: l(a.dataPacketSpeed, b.dataPacketSpeed),
    }
}

/*  Easing functions  */

function easeInOut(t: number): number {
    return t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2
}

function easeOut(t: number): number {
    return 1 - (1 - t) ** 3
}

function easeIn(t: number): number {
    return t * t * t
}

function elastic(t: number): number {
    if (t === 0 || t === 1) return t
    return -(2 ** (10 * t - 10)) * Math.sin((t * 10 - 10.75) * ((2 * Math.PI) / 3))
}

function elasticOut(t: number): number {
    return 1 - elastic(1 - t)
}

function bounce(t: number): number {
    const n1 = 7.5625
    const d1 = 2.75
    if (t < 1 / d1) return n1 * t * t
    if (t < 2 / d1) { t -= 1.5 / d1; return n1 * t * t + 0.75 }
    if (t < 2.5 / d1) { t -= 2.25 / d1; return n1 * t * t + 0.9375 }
    t -= 2.625 / d1
    return n1 * t * t + 0.984375
}

function sharp(t: number): number {
    return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
}

function applyEasing(t: number, type: TransitionConfig['easing']): number {
    switch (type) {
        case 'easeInOut': return easeInOut(t)
        case 'easeOut':   return easeOut(t)
        case 'easeIn':    return easeIn(t)
        case 'elastic':   return elasticOut(t)
        case 'bounce':    return bounce(t)
        case 'sharp':     return sharp(t)
    }
}

/*  Engine  */

export class NeuralEngine {
    private canvas!: HTMLCanvasElement
    private ctx!: CanvasRenderingContext2D
    private nodes: NeuralNode[] = []
    private connections: Connection[] = []
    private particles: FlowParticle[] = []
    private dataPackets: DataPacket[] = []
    private rings: EnergyRing[] = []

    private state: OrbState = 'idle'
    private prevConfig: StateConfig = { ...STATE_CONFIGS.idle }
    private targetConfig: StateConfig = STATE_CONFIGS.idle
    private currentConfig: StateConfig = { ...STATE_CONFIGS.idle }
    private transitionT = 1
    private transitionCfg: TransitionConfig = TRANSITION_CONFIGS.idle

    private audioLevel = 0
    private compact: boolean
    private width = 0
    private height = 0
    private dpr = 1
    private cx = 0
    private cy = 0
    private fov = 300
    private time = 0
    private animId = 0
    private lastFrame = 0
    private resizeObs: ResizeObserver | null = null

    // Accumulated rotation angles
    private rotX = 0
    private rotY = 0
    private rotZ = 0

    constructor(compact: boolean) {
        this.compact = compact
        this.fov = compact ? 220 : 350
    }

    init(canvas: HTMLCanvasElement): void {
        this.canvas = canvas
        this.ctx = canvas.getContext('2d')!
        this.dpr = Math.min(window.devicePixelRatio || 1, 2)
        this.resize()
        this.buildNetwork()
        this.lastFrame = performance.now()

        const parent = canvas.parentElement
        if (parent) {
            this.resizeObs = new ResizeObserver(() => this.handleResize())
            this.resizeObs.observe(parent)
        }

        this.loop()
    }

    private resize(): void {
        const parent = this.canvas.parentElement
        if (!parent) return
        const rect = parent.getBoundingClientRect()
        this.width = rect.width
        this.height = rect.height
        this.canvas.width = this.width * this.dpr
        this.canvas.height = this.height * this.dpr
        this.canvas.style.width = `${this.width}px`
        this.canvas.style.height = `${this.height}px`
        this.cx = this.width / 2
        this.cy = this.height / 2
    }

    private buildNetwork(): void {
        const scale = this.compact ? 0.7 : 1.1
        this.nodes = createNodes(scale, this.compact)
        this.connections = createConnections(this.nodes, this.compact)
        this.particles = []
        this.dataPackets = []
        this.rings = []
    }

    setState(newState: OrbState): void {
        if (newState === this.state) return
        this.state = newState
        this.prevConfig = { ...this.currentConfig }
        this.targetConfig = STATE_CONFIGS[newState]
        this.transitionCfg = TRANSITION_CONFIGS[newState]
        this.transitionT = 0
    }

    setAudioLevel(level: number): void {
        this.audioLevel += (level - this.audioLevel) * 0.3
    }

    private handleResize(): void {
        this.resize()
    }

    private loop = (): void => {
        this.animId = requestAnimationFrame(this.loop)
        const now = performance.now()
        const dt = Math.min((now - this.lastFrame) / 1000, 0.05)
        this.lastFrame = now
        this.time += dt

        // State transition with per-state easing
        if (this.transitionT < 1) {
            this.transitionT = Math.min(
                this.transitionT + dt / this.transitionCfg.duration,
                1,
            )
            const eased = applyEasing(this.transitionT, this.transitionCfg.easing)
            this.currentConfig = lerpConfig(this.prevConfig, this.targetConfig, eased)
        }

        const cfg = this.currentConfig

        // Accumulate rotation
        this.rotX += cfg.rotationSpeedX * dt
        this.rotY += cfg.rotationSpeedY * dt
        this.rotZ += cfg.rotationSpeedZ * dt

        // Physics
        updateActivations(this.nodes, cfg, this.time, this.audioLevel)
        updateNodes(
            this.nodes, cfg, this.time, dt, this.audioLevel,
            this.rotX, this.rotY, this.rotZ,
            this.cx, this.cy, this.fov,
        )
        updateParticles(this.particles, this.connections, cfg, dt)
        updateDataPackets(this.dataPackets, this.connections, cfg, dt)
        updateRings(this.rings, cfg, dt, Math.max(this.width, this.height) * 0.5)

        // Render
        renderFrame(
            this.ctx,
            this.nodes,
            this.connections,
            this.particles,
            this.dataPackets,
            this.rings,
            cfg,
            this.time,
            this.audioLevel,
            this.width,
            this.height,
            this.dpr,
        )
    }

    destroy(): void {
        cancelAnimationFrame(this.animId)
        this.resizeObs?.disconnect()
        this.resizeObs = null
    }
}
