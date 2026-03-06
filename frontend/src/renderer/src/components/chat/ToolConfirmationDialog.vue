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
        const focused = document.activeElement as HTMLElement | null
        if (focused?.classList.contains('confirm-card__btn--reject')) {
            reject()
        } else {
            approve()
        }
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
    nextTick(() => {
        const firstBtn = dialogRoot.value?.querySelector('.confirm-card__btn--reject') as HTMLElement | null
        firstBtn?.focus()
    })
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

                <div class="confirm-card__risk">
                    <span class="confirm-card__risk-badge"
                        :class="`confirm-card__risk-badge--${confirmation.riskLevel}`">
                        {{ confirmation.riskLevel }}
                    </span>
                </div>

                <p v-if="confirmation.description" class="confirm-card__desc">
                    {{ confirmation.description }}
                </p>

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
    z-index: var(--z-modal);
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--black-heavy);
    backdrop-filter: blur(var(--blur-sm));
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
    padding: var(--space-5) var(--space-6);
    box-shadow: var(--shadow-lg);
    animation: cardSlideIn 0.25s ease;
}

.confirm-card__title {
    margin: 0 0 14px;
    font-size: var(--text-lg);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
}

.confirm-card__tool {
    margin-bottom: var(--space-3);
}

.confirm-card__badge {
    display: inline-block;
    font-family: var(--font-mono);
    font-size: var(--text-base);
    color: var(--accent);
    background: var(--accent-light);
    padding: 3px var(--space-2-5);
    border-radius: var(--radius-sm);
    border: 1px solid var(--accent-border);
}

.confirm-card__risk {
    margin-bottom: var(--space-3);
}

.confirm-card__risk-badge {
    display: inline-block;
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: var(--space-0-5) var(--space-2);
    border-radius: var(--radius-sm);
}

.confirm-card__risk-badge--medium {
    color: var(--warning);
    background: var(--warning-bg);
    border: 1px solid var(--warning-border);
}

.confirm-card__risk-badge--dangerous {
    color: var(--error);
    background: var(--error-bg);
    border: 1px solid var(--error-border);
}

.confirm-card__risk-badge--forbidden {
    color: var(--error-severe);
    background: var(--error-severe-bg);
    border: 1px solid var(--error-severe-border);
}

.confirm-card__desc {
    margin: 0 0 var(--space-3);
    font-size: var(--text-base);
    color: var(--text-secondary);
    line-height: var(--leading-snug);
}

.confirm-card__args-wrap {
    margin-bottom: var(--space-4);
}

.confirm-card__args-label {
    display: block;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    margin-bottom: var(--space-1);
}

.confirm-card__args {
    margin: 0;
    padding: var(--space-2) var(--space-3);
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    line-height: var(--leading-normal);
    color: var(--text-secondary);
    background: var(--black-light);
    border-radius: var(--radius-sm);
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 200px;
}

.confirm-card__actions {
    display: flex;
    gap: var(--space-2-5);
    justify-content: flex-end;
}

.confirm-card__btn {
    padding: 7px 18px;
    font-size: var(--text-base);
    font-weight: var(--weight-medium);
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
    cursor: pointer;
    transition: background var(--transition-fast), border-color var(--transition-fast);
}

.confirm-card__btn--approve {
    background: var(--approve-bg);
    border-color: var(--approve-border);
    color: var(--approve);
}

.confirm-card__btn--approve:hover {
    background: var(--approve-bg-hover);
    border-color: var(--approve-border-hover);
}

.confirm-card__btn--reject {
    background: var(--error-bg);
    border-color: var(--error-border);
    color: var(--error);
}

.confirm-card__btn--reject:hover {
    background: var(--error-bg-hover);
    border-color: var(--error-border-hover);
}

.confirm-card__hint {
    margin: var(--space-3) 0 0;
    font-size: var(--text-xs);
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
