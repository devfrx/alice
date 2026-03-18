<script setup lang="ts">
/**
 * EmailPageView — Vista principale Email Assistant.
 *
 * Layout a tre colonne: EmailFoldersSidebar | InboxList | EmailViewer.
 * Le notifiche EMAIL_RECEIVED arrivano tramite useEventsWebSocket.ts (singleton).
 */
import { onMounted } from 'vue'
import { useEmailStore } from '../stores/email'
import EmailFoldersSidebar from '../components/email/EmailFoldersSidebar.vue'
import InboxList from '../components/email/InboxList.vue'
import EmailViewer from '../components/email/EmailViewer.vue'

const emailStore = useEmailStore()

onMounted(async () => {
  await Promise.all([emailStore.fetchInbox(), emailStore.fetchFolders()])
})
</script>

<template>
  <div class="email-page">
    <EmailFoldersSidebar />

    <section class="email-page__inbox">
      <InboxList />
    </section>

    <section class="email-page__viewer">
      <EmailViewer v-if="emailStore.currentEmail" />
      <div v-else class="email-page__empty">
        <svg class="email-page__empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
          <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
          <polyline points="22 6 12 13 2 6" />
        </svg>
        <span class="email-page__empty-title">Seleziona un'email</span>
        <span class="email-page__empty-text">
          Scegli un messaggio dalla lista per visualizzarlo qui
        </span>
      </div>
    </section>
  </div>
</template>

<style scoped>
.email-page {
  display: grid;
  grid-template-columns: 200px 340px 1fr;
  height: 100%;
  width: 100%;
  overflow: hidden;
  background: var(--surface-0);
  color: var(--text-primary);
}

.email-page__inbox {
  border-right: 1px solid var(--border);
  overflow: hidden;
}

.email-page__viewer {
  overflow: hidden;
}

.email-page__empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  padding: var(--space-8);
}

.email-page__empty-icon {
  width: 56px;
  height: 56px;
  color: var(--text-muted);
  opacity: 0.3;
  margin-bottom: var(--space-2);
}

.email-page__empty-title {
  font-size: var(--text-md);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
}

.email-page__empty-text {
  font-size: var(--text-sm);
  color: var(--text-muted);
  text-align: center;
  max-width: 240px;
  line-height: var(--leading-relaxed);
}
</style>
