<script setup lang="ts">
/**
 * ToolConfirmationDialog.vue — Modal for tool approval/rejection.
 *
 * Shows a centered dialog with tool name, arguments, and approve/reject buttons.
 * Keyboard shortcuts: Escape = reject. Enter triggers the focused button natively.
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'

import type { ConfirmationRequest, RememberChoice } from '../../types/chat'
import UiButton from '../ui/UiButton.vue'
import UiBadge from '../ui/UiBadge.vue'
import type { DiffRow } from './editDiff'
import { buildConfirmationBody } from './toolConfirmationView'

const props = defineProps<{
  /** The pending confirmation request to display. */
  confirmation: ConfirmationRequest
}>()

const emit = defineEmits<{
  respond: [interactionId: string, approved: boolean, remember: RememberChoice]
}>()

/* ── Remember choice ──
 * Only offered when the server advertised `allowRemember`. The selection is
 * applied solely on approval; a rejection always sends `none` so a declined
 * tool is never silently remembered. */
const rememberChoice = ref<RememberChoice>('none')

const REMEMBER_OPTIONS: { value: RememberChoice; label: string; hint: string }[] = [
  { value: 'none', label: 'Solo ora', hint: 'Chiedi di nuovo la prossima volta' },
  {
    value: 'conversation',
    label: 'Questa conversazione',
    hint: 'Crea una regola per questa conversazione'
  },
  { value: 'persistent', label: 'Sempre', hint: 'Crea una regola permanente globale' }
]

const dialogRoot = ref<HTMLElement | null>(null)

/* ── Countdown timer ── */
const TIMEOUT_S = 60
const remainingSeconds = ref(TIMEOUT_S)
let timerInterval: ReturnType<typeof setInterval> | null = null

const timerColor = computed(() => {
  if (remainingSeconds.value <= 10) return 'var(--danger)'
  if (remainingSeconds.value <= 20) return 'var(--warning)'
  return 'var(--text-secondary)'
})

/** Risk badge variant — medium maps to warning, dangerous/forbidden to danger. */
const riskBadgeVariant = computed<'warning' | 'danger'>(() =>
  props.confirmation.riskLevel === 'medium' ? 'warning' : 'danger'
)

/* ── Tool provenance (tool_meta) ──
 * Informative only: the operational authority stays with `riskLevel` —
 * these flags never drive approve/reject behavior, only transparency. */

/** Origin badge label — `MCP · <server>` for MCP tools, null for native. */
const mcpBadgeLabel = computed<string | null>(() => {
  const meta = props.confirmation.toolMeta
  if (meta?.origin !== 'mcp') return null
  return meta.server ? `MCP · ${meta.server}` : 'MCP'
})

/**
 * Transparency warning (spec §6.1) — null when not needed. Differentiated:
 * a tool without annotations vs a server whose annotations are present but
 * not trusted (`trust_annotations: false`) get a truthful, distinct message.
 */
const fallbackWarning = computed<string | null>(() => {
  const meta = props.confirmation.toolMeta
  if (meta?.annotated === false) return 'Tool non annotato: trattato come distruttivo'
  if (meta?.trusted === false) return 'Annotazioni non attendibili: trattato come distruttivo'
  return null
})

const formattedTime = computed(() => {
  const s = remainingSeconds.value
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
})

/* ── Reasoning toggle ── */
const showReasoning = ref(false)

function approve(): void {
  emit('respond', props.confirmation.interactionId, true, rememberChoice.value)
}

function reject(): void {
  emit('respond', props.confirmation.interactionId, false, 'none')
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    e.preventDefault()
    // The dialog owns this Esc — global interrupt chains must not also run.
    e.stopPropagation()
    reject()
  }
}

/**
 * Body view-model (spec §6.2): line diff for exact-string edits, truncated
 * preview for writes, raw JSON for everything else. Pure logic lives in
 * `toolConfirmationView.ts` (tested there — this component is not mounted
 * in tests).
 */
const body = computed(() =>
  buildConfirmationBody(props.confirmation.toolName, props.confirmation.args)
)

/** Visual gutter prefix for a diff row kind. */
const DIFF_PREFIX: Record<DiffRow['kind'], string> = {
  context: ' ',
  removed: '-',
  added: '+'
}

onMounted(() => {
  nextTick(() => {
    const approveBtn = dialogRoot.value?.querySelector(
      '.confirm-card__btn--approve'
    ) as HTMLElement | null
    approveBtn?.focus()
  })
  timerInterval = setInterval(() => {
    if (remainingSeconds.value > 0) {
      remainingSeconds.value--
    } else {
      if (timerInterval) {
        clearInterval(timerInterval)
        timerInterval = null
      }
      emit('respond', props.confirmation.interactionId, false, 'none')
    }
  }, 1000)
})

