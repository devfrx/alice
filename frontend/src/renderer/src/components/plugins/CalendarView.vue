<script setup lang="ts">
/**
 * CalendarView.vue — Weekly/monthly calendar with full CRUD support.
 *
 * Displays events in a week or month grid. Event create/edit
 * is handled by CalendarEventModal via the UiModal system.
 */
import {
  useCalendar,
  HOURS,
  DAY_NAMES,
  type CalendarEvent,
  type EventFormData,
  type ViewMode
} from '../../composables/useCalendar'
import { useModal } from '../../composables/useModal'
import CalendarEventModal from '../calendar/CalendarEventModal.vue'
import { UiButton, UiIconButton, UiSegmented, AppIcon } from '../ui'
import type { UiSegmentedOption } from '../ui/UiSegmented.vue'

const {
  viewMode,
  loading,
  error,
  headerLabel,
  events,
  visibleDays,
  isToday,
  isCurrentMonth,
  eventsForDay,
  eventStyle,
  eventColor,
  eventColumnStyle,
  formatTime,
  navigate,
  goToday,
  fetchEvents
} = useCalendar()

const { openCustom } = useModal()

const viewModeOptions: UiSegmentedOption[] = [
  { value: 'week', label: 'Settimana' },
  { value: 'month', label: 'Mese' }
]

function setViewMode(value: string | number): void {
  viewMode.value = value as ViewMode
}

