/**
 * Canvas 2D rendering with 3D perspective projection.
 *
 * Draws depth-sorted layers: ambient glow, energy rings, connections,
 * flow particles, data packets (thinking-state glyphs), neurons, and core.
 * All positions are pre-projected from 3D; depth controls opacity/size fog.
 */
import type {
    NeuralNode,
    Connection,
    FlowParticle,
    DataPacket,
    EnergyRing,
    StateConfig,
    RGB,
} from './types'

type Ctx = CanvasRenderingContext2D

function rgba(c: RGB, a: number): string {
    return `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${Math.min(Math.max(a, 0), 1).toFixed(3)})`
}

function lerpColor(a: RGB, b: RGB, t: number): RGB {
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

/** Depth fog: further nodes are more transparent. */
function depthAlpha(depth: number, dof: number): number {
    return 1 - depth * dof
}

/*  Ambient glow  */

function drawGlow(ctx: Ctx, core: NeuralNode, cfg: StateConfig, audioLevel: number, w: number, h: number): void {
    const r = Math.max(w, h) * (0.28 + cfg.glowIntensity * 0.2 + audioLevel * 0.08)
    const grad = ctx.createRadialGradient(core.projected.x, core.projected.y, 0, core.projected.x, core.projected.y, r)
    grad.addColorStop(0, rgba(cfg.glow, cfg.glowIntensity * 0.3 + audioLevel * 0.06))
    grad.addColorStop(0.35, rgba(cfg.glow, cfg.glowIntensity * 0.06))
    grad.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = grad
    ctx.fillRect(0, 0, w, h)
}

/*  Energy rings  */

function drawRings(ctx: Ctx, rings: EnergyRing[], core: NeuralNode, cfg: StateConfig): void {
    for (const ring of rings) {
        ctx.beginPath()
        ctx.arc(core.projected.x, core.projected.y, ring.radius, 0, Math.PI * 2)
        ctx.strokeStyle = rgba(cfg.primary, ring.opacity)
        ctx.lineWidth = 1.2
        ctx.stroke()
    }
}

/*  Connections  */

function connPoint(a: NeuralNode, b: NeuralNode, t: number): { x: number; y: number; depth: number } {
    // Slightly curved via perpendicular midpoint offset
    const mx = (a.projected.x + b.projected.x) / 2
    const my = (a.projected.y + b.projected.y) / 2
    const dx = b.projected.x - a.projected.x
    const dy = b.projected.y - a.projected.y
    const curvature = 0.1
    const cpx = mx - dy * curvature
    const cpy = my + dx * curvature
    const it = 1 - t
    return {
        x: it * it * a.projected.x + 2 * it * t * cpx + t * t * b.projected.x,
        y: it * it * a.projected.y + 2 * it * t * cpy + t * t * b.projected.y,
        depth: a.depth + (b.depth - a.depth) * t,
    }
}

function drawConnections(ctx: Ctx, nodes: NeuralNode[], conns: Connection[], cfg: StateConfig, time: number): void {
    for (const conn of conns) {
        const a = nodes[conn.from]
        const b = nodes[conn.to]
        const avgAct = (a.activation + b.activation) / 2
        const avgDepth = (a.depth + b.depth) / 2
        const dAlpha = depthAlpha(avgDepth, cfg.depthOfField)
        // Ensure a visible baseline even at low activation
        const alpha = cfg.connectionAlpha * (0.45 + avgAct * 0.55) * conn.strength * dAlpha

        if (alpha < 0.005) continue

        const mx = (a.projected.x + b.projected.x) / 2
        const my = (a.projected.y + b.projected.y) / 2
        const dx = b.projected.x - a.projected.x
        const dy = b.projected.y - a.projected.y
        const cpx = mx - dy * 0.1
        const cpy = my + dx * 0.1

        // Gradient along the connection from node-a color to node-b color
        const lineGrad = ctx.createLinearGradient(a.projected.x, a.projected.y, b.projected.x, b.projected.y)
        const cFrom = lerpColor(cfg.primary, cfg.secondary, a.activation)
        const cTo = lerpColor(cfg.primary, cfg.secondary, b.activation)
        lineGrad.addColorStop(0, rgba(cFrom, alpha * 0.7))
        lineGrad.addColorStop(0.5, rgba(lerpColor(cFrom, cTo, 0.5), alpha))
        lineGrad.addColorStop(1, rgba(cTo, alpha * 0.7))

        ctx.beginPath()
        ctx.moveTo(a.projected.x, a.projected.y)
        ctx.quadraticCurveTo(cpx, cpy, b.projected.x, b.projected.y)
        ctx.strokeStyle = lineGrad
        ctx.lineWidth = (0.6 + avgAct * 1.2) * (1 - avgDepth * 0.3)
        ctx.stroke()

        // Traveling pulse dot
        const pulseT = ((time * cfg.pulseSpeed + conn.pulseOffset) % 1 + 1) % 1
        const pp = connPoint(a, b, pulseT)
        const pAlpha = Math.min(alpha * (1.2 + avgAct * 0.8), 0.5)
        const pr = (2.5 + avgAct * 3) * (1 - pp.depth * 0.25)
        if (pr > 0.5) {
            const grad = ctx.createRadialGradient(pp.x, pp.y, 0, pp.x, pp.y, pr)
            grad.addColorStop(0, rgba(cfg.secondary, pAlpha))
            grad.addColorStop(1, 'rgba(0,0,0,0)')
            ctx.fillStyle = grad
            ctx.fillRect(pp.x - pr, pp.y - pr, pr * 2, pr * 2)
        }
    }
}

/*  Flow particles  */

function drawParticles(ctx: Ctx, nodes: NeuralNode[], conns: Connection[], particles: FlowParticle[], cfg: StateConfig): void {
    for (const p of particles) {
        const conn = conns[p.connIdx]
        if (!conn) continue
        const a = nodes[conn.from]
        const b = nodes[conn.to]
        const pt = connPoint(a, b, Math.max(0, Math.min(1, p.t)))
        const dAlpha = depthAlpha(pt.depth, cfg.depthOfField)
        const edgeFade = Math.min(p.t * 4, (1 - p.t) * 4, 1)
        const alpha = edgeFade * 0.75 * dAlpha

        if (alpha < 0.01) continue

        const sz = p.size * (1 - pt.depth * 0.25)

        // Soft glow (smaller radius)
        const gr = sz * 2.2
        const grad = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, gr)
        grad.addColorStop(0, rgba(cfg.secondary, alpha * 0.35))
        grad.addColorStop(1, 'rgba(0,0,0,0)')
        ctx.fillStyle = grad
        ctx.fillRect(pt.x - gr, pt.y - gr, gr * 2, gr * 2)

        // Bright dot core
        ctx.beginPath()
        ctx.arc(pt.x, pt.y, sz, 0, Math.PI * 2)
        ctx.fillStyle = rgba(cfg.secondary, alpha * 0.9)
        ctx.fill()
    }
}

