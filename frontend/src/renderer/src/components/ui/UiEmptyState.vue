<script setup lang="ts">
/**
 * UiEmptyState — Generic empty / zero-state component.
 *
 * Used wherever a list, board, or panel has nothing to show. Composes a
 * centred icon orb, a title and an optional subtitle, with a slot for
 * primary actions (typically a UiButton).
 *
 * Visuals follow the cream-on-charcoal theme — no hardcoded colors.
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
        <div v-if="icon" class="ui-empty__orb" aria-hidden="true">
            <AppIcon :name="icon" :size="iconSize" />
        </div>
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
    gap: var(--space-3);
    padding: var(--space-8) var(--space-4);
    color: var(--text-secondary);
    width: 100%;
    height: 100%;
}

.ui-empty--compact {
    gap: var(--space-2);
    padding: var(--space-4);
}

.ui-empty__orb {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 64px;
    height: 64px;
    border-radius: 50%;
    background: var(--accent-dim);
    border: 1px solid var(--accent-border);
    color: var(--accent);
    box-shadow: inset 0 0 24px var(--accent-glow);
}

.ui-empty--compact .ui-empty__orb {
    width: 44px;
    height: 44px;
}

.ui-empty__title {
    margin: 0;
    font-size: var(--text-base);
    font-weight: var(--weight-semibold);
    color: var(--text-primary);
    letter-spacing: 0.01em;
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
