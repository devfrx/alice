<script setup lang="ts">
/**
 * EmailFoldersSidebar — Left sidebar with email folders, icons, and unread counts.
 *
 * Maps known IMAP folder names to icons and labels.
 * Active folder is highlighted with accent left-bar.
 */
import { computed } from 'vue'
import { useEmailStore } from '../../stores/email'

const emailStore = useEmailStore()

/** Icon + label map for known IMAP/Gmail folder names. */
const FOLDER_META: Record<string, { icon: string; label: string }> = {
  INBOX: { icon: 'inbox', label: 'Inbox' },
  '[Gmail]/Posta inviata': { icon: 'send', label: 'Inviata' },
  '[Gmail]/Bozze': { icon: 'draft', label: 'Bozze' },
  '[Gmail]/Importanti': { icon: 'star', label: 'Importanti' },
  '[Gmail]/Speciali': { icon: 'bookmark', label: 'Speciali' },
  '[Gmail]/Spam': { icon: 'warning', label: 'Spam' },
  '[Gmail]/Cestino': { icon: 'trash', label: 'Cestino' },
  '[Gmail]/Tutti i messaggi': { icon: 'archive', label: 'Tutti' },
  'Unsubscribed mailing lists': { icon: 'unsubscribe', label: 'Disiscritti' },
}

function getMeta(folder: string) {
  return FOLDER_META[folder] ?? { icon: 'folder', label: folder }
}

/** Primary folders shown first, rest grouped below. */
const primaryFolders = computed(() =>
  emailStore.folders.filter((f) => ['INBOX', '[Gmail]/Posta inviata', '[Gmail]/Bozze'].includes(f)),
)

const secondaryFolders = computed(() =>
  emailStore.folders.filter(
    (f) => !['INBOX', '[Gmail]/Posta inviata', '[Gmail]/Bozze'].includes(f),
  ),
)
</script>

<template>
  <aside class="folders">
    <div class="folders__header">
      <span class="folders__title">Cartelle</span>
    </div>

    <!-- Primary folders -->
    <nav class="folders__nav">
      <button
        v-for="folder in primaryFolders"
        :key="folder"
        class="folders__item"
        :class="{ 'folders__item--active': emailStore.currentFolder === folder }"
        @click="emailStore.fetchInbox(folder)"
      >
        <svg class="folders__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <!-- Inbox -->
          <template v-if="getMeta(folder).icon === 'inbox'">
            <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" />
            <path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
          </template>
          <!-- Send -->
          <template v-else-if="getMeta(folder).icon === 'send'">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </template>
          <!-- Draft -->
          <template v-else-if="getMeta(folder).icon === 'draft'">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
          </template>
        </svg>
        <span class="folders__label">{{ getMeta(folder).label }}</span>
        <span v-if="folder === 'INBOX' && emailStore.unreadCount > 0" class="folders__badge">
          {{ emailStore.unreadCount }}
        </span>
      </button>
    </nav>

    <div class="folders__divider" />

    <!-- Secondary folders -->
    <nav class="folders__nav folders__nav--secondary">
      <button
        v-for="folder in secondaryFolders"
        :key="folder"
        class="folders__item"
        :class="{ 'folders__item--active': emailStore.currentFolder === folder }"
        @click="emailStore.fetchInbox(folder)"
      >
        <svg class="folders__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <!-- Star -->
          <template v-if="getMeta(folder).icon === 'star'">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
          </template>
          <!-- Bookmark -->
          <template v-else-if="getMeta(folder).icon === 'bookmark'">
            <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
          </template>
          <!-- Warning/Spam -->
          <template v-else-if="getMeta(folder).icon === 'warning'">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </template>
          <!-- Trash -->
          <template v-else-if="getMeta(folder).icon === 'trash'">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6l-1 14H6L5 6" />
            <path d="M10 11v6" />
            <path d="M14 11v6" />
            <path d="M9 6V4h6v2" />
          </template>
          <!-- Archive -->
          <template v-else-if="getMeta(folder).icon === 'archive'">
            <polyline points="21 8 21 21 3 21 3 8" />
            <rect x="1" y="3" width="22" height="5" />
            <line x1="10" y1="12" x2="14" y2="12" />
          </template>
          <!-- Unsubscribe -->
          <template v-else-if="getMeta(folder).icon === 'unsubscribe'">
            <path d="M18.36 6.64a9 9 0 1 1-12.73 0" />
            <line x1="12" y1="2" x2="12" y2="12" />
          </template>
          <!-- Generic folder -->
          <template v-else>
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" />
          </template>
        </svg>
        <span class="folders__label">{{ getMeta(folder).label }}</span>
      </button>
    </nav>
  </aside>
</template>

<style scoped>
.folders {
  width: 200px;
  min-width: 200px;
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  overflow-y: auto;
  overflow-x: hidden;
}

.folders__header {
  padding: var(--space-4) var(--space-4) var(--space-2);
}

.folders__title {
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: var(--tracking-wide);
}

.folders__nav {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  padding: 0 var(--space-2);
}

.folders__nav--secondary {
  flex: 1;
  overflow-y: auto;
}

.folders__divider {
  height: 1px;
  background: var(--border);
  margin: var(--space-2) var(--space-4);
}

.folders__item {
  display: flex;
  align-items: center;
  gap: var(--space-2-5);
  padding: var(--space-2) var(--space-3);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-family: var(--font-sans);
  cursor: pointer;
  transition:
    background-color var(--transition-fast),
    color var(--transition-fast);
  text-align: left;
  position: relative;
}

.folders__item:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.folders__item--active {
  background: var(--accent-dim);
  color: var(--accent);
}

.folders__item--active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 3px;
  background: var(--accent);
  border-radius: var(--radius-pill);
}

.folders__item--active:hover {
  background: var(--accent-light);
}

.folders__icon {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}

.folders__label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folders__badge {
  background: var(--accent);
  color: var(--surface-0);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  line-height: 1.4;
  min-width: 18px;
  text-align: center;
}
</style>
