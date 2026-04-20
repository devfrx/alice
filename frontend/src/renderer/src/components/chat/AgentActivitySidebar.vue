<script setup lang="ts">
/**
 * AgentActivitySidebar.vue — Floating "Cosa sto facendo" panel.
 *
 * Slide-in inset panel that surfaces what the agent is *really* doing
 * by interleaving the high-level plan steps with the actual tool
 * calls executed by the LLM.  Unlike the inline `AgentPlanCard`, the
 * sidebar always shows the result preview line and reserves enough
 * vertical space for long timelines.
 *
 * Layout: floats inside its `position: relative` parent with margin
 * around all four sides, leaving the rest of the workspace fully
 * visible.  Closing is per-run (dismissed runs don't auto-reopen).
 */

import { computed, ref, watch } from 'vue'

import AppIcon from '../ui/AppIcon.vue'
import { useUIStore } from '../../stores/ui'
import { useChatStore } from '../../stores/chat'
import { useAgentActivity } from '../../composables/useAgentActivity'
import { humanizeRunSubtitle } from '../../utils/agentLabels'
import type { AgentRun, Verdict } from '../../types/agent'

const uiStore = useUIStore()
const chatStore = useChatStore()

// ---------------------------------------------------------------------------
// Run selection
// ---------------------------------------------------------------------------

const focusedRun = computed<AgentRun | null>(() => {
    const focusId = uiStore.agentSidebarFocusedRunId
    if (focusId) {
        const run = chatStore.agentRuns.get(focusId)
        if (run) return run
    }
    let latest: AgentRun | null = null
    for (const r of chatStore.agentRuns.values()) {
        if (!latest || r.started_at > latest.started_at) latest = r
    }
    return latest
})

const visible = computed<boolean>(
    () => uiStore.agentSidebarOpen && focusedRun.value !== null,
)

const isBypass = computed<boolean>(() => focusedRun.value?.mode === 'bypass')

// ---------------------------------------------------------------------------
// Activity feed (real tool calls + plan steps)
// ---------------------------------------------------------------------------

const feed = useAgentActivity(focusedRun)
const toolActivity = computed(() => feed.value?.toolActivity ?? [])
const planSteps = computed(() => feed.value?.planSteps ?? [])
const showPlanSection = computed(() => planSteps.value.length > 1)

const planSectionOpen = ref(false)
function togglePlanSection(): void {
    planSectionOpen.value = !planSectionOpen.value
}

watch(() => focusedRun.value?.id, () => {
    planSectionOpen.value = false
})

// ---------------------------------------------------------------------------
// Subtitle / latest verdict (bypass mode)
// ---------------------------------------------------------------------------

const subtitle = computed<string>(() => {
    const run = focusedRun.value
    if (!run) return ''
    return humanizeRunSubtitle(run.state, run.current_step, run.total_steps)
})

const latestVerdict = computed<Verdict | null>(() => {
    const run = focusedRun.value
    if (!run) return null
    const indices = Object.keys(run.verdicts).map((k) => Number(k))
    if (!indices.length) return null
    const last = Math.max(...indices)
    return run.verdicts[last] ?? null
})

// ---------------------------------------------------------------------------
// Ask-user reply box
// ---------------------------------------------------------------------------

const replyText = ref<string>('')

const emit = defineEmits<{
    (e: 'reply', payload: { text: string; runId: string }): void
}>()

function submitReply(): void {
    const run = focusedRun.value
    const text = replyText.value.trim()
    if (!run || !text) return
    emit('reply', { text, runId: run.id })
    replyText.value = ''
}

// ---------------------------------------------------------------------------
// Close
// ---------------------------------------------------------------------------

function close(): void {
    uiStore.closeAgentSidebar(focusedRun.value?.id ?? null)
}
</script>

