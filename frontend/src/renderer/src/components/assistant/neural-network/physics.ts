/**
 * 3D physics, rotation, projection, and activation logic.
 *
 * Handles slow 3D rotation of the entire network, organic node floating,
 * perspective projection, state-specific activation patterns,
 * flow particles, data packets, and energy rings.
 */
import type {
    NeuralNode,
    Connection,
    FlowParticle,
    DataPacket,
    EnergyRing,
    StateConfig,
    Vec3,
} from './types'
import { DATA_GLYPHS } from './config'

/*  3D rotation  */

/** Rotate a Vec3 around X, Y, Z axes. */
function rotate3d(p: Vec3, ax: number, ay: number, az: number): Vec3 {
    // Rotate Y
    let x = p.x * Math.cos(ay) + p.z * Math.sin(ay)
    let z = -p.x * Math.sin(ay) + p.z * Math.cos(ay)
    let y = p.y

    // Rotate X
    const y2 = y * Math.cos(ax) - z * Math.sin(ax)
    const z2 = y * Math.sin(ax) + z * Math.cos(ax)
    y = y2
    z = z2

    // Rotate Z
    const x2 = x * Math.cos(az) - y * Math.sin(az)
    const y3 = x * Math.sin(az) + y * Math.cos(az)
    x = x2
    y = y3

    return { x, y, z }
}

/** Perspective project a 3D point onto 2D screen. Returns depth 0-1 (0=near). */
export function project(
    p: Vec3,
    cx: number,
    cy: number,
    fov: number,
): { x: number; y: number; scale: number; depth: number } {
    const d = fov + p.z
    const scale = Math.max(fov / d, 0.1)
    return {
        x: cx + p.x * scale,
        y: cy + p.y * scale,
        scale,
        depth: Math.max(0, Math.min(1, (p.z + fov) / (fov * 2))),
    }
}

/*  Node position & projection update  */

export function updateNodes(
    nodes: NeuralNode[],
    cfg: StateConfig,
    time: number,
    dt: number,
    audioLevel: number,
    rotX: number,
    rotY: number,
    rotZ: number,
    cx: number,
    cy: number,
    fov: number,
): void {
    for (const node of nodes) {
        // Organic floating offset in 3D space
        const t1 = time * cfg.nodeFloatSpeed
        const t2 = time * cfg.nodeFloatSpeed * 0.73
        const fx = Math.sin(t1 + node.phase) * cfg.nodeFloat + Math.sin(t2 * 1.3 + node.phase * 2.1) * cfg.nodeFloat * 0.3
        const fy = Math.cos(t2 + node.phase * 1.3) * cfg.nodeFloat + Math.cos(t1 * 0.8 + node.phase * 0.7) * cfg.nodeFloat * 0.25
        const fz = Math.sin(t1 * 0.6 + node.phase * 0.9) * cfg.nodeFloat * 0.4

        // Apply spread
        const sx = node.basePos3d.x * cfg.nodeSpread + fx
        const sy = node.basePos3d.y * cfg.nodeSpread + fy
        const sz = node.basePos3d.z * cfg.nodeSpread + fz

        // Rotate entire structure
        const rotated = rotate3d({ x: sx, y: sy, z: sz }, rotX, rotY, rotZ)

        // Smooth interpolation toward target 3D position
        const lr = Math.min(dt * 3.5, 1)
        node.pos3d.x += (rotated.x - node.pos3d.x) * lr
        node.pos3d.y += (rotated.y - node.pos3d.y) * lr
        node.pos3d.z += (rotated.z - node.pos3d.z) * lr

        // Perspective projection
        const proj = project(node.pos3d, cx, cy, fov)
        node.projected.x = proj.x
        node.projected.y = proj.y
        node.depth = proj.depth

        // Audio-reactive radius
        const audioBoost = node.layer === 0
            ? audioLevel * 0.7
            : audioLevel * Math.max(0.08, 0.3 - node.layer * 0.05)
        const targetR = node.baseRadius * proj.scale * (1 + audioBoost + cfg.energy * 0.12)
        node.radius += (targetR - node.radius) * Math.min(dt * 6, 1)

        // Activation interpolation
        node.activation += (node.targetActivation - node.activation) * Math.min(dt * cfg.activationSpeed, 1)
    }
}

/*  Activation patterns  */

