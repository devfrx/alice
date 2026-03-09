/**
 * Calendar-related types aligned with the OMNIA backend calendar API.
 */

/** A single calendar event from the backend. */
export interface CalendarEvent {
  id: string
  title: string
  description: string | null
  start_time: string   // ISO 8601 in local timezone
  end_time: string     // ISO 8601 in local timezone
  recurrence_rule: string | null
  reminder_minutes: number | null
  occurrence_date: string | null  // ISO date for recurring occurrence dedup
}

/** Response from the /calendar/today endpoint. */
export interface TodaySummary {
  date: string
  event_count: number
  events: CalendarEvent[]
}
