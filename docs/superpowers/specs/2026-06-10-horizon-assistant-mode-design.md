# Horizon — Assistant Mode Redesign

**Date:** 2026-06-10
**Status:** Approved design, pending implementation plan
**Scope:** `frontend/` only — the `'assistant'` route surface. No backend or WS-contract changes.

## 1. Summary

The assistant mode is rebuilt from scratch as a single morphing scene called **Horizon**
(working name; component prefix `Horizon*`). The current orb-centric view (`AssistantView.vue`,
the Veil canvas orb, ambient glow, FAB, side panel) is removed entirely and replaced by an
**editorial, typography-first stage** whose persistent visual axis is a thin horizontal line of
light — *the horizon line* — that **is** AL\CE's presence. Everything that happens (listening,
responding, agent work, artifact presentation) is a transformation of the same scene around
that axis.

Design intent, in the user's words: *"un po' alla Jarvis"* — an ambient companion, an agent
mission-control, and a presentation surface; innovative and professional; modular, with no
future debt; using AL\CE's existing palette.

## 2. Decisions taken (with the user, in order)

| Question | Decision |
|---|---|
| How radical is "from scratch"? | New concept — the orb itself is retired. Voice remains but is not the visual protagonist. |
| Role of assistant mode vs Workspace | Jarvis-like: ambient companion + agent mission-control + result presentation. (Not a quick-command palette.) |
| Surface architecture | **A single scene that morphs** per state — information materializes when needed and vanishes after. No fixed dashboard zones. |
| Quiet state content | Presence + ambient info (date, time, next event, service status) — "luxury watch face" restraint. |
| Aesthetic direction | **Editorial noir** (the original "C" mockup): folio `AL\CE` top-center, large serif word center, horizon line below it, single masthead/colophon info line at the bottom. |
| Scene structure for active states | **"Palco d'orizzonte"** — the line never leaves the stage: response in large serif above it; agent plan rendered *on* the line (notches + travelling spark); artifacts take the stage below it. |
| Input | Invisible until needed: first keystroke (or click / wake word) materializes a boxless serif composition line. |
| Palette | **No new colors.** The scene uses AL\CE's existing theme tokens and follows the active theme (noir in dark, ink-on-paper in light). This supersedes the earlier "always-noir" idea. |

## 3. The scene: states and behaviors

One state machine, one active state at a time, explicit priority:

```
presenting ▸ working ▸ responding ▸ listening/composing ▸ quiet
```

Transitions are fluid (~600ms, eased); the line's vertical position is a per-state parameter
and animates between states — this is the visible "morph".

### 3.1 QUIET
The chosen "C" composition:
- Folio `AL\CE` top-center (small caps, tracked out), plus a minimal service-status glyph.
- Contextual greeting in large serif at center (e.g. "Buongiorno." — time-of-day aware;
  uses the persona/user name from settings when available, plain otherwise).
- The horizon line below the greeting, breathing almost imperceptibly.
- Colophon at the bottom: `MARTEDÌ 10 GIUGNO · 06:42 · RIUNIONE ALLE 15:00` — date, clock,
  next calendar event (from the calendar store). Each segment degrades gracefully: calendar
  plugin off → date · time only.

### 3.2 LISTENING / COMPOSING
- Entered by: click on empty scene, wake word (existing voice store activation modes), or
  first keystroke.
- The greeting fades; the line **tightens** and becomes audio-reactive (oscillates with
  `voiceStore.audioLevel`) — this replaces the current transcript audio bar.
- Spoken transcript composes word-by-word in italic serif above the line.
- Typed input appears in the same position: serif, editorial cursor, **no box, no border**.
- STT/processing shimmer states reuse existing voice-store flags.

### 3.3 RESPONDING
- The response appears above the line in large serif, **paced by sentences** (committed
  blocks at reading rhythm — not a raw token stream). The user's question remains below the
  line in small caps.
- While TTS plays, the line pulses gently in sync (`isSpeaking`).
- **Long-response degradation:** beyond ~4–5 sentences the scene slides into a
  **magazine column**: the line rises near the top and narrows; the text flows as a single
  centered reading column (drop cap on the lede). Full history stays in the History drawer.

### 3.4 WORKING (the mission-control)
- With a plan (steps from the tasks store): the line **becomes the plan's timeline** —
  one notch per step with a small mono label, a travelling spark on the active step,
  `2 DI 5` counter below.
- Above the line: a single italic status sentence (current step / model status).
- Tool calls appear as ephemeral mono annotations below the line and fade out.
- No plan but streaming/tools running: the line shows a directional light flow
  (indeterminate work).

### 3.5 PRESENTING
- When an artifact arrives (3D model, chart, whiteboard): text recedes to the top at small
  size; the artifact **takes the stage below the line**, full width, with a museum caption
  (`Fig. I — vista prospettica · trascina per ruotare`).
- Multiple artifacts: mono navigation `‹ I / III ›`. This replaces the current right side
  panel and its three toggle buttons.

### 3.6 Cross-cutting
- Tool confirmations / `ask_user`: the scene dims to ~40% and the existing dialogs render
  above it (restyled chrome only) — work remains visible behind.
- Connection lost: colophon shows `· DISCONNESSA ·` in mono; the line dims to embers.
  No popup.
- Interrupt: `Esc`, or click on the line during response/TTS → existing `stopGeneration` /
  cancel-speak paths.
