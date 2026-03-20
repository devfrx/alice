<script setup lang="ts">
/**
 * MessageEditDialog.vue — Inline dialog for editing a sent message.
 *
 * Appears as a modal overlay with a textarea pre-filled with the
 * original message content.  Supports Ctrl+Enter to submit and
 * Escape to cancel.
 */
import { ref, onMounted, nextTick } from 'vue'

const props = defineProps<{
    /** Original message content to edit. */
    originalContent: string
}>()

const emit = defineEmits<{
    submit: [content: string]
    cancel: []
}>()

const content = ref(props.originalContent)
const textareaRef = ref<HTMLTextAreaElement | null>(null)

/** Auto-resize textarea to fit content. */
function autoResize(): void {
    const el = textareaRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 320)}px`
}

function handleSubmit(): void {
    const trimmed = content.value.trim()
    if (trimmed && trimmed !== props.originalContent) {
        emit('submit', trimmed)
    } else {
        emit('cancel')
    }
}

function handleKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
        emit('cancel')
    } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        handleSubmit()
    }
}

onMounted(async () => {
    await nextTick()
    const el = textareaRef.value
    if (el) {
        el.focus()
        el.setSelectionRange(el.value.length, el.value.length)
        autoResize()
    }
})
</script>

<template>
    <Teleport to="body">
        <div class="edit-overlay" @click.self="emit('cancel')" @keydown="handleKeydown">
            <div class="edit-dialog">
                <div class="edit-dialog__header">
                    <span class="edit-dialog__title">Modifica messaggio</span>
                    <button class="edit-dialog__close" aria-label="Annulla" @click="emit('cancel')">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                            stroke-width="2" stroke-linecap="round">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    </button>
                </div>
                <textarea ref="textareaRef" v-model="content" class="edit-dialog__textarea" rows="3"
                    placeholder="Scrivi il messaggio modificato…" @input="autoResize" />
                <div class="edit-dialog__actions">
                    <span class="edit-dialog__hint">Ctrl+Invio per inviare</span>
                    <div class="edit-dialog__buttons">
                        <button class="edit-dialog__btn edit-dialog__btn--cancel" @click="emit('cancel')">
                            Annulla
                        </button>
                        <button class="edit-dialog__btn edit-dialog__btn--submit"
                            :disabled="!content.trim() || content.trim() === originalContent" @click="handleSubmit">
                            Invia modifica
                        </button>
                    </div>
                </div>
            </div>
        </div>
    </Teleport>
</template>

<style scoped>
.edit-overlay {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--black-heavy);
    backdrop-filter: blur(var(--blur-sm));
    -webkit-backdrop-filter: blur(var(--blur-sm));
    animation: modalOverlayIn 200ms ease both;
}

.edit-dialog {
    width: min(560px, 90vw);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-5);
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    box-shadow: var(--shadow-floating);
    animation: modalCardIn 250ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

.edit-dialog__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.edit-dialog__title {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-primary);
}

.edit-dialog__close {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    transition: color var(--transition-fast), background var(--transition-fast);
}

.edit-dialog__close:hover {
    color: var(--text-primary);
    background: var(--surface-2);
}

.edit-dialog__textarea {
    width: 100%;
    min-height: 72px;
    max-height: 320px;
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--surface-0);
    color: var(--text-primary);
    font-family: var(--font-sans);
    font-size: var(--text-sm);
    line-height: var(--leading-relaxed);
    resize: none;
    outline: none;
    transition: border-color var(--transition-fast);
}

.edit-dialog__textarea:focus {
    border-color: var(--accent-border);
}

.edit-dialog__actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
}

.edit-dialog__hint {
    font-size: var(--text-2xs);
    color: var(--text-muted);
}

.edit-dialog__buttons {
    display: flex;
    gap: var(--space-2);
}

.edit-dialog__btn {
    padding: var(--space-2) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    cursor: pointer;
    transition: background var(--transition-fast), color var(--transition-fast),
        border-color var(--transition-fast);
}

.edit-dialog__btn--cancel {
    background: transparent;
    color: var(--text-secondary);
}

.edit-dialog__btn--cancel:hover {
    background: var(--surface-2);
    color: var(--text-primary);
}

.edit-dialog__btn--submit {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--text-on-accent);
}

.edit-dialog__btn--submit:hover:not(:disabled) {
    background: var(--accent-hover);
}

.edit-dialog__btn--submit:disabled {
    opacity: 0.5;
    cursor: default;
}

@keyframes modalOverlayIn {
    from {
        opacity: 0;
    }

    to {
        opacity: 1;
    }
}

@keyframes modalCardIn {
    from {
        opacity: 0;
        transform: scale(0.97) translateY(-6px);
    }

    to {
        opacity: 1;
        transform: scale(1) translateY(0);
    }
}
</style>
