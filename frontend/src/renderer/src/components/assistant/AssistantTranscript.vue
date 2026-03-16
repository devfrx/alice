<script setup lang="ts">
/**
 * AssistantTranscript.vue — Premium voice transcript display card.
 *
 * Shows the user's voice input with phase-aware styling:
 * listening (live), processing (STT working), and transcript ready.
 */
import { computed } from 'vue'

const props = defineProps<{
    text: string
    isListening: boolean
    isProcessing: boolean
    audioLevel: number
}>()

/** Normalised audio bar width (0–100%). */
const audioBarWidth = computed(() => Math.min(props.audioLevel * 100, 100))
</script>

<template>
    <div class="assistant-transcript" :class="{
        'assistant-transcript--listening': isListening,
        'assistant-transcript--processing': isProcessing
    }">
        <!-- Audio level bar (only while listening) -->
        <div v-if="isListening" class="transcript-audio-bar">
            <div class="transcript-audio-bar__fill" :style="{ width: audioBarWidth + '%' }" />
        </div>

        <div class="transcript-inner">
            <!-- Mic icon -->
            <span class="transcript-icon" :class="{ 'transcript-icon--active': isListening }">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                    <line x1="12" y1="19" x2="12" y2="23" />
                    <line x1="8" y1="23" x2="16" y2="23" />
                </svg>
            </span>

            <!-- Text -->
            <span v-if="text" class="transcript-text">{{ text }}</span>
            <span v-else-if="isListening" class="transcript-placeholder">Ascolto in corso…</span>
            <span v-else-if="isProcessing" class="transcript-placeholder">Elaborazione…</span>
        </div>

        <!-- Processing shimmer overlay -->
        <div v-if="isProcessing" class="transcript-shimmer" />
    </div>
</template>

<style scoped>
/* ── Card container ── */
.assistant-transcript {
    position: relative;
    max-width: 420px;
    width: 100%;
    padding: var(--space-3) var(--space-4);
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--glass-border);
    border-radius: var(--radius-md);
    overflow: hidden;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03);
    transition:
        border-color 300ms var(--ease-smooth),
        box-shadow 300ms var(--ease-smooth);
}

/* ── Phase: Listening ── */
.assistant-transcript--listening {
    border-color: var(--listening-border);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.03),
        0 0 14px rgba(224, 96, 96, 0.06);
}

/* ── Phase: Processing ── */
.assistant-transcript--processing {
    border-color: var(--thinking-border);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.03),
        0 0 14px var(--accent-glow);
}

/* ── Audio level bar ── */
.transcript-audio-bar {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--listening-dim);
}

.transcript-audio-bar__fill {
    height: 100%;
    background: var(--listening);
    border-radius: 0 1px 1px 0;
    transition: width 0.08s linear;
}

/* ── Inner layout ── */
.transcript-inner {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    position: relative;
    z-index: 1;
}

/* ── Mic icon ── */
.transcript-icon {
    flex-shrink: 0;
    color: var(--text-secondary);
    display: flex;
    transition: color var(--transition-fast);
}

.transcript-icon--active {
    color: var(--listening);
    animation: icon-pulse 1.5s ease-in-out infinite;
}

@keyframes icon-pulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.5;
    }
}

/* ── Text ── */
.transcript-text {
    color: var(--text-primary);
    font-size: var(--text-md);
    line-height: var(--leading-normal);
}

.transcript-placeholder {
    color: var(--text-secondary);
    font-size: var(--text-sm);
    font-style: italic;
    opacity: var(--opacity-medium);
}

/* ── Processing shimmer ── */
.transcript-shimmer {
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg,
            transparent 0%,
            var(--accent-faint) 50%,
            transparent 100%);
    background-size: 200% 100%;
    animation: shimmer 1.8s ease-in-out infinite;
    pointer-events: none;
}

@keyframes shimmer {
    0% {
        background-position: 200% 0;
    }

    100% {
        background-position: -200% 0;
    }
}

@media (prefers-reduced-motion: reduce) {

    .transcript-icon--active,
    .transcript-shimmer {
        animation: none;
    }
}
</style>
