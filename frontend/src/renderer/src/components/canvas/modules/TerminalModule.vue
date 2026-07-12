<script setup lang="ts">
/**
 * TerminalModule — real interactive multi-tab terminal (Fase 7 E1/E2).
 *
 * ## Param keys
 * None. The terminal is per-conversation; the subject comes from the chat store.
 *
 * ## What it is
 * One {@link https://xtermjs.org xterm.js} terminal per live PTY session, with a
 * tab strip (multi-instance), inline rename, an "assign to agent" toggle (the
 * agent's `run_terminal_command` runs in — and mirrors output to — the assigned
 * session), and per-tab kill (terminates the whole process tree).
 *
 * ## Data flow
 * Session metadata + scrollback live in {@link useTerminalSessionsStore} (fed by
 * REST + events-WS frames). Each xterm replays the session's buffer on attach
 * (so reopening the module reattaches live sessions), then writes live output
 * via a store subscription. Keystrokes (`onData`) and resizes are sent back over
 * the events WS. The whole capability is gated by the backend `enabled` flag.
 */
import '@xterm/xterm/css/xterm.css'
import { Terminal, type ITheme } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import AppIcon from '../../ui/AppIcon.vue'
import UiEmptyState from '../../ui/UiEmptyState.vue'
import { useChatStore } from '@renderer/stores/chat'
import { useTerminalSessionsStore } from '@renderer/stores/terminalSessions'
import type { TerminalSession } from '@renderer/types/terminal'
import { readTokens } from '@renderer/composables/useThemeTokens'
import { ANSI_PALETTE } from '@renderer/utils/ansiPalette'

defineProps<{
  params?: Record<string, unknown>
}>()

const chatStore = useChatStore()
const store = useTerminalSessionsStore()

const conversationId = computed<string | null>(() => chatStore.currentConversation?.id ?? null)
const sessions = computed<TerminalSession[]>(() => store.sessionsFor(conversationId.value))
const activeId = ref<string | null>(null)
const errorMsg = ref<string | null>(null)
const busy = ref(false)

/* Inline rename state. */
const editingId = ref<string | null>(null)
const editTitle = ref('')

/** Per-session xterm instances (component-local; recreated on reattach). */
interface TermHandle {
  term: Terminal
  fit: FitAddon
  unsub: () => void
  ro: ResizeObserver | null
}
const terms = new Map<string, TermHandle>()
const hostEls = new Map<string, HTMLElement>()

/**
 * xterm theme from the dedicated `--terminal-*` tokens (xterm renders to
 * <canvas>, which cannot read var(--…) itself — hence readTokens). These
 * tokens are deliberately NON-flipping: the terminal stays dark in BOTH
 * themes, because the ANSI palette is dark-tuned and unreadable on ivory
 * (see the Terminal Tokens section in theme.css). The tokens are fixed, so
 * a one-shot read per terminal creation is enough — no theme-change watch.
 * The 16 ANSI colors are a separate, deliberately NOT tokenized, shared
 * constant — see utils/ansiPalette.ts.
 */
const TERMINAL_TOKEN_NAMES = [
  '--terminal-surface',
  '--terminal-fg',
  '--terminal-cursor',
  '--terminal-selection'
] as const

function buildXtermTheme(): ITheme {
  const t = readTokens(TERMINAL_TOKEN_NAMES)
  return {
    background: t['--terminal-surface'],
    foreground: t['--terminal-fg'],
    cursor: t['--terminal-cursor'],
    selectionBackground: t['--terminal-selection'],
    ...ANSI_PALETTE
  }
}

function setHostRef(sessionId: string, el: Element | null): void {
  if (el) hostEls.set(sessionId, el as HTMLElement)
  else hostEls.delete(sessionId)
}

/** Create + attach an xterm for a session (idempotent), replaying its buffer. */
function ensureTerm(session: TerminalSession): void {
  if (terms.has(session.id)) return
  const host = hostEls.get(session.id)
  if (!host) return

  const term = new Terminal({
    fontFamily: 'var(--font-mono, monospace)',
    fontSize: 13,
    cursorBlink: true,
    theme: buildXtermTheme(),
    scrollback: 5000,
    convertEol: false
  })
  const fit = new FitAddon()
  term.loadAddon(fit)
  term.open(host)
  try {
    fit.fit()
  } catch {
    /* host not laid out yet — a later resize will fit */
  }

  // Replay scrollback so a reattached session shows its history.
  const buffered = store.bufferFor(session.id)
  if (buffered) term.write(buffered)

  // Live output → terminal; keystrokes → backend.
  const unsub = store.subscribe(session.id, (chunk) => term.write(chunk))
  const conv = session.conversation_id
  term.onData((data) => store.sendInput(conv, session.id, data))

  // Track resizes and tell the PTY.
  const ro = new ResizeObserver(() => fitAndReport(session.id))
  ro.observe(host)

  terms.set(session.id, { term, fit, unsub, ro })
  fitAndReport(session.id)
}

