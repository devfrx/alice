# Home Rework — Editorial Dossier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the launcher-style `HomeView.vue` with a personal, agentic "editorial dossier" home — time-of-day greeting (Fraunces, scoped), a hero composer that starts a real turn, a dated "Resume" of recent conversations, and a mono runtime colophon — plus an optional preferred-name setting injected into the LLM system prompt. Make `/home` the default landing.

**Architecture:** Frontend is the bulk: a rewritten `HomeView.vue` orchestrating small single-responsibility components under `components/home/`, reusing existing stores, the real `useChat().sendMessage` turn-start flow, and existing theme tokens. A thin backend change adds `llm.user_preferred_name`, injected into the system prompt's environment block and persisted as a user preference. No new agent-activity persistence — the home renders only data that exists today.

**Tech Stack:** Vue 3 `<script setup lang="ts">` + Pinia + vue-router (frontend), Vitest for pure-util tests, `@fontsource/fraunces` (local font, no CDN — preserves the 100%-local principle); FastAPI + pydantic-settings + pytest (backend).

**Design spec:** `docs/superpowers/specs/2026-06-09-home-rework-editorial-dossier-design.md`

---

## File Map

**Create**
- `frontend/src/renderer/src/utils/relativeTime.ts` — shared "time ago" formatter (it-IT)
- `frontend/src/renderer/src/utils/relativeTime.test.ts` — Vitest unit tests
- `frontend/src/renderer/src/components/home/HomeGreeting.vue` — kicker + Fraunces greeting + lede
- `frontend/src/renderer/src/components/home/HomeComposer.vue` — hero input (presentational; v-model + submit)
- `frontend/src/renderer/src/components/home/HomeIntents.vue` — intent chips
- `frontend/src/renderer/src/components/home/HomeResume.vue` — recent-conversations dossier list
- `frontend/src/renderer/src/components/home/HomeResumeEntry.vue` — one dossier entry
- `frontend/src/renderer/src/components/home/HomeColophon.vue` — mono runtime status line
- `backend/tests/test_llm_preferred_name.py` — system-prompt injection test

**Modify**
- `backend/core/config.py` — add `user_preferred_name` to `LLMConfig` (after line 131)
- `backend/services/llm_service.py` — inject name into env block (`_load_system_prompt`, ~line 472)
- `backend/services/preferences_service.py` — add key to `PERSISTABLE_LLM_KEYS` (line 31-41)
- `backend/api/routes/config.py` — handle `user_preferred_name` in PUT `/config` (after line 475)
- `frontend/src/renderer/src/stores/settings.ts` — add `userPreferredName` to `llm` shape + load/save
- `frontend/src/renderer/src/views/SettingsView.vue` — add the preferred-name field
- `frontend/src/renderer/src/assets/icons.ts` — add `home` icon
- `frontend/src/renderer/src/router/index.ts` — default `/` → `/home` (line 57)
- `frontend/src/renderer/src/components/sidebar/AppSidebar.vue` — add Home nav link
- `frontend/src/renderer/src/components/sidebar/ConversationList.vue` — reuse shared formatter
- `frontend/src/renderer/src/views/HomeView.vue` — full rewrite
- `frontend/package.json` — add `@fontsource/fraunces` dependency

---

## Task 1: Backend — inject preferred name into the system prompt (TDD)

**Files:**
- Modify: `backend/core/config.py:131`
- Modify: `backend/services/llm_service.py:467-474`
- Test: `backend/tests/test_llm_preferred_name.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_preferred_name.py`:

```python
"""The user's preferred name is injected into the system prompt env block."""

from __future__ import annotations

from pathlib import Path

from backend.core.config import LLMConfig
from backend.services.llm_service import LLMService


def _service(tmp_path: Path, name: str) -> LLMService:
    prompt_file = tmp_path / "system_prompt.md"
    prompt_file.write_text("Sei AL\\CE.", encoding="utf-8")
    config = LLMConfig(
        system_prompt_enabled=True,
        system_prompt_file=str(prompt_file),
        user_preferred_name=name,
    )
    return LLMService(config)


def test_preferred_name_present_in_system_prompt(tmp_path: Path) -> None:
    service = _service(tmp_path, "Marco")
    prompt = service.get_system_prompt()
    assert "Come preferisci essere chiamato" in prompt
    assert "Marco" in prompt


def test_no_name_omits_the_line(tmp_path: Path) -> None:
    service = _service(tmp_path, "")
    prompt = service.get_system_prompt()
    assert "Come preferisci essere chiamato" not in prompt
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `backend/`): `pytest tests/test_llm_preferred_name.py -v`
Expected: FAIL — `LLMConfig` has no field `user_preferred_name` (pydantic raises on the unexpected kwarg), or the assertion fails.

- [ ] **Step 3: Add the config field**

In `backend/core/config.py`, inside `class LLMConfig`, immediately after the `system_prompt_enabled` block (line 130-131), add:

```python
    user_preferred_name: str = ""
    """How the user wants the assistant to address them. Injected into the
    system prompt's environment block so the model uses it. Empty = unset."""
