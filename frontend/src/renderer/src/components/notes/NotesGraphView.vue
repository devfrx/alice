<script setup lang="ts">
/**
 * Interactive Cytoscape.js graph visualization of the AL\CE note vault.
 * Nodes = notes, edges = wikilink references between notes.
 * Colored by folder, sized by incoming link count.
 * Uses cytoscape-cola for continuous force-directed physics (Obsidian-like).
 */
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import cytoscape from 'cytoscape'
import cytoscapeCola from 'cytoscape-cola'
import { useNotesStore } from '../../stores/notes'
import UiContextMenu from '../ui/UiContextMenu.vue'
import UiContextMenuItem from '../ui/UiContextMenuItem.vue'
import UiContextMenuDivider from '../ui/UiContextMenuDivider.vue'
import AppIcon from '../ui/AppIcon.vue'

// Register cola — guard against HMR double-registration
try {
    cytoscape.use(cytoscapeCola)
} catch {
    // Already registered
}

const store = useNotesStore()
const cyContainer = ref<HTMLDivElement | null>(null)
let cy: cytoscape.Core | null = null
let activeLayout: cytoscape.Layouts | null = null

// ---------------------------------------------------------------------------
// Context menu state
// ---------------------------------------------------------------------------

const ctxMenu = ref({ visible: false, x: 0, y: 0 })
const ctxNodeId = ref<string | null>(null)
const ctxNodeLabel = ref('')

function closeContextMenu(): void {
    ctxMenu.value.visible = false
    ctxNodeId.value = null
    ctxNodeLabel.value = ''
}

// ---------------------------------------------------------------------------
// Linking mode — connect two notes with a wikilink directly from the graph
// ---------------------------------------------------------------------------

const linkingSource = ref<string | null>(null)
const linkingSourceLabel = ref('')

function ctxStartLinking(): void {
    if (ctxNodeId.value) {
        linkingSource.value = ctxNodeId.value
        linkingSourceLabel.value = ctxNodeLabel.value
        if (cy) {
            cy.nodes().removeClass('linking-source')
            const node = cy.getElementById(ctxNodeId.value)
            if (node.length) node.addClass('linking-source')
        }
    }
    closeContextMenu()
}

function cancelLinking(): void {
    if (cy) cy.nodes().removeClass('linking-source')
    linkingSource.value = null
    linkingSourceLabel.value = ''
}

async function createWikilink(sourceId: string, targetId: string): Promise<void> {
    const sourceNote = store.allNotes.find((n) => n.id === sourceId)
    const targetNote = store.allNotes.find((n) => n.id === targetId)
    if (!sourceNote || !targetNote) return

    // Prevent duplicate wikilinks
    const targetLower = targetNote.title.toLowerCase()
    if (sourceNote.wikilinks.some((w) => w.toLowerCase() === targetLower)) {
        cancelLinking()
        return
    }

    const separator = sourceNote.content.endsWith('\n') ? '' : '\n'
    const newContent = sourceNote.content + separator + `[[${targetNote.title}]]`
    cancelLinking()
    await store.updateNote(sourceId, { content: newContent })
}

function onKeyDown(e: KeyboardEvent): void {
    if (e.key === 'Escape' && linkingSource.value) {
        cancelLinking()
    }
}

// Context-menu actions (node)
function ctxOpenNote(): void {
    if (ctxNodeId.value) {
        store.loadNote(ctxNodeId.value)
        store.setViewMode('list')
    }
    closeContextMenu()
}

function ctxDeleteNote(): void {
    if (ctxNodeId.value) store.deleteNote(ctxNodeId.value)
    closeContextMenu()
}

function ctxFocusNeighbors(): void {
    if (!cy || !ctxNodeId.value) return
    const node = cy.getElementById(ctxNodeId.value)
    if (node.length) {
        const neighborhood = node.neighborhood().add(node)
        cy.animate({ fit: { eles: neighborhood, padding: 60 }, duration: 300 })
    }
    closeContextMenu()
}

