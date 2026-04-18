<script setup lang="ts">
/**
 * UiAvatar — User / agent avatar with optional status indicator.
 *
 * Renders a circular monogram (first letter of `label`, falling back to
 * "O" for agent and "U" for user). Use `ariaLabel` to expose a
 * screen-reader-friendly name (defaults to `label`).
 */

export interface UiAvatarProps {
    label?: string
    size?: 'sm' | 'md' | 'lg'
    variant?: 'user' | 'agent'
    status?: 'online' | 'busy' | 'offline' | ''
    /** Overrides the default accessible name (defaults to `label`). */
    ariaLabel?: string
}

const props = withDefaults(defineProps<UiAvatarProps>(), {
    label: '',
    size: 'md',
    variant: 'agent',
    status: '',
    ariaLabel: undefined,
})

const monogram = (): string => {
    if (props.label) return props.label[0]!.toUpperCase()
    return props.variant === 'agent' ? 'O' : 'U'
}
</script>

<template>
    <div class="ui-avatar" :class="[`ui-avatar--${size}`, `ui-avatar--${variant}`]" role="img"
        :aria-label="ariaLabel || label || variant">
        <span class="ui-avatar__letter" aria-hidden="true">{{ monogram() }}</span>
        <span v-if="status" class="ui-avatar__status" :class="`ui-avatar__status--${status}`" aria-hidden="true" />
    </div>
</template>

<style scoped>
.ui-avatar {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: var(--radius-full);
    flex-shrink: 0;
    font-weight: var(--weight-medium);
}

/* ── Sizes ─── */
.ui-avatar--sm { width: 24px; height: 24px; font-size: var(--text-2xs); }
.ui-avatar--md { width: 32px; height: 32px; font-size: var(--text-xs); }
.ui-avatar--lg { width: 40px; height: 40px; font-size: var(--text-sm); }

/* ── Variants ─── */
.ui-avatar--agent { background: var(--accent-dim); color: var(--accent); }
.ui-avatar--user  { background: var(--surface-3); color: var(--text-secondary); }

.ui-avatar__letter {
    line-height: var(--leading-tight);
    letter-spacing: var(--tracking-tight);
}

/* ── Status Dot ─── */
.ui-avatar__status {
    position: absolute;
    bottom: 0;
    right: 0;
    width: 8px;
    height: 8px;
    border-radius: var(--radius-full);
    border: 2px solid var(--surface-0);
    transform: translate(15%, 15%);
}

.ui-avatar__status--online  { background: var(--success); }
.ui-avatar__status--busy    { background: var(--warning); }
.ui-avatar__status--offline { background: var(--text-muted); }
</style>
