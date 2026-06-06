<script setup lang="ts">
/**
 * StatusBubbles.vue — Top-center floating status capsules.
 * Shows state (listening/thinking/speaking) and active tool executions.
 * Compact capsules with entrance animations and state-matched colors.
 */
import { computed } from 'vue'
import { useChatStore } from '../../stores/chat'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{
    state: 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'
}>()

const chatStore = useChatStore()

const statusText = computed(() => {
    switch (props.state) {
        case 'listening': return 'In ascolto'
        case 'thinking': return 'Penso...'
        case 'speaking': return 'Parlo...'
        case 'processing': return 'Elaboro...'
        default: return ''
    }
})

const toolExecutions = computed(() => chatStore.activeToolExecutions)

/** Whether any non-idle status should be shown. */
const showStatus = computed(() => props.state !== 'idle')
</script>

<template>
    <div class="status-area">
        <!-- Primary status capsule -->
        <Transition name="capsule-pop">
            <div v-if="showStatus && statusText" class="status-capsule" :class="`status-capsule--${state}`">
                <!-- State icon -->
                <AppIcon v-if="state === 'listening'" name="mic-alt" :size="16" class="status-capsule__icon" />
                <AppIcon v-else-if="state === 'thinking'" name="spinner-arc" :size="16"
                    class="status-capsule__icon status-capsule__icon--spin" />
                <AppIcon v-else-if="state === 'speaking'" name="volume-two" :size="16" class="status-capsule__icon" />
                <AppIcon v-else name="spinner-rays" :size="16"
                    class="status-capsule__icon status-capsule__icon--spin" />

                <span class="status-capsule__dot" />
                <span class="status-capsule__text">{{ statusText }}</span>
            </div>
        </Transition>

        <!-- Tool execution list -->
        <TransitionGroup name="tool-pop" tag="div" class="status-tools">
            <div v-for="exec in toolExecutions" :key="exec.executionId" class="tool-capsule">
                <AppIcon name="lightning" :size="16" class="tool-capsule__icon" />
                <span class="tool-capsule__text">{{ exec.toolName }}</span>
            </div>
        </TransitionGroup>
    </div>
</template>

<style scoped>
.status-area {
    position: absolute;
    top: var(--space-6);
    left: 50%;
    transform: translateX(-50%);
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-2);
    z-index: var(--z-raised);
    pointer-events: none;
}

/* ── Primary status capsule ── */
.status-capsule {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    padding: 6px var(--space-3) 6px var(--space-2-5);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    font-size: var(--text-2xs);
    font-weight: var(--weight-medium);
    color: var(--text-secondary);
    pointer-events: auto;
    box-shadow: var(--shadow-md);
    transition:
        border-color 250ms var(--ease-smooth),
        color 250ms var(--ease-smooth),
        box-shadow 250ms var(--ease-smooth);
}

.status-capsule--listening {
    border-color: var(--listening-border);
    color: var(--listening);
    box-shadow: var(--shadow-md), 0 0 12px var(--listening-dim);
}

.status-capsule--thinking {
    border-color: var(--thinking-border);
    color: var(--thinking);
    box-shadow: var(--shadow-md), 0 0 12px var(--accent-glow);
}

.status-capsule--speaking {
    border-color: var(--speaking-border);
    color: var(--speaking);
    box-shadow: var(--shadow-md), 0 0 12px var(--speaking-dim);
}

.status-capsule--processing {
    border-color: var(--thinking-border);
    color: var(--thinking);
}

.status-capsule__icon {
    flex-shrink: 0;
    opacity: 0.85;
}

.status-capsule__icon--spin {
    animation: spinIcon 1.2s linear infinite;
}

.status-capsule__dot {
    width: 5px;
    height: 5px;
    border-radius: var(--radius-full);
    background: currentColor;
    animation: statusPulse 1.5s ease-in-out infinite;
}

.status-capsule__text {
    letter-spacing: 0.03em;
}

/* ── Tool execution capsules ── */
.status-tools {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--space-1);
}

.tool-capsule {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    padding: 4px var(--space-2-5) 4px var(--space-2);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-pill);
    font-size: var(--text-2xs);
    color: var(--accent);
    pointer-events: auto;
    box-shadow: var(--shadow-sm);
    transition:
        border-color 200ms ease,
        box-shadow 200ms ease;
}

.tool-capsule:hover {
    border-color: var(--border-hover);
}

.tool-capsule__icon {
    flex-shrink: 0;
    opacity: 0.8;
}

.tool-capsule__text {
    max-width: 180px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    letter-spacing: 0.02em;
}

/* ── Capsule pop-in transition ── */
.capsule-pop-enter-active {
    transition:
        opacity 250ms var(--ease-smooth),
        transform 300ms var(--ease-out-expo);
}

.capsule-pop-leave-active {
    transition:
        opacity 150ms ease,
        transform 150ms ease;
}

.capsule-pop-enter-from {
    opacity: 0;
    transform: scale(0.85) translateY(-6px);
}

.capsule-pop-leave-to {
    opacity: 0;
    transform: scale(0.9) translateY(-4px);
}

/* ── Tool pop-in transition ── */
.tool-pop-enter-active {
    transition:
        opacity 250ms var(--ease-smooth),
        transform 300ms var(--ease-out-expo);
}

.tool-pop-leave-active {
    transition:
        opacity 150ms ease,
        transform 150ms ease;
}

.tool-pop-enter-from {
    opacity: 0;
    transform: scale(0.85) translateY(4px);
}

.tool-pop-leave-to {
    opacity: 0;
    transform: scale(0.9);
}

/* ── Keyframes ── */
@keyframes statusPulse {

    0%,
    100% {
        opacity: 1;
    }

    50% {
        opacity: 0.3;
    }
}

@keyframes spinIcon {
    from {
        transform: rotate(0deg);
    }

    to {
        transform: rotate(360deg);
    }
}

@media (prefers-reduced-motion: reduce) {

    .status-capsule__dot,
    .status-capsule__icon--spin {
        animation: none;
    }
}
</style>
