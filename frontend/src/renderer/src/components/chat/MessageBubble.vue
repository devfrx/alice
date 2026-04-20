<script setup lang="ts">
/**
 * MessageBubble.vue — Renders a single chat message.
 *
 * User messages are right-aligned with an accent background.
 * Assistant messages are left-aligned with a secondary background
 * and a subtle glow border.  Markdown is rendered via `useMarkdown`.
 * Supports collapsible thinking content and image attachments.
 */
import { computed, ref, watch, onUnmounted, defineAsyncComponent } from 'vue'

import { renderMarkdown } from '../../composables/useMarkdown'
import { useCodeBlocks } from '../../composables/useCodeBlocks'
import { useGenerationState } from '../../composables/useGenerationState'
import { useArtifactsStore } from '../../stores/artifacts'
import { useChatStore } from '../../stores/chat'
import ThinkingSection from './ThinkingSection.vue'
import ToolCallSection from './ToolCallSection.vue'
import MessageVersionNav from './MessageVersionNav.vue'
import AgentPlanCard from './AgentPlanCard.vue'
import AppIcon from '../ui/AppIcon.vue'
import type { ChatMessage, CadModelPayload, ChartPayload, WhiteboardPayload } from '../../types/chat'
import { isWhiteboardPayload } from '../../types/chat'

const CADViewer = defineAsyncComponent(() => import('./CADViewer.vue'))
const ChartViewer = defineAsyncComponent(() => import('./ChartViewer.vue'))
const CADGenerationPlaceholder = defineAsyncComponent(() => import('./CADGenerationPlaceholder.vue'))

const props = withDefaults(
  defineProps<{
    /** The message to render. */
    message: ChatMessage
    /** Total number of edit versions (1 = no edits). */
    versionCount?: number
    /** Currently active version index (0-based). */
    activeVersionIndex?: number
    /** Whether editing is disabled (e.g. during streaming). */
    editDisabled?: boolean
    /** Whether branching is disabled (e.g. during streaming). */
    branchDisabled?: boolean
  }>(),
  { versionCount: 1, activeVersionIndex: 0, editDisabled: false, branchDisabled: false }
)

const emit = defineEmits<{
  /** User wants to edit this message. */
  edit: [messageId: string]
  /** User wants to switch to a different version. */
  'switch-version': [versionGroupId: string, versionIndex: number]
  /** User wants to branch the conversation from this message. */
  branch: [messageId: string]
}>()

/** Whether this assistant message can be branched. */
const isBranchable = computed(() => props.message.role === 'assistant' && !props.branchDisabled)

/** Whether the user message is editable (only user messages). */
const isEditable = computed(() => props.message.role === 'user' && !props.editDisabled)

/** Whether to show the version navigator. */
const hasVersions = computed(() => props.versionCount > 1)

/** Pre-rendered HTML from the message's markdown content. */
const htmlContent = computed(() => renderMarkdown(props.message.content))

/** Pre-rendered HTML from the message's thinking content (if any). */
const thinkingHtml = computed(() =>
  props.message.thinking_content ? renderMarkdown(props.message.thinking_content) : ''
)

/** URL of the image shown in the full-size overlay. */
const overlayImageUrl = ref<string | null>(null)

/** Alt text for the overlay image. */
const overlayImageAlt = ref('')

