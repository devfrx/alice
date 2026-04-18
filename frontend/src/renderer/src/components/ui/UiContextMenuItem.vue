<script setup lang="ts">
/**
 * UiContextMenuItem — Single action row inside a UiContextMenu.
 *
 * Supports an SVG icon via the #icon slot, a text label, an optional
 * right-aligned hint, and danger / disabled variants.
 */
export interface UiContextMenuItemProps {
    label: string
    hint?: string
    danger?: boolean
    disabled?: boolean
}

withDefaults(defineProps<UiContextMenuItemProps>(), {
    hint: undefined,
    danger: false,
    disabled: false,
})

const emit = defineEmits<{ click: [] }>()
</script>

<template>
    <button type="button" role="menuitem" class="ctx-item"
        :class="{ 'ctx-item--danger': danger, 'ctx-item--disabled': disabled }" :disabled="disabled"
        :aria-disabled="disabled || undefined" @click="emit('click')">
        <span class="ctx-item__icon" aria-hidden="true">
            <slot name="icon" />
        </span>
        <span class="ctx-item__label">{{ label }}</span>
        <span v-if="hint" class="ctx-item__hint">{{ hint }}</span>
    </button>
</template>

<style scoped>
.ctx-item {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    width: 100%;
    padding: var(--space-2) var(--space-3);
    border: none;
    background: transparent;
    color: var(--text-primary);
    font-size: var(--text-sm);
    font-family: var(--font-sans);
    cursor: pointer;
    text-align: left;
    white-space: nowrap;
    outline: none;
    transition: background-color var(--duration-fast) var(--ease-out-quart);
}

.ctx-item:hover:not(:disabled),
.ctx-item:focus-visible:not(:disabled) {
    background: var(--surface-hover);
}

.ctx-item:focus-visible { box-shadow: var(--shadow-focus); }

.ctx-item:active:not(:disabled) { background: var(--surface-active); }

.ctx-item--danger { color: var(--danger); }
.ctx-item--danger:hover:not(:disabled),
.ctx-item--danger:focus-visible:not(:disabled) { background: var(--danger-faint); }

.ctx-item--disabled {
    color: var(--text-muted);
    cursor: not-allowed;
    opacity: var(--opacity-dim);
}

.ctx-item__icon {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 16px;
    height: 16px;
    color: var(--text-secondary);
}

.ctx-item--danger .ctx-item__icon { color: var(--danger); }

.ctx-item__label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
}

.ctx-item__hint {
    font-size: var(--text-2xs);
    color: var(--text-muted);
    margin-left: var(--space-4);
}
</style>
