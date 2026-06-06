<script setup lang="ts">
/**
 * UiPopover — Shared teleported floating panel (the unified floating recipe).
 *
 * A controlled (`open` prop + `update:open` emit) panel teleported to
 * `<body>` and anchored to an arbitrary trigger element via
 * {@link useFloatingPosition}. It bakes in AL\CE's single floating recipe —
 * `--surface-2` chrome, `1px solid var(--border)`, `--radius-md`,
 * `--shadow-dropdown`, `--z-dropdown`, NO glass/backdrop-filter — plus a
 * subtle fade + translateY transition.
 *
 * The host stays in control of open-state: this component never flips `open`
 * itself, it only *requests* a close (outside-click / Escape) by emitting
 * `update:open=false` and `close`.
 *
 * @example
 *   <button ref="triggerRef" @click="open = !open">Menu</button>
 *   <UiPopover :open="open" :anchor-el="triggerRef" @update:open="open = $event">
 *     <ul>…</ul>
 *   </UiPopover>
 */
import { onBeforeUnmount, ref, toRef, watch } from 'vue'
import {
  useFloatingPosition,
  type FloatingAlign,
  type FloatingPlacement,
} from '../../composables/useFloatingPosition'

const props = withDefaults(
  defineProps<{
    /** Controlled open state. */
    open: boolean
    /** Trigger element the panel anchors to. */
    anchorEl: HTMLElement | null
    /** Preferred side; default `'bottom'`. */
    placement?: FloatingPlacement
    /** Horizontal alignment to the anchor; default `'start'`. */
    align?: FloatingAlign
    /** Gap in px between anchor and panel; default `8`. */
    offset?: number
    /** Match the panel's `min-width` to the anchor width. */
    matchWidth?: boolean
    /** Optional fixed panel width (CSS length, e.g. `'320px'`). */
    width?: string
    /** Close when clicking outside the panel and anchor; default `true`. */
    closeOnOutside?: boolean
    /** Close on Escape; default `true`. */
    closeOnEsc?: boolean
    /** Extra class applied to the `.ui-popover` panel. */
    panelClass?: string
    /** Accessible label for the panel. */
    ariaLabel?: string
  }>(),
  {
    placement: 'bottom',
    align: 'start',
    offset: 8,
    matchWidth: false,
    width: undefined,
    closeOnOutside: true,
    closeOnEsc: true,
    panelClass: undefined,
    ariaLabel: undefined,
  },
)

const emit = defineEmits<{
  'update:open': [value: boolean]
  close: []
}>()

/** The teleported panel element (for positioning + outside-click). */
const panelRef = ref<HTMLElement | null>(null)
/** Anchor as a ref so the composable can react to anchor changes. */
const anchorRef = toRef(props, 'anchorEl')
const openRef = toRef(props, 'open')

const { floatingStyle, update } = useFloatingPosition(anchorRef, panelRef, openRef, {
  placement: props.placement,
  align: props.align,
  offset: props.offset,
  matchWidth: props.matchWidth,
})

/** Request a close (host owns the actual state). */
function requestClose(): void {
  emit('update:open', false)
  emit('close')
}

function onMousedown(event: MouseEvent): void {
  if (!props.open || !props.closeOnOutside) return
  const target = event.target as Node | null
  if (!target) return
  const insidePanel = panelRef.value?.contains(target) ?? false
  // Clicks on the anchor are owned by the trigger (it toggles open itself);
  // ignore them here so the panel doesn't immediately reopen-then-close.
  const insideAnchor = props.anchorEl?.contains(target) ?? false
  if (!insidePanel && !insideAnchor) {
    requestClose()
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (props.open && props.closeOnEsc && event.key === 'Escape') {
    event.stopPropagation()
    requestClose()
  }
}

function addListeners(): void {
  document.addEventListener('mousedown', onMousedown)
  document.addEventListener('keydown', onKeydown)
}

function removeListeners(): void {
  document.removeEventListener('mousedown', onMousedown)
  document.removeEventListener('keydown', onKeydown)
}

watch(
  () => props.open,
  (open) => {
    if (open) addListeners()
    else removeListeners()
  },
  { immediate: true },
)

onBeforeUnmount(removeListeners)

// Expose `update` so consumers can force a reposition after content changes.
defineExpose({ update })
</script>

<template>
  <Teleport to="body">
    <Transition name="ui-popover">
      <div
        v-if="open"
        ref="panelRef"
        class="ui-popover"
        :class="panelClass"
        role="dialog"
        :aria-label="ariaLabel"
        :style="[floatingStyle, width ? { width } : {}]"
      >
        <slot />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* ── The unified floating recipe ── */
.ui-popover {
  /* position/top/left/bottom/min-width set inline via floatingStyle */
  padding: var(--space-1-5);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-dropdown);
  /* Transient menus/selects render above modals (they can be opened from
     inside a dialog) — see --z-popover in theme.css. */
  z-index: var(--z-popover);
  /* NO glass / NO backdrop-filter — solid surface only. */
}

/* ── Transition: subtle fade + translateY (mirrors ctc-pop / ms-drop) ── */
.ui-popover-enter-active,
.ui-popover-leave-active {
  transition:
    opacity var(--duration-fast) var(--ease-out-quart),
    transform var(--duration-fast) var(--ease-out-quart);
}

.ui-popover-enter-from,
.ui-popover-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
</style>
