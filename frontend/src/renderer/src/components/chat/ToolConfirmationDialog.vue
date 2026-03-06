<script setup lang="ts">
/**
 * ToolConfirmationDialog.vue — Modal for tool approval/rejection.
 *
 * Shows a centered dialog with tool name, arguments, and approve/reject buttons.
 * Keyboard shortcuts: Enter = approve, Escape = reject.
 */
import { nextTick, onMounted, ref } from 'vue'

import type { ConfirmationRequest } from '../../types/chat'

const props = defineProps<{
    /** The pending confirmation request to display. */
    confirmation: ConfirmationRequest
}>()

const emit = defineEmits<{
    respond: [executionId: string, approved: boolean]
}>()

const dialogRoot = ref<HTMLElement | null>(null)

function approve(): void {
    emit('respond', props.confirmation.executionId, true)
}

function reject(): void {
    emit('respond', props.confirmation.executionId, false)
}

function handleKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
        e.preventDefault()
        approve()
    } else if (e.key === 'Escape') {
        e.preventDefault()
        reject()
    }
}

/** Format arguments for display. */
function formatArgs(args: Record<string, unknown>): string {
    return JSON.stringify(args, null, 2)
}

onMounted(() => {
    nextTick(() => dialogRoot.value?.focus())
})
</script>

<template>
    <Teleport to="body">
        <div ref="dialogRoot" class="confirm-overlay" tabindex="-1" @click.self="reject" @keydown="handleKeydown">
            <div class="confirm-card" role="dialog" aria-modal="true" aria-label="Conferma strumento">
                <h3 class="confirm-card__title">Conferma esecuzione</h3>

                <div class="confirm-card__tool">
                    <span class="confirm-card__badge">{{ confirmation.toolName }}</span>
                </div>

                <div class="confirm-card__args-wrap">
                    <span class="confirm-card__args-label">Argomenti:</span>
                    <pre class="confirm-card__args"><code>{{ formatArgs(confirmation.args) }}</code></pre>
                </div>

                <div class="confirm-card__actions">
                    <button class="confirm-card__btn confirm-card__btn--reject" @click="reject">
                        Rifiuta
                    </button>
                    <button class="confirm-card__btn confirm-card__btn--approve" @click="approve">
                        Approva
                    </button>
                </div>

                <p class="confirm-card__hint">Enter = Approva · Esc = Rifiuta</p>
            </div>
        </div>
    </Teleport>
</template>

<style scoped>
.confirm-overlay {
    position: fixed;
    inset: 0;
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(4px);
    animation: overlayFadeIn 0.2s ease;
}

.confirm-card {
    width: 420px;
    max-width: 90vw;
    max-height: 80vh;
    overflow-y: auto;
    background: var(--bg-secondary);
    border: 1px solid var(--accent-border);
    border-radius: var(--radius-lg);
    padding: 20px 24px;
    box-shadow: 0 0 40px rgba(201, 168, 76, 0.12);
    animation: cardSlideIn 0.25s ease;
}

.confirm-card__title {
    margin: 0 0 14px;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text-primary);
}

.confirm-card__tool {
    margin-bottom: 12px;
}

.confirm-card__badge {
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 0.82rem;
    color: var(--accent);
    background: rgba(201, 168, 76, 0.1);
    padding: 3px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--accent-border);
}

.confirm-card__args-wrap {
    margin-bottom: 16px;
}

.confirm-card__args-label {
    display: block;
    font-size: 0.75rem;
    color: var(--text-secondary);
    margin-bottom: 4px;
}

.confirm-card__args {
    margin: 0;
    padding: 8px 12px;
    font-family: var(--font-mono);
    font-size: 0.74rem;
    line-height: 1.5;
    color: var(--text-secondary);
    background: rgba(0, 0, 0, 0.3);
    border-radius: var(--radius-sm);
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 200px;
}

.confirm-card__actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
}

.confirm-card__btn {
    padding: 7px 18px;
    font-size: 0.82rem;
    font-weight: 500;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background 0.2s ease, border-color 0.2s ease;
}

.confirm-card__btn--approve {
    background: rgba(74, 222, 128, 0.15);
    border-color: rgba(74, 222, 128, 0.4);
    color: #4ade80;
}

.confirm-card__btn--approve:hover {
    background: rgba(74, 222, 128, 0.25);
    border-color: rgba(74, 222, 128, 0.6);
}

.confirm-card__btn--reject {
    background: rgba(248, 113, 113, 0.1);
    border-color: rgba(248, 113, 113, 0.3);
    color: #f87171;
}

.confirm-card__btn--reject:hover {
    background: rgba(248, 113, 113, 0.2);
    border-color: rgba(248, 113, 113, 0.5);
}

.confirm-card__hint {
    margin: 12px 0 0;
    font-size: 0.68rem;
    color: var(--text-secondary);
    opacity: 0.4;
    text-align: center;
}

@keyframes overlayFadeIn {
    from {
        opacity: 0;
    }

    to {
        opacity: 1;
    }
}

@keyframes cardSlideIn {
    from {
        opacity: 0;
        transform: translateY(-12px) scale(0.97);
    }

    to {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}
</style>