/** Convert Date to datetime-local input value (YYYY-MM-DDTHH:mm). */
function toLocalISOString(d: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Convert ISO string to datetime-local value. */
function toDatetimeLocalValue(iso: string): string {
  return toLocalISOString(new Date(iso))
}

async function openEventModal(
  editingEvent: CalendarEvent | null,
  initialForm: EventFormData,
  title: string
): Promise<void> {
  const saved = await openCustom({
    component: CalendarEventModal,
    props: { editingEvent, initialForm },
    title,
    width: '480px'
  })
  if (saved) await fetchEvents()
}

function handleDayClick(day: Date): void {
  const clickDate = new Date(day)
  clickDate.setHours(9, 0, 0, 0)
  const endDate = new Date(clickDate)
  endDate.setHours(10, 0, 0, 0)
  openEventModal(
    null,
    {
      title: '',
      description: '',
      start: toLocalISOString(clickDate),
      end: toLocalISOString(endDate),
      reminder_minutes: null,
      recurrence_rule: ''
    },
    'Nuovo Evento'
  )
}

/** Week-view: open create form with the clicked hour pre-filled. */
function handleHourClick(day: Date, hour: number): void {
  const clickDate = new Date(day)
  clickDate.setHours(hour, 0, 0, 0)
  const endDate = new Date(day)
  endDate.setHours(hour + 1, 0, 0, 0)
  openEventModal(
    null,
    {
      title: '',
      description: '',
      start: toLocalISOString(clickDate),
      end: toLocalISOString(endDate),
      reminder_minutes: null,
      recurrence_rule: ''
    },
    'Nuovo Evento'
  )
}

function handleEventClick(ev: CalendarEvent, e: MouseEvent): void {
  e.stopPropagation()
  openEventModal(
    ev,
    {
      title: ev.title,
      description: ev.description ?? '',
      start: toDatetimeLocalValue(ev.start_time),
      end: toDatetimeLocalValue(ev.end_time),
      reminder_minutes: ev.reminder_minutes,
      recurrence_rule: ev.recurrence_rule ?? ''
    },
    'Modifica Evento'
  )
}

/** Extract the effective hour for creating a new event from an event block. */
function getEventHour(ev: CalendarEvent, day: Date): number {
  const evStart = new Date(ev.start_time)
  if (evStart.toDateString() === day.toDateString()) {
    return Math.max(evStart.getHours(), HOURS[0])
  }
  return HOURS[0]
}
</script>

<template>
  <div class="calendar">
    <header class="calendar__header">
      <div class="calendar__nav">
        <UiIconButton variant="outlined" size="md" label="Periodo precedente" @click="navigate(-1)">
          <AppIcon name="chevron-left" :size="14" />
        </UiIconButton>
        <UiButton variant="secondary" size="md" @click="goToday">Oggi</UiButton>
        <UiIconButton variant="outlined" size="md" label="Periodo successivo" @click="navigate(1)">
          <AppIcon name="chevron-right" :size="14" />
        </UiIconButton>
      </div>
      <h2 class="calendar__title">{{ headerLabel }}</h2>
      <UiSegmented
        class="calendar__mode"
        :model-value="viewMode"
        :options="viewModeOptions"
        size="md"
        aria-label="Vista calendario"
        @update:model-value="setViewMode"
      />
    </header>

    <div v-if="loading" class="calendar__loading">Caricamento eventi…</div>
    <div v-else-if="error" class="calendar__error">
      {{ error }}
      <UiButton variant="secondary" size="sm" @click="fetchEvents">Riprova</UiButton>
    </div>

    <div v-else-if="viewMode === 'week'" class="calendar__week">
      <div class="calendar__week-header">
        <div class="calendar__time-gutter"></div>
        <div
          v-for="day in visibleDays"
          :key="day.toISOString()"
          :class="['calendar__day-label', { 'calendar__day-label--today': isToday(day) }]"
        >
          {{ DAY_NAMES[day.getDay() === 0 ? 6 : day.getDay() - 1] }}
          <span class="calendar__day-num">{{ day.getDate() }}</span>
        </div>
      </div>
      <div class="calendar__week-body">
        <div class="calendar__time-gutter">
          <div v-for="h in HOURS" :key="h" class="calendar__hour-label">
            {{ String(h).padStart(2, '0') }}:00
          </div>
        </div>
        <div
          v-for="day in visibleDays"
          :key="day.toISOString()"
          :class="['calendar__day-col', { 'calendar__day-col--today': isToday(day) }]"
        >
          <div
            v-for="h in HOURS"
            :key="h"
            class="calendar__hour-slot"
            @click.stop="handleHourClick(day, h)"
          ></div>
          <div
            v-for="ev in eventsForDay(day)"
            :key="ev.occurrence_date ? `${ev.id}_${ev.occurrence_date}` : ev.id"
            class="calendar__event"
            :style="{
              ...eventStyle(ev, day),
              ...eventColumnStyle(ev, day),
              backgroundColor: eventColor(ev)
            }"
            :title="`${ev.title}\n${formatTime(ev.start_time)} – ${formatTime(ev.end_time)}`"
            @click="handleEventClick(ev, $event)"
          >
            <span class="calendar__event-time">{{ formatTime(ev.start_time) }}</span>
            <span class="calendar__event-title">{{ ev.title }}</span>
            <button
              class="calendar__event-add"
              title="Nuovo evento"
              @click.stop="handleHourClick(day, getEventHour(ev, day))"
            >
              +
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="calendar__month">
      <div class="calendar__month-header">
        <div v-for="name in DAY_NAMES" :key="name">{{ name }}</div>
      </div>
      <div class="calendar__month-grid">
        <div
          v-for="day in visibleDays"
          :key="day.toISOString()"
          :class="[
            'calendar__month-cell',
            {
              'calendar__month-cell--today': isToday(day),
              'calendar__month-cell--dim': !isCurrentMonth(day)
            }
          ]"
          @click="handleDayClick(day)"
        >
          <span class="calendar__month-date">{{ day.getDate() }}</span>
          <template v-for="(dayEvts, dayEvtIdx) in [eventsForDay(day)]">
            <div
              v-for="ev in dayEvts.slice(0, 3)"
              :key="ev.occurrence_date ? `${ev.id}_${ev.occurrence_date}` : ev.id"
              class="calendar__month-event"
              :style="{ backgroundColor: eventColor(ev) }"
              @click="handleEventClick(ev, $event)"
            >
              {{ ev.title }}
            </div>
            <span v-if="dayEvts.length > 3" :key="`more-${dayEvtIdx}`" class="calendar__month-more"
              >+{{ dayEvts.length - 3 }} altri</span
            >
          </template>
        </div>
      </div>
    </div>

    <div v-if="!loading && !error && events.length === 0" class="calendar__empty">
      Nessun evento in questo periodo. Clicca su un giorno per crearne uno.
    </div>
  </div>
</template>

<style scoped>
.calendar {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface-0);
  color: var(--text-primary);
  overflow: hidden;
}

.calendar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  background: var(--surface-1);
  border-bottom: 1px solid var(--border);
  gap: var(--space-4);
  flex-shrink: 0;
}

.calendar__nav {
  display: flex;
  gap: var(--space-1);
}