// Context-menu actions (canvas)
function ctxNewNote(): void {
    store.createNote('Nuova nota')
    closeContextMenu()
}

function ctxFitView(): void {
    if (cy) cy.animate({ fit: { eles: cy.elements(), padding: 40 }, duration: 300 })
    closeContextMenu()
}

function ctxResetLayout(): void {
    startLayout(true)
    closeContextMenu()
}

// ---------------------------------------------------------------------------
// Graph data (computed from allNotes — always unfiltered)
// ---------------------------------------------------------------------------

const graphData = computed(() => {
    // Folder → warm-palette color (index-based, stable order)
    const folderColorMap = new Map<string, string>()
    let colorIdx = 0
    for (const n of store.allNotes) {
        const f = n.folder_path || '(root)'
        if (!folderColorMap.has(f)) {
            folderColorMap.set(f, `hsl(${FOLDER_HUES[colorIdx % FOLDER_HUES.length]}, 30%, 55%)`)
            colorIdx++
        }
    }

    const titleToId = new Map<string, string>()
    for (const n of store.allNotes) titleToId.set(n.title.toLowerCase(), n.id)

    // Indegree for size scaling
    const indegreeMap = new Map<string, number>()
    for (const n of store.allNotes) {
        for (const wl of n.wikilinks) {
            const targetId = titleToId.get(wl.toLowerCase())
            if (targetId && targetId !== n.id) {
                indegreeMap.set(targetId, (indegreeMap.get(targetId) ?? 0) + 1)
            }
        }
    }

    const nodes = store.allNotes.map((n) => {
        const folder = n.folder_path || '(root)'
        const nodeColor = folderColorMap.get(folder) ?? 'hsl(35, 30%, 55%)'
        const deg = indegreeMap.get(n.id) ?? 0
        const nodeSize = Math.max(14, Math.min(44, 14 + deg * 5))
        return { data: { id: n.id, label: n.title, folder, nodeColor, nodeSize } }
    })

    const edges: { data: { id: string; source: string; target: string } }[] = []
    for (const n of store.allNotes) {
        for (const wl of n.wikilinks) {
            const targetId = titleToId.get(wl.toLowerCase())
            if (targetId && targetId !== n.id) {
                edges.push({ data: { id: `${n.id}->${targetId}`, source: n.id, target: targetId } })
            }
        }
    }

    return { nodes, edges, folderColorMap }
})

// ---------------------------------------------------------------------------
// Folder color palette (embedded in node data — see graphData)
// ---------------------------------------------------------------------------

const FOLDER_HUES = [35, 25, 45, 15, 55, 5, 30, 50, 40, 20] as const

/** Derived from graphData so legend and nodes always agree. */
const folderColors = computed(() => graphData.value.folderColorMap)

// ---------------------------------------------------------------------------
// Cytoscape initialization
// ---------------------------------------------------------------------------

function buildStylesheet(): cytoscape.StylesheetStyle[] {
    return [
        {
            selector: 'node',
            style: {
                label: 'data(label)',
                // nodeColor and nodeSize come from element data — no bypass styles
                'background-color': 'data(nodeColor)',
                width: 'data(nodeSize)',
                height: 'data(nodeSize)',
                // Disable CSS transitions — they interact badly with class additions
                // (transitioning from highlighted → normal can freeze at the wrong value).
                'font-size': '10px',
                color: '#A09B90',
                'text-valign': 'bottom',
                'text-halign': 'center',
                'text-margin-y': 4,
                'text-outline-width': 2,
                'text-outline-color': '#161616',
                'border-width': 1.5,
                'border-color': 'rgba(232, 220, 200, 0.15)',
                'min-zoomed-font-size': 8,
            } as unknown as cytoscape.Css.Node
        },
        {
            selector: 'node.highlighted',
            style: {
                'border-color': '#E8DCC8',
                'border-width': 2.5,
                'background-color': 'rgba(232, 220, 200, 0.55)',
                color: '#EDEDE9',
                'font-weight': 'bold',
                'text-outline-color': '#161616',
                'text-outline-width': 2,
            }
        },
        {
            selector: 'node.linking-source',
            style: {
                'border-color': 'hsl(45, 60%, 55%)',
                'border-width': 3,
                'border-style': 'dashed',
                'background-color': 'rgba(200, 180, 100, 0.35)',
            }
        },
        {
            selector: 'node:grabbed',
            style: {
                'border-color': 'rgba(232, 220, 200, 0.4)',
                'border-width': 2,
                opacity: 0.85,
            }
        },
        {
            selector: 'edge',
            style: {
                width: 0.8,
                'line-color': 'rgba(255, 255, 255, 0.06)',
                opacity: 0.5,
                'curve-style': 'bezier',
                'target-arrow-shape': 'triangle',
                'target-arrow-color': 'rgba(255, 255, 255, 0.06)',
                'arrow-scale': 0.5
            }
        }
    ]
}

