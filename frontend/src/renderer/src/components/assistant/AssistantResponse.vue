<script setup lang="ts">
/**
 * AssistantResponse.vue — OMNIA voice output.
 *
 * Renders OMNIA's response as if it's speaking directly — no chat card,
 * centered flowing text that emanates from the orb. Supports markdown,
 * thinking/reasoning section, tool call/execution timeline, and streaming.
 */
import { computed, ref, watch, nextTick, onMounted } from 'vue'
import { renderMarkdown } from '../../utils/markdownRenderer'
import OmniaSpinner from '../../components/ui/OmniaSpinner.vue'
import ToolCallSection from '../chat/ToolCallSection.vue'
import ToolExecutionIndicator from '../chat/ToolExecutionIndicator.vue'
import type { ToolCall, ToolExecution } from '../../types/chat'

const props = withDefaults(
    defineProps<{
        content: string
        isStreaming: boolean
        thinkingContent: string
        /** Live tool executions during streaming. */
        toolExecutions?: ToolExecution[]
        /** Completed tool calls from assistant messages. */
        toolCalls?: ToolCall[]
        /** The user's original query (for echo display). */
        userQuery?: string
    }>(),
    {
        toolExecutions: () => [],
        toolCalls: () => [],
        userQuery: '',
    }
)

/** Whether to show live execution indicator (streaming + has active tools). */
const showToolExecution = computed(
    () => props.isStreaming && props.toolExecutions.length > 0
)

/** Whether to show completed tool calls summary (not streaming, has calls). */
const showToolCalls = computed(
    () => !props.isStreaming && props.toolCalls.length > 0
)

const thinkingExpanded = ref(false)
const scrollContainer = ref<HTMLElement | null>(null)

/** Whether the assistant is currently in the thinking phase (no content yet). */
const isThinkingPhase = computed(
    () => !!props.thinkingContent && !props.content && props.isStreaming
)

/** Whether we're actively generating response content. */
const isGenerating = computed(() => props.isStreaming && !!props.content)

/** Rendered HTML for the main response content. */
const renderedContent = computed(() => renderMarkdown(props.content))

/** Rendered HTML for the thinking content. */
const renderedThinking = computed(() => renderMarkdown(props.thinkingContent))

/** Truncated thinking preview (first ~2 lines). */
const thinkingPreview = computed(() => {
    if (!props.thinkingContent) return ''
    const lines = props.thinkingContent.split('\n').filter((l) => l.trim())
    const preview = lines.slice(0, 2).join(' ')
    return preview.length > 120 ? preview.slice(0, 120) + '…' : preview
})

/** Auto-scroll to bottom during streaming. */
watch(
    () => props.content + props.thinkingContent,
    async () => {
        if (!props.isStreaming) return
        await nextTick()
        if (scrollContainer.value) {
            scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight
        }
    }
)

/** Expand thinking section automatically during thinking phase. */
watch(isThinkingPhase, (thinking) => {
    if (thinking) thinkingExpanded.value = true
})

onMounted(() => {
    if (isThinkingPhase.value) thinkingExpanded.value = true
})
</script>

<template>
    <div ref="scrollContainer" class="omnia-voice" :class="{
        'omnia-voice--thinking': isThinkingPhase,
        'omnia-voice--generating': isGenerating,
        'omnia-voice--complete': !isStreaming && !!content
    }">
        <!-- Glowing connector dot from orb -->
        <div class="omnia-voice__connector">
            <span class="omnia-voice__dot" />
        </div>

        <!-- User query echo -->
        <p v-if="userQuery" class="omnia-voice__query">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
            </svg>
            {{ userQuery }}
        </p>

        <!-- Thinking section -->
        <div v-if="thinkingContent" class="thinking-section" :class="{ 'thinking-section--active': isThinkingPhase }">
            <button class="thinking-toggle" @click="thinkingExpanded = !thinkingExpanded">
                <span class="thinking-toggle__icon">✦</span>
                <span class="thinking-toggle__label">Ragionamento</span>
                <span v-if="isThinkingPhase" class="thinking-toggle__indicator" />
                <span class="thinking-toggle__chevron"
                    :class="{ 'thinking-toggle__chevron--open': thinkingExpanded }">›</span>
            </button>

            <!-- Collapsed preview -->
            <p v-if="!thinkingExpanded" class="thinking-preview">
                {{ thinkingPreview }}
            </p>

            <!-- Expanded content -->
            <Transition name="thinking-expand">
                <div v-if="thinkingExpanded" class="thinking-body" v-html="renderedThinking" />
            </Transition>
        </div>

        <!-- Main response content -->
        <div v-if="content" class="response-body" v-html="renderedContent" />

        <!-- Streaming cursor -->
        <span v-if="isStreaming && content" class="streaming-cursor" />

        <!-- Tool activity: live executions during streaming -->
        <Transition name="tool-activity-fade">
            <div v-if="showToolExecution" class="tool-activity">
                <ToolExecutionIndicator :executions="toolExecutions" />
            </div>
        </Transition>

        <!-- Tool activity: completed tool calls after streaming -->
        <Transition name="tool-activity-fade">
            <div v-if="showToolCalls" class="tool-activity">
                <ToolCallSection :tool-calls="toolCalls" />
            </div>
        </Transition>

        <!-- Thinking phase placeholder (no content yet) -->
        <div v-if="isThinkingPhase && !content && !showToolExecution" class="thinking-placeholder">
            <OmniaSpinner size="sm" variant="dots" />
        </div>
    </div>
