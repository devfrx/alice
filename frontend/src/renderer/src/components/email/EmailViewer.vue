<script setup lang="ts">
/**
 * EmailViewer — Full email detail view with structured header,
 * action toolbar, sender avatar, and formatted body.
 */
import { useEmailStore } from '../../stores/email'

const emailStore = useEmailStore()

async function handleArchive(): Promise<void> {
  if (!emailStore.currentEmail) return
  await emailStore.archiveEmail(
    emailStore.currentEmail.uid,
    emailStore.currentFolder,
  )
}

async function handleMarkRead(read: boolean): Promise<void> {
  if (!emailStore.currentEmail) return
  await emailStore.markRead(
    emailStore.currentEmail.uid,
    read,
    emailStore.currentFolder,
  )
}

/** Extract display name from "Name <email>" format. */
function senderName(from: string): string {
  const match = from.match(/^"?([^"<]+)"?\s*</)
  return match ? match[1].trim() : from.split('@')[0]
}

/** Extract email address from "Name <email>" format. */
function senderEmail(from: string): string {
  const match = from.match(/<([^>]+)>/)
  return match ? match[1] : from
}

/** First letter for avatar. */
function senderInitial(from: string): string {
  return senderName(from).charAt(0).toUpperCase()
}

/** Human-readable date in Italian. */
function formatFullDate(dateStr: string): string {
  const date = new Date(dateStr)
  if (isNaN(date.getTime())) return dateStr
  return date.toLocaleDateString('it-IT', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
</script>

<template>
  <div v-if="emailStore.currentEmail" class="viewer">
    <!-- Top action bar -->
    <div class="viewer__topbar">
      <button class="viewer__topbar-btn" title="Chiudi" @click="emailStore.clearCurrentEmail()">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="19" y1="12" x2="5" y2="12" />
          <polyline points="12 19 5 12 12 5" />
        </svg>
      </button>

      <div class="viewer__topbar-actions">
        <button
          class="viewer__topbar-btn"
          :title="emailStore.currentEmail.is_read ? 'Segna come non letta' : 'Segna come letta'"
          @click="handleMarkRead(!emailStore.currentEmail?.is_read)"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <template v-if="emailStore.currentEmail.is_read">
              <path d="M22 13V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h9" />
              <polyline points="22 6 12 13 2 6" />
              <circle cx="19" cy="19" r="3" fill="var(--accent)" stroke="var(--accent)" />
            </template>
            <template v-else>
              <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
              <polyline points="22 6 12 13 2 6" />
            </template>
          </svg>
        </button>

        <button
          class="viewer__topbar-btn viewer__topbar-btn--accent"
          title="Archivia"
          @click="handleArchive"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <polyline points="21 8 21 21 3 21 3 8" />
            <rect x="1" y="3" width="22" height="5" />
            <line x1="10" y1="12" x2="14" y2="12" />
          </svg>
        </button>
      </div>
    </div>

    <!-- Header with avatar and metadata -->
    <div class="viewer__header">
      <div class="viewer__subject">
        {{ emailStore.currentEmail.subject || '(nessun oggetto)' }}
      </div>

      <div class="viewer__sender-row">
        <span class="viewer__avatar">
          {{ senderInitial(emailStore.currentEmail.from) }}
        </span>
        <div class="viewer__sender-info">
          <div class="viewer__sender-name">
            {{ senderName(emailStore.currentEmail.from) }}
          </div>
          <div class="viewer__sender-email">
            {{ senderEmail(emailStore.currentEmail.from) }}
          </div>
        </div>
        <div class="viewer__date">
          {{ formatFullDate(emailStore.currentEmail.date) }}
        </div>
      </div>

      <!-- Recipients -->
      <div class="viewer__recipients">
        <div class="viewer__recipient-row">
          <span class="viewer__recipient-label">A:</span>
          <span class="viewer__recipient-value">{{ emailStore.currentEmail.to }}</span>
        </div>
        <div v-if="emailStore.currentEmail.cc" class="viewer__recipient-row">
          <span class="viewer__recipient-label">Cc:</span>
          <span class="viewer__recipient-value">{{ emailStore.currentEmail.cc }}</span>
        </div>
      </div>

      <!-- Attachment badge -->
      <div v-if="emailStore.currentEmail.has_attachments" class="viewer__attachment-badge">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" width="14" height="14">
          <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
        </svg>
        <span>Allegati presenti</span>
      </div>
    </div>

    <!-- Body -->
    <div class="viewer__body-wrapper">
      <div class="viewer__body">{{ emailStore.currentEmail.body }}</div>
    </div>
  </div>
</template>

<style scoped>
.viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* ── Top action bar ──────────────────── */
.viewer__topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-4);
  border-bottom: 1px solid var(--border);
  background: var(--surface-0);
  flex-shrink: 0;
}

.viewer__topbar-actions {
  display: flex;
  gap: var(--space-1);
}

.viewer__topbar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition:
    background-color var(--transition-fast),
    color var(--transition-fast),
    border-color var(--transition-fast);
}

.viewer__topbar-btn svg {
  width: 16px;
  height: 16px;
}

.viewer__topbar-btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.viewer__topbar-btn--accent:hover {
  background: var(--accent-dim);
  color: var(--accent);
  border-color: var(--accent-border);
}

/* ── Header ──────────────────────────── */
.viewer__header {
  padding: var(--space-5) var(--space-5) var(--space-4);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.viewer__subject {
  font-size: var(--text-lg);
  font-weight: var(--weight-bold);
  color: var(--text-primary);
  line-height: var(--leading-snug);
  margin-bottom: var(--space-4);
}

.viewer__sender-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.viewer__avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  min-width: 40px;
  border-radius: var(--radius-full);
  background: var(--accent-dim);
  color: var(--accent);
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
}

.viewer__sender-info {
  flex: 1;
  min-width: 0;
}

.viewer__sender-name {
  font-size: var(--text-base);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  line-height: 1.3;
}

.viewer__sender-email {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.viewer__date {
  font-size: var(--text-xs);
  color: var(--text-muted);
  flex-shrink: 0;
  text-align: right;
  white-space: nowrap;
}

/* ── Recipients ──────────────────────── */
.viewer__recipients {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding-left: 52px; /* aligned with sender info */
}

.viewer__recipient-row {
  display: flex;
  gap: var(--space-2);
  font-size: var(--text-xs);
}

.viewer__recipient-label {
  color: var(--text-muted);
  font-weight: var(--weight-medium);
  flex-shrink: 0;
}

.viewer__recipient-value {
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── Attachments badge ───────────────── */
.viewer__attachment-badge {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-3);
  margin-left: 52px;
  padding: var(--space-1-5) var(--space-3);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  color: var(--text-secondary);
  font-size: var(--text-xs);
}

/* ── Body ────────────────────────────── */
.viewer__body-wrapper {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-5);
}

.viewer__body {
  white-space: pre-wrap;
  font-size: var(--text-base);
  line-height: var(--leading-relaxed);
  color: var(--text-primary);
  background: var(--surface-1);
  padding: var(--space-5);
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  word-break: break-word;
}
</style>