```

- [ ] **Step 4: Inject it into the system prompt**

In `backend/services/llm_service.py`, in `_load_system_prompt`, replace the block that assigns `self._system_prompt` (currently lines 467-474):

```python
        env_block = (
            f"\n\n## Ambiente utente\n\n"
            f"- **Username**: {username}\n"
            f"- **Home**: {home}\n"
            f"- **Desktop**: {desktop}\n"
        )

        self._system_prompt = base + env_block
```

with:

```python
        env_block = (
            f"\n\n## Ambiente utente\n\n"
            f"- **Username**: {username}\n"
            f"- **Home**: {home}\n"
            f"- **Desktop**: {desktop}\n"
        )
        if self._config.user_preferred_name:
            env_block += (
                f"- **Come preferisci essere chiamato/a**: "
                f"{self._config.user_preferred_name}\n"
            )

        self._system_prompt = base + env_block
```

- [ ] **Step 5: Run the test to verify it passes**

Run (from `backend/`): `pytest tests/test_llm_preferred_name.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Type-check and lint the changed files**

Run (from `backend/`): `ruff check services/llm_service.py core/config.py tests/test_llm_preferred_name.py && mypy services/llm_service.py core/config.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/core/config.py backend/services/llm_service.py backend/tests/test_llm_preferred_name.py
git commit -m "feat(llm): inject optional user preferred name into system prompt"
```

---

## Task 2: Backend — persist the preferred name & accept it over PUT /config

**Files:**
- Modify: `backend/services/preferences_service.py:31-41`
- Modify: `backend/api/routes/config.py:475` (end of the `llm` updates block)

- [ ] **Step 1: Make the key persistable**

In `backend/services/preferences_service.py`, add `"user_preferred_name"` to `PERSISTABLE_LLM_KEYS`:

```python
PERSISTABLE_LLM_KEYS: frozenset[str] = frozenset({
    "system_prompt_enabled",
    "tools_enabled",
    "max_tool_iterations",
    "context_compression_enabled",
    "context_compression_threshold",
    "context_compression_reserve",
    "tool_rag_enabled",
    "tool_rag_top_k",
    "disabled_tools",
    "user_preferred_name",
})
```

- [ ] **Step 2: Handle the field in PUT /config**

In `backend/api/routes/config.py`, inside the `if "llm" in body:` block, immediately after the `tool_rag_top_k` handler (which ends at line 475 with `object.__setattr__(cfg.llm, "tool_rag_top_k", trk)`), add:

```python
        if "user_preferred_name" in llm_updates:
            raw_name = llm_updates["user_preferred_name"]
            name = "" if raw_name is None else str(raw_name).strip()
            if len(name) > 80:
                raise HTTPException(
                    400, "user_preferred_name must be at most 80 characters",
                )
            object.__setattr__(cfg.llm, "user_preferred_name", name)
            # Drop the cached prompt so the next turn rebuilds it with the name.
            if ctx.llm_service is not None:
                ctx.llm_service.invalidate_system_prompt_cache()
```

(Persistence is automatic: `persist_from_update(body)` at line 690 stores `llm.user_preferred_name` now that the key is in `PERSISTABLE_LLM_KEYS`.)

- [ ] **Step 3: Verify lint/type-check**

Run (from `backend/`): `ruff check api/routes/config.py services/preferences_service.py && mypy api/routes/config.py services/preferences_service.py`
Expected: no errors.

- [ ] **Step 4: Smoke-test the round-trip (optional but recommended)**

Run (from `backend/`): `pytest tests/test_app.py -q`
Expected: PASS (no regression in app/config wiring).

- [ ] **Step 5: Commit**

```bash
git add backend/services/preferences_service.py backend/api/routes/config.py
git commit -m "feat(config): persist and accept user_preferred_name over PUT /config"
```

---

## Task 3: Frontend — add `userPreferredName` to the settings store

**Files:**
- Modify: `frontend/src/renderer/src/stores/settings.ts` (interface 9-19, defaults 54-64, load 233-249, save 300-309)

- [ ] **Step 1: Extend the `llm` shape in the interface**

In `AliceSettings.llm` (interface, after `toolRagTopK: number` on line 18), add:

```ts
    toolRagTopK: number
    userPreferredName: string
```

- [ ] **Step 2: Add the default value**

In the `settings` ref default `llm` object (after `toolRagTopK: 15` on line 63), add:

```ts
      toolRagTopK: 15,
      userPreferredName: ''
```

- [ ] **Step 3: Map it when loading from the backend**

In `loadSettings`, inside `if (config.llm) {`, after the `toolRagTopK` mapping (line 247-248), add:

```ts
        settings.value.llm.userPreferredName =
          (llm.user_preferred_name as string) ?? settings.value.llm.userPreferredName
```

- [ ] **Step 4: Send it when saving to the backend**

