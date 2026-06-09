# UiToggle + UiCheckbox — Design Spec

**Date:** 2026-06-09
**Scope:** Frontend (`frontend/src/renderer/`)
**Goal:** Eliminate duplicated toggle-switch / checkbox markup by introducing two
reusable primitives in `components/ui/`, and replace the single remaining native
browser dialog in the tool-RAG settings with the existing custom modal system.

---

## 1. Motivation

The codebase has **4 independent implementations of the same pill toggle switch**
and **2+ ad-hoc native checkboxes**, each re-declaring identical CSS:

| Pattern | Files | Count |
|---|---|---|
| `.sv__toggle` / `.sv__toggle-thumb` | SettingsView, EmailSettings, VectorStoreManager, BrandThemeToggle | 9 instances |
| `.settings-toggle` / `.settings-toggle__thumb` | PluginManagement, VoiceSettings | 6 instances |
| `.ctc__sw` / `.ctc__sw-thumb` | ChatToolControls | 2 instances |
| `.trellis-card__toggle` (hidden `<input checkbox>` + track/knob) | TrellisConfigCard | 1 instance |
| native `<input type="checkbox">` + label | ModelManager (`mm-dialog__toggle`) | 1 instance |

These drift in size, color, and thumb offset. Consolidating them into `UiToggle`
and `UiCheckbox` removes the duplication and guarantees a single accessible,
token-driven look.

Separately, `VectorStoreManager.onRepair()` uses a native `window.confirm()` — the
**only** remaining native browser dialog in the renderer (every other confirm
already uses `useModal`). It must be migrated to the existing custom modal.

---

## 2. Components

Both follow the existing `components/ui/` conventions (see `UiButton.vue`):
exported props interface, `withDefaults(defineProps<…>())`, typed `defineEmits`,
design tokens only, scoped CSS, `ui-<name>` BEM classes. Imports are direct
(`import UiToggle from '…/ui/UiToggle.vue'`) — there is no barrel file.

### 2.1 `UiToggle.vue` (pill switch)

```ts
export interface UiToggleProps {
  modelValue: boolean
  /** Sizing scale. md = 36×20 (default), sm = compact for dense lists. */
  size?: 'sm' | 'md'
  disabled?: boolean
  /** Optional label text. If set (or #default slot used), renders the row layout. */
  label?: string
  /** Optional secondary hint under the label. Only shown in row mode. */
  hint?: string
  /** Accessible label — required when used bare (no label/slot). */
  ariaLabel?: string
}
```

- **Emits:** `update:modelValue: [boolean]` → supports `v-model`.
- **Two render modes:**
  - **Bare** (no `label`/`hint`/slot): renders just the `<button role="switch">`.
    For inline uses — ChatToolControls, BrandThemeToggle.
  - **Row** (label/hint/slot present): renders `text block (left) + switch (right)`,
    the whole row clickable, vertically aligned. For settings rows — SettingsView,
    EmailSettings, VoiceSettings, PluginManagement, VectorStoreManager,
    TrellisConfigCard.
- **Markup:** the interactive element is a `<button type="button" role="switch"
  :aria-checked="modelValue" :aria-disabled>`. In row mode the surrounding label
  text is associated via the button's `aria-label`/`aria-labelledby`. Clicking the
  text region also toggles.
- **Styling:** `--accent` track when on, `--surface-3` when off; `--text-primary`
  thumb; `--radius-pill`; `--duration-fast` transitions; `--opacity-disabled` when
  disabled. `md` = 36×20 track / 14px thumb / 16px travel. `sm` ≈ 30×17 / 12px
  thumb (for ChatToolControls list rows).

### 2.2 `UiCheckbox.vue`

```ts
export interface UiCheckboxProps {
  modelValue: boolean
  size?: 'sm' | 'md'
  disabled?: boolean
  /** Optional label text (or use #default slot). */
  label?: string
  indeterminate?: boolean
  /** Accessible label — required when no label/slot. */
  ariaLabel?: string
}
```

- **Emits:** `update:modelValue: [boolean]` → `v-model`.
- **Markup:** a `<label>` wrapping a visually-hidden native
  `<input type="checkbox">` (keeps native a11y/keyboard) + a custom `<span>` box
  rendering a check (or dash when `indeterminate`) via `AppIcon`. Label text from
  prop or `#default` slot sits to the right.
- **Styling:** box uses `--accent` fill + `--surface-0` check when checked,
  `--border` when unchecked; `--radius-sm`; focus ring on the box driven by the
  hidden input's `:focus-visible`.

---

## 3. Migration map

