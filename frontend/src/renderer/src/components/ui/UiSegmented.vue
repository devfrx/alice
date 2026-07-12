<script setup lang="ts">
/**
 * UiSegmented — Shared segmented control / tab switch.
 *
 * The single, reusable tab primitive for AL\CE, generalized from the sidebar
 * mode tabs. A sliding accent indicator glides under the active option; the
 * indicator is *measured* from the active tab's real geometry, so it works for
 * any number of options and any tab widths (equal or content-sized).
 *
 * Controlled: bind `modelValue` and listen to `update:modelValue`.
 *
 * @example
 *   <UiSegmented
 *     v-model="tab"
 *     :options="[{ value: 'a', label: 'A', icon: 'home' }, { value: 'b', label: 'B' }]"
 *     aria-label="Sezione"
 *   />
 */
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
  type ComponentPublicInstance
} from 'vue'
import AppIcon from './AppIcon.vue'
import type { AppIconName } from '../../assets/icons'

/** A single selectable segment. */
export interface UiSegmentedOption {
  /** Value emitted when selected. */
  value: string | number
  /** Visible label. */
  label: string
  /** Optional leading icon. */
  icon?: AppIconName
  /** Optional trailing count badge. */
  badge?: string | number
}

const props = withDefaults(
  defineProps<{
    /** Currently selected value (null = none active → indicator hidden). */
    modelValue: string | number | null
    /** The segments to render. */
    options: UiSegmentedOption[]
    /** Density; default `'md'`. */
    size?: 'sm' | 'md'
    /** Accessible label for the tablist. */
    ariaLabel?: string
    /** Equal-width segments (default) or content-sized. */
    equal?: boolean
  }>(),
  { size: 'md', ariaLabel: undefined, equal: true }
)

const emit = defineEmits<{
  'update:modelValue': [value: string | number]
}>()

const containerRef = ref<HTMLElement | null>(null)
/** Per-segment element refs, indexed positionally. */
const tabEls = ref<(HTMLElement | null)[]>([])

function setTabRef(el: Element | ComponentPublicInstance | null, index: number): void {
  tabEls.value[index] = (el as HTMLElement | null) ?? null
}

const activeIndex = computed(() => props.options.findIndex((o) => o.value === props.modelValue))

/** Inline style for the sliding indicator, measured from the active tab. */
const indicatorStyle = ref<Record<string, string>>({ opacity: '0' })

function updateIndicator(): void {
  const index = activeIndex.value
  const el = index >= 0 ? tabEls.value[index] : null
  if (!el) {
    indicatorStyle.value = { ...indicatorStyle.value, opacity: '0' }
    return
  }
  indicatorStyle.value = {
    transform: `translateX(${el.offsetLeft}px)`,
    width: `${el.offsetWidth}px`,
    opacity: '1'
  }
}

function select(option: UiSegmentedOption): void {
  emit('update:modelValue', option.value)
}

let resizeObserver: ResizeObserver | null = null

watch([activeIndex, () => props.options.length], () => nextTick(updateIndicator))

onMounted(() => {
  nextTick(updateIndicator)
  if (typeof ResizeObserver !== 'undefined' && containerRef.value) {
    resizeObserver = new ResizeObserver(() => updateIndicator())
    resizeObserver.observe(containerRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div
    ref="containerRef"
    class="ui-seg"
    :class="[`ui-seg--${size}`, { 'ui-seg--equal': equal }]"
    role="tablist"
    :aria-label="ariaLabel"
  >
    <!-- Sliding active indicator (measured from the active tab). -->
    <span class="ui-seg__indicator" :style="indicatorStyle" aria-hidden="true" />

    <button
      v-for="(opt, i) in options"
      :key="opt.value"
      :ref="(el) => setTabRef(el, i)"
      type="button"
      role="tab"
      :aria-selected="opt.value === modelValue"
      class="ui-seg__tab"
      :class="{ 'ui-seg__tab--active': opt.value === modelValue }"
      @click="select(opt)"
    >
      <AppIcon v-if="opt.icon" :name="opt.icon" :size="14" class="ui-seg__icon" />
      <span class="ui-seg__label">{{ opt.label }}</span>
      <span v-if="opt.badge !== undefined" class="ui-seg__badge">{{ opt.badge }}</span>
    </button>
  </div>
</template>

<style scoped>
.ui-seg {
  position: relative;
  display: flex;
  gap: var(--space-1);
  min-width: 0;
}

/* Equal-width segments (the sidebar reference look). */
.ui-seg--equal .ui-seg__tab {
  flex: 1 1 0;
  min-width: 0;
}

/* ── Sliding indicator ── */
.ui-seg__indicator {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  border-radius: var(--radius-sm);
  background: var(--accent-dim);
  box-shadow: var(--shadow-xs);
  pointer-events: none;
  z-index: 0;
  transition:
    transform var(--duration-moderate) var(--ease-out-expo),
    width var(--duration-moderate) var(--ease-out-expo),
    opacity var(--duration-normal) ease;
}

/* ── Tab ── */
.ui-seg__tab {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1-5);
  padding: 0 var(--space-2-5);
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-weight: var(--weight-medium);
  white-space: nowrap;
  cursor: pointer;
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.ui-seg--md .ui-seg__tab {
  min-height: 34px;
  font-size: var(--text-xs);
}

.ui-seg--sm .ui-seg__tab {
  min-height: 28px;
  font-size: var(--text-2xs);
}

/* Hover only on the inactive tab so it never paints over the indicator. */
.ui-seg__tab:not(.ui-seg__tab--active):hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}

.ui-seg__tab--active {
  color: var(--text-primary);
}

.ui-seg__tab--active .ui-seg__icon {
  color: var(--accent);
}

.ui-seg__icon {
  flex-shrink: 0;
  color: var(--text-muted);
  transition: color var(--transition-fast);
}

.ui-seg__label {
  overflow: hidden;
  text-overflow: ellipsis;
}

.ui-seg__badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 var(--space-1);
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: var(--text-on-accent);
  font-size: var(--text-2xs);
  font-weight: var(--weight-bold);
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

@media (prefers-reduced-motion: reduce) {
  .ui-seg__indicator {
    transition: opacity var(--duration-normal) ease;
  }
}
</style>