/** Human-readable time string derived from `created_at`. */
const formattedTime = computed(() => {
  try {
    const date = new Date(props.message.created_at)
    return date.toLocaleTimeString(undefined, {
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return ''
  }
})

/** CSS modifier class based on the message role. */
const bubbleClass = computed(() => `bubble--${props.message.role}`)

const { handleCodeBlockClick } = useCodeBlocks()

/** Whether this is a plain tool result (not CAD/Chart/Whiteboard payload). */
const isPlainToolResult = computed(() =>
  props.message.role === 'tool' && !cadPayload.value && !chartPayload.value && !whiteboardPayload.value
)

/** Whether this message is a context summary (compressed context archive). */
const isContextSummary = computed(() => props.message.is_context_summary === true)
const summaryCollapsed = ref(true)

/** Agent loop run associated with this assistant message (if any). */
const chatStore = useChatStore()
const agentRun = computed(() =>
  props.message.role === 'assistant'
    ? chatStore.getAgentRunByMessageId(props.message.id)
    : null,
)

/** Tool result collapsed state (collapsed by default). */
const toolResultCollapsed = ref(true)

/** Truncated preview for collapsed tool results. */
const toolResultPreview = computed(() => {
  if (!isPlainToolResult.value) return ''
  const text = props.message.content.trim()
  const firstLine = text.split('\n')[0] ?? ''
  return firstLine.length > 120 ? firstLine.slice(0, 120) + '…' : firstLine
})

/**
 * If this is a tool message with a CAD model payload, return the parsed
 * payload — otherwise null.  Used to render CADViewer inline.
 */
const cadPayload = computed((): CadModelPayload | null => {
  if (props.message.role !== 'tool') return null
  try {
    const p = JSON.parse(props.message.content)
    if (typeof p.model_name === 'string' && typeof p.export_url === 'string') {
      return p as CadModelPayload
    }
  } catch { /* not JSON */ }
  return null
})

/**
 * If this is a tool message with a Chart payload, return the parsed
 * payload — otherwise null.  Used to render ChartViewer inline.
 */
const chartPayload = computed((): ChartPayload | null => {
  if (props.message.role !== 'tool') return null
  try {
    const p = JSON.parse(props.message.content)
    if (
      typeof p.chart_id === 'string' &&
      typeof p.chart_url === 'string' &&
      typeof p.chart_type === 'string'
    ) {
      return p as ChartPayload
    }
  } catch { /* not JSON chart payload */ }
  return null
})

/**
 * If this is a tool message with a Whiteboard payload, return the parsed
 * payload — otherwise null.  Used to render a whiteboard card inline.
 */
const whiteboardPayload = computed((): WhiteboardPayload | null => {
  if (props.message.role !== 'tool') return null
  try {
    const p = JSON.parse(props.message.content)
    if (isWhiteboardPayload(p)) return p
  } catch { /* not JSON */ }
  return null
})

/* ── Artifact lookup + in-progress generation overlay ──────────────────── */

const artifactsStore = useArtifactsStore()
const { cadGenerationInProgress } = useGenerationState()

/** Artifact id matched by ``tool_call_id``, when this is a tool message. */
const artifactId = computed<string | undefined>(() => {
  if (props.message.role !== 'tool' || !props.message.tool_call_id) return undefined
  return artifactsStore.byToolCallId(props.message.tool_call_id)?.id
})

/**
 * Show the inline CAD generation placeholder on the assistant message that
 * issued the in-flight cad tool call. Matched by tool_call id presence
 * inside ``message.tool_calls``.
 */
const showInlineGenerationPlaceholder = computed(() => {
  if (props.message.role !== 'assistant') return false
  const gen = cadGenerationInProgress.value
  if (!gen) return false
  const calls = props.message.tool_calls ?? []
  return calls.some((c) => c.function?.name === gen.toolName)
})

/** Emit version switch with the message's version_group_id. */
function onVersionSwitch(idx: number): void {
  if (props.message.version_group_id) {
    emit('switch-version', props.message.version_group_id, idx)
  }
}

/** Open full-size image overlay. */
function openOverlay(url: string, alt: string): void {
  overlayImageUrl.value = url
  overlayImageAlt.value = alt
}

/** Close the full-size image overlay. */
function closeOverlay(): void {
  overlayImageUrl.value = null
  overlayImageAlt.value = ''
}

/** Handle Escape key to close overlay. */
function handleKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && overlayImageUrl.value) {
    closeOverlay()
  }
}

