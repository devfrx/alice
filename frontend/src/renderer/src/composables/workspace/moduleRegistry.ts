/**
 * moduleRegistry.ts — Central registry of tiling-workspace modules for AL\CE.
 *
 * Each ModuleDef describes a module that can be opened into a tile. Lazy
 * imports are used for the component so the main bundle stays small.
 *
 * To register a new module add an entry to MODULE_REGISTRY and export the
 * stub (or real) adapter SFC from `components/canvas/modules/`.
 */
import type { Component } from 'vue'
import type { AppIconName } from '../../assets/icons'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Preferred dock zone when a module is first opened. */
export type ModuleZone = 'right' | 'bottom' | 'fill'

export interface ModuleDef {
  /** Stable module identifier — must match the key in MODULE_REGISTRY. */
  id: string
  /** Human-readable label shown in launchers / tab headers. */
  label: string
  /** Icon from the AL\CE icon registry. */
  icon: AppIconName
  /** Lazy import factory that resolves to the adapter SFC. */
  component: () => Promise<{ default: Component }>
  /** Preferred zone when auto-placing the tile. Defaults to 'right'. */
  defaultZone?: ModuleZone
  /**
   * If true, at most one tile with this moduleId may exist at a time.
   * Opening a second instance focuses the existing tile instead.
   */
  singleton?: boolean
  /**
   * Optional runtime guard. Called with the current app context to decide
   * whether the module should appear in launchers.
   */
  available?: (ctx: { conversationId: string | null }) => boolean
}

// ---------------------------------------------------------------------------
// Module definitions
// ---------------------------------------------------------------------------

const chat: ModuleDef = {
  id: 'chat',
  label: 'Chat',
  icon: 'message',
  component: () => import('../../components/canvas/modules/ChatModule.vue'),
  defaultZone: 'fill',
  singleton: true
}

const chart: ModuleDef = {
  id: 'chart',
  label: 'Grafico',
  icon: 'bar-chart',
  component: () => import('../../components/canvas/modules/ChartModule.vue'),
  defaultZone: 'right'
}

const whiteboard: ModuleDef = {
  id: 'whiteboard',
  label: 'Whiteboard',
  icon: 'edit',
  component: () => import('../../components/canvas/modules/WhiteboardModule.vue'),
  defaultZone: 'right'
}

const cad3d: ModuleDef = {
  id: 'cad3d',
  label: '3D',
  icon: 'box-3d',
  component: () => import('../../components/canvas/modules/Cad3dModule.vue'),
  defaultZone: 'right'
}

const plan: ModuleDef = {
  id: 'plan',
  label: 'Plan',
  icon: 'file-lines',
  component: () => import('../../components/canvas/modules/PlanModule.vue'),
  defaultZone: 'right',
  singleton: true
}

const terminal: ModuleDef = {
  id: 'terminal',
  label: 'Terminal',
  icon: 'embedding',
  component: () => import('../../components/canvas/modules/TerminalModule.vue'),
  defaultZone: 'bottom',
  singleton: true
}

const scope: ModuleDef = {
  id: 'scope',
  label: 'Scope',
  icon: 'folder',
  component: () => import('../../components/canvas/modules/ScopeModule.vue'),
  defaultZone: 'right',
  singleton: true
}

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export const MODULE_REGISTRY: Record<string, ModuleDef> = {
  chat,
  chart,
  whiteboard,
  cad3d,
  plan,
  terminal,
  scope
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns the ModuleDef for `id`, or undefined if not registered. */
export function getModule(id: string): ModuleDef | undefined {
  return MODULE_REGISTRY[id]
}

/** Returns all registered ModuleDefs as an ordered array. */
export function listModules(): ModuleDef[] {
  return Object.values(MODULE_REGISTRY)
}

/** Returns true when `id` maps to a registered module. */
export function isModuleRegistered(id: string): boolean {
  return Object.prototype.hasOwnProperty.call(MODULE_REGISTRY, id)
}
