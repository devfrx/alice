<script setup lang="ts">
/**
 * HorizonComposer — the materializing input: a boxless serif line above the
 * horizon. Shows the live STT transcript while listening/processing;
 * otherwise an editable line seeded with the first globally-typed character.
 */
import { nextTick, ref, watch } from 'vue'

const props = defineProps<{
  /** Typed-composition mode is active. */
  active: boolean
  listening: boolean
  sttProcessing: boolean
  transcript: string
  disabled: boolean
}>()

const emit = defineEmits<{
  send: [text: string]
  paste: [event: ClipboardEvent]
}>()

const text = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)
const multiline = ref(false)

/** Grow with content up to ~5 lines, then scroll; left-align once wrapped. */
function autoResize(): void {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  const lineH = parseFloat(getComputedStyle(el).lineHeight) || 33
  el.style.height = `${Math.min(el.scrollHeight, lineH * 5)}px`
  multiline.value = el.scrollHeight > lineH * 1.5
}

watch(text, () => nextTick(autoResize))

watch(
  () => props.active,
  async (active) => {
    if (active) {
      await nextTick()
      inputRef.value?.focus()
      autoResize()
    } else {
      text.value = ''
      multiline.value = false
    }
  }
)

/** Seed the first character captured by the view's global keydown. */
function seed(ch: string): void {
  text.value += ch
  void nextTick(() => {
    inputRef.value?.focus()
    autoResize()
  })
}

/** Programmatic send (cockpit send button). */
function submit(): void {
  const t = text.value.trim()
  if (t && !props.disabled) {
    emit('send', t)
    text.value = ''
  }
}

defineExpose({ seed, submit })

function onKeydown(e: KeyboardEvent): void {
  if (e.isComposing) return
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    const t = text.value.trim()
    if (t && !props.disabled) {
      emit('send', t)
      text.value = ''
    }
  }
}
</script>

<template>
  <div v-if="active || listening || sttProcessing" class="hz-composer">
    <p v-if="listening || sttProcessing" class="hz-composer__transcript" aria-live="polite">
      <em>{{ transcript || (listening ? 'Ti ascolto…' : 'Elaboro…') }}</em>
    </p>
    <textarea
      v-else
      ref="inputRef"
      v-model="text"
      class="hz-composer__input"
      :class="{ 'hz-composer__input--multi': multiline }"
      rows="1"
      aria-label="Scrivi ad AL\CE"
      placeholder=""
      @keydown="onKeydown"
      @input="autoResize"
      @paste="(e) => emit('paste', e)"
    />
  </div>
</template>

<style scoped>
.hz-composer {
  width: min(72%, 720px);
  margin-bottom: clamp(20px, 4vh, 48px);
  text-align: center;
}

.hz-composer__transcript {
  margin: 0;
  font-family: var(--hz-serif);
  font-style: italic;
  font-weight: 300;
  font-size: clamp(18px, 2.6vmin, 26px);
  line-height: 1.5;
  color: var(--hz-ink-dim);
}

.hz-composer__input {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  overflow-y: auto;
  scrollbar-width: thin;
  text-align: center;
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: clamp(18px, 2.6vmin, 26px);
  line-height: 1.5;
  color: var(--hz-ink);
  caret-color: var(--hz-gold);
}

/* Wrapped content reads better ragged-right than centered. */
.hz-composer__input--multi {
  text-align: left;
}
</style>
