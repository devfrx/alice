/**
 * permissionMode.ts — Pinia setup-store for the per-conversation permission tier.
 *
 * The *permission mode* is the authorization tier governing every tool-call the
 * agent makes (``strict`` / ``auto_edits`` / ``plan`` / ``autopilot``). It is
 * set ONLY by the user. Kept in sync three ways (mirroring `scope.ts`):
 *
 * - On-demand REST snapshot via {@link ensureForConversation}, backed by
 *   `GET /api/permission-mode/{conversation_id}`.
 * - User mutation via {@link setMode}, backed by `PUT` (NOT idle-guarded — the
 *   engine reads the tier per tool-call, so a mid-turn change is sound).
 * - Live push: the events WebSocket folds each `permission_mode.updated` frame
 *   through {@link applyModeUpdated}.
 *
 * State is keyed by conversation id; reactivity is preserved by reassigning the
 * record on every mutation (mirroring `scope.ts` / `plan.ts`).
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'

import { permissionsApi } from '../services/api'
import type { PermissionMode, WsPermissionModeUpdatedMessage } from '../types/permission'

/** The default tier assumed before a snapshot is fetched (matches backend). */
export const DEFAULT_PERMISSION_MODE: PermissionMode = 'strict'

export const usePermissionModeStore = defineStore('permissionMode', () => {
  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------

  /** The tier per conversation id. */
  const byConversation = ref<Record<string, PermissionMode>>({})

  /** Conversation ids whose mode has been fetched at least once. */
  const fetched = ref<Set<string>>(new Set())

  // -----------------------------------------------------------------------
  // Getters
  // -----------------------------------------------------------------------

  /** The tier for a conversation, defaulting to ``strict`` when unknown. */
  function modeFor(conversationId: string | null): PermissionMode {
    if (!conversationId) return DEFAULT_PERMISSION_MODE
    return byConversation.value[conversationId] ?? DEFAULT_PERMISSION_MODE
  }

  // -----------------------------------------------------------------------
  // Actions
  // -----------------------------------------------------------------------

  /** Fetch the tier snapshot for a conversation, replacing any cached entry. */
  async function fetch(conversationId: string): Promise<void> {
    const res = await permissionsApi.getPermissionMode(conversationId)
    byConversation.value = { ...byConversation.value, [conversationId]: res.mode }
    fetched.value.add(conversationId)
  }

  /** Fetch a conversation's tier only once per session. */
  async function ensureForConversation(conversationId: string): Promise<void> {
    if (fetched.value.has(conversationId)) return
    fetched.value.add(conversationId)
    try {
      await fetch(conversationId)
    } catch (err) {
      fetched.value.delete(conversationId)
      throw err
    }
  }

  /** `permission_mode.updated` → replace the conversation's tier. */
  function applyModeUpdated(msg: WsPermissionModeUpdatedMessage): void {
    byConversation.value = {
      ...byConversation.value,
      [msg.conversation_id]: msg.mode,
    }
  }

  /** Set the conversation's tier, persisting server-side (optimistic). */
  async function setMode(conversationId: string, mode: PermissionMode): Promise<void> {
    const prev = byConversation.value[conversationId]
    byConversation.value = { ...byConversation.value, [conversationId]: mode }
    try {
      const res = await permissionsApi.setPermissionMode(conversationId, mode)
      byConversation.value = { ...byConversation.value, [conversationId]: res.mode }
    } catch (err) {
      // Roll back the optimistic change on failure.
      byConversation.value = { ...byConversation.value, [conversationId]: prev ?? DEFAULT_PERMISSION_MODE }
      throw err
    }
  }

  /** Clear all cached tiers and the fetched-once guard. */
  function reset(): void {
    byConversation.value = {}
    fetched.value = new Set()
  }

  return {
    // state
    byConversation,
    fetched,
    // getters
    modeFor,
    // actions
    fetch,
    ensureForConversation,
    applyModeUpdated,
    setMode,
    reset,
  }
})
