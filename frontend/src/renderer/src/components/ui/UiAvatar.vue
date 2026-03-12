<script setup lang="ts">
/**
 * UiAvatar — User/agent avatar with status indicator.
 */

export interface UiAvatarProps {
    label?: string
    size?: 'sm' | 'md' | 'lg'
    variant?: 'user' | 'agent'
    status?: 'online' | 'busy' | 'offline' | ''
}

withDefaults(defineProps<UiAvatarProps>(), {
    label: '',
    size: 'md',
    variant: 'agent',
    status: '',
})
</script>

<template>
    <div class="ui-avatar" :class="[`ui-avatar--${size}`, `ui-avatar--${variant}`]">
        <span class="ui-avatar__letter">{{ label ? label[0].toUpperCase() : (variant === 'agent' ? 'O' : 'U') }}</span>
        <span v-if="status" class="ui-avatar__status" :class="`ui-avatar__status--${status}`" />
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
.ui-avatar--sm {
    width: 24px;
    height: 24px;
    font-size: var(--text-2xs);
}

.ui-avatar--md {
    width: 32px;
    height: 32px;
    font-size: var(--text-xs);
}

.ui-avatar--lg {
    width: 40px;
    height: 40px;
    font-size: var(--text-sm);
}

/* ── Variants ─── */
.ui-avatar--agent {
    background: var(--accent-dim);
    color: var(--accent);
}

.ui-avatar--user {
    background: var(--surface-3);
    color: var(--text-secondary);
}

.ui-avatar__letter {
    line-height: 1;
    letter-spacing: var(--tracking-tight);
}

/* ── Status Dot ─── */
.ui-avatar__status {
    position: absolute;
    bottom: -1px;
    right: -1px;
    width: 8px;
    height: 8px;
    border-radius: var(--radius-full);
    border: 2px solid var(--surface-0);
}

.ui-avatar__status--online {
    background: var(--success);
}

.ui-avatar__status--busy {
    background: var(--warning);
}

.ui-avatar__status--offline {
    background: var(--text-muted);
}
</style>
