<script setup lang="ts">
/**
 * ModuleLauncher — Floating "add panel" button that opens a context-menu
 * listing all available workspace modules.
 *
 * Positioning: on trigger click we capture the button's getBoundingClientRect()
 * and pass the bottom-left corner as viewport coords to UiContextMenu, which
 * auto-adjusts if the menu would overflow the viewport.
 *
 * Filtering: chat is excluded (its anchored/tiled conversion is handled
 * elsewhere); any module whose available() guard returns false is also excluded.
 *
 * Toggle semantics (Claude Code desktop style): each module type is
 * single-instance. Clicking an entry opens + focuses it when closed, and closes
 * it when already open; open entries show a ✓ marker.
 */
import { ref, computed } from 'vue'
import UiIconButton from '../ui/UiIconButton.vue'
import UiContextMenu from '../ui/UiContextMenu.vue'
import UiContextMenuItem from '../ui/UiContextMenuItem.vue'
import AppIcon from '../ui/AppIcon.vue'
import { listModules, type ModuleDef } from '../../composables/workspace/moduleRegistry'
import { useWorkspaceStore } from '../../stores/workspace'
import { useTerminalSessionsStore } from '../../stores/terminalSessions'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

const props = withDefaults(
  defineProps<{
    conversationId?: string | null
  }>(),
  { conversationId: null }
)

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const workspaceStore = useWorkspaceStore()
const terminalStore = useTerminalSessionsStore()

const menuVisible = ref(false)
const menuX = ref(0)
const menuY = ref(0)

/** Ref to the trigger button element so we can restore focus on close. */
const triggerRef = ref<InstanceType<typeof UiIconButton> | null>(null)

// ---------------------------------------------------------------------------
// Computed module list
// ---------------------------------------------------------------------------

const visibleModules = computed<ModuleDef[]>(() =>
  listModules().filter(
    (m) =>
      m.id !== 'chat' && (m.available?.({ conversationId: props.conversationId ?? null }) ?? true)
  )
)

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

function openMenu(): void {
  const el = (triggerRef.value as unknown as { $el?: HTMLElement } | null)?.$el
  if (!el) return
  const rect = el.getBoundingClientRect()
  // Anchor the menu below and left-aligned with the button
  menuX.value = rect.left
  menuY.value = rect.bottom + 4
  menuVisible.value = true
}

function closeMenu(): void {
  menuVisible.value = false
  // Return focus to the trigger button
  const btnEl = triggerRef.value as unknown as { $el?: HTMLElement } | null
  btnEl?.$el?.focus()
}

function selectModule(moduleId: string): void {
  workspaceStore.toggleModule(moduleId)
  closeMenu()
}

/**
 * Menu hint per module: ✓ when open; for a *closed* terminal module, the count
 * of live sessions so the user sees "N terminals active" without opening it.
 */
function hintFor(mod: ModuleDef): string | undefined {
  if (workspaceStore.openModuleIds.has(mod.id)) return '✓'
  if (mod.id === 'terminal') {
    const n = terminalStore.activeCountFor(props.conversationId ?? null)
    if (n > 0) return String(n)
  }
  return undefined
}
</script>

<template>
  <div class="module-launcher">
    <UiIconButton
      ref="triggerRef"
      label="Apri modulo"
      size="sm"
      variant="subtle"
      :active="menuVisible"
      @click="openMenu"
    >
      <AppIcon name="modules" :size="16" />
    </UiIconButton>

    <UiContextMenu
      :visible="menuVisible"
      :x="menuX"
      :y="menuY"
      title="Apri modulo"
      @close="closeMenu"
    >
      <UiContextMenuItem
        v-for="mod in visibleModules"
        :key="mod.id"
        :label="mod.label"
        :hint="hintFor(mod)"
        @click="selectModule(mod.id)"
      >
        <template #icon>
          <AppIcon :name="mod.icon" :size="14" />
        </template>
      </UiContextMenuItem>
    </UiContextMenu>
  </div>
</template>

<style scoped>
.module-launcher {
  display: inline-flex;
  align-items: center;
}
</style>