In `saveSettings`, inside the `llm:` payload object (after `tool_rag_top_k: settings.value.llm.toolRagTopK` on line 308), add:

```ts
          tool_rag_top_k: settings.value.llm.toolRagTopK,
          user_preferred_name: settings.value.llm.userPreferredName
```

- [ ] **Step 5: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS (no type errors).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/renderer/src/stores/settings.ts
git commit -m "feat(settings): add userPreferredName to the settings store"
```

---

## Task 4: Frontend — preferred-name field in Settings

**Files:**
- Modify: `frontend/src/renderer/src/views/SettingsView.vue` (LLM section `sv__fields`, line 65-87)

- [ ] **Step 1: Add the field as the first entry of the LLM `sv__fields` group**

In `SettingsView.vue`, inside the LLM section's `<div class="sv__fields">` (line 65), add this as the FIRST `<label>` (before "Temperatura"):

```vue
          <label class="sv__field">
            <span class="sv__field-label">Come Alice deve chiamarti</span>
            <div class="sv__input-wrap">
              <input v-model="settingsStore.settings.llm.userPreferredName" type="text" class="sv__input"
                maxlength="80" placeholder="es. Marco" />
            </div>
          </label>
```

- [ ] **Step 2: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/views/SettingsView.vue
git commit -m "feat(settings-ui): add preferred-name field to the LLM settings section"
```

---

## Task 5: Frontend — shared relative-time formatter (TDD) + reuse in ConversationList

**Files:**
- Create: `frontend/src/renderer/src/utils/relativeTime.ts`
- Test: `frontend/src/renderer/src/utils/relativeTime.test.ts`
- Modify: `frontend/src/renderer/src/components/sidebar/ConversationList.vue:195-205`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/renderer/src/utils/relativeTime.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { formatRelativeTime } from './relativeTime'

const NOW = new Date('2026-06-09T12:00:00Z').getTime()
const isoAgo = (ms: number): string => new Date(NOW - ms).toISOString()

