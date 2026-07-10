# Fase 6 — Frontend (Horizon unica superficie, client per dominio, dispatcher chat tipizzato, Command Registry) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** il frontend diventa coerente con la spec §5 riga 215 (+ §6/§7): **Horizon unica superficie** (rimozione dell'intero stack Workspace + dead code orb, con salvataggio del terminale in route standalone); **client REST per dominio** (`services/api/<dominio>.ts` al posto di `api.ts` da 988 righe); **dispatcher tipizzato anche sul canale chat-WS** (parità con events, fatto in 1b); **Command Registry** frontend con capability tag (§7, fondamenta per il Command Bridge di fase 7); chiusura dei backlog FE ereditati (bulk-delete artifacts, live-update whiteboard, CAD export_url, AgentTier, KGMutationResponse, memory.spec); **lint sanato a fondo** e **lint+vitest come gate CI**.

**Architecture:** la rotta è l'unica fonte di verità della superficie (via `UIMode`/`mode` dallo store ui); i client di dominio condividono un core http (`services/api/http.ts`) e NON esiste barrel di compatibilità `api` — i 42 importatori migrano ai namespace di dominio; il dispatcher chat replica ESATTAMENTE il pattern events (mapped type esaustivo su `ChatServerMessage['type']`); il Command Registry è frontend-only in questa fase (manifest e tool `app_command` = fase 7) ma nasce già con capability tag + campo `exposeToAgent` default-false (seam dell'invariante anti-escalation §7).

**Tech Stack:** Vue 3 `<script setup>` + Pinia + vue-router 4, tipi generati openapi-typescript, vitest 4 (node env), eslint 9 flat + prettier, pydantic ws_schema + gen-contracts.ps1 (solo Task 6).

**Branch:** `arch/fase6-frontend` (figlio di `arch/fase5-kernel`, già creato).

---

## Contesto verificato (recon 2026-07-10, 4 agenti + verifica a mano)

**Orb-era:** i componenti orb VERI sono già stati cancellati in commit precedenti (`AssistantView`, `ChatView`, `HybridView`, `AliceOrb`, fluid-orb/neural-network/veil-orb interi). `/assistant` punta già a `HorizonView.vue`. Restano SOLO residui morti: `components/assistant/ModeSwitcher.vue` (186 righe, dormiente — unico riferimento è il commento `App.vue:121` "NON ATTIVARE!"), `stores/ui.ts:32,35` `ambientEnabled`/`orbVisible` (zero consumatori), `assets/styles/transitions.css:310-338` keyframes `orbEntrance`, icone `'orb'`/`'orb-full'` in `assets/icons.ts:166-170`, e 3 componenti voice orfani (`VoiceIndicator.vue`, `TranscriptOverlay.vue`, `AudioPlayback.vue` — grep: zero importatori; `MicrophoneButton` e `VoiceSettings` invece sono VIVI: HorizonCockpit/ChatInput e SettingsView).

