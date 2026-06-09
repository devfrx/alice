# Home Rework — "Editorial Dossier" — Design

**Date:** 2026-06-09
**Branch:** `home-rework-editorial-dossier`
**Status:** Approved (design); spec under review

## Goal

Replace the current `HomeView.vue` (a landing/launcher page with mode selection and
marketing copy) with a personal, agentic entry surface — Alice's "desk." It greets the
user, lets them resume where they left off, and shows the living presence of the local
runtime. The aesthetic is **editorial / dossier**, not a SaaS dashboard ("cruscotto").
It becomes the default landing route and stays reachable from the sidebar.

Non-goals: rebuild AssistantView/WorkspaceView, change the chat engine, or add a
persisted agent-activity history (see Honesty constraint).

## Design principles

- **Abandon the landing page.** No "here's what I can do, pick a mode." Instead: a
  greeting + a hero input that starts a real turn + real context to resume.
- **Editorial, not dashboard.** Strong typographic hierarchy, asymmetry, generous space,
  monochrome + one accent, content framed as a dated dossier. No grid of identical widget
  cards. This is what keeps the dense "agentic" feeling from sliding into AI slop.
- **Honesty constraint (critical).** Every element must be backed by data that *exists
  today*. There is **no persisted log of past agent activity** (`agentRunStore.currentRun`
  is live-only and ephemeral), so the home must NOT render a fabricated "what Alice did"
  timeline. Real signals only.
- **Reuse first.** Reuse existing components, the real turn-start flow, and the existing
  CSS theme tokens. Create new generic UI only where justified. Zero hardcoded colors.

## Aesthetic direction

- **Palette:** the existing theme (`assets/styles/theme.css`) is already the Claude
  Desktop palette — warm cream "Panna" (`--accent: #E8DCC8`) on a neutral dark base
  (`--bg-primary: #1A1A19`); ivory/Taupe-Mocha in light mode. The dossier sits on this
  natively. Use only existing tokens.
- **Typography:** body stays Geist (`--font-sans`). The greeting is the **only** serif
  element — **Fraunces**, loaded scoped to the greeting component. This is consistent
  with the deliberate global retirement of the display serif (`--font-display` →
  `--font-sans` in theme.css); we are not reintroducing serif globally, only for the one
  hero line. Kicker and colophon use `--font-mono`.
- **Atmosphere:** a single, very subtle warm radial light (cream, ~4% alpha) in one
  corner via pure CSS. Optional faint grain. No purple gradients. Gated behind
  `[data-reduce-motion]` / `prefers-reduced-motion` where it animates.

## Layout (top → bottom, single editorial column, max-width ~680px)

1. **Kicker** — mono, uppercase, muted: full date · "runtime locale" · status dot · time.
2. **Greeting** — Fraunces, large: `Buon{giorno|pomeriggio|asera}, <nome>.` Time-of-day
   from the clock; `<nome>` from the preferred-name setting (omitted gracefully if unset).
