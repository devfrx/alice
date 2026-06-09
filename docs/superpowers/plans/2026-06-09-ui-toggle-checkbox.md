# UiToggle + UiCheckbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 4 duplicated pill-switch styles and ad-hoc checkboxes with two reusable `ui/` components, and migrate the tool-RAG native `window.confirm` to the existing `useModal` system.

**Architecture:** Add `UiToggle.vue` (pill switch, bare or labelled-row mode, `v-model`) and `UiCheckbox.vue` (native-input-backed) to `components/ui/`, following the existing `UiButton.vue` conventions. Migrate every call site, deleting the now-dead per-file CSS. Wire `v-model`, preserving any existing toggle side-effects via an explicit `@update:modelValue` handler.

**Tech Stack:** Vue 3 (`<script setup lang="ts">`, Composition API), TypeScript, scoped CSS with design tokens, electron-vite.

> **Testing note — read first:** The renderer has **no component-test harness** (`vitest` is present but only for Pinia stores; `@vue/test-utils` and a DOM env are not installed). So these tasks are **not** TDD-with-unit-tests. The "test" for every task is: `npm run typecheck` (vue-tsc) + `npm run lint` pass, plus a described manual visual smoke. Run all `npm` commands from `frontend/`.

---

## File Structure

**Created:**
- `frontend/src/renderer/src/components/ui/UiToggle.vue` — pill on/off switch.
- `frontend/src/renderer/src/components/ui/UiCheckbox.vue` — checkbox.

**Modified (migrations):**
- `views/SettingsView.vue` — 3 toggles + remove `.sv__toggle*` CSS.
- `components/settings/EmailSettings.vue` — 4 toggles + remove CSS.
- `components/settings/VectorStoreManager.vue` — 1 toggle + CSS + `window.confirm`→`useModal`.
- `components/branding/BrandThemeToggle.vue` — theme toggle.
- `components/settings/PluginManagement.vue` — 1 toggle + remove `.settings-toggle*` CSS.
- `components/voice/VoiceSettings.vue` — 5 toggles (with `save()` side-effect) + remove CSS.
- `components/chat/ChatToolControls.vue` — 2 bare `sm` toggles + remove `.ctc__sw*` CSS.
- `components/services/TrellisConfigCard.vue` — 1 row toggle + remove `.trellis-card__toggle*` CSS.
- `components/settings/ModelManager.vue` — flash-attention → `UiCheckbox` + remove `.mm-dialog__toggle` CSS.

---

## Task 1: Create `UiToggle.vue`

**Files:**
- Create: `frontend/src/renderer/src/components/ui/UiToggle.vue`

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
/**
 * UiToggle — pill on/off switch. Consolidates the previously duplicated
 * sv__toggle / settings-toggle / ctc__sw / trellis-card__toggle styles.
 *
 * Render modes:
 *   - Bare (no label/hint/#default): renders just the <button role="switch">.
 *     Requires `ariaLabel`. Used inline (ChatToolControls, BrandThemeToggle).
 *   - Row (label/hint/#default present): text block left, switch right; the
 *     whole row is clickable. Used for settings rows.
 *
 * Supports `v-model`. Where toggling has a side effect, bind `:model-value`
 * and handle `@update:model-value` explicitly instead of a bare v-model.
 */
import { computed, useSlots } from 'vue'

export interface UiToggleProps {
    /** Current on/off state. */
    modelValue: boolean
    /** Sizing scale. md = 36×20 (default), sm = compact for dense lists. */
    size?: 'sm' | 'md'
    /** Greys out and blocks activation. */
    disabled?: boolean
    /** Optional label text (row mode). Overridden by the #default slot. */
    label?: string
    /** Optional secondary hint under the label (row mode only). */
    hint?: string
    /** Accessible label — required when used bare (no label/slot). */
    ariaLabel?: string
}

const props = withDefaults(defineProps<UiToggleProps>(), {
    size: 'md',
    disabled: false,
    label: undefined,
    hint: undefined,
    ariaLabel: undefined,
})

