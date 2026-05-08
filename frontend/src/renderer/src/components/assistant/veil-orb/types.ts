/**
 * Type definitions for the Veil renderer.
 *
 * The Veil is a stack of translucent silk sheets drifting in front of a soft
 * pearl core, lit by a vertical light shaft from above. Each AL\CE state has
 * a distinct *mechanic* (audio pressure, helical twist, warm bloom, prism caustics)
 * not just a different palette — so the assistant feels alive and legible.
 */

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'

export type RGB = [number, number, number]

export interface VeilStateConfig {
    /* Palette */
    silkPrimary: RGB
    silkAccent: RGB
    warmLight: RGB
    coolLight: RGB

    /* Sheet motion */
    driftAmp: number
    driftSpeed: number
    warpAmp: number
    warpFreq: number
    warpSpeed: number
    twistAmount: number
    breath: number
    breathSpeed: number

    /* Sheet appearance */
    sheetCount: number
    sheetOpacity: number
    rimLight: number

    /* Backdrop */
    coreIntensity: number
    coreSize: number
    shaftIntensity: number
    shaftWidth: number
    haloIntensity: number

    /* Motes */
    moteCount: number
    moteDirection: -1 | 0 | 1
    moteSpeed: number

    /* State signatures */
    audioWave: number
    weave: number
    prism: number
    bloom: number

    /* Audio reactivity & global pacing */
    audioReactivity: number
    energy: number
    /** Silk-sheet width multiplier — 1.0 = default, >1 = wider spread (idle only). */
    veilSpread: number
}

export interface TransitionConfig {
    duration: number
}

export interface Mote {
    x: number
    y: number
    vx: number
    vy: number
    size: number
    phase: number
    life: number
    maxLife: number
}

export type FlourishKind =
    | 'ripple'   // listening — soft edge-pressure inhale
    | 'twist'    // thinking — helical snap
    | 'bloom'    // speaking — warm radial expansion
    | 'prism'    // processing — milky prism refraction
    | 'settle'   // → idle — amplitude damping fall
    | 'shock'    // click — radial outward ripple
    | 'glyph'    // tool-call — square stitch through the veils

export interface Flourish {
    kind: FlourishKind
    progress: number
    duration: number
    intensity: number
    /** Vertical anchor for shock / glyph (0 = top, 1 = bottom). */
    anchorY?: number
}