Each replacement deletes the now-dead local CSS for that pattern.

| File | Change |
|---|---|
| `views/SettingsView.vue` | 3× `.sv__toggle` button → `UiToggle` (row); remove `.sv__toggle*` CSS |
| `components/settings/EmailSettings.vue` | 4× `.sv__toggle` → `UiToggle` (row) |
| `components/settings/VectorStoreManager.vue` | 1× `.sv__toggle` → `UiToggle`; remove `.sv__toggle*` CSS; **`window.confirm` → `useModal().confirm({ type: 'danger', … })`** |
| `components/branding/BrandThemeToggle.vue` | `.sv__toggle` → `UiToggle` (bare, `ariaLabel`); component may reduce to a thin wrapper |
| `components/settings/PluginManagement.vue` | 1× `.settings-toggle` → `UiToggle` (bare or row); remove `.settings-toggle*` CSS |
| `components/voice/VoiceSettings.vue` | 5× `.settings-toggle` → `UiToggle` (row); remove CSS |
| `components/chat/ChatToolControls.vue` | 2× `.ctc__sw` → `UiToggle` (bare, `size="sm"`); remove `.ctc__sw*` CSS |
| `components/services/TrellisConfigCard.vue` | `.trellis-card__toggle` → `UiToggle` (row, label+hint); remove `.trellis-card__toggle*` / `__checkbox` CSS |
| `components/settings/ModelManager.vue` | `.mm-dialog__toggle` flash-attention → `UiCheckbox`; remove CSS |

---

## 4. Explicitly out of scope (with rationale)

1. **Pinned filter chip** (`ArtifactBoardFilters.vue`): a checkbox *semantically*
   but rendered as an icon chip with a pressed state — no text label. Converting to
   `UiCheckbox` would change its UX. **Left as-is** (distinct control, not a
   duplicate of the toggle/checkbox family). Confirmed with user.
2. **Activation-mode radio group** (`VoiceSettings.vue`): a different primitive
   (`<input type="radio">`). Noted as a future `UiRadio`. Confirmed with user.
3. **Disclosure / collapse toggles** (ThinkingSection, ReasoningThread,
   ToolConfirmationDialog `reasoning-toggle`): expand/collapse buttons, not on/off
   switches. Untouched.
4. **Bespoke modal overlays** — see §5.

---

## 5. Modal duplication — finding & decision

The requested "native modal in tool-RAG settings" is the `window.confirm` in
`VectorStoreManager` (§3). A complete custom modal system already exists
(`composables/useModal.ts` + `components/ModalContainer.vue`, with `confirm`,
`alert`, `show`, `openCustom`) — so we **reuse** it, not create a new one.

While auditing, 6 components were found rolling their **own** `Teleport`+overlay
instead of `useModal().openCustom()`: `TrellisSetupGuideModal`, `MessageEditDialog`,
`ToolConfirmationDialog`, `MemoryManager`, `KnowledgeGraphManager` (×3),
`ModelManager`. This is genuine duplication of the modal *shell*, but unifying 6
bespoke, individually-styled overlays is a large, higher-risk refactor with
concerns orthogonal to toggles/checkboxes.

**Decision:** keep this branch focused. Do the requested `window.confirm` → custom
modal swap now; surface the 6 bespoke overlays as a **separate follow-up task**
rather than bundling them into this change.

---

## 6. Verification

- `npm run typecheck` (vue-tsc) and `npm run lint` — the established FE gates.
- Visual smoke: Settings (system-prompt / tools / confirmations rows), Email
  settings, Vector store (toggle + repair confirm modal), Voice settings, Plugin
  management, Chat tool controls, Trellis card, Model manager flash-attention.
- **No component unit tests:** the FE test harness is `vitest` over Pinia stores
  only; `@vue/test-utils` / a DOM environment are not installed, so there is no
  precedent or tooling for mounting components. Verification stays at
  typecheck + lint + manual smoke, consistent with the rest of the renderer.

---

## 7. Risks

- **Visual regressions** from per-file CSS removal: mitigated by matching the
  dominant `md` look and smoke-testing each touched view.
- **`v-model` wiring**: several current toggles flip a store value directly in
  `@click`; converting to `v-model` must preserve any side effects (e.g.
  VoiceSettings calls `save()` after toggling, ChatToolControls calls store
  setters). These keep an explicit `@update:modelValue` handler rather than a bare
  `v-model` where a side effect exists.
- **BrandThemeToggle / theme semantics**: it toggles light/dark, not a boolean
  setting — wire `modelValue` to `isLight` and map back in the handler.