const emit = defineEmits<{
    'update:modelValue': [value: boolean]
}>()

const slots = useSlots()

/** True when there is text to render → use the row layout. */
const hasText = computed(() => Boolean(props.label || props.hint || slots.default))

function toggle(): void {
    if (props.disabled) return
    emit('update:modelValue', !props.modelValue)
}
</script>

<template>
    <div v-if="hasText" class="ui-toggle-row" :class="{ 'ui-toggle-row--disabled': disabled }" @click="toggle">
        <div class="ui-toggle-row__text">
            <span v-if="label || slots.default" class="ui-toggle-row__label">
                <slot>{{ label }}</slot>
            </span>
            <span v-if="hint" class="ui-toggle-row__hint">{{ hint }}</span>
        </div>
        <button class="ui-toggle" :class="[`ui-toggle--${size}`, { 'ui-toggle--on': modelValue }]" type="button"
            role="switch" :aria-checked="modelValue" :aria-label="ariaLabel || label" :disabled="disabled"
            @click.stop="toggle">
            <span class="ui-toggle__thumb" />
        </button>
    </div>
    <button v-else class="ui-toggle" :class="[`ui-toggle--${size}`, { 'ui-toggle--on': modelValue }]" type="button"
        role="switch" :aria-checked="modelValue" :aria-label="ariaLabel" :disabled="disabled" @click="toggle">
        <span class="ui-toggle__thumb" />
    </button>
</template>

<style scoped>
/* ── Row layout ───────────────────────── */
.ui-toggle-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-4);
    cursor: pointer;
}

.ui-toggle-row--disabled {
    cursor: not-allowed;
    opacity: var(--opacity-disabled);
}

.ui-toggle-row__text {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
}

.ui-toggle-row__label {
    font-size: var(--text-sm);
    font-weight: var(--weight-medium);
    color: var(--text-primary);
}

.ui-toggle-row__hint {
    font-size: var(--text-xs);
    color: var(--text-muted);
}

/* ── Switch ───────────────────────────── */
.ui-toggle {
    position: relative;
    border: none;
    border-radius: var(--radius-pill);
    background: var(--surface-3);
    cursor: pointer;
    padding: 0;
    flex-shrink: 0;
    outline: none;
    transition: background var(--duration-fast) ease;
}

.ui-toggle:disabled {
    cursor: not-allowed;
    opacity: var(--opacity-disabled);
}

.ui-toggle--on {
    background: var(--accent);
}

.ui-toggle__thumb {
    position: absolute;
    border-radius: 50%;
    background: var(--text-primary);
    transition:
        transform var(--duration-fast) ease,
        background var(--duration-fast) ease;
}

.ui-toggle--on .ui-toggle__thumb {
    background: var(--surface-0);
}

/* ── Sizes ────────────────────────────── */
.ui-toggle--md {
    width: 36px;
    height: 20px;
}

.ui-toggle--md .ui-toggle__thumb {
    top: 3px;
    left: 3px;
    width: 14px;
    height: 14px;
}

.ui-toggle--md.ui-toggle--on .ui-toggle__thumb {
    transform: translateX(16px);
}

.ui-toggle--sm {
    width: 30px;
    height: 17px;
}

.ui-toggle--sm .ui-toggle__thumb {
    top: 2.5px;
    left: 2.5px;
    width: 12px;
    height: 12px;
}

.ui-toggle--sm.ui-toggle--on .ui-toggle__thumb {
    transform: translateX(13px);
}
</style>
```

- [ ] **Step 2: Typecheck + lint**

Run (from `frontend/`): `npm run typecheck && npm run lint`
Expected: PASS, no errors referencing `UiToggle.vue`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/ui/UiToggle.vue
git commit -m "feat(ui): add UiToggle pill switch component"
```

---

## Task 2: Create `UiCheckbox.vue`

**Files:**
- Create: `frontend/src/renderer/src/components/ui/UiCheckbox.vue`

