<script setup lang="ts">
/**
 * InboxList — Email list with search, filter, sender avatars, and relative dates.
 *
 * Features: search bar, all/unread filter, skeleton loading,
 * sender initials avatar, formatted dates, selected state, hover actions.
 */
import { ref, computed, watch, onUnmounted } from 'vue'
import { useEmailStore } from '../../stores/email'
import UiSkeleton from '../ui/UiSkeleton.vue'
import UiSegmented, { type UiSegmentedOption } from '../ui/UiSegmented.vue'
import AppIcon from '../ui/AppIcon.vue'

const emailStore = useEmailStore()

const searchQuery = ref('')
const filterMode = ref<'all' | 'unread'>('all')

/** Segmented filter options; the unread tab carries the unread-count badge. */
const filterOptions = computed<UiSegmentedOption[]>(() => {
  const unread: UiSegmentedOption = { value: 'unread', label: 'Non lette' }
  if (emailStore.unreadCount > 0) unread.badge = emailStore.unreadCount
  return [{ value: 'all', label: 'Tutte' }, unread]
})
let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(searchQuery, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    if (val.trim()) {
      emailStore.searchEmails({ query: val.trim(), folder: emailStore.currentFolder })
    } else {
      emailStore.fetchInbox(emailStore.currentFolder)
    }
  }, 400)
})

onUnmounted(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
})

const filteredInbox = computed(() => {
  if (filterMode.value === 'unread') {
    return emailStore.inbox.filter((e) => !e.is_read)
  }
  return emailStore.inbox
})

function isSelected(uid: string): boolean {
  return emailStore.currentEmail?.uid === uid
}

/** Extract sender display name from "Name <email>" format. */
function senderName(from: string): string {
  const match = from.match(/^"?([^"<]+)"?\s*</)
  return match ? match[1].trim() : from.split('@')[0]
}

/** First letter of sender name for avatar. */
function senderInitial(from: string): string {
  const name = senderName(from)
  return name.charAt(0).toUpperCase()
}

