/** Calendar endpoints (`/api/calendar`). */
import { request } from './http'
import type { CalendarEvent, TodaySummary } from '../../types/calendar'

export const calendarApi = {
  /** Fetch today's calendar events. */
  getCalendarToday: (): Promise<TodaySummary> => request<TodaySummary>('/calendar/today'),

  /** Fetch upcoming events (next N). */
  getCalendarUpcoming: (limit?: number): Promise<CalendarEvent[]> =>
    request<CalendarEvent[]>(`/calendar/upcoming${limit ? `?limit=${limit}` : ''}`),

  /** Fetch events in a date range. */
  getCalendarEvents: (
    startDate?: string,
    endDate?: string,
    maxResults?: number
  ): Promise<CalendarEvent[]> => {
    const params = new URLSearchParams()
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    if (maxResults) params.set('max_results', String(maxResults))
    const qs = params.toString()
    return request<CalendarEvent[]>(`/calendar/events${qs ? `?${qs}` : ''}`)
  },

  /** Create a new calendar event. */
  createCalendarEvent: (data: {
    title: string
    start_time: string
    end_time: string
    description?: string
    reminder_minutes?: number
    recurrence_rule?: string
  }): Promise<CalendarEvent> =>
    request<CalendarEvent>('/calendar/events', {
      method: 'POST',
      body: JSON.stringify(data)
    }),

  /** Update an existing calendar event. */
  updateCalendarEvent: (id: string, data: Record<string, unknown>): Promise<CalendarEvent> =>
    request<CalendarEvent>(`/calendar/events/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(data)
    }),

  /** Delete a calendar event. */
  deleteCalendarEvent: (id: string): Promise<{ deleted: boolean; id: string }> =>
    request<{ deleted: boolean; id: string }>(`/calendar/events/${encodeURIComponent(id)}`, {
      method: 'DELETE'
    })
}