> `AppIcon` lives at `components/ui/AppIcon.vue` and takes `name` + `:size`. Uses lucide-style names already in the repo (`check`, `minus` are standard lucide icons).

- [ ] **Step 1: Write the component**

```vue
<script setup lang="ts">
/**
 * UiCheckbox — accessible checkbox built on a visually-hidden native input,
 * replacing ad-hoc <input type="checkbox"> usages. Supports v-model.
 */
import { onMounted, ref, watch } from 'vue'

import AppIcon from './AppIcon.vue'

export interface UiCheckboxProps {
    /** Checked state. */
    modelValue: boolean
    /** Sizing scale — md (default) or sm. */
    size?: 'sm' | 'md'
    /** Greys out and blocks activation. */
    disabled?: boolean
    /** Optional label text. Overridden by the #default slot. */
    label?: string
    /** Renders the mixed (dash) state; sets the native input's indeterminate flag. */
    indeterminate?: boolean
    /** Accessible label — required when no label/slot is provided. */
    ariaLabel?: string
}

const props = withDefaults(defineProps<UiCheckboxProps>(), {
    size: 'md',
    disabled: false,
    label: undefined,
    indeterminate: false,
    ariaLabel: undefined,
})

const emit = defineEmits<{
    'update:modelValue': [value: boolean]
}>()

const inputRef = ref<HTMLInputElement | null>(null)

/** Keep the native indeterminate flag in sync (it is DOM-only, not an attribute). */
function syncIndeterminate(): void {
    if (inputRef.value) inputRef.value.indeterminate = props.indeterminate
}

onMounted(syncIndeterminate)
watch(() => props.indeterminate, syncIndeterminate)

function onChange(e: Event): void {
    emit('update:modelValue', (e.target as HTMLInputElement).checked)
}
</script>

<template>
    <label class="ui-checkbox" :class="[`ui-checkbox--${size}`, { 'ui-checkbox--disabled': disabled }]">
        <input ref="inputRef" class="ui-checkbox__input" type="checkbox" :checked="modelValue" :disabled="disabled"
            :aria-label="ariaLabel || label" @change="onChange" />
        <span class="ui-checkbox__box" :class="{ 'ui-checkbox__box--on': modelValue || indeterminate }"
            aria-hidden="true">
            <AppIcon v-if="indeterminate" name="minus" :size="size === 'sm' ? 11 : 13" />
            <AppIcon v-else-if="modelValue" name="check" :size="size === 'sm' ? 11 : 13" />
        </span>
        <span v-if="label || $slots.default" class="ui-checkbox__label">
            <slot>{{ label }}</slot>
        </span>
    </label>
</template>

<style scoped>
.ui-checkbox {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
    cursor: pointer;
    user-select: none;
}

.ui-checkbox--disabled {
    cursor: not-allowed;
    opacity: var(--opacity-disabled);
}

/* Visually-hidden native input (keeps keyboard + a11y semantics). */
.ui-checkbox__input {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    white-space: nowrap;
    border: 0;
}

.ui-checkbox__box {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--surface-2);
    color: var(--surface-0);
    transition:
        background var(--duration-fast) ease,
        border-color var(--duration-fast) ease;
}

.ui-checkbox__box--on {
    background: var(--accent);
    border-color: var(--accent);
}

.ui-checkbox__input:focus-visible + .ui-checkbox__box {
    outline: 2px solid var(--accent-border);
    outline-offset: 1px;
}

.ui-checkbox__label {
    font-size: var(--text-sm);
    color: var(--text-primary);
}

/* ── Sizes ────────────────────────────── */
.ui-checkbox--md .ui-checkbox__box {
    width: 18px;
    height: 18px;
}

.ui-checkbox--sm .ui-checkbox__box {
    width: 15px;
    height: 15px;
}
</style>
```

- [ ] **Step 2: Typecheck + lint**

Run: `npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/ui/UiCheckbox.vue
git commit -m "feat(ui): add UiCheckbox component"
```

---

## Task 3: Migrate `SettingsView.vue` (3 toggles)

**Files:**
- Modify: `frontend/src/renderer/src/views/SettingsView.vue`

