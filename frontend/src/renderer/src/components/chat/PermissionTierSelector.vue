<script setup lang="ts">
/**
 * PermissionTierSelector — compact input-bar control to set the conversation's
 * permission tier (Fase 7).
 *
 * The four tiers (strict / auto_edits / plan / autopilot) govern every tool-call
 * the agent makes. The model can NEVER change this — only the user, here. The
 * tier is read/written per-conversation through the `permissionMode` store
 * (REST + the `permission_mode.updated` events-WS push); setting it is not
 * idle-guarded server-side, so it can be changed mid-turn.
 */
import { computed, onMounted, ref, watch } from 'vue'

import UiContextMenu from '../ui/UiContextMenu.vue'
import UiContextMenuItem from '../ui/UiContextMenuItem.vue'
import AppIcon from '../ui/AppIcon.vue'
import type { AppIconName } from '../../assets/icons'
import { useChatStore } from '../../stores/chat'
import { usePermissionModeStore } from '../../stores/permissionMode'
import type { PermissionMode } from '../../types/permission'

interface TierMeta {
  mode: PermissionMode
  label: string
  icon: AppIconName
  hint: string
}

/** Tier presentation metadata (order = the cycle order shown in the menu). */
const TIERS: readonly TierMeta[] = [
  { mode: 'strict', label: 'Conferma', icon: 'shield', hint: 'Chiede conferma per ogni azione sensibile' },
  { mode: 'auto_edits', label: 'Auto-modifiche', icon: 'edit', hint: 'Approva le scritture sicure nello scope; chiede per pericolose/comandi' },
  { mode: 'plan', label: 'Pianifica', icon: 'file-lines', hint: 'Sola lettura: niente scritture né comandi' },
  { mode: 'autopilot', label: 'Autopilota', icon: 'lightning', hint: 'Autonomia totale (i blocchi di sicurezza restano)' },
]

const chatStore = useChatStore()
const modeStore = usePermissionModeStore()

const conversationId = computed<string | null>(() => chatStore.currentConversation?.id ?? null)
const currentMode = computed<PermissionMode>(() => modeStore.modeFor(conversationId.value))
const currentMeta = computed<TierMeta>(
  () => TIERS.find((t) => t.mode === currentMode.value) ?? TIERS[0]
)

const menuVisible = ref(false)
const menuX = ref(0)
const menuY = ref(0)
const triggerRef = ref<HTMLButtonElement | null>(null)

function load(id: string | null): void {
  if (id) void modeStore.ensureForConversation(id)
}
onMounted(() => load(conversationId.value))
watch(conversationId, (id) => load(id))

function openMenu(): void {
  const el = triggerRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  menuX.value = rect.left
  menuY.value = rect.bottom + 4
  menuVisible.value = true
}

function closeMenu(): void {
  menuVisible.value = false
  triggerRef.value?.focus()
}

async function select(mode: PermissionMode): Promise<void> {
  closeMenu()
  const id = conversationId.value
  if (!id || mode === currentMode.value) return
  try {
    await modeStore.setMode(id, mode)
  } catch {
    /* a failed PUT rolls back in the store; nothing to surface here */
  }
}
</script>

<template>
  <div class="tier-selector">
    <button
      ref="triggerRef"
      type="button"
      class="tier-chip"
      :class="`tier-chip--${currentMode}`"
      :disabled="conversationId === null"
      :title="`Permessi: ${currentMeta.label} — ${currentMeta.hint}`"
      :aria-label="`Modalità permessi: ${currentMeta.label}`"
      @click="openMenu"
    >
      <AppIcon :name="currentMeta.icon" :size="14" />
      <span class="tier-chip__label">{{ currentMeta.label }}</span>
    </button>

    <UiContextMenu
      :visible="menuVisible"
      :x="menuX"
      :y="menuY"
      title="Modalità permessi"
      @close="closeMenu"
    >
      <UiContextMenuItem
        v-for="t in TIERS"
        :key="t.mode"
        :label="t.label"
        :hint="t.mode === currentMode ? '✓' : undefined"
        @click="select(t.mode)"
      >
        <template #icon>
          <AppIcon :name="t.icon" :size="14" />
        </template>
      </UiContextMenuItem>
    </UiContextMenu>
  </div>
</template>

<style scoped>
.tier-selector {
  display: inline-flex;
  align-items: center;
}

.tier-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-1) var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-0);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-family: var(--font-sans);
  cursor: pointer;
  white-space: nowrap;
  transition:
    background-color var(--duration-fast) var(--ease-out-quart),
    color var(--duration-fast) var(--ease-out-quart),
    border-color var(--duration-fast) var(--ease-out-quart);
}

.tier-chip:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.tier-chip:disabled {
  opacity: var(--opacity-dim);
  cursor: not-allowed;
}

/* Tier accents — autopilot/plan are visually distinct so the active posture is
   obvious at a glance. */
.tier-chip--autopilot {
  border-color: var(--accent);
  color: var(--accent);
}

.tier-chip--plan {
  border-color: var(--border-strong, var(--border));
  color: var(--text-secondary);
  font-style: italic;
}

.tier-chip__label {
  line-height: 1;
}
</style>
