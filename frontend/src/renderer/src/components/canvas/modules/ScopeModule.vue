<script setup lang="ts">
/**
 * ScopeModule — Workspace tile for the conversation's workspace folder scope.
 *
 * Promotes the (previously Terminal-embedded) {@link ScopeManager} to a
 * first-class, session-level module: the scope is the workspace boundary for
 * the whole agentic session — every filesystem tool is confined to it, not just
 * the terminal. {@link ScopeManager} is self-contained (it derives its
 * conversation from the chat store and owns its own scroll), so this adapter is
 * a thin host tile.
 *
 * ## Param keys (params?: Record<string, unknown>)
 * None consumed.
 */
import ScopeManager from '../ScopeManager.vue'

defineProps<{
  params?: Record<string, unknown>
}>()
</script>

<template>
  <div class="scope-module">
    <ScopeManager />
  </div>
</template>

<style scoped>
.scope-module {
  width: 100%;
  height: 100%;
  display: flex;
  overflow: hidden;
}
</style>