The three `.sv__toggle` buttons sit inside an existing `.sv__row` with `.sv__row-text` (label + hint). Keep the surrounding `.sv__row`/warn markup; replace only the `<button class="sv__toggle">…</button>` with a bare `UiToggle` (the row layout already exists here).

Current bindings:
- `settingsStore.systemPromptEnabled` (line ~39)
- `settingsStore.toolsEnabled` (line ~59)
- `settingsStore.toolConfirmations` (line ~145)

- [ ] **Step 1: Add the import**

In `<script setup>`, alongside the other component imports:

```ts
import UiToggle from '../components/ui/UiToggle.vue'
```

- [ ] **Step 2: Replace each toggle button**

For each of the three, replace:

```vue
<button class="sv__toggle" :class="{ 'sv__toggle--on': settingsStore.systemPromptEnabled }" role="switch"
  :aria-checked="settingsStore.systemPromptEnabled"
  @click="settingsStore.systemPromptEnabled = !settingsStore.systemPromptEnabled">
  <span class="sv__toggle-thumb" />
</button>
```

with (bare mode — the `.sv__row-text` already provides the label):

```vue
<UiToggle v-model="settingsStore.systemPromptEnabled" aria-label="System Prompt" />
```

Repeat for `toolsEnabled` (`aria-label="Strumenti (Tool Calling)"`) and `toolConfirmations` (`aria-label="Conferma esecuzione strumenti"`).

- [ ] **Step 3: Remove dead CSS**

Delete the `.sv__toggle`, `.sv__toggle--on`, `.sv__toggle-thumb`, `.sv__toggle--on .sv__toggle-thumb` rules (the `/* ── Toggle switch ── */` block, ~lines 488–521). Also remove `.sv__toggle` and `.sv__toggle-thumb` from the `prefers-reduced-motion` selector list (~lines 628–629) — leave the other selectors in that list intact.

- [ ] **Step 4: Typecheck + lint + smoke**

Run: `npm run typecheck && npm run lint`
Smoke: open Settings → toggle System Prompt / Tools / Confirmations; verify the warn banners still appear when turned off.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/views/SettingsView.vue
git commit -m "refactor(settings): use UiToggle in SettingsView"
```

---

## Task 4: Migrate `EmailSettings.vue` (4 toggles)

**Files:**
- Modify: `frontend/src/renderer/src/components/settings/EmailSettings.vue`

Four `.sv__toggle` buttons, each in a row whose text is already rendered separately. Bindings: `email.enabled`, `email.imapSsl`, `email.smtpSsl`, `email.imapIdleEnabled`.

- [ ] **Step 1: Add import**

```ts
import UiToggle from '../ui/UiToggle.vue'
```

- [ ] **Step 2: Replace each button**

Replace each `<button class="sv__toggle" …><span class="sv__toggle-thumb" /></button>` with a bare `UiToggle`, e.g.:

```vue
<UiToggle v-model="email.enabled" aria-label="Abilita email" />
```

- `email.imapSsl` → `aria-label="IMAP SSL/TLS"`
- `email.smtpSsl` → `aria-label="SMTP SSL/TLS"`
- `email.imapIdleEnabled` → `aria-label="IMAP IDLE"`

- [ ] **Step 3: Remove dead CSS**

If `EmailSettings.vue` declares its own `.sv__toggle*` rules, delete them. If it relied on `SettingsView`'s (non-scoped) styles, none exist locally — confirm by searching the file for `.sv__toggle`; delete any found.

- [ ] **Step 4: Typecheck + lint + smoke**

Run: `npm run typecheck && npm run lint`
Smoke: Settings → Email; toggle each of the four switches.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/components/settings/EmailSettings.vue
git commit -m "refactor(settings): use UiToggle in EmailSettings"
```

---

## Task 5: Migrate `VectorStoreManager.vue` (toggle + native confirm)

**Files:**
- Modify: `frontend/src/renderer/src/components/settings/VectorStoreManager.vue`