/** Format date to relative italian time. */
function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return dateStr
  const now = Date.now()
  const diff = now - date.getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'ora'
  if (mins < 60) return `${mins}m`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}g`
  return date.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })
}

/** First ~60 chars of subject as preview, or "(nessun oggetto)". */
function subjectPreview(subject: string): string {
  if (!subject?.trim()) return '(nessun oggetto)'
  return subject.length > 60 ? subject.slice(0, 60) + '…' : subject
}
</script>

<template>
  <div class="inbox">
    <!-- Search bar -->
    <div class="inbox__search">
      <div class="inbox__search-wrapper">
        <AppIcon class="inbox__search-icon" name="search" />
        <input v-model="searchQuery" type="text" class="inbox__search-input" placeholder="Cerca email…" />
      </div>
    </div>

    <!-- Toolbar: count + filters + refresh -->
    <div class="inbox__toolbar">
      <UiSegmented size="sm" :equal="false" :model-value="filterMode" :options="filterOptions"
        aria-label="Filtro email" @update:model-value="(v) => filterMode = v as 'all' | 'unread'" />
      <button class="inbox__refresh" :disabled="emailStore.loading"
        :class="{ 'inbox__refresh--spinning': emailStore.loading }" title="Aggiorna"
        @click="emailStore.fetchInbox(emailStore.currentFolder)">
        <AppIcon name="refresh-ccw" />
      </button>
    </div>

    <!-- Loading skeletons -->
    <div v-if="emailStore.loading && emailStore.inbox.length === 0" class="inbox__skeletons">
      <div v-for="i in 6" :key="i" class="inbox__skeleton-item">
        <UiSkeleton width="36px" height="36px" circle />
        <div class="inbox__skeleton-lines">
          <UiSkeleton :width="i % 2 === 0 ? '60%' : '80%'" height="12px" />
          <UiSkeleton :width="i % 3 === 0 ? '90%' : '70%'" height="10px" />
        </div>
      </div>
    </div>

    <!-- Error state -->
    <div v-else-if="emailStore.error" class="inbox__state">
      <AppIcon class="inbox__state-icon inbox__state-icon--error" name="alert-circle" :stroke-width="1.5" />
      <span class="inbox__state-text inbox__state-text--error">{{ emailStore.error }}</span>
    </div>

    <!-- Empty state -->
    <div v-else-if="filteredInbox.length === 0" class="inbox__state">
      <AppIcon class="inbox__state-icon" name="inbox" :stroke-width="1.2" />
      <span class="inbox__state-text">
        {{ filterMode === 'unread' ? 'Nessuna email non letta' : 'Nessuna email' }}
      </span>
    </div>

    <!-- Email list -->
    <div v-else class="inbox__list">
      <button v-for="mail in filteredInbox" :key="mail.uid" class="inbox__item" :class="{
        'inbox__item--unread': !mail.is_read,
        'inbox__item--selected': isSelected(mail.uid),
      }" @click="emailStore.fetchEmail(mail.uid, emailStore.currentFolder)">
        <!-- Unread dot -->
        <span v-if="!mail.is_read" class="inbox__unread-dot" />

        <!-- Avatar -->
        <span class="inbox__avatar" :class="{ 'inbox__avatar--unread': !mail.is_read }">
          {{ senderInitial(mail.from) }}
        </span>

        <!-- Content -->
        <div class="inbox__content">
          <div class="inbox__row-top">
            <span class="inbox__sender" :class="{ 'inbox__sender--unread': !mail.is_read }">
              {{ senderName(mail.from) }}
            </span>
            <span class="inbox__date">{{ formatDate(mail.date) }}</span>
          </div>
          <div class="inbox__subject" :class="{ 'inbox__subject--unread': !mail.is_read }">
            {{ subjectPreview(mail.subject) }}
          </div>
        </div>
      </button>
    </div>
  </div>
</template>

<style scoped>
.inbox {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--surface-0);
}

/* ── Search ──────────────────────────── */
.inbox__search {
  padding: var(--space-3);
  border-bottom: 1px solid var(--border);
}

.inbox__search-wrapper {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-3);
  height: 32px;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.inbox__search-wrapper:focus-within {
  border-color: var(--accent-border);
  box-shadow: 0 0 0 2px var(--accent-faint);
}

.inbox__search-icon {
  width: 14px;
  height: 14px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.inbox__search-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
}

.inbox__search-input::placeholder {
  color: var(--text-muted);
}

/* ── Toolbar ─────────────────────────── */
.inbox__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  border-bottom: 1px solid var(--border);
}

.inbox__refresh {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background-color var(--transition-fast), color var(--transition-fast);
}

.inbox__refresh:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.inbox__refresh:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.inbox__refresh svg {
  width: 15px;
  height: 15px;
}

.inbox__refresh--spinning svg {
  animation: spin-refresh 1s linear infinite;
}

@keyframes spin-refresh {
  to {
    transform: rotate(360deg);
  }
}

/* ── Skeleton loading ────────────────── */
.inbox__skeletons {
  padding: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.inbox__skeleton-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.inbox__skeleton-lines {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* ── Empty / Error states ────────────── */
.inbox__state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-8);
}

.inbox__state-icon {
  width: 40px;
  height: 40px;
  color: var(--text-muted);
  opacity: 0.5;
}

.inbox__state-icon--error {
  color: var(--danger);
  opacity: 0.7;
}

.inbox__state-text {
  font-size: var(--text-sm);
  color: var(--text-muted);
  text-align: center;
}

.inbox__state-text--error {
  color: var(--danger);
}

/* ── Email list ──────────────────────── */
.inbox__list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.inbox__item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: none;
  border-bottom: 1px solid var(--border);
  background: transparent;
  cursor: pointer;
  text-align: left;
  font-family: var(--font-sans);
  position: relative;
  transition: background-color var(--transition-fast);
}

.inbox__item:hover {
  background: var(--surface-hover);
}

.inbox__item--selected {
  background: var(--surface-selected);
}

.inbox__item--selected::after {
  content: '';
  position: absolute;
  right: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  background: var(--accent);
  border-radius: var(--radius-pill);
}

/* ── Unread dot ──────────────────────── */
.inbox__unread-dot {
  position: absolute;
  left: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 6px;
  height: 6px;
  background: var(--accent);
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

/* ── Avatar ──────────────────────────── */
.inbox__avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  min-width: 36px;
  border-radius: var(--radius-full);
  background: var(--surface-3);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  flex-shrink: 0;
}

.inbox__avatar--unread {
  background: var(--accent-dim);
  color: var(--accent);
}

/* ── Content ─────────────────────────── */
.inbox__content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
}

.inbox__row-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.inbox__sender {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.inbox__sender--unread {
  color: var(--text-primary);
  font-weight: var(--weight-semibold);
}

.inbox__date {
  font-size: var(--text-xs);
  color: var(--text-muted);
  flex-shrink: 0;
  white-space: nowrap;
}

.inbox__subject {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--leading-snug);
}

.inbox__subject--unread {
  color: var(--text-primary);
  font-weight: var(--weight-medium);
}
</style>