<template>
    <Transition name="agent-sidebar">
        <aside v-if="visible && focusedRun" class="agent-sidebar" role="complementary" aria-label="Cosa sto facendo">
            <header class="agent-sidebar__head">
                <div class="agent-sidebar__head-text">
                    <span class="agent-sidebar__title">Cosa sto facendo</span>
                    <span class="agent-sidebar__subtitle">{{ subtitle }}</span>
                </div>
                <button type="button" class="agent-sidebar__close" aria-label="Chiudi" @click="close">
                    <AppIcon name="x" :size="14" :stroke-width="2" />
                </button>
            </header>

            <div class="agent-sidebar__scroll">
                <p v-if="focusedRun.plan?.goal" class="agent-sidebar__goal">{{ focusedRun.plan.goal }}</p>

                <!-- Bypass: no plan, single verdict summary -->
                <div v-if="isBypass" class="agent-sidebar__bypass">
                    <p class="agent-sidebar__bypass-text">
                        Risposta diretta — nessun piano necessario.
                    </p>
                    <div v-if="latestVerdict" class="agent-sidebar__bypass-verdict"
                        :class="`agent-sidebar__bypass-verdict--${latestVerdict.action}`">
                        <span class="agent-sidebar__bypass-icon">
                            <AppIcon v-if="latestVerdict.action === 'ok'" name="check" :size="11" :stroke-width="2.5" />
                            <AppIcon v-else-if="latestVerdict.action === 'abort'" name="x" :size="11"
                                :stroke-width="2.5" />
                            <AppIcon v-else name="refresh-cw" :size="11" :stroke-width="2" />
                        </span>
                        <span class="agent-sidebar__bypass-reason">
                            {{ latestVerdict.reason }}
                        </span>
                    </div>
                    <p v-for="(w, i) in focusedRun.warnings" :key="i" class="agent-sidebar__warning">{{ w.message }}</p>
                </div>

                <!-- Agent: real tool-call timeline -->
                <ul v-else-if="toolActivity.length" class="activity-list">
                    <li v-for="item in toolActivity" :key="item.callId" class="activity-item"
                        :class="`activity-item--${item.status}`">
                        <span class="activity-item__dot" aria-hidden="true">
                            <AppIcon v-if="item.status === 'done'" name="check" :size="10" :stroke-width="2.5" />
                            <AppIcon v-else-if="item.status === 'failed'" name="x" :size="10" :stroke-width="2.5" />
                            <span v-else class="activity-item__pulse" />
                        </span>
                        <div class="activity-item__main">
                            <div class="activity-item__row">
                                <span class="activity-item__label">{{ item.toolLabel }}</span>
                                <span class="activity-item__name">{{ item.toolName }}</span>
                            </div>
                            <p v-if="item.argsSummary" class="activity-item__args">{{ item.argsSummary }}</p>
                            <p v-if="item.resultPreview" class="activity-item__preview"
                                :class="{ 'activity-item__preview--error': item.resultIsError }">{{ item.resultPreview
                                }}</p>
                        </div>
                    </li>
                </ul>
                <p v-else class="agent-sidebar__empty">In attesa del piano…</p>

                <!-- Plan checklist (collapsible, hidden for 1-step plans) -->
                <div v-if="!isBypass && showPlanSection" class="agent-sidebar__plan">
                    <button type="button" class="agent-sidebar__plan-head" :aria-expanded="planSectionOpen"
                        @click="togglePlanSection">
                        <AppIcon name="chevron-down" :size="11" :stroke-width="1.5" class="agent-sidebar__plan-chevron"
                            :class="{ 'agent-sidebar__plan-chevron--open': planSectionOpen }" />
                        Piano ({{ planSteps.length }} passi)
                    </button>
                    <ol v-if="planSectionOpen" class="agent-sidebar__plan-list">
                        <li v-for="step in planSteps" :key="step.index" class="plan-row"
                            :class="`plan-row--${step.status}`">
                            <span class="plan-row__num">{{ step.index + 1 }}.</span>
                            <span class="plan-row__desc">{{ step.description }}</span>
                        </li>
                    </ol>
                </div>
            </div>

            <footer class="agent-sidebar__foot">
                <div v-if="focusedRun.state === 'asked_user' && focusedRun.pending_question" class="agent-sidebar__ask">
                    <p class="agent-sidebar__ask-question">{{ focusedRun.pending_question }}</p>
                    <div class="agent-sidebar__ask-row">
                        <input v-model="replyText" type="text" class="agent-sidebar__ask-input"
                            placeholder="Scrivi la tua risposta…" @keydown.enter.prevent="submitReply" />
                        <button type="button" class="agent-sidebar__ask-send" :disabled="!replyText.trim()"
                            @click="submitReply">
                            Invia
                        </button>
                    </div>
                </div>

                <div v-if="!isBypass && focusedRun.replans > 0" class="agent-sidebar__foot-meta">
                    <AppIcon name="refresh-cw" :size="10" :stroke-width="2" />
                    Piano rivisto {{ focusedRun.replans }}
                    {{ focusedRun.replans === 1 ? 'volta' : 'volte' }}
                </div>
            </footer>
        </aside>
    </Transition>
</template>

<style scoped>
/* ── Layout ─────────────────────────────────────────────── */
.agent-sidebar {
    position: absolute;
    top: var(--space-3);
    right: var(--space-3);
    bottom: var(--space-3);
    z-index: var(--z-sticky);
    width: 380px;
    display: flex;
    flex-direction: column;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-sidebar), var(--shadow-lg);
    color: var(--text-primary);
    font-size: var(--text-base);
    overflow: hidden;
}

/* ── Slide-in transition ─────────────────────────────────── */
.agent-sidebar-enter-active,
.agent-sidebar-leave-active {
    transition: transform var(--transition-normal) var(--ease-decel),
        opacity var(--transition-normal) var(--ease-decel);
}

