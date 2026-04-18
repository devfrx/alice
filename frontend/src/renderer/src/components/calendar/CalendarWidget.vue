<script setup lang="ts">
/**
 * CalendarWidget — Sidebar widget showing today's events and next upcoming event.
 *
 * Expanded mode: date header, next-event preview, expandable event list.
 * Collapsed mode: calendar icon with event count badge (34x34 circle).
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useCalendarStore } from '../../stores/calendar'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{
    collapsed: boolean
}>()

const store = useCalendarStore()
const router = useRouter()
const expanded = ref(false)

/** Relative time until next event (e.g. "tra 2h 15min"). */
const nextEventRelative = computed((): string => {
    if (!store.nextEvent) return ''
    const diff = new Date(store.nextEvent.start_time).getTime() - Date.now()
    if (diff < 0) return 'in corso'
    const mins = Math.round(diff / 60000)
    if (mins < 60) return `tra ${mins}min`
    const hours = Math.floor(mins / 60)
    if (hours < 24) {
        const rem = mins % 60
        return rem > 0 ? `tra ${hours}h ${rem}min` : `tra ${hours}h`
    }
    return `tra ${Math.floor(hours / 24)}g`
})

/** Italian day names (title-case). */
const DAYS_IT = [
    'Domenica', 'Lunedì', 'Martedì', 'Mercoledì',
    'Giovedì', 'Venerdì', 'Sabato',
] as const

/** Italian abbreviated month names. */
const MONTHS_IT = [
    'Gen', 'Feb', 'Mar', 'Apr', 'Mag', 'Giu',
    'Lug', 'Ago', 'Set', 'Ott', 'Nov', 'Dic',
] as const

/** Format today's date as "Mercoledi 15 Gen". */
const formattedDate = computed((): string => {
    const now = new Date()
    const day = DAYS_IT[now.getDay()]
    const date = now.getDate()
    const month = MONTHS_IT[now.getMonth()]
    return `${day} ${date} ${month}`
})

/** Extract HH:MM from an ISO 8601 datetime string. */
function formatTime(iso: string): string {
    const d = new Date(iso)
    return d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
}

/** Tooltip for collapsed mode. */
const tooltipText = computed((): string => {
    const count = store.todayCount
    if (count === 0) return 'Nessun evento oggi'
    return count === 1 ? '1 evento oggi' : `${count} eventi oggi`
})

function toggleExpanded(): void {
    expanded.value = !expanded.value
}

function openCalendar(): void {
    router.push('/calendar')
}

onMounted(() => {
    store.startPolling()
})

onUnmounted(() => {
    store.stopPolling()
})
</script>