/*  Data packets (thinking)  */

function drawDataPackets(ctx: Ctx, nodes: NeuralNode[], conns: Connection[], packets: DataPacket[], cfg: StateConfig): void {
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'

    for (const pk of packets) {
        const conn = conns[pk.connIdx]
        if (!conn) continue
        const a = nodes[conn.from]
        const b = nodes[conn.to]
        const pt = connPoint(a, b, Math.max(0, Math.min(1, pk.t)))
        const dAlpha = depthAlpha(pt.depth, cfg.depthOfField)
        const alpha = pk.opacity * dAlpha

        if (alpha < 0.02) continue

        const sz = pk.size * (1 - pt.depth * 0.3)

        // Background glow behind text
        const gr = sz * 2
        const grad = ctx.createRadialGradient(pt.x, pt.y, 0, pt.x, pt.y, gr)
        grad.addColorStop(0, rgba(pk.color, alpha * 0.35))
        grad.addColorStop(1, 'rgba(0,0,0,0)')
        ctx.fillStyle = grad
        ctx.fillRect(pt.x - gr, pt.y - gr, gr * 2, gr * 2)

        // Glyph text
        ctx.font = `bold ${sz | 0}px monospace`
        ctx.fillStyle = rgba(pk.color, alpha * 0.9)
        ctx.fillText(pk.glyph, pt.x, pt.y)
    }
}

/*  Neuron nodes (depth-sorted)  */

function drawNodes(ctx: Ctx, sorted: NeuralNode[], cfg: StateConfig): void {
    // sorted = back-to-front order; skip core (drawn separately)
    for (const node of sorted) {
        if (node.layer === 0) continue
        const { projected: pos, radius, activation, depth, layer } = node
        const dAlpha = depthAlpha(depth, cfg.depthOfField)

        // Layer-based color: inner layers lean primary, outer layers lean tertiary
        const layerT = Math.min(layer / 4, 1)
        const baseColor = lerpColor(cfg.primary, cfg.tertiary, layerT * 0.5)
        const color = lerpColor(baseColor, cfg.secondary, activation)

        // Subtle halo (reduced from 3-6x to 1.8-3x)
        const glowR = radius * (1.8 + activation * 1.5)
        if (glowR > 0.5) {
            const gr = ctx.createRadialGradient(pos.x, pos.y, radius * 0.3, pos.x, pos.y, glowR)
            gr.addColorStop(0, rgba(color, activation * 0.25 * dAlpha))
            gr.addColorStop(1, 'rgba(0,0,0,0)')
            ctx.fillStyle = gr
            ctx.fillRect(pos.x - glowR, pos.y - glowR, glowR * 2, glowR * 2)
        }

        // Body with subtle radial gradient
        const bodyGrad = ctx.createRadialGradient(pos.x, pos.y, 0, pos.x, pos.y, radius)
        bodyGrad.addColorStop(0, rgba(lerpColor(color, [255, 255, 255], 0.2), (0.5 + activation * 0.45) * dAlpha))
        bodyGrad.addColorStop(0.7, rgba(color, (0.4 + activation * 0.5) * dAlpha))
        bodyGrad.addColorStop(1, rgba(color, (0.2 + activation * 0.35) * dAlpha))
        ctx.beginPath()
        ctx.arc(pos.x, pos.y, radius, 0, Math.PI * 2)
        ctx.fillStyle = bodyGrad
        ctx.fill()

        // Thin rim stroke for definition
        ctx.strokeStyle = rgba(color, (0.15 + activation * 0.3) * dAlpha)
        ctx.lineWidth = 0.5
        ctx.stroke()
    }
}

