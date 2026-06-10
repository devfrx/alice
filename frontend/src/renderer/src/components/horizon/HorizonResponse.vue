<script setup lang="ts">
/**
 * HorizonResponse — the serif response above the line.
 *
 * Two layouts: "stage" (large centered serif, a few sentences) and
 * "magazine" (a scrollable reading column with a drop cap) for long answers.
 * The component only *reports* when the magazine threshold is crossed —
 * the parent owns the flag (it also drives the scene's line quota).
 */
import { computed, watch } from 'vue'
import { renderMarkdown } from '../../composables/useMarkdown'
import { useCodeBlocks } from '../../composables/useCodeBlocks'

const props = defineProps<{
  text: string
  userQuery: string
  magazine: boolean
  /** Compact mode while the stage (presenting) is open. */
  compact?: boolean
}>()

const emit = defineEmits<{ 'update:magazine': [v: boolean] }>()

const MAGAZINE_THRESHOLD = 5

const sentenceCount = computed(() => (props.text.match(/[.!?…]+(\s|$)/g) ?? []).length)

watch(
  sentenceCount,
  (n) => {
    // Never flip while compact (presenting): the stage owns the lower zone
    // and a magazine column there would squeeze it to half height.
    if (n > MAGAZINE_THRESHOLD && !props.magazine && !props.compact) {
      emit('update:magazine', true)
    }
  },
  { immediate: true }
)

const html = computed(() => renderMarkdown(props.text))

const { handleCodeBlockClick } = useCodeBlocks()
</script>

<template>
  <div
    class="hz-response"
    :class="{ 'hz-response--magazine': magazine, 'hz-response--compact': compact }"
  >
    <!-- eslint-disable-next-line vue/no-v-html -->
    <div class="hz-response__body markdown-body" @click="handleCodeBlockClick" v-html="html" />
  </div>
</template>

<style scoped>
.hz-response {
  width: min(78%, 760px);
  margin-bottom: clamp(16px, 3vh, 40px);
  overflow: hidden;
}

.hz-response__body {
  font-family: var(--hz-serif);
  font-weight: 300;
  font-size: clamp(17px, 2.4vmin, 24px);
  line-height: 1.6;
  color: var(--hz-ink);
  text-align: center;
}

.hz-response__body :deep(p) {
  margin: 0 0 0.6em;
}

.hz-response__body :deep(code),
.hz-response__body :deep(pre) {
  font-family: var(--font-mono);
  font-size: 0.78em;
  text-align: left;
}

/* ── magazine: long answers become a reading column ── */
.hz-response--magazine {
  width: min(86%, 760px);
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  scrollbar-width: thin;
}

.hz-response--magazine .hz-response__body {
  text-align: left;
  font-size: clamp(15px, 1.9vmin, 19px);
  max-width: 64ch;
  margin: 0 auto;
  padding-bottom: var(--space-4);
}

.hz-response--magazine .hz-response__body :deep(> p:first-child)::first-letter {
  font-size: 2.6em;
  float: left;
  line-height: 0.85;
  margin: 0.04em 0.12em 0 0;
  color: var(--hz-gold);
}

/* ── compact: text recedes while the stage presents ── */
.hz-response--compact {
  margin-bottom: var(--space-2);
}

.hz-response--compact .hz-response__body {
  font-size: clamp(13px, 1.5vmin, 16px);
  color: var(--hz-ink-dim);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