</template>

<style scoped>
/* ── Container: borderless, open, emanates from orb ── */
.omnia-voice {
    position: relative;
    max-width: 600px;
    width: 100%;
    overflow-y: auto;
    overflow-x: hidden;
    padding: var(--space-2) var(--space-4) var(--space-6);
    color: var(--text-primary);
    font-size: var(--text-md);
    line-height: var(--leading-relaxed);
    font-family: var(--font-sans);
    text-align: center;
    transition: opacity 400ms var(--ease-smooth);
}

/* Scrollbar */
.omnia-voice::-webkit-scrollbar {
    width: 3px;
}

.omnia-voice::-webkit-scrollbar-track {
    background: transparent;
}

.omnia-voice::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: var(--radius-pill);
}

.omnia-voice:hover::-webkit-scrollbar-thumb {
    background: var(--border-hover);
}

/* ── Connector dot from orb ── */
.omnia-voice__connector {
    display: flex;
    justify-content: center;
    margin-bottom: var(--space-3);
}

.omnia-voice__dot {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-full);
    background: var(--accent);
    opacity: 0.6;
    box-shadow: 0 0 10px var(--accent-glow, var(--accent));
    transition:
        opacity 300ms var(--ease-smooth),
        box-shadow 300ms var(--ease-smooth);
}

.omnia-voice--generating .omnia-voice__dot {
    opacity: 1;
    box-shadow: 0 0 16px var(--accent-glow, var(--accent));
    animation: dot-pulse 2s ease-in-out infinite;
}

.omnia-voice--thinking .omnia-voice__dot {
    opacity: 0.8;
    background: var(--thinking);
    box-shadow: 0 0 12px var(--thinking);
    animation: dot-pulse 1.5s ease-in-out infinite;
}

.omnia-voice--complete .omnia-voice__dot {
    opacity: 0.3;
    box-shadow: none;
}

