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
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                <line x1="16" y1="2" x2="16" y2="6" />
                <line x1="8" y1="2" x2="8" y2="6" />
                <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
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
        <!-- Section label (same style as "Conversazioni") -->
        <div class="cal-widget__section-label">
            <span>Calendario</span>
        </div>

        <!-- Header: icon + date + badge + chevron -->
        <div class="cal-widget__header" @click="toggleExpanded">
            <span class="cal-widget__icon" aria-hidden="true">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                    <line x1="16" y1="2" x2="16" y2="6" />
                    <line x1="8" y1="2" x2="8" y2="6" />
                    <line x1="3" y1="10" x2="21" y2="10" />
                </svg>
            </span>
            <span class="cal-widget__date">{{ formattedDate }}</span>
            <span v-if="store.todayCount > 0" class="cal-widget__badge">
                {{ store.todayCount }}
            </span>
            <button class="cal-widget__open-btn" title="Apri calendario" @click.stop="openCalendar">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                    <polyline points="15 3 21 3 21 9" />
                    <line x1="10" y1="14" x2="21" y2="3" />
                </svg>
            </button>
            <span class="cal-widget__chevron" :class="{ 'cal-widget__chevron--open': expanded }" aria-hidden="true">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
                    stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="6 9 12 15 18 9" />
                </svg>
            </span>
        </div>

        <!-- Next event preview (when list is collapsed) -->
        <div v-if="!expanded && store.nextEvent" class="cal-widget__next">
            <span class="cal-widget__next-time">{{ formatTime(store.nextEvent.start_time) }}</span>
            <span class="cal-widget__next-title">{{ store.nextEvent.title }}</span>
            <span class="cal-widget__next-rel">{{ nextEventRelative }}</span>
        </div>

        <!-- Expanded event list -->
        <transition name="cal-expand">
            <div v-if="expanded" class="cal-widget__list">
                <div v-if="!store.todaySummary?.events.length" class="cal-widget__empty">
                    Nessun evento oggi
                </div>
                <div v-for="event in store.todaySummary?.events"
                    :key="event.occurrence_date ? `${event.id}_${event.occurrence_date}` : event.id"
                    class="cal-widget__event">
                    <span class="cal-widget__event-time">{{ formatTime(event.start_time) }}</span>
                    <span class="cal-widget__event-title">{{ event.title }}</span>
                </div>
            </div>
        </transition>
    </div>
</template>

<style scoped>
/* ═══════════════════════════════════════════════════════════
   CalendarWidget — Sidebar calendar widget
   ═══════════════════════════════════════════════════════════ */

/* ------------------------------------------------- Root */
.cal-widget {
    position: relative;
    z-index: 1;
    flex-shrink: 0;
}

/* ------------------------------------------------- Section label
   Mirrors .sidebar__section-label from AppSidebar */
.cal-widget__section-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) 14px var(--space-1);
    font-size: var(--text-2xs);
    font-weight: var(--weight-bold);
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-muted);
}

.cal-widget__section-label::after {
    content: '';
    flex: 1;
    height: var(--space-px);
    background: linear-gradient(90deg, var(--border) 0%, transparent 100%);
}

/* ------------------------------------------------- Header */
.cal-widget__header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1-5) 14px;
    cursor: pointer;
    border-radius: var(--radius-md);
    margin: 0 var(--space-1);
    transition:
        background var(--transition-fast),
        color var(--transition-fast);
}

.cal-widget__header:hover {
    background: rgba(255, 255, 255, 0.04);
}

.cal-widget__header:active {
    transform: scale(0.98);
}

/* ------------------------------------------------- Icon */
.cal-widget__icon {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: var(--text-muted);
    opacity: var(--opacity-soft);
    transition: opacity var(--transition-fast);
}

.cal-widget__header:hover .cal-widget__icon {
    opacity: 1;
}

/* ------------------------------------------------- Date */
.cal-widget__date {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex: 1;
    min-width: 0;
}

