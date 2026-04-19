<script setup lang="ts">
/**
 * ArtifactCard.vue — One artifact tile for the board grid.
 *
 * Renders a 3D preview, title, conversation chip, timestamp + size, and
 * pin / download / delete / open-in-conversation actions. Emits intents
 * back to the parent for store mutation and routing.
 */
import { computed, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import AppIcon from '../ui/AppIcon.vue'
import UiBadge from '../ui/UiBadge.vue'
import UiCard from '../ui/UiCard.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import { resolveBackendUrl } from '../../services/api'
import { useChatStore } from '../../stores/chat'
import type { Artifact, ArtifactKind } from '../../types/artifacts'

const ArtifactPreview3D = defineAsyncComponent(() => import('./ArtifactPreview3D.vue'))

const props = defineProps<{
    artifact: Artifact
}>()

const emit = defineEmits<{
    'toggle-pin': [id: string]
    delete: [id: string]
}>()

const router = useRouter()
const chatStore = useChatStore()

const KIND_LABEL: Record<ArtifactKind, string> = {
    cad_3d_text: '3D · Testo',
    cad_3d_image: '3D · Immagine',
}

const kindLabel = computed(() => KIND_LABEL[props.artifact.kind] ?? props.artifact.kind)

const conversation = computed(() =>
    chatStore.conversations.find((c) => c.id === props.artifact.conversation_id) ?? null,
)

const conversationLabel = computed(() => conversation.value?.title ?? 'Conversazione')

const formattedDate = computed(() => {
    try {
        return new Date(props.artifact.created_at).toLocaleString(undefined, {
            day: '2-digit',
            month: 'short',
            hour: '2-digit',
            minute: '2-digit',
        })
    } catch {
        return ''
    }
})

const formattedSize = computed(() => {
    const bytes = props.artifact.size_bytes
    if (!bytes) return ''
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
})

const downloadHref = computed(() => resolveBackendUrl(props.artifact.download_url))

function openConversation(): void {
    router.push({ path: '/hybrid', query: { conv: props.artifact.conversation_id } })
}
</script>

<template>
    <UiCard variant="default" no-padding class="artifact-card">
        <div class="artifact-card__preview">
            <ArtifactPreview3D :artifact="artifact" />
            <button class="artifact-card__pin" :class="{ 'artifact-card__pin--active': artifact.pinned }"
                :aria-label="artifact.pinned ? 'Rimuovi dai preferiti' : 'Aggiungi ai preferiti'"
                :title="artifact.pinned ? 'Rimuovi dalla bacheca' : 'Pinna in bacheca'"
                @click="emit('toggle-pin', artifact.id)">
                <AppIcon name="pin" :size="14" />
            </button>
        </div>

        <div class="artifact-card__body">
            <div class="artifact-card__head">
                <h3 class="artifact-card__title" :title="artifact.title">{{ artifact.title }}</h3>
                <UiBadge variant="accent" size="sm">{{ kindLabel }}</UiBadge>
            </div>

            <button class="artifact-card__conv" :title="`Apri «${conversationLabel}»`" @click="openConversation">
                <AppIcon name="message" :size="12" />
                <span class="artifact-card__conv-label">{{ conversationLabel }}</span>
            </button>

            <div class="artifact-card__meta">
                <span>{{ formattedDate }}</span>
                <span v-if="formattedSize" class="artifact-card__sep">·</span>
                <span v-if="formattedSize">{{ formattedSize }}</span>
            </div>
        </div>

        <div class="artifact-card__actions">
            <a class="artifact-card__action artifact-card__action--link" :href="downloadHref"
                :download="artifact.title || 'artifact'" :title="`Scarica ${artifact.title}`" aria-label="Scarica file">
                <AppIcon name="download" :size="14" />
            </a>
            <UiIconButton variant="ghost" size="sm" label="Apri nella conversazione" @click="openConversation">
                <AppIcon name="external-link" :size="14" />
            </UiIconButton>
            <UiIconButton variant="ghost" size="sm" label="Elimina artifact" @click="emit('delete', artifact.id)">
                <AppIcon name="trash" :size="14" />
            </UiIconButton>
        </div>
    </UiCard>
</template>

<style scoped>
.artifact-card {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    transition:
        border-color var(--transition-fast),
        transform var(--transition-fast);
}

.artifact-card:hover {
    border-color: var(--border-hover);
    transform: translateY(-1px);
}

/* ── Preview ── */
.artifact-card__preview {
    position: relative;
    aspect-ratio: 4 / 3;
    background: var(--surface-0);
    border-bottom: 1px solid var(--border);
}

.artifact-card__pin {
    position: absolute;
    top: var(--space-2);
    right: var(--space-2);
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
    background: color-mix(in srgb, var(--surface-0) 70%, transparent);
    color: var(--text-muted);
    backdrop-filter: blur(6px);
    cursor: pointer;
    transition:
        color var(--transition-fast),
        background var(--transition-fast),
        border-color var(--transition-fast);
}

.artifact-card__pin:hover {
    color: var(--text-primary);
    border-color: var(--accent-border);
}

.artifact-card__pin--active {
    color: var(--accent);
    background: var(--accent-dim);
    border-color: var(--accent-border);
}

/* ── Body ── */
.artifact-card__body {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) var(--space-4);
}

.artifact-card__head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-2);
}

.artifact-card__title {
    margin: 0;
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
    min-width: 0;
}

.artifact-card__conv {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: var(--text-xs);
    cursor: pointer;
    text-align: left;
    max-width: 100%;
}

.artifact-card__conv:hover {
    color: var(--accent);
}

.artifact-card__conv-label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
}

.artifact-card__meta {
    display: flex;
    align-items: center;
    gap: var(--space-1-5);
    font-size: var(--text-2xs);
    color: var(--text-muted);
    font-family: var(--font-mono);
    letter-spacing: 0.04em;
}

.artifact-card__sep {
    opacity: 0.6;
}

/* ── Actions ── */
.artifact-card__actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-1);
    padding: var(--space-2) var(--space-3);
    border-top: 1px solid var(--border);
    background: var(--surface-1);
}

.artifact-card__action {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    border-radius: var(--radius-sm);
    color: var(--text-muted);
    transition:
        color var(--transition-fast),
        background var(--transition-fast);
    text-decoration: none;
}

.artifact-card__action:hover {
    color: var(--text-primary);
    background: var(--surface-2);
}

.artifact-card__action--link:hover {
    color: var(--accent);
}
</style>
