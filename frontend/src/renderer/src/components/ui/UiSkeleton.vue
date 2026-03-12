<script setup lang="ts">
/**
 * UiSkeleton — Loading placeholder with shimmer effect.
 *
 * Creates smooth, content-shaped loading states.
 * Use width/height props or wrap around content for auto-sizing.
 */

export interface UiSkeletonProps {
    width?: string
    height?: string
    radius?: string
    circle?: boolean
}

withDefaults(defineProps<UiSkeletonProps>(), {
    width: '100%',
    height: '16px',
    radius: '',
    circle: false,
})
</script>

<template>
    <div class="ui-skeleton" :class="{ 'ui-skeleton--circle': circle }" :style="{
        width: circle ? height : width,
        height,
        borderRadius: circle ? '50%' : radius || undefined,
    }" />
</template>

<style scoped>
.ui-skeleton {
    background: var(--surface-2);
    border-radius: var(--radius-sm);
    animation: skeleton-pulse 1.5s ease infinite;
}

.ui-skeleton--circle {
    border-radius: var(--radius-full);
}

@keyframes skeleton-pulse {

    0%,
    100% {
        opacity: 0.4;
    }

    50% {
        opacity: 0.8;
    }
}
</style>
