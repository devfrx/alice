/** Email assistant endpoints (`/api/email`). */
import { request } from './http'
import type { EmailHeader, EmailDetail, EmailSearchRequest } from '../../types/email'

export const emailApi = {
  /** Fetch email inbox headers. */
  getEmailInbox: (params?: {
    folder?: string
    limit?: number
    unread_only?: boolean
  }): Promise<EmailHeader[]> => {
    const qs = new URLSearchParams()
    if (params?.folder) qs.set('folder', params.folder)
    if (params?.limit !== undefined) qs.set('limit', String(params.limit))
    if (params?.unread_only !== undefined) qs.set('unread_only', String(params.unread_only))
    const q = qs.toString()
    return request<EmailHeader[]>(`/email/inbox${q ? `?${q}` : ''}`)
  },

  /** Fetch a single email's full content. */
  getEmail: (uid: string, folder = 'INBOX'): Promise<EmailDetail> =>
    request<EmailDetail>(`/email/${encodeURIComponent(uid)}?folder=${encodeURIComponent(folder)}`),

  /** Search emails using IMAP criteria. */
  searchEmails: (req: EmailSearchRequest): Promise<EmailHeader[]> =>
    request<EmailHeader[]>('/email/search', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  /** Mark email as read or unread. */
  markEmailRead: (uid: string, folder: string, read: boolean): Promise<{ success: boolean }> =>
    request<{ success: boolean }>(
      `/email/${encodeURIComponent(uid)}/read?folder=${encodeURIComponent(folder)}&read=${read}`,
      { method: 'PUT' },
    ),

  /** Archive an email. */
  archiveEmail: (uid: string, fromFolder: string): Promise<{ success: boolean }> =>
    request<{ success: boolean }>(
      `/email/${encodeURIComponent(uid)}/archive?from_folder=${encodeURIComponent(fromFolder)}`,
      { method: 'PUT' },
    ),

  /** List IMAP folders. */
  getEmailFolders: (): Promise<string[]> => request<string[]>('/email/folders'),
}