Two changes: (a) the `.sv__toggle` for `settingsStore.settings.llm.toolRagEnabled`; (b) replace `window.confirm` in `onRepair()` with `useModal().confirm` (danger).

- [ ] **Step 1: Add imports**

```ts
import UiToggle from '../ui/UiToggle.vue'
import { useModal } from '../../composables/useModal'
```

And in `<script setup>` body:

```ts
const { confirm } = useModal()
```

(Place near the other composable/store initializations at the top of the setup block.)

- [ ] **Step 2: Replace the toggle**

Replace (lines ~54–58):

```vue
<button class="sv__toggle" :class="{ 'sv__toggle--on': settingsStore.settings.llm.toolRagEnabled }"
    role="switch" :aria-checked="settingsStore.settings.llm.toolRagEnabled"
    @click="settingsStore.settings.llm.toolRagEnabled = !settingsStore.settings.llm.toolRagEnabled">
    <span class="sv__toggle-thumb" />
</button>
```

with:

```vue
<UiToggle v-model="settingsStore.settings.llm.toolRagEnabled" aria-label="Tool RAG" />
```

- [ ] **Step 3: Replace `window.confirm`**

Replace (lines ~143–147):

```ts
const ok = window.confirm(
    'Ripristinare il vector store? I dati embedded salvati (memorie/fatti) ' +
    'verranno cancellati e ricreati da zero. L’operazione non è reversibile.',
)
if (!ok) return
```

with:

```ts
const ok = await confirm({
    title: 'Ripristina vector store',
    message:
        'Ripristinare il vector store? I dati embedded salvati (memorie/fatti) ' +
        'verranno cancellati e ricreati da zero. L’operazione non è reversibile.',
    type: 'danger',
    confirmText: 'Ripristina',
})
if (!ok) return
```

(`onRepair` is already `async`, so `await` is valid.)

- [ ] **Step 4: Remove dead CSS**

Delete the `/* ── Reuse SettingsView toggle styles ── */` block: `.sv__toggle`, `.sv__toggle--on`, `.sv__toggle-thumb`, `.sv__toggle--on .sv__toggle-thumb` (~lines 432–463).

- [ ] **Step 5: Typecheck + lint + smoke**

Run: `npm run typecheck && npm run lint`
Smoke: Settings → Vector store; toggle Tool RAG; click Repair → a custom danger modal (not the native browser dialog) appears; Cancel aborts, Confirm runs the repair.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/renderer/src/components/settings/VectorStoreManager.vue
git commit -m "refactor(settings): UiToggle + useModal in VectorStoreManager"
```

---

## Task 6: Migrate `BrandThemeToggle.vue` (theme switch)

**Files:**
- Modify: `frontend/src/renderer/src/components/branding/BrandThemeToggle.vue`

This toggles `theme` between `'light'`/`'dark'`, not a boolean. Use a computed `get/set` so `v-model` maps cleanly, and render `UiToggle` bare.

- [ ] **Step 1: Rewrite the component**

```vue
<script setup lang="ts">
import { computed } from 'vue'

import UiToggle from '../ui/UiToggle.vue'
import { useSettingsStore } from '../../stores/settings'

const settingsStore = useSettingsStore()

/** v-model proxy: true = light theme. */
const isLight = computed({
    get: () => settingsStore.settings.ui.theme === 'light',
    set: (v: boolean) => {
        settingsStore.settings.ui.theme = v ? 'light' : 'dark'
    },
})
</script>

<template>
    <UiToggle v-model="isLight" class="brand-theme-toggle"
        :aria-label="isLight ? 'Tema chiaro attivo' : 'Tema scuro attivo'" />
</template>

<style scoped>
/* Hook for any positioning the parent relied on; visual switch lives in UiToggle. */
.brand-theme-toggle {
    flex-shrink: 0;
}
</style>
```

- [ ] **Step 2: Typecheck + lint + smoke**

Run: `npm run typecheck && npm run lint`
Smoke: click the theme toggle in the branding area; the app switches light/dark and the switch reflects state.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/branding/BrandThemeToggle.vue
git commit -m "refactor(branding): build BrandThemeToggle on UiToggle"
```

