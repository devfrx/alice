<script setup lang="ts">
/**
 * UiDivider — Visual separator for sections and content groups.
 */

export interface UiDividerProps {
    label?: string
    spacing?: 'sm' | 'md' | 'lg'
}

withDefaults(defineProps<UiDividerProps>(), {
    label: '',
    spacing: 'md',
})
</script>

<template>
    <div class="ui-divider" :class="`ui-divider--${spacing}`">
        <div class="ui-divider__line" />
        <span v-if="label" class="ui-divider__label">{{ label }}</span>
        <div v-if="label" class="ui-divider__line" />
    </div>
</template>

<style scoped>
.ui-divider {
    display: flex;
    align-items: center;
    width: 100%;
}

.ui-divider--sm {
    margin: var(--space-2) 0;
}

.ui-divider--md {
    margin: var(--space-4) 0;
}

.ui-divider--lg {
    margin: var(--space-6) 0;
}

.ui-divider__line {
    flex: 1;
    height: 1px;
    background: var(--border);
}

.ui-divider__label {
    padding: 0 var(--space-3);
    font-size: var(--text-2xs);
    font-weight: var(--weight-medium);
    color: var(--text-muted);
    letter-spacing: var(--tracking-wider);
    text-transform: uppercase;
    white-space: nowrap;
}
</style>
