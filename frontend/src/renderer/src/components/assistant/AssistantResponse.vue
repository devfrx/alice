<script setup lang="ts">
/**
 * AssistantResponse.vue — AL\CE voice output.
 *
 * Renders AL\CE's response as if it's speaking directly — no chat card,
 * centered flowing text that emanates from the orb. Supports markdown,
 * thinking/reasoning section, tool call/execution timeline, and streaming.
 */
import { computed, ref, watch, nextTick, onMounted } from 'vue'
import { renderMarkdown } from '../../composables/useMarkdown'
import { useCodeBlocks } from '../../composables/useCodeBlocks'
import AliceSpinner from '../../components/ui/AliceSpinner.vue'
import AppIcon from '../ui/AppIcon.vue'
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
        /** Current orb state for reactive visual effects. */
        orbState?: 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'
    }>(),
    {
        toolExecutions: () => [],
        toolCalls: () => [],
        userQuery: '',
        orbState: 'idle',
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

const { handleCodeBlockClick } = useCodeBlocks()

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
    <div ref="scrollContainer" class="alice-voice" :class="[
        {
            'alice-voice--thinking': isThinkingPhase,
            'alice-voice--generating': isGenerating,
            'alice-voice--complete': !isStreaming && !!content
        },
        `alice-voice--${orbState}`
    ]">
        <!-- Dynamic emanation line from orb -->
        <div class="alice-voice__emanation">
            <div class="alice-voice__emanation-line" />
            <span class="alice-voice__dot" />
        </div>

        <!-- User query echo -->
        <p v-if="userQuery" class="alice-voice__query">
            <AppIcon name="user" :size="14" />
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
                <!-- eslint-disable-next-line vue/no-v-html — content is sanitised by markdown-it -->
                <div v-if="thinkingExpanded" class="thinking-body" v-html="renderedThinking" @click="handleCodeBlockClick" />
            </Transition>
        </div>

        <!-- Main response content -->
        <!-- eslint-disable-next-line vue/no-v-html — content is sanitised by markdown-it -->
        <div v-if="content" class="response-body" v-html="renderedContent" @click="handleCodeBlockClick" />

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
            <AliceSpinner size="sm" variant="dots" />
        </div>
    </div>
</template>

<style scoped>
/* ── Container: borderless, open, emanates from orb ── */
.alice-voice {
    position: relative;
    max-width: 860px;
    width: 100%;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 0 var(--space-6) var(--space-6);
    color: var(--text-primary);
    font-size: var(--text-md);
    line-height: var(--leading-relaxed);
    font-family: var(--font-sans);
    text-align: center;
    transition: opacity 400ms var(--ease-smooth);
}

/* Scrollbar */
.alice-voice::-webkit-scrollbar {
    width: 3px;
}

.alice-voice::-webkit-scrollbar-track {
    background: transparent;
}

.alice-voice::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: var(--radius-pill);
}

.alice-voice:hover::-webkit-scrollbar-thumb {
    background: var(--border-hover);
}

/* ── Dynamic emanation from orb ── */
.alice-voice__emanation {
    display: flex;
    flex-direction: column;
    align-items: center;
    margin-bottom: var(--space-3);
}

.alice-voice__emanation-line {
    width: 1px;
    height: 28px;
    background: linear-gradient(to bottom,
            transparent,
            var(--accent-glow, var(--accent)));
    opacity: 0.25;
    transition:
        height 500ms var(--ease-smooth),
        opacity 500ms var(--ease-smooth),
        background 500ms var(--ease-smooth);
}

.alice-voice--generating .alice-voice__emanation-line {
    height: 36px;
    opacity: 0.5;
    animation: emanation-pulse 2.5s ease-in-out infinite;
}

.alice-voice--thinking .alice-voice__emanation-line {
    height: 32px;
    opacity: 0.4;
    background: linear-gradient(to bottom,
            transparent,
            var(--thinking));
    animation: emanation-pulse 1.8s ease-in-out infinite;
}

.alice-voice--speaking .alice-voice__emanation-line {
    height: 36px;
    opacity: 0.5;
}

.alice-voice--complete .alice-voice__emanation-line {
    height: 20px;
    opacity: 0.12;
}

.alice-voice__dot {
    width: 6px;
    height: 6px;
    border-radius: var(--radius-full);
    background: var(--accent);
    opacity: 0.6;
    box-shadow: 0 0 10px var(--accent-glow, var(--accent));
    transition:
        opacity 300ms var(--ease-smooth),
        box-shadow 300ms var(--ease-smooth),
        transform 300ms var(--ease-smooth),
        width 300ms var(--ease-smooth),
        height 300ms var(--ease-smooth);
}

.alice-voice--generating .alice-voice__dot {
    width: 8px;
    height: 8px;
    opacity: 1;
    box-shadow: 0 0 20px var(--accent-glow, var(--accent)),
        0 0 40px rgba(140, 180, 160, 0.15);
    animation: dot-pulse 2s ease-in-out infinite;
}

.alice-voice--thinking .alice-voice__dot {
    width: 8px;
    height: 8px;
    opacity: 0.9;
    background: var(--thinking);
    box-shadow: 0 0 16px var(--thinking),
        0 0 32px rgba(155, 140, 210, 0.15);
    animation: dot-pulse 1.5s ease-in-out infinite;
}

.alice-voice--speaking .alice-voice__dot {
    width: 7px;
    height: 7px;
    opacity: 0.9;
    box-shadow: 0 0 18px var(--accent-glow, var(--accent));
    animation: dot-pulse 2.2s ease-in-out infinite;
}

.alice-voice--complete .alice-voice__dot {
    opacity: 0.2;
    box-shadow: none;
}

/* ── User query echo ── */
.alice-voice__query {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    margin: 0 auto var(--space-4);
    padding: var(--space-1) var(--space-3);
    font-size: var(--text-xs);
    color: var(--text-muted);
    background: var(--white-faint);
    border-radius: var(--radius-md);
    max-width: 80%;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.alice-voice__query svg {
    flex-shrink: 0;
    opacity: 0.5;
}

/* ── Phase states ── */
.alice-voice--thinking {
    opacity: var(--opacity-visible);
}

.alice-voice--generating .response-body {
    opacity: 0.92;
}

.alice-voice--complete .response-body {
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
    padding: var(--space-3) var(--space-2);
    border-radius: var(--radius-lg);
}

/* Ambient glow behind response during active states */
.alice-voice--generating .response-body {
    opacity: 0.92;
    background: radial-gradient(ellipse at center top,
            rgba(140, 180, 160, 0.04) 0%,
            transparent 70%);
}

.alice-voice--thinking .response-body {
    background: radial-gradient(ellipse at center top,
            rgba(155, 140, 210, 0.04) 0%,
            transparent 70%);
}

.alice-voice--speaking .response-body {
    opacity: 1;
    background: radial-gradient(ellipse at center top,
            rgba(92, 170, 120, 0.03) 0%,
            transparent 70%);
}

.alice-voice--complete .response-body {
    opacity: 1;
    transition: opacity var(--transition-fast);
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
    background: var(--white-faint);
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

@keyframes emanation-pulse {

    0%,
    100% {
        opacity: 0.3;
    }

    50% {
        opacity: 0.65;
    }
}

/* ── Reduced Motion ── */
@media (prefers-reduced-motion: reduce) {

    .streaming-cursor,
    .thinking-toggle__indicator,
    .alice-voice__emanation-line {
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
