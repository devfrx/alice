/**
 * useCalendar — Composable for calendar state, navigation, and API access.
 *
 * Encapsulates all data logic for the CalendarView component:
 * date navigation, event fetching via plugin tool execution,
 * and helper utilities for rendering.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../services/api'
import { useCalendarStore } from '../stores/calendar'
import type { CalendarEvent } from '../types/calendar'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type { CalendarEvent }

export interface EventFormData {
  title: string
  description: string
  start: string
  end: string
  reminder_minutes: number | null
  recurrence_rule: string
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
  '#C9A84C', '#E07B53', '#5DADE2', '#58D68D',
  '#AF7AC5', '#F1948A', '#45B7D1', '#F0B27A'
]

// ---------------------------------------------------------------------------
// Composable
// ---------------------------------------------------------------------------

export function useCalendar() {
  const calendarStore = useCalendarStore()
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
      const startDay = new Date(event.start_time)
      startDay.setHours(0, 0, 0, 0)
      const endDay = new Date(event.end_time)
      endDay.setHours(0, 0, 0, 0)
      const endRaw = new Date(event.end_time)
      if (endRaw.getHours() === 0 && endRaw.getMinutes() === 0 && endRaw.getSeconds() === 0 && endDay > startDay) {
        endDay.setDate(endDay.getDate() - 1)
      }
      const cursor = new Date(startDay)
      while (cursor <= endDay) {
        const key = cursor.toDateString()
        if (!map.has(key)) map.set(key, [])
        const arr = map.get(key)!
        if (!arr.some(e => e.id === event.id && e.occurrence_date === event.occurrence_date)) arr.push(event)
        cursor.setDate(cursor.getDate() + 1)
      }
    }
    return map
  })

  function eventsForDay(day: Date): CalendarEvent[] {
    return eventsByDay.value.get(day.toDateString()) || []
  }

  /**
   * Effective minute range of an event within a specific day's grid.
   * Returns null if the event does not intersect the visible grid on that day.
   */
  function effectiveRange(
    ev: CalendarEvent,
    day: Date
  ): { startMin: number; endMin: number } | null {
    const gridStart = HOURS[0] * 60
    const gridEnd = (HOURS[HOURS.length - 1] + 1) * 60
    const evStart = new Date(ev.start_time)
    const evEnd = new Date(ev.end_time)
    const dayMidnight = new Date(day)
    dayMidnight.setHours(0, 0, 0, 0)
    const nextDay = new Date(dayMidnight)
    nextDay.setDate(nextDay.getDate() + 1)
    if (evStart >= nextDay || evEnd <= dayMidnight) return null
    const onStartDay = evStart >= dayMidnight && evStart < nextDay
    const onEndDay = evEnd > dayMidnight && evEnd < nextDay
    const startMin = onStartDay
      ? Math.max(evStart.getHours() * 60 + evStart.getMinutes(), gridStart)
      : gridStart
    const endMin = onEndDay
      ? Math.min(evEnd.getHours() * 60 + evEnd.getMinutes(), gridEnd)
      : gridEnd
    return endMin > startMin ? { startMin, endMin } : null
  }

  /** Position style for a week-view event block (day-aware for multi-day). */
  function eventStyle(ev: CalendarEvent, day: Date): Record<string, string> {
    const gridStart = HOURS[0] * 60
    const maxTop = HOURS.length * 3.5
    const range = effectiveRange(ev, day)
    if (!range) return { display: 'none' }
    let topRem = ((range.startMin - gridStart) / 60) * 3.5
    let heightRem = ((range.endMin - range.startMin) / 60) * 3.5
    topRem = Math.max(0, Math.min(topRem, maxTop))
    topRem = Math.min(topRem, maxTop - 1.5)
    heightRem = Math.max(1.5, Math.min(heightRem, maxTop - topRem))
    return { top: `${topRem}rem`, height: `${heightRem}rem` }
  }

  /** Deterministic color for an event based on title hash. */
  function eventColor(ev: CalendarEvent): string {
    let hash = 0
    for (const ch of ev.title) hash = ((hash << 5) - hash + ch.charCodeAt(0)) | 0
    return EVENT_COLORS[Math.abs(hash) % EVENT_COLORS.length]
  }

  /** Compute column layout for overlapping events on a given day. */
  function computeColumnLayout(
    dayEvents: CalendarEvent[],
    day: Date
  ): Map<string, { left: string; width: string }> {
    const items: Array<{ key: string; startMin: number; endMin: number }> = []
    for (const ev of dayEvents) {
      const range = effectiveRange(ev, day)
      if (!range) continue
      const key = ev.occurrence_date ? `${ev.id}_${ev.occurrence_date}` : ev.id
      items.push({ key, startMin: range.startMin, endMin: range.endMin })
    }
    items.sort(
      (a, b) => a.startMin - b.startMin
        || (b.endMin - b.startMin) - (a.endMin - a.startMin)
    )
    const columns: number[] = []
    const placed: Array<{
      key: string; column: number; startMin: number; endMin: number
    }> = []
    for (const item of items) {
      let col = columns.findIndex(end => end <= item.startMin)
      if (col === -1) { col = columns.length; columns.push(0) }
      columns[col] = item.endMin
      placed.push({ ...item, column: col })
    }
    placed.sort((a, b) => a.startMin - b.startMin)
    const groups: (typeof placed)[] = []
    let cur: typeof placed = []
    let groupEnd = -Infinity
    for (const p of placed) {
      if (cur.length === 0 || p.startMin < groupEnd) {
        cur.push(p)
        groupEnd = Math.max(groupEnd, p.endMin)
      } else {
        groups.push(cur)
        cur = [p]
        groupEnd = p.endMin
      }
    }
    if (cur.length > 0) groups.push(cur)
    const result = new Map<string, { left: string; width: string }>()
    for (const group of groups) {
      const totalCols = Math.max(...group.map(e => e.column)) + 1
      const pct = 100 / totalCols
      for (const ev of group) {
        result.set(ev.key, {
          left: `calc(${ev.column * pct}% + 1px)`,
          width: `calc(${pct}% - 2px)`
        })
      }
    }
    return result
  }

  /** Pre-computed column layouts per day (reacts to event changes). */
  const allDayLayouts = computed(() => {
    const result = new Map<string, Map<string, { left: string; width: string }>>()
    for (const [dayKey, dayEvents] of eventsByDay.value) {
      result.set(dayKey, computeColumnLayout(dayEvents, new Date(dayKey)))
    }
    return result
  })

  /** Column position style (left/width) for an event on a specific day. */
  function eventColumnStyle(
    ev: CalendarEvent,
    day: Date
  ): Record<string, string> {
    const layout = allDayLayouts.value.get(day.toDateString())
    if (!layout) return { left: '2px', width: 'calc(100% - 4px)' }
    const key = ev.occurrence_date ? `${ev.id}_${ev.occurrence_date}` : ev.id
    return layout.get(key) ?? { left: '2px', width: 'calc(100% - 4px)' }
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
      events.value = await api.getCalendarEvents(startDate, endDate, 100)
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Errore di rete'
      events.value = []
    } finally {
      loading.value = false
    }
  }

  async function createEvent(data: EventFormData): Promise<void> {
    await api.createCalendarEvent({
      title: data.title,
      description: data.description || undefined,
      start_time: data.start,
      end_time: data.end,
      reminder_minutes: data.reminder_minutes ?? undefined,
      recurrence_rule: data.recurrence_rule || undefined,
    })
    await fetchEvents()
    void calendarStore.refresh()
  }

  async function updateEvent(id: string, data: Partial<EventFormData>): Promise<void> {
    const payload: Record<string, unknown> = {}
    if (data.title !== undefined) payload.title = data.title
    if (data.description !== undefined) payload.description = data.description
    if (data.start !== undefined) payload.start_time = data.start
    if (data.end !== undefined) payload.end_time = data.end
    if (data.reminder_minutes !== undefined) payload.reminder_minutes = data.reminder_minutes
    if (data.recurrence_rule !== undefined) payload.recurrence_rule = data.recurrence_rule
    await api.updateCalendarEvent(id, payload)
    await fetchEvents()
    void calendarStore.refresh()
  }

  async function deleteEvent(id: string): Promise<void> {
    await api.deleteCalendarEvent(id)
    await fetchEvents()
    void calendarStore.refresh()
  }

  onMounted(fetchEvents)
  watch([currentDate, viewMode], fetchEvents)

  return {
    viewMode, currentDate, events, loading, error, headerLabel,
    visibleDays, isToday, isCurrentMonth, eventsForDay,
    eventStyle, eventColor, eventColumnStyle, formatTime,
    navigate, goToday, fetchEvents, createEvent, updateEvent, deleteEvent
  }
}