- `prefers-reduced-motion`: static line, no rAF loop, opacity-only changes; the sentence
  pacer flushes text immediately.

## 4. Component architecture

All new code under `frontend/src/renderer/src/components/horizon/` (plus the view and
composables). Small single-responsibility modules; **only the orchestrator touches stores**;
children communicate via props/events.

```
views/HorizonView.vue          route 'assistant' — orchestration only: stores → scene props
composables/useHorizonScene.ts pure derivation: (voice, chat, tasks, artifacts, connection)
                               → { state, ...per-state data }. Testable without DOM.
composables/useSentencePacer.ts streaming tokens → committed sentences at reading rhythm.

components/horizon/
  HorizonScene.vue             the stage: vertical zones, animates the line's position
  HorizonLine.vue              THE line — one 2D canvas, declarative API (props only:
                               mode, audioLevel, plan, progress). Modes: breathe / tense
                               (audio) / pulse (TTS) / timeline (notches+spark) / flow.
  HorizonMasthead.vue          folio + service-status glyph
  HorizonQuiet.vue             greeting + colophon (ambient info)
  HorizonComposer.vue          materializing input; unifies typed text + voice transcript
  HorizonResponse.vue          sentence-paced serif response + magazine-column fallback
  HorizonPlan.vue              plan → notch/label data for the line; status sentence;
                               ephemeral tool annotations
  HorizonStage.vue             artifact stage (3D/chart/whiteboard) + caption + navigation
  HorizonHistory.vue           conversation drawer, editorial chrome
```

**Interactions:** click empty scene = toggle listening; first keystroke = composer;
`Esc` = interrupt; two discreet mono affordances bottom-right (`STORIA` / `WORKSPACE`)
replace the FAB.

**Reused untouched:** chat WS pipeline (`ChatApiKey` / `useChat`), `chat`/`voice`/`tasks`
stores, `useVoice`, `ImmersiveCADCanvas`, `TldrawCanvas`, chart viewer internals,
`ToolConfirmationDialog`, `AskUserPrompt`, `MessageEditDialog`. The scene is a *consumer*
of existing stores — zero backend or WS-contract changes.

**No new runtime dependencies.** Animations = CSS transitions + a single rAF loop inside
`HorizonLine`.

## 5. Visual language

- **Typography:** Fraunces (variable, weights ~200–500 + italic) is the serif identity for
  greeting, responses, captions — **bundled locally** as woff2 with `@font-face`
  (local-first app, no CDN at runtime). Mono and sans remain the existing
  `--font-mono` / `--font-sans` tokens.
- **Palette:** existing theme tokens only. The horizon line and warm light = `--accent`
  (cream `#E8DCC8` in dark, taupe mocha `#8C6A4A` in light); text = `--text-*`; surfaces =
  `--surface-*`; functional voice states = `--listening` / `--speaking` / `--thinking`.
  The scene **follows the active theme**: noir at night, ink-on-paper broadsheet in light.
- **Tokens file:** `assets/styles/horizon.css` defines `--hz-*` as *aliases/derivations*
  of theme tokens (opacity ramps for the line, durations: breath, 600ms morph, fades; line
  vertical quotas per state). **No literal colors in components.**

## 6. Performance

- One rAF loop total (in `HorizonLine`), suspended when the window is hidden or the scene
  is settled-quiet (on-demand redraw after the breath settles).
- Canvas sized via `ResizeObserver`, devicePixelRatio-aware.
- Budget: zero idle work after settle.

## 7. Removal list (full deletion, not deprecation)

- `views/AssistantView.vue` (1653 lines)
- `components/assistant/AliceOrb.vue` + the whole `components/assistant/veil-orb/`
  (engine.ts, config.ts, types.ts)
- `components/assistant/AmbientBackground.vue`
- `components/assistant/AssistantFab.vue`
- `components/assistant/AssistantTranscript.vue`
- `components/assistant/AssistantResponse.vue`
- `components/assistant/ConversationDrawer.vue` (replaced by `HorizonHistory`)

Router: `'assistant'` route points to `HorizonView`. Definition-of-done includes a final
grep for every removed name with zero hits.

## 8. Testing

- `useHorizonScene.spec.ts` — state derivation for every input combination (voice flags,
  streaming, active plan, artifacts, disconnection) + priority ordering.
- `useSentencePacer.spec.ts` — sentence segmentation, end-of-stream flush, reduced-motion
  immediate flush.
- Mount smoke test for `HorizonView` (renders with empty stores, no crash).
- Gates: `npm run typecheck` and lint clean (no new errors over baseline).

## 9. Delivery phases (each leaves the app working)

1. **Foundations** — `horizon.css` tokens, bundled fonts, `HorizonLine` + `HorizonScene`
   with quiet/listening states; new view behind the existing route (old view still default
   until phase 5).
2. **Conversation** — composer, sentence pacer, response + magazine fallback.
3. **Mission-control** — plan on the line, tool annotations, working state.
4. **Stage** — artifacts, navigation, captions.
5. **Polish + demolition** — history drawer, dialog chrome, route flip, removal list
   executed, cleanup grep.

## 10. Out of scope

- Backend changes, WS protocol, stores' shape.
- Workspace surface (keeps its own input bar/task strip as shipped).
- Wake-word engine changes (UI reflects existing activation modes only).
- Light/dark theme system itself (the scene only consumes it).
