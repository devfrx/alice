/**
 * Per-state visual configurations for the Veil renderer.
 *
 * Palette stays in the cream / pearl / warm-amber family that defines AL\CE
 * and Continuum branding. Each state shifts hue subtly *and* changes the
 * dominant motion mechanic via the signature fields (audioWave, weave,
 * prism caustics, bloom).
 */
import type { OrbState, TransitionConfig, VeilStateConfig } from './types'

export const STATE_CONFIGS: Record<OrbState, VeilStateConfig> = {
    idle: {
        silkPrimary: [238, 228, 208],
        silkAccent: [218, 198, 168],
        warmLight: [248, 234, 208],
        coolLight: [188, 198, 210],

        driftAmp: 0.034,
        driftSpeed: 0.18,
        warpAmp: 0.032,
        warpFreq: 1.4,
        warpSpeed: 0.46,
        twistAmount: 0.025,
        breath: 0.024,
        breathSpeed: 0.68,

        sheetCount: 3,
        sheetOpacity: 0.28,
        rimLight: 0.20,

        coreIntensity: 0.50,
        coreSize: 0.17,
        shaftIntensity: 0.15,
        shaftWidth: 0.68,
        haloIntensity: 0.085,

        moteCount: 0,
        moteDirection: -1,
        moteSpeed: 0.08,

        audioWave: 0,
        weave: 0,
        prism: 0,
        bloom: 0,

        audioReactivity: 0.04,
        energy: 0.28,
        veilSpread: 1.92,
    },

    listening: {
        silkPrimary: [238, 220, 216],
        silkAccent: [238, 112, 102],
        warmLight: [255, 214, 202],
        coolLight: [210, 164, 160],

        driftAmp: 0.035,
        driftSpeed: 0.24,
        warpAmp: 0.038,
        warpFreq: 1.7,
        warpSpeed: 0.78,
        twistAmount: 0.032,
        breath: 0.024,
        breathSpeed: 1.0,

        sheetCount: 4,
        sheetOpacity: 0.28,
        rimLight: 0.22,

        coreIntensity: 0.52,
        coreSize: 0.16,
        shaftIntensity: 0.12,
        shaftWidth: 0.50,
        haloIntensity: 0.085,

        moteCount: 1,
        moteDirection: 0,
        moteSpeed: 0.12,

        audioWave: 1.0,
        weave: 0,
        prism: 0,
        bloom: 0,

        audioReactivity: 0.55,
        energy: 0.62,
        veilSpread: 1.0,
    },

    thinking: {
        silkPrimary: [218, 224, 232],
        silkAccent: [168, 188, 218],
        warmLight: [228, 224, 224],
        coolLight: [170, 188, 210],

        driftAmp: 0.045,
        driftSpeed: 0.34,
        warpAmp: 0.045,
        warpFreq: 1.9,
        warpSpeed: 0.92,
        twistAmount: 0.14,
        breath: 0.018,
        breathSpeed: 0.78,

        sheetCount: 4,
        sheetOpacity: 0.26,
        rimLight: 0.20,

        coreIntensity: 0.56,
        coreSize: 0.16,
        shaftIntensity: 0.13,
        shaftWidth: 0.52,
        haloIntensity: 0.075,

        moteCount: 3,
        moteDirection: 0,
        moteSpeed: 0.18,

        audioWave: 0,
        weave: 1.0,
        prism: 0,
        bloom: 0,

        audioReactivity: 0.05,
        energy: 0.85,
        veilSpread: 1.0,
    },

    speaking: {
        silkPrimary: [244, 228, 198],
        silkAccent: [232, 184, 128],
        warmLight: [254, 232, 200],
        coolLight: [200, 200, 200],

        driftAmp: 0.036,
        driftSpeed: 0.24,
        warpAmp: 0.04,
        warpFreq: 1.55,
        warpSpeed: 0.70,
        twistAmount: 0.03,
        breath: 0.038,
        breathSpeed: 1.25,

        sheetCount: 4,
        sheetOpacity: 0.30,
        rimLight: 0.24,

        coreIntensity: 0.66,
        coreSize: 0.20,
        shaftIntensity: 0.18,
        shaftWidth: 0.66,
        haloIntensity: 0.10,

        moteCount: 3,
        moteDirection: 1,
        moteSpeed: 0.20,

        audioWave: 0,
        weave: 0,
        prism: 0,
        bloom: 1.0,

        audioReactivity: 0.32,
        energy: 0.65,
        veilSpread: 1.0,
    },

    processing: {
        silkPrimary: [246, 245, 240],
        silkAccent: [232, 242, 248],
        warmLight: [252, 248, 236],
        coolLight: [202, 230, 244],

        driftAmp: 0.024,
        driftSpeed: 0.18,
        warpAmp: 0.030,
        warpFreq: 1.8,
        warpSpeed: 0.50,
        twistAmount: 0.045,
        breath: 0.016,
        breathSpeed: 0.76,

        sheetCount: 4,
        sheetOpacity: 0.27,
        rimLight: 0.28,

        coreIntensity: 0.54,
        coreSize: 0.145,
        shaftIntensity: 0.18,
        shaftWidth: 0.58,
        haloIntensity: 0.09,

        moteCount: 2,
        moteDirection: 1,
        moteSpeed: 0.22,

        audioWave: 0,
        weave: 0,
        prism: 1.0,
        bloom: 0,

        audioReactivity: 0.08,
        energy: 0.76,
        veilSpread: 1.92,
    },
}

/**
 * Transition durations per destination state.
 * Drives both config interpolation half-life and the duration of the
 * destination-specific flourish triggered on entry.
 */
export const TRANSITION_CONFIGS: Record<OrbState, TransitionConfig> = {
    idle: { duration: 1.4 },
    listening: { duration: 0.7 },
    thinking: { duration: 0.85 },
    speaking: { duration: 0.85 },
    processing: { duration: 0.7 },
}
