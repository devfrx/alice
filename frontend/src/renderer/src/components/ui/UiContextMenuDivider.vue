<script setup lang="ts">
/** UiContextMenuDivider — Horizontal separator for context menu groups. */
export interface UiContextMenuDividerProps {
    label?: string
}

withDefaults(defineProps<UiContextMenuDividerProps>(), {
    label: undefined,
})
</script>

<template>
    <div class="ctx-divider">
        <span v-if="label" class="ctx-divider__label">{{ label }}</span>
    </div>
</template>

<style scoped>
.ctx-divider {
    height: 1px;
    margin: var(--space-1) 0;
    background: var(--border);
    position: relative;
}

.ctx-divider__label {
    position: absolute;
    top: 50%;
    left: var(--space-3);
    transform: translateY(-50%);
    padding: 0 var(--space-1);
    background: var(--glass-bg);
    font-size: var(--text-2xs);
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: var(--tracking-wide);
}
</style>