describe('formatRelativeTime', () => {
  it('returns "adesso" under a minute', () => {
    expect(formatRelativeTime(isoAgo(30_000), NOW)).toBe('adesso')
  })
  it('returns minutes', () => {
    expect(formatRelativeTime(isoAgo(5 * 60_000), NOW)).toBe('5 min fa')
  })
  it('returns hours', () => {
    expect(formatRelativeTime(isoAgo(3 * 3_600_000), NOW)).toBe('3h fa')
  })
  it('returns "ieri" at one day', () => {
    expect(formatRelativeTime(isoAgo(25 * 3_600_000), NOW)).toBe('ieri')
  })
  it('returns days under a month', () => {
    expect(formatRelativeTime(isoAgo(5 * 86_400_000), NOW)).toBe('5g fa')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`): `npm run test -- relativeTime`
Expected: FAIL — `Cannot find module './relativeTime'`.

- [ ] **Step 3: Implement the util**

Create `frontend/src/renderer/src/utils/relativeTime.ts`:

```ts
/**
 * Human-readable "time ago" label (it-IT) from an ISO timestamp.
 *
 * @param iso ISO 8601 timestamp string.
 * @param now Reference time in ms (defaults to `Date.now()`; injectable for tests).
 */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const diff = now - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'adesso'
  if (mins < 60) return `${mins} min fa`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h fa`
  const days = Math.floor(hours / 24)
  if (days === 1) return 'ieri'
  if (days < 30) return `${days}g fa`
  return new Date(iso).toLocaleDateString('it-IT')
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `frontend/`): `npm run test -- relativeTime`
Expected: PASS (5 tests).

- [ ] **Step 5: Reuse it in ConversationList (DRY)**

In `frontend/src/renderer/src/components/sidebar/ConversationList.vue`, add the import alongside the other imports in `<script setup>` (top of the script block):

```ts
import { formatRelativeTime } from '../../utils/relativeTime'
```

Then DELETE the local `timeAgo` function (lines 192-206, the JSDoc + the `function timeAgo(iso: string): string { ... }`) and replace it with a thin alias so existing template usages keep working:

```ts
/** Human-readable "time ago" — delegates to the shared util. */
const timeAgo = (iso: string): string => formatRelativeTime(iso)
```

- [ ] **Step 6: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/renderer/src/utils/relativeTime.ts frontend/src/renderer/src/utils/relativeTime.test.ts frontend/src/renderer/src/components/sidebar/ConversationList.vue
git commit -m "feat(utils): add shared relativeTime formatter; reuse in ConversationList"
```

---

## Task 6: Frontend — `home` icon, default route, sidebar Home link

**Files:**
- Modify: `frontend/src/renderer/src/assets/icons.ts`
- Modify: `frontend/src/renderer/src/router/index.ts:57`
- Modify: `frontend/src/renderer/src/components/sidebar/AppSidebar.vue:203-210`

- [ ] **Step 1: Add a `home` icon to the registry**

In `frontend/src/renderer/src/assets/icons.ts`, add a new entry to the icon map (place it near the other nav icons, alphabetical is fine):

```ts
  'home': { icon: 'solar:home-smile-bold' },
```

- [ ] **Step 2: Make `/home` the default landing**

In `frontend/src/renderer/src/router/index.ts`, change the root redirect (line 55-58):

```ts
    {
      path: '/',
      redirect: '/home'
    },
```

- [ ] **Step 3: Add the Home link to the sidebar nav**

In `frontend/src/renderer/src/components/sidebar/AppSidebar.vue`, inside `<nav class="sidebar__nav" ...>` (line 203), add this as the FIRST link (before the Lavagna link on line 204):

```vue
          <router-link to="/home" class="sidebar__link" active-class="sidebar__link--active" title="Home"
            @click="toggle">
            <span class="sidebar__link-icon" aria-hidden="true">
              <AppIcon name="home" :size="15" />
            </span>
            <span class="sidebar__link-label">Home</span>
          </router-link>
```

- [ ] **Step 4: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS (the `home` icon name now resolves in `AppIconName`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/renderer/src/assets/icons.ts frontend/src/renderer/src/router/index.ts frontend/src/renderer/src/components/sidebar/AppSidebar.vue
git commit -m "feat(nav): add Home icon + sidebar link; default landing to /home"
```

---

## Task 7: Frontend — bundle Fraunces locally (no CDN)

**Files:**
- Modify: `frontend/package.json` (dependency)

- [ ] **Step 1: Add the font package**

Run (from `frontend/`): `npm install @fontsource/fraunces`
Expected: `@fontsource/fraunces` added to `dependencies` (OFL-licensed; bundled by Vite, served locally — no runtime CDN call, preserving AL\CE's 100%-local principle).

- [ ] **Step 2: Verify the weight asset exists**

Run (from `frontend/`): `node -e "require.resolve('@fontsource/fraunces/600.css'); console.log('ok')"`
Expected: prints `ok` (the import path used by `HomeGreeting.vue` in Task 8 resolves).

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "build(frontend): add @fontsource/fraunces (local font for home greeting)"
```

---

## Task 8: Frontend — HomeGreeting.vue

**Files:**
- Create: `frontend/src/renderer/src/components/home/HomeGreeting.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
/**
 * Editorial greeting block: mono kicker (date · runtime) + Fraunces greeting
 * (the ONLY serif element in the app) + a lede built from real counts.
 */
import { computed } from 'vue'
import { useSettingsStore } from '../../stores/settings'
// Local font — bundled by Vite, no CDN. Family name: 'Fraunces'.
import '@fontsource/fraunces/600.css'

const props = defineProps<{ conversationCount: number; memoryCount: number }>()
const settingsStore = useSettingsStore()

// Captured once at mount — the home is re-created on navigation, so a live
// clock is unnecessary churn.
const now = new Date()

const greetingWord = computed<string>(() => {
  const h = now.getHours()
  if (h < 12) return 'Buongiorno'
  if (h < 18) return 'Buon pomeriggio'
  return 'Buonasera'
})

const name = computed<string>(() => settingsStore.settings.llm.userPreferredName?.trim() ?? '')

const dateLabel = computed<string>(() =>
  new Intl.DateTimeFormat('it-IT', { weekday: 'long', day: 'numeric', month: 'long' }).format(now),
)

const lede = computed<string>(() => {
  const c = props.conversationCount
  const m = props.memoryCount
  if (c === 0 && m === 0) return 'Iniziamo da qui. Dimmi su cosa lavoriamo.'
  const parts: string[] = []
  if (c > 0) parts.push(`${c} ${c === 1 ? 'conversazione aperta' : 'conversazioni aperte'}`)
  if (m > 0) parts.push(`${m} ${m === 1 ? 'ricordo' : 'ricordi'} in memoria`)
  return `Hai ${parts.join(' e ')}. Da dove ripartiamo?`
})
</script>

<template>
  <header class="hg">
    <p class="hg__kicker">
      <span class="hg__dot" aria-hidden="true" />
      <span>{{ dateLabel }} · runtime locale</span>
    </p>
    <h1 class="hg__greet">
      {{ greetingWord }}<template v-if="name">, <em>{{ name }}</em></template>.
    </h1>
    <p class="hg__lede">{{ lede }}</p>
  </header>
</template>

<style scoped>
.hg__kicker {
  display: flex;
  align-items: center;
  gap: var(--space-2-5);
  margin: 0 0 var(--space-5);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  letter-spacing: var(--tracking-wide);
  text-transform: uppercase;
}

.hg__dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: var(--success);
  box-shadow: 0 0 8px var(--success-glow);
}

.hg__greet {
  margin: 0 0 var(--space-3);
  /* Fraunces — scoped to this one element. Everything else stays sans. */
  font-family: 'Fraunces', Georgia, serif;
  font-weight: 600;
  font-size: clamp(2.4rem, 4.4vw, 3.4rem);
  line-height: 1.04;
  letter-spacing: -0.015em;
  color: var(--text-primary);
}

.hg__greet em {
  font-style: italic;
  color: var(--accent);
}

.hg__lede {
  max-width: 46ch;
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--text-lg);
  line-height: var(--leading-snug);
}
</style>
```

- [ ] **Step 2: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/home/HomeGreeting.vue
git commit -m "feat(home): add HomeGreeting (Fraunces greeting + real-count lede)"
```

---

## Task 9: Frontend — HomeComposer.vue

**Files:**
- Create: `frontend/src/renderer/src/components/home/HomeComposer.vue`

- [ ] **Step 1: Create the component (presentational; parent owns the send flow)**

```vue
<script setup lang="ts">
/**
 * Hero composer for the home. Purely presentational: it owns no chat logic,
 * just two-way text binding + a `submit` event. The parent (HomeView) calls
 * the real `useChat().sendMessage` flow and navigates. Enter submits;
 * Shift+Enter inserts a newline.
 */
import { ref } from 'vue'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{ modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [string]; submit: [] }>()

const el = ref<HTMLTextAreaElement | null>(null)

function onInput(e: Event): void {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}

function submit(): void {
  if (props.modelValue.trim()) emit('submit')
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    submit()
  }
}

defineExpose({ focus: (): void => el.value?.focus() })
</script>

<template>
  <div class="hc">
    <textarea ref="el" class="hc__input" rows="1" :value="modelValue"
      placeholder="Chiedi, pianifica, o lascia che me ne occupi io…" aria-label="Messaggio per Alice"
      @input="onInput" @keydown="onKeydown" />
    <button class="hc__send" type="button" aria-label="Invia" :disabled="!modelValue.trim()" @click="submit">
      <AppIcon name="send" :size="16" />
    </button>
  </div>
</template>

<style scoped>
.hc {
  display: flex;
  align-items: flex-end;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-3) var(--space-3) var(--space-5);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  transition: border-color var(--transition-fast);
}

.hc:focus-within {
  border-color: var(--accent-border);
}

.hc__input {
  flex: 1;
  min-height: 28px;
  max-height: 160px;
  resize: none;
  border: none;
  outline: none;
  background: transparent;
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-lg);
  line-height: var(--leading-snug);
}

.hc__input::placeholder {
  color: var(--text-muted);
}

.hc__send {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 38px;
  height: 38px;
  border: none;
  border-radius: var(--radius-md);
  background: var(--accent);
  color: var(--text-on-accent);
  cursor: pointer;
  transition: background var(--transition-fast), opacity var(--transition-fast);
}

.hc__send:hover:not(:disabled) {
  background: var(--accent-hover);
}

.hc__send:disabled {
  opacity: var(--opacity-disabled);
  cursor: default;
}
</style>
```

- [ ] **Step 2: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/home/HomeComposer.vue
git commit -m "feat(home): add HomeComposer hero input (presentational)"
```

---

## Task 10: Frontend — HomeIntents.vue

**Files:**
- Create: `frontend/src/renderer/src/components/home/HomeIntents.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
/**
 * Intent chips. Most chips prefill the composer; "Riprendi l'ultima" emits a
 * dedicated event the parent handles by reopening the most recent thread.
 */
import AppIcon from '../ui/AppIcon.vue'

const emit = defineEmits<{ prefill: [string]; 'resume-last': [] }>()

interface Intent {
  label: string
  prefill?: string
  resumeLast?: boolean
  lead?: boolean
}

const intents: Intent[] = [
  { label: 'Pianifica un lavoro', prefill: 'Aiutami a pianificare: ', lead: true },
  { label: 'Cerca nei file', prefill: 'Cerca nei miei file: ' },
  { label: 'Genera un grafico', prefill: 'Genera un grafico che mostri ' },
  { label: "Riprendi l'ultima", resumeLast: true },
]

function activate(intent: Intent): void {
  if (intent.resumeLast) emit('resume-last')
  else if (intent.prefill) emit('prefill', intent.prefill)
}
</script>

<template>
  <div class="hi">
    <button v-for="intent in intents" :key="intent.label" class="hi__chip" type="button" @click="activate(intent)">
      <AppIcon v-if="intent.lead" name="plus" :size="13" />
      <span>{{ intent.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.hi {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

.hi__chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-2) var(--space-3-5, 14px);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: border-color var(--transition-fast), color var(--transition-fast);
}

.hi__chip:hover {
  border-color: var(--accent-border);
  color: var(--text-primary);
}

.hi__chip :deep(svg) {
  color: var(--accent);
}
</style>
```

- [ ] **Step 2: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/home/HomeIntents.vue
git commit -m "feat(home): add HomeIntents chips"
```

---

## Task 11: Frontend — HomeResume.vue + HomeResumeEntry.vue

**Files:**
- Create: `frontend/src/renderer/src/components/home/HomeResumeEntry.vue`
- Create: `frontend/src/renderer/src/components/home/HomeResume.vue`

- [ ] **Step 1: Create HomeResumeEntry.vue**

```vue
<script setup lang="ts">
/** One dossier entry: when (mono, accent) · title · meta · arrow. */
import type { ConversationSummary } from '../../types/chat'
import { formatRelativeTime } from '../../utils/relativeTime'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{ conversation: ConversationSummary }>()
const emit = defineEmits<{ open: [string] }>()

function metaLabel(c: ConversationSummary): string {
  const n = c.message_count
  return `${n} ${n === 1 ? 'messaggio' : 'messaggi'}`
}
</script>

<template>
  <button class="hre" type="button" @click="emit('open', props.conversation.id)">
    <span class="hre__when">{{ formatRelativeTime(props.conversation.updated_at) }}</span>
    <span class="hre__body">
      <span class="hre__title">{{ props.conversation.title || 'Conversazione senza titolo' }}</span>
      <span class="hre__meta">{{ metaLabel(props.conversation) }}</span>
    </span>
    <AppIcon class="hre__go" name="chevron-right" :size="15" />
  </button>
</template>

<style scoped>
.hre {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr) auto;
  align-items: baseline;
  gap: var(--space-4);
  width: 100%;
  padding: var(--space-4) var(--space-2);
  border: none;
  border-bottom: 1px solid var(--border);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background var(--transition-fast);
}

.hre:hover {
  background: var(--accent-faint);
}

.hre__when {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--accent);
  letter-spacing: var(--tracking-normal);
}

