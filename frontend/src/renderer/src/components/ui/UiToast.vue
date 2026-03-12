<script setup lang="ts">
/**
 * O.M.N.I.A. — Global toast notification renderer.
 *
 * Mount once in App.vue. Reads from the useToast() singleton
 * and renders all active toasts via a Teleport to <body>.
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
</script>

<template>
  <Teleport to="body">
    <TransitionGroup name="ui-toast" tag="div" class="ui-toast-container">
      <div v-for="toast in toasts" :key="toast.id" class="ui-toast" :class="`ui-toast--${toast.type}`" role="status"
        @click="dismiss(toast.id)">
        <span class="ui-toast__icon">{{ ICONS[toast.type] }}</span>
        <span class="ui-toast__text">{{ toast.message }}</span>
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
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Transition: slide in/out from right ────────────────────── */
.ui-toast-enter-active {
  animation: uiToastIn 0.3s var(--ease-out-expo);
}

.ui-toast-leave-active {
  animation: uiToastOut 0.2s ease-in forwards;
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