.agent-sidebar-enter-from,
.agent-sidebar-leave-to {
    transform: translateX(calc(100% + var(--space-3)));
    opacity: 0;
}

/* ── Header (sticky) ────────────────────────────────────── */
.agent-sidebar__head {
    position: sticky;
    top: 0;
    z-index: 1;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: var(--space-3);
    padding: var(--space-3) var(--space-4);
    border-bottom: 1px solid var(--border);
    background: var(--surface-1);
}

.agent-sidebar__head-text {
    display: flex;
    flex-direction: column;
    gap: var(--space-0-5);
    min-width: 0;
}

.agent-sidebar__title {
    font-size: var(--text-md);
    font-weight: var(--weight-medium);
    color: var(--text-primary);
    line-height: var(--leading-tight);
}

.agent-sidebar__subtitle {
    font-size: var(--text-sm);
    color: var(--text-secondary);
    line-height: var(--leading-snug);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.agent-sidebar__close {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    border-radius: var(--radius-sm);
    background: transparent;
    border: 0;
    color: var(--text-secondary);
    cursor: pointer;
    flex-shrink: 0;
    transition: background var(--transition-fast),
        color var(--transition-fast);
}

.agent-sidebar__close:hover {
    background: var(--surface-hover);
    color: var(--text-primary);
}

/* ── Scrollable body ────────────────────────────────────── */
.agent-sidebar__scroll {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
}

/* ── Goal ──────────────────────────────────────────────── */
.agent-sidebar__goal {
    margin: 0;
    padding: var(--space-3) var(--space-4);
    font-size: var(--text-sm);
    font-style: italic;
    line-height: var(--leading-snug);
    color: var(--text-secondary);
    border-bottom: 1px solid var(--border);
}

/* ── Activity timeline ──────────────────────────────────── */
.activity-list {
    list-style: none;
    margin: 0;
    padding: var(--space-3) var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-2-5);
    min-width: 0;
}

.activity-item {
    position: relative;
    display: flex;
    gap: var(--space-2-5);
    align-items: flex-start;
    padding: var(--space-1) 0 var(--space-1) var(--space-2);
    border-left: 2px solid transparent;
    transition: border-color var(--transition-normal);
    min-width: 0;
}

.activity-item--running {
    border-left-color: var(--accent);
}

.activity-item--done {
    border-left-color: var(--success-border);
}

.activity-item--failed {
    border-left-color: var(--danger-border);
}

.activity-item__dot {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 18px;
    height: 18px;
    border-radius: var(--radius-full);
    background: var(--surface-3);
    color: var(--text-secondary);
    margin-top: 1px;
}

.activity-item--running .activity-item__dot {
    background: var(--accent-medium);
    color: var(--accent);
}

.activity-item--done .activity-item__dot {
    background: var(--success-medium);
    color: var(--success);
}

.activity-item--failed .activity-item__dot {
    background: var(--danger-medium);
    color: var(--danger);
}

.activity-item__pulse {
    width: 7px;
    height: 7px;
    border-radius: var(--radius-full);
    background: currentColor;
    animation: agent-sidebar-pulse 1500ms var(--ease-decel) infinite;
}

@keyframes agent-sidebar-pulse {

    0%,
    100% {
        opacity: 0.4;
    }

    50% {
        opacity: 1;
    }
}

.activity-item__main {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 3px;
}

.activity-item__row {
    display: flex;
    align-items: baseline;
    gap: var(--space-1-5);
    min-width: 0;
}

.activity-item__label {
    flex: 1;
    min-width: 0;
    color: var(--text-primary);
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.activity-item__name {
    font-family: ui-monospace, SFMono-Regular, monospace;
    font-size: var(--text-2xs);
    padding: 1px var(--space-1);
    border-radius: var(--radius-xs);
    background: var(--surface-3);
    color: var(--text-muted);
    white-space: nowrap;
    flex-shrink: 0;
}

.activity-item__args {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--text-secondary);
    line-height: var(--leading-snug);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.activity-item__preview {
    margin: 0;
    font-size: var(--text-2xs);
    color: var(--text-muted);
    line-height: var(--leading-snug);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.activity-item__preview--error {
    color: var(--danger);
}

.agent-sidebar__empty {
    margin: 0;
    padding: var(--space-6) var(--space-4);
    color: var(--text-muted);
    text-align: center;
    font-size: var(--text-sm);
}

/* ── Bypass debug view ──────────────────────────────────── */
.agent-sidebar__bypass {
    padding: var(--space-3) var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
}

.agent-sidebar__bypass-text {
    margin: 0;
    font-size: var(--text-sm);
    color: var(--text-secondary);
}

.agent-sidebar__bypass-verdict {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-2-5);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    border: 1px solid var(--border);
    font-size: var(--text-sm);
    line-height: var(--leading-snug);
}

.agent-sidebar__bypass-verdict--ok {
    border-color: var(--success-border);
}

.agent-sidebar__bypass-verdict--abort {
    border-color: var(--danger-border);
}

.agent-sidebar__bypass-verdict--retry,
.agent-sidebar__bypass-verdict--ask_user,
.agent-sidebar__bypass-verdict--replan {
    border-color: var(--warning-border);
}

.agent-sidebar__bypass-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 18px;
    height: 18px;
    border-radius: var(--radius-full);
    flex-shrink: 0;
    margin-top: 1px;
    background: var(--surface-3);
    color: var(--text-secondary);
}

