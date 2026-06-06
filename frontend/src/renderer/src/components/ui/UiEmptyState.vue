<script setup lang="ts">
/**
 * UiEmptyState — Generic empty / zero-state component.
 *
 * Used wherever a list, board, or panel has nothing to show. Composes a
 * plain muted icon, a title and an optional subtitle, with a slot for
 * primary actions (typically a UiButton).
 *
 * Restrained Claude-style aesthetic — no orb / glow, all tokenized.
 */
import AppIcon from './AppIcon.vue'
import type { AppIconName } from '../../assets/icons'

withDefaults(
    defineProps<{
        /** Iconify name from the AL\\CE icon registry. */
        icon?: AppIconName
        /** Title shown in primary text color. */
        title: string
        /** Optional subtitle shown muted below the title. */
        subtitle?: string
        /** Visual size of the icon (px). */
        iconSize?: number
        /** Compact mode reduces vertical spacing. */
        compact?: boolean
    }>(),
    { icon: undefined, subtitle: '', iconSize: 32, compact: false },
)
</script>

<template>
    <div class="ui-empty" :class="{ 'ui-empty--compact': compact }" role="status">
        <AppIcon v-if="icon" :name="icon" :size="iconSize" class="ui-empty__icon" aria-hidden="true" />
        <p class="ui-empty__title">{{ title }}</p>
        <p v-if="subtitle" class="ui-empty__subtitle">{{ subtitle }}</p>
        <div v-if="$slots.actions" class="ui-empty__actions">
            <slot name="actions" />
        </div>
    </div>
</template>

<style scoped>
.ui-empty {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    gap: var(--space-2);
    padding: var(--space-6) var(--space-4);
    color: var(--text-muted);
    width: 100%;
    height: 100%;
}

.ui-empty--compact {
    gap: var(--space-1-5);
    padding: var(--space-3);
}

.ui-empty__icon {
    color: var(--text-muted);
    opacity: 0.4;
}

.ui-empty__title {
    margin: 0;
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-secondary);
}

.ui-empty__subtitle {
    margin: 0;
    max-width: 38ch;
    font-size: var(--text-xs);
    color: var(--text-muted);
    line-height: var(--leading-relaxed);
}

.ui-empty__actions {
    margin-top: var(--space-3);
    display: inline-flex;
    gap: var(--space-2);
}
</style>