/* ------------------------------------------------- Badge (event count) */
.cal-widget__badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    border-radius: var(--radius-full, 9999px);
    background: var(--accent);
    color: #1a1a2e;
    font-size: var(--text-2xs);
    font-weight: var(--weight-bold);
    line-height: 1;
    flex-shrink: 0;
}

/* ------------------------------------------------- Open calendar button */
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
    flex-shrink: 0;
    transition: color var(--transition-fast), background var(--transition-fast);
}

.cal-widget__open-btn:hover {
    color: var(--accent);
    background: rgba(255, 255, 255, 0.05);
}

/* ------------------------------------------------- Chevron */
.cal-widget__chevron {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: var(--text-muted);
    transition: transform var(--transition-fast);
}

.cal-widget__chevron--open {
    transform: rotate(180deg);
}

/* ------------------------------------------------- Next event preview */
.cal-widget__next {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) 14px var(--space-1-5);
    margin: 0 var(--space-1);
}

.cal-widget__next-time {
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    color: var(--accent);
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
}

.cal-widget__next-title {
    font-size: var(--text-xs);
    color: var(--text-primary);
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
}

/* ------------------------------------------------- Expanded event list */
.cal-widget__list {
    max-height: 150px;
    overflow-y: auto;
    padding: var(--space-1) 0 var(--space-2);
    margin: 0 var(--space-1);
}

/* Thin custom scrollbar */
.cal-widget__list::-webkit-scrollbar {
    width: 3px;
}

.cal-widget__list::-webkit-scrollbar-track {
    background: transparent;
}

.cal-widget__list::-webkit-scrollbar-thumb {
    background: var(--glass-border);
    border-radius: var(--radius-full, 9999px);
}

/* ------------------------------------------------- Event row */
.cal-widget__event {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-1) 14px;
    border-radius: var(--radius-sm);
    transition: background var(--transition-fast);
}

.cal-widget__event:hover {
    background: rgba(255, 255, 255, 0.03);
}

.cal-widget__event-time {
    font-size: var(--text-xs);
    font-weight: var(--weight-medium);
    color: var(--text-muted);
    flex-shrink: 0;
    min-width: 38px;
    font-variant-numeric: tabular-nums;
}

.cal-widget__event-title {
    font-size: var(--text-xs);
    color: var(--text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
}

/* ------------------------------------------------- Empty state */
.cal-widget__empty {
    padding: var(--space-2) 14px;
    font-size: var(--text-xs);
    color: var(--text-muted);
    font-style: italic;
}

/* ------------------------------------------------- Expand/collapse transition */
.cal-expand-enter-active,
.cal-expand-leave-active {
    transition:
        max-height 0.25s cubic-bezier(0.4, 0, 0.2, 1),
        opacity 0.2s ease;
    overflow: hidden;
}

.cal-expand-enter-from,
.cal-expand-leave-to {
    max-height: 0;
    opacity: 0;
}

.cal-expand-enter-to,
.cal-expand-leave-from {
    max-height: 150px;
    opacity: 1;
}

/* ═══════════════════════════════════════════════════════════
   Collapsed mode — icon-only circular button
   ═══════════════════════════════════════════════════════════ */
.cal-widget--collapsed {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: var(--space-1) 0;
    cursor: pointer;
}

.cal-widget__mini-time {
    font-size: 0.6rem;
    color: var(--text-muted);
    text-align: center;
    line-height: 1;
    white-space: nowrap;
}

.cal-widget__icon-btn {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 34px;
    height: 34px;
    border-radius: var(--radius-full, 9999px);
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

/* Mini badge — positioned top-right of icon circle */
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
    border-radius: var(--radius-full, 9999px);
    background: var(--accent);
    color: #1a1a2e;
    font-size: 9px;
    font-weight: var(--weight-bold);
    line-height: 1;
    pointer-events: none;
}

/* ------------------------------------------------- Reduced motion */
@media (prefers-reduced-motion: reduce) {

    .cal-widget__header,
    .cal-widget__icon,
    .cal-widget__chevron,
    .cal-widget__event,
    .cal-widget__icon-btn,
    .cal-expand-enter-active,
    .cal-expand-leave-active {
        transition: none;
    }
}
</style>