<template>
    <!-- Collapsed sidebar mode — icon + badge only -->
    <div v-if="props.collapsed" class="cal-widget cal-widget--collapsed" :title="tooltipText">
        <div class="cal-widget__icon-btn" @click="openCalendar">
            <AppIcon name="calendar" :size="16" />
            <span v-if="store.todayCount > 0" class="cal-widget__mini-badge">
                {{ store.todayCount }}
            </span>
        </div>
        <span v-if="store.nextEvent" class="cal-widget__mini-time">
            {{ formatTime(store.nextEvent.start_time) }}
        </span>
    </div>

    <!-- Expanded sidebar mode — full widget -->
    <div v-else class="cal-widget">
        <!-- Header row: date + event count + open link -->
        <div class="cal-widget__header" @click="toggleExpanded">
            <div class="cal-widget__header-left">
                <span class="cal-widget__day">{{ formattedDate }}</span>
                <span v-if="store.todayCount > 0" class="cal-widget__count">
                    {{ store.todayCount }} {{ store.todayCount === 1 ? 'evento' : 'eventi' }}
                </span>
                <span v-else class="cal-widget__count cal-widget__count--empty">nessun evento</span>
            </div>
            <div class="cal-widget__header-right">
                <button class="cal-widget__open-btn" title="Apri calendario" @click.stop="openCalendar">
                    <AppIcon name="external-link" :size="11" />
                </button>
                <span class="cal-widget__chevron" :class="{ 'cal-widget__chevron--open': expanded }">
                    <AppIcon name="chevron-down" :size="11" />
                </span>
            </div>
        </div>

        <!-- Next event pill (when collapsed) -->
        <Transition name="cal-next">
            <div v-if="!expanded && store.nextEvent" class="cal-widget__next">
                <span class="cal-widget__next-dot" />
                <span class="cal-widget__next-time">{{ formatTime(store.nextEvent.start_time) }}</span>
                <span class="cal-widget__next-title">{{ store.nextEvent.title }}</span>
                <span class="cal-widget__next-rel">{{ nextEventRelative }}</span>
            </div>
        </Transition>

        <!-- Expanded full list -->
        <Transition name="cal-expand">
            <div v-if="expanded" class="cal-widget__list">
                <div v-if="!store.todaySummary?.events.length" class="cal-widget__empty">
                    Nessun evento oggi
                </div>
                <div v-for="event in store.todaySummary?.events"
                    :key="event.occurrence_date ? `${event.id}_${event.occurrence_date}` : event.id"
                    class="cal-widget__event">
                    <span class="cal-widget__event-dot" />
                    <span class="cal-widget__event-time">{{ formatTime(event.start_time) }}</span>
                    <span class="cal-widget__event-title">{{ event.title }}</span>
                </div>
            </div>
        </Transition>
    </div>
</template>

<style scoped>
/* ── CalendarWidget — minimal sidebar design ── */

.cal-widget {
    flex-shrink: 0;
    margin: 0 var(--space-3) var(--space-2);
    border-radius: var(--radius-md);
    border: 1px solid var(--glass-border);
    background: var(--surface-2);
    overflow: hidden;
}

/* ── Header ───────────────────────────────────────────────── */
.cal-widget__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-2) var(--space-2-5);
    cursor: pointer;
    transition: background var(--transition-fast);
    user-select: none;
}

.cal-widget__header:hover {
    background: var(--surface-hover);
}

.cal-widget__header:active {
    background: var(--surface-active);
}

.cal-widget__header-left {
    display: flex;
    align-items: baseline;
    gap: var(--space-1-5);
    min-width: 0;
    overflow: hidden;
}

.cal-widget__header-right {
    display: flex;
    align-items: center;
    gap: 2px;
    flex-shrink: 0;
}

.cal-widget__day {
    font-size: var(--text-xs);
    font-weight: var(--weight-semibold);
    color: var(--text-secondary);
    white-space: nowrap;
}

.cal-widget__count {
    font-size: var(--text-2xs);
    color: var(--accent);
    white-space: nowrap;
    flex-shrink: 0;
}

.cal-widget__count--empty {
    color: var(--text-muted);
    opacity: 0.6;
}

/* ── Open + chevron buttons ───────────────────────────────── */
.cal-widget__open-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: var(--radius-sm);
    border: none;
    background: transparent;
    color: var(--text-muted);
    cursor: pointer;
    opacity: 0;
    transition:
        opacity var(--transition-fast),
        color var(--transition-fast),
        background var(--transition-fast);
}

.cal-widget__header:hover .cal-widget__open-btn {
    opacity: 1;
}

.cal-widget__open-btn:hover {
    color: var(--accent);
    background: var(--surface-hover);
}

.cal-widget__chevron {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    color: var(--text-muted);
    transition: transform var(--transition-fast);
}

.cal-widget__chevron--open {
    transform: rotate(180deg);
}

/* ── Next event pill ──────────────────────────────────────── */
.cal-widget__next {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: 0 var(--space-2-5) var(--space-2);
}