onUnmounted(() => {
  if (timerInterval) {
    clearInterval(timerInterval)
    timerInterval = null
  }
})
</script>

<template>
  <Teleport to="body">
    <div
      ref="dialogRoot"
      class="confirm-overlay"
      tabindex="-1"
      @click.self="reject"
      @keydown="handleKeydown"
    >
      <div class="confirm-card" role="dialog" aria-modal="true" aria-label="Conferma strumento">
        <div class="confirm-card__header">
          <h3 class="confirm-card__title">Conferma esecuzione</h3>
          <div class="confirm-card__timer" :style="{ color: timerColor }">
            <span class="timer-icon">⏱</span>
            <span class="timer-value">{{ formattedTime }}</span>
          </div>
        </div>

        <div class="confirm-card__tool">
          <span class="confirm-card__badge">{{ confirmation.toolName }}</span>
          <UiBadge v-if="mcpBadgeLabel" class="confirm-card__origin-badge" variant="info">
            {{ mcpBadgeLabel }}
          </UiBadge>
        </div>

        <p v-if="fallbackWarning" role="note" class="confirm-card__meta-warning">
          {{ fallbackWarning }}
        </p>

        <div class="confirm-card__risk">
          <UiBadge class="confirm-card__risk-badge" :variant="riskBadgeVariant">
            {{ confirmation.riskLevel }}
          </UiBadge>
        </div>

        <p v-if="confirmation.description" class="confirm-card__desc">
          {{ confirmation.description }}
        </p>

        <!-- LLM Reasoning (collapsible) -->
        <div v-if="confirmation.reasoning" class="confirm-card__reasoning">
          <button class="reasoning-toggle" type="button" @click="showReasoning = !showReasoning">
            <span class="toggle-icon">{{ showReasoning ? '▼' : '▶' }}</span>
            Ragionamento AI
          </button>
          <div v-show="showReasoning" class="reasoning-content">
            <p>{{ confirmation.reasoning }}</p>
          </div>
        </div>

        <div class="confirm-card__args-wrap">
          <!-- Exact-string edit: red/green line diff (spec §6.2) -->
          <template v-if="body.mode === 'diff'">
            <div v-if="body.path || body.replaceAll" class="confirm-card__file-header">
              <span v-if="body.path" class="confirm-card__file-path" :title="body.path">
                {{ body.path }}
              </span>
              <span v-if="body.replaceAll" class="confirm-card__diff-tag">replace_all</span>
            </div>
            <div
              class="confirm-card__diff"
              role="figure"
              aria-label="Anteprima modifica"
              tabindex="0"
            >
              <div
                v-for="(row, idx) in body.rows"
                :key="idx"
                class="diff-row"
                :class="`diff-row--${row.kind}`"
              >
                <span class="diff-row__prefix">{{ DIFF_PREFIX[row.kind] }}</span
                >{{ row.text }}
              </div>
            </div>
          </template>

          <!-- File write: truncated content preview -->
          <template v-else-if="body.mode === 'write-preview'">
            <div v-if="body.path" class="confirm-card__file-header">
              <span class="confirm-card__file-path" :title="body.path">{{ body.path }}</span>
            </div>
            <pre class="confirm-card__args" tabindex="0"><code>{{ body.preview }}</code></pre>
            <p v-if="body.truncated" class="confirm-card__truncated-note">(troncato)</p>
          </template>

          <!-- Everything else: raw JSON args (historical rendering) -->
          <template v-else>
            <span class="confirm-card__args-label">Argomenti:</span>
            <pre class="confirm-card__args"><code>{{ body.json }}</code></pre>
          </template>
        </div>

        <!-- Remember decision (only when the server allows it) -->
        <div v-if="confirmation.allowRemember" class="confirm-card__remember">
          <span class="confirm-card__remember-label">Ricorda la decisione</span>
          <div
            class="confirm-card__remember-options"
            role="radiogroup"
            aria-label="Ricorda la decisione"
          >
            <button
              v-for="opt in REMEMBER_OPTIONS"
              :key="opt.value"
              type="button"
              role="radio"
              :aria-checked="rememberChoice === opt.value"
              class="confirm-card__remember-btn"
              :class="{ 'confirm-card__remember-btn--active': rememberChoice === opt.value }"
              :title="opt.hint"
              @click="rememberChoice = opt.value"
            >
              {{ opt.label }}
            </button>
          </div>
        </div>

        <div class="confirm-card__actions">
          <UiButton variant="secondary" @click="reject">Rifiuta</UiButton>
          <UiButton class="confirm-card__btn--approve" variant="primary" @click="approve">
            Approva
          </UiButton>
        </div>

        <p class="confirm-card__hint">Esc = Rifiuta</p>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* ToolConfirmationDialog — Supabase dialog */

