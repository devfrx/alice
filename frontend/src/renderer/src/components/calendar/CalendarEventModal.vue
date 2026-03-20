<script setup lang="ts">
/**
 * CalendarEventModal — Form content for creating/editing calendar events.
 *
 * Rendered inside the UiModal shell via `useModal().openCustom()`.
 * Emits `'close'` with `true` (saved/deleted) or `false` (cancelled).
 */
import { ref } from 'vue'
import { api } from '../../services/api'
import { useCalendarStore } from '../../stores/calendar'
import { useModal } from '../../composables/useModal'
import type { CalendarEvent, EventFormData } from '../../composables/useCalendar'

interface CalendarEventModalProps {
  /** The existing event being edited, or null for create mode. */
  editingEvent: CalendarEvent | null
  /** Pre-filled form data. */
  initialForm: EventFormData
}

const props = defineProps<CalendarEventModalProps>()
const emit = defineEmits<{ close: [result: boolean] }>()

const calendarStore = useCalendarStore()
const { confirm: modalConfirm } = useModal()

const form = ref<EventFormData>({ ...props.initialForm })
const saveError = ref<string | null>(null)
const saving = ref(false)

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
    if (props.editingEvent) {
      const updatePayload: Record<string, unknown> = {}
      if (payload.title !== undefined) updatePayload.title = payload.title
      if (payload.description !== undefined) updatePayload.description = payload.description
      if (payload.start !== undefined) updatePayload.start_time = payload.start
      if (payload.end !== undefined) updatePayload.end_time = payload.end
      if (payload.reminder_minutes !== undefined) updatePayload.reminder_minutes = payload.reminder_minutes
      if (payload.recurrence_rule !== undefined) updatePayload.recurrence_rule = payload.recurrence_rule
      await api.updateCalendarEvent(props.editingEvent.id, updatePayload)
    } else {
      await api.createCalendarEvent({
        title: payload.title,
        description: payload.description || undefined,
        start_time: payload.start,
        end_time: payload.end,
        reminder_minutes: payload.reminder_minutes ?? undefined,
        recurrence_rule: payload.recurrence_rule || undefined,
      })
    }
    await calendarStore.refresh()
    emit('close', true)
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : 'Salvataggio fallito'
  } finally {
    saving.value = false
  }
}

async function handleDelete(): Promise<void> {
  if (!props.editingEvent) return
  const confirmed = await modalConfirm({
    title: 'Elimina evento',
    message: props.editingEvent.recurrence_rule
      ? 'Eliminare questo evento e tutte le occorrenze? Azione irreversibile.'
      : 'Eliminare questo evento? Azione irreversibile.',
    type: 'danger',
    confirmText: 'Elimina',
  })
  if (!confirmed) return
  saving.value = true
  saveError.value = null
  try {
    await api.deleteCalendarEvent(props.editingEvent.id)
    await calendarStore.refresh()
    emit('close', true)
  } catch (err) {
    saveError.value = err instanceof Error ? err.message : 'Eliminazione fallita'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="event-form">
    <p v-if="editingEvent?.recurrence_rule" class="event-form__warn">
      Attenzione: le modifiche verranno applicate a tutte le occorrenze.
    </p>
    <p v-if="saveError" class="event-form__error">{{ saveError }}</p>

    <div class="event-form__field">
      <label>Titolo</label>
      <input v-model="form.title" type="text" placeholder="Titolo evento" />
    </div>

    <div class="event-form__field">
      <label>Descrizione</label>
      <textarea v-model="form.description" rows="3" placeholder="Descrizione (opzionale)" />
    </div>

    <div class="event-form__row">
      <div class="event-form__field">
        <label>Inizio</label>
        <input v-model="form.start" type="datetime-local" />
      </div>
      <div class="event-form__field">
        <label>Fine</label>
        <input v-model="form.end" type="datetime-local" />
      </div>
    </div>

    <div class="event-form__row">
      <div class="event-form__field">
        <label>Promemoria (minuti prima)</label>
        <input v-model.number="form.reminder_minutes" type="number" min="1" placeholder="Es. 15" />
      </div>
      <div class="event-form__field">
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

    <div class="event-form__actions">
      <button v-if="editingEvent" class="event-form__btn event-form__btn--danger" :disabled="saving"
        @click="handleDelete">Elimina</button>
      <div class="event-form__spacer" />
      <button class="event-form__btn event-form__btn--secondary" @click="emit('close', false)">Annulla</button>
      <button class="event-form__btn event-form__btn--primary"
        :disabled="saving || !form.title || !form.start || !form.end" @click="handleSave">
        {{ saving ? 'Salvataggio...' : (editingEvent ? 'Aggiorna' : 'Crea') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.event-form {
  display: flex;
  flex-direction: column;
}

.event-form__warn {
  font-size: 0.8rem;
  color: var(--accent);
  margin: 0 0 var(--space-3);
}

.event-form__error {
  font-size: 0.85rem;
  color: var(--danger);
  margin: 0 0 var(--space-3);
  padding: var(--space-2);
  background: var(--danger-light);
  border-radius: var(--radius-sm);
}

.event-form__field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-bottom: var(--space-3);
  flex: 1;
}

.event-form__field label {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.event-form__field input,
.event-form__field textarea,
.event-form__field select {
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-2);
  color: var(--text-primary);
  font-size: var(--text-sm);
  outline: none;
  transition: border-color var(--transition-fast);
}

.event-form__field input:focus,
.event-form__field textarea:focus,
.event-form__field select:focus {
  border-color: var(--accent-border);
}

.event-form__row {
  display: flex;
  gap: var(--space-3);
}

.event-form__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

.event-form__spacer {
  flex: 1;
}

.event-form__btn {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  border: 1px solid var(--border);
  transition: all var(--transition-fast);
}

.event-form__btn--primary {
  background: var(--accent);
  color: var(--surface-0);
  border-color: var(--accent);
}

.event-form__btn--primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.event-form__btn--primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.event-form__btn--secondary {
  background: transparent;
  color: var(--text-secondary);
}

.event-form__btn--secondary:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.event-form__btn--danger {
  background: transparent;
  color: var(--danger);
  border-color: var(--danger-border);
}

.event-form__btn--danger:hover:not(:disabled) {
  background: var(--danger-light);
}
</style>
