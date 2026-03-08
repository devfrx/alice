/**
 * useCalendar — Composable for calendar state, navigation, and API access.
 *
 * Encapsulates all data logic for the CalendarView component:
 * date navigation, event fetching via plugin tool execution,
 * and helper utilities for rendering.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../services/api'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface CalendarEvent {
  id: string
  title: string
  description: string | null
  start_time: string
  end_time: string
  reminder_minutes: number | null
  recurrence_rule: string | null
}

export interface EventFormData {
  title: string
  description: string
  start: string
  end: string
  reminder_minutes: number | null
}

export type ViewMode = 'week' | 'month'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Visible hours in week view grid (07:00–22:00). */
export const HOURS = Array.from({ length: 16 }, (_, i) => i + 7)
export const DAY_NAMES = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom']
export const MONTH_NAMES = [
  'Gennaio', 'Febbraio', 'Marzo', 'Aprile', 'Maggio', 'Giugno',
  'Luglio', 'Agosto', 'Settembre', 'Ottobre', 'Novembre', 'Dicembre'
]

/** Milliseconds in one day. */
const MS_PER_DAY = 86_400_000

/** Palette for event block backgrounds. */
const EVENT_COLORS = [
  '#e94560', '#0f3460', '#00b4d8', '#e77f67',
  '#786fa6', '#f8a5c2', '#63cdda', '#cf6a87'
]

// ---------------------------------------------------------------------------
// Composable
// ---------------------------------------------------------------------------

export function useCalendar() {
  const viewMode = ref<ViewMode>('week')
  const currentDate = ref(new Date())
  const events = ref<CalendarEvent[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  /** Monday of the current week. */
  const weekStart = computed(() => {
    const d = new Date(currentDate.value)
    const day = d.getDay()
    d.setDate(d.getDate() - day + (day === 0 ? -6 : 1))
    d.setHours(0, 0, 0, 0)
    return d
  })

  /** Days visible in the current grid view. */
  const visibleDays = computed((): Date[] => {
    if (viewMode.value === 'week') {
      return Array.from({ length: 7 }, (_, i) => {
        const d = new Date(weekStart.value)
        d.setDate(d.getDate() + i)
        return d
      })
    }
    const first = new Date(currentDate.value.getFullYear(), currentDate.value.getMonth(), 1)
    const offset = first.getDay() === 0 ? -6 : 1 - first.getDay()
    const start = new Date(first)
    start.setDate(first.getDate() + offset)
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start)
      d.setDate(d.getDate() + i)
      return d
    })
  })

  /** Header label (e.g. "3–9 Marzo 2026" or "Marzo 2026"). */
  const headerLabel = computed((): string => {
    if (viewMode.value === 'month') {
      return `${MONTH_NAMES[currentDate.value.getMonth()]} ${currentDate.value.getFullYear()}`
    }
    const ws = weekStart.value
    const we = new Date(ws)
    we.setDate(we.getDate() + 6)
    if (ws.getMonth() === we.getMonth()) {
      return `${ws.getDate()}–${we.getDate()} ${MONTH_NAMES[ws.getMonth()]} ${ws.getFullYear()}`
    }
    return `${ws.getDate()} ${MONTH_NAMES[ws.getMonth()]} – ${we.getDate()} ${MONTH_NAMES[we.getMonth()]} ${we.getFullYear()}`
  })

  // ── Helpers ──────────────────────────────────────────────────

  const isToday = (d: Date): boolean => d.toDateString() === new Date().toDateString()

  const isCurrentMonth = (d: Date): boolean =>
    d.getMonth() === currentDate.value.getMonth()

  /** Pre-computed map: date string → events for that day (O(1) lookup). */
  const eventsByDay = computed(() => {
    const map = new Map<string, CalendarEvent[]>()
    for (const event of events.value) {
      const key = new Date(event.start_time).toDateString()
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(event)
    }
    return map
  })

  function eventsForDay(day: Date): CalendarEvent[] {
    return eventsByDay.value.get(day.toDateString()) || []
  }

  /** Position style for a week-view event block. */
  function eventStyle(ev: CalendarEvent): Record<string, string> {
    const start = new Date(ev.start_time)
    const end = new Date(ev.end_time)
    const gridStart = HOURS[0] * 60
    const topRem = ((start.getHours() * 60 + start.getMinutes() - gridStart) / 60) * 3.5
    const heightRem = Math.max(((end.getHours() * 60 + end.getMinutes() - start.getHours() * 60 - start.getMinutes()) / 60) * 3.5, 1.5)
    return { top: `${topRem}rem`, height: `${heightRem}rem` }
  }

  /** Deterministic color for an event based on title hash. */
  function eventColor(ev: CalendarEvent): string {
    let hash = 0
    for (const ch of ev.title) hash = ((hash << 5) - hash + ch.charCodeAt(0)) | 0
    return EVENT_COLORS[Math.abs(hash) % EVENT_COLORS.length]
  }

  const formatTime = (iso: string): string =>
    new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  // ── Navigation ───────────────────────────────────────────────

  function navigate(direction: -1 | 1): void {
    const d = new Date(currentDate.value)
    if (viewMode.value === 'week') d.setDate(d.getDate() + direction * 7)
    else d.setMonth(d.getMonth() + direction)
    currentDate.value = d
  }

  function goToday(): void { currentDate.value = new Date() }

  // ── Data fetching ────────────────────────────────────────────

  async function fetchEvents(): Promise<void> {
    loading.value = true
    error.value = null
    const days = visibleDays.value
    const startDate = days[0].toISOString()
    const endDate = new Date(days[days.length - 1].getTime() + MS_PER_DAY).toISOString()
    try {
      const res = await api.executePluginTool<CalendarEvent[]>(
        'calendar', 'list_events',
        { start_date: startDate, end_date: endDate, max_results: 100 }
      )
      events.value = res.success && Array.isArray(res.content) ? res.content : []
      if (!res.success) error.value = res.error_message ?? 'Failed to fetch events'
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Network error'
    } finally {
      loading.value = false
    }
  }

  onMounted(fetchEvents)
  watch([currentDate, viewMode], fetchEvents)

  return {
    viewMode, currentDate, events, loading, error, headerLabel,
    visibleDays, isToday, isCurrentMonth, eventsForDay,
    eventStyle, eventColor, formatTime, navigate, goToday, fetchEvents
  }
}
