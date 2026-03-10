/**
 * 3D spherical node layout and connection generation.
 *
 * Nodes are placed on concentric spherical shells with organic jitter.
 * Generates a dense, multilayer network with cross-layer connections.
 */
import type { NeuralNode, Connection } from './types'

/** Place nodes on concentric spherical shells for a 3D brain-like structure. */
export function createNodes(scale: number, compact: boolean): NeuralNode[] {
    const nodes: NeuralNode[] = []
    let id = 0

    const add = (layer: number, theta: number, phi: number, dist: number, rBase: number): void => {
        const jitter = (Math.random() - 0.5) * 0.1 * dist
        const d = dist + jitter
        const x = d * Math.sin(phi) * Math.cos(theta)
        const y = d * Math.sin(phi) * Math.sin(theta)
        const z = d * Math.cos(phi)
        const r = scale * (rBase + (Math.random() - 0.5) * rBase * 0.3)

        nodes.push({
            id: id++,
            pos3d: { x, y, z },
            basePos3d: { x, y, z },
            projected: { x: 0, y: 0 },
            depth: 0,
            radius: r,
            baseRadius: r,
            activation: layer === 0 ? 0.3 : 0,
            targetActivation: 0,
            layer,
            phase: Math.random() * Math.PI * 2,
        })
    }

    // Layer 0: core (single node at center)
    add(0, 0, 0, 0, compact ? 8 : 10)

    // Layer 1: inner shell
    const n1 = compact ? 6 : 8
    for (let i = 0; i < n1; i++) {
        const theta = (i / n1) * Math.PI * 2 + (Math.random() - 0.5) * 0.3
        const phi = Math.PI * 0.3 + Math.random() * Math.PI * 0.4
        add(1, theta, phi, scale * 28, compact ? 4.5 : 5.5)
    }

    // Layer 2: mid shell
    const n2 = compact ? 10 : 16
    for (let i = 0; i < n2; i++) {
        const theta = (i / n2) * Math.PI * 2 + (Math.random() - 0.5) * 0.25
        const phi = Math.PI * 0.2 + (i % 3) * Math.PI * 0.25 + Math.random() * 0.2
        add(2, theta, phi, scale * 50, compact ? 3 : 3.5)
    }

    // Layer 3: outer shell
    const n3 = compact ? 8 : 14
    for (let i = 0; i < n3; i++) {
        const theta = (i / n3) * Math.PI * 2 + (Math.random() - 0.5) * 0.2
        const phi = Math.PI * 0.15 + (i % 4) * Math.PI * 0.2 + Math.random() * 0.15
        add(3, theta, phi, scale * 72, compact ? 2.5 : 2.8)
    }

    // Layer 4: outermost shell (full mode only)
    if (!compact) {
        const n4 = 12
        for (let i = 0; i < n4; i++) {
            const theta = (i / n4) * Math.PI * 2 + (Math.random() - 0.5) * 0.2
            const phi = Math.PI * 0.15 + (i % 3) * Math.PI * 0.3 + Math.random() * 0.1
            add(4, theta, phi, scale * 92, 2)
        }
    }

    return nodes
}

/** Build dense connections with cross-layer wiring for neural complexity. */
export function createConnections(nodes: NeuralNode[], compact: boolean): Connection[] {
    const conns: Connection[] = []
    const byLayer = (l: number): NeuralNode[] => nodes.filter((n) => n.layer === l)
    const dist3d = (a: NeuralNode, b: NeuralNode): number =>
        Math.hypot(
            a.basePos3d.x - b.basePos3d.x,
            a.basePos3d.y - b.basePos3d.y,
            a.basePos3d.z - b.basePos3d.z,
        )

    const addConn = (from: number, to: number, str: number): void => {
        conns.push({
            from,
            to,
            strength: str,
            pulseOffset: Math.random() * Math.PI * 2,
        })
    }

    const ring1 = byLayer(1)
    const ring2 = byLayer(2)
    const ring3 = byLayer(3)
    const ring4 = byLayer(4)

    // Core -> all layer-1 nodes
    for (const n of ring1) addConn(0, n.id, 0.8 + Math.random() * 0.2)

    // Layer 1 -> 2-3 nearest in layer 2
    for (const n of ring1) {
        const sorted = nearest(n, ring2, dist3d, 4)
        const count = 2 + (Math.random() > 0.3 ? 1 : 0)
        for (let i = 0; i < Math.min(count, sorted.length); i++) {
            addConn(n.id, sorted[i].id, 0.5 + Math.random() * 0.35)
        }
    }

    // Layer 2 -> 1-2 nearest in layer 3
    for (const n of ring2) {
        const sorted = nearest(n, ring3, dist3d, 3)
        const count = 1 + (Math.random() > 0.4 ? 1 : 0)
        for (let i = 0; i < Math.min(count, sorted.length); i++) {
            addConn(n.id, sorted[i].id, 0.35 + Math.random() * 0.3)
        }
    }

    // Layer 3 -> layer 4
    if (!compact && ring4.length > 0) {
        for (const n of ring3) {
            if (Math.random() < 0.55) {
                const sorted = nearest(n, ring4, dist3d, 2)
                if (sorted.length > 0) {
                    addConn(n.id, sorted[0].id, 0.25 + Math.random() * 0.25)
                }
            }
        }
    }

    // Intra-layer cross-connections (skip-one neighbors) for layers 1-2
    for (const ring of [ring1, ring2]) {
        for (let i = 0; i < ring.length; i++) {
            const j = (i + 2) % ring.length
            if (Math.random() > 0.35) {
                addConn(ring[i].id, ring[j].id, 0.18 + Math.random() * 0.2)
            }
        }
    }

    // A few long-range skip connections (layer 1 <-> 3) for neural feel
    for (const n of ring1) {
        if (Math.random() < 0.35) {
            const sorted = nearest(n, ring3, dist3d, 2)
            if (sorted.length > 0) {
                addConn(n.id, sorted[0].id, 0.15 + Math.random() * 0.15)
            }
        }
    }

    return conns
}

function nearest(
    ref: NeuralNode,
    candidates: NeuralNode[],
    distFn: (a: NeuralNode, b: NeuralNode) => number,
    count: number,
): NeuralNode[] {
    return [...candidates].sort((a, b) => distFn(ref, a) - distFn(ref, b)).slice(0, count)
}
