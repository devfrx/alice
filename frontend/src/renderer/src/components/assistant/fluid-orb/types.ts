/**
 * Type definitions for the fluid aurora orb visualization.
 *
 * Inspired by Anthropic/Supabase aesthetic: soft gradients,
 * organic morphing shapes, living color mixing.
 */

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'

export type RGB = [number, number, number]

export interface StateConfig {
    /** Gradient colors */
    primary: RGB
    secondary: RGB
    tertiary: RGB
    glow: RGB

    /** Organic shape morphing */
    morphSpeed: number
    turbulence: number

    /** Breathing pulse */
    breathSpeed: number
    breathAmount: number

    /** Internal light pool motion */
    orbitRadius: number
    orbitSpeed: number
    blobOpacity: number

    /** Ambient glow */
    glowIntensity: number
    glowSize: number

    /** Core highlight */
    coreIntensity: number
    coreSize: number

    /** Orbiting edge particles */
    particleCount: number
    particleSpeed: number
    particleSize: number

    /** Emanating ring pulses */
    pulseRate: number

    /** Microphone reactivity */
    audioReactivity: number

    /** Overall energy level (0-1) */
    energy: number
}

export interface TransitionConfig {
    /** Time in seconds */
    duration: number
}

export interface Particle {
    angle: number
    radiusFactor: number
    speed: number
    size: number
    baseOpacity: number
    phase: number
}

export interface PulseRing {
    progress: number
    speed: number
    opacity: number
}
