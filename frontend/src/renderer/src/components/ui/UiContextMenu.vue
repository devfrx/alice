<script setup lang="ts">
/**
 * UiContextMenu — Floating glassmorphism context menu.
 *
 * Usage:
 *   <UiContextMenu :visible="show" :x="posX" :y="posY" @close="show = false">
 *     <UiContextMenuItem label="Edit" @click="edit()">
 *       <template #icon><svg ...></template>
 *     </UiContextMenuItem>
 *     <UiContextMenuDivider />
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
}

function onClickOutside(e: MouseEvent): void {
    if (menuEl.value && !menuEl.value.contains(e.target as Node)) {
        emit('close')
    }
}

function onKeydown(e: KeyboardEvent): void {
    if (e.key === 'Escape') emit('close')
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
    }
)

onUnmounted(() => {
    document.removeEventListener('mousedown', onClickOutside, true)
    document.removeEventListener('keydown', onKeydown, true)
})
</script>

<template>
    <Teleport to="body">
        <Transition name="ctx-fade">
            <div v-if="visible" ref="menuEl" class="ctx-menu" :style="{ left: `${adjustedX}px`, top: `${adjustedY}px` }"
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
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-md);
    user-select: none;
}

.ctx-menu__title {
    padding: var(--space-2) var(--space-3) var(--space-1-5);
    font-size: var(--text-2xs);
    font-weight: var(--weight-semibold);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--text-muted);
}

/* Transition */
.ctx-fade-enter-active {
    transition: opacity 0.1s ease-out, transform 0.1s ease-out;
}

.ctx-fade-leave-active {
    transition: opacity 0.06s ease-in;
}

.ctx-fade-enter-from {
    opacity: 0;
    transform: scale(0.96) translateY(-2px);
}

.ctx-fade-leave-to {
    opacity: 0;
}
</style>