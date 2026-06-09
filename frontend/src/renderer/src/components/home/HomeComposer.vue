<script setup lang="ts">
/**
 * Hero composer for the home. Purely presentational: it owns no chat logic,
 * just two-way text binding + a `submit` event. The parent (HomeView) calls
 * the real `useChat().sendMessage` flow and navigates. Enter submits;
 * Shift+Enter inserts a newline.
 */
import { ref } from 'vue'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [string]; submit: [] }>()

const el = ref<HTMLTextAreaElement | null>(null)

function onInput(e: Event): void {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}

function submit(): void {
  if (props.modelValue.trim()) emit('submit')
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

defineExpose({ focus: (): void => el.value?.focus() })
</script>

<template>
  <div class="hc">
    <textarea
      ref="el"
      class="hc__input"
      rows="1"
      :value="modelValue"
      placeholder="Chiedi, pianifica, o lascia che me ne occupi io…"
      aria-label="Messaggio per Alice"
      @input="onInput"
      @keydown="onKeydown"
    />
    <button
      class="hc__send"
      type="button"
      aria-label="Invia"
      :disabled="!modelValue.trim()"
      @click="submit"
    >
      <AppIcon name="send" :size="16" />
    </button>
  </div>
</template>

<style scoped>
.hc {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-4) var(--space-4) var(--space-6);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  transition:
    border-color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.hc:focus-within {
  border-color: var(--accent-border);
  box-shadow: var(--shadow-md);
}

.hc__input {
  flex: 1;
  min-height: 36px;
  max-height: 160px;
  padding-block: var(--space-1);
  resize: none;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-lg);
  line-height: var(--leading-snug);
}

.hc__input::placeholder {
  color: var(--text-muted);
}

.hc__send {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--accent);
  color: var(--text-on-accent);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    opacity var(--transition-fast);
}

.hc__send:hover:not(:disabled) {
  background: var(--accent-hover);
}

.hc__send:disabled {
  opacity: var(--opacity-disabled);
  cursor: default;
}
</style>