**Stack Workspace (l'altra superficie, ~2.800 righe):** `views/WorkspaceView.vue` (93) monta `HomeSurface` + `PanelWorkspace`. Catene chiuse: `components/home/*` (7 file, ~714 righe, importati solo da WorkspaceView→HomeSurface); `components/canvas/*` tiling (`PanelWorkspace`, `ChatPanel` 364, `ModuleLauncher`, `ModulePanel`, `ModuleSelectorBar`, `PaneDivider`, `PanelLeaf`, `SplitContainer`) — ECCEZIONE `DockedSidebar.vue` (195, chrome permanente dello shell, montato da `App.vue:110`); `components/canvas/modules/*` (6 moduli, lazy-loaded solo da `composables/workspace/moduleRegistry.ts:51-93`); `composables/workspace/*` (6 moduli + 4 spec); `stores/workspace.ts` (438) usato dai canvas E da `DockedSidebar.vue:24` (solo `sidebarWidth`/`setSidebarWidth`). `ChatPanel` è l'UNICO importatore di `MessageBubble`, `StreamingIndicator`, `ReasoningThread`, `ChatInput`, `TaskStrip` (grep verificato) → cascata di orfani da gestire. **`TerminalModule.vue` (499 righe) è l'UNICA UI del terminale** → va salvato come route standalone (decisione utente 2026-07-10). Router: `/`→`/workspace`, `/home`/`/hybrid`/catch-all→`/workspace`, `MODE_ROUTES` sync in `router/index.ts:27,131-139`. `AppSidebar.vue:69-95` segmented a 2 modi; `ChatInput.vue:41` `modeIcon` (muore con ChatPanel).

**api.ts (988 righe):** oggetto unico `export const api` (righe 250-988, ~80 metodi in 18 gruppi con commenti `// -- <dominio>`); infra condivisa: `ApiError` (84), `BACKEND_HOST` (105), `resolveBackendUrl` (112), `withTimeout` (150), `request<T>` (181), `waitForBackend` (227), `BASE_URL` (102), `DEFAULT_REQUEST_TIMEOUT_MS` (144). **42 file importatori** (21 store+spec, 4 composables, 17 componenti); simboli non-`api`: `resolveBackendUrl` (5 usi), `BACKEND_HOST` (3: services store, useEventsWebSocket, useVoice), `ApiError` (2), `waitForBackend` (1, App.vue). `TldrawCanvas.vue:10` usa l'alias `@renderer/services/api`. Le 6 mutazioni KG (righe 709-748) ritornano `Promise<unknown>`; `KGMutationResponse` ESISTE già nei generati (`api.d.ts:2725`, `{ ok?: boolean }`) ed è già il response_model dei 6 endpoint.

**WS:** events-WS dispatcher esaustivo GIÀ FATTO (1b): `useEventsWebSocket.ts:30-32` mapped type su `EventsServerMessage['type']`, oggetto `handlers` esaustivo (83-110). Il canale CHAT invece è un emitter a stringhe (`services/ws.ts:14,210-243`, `MessageHandler = (data: unknown) => void`, dispatch `emit(data.type ?? 'message')` a riga 77) + 28 registrazioni manuali con cast in `useChat.ts:339-366` — **unico registrante di `wsManager.on` in tutto il renderer** (grep verificato). Vocabolario chat server congelato (27 tipi, `backend/tests/contracts/test_ws_schema_chat.py:21-49`): token, thinking, tool_call, done, error, tool_execution_start, tool_execution_done, tool_progress, context_info, context_compression_start/done/failed, llm_requery, warning, tool_confirmation_required, client_tool_call, ask_user_required, turn.started, turn.llm_step, tool.call, tool.result, interaction.requested, interaction.resolved, turn.usage, turn.finished, agent.critic_invoked, agent.warning. `client_tool_call`, `agent.critic_invoked`, `agent.warning` NON sono gestiti oggi (il registro manuale li ignora silenziosamente — il dispatcher esaustivo li scoprirà). Il frame di INVIO utente (`WsSendPayload`: content/conversation_id/attachments/edit_message_id) NON ha `type` e NON è nell'unione client (decisione 1b, vocabolario congelato) — non si tocca.

**Backlog FE confermati:** (a) `AgentTier` in `types/settings.ts:159` duplica il generato `PermissionMode` (`api.d.ts:2903`); (b) bulk-delete: `registry.py:471-513 delete_for_conversation` e `:515-532 delete_all` NON emettono eventi WS (commento esplicito) → FE mai invalidato; (c) whiteboard live-update: l'handler `artifact.updated` chiama `refreshById` che aggiorna SOLO la riga, non `contents[id]` (cache snapshot tldraw, `artifacts.ts:38,156-163`); (d) CAD: il plugin emette `export_url = /api/cad/models/{name}` (plugin.py:538,995,1274, endpoint legacy per nome file); i parser lo copiano nei metadata artifact (`parsers.py:148`); l'endpoint unificato `GET /api/artifacts/{id}/download` ESISTE (`artifacts.py:262`) e `download_url` è già computed field (`schemas.py:33-37`); l'artifact id nasce SOLO in `tool_loop.py:636` (registrazione centralizzata) — il payload live non può conoscerlo; (e) `memory.spec.ts` assente (lo store `memory.ts` esiste, 137 righe).

**Lint/CI:** `npx eslint --cache .` → exit 1 con **15 errori** (10 `explicit-function-return-type`, 4 `no-unused-vars`, 1 `triple-slash-reference` in `env.d.ts:2`) + 17.822 warning di cui 17.576 `prettier/prettier` (8.522 = `Delete ␍`, CRLF fantasma: `.prettierrc.yaml` non imposta `endOfLine`). File con errori: stores/chat.ts, stores/calendar.ts, useChat.ts, useCodeBlocks.ts, useWhiteboardBoards.ts, useModuleItemSelection.ts (muore col workspace), toolTierView.ts, vari .vue/.spec, env.d.ts. CI (`contracts.yml`): per il FE gira SOLO `npm run typecheck` (righe 58-60) — niente lint, niente vitest. vitest 4 configurato (`vitest.config.ts`, node env, ~30 spec).

**Command Registry:** zero abbozzi nel renderer (grep). Precedenti architetturali riusabili: pattern registry tipizzato di `moduleRegistry.ts` (muore col workspace) e bus di `moduleIntents.ts` (muore).

---

## Decisioni di design della fase (registrate, non rilitigare durante l'esecuzione)

1. **"Horizon unica superficie" = rimozione dell'intero stack Workspace** (decisione utente 2026-07-10: "la soluzione più professionale, senza debiti") + dead code orb. Il **terminale sopravvive** come route standalone `/terminal` (view dedicata, stessa dignità di `/whiteboard` e `/board`) perché `TerminalModule` è l'unica UI della feature. La chat duplicata (ChatPanel/ChatModule) viene eliminata: principio §4.1 "una sola implementazione".
2. **La rotta è l'unica fonte di verità della superficie**: `UIMode`, `mode`, `setMode`, `MODE_ROUTES` e i computed morti spariscono; `stores/ui.ts` tiene `sidebarOpen` + assorbe `sidebarWidth` (unico pezzo di `stores/workspace` usato dallo shell). `DockedSidebar.vue` si sposta in `components/sidebar/` (la cartella `canvas/` muore).
3. **Client per dominio senza barrel di compatibilità**: package `services/api/` con `http.ts` (core condiviso: `request`, `ApiError`, `BACKEND_HOST`, `BASE_URL`, `resolveBackendUrl`, `withTimeout`, `waitForBackend`) + 18 moduli dominio + `index.ts` che ri-esporta tutto. Il PATH di import `../services/api` resta valido (directory index) — cambia solo il simbolo (`api.getX()` → `<dominio>Api.getX()`). I metodi si SPOSTANO VERBATIM (stessi tipi, stesse righe), unica eccezione: le 6 mutazioni KG diventano `Promise<KGMutationResponse>`.
4. **Dispatcher chat-WS speculare a events**: `ChatHandlerMap` mapped-type esaustivo su `ChatServerMessage['type']`; `WebSocketManager` mantiene reconnect/backpressure ma smette di fare emitter per stringhe — un solo frame-handler tipizzato + eventi socket-level (`connected`/`disconnected`/`error`/`reconnect_failed`/`binary`) su union chiusa. I 3 frame oggi ignorati (`client_tool_call`, `agent.critic_invoked`, `agent.warning`) diventano no-op ESPLICITI con commento. Nessun cast nei handler: se un alias hand-written di `types/chat.ts`/`types/turn.ts` non combacia col generato, si corregge l'alias (mai castare).
5. **Command Registry frontend-only** (`src/renderer/src/commands/`): `CommandDefinition` con `capability ∈ {navigation, read, mutate, destructive}` (§7), `argsSchema` JSON-schema-like (servirà al manifest di fase 7) e `exposeToAgent: boolean` default **false** — l'invariante anti-escalation §7 nasce qui: i comandi guardrail non saranno MAI `exposeToAgent`. Core commands fase 6: `view.switch`, `conversation.open`, `conversation.new`, `sidebar.toggle`, `artifact.show`. Call-site migrati: le azioni programmatiche di `AppSidebar` (select/create/home). I `<router-link>` dichiarativi restano (la "sola implementazione" è `router.push`, condivisa). Manifest, `app_command` e RPC = fase 7.
6. **Eventi artifacts**: nuovo frame `artifact.bulk_deleted` (`conversation_id: str | None` + `artifact_ids: list[str]`) emesso da `delete_for_conversation` E `delete_all` (`conversation_id=None` = wipe totale); l'handler FE di `artifact.updated` invalida ANCHE la cache contenuti (chiude il live-update whiteboard). Task 6 è l'UNICO task con regen contracts.
7. **CAD**: `export_url` esce dai metadata artifact (era una copia del path legacy; `download_url` computed field è l'URL canonico derivabile) — i consumer artifact-driven usano `download_url`. Il payload live del turno e la route legacy `/api/cad/models/{name}` restano INVARIATI (il payload non può conoscere l'artifact id, che nasce dopo in tool_loop.py:636); l'unificazione completa del payload è backlog di fase 7/8. `AgentTier` diventa alias di `ApiSchema<'PermissionMode'>`.
8. **Lint a fondo** (decisione utente): fix dei 15 errori, `endOfLine: auto` in `.prettierrc.yaml`, eccezione `triple-slash-reference` per `**/*.d.ts` (idioma electron-vite), riformattazione completa `npm run format`, `vue/no-v-html` residui giustificati con disable mirato e commento. `npm run lint` e `npm test` diventano step di `contracts.yml`. Il reformat è il PENULTIMO task (dopo tutte le modifiche di codice, per non riformattare due volte).
9. **Comportamento backend osservabile invariato** salvo: i 2 nuovi punti di emissione WS (frame nuovo, additivo) e i metadata CAD senza `export_url` (dichiarato). Ogni task lascia `npm run typecheck` verde e la suite vitest verde.
10. Docstring/commenti in codice in **inglese**; piano ed esiti in italiano. Commit convenzionali con trailer `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` (due `-m`, mai here-string).

---

## Vincoli operativi (gotchas handoff, adattati alla fase)

- **EOL (3 incidenti nel programma)**: `git ls-files --eol <file toccati>` PRIMA e DOPO ogni commit; diff sospettosamente grande → `git diff --ignore-cr-at-eol --stat` per smascherare flip. MAI cmdlet PowerShell su file non-ASCII. Nel Task 7 (reformat) la verifica è OBBLIGATORIA: `git diff --stat` e `git diff --ignore-cr-at-eol --stat` devono coincidere.
- **Fino al Task 7 il gate lint è scoped**: `npx eslint <file toccati>` contando SOLO gli errori (i warning prettier pre-esistenti non bloccano). `npm run typecheck` SEMPRE (node + web). `npm test` (vitest, veloce) a ogni task.
- **Task 6 (unico task backend)**: pytest mirato da `backend/` con `..\.venv\Scripts\python.exe -m pytest tests/contracts/ tests/test_artifact_registry.py -v`; boot-check (`create_app`) dalla REPO ROOT; regen SOLO qui (`.\scripts\gen-contracts.ps1`); `check-contracts.ps1` DOPO il commit (untracked = dirty). `test_plugins_enabled_list` è ROSSO EREDITATO — non è una regressione.
- **PowerShell 5.1**: niente `&&`; comandi npm da `frontend/`.
- I file in `types/generated/` sono artefatti: MAI editarli a mano (tranne `index.ts`), MAI risolvere conflitti a mano — rigenerare.
- **Subagent**: prescrizioni esatte, verificare il diff al ritorno (`git show`); un reviewer con output vuoto → rilanciare.

---

### Task 1: Terminale standalone — `views/TerminalPageView.vue` + route `/terminal`

Additivo: l'app resta identica, il terminale diventa raggiungibile anche fuori dal Workspace. (Il modulo tile verrà rimosso nel Task 2.)

**Files:**
- Create: `frontend/src/renderer/src/views/TerminalPageView.vue`
- Modify: `frontend/src/renderer/src/router/index.ts` (nuova route dopo `/board`, righe ~109-114)
- Modify: `frontend/src/renderer/src/components/sidebar/AppSidebar.vue` (nav link dopo "Bacheca", righe ~291-297)
- Modify (se manca l'icona): `frontend/src/renderer/src/assets/icons.ts`

- [ ] **Step 1: icona `terminal`**

`Grep '"terminal"|'terminal'' frontend/src/renderer/src/assets/icons.ts`. Se non esiste una entry `'terminal'`, aggiungila accanto alle altre (stile Solar già in uso):

```ts
  'terminal': { icon: 'solar:code-square-bold' },
```

- [ ] **Step 2: crea la view**

`TerminalPageView.vue` è il contenuto di `components/canvas/modules/TerminalModule.vue` (499 righe, letto e riusato VERBATIM) con QUATTRO adattamenti e nient'altro:
1. rimuovi il blocco `defineProps<{ params?: Record<string, unknown> }>()` (righe 32-34: la view non è un tile);
2. import path aggiornati alla profondità `views/`: `AppIcon` → `'../components/ui/AppIcon.vue'`, `UiEmptyState` → `'../components/ui/UiEmptyState.vue'`, `useChatStore` → `'../stores/chat'`, `useTerminalSessionsStore` → `'../stores/terminalSessions'`, `TerminalSession` → `'../types/terminal'`;
3. docstring di testa sostituita:

```ts
/**
 * TerminalPageView — standalone page for the interactive multi-tab terminal.
 *
 * Hosts the real PTY terminal (xterm.js) previously embedded as a Workspace
 * tile (TerminalModule, retired in Fase 6). The terminal is per-conversation;
 * the subject comes from the chat store. Session metadata + scrollback live in
 * {@link useTerminalSessionsStore} (REST + events-WS frames); keystrokes and
 * resizes go back over the events WS. Gated by the backend `enabled` flag.
 */
```
4. la classe root del template e dello style passa da `terminal-module` a `terminal-page`, con il blocco base così (il resto dello `<style scoped>` resta identico):

```css
.terminal-page {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #0d1117;
}
```

- [ ] **Step 3: route**

In `router/index.ts`, dopo il blocco `/board`:

```ts
    {
      path: '/terminal',
      name: 'terminal',
      component: () => import('../views/TerminalPageView.vue'),
      meta: { title: 'Terminale', transition: DEFAULT_PAGE_TRANSITION }
    },
```

- [ ] **Step 4: voce sidebar**

In `AppSidebar.vue`, dopo il `<router-link to="/board">` (riga ~297):

```html
          <router-link to="/terminal" class="sidebar__link" active-class="sidebar__link--active" title="Terminale"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="terminal" :size="15" />
            </span>
            <span class="sidebar__link-label">Terminale</span>
          </router-link>
```

- [ ] **Step 5: verifica**

Da `frontend/`: `npm run typecheck` → PASS; `npm test` → PASS; `npx eslint src/renderer/src/views/TerminalPageView.vue src/renderer/src/router/index.ts src/renderer/src/components/sidebar/AppSidebar.vue src/renderer/src/assets/icons.ts` → zero ERRORI nuovi.

- [ ] **Step 6: EOL + commit**

`git ls-files --eol` sui file toccati (attesi `i/lf`), poi:

```
git add -A
git commit -m "feat(fe): standalone /terminal page hosting the PTY terminal" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Rimozione stack Workspace + dead code orb (Horizon unica superficie)

**Files:**
- Rewrite: `frontend/src/renderer/src/stores/ui.ts`
- Rewrite: `frontend/src/renderer/src/router/index.ts`
- Move+Modify: `frontend/src/renderer/src/components/canvas/DockedSidebar.vue` → `frontend/src/renderer/src/components/sidebar/DockedSidebar.vue`
- Modify: `frontend/src/renderer/src/App.vue`, `frontend/src/renderer/src/components/sidebar/AppSidebar.vue`, `frontend/src/renderer/src/assets/icons.ts`, `frontend/src/renderer/src/assets/styles/transitions.css`
- Delete: `views/WorkspaceView.vue`; `components/home/` (intera: HomeSurface, HomeComposer, HomeGreeting, HomeIntents, HomeResume, HomeResumeEntry, HomeColophon); `components/canvas/` residua (PanelWorkspace, ChatPanel, ModuleLauncher, ModulePanel, ModuleSelectorBar, PaneDivider, PanelLeaf, SplitContainer + `modules/` intera); `composables/workspace/` (intera, spec inclusi); `stores/workspace.ts` + `stores/workspace.spec.ts`; `components/assistant/ModeSwitcher.vue`; `components/voice/VoiceIndicator.vue`, `components/voice/TranscriptOverlay.vue`, `components/voice/AudioPlayback.vue`; orfani di seconda battuta (Step 5)

- [ ] **Step 1: riscrivi `stores/ui.ts`** (assorbe `sidebarWidth`, perde `mode` e i computed morti)

```ts
/**
 * Pinia store for shell UI state.
 *
 * Since Fase 6 the route is the single source of truth for which surface is
 * on screen (Horizon is the only chat surface); this store only tracks shell
 * chrome: the docked sidebar's open state and persisted width.
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'

const SIDEBAR_WIDTH_KEY = 'alice_sidebar_width'

function loadSidebarWidth(): number {
  try {
    const raw = localStorage.getItem(SIDEBAR_WIDTH_KEY)
    if (raw !== null) {
      const n = parseInt(raw, 10)
      if (!isNaN(n)) return Math.min(420, Math.max(200, n))
    }
  } catch {
    /* localStorage may be unavailable */
  }
  return 260
}

