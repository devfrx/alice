<script setup lang="ts">
/**
 * CalendarView.vue — Weekly/monthly calendar for the OMNIA calendar plugin.
 *
 * Displays events in a week or month grid. Emits events for modal
 * operations (create/edit) to be handled by a CalendarEventModal sibling.
 */
import {
  useCalendar,
  HOURS, DAY_NAMES,
  type CalendarEvent
} from '../../composables/useCalendar'

const emit = defineEmits<{
  create: [date: Date]
  edit: [event: CalendarEvent]
}>()

const {
  viewMode, loading, error, headerLabel, events,
  visibleDays, isToday, isCurrentMonth, eventsForDay,
  eventStyle, eventColor, formatTime, navigate, goToday, fetchEvents
} = useCalendar()

function handleDayClick(day: Date): void { emit('create', day) }
function handleEventClick(ev: CalendarEvent, e: MouseEvent): void {
  e.stopPropagation()
  emit('edit', ev)
}
</script>

<template>
  <div class="calendar">
    <header class="calendar__header">
      <div class="calendar__nav">
        <button class="calendar__btn" @click="navigate(-1)">‹</button>
        <button class="calendar__btn" @click="goToday">Oggi</button>
        <button class="calendar__btn" @click="navigate(1)">›</button>
      </div>
      <h2 class="calendar__title">{{ headerLabel }}</h2>
      <div class="calendar__mode">
        <button :class="['calendar__btn', { 'calendar__btn--active': viewMode === 'week' }]" @click="viewMode = 'week'">Settimana</button>
        <button :class="['calendar__btn', { 'calendar__btn--active': viewMode === 'month' }]" @click="viewMode = 'month'">Mese</button>
      </div>
    </header>

    <div v-if="loading" class="calendar__loading">Caricamento eventi…</div>
    <div v-else-if="error" class="calendar__error">
      {{ error }} <button class="calendar__btn" @click="fetchEvents">Riprova</button>
    </div>

    <div v-else-if="viewMode === 'week'" class="calendar__week">
      <div class="calendar__week-header">
        <div class="calendar__time-gutter"></div>
        <div v-for="day in visibleDays" :key="day.toISOString()" :class="['calendar__day-label', { 'calendar__day-label--today': isToday(day) }]">
          {{ DAY_NAMES[day.getDay() === 0 ? 6 : day.getDay() - 1] }} <span class="calendar__day-num">{{ day.getDate() }}</span>
        </div>
      </div>
      <div class="calendar__week-body">
        <div class="calendar__time-gutter">
          <div v-for="h in HOURS" :key="h" class="calendar__hour-label">{{ String(h).padStart(2, '0') }}:00</div>
        </div>
        <div v-for="day in visibleDays" :key="day.toISOString()" :class="['calendar__day-col', { 'calendar__day-col--today': isToday(day) }]" @click="handleDayClick(day)">
          <div v-for="h in HOURS" :key="h" class="calendar__hour-slot"></div>
          <div v-for="ev in eventsForDay(day)" :key="ev.id" class="calendar__event" :style="{ ...eventStyle(ev), backgroundColor: eventColor(ev) }" :title="`${ev.title}\n${formatTime(ev.start_time)} – ${formatTime(ev.end_time)}`" @click="handleEventClick(ev, $event)">
            <span class="calendar__event-time">{{ formatTime(ev.start_time) }}</span>
            <span class="calendar__event-title">{{ ev.title }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="calendar__month">
      <div class="calendar__month-header">
        <div v-for="name in DAY_NAMES" :key="name">{{ name }}</div>
      </div>
      <div class="calendar__month-grid">
        <div v-for="day in visibleDays" :key="day.toISOString()" :class="['calendar__month-cell', { 'calendar__month-cell--today': isToday(day), 'calendar__month-cell--dim': !isCurrentMonth(day) }]" @click="handleDayClick(day)">
          <span class="calendar__month-date">{{ day.getDate() }}</span>
          <div v-for="ev in eventsForDay(day).slice(0, 3)" :key="ev.id" class="calendar__month-event" :style="{ backgroundColor: eventColor(ev) }" @click="handleEventClick(ev, $event)">{{ ev.title }}</div>
          <span v-if="eventsForDay(day).length > 3" class="calendar__month-more">+{{ eventsForDay(day).length - 3 }} altri</span>
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
  --bg-primary: #1a1a2e; --bg-secondary: #16213e; --bg-tertiary: #0f3460;
  --accent: #e94560; --text-primary: #eee; --text-secondary: #aaa;
  --border: rgba(255, 255, 255, 0.1);
  display: flex; flex-direction: column; height: 100%;
  background: var(--bg-primary); color: var(--text-primary); overflow: hidden;
}
.calendar__header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 0.75rem 1rem; background: var(--bg-secondary);
  border-bottom: 1px solid var(--border); gap: 1rem; flex-shrink: 0;
}
.calendar__nav, .calendar__mode { display: flex; gap: 0.25rem; }
.calendar__title { font-size: 1.1rem; font-weight: 600; margin: 0; white-space: nowrap; }
.calendar__btn {
  background: var(--bg-tertiary); color: var(--text-primary);
  border: 1px solid var(--border); border-radius: 4px;
  padding: 0.35rem 0.7rem; cursor: pointer; font-size: 0.85rem;
}
.calendar__btn:hover { background: var(--accent); }
.calendar__btn--active { background: var(--accent); border-color: var(--accent); }
.calendar__loading, .calendar__error, .calendar__empty {
  display: flex; align-items: center; justify-content: center;
  gap: 0.5rem; padding: 2rem; color: var(--text-secondary); font-size: 0.9rem;
}
.calendar__error { color: var(--accent); }

