/**
 * usePluginComponents — Plugin component registry and mount point infrastructure.
 *
 * Maps plugin names to lazy-loaded Vue components at specific mount points.
 * Components are only returned for plugins that are currently enabled.
 */
import { computed, defineAsyncComponent, type Component, type ComputedRef } from 'vue'

import { usePluginsStore } from '../stores/plugins'

/** Supported mount point locations in the UI. */
export type MountPoint = 'sidebar' | 'modal' | 'toolbar' | 'settings-panel'

/** A plugin component registration entry. */
export interface PluginComponent {
  /** Plugin name (must match backend plugin name) */
  name: string
  /** Vue async component */
  component: Component
  /** Where this component renders in the UI */
  mountPoint: MountPoint
  /** Display order within the mount point (lower = first) */
  order: number
}

/** Static registry of all plugin component registrations. */
const PLUGIN_COMPONENT_REGISTRY: PluginComponent[] = [
  {
    name: 'calendar',
    component: defineAsyncComponent(
      () => import('../components/plugins/CalendarView.vue')
    ),
    mountPoint: 'sidebar',
    order: 10,
  },
  {
    name: 'calendar',
    component: defineAsyncComponent(
      () => import('../components/plugins/CalendarView.vue')
    ),
    mountPoint: 'settings-panel',
    order: 10,
  },
  {
    name: 'web_search',
    component: defineAsyncComponent(
      () => import('../components/plugins/SearchResultsPanel.vue')
    ),
    mountPoint: 'sidebar',
    order: 20,
  },
]

/**
 * Returns reactive lists of plugin components filtered by mount point,
 * including only components whose plugin is currently enabled.
 */
export function usePluginComponents(): {
  toolbarComponents: ComputedRef<PluginComponent[]>
  sidebarComponents: ComputedRef<PluginComponent[]>
  settingsComponents: ComputedRef<PluginComponent[]>
  modalComponents: ComputedRef<PluginComponent[]>
  getComponentsForMountPoint: (mountPoint: MountPoint) => PluginComponent[]
} {
  const pluginsStore = usePluginsStore()

  /** Filter registry entries by mount point, keeping only enabled plugins. */
  function getComponentsForMountPoint(mountPoint: MountPoint): PluginComponent[] {
    const enabledNames = new Set(
      pluginsStore.plugins
        .filter((p) => p.enabled)
        .map((p) => p.name)
    )

    return PLUGIN_COMPONENT_REGISTRY
      .filter((entry) => entry.mountPoint === mountPoint && enabledNames.has(entry.name))
      .sort((a, b) => a.order - b.order)
  }

  const toolbarComponents = computed(() => getComponentsForMountPoint('toolbar'))
  const sidebarComponents = computed(() => getComponentsForMountPoint('sidebar'))
  const settingsComponents = computed(() => getComponentsForMountPoint('settings-panel'))
  const modalComponents = computed(() => getComponentsForMountPoint('modal'))

  return {
    toolbarComponents,
    sidebarComponents,
    settingsComponents,
    modalComponents,
    getComponentsForMountPoint,
  }
}
