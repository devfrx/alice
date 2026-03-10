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
    background: linear-gradient(90deg,
            var(--surface-2) 0%,
            var(--surface-3) 40%,
            var(--surface-2) 80%);
    background-size: 200% 100%;
    animation: shimmer 1.8s ease-in-out infinite;
    border-radius: var(--radius-sm);
}

.ui-skeleton--circle {
    border-radius: 50%;
}

@keyframes shimmer {
    0% {
        background-position: 200% 0;
    }

    100% {
        background-position: -200% 0;
    }
}
</style>
