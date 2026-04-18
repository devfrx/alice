<script setup lang="ts">
/**
 * UiContextMenu — Floating glassmorphism context menu.
 *
 * Features:
 *  - Auto-reposition so the menu never overflows the viewport.
 *  - Closes on Esc, outside click, or when visibility prop flips to false.
 *  - Keyboard navigation: ArrowUp / ArrowDown cycle between focusable
 *    items; focus is trapped within the menu while it is open.
 *  - Initial focus moves to the first enabled item on open (so the user
 *    can immediately use the arrow keys without reaching for the mouse).
 *
 * Usage:
 *   <UiContextMenu :visible="show" :x="posX" :y="posY" @close="show = false">
 *     <UiContextMenuItem label="Edit" @click="edit()" />
 *     <UiContextMenuDivider />
 *     <UiContextMenuItem label="Delete" danger @click="del()" />
 *   </UiContextMenu>
 */
import { ref, watch, onUnmounted, nextTick } from 'vue'

export interface UiContextMenuProps {
    visible: boolean
    x: number
    y: number
    title?: string
}

const props = withDefaults(defineProps<UiContextMenuProps>(), {
    title: undefined,
})
const emit = defineEmits<{ close: [] }>()

const menuEl = ref<HTMLDivElement | null>(null)
const adjustedX = ref(0)
const adjustedY = ref(0)

/** Query all focusable items rendered inside the menu slot. */
function focusableItems(): HTMLElement[] {
    if (!menuEl.value) return []
    return Array.from(
        menuEl.value.querySelectorAll<HTMLElement>(
            'button:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
    )
}

async function adjustPosition(): Promise<void> {
    await nextTick()
    const el = menuEl.value
    if (!el) {
        adjustedX.value = props.x
        adjustedY.value = props.y
        return
    }
    const rect = el.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight

    adjustedX.value = props.x + rect.width > vw ? vw - rect.width - 4 : props.x
    adjustedY.value = props.y + rect.height > vh ? vh - rect.height - 4 : props.y

    // Move initial focus to the first enabled item so arrow keys work
    // immediately. Falls back to the menu container itself.
    const items = focusableItems()
    if (items.length > 0) items[0]!.focus()
    else el.focus()
}

function onClickOutside(e: MouseEvent): void {
    if (menuEl.value && !menuEl.value.contains(e.target as Node)) {
        emit('close')
    }
}

function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') {
        emit('close')
        return
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return

    const items = focusableItems()
    if (items.length === 0) return
    const active = document.activeElement as HTMLElement | null
    const currentIdx = active ? items.indexOf(active) : -1

    let nextIdx = currentIdx
    if (e.key === 'ArrowDown') nextIdx = currentIdx < items.length - 1 ? currentIdx + 1 : 0
    else if (e.key === 'ArrowUp') nextIdx = currentIdx > 0 ? currentIdx - 1 : items.length - 1
    else if (e.key === 'Home') nextIdx = 0
    else if (e.key === 'End') nextIdx = items.length - 1

    e.preventDefault()
    items[nextIdx]!.focus()
}

watch(
    () => props.visible,
    (v) => {
        if (v) {
            adjustPosition()
            document.addEventListener('mousedown', onClickOutside, true)
            document.addEventListener('keydown', onKeydown, true)
        } else {
            document.removeEventListener('mousedown', onClickOutside, true)
            document.removeEventListener('keydown', onKeydown, true)
        }
    },
)

onUnmounted(() => {
    document.removeEventListener('mousedown', onClickOutside, true)
    document.removeEventListener('keydown', onKeydown, true)
})
</script>

<template>
    <Teleport to="body">
        <Transition name="ctx-fade">
            <div v-if="visible" ref="menuEl" class="ctx-menu" role="menu" tabindex="-1"
                :aria-label="title || 'Context menu'" :style="{ left: `${adjustedX}px`, top: `${adjustedY}px` }"
                @contextmenu.prevent>
                <div v-if="title" class="ctx-menu__title">{{ title }}</div>
                <slot />
            </div>
        </Transition>
    </Teleport>
</template>

<style scoped>
.ctx-menu {
    position: fixed;
    z-index: var(--z-dropdown);
    min-width: 180px;
    padding: var(--space-1) 0;
    background: var(--glass-bg);
    backdrop-filter: blur(var(--glass-blur));
    -webkit-backdrop-filter: blur(var(--glass-blur));
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
    user-select: none;
    outline: none;
}

.ctx-menu:focus-visible {
    box-shadow: var(--shadow-focus);
}

.ctx-menu__title {
    padding: var(--space-2) var(--space-3) var(--space-1-5);
    font-size: var(--text-2xs);
    font-weight: var(--weight-semibold);
    text-transform: uppercase;
    letter-spacing: var(--tracking-wide);
    color: var(--text-muted);
}

/* Transition */
.ctx-fade-enter-active {
    transition:
        opacity var(--duration-fast) var(--ease-out-quart),
        transform var(--duration-fast) var(--ease-out-quart);
}

.ctx-fade-leave-active {
    transition: opacity var(--duration-instant) ease-in;
}

.ctx-fade-enter-from {
    opacity: 0;
    transform: scale(0.96) translateY(-2px);
}

.ctx-fade-leave-to {
    opacity: 0;
}
</style>