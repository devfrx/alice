<script setup lang="ts">
/**
 * EmailFoldersSidebar — Left sidebar with email folders, icons, and unread counts.
 *
 * Maps known IMAP folder names to icons and labels.
 * Active folder is highlighted with accent left-bar.
 */
import { computed } from 'vue'
import { useEmailStore } from '../../stores/email'
import type { AppIconName } from '../../assets/icons'
import AppIcon from '../ui/AppIcon.vue'

const emailStore = useEmailStore()

/** Icon + label map for known IMAP/Gmail folder names. */
const FOLDER_META: Record<string, { icon: AppIconName; label: string }> = {
  INBOX: { icon: 'inbox', label: 'Inbox' },
  '[Gmail]/Posta inviata': { icon: 'send', label: 'Inviata' },
  '[Gmail]/Bozze': { icon: 'draft', label: 'Bozze' },
  '[Gmail]/Importanti': { icon: 'star', label: 'Importanti' },
  '[Gmail]/Speciali': { icon: 'bookmark', label: 'Speciali' },
  '[Gmail]/Spam': { icon: 'alert-triangle', label: 'Spam' },
  '[Gmail]/Cestino': { icon: 'trash', label: 'Cestino' },
  '[Gmail]/Tutti i messaggi': { icon: 'archive', label: 'Tutti' },
  'Unsubscribed mailing lists': { icon: 'power', label: 'Disiscritti' },
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
      <button v-for="folder in primaryFolders" :key="folder" class="folders__item"
        :class="{ 'folders__item--active': emailStore.currentFolder === folder }"
        @click="emailStore.fetchInbox(folder)">
        <AppIcon class="folders__icon" :name="getMeta(folder).icon" :size="16" :stroke-width="1.8" />
        <span class="folders__label">{{ getMeta(folder).label }}</span>
        <span v-if="folder === 'INBOX' && emailStore.unreadCount > 0" class="folders__badge">
          {{ emailStore.unreadCount }}
        </span>
      </button>
    </nav>

    <div class="folders__divider" />

    <!-- Secondary folders -->
    <nav class="folders__nav folders__nav--secondary">
      <button v-for="folder in secondaryFolders" :key="folder" class="folders__item"
        :class="{ 'folders__item--active': emailStore.currentFolder === folder }"
        @click="emailStore.fetchInbox(folder)">
        <AppIcon class="folders__icon" :name="getMeta(folder).icon" :size="16" :stroke-width="1.8" />
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
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur-heavy));
  -webkit-backdrop-filter: blur(var(--glass-blur-heavy));
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-lg);
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
