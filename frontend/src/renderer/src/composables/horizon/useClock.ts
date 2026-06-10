/**
 * useClock — a Date ref that ticks on an interval (default 30 s).
 * Shared by the greeting and the colophon so they agree on "now".
 */
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

export function useClock(intervalMs = 30_000): Ref<Date> {
  const now = ref(new Date())
  let timer: ReturnType<typeof setInterval> | null = null
  onMounted(() => {
    timer = setInterval(() => {
      now.value = new Date()
    }, intervalMs)
  })
  onBeforeUnmount(() => {
    if (timer) clearInterval(timer)
  })
  return now
}
