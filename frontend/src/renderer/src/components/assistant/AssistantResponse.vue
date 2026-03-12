<script setup lang="ts">
/**
 * AssistantResponse.vue — Rich markdown response display for OMNIA.
 *
 * Renders the assistant's streamed/final response with full markdown support,
 * thinking/reasoning collapse section, streaming cursor, and phase-aware styling.
 */
import { computed, ref, watch, nextTick, onMounted } from 'vue'
import { renderMarkdown } from '../../utils/markdownRenderer'

const props = defineProps<{
    content: string
    isStreaming: boolean
    thinkingContent: string
}>()

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
    <div ref="scrollContainer" class="assistant-response" :class="{
        'assistant-response--thinking': isThinkingPhase,
        'assistant-response--generating': isGenerating,
        'assistant-response--complete': !isStreaming && !!content
    }">
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

        <!-- Thinking phase placeholder (no content yet) -->
        <div v-if="isThinkingPhase && !content" class="thinking-placeholder">
            <span class="thinking-placeholder__dot" />
            <span class="thinking-placeholder__dot" />
            <span class="thinking-placeholder__dot" />
        </div>
    </div>
</template>

<style scoped>
/* ── Container ── */
.assistant-response {
    position: relative;
    max-width: 560px;
    width: 100%;
    max-height: 70vh;
    overflow-y: auto;
    overflow-x: hidden;
    padding: var(--space-6) var(--space-5);
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    color: var(--text-primary);
    font-size: var(--text-md);
    line-height: var(--leading-relaxed);
    font-family: var(--font-sans);
    transition: opacity var(--transition-fast);
}

/* Scrollbar */
.assistant-response::-webkit-scrollbar {
    width: 3px;
}

.assistant-response::-webkit-scrollbar-track {
    background: transparent;
}

.assistant-response::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: var(--radius-pill);
}

.assistant-response:hover::-webkit-scrollbar-thumb {
    background: var(--border-hover);
}

/* ── Phase states ── */
.assistant-response--thinking {
    opacity: var(--opacity-visible);
}

.assistant-response--generating .response-body {
    opacity: 0.9;
}

.assistant-response--complete .response-body {
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

/* ── Response Body — Typography ── */
.response-body {
    position: relative;
    overflow-wrap: break-word;
    word-break: break-word;
    transition: opacity var(--transition-fast);
}

.response-body :deep(p) {
    font-size: var(--text-md);
    line-height: var(--leading-relaxed);
    margin: 0 0 1em;
    color: var(--text-primary);
}

.response-body :deep(p:last-child) {
    margin-bottom: 0;
}

.response-body :deep(h1) {
    font-size: var(--text-xl);
    font-weight: var(--weight-semibold);
    letter-spacing: var(--tracking-tight);
    color: var(--text-primary);
    margin: 1.5em 0 0.6em;
    line-height: var(--leading-tight);
}

.response-body :deep(h2) {
    font-size: var(--text-lg);
    font-weight: var(--weight-medium);
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

.response-body :deep(.inline-code) {
    font-family: var(--font-mono);
    background: var(--surface-2);
    border-radius: var(--radius-xs);
    padding: 1px 5px;
    font-size: 0.87em;
    color: var(--text-primary);
}

.response-body :deep(.code-block) {
    position: relative;
    background: var(--surface-0);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: var(--space-4);
    margin: 1em 0;
    overflow-x: auto;
    font-family: var(--font-mono);
    font-size: 0.84em;
    line-height: var(--leading-relaxed);
    color: var(--text-primary);
}

.response-body :deep(.code-block code) {
    background: none;
    border: none;
    padding: 0;
    font-size: inherit;
    color: inherit;
}

.response-body :deep(.code-block__lang) {
    display: block;
    margin-bottom: var(--space-2);
    font-size: var(--text-2xs);
    text-transform: uppercase;
    letter-spacing: var(--tracking-wider);
    color: var(--text-muted);
    font-weight: var(--weight-normal);
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

.thinking-placeholder__dot {
    width: 4px;
    height: 4px;
    border-radius: var(--radius-full);
    background: var(--text-muted);
    animation: dot-pulse 1.4s ease-in-out infinite;
}

.thinking-placeholder__dot:nth-child(1) {
    animation-delay: 0s;
}

.thinking-placeholder__dot:nth-child(2) {
    animation-delay: 0.15s;
}

.thinking-placeholder__dot:nth-child(3) {
    animation-delay: 0.3s;
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

@keyframes dot-pulse {

    0%,
    100% {
        opacity: 0.15;
    }

    50% {
        opacity: 0.6;
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

/* ── Reduced Motion ── */
@media (prefers-reduced-motion: reduce) {

    .streaming-cursor,
    .thinking-placeholder__dot,
    .thinking-toggle__indicator {
        animation: none;
    }

    .streaming-cursor {
        opacity: 1;
    }

    .thinking-placeholder__dot {
        opacity: 0.4;
    }

    .thinking-toggle__chevron {
        transition: none;
    }

    .thinking-expand-enter-active,
    .thinking-expand-leave-active {
        transition: none;
    }
}
</style>