/* Week view */
.calendar__week { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.calendar__week-header {
  display: grid; grid-template-columns: 3.5rem repeat(7, 1fr);
  border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.calendar__day-label {
  text-align: center; padding: 0.4rem 0; font-size: 0.8rem; color: var(--text-secondary);
}
.calendar__day-label--today { color: var(--accent); font-weight: 700; }
.calendar__day-num { margin-left: 0.25rem; font-weight: 600; color: var(--text-primary); }
.calendar__day-label--today .calendar__day-num {
  background: var(--accent); border-radius: 50%;
  display: inline-block; width: 1.5rem; height: 1.5rem;
  line-height: 1.5rem; text-align: center; color: #fff;
}
.calendar__week-body {
  display: grid; grid-template-columns: 3.5rem repeat(7, 1fr);
  flex: 1; overflow-y: auto;
}
.calendar__time-gutter { display: flex; flex-direction: column; }
.calendar__hour-label {
  height: 3.5rem; display: flex; align-items: flex-start;
  justify-content: flex-end; padding-right: 0.4rem;
  font-size: 0.7rem; color: var(--text-secondary);
}
.calendar__day-col {
  position: relative; border-left: 1px solid var(--border); cursor: pointer;
}
.calendar__day-col--today { background: rgba(233, 69, 96, 0.05); }
.calendar__hour-slot { height: 3.5rem; border-bottom: 1px solid var(--border); }
.calendar__event {
  position: absolute; left: 2px; right: 2px; border-radius: 4px;
  padding: 0.15rem 0.3rem; font-size: 0.75rem; overflow: hidden;
  cursor: pointer; z-index: 1;
}
.calendar__event:hover { filter: brightness(1.2); }
.calendar__event-time { opacity: 0.85; margin-right: 0.25rem; }
.calendar__event-title { font-weight: 600; }

/* Month view */
.calendar__month { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.calendar__month-header {
  display: grid; grid-template-columns: repeat(7, 1fr);
  text-align: center; font-size: 0.8rem; color: var(--text-secondary);
  padding: 0.3rem 0; border-bottom: 1px solid var(--border); flex-shrink: 0;
}
.calendar__month-grid {
  display: grid; grid-template-columns: repeat(7, 1fr);
  grid-template-rows: repeat(6, 1fr); flex: 1; overflow: hidden;
}
.calendar__month-cell {
  border: 1px solid var(--border); padding: 0.25rem;
  cursor: pointer; min-height: 4rem; overflow: hidden;
}
.calendar__month-cell:hover { background: var(--bg-secondary); }
.calendar__month-cell--today { background: rgba(233, 69, 96, 0.08); }
.calendar__month-cell--dim { opacity: 0.4; }
.calendar__month-date { font-size: 0.8rem; font-weight: 600; }
.calendar__month-event {
  font-size: 0.7rem; padding: 0.1rem 0.3rem; border-radius: 3px;
  margin-top: 0.15rem; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; cursor: pointer;
}
.calendar__month-more { font-size: 0.65rem; color: var(--text-secondary); }
</style>
