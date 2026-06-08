<script setup lang="ts">
/**
 * AskUserPrompt.vue — Inline prompt for the `ask_user` meta-tool.
 *
 * Unlike ToolConfirmationDialog (a centered modal), this renders inline in the
 * message flow and always requires human input — there is no auto-approve path.
 * The user can either click one of the suggested `options` or type a free-form
 * answer. Both paths emit `answer` with the trimmed text; empty input is ignored.
 */
import { nextTick, onMounted, ref } from 'vue'

import type { AskUserRequest } from '../../types/chat'

const props = defineProps<{
    /** The pending ask_user request to display. */
    request: AskUserRequest
}>()

const emit = defineEmits<{
    answer: [executionId: string, answer: string]
}>()

const inputRef = ref<HTMLInputElement | null>(null)
const text = ref('')

/** Submit the free-form text answer (ignores empty/whitespace-only). */
function submitText(): void {
    const trimmed = text.value.trim()
    if (!trimmed) return
    emit('answer', props.request.executionId, trimmed)
    text.value = ''
}

/** Answer immediately with a clicked option. */
function chooseOption(option: string): void {
    emit('answer', props.request.executionId, option)
}

onMounted(() => {
    nextTick(() => inputRef.value?.focus())
})
</script>

<template>
    <div class="ask-card" role="group" aria-label="Domanda dall'assistente">
        <div class="ask-card__header">
            <span class="ask-card__icon" aria-hidden="true">?</span>
            <h3 class="ask-card__title">Domanda</h3>
        </div>

        <p class="ask-card__question">{{ request.question }}</p>

        <div v-if="request.options?.length" class="ask-card__options">
            <button v-for="option in request.options" :key="option" type="button" class="ask-card__option"
                @click="chooseOption(option)">
                {{ option }}
            </button>
        </div>

        <form class="ask-card__form" @submit.prevent="submitText">
            <input ref="inputRef" v-model="text" type="text" class="ask-card__input"
                placeholder="Scrivi una risposta…" />
            <button type="submit" class="ask-card__submit" :disabled="!text.trim()">
                Invia
            </button>
        </form>
    </div>
</template>

<style scoped>
/* AskUserPrompt — inline variant of the Supabase confirmation card. */

.ask-card {
    width: 100%;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: var(--space-4);
    box-shadow: var(--shadow-sm);
    animation: askCardIn 250ms cubic-bezier(0.16, 1, 0.3, 1);
}

.ask-card__header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
}

.ask-card__icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: var(--radius-pill);
    background: var(--surface-3);
    border: 1px solid var(--border);
    color: var(--accent);
    font-size: var(--text-sm);
    font-weight: var(--weight-semibold);
    flex-shrink: 0;
}

.ask-card__title {
    margin: 0;
    font-size: var(--text-base);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
}

.ask-card__question {
    margin: 0 0 var(--space-3);
    font-size: var(--text-base);
    color: var(--text-secondary);
    line-height: var(--leading-snug);
    white-space: pre-wrap;
}

.ask-card__options {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-bottom: var(--space-3);
}

.ask-card__option {
    padding: var(--space-1-5) var(--space-3);
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-primary);
    background: var(--surface-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: background var(--transition-fast), border-color var(--transition-fast),
        color var(--transition-fast);
}

.ask-card__option:hover {
    background: var(--surface-4);
    border-color: var(--border-hover);
    color: var(--accent);
}

.ask-card__form {
    display: flex;
    gap: var(--space-2);
    align-items: stretch;
}

.ask-card__input {
    flex: 1;
    min-width: 0;
    padding: var(--space-2) var(--space-3);
    font-size: var(--text-sm);
    font-family: inherit;
    color: var(--text-primary);
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    transition: border-color var(--transition-fast);
}

.ask-card__input::placeholder {
    color: var(--text-muted);
}

.ask-card__input:focus {
    outline: none;
    border-color: var(--accent);
}

.ask-card__submit {
    padding: var(--space-2) var(--space-5);
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--surface-0);
    background: var(--accent);
    border: 1px solid var(--accent);
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: background var(--transition-fast), border-color var(--transition-fast),
        opacity var(--transition-fast);
}

.ask-card__submit:hover:not(:disabled) {
    background: var(--accent-hover);
    border-color: var(--accent-hover);
}

.ask-card__submit:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

@keyframes askCardIn {
    from {
        opacity: 0;
        transform: translateY(6px);
    }

    to {
        opacity: 1;
        transform: translateY(0);
    }
}
</style>
