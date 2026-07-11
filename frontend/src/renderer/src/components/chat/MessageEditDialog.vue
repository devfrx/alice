<script setup lang="ts">
/**
 * MessageEditDialog.vue — Inline dialog for editing a sent message.
 *
 * Rendered inside the UiModal shell via `useModal().openCustom()`.
 * Emits `'close'` with `true` (submitted) or `false` (cancelled).
 * The edited string is delivered via the `onSubmit` callback prop
 * because `openCustom` resolves only a boolean.
 *
 * Supports Ctrl/Cmd+Enter to submit.  Escape is handled by ModalContainer.
 */
import { ref, onMounted, nextTick } from 'vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiButton from '../ui/UiButton.vue'
import UiTextarea from '../ui/UiTextarea.vue'

const props = defineProps<{
  /** Original message content to edit. */
  originalContent: string
  /** Called with the edited string before `emit('close', true)`. */
  onSubmit: (content: string) => void | Promise<void>
}>()

const emit = defineEmits<{ close: [result: boolean] }>()

const content = ref(props.originalContent)
const dialogRef = ref<HTMLElement | null>(null)

async function handleSubmit(): Promise<void> {
  const trimmed = content.value.trim()
  if (trimmed && trimmed !== props.originalContent) {
    await props.onSubmit(trimmed)
    emit('close', true)
  } else {
    emit('close', false)
  }
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    void handleSubmit()
  }
}

onMounted(async () => {
  await nextTick()
  const el = dialogRef.value?.querySelector('textarea')
  if (el) {
    el.focus()
    el.setSelectionRange(el.value.length, el.value.length)
  }
})
</script>

<template>
  <div ref="dialogRef" class="edit-dialog" @keydown="handleKeydown">
    <div class="edit-dialog__header">
      <span class="edit-dialog__title">Modifica messaggio</span>
      <UiIconButton size="sm" variant="ghost" label="Annulla" @click="emit('close', false)">
        <AppIcon name="x" :size="16" />
      </UiIconButton>
    </div>
    <UiTextarea
      v-model="content"
      :rows="3"
      auto-grow
      :max-rows="14"
      placeholder="Scrivi il messaggio modificato…"
      aria-label="Modifica messaggio"
    />
    <div class="edit-dialog__actions">
      <span class="edit-dialog__hint">Ctrl+Invio per inviare</span>
      <div class="edit-dialog__buttons">
        <UiButton variant="secondary" size="sm" @click="emit('close', false)">Annulla</UiButton>
        <UiButton
          variant="primary"
          size="sm"
          :disabled="!content.trim() || content.trim() === originalContent"
          @click="handleSubmit"
        >
          Invia modifica
        </UiButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.edit-dialog {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.edit-dialog__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.edit-dialog__title {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
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
</style>
