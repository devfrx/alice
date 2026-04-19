<script setup lang="ts">
/**
 * ArtifactBoardView.vue — "Bacheca" view: grid of all persisted artifacts.
 *
 * Lists every artifact registered by the backend, with filters (kind /
 * pinned / conversation) and per-card actions (pin, download, delete,
 * open in conversation). Subscribes to the artifacts store so newly-
 * generated artifacts appear automatically thanks to the global
 * ``artifact.created`` WS event handled in {@link useEventsWebSocket}.
 */
import { computed, onMounted, ref } from 'vue'

import ArtifactBoardFilters from '../components/board/ArtifactBoardFilters.vue'
import ArtifactCard from '../components/board/ArtifactCard.vue'
import UiEmptyState from '../components/ui/UiEmptyState.vue'
import AliceSpinner from '../components/ui/AliceSpinner.vue'
import { useArtifactsStore } from '../stores/artifacts'
import { useChatStore } from '../stores/chat'
import { useModal } from '../composables/useModal'
import type { ArtifactKind } from '../types/artifacts'

const artifactsStore = useArtifactsStore()
const chatStore = useChatStore()
const { confirm } = useModal()

const kindFilter = ref<ArtifactKind | 'all'>('all')
const pinnedOnly = ref(false)
const conversationFilter = ref<string | 'all'>('all')

/** Filtered list reactive to all three filter controls. */
const visibleItems = computed(() => {
    return artifactsStore.items.filter((a) => {
        if (kindFilter.value !== 'all' && a.kind !== kindFilter.value) return false
        if (pinnedOnly.value && !a.pinned) return false
        if (conversationFilter.value !== 'all' && a.conversation_id !== conversationFilter.value) return false
        return true
    })
})

const isFiltered = computed(
    () =>
        kindFilter.value !== 'all' ||
        pinnedOnly.value ||
        conversationFilter.value !== 'all',
)

async function togglePin(id: string): Promise<void> {
    try {
        await artifactsStore.togglePin(id)
    } catch (err) {
        console.error('[ArtifactBoardView] togglePin failed:', err)
    }
}

async function deleteArtifact(id: string): Promise<void> {
    const target = artifactsStore.findById(id)
    const confirmed = await confirm({
        title: 'Eliminare l\u2019artifact?',
        message: target
            ? `«${target.title}» verrà rimosso dalla bacheca e il file su disco verrà cancellato.`
            : 'L\u2019elemento verrà rimosso dalla bacheca e il file su disco verrà cancellato.',
        type: 'danger',
        confirmText: 'Elimina',
    })
    if (!confirmed) return
    try {
        await artifactsStore.remove(id, true)
    } catch (err) {
        console.error('[ArtifactBoardView] delete failed:', err)
    }
}

onMounted(async () => {
    // Conversations may not have been loaded yet (deep-linking to /board).
    if (!chatStore.conversations.length) {
        chatStore.loadConversations().catch(console.error)
    }
    try {
        await artifactsStore.fetch({ limit: 200 })
    } catch (err) {
        console.error('[ArtifactBoardView] fetch failed:', err)
    }
})
</script>

<template>
    <section class="board-view" aria-label="Bacheca artefatti">
        <header class="board-view__header">
            <div class="board-view__title-block">
                <h1 class="board-view__title">Bacheca</h1>
                <p class="board-view__count">
                    <template v-if="artifactsStore.loading">Caricamento…</template>
                    <template v-else>
                        {{ visibleItems.length }} di {{ artifactsStore.items.length }} artefatti
                    </template>
                </p>
            </div>
        </header>

        <ArtifactBoardFilters :kind-filter="kindFilter" :pinned-only="pinnedOnly"
            :conversation-filter="conversationFilter" :conversations="chatStore.conversations"
            @update:kind-filter="kindFilter = $event" @update:pinned-only="pinnedOnly = $event"
            @update:conversation-filter="conversationFilter = $event" />

        <div class="board-view__body">
            <div v-if="artifactsStore.loading && !artifactsStore.items.length" class="board-view__loading">
                <AliceSpinner size="md" label="Caricamento artefatti" />
            </div>

            <div v-else-if="visibleItems.length" class="board-view__grid">
                <ArtifactCard v-for="item in visibleItems" :key="item.id" :artifact="item" @toggle-pin="togglePin"
                    @delete="deleteArtifact" />
            </div>

            <UiEmptyState v-else-if="isFiltered" icon="search" title="Nessun risultato"
                subtitle="Prova a rimuovere i filtri attivi per vedere altri artefatti." />

            <UiEmptyState v-else icon="bookmark" title="La bacheca è vuota"
                subtitle="Gli artefatti generati da AL\CE (modelli 3D, immagini, …) appariranno qui automaticamente." />
        </div>
    </section>
</template>

<style scoped>
.board-view {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    background: var(--surface-0);
    color: var(--text-primary);
    overflow: hidden;
}

.board-view__header {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-6) var(--space-6) var(--space-3);
}

.board-view__title-block {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
}

.board-view__title {
    margin: 0;
    font-size: var(--text-2xl);
    font-weight: var(--weight-semibold);
    letter-spacing: -0.01em;
    color: var(--text-primary);
}

.board-view__count {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--text-muted);
    font-family: var(--font-mono);
    letter-spacing: 0.05em;
}

.board-view__body {
    flex: 1;
    overflow-y: auto;
    padding: var(--space-5) var(--space-6) var(--space-6);
}

.board-view__loading {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: var(--text-muted);
}

.board-view__grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: var(--space-5);
}

@media (max-width: 720px) {
    .board-view__header {
        padding: var(--space-4) var(--space-4) var(--space-2);
    }

    .board-view__body {
        padding: var(--space-3) var(--space-4) var(--space-5);
    }

    .board-view__grid {
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: var(--space-3);
    }
}
</style>
