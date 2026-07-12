<script setup lang="ts">
/**
 * AliceSpinner.vue — Compact inline loading spinner.
 *
 * A reusable loading indicator for inline contexts: tool call execution,
 * model loading, STT/TTS initialisation, connection pending states.
 *
 * Two visual variants:
 *   "rings" — two concentric rotating arcs, mirrors the AliceLoader aesthetic
 *             at small sizes.
 *   "dots"  — three sequentially bouncing dots, better for tight horizontal
 *             spaces (e.g. inside a button or status chip).
 *
 * Four sizes:
 *   xs → 14 px  |  sm → 20 px  |  md → 28 px  |  lg → 40 px
 */
withDefaults(
  defineProps<{
    /** Visual size of the spinner. */
    size?: 'xs' | 'sm' | 'md' | 'lg'
    /** Optional text label rendered beside the spinner. */
    label?: string
    /** Spinner style variant. */
    variant?: 'rings' | 'dots'
  }>(),
  {
    size: 'sm',
    variant: 'rings'
  }
)
</script>

<template>
  <span
    class="alice-spinner"
    :class="[`alice-spinner--${size}`, `alice-spinner--${variant}`]"
    role="status"
    :aria-label="label || 'Caricamento in corso'"
  >
    <!-- ── Rings variant ── -->
    <span v-if="variant === 'rings'" class="alice-spinner__rings" aria-hidden="true">
      <!--
        Single SVG block; the viewBox is always 40×40 and the CSS
        width/height are set per-size class.  This keeps the stroke
        proportions consistent no matter which size prop is used.
      -->
      <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
        <!-- Outer arc: clockwise, low opacity -->
        <circle
          class="alice-spinner__ring alice-spinner__ring--outer"
          cx="20"
          cy="20"
          r="17"
          stroke="var(--accent)"
          stroke-width="1.8"
          stroke-dasharray="88 18"
          stroke-linecap="round"
          opacity="0.35"
        />
        <!-- Inner arc: counter-clockwise, higher opacity -->
        <circle
          class="alice-spinner__ring alice-spinner__ring--inner"
          cx="20"
          cy="20"
          r="10"
          stroke="var(--accent)"
          stroke-width="1.8"
          stroke-dasharray="48 14"
          stroke-linecap="round"
          opacity="0.70"
        />
      </svg>
    </span>

    <!-- ── Dots variant ── -->
    <span v-else class="alice-spinner__dots" aria-hidden="true">
      <span class="alice-spinner__dot alice-spinner__dot--1" />
      <span class="alice-spinner__dot alice-spinner__dot--2" />
      <span class="alice-spinner__dot alice-spinner__dot--3" />
    </span>

    <!-- Optional text label -->
    <span v-if="label" class="alice-spinner__label">{{ label }}</span>
  </span>
</template>

<style scoped>
/* ── Root element ────────────────────────────────────────────── */

.alice-spinner {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2, 8px);
  flex-shrink: 0;
  vertical-align: middle;
}

/* ── Size scale (applied to the SVG wrapper) ─────────────────── */

.alice-spinner__rings {
  display: flex;
  align-items: center;
  justify-content: center;
}

.alice-spinner--xs .alice-spinner__rings {
  width: 14px;
  height: 14px;
}

.alice-spinner--sm .alice-spinner__rings {
  width: 20px;
  height: 20px;
}

.alice-spinner--md .alice-spinner__rings {
  width: 28px;
  height: 28px;
}

.alice-spinner--lg .alice-spinner__rings {
  width: 40px;
  height: 40px;
}

.alice-spinner__rings svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}

/* ── Ring keyframes ──────────────────────────────────────────── */

@keyframes aliceSpin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes aliceSpinRev {
  to {
    transform: rotate(-360deg);
  }
}

/* ── Ring animations ─────────────────────────────────────────── */

.alice-spinner__ring {
  transform-origin: 20px 20px;
}

.alice-spinner__ring--outer {
  animation: aliceSpin 2.4s linear infinite;
}

.alice-spinner__ring--inner {
  animation: aliceSpinRev 1.6s linear infinite;
}

/* ── Dots variant ────────────────────────────────────────────── */

.alice-spinner__dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

.alice-spinner--xs .alice-spinner__dot {
  width: 3px;
  height: 3px;
}

.alice-spinner--sm .alice-spinner__dot {
  width: 4px;
  height: 4px;
}

.alice-spinner--md .alice-spinner__dot {
  width: 5px;
  height: 5px;
}

.alice-spinner--lg .alice-spinner__dot {
  width: 7px;
  height: 7px;
}

.alice-spinner__dot {
  border-radius: 50%;
  background: var(--accent);
  animation: aliceDotsJump 1.2s ease-in-out infinite;
}

.alice-spinner__dot--1 {
  animation-delay: 0s;
  opacity: 0.5;
}

.alice-spinner__dot--2 {
  animation-delay: 0.18s;
  opacity: 0.7;
}

.alice-spinner__dot--3 {
  animation-delay: 0.36s;
  opacity: 0.9;
}

@keyframes aliceDotsJump {
  0%,
  80%,
  100% {
    transform: translateY(0);
    opacity: 0.4;
  }

  40% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

/* ── Label ───────────────────────────────────────────────────── */

.alice-spinner__label {
  font-size: var(--text-xs, 11px);
  color: var(--text-muted);
  white-space: nowrap;
}

.alice-spinner--lg .alice-spinner__label {
  font-size: var(--text-sm, 13px);
}

/* ── Reduced Motion ─────────────────────────────────────────── */
/* Convenzione repo (theme.css): niente kill globale, opt-out mirato.
   Con reduce: gli archi si fermano, i dots restano statici e visibili.
   Gli archi statici restano leggibili come indicatore di attività:
   il dasharray lascia un varco visibile su entrambi gli anelli
   (opacity 0.35/0.70 sufficiente su entrambi i temi). */
@media (prefers-reduced-motion: reduce) {
  .alice-spinner__ring--outer,
  .alice-spinner__ring--inner {
    animation: none;
  }

  .alice-spinner__dot {
    animation: none;
    opacity: 0.7;
  }
}
</style>