---

## Task 7: Migrate `PluginManagement.vue` (1 toggle)

**Files:**
- Modify: `frontend/src/renderer/src/components/settings/PluginManagement.vue`

The `.settings-toggle` button (lines ~36–41) toggles `plugin.enabled` via the store action `pluginsStore.togglePlugin(plugin.name, !plugin.enabled)`. Preserve that store call via an explicit `@update:model-value` handler — do NOT switch to a bare `v-model` that writes `plugin.enabled` directly.

- [ ] **Step 1: Add import**

In `<script setup>` (alongside `usePluginsStore`):

```ts
import UiToggle from '../ui/UiToggle.vue'
```

- [ ] **Step 2: Replace the button**

Replace:

```vue
<button class="settings-toggle" :class="{ 'settings-toggle--on': plugin.enabled }" role="switch"
    :aria-checked="plugin.enabled"
    :aria-label="`${plugin.enabled ? 'Disattiva' : 'Attiva'} plugin ${plugin.name}`"
    @click="pluginsStore.togglePlugin(plugin.name, !plugin.enabled)">
    <span class="settings-toggle__thumb" />
</button>
```

with:

```vue
<UiToggle :model-value="plugin.enabled"
    :aria-label="`${plugin.enabled ? 'Disattiva' : 'Attiva'} plugin ${plugin.name}`"
    @update:model-value="(v) => pluginsStore.togglePlugin(plugin.name, v)" />
```

- [ ] **Step 3: Remove dead CSS**

Delete the `/* Toggle switch — aligned with sv__toggle … */` block: `.settings-toggle`, `.settings-toggle--on`, `.settings-toggle__thumb`, and the on-state thumb rule (~lines 188+).

- [ ] **Step 4: Typecheck + lint + smoke**

Run: `npm run typecheck && npm run lint`
Smoke: Settings → Plugins; toggle a plugin on/off; confirm it persists/calls the backend as before.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/components/settings/PluginManagement.vue
git commit -m "refactor(settings): use UiToggle in PluginManagement"
```

---

## Task 8: Migrate `VoiceSettings.vue` (5 toggles, with `save()` side-effect)

**Files:**
- Modify: `frontend/src/renderer/src/components/voice/VoiceSettings.vue`

Five `.settings-toggle` buttons. Several call `save()` after flipping the value, and two have `:disabled`. Preserve both. Bindings/handlers:
- `sttEnabled` — `@click="sttEnabled = !sttEnabled; save()"`, `:disabled="!sttLibAvailable"`
- `ttsEnabled` — `@click="ttsEnabled = !ttsEnabled; save()"`, `:disabled="ttsEngines.length === 0"`
- `autoTtsResponse` — `@click="autoTtsResponse = !autoTtsResponse; save()"`
- `voiceStore.confirmTranscript` — `@click="voiceStore.confirmTranscript = !voiceStore.confirmTranscript"` (no save)
- `voiceStore.sttIncludeAttachments` — `@click="… = !…"` (no save)

- [ ] **Step 1: Add import**

```ts
import UiToggle from '../ui/UiToggle.vue'
```

- [ ] **Step 2: Replace each button**

For the three that call `save()`, use an explicit handler so the side-effect is preserved:

```vue
<UiToggle :model-value="sttEnabled" :disabled="!sttLibAvailable" aria-label="Abilita STT"
    @update:model-value="(v) => { sttEnabled = v; save() }" />
```

```vue
<UiToggle :model-value="ttsEnabled" :disabled="ttsEngines.length === 0" aria-label="Abilita TTS"
    @update:model-value="(v) => { ttsEnabled = v; save() }" />
```

```vue
<UiToggle :model-value="autoTtsResponse" aria-label="Rispondi automaticamente a voce"
    @update:model-value="(v) => { autoTtsResponse = v; save() }" />
