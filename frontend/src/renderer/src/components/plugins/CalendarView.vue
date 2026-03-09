<script setup lang="ts">
/**
 * CalendarView.vue — Weekly/monthly calendar with full CRUD support.
 *
 * Displays events in a week or month grid. Inline modal for
 * creating, editing, and deleting events via REST API.
 */
import { ref } from 'vue'
import {
  useCalendar,
  HOURS, DAY_NAMES,
  type CalendarEvent, type EventFormData
} from '../../composables/useCalendar'

const {
  viewMode, loading, error, headerLabel, events,
  visibleDays, isToday, isCurrentMonth, eventsForDay,
  eventStyle, eventColor, eventColumnStyle, formatTime,
  navigate, goToday, fetchEvents, createEvent, updateEvent, deleteEvent
} = useCalendar()

const showModal = ref(false)
const editingEvent = ref<CalendarEvent | null>(null)
const saveError = ref<string | null>(null)
const form = ref<EventFormData>({
  title: '',
  description: '',
  start: '',
  end: '',
  reminder_minutes: null,
  recurrence_rule: '',
})
const saving = ref(false)

/** Convert Date to datetime-local input value (YYYY-MM-DDTHH:mm). */
function toLocalISOString(d: Date): string {
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** Convert ISO string to datetime-local value. */
function toDatetimeLocalValue(iso: string): string {
  return toLocalISOString(new Date(iso))
}

function handleDayClick(day: Date): void {
  editingEvent.value = null
  const clickDate = new Date(day)
  clickDate.setHours(9, 0, 0, 0)
  const endDate = new Date(clickDate)
  endDate.setHours(10, 0, 0, 0)
  form.value = {
    title: '',
    description: '',
    start: toLocalISOString(clickDate),
    end: toLocalISOString(endDate),
    reminder_minutes: null,
    recurrence_rule: '',
  }
  showModal.value = true
}

/** Week-view: open create form with the clicked hour pre-filled. */
function handleHourClick(day: Date, hour: number): void {
  editingEvent.value = null
  const clickDate = new Date(day)
  clickDate.setHours(hour, 0, 0, 0)
  const endDate = new Date(day)
  endDate.setHours(hour + 1, 0, 0, 0)
  form.value = {
    title: '',
    description: '',
    start: toLocalISOString(clickDate),
    end: toLocalISOString(endDate),
    reminder_minutes: null,
    recurrence_rule: '',
  }
  showModal.value = true
}

function handleEventClick(ev: CalendarEvent, e: MouseEvent): void {
  e.stopPropagation()
  editingEvent.value = ev
  form.value = {
    title: ev.title,
    description: ev.description ?? '',
    start: toDatetimeLocalValue(ev.start_time),
    end: toDatetimeLocalValue(ev.end_time),
    reminder_minutes: ev.reminder_minutes,
    recurrence_rule: ev.recurrence_rule ?? '',
  }
  showModal.value = true
}

async function handleSave(): Promise<void> {
  saving.value = true
  saveError.value = null
  if (new Date(form.value.end) <= new Date(form.value.start)) {
    saveError.value = 'La fine deve essere dopo l\'inizio'
    saving.value = false
    return
  }
  const rawReminder: unknown = form.value.reminder_minutes
  const reminderMinutes = (rawReminder != null && rawReminder !== '' && !Number.isNaN(Number(rawReminder)))
    ? Number(rawReminder)
    : null
  const payload: EventFormData = { ...form.value, reminder_minutes: reminderMinutes }
  try {
    if (editingEvent.value) {
      await updateEvent(editingEvent.value.id, payload)
    } else {
      await createEvent(payload)
    }
    showModal.value = false
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : 'Salvataggio fallito'
  } finally {
    saving.value = false
  }
}

async function handleDelete(): Promise<void> {
  if (!editingEvent.value) return
  saving.value = true
  saveError.value = null
  try {
    await deleteEvent(editingEvent.value.id)
    showModal.value = false
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : 'Eliminazione fallita'
  } finally {
    saving.value = false
  }
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
        <button class="calendar__btn" @click="navigate(-1)">‹</button>
        <button class="calendar__btn" @click="goToday">Oggi</button>
        <button class="calendar__btn" @click="navigate(1)">›</button>
      </div>
      <h2 class="calendar__title">{{ headerLabel }}</h2>
      <div class="calendar__mode">
        <button :class="['calendar__btn', { 'calendar__btn--active': viewMode === 'week' }]"
          @click="viewMode = 'week'">Settimana</button>
        <button :class="['calendar__btn', { 'calendar__btn--active': viewMode === 'month' }]"
          @click="viewMode = 'month'">Mese</button>
      </div>
    </header>

    <div v-if="loading" class="calendar__loading">Caricamento eventi…</div>
    <div v-else-if="error" class="calendar__error">
      {{ error }} <button class="calendar__btn" @click="fetchEvents">Riprova</button>
    </div>

    <div v-else-if="viewMode === 'week'" class="calendar__week">
      <div class="calendar__week-header">
        <div class="calendar__time-gutter"></div>
        <div v-for="day in visibleDays" :key="day.toISOString()"
          :class="['calendar__day-label', { 'calendar__day-label--today': isToday(day) }]">
          {{ DAY_NAMES[day.getDay() === 0 ? 6 : day.getDay() - 1] }} <span class="calendar__day-num">{{ day.getDate()
          }}</span>
        </div>
      </div>
      <div class="calendar__week-body">
        <div class="calendar__time-gutter">
          <div v-for="h in HOURS" :key="h" class="calendar__hour-label">{{ String(h).padStart(2, '0') }}:00</div>
        </div>
        <div v-for="day in visibleDays" :key="day.toISOString()"
          :class="['calendar__day-col', { 'calendar__day-col--today': isToday(day) }]">
          <div v-for="h in HOURS" :key="h" class="calendar__hour-slot" @click.stop="handleHourClick(day, h)"></div>
          <div v-for="ev in eventsForDay(day)" :key="ev.occurrence_date ? `${ev.id}_${ev.occurrence_date}` : ev.id"
            class="calendar__event"
            :style="{ ...eventStyle(ev, day), ...eventColumnStyle(ev, day), backgroundColor: eventColor(ev) }"
            :title="`${ev.title}\n${formatTime(ev.start_time)} – ${formatTime(ev.end_time)}`"
            @click="handleEventClick(ev, $event)">
            <span class="calendar__event-time">{{ formatTime(ev.start_time) }}</span>
            <span class="calendar__event-title">{{ ev.title }}</span>
            <button class="calendar__event-add" @click.stop="handleHourClick(day, getEventHour(ev, day))"
              title="Nuovo evento">+</button>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="calendar__month">
      <div class="calendar__month-header">
        <div v-for="name in DAY_NAMES" :key="name">{{ name }}</div>
      </div>
      <div class="calendar__month-grid">
        <div v-for="day in visibleDays" :key="day.toISOString()"
          :class="['calendar__month-cell', { 'calendar__month-cell--today': isToday(day), 'calendar__month-cell--dim': !isCurrentMonth(day) }]"
          @click="handleDayClick(day)">
          <span class="calendar__month-date">{{ day.getDate() }}</span>
          <template v-for="(dayEvts, dayEvtIdx) in [eventsForDay(day)]">
            <div v-for="ev in dayEvts.slice(0, 3)" :key="ev.occurrence_date ? `${ev.id}_${ev.occurrence_date}` : ev.id"
              class="calendar__month-event" :style="{ backgroundColor: eventColor(ev) }"
              @click="handleEventClick(ev, $event)">{{ ev.title }}</div>
            <span v-if="dayEvts.length > 3" :key="`more-${dayEvtIdx}`" class="calendar__month-more">+{{ dayEvts.length -
              3 }}
              altri</span>
          </template>
        </div>
      </div>
    </div>

    <div v-if="!loading && !error && events.length === 0" class="calendar__empty">
      Nessun evento in questo periodo. Clicca su un giorno per crearne uno.
    </div>

    <!-- Event create/edit modal -->
    <Teleport to="body">
      <div v-if="showModal" class="cal-modal-overlay" @click.self="showModal = false">
        <div class="cal-modal">
          <h3 class="cal-modal__title">{{ editingEvent ? 'Modifica Evento' : 'Nuovo Evento' }}</h3>
          <p v-if="editingEvent?.recurrence_rule" class="cal-modal__recurrence-warn">
            Attenzione: le modifiche verranno applicate a tutte le occorrenze.
          </p>
          <p v-if="saveError" class="cal-modal__error">{{ saveError }}</p>

          <div class="cal-modal__field">
            <label>Titolo</label>
            <input v-model="form.title" type="text" placeholder="Titolo evento" />
          </div>

          <div class="cal-modal__field">
            <label>Descrizione</label>
            <textarea v-model="form.description" rows="3" placeholder="Descrizione (opzionale)" />
          </div>

          <div class="cal-modal__row">
            <div class="cal-modal__field">
              <label>Inizio</label>
              <input v-model="form.start" type="datetime-local" />
            </div>
            <div class="cal-modal__field">
              <label>Fine</label>
              <input v-model="form.end" type="datetime-local" />
            </div>
          </div>

          <div class="cal-modal__row">
            <div class="cal-modal__field">
              <label>Promemoria (minuti prima)</label>
              <input v-model.number="form.reminder_minutes" type="number" min="1" placeholder="Es. 15" />
            </div>
            <div class="cal-modal__field">
              <label>Ricorrenza (RRULE)</label>
              <select v-model="form.recurrence_rule">
                <option value="">Nessuna</option>
                <option value="FREQ=DAILY">Ogni giorno</option>
                <option value="FREQ=WEEKLY">Ogni settimana</option>
                <option value="FREQ=WEEKLY;BYDAY=MO,WE,FR">Lun/Mer/Ven</option>
                <option value="FREQ=MONTHLY">Ogni mese</option>
                <option value="FREQ=YEARLY">Ogni anno</option>
              </select>
            </div>
          </div>

          <div class="cal-modal__actions">
            <button v-if="editingEvent" class="cal-modal__btn cal-modal__btn--danger" :disabled="saving"
              @click="handleDelete">Elimina</button>
            <div class="cal-modal__spacer" />
            <button class="cal-modal__btn cal-modal__btn--secondary" @click="showModal = false">Annulla</button>
            <button class="cal-modal__btn cal-modal__btn--primary"
              :disabled="saving || !form.title || !form.start || !form.end" @click="handleSave">
              {{ saving ? 'Salvataggio...' : (editingEvent ? 'Aggiorna' : 'Crea') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.calendar {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
  color: var(--text-primary);
  overflow: hidden;
}

.calendar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  gap: 1rem;
  flex-shrink: 0;
}

.calendar__nav,
.calendar__mode {
  display: flex;
  gap: 0.25rem;
}

.calendar__title {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0;
  white-space: nowrap;
}

.calendar__btn {
  background: var(--glass-bg);
  color: var(--text-primary);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  padding: 0.35rem 0.7rem;
  cursor: pointer;
  font-size: 0.85rem;
  backdrop-filter: blur(var(--glass-blur));
  transition: all var(--transition-fast);
}

.calendar__btn:hover {
  background: var(--accent);
  color: #1a1a2e;
  box-shadow: var(--accent-glow);
}

.calendar__btn--active {
  background: var(--accent);
  border-color: var(--accent);
  color: #1a1a2e;
}

.calendar__loading,
.calendar__error,
.calendar__empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 2rem;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.calendar__error {
  color: #e94560;
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
  grid-template-columns: 3.5rem repeat(7, 1fr);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.calendar__day-label {
  text-align: center;
  padding: 0.4rem 0;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.calendar__day-label--today {
  color: var(--accent);
  font-weight: 700;
}

.calendar__day-num {
  margin-left: 0.25rem;
  font-weight: 600;
  color: var(--text-primary);
}

.calendar__day-label--today .calendar__day-num {
  background: var(--accent);
  border-radius: 50%;
  display: inline-block;
  width: 1.5rem;
  height: 1.5rem;
  line-height: 1.5rem;
  text-align: center;
  color: #1a1a2e;
}

.calendar__week-body {
  display: grid;
  grid-template-columns: 3.5rem repeat(7, 1fr);
  flex: 1;
  overflow-y: auto;
}

.calendar__time-gutter {
  display: flex;
  flex-direction: column;
}

.calendar__hour-label {
  height: 3.5rem;
  display: flex;
  align-items: flex-start;
  justify-content: flex-end;
  padding-right: 0.4rem;
  font-size: 0.7rem;
  color: var(--text-secondary);
}

.calendar__day-col {
  position: relative;
  border-left: 1px solid var(--border);
  cursor: pointer;
}

.calendar__day-col--today {
  background: rgba(201, 168, 76, 0.05);
}

.calendar__hour-slot {
  height: 3.5rem;
  border-bottom: 1px solid var(--border);
}

.calendar__event {
  position: absolute;
  border-radius: var(--radius-sm);
  padding: 0.15rem 0.3rem;
  font-size: 0.75rem;
  overflow: hidden;
  cursor: pointer;
  z-index: 1;
  color: #1a1a2e;
}

.calendar__event:hover {
  filter: brightness(1.2);
}

.calendar__event-time {
  opacity: 0.85;
  margin-right: 0.25rem;
}

.calendar__event-title {
  font-weight: 600;
}

.calendar__event-add {
  display: none;
  position: absolute;
  top: 1px;
  right: 1px;
  width: 1.1rem;
  height: 1.1rem;
  border-radius: 50%;
  background: rgba(26, 26, 46, 0.7);
  color: var(--accent);
  border: 1px solid var(--accent);
  font-size: 0.75rem;
  line-height: 1;
  cursor: pointer;
  z-index: 2;
  padding: 0;
  align-items: center;
  justify-content: center;
}

.calendar__event:hover .calendar__event-add {
  display: flex;
}

.calendar__event-add:hover {
  background: var(--accent);
  color: #1a1a2e;
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
  font-size: 0.8rem;
  color: var(--text-secondary);
  padding: 0.3rem 0;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
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
  padding: 0.25rem;
  cursor: pointer;
  min-height: 4rem;
  overflow: hidden;
}

.calendar__month-cell:hover {
  background: var(--bg-secondary);
}

.calendar__month-cell--today {
  background: rgba(201, 168, 76, 0.08);
}

.calendar__month-cell--dim {
  opacity: 0.4;
}

.calendar__month-date {
  font-size: 0.8rem;
  font-weight: 600;
}

.calendar__month-event {
  font-size: 0.7rem;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  margin-top: 0.15rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
  color: #1a1a2e;
}

.calendar__month-more {
  font-size: 0.65rem;
  color: var(--text-secondary);
}

/* Modal overlay */
.cal-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.cal-modal {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  width: 480px;
  max-width: 90vw;
  max-height: 85vh;
  overflow-y: auto;
  box-shadow: var(--shadow-lg, 0 20px 60px rgba(0, 0, 0, 0.5));
}

.cal-modal__title {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-4);
}

.cal-modal__recurrence-warn {
  font-size: 0.8rem;
  color: var(--accent);
  margin: 0 0 var(--space-3);
}

.cal-modal__error {
  font-size: 0.85rem;
  color: #e94560;
  margin: 0 0 var(--space-3);
  padding: var(--space-2);
  background: rgba(233, 69, 96, 0.1);
  border-radius: var(--radius-sm);
}

.cal-modal__field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
  flex: 1;
}

.cal-modal__field label {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.cal-modal__field input,
.cal-modal__field textarea,
.cal-modal__field select {
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: var(--space-2);
  color: var(--text-primary);
  font-size: var(--text-sm);
  outline: none;
  transition: border-color var(--transition-fast);
}

.cal-modal__field input:focus,
.cal-modal__field textarea:focus,
.cal-modal__field select:focus {
  border-color: var(--accent);
}

.cal-modal__row {
  display: flex;
  gap: var(--space-3);
}

.cal-modal__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

.cal-modal__spacer {
  flex: 1;
}

.cal-modal__btn {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: 500;
  cursor: pointer;
  border: 1px solid var(--border);
  transition: all var(--transition-fast);
}

.cal-modal__btn--primary {
  background: var(--accent);
  color: #1a1a2e;
  border-color: var(--accent);
}

.cal-modal__btn--primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.cal-modal__btn--primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.cal-modal__btn--secondary {
  background: transparent;
  color: var(--text-secondary);
}

.cal-modal__btn--secondary:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary);
}

.cal-modal__btn--danger {
  background: transparent;
  color: #e94560;
  border-color: rgba(233, 69, 96, 0.3);
}

.cal-modal__btn--danger:hover:not(:disabled) {
  background: rgba(233, 69, 96, 0.1);
}
</style>