watch(overlayImageUrl, (url) => {
  if (url) {
    window.addEventListener('keydown', handleKeydown)
  } else {
    window.removeEventListener('keydown', handleKeydown)
  }
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <div class="bubble-row" :class="`row--${message.role}`" role="article" :aria-label="`Messaggio ${message.role}`">
    <!-- User hover actions — to the left of the bubble -->
    <div v-if="message.role === 'user'" class="bubble-side-actions">
      <span class="bubble__time">{{ formattedTime }}</span>
      <button v-if="isEditable" class="bubble__edit-btn" aria-label="Modifica messaggio"
        @click="emit('edit', message.id)">
        <AppIcon name="edit" :size="14" />
      </button>
    </div>

    <div class="bubble" :class="bubbleClass">
      <!-- Image attachments -->
      <div v-if="message.attachments?.length" class="bubble__attachments">
        <div v-for="att in message.attachments" :key="att.file_id" class="bubble__attachment" :title="att.filename"
          @click="openOverlay(att.url, att.filename)">
          <img :src="att.url" :alt="att.filename" loading="lazy" />
        </div>
      </div>

      <!-- Thinking section (assistant only) -->
      <ThinkingSection v-if="message.thinking_content" :thinking-html="thinkingHtml" :initial-collapsed="true" />

      <!-- Context summary (compressed context archive) -->
      <div v-if="isContextSummary" class="context-summary">
        <button class="context-summary__toggle" @click="summaryCollapsed = !summaryCollapsed">
          <span class="context-summary__icon">📦</span>
          <span class="context-summary__title">Contesto compresso</span>
          <AppIcon name="chevron-down" :size="12" :stroke-width="1.5" class="context-summary__chevron"
            :class="{ 'context-summary__chevron--open': !summaryCollapsed }" />
        </button>
        <div class="context-summary__body" :class="{ 'context-summary__body--collapsed': summaryCollapsed }">
          <!-- eslint-disable-next-line vue/no-v-html — content is sanitised by markdown-it -->
          <div class="context-summary__content" v-html="htmlContent" @click="handleCodeBlockClick" />
        </div>
      </div>

      <!-- Tool calls section (assistant only) -->
      <ToolCallSection v-if="message.tool_calls?.length" :tool-calls="message.tool_calls ?? []" />

      <!-- Inline placeholder while a CAD generation tied to this assistant
           message is still running. -->
      <CADGenerationPlaceholder v-if="showInlineGenerationPlaceholder && cadGenerationInProgress" compact
        :generation="cadGenerationInProgress" />

      <!-- CAD model viewer (tool message with cad-model payload) -->
      <CADViewer v-if="cadPayload" :model-url="cadPayload.export_url" :model-name="cadPayload.model_name"
        :artifact-id="artifactId" />

      <!-- Chart viewer (tool message with chart payload) -->
      <ChartViewer v-if="chartPayload" :payload="chartPayload" />

      <!-- Whiteboard card (tool message with whiteboard payload) -->
      <div v-if="whiteboardPayload" class="whiteboard-card">
        <AppIcon name="whiteboard-card" :size="14" :stroke-width="1.5" class="whiteboard-card__icon" />
        <span class="whiteboard-card__title">{{ whiteboardPayload.title }}</span>
        <span class="whiteboard-card__badge">Lavagna</span>
      </div>

      <!-- Plain tool result — collapsible -->
      <template v-if="isPlainToolResult">
        <button class="tool-result__toggle" @click="toolResultCollapsed = !toolResultCollapsed">
          <AppIcon name="check" :size="12" :stroke-width="2.5" class="tool-result__icon" />
          <span class="tool-result__label">Risultato</span>
          <span v-if="toolResultCollapsed" class="tool-result__preview">{{ toolResultPreview }}</span>
          <AppIcon name="chevron-down" :size="10" class="tool-result__chevron"
            :class="{ 'tool-result__chevron--open': !toolResultCollapsed }" />
        </button>
        <div class="tool-result__body" :class="{ 'tool-result__body--collapsed': toolResultCollapsed }">
          <div class="tool-result__inner">
            <!-- eslint-disable-next-line vue/no-v-html — content is sanitised by markdown-it -->
            <div class="bubble__content" v-html="htmlContent" @click="handleCodeBlockClick" />
          </div>
        </div>
      </template>

      <!-- Message content (non-tool or assistant/user) -->
      <!-- eslint-disable-next-line vue/no-v-html — content is sanitised by markdown-it -->
      <div v-if="!cadPayload && !chartPayload && !whiteboardPayload && !isPlainToolResult && !isContextSummary"
        class="bubble__content" v-html="htmlContent" @click="handleCodeBlockClick" />

      <!-- Agent loop plan card (assistant only, when an agent run produced this message) -->
      <AgentPlanCard v-if="agentRun" :run="agentRun" />

      <!-- Timestamp for assistant/tool messages (inside bubble) -->
      <span v-if="message.role !== 'user'" class="bubble__time">{{ formattedTime }}</span>

      <!-- Version navigator — only for user messages, inside the bubble -->
      <MessageVersionNav v-if="hasVersions && message.role === 'user' && message.version_group_id"
        :active-index="activeVersionIndex" :total-versions="versionCount" :disabled="editDisabled"
        @switch="onVersionSwitch" />
    </div>

    <!-- Assistant hover actions — to the right of the assistant bubble -->
    <div v-if="message.role === 'assistant'" class="bubble-side-actions bubble-side-actions--right">
      <button v-if="isBranchable" class="bubble__branch-btn" aria-label="Dirama conversazione da qui"
        :title="`Inizia una nuova conversazione da questo punto`" @click="emit('branch', message.id)">
        <!-- Git fork icon -->
        <AppIcon name="branch" :size="14" />
      </button>
    </div>

    <!-- Full-size image overlay -->
    <Teleport to="body">
      <div v-if="overlayImageUrl" class="image-overlay" @click.self="closeOverlay">
        <button class="image-overlay__close" aria-label="Chiudi" @click="closeOverlay">
          <AppIcon name="x" :size="24" />
        </button>
        <img :src="overlayImageUrl" :alt="overlayImageAlt" class="image-overlay__img" />
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* MessageBubble — Supabase-clean */

/* Row layout */
.bubble-row {
  display: flex;
  align-items: flex-end;
  margin-bottom: var(--space-4);
  position: relative;
}

.row--user {
  justify-content: flex-end;
  gap: var(--space-2);
}

.row--assistant,
.row--tool {
  justify-content: flex-start;
}

/* Side actions bar — to the left of user bubbles, visible on row hover */
.bubble-side-actions {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  opacity: 0;
  transition: opacity var(--transition-fast);
  flex-shrink: 0;
}

.row--user:hover .bubble-side-actions {
  opacity: 1;
}

/* Branch button — to the right of assistant bubbles, visible on row hover */
.bubble-side-actions--right {
  order: 1;
}

.row--assistant:hover .bubble-side-actions--right,
.row--tool:hover .bubble-side-actions--right {
  opacity: 1;
}

/* Branch button */
.bubble__branch-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: color var(--transition-fast), background var(--transition-fast);
}

.bubble__branch-btn:hover {
  color: var(--text-primary);
  background: var(--surface-2);
}

.bubble-side-actions .bubble__time {
  position: static;
  transform: none;
  opacity: 1;
  pointer-events: auto;
}

/* Edit button (inside side-actions bar) */
.bubble__edit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: color var(--transition-fast), background var(--transition-fast);
}

