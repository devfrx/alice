<script setup lang="ts">
/**
 * ErrorBoundary.vue — Isolates child component crashes.
 *
 * Catches errors from child components via `onErrorCaptured` and
 * renders a user-friendly fallback with a retry button. In development,
 * the full stack trace is displayed for debugging. A "report" action
 * copies diagnostic information to the clipboard.
 */
import { onBeforeUnmount, onErrorCaptured, ref } from 'vue'
import AppIcon from './ui/AppIcon.vue'

const emit = defineEmits<{
    /** Emitted when a child component throws an error. */
    error: [err: Error, info: string]
}>()

const hasError = ref(false)
const errorMessage = ref('')
const errorStack = ref('')
const errorInfo = ref('')
const reportCopied = ref(false)
let copyResetTimer: ReturnType<typeof setTimeout> | null = null

/** Is the app running in development mode? */
const isDev = import.meta.env.DEV

onErrorCaptured((err: Error, _instance, info: string) => {
    hasError.value = true
    errorMessage.value = err.message || 'Errore sconosciuto'
    errorStack.value = err.stack ?? ''
    errorInfo.value = info
    console.error('[ErrorBoundary] Caught error:', err, '\nInfo:', info)
    emit('error', err, info)
    // Return false to stop propagation
    return false
})

/** Reset the error state to re-render children. */
function retry(): void {
    hasError.value = false
    errorMessage.value = ''
    errorStack.value = ''
    errorInfo.value = ''
    reportCopied.value = false
}

/** Copy a diagnostic report to the clipboard so the user can forward it. */
async function copyReport(): Promise<void> {
    const payload = [
        `AL\\CE — Error Report`,
        `Time: ${new Date().toISOString()}`,
        `Message: ${errorMessage.value}`,
        `Component: ${errorInfo.value}`,
        ``,
        `Stack:`,
        errorStack.value || '(no stack trace)',
    ].join('\n')
    try {
        await navigator.clipboard.writeText(payload)
        reportCopied.value = true
        if (copyResetTimer) clearTimeout(copyResetTimer)
        copyResetTimer = setTimeout(() => {
            reportCopied.value = false
            copyResetTimer = null
        }, 2000)
    } catch (err) {
        console.warn('[ErrorBoundary] clipboard write failed:', err)
    }
}

onBeforeUnmount(() => {
    if (copyResetTimer) {
        clearTimeout(copyResetTimer)
        copyResetTimer = null
    }
})
</script>

<template>
    <slot v-if="!hasError" />
    <div v-else class="error-boundary" role="alert" aria-live="assertive">
        <div class="error-boundary__icon">
            <AppIcon name="alert-circle" :size="32" :stroke-width="1.5" />
        </div>
        <p class="error-boundary__title">Qualcosa è andato storto</p>
        <p class="error-boundary__detail">{{ errorMessage }}</p>

        <!-- Dev-only stack trace -->
        <details v-if="isDev && errorStack" class="error-boundary__stack">
            <summary>Stack trace (dev)</summary>
            <pre>{{ errorStack }}</pre>
            <p v-if="errorInfo" class="error-boundary__info">Componente: {{ errorInfo }}</p>
        </details>

        <div class="error-boundary__actions">
            <button class="error-boundary__btn" aria-label="Riprova" @click="retry">
                Riprova
            </button>
            <button class="error-boundary__btn error-boundary__btn--ghost" type="button"
                :aria-label="reportCopied ? 'Report copiato' : 'Copia report diagnostico'" @click="copyReport">
                {{ reportCopied ? 'Copiato!' : 'Segnala' }}
            </button>
        </div>
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

.error-boundary__stack {
    width: 100%;
    max-width: 520px;
    margin-top: var(--space-3);
    padding: var(--space-2) var(--space-3);
    background: var(--surface-0);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    text-align: left;
    font-size: var(--text-xs);
    color: var(--text-muted);
}

.error-boundary__stack summary {
    cursor: pointer;
    color: var(--text-secondary);
    font-weight: var(--weight-medium);
    user-select: none;
}

.error-boundary__stack pre {
    margin: var(--space-2) 0 0;
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    color: var(--text-secondary);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 240px;
    overflow-y: auto;
}

.error-boundary__info {
    margin: var(--space-2) 0 0;
    font-family: var(--font-mono);
    font-size: var(--text-2xs);
    color: var(--text-muted);
}

.error-boundary__actions {
    display: flex;
    gap: var(--space-2);
    margin-top: var(--space-2);
}

.error-boundary__btn {
    padding: var(--space-1-5) var(--space-4);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    font-size: var(--text-base);
    cursor: pointer;
    transition: all var(--transition-fast);
}

.error-boundary__btn:hover {
    background: var(--surface-hover);
    color: var(--text-primary);
    border-color: var(--border-hover);
}

.error-boundary__btn:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: var(--space-0-5);
}

.error-boundary__btn--ghost {
    color: var(--text-muted);
}
</style>