function applyVisuals(): void {
    if (!cy) return
    // Update element data (not bypass styles) so class selectors can cleanly
    // override and restore without transitions getting stuck in between.
    const nodeDataMap = new Map(graphData.value.nodes.map((n) => [n.data.id, n.data]))
    cy.nodes().forEach((node) => {
        const d = nodeDataMap.get(node.id())
        if (!d) return
        node.data('nodeColor', d.nodeColor)
        node.data('nodeSize', d.nodeSize)
    })
}

function highlightCurrentNote(): void {
    if (!cy) return
    cy.nodes().removeClass('highlighted')
    if (store.currentNote) {
        const node = cy.getElementById(store.currentNote.id)
        if (node.length) node.addClass('highlighted')
    }
}

function stopLayout(): void {
    if (activeLayout) {
        activeLayout.stop()
        activeLayout = null
    }
}

function startLayout(randomize: boolean): void {
    if (!cy || cy.nodes().length === 0) return
    stopLayout()

    activeLayout = cy.layout({
        name: 'cola',
        animate: true,
        infinite: true,
        fit: false,
        randomize,
        avoidOverlap: true,
        nodeSpacing: 12,
        edgeLength: 120,
        convergenceThreshold: 0.001,
        handleDisconnected: true,
        padding: 40,
    } as cytoscape.LayoutOptions)

    activeLayout.run()

    // Fit viewport once after cola has positioned nodes from random initial state
    if (randomize) {
        const cyRef = cy
        setTimeout(() => {
            if (cyRef && !cyRef.destroyed()) cyRef.fit(undefined, 40)
        }, 350)
    }
}

function initCytoscape(): void {
    if (!cyContainer.value) return

    const { nodes, edges } = graphData.value

    cy = cytoscape({
        container: cyContainer.value,
        elements: { nodes, edges },
        style: buildStylesheet(),
        minZoom: 0.15,
        maxZoom: 5,
        selectionType: 'single',
        userPanningEnabled: true,
        boxSelectionEnabled: false,
    })

    // Disable node selectability — we manage highlight via .highlighted class
    cy.nodes().unselectify()

    // Force dimension recalculation in case container just became visible
    cy.resize()

    applyVisuals()
    highlightCurrentNote()

    // Start continuous cola layout — initial fit after 350ms
    startLayout(true)

    // Left-click node → open note or complete wikilink
    cy.on('tap', 'node', (evt) => {
        const nodeId = evt.target.id() as string
        if (linkingSource.value) {
            if (nodeId !== linkingSource.value) {
                createWikilink(linkingSource.value, nodeId)
            }
            return
        }
        store.loadNote(nodeId)
    })

    // Left-click canvas background → cancel linking or deselect current note
    cy.on('tap', (evt) => {
        if (evt.target === cy) {
            if (linkingSource.value) {
                cancelLinking()
                return
            }
            store.clearCurrentNote()
        }
    })

    // Right-click node → cancel linking + show node context menu
    cy.on('cxttap', 'node', (evt) => {
        if (linkingSource.value) { cancelLinking(); return }
        const pos = evt.originalEvent as MouseEvent
        ctxNodeId.value = evt.target.id() as string
        ctxNodeLabel.value = (evt.target.data('label') as string) || ''
        ctxMenu.value = { visible: true, x: pos.clientX, y: pos.clientY }
    })

    // Right-click canvas → cancel linking or show canvas context menu
    cy.on('cxttap', (evt) => {
        if (evt.target === cy) {
            if (linkingSource.value) { cancelLinking(); return }
            const pos = evt.originalEvent as MouseEvent
            ctxNodeId.value = null
            ctxNodeLabel.value = ''
            ctxMenu.value = { visible: true, x: pos.clientX, y: pos.clientY }
        }
    })
}