.bubble__edit-btn:hover {
  color: var(--text-primary);
  background: var(--surface-2);
}

/* Bubble base */
.bubble {
  position: relative;
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  word-break: break-word;
}

/* User bubble */
.bubble--user {
  max-width: 65%;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-primary);
  padding: var(--space-3) var(--space-4);
  line-height: var(--leading-relaxed);
  animation: slideInRight 300ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* Assistant bubble */
.bubble--assistant {
  max-width: 82%;
  background: transparent;
  border: none;
  border-radius: 0;
  padding: var(--space-3) var(--space-4);
  color: var(--text-primary);
  line-height: var(--leading-relaxed);
  animation: slideInLeft 300ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* Tool result bubble */
.bubble--tool {
  max-width: 82%;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  padding: var(--space-3) var(--space-4);
  line-height: var(--leading-relaxed);
  animation: slideInLeft 300ms cubic-bezier(0.16, 1, 0.3, 1) both;
}

/* When tool bubble contains a CAD viewer, remove the mono/small styling
   so the viewer renders at full width without text constraints */
.bubble--tool:has(.cad-viewer),
.bubble--tool:has(.chart-viewer) {
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  background: transparent;
  border-color: transparent;
  padding: 0;
}

/* Whiteboard card — same treatment as CAD/Chart */
.bubble--tool:has(.whiteboard-card) {
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  background: transparent;
  border-color: transparent;
  padding: 0;
}

.whiteboard-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.whiteboard-card__icon {
  flex-shrink: 0;
  color: var(--accent);
}

.whiteboard-card__title {
  flex: 1;
  color: var(--text-primary);
  font-weight: var(--weight-medium);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.whiteboard-card__badge {
  font-size: var(--text-xs);
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

/* Collapsible tool result */
.tool-result__toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: 0;
  background: none;
  border: none;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-size: var(--text-xs);
  cursor: pointer;
  text-align: left;
  transition: color var(--transition-fast);
}

.tool-result__toggle:hover {
  color: var(--text-primary);
}

.tool-result__icon {
  flex-shrink: 0;
  color: var(--success);
}

.tool-result__label {
  font-weight: var(--weight-medium);
  white-space: nowrap;
}

.tool-result__preview {
  flex: 1;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.tool-result__chevron {
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform var(--transition-fast);
}

.tool-result__chevron--open {
  transform: rotate(180deg);
}

.tool-result__body {
  display: grid;
  grid-template-rows: 1fr;
  opacity: 1;
  transition:
    grid-template-rows var(--duration-normal) ease,
    opacity var(--duration-normal) ease;
}

.tool-result__body--collapsed {
  grid-template-rows: 0fr;
  opacity: 0;
  pointer-events: none;
}

.tool-result__inner {
  overflow: hidden;
  min-height: 0;
}

.tool-result__inner .bubble__content {
  margin-top: var(--space-2);
  max-height: 300px;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}

.tool-result__inner .bubble__content::-webkit-scrollbar {
  width: 3px;
}

.tool-result__inner .bubble__content::-webkit-scrollbar-track {
  background: transparent;
}

.tool-result__inner .bubble__content::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: var(--radius-xs);
}

/* Attachments */
.bubble__attachments {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.bubble__attachment {
  width: 144px;
  height: 104px;
  border-radius: var(--radius-sm);
  overflow: hidden;
  cursor: pointer;
  border: 1px solid var(--border);
  transition: border-color var(--transition-fast);
}

.bubble__attachment:hover {
  border-color: var(--accent-border);
}

.bubble__attachment img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

/* Content typography */
.bubble__content {
  overflow-wrap: break-word;
  user-select: text;
  cursor: text;
}

.bubble__content :deep(p) {
  margin: 0 0 0.5em;
}

.bubble__content :deep(p:last-child) {
  margin-bottom: 0;
}

.bubble__content :deep(a) {
  color: var(--accent);
  text-decoration: underline;
  text-decoration-color: var(--accent-border);
  text-underline-offset: 2px;
  transition: text-decoration-color var(--transition-fast);
}

.bubble__content :deep(a:hover) {
  text-decoration-color: var(--accent);
}

.bubble__content :deep(ul),
.bubble__content :deep(ol) {
  padding-left: 1.4em;
  margin: 0.4em 0;
}

.bubble__content :deep(blockquote) {
  border-left: 2px solid var(--border);
  margin: 0.5em 0;
  padding: var(--space-2) var(--space-3);
  color: var(--text-secondary);
}

/* Timestamp — hover to reveal, positioned to the side */
.bubble__time {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  opacity: 0;
  white-space: nowrap;
  pointer-events: none;
  transition: opacity var(--transition-fast);
}

.bubble:hover .bubble__time {
  opacity: 1;
}

.row--assistant .bubble__time,
.row--tool .bubble__time {
  left: calc(100% + var(--space-3));
  right: auto;
}

/* Image overlay */
.image-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--black-overlay);
  animation: overlayFadeIn 200ms ease both;
}

.image-overlay__close {
  position: absolute;
  top: var(--space-4);
  right: var(--space-4);
  background: none;
  border: none;
  padding: var(--space-2);
  cursor: pointer;
  color: var(--text-secondary);
  transition: color var(--transition-fast);
}

.image-overlay__close:hover {
  color: var(--text-primary);
}

.image-overlay__img {
  max-width: 90vw;
  max-height: 88vh;
  object-fit: contain;
  border-radius: var(--radius-md);
  animation: overlayZoomIn 250ms ease both;
}

/* Keyframes */
@keyframes slideInRight {
  from {
    opacity: 0;
    transform: translateX(20px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes slideInLeft {
  from {
    opacity: 0;
    transform: translateX(-20px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes bubbleFadeIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

@keyframes overlayFadeIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

@keyframes overlayZoomIn {
  from {
    opacity: 0;
    transform: scale(0.96);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}

/* Context summary (compressed archive bubble) */
.context-summary {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  overflow: hidden;
}

.context-summary__toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: var(--text-xs);
  cursor: pointer;
  text-align: left;
}

.context-summary__toggle:hover {
  color: var(--text-secondary);
}

.context-summary__icon {
  flex-shrink: 0;
}

.context-summary__title {
  flex: 1;
  font-weight: var(--weight-medium);
  white-space: nowrap;
}

.context-summary__chevron {
  flex-shrink: 0;
  color: var(--text-muted);
  transition: transform var(--transition-fast);
}

.context-summary__chevron--open {
  transform: rotate(180deg);
}

.context-summary__body {
  display: grid;
  grid-template-rows: 1fr;
  opacity: 1;
  transition: grid-template-rows var(--duration-normal) ease,
    opacity var(--duration-normal) ease;
}

.context-summary__body--collapsed {
  grid-template-rows: 0fr;
  opacity: 0;
  pointer-events: none;
}

.context-summary__content {
  overflow: hidden;
  min-height: 0;
  padding: 0 var(--space-3) var(--space-2);
  color: var(--text-muted);
  font-size: var(--text-xs);
  line-height: 1.5;
}

@media (prefers-reduced-motion: reduce) {

  .bubble--user,
  .bubble--assistant,
  .bubble--tool,
  .image-overlay,
  .image-overlay__img {
    animation: none !important;
  }

  .bubble__time,
  .bubble__attachment,
  .image-overlay__close {
    transition: none;
  }
}
</style>