.hre__body {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}

.hre__title {
  color: var(--text-primary);
  font-size: var(--text-md);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.hre__meta {
  color: var(--text-muted);
  font-size: var(--text-xs);
}

.hre__go {
  align-self: center;
  color: var(--text-muted);
  transition: color var(--transition-fast);
}

.hre:hover .hre__go {
  color: var(--accent);
}
</style>
```

- [ ] **Step 2: Create HomeResume.vue**

```vue
<script setup lang="ts">
/**
 * "Riprendi" — the most recent non-empty conversations as dated dossier
 * entries. Real data only: empty drafts are filtered out, and a warm empty
 * state shows on first run (no fabricated entries).
 */
import { computed } from 'vue'
import type { ConversationSummary } from '../../types/chat'
import UiEmptyState from '../ui/UiEmptyState.vue'
import HomeResumeEntry from './HomeResumeEntry.vue'

const props = defineProps<{ conversations: ConversationSummary[] }>()
const emit = defineEmits<{ open: [string] }>()

const MAX = 4

const recent = computed<ConversationSummary[]>(() =>
  [...props.conversations]
    .filter((c) => c.message_count > 0)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, MAX),
)
</script>

<template>
  <section class="hr" aria-label="Riprendi">
    <p class="hr__label">
      <span>Riprendi</span>
      <span class="hr__rule" aria-hidden="true" />
      <span v-if="recent.length">{{ recent.length }} thread</span>
    </p>

    <div v-if="recent.length" class="hr__list">
      <HomeResumeEntry v-for="c in recent" :key="c.id" :conversation="c" @open="(id) => emit('open', id)" />
    </div>

    <UiEmptyState v-else compact icon="message" title="Iniziamo da qui."
      subtitle="Le conversazioni che apri compariranno qui per riprenderle al volo." />
  </section>