```

For the two store-backed ones with no save, a bare `v-model` is fine:

```vue
<UiToggle v-model="voiceStore.confirmTranscript" aria-label="Conferma trascrizione" />
```

```vue
<UiToggle v-model="voiceStore.sttIncludeAttachments" aria-label="Includi allegati STT" />
```

- [ ] **Step 3: Remove dead CSS**

Delete the local `.settings-toggle`, `.settings-toggle--on`, `.settings-toggle__thumb` (+ on-thumb) rules.

- [ ] **Step 4: Typecheck + lint + smoke**

Run: `npm run typecheck && npm run lint`
Smoke: Settings → Voice; toggle each; confirm STT/TTS switches are disabled when unavailable and that `save()` still fires (values persist after reopening).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/components/voice/VoiceSettings.vue
git commit -m "refactor(voice): use UiToggle in VoiceSettings"
```

---

## Task 9: Migrate `ChatToolControls.vue` (2 bare `sm` toggles)

**Files:**
- Modify: `frontend/src/renderer/src/components/chat/ChatToolControls.vue`

Two `.ctc__sw` switches in dense list rows; both call store setters. Use bare `UiToggle size="sm"` with explicit handlers (preserve store calls).

Handlers:
- Plugin row: `@click="settingsStore.setPluginEnabled(group.plugin, !isPluginEnabled(group.plugin))"`
- Tool row: `@click="settingsStore.setToolEnabled(tool.name, !settingsStore.isToolEnabled(tool.name))"`

- [ ] **Step 1: Add import**

```ts
import UiToggle from '../ui/UiToggle.vue'
```

- [ ] **Step 2: Replace the plugin switch**

Replace the `<button class="ctc__sw" …><span class="ctc__sw-thumb" /></button>` (plugin row) with:

```vue
<UiToggle size="sm" :model-value="isPluginEnabled(group.plugin)" :aria-label="`Attiva ${group.plugin}`"
    @update:model-value="(v) => settingsStore.setPluginEnabled(group.plugin, v)" />
```

- [ ] **Step 3: Replace the tool switch**

```vue
<UiToggle size="sm" :model-value="settingsStore.isToolEnabled(tool.name)" :aria-label="`Attiva ${tool.label}`"
    @update:model-value="(v) => settingsStore.setToolEnabled(tool.name, v)" />
```

- [ ] **Step 4: Remove dead CSS**

Delete the `.ctc__sw`, `.ctc__sw--on`, `.ctc__sw-thumb`, and on-state thumb rules.

- [ ] **Step 5: Typecheck + lint + smoke**

Run: `npm run typecheck && npm run lint`
Smoke: open the chat tool-controls popover; toggle a plugin group and an individual tool; confirm enable/disable still works and the compact size looks right in the list.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/renderer/src/components/chat/ChatToolControls.vue
git commit -m "refactor(chat): use UiToggle in ChatToolControls"
```

---

## Task 10: Migrate `TrellisConfigCard.vue` (row toggle with label+hint)

**Files:**
- Modify: `frontend/src/renderer/src/components/services/TrellisConfigCard.vue`

This is a checkbox-backed pill with a title + description. Replace the whole `<label class="trellis-card__toggle">…</label>` (lines ~204–220) with a `UiToggle` in **row** mode (label + hint), bound to the existing `enabled` model. Preserve `:disabled="loading"`.

- [ ] **Step 1: Add import**

```ts
import UiToggle from '../ui/UiToggle.vue'
```

- [ ] **Step 2: Replace the label block**

Replace:

```vue
<label class="trellis-card__toggle">
  <input v-model="enabled" type="checkbox" class="trellis-card__checkbox" :disabled="loading" />
  <span class="trellis-card__toggle-track" aria-hidden="true">
    <span class="trellis-card__toggle-knob" />
  </span>
  <span class="trellis-card__toggle-label">
    <span class="trellis-card__toggle-title">Abilita servizio</span>
    <span class="trellis-card__toggle-desc">
      Quando attivo, AL\CE può avviare automaticamente il processo.
    </span>
  </span>