// ---------------------------------------------------------------------------
// Reactive watchers
// ---------------------------------------------------------------------------

let lastElementsKey = ''

function buildElementsKey(): string {
    const gd = graphData.value
    return gd.nodes.map((n) => n.data.id).sort().join(',')
        + '|' + gd.edges.map((e) => e.data.id).sort().join(',')
}

watch(
    graphData,
    (newData) => {
        if (!cy) return
        const key = buildElementsKey()
        if (key === lastElementsKey) return
        lastElementsKey = key

        stopLayout()

        // Diff: add new, remove stale
        const currentNodeIds = new Set(cy.nodes().map((n) => n.id()))
        const currentEdgeIds = new Set(cy.edges().map((e) => e.id()))
        const newNodeIds = new Set(newData.nodes.map((n) => n.data.id))
        const newEdgeIds = new Set(newData.edges.map((e) => e.data.id))

        cy.nodes().filter((n) => !newNodeIds.has(n.id())).remove()
        cy.edges().filter((e) => !newEdgeIds.has(e.id())).remove()

        for (const n of newData.nodes) {
            if (!currentNodeIds.has(n.data.id)) cy.add({ group: 'nodes', ...n })
        }
        for (const e of newData.edges) {
            if (!currentEdgeIds.has(e.data.id)) cy.add({ group: 'edges', ...e })
        }

        cy.nodes().unselectify()
        applyVisuals()
        highlightCurrentNote()
        startLayout(false)
    },
    { deep: true }
)

watch(
    () => store.currentNote,
    () => highlightCurrentNote()
)

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(async () => {
    // Wait for DOM layout to settle (container needs real dimensions)
    await nextTick()
    lastElementsKey = buildElementsKey()
    initCytoscape()
    window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
    window.removeEventListener('keydown', onKeyDown)
    stopLayout()
    if (cy) {
        cy.destroy()
        cy = null
    }
})
</script>

