<script setup lang="ts">
/**
 * PlanModule — Workspace tile showing the active conversation's plan.
 *
 * ## Param keys (params?: Record<string, unknown>)
 * None consumed. The plan is per-conversation, so the module derives its
 * subject from the chat store's current conversation rather than tile params.
 *
 * ## Data flow
 * On mount and whenever the conversation changes, the plan is fetched once via
 * {@link usePlanStore.ensureForConversation}. Live updates arrive out-of-band
 * through the `plan.updated` events-WS frame (folded by the plan store), so no
 * polling is needed here.
 *
 * ## Fallback
 * A {@link UiEmptyState} is rendered until the conversation has any plan steps.
 */
import { computed, onMounted, watch } from 'vue'

import UiEmptyState from '../../ui/UiEmptyState.vue'
import PlanStepList from './PlanStepList.vue'
import { useChatStore } from '../../../stores/chat'
import { usePlanStore } from '../../../stores/plan'

defineProps<{
  params?: Record<string, unknown>
}>()

const chatStore = useChatStore()
const planStore = usePlanStore()

/** Active conversation id, or null when none is open. */
const conversationId = computed<string | null>(() => chatStore.currentConversation?.id ?? null)

/** Plan steps for the active conversation (empty when none). */
const steps = computed(() => (conversationId.value ? planStore.planFor(conversationId.value) : []))

/** Fetch-once the plan for a given conversation id. */
function load(id: string | null): void {
  if (id) void planStore.ensureForConversation(id)
}

onMounted(() => load(conversationId.value))
watch(conversationId, (id) => load(id))
</script>

<template>
  <div class="plan-module">
    <div v-if="steps.length > 0" class="plan-module__scroll">
      <PlanStepList :steps="steps" />
    </div>
    <UiEmptyState
      v-else
      icon="file-lines"
      title="Nessun piano"
      subtitle="Il piano comparirà qui quando l'assistente inizierà a pianificare."
    />
  </div>
</template>

<style scoped>
.plan-module {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Scrollable step list fills the height of the tile. */
.plan-module__scroll {
  flex: 1 1 0;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-4);
}
</style>