.agent-sidebar__bypass-verdict--ok .agent-sidebar__bypass-icon {
    background: var(--success-medium);
    color: var(--success);
}

.agent-sidebar__bypass-verdict--abort .agent-sidebar__bypass-icon {
    background: var(--danger-medium);
    color: var(--danger);
}

.agent-sidebar__bypass-verdict--retry .agent-sidebar__bypass-icon,
.agent-sidebar__bypass-verdict--ask_user .agent-sidebar__bypass-icon,
.agent-sidebar__bypass-verdict--replan .agent-sidebar__bypass-icon {
    background: var(--warning-bg);
    color: var(--warning);
}

.agent-sidebar__bypass-reason {
    flex: 1;
    color: var(--text-primary);
}

.agent-sidebar__warning {
    margin: 0;
    font-size: var(--text-xs);
    color: var(--text-secondary);
    font-style: italic;
}

/* ── Plan section (collapsible) ─────────────────────────── */
.agent-sidebar__plan {
    margin: 0 var(--space-4) var(--space-3);
    padding-top: var(--space-2);
    border-top: 1px dashed var(--border);
}

.agent-sidebar__plan-head {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    background: transparent;
    border: 0;
    cursor: pointer;
    font: inherit;
    font-size: var(--text-xs);
    color: var(--text-secondary);
    padding: 0;
}

.agent-sidebar__plan-chevron {
    transition: transform var(--transition-fast);
}

.agent-sidebar__plan-chevron--open {
    transform: rotate(180deg);
}

.agent-sidebar__plan-list {
    list-style: none;
    margin: var(--space-2) 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
}

.plan-row {
    display: flex;
    align-items: baseline;
    gap: var(--space-1-5);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    line-height: var(--leading-snug);
}

.plan-row__num {
    color: var(--text-muted);
    font-variant-numeric: tabular-nums;
    flex-shrink: 0;
}

.plan-row__desc {
    flex: 1;
    min-width: 0;
    color: var(--text-primary);
}

.plan-row--failed {
    color: var(--danger);
}

.plan-row--pending {
    opacity: 0.6;
}

.plan-row--skipped {
    opacity: 0.4;
    text-decoration: line-through;
}

/* ── Footer ─────────────────────────────────────────────── */
.agent-sidebar__foot {
    border-top: 1px solid var(--border);
    padding: var(--space-2-5) var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    background: var(--surface-inset);
}

.agent-sidebar__foot:empty {
    display: none;
}

.agent-sidebar__foot-meta {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    font-size: var(--text-xs);
    color: var(--text-secondary);
}

/* ── Ask-user reply box ─────────────────────────────────── */
.agent-sidebar__ask {
    padding: var(--space-2) var(--space-2-5);
    border-radius: var(--radius-sm);
    background: var(--warning-bg);
    border: 1px solid var(--warning-border);
    display: flex;
    flex-direction: column;
    gap: var(--space-1-5);
}

.agent-sidebar__ask-question {
    margin: 0;
    font-size: var(--text-sm);
    line-height: var(--leading-snug);
    color: var(--warning);
}

.agent-sidebar__ask-row {
    display: flex;
    gap: var(--space-1-5);
}

.agent-sidebar__ask-input {
    flex: 1;
    min-width: 0;
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-xs);
    border: 1px solid var(--border);
    background: var(--bg-input);
    color: var(--text-primary);
    font: inherit;
    font-size: var(--text-sm);
}

.agent-sidebar__ask-input:focus {
    outline: none;
    border-color: var(--accent-border);
}

.agent-sidebar__ask-send {
    padding: var(--space-1) var(--space-3);
    border-radius: var(--radius-xs);
    border: 1px solid var(--accent-border);
    background: var(--accent-medium);
    color: var(--accent);
    font: inherit;
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    cursor: pointer;
    transition: background var(--transition-fast);
}

.agent-sidebar__ask-send:hover:not(:disabled) {
    background: var(--accent-strong);
}

.agent-sidebar__ask-send:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
</style>
