<script setup lang="ts">
withDefaults(
    defineProps<{
        brand?: 'alce' | 'continuum'
        variant?: 'mark' | 'text' | 'desktop'
        label?: string
    }>(),
    {
        brand: 'alce',
        variant: 'mark',
        label: undefined,
    },
)
</script>

<template>
    <span class="brand-asset" :class="[`brand-asset--${brand}`, `brand-asset--${variant}`]" :aria-label="label"
        :aria-hidden="label ? undefined : 'true'" role="img" />
</template>

<style scoped>
.brand-asset {
    display: inline-block;
    flex: 0 0 auto;
    background-repeat: no-repeat;
    background-position: center;
    background-size: contain;
}

.brand-asset--mark {
    width: var(--space-6);
    height: var(--space-6);
}

.brand-asset--text {
    width: calc(var(--space-20) + var(--space-1));
    height: var(--space-5);
}

.brand-asset--desktop {
    width: var(--space-8);
    height: var(--space-8);
}

.brand-asset--alce.brand-asset--mark {
    background-image: var(--brand-alce-logo);
}

.brand-asset--alce.brand-asset--text {
    background-image: var(--brand-alce-text-logo);
}

.brand-asset--alce.brand-asset--desktop {
    background-image: var(--brand-alce-desktop-logo);
}

.brand-asset--continuum.brand-asset--mark {
    background-image: var(--brand-continuum-logo);
}

.brand-asset--continuum.brand-asset--text {
    background-image: var(--brand-continuum-text-logo);
}

.brand-asset--continuum.brand-asset--desktop {
    background-image: var(--brand-continuum-desktop-logo);
}
</style>