export function updateActivations(
    nodes: NeuralNode[],
    cfg: StateConfig,
    time: number,
    audioLevel: number,
): void {
    const { activationMin: lo, activationMax: hi } = cfg

    for (const node of nodes) {
        let a = 0
        switch (cfg.activationPattern) {
            case 'gentle': {
                const wave = Math.sin(time * 0.4 + node.phase * 3) * 0.5 + 0.5
                a = lo + wave * (hi - lo)
                break
            }
            case 'cascade': {
                // Overlapping cascading waves radiating from center in 3D
                const d = Math.hypot(node.basePos3d.x, node.basePos3d.y, node.basePos3d.z)
                const w1 = Math.sin(time * 2.8 - d * 0.05 + node.phase * 0.4)
                const w2 = Math.sin(time * 2.0 - d * 0.035 + node.phase * 0.8)
                const w3 = Math.sin(time * 3.5 - d * 0.07)
                const wave = (w1 + w2 + w3) / 3 * 0.5 + 0.5
                a = lo + wave * (hi - lo)
                break
            }
            case 'rhythmic': {
                const pulse = Math.sin(time * 2.5) * 0.5 + 0.5
                const audio = audioLevel * 0.65
                a = lo + (pulse * 0.45 + audio) * (hi - lo) * (1 + Math.sin(node.phase) * 0.15)
                break
            }
            case 'wave': {
                const wave = Math.sin(time * 1.8 + node.phase * 2) * 0.5 + 0.5
                const audio = audioLevel * (node.layer <= 1 ? 0.85 : 0.35)
                a = lo + (wave * 0.35 + audio * 0.45 + 0.2) * (hi - lo)
                break
            }
            case 'systematic': {
                // Sweeping plane through 3D space
                const sweep = Math.sin(time * 1.5)
                const nz = node.basePos3d.z / 100
                const diff = Math.abs(sweep - nz)
                a = lo + Math.max(0, 1 - diff / 0.5) * (hi - lo)
                break
            }
        }
        node.targetActivation = Math.min(a, 1)
    }

    // Core always prominent
    nodes[0].targetActivation = Math.max(
        nodes[0].targetActivation,
        0.4 + audioLevel * 0.3 + cfg.energy * 0.2,
    )
}

/*  Flow particles  */

export function updateParticles(
    particles: FlowParticle[],
    connections: Connection[],
    cfg: StateConfig,
    dt: number,
): void {
    for (let i = particles.length - 1; i >= 0; i--) {
        particles[i].t += particles[i].speed * dt
        if (particles[i].t > 1 || particles[i].t < 0) particles.splice(i, 1)
    }

    while (particles.length < cfg.particleCount && connections.length > 0) {
        const ci = Math.floor(Math.random() * connections.length)
        const rev = Math.random() > 0.5
        particles.push({
            connIdx: ci,
            t: rev ? 1 : 0,
            speed: cfg.particleSpeed * (0.65 + Math.random() * 0.7) * (rev ? -1 : 1),
            size: cfg.particleSize * (0.7 + Math.random() * 0.6),
            reverse: rev,
        })
    }
}

/*  Data packets (thinking state)  */

export function updateDataPackets(
    packets: DataPacket[],
    connections: Connection[],
    cfg: StateConfig,
    dt: number,
): void {
    // Move packets
    for (let i = packets.length - 1; i >= 0; i--) {
        packets[i].t += packets[i].speed * dt
        packets[i].opacity = Math.min(
            packets[i].t * 5,
            (1 - packets[i].t) * 5,
            1,
        ) * 0.9
        if (packets[i].t > 1 || packets[i].t < 0) packets.splice(i, 1)
    }

    // Spawn to reach target
    const target = cfg.dataPacketCount
    while (packets.length < target && connections.length > 0) {
        const ci = Math.floor(Math.random() * connections.length)
        const rev = Math.random() > 0.5
        packets.push({
            connIdx: ci,
            t: rev ? 0.95 : 0.05,
            speed: cfg.dataPacketSpeed * (0.6 + Math.random() * 0.8) * (rev ? -1 : 1),
            glyph: DATA_GLYPHS[Math.floor(Math.random() * DATA_GLYPHS.length)],
            color: [
                cfg.tertiary[0] + Math.floor((Math.random() - 0.5) * 40),
                cfg.tertiary[1] + Math.floor((Math.random() - 0.5) * 40),
                cfg.tertiary[2] + Math.floor((Math.random() - 0.5) * 40),
            ],
            opacity: 0,
            size: 7 + Math.random() * 4,
        })
    }
}

/*  Energy rings  */

export function updateRings(
    rings: EnergyRing[],
    cfg: StateConfig,
    dt: number,
    maxRadius: number,
): void {
    for (let i = rings.length - 1; i >= 0; i--) {
        const r = rings[i]
        r.radius += r.speed * dt
        r.opacity = Math.max(0, 1 - r.radius / r.maxRadius) * 0.25 * cfg.glowIntensity
        if (r.radius >= r.maxRadius) rings.splice(i, 1)
    }

    if (cfg.ringFrequency > 0 && Math.random() < cfg.ringFrequency * dt) {
        rings.push({
            radius: 4,
            maxRadius,
            opacity: 0.25 * cfg.glowIntensity,
            speed: 25 + cfg.energy * 45,
        })
    }
}
