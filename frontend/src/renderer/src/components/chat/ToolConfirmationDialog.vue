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
  { value: 'session', label: 'Questa sessione', hint: 'Consenti per questa conversazione' },
  { value: 'persistent', label: 'Sempre', hint: 'Crea una regola permanente' }
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

/** Format arguments for display. */
function formatArgs(args: Record<string, unknown>): string {
  return JSON.stringify(args, null, 2)
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
        </div>

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
          <span class="confirm-card__args-label">Argomenti:</span>
          <pre class="confirm-card__args"><code>{{ formatArgs(confirmation.args) }}</code></pre>
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
  margin-bottom: var(--space-3);
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