.confirm-overlay {
  position: fixed;
  inset: 0;
  z-index: var(--z-modal);
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--black-heavy);
  backdrop-filter: blur(var(--blur-sm));
  -webkit-backdrop-filter: blur(var(--blur-sm));
  animation: modalOverlayIn var(--duration-normal) ease;
}

.confirm-card {
  width: 420px;
  max-width: 90vw;
  max-height: 80vh;
  overflow-y: auto;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  box-shadow: var(--shadow-floating);
  animation: modalCardIn var(--duration-normal) var(--ease-smooth);
}

.confirm-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.confirm-card__title {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
}

.confirm-card__timer {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.timer-icon {
  font-size: var(--text-base);
}

.timer-value {
  min-width: 2.5ch;
}

.confirm-card__tool {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.confirm-card__origin-badge {
  font-family: var(--font-mono);
  letter-spacing: 0.02em;
}

.confirm-card__meta-warning {
  margin: 0 0 var(--space-3);
  padding: var(--space-1-5) var(--space-2-5);
  font-size: var(--text-xs);
  color: var(--warning);
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  border-radius: var(--radius-sm);
  line-height: var(--leading-snug);
}

.confirm-card__badge {
  display: inline-block;
  font-family: var(--font-mono);
  font-size: var(--text-base);
  color: var(--accent);
  background: var(--surface-3);
  padding: var(--space-0-5) var(--space-2-5);
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
}

.confirm-card__risk {
  margin-bottom: var(--space-3);
}

.confirm-card__risk-badge {
  font-family: var(--font-mono);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.confirm-card__desc {
  margin: 0 0 var(--space-3);
  font-size: var(--text-base);
  color: var(--text-secondary);
  line-height: var(--leading-snug);
}

.confirm-card__reasoning {
  margin-bottom: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}

.reasoning-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: var(--text-xs);
  text-align: left;
  transition: background var(--transition-fast);
}

.reasoning-toggle:hover {
  background: var(--surface-3);
}

.toggle-icon {
  font-size: var(--text-2xs);
}

.reasoning-content {
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  max-height: 150px;
  overflow-y: auto;
  white-space: pre-wrap;
  line-height: var(--leading-normal);
}

.reasoning-content p {
  margin: 0;
}

.confirm-card__args-wrap {
  margin-bottom: var(--space-4);
}

.confirm-card__args-label {
  display: block;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-bottom: var(--space-1);
}

.confirm-card__args {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  color: var(--text-secondary);
  background: var(--surface-1);
  border-radius: var(--radius-sm);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
}

.confirm-card__file-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-1);
  min-width: 0;
}

.confirm-card__file-path {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  direction: rtl; /* Ellipsize the head, keep the filename tail visible */
  text-align: left;
}

.confirm-card__diff-tag {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  color: var(--warning);
  background: var(--warning-bg);
  border: 1px solid var(--warning-border);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-1-5);
}

.confirm-card__diff {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  background: var(--surface-1);
  border-radius: var(--radius-sm);
  overflow-x: auto;
  overflow-y: auto;
  max-height: 200px;
  padding: var(--space-1) 0;
}

.diff-row {
  white-space: pre;
  padding: 0 var(--space-3) 0 var(--space-2);
  color: var(--text-secondary);
  /* Rows must span the full scrollable width, or the red/green background
     is cut off when scrolling horizontally past the container width. */
  width: max-content;
  min-width: 100%;
}

.diff-row__prefix {
  display: inline-block;
  width: 1.5ch;
  user-select: none;
}

.diff-row--removed {
  color: var(--danger);
  background: var(--danger-light);
}

.diff-row--added {
  color: var(--success);
  background: var(--success-light);
}

.confirm-card__truncated-note {
  margin: var(--space-1) 0 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-style: italic;
}

.confirm-card__remember {
  margin-bottom: var(--space-4);
}

.confirm-card__remember-label {
  display: block;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  margin-bottom: var(--space-1-5);
}

.confirm-card__remember-options {
  display: flex;
  gap: var(--space-1);
  padding: var(--space-0-5);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.confirm-card__remember-btn {
  flex: 1;
  padding: var(--space-1-5) var(--space-2);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    border-color var(--transition-fast);
}

.confirm-card__remember-btn:hover {
  color: var(--text-primary);
  background: var(--surface-3);
}

.confirm-card__remember-btn--active {
  color: var(--surface-0);
  background: var(--accent);
  border-color: var(--accent);
}

.confirm-card__remember-btn--active:hover {
  color: var(--surface-0);
  background: var(--accent-hover);
}

.confirm-card__actions {
  display: flex;
  gap: var(--space-2-5);
  justify-content: flex-end;
}

.confirm-card__hint {
  margin: var(--space-3) 0 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-align: center;
}

@keyframes modalOverlayIn {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

@keyframes modalCardIn {
  from {
    opacity: 0;
    transform: scale(0.97) translateY(-6px);
  }

  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}
</style>
