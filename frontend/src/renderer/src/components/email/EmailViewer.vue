<script setup lang="ts">
/**
 * EmailViewer — Full email detail view with structured header,
 * action toolbar, sender avatar, and formatted body.
 */
import { useEmailStore } from '../../stores/email'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'

const emailStore = useEmailStore()

async function handleArchive(): Promise<void> {
  if (!emailStore.currentEmail) return
  await emailStore.archiveEmail(emailStore.currentEmail.uid, emailStore.currentFolder)
}

async function handleMarkRead(read: boolean): Promise<void> {
  if (!emailStore.currentEmail) return
  await emailStore.markRead(emailStore.currentEmail.uid, read, emailStore.currentFolder)
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
    minute: '2-digit'
  })
}
</script>

<template>
  <div v-if="emailStore.currentEmail" class="viewer">
    <!-- Top action bar -->
    <div class="viewer__topbar">
      <UiIconButton label="Chiudi" size="md" @click="emailStore.clearCurrentEmail()">
        <AppIcon name="arrow-left" :size="16" />
      </UiIconButton>

      <div class="viewer__topbar-actions">
        <UiIconButton
          :label="emailStore.currentEmail.is_read ? 'Segna come non letta' : 'Segna come letta'"
          size="md"
          @click="handleMarkRead(!emailStore.currentEmail?.is_read)"
        >
          <AppIcon
            :name="emailStore.currentEmail.is_read ? 'email-read' : 'email-unread'"
            :size="16"
            :stroke-width="1.8"
          />
        </UiIconButton>

        <UiIconButton label="Archivia" size="md" tone="accent" @click="handleArchive">
          <AppIcon name="archive" :size="16" :stroke-width="1.8" />
        </UiIconButton>
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
        <AppIcon name="paperclip" :size="14" :stroke-width="1.8" />
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

/* ── Header ──────────────────────────── */
.viewer__header {
  padding: var(--space-5) var(--space-5) var(--space-4);
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
  padding-left: 52px;
  /* aligned with sender info */
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