</template>

<style scoped>
.hr {
  margin-top: var(--space-12);
}

.hr__label {
  display: flex;
  align-items: baseline;
  gap: var(--space-3);
  margin: 0 0 var(--space-1);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: var(--tracking-wider);
  text-transform: uppercase;
}

.hr__rule {
  flex: 1;
  height: 1px;
  background: var(--border);
}

.hr__list {
  display: flex;
  flex-direction: column;
}
</style>
```

- [ ] **Step 3: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/renderer/src/components/home/HomeResume.vue frontend/src/renderer/src/components/home/HomeResumeEntry.vue
git commit -m "feat(home): add HomeResume dossier list + entry"
```

---

## Task 12: Frontend — HomeColophon.vue

**Files:**
- Create: `frontend/src/renderer/src/components/home/HomeColophon.vue`

- [ ] **Step 1: Create the component**

```vue
<script setup lang="ts">
/**
 * Mono runtime colophon: local model readiness, memory count, services health,
 * RAG readiness. Real signals only. Loads memory stats on mount if missing.
 */
import { computed, onMounted } from 'vue'
import { useSettingsStore } from '../../stores/settings'
import { useServicesStore } from '../../stores/services'
import { useMemoryStore } from '../../stores/memory'

type Tone = 'ok' | 'warn' | 'muted'
interface ColophonItem { label: string; value: string; tone: Tone }

const settingsStore = useSettingsStore()
const servicesStore = useServicesStore()
const memoryStore = useMemoryStore()

onMounted(() => {
  if (!memoryStore.stats) void memoryStore.loadStats()
})

const modelItem = computed<ColophonItem>(() => {
  const ready = settingsStore.lmStudioConnected && settingsStore.activeModel
  return {
    label: 'modello locale',
    value: ready ? `${settingsStore.activeModel?.name} pronto` : 'non pronto',
    tone: ready ? 'ok' : 'warn',
  }
})

const memoryItem = computed<ColophonItem>(() => {
  const total = memoryStore.stats?.total ?? 0
  return { label: 'memoria', value: `${total} ricordi`, tone: 'muted' }
})

const servicesItem = computed<ColophonItem>(() => ({
  label: 'servizi',
  value: servicesStore.hasDegraded ? 'attenzione' : 'attivi',
  tone: servicesStore.hasDegraded ? 'warn' : 'ok',
}))

const ragItem = computed<ColophonItem>(() => {
  const ready = servicesStore.knowledge?.ready ?? false
  return { label: 'rag', value: ready ? 'pronto' : 'non pronto', tone: ready ? 'ok' : 'muted' }
})

const items = computed<ColophonItem[]>(() => [
  modelItem.value,
  memoryItem.value,
  servicesItem.value,
  ragItem.value,
])
</script>

<template>
  <footer class="hcol">
    <span v-for="item in items" :key="item.label" class="hcol__item">
      <span class="hcol__dot" :class="`hcol__dot--${item.tone}`" aria-hidden="true" />
      <b class="hcol__label">{{ item.label }}</b>
      <span class="hcol__value">· {{ item.value }}</span>
    </span>
  </footer>
</template>

<style scoped>
.hcol {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-5);
  margin-top: var(--space-12);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  letter-spacing: var(--tracking-normal);
  color: var(--text-muted);
}

.hcol__item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
}

.hcol__dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
}

.hcol__dot--ok {
  background: var(--success);
}

.hcol__dot--warn {
  background: var(--warning);
}

.hcol__dot--muted {
  background: var(--text-muted);
}

.hcol__label {
  color: var(--text-secondary);
  font-weight: var(--weight-medium);
}
</style>
```