/*  Core node  */

function drawCore(ctx: Ctx, core: NeuralNode, cfg: StateConfig, time: number, audioLevel: number): void {
    const { projected: pos, radius, activation } = core
    const brightness = 0.5 + activation * 0.25 + audioLevel * 0.12

    // Compact halo (reduced from 5-11x to 3-5x radius)
    const hr = radius * (3 + activation * 1.5 + audioLevel * 1)
    const hg = ctx.createRadialGradient(pos.x, pos.y, radius * 0.5, pos.x, pos.y, hr)
    hg.addColorStop(0, rgba(cfg.glow, brightness * 0.25))
    hg.addColorStop(0.5, rgba(cfg.glow, brightness * 0.05))
    hg.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = hg
    ctx.fillRect(pos.x - hr, pos.y - hr, hr * 2, hr * 2)

    // Inner glow (tighter)
    const igr = radius * 1.8
    const ig = ctx.createRadialGradient(pos.x, pos.y, 0, pos.x, pos.y, igr)
    ig.addColorStop(0, rgba(cfg.primary, brightness * 0.55))
    ig.addColorStop(0.6, rgba(lerpColor(cfg.primary, cfg.secondary, 0.5), brightness * 0.12))
    ig.addColorStop(1, 'rgba(0,0,0,0)')
    ctx.fillStyle = ig
    ctx.fillRect(pos.x - igr, pos.y - igr, igr * 2, igr * 2)

    // Body with gradient
    ctx.beginPath()
    ctx.arc(pos.x, pos.y, radius, 0, Math.PI * 2)
    const cg = ctx.createRadialGradient(pos.x, pos.y, 0, pos.x, pos.y, radius)
    cg.addColorStop(0, rgba([255, 255, 255], brightness * 0.85))
    cg.addColorStop(0.3, rgba(cfg.primary, brightness * 0.8))
    cg.addColorStop(1, rgba(cfg.secondary, brightness * 0.4))
    ctx.fillStyle = cg
    ctx.fill()

    // Rim stroke
    ctx.strokeStyle = rgba(cfg.primary, 0.2 + activation * 0.15)
    ctx.lineWidth = 0.8
    ctx.stroke()

    // Pulsing ring
    const pr = radius * (1.6 + Math.sin(time * 3) * 0.25 + audioLevel * 0.3)
    ctx.beginPath()
    ctx.arc(pos.x, pos.y, pr, 0, Math.PI * 2)
    ctx.strokeStyle = rgba(cfg.primary, 0.1 + activation * 0.15)
    ctx.lineWidth = 0.8
    ctx.stroke()
}

/*  Full render pass  */

export function renderFrame(
    ctx: Ctx,
    nodes: NeuralNode[],
    connections: Connection[],
    particles: FlowParticle[],
    dataPackets: DataPacket[],
    rings: EnergyRing[],
    cfg: StateConfig,
    time: number,
    audioLevel: number,
    w: number,
    h: number,
    dpr: number,
): void {
    ctx.clearRect(0, 0, w * dpr, h * dpr)
    ctx.save()
    ctx.scale(dpr, dpr)

    // Sort nodes back-to-front for depth ordering
    const sorted = [...nodes].sort((a, b) => b.depth - a.depth)

    drawGlow(ctx, nodes[0], cfg, audioLevel, w, h)
    drawRings(ctx, rings, nodes[0], cfg)
    drawConnections(ctx, nodes, connections, cfg, time)
    drawParticles(ctx, nodes, connections, particles, cfg)
    if (dataPackets.length > 0) {
        drawDataPackets(ctx, nodes, connections, dataPackets, cfg)
    }
    drawNodes(ctx, sorted, cfg)
    drawCore(ctx, nodes[0], cfg, time, audioLevel)

    ctx.restore()
}
