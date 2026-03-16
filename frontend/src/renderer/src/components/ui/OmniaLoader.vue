<script setup lang="ts">
/**
 * OmniaLoader.vue — Full-screen animated splash loader.
 *
 * Displayed during app startup while the backend initialises, and reusable
 * for any full-screen blocking loading state.
 *
 * The animation is inspired by the OMNIA logo: three concentric rings in
 * warm cream that rotate at different speeds and pulse with a soft glow.
 *
 * Props:
 *   message — Optional status string shown below the logo (defaults to
 *             "Avvio in corso…").
 *   visible — Controls visibility; the component plays a fade+scale-out
 *             transition before unmounting (leave duration: 0.6 s).
 */
withDefaults(
    defineProps<{
        /** Status message shown below the animated logo. */
        message?: string
        /** Show/hide with transition. Set to false to trigger the exit animation. */
        visible?: boolean
    }>(),
    {
        message: 'Avvio in corso…',
        visible: true,
    }
)
</script>

<template>
    <Transition name="omnia-splash-fade">
        <div v-if="visible" class="omnia-splash" role="status" :aria-label="message">
            <!-- Animated logo ─────────────────────────────────── -->
            <div class="omnia-splash__logo" aria-hidden="true">
                <svg class="omnia-splash__svg" viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <!--
            Three concentric rings, each with a stroke-dasharray gap so they
            appear as arcs rather than full circles — this produces the
            "spiral / ripple" visual feel of the original logo.
            Different rotation speeds and directions create depth.
          -->

                    <!-- Outer ring: largest, most transparent, slow clockwise -->
                    <circle class="omnia-splash__ring omnia-splash__ring--outer" cx="60" cy="60" r="52"
                        stroke="var(--accent)" stroke-width="1.2" stroke-dasharray="272 54" stroke-dashoffset="0"
                        stroke-linecap="round" opacity="0.30" />

                    <!-- Mid ring: medium, counter-clockwise, offset dasharray -->
                    <circle class="omnia-splash__ring omnia-splash__ring--mid" cx="60" cy="60" r="37"
                        stroke="var(--accent)" stroke-width="1.5" stroke-dasharray="200 32" stroke-dashoffset="40"
                        stroke-linecap="round" opacity="0.52" />

                    <!-- Inner ring: tightest, clockwise, highest speed -->
                    <circle class="omnia-splash__ring omnia-splash__ring--inner" cx="60" cy="60" r="22"
                        stroke="var(--accent)" stroke-width="1.8" stroke-dasharray="110 28" stroke-dashoffset="15"
                        stroke-linecap="round" opacity="0.72" />

                    <!-- Core dot: always visible, gently pulses in scale -->
                    <circle class="omnia-splash__core" cx="60" cy="60" r="5" fill="var(--accent)" opacity="0.85" />
                </svg>

                <!--
          Glow layer — a blurred, slightly enlarged copy of the SVG that
          sits behind the crisp version to simulate an ambient glow without
          requiring a CSS filter on the animated element (avoids stacking
          context performance issues on low-end hardware).
        -->
                <svg class="omnia-splash__glow" viewBox="0 0 120 120" fill="none" aria-hidden="true">
                    <circle cx="60" cy="60" r="52" stroke="var(--accent)" stroke-width="8" opacity="0.04" />
                    <circle cx="60" cy="60" r="37" stroke="var(--accent)" stroke-width="10" opacity="0.05" />
                    <circle cx="60" cy="60" r="22" stroke="var(--accent)" stroke-width="12" opacity="0.06" />
                    <circle cx="60" cy="60" r="5" fill="var(--accent)" opacity="0.10" />
                </svg>
            </div>

            <!-- Message ─────────────────────────────────────────── -->
            <p class="omnia-splash__message">{{ message }}</p>
        </div>
    </Transition>
</template>

<style scoped>
/* ── Shell ───────────────────────────────────────────────────── */

.omnia-splash {
    position: fixed;
    inset: 0;
    z-index: var(--z-modal);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-8, 32px);
    background: var(--surface-0);
}

/* ── Logo container ──────────────────────────────────────────── */

.omnia-splash__logo {
    position: relative;
    width: 120px;
    height: 120px;
}

.omnia-splash__svg,
.omnia-splash__glow {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    overflow: visible;
}

.omnia-splash__glow {
    filter: blur(10px);
    z-index: -1;
}

/* ── Ring keyframes ──────────────────────────────────────────── */

@keyframes omniaRotateCW {
    to {
        transform: rotate(360deg);
    }
}

@keyframes omniaRotateCCW {
    to {
        transform: rotate(-360deg);
    }
}

@keyframes omniaCorePulse {

    0%,
    100% {
        r: 5;
        opacity: 0.85;
    }

    50% {
        r: 7;
        opacity: 1;
    }
}

@keyframes omniaOpacityBreath {

    0%,
    100% {
        opacity: var(--ring-lo, 0.28);
    }

    50% {
        opacity: var(--ring-hi, 0.55);
    }
}

/* ── Ring animations ─────────────────────────────────────────── */

.omnia-splash__ring {
    transform-origin: 60px 60px;
}

.omnia-splash__ring--outer {
    --ring-lo: 0.22;
    --ring-hi: 0.42;
    animation:
        omniaRotateCW 9s linear infinite,
        omniaOpacityBreath 4s ease-in-out infinite;
}

.omnia-splash__ring--mid {
    --ring-lo: 0.42;
    --ring-hi: 0.68;
    animation:
        omniaRotateCCW 5.5s linear infinite,
        omniaOpacityBreath 3.5s ease-in-out 0.5s infinite;
}

.omnia-splash__ring--inner {
    --ring-lo: 0.60;
    --ring-hi: 0.90;
    animation:
        omniaRotateCW 3.2s linear infinite,
        omniaOpacityBreath 2.8s ease-in-out 0.9s infinite;
}

.omnia-splash__core {
    transform-origin: 60px 60px;
    animation: omniaCorePulse 2.4s ease-in-out infinite;
}

/* ── Message ─────────────────────────────────────────────────── */

.omnia-splash__message {
    font-family: var(--font-sans);
    font-size: var(--text-xs, 11px);
    color: var(--text-muted);
    letter-spacing: 0.12em;
    text-transform: uppercase;
    animation: omniaOpacityBreath 2.4s ease-in-out infinite;
    --ring-lo: 0.45;
    --ring-hi: 0.90;
}

/* ── Enter / leave transitions ───────────────────────────────── */

.omnia-splash-fade-enter-active {
    transition: opacity 0.4s ease;
}

.omnia-splash-fade-leave-active {
    transition: opacity 0.6s ease, transform 0.6s ease;
    pointer-events: none;
}

.omnia-splash-fade-enter-from {
    opacity: 0;
}

.omnia-splash-fade-leave-from {
    opacity: 1;
    transform: scale(1);
}

.omnia-splash-fade-leave-to {
    opacity: 0;
    transform: scale(1.03);
}
</style>