<template>
    <div class="graph-view">
        <!-- Empty state -->
        <div v-if="store.allNotes.length === 0" class="graph-empty">
            <span class="graph-empty__icon">◇</span>
            <span class="graph-empty__text">Nessuna nota nel vault</span>
        </div>

        <!-- Cytoscape container -->
        <div v-show="store.allNotes.length > 0" ref="cyContainer" class="graph-canvas"
            :class="{ 'linking-active': linkingSource }" @contextmenu.prevent />

        <!-- Folder legend -->
        <div v-if="folderColors.size > 0 && store.allNotes.length > 0" class="graph-legend">
            <div v-for="[folder, color] in folderColors" :key="folder" class="graph-legend__item">
                <span class="graph-legend__dot" :style="{ backgroundColor: color }" />
                <span class="graph-legend__label">{{ folder }}</span>
            </div>
        </div>

        <!-- Linking mode indicator -->
        <div v-if="linkingSource" class="graph-linking-bar">
            <span class="graph-linking-bar__icon">
                <AppIcon name="link" :size="14" />
            </span>
            <span>Seleziona la nota da collegare a <strong>{{ linkingSourceLabel }}</strong></span>
            <button class="graph-linking-bar__cancel" @click="cancelLinking">Annulla</button>
        </div>

        <!-- Context menu -->
        <UiContextMenu :visible="ctxMenu.visible" :x="ctxMenu.x" :y="ctxMenu.y"
            :title="ctxNodeId ? ctxNodeLabel : undefined" @close="closeContextMenu">
            <!-- Node actions -->
            <template v-if="ctxNodeId">
                <UiContextMenuItem label="Apri nota" @click="ctxOpenNote">
                    <template #icon>
                        <AppIcon name="file-text" :size="16" :stroke-width="1.5" />
                    </template>
                </UiContextMenuItem>
                <UiContextMenuItem label="Focalizza connessioni" @click="ctxFocusNeighbors">
                    <template #icon>
                        <AppIcon name="search-plus" :size="16" :stroke-width="1.5" />
                    </template>
                </UiContextMenuItem>
                <UiContextMenuItem label="Collega a..." @click="ctxStartLinking">
                    <template #icon>
                        <AppIcon name="link" :size="16" :stroke-width="1.5" />
                    </template>
                </UiContextMenuItem>
                <UiContextMenuDivider />
                <UiContextMenuItem label="Elimina nota" danger @click="ctxDeleteNote">
                    <template #icon>
                        <AppIcon name="trash" :size="16" :stroke-width="1.5" />
                    </template>
                </UiContextMenuItem>
            </template>

            <!-- Canvas actions -->
            <template v-else>
                <UiContextMenuItem label="Nuova nota" @click="ctxNewNote">
                    <template #icon>
                        <AppIcon name="plus" :size="16" :stroke-width="1.5" />
                    </template>
                </UiContextMenuItem>
                <UiContextMenuDivider />
                <UiContextMenuItem label="Ricalcola layout" @click="ctxResetLayout">
                    <template #icon>
                        <AppIcon name="refresh-cw" :size="16" :stroke-width="1.5" />
                    </template>
                </UiContextMenuItem>
                <UiContextMenuItem label="Adatta alla vista" @click="ctxFitView">
                    <template #icon>
                        <AppIcon name="maximize-fit" :size="16" :stroke-width="1.5" />
                    </template>
                </UiContextMenuItem>
            </template>
        </UiContextMenu>
    </div>
</template>

<style scoped>
.graph-view {
    position: relative;
    flex: 1;
    height: 100%;
    min-height: 0;
    background: var(--surface-0);
    border-radius: var(--radius-sm);
    overflow: hidden;
}

.graph-canvas {
    width: 100%;
    height: 100%;
}

/* Empty state */
.graph-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    height: 100%;
}

.graph-empty__icon {
    font-size: var(--text-2xl);
    color: var(--text-muted);
    opacity: 0.5;
}

.graph-empty__text {
    color: var(--text-muted);
    font-size: var(--text-sm);
    letter-spacing: var(--tracking-wide);
}

/* Folder legend (bottom-left) */
.graph-legend {
    position: absolute;
    bottom: var(--space-3);
    left: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-2) var(--space-3);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    max-height: 160px;
    overflow-y: auto;
    opacity: var(--opacity-visible);
    transition: opacity var(--transition-fast);
}

.graph-legend:hover {
    opacity: 1;
}

.graph-legend__item {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
}

.graph-legend__dot {
    width: 8px;
    height: 8px;
    border-radius: var(--radius-full);
    flex-shrink: 0;
}

.graph-legend__label {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 120px;
}

/* Linking mode — crosshair cursor */
.graph-canvas.linking-active {
    cursor: crosshair;
}

/* Linking mode indicator bar */
.graph-linking-bar {
    position: absolute;
    top: var(--space-3);
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4);
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    font-size: var(--text-sm);
    color: var(--text-primary);
    z-index: 10;
    box-shadow: var(--shadow-md);
    white-space: nowrap;
}

.graph-linking-bar__icon {
    color: hsl(45, 60%, 55%);
    display: flex;
}

.graph-linking-bar__cancel {
    margin-left: var(--space-2);
    padding: var(--space-1) var(--space-2);
    background: transparent;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: var(--text-xs);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.graph-linking-bar__cancel:hover {
    background: var(--surface-hover);
    color: var(--text-primary);
}
</style>
