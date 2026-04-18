<script setup lang="ts">
/**
 * EmailPageView — Vista principale dell'Email Assistant.
 *
 * Layout a tre colonne: EmailFoldersSidebar | InboxList | EmailViewer.
 * Le notifiche EMAIL_RECEIVED arrivano tramite useEventsWebSocket.ts (singleton).
 *
 * Deep-link contract (route `/email/:id?`): se `id` è presente nel path,
 * la pagina tenta di caricare l'email corrispondente dalla cartella di
 * default (INBOX). Se non esiste, il viewer mostra l'empty state.
 */
import { onMounted, watch } from 'vue'
import { useEmailStore } from '../stores/email'
import EmailFoldersSidebar from '../components/email/EmailFoldersSidebar.vue'
import InboxList from '../components/email/InboxList.vue'
import EmailViewer from '../components/email/EmailViewer.vue'
import AppIcon from '../components/ui/AppIcon.vue'

const props = defineProps<{ id?: string }>()

const emailStore = useEmailStore()

async function syncDeepLink(uid: string | undefined): Promise<void> {
  const trimmed = uid?.trim()
  if (!trimmed) return
  if (emailStore.currentEmail?.uid === trimmed) return
  await emailStore.fetchEmail(trimmed)
}

onMounted(async () => {
  await Promise.all([emailStore.fetchInbox(), emailStore.fetchFolders()])
  await syncDeepLink(props.id)
})

watch(() => props.id, (id) => { void syncDeepLink(id) })
</script>

<template>
  <div class="email-page" aria-label="Email">
    <EmailFoldersSidebar />

    <section class="email-page__inbox">
      <InboxList />
    </section>

    <section class="email-page__viewer">
      <EmailViewer v-if="emailStore.currentEmail" />
      <div v-else class="email-page__empty">
        <AppIcon name="mail" class="email-page__empty-icon" :size="56" :stroke-width="1" />
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
  padding: 10px;
  gap: 10px;
  overflow: hidden;
  background: var(--surface-0);
  color: var(--text-primary);
  box-sizing: border-box;
}

.email-page__inbox {
  overflow: hidden;
  border-radius: 14px;
  border: 1px solid var(--glass-border);
  background: var(--surface-0);
  /* box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15); */
}

.email-page__viewer {
  overflow: hidden;
  border-radius: 14px;
  border: 1px solid var(--glass-border);
  background: var(--surface-1);
  /* box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15); */
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