- [ ] **Step 2: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/renderer/src/components/home/HomeColophon.vue
git commit -m "feat(home): add HomeColophon runtime status line"
```

---

## Task 13: Frontend — rewrite HomeView.vue (orchestration + layout + atmosphere)

**Files:**
- Modify (full rewrite): `frontend/src/renderer/src/views/HomeView.vue`

- [ ] **Step 1: Replace the entire file**

Overwrite `frontend/src/renderer/src/views/HomeView.vue` with:

```vue
<script setup lang="ts">
/**
 * AL\CE — Home ("editorial dossier").
 *
 * A personal, agentic entry surface (not a launcher): time-of-day greeting,
 * a hero composer that starts a REAL turn via useChat().sendMessage, recent
 * conversations to resume, and a runtime colophon. Real signals only.
 */
import { computed, inject, nextTick, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ChatApiKey } from '../composables/useChat'
import { useChatStore } from '../stores/chat'
import { useMemoryStore } from '../stores/memory'
import { useUIStore } from '../stores/ui'

import HomeGreeting from '../components/home/HomeGreeting.vue'
import HomeComposer from '../components/home/HomeComposer.vue'
import HomeIntents from '../components/home/HomeIntents.vue'
import HomeResume from '../components/home/HomeResume.vue'
import HomeColophon from '../components/home/HomeColophon.vue'

const router = useRouter()
const chatStore = useChatStore()
const memoryStore = useMemoryStore()
const uiStore = useUIStore()
const chatApi = inject(ChatApiKey)

const draft = ref('')
const composerRef = ref<InstanceType<typeof HomeComposer> | null>(null)

const conversationCount = computed(
  () => chatStore.conversations.filter((c) => c.message_count > 0).length,
)
const memoryCount = computed(() => memoryStore.stats?.total ?? 0)

/** Navigate into the user's active chat surface (workspace/assistant). */
async function enterActiveSurface(): Promise<void> {
  try {
    await router.push({ name: uiStore.mode })
  } catch (err) {
    console.error('[HomeView] Navigation failed:', err)
  }
}

/** Submit the composer: start a real turn, then enter the active surface. */
async function onSubmit(): Promise<void> {
  const text = draft.value.trim()
  if (!text || !chatApi) return
  draft.value = ''
  await chatApi.sendMessage(text)
  await enterActiveSurface()
}

/** Prefill the composer from an intent chip and focus it. */
function onPrefill(text: string): void {
  draft.value = text
  void nextTick(() => composerRef.value?.focus())
}

/** Reopen the most recent non-empty conversation. */
async function onResumeLast(): Promise<void> {
  const last = [...chatStore.conversations]
    .filter((c) => c.message_count > 0)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())[0]
  if (last) await onOpen(last.id)
}

/** Open a specific conversation, then enter the active surface. */
async function onOpen(id: string): Promise<void> {
  try {
    await chatStore.loadConversation(id)
  } catch (err) {
    console.error(`[HomeView] Failed to load conversation ${id}:`, err)
    return
  }
  await enterActiveSurface()
}
</script>