</label>
```

with:

```vue
<UiToggle v-model="enabled" :disabled="loading" label="Abilita servizio"
    hint="Quando attivo, AL\CE può avviare automaticamente il processo." />
```

- [ ] **Step 3: Remove dead CSS**

Delete all `.trellis-card__toggle`, `.trellis-card__checkbox`, `.trellis-card__toggle-track`, `.trellis-card__toggle-knob`, `.trellis-card__toggle-label`, `.trellis-card__toggle-title`, `.trellis-card__toggle-desc` rules.

- [ ] **Step 4: Typecheck + lint + smoke**

Run: `npm run typecheck && npm run lint`
Smoke: Services → Trellis card; toggle "Abilita servizio"; confirm it disables while `loading` and the label/hint render.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/components/services/TrellisConfigCard.vue
git commit -m "refactor(services): use UiToggle in TrellisConfigCard"
```

---

## Task 11: Migrate `ModelManager.vue` flash-attention → `UiCheckbox`

**Files:**
- Modify: `frontend/src/renderer/src/components/settings/ModelManager.vue`

The `<label class="mm-dialog__toggle">` wraps a native checkbox + "Flash Attention" text, bound to `loadFlashAttention`.

- [ ] **Step 1: Add import**

```ts
import UiCheckbox from '../ui/UiCheckbox.vue'
```

- [ ] **Step 2: Replace the label**

Replace (lines ~328–331):

```vue
<label class="mm-dialog__toggle">
    <input v-model="loadFlashAttention" type="checkbox" />
    <span>Flash Attention</span>
</label>
```

with:

```vue
<UiCheckbox v-model="loadFlashAttention" label="Flash Attention" />
```

- [ ] **Step 3: Remove dead CSS**

Delete the `.mm-dialog__toggle` rule(s).

- [ ] **Step 4: Typecheck + lint + smoke**

Run: `npm run typecheck && npm run lint`
Smoke: open the Model load dialog; toggle Flash Attention; confirm the checkbox check/uncheck and that load uses the value.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/components/settings/ModelManager.vue
git commit -m "refactor(settings): use UiCheckbox for Flash Attention"
```

---

## Task 12: Final verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Confirm no toggle/checkbox duplication remains**

Run: `grep -rn "sv__toggle\|settings-toggle\|ctc__sw\|trellis-card__toggle\|mm-dialog__toggle" frontend/src/renderer/src`
Expected: **no matches** (all removed). If any remain, migrate or delete them.

- [ ] **Step 2: Full FE gates**

Run (from `frontend/`): `npm run typecheck && npm run lint`
Expected: PASS.

- [ ] **Step 3: Out-of-scope items untouched**

Confirm still using their original controls (intentionally NOT migrated):
- `components/board/ArtifactBoardFilters.vue` — pinned chip checkbox.
- `components/voice/VoiceSettings.vue` — `activation-mode` radio group.
Run: `grep -n "artifact-filters__pinned\|vs__activation-radio" frontend/src/renderer/src/components/board/ArtifactBoardFilters.vue frontend/src/renderer/src/components/voice/VoiceSettings.vue`
Expected: still present.

- [ ] **Step 4: Final commit (if any sweep fixes were needed)**

```bash
git add -A frontend/src/renderer/src
git commit -m "chore(ui): finalize UiToggle/UiCheckbox migration"
```

---

## Self-Review notes

- **Spec coverage:** All §3 migration rows map to Tasks 3–11; §5 modal swap is Task 5; the bare/row/`v-model`-side-effect risks (§7) are handled explicitly in Tasks 7/8/9; out-of-scope §4 items are guarded in Task 12.
- **Bespoke modal unification (§5)** is intentionally NOT in this plan — tracked as a separate follow-up task.
- **Naming consistency:** event is `update:modelValue` (template attr `@update:model-value`); classes `ui-toggle*` / `ui-checkbox*`; size values `'sm' | 'md'` throughout.
- **No component unit tests** by design (no harness) — every task verifies via typecheck + lint + manual smoke.