export const useUIStore = defineStore('ui', () => {
  /**
   * Sidebar open state — source of truth for the docked sidebar's
   * expanded ↔ closed state (wired to the TitleBar toggle).
   */
  const sidebarOpen = ref(true)

  /** Persisted sidebar width in px (clamped 200–420). */
  const sidebarWidth = ref<number>(loadSidebarWidth())

  function toggleSidebar(): void {
    sidebarOpen.value = !sidebarOpen.value
  }

  function setSidebarWidth(n: number): void {
    sidebarWidth.value = Math.min(420, Math.max(200, n))
    try {
      localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth.value))
    } catch {
      /* localStorage may be unavailable */
    }
  }

  return {
    sidebarOpen,
    sidebarWidth,
    toggleSidebar,
    setSidebarWidth,
  }
})
```

- [ ] **Step 2: riscrivi `router/index.ts`**

Sostituisci il file intero con questa versione (sparisce `MODE_ROUTES` + il primo `afterEach` + l'import dello store ui; tutti i redirect puntano a `/assistant`; la route `/terminal` del Task 1 resta):

```ts
/**
 * Application router.
 *
 * Route `meta` contract:
 *   - `title`    string — human-readable page title, used as the window title
 *                         suffix ("<Title> — AL\\CE"). Also usable as a
 *                         fallback aria-label by views.
 *   - `transition` string — transition name for the <router-view> wrapper.
 *                           Defaults to `DEFAULT_PAGE_TRANSITION` if missing.
 *
 * Deep-link routes:
 *   - `/email/:id?` — optional email uid, consumed by EmailPageView.
 *   - `/calendar`   — optional `?date=YYYY-MM-DD` query (delegated to the
 *                     CalendarView component).
 *
 * Since Fase 6 Horizon (`/assistant`) is the only chat surface: the retired
 * Workspace/Hybrid routes redirect there so old deep links keep resolving.
 */
import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteLocationNormalized, RouterScrollBehavior } from 'vue-router'

/** Window-title suffix shared by every page. */
const TITLE_SUFFIX = 'AL\\CE'

/** Default transition name when route meta does not specify one. */
export const DEFAULT_PAGE_TRANSITION = 'page-fade'

/**
 * Scroll behavior:
 * - Restore saved position on browser back/forward (native UX).
 * - Same-path navigation (hash-only / query-only) keeps current scroll so
 *   in-view tab switches and anchor changes are not hijacked.
 * - Otherwise scroll to top; honour `prefers-reduced-motion`.
 */
const scrollBehavior: RouterScrollBehavior = (to, from, savedPosition) => {
  if (savedPosition) return savedPosition
  if (to.path === from.path) return false
  const prefersReducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  return { top: 0, left: 0, behavior: prefersReducedMotion ? 'auto' : 'smooth' }
}

