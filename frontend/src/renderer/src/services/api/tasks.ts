/** Task list + plan document endpoints (`/api/tasks`, `/api/plan-document`). */
import { request } from './http'
import type { TasksResponse } from '../../types/tasks'
import type { PlanDocumentResponse } from '../../types/planDocument'

export const tasksApi = {
  /** Fetch the persisted task list (todo-list) for a conversation. */
  getTasks: (conversationId: string): Promise<TasksResponse> =>
    request<TasksResponse>(`/tasks/${encodeURIComponent(conversationId)}`),

  /** Fetch the persisted plan document (Markdown write-up) for a conversation. */
  getPlanDocument: (conversationId: string): Promise<PlanDocumentResponse> =>
    request<PlanDocumentResponse>(`/plan-document/${encodeURIComponent(conversationId)}`),
}
