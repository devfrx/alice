<script setup lang="ts">
/**
 * AmbientBackground.vue — Ambient particle and wave background.
 * Creates a living, breathing atmosphere behind the main content.
 * Pure CSS for performance (no canvas).
 */

withDefaults(defineProps<{
    state: 'idle' | 'listening' | 'thinking' | 'speaking' | 'processing'
    audioLevel: number
    subtle?: boolean
}>(), {
    subtle: false
})
</script>

<template>
    <div class="ambient" :class="[`ambient--${state}`, { 'ambient--subtle': subtle }]" aria-hidden="true">
        <!-- Gradient mesh background -->
        <div class="ambient__mesh" />

        <!-- Floating particles -->
        <div class="ambient__particles">
            <span v-for="i in 20" :key="i" class="ambient__particle" :style="{
                '--delay': `${(i * 1.7) % 8}s`,
                '--duration': `${12 + (i * 2.3) % 10}s`,
                '--x-start': `${(i * 13) % 100}%`,
                '--y-start': `${(i * 17) % 100}%`,
                '--size': `${1.5 + (i * 0.3) % 3}px`,
                '--opacity': `${0.1 + (i * 0.02) % 0.3}`,
            }" />
        </div>

        <!-- Gradient waves (bottom) -->
        <div class="ambient__waves">
            <div class="ambient__wave ambient__wave--1" />
            <div class="ambient__wave ambient__wave--2" />
            <div class="ambient__wave ambient__wave--3" />
        </div>

        <!-- Radial spotlight (follows state) -->
        <div class="ambient__spotlight" />

        <!-- Grid lines (very subtle) -->
        <div class="ambient__grid" />
    </div>
</template>

<style scoped>
/* Ultra-subtle ambient background — barely visible */
.ambient {
    position: absolute;
    inset: 0;
    z-index: 0;
    overflow: hidden;
    pointer-events: none;
}

.ambient--subtle .ambient__particles,
.ambient--subtle .ambient__waves {
    opacity: 0.2;
}

/* ── Gradient Mesh — single soft radial ── */
.ambient__mesh {
    position: absolute;
    inset: 0;
    background: radial-gradient(ellipse at 50% 40%, var(--accent-faint) 0%, transparent 70%);
    transition: background var(--transition-slow);
}

.ambient--listening .ambient__mesh {
    background: radial-gradient(ellipse at 50% 40%, var(--listening-dim) 0%, transparent 70%);
}

.ambient--thinking .ambient__mesh {
    background: radial-gradient(ellipse at 50% 40%, var(--thinking-dim) 0%, transparent 70%);
}

.ambient--speaking .ambient__mesh {
    background: radial-gradient(ellipse at 50% 40%, var(--speaking-dim) 0%, transparent 70%);
}

/* ── Particles — hidden for clean look ── */
.ambient__particles {
    position: absolute;
    inset: 0;
    display: none;
}

.ambient__particle {
    display: none;
}

/* ── Waves — hidden ── */
.ambient__waves {
    display: none;
}

.ambient__wave {
    display: none;
}

/* ── Spotlight — very subtle center glow ── */
.ambient__spotlight {
    position: absolute;
    top: 50%;
    left: 50%;
    width: 50%;
    height: 50%;
    transform: translate(-50%, -50%);
    border-radius: var(--radius-full);
    background: radial-gradient(circle, var(--accent-faint) 0%, transparent 70%);
    opacity: 0.5;
    transition: opacity var(--transition-slow), background var(--transition-slow);
}

.ambient--thinking .ambient__spotlight {
    opacity: 0.7;
}

.ambient--listening .ambient__spotlight {
    background: radial-gradient(circle, var(--listening-dim) 0%, transparent 70%);
    opacity: 0.4;
}

.ambient--speaking .ambient__spotlight {
    background: radial-gradient(circle, var(--speaking-dim) 0%, transparent 70%);
    opacity: 0.4;
}

/* ── Grid — hidden ── */
.ambient__grid {
    display: none;
}
</style>