.cal-widget__next-dot {
    width: 5px;
    height: 5px;
    border-radius: var(--radius-full);
    background: var(--accent);
    flex-shrink: 0;
    box-shadow: 0 0 5px var(--accent-glow);
}

.cal-widget__next-time {
    font-size: var(--text-2xs);
    font-weight: var(--weight-semibold);
    color: var(--text-secondary);
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
}

.cal-widget__next-title {
    font-size: var(--text-2xs);
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
    flex: 1;
}

.cal-widget__next-rel {
    font-size: var(--text-2xs);
    color: var(--text-muted);
    flex-shrink: 0;
    white-space: nowrap;
    opacity: 0.7;
}

/* ── Expanded event list ──────────────────────────────────── */
.cal-widget__list {
    max-height: 140px;
    overflow-y: auto;
    padding: 0 0 6px;
    border-top: 1px solid var(--glass-border);
}

.cal-widget__list::-webkit-scrollbar {
    width: 2px;
}

.cal-widget__list::-webkit-scrollbar-track {
    background: transparent;
}

.cal-widget__list::-webkit-scrollbar-thumb {
    background: var(--glass-border);
    border-radius: var(--radius-full);
}

/* ── Event row ────────────────────────────────────────────── */
.cal-widget__event {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2-5);
    transition: background var(--transition-fast);
}

.cal-widget__event:hover {
    background: var(--surface-hover);
}

.cal-widget__event-dot {
    width: 4px;
    height: 4px;
    border-radius: var(--radius-full);
    background: var(--text-muted);
    flex-shrink: 0;
    opacity: 0.6;
}

.cal-widget__event-time {
    font-size: var(--text-2xs);
    font-weight: var(--weight-medium);
    color: var(--text-muted);
    flex-shrink: 0;
    min-width: 34px;
    font-variant-numeric: tabular-nums;
}

.cal-widget__event-title {
    font-size: var(--text-2xs);
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}

/* ── Empty state ──────────────────────────────────────────── */
.cal-widget__empty {
    padding: var(--space-2) var(--space-2-5);
    font-size: var(--text-2xs);
    color: var(--text-muted);
    font-style: italic;
    border-top: 1px solid var(--glass-border);
}

/* ── Transitions ──────────────────────────────────────────── */
.cal-expand-enter-active,
.cal-expand-leave-active {
    transition:
        max-height 0.22s cubic-bezier(0.4, 0, 0.2, 1),
        opacity 0.18s ease;
    overflow: hidden;
}

.cal-expand-enter-from,
.cal-expand-leave-to {
    max-height: 0;
    opacity: 0;
}

.cal-expand-enter-to,
.cal-expand-leave-from {
    max-height: 140px;
    opacity: 1;
}

.cal-next-enter-active,
.cal-next-leave-active {
    transition: opacity 0.15s ease, transform 0.15s ease;
}

.cal-next-enter-from,
.cal-next-leave-to {
    opacity: 0;
    transform: translateY(-4px);
}

/* ══ Collapsed mode ══════════════════════════════════════════ */
.cal-widget--collapsed {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--space-1) 0;
    cursor: pointer;
}

.cal-widget__icon-btn {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: var(--radius-full);
    color: var(--text-secondary);
    cursor: pointer;
    transition:
        background var(--transition-fast),
        color var(--transition-fast);
}

.cal-widget__icon-btn:hover {
    background: rgba(255, 255, 255, 0.04);
    color: var(--text-primary);
}

.cal-widget__mini-badge {
    position: absolute;
    top: 1px;
    right: 1px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 14px;
    height: 14px;
    padding: 0 3px;
    border-radius: var(--radius-full);
    background: var(--accent);
    color: var(--bg-primary);
    font-size: 0.6rem;
    font-weight: 700;
    line-height: 1;
}

.cal-widget__mini-time {
    font-size: 0.6rem;
    color: var(--text-muted);
    text-align: center;
    line-height: 1;
    white-space: nowrap;
}
</style>
