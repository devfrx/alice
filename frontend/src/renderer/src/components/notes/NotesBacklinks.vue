<script setup lang="ts">
/**
 * NotesBacklinks — Right panel showing notes that reference the current note.
 *
 * Reads the `backlinks` computed from the notes store and displays them
 * as clickable items. Collapsible via a toggle button.
 */
import { ref } from 'vue'
import { useNotesStore } from '../../stores/notes'

const store = useNotesStore()
const collapsed = ref(false)

function openNote(id: string): void {
    store.loadNote(id)
}
</script>

<template>
    <aside class="backlinks" :class="{ 'backlinks--collapsed': collapsed }">
        <header class="backlinks__header" @click="collapsed = !collapsed">
            <span class="backlinks__title">Backlinks</span>
            <svg class="backlinks__chevron" :class="{ 'backlinks__chevron--collapsed': collapsed }" width="12"
                height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
                stroke-linecap="round" stroke-linejoin="round">
                <polyline points="9 18 15 12 9 6" />
            </svg>
        </header>

        <div v-if="!collapsed" class="backlinks__body">
            <template v-if="store.backlinks.length > 0">
                <button v-for="bl in store.backlinks" :key="bl.id" class="backlinks__item" @click="openNote(bl.id)">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                    </svg>
                    <span class="backlinks__item-title">{{ bl.title }}</span>
                </button>
            </template>

            <p v-else class="backlinks__empty">
                Nessuna nota fa riferimento a questa
            </p>
        </div>
    </aside>
</template>

<style scoped>
.backlinks {
    width: 240px;
    min-width: 240px;
    height: 100%;
    display: flex;
    flex-direction: column;
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur-heavy));
    -webkit-backdrop-filter: blur(var(--glass-blur-heavy));
    border: 1px solid var(--glass-border);
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.2), 0 0 1px rgba(255, 255, 255, 0.04);
    flex-shrink: 0;
    transition: width var(--transition-normal), min-width var(--transition-normal);
}

.backlinks--collapsed {
    width: 40px;
    min-width: 40px;
}

.backlinks__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-3);
    cursor: pointer;
    user-select: none;
    border-bottom: 1px solid var(--border);
}

.backlinks__title {
    font-size: var(--text-xs);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
    overflow: hidden;
}

.backlinks--collapsed .backlinks__title {
    display: none;
}

.backlinks__chevron {
    color: var(--text-muted);
    transition: transform var(--transition-fast);
    flex-shrink: 0;
}

.backlinks__chevron--collapsed {
    transform: rotate(180deg);
}

.backlinks__body {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-2);
}

.backlinks__body::-webkit-scrollbar {
    width: 4px;
}

.backlinks__body::-webkit-scrollbar-thumb {
    background: var(--surface-3);
    border-radius: 2px;
}

.backlinks__item {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-2);
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    color: var(--text-secondary);
    font-size: var(--text-sm);
    cursor: pointer;
    text-align: left;
    transition: background var(--transition-fast), color var(--transition-fast);
}

.backlinks__item:hover {
    background: var(--surface-2);
    color: var(--text-primary);
}

.backlinks__item-title {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.backlinks__empty {
    padding: var(--space-3);
    color: var(--text-muted);
    font-size: var(--text-xs);
    text-align: center;
}
</style>
