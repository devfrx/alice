<script setup lang="ts">
/**
 * ErrorBoundary.vue — Isolates child component crashes.
 *
 * Catches errors from child components via `onErrorCaptured` and
 * renders a user-friendly fallback with a retry button.
 */
import { onErrorCaptured, ref } from 'vue'

const emit = defineEmits<{
    /** Emitted when a child component throws an error. */
    error: [err: Error, info: string]
}>()

const hasError = ref(false)
const errorMessage = ref('')

onErrorCaptured((err: Error, _instance, info: string) => {
    hasError.value = true
    errorMessage.value = err.message || 'Errore sconosciuto'
    console.error('[ErrorBoundary] Caught error:', err, '\nInfo:', info)
    emit('error', err, info)
    // Return false to stop propagation
    return false
})

/** Reset the error state to re-render children. */
function retry(): void {
    hasError.value = false
    errorMessage.value = ''
}
</script>

<template>
    <slot v-if="!hasError" />
    <div v-else class="error-boundary" role="alert">
        <div class="error-boundary__icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"
                stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
        </div>
        <p class="error-boundary__title">Qualcosa è andato storto</p>
        <p class="error-boundary__detail">{{ errorMessage }}</p>
        <button class="error-boundary__retry" aria-label="Riprova" @click="retry">
            Riprova
        </button>
    </div>
</template>

<style scoped>
.error-boundary {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-6);
    border: 1px solid var(--danger-border);
    border-radius: var(--radius-md);
    background: var(--surface-1);
    text-align: center;
}

.error-boundary__icon {
    color: var(--danger);
    opacity: var(--opacity-medium);
}

.error-boundary__title {
    font-size: var(--text-md);
    color: var(--text-primary);
    font-weight: var(--weight-medium);
}

.error-boundary__detail {
    font-size: var(--text-sm);
    color: var(--text-secondary);
    max-width: 300px;
    word-break: break-word;
}

.error-boundary__retry {
    margin-top: var(--space-2);
    padding: var(--space-1-5) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    font-size: var(--text-base);
    cursor: pointer;
    transition: all var(--transition-fast);
}

.error-boundary__retry:hover {
    background: var(--surface-hover);
    color: var(--text-primary);
    border-color: var(--border-hover);
}

.error-boundary__retry:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: var(--space-0-5);
}
</style>
