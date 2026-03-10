/**
 * Type definitions for the 3D neural network visualization engine.
 */

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'

export type RGB = [number, number, number]

export type ActivationPattern = 'gentle' | 'cascade' | 'rhythmic' | 'wave' | 'systematic'

export interface Vec3 {
    x: number
    y: number
    z: number
}

export interface Vec2 {
    x: number
    y: number
}

export interface NeuralNode {
    id: number
    pos3d: Vec3       // current 3D position (after rotation)
    basePos3d: Vec3   // base 3D position (before rotation)
    projected: Vec2   // 2D screen projection
    depth: number     // 0-1 normalized depth for sorting / fogging
    radius: number
    baseRadius: number
    activation: number
    targetActivation: number
    layer: number     // 0=core, 1=inner, 2=mid, 3=outer, 4=shell
    phase: number     // random phase offset for organic motion
}

export interface Connection {
    from: number
    to: number
    strength: number
    pulseOffset: number
}

export interface FlowParticle {
    connIdx: number
    t: number         // 0-1 progress along connection
    speed: number
    size: number
    reverse: boolean
}

/** Special data-processing packet visible during thinking state. */
export interface DataPacket {
    connIdx: number
    t: number
    speed: number
    glyph: string     // e.g. "01", "A3", ">>", etc.
    color: RGB
    opacity: number
    size: number
}

export interface EnergyRing {
    radius: number
    maxRadius: number
    opacity: number
    speed: number
}

export interface StateConfig {
    primary: RGB
    secondary: RGB
    tertiary: RGB
    glow: RGB
    nodeFloat: number
    nodeFloatSpeed: number
    activationSpeed: number
    activationMin: number
    activationMax: number
    activationPattern: ActivationPattern
    connectionAlpha: number
    pulseSpeed: number
    particleCount: number
    particleSpeed: number
    particleSize: number
    glowIntensity: number
    energy: number
    nodeSpread: number
    ringFrequency: number
    rotationSpeedX: number
    rotationSpeedY: number
    rotationSpeedZ: number
    depthOfField: number     // how much depth fogs distant nodes (0-1)
    dataPacketCount: number  // thinking-state data burst count
    dataPacketSpeed: number
}

/** Per-state transition configuration: different easing per destination state. */
export interface TransitionConfig {
    duration: number
    easing: 'easeInOut' | 'easeOut' | 'easeIn' | 'elastic' | 'bounce' | 'sharp'
}
