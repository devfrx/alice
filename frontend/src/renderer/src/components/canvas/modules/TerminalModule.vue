<script setup lang="ts">
/**
 * TerminalModule — Read-only workspace tile for the scoped Terminal plugin.
 *
 * ## Param keys (params?: Record<string, unknown>)
 * None consumed. The terminal is per-conversation, so the module derives its
 * subject from the chat store's current conversation rather than tile params.
 *
 * ## Layout
 * - **Top (non-scrolling):** an embedded {@link ScopeManager} — the folder
 *   scope the model's `run_terminal_command` calls are confined to. It is
 *   self-contained (derives its own conversation from the chat store) and owns
 *   its internal scroll, so it is given a capped flex region here.
 * - **Below (scrollable):** a chronological log of `run_terminal_command`
 *   activity for the active conversation.
 *
 * ## Data flow
 * This view is read-only: the user does not type shell commands. The model runs
 * `run_terminal_command`; the resulting `tool.call` / `tool.result` canonical
 * frames are folded into the {@link useAgentRunStore} (per-turn `AgentRun`
 * keyed by `turnId`). Here we simply aggregate the terminal tool activities
 * across this conversation's runs — no fetching is needed.
 *
 * ## Fallback
 * A {@link UiEmptyState} is rendered until at least one command has run.
 */
import { computed } from 'vue'

import ScopeManager from '../ScopeManager.vue'
import AliceSpinner from '../../ui/AliceSpinner.vue'
import AppIcon from '../../ui/AppIcon.vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import { useChatStore } from '../../../stores/chat'
import { useAgentRunStore } from '../../../stores/agentRun'

defineProps<{
  params?: Record<string, unknown>
}>()

const chatStore = useChatStore()
const agentRun = useAgentRunStore()

/** Active conversation id, or null when none is open. */
const conversationId = computed<string | null>(() => chatStore.currentConversation?.id ?? null)

/**
 * Terminal commands run in the active conversation, across all of its turns.
 *
 * Insertion order is roughly chronological (runs are appended as turns start,
 * tools as they are invoked); that ordering is good enough for a log. When no
 * conversation is open the list is empty.
 */
const commands = computed(() =>
  Object.values(agentRun.runs)
    .filter((r) => r.conversationId === conversationId.value)
    .flatMap((r) => r.tools)
    .filter((t) => t.toolName === 'run_terminal_command')
)
</script>

<template>
  <div class="terminal-module">
    <!-- Scope editor (non-scrolling header region; owns its own internal scroll) -->
    <div class="terminal-module__scope">
      <ScopeManager />
    </div>

    <!-- Command / output log -->
    <div v-if="commands.length > 0" class="terminal-module__log">
      <ul class="term-log" role="list">
        <li
          v-for="t in commands"
          :key="t.executionId"
          class="term-cmd"
          :class="`term-cmd--${t.status}`"
        >
          <div class="term-cmd__prompt">
            <span class="term-cmd__sigil" aria-hidden="true">$</span>
            <span class="term-cmd__command">{{ String(t.args.command ?? '') }}</span>
            <span class="term-cmd__status">
              <AliceSpinner v-if="t.status === 'running'" size="xs" aria-label="In esecuzione" />
              <AppIcon
                v-else-if="t.status === 'success'"
                name="check"
                :size="13"
                class="term-cmd__status-icon term-cmd__status-icon--ok"
                aria-label="Completato"
              />
              <AppIcon
                v-else
                name="alert-circle"
                :size="13"
                class="term-cmd__status-icon term-cmd__status-icon--err"
                aria-label="Errore"
              />
            </span>
          </div>
          <pre v-if="t.result" class="term-cmd__output">{{ t.result }}</pre>
        </li>
      </ul>
    </div>
    <UiEmptyState
      v-else
      icon="embedding"
      title="Nessun comando eseguito"
      subtitle="I comandi che l'assistente esegue nel terminale compariranno qui."
    />
  </div>
</template>

<style scoped>
.terminal-module {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Capped scope region — ScopeManager fills it and scrolls internally. */
.terminal-module__scope {
  flex: 0 0 auto;
  max-height: 45%;
  min-height: 0;
  display: flex;
  overflow: hidden;
  border-bottom: 1px solid var(--border);
}

/* Scrollable command log fills the remaining height of the tile. */
.terminal-module__log {
  flex: 1 1 0;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-3);
}

.term-log {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.term-cmd {
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
}

/* ── Prompt line ────────────────────────────────────────────── */
.term-cmd__prompt {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
}

.term-cmd__sigil {
  flex-shrink: 0;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--accent);
  user-select: none;
}

.term-cmd__command {
  flex: 1 1 auto;
  min-width: 0;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.term-cmd__status {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  margin-top: 1px;
}

.term-cmd__status-icon--ok {
  color: var(--success);
}

.term-cmd__status-icon--err {
  color: var(--danger);
}

/* ── Output ─────────────────────────────────────────────────── */
.term-cmd__output {
  margin: 0;
  padding: var(--space-2) var(--space-2-5);
  background: var(--surface-inset, var(--surface-0));
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: var(--leading-relaxed);
  color: var(--text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
  overflow-x: auto;
}

/* Error commands tint their output frame. */
.term-cmd--error .term-cmd__output {
  border-color: var(--danger-border);
  color: var(--text-primary);
}
</style>
