<script setup lang="ts">
/**
 * UiTextarea — Multiline input with the same states/a11y as UiInput.
 *
 *  - Real <label for> / <textarea id> association (auto id via useId).
 *  - aria-invalid + aria-describedby for error / hint.
 *  - `autoGrow` resizes the textarea to its content (up to maxRows).
 */
import { computed, ref, useId, watch, nextTick, onMounted } from 'vue'

export interface UiTextareaProps {
  modelValue?: string
  placeholder?: string
  label?: string
  hint?: string
  error?: string
  disabled?: boolean
  readonly?: boolean
  required?: boolean
  rows?: number
  /** Grow with content instead of showing a scrollbar. */
  autoGrow?: boolean
  /** Upper bound for autoGrow, in rows. */
  maxRows?: number
  maxlength?: number
  name?: string
  id?: string
  ariaLabel?: string
}

const props = withDefaults(defineProps<UiTextareaProps>(), {
  modelValue: '',
  placeholder: '',
  label: '',
  hint: '',
  error: '',
  disabled: false,
  readonly: false,
  required: false,
  rows: 3,
  autoGrow: false,
  maxRows: 10,
  maxlength: undefined,
  name: undefined,
  id: undefined,
  ariaLabel: undefined
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  focus: [event: FocusEvent]
  blur: [event: FocusEvent]
  keydown: [event: KeyboardEvent]
}>()

const autoId = useId()
const fieldId = computed(() => props.id ?? `ui-textarea-${autoId}`)
const errorId = computed(() => `${fieldId.value}-error`)
const hintId = computed(() => `${fieldId.value}-hint`)
const describedBy = computed(() => {
  if (props.error) return errorId.value
  if (props.hint) return hintId.value
  return undefined
})

const el = ref<HTMLTextAreaElement | null>(null)

function resize(): void {
  const node = el.value
  if (!node || !props.autoGrow) return
  node.style.height = 'auto'
  const lineHeight = parseFloat(getComputedStyle(node).lineHeight) || 20
  const max = props.maxRows * lineHeight
  node.style.height = `${Math.min(node.scrollHeight, max)}px`
  node.style.overflowY = node.scrollHeight > max ? 'auto' : 'hidden'
}

function onInput(e: Event): void {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}

watch(
  () => props.modelValue,
  () => void nextTick(resize)
)
onMounted(resize)
</script>

<template>
  <div
    class="ui-textarea"
    :class="{ 'ui-textarea--error': error, 'ui-textarea--disabled': disabled }"
  >
    <label v-if="label" :for="fieldId" class="ui-textarea__label">
      {{ label }}
      <span v-if="required" class="ui-textarea__required" aria-hidden="true">*</span>
    </label>
    <textarea
      :id="fieldId"
      ref="el"
      class="ui-textarea__field"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      :readonly="readonly"
      :required="required"
      :rows="rows"
      :maxlength="maxlength"
      :name="name"
      :aria-label="ariaLabel || undefined"
      :aria-invalid="!!error || undefined"
      :aria-describedby="describedBy"
      @input="onInput"
      @focus="emit('focus', $event)"
      @blur="emit('blur', $event)"
      @keydown="emit('keydown', $event)"
    />
    <p v-if="error" :id="errorId" class="ui-textarea__error" role="alert">{{ error }}</p>
    <p v-else-if="hint" :id="hintId" class="ui-textarea__hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.ui-textarea {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.ui-textarea__label {
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
  display: inline-flex;
  gap: var(--space-1);
}

.ui-textarea__required {
  color: var(--danger);
}

.ui-textarea__field {
  width: 100%;
  min-height: calc(var(--input-height-md) * 1.5);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  resize: vertical;
  transition:
    background-color var(--duration-fast) var(--ease-out-quart),
    border-color var(--duration-fast) var(--ease-out-quart);
}

.ui-textarea__field::placeholder {
  color: var(--text-muted);
}

.ui-textarea:not(.ui-textarea--disabled):not(.ui-textarea--error) .ui-textarea__field:hover {
  border-color: var(--border-hover);
}

.ui-textarea:not(.ui-textarea--error) .ui-textarea__field:focus {
  border-color: var(--accent-border);
  outline: none;
}

.ui-textarea--error .ui-textarea__field {
  border-color: var(--danger-border);
}

.ui-textarea__error {
  font-size: var(--text-xs);
  color: var(--danger);
}

.ui-textarea__hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.ui-textarea--disabled {
  opacity: var(--opacity-disabled);
  pointer-events: none;
}

.ui-textarea--disabled .ui-textarea__field {
  background: var(--surface-inset);
  resize: none;
}
</style>
