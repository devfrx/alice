/**
 * AL\CE — Observable background tasks (Fase 8, spec §8).
 *
 * Fed exclusively by `background_task.updated` frames on the events WS;
 * frames carry the FULL task snapshot, so applying one is a plain fold.
 * In-memory only: the backend registry is ephemeral by design.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { ApiSchema } from '../types/generated'

export type BackgroundTaskInfo = ApiSchema<'WsBackgroundTaskUpdated'>

export const useBackgroundTasksStore = defineStore('backgroundTasks', () => {
  /** Latest snapshot per task id. */
  const byId = ref<Record<string, BackgroundTaskInfo>>({})

  /** Every known task, unordered. */
  const all = computed(() => Object.values(byId.value))

  /** Tasks still running (subagents, autonomous turns). */
  const active = computed(() => all.value.filter((t) => t.status === 'running'))

  function applyBackgroundTaskUpdated(msg: BackgroundTaskInfo): void {
    byId.value = { ...byId.value, [msg.task_id]: msg }
  }

  function reset(): void {
    byId.value = {}
  }

  return { byId, all, active, applyBackgroundTaskUpdated, reset }
})
