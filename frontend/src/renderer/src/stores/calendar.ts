/**
 * Pinia store for calendar widget state.
 *
 * Provides today's events and upcoming events for sidebar display.
 * Auto-refreshes every 5 minutes.
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../services/api'
import type { CalendarEvent, TodaySummary } from '../types/calendar'

export const useCalendarStore = defineStore('calendar', () => {
  const todaySummary = ref<TodaySummary | null>(null)
  const upcomingEvents = ref<CalendarEvent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** Number of events today. */
  const todayCount = computed(() => todaySummary.value?.event_count ?? 0)

  /** The next upcoming event (closest to now). */
  const nextEvent = computed(() => upcomingEvents.value[0] ?? null)

  let refreshInterval: ReturnType<typeof setInterval> | null = null

  /** Fetch today's summary and upcoming events. */
  async function refresh(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [today, upcoming] = await Promise.all([
        api.getCalendarToday(),
        api.getCalendarUpcoming(5),
      ])
      todaySummary.value = today
      upcomingEvents.value = upcoming
    } catch (err) {
      error.value = err instanceof Error ? err.message : String(err)
    } finally {
      loading.value = false
    }
  }

  /** Start periodic refresh (every 5 minutes). */
  function startPolling(): void {
    if (refreshInterval) return
    refresh()
    refreshInterval = setInterval(refresh, 5 * 60 * 1000)
  }

  /** Stop periodic refresh. */
  function stopPolling(): void {
    if (refreshInterval) {
      clearInterval(refreshInterval)
      refreshInterval = null
    }
  }

  return {
    todaySummary,
    upcomingEvents,
    loading,
    error,
    todayCount,
    nextEvent,
    refresh,
    startPolling,
    stopPolling,
  }
})