function fitAndReport(sessionId: string): void {
  const handle = terms.get(sessionId)
  if (!handle) return
  try {
    handle.fit.fit()
  } catch {
    return
  }
  const conv = conversationId.value
  if (conv) store.sendResize(conv, sessionId, handle.term.rows, handle.term.cols)
}

function disposeTerm(sessionId: string): void {
  const handle = terms.get(sessionId)
  if (!handle) return
  handle.unsub()
  handle.ro?.disconnect()
  handle.term.dispose()
  terms.delete(sessionId)
}

/** Activate a tab: attach its xterm (after the host renders) and focus it. */
async function activate(sessionId: string): Promise<void> {
  activeId.value = sessionId
  await nextTick()
  const session = sessions.value.find((s) => s.id === sessionId)
  if (!session) return
  ensureTerm(session)
  await nextTick()
  fitAndReport(sessionId)
  terms.get(sessionId)?.term.focus()
}

async function openNew(): Promise<void> {
  const conv = conversationId.value
  if (!conv || busy.value) return
  busy.value = true
  errorMsg.value = null
  try {
    const session = await store.create(conv)
    await activate(session.id)
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : 'Impossibile aprire il terminale'
  } finally {
    busy.value = false
  }
}

async function killSession(sessionId: string): Promise<void> {
  const conv = conversationId.value
  if (!conv) return
  try {
    await store.kill(conv, sessionId)
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : 'Errore nella chiusura'
  }
}

async function assignToAgent(sessionId: string): Promise<void> {
  const conv = conversationId.value
  if (!conv) return
  try {
    await store.assign(conv, sessionId)
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : "Errore nell'assegnazione"
  }
}

/* ── Rename ── */
function startRename(session: TerminalSession): void {
  editingId.value = session.id
  editTitle.value = session.title
}

async function commitRename(): Promise<void> {
  const id = editingId.value
  const conv = conversationId.value
  const title = editTitle.value.trim()
  editingId.value = null
  if (!id || !conv || !title) return
  try {
    await store.rename(conv, id, title)
  } catch {
    /* non-fatal */
  }
}

/* ── Reconciliation ── */

// Load sessions for the active conversation (fetch-once), pick an active tab.
watch(
  conversationId,
  (conv) => {
    if (!conv) return
    void store.ensureForConversation(conv).then(() => {
      if (!activeId.value || !sessions.value.some((s) => s.id === activeId.value)) {
        const first = store.assignedFor(conv) ?? sessions.value[0]
        if (first) void activate(first.id)
      }
    })
  },
  { immediate: true }
)

// Dispose xterms for sessions that have vanished; keep the active tab valid.
watch(
  sessions,
  (list) => {
    const live = new Set(list.map((s) => s.id))
    for (const id of [...terms.keys()]) {
      if (!live.has(id)) disposeTerm(id)
    }
    if (activeId.value && !live.has(activeId.value)) {
      const next = list[0]
      activeId.value = next ? next.id : null
      if (next) void activate(next.id)
    } else if (!activeId.value && list.length > 0) {
      void activate(list[0].id)
    }
  },
  { deep: false }
)

onBeforeUnmount(() => {
  for (const id of [...terms.keys()]) disposeTerm(id)
  hostEls.clear()
})
</script>

