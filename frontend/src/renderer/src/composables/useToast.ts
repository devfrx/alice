/**
 * AL\CE — Universal toast notification composable.
 *
 * Singleton module-level state (same pattern as useModal).
 * Any part of the app can call `useToast().success('Done!')`.
 */
import { ref } from 'vue'
import type { Ref } from 'vue'

export type ToastType = 'info' | 'success' | 'warning' | 'error'

export interface Toast {
  id: number
  type: ToastType
  message: string
  duration: number
}

export interface ToastOptions {
  message: string
  type?: ToastType
  duration?: number
}

// ── Module-level singleton state ──────────────────────────────

let _counter = 0
const toasts: Ref<Toast[]> = ref([])
const _timers = new Map<number, ReturnType<typeof setTimeout>>()

// ── Defaults ──────────────────────────────────────────────────

const DEFAULT_DURATION: Record<ToastType, number> = {
  info: 4000,
  success: 4000,
  warning: 4000,
  error: 6000
}

// ── Core helpers ──────────────────────────────────────────────

function show(opts: ToastOptions | string): number {
  const resolved: ToastOptions = typeof opts === 'string' ? { message: opts } : opts
  const type = resolved.type ?? 'info'
  const duration = resolved.duration ?? DEFAULT_DURATION[type]

  const id = ++_counter
  toasts.value.push({ id, type, message: resolved.message, duration })

  if (duration > 0) {
    _timers.set(
      id,
      setTimeout(() => dismiss(id), duration)
    )
  }
  return id
}

function dismiss(id: number): void {
  const timer = _timers.get(id)
  if (timer) {
    clearTimeout(timer)
    _timers.delete(id)
  }
  const idx = toasts.value.findIndex((t) => t.id === id)
  if (idx !== -1) toasts.value.splice(idx, 1)
}

function dismissAll(): void {
  for (const timer of _timers.values()) clearTimeout(timer)
  _timers.clear()
  toasts.value = []
}

// ── Convenience shortcuts ─────────────────────────────────────

function info(message: string, duration?: number): number {
  return show({ message, type: 'info', duration })
}

function success(message: string, duration?: number): number {
  return show({ message, type: 'success', duration })
}

function warning(message: string, duration?: number): number {
  return show({ message, type: 'warning', duration })
}

function error(message: string, duration?: number): number {
  return show({ message, type: 'error', duration })
}

// ── Public composable ─────────────────────────────────────────

export function useToast(): {
  toasts: Ref<Toast[]>
  show: (opts: ToastOptions | string) => number
  dismiss: (id: number) => void
  dismissAll: () => void
  info: (message: string, duration?: number) => number
  success: (message: string, duration?: number) => number
  warning: (message: string, duration?: number) => number
  error: (message: string, duration?: number) => number
} {
  return { toasts, show, dismiss, dismissAll, info, success, warning, error } as const
}
