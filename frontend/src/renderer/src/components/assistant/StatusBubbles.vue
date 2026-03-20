<script setup lang="ts">
/**
 * StatusBubbles.vue — Top-center floating status capsules.
 * Shows state (listening/thinking/speaking) and active tool executions.
 * Compact capsules with entrance animations and state-matched colors.
 */
import { computed } from 'vue'
import { useChatStore } from '../../stores/chat'

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
                <svg v-if="state === 'listening'" class="status-capsule__icon" width="14" height="14"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 1a4 4 0 0 0-4 4v7a4 4 0 0 0 8 0V5a4 4 0 0 0-4-4z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                    <line x1="12" y1="19" x2="12" y2="23" />
                </svg>
                <svg v-else-if="state === 'thinking'" class="status-capsule__icon status-capsule__icon--spin" width="14"
                    height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10" stroke-dasharray="31.4 31.4" />
                </svg>
                <svg v-else-if="state === 'speaking'" class="status-capsule__icon" width="14" height="14"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
                    <path d="M15.5 8.5a5 5 0 0 1 0 7" />
                    <path d="M18.5 5.5a10 10 0 0 1 0 13" />
                </svg>
                <svg v-else class="status-capsule__icon status-capsule__icon--spin" width="14" height="14"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path
                        d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
                </svg>

                <span class="status-capsule__dot" />
                <span class="status-capsule__text">{{ statusText }}</span>
            </div>
        </Transition>

        <!-- Tool execution list -->
        <TransitionGroup name="tool-pop" tag="div" class="status-tools">
            <div v-for="exec in toolExecutions" :key="exec.executionId" class="tool-capsule">
                <svg class="tool-capsule__icon" width="12" height="12" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" stroke-width="2">
                    <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
                </svg>
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

/* ── Primary status capsule — glass ── */
.status-capsule {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1-5);
    padding: 6px var(--space-3) 6px var(--space-2-5);
    background: var(--glass-bg-light);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--glass-border);
    border-radius: 20px;
    font-size: var(--text-2xs);
    font-weight: var(--weight-medium);
    color: var(--text-secondary);
    pointer-events: auto;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    transition:
        border-color 250ms var(--ease-smooth),
        color 250ms var(--ease-smooth),
        box-shadow 250ms var(--ease-smooth);
}

.status-capsule--listening {
    border-color: var(--listening-border);
    color: var(--listening);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2), 0 0 12px rgba(174, 65, 65, 0.12);
}

.status-capsule--thinking {
    border-color: var(--thinking-border);
    color: var(--thinking);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2), 0 0 12px rgba(232, 220, 200, 0.08);
}

.status-capsule--speaking {
    border-color: var(--speaking-border);
    color: var(--speaking);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2), 0 0 12px rgba(55, 103, 68, 0.12);
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

/* ── Tool execution capsules — glass ── */
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
    background: var(--glass-bg-light);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--glass-border);
    border-radius: 20px;
    font-size: var(--text-2xs);
    color: var(--accent);
    pointer-events: auto;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.15);
    transition:
        border-color 200ms ease,
        box-shadow 200ms ease;
}

.tool-capsule:hover {
    border-color: var(--glass-border-hover);
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
