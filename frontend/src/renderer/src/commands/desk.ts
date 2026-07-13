/**
 * Desk window commands (spec §5): the agent drives Horizon's floating
 * windows through the SAME implementations the UI uses (desk store actions).
 *
 * Capabilities follow the §7 permission matrix: open/focus/arrange are
 * `navigation`, list is `read`, close is `mutate` (denied in plan tier,
 * confirmed in strict). `window` is not a guardrail domain.
 */
import type { Router } from 'vue-router'
import { commandRegistry } from './registry'
import { MODULE_REGISTRY } from '../composables/workspace/moduleRegistry'
import { useDeskStore } from '../stores/desk'

export interface WindowOpenArgs {
  module: string
  params?: Record<string, unknown>
}
export interface WindowIdArgs {
  window_id: string
}
export interface WindowArrangeArgs {
  preset: 'cascade' | 'tile'
}

export const DESK_COMMAND_NAMES = [
  'window.open',
  'window.focus',
  'window.list',
  'window.close',
  'window.arrange'
] as const

export function installDeskCommands(router: Router): void {
  // Idempotent install (same HMR rationale as installCoreCommands).
  for (const name of DESK_COMMAND_NAMES) {
    commandRegistry.unregister(name)
  }

  commandRegistry.register<WindowOpenArgs>({
    name: 'window.open',
    title: 'Apri finestra',
    description:
      'Open a module as a floating window on the assistant desk (navigates to the assistant view first when needed). Singleton modules focus the existing window.',
    exposeToAgent: true,
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: {
        module: { type: 'string', enum: Object.keys(MODULE_REGISTRY) },
        params: { type: 'object' }
      },
      required: ['module']
    },
    run: async ({ module, params }) => {
      if (router.currentRoute.value.name !== 'assistant') {
        await router.push({ name: 'assistant' })
      }
      const id = useDeskStore().openWindow(module, params)
      if (id === null) throw new Error(`Unknown module: ${module}`)
      return { window_id: id }
    }
  })

  commandRegistry.register<WindowIdArgs>({
    name: 'window.focus',
    title: 'Porta in primo piano',
    description: 'Bring a desk window to the front (restores it when minimized)',
    exposeToAgent: true,
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { window_id: { type: 'string' } },
      required: ['window_id']
    },
    run: ({ window_id }) => {
      if (!useDeskStore().focusWindow(window_id)) {
        throw new Error(`Unknown window: ${window_id}`)
      }
    }
  })

  commandRegistry.register({
    name: 'window.list',
    title: 'Elenca finestre',
    description:
      'List the desk windows with id, module, title, geometry, minimized and focused flags',
    exposeToAgent: true,
    capability: 'read',
    argsSchema: { type: 'object', properties: {} },
    run: () => ({ windows: useDeskStore().listWindows() })
  })

  commandRegistry.register<WindowIdArgs>({
    name: 'window.close',
    title: 'Chiudi finestra',
    description:
      'Close a desk window (visibility only: the underlying module state is never destroyed)',
    exposeToAgent: true,
    capability: 'mutate',
    argsSchema: {
      type: 'object',
      properties: { window_id: { type: 'string' } },
      required: ['window_id']
    },
    run: ({ window_id }) => {
      if (!useDeskStore().closeWindow(window_id)) {
        throw new Error(`Unknown window: ${window_id}`)
      }
    }
  })

  commandRegistry.register<WindowArrangeArgs>({
    name: 'window.arrange',
    title: 'Disponi finestre',
    description: 'Arrange the non-minimized desk windows with a preset (cascade or tile)',
    exposeToAgent: true,
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { preset: { type: 'string', enum: ['cascade', 'tile'] } },
      required: ['preset']
    },
    run: ({ preset }) => {
      useDeskStore().arrangeWindows(preset)
    }
  })
}
