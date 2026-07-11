<script setup lang="ts">
/**
 * AskUserPrompt.vue — Inline sequential wizard for the `ask_user` meta-tool.
 *
 * Unlike ToolConfirmationDialog (a centered modal), this renders inline in the
 * message flow and always requires human input — there is no auto-approve path.
 * It walks the user through one question per step (radio or checkbox, with an
 * optional free-text field), then emits a single `answer` carrying every
 * answer keyed by `question_id`.
 */
import { ref, computed } from 'vue'

import type { AskUserRequest, AskUserAnswer } from '../../types/chat'
import UiButton from '../ui/UiButton.vue'

const props = defineProps<{ request: AskUserRequest }>()
const emit = defineEmits<{ answer: [executionId: string, answers: AskUserAnswer[]] }>()

const step = ref(0)
const total = computed(() => props.request.questions.length)
const current = computed(() => props.request.questions[step.value])

const selected = ref<Record<string, string[]>>({})
const freeText = ref<Record<string, string>>({})

/** Toggle an option for a question; replaces (radio) or accumulates (checkbox). */
function toggle(qid: string, option: string, multi: boolean): void {
  const cur = selected.value[qid] ?? []
  if (multi) {
    selected.value[qid] = cur.includes(option) ? cur.filter((o) => o !== option) : [...cur, option]
  } else {
    selected.value[qid] = [option]
  }
}

/** Whether the current question has enough input to move on. */
const canAdvance = computed(() => {
  const q = current.value
  if (!q) return false
  const hasSel = (selected.value[q.id]?.length ?? 0) > 0
  const hasFree = (freeText.value[q.id]?.trim().length ?? 0) > 0
  return hasSel || (q.allow_free_text ? hasFree : false) || (q.options?.length ?? 0) === 0
})

function next(): void {
  if (step.value < total.value - 1) step.value += 1
  else submit()
}

function back(): void {
  if (step.value > 0) step.value -= 1
}

function submit(): void {
  const answers: AskUserAnswer[] = props.request.questions.map((q) => ({
    question_id: q.id,
    selected: selected.value[q.id] ?? [],
    free_text: freeText.value[q.id]?.trim() || undefined
  }))
  emit('answer', props.request.executionId, answers)
}
</script>

<template>
  <div v-if="current" class="ask-card" role="group" aria-label="Domanda dall'assistente">
    <div class="ask-card__progress">{{ step + 1 }} / {{ total }}</div>
    <p class="ask-card__question">{{ current.text }}</p>

    <div v-if="current.options?.length" class="ask-card__options">
      <button
        v-for="option in current.options"
        :key="option"
        type="button"
        class="ask-card__option"
        :class="{ 'ask-card__option--on': (selected[current.id] ?? []).includes(option) }"
        @click="toggle(current.id, option, current.type === 'checkbox')"
      >
        <span class="ask-card__marker" :class="current.type" />
        {{ option }}
      </button>
    </div>

    <input
      v-if="current.allow_free_text"
      v-model="freeText[current.id]"
      class="ask-card__free"
      type="text"
      placeholder="Oppure scrivi una risposta…"
    />

    <div class="ask-card__nav">
      <UiButton variant="secondary" size="sm" :disabled="step === 0" @click="back">
        Indietro
      </UiButton>
      <UiButton variant="primary" size="sm" :disabled="!canAdvance" @click="next">
        {{ step < total - 1 ? 'Avanti' : 'Invia' }}
      </UiButton>
    </div>
  </div>
</template>

<style scoped>
.ask-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface-1);
}

.ask-card__progress {
  font-size: 11px;
  opacity: 0.6;
}

.ask-card__question {
  margin: 0;
  font-weight: 600;
}

.ask-card__options {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ask-card__option {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  text-align: left;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: inherit;
  cursor: pointer;
  transition:
    border-color 0.15s,
    background 0.15s;
}

.ask-card__option--on {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 12%, var(--surface-2));
}

.ask-card__marker {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  border: 1.5px solid var(--border-strong);
}

.ask-card__marker.radio {
  border-radius: 50%;
}

.ask-card__marker.checkbox {
  border-radius: 3px;
}

.ask-card__option--on .ask-card__marker {
  background: var(--accent);
  border-color: var(--accent);
}

.ask-card__free {
  padding: 8px 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: inherit;
  font-family: inherit;
}

.ask-card__nav {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
}
</style>
