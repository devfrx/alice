/**
 * Core UI commands (Fase 6): navigation and conversation lifecycle.
 *
 * Registered once at app startup by {@link installCoreCommands}. Handlers
 * resolve Pinia stores lazily (at execution time) so registration can happen
 * before store initialisation.
 */
import type { Router } from 'vue-router'
import { commandRegistry } from './registry'
import { useChatStore } from '../stores/chat'
import { useUIStore } from '../stores/ui'

/** Route names addressable via `view.switch`. */
export const SWITCHABLE_VIEWS = [
  'assistant',
  'calendar',
  'settings',
  'email',
  'whiteboard',
  'board',
  'terminal',
  'services',
] as const
export type SwitchableView = (typeof SWITCHABLE_VIEWS)[number]

export interface ViewSwitchArgs {
  view: SwitchableView
}
export interface ConversationOpenArgs {
  conversation_id: string
}
export interface ArtifactShowArgs {
  artifact_id: string
}

/** Names owned by this module — kept in sync with the registrations below. */
const CORE_COMMAND_NAMES = [
  'view.switch',
  'conversation.open',
  'conversation.new',
  'sidebar.toggle',
  'artifact.show',
] as const

export function installCoreCommands(router: Router): void {
  // Idempotent install: drop any previous core registrations first. Under
  // Vite HMR an edit to this module re-runs App.vue's setup while the
  // registry singleton (a dependency, not an importer) survives — a
  // presence-guard would keep STALE handler closures alive; re-registering
  // swaps in the fresh ones instead.
  for (const name of CORE_COMMAND_NAMES) {
    commandRegistry.unregister(name)
  }

  commandRegistry.register<ViewSwitchArgs>({
    name: 'view.switch',
    title: 'Vai alla vista',
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { view: { type: 'string', enum: [...SWITCHABLE_VIEWS] } },
      required: ['view'],
    },
    run: async ({ view }) => {
      if (!SWITCHABLE_VIEWS.includes(view)) {
        throw new Error(`Unknown view: ${String(view)}`)
      }
      await router.push({ name: view })
    },
  })

  commandRegistry.register<ConversationOpenArgs>({
    name: 'conversation.open',
    title: 'Apri conversazione',
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { conversation_id: { type: 'string' } },
      required: ['conversation_id'],
    },
    run: async ({ conversation_id }) => {
      const chatStore = useChatStore()
      await chatStore.loadConversation(conversation_id)
      if (router.currentRoute.value.name !== 'assistant') {
        await router.push({ name: 'assistant' })
      }
    },
  })

  commandRegistry.register({
    name: 'conversation.new',
    title: 'Nuova conversazione',
    capability: 'mutate',
    argsSchema: { type: 'object', properties: {} },
    run: async () => {
      const chatStore = useChatStore()
      await chatStore.createConversation()
      if (router.currentRoute.value.name !== 'assistant') {
        await router.push({ name: 'assistant' })
      }
    },
  })

  commandRegistry.register({
    name: 'sidebar.toggle',
    title: 'Mostra/nascondi sidebar',
    // Shell chrome, not a route change; tagged with the least-privileged
    // capability so Fase-7 gating fails safe.
    capability: 'navigation',
    argsSchema: { type: 'object', properties: {} },
    run: () => {
      useUIStore().toggleSidebar()
    },
  })

  commandRegistry.register<ArtifactShowArgs>({
    name: 'artifact.show',
    title: 'Mostra artefatto',
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { artifact_id: { type: 'string' } },
      required: ['artifact_id'],
    },
    run: async ({ artifact_id }) => {
      // The board view does not consume `query.artifact` yet (backlog: it
      // may highlight/scroll to the artifact) — the command surface is
      // stable so Fase-7 callers need no change when that lands.
      await router.push({ name: 'board', query: { artifact: artifact_id } })
    },
  })
}