/* ── User query echo ── */
.omnia-voice__query {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    margin: 0 auto var(--space-4);
    padding: var(--space-1) var(--space-3);
    font-size: var(--text-xs);
    color: var(--text-muted);
    background: rgba(255, 255, 255, 0.03);
    border-radius: var(--radius-pill);
    max-width: 80%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.omnia-voice__query svg {
    flex-shrink: 0;
    opacity: 0.5;
}

/* ── Phase states ── */
.omnia-voice--thinking {
    opacity: var(--opacity-visible);
}

.omnia-voice--generating .response-body {
    opacity: 0.92;
}

.omnia-voice--complete .response-body {
    opacity: 1;
    transition: opacity var(--transition-fast);
}

/* ── Thinking Section ── */
.thinking-section {
    position: relative;
    margin-left: var(--space-4);
    margin-bottom: var(--space-4);
}

.thinking-section--active .thinking-body {
    opacity: var(--opacity-soft);
}

.thinking-toggle {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: var(--text-xs);
    cursor: pointer;
    padding: var(--space-1) 0;
    font-family: inherit;
    transition: color var(--transition-fast);
}

.thinking-toggle:hover {
    color: var(--text-primary);
}

.thinking-toggle__icon {
    font-size: 0.7rem;
    color: var(--text-muted);
}

.thinking-toggle__label {
    font-weight: var(--weight-normal);
}

.thinking-toggle__indicator {
    width: 4px;
    height: 4px;
    border-radius: var(--radius-full);
    background: var(--accent-border);
    animation: blink 1.4s ease-in-out infinite;
}

.thinking-toggle__chevron {
    font-size: 10px;
    color: var(--text-muted);
    margin-left: auto;
    transition: transform var(--transition-normal) var(--ease-decel);
}

.thinking-toggle__chevron--open {
    transform: rotate(90deg);
}

.thinking-preview {
    margin: var(--space-1) 0 0;
    color: var(--text-muted);
    font-size: var(--text-xs);
    font-style: italic;
    line-height: var(--leading-snug);
}

.thinking-body {
    margin-top: var(--space-2);
    padding-left: var(--space-3);
    border-left: 1px solid var(--border);
    color: var(--text-secondary);
    font-size: var(--text-xs);
    line-height: var(--leading-snug);
    overflow-wrap: break-word;
}

/* Thinking expand transition */
.thinking-expand-enter-active {
    transition: opacity var(--transition-normal), max-height var(--transition-normal);
    overflow: hidden;
}

.thinking-expand-leave-active {
    transition: opacity var(--transition-fast), max-height var(--transition-fast);
    overflow: hidden;
}

.thinking-expand-enter-from,
.thinking-expand-leave-to {
    opacity: 0;
    max-height: 0;
    margin-top: 0;
}

/* ── Response Body — Typography (centered, speech-like) ── */
.response-body {
    position: relative;
    overflow-wrap: break-word;
    word-break: break-word;
    transition: opacity var(--transition-fast);
    text-align: center;
}

.response-body :deep(p) {
    font-size: var(--text-lg);
    line-height: 1.7;
    margin: 0 0 0.8em;
    color: var(--text-primary);
    font-weight: 300;
    letter-spacing: 0.01em;
}

.response-body :deep(p:last-child) {
    margin-bottom: 0;
}

/* Structured content reverts to left-aligned for readability */
.response-body :deep(pre),
.response-body :deep(table),
.response-body :deep(ul),
.response-body :deep(ol),
.response-body :deep(blockquote) {
    text-align: left;
}

.response-body :deep(h1) {
    font-size: var(--text-xl);
    font-weight: var(--weight-normal);
    letter-spacing: var(--tracking-tight);
    color: var(--text-primary);
    margin: 1.5em 0 0.6em;
    line-height: var(--leading-tight);
}

.response-body :deep(h2) {
    font-size: var(--text-lg);
    font-weight: var(--weight-normal);
    color: var(--text-primary);
    margin: 1.4em 0 0.55em;
    line-height: var(--leading-snug);
}

.response-body :deep(h3) {
    font-size: var(--text-md);
    font-weight: var(--weight-medium);
    color: var(--text-secondary);
    margin: 1.3em 0 0.5em;
    line-height: var(--leading-snug);
}

.response-body :deep(h1:first-child),
.response-body :deep(h2:first-child),
.response-body :deep(h3:first-child) {
    margin-top: 0;
}

.response-body :deep(strong) {
    font-weight: var(--weight-semibold);
    color: inherit;
}

.response-body :deep(em) {
    font-style: italic;
    color: inherit;
}

.response-body :deep(a) {
    color: var(--accent);
    text-decoration: none;
    transition: color var(--transition-fast);
}

.response-body :deep(a:hover) {
    color: var(--accent-hover);
}

.response-body :deep(blockquote) {
    margin: 1em 0 1em var(--space-4);
    padding-left: var(--space-3);
    border-left: 2px solid var(--border);
    color: var(--text-secondary);
    font-size: var(--text-sm);
}

.response-body :deep(ul),
.response-body :deep(ol) {
    margin: 0.6em 0;
    padding-left: 1.4em;
}

.response-body :deep(li) {
    margin-bottom: var(--space-1);
    line-height: var(--leading-relaxed);
}

/* ── Streaming Cursor ── */
.streaming-cursor {
    display: inline-block;
    width: 1.5px;
    height: 1em;
    margin-left: 2px;
    vertical-align: text-bottom;
    background: var(--accent);
    border-radius: 1px;
    animation: cursor-blink 0.7s steps(1) infinite;
}

/* ── Thinking Placeholder Dots ── */
.thinking-placeholder {
    display: flex;
    gap: var(--space-1-5);
    align-items: center;
    padding: var(--space-4) 0;
}

/* ── Tool Activity Section ── */
.tool-activity {
    margin-top: var(--space-3);
    padding-top: var(--space-3);
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    text-align: left;
}

.tool-activity :deep(.tool-section__args),
.tool-activity :deep(.tool-exec__result-full) {
    background: rgba(255, 255, 255, 0.03);
    border-color: var(--border);
}

/* Transition */
.tool-activity-fade-enter-active {
    transition:
        opacity 350ms var(--ease-smooth),
        transform 350ms var(--ease-out-expo);
}

.tool-activity-fade-leave-active {
    transition:
        opacity 200ms ease,
        transform 200ms ease;
}

.tool-activity-fade-enter-from {
    opacity: 0;
    transform: translateY(8px);
}

.tool-activity-fade-leave-to {
    opacity: 0;
    transform: translateY(-4px);
}

/* ── Keyframes ── */
@keyframes cursor-blink {
    0% {
        opacity: 1;
    }

    50% {
        opacity: 0;
    }
}

@keyframes blink {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.2;
    }
}

@keyframes dot-pulse {

    0%,
    100% {
        opacity: 0.6;
        transform: scale(1);
    }

    50% {
        opacity: 1;
        transform: scale(1.5);
    }
}

/* ── Reduced Motion ── */
@media (prefers-reduced-motion: reduce) {

    .streaming-cursor,
    .thinking-toggle__indicator {
        animation: none;
    }

    .streaming-cursor {
        opacity: 1;
    }

    .thinking-toggle__chevron {
        transition: none;
    }

    .thinking-expand-enter-active,
    .thinking-expand-leave-active,
    .tool-activity-fade-enter-active,
    .tool-activity-fade-leave-active {
        transition: none;
    }
}
</style>