const router = createRouter({
  history: createWebHashHistory(),
  scrollBehavior,
  routes: [
    {
      path: '/',
      redirect: '/assistant'
    },
    {
      // Legacy named redirect: keeps old `#/home` deep links and
      // `{ name: 'home' }` fallbacks resolving to the primary surface.
      path: '/home',
      name: 'home',
      redirect: '/assistant'
    },
    {
      // Workspace retired (Fase 6) — Horizon is the only chat surface.
      path: '/workspace',
      redirect: '/assistant'
    },
    {
      path: '/assistant',
      name: 'assistant',
      component: () => import('../views/HorizonView.vue'),
      meta: { title: 'Assistente', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      // HybridView retired — redirect to the primary surface.
      path: '/hybrid',
      redirect: '/assistant'
    },
    {
      path: '/calendar',
      name: 'calendar',
      component: () => import('../views/CalendarPageView.vue'),
      meta: { title: 'Calendario', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue'),
      meta: { title: 'Impostazioni', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/email/:id?',
      name: 'email',
      component: () => import('../views/EmailPageView.vue'),
      props: true,
      meta: { title: 'Email', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/whiteboard',
      name: 'whiteboard',
      component: () => import('../views/WhiteboardPageView.vue'),
      meta: { title: 'Lavagna', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/board',
      name: 'board',
      component: () => import('../views/ArtifactBoardView.vue'),
      meta: { title: 'Bacheca', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/terminal',
      name: 'terminal',
      component: () => import('../views/TerminalPageView.vue'),
      meta: { title: 'Terminale', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/services',
      name: 'services',
      component: () => import('../views/ServicesView.vue'),
      meta: { title: 'Servizi', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/assistant'
    }
  ]
})

// Mirror the active route meta into the window/document title so the Electron
// window chrome stays in sync with in-app navigation.
router.afterEach((to: RouteLocationNormalized) => {
  const title = (to.meta?.title as string | undefined)?.trim()
  document.title = title ? `${title} — ${TITLE_SUFFIX}` : TITLE_SUFFIX
})

// Retry failed dynamic imports once (handles Vite HMR / dep optimisation races).
const retriedPaths = new Set<string>()
router.onError((error, to) => {
  if (
    error.message.includes('Failed to fetch dynamically imported module') &&
    !retriedPaths.has(to.fullPath)
  ) {
    retriedPaths.add(to.fullPath)
    router.replace(to.fullPath)
  }
})

export default router
```

- [ ] **Step 3: sposta e sgancia `DockedSidebar.vue`**

`git mv frontend/src/renderer/src/components/canvas/DockedSidebar.vue frontend/src/renderer/src/components/sidebar/DockedSidebar.vue`, poi nel file:
- import: `import AppSidebar from './AppSidebar.vue'` (era `'../sidebar/AppSidebar.vue'`); rimuovi `import { useWorkspaceStore } from '../../stores/workspace'`;
- rimuovi `const workspaceStore = useWorkspaceStore()`;
- le tre occorrenze `workspaceStore.sidebarWidth`/`workspaceStore.setSidebarWidth(v)` diventano `uiStore.sidebarWidth`/`uiStore.setSidebarWidth(v)` (righe 36, 41, 47 del file letto).

In `App.vue:8`: `import DockedSidebar from './components/sidebar/DockedSidebar.vue'`. Rimuovi anche la riga commento `App.vue:121` (`<!-- <ModeSwitcher ... /> NON ATTIVARE! -->`).

- [ ] **Step 4: adegua `AppSidebar.vue`**

Nel `<script setup>`:
- rimuovi `import UiSegmented, { type UiSegmentedOption } from '../ui/UiSegmented.vue'` (l'import di `useUIStore` invece RESTA: serve a `toggle()`);
- rimuovi `isWorkspaceActive`, `modeTabOptions`, `activeModeValue`, `onModeSelect` (righe 54, 69-95);
- `isHomeActive` diventa:

```ts
/**
 * The Home affordance is "fresh conversation on the primary surface": active
 * exactly when Horizon is on screen with an empty conversation.
 */
const isHomeActive = computed(
  () =>
    isAssistantActive.value &&
    chatStore.messages.length === 0 &&
    !chatStore.isStreamingCurrentConversation
)
```
- in `onSelect` (righe 129-139) il blocco di navigazione diventa:

```ts
  const current = router.currentRoute.value.name as string
  if (current !== 'assistant') {
    try {
      await router.push('/assistant')
    } catch (err) {
      console.error('[AppSidebar] Navigation failed:', err)
    }
  }
```
- in `onHome` (righe 146-162) e `onCreate` (righe 171-180) sostituisci ogni `'/workspace'` / `name !== 'workspace'` con `'/assistant'` / `name !== 'assistant'` e aggiorna le docstring (la Home è "conversazione fresca su Horizon", non più "empty Workspace").

Nel `<template>`: rimuovi il blocco `<UiSegmented class="sidebar__mode-seg" …/>` (righe 269-271) e la regola CSS `.sidebar__mode-seg` (righe 482-486).

- [ ] **Step 5: cancella lo stack e i residui orb, poi sweep degli orfani**

```
git rm frontend/src/renderer/src/views/WorkspaceView.vue
git rm -r frontend/src/renderer/src/components/home
git rm -r frontend/src/renderer/src/components/canvas
git rm -r frontend/src/renderer/src/composables/workspace
git rm frontend/src/renderer/src/stores/workspace.ts frontend/src/renderer/src/stores/workspace.spec.ts
git rm frontend/src/renderer/src/components/assistant/ModeSwitcher.vue
git rm frontend/src/renderer/src/components/voice/VoiceIndicator.vue frontend/src/renderer/src/components/voice/TranscriptOverlay.vue frontend/src/renderer/src/components/voice/AudioPlayback.vue
```
(`components/canvas` a questo punto contiene solo lo stack tiling: DockedSidebar è già stato spostato.)

Poi lo **sweep iterativo degli orfani**: `npm run typecheck` segnala gli import pendenti; per ogni candidato la regola è *si cancella SOLO se i suoi unici importatori erano nello stack cancellato* (verifica con `Grep "NomeComponente" frontend/src`). Prima ondata NOTA (unici importatori = ChatPanel, grep verificato in recon): `components/chat/ChatInput.vue`, `components/chat/MessageBubble.vue`, `components/chat/StreamingIndicator.vue`, `components/chat/ReasoningThread.vue`, `components/chat/TaskStrip.vue` + `TaskStrip.spec.ts`. Seconda ondata da VERIFICARE al grep (importatori tipici: MessageBubble/ChatInput): `ChartViewer.vue`, `CADViewer.vue`, `composables/useCodeBlocks.ts`, eventuali altri. NON toccare (usati da Horizon/board/settings, verificato): `ToolConfirmationDialog`, `AskUserPrompt`, `MessageEditDialog`, `MessageVersionNav`, `CADGenerationPlaceholder`, `ChatToolControls`, `PermissionTierSelector`, `ScopeIndicator`, `ContextBar`, `MicrophoneButton`, `VoiceSettings`, `ImmersiveCADCanvas`, `useResizablePane`, `ConversationList`. Itera finché typecheck è verde e `Grep` non trova più riferimenti ai file cancellati.

- [ ] **Step 6: residui icone/CSS**

- `assets/icons.ts`: rimuovi le entry `'orb'` e `'orb-full'` (righe 166-170); poi `Grep "hybrid-panel" frontend/src` — se gli unici usi erano ChatInput/AppSidebar (ora morti), rimuovi anche `'hybrid-panel'`. Aggiorna l'esempio in docstring di `UiSegmented.vue:15` (usa `icon: 'home'`).
- `assets/styles/transitions.css`: rimuovi il blocco `@keyframes orbEntrance` + commento (righe 310-338).
- `Grep "alice_ui_mode|alice_workspace" frontend/src` → deve restare solo (eventualmente) la chiave nuova `alice_sidebar_width`; i vecchi localStorage non si migrano (dati azzerabili).

- [ ] **Step 7: verifica**

Da `frontend/`: `npm run typecheck` → PASS; `npm test` → PASS (gli spec workspace sono stati rimossi CON i moduli); `npx eslint <tutti i file modificati non cancellati>` → zero errori nuovi. Grep finale: `Grep "useWorkspaceStore|moduleRegistry|WorkspaceView|HomeSurface|ModeSwitcher" frontend/src` → zero risultati.

- [ ] **Step 8: EOL + commit**

```
git add -A
git commit -m "feat(fe)!: Horizon is the only chat surface - remove Workspace stack and orb-era leftovers" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Client REST per dominio — package `services/api/`

Split PURO (i corpi dei metodi si spostano verbatim da `api.ts`, oggetto `api` incluso il commento di gruppo); unica modifica di comportamento: le 6 mutazioni KG tipizzate.

**Files:**
- Create: `frontend/src/renderer/src/services/api/http.ts`, `chat.ts`, `config.ts`, `models.ts`, `plugins.ts`, `voice.ts`, `settings.ts`, `calendar.ts`, `audit.ts`, `memory.ts`, `mcp.ts`, `mcpMemory.ts`, `email.ts`, `artifacts.ts`, `tasks.ts`, `scope.ts`, `permissions.ts`, `terminal.ts`, `index.ts`
- Modify: `frontend/src/renderer/src/types/mcpMemory.ts` (+alias `KGMutationResponse`), i ~38 file importatori sopravvissuti al Task 2 (spec inclusi)
- Delete: `frontend/src/renderer/src/services/api.ts`

- [ ] **Step 1: `http.ts` (core condiviso)**

Contenuto = righe 77-244 di `api.ts` spostate VERBATIM (classe `ApiError`, `BACKEND_BASE`, `BASE_URL`, `BACKEND_HOST`, `resolveBackendUrl`, `DEFAULT_REQUEST_TIMEOUT_MS`, `withTimeout`, `request`, `waitForBackend`) con due cambi: header docstring nuovo e **`BASE_URL` e `request` diventano `export`** (i moduli dominio li importano):

```ts
/**
 * Shared HTTP core for the per-domain REST clients (services/api/<domain>.ts).
 *
 * Owns the backend base URL, the generic `request` wrapper (JSON, timeout,
 * ApiError), URL resolution helpers and the startup readiness gate.
 */
```

- [ ] **Step 2: moduli dominio**

Ogni modulo segue lo stesso schema — esempio COMPLETO per `scope.ts` (gli altri sono identici nella forma):

```ts
/** Workspace-scope endpoints (`/api/scope`). */
import { request } from './http'
import type { ScopeResponse } from '../../types/scope'

export const scopeApi = {
  // corpi di getScope / setScope / clearScope spostati VERBATIM
  // da services/api.ts righe 880-903, docstring comprese
}
```

Mappa COMPLETA metodo→modulo (righe = `api.ts` sorgente; spostare verbatim, import di tipo al seguito):

| Modulo | Export | Metodi (righe api.ts) |
|---|---|---|
| `chat.ts` | `chatApi` | getConversations…branchConversation (253-347), uploadFile (438-461; importa `resolveBackendUrl`, `BASE_URL` da `./http`) |
| `config.ts` | `configApi` | getConfig, updateConfig, getResolvedConfig, patchConfig (395-434), syncModel (465-469) |
| `models.ts` | `modelsApi` | getModels, listModels, loadModel, unloadModel, downloadModel, getDownloadStatus, getModelsStatus, getModelOperation (351-393) |
| `plugins.ts` | `pluginsApi` | getPlugins, togglePlugin (473-481), executePluginTool (554-566) |
| `voice.ts` | `voiceApi` | getVoiceStatus (485-487), getAvailableVoiceEngines (543-550) |
| `settings.ts` | `settingsApi` | setToolConfirmations…setActiveTools, getPreferences, resetPreferences (491-541) |
| `calendar.ts` | `calendarApi` | getCalendarToday…deleteCalendarEvent (570-613) |
| `audit.ts` | `auditApi` | getAuditConfirmations (617-633) |
| `memory.ts` | `memoryApi`, `vectorStoreApi` | getMemories…getMemoryStats (637-674); getVectorStoreStats, reembedTools, repairVectorStore (796-809) |
| `mcp.ts` | `mcpApi` | getMcpServers, reconnectMcpServer (678-686) |
| `mcpMemory.ts` | `mcpMemoryApi` | getKnowledgeGraph…deleteKGObservations (690-748) **con le 6 mutazioni tipizzate** (Step 3) |
| `email.ts` | `emailApi` | getEmailInbox…getEmailFolders (752-792) |
| `artifacts.ts` | `artifactsApi` | listArtifacts…deleteArtifact (813-866) |
| `tasks.ts` | `tasksApi` | getTasks (870-872), getPlanDocument (874-876) |
| `scope.ts` | `scopeApi` | getScope, setScope, clearScope (880-903) |
| `permissions.ts` | `permissionsApi` | getPermissionMode, setPermissionMode (907-922), listPermissionRules, addPermissionRule, deletePermissionRule (926-953) |
| `terminal.ts` | `terminalApi` | listTerminals, createTerminal, updateTerminal, deleteTerminal (957-986) |

- [ ] **Step 3: mutazioni KG tipizzate**

In `types/mcpMemory.ts` aggiungi (accanto agli altri alias):

```ts
import type { ApiSchema } from './generated'

/** Mutation acknowledgement for the 6 KG mutation endpoints. */
export type KGMutationResponse = ApiSchema<'KGMutationResponse'>
```

In `services/api/mcpMemory.ts` le 6 mutazioni diventano `Promise<KGMutationResponse>` / `request<KGMutationResponse>(…)` (identiche per il resto). Lo store `mcpMemory.ts` non dipende dal valore di ritorno (ricarica il grafo) — nessun altro cambio.

- [ ] **Step 4: `index.ts` (barrel del package)**

```ts
/**
 * Per-domain REST clients for the AL\CE backend (Fase 6).
 *
 * Import the domain namespace you need (`chatApi`, `artifactsApi`, …) or the
 * shared HTTP infrastructure (`ApiError`, `BACKEND_HOST`, `resolveBackendUrl`,
 * `waitForBackend`). There is NO aggregated legacy `api` object.
 */
export { ApiError, BACKEND_HOST, resolveBackendUrl, waitForBackend } from './http'
export { chatApi } from './chat'
export { configApi } from './config'
export { modelsApi } from './models'
export { pluginsApi } from './plugins'
export { voiceApi } from './voice'
export { settingsApi } from './settings'
export { calendarApi } from './calendar'
export { auditApi } from './audit'
export { memoryApi, vectorStoreApi } from './memory'
export { mcpApi } from './mcp'
export { mcpMemoryApi } from './mcpMemory'
export { emailApi } from './email'
export { artifactsApi } from './artifacts'
export { tasksApi } from './tasks'
export { scopeApi } from './scope'
export { permissionsApi } from './permissions'
export { terminalApi } from './terminal'
```

- [ ] **Step 5: `git rm frontend/src/renderer/src/services/api.ts` e migra i ~38 importatori**

Il path `'../services/api'` (e l'alias `@renderer/services/api`) ora risolve sull'`index.ts` del package: si cambia SOLO il simbolo importato e i call-site `api.<metodo>` → `<dominio>Api.<metodo>` secondo la tabella dello Step 2. Mappa per file (post Task 2):

stores: `artifacts→artifactsApi`; `calendar→calendarApi`; `chat→chatApi + resolveBackendUrl`; `email→emailApi`; `mcp→mcpApi`; `mcpMemory→mcpMemoryApi`; `memory→memoryApi`; `permissionMode→permissionsApi`; `planDocument→tasksApi`; `scope→scopeApi (+ApiError nello spec)`; `services→BACKEND_HOST`; `settings→configApi/modelsApi/settingsApi/voiceApi (per metodo, seguire la tabella)`; `plugins→pluginsApi`; `tasks→tasksApi`; `terminalSessions→terminalApi`.
composables: `useChat→chatApi`; `useCalendar→calendarApi`; `useEventsWebSocket→BACKEND_HOST`; `useVoice→BACKEND_HOST`.
componenti: `App.vue→waitForBackend`; `TldrawCanvas→artifactsApi (verificare i metodi usati)`; `VoiceSettings→voiceApi/settingsApi`; `ArtifactPreview3D/ArtifactCard/CADViewer*/ImmersiveCADCanvas→resolveBackendUrl`; `WeatherWidget/SearchResultsPanel/NetworkProbePanel→pluginsApi`; `ScopeIndicator→ApiError`; `CalendarEventModal→calendarApi`; `AppSidebar→chatApi`; `VectorStoreManager→vectorStoreApi`; `PermissionRulesManager→permissionsApi`. (*se sopravvissuti al Task 2.)

**Spec/mock**: i `vi.mock('../services/api', …)` diventano mock del namespace di dominio. Esempio per `scope.spec.ts` (pattern per tutti):

```ts
vi.mock('../services/api', () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
    ) {
      super(message)
      this.name = 'ApiError'
    }
  }
  return {
    ApiError,
    scopeApi: {
      getScope: vi.fn(),
      setScope: vi.fn(),
      clearScope: vi.fn(),
    },
  }
})

const getScopeMock = vi.mocked(scopeApi.getScope)
```

- [ ] **Step 6: verifica**

`Grep "from '.*services/api'" frontend/src -o` → nessun import residuo del simbolo `api`; `Grep "\bapi\." frontend/src/renderer/src --glob "*.{ts,vue}"` → verificare che i residui siano falsi positivi (es. `xxxApi.`). Da `frontend/`: `npm run typecheck` → PASS; `npm test` → PASS; `npx eslint src/renderer/src/services/api` → zero errori.

- [ ] **Step 7: EOL + commit**

```
git add -A
git commit -m "refactor(fe): split flat api.ts into per-domain REST clients (services/api/)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Dispatcher tipizzato sul canale chat-WS

**Files:**
- Rewrite (sezione emitter): `frontend/src/renderer/src/services/ws.ts`
- Rewrite (sezione handler, righe 106-412): `frontend/src/renderer/src/composables/useChat.ts`

- [ ] **Step 1: `ws.ts` — da emitter a stringhe a socket tipizzato**

Mantieni INVARIATE: connessione/reconnect (righe 44-147), backpressure/send/drain (149-203). Sostituisci la parte emitter (righe 13-14, 25, 68-95, 205-243) così:

```ts
import type { ChatServerMessage } from '../types/generated'
import { BACKEND_HOST } from './api'

/** Socket-level lifecycle events (NOT contract frames). */
type SocketEvent = 'connected' | 'disconnected' | 'error' | 'reconnect_failed' | 'binary'
type SocketEventHandler = (payload?: unknown) => void
/** Handler receiving every parsed server frame (exhaustive dispatch upstream). */
type FrameHandler = (msg: ChatServerMessage) => void
```

- campo `private handlers: Map<string, MessageHandler[]>` → due campi: `private frameHandlers: FrameHandler[] = []` e `private socketHandlers: Map<SocketEvent, SocketEventHandler[]> = new Map()`;
- `onmessage` diventa:

```ts
    this.ws.onmessage = (event: MessageEvent): void => {
      let frame: ChatServerMessage
      try {
        frame = JSON.parse(event.data as string) as ChatServerMessage
      } catch {
        // Binary data (e.g. audio frames) — pass through raw.
        this.emitSocket('binary', event.data)
        return
      }
      for (const handler of this.frameHandlers.slice()) {
        try {
          handler(frame)
        } catch (err) {
          console.error('[ALICE WS] Frame handler threw:', err)
        }
      }
    }
```
- `onopen`/`onclose`/`onerror` chiamano `this.emitSocket('connected')` ecc.;
- API pubblica: `onFrame(h: FrameHandler)`, `offFrame(h: FrameHandler)`, `on(event: SocketEvent, h: SocketEventHandler)`, `off(event: SocketEvent, h: SocketEventHandler)`; `emitSocket` privato con lo stesso snapshot+isolamento del vecchio `emit`;
- `send(data: unknown)` resta `unknown` nella firma (il frame utente `WsSendPayload` è fuori dall'unione client per decisione 1b — documentalo nella docstring del metodo).

- [ ] **Step 2: `useChat.ts` — mappa esaustiva**

Sostituisci le sezioni "WS event handlers" + "Register handlers & connect" + il blocco `onScopeDispose` (righe 106-412) con il pattern events. Struttura (i CORPI dei singoli handler restano quelli attuali, spostati dentro la mappa; spariscono TUTTI i cast `data as Ws*`, il parametro arriva già ristretto via `Extract`):

```ts
import type { ChatServerMessage } from '../types/generated'

/**
 * Exhaustive map of chat-WS frame types to handlers. Adding a frame to the
 * backend ws_schema and regenerating the contracts makes this object FAIL TO
 * COMPILE until the new frame is handled (or explicitly no-op'd) — same
 * guarantee the events channel has had since 1b.
 */
type ChatHandlerMap = {
  [K in ChatServerMessage['type']]: (msg: Extract<ChatServerMessage, { type: K }>) => void
}
```

Dentro `useChat()`:

```ts
  const noop = (): void => {}
  const handlers: ChatHandlerMap = {
    token: (msg) => { /* corpo attuale di onToken, senza cast */ },
    thinking: (msg) => { /* corpo di onThinking */ },
    done: (msg) => { /* corpo di onDone */ },
    error: (msg) => {
      // Server-side error frame (native WS errors arrive via the socket-level
      // 'error' event, not here).
      console.error('[useChat] Server error:', msg.content)
    },
    warning: (msg) => console.warn('[useChat] Server warning:', msg.content),
    tool_call: (msg) => console.debug('[useChat] Legacy tool_call frame:', msg),
    tool_execution_start: (msg) => { /* corpo di onToolExecutionStart */ },
    tool_execution_done: (msg) => { /* corpo di onToolExecutionDone */ },
    tool_progress: (msg) => { /* corpo di onToolProgress */ },
    tool_confirmation_required: (msg) => { /* corpo di onToolConfirmationRequired */ },
    ask_user_required: (msg) => { /* corpo di onAskUserRequired */ },
    llm_requery: (msg) => { /* corpo di onLlmRequery */ },
    context_info: (msg) => { /* corpo di onContextInfo */ },
    context_compression_start: () => { /* corpo di onContextCompressionStart */ },
    context_compression_done: (msg) => { /* corpo di onContextCompressionDone */ },
    context_compression_failed: () => { /* corpo di onContextCompressionFailed */ },
    // Client-tool bridge: no renderer executor is wired yet (dormant since 1b).
    client_tool_call: noop,
    // Reflective-executor telemetry frames — no UI surface yet (backlog).
    'agent.critic_invoked': noop,
    'agent.warning': (msg) => console.warn('[useChat] Agent warning frame:', msg),
    'turn.started': (msg) => agentRunStore.applyTurnStarted(msg),
    'turn.llm_step': (msg) => agentRunStore.applyLlmStep(msg),
    'tool.call': (msg) => agentRunStore.applyToolCall(msg),
    'tool.result': (msg) => agentRunStore.applyToolResult(msg),
    'interaction.requested': (msg) => agentRunStore.applyInteractionRequested(msg),
    'interaction.resolved': (msg) => agentRunStore.applyInteractionResolved(msg),
    'turn.usage': (msg) => agentRunStore.applyTurnUsage(msg),
    'turn.finished': (msg) => agentRunStore.applyTurnFinished(msg)
  }

  const dispatchFrame = (frame: ChatServerMessage): void => {
    const handler = handlers[frame.type] as ((msg: ChatServerMessage) => void) | undefined
    if (handler) {
      handler(frame)
    } else {
      // Runtime safety net for frames newer than the bundled contract.
      console.warn('[useChat] Unhandled chat frame type:', (frame as { type?: string }).type)
    }
  }

  wsManager.onFrame(dispatchFrame)
  wsManager.on('connected', onConnected)
  wsManager.on('disconnected', onDisconnected)
  wsManager.on('error', onSocketError)
  wsManager.on('reconnect_failed', onReconnectFailed)
```

`onConnected`/`onDisconnected`/`onReconnectFailed` restano identici; `onError` si rinomina `onSocketError` e perde il check `instanceof Event` (arrivano SOLO errori socket-level). Il cleanup `onScopeDispose` rimuove `offFrame(dispatchFrame)` + i 4 socket-level. Le guardie stale-generation (`store.streamGeneration !== activeGeneration`) restano DENTRO i corpi. Se un tipo di `types/chat.ts`/`types/turn.ts` non combacia col generato a typecheck: correggi l'ALIAS (deve essere `ApiSchema<'…'>`), MAI castare. Gli import `Ws*Message` non più usati si rimuovono.

- [ ] **Step 3: verifica**

`npm run typecheck` → PASS (l'esaustività è verificata dal compilatore: prova a commentare una chiave → deve fallire, poi ripristina); `npm test` → PASS; `npx eslint src/renderer/src/services/ws.ts src/renderer/src/composables/useChat.ts` → zero errori.

- [ ] **Step 4: EOL + commit**

```
git add -A
git commit -m "feat(fe): exhaustive typed dispatcher for the chat WS channel (parity with events)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Command Registry (spec §7, lato frontend)

**Files:**
- Create: `frontend/src/renderer/src/commands/types.ts`, `commands/registry.ts`, `commands/core.ts`, `commands/index.ts`, `commands/registry.spec.ts`, `commands/core.spec.ts`
- Modify: `frontend/src/renderer/src/App.vue` (installazione), `frontend/src/renderer/src/components/sidebar/AppSidebar.vue` (call-site)

- [ ] **Step 1: `commands/types.ts`**

```ts
/**
 * Command Layer types (spec §7).
 *
 * Every UI capability is a named command with a typed handler and a
 * capability tag. In Fase 7 the registry's agent-exposable subset becomes the
 * manifest sent to the backend (`app_command` tool); `exposeToAgent` is the
 * structural anti-escalation seam: commands touching permission mode, scope,
 * allowlists or guardrail config MUST NEVER set it.
 */

/** What a command does to the app — used for permission-mode gating (Fase 7). */
export type CommandCapability = 'navigation' | 'read' | 'mutate' | 'destructive'

export interface CommandDefinition<A = Record<string, never>> {
  /** Unique dotted name, `domain.action` (e.g. `view.switch`). */
  name: string
  /** Human-readable label (command palette / audit). */
  title: string
  capability: CommandCapability
  /**
   * Whether the command may appear in the agent-callable manifest (Fase 7).
   * Defaults to false; guardrail commands must never be exposable.
   */
  exposeToAgent?: boolean
  /** JSON-Schema-like description of `args` (feeds the Fase 7 manifest). */
  argsSchema?: Record<string, unknown>
  /** The single implementation of the capability. */
  run: (args: A) => Promise<unknown> | unknown
}
```

- [ ] **Step 2: `commands/registry.ts`**

```ts
/**
 * Frontend Command Registry (spec §7) — single registration point for UI
 * commands. UI call sites and (from Fase 7) the agent bridge execute the
 * SAME commands: one implementation per capability.
 */
import type { CommandDefinition } from './types'

export class CommandNotFoundError extends Error {
  constructor(name: string) {
    super(`Command not registered: ${name}`)
    this.name = 'CommandNotFoundError'
  }
}

export class DuplicateCommandError extends Error {
  constructor(name: string) {
    super(`Command already registered: ${name}`)
    this.name = 'DuplicateCommandError'
  }
}

export class CommandRegistry {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- heterogeneous arg shapes live in one map; typing is at the register/execute seam
  private commands = new Map<string, CommandDefinition<any>>()

  /** Register a command. Throws {@link DuplicateCommandError} on name reuse. */
  register<A>(def: CommandDefinition<A>): void {
    if (this.commands.has(def.name)) throw new DuplicateCommandError(def.name)
    this.commands.set(def.name, def)
  }

  /** Remove a command (no-op if absent). */
  unregister(name: string): void {
    this.commands.delete(name)
  }

  has(name: string): boolean {
    return this.commands.has(name)
  }

  /** Snapshot of all registered definitions (stable order of registration). */
  list(): CommandDefinition<unknown>[] {
    return [...this.commands.values()]
  }

  /** Execute a command by name. Throws {@link CommandNotFoundError} if absent. */
  async execute<A>(name: string, args: A): Promise<unknown> {
    const def = this.commands.get(name)
    if (!def) throw new CommandNotFoundError(name)
    return await def.run(args)
  }

  /** Test helper: drop every registration. */
  clear(): void {
    this.commands.clear()
  }
}

/** App-wide singleton registry. */
export const commandRegistry = new CommandRegistry()
```

- [ ] **Step 3: `commands/core.ts`** (i core command; gli store si risolvono DENTRO i run così pinia è attiva)

```ts
/**
 * Core UI commands (Fase 6): navigation and conversation lifecycle.
 *
 * Registered once at app startup by {@link installCoreCommands}. Handlers
 * resolve Pinia stores lazily (at execution time) so registration can happen
 * before store initialisation.
 */
import type { Router } from 'vue-router'
import { commandRegistry } from './registry'
import { useChatStore } from '../stores/chat'
import { useUIStore } from '../stores/ui'

/** Route names addressable via `view.switch`. */
export const SWITCHABLE_VIEWS = [
  'assistant',
  'calendar',
  'settings',
  'email',
  'whiteboard',
  'board',
  'terminal',
  'services',
] as const
export type SwitchableView = (typeof SWITCHABLE_VIEWS)[number]

export interface ViewSwitchArgs {
  view: SwitchableView
}
export interface ConversationOpenArgs {
  conversation_id: string
}
export interface ArtifactShowArgs {
  artifact_id: string
}

export function installCoreCommands(router: Router): void {
  commandRegistry.register<ViewSwitchArgs>({
    name: 'view.switch',
    title: 'Vai alla vista',
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { view: { type: 'string', enum: [...SWITCHABLE_VIEWS] } },
      required: ['view'],
    },
    run: async ({ view }) => {
      if (!SWITCHABLE_VIEWS.includes(view)) {
        throw new Error(`Unknown view: ${String(view)}`)
      }
      await router.push({ name: view })
    },
  })

  commandRegistry.register<ConversationOpenArgs>({
    name: 'conversation.open',
    title: 'Apri conversazione',
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { conversation_id: { type: 'string' } },
      required: ['conversation_id'],
    },
    run: async ({ conversation_id }) => {
      const chatStore = useChatStore()
      await chatStore.loadConversation(conversation_id)
      if (router.currentRoute.value.name !== 'assistant') {
        await router.push('/assistant')
      }
    },
  })

  commandRegistry.register({
    name: 'conversation.new',
    title: 'Nuova conversazione',
    capability: 'mutate',
    argsSchema: { type: 'object', properties: {} },
    run: async () => {
      const chatStore = useChatStore()
      await chatStore.createConversation()
      if (router.currentRoute.value.name !== 'assistant') {
        await router.push('/assistant')
      }
    },
  })

  commandRegistry.register({
    name: 'sidebar.toggle',
    title: 'Mostra/nascondi sidebar',
    capability: 'navigation',
    argsSchema: { type: 'object', properties: {} },
    run: () => {
      useUIStore().toggleSidebar()
    },
  })

  commandRegistry.register<ArtifactShowArgs>({
    name: 'artifact.show',
    title: 'Mostra artefatto',
    capability: 'navigation',
    argsSchema: {
      type: 'object',
      properties: { artifact_id: { type: 'string' } },
      required: ['artifact_id'],
    },
    run: async ({ artifact_id }) => {
      await router.push({ name: 'board', query: { artifact: artifact_id } })
    },
  })
}
```

- [ ] **Step 4: `commands/index.ts`**

```ts
export type { CommandCapability, CommandDefinition } from './types'
export { CommandRegistry, commandRegistry, CommandNotFoundError, DuplicateCommandError } from './registry'
export { installCoreCommands, SWITCHABLE_VIEWS } from './core'
export type { SwitchableView, ViewSwitchArgs, ConversationOpenArgs, ArtifactShowArgs } from './core'
```

- [ ] **Step 5: installazione in `App.vue`**

Nel `<script setup>` (dopo `const router = useRouter()`):

```ts
import { installCoreCommands } from './commands'
// Register the core UI commands once for the app lifetime (spec §7 registry;
// the agent-facing manifest arrives in Fase 7).
installCoreCommands(router)
```

- [ ] **Step 6: call-site `AppSidebar.vue`**

`onSelect`/`onCreate` delegano ai comandi (la logica di navigazione vive UNA volta, in `core.ts`):

```ts
import { commandRegistry } from '../../commands'

/** Select an existing conversation via the command layer. */
async function onSelect(id: string): Promise<void> {
  try {
    await commandRegistry.execute('conversation.open', { conversation_id: id })
  } catch (err) {
    console.error(`[AppSidebar] Failed to open conversation ${id}:`, err)
  }
}

/** Start a new conversation via the command layer. */
async function onCreate(): Promise<void> {
  try {
    await commandRegistry.execute('conversation.new', {})
  } catch (err) {
    console.error('[AppSidebar] Failed to start a new conversation:', err)
  }
}
```
`onHome` diventa: `toggle()`, poi `if (chatStore.messages.length > 0) → execute('conversation.new', {})` altrimenti `execute('view.switch', { view: 'assistant' })`, con lo stesso try/catch.

- [ ] **Step 7: test — `commands/registry.spec.ts`**

```ts
/** Unit tests for the Command Registry (vitest node env, no DOM). */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { CommandRegistry, CommandNotFoundError, DuplicateCommandError } from './registry'

let reg: CommandRegistry
beforeEach(() => {
  reg = new CommandRegistry()
})

describe('register/list', () => {
  it('registers and lists definitions in order', () => {
    reg.register({ name: 'a.one', title: 'A', capability: 'read', run: () => 1 })
    reg.register({ name: 'b.two', title: 'B', capability: 'mutate', run: () => 2 })
    expect(reg.list().map((d) => d.name)).toEqual(['a.one', 'b.two'])
    expect(reg.has('a.one')).toBe(true)
  })

  it('throws on duplicate names', () => {
    reg.register({ name: 'a.one', title: 'A', capability: 'read', run: () => 1 })
    expect(() =>
      reg.register({ name: 'a.one', title: 'A2', capability: 'read', run: () => 2 }),
    ).toThrow(DuplicateCommandError)
  })

  it('exposeToAgent defaults to undefined/false', () => {
    reg.register({ name: 'a.one', title: 'A', capability: 'read', run: () => 1 })
    expect(reg.list()[0].exposeToAgent ?? false).toBe(false)
  })
})

describe('execute', () => {
  it('runs the handler with args and returns its value', async () => {
    const run = vi.fn().mockResolvedValue('ok')
    reg.register({ name: 'x.y', title: 'X', capability: 'navigation', run })
    await expect(reg.execute('x.y', { k: 1 })).resolves.toBe('ok')
    expect(run).toHaveBeenCalledWith({ k: 1 })
  })

  it('throws CommandNotFoundError for unknown names', async () => {
    await expect(reg.execute('nope', {})).rejects.toThrow(CommandNotFoundError)
  })

  it('unregister removes the command', async () => {
    reg.register({ name: 'x.y', title: 'X', capability: 'navigation', run: () => 0 })
    reg.unregister('x.y')
    await expect(reg.execute('x.y', {})).rejects.toThrow(CommandNotFoundError)
  })
})
```

- [ ] **Step 8: test — `commands/core.spec.ts`**

```ts
/**
 * Core-commands tests: registration metadata + navigation handlers.
 * Store-backed handlers are exercised with a fresh Pinia and mocked API.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { Router } from 'vue-router'
import { commandRegistry } from './registry'
import { installCoreCommands, SWITCHABLE_VIEWS } from './core'

vi.mock('../services/api', () => ({
  chatApi: {
    getConversations: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    createConversation: vi.fn(),
    getConversation: vi.fn(),
  },
  resolveBackendUrl: (p: string) => p,
}))

function fakeRouter(routeName = 'assistant'): Router {
  return {
    push: vi.fn().mockResolvedValue(undefined),
    currentRoute: { value: { name: routeName } },
  } as unknown as Router
}

beforeEach(() => {
  setActivePinia(createPinia())
  commandRegistry.clear()
})

describe('installCoreCommands', () => {
  it('registers the Fase 6 core set with the spec §7 capability tags', () => {
    installCoreCommands(fakeRouter())
    const byName = new Map(commandRegistry.list().map((d) => [d.name, d]))
    expect([...byName.keys()].sort()).toEqual([
      'artifact.show',
      'conversation.new',
      'conversation.open',
      'sidebar.toggle',
      'view.switch',
    ])
    expect(byName.get('view.switch')?.capability).toBe('navigation')
    expect(byName.get('conversation.new')?.capability).toBe('mutate')
    // Anti-escalation seam: nothing in the core set is agent-exposable yet.
    for (const def of byName.values()) expect(def.exposeToAgent ?? false).toBe(false)
  })

  it('view.switch pushes the named route and rejects unknown views', async () => {
    const router = fakeRouter()
    installCoreCommands(router)
    await commandRegistry.execute('view.switch', { view: 'settings' })
    expect(router.push).toHaveBeenCalledWith({ name: 'settings' })
    await expect(
      commandRegistry.execute('view.switch', { view: 'not-a-view' }),
    ).rejects.toThrow(/Unknown view/)
  })

  it('every SWITCHABLE_VIEWS entry is accepted', async () => {
    const router = fakeRouter()
    installCoreCommands(router)
    for (const view of SWITCHABLE_VIEWS) {
      await commandRegistry.execute('view.switch', { view })
    }
    expect(router.push).toHaveBeenCalledTimes(SWITCHABLE_VIEWS.length)
  })

  it('artifact.show routes to the board with the artifact query', async () => {
    const router = fakeRouter()
    installCoreCommands(router)
    await commandRegistry.execute('artifact.show', { artifact_id: 'a1' })
    expect(router.push).toHaveBeenCalledWith({ name: 'board', query: { artifact: 'a1' } })
  })
})
```
NOTA: se il mock di `../services/api` per lo store chat richiede altri metodi (lo store viene importato transitivamente), estendi il mock finché `npm test` è verde — MAI importare il backend vero.

- [ ] **Step 9: verifica + commit**

`npm run typecheck` → PASS; `npm test` → PASS (nuovi spec inclusi); `npx eslint src/renderer/src/commands src/renderer/src/App.vue src/renderer/src/components/sidebar/AppSidebar.vue` → zero errori.

```
git add -A
git commit -m "feat(fe): Command Registry with capability tags and core UI commands (spec §7)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Eventi artifacts (bulk delete + live-update whiteboard) + sanature contratti (CAD export_url, AgentTier) — UNICO task con regen

**Files:**
- Modify: `backend/api/ws_schema/events.py` (+frame, +union), `backend/services/artifacts/registry.py` (emissioni), `backend/services/artifacts/parsers.py` (via `export_url` dai metadata), `backend/tests/contracts/test_ws_schema_events.py` (vocabolario+frame), `backend/tests/test_artifact_registry.py` (+2 test emissione)
- Regen: `frontend/src/renderer/src/types/generated/*` via `.\scripts\gen-contracts.ps1`
- Modify: `frontend/src/renderer/src/stores/artifacts.ts` (+2 azioni), `frontend/src/renderer/src/composables/useEventsWebSocket.ts` (+1 handler, 1 cambiato), `frontend/src/renderer/src/types/settings.ts` (AgentTier alias), consumer FE di `meta.export_url` residui

- [ ] **Step 1: frame backend**

In `events.py`, dopo `WsArtifactDeleted` (riga 178):

```python
class WsArtifactsBulkDeleted(EventsServerFrame):
    """Bulk artifact deletion (conversation cleanup or full wipe).

    ``conversation_id`` is ``None`` for the delete-all wipe.  Pinned
    artifacts of a deleted conversation survive detached
    (``conversation_id=NULL``) and are NOT listed in ``artifact_ids``.
    """

    type: Literal["artifact.bulk_deleted"]
    conversation_id: str | None = None
    artifact_ids: list[str]
```

Aggiungi `WsArtifactsBulkDeleted` all'unione `EventsServerMessage` (dopo `WsArtifactDeleted`, riga 379). Se `backend/api/ws_schema/__init__.py` ri-esporta i frame per nome, aggiungilo lì.

- [ ] **Step 2: emissioni nel registry**

In `delete_for_conversation` (registry.py), dopo il loop di cleanup file (riga 512), PRIMA del `return`:

```python
        if unpinned:
            await self._emit_event({
                "type": "artifact.bulk_deleted",
                "conversation_id": str(conv_uuid),
                "artifact_ids": [str(aid) for aid, _ in unpinned],
            })
        return len(unpinned)
```
Aggiorna la docstring (via la frase "No per-row WS events (bulk operation)", ora: "Emits a single ``artifact.bulk_deleted`` event.").

In `delete_all`, dopo il loop file (riga 531), PRIMA del `return`:

```python
        if rows:
            await self._emit_event({
                "type": "artifact.bulk_deleted",
                "conversation_id": None,
                "artifact_ids": [str(aid) for aid, _ in rows],
            })
        return len(rows)
```
(docstring: via "No WS events.")

- [ ] **Step 3: CAD `export_url` fuori dai metadata**

In `parsers.py` rimuovi la riga `"export_url": payload.get("export_url"),` da ENTRAMBI i parser CAD (`_parse_cad_generate`, riga 148, e `_parse_cad_generate_from_image`, analoga). `Grep "export_url" backend/` per verificare che i residui siano SOLO: plugin cad_generator (payload live, INVARIATO per decisione 7), route `api/routes/cad.py` (legacy, resta), eventuali test da aggiornare. Poi `Grep "export_url" frontend/src`: i consumer del PAYLOAD live (`horizonArtifacts.ts:53`, `ImmersiveCADCanvas`, `MessageBubble`* , `types/chat.ts`) restano invariati; eventuali consumer dei METADATA artifact (`meta.export_url` — `Cad3dModule` è morto nel Task 2) passano ad `artifact.download_url`. (*se sopravvissuto al Task 2.)

- [ ] **Step 4: contratti backend**

In `test_ws_schema_events.py`: aggiungi `"artifact.bulk_deleted"` a `EXPECTED_EVENTS_SERVER_TYPES` (dopo `"artifact.deleted"`, riga 38) e due frame rappresentativi in `REPRESENTATIVE_SERVER_FRAMES`:

```python
    {
        "type": "artifact.bulk_deleted",
        "conversation_id": "c0ffee00-0000-0000-0000-000000000000",
        "artifact_ids": ["a1", "a2"],
    },
    {"type": "artifact.bulk_deleted", "conversation_id": None, "artifact_ids": []},
```

In `test_artifact_registry.py` aggiungi due test accanto a quelli di delete esistenti (segui le fixture del file — registry con `set_event_callback` che accumula in lista):

```python
async def test_delete_for_conversation_emits_bulk_event(registry_with_events):
    """delete_for_conversation emits one artifact.bulk_deleted with the unpinned ids."""
    # arrange: 2 unpinned + 1 pinned artifact nella stessa conversazione (riusa gli helper del file)
    # act: await registry.delete_for_conversation(conv_id)
    # assert: l'ultimo evento è {"type": "artifact.bulk_deleted", "conversation_id": str(conv_id),
    #         "artifact_ids": [i due id unpinned]} e il pinned NON è elencato


async def test_delete_all_emits_bulk_event_with_null_conversation(registry_with_events):
    """delete_all emits artifact.bulk_deleted with conversation_id=None and every id."""
```
(I corpi seguono ESATTAMENTE il pattern arrange/act/assert dei test di delete già presenti nel file — stessi helper di creazione artifact; il commento sopra è la specifica del comportamento da asserire, non un TODO.)

Esegui da `backend/`: `..\.venv\Scripts\python.exe -m pytest tests/contracts/test_ws_schema_events.py tests/test_artifact_registry.py -v` → PASS.

- [ ] **Step 5: regen contracts**

Da repo root: `.\scripts\gen-contracts.ps1` → rigenera `openapi.json` + `api.d.ts`. Verifica: `git diff --stat frontend/src/renderer/src/types/generated/` mostra il nuovo frame. **`npm run typecheck` ora DEVE fallire** su `useEventsWebSocket.ts` (chiave mancante nella mappa esaustiva) — è la garanzia 1b al lavoro.

- [ ] **Step 6: FE — store actions + handler**

In `stores/artifacts.ts`, dopo `removeLocal` (riga 202):

```ts
  /**
   * Fold an `artifact.updated` event: refresh the row AND, if the JSON
   * content is cached, force-refetch it so open viewers (whiteboard) react.
   */
  async function applyArtifactUpdated(id: string): Promise<void> {
    await refreshById(id)
    if (contents.value[id]) {
      await fetchContent(id, true)
    }
  }

  /**
   * Fold an `artifact.bulk_deleted` event. `conversationId === null` means a
   * full wipe (delete_all). Pinned artifacts of a deleted conversation
   * survive detached — mirror that locally by nulling their conversation_id.
   */
  function applyBulkDeleted(conversationId: string | null, artifactIds: string[]): void {
    if (conversationId === null) {
      // Full wipe: every row (pinned included) is gone server-side.
      items.value = []
      contents.value = {}
      total.value = 0
      return
    }
    for (const id of artifactIds) removeLocal(id)
    for (const a of items.value) {
      if (a.conversation_id === conversationId && a.pinned) {
        upsertById(a.id, { conversation_id: null })
      }
    }
    fetchedConversations.value.delete(conversationId)
    total.value = Math.max(0, total.value - artifactIds.length)
  }
```
Esporta entrambe nel return dello store.

In `useEventsWebSocket.ts` (mappa `handlers`):

```ts
    'artifact.updated': (msg) => void artifactsStore.applyArtifactUpdated(msg.artifact_id),
    'artifact.bulk_deleted': (msg) =>
      artifactsStore.applyBulkDeleted(msg.conversation_id ?? null, msg.artifact_ids),
```

**Live-update whiteboard**: verifica che la superficie whiteboard aperta reagisca alla cache invalidata — apri `WhiteboardPageView.vue`/`TldrawCanvas.vue`: se il canvas carica lo snapshot solo su mount/cambio board (com'era in WhiteboardModule), aggiungi un `watch(() => artifactsStore.contents[<boardId corrente>], (snap) => { /* re-import dello snapshot nel canvas */ })` nel componente che possiede il canvas, riusando la funzione di load già esistente nel file. Criterio di accettazione: con la board aperta, un `artifact.updated` per quella board ricarica le shape senza cambiare board o rimontare la view.

- [ ] **Step 7: `AgentTier` = alias del generato**

In `types/settings.ts` (riga 159):

```ts
import type { ApiSchema } from './generated'

/** Permission-tier keys for per-tier agent guidance overrides (generated vocab). */
export type AgentTier = ApiSchema<'PermissionMode'>
```
(L'import va in testa al file accanto agli altri; i consumatori — `utils/agentPrompts.ts`, `stores/settings.ts`, `AgentPersonaSettings.vue` — compilano invariati.)

- [ ] **Step 8: verifica completa**

`npm run typecheck` → PASS (la chiave mancante è stata aggiunta); `npm test` → PASS; da `backend/`: `..\.venv\Scripts\python.exe -m pytest tests/contracts/ tests/test_artifact_registry.py -v` → PASS (salvo rossi ereditati noti); boot-check da repo root:

```powershell
.\.venv\Scripts\python.exe -c "from backend.core.app import create_app; create_app(); print('boot ok')"
```

- [ ] **Step 9: EOL + commit + check contratti**

```
git add -A
git commit -m "feat(contracts): artifact.bulk_deleted event, whiteboard live-update, CAD metadata cleanup, AgentTier from generated vocab" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
DOPO il commit: `.\scripts\check-contracts.ps1` → PASS.

---

### Task 7: Lint sanato a fondo (errori + endOfLine + riformattazione completa)

**Files:**
- Modify: `frontend/.prettierrc.yaml`, `frontend/eslint.config.mjs`, i file con errori residui, l'intero renderer (riformattazione)

- [ ] **Step 1: config**

`.prettierrc.yaml` — aggiungi:

```yaml
endOfLine: auto
```

`eslint.config.mjs` — nel blocco rules (o come blocco dedicato prima di `eslintConfigPrettier`) aggiungi l'eccezione per i declaration file (idioma electron-vite in `env.d.ts`):

```js
  {
    files: ['**/*.d.ts'],
    rules: {
      '@typescript-eslint/triple-slash-reference': 'off'
    }
  },
```

- [ ] **Step 2: censisci gli errori residui**

Da `frontend/`: `npx eslint . 2>&1 | Select-String "error"` — la lista di partenza era 15 (10 return-type, 4 unused-vars, 1 triple-slash); i Task 2-4 ne hanno eliminati diversi (file cancellati o riscritti). Fix per categoria: **explicit-function-return-type** → annota il tipo di ritorno reale (mai `any`); **no-unused-vars** → rimuovi la variabile (se è un parametro obbligatorio di callback, rinominalo `_` e valuta l'opzione `argsIgnorePattern` SOLO se già presente nella config — non aggiungerla).

- [ ] **Step 3: riformattazione completa**

```powershell
npm run format
npx eslint --fix .
```
Poi il controllo EOL OBBLIGATORIO (gotcha 4, tre incidenti nel programma):

```powershell
git diff --stat
git diff --ignore-cr-at-eol --stat
```
I due output devono coincidere (nessun flip EOL mascherato da riformattazione). `git ls-files --eol frontend/src` → tutti `i/lf` come prima.

- [ ] **Step 4: `vue/no-v-html` residui**

Per ogni occorrenza rimasta (erano 6, alcune in file morti): se il contenuto è markdown sanitizzato renderizzato deliberatamente, aggiungi sopra l'elemento:

```html
<!-- eslint-disable-next-line vue/no-v-html -- sanitized markdown render -->
```
Altrimenti (HTML non sanitizzato da input non fidato) NON silenziare: segnala nel report di task.

- [ ] **Step 5: gate verde**

`npm run lint` → **exit 0, zero errori**; annota nel commit quanti warning restano (target: zero o giustificati). `npm run typecheck` → PASS; `npm test` → PASS.

- [ ] **Step 6: commit**

```
git add -A
git commit -m "style(fe): repo-wide prettier reformat, endOfLine auto, fix remaining eslint errors" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Gate CI frontend (lint + vitest) + `memory.spec.ts`

**Files:**
- Create: `frontend/src/renderer/src/stores/memory.spec.ts`
- Modify: `.github/workflows/contracts.yml`

- [ ] **Step 1: `memory.spec.ts`** (pattern identico a `scope.spec.ts`; lo store al Task 3 importa `memoryApi`)

```ts
/**
 * Unit tests for stores/memory.ts (vitest node env, no DOM).
 *
 * The store wraps the /api/memory endpoints: list (entries+total), semantic
 * search, per-id delete, session/all clear and stats, normalising every
 * failure into the `error` ref (it never throws).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

import { useMemoryStore } from './memory'
import { memoryApi } from '../services/api'
import type { MemoryEntry } from '../types/memory'

vi.mock('../services/api', () => ({
  memoryApi: {
    getMemories: vi.fn(),
    searchMemories: vi.fn(),
    deleteMemory: vi.fn(),
    clearSessionMemory: vi.fn(),
    clearAllMemory: vi.fn(),
    getMemoryStats: vi.fn(),
  },
}))

const getMemoriesMock = vi.mocked(memoryApi.getMemories)
const searchMock = vi.mocked(memoryApi.searchMemories)
const deleteMock = vi.mocked(memoryApi.deleteMemory)
const clearSessionMock = vi.mocked(memoryApi.clearSessionMemory)
const clearAllMock = vi.mocked(memoryApi.clearAllMemory)
const statsMock = vi.mocked(memoryApi.getMemoryStats)

function entry(id: string, scope = 'long_term'): MemoryEntry {
  return { id, scope, content: `memory ${id}` } as MemoryEntry
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(memoryApi.getMemories).mockReset()
  searchMock.mockReset()
  deleteMock.mockReset()
  clearSessionMock.mockReset()
  clearAllMock.mockReset()
  statsMock.mockReset()
})

describe('loadMemories', () => {
  it('fills entries and total from the list response', async () => {
    getMemoriesMock.mockResolvedValue({ items: [entry('a'), entry('b')], total: 2 })
    const s = useMemoryStore()
    await s.loadMemories()
    expect(s.entries.map((e) => e.id)).toEqual(['a', 'b'])
    expect(s.total).toBe(2)
    expect(s.loading).toBe(false)
    expect(s.error).toBeNull()
  })

  it('captures failures into error without throwing', async () => {
    getMemoriesMock.mockRejectedValue(new Error('boom'))
    const s = useMemoryStore()
    await s.loadMemories()
    expect(s.error).toBe('boom')
    expect(s.loading).toBe(false)
  })
})

describe('deleteMemory', () => {
  it('removes the entry locally and decrements total', async () => {
    getMemoriesMock.mockResolvedValue({ items: [entry('a'), entry('b')], total: 2 })
    deleteMock.mockResolvedValue({ deleted: true, id: 'a' } as never)
    const s = useMemoryStore()
    await s.loadMemories()
    await s.deleteMemory('a')
    expect(s.entries.map((e) => e.id)).toEqual(['b'])
    expect(s.total).toBe(1)
  })
})

describe('clearSessionMemory', () => {
  it('drops session-scoped entries and subtracts deleted_count', async () => {
    getMemoriesMock.mockResolvedValue({
      items: [entry('a', 'session'), entry('b', 'long_term')],
      total: 2,
    })
    clearSessionMock.mockResolvedValue({ deleted_count: 1 } as never)
    const s = useMemoryStore()
    await s.loadMemories()
    await s.clearSessionMemory()
    expect(s.entries.map((e) => e.id)).toEqual(['b'])
    expect(s.total).toBe(1)
  })
})

describe('clearAllMemory / search / stats', () => {
  it('clearAllMemory empties everything', async () => {
    getMemoriesMock.mockResolvedValue({ items: [entry('a')], total: 1 })
    clearAllMock.mockResolvedValue({ deleted_count: 1 } as never)
    const s = useMemoryStore()
    await s.loadMemories()
    await s.clearAllMemory()
    expect(s.entries).toEqual([])
    expect(s.total).toBe(0)
  })

  it('searchMemories fills searchResults and clearSearchResults empties them', async () => {
    searchMock.mockResolvedValue({ results: [{ entry: entry('a'), score: 0.9 }] } as never)
    const s = useMemoryStore()
    await s.searchMemories('query')
    expect(s.searchResults).toHaveLength(1)
    s.clearSearchResults()
    expect(s.searchResults).toEqual([])
  })

  it('loadStats stores the stats payload', async () => {
    statsMock.mockResolvedValue({ total: 5 } as never)
    const s = useMemoryStore()
    await s.loadStats()
    expect(s.stats).toEqual({ total: 5 })
  })
})
```
NOTA: allinea i literal (`MemoryEntry`, shape di `results`/`stats`) ai tipi REALI di `types/memory.ts` — se `as never`/`as MemoryEntry` non servono perché i tipi combaciano, rimuovili.

- [ ] **Step 2: CI**

In `contracts.yml`, dopo lo step "Frontend typecheck" (righe 58-60):

```yaml
      - name: Frontend lint
        working-directory: frontend
        run: npm run lint

      - name: Frontend tests
        working-directory: frontend
        run: npm test
```

- [ ] **Step 3: verifica + commit**

`npm test` → PASS (nuovo spec incluso); `npm run lint` → exit 0; `npm run typecheck` → PASS.

```
git add -A
git commit -m "ci(fe): lint and vitest gates in contracts.yml; memory store spec" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Gate finale di fase

1. Da `frontend/`: `npm run typecheck` + `npm run lint` (exit 0) + `npm test` → tutti PASS.
2. Da `backend/`: `..\.venv\Scripts\python.exe -m pytest tests/contracts/ tests/test_artifact_registry.py -v` → PASS (rossi ereditati esclusi).
3. Da repo root: boot-check `create_app` + `.\scripts\check-contracts.ps1` + `./.venv/Scripts/lint-imports --config backend/pyproject.toml` (6 contratti kept) → PASS.
4. Smoke funzionale (manuale o via `npm run dev`): l'app apre su `/assistant`; sidebar senza segmented; `/terminal` funziona (apertura sessione se `terminal.enabled`); `/whiteboard`, `/board`, `/settings`, `/email`, `/calendar`, `/services` raggiungibili; una conversazione si apre dalla sidebar (via command layer); vecchi deep-link `#/workspace`/`#/home`/`#/hybrid` redirigono.
5. Review finale di fase (modello top, range `arch/fase5-kernel..HEAD`, angolo: coerenza cross-task + regressioni di rimozione).
6. Aggiornare l'handoff (`docs/superpowers/handoffs/`) con stato post-fase6.

## Backlog di fase (fuori scope, registrare in fondo al piano a fine esecuzione)

- Unificazione COMPLETA del payload CAD live sull'endpoint artifacts (`/api/cad/models/{name}` rimovibile solo quando il payload del turno porta l'artifact id — richiede arricchimento del tool result in tool_loop, fase 7/8).
- Bridge `client_tool_call` nel renderer (frame oggi no-op esplicito).
- Frame di invio chat (`WsSendPayload`) senza `type` nel vocabolario client — valutare la promozione a frame tipizzato in fase 7 (breaking sul protocollo WS).
- Validazione runtime dei frame WS in ingresso (oggi cast al confine, come events — eventuale zod/valibot).
- Migrare i `<router-link>` di navigazione ai comandi quando la palette/manifest lo richiederà (fase 7).
- `artifact.show` porta `?artifact=` alla board: la view può imparare a evidenziare/scrollare l'artifact.
