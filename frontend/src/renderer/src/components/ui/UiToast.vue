<script setup lang="ts">
/**
 * AL\CE — Global toast notification renderer.
 *
 * Mount once in App.vue. Reads from the useToast() singleton and renders
 * all active toasts via a Teleport to <body>.
 *
 * Accessibility:
 *  - The container is an aria-live region so new toasts are announced.
 *    `error` toasts use `role="alert"` + `aria-live="assertive"`, all
 *    others use `role="status"` + `aria-live="polite"`.
 *  - Each toast exposes an explicit close button (kept alongside the
 *    whole-toast click dismiss for mouse convenience).
 */
import { TransitionGroup } from 'vue'
import { useToast } from '../../composables/useToast'
import type { ToastType } from '../../composables/useToast'

const { toasts, dismiss } = useToast()

const ICONS: Record<ToastType, string> = {
  info: '\u2139',    // ℹ
  success: '\u2713', // ✓
  warning: '\u26A0', // ⚠
  error: '\u2715',   // ✕
}

const isAssertive = (type: ToastType): boolean => type === 'error' || type === 'warning'
</script>

<template>
  <Teleport to="body">
    <TransitionGroup name="ui-toast" tag="div" class="ui-toast-container" aria-live="polite" aria-atomic="false">
      <div v-for="toast in toasts" :key="toast.id" class="ui-toast" :class="`ui-toast--${toast.type}`"
        :role="isAssertive(toast.type) ? 'alert' : 'status'"
        :aria-live="isAssertive(toast.type) ? 'assertive' : 'polite'" @click="dismiss(toast.id)">
        <span class="ui-toast__icon" aria-hidden="true">{{ ICONS[toast.type] }}</span>
        <span class="ui-toast__text">{{ toast.message }}</span>
        <button type="button" class="ui-toast__close" aria-label="Dismiss notification" @click.stop="dismiss(toast.id)">
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
            <path d="M2 2 L8 8 M8 2 L2 8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
          </svg>
        </button>
      </div>
    </TransitionGroup>
  </Teleport>
</template>

<style scoped>
.ui-toast-container {
  position: fixed;
  bottom: var(--space-6);
  right: var(--space-6);
  z-index: var(--z-modal);
  display: flex;
  flex-direction: column-reverse;
  gap: var(--space-2);
  pointer-events: none;
}

.ui-toast {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2-5) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  color: var(--text-primary);
  background: var(--surface-2);
  border: 1px solid var(--border);
  box-shadow: var(--shadow-elevated);
  max-width: 380px;
  cursor: pointer;
  pointer-events: auto;
}

.ui-toast--info {
  border-left: 3px solid var(--accent);
}

.ui-toast--success {
  border-left: 3px solid var(--success);
}

.ui-toast--warning {
  border-left: 3px solid var(--warning);
}

.ui-toast--error {
  border-left: 3px solid var(--danger);
}

.ui-toast__icon {
  flex-shrink: 0;
  font-size: var(--text-sm);
}

.ui-toast--info .ui-toast__icon {
  color: var(--accent);
}

.ui-toast--success .ui-toast__icon {
  color: var(--success);
}

.ui-toast--warning .ui-toast__icon {
  color: var(--warning);
}

.ui-toast--error .ui-toast__icon {
  color: var(--danger);
}

.ui-toast__text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ui-toast__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  padding: 0;
  margin-inline-start: var(--space-1);
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  outline: none;
  opacity: var(--opacity-medium);
  transition:
    background-color var(--duration-fast) var(--ease-out-quart),
    opacity var(--duration-fast) var(--ease-out-quart);
}

.ui-toast__close:hover {
  background: var(--surface-hover);
  opacity: 1;
  color: var(--text-primary);
}

.ui-toast__close:focus-visible {
  box-shadow: var(--shadow-focus);
}

/* ── Transition: slide in/out from right ────────────────────── */
.ui-toast-enter-active {
  animation: uiToastIn var(--duration-moderate) var(--ease-out-expo);
}

.ui-toast-leave-active {
  animation: uiToastOut var(--duration-normal) ease-in forwards;
}

@keyframes uiToastIn {
  from {
    opacity: 0;
    transform: translateX(40px);
  }

  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@keyframes uiToastOut {
  from {
    opacity: 1;
    transform: translateX(0);
  }

  to {
    opacity: 0;
    transform: translateX(40px);
  }
}
</style>