3. **Lede** — one warm line built from real counts (e.g. "Hai N conversazioni aperte e M
   ricordi in memoria. Da dove ripartiamo?"). Degrades when counts are zero.
4. **Hero composer** — large editorial input → starts a real turn.
5. **Intents** — chips that prefill the composer; one ("Riprendi l'ultima") navigates.
6. **Resume** — recent conversations rendered as dated dossier entries.
7. **Colophon** — mono runtime status line: local model · memory · services · RAG.

## Component architecture

Decomposed into small single-responsibility components under
`frontend/src/renderer/src/components/home/` (new folder), orchestrated by a rewritten
`views/HomeView.vue`.

| Component | Responsibility | Real data / reuse |
|---|---|---|
| `views/HomeView.vue` (rewrite) | Layout/orchestration; reads stores, wires actions | router, pinia stores, `useChat` |
| `home/HomeGreeting.vue` | Kicker + Fraunces greeting + lede | clock; `settingsStore.settings.llm.userPreferredName`; counts from `chat`/`memory` |
| `home/HomeComposer.vue` | Hero input; submit/voice | **`useChat().sendMessage`**, `useVoice` (optional mic), `AppIcon` |
| `home/HomeIntents.vue` | Intent chips | `AppIcon`; emits prefill/navigate |
| `home/HomeResume.vue` | "Riprendi" dossier list | `chatStore.conversations`; time-ago util; `UiEmptyState` for zero-state |
| `home/HomeResumeEntry.vue` | One dated entry (when / title / meta / →) | — |
| `home/HomeColophon.vue` | Runtime status (mono) | `servicesStore`, `settingsStore.activeModel`, `memoryStore.stats`, `servicesStore.knowledge` |

**Reused as-is:** `AppIcon`, `UiButton`, `UiEmptyState`, all Pinia stores, theme tokens.

**Deliberately NOT reused:** `ChatInput.vue` for the hero. It embeds chat-only chrome
(ModelSelector, ChatToolControls, PermissionTierSelector, ContextBar, attachments) that
would break the editorial look. We reuse the underlying `sendMessage` flow instead — a
slim bespoke `HomeComposer` is the justified "new generic UI." Likewise `ConversationList`
(sidebar virtual-scroll list with hover action trays) is too heavy; the calm 3–5 entry
editorial `HomeResume` is a new, lighter component.

## Data flow & actions

All store reads are read-only. No fabricated data.

- **Submit (composer):** `await sendMessage(content)` (from `useChat`, injected via
  `ChatApiKey`) creates a conversation if needed and starts the turn, then
  `router.push({ name: uiStore.mode })` to drop the user into their active surface
  (workspace/assistant) with the turn running.
- **Intent chip:** sets the composer text and focuses it (no auto-send), except
  "Riprendi l'ultima" → select most-recent conversation + navigate.
- **Resume entry:** select that conversation (existing chat switch flow) +
  `router.push({ name: uiStore.mode })`.
- **Greeting/lede/colophon:** computed from `chatStore.conversations`,
  `memoryStore.stats`, `servicesStore` (+ `lmStudioConnected` / `activeModel.loaded`),
  `servicesStore.knowledge`.
- **Live work (optional):** if `agentRunStore.currentRun?.status === 'running'`, show a
  single quiet "Alice sta lavorando…" strip. Included only if it stays trivial; otherwise
  deferred. Not a persisted feed — purely the live turn.

## Personalization: preferred name

The user wants a name that (a) personalizes the greeting and (b) is the name the **model**
uses to address them. Mechanism decision: inject into the **system prompt**, not memory.
Semantic memory (`user_fact`) retrieval is query-dependent and unreliable; the name is
short and always relevant, so it belongs in the always-present system prompt.

**Backend** (`backend/`):
- `core/config.py` — add `user_preferred_name: str = ""` to `LLMConfig`.
- `services/llm_service.py` `_load_system_prompt()` — append to the existing environment
  block (which already injects username/home/desktop): e.g.
  `- **Come preferisci essere chiamato/a**: <name>` (only when non-empty). Ensure the
  system-prompt cache is invalidated when the value changes (reuse existing invalidation;
  the value flows through `self._config`).
- `services/preferences_service.py` — add `"user_preferred_name"` to
  `PERSISTABLE_LLM_KEYS` so it survives restarts.
- No new REST endpoint: the generic `PUT /config` already accepts `{ llm: { user_preferred_name } }`.

**Frontend** (`frontend/`):
- `stores/settings.ts` — add `userPreferredName: string` to the `llm` section of
  `AliceSettings`; map `llm.user_preferred_name` ↔ `userPreferredName` in `loadSettings`
  and include it in the `llm` payload of `saveSettings` (deep-watch auto-persists).
- `views/SettingsView.vue` — add a small **"Profilo"** section (nav item, icon `user`)
  with one text field "Come Alice deve chiamarti" bound to
  `settingsStore.settings.llm.userPreferredName`.
- `HomeGreeting` reads the same `settingsStore.settings.llm.userPreferredName` — single
  source of truth, no separate state.

## Routing & navigation

- `router/index.ts` — change default `/` redirect from `/workspace` to `/home`. The
  `/home` route already exists. Keep `/home` **out** of `MODE_ROUTES` so navigating home
  does not change `uiStore.mode` (orb/ambient stay as the user left them). Window title
  already wired via route meta `title: 'Home'`.
- `components/sidebar/AppSidebar.vue` — add a "Home" `<router-link to="/home">` (icon
  `home`) at the top of the nav list.

## Edge cases & states

- **First run (no conversations / empty memory):** no fake entries. The Resume block
  shows a warm `UiEmptyState` ("Iniziamo da qui."); the lede adapts (drops counts).
- **Name unset:** greeting renders without a name ("Buonasera.").
- **Degraded service:** colophon status dot uses `--warning`; one short reason if down.
- **Local model not loaded:** colophon shows "modello locale · non pronto" rather than a
  model name; composer remains usable (submit still creates the turn).
- **Reduced motion:** atmospheric animation disabled; static fallback.
- **Light theme:** all tokens already have light parallels; verify Fraunces + cream→taupe
  reads well in both.

## Out of scope (explicit)

- Persisted agent-activity history / literal "dispatch log" (decision: real signals only).
- Reworking AssistantView/WorkspaceView or the chat engine.
- Any new vector/memory write path.

## Verification

- `npm run typecheck` and `npm run lint` clean (frontend).
- Backend: `ruff check .`, `mypy .`, and `pytest tests/` for the config/llm changes;
  add/extend a test asserting the preferred name appears in the assembled system prompt
  when set and is absent when empty.
- Manual: launch app → lands on `/home`; greeting reflects time + name; submitting starts
  a turn and navigates into the active mode; Resume lists real conversations and resumes
  them; colophon reflects real service/model/memory state; Home reachable from sidebar;
  first-run empty state renders; light/dark both correct.

## Open questions

None blocking. The live-work strip (section "Data flow & actions") is the only optional;
default to including it only if trivial.