<template>
  <div class="terminal-module">
    <!-- Disabled capability -->
    <UiEmptyState
      v-if="!store.enabled"
      icon="embedding"
      title="Terminale disabilitato"
      subtitle="Abilita il terminale nella configurazione (terminal.enabled) per usarlo."
    />

    <!-- Enabled -->
    <template v-else>
      <!-- Tab strip -->
      <div class="tm__tabs" role="tablist">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="tm__tab"
          :class="{ 'tm__tab--active': s.id === activeId }"
          role="tab"
          :aria-selected="s.id === activeId"
          @click="activate(s.id)"
          @dblclick="startRename(s)"
        >
          <AppIcon
            v-if="s.agent_assigned"
            name="lightning"
            :size="12"
            class="tm__tab-agent"
            aria-label="Assegnato all'agente"
          />
          <input
            v-if="editingId === s.id"
            v-model="editTitle"
            class="tm__tab-edit"
            type="text"
            @click.stop
            @keydown.enter.prevent="commitRename"
            @keydown.esc.prevent="editingId = null"
            @blur="commitRename"
            @vue:mounted="(vn) => (vn.el as HTMLInputElement | null)?.focus()"
          />
          <span v-else class="tm__tab-title">{{ s.title }}</span>
          <button
            v-if="!s.agent_assigned"
            class="tm__tab-action"
            title="Assegna all'agente"
            aria-label="Assegna all'agente"
            @click.stop="assignToAgent(s.id)"
          >
            <AppIcon name="lightning" :size="12" />
          </button>
          <button
            class="tm__tab-close"
            title="Chiudi (termina i processi)"
            aria-label="Chiudi terminale"
            @click.stop="killSession(s.id)"
          >
            <AppIcon name="x" :size="12" />
          </button>
        </div>
        <button
          class="tm__new"
          title="Nuovo terminale"
          aria-label="Nuovo terminale"
          :disabled="busy || conversationId === null"
          @click="openNew"
        >
          <AppIcon name="plus" :size="14" />
        </button>
      </div>

      <p v-if="errorMsg" class="tm__error">
        <AppIcon name="alert-triangle" :size="13" :stroke-width="2" />
        {{ errorMsg }}
      </p>

      <!-- Terminals (one host per session; only the active is shown) -->
      <div class="tm__body">
        <div
          v-for="s in sessions"
          v-show="s.id === activeId"
          :key="s.id"
          :ref="(el) => setHostRef(s.id, el as Element | null)"
          class="tm__host"
        />
        <UiEmptyState
          v-if="sessions.length === 0"
          icon="embedding"
          title="Nessun terminale aperto"
          subtitle="Apri un terminale per lavorare nella cartella dello scope."
        >
          <template #actions>
            <button
              class="tm__open-btn"
              :disabled="busy || conversationId === null"
              @click="openNew"
            >
              <AppIcon name="plus" :size="14" />
              Apri terminale
            </button>
          </template>
        </UiEmptyState>
      </div>
    </template>
  </div>
</template>

<style scoped>
.terminal-module {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  /* --terminal-surface (non-flipping): il wrapper resta scuro come l'xterm
     anche in light theme — vedi Terminal Tokens in theme.css. */
  background: var(--terminal-surface);
}

/* ── Tab strip ── */
.tm__tabs {
  display: flex;
  align-items: stretch;
  gap: var(--space-0-5);
  padding: var(--space-1) var(--space-1) 0;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  flex-shrink: 0;
}

.tm__tab {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-1) var(--space-2-5);
  max-width: 200px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: transparent;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  cursor: pointer;
  white-space: nowrap;
  user-select: none;
}

.tm__tab:hover {
  background: var(--surface-3);
}

.tm__tab--active {
  /* Testo pinnato a --terminal-fg: su sfondo sempre-scuro il --text-primary
     light (inchiostro scuro) sarebbe illeggibile. */
  color: var(--terminal-fg);
  background: var(--terminal-surface);
  border-color: var(--border);
}

.tm__tab-agent {
  color: var(--accent);
  flex-shrink: 0;
}

.tm__tab-title {
  overflow: hidden;
  text-overflow: ellipsis;
}

.tm__tab-edit {
  width: 100px;
  font-size: var(--text-xs);
  color: var(--text-primary);
  background: var(--surface-0);
  border: 1px solid var(--accent);
  border-radius: var(--radius-sm);
  padding: 0 var(--space-1);
}

.tm__tab-action,
.tm__tab-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 1px;
  color: var(--text-muted);
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  flex-shrink: 0;
}

.tm__tab-action:hover {
  color: var(--accent);
  background: var(--surface-hover);
}

.tm__tab-close:hover {
  color: var(--danger);
  background: var(--surface-hover);
}

.tm__new {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 var(--space-2);
  color: var(--text-secondary);
  background: transparent;
  border: none;
  cursor: pointer;
  flex-shrink: 0;
}

.tm__new:hover:not(:disabled) {
  color: var(--text-primary);
}

.tm__new:disabled {
  opacity: var(--opacity-dim);
  cursor: not-allowed;
}

.tm__error {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  margin: 0;
  padding: var(--space-1-5) var(--space-2-5);
  font-size: var(--text-xs);
  color: var(--error);
  background: var(--error-bg);
}

/* ── Body ── */
.tm__body {
  position: relative;
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
}

.tm__host {
  position: absolute;
  inset: 0;
  padding: var(--space-2);
}

.tm__open-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  color: var(--surface-0);
  background: var(--accent);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.tm__open-btn:hover:not(:disabled) {
  background: var(--accent-hover);
}

.tm__open-btn:disabled {
  opacity: var(--opacity-dim);
  cursor: not-allowed;
}
</style>
