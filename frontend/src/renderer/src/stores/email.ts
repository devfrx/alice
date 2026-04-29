import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '../services/api'
import type { EmailHeader, EmailDetail, EmailSearchRequest } from '../types/email'

export const useEmailStore = defineStore('email', () => {
  const inbox = ref<EmailHeader[]>([])
  const currentEmail = ref<EmailDetail | null>(null)
  const folders = ref<string[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const currentFolder = ref('INBOX')
  const unreadCount = computed(() => inbox.value.filter((e) => !e.is_read).length)

  function _toErrorMessage(err: unknown): string {
    return err instanceof Error ? err.message : String(err)
  }

  async function fetchInbox(folder = 'INBOX', limit = 20, unreadOnly = false): Promise<void> {
    loading.value = true
    error.value = null
    try {
      inbox.value = await api.getEmailInbox({ folder, limit, unread_only: unreadOnly })
      currentFolder.value = folder
    } catch (err) {
      error.value = _toErrorMessage(err)
    } finally {
      loading.value = false
    }
  }

  async function fetchEmail(uid: string, folder = 'INBOX'): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const detail = await api.getEmail(uid, folder)
      // Backend detail response may omit is_read; infer from inbox header
      const idx = inbox.value.findIndex((e) => e.uid === uid)
      if (idx !== -1) {
        detail.is_read = inbox.value[idx].is_read
        inbox.value[idx].is_read = true
      }
      detail.is_read = detail.is_read ?? true
      currentEmail.value = detail
    } catch (err) {
      error.value = _toErrorMessage(err)
    } finally {
      loading.value = false
    }
  }

  async function searchEmails(req: EmailSearchRequest): Promise<void> {
    loading.value = true
    error.value = null
    try {
      inbox.value = await api.searchEmails(req)
    } catch (err) {
      error.value = _toErrorMessage(err)
    } finally {
      loading.value = false
    }
  }

  async function markRead(uid: string, read = true, folder = 'INBOX'): Promise<void> {
    await api.markEmailRead(uid, folder, read)
    const idx = inbox.value.findIndex((e) => e.uid === uid)
    if (idx !== -1) inbox.value[idx].is_read = read
    if (currentEmail.value?.uid === uid) currentEmail.value.is_read = read
  }

  async function archiveEmail(uid: string, fromFolder = 'INBOX'): Promise<void> {
    await api.archiveEmail(uid, fromFolder)
    inbox.value = inbox.value.filter((e) => e.uid !== uid)
    if (currentEmail.value?.uid === uid) currentEmail.value = null
  }

  async function fetchFolders(): Promise<void> {
    try {
      folders.value = await api.getEmailFolders()
    } catch { /* non-critical */ }
  }

  function handleEmailReceived(folder: string): void {
    if (folder === currentFolder.value) {
      void fetchInbox(currentFolder.value)
    }
  }

  function clearCurrentEmail(): void {
    currentEmail.value = null
  }

  return {
    inbox, currentEmail, folders, loading, error, currentFolder, unreadCount,
    fetchInbox, fetchEmail, searchEmails, markRead, archiveEmail,
    fetchFolders, handleEmailReceived, clearCurrentEmail,
  }
})