.calendar__title {
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  margin: 0;
  white-space: nowrap;
}

.calendar__loading,
.calendar__error,
.calendar__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-8);
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.calendar__error {
  color: var(--danger);
}

/* Week view */
.calendar__week {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.calendar__week-header {
  display: grid;
  grid-template-columns: 56px repeat(7, 1fr);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.calendar__day-label {
  text-align: center;
  padding: var(--space-2) 0;
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.calendar__day-label--today {
  color: var(--accent);
  font-weight: var(--weight-bold);
}

.calendar__day-num {
  margin-left: var(--space-1);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
}

.calendar__day-label--today .calendar__day-num {
  background: var(--accent);
  border-radius: var(--radius-full);
  display: inline-block;
  width: 22px;
  height: 22px;
  line-height: 22px;
  text-align: center;
  color: var(--text-on-accent);
}

.calendar__week-body {
  display: grid;
  grid-template-columns: 56px repeat(7, 1fr);
  flex: 1;
  overflow-y: auto;
}

.calendar__time-gutter {
  display: flex;
  flex-direction: column;
}

.calendar__hour-label {
  height: 56px;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding-right: var(--space-2);
  font-size: var(--text-2xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.calendar__day-col {
  position: relative;
  border-left: 1px solid var(--border);
  cursor: pointer;
}

.calendar__day-col--today {
  background: var(--accent-faint);
}

.calendar__hour-slot {
  height: 56px;
  border-bottom: 1px solid var(--border);
  transition: background var(--transition-fast);
}

.calendar__hour-slot:hover {
  background: var(--surface-hover);
}

.calendar__event {
  position: absolute;
  border-radius: var(--radius-sm);
  padding: var(--space-0-5) var(--space-1-5);
  font-size: var(--text-xs);
  overflow: hidden;
  cursor: pointer;
  z-index: var(--z-raised);
  color: var(--text-on-accent);
  transition: box-shadow var(--transition-fast);
}

.calendar__event:hover {
  box-shadow: var(--shadow-sm);
}

.calendar__event-time {
  opacity: 0.85;
  margin-right: var(--space-1);
  font-variant-numeric: tabular-nums;
}

.calendar__event-title {
  font-weight: var(--weight-semibold);
}

.calendar__event-add {
  display: none;
  position: absolute;
  top: var(--space-0-5);
  right: var(--space-0-5);
  width: 16px;
  height: 16px;
  border-radius: var(--radius-full);
  background: var(--surface-2);
  color: var(--text-secondary);
  border: none;
  font-size: var(--text-sm);
  line-height: 1;
  cursor: pointer;
  padding: 0;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-sm);
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.calendar__event:hover .calendar__event-add {
  display: flex;
}

.calendar__event-add:hover {
  background: var(--accent);
  color: var(--text-on-accent);
}

.calendar__event-add:active {
  transform: scale(0.92);
}

/* Month view */
.calendar__month {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.calendar__month-header {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  text-align: center;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  letter-spacing: var(--tracking-wide);
  text-transform: uppercase;
}

.calendar__month-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  grid-template-rows: repeat(6, 1fr);
  flex: 1;
  overflow: hidden;
}

.calendar__month-cell {
  border: 1px solid var(--border);
  padding: var(--space-1);
  cursor: pointer;
  min-height: 64px;
  overflow: hidden;
  transition: background var(--transition-fast);
}

.calendar__month-cell:hover {
  background: var(--surface-hover);
}

.calendar__month-cell--today {
  background: var(--accent-faint);
}

.calendar__month-cell--today:hover {
  background: var(--accent-dim);
}

.calendar__month-cell--today .calendar__month-date {
  color: var(--accent);
}

.calendar__month-cell--dim {
  opacity: var(--opacity-dim);
}

.calendar__month-date {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  font-variant-numeric: tabular-nums;
}

.calendar__month-event {
  font-size: var(--text-2xs);
  padding: var(--space-0-5) var(--space-1);
  border-radius: var(--radius-sm);
  margin-top: var(--space-0-5);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
  color: var(--text-on-accent);
  transition: box-shadow var(--transition-fast);
}

.calendar__month-event:hover {
  box-shadow: var(--shadow-sm);
}

.calendar__month-more {
  font-size: var(--text-2xs);
  color: var(--text-secondary);
}
</style>
