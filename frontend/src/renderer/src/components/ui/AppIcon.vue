<script setup lang="ts">
/**
 * AppIcon — Centralized icon renderer for AL\CE.
 *
 * Renders any icon from the global registry (assets/icons.ts) using the
 * Iconify Vue component. All icons are served from the locally bundled
 * Solar icon set — no network requests.
 *
 * To change an icon across the whole app, update its entry in icons.ts.
 *
 * @example
 *   <AppIcon name="settings" :size="16" />
 *   <AppIcon name="send" :size="20" />
 */
import { Icon } from '@iconify/vue'
import { ICONS, type AppIconName } from '../../assets/icons'

withDefaults(
  defineProps<{
    /** Icon name from the centralized registry */
    name: AppIconName
    /** Width and height in pixels (default: 16) */
    size?: number | string
    /**
     * Kept for API compatibility with existing call sites.
     * Solar icons are fill-based — stroke-width has no effect.
     */
    strokeWidth?: number | string
  }>(),
  {
    size: 16,
    strokeWidth: 2
  }
)
</script>

<template>
  <!-- eslint-disable vue/no-v-html -- static developer-authored SVG from the local icon registry (assets/icons.ts), not user input -->
  <svg
    v-if="ICONS[name].inner != null"
    :width="size"
    :height="size"
    :viewBox="ICONS[name].viewBox ?? '0 0 24 24'"
    fill="none"
    aria-hidden="true"
    class="app-icon"
    v-html="ICONS[name].inner"
  />
  <!-- eslint-enable vue/no-v-html -->
  <Icon
    v-else
    :icon="ICONS[name].icon!"
    :width="size"
    :height="size"
    aria-hidden="true"
    class="app-icon"
  />
</template>

<style scoped>
.app-icon {
  display: inline-block;
  flex-shrink: 0;
  line-height: 1;
}
</style>