<template>
  <div class="home">
    <div class="home__atmosphere" aria-hidden="true" />
    <main class="home__page">
      <HomeGreeting :conversation-count="conversationCount" :memory-count="memoryCount" />
      <HomeComposer ref="composerRef" v-model="draft" @submit="onSubmit" />
      <HomeIntents @prefill="onPrefill" @resume-last="onResumeLast" />
      <HomeResume :conversations="chatStore.conversations" @open="onOpen" />
      <HomeColophon />
    </main>
  </div>
</template>

<style scoped>
.home {
  position: relative;
  width: 100%;
  height: 100%;
  overflow-y: auto;
  background: var(--surface-0);
  color: var(--text-primary);
}

/* A single warm light source, top-right — atmosphere, not decoration. */
.home__atmosphere {
  position: absolute;
  inset: 0;
  z-index: var(--z-base);
  pointer-events: none;
  background: radial-gradient(120% 90% at 88% -10%, var(--accent-glow), transparent 55%);
}

.home__page {
  position: relative;
  z-index: var(--z-raised);
  width: min(680px, 100%);
  margin-inline: auto;
  padding: clamp(var(--space-10), 9vh, var(--space-20)) var(--space-8) var(--space-12);
}

@media (max-width: 680px) {
  .home__page {
    padding: var(--space-10) var(--space-5) var(--space-8);
  }
}
</style>
```

- [ ] **Step 2: Type-check**

Run (from `frontend/`): `npm run typecheck`
Expected: PASS (no unused imports, all component props/events match).

- [ ] **Step 3: Lint**

Run (from `frontend/`): `npm run lint`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/renderer/src/views/HomeView.vue
git commit -m "feat(home): rewrite HomeView as editorial dossier (greeting/composer/resume/colophon)"
```

---

## Task 14: Verification — full build, tests, and manual check

**Files:** none (verification only)

- [ ] **Step 1: Frontend type-check + lint + unit tests**

Run (from `frontend/`):
```
npm run typecheck
npm run lint
npm run test
```
Expected: typecheck PASS, lint clean, Vitest PASS (relativeTime suite).

- [ ] **Step 2: Backend tests + lint + types**

Run (from `backend/`):
```
pytest tests/test_llm_preferred_name.py tests/test_app.py -q
ruff check .
mypy services/llm_service.py core/config.py api/routes/config.py services/preferences_service.py
```
Expected: tests PASS, ruff clean, mypy clean.

- [ ] **Step 3: Manual verification (run the app)**

Start backend + frontend (`./scripts/start-dev.ps1`), then verify:
- App opens on `/home` (default landing).
- Greeting shows the correct time-of-day word; date kicker is in Italian; the greeting is the only serif text.
- Set a name in Settings → "Come Alice deve chiamarti" → return to Home → greeting shows ", <name>". Send a message → the model addresses you by name (confirms the system-prompt injection).
- Typing a message + Enter starts a turn and navigates into the active surface (workspace/assistant) with the turn running.
- Intent chips prefill the composer; "Riprendi l'ultima" reopens the latest thread.
- "Riprendi" lists real recent conversations and opens them; first run (no conversations) shows the empty state — no fabricated entries.
- Colophon reflects real model/memory/services/RAG state; a degraded service shows the warning dot.
- "Home" link appears in the sidebar and routes to `/home`; mode (assistant/workspace) is unchanged by visiting Home.
- Toggle light/dark — greeting and palette read correctly in both.

- [ ] **Step 4: Final commit (if any manual fixes were needed)**

```bash
git add -A
git commit -m "fix(home): manual verification adjustments"
```

(Skip if Step 3 required no changes.)

---

## Notes for the implementer

- **Local-first:** never load fonts from a CDN. `@fontsource/fraunces` bundles the font into the build (Task 7). If install is blocked offline, fall back to `Georgia, serif` in `HomeGreeting.vue` — do NOT add a `<link>` to Google Fonts.
- **Real data only:** do not add fabricated activity timestamps or fake entries anywhere. Every value comes from a store.
- **Theme tokens only:** no hardcoded colors/sizes — use the CSS variables in `assets/styles/theme.css` (light + dark both derive from them).
- **`--space-3-5` fallback:** `HomeIntents.vue` uses `var(--space-3-5, 14px)` — the fallback covers the token not existing; leave as written.
- **Deferred (intentional):** the optional "Alice sta lavorando…" live-work strip (`agentRunStore.currentRun`) is NOT built — it was marked optional in the spec and omitted to keep scope tight. Add later if desired.
- **Persistence gate:** Task 2 relies on `PreferencesService.persist_from_update` honoring `PERSISTABLE_LLM_KEYS`. If a post-restart check shows the name not persisting, verify that method filters `llm.*` through `PERSISTABLE_LLM_KEYS` (it should) before looking elsewhere.
```
