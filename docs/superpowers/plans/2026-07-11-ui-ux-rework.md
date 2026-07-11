# Piano di Rework UI/UX — Frontend AL\CE

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare il frontend a coerenza professionale completa: kit UI adottato ovunque, stati interattivi completi (incluso focus da tastiera oggi invisibile), pattern consolidati, zero valori hardcoded residui, struttura pulita.

**Architecture:** Il kit `components/ui/` esiste ed è di alta qualità (API coerenti `size/variant/disabled/loading/ariaLabel`, a11y, tutto tokenizzato) ma ha adozione quasi nulla fuori da settings/board/canvas: 199 `<button>` nativi vs 0 usi di UiButton, 56 `<input>` vs 0 UiInput, ~145 `title=` vs 0 UiTooltip, 12 spinner reimplementati, 8 empty-state manuali, chip a mano in 29 file. Il rework quindi NON riscrive il kit: lo completa (focus ring, UiChip, UiSearchInput, UiTextarea, UiSectionHeader) e poi migra le superfici area per area, infine tokenizza il residuo (transition, pannelli, code-blocks, palette JS di ECharts/xterm).

**Tech Stack:** Vue 3 `<script setup lang="ts">` + Composition API, Pinia, electron-vite, CSS custom property in `assets/styles/theme.css` (dual theme via `[data-theme='light']`), icone via `AppIcon` + `assets/icons.ts`.

**Vincolo di test:** `vitest` gira in ambiente `node` SENZA plugin SFC né `@vue/test-utils` (vedi header di `src/renderer/src/components/chat/TaskStrip.spec.ts`): i componenti `.vue` non sono montabili nei test. I gate di verifica per il lavoro UI sono: `npm run typecheck` + `npm run lint` + `npx vitest run` (per non regredire gli spec esistenti) + verifica visiva nell'app (`npm run dev`). Non scrivere spec che importano `.vue`.

**Percorsi:** tutti relativi a `frontend/` salvo indicazione. Comandi da eseguire in `frontend/`.

---

## Linee guida di design (normative per tutte le fasi)

Queste regole governano ogni task. In caso di dubbio durante l'esecuzione, si applicano queste.

### Gerarchia CTA
| Livello | Componente | Quando |
|---|---|---|
| Primary | `UiButton variant="primary"` (pieno, crema) | L'azione principale della superficie/dialogo. **Massimo una per vista/dialogo.** |
| Secondary | `UiButton variant="secondary"` (outline) | Azioni alternative accanto alla primary (Annulla, opzioni). |
| Ghost | `UiButton variant="ghost"` | Azioni terziarie, toolbar, azioni inline in liste. |
| Danger | `UiButton variant="danger"` | Azioni distruttive. Nei dialoghi di conferma distruttivi il bottone di conferma è `danger`, MAI `primary`. |
| Icon-only | `UiIconButton` (varianti `ghost/subtle/outlined`, prop `active`) | Toolbar, controlli inline, navigazione. `label` obbligatoria (diventa aria-label + tooltip nativo). |

### Matrice stati obbligatoria
Ogni elemento interattivo (kit o bespoke) deve coprire: **default / hover / active(pressed) / focus-visible / disabled / loading** (dove applicabile), più `selected`/`active` per elementi toggle-like e `error` per gli input. I componenti kit la coprono già; per elementi bespoke che si decide di NON migrare (vedi "Regola bespoke"), verificare la matrice e completarla con i token (`--surface-hover`, `--surface-active`, `--opacity-disabled`, focus ring globale della Fase 1).

### Icone
- Icone interattive SOLO dentro `UiIconButton` (mai `<button class="..."><svg>` a mano nei nuovi cambi).
- Colori degli stati icona via token: `--interactive-normal/hover/active/muted`; stato attivo `--accent` su `--accent-dim` (UiIconButton `active` lo fa già).
- Icone decorative: `AppIcon` con `aria-hidden` (default del componente).

### Tooltip
- Icon-only: il `title` nativo lo fornisce già `UiIconButton` dalla `label` — non aggiungere altro.
- Contenuti più ricchi o delay controllato: `UiTooltip`.
- Vietato aggiungere nuovi `title=` su elementi custom.

### Token
- Colori e ombre: SOLO `var(--…)`. Nei nuovi cambi anche font-size, radius, durate e easing SOLO a token (`--text-*`, `--radius-*`, `--duration-*`, `--ease-*`, `--z-*`).
- Px letterali ammessi solo per geometrie interne ≤ 4px non riusabili (es. dot 6px, stroke 1.4) — già così nel kit.
- Motion: `--duration-fast` per micro-interazioni, `--duration-normal` per pannelli, easing `--ease-out-quart` di default.

### Regola bespoke (Horizon e superfici editoriali)
Non tutto va convertito al kit. Regola di decisione per ogni elemento:
1. Se ha l'aspetto/il ruolo di una variante kit esistente → **migra** al componente kit.
2. Se è un elemento di design unico e intenzionale (composer di Horizon, horizon line, stage) → **NON forzarlo nel kit**: tokenizza, completa la matrice stati e lascia il markup bespoke.
In caso di dubbio: migra i controlli funzionali (icon button, close, nav), lascia bespoke gli elementi editoriali.

---

## FASE 0 — Igiene (rischio zero, ~mezza giornata)

### Task 0.1: Rimuovere i componenti morti

**Files:**
- Delete: `src/renderer/src/components/plugins/WeatherWidget.vue`
- Delete: `src/renderer/src/components/Versions.vue`

- [ ] **Step 1: Verificare che siano davvero orfani**

```powershell
cd frontend
Select-String -Path src -Pattern "WeatherWidget|Versions\.vue" -Recurse -Exclude *.spec.ts
```
Atteso: nessun match fuori dai file stessi (WeatherWidget non è registrato in `composables/usePluginComponents.ts`, che contiene solo calendar/web_search/network_probe). Se compare un match reale, fermarsi e riportare.

- [ ] **Step 2: Eliminare i file**

```powershell
git rm src/renderer/src/components/plugins/WeatherWidget.vue src/renderer/src/components/Versions.vue
```

- [ ] **Step 3: Gate**

```powershell
npm run typecheck; if ($?) { npm run lint }
```
Atteso: PASS entrambi.

- [ ] **Step 4: Commit**

```powershell
git commit -m "chore(frontend): remove dead components (WeatherWidget, Versions boilerplate)"
```

### Task 0.2: Sistemare il barrel `ui/index.ts`

Oggi il barrel esporta componenti mai usati e omette i più usati (UiSelect, UiToggle, UiCheckbox, UiPopover, UiSegmented, AppIcon). Va reso completo così gli import futuri della migrazione sono uniformi.

**Files:**
- Modify: `src/renderer/src/components/ui/index.ts`

- [ ] **Step 1: Sostituire l'intero contenuto con**

```ts
/**
 * AL\CE UI Component Library
 *
 * Reusable, accessible base components.
 * Import from '../ui' (or '@renderer/components/ui') for clean imports.
 */
export { default as AppIcon } from './AppIcon.vue'
export { default as UiButton } from './UiButton.vue'
export { default as UiIconButton } from './UiIconButton.vue'
export { default as UiInput } from './UiInput.vue'
export { default as UiSelect } from './UiSelect.vue'
export { default as UiCheckbox } from './UiCheckbox.vue'
export { default as UiToggle } from './UiToggle.vue'
export { default as UiSegmented } from './UiSegmented.vue'
export { default as UiCard } from './UiCard.vue'
export { default as UiBadge } from './UiBadge.vue'
export { default as UiSkeleton } from './UiSkeleton.vue'
export { default as UiTooltip } from './UiTooltip.vue'
export { default as UiPopover } from './UiPopover.vue'
export { default as UiDivider } from './UiDivider.vue'
export { default as UiAvatar } from './UiAvatar.vue'
export { default as UiToast } from './UiToast.vue'
export { default as UiContextMenu } from './UiContextMenu.vue'
export { default as UiContextMenuItem } from './UiContextMenuItem.vue'
export { default as UiContextMenuDivider } from './UiContextMenuDivider.vue'
export { default as UiEmptyState } from './UiEmptyState.vue'
export { default as AliceLoader } from './AliceLoader.vue'
export { default as AliceSpinner } from './AliceSpinner.vue'
export { default as BrandAsset } from '../branding/BrandAsset.vue'
export { default as BrandThemeToggle } from '../branding/BrandThemeToggle.vue'
export { default as BrandWordmark } from '../branding/BrandWordmark.vue'
```

- [ ] **Step 2: Gate + commit**

```powershell
npm run typecheck; if ($?) { npm run lint }
git add src/renderer/src/components/ui/index.ts
git commit -m "chore(ui): complete barrel exports (UiSelect, UiToggle, UiCheckbox, UiPopover, UiSegmented, AppIcon)"
```

### Task 0.3: Adottare l'alias `@renderer` sugli import profondi

L'alias è già configurato (`electron.vite.config.ts:13` → `'@renderer': resolve('src/renderer/src')`; `tsconfig.web.json` → `"@renderer/*": ["src/renderer/src/*"]`) ma ha 0 usi; esistono 18 import `../../../` (tutti in `components/canvas/modules/` e `components/whiteboard/`).

- [ ] **Step 1: Elencare i file coinvolti**

```powershell
Select-String -Path src/renderer/src -Pattern "from '\.\./\.\./\.\./" -Recurse | Select-Object Path, LineNumber, Line
```

- [ ] **Step 2: Per ogni occorrenza, sostituire il prefisso `../../../` con `@renderer/`**

Esempio (pattern, stessa forma per tutte):
```ts
// Prima
import { useWorkspaceStore } from '../../../stores/workspace'
// Dopo
import { useWorkspaceStore } from '@renderer/stores/workspace'
```
NON toccare gli import `../` e `../../` in questo task (513 totali — migrazione progressiva fuori scope).

- [ ] **Step 3: Gate + commit**

```powershell
npm run typecheck; if ($?) { npm run lint }; if ($?) { npx vitest run }
git add -A; git commit -m "refactor(frontend): use @renderer alias for deep relative imports"
```

### Task 0.4: Incapsulare gli `<style>` non-scoped

4 SFC hanno `<style>` senza `scoped` fuori da App.vue: `components/chat/ChatToolControls.vue`, `components/chat/ContextBar.vue`, `components/chat/ScopeIndicator.vue`, `components/settings/ModelSelector.vue`.

- [ ] **Step 1: Per ciascun file, ispezionare PERCHÉ è globale**

Se gli stili targetizzano contenuto renderizzato da componenti figli o da teleport (motivo tipico per non-scoped), convertire a `<style scoped>` usando `:deep()` sui selettori che attraversano il confine. Se targetizzano elementi globali (body, overlay teleportati a body), spostare quelle sole regole in un blocco `<style>` globale minimale con commento che ne spiega la necessità, e portare il resto sotto `scoped`.

- [ ] **Step 2: Verifica visiva**

`npm run dev` → aprire chat (tool controls, context bar, scope indicator) e settings → Models; confermare che nulla è cambiato visivamente.

- [ ] **Step 3: Gate + commit**

```powershell
npm run typecheck; if ($?) { npm run lint }
git add -A; git commit -m "fix(frontend): scope leaky component styles (ChatToolControls, ContextBar, ScopeIndicator, ModelSelector)"
```

---

## FASE 1 — Fondamenta: focus ring + componenti mancanti

### Task 1.1: Focus ring visibile (a11y + UX tastiera)

Oggi il focus da tastiera è INVISIBILE ovunque: `theme.css:335-342` definisce `--focus-ring-width: 0px` / `--focus-ring-shadow: none`, `theme.css:436-439` fa `:focus-visible { outline: none; box-shadow: none; }`, e i componenti kit ribadiscono `outline: none` su `:focus-visible`. Il redesign introduce un anello elegante (crema, 2px, offset) solo per navigazione da tastiera (`:focus-visible`, non `:focus`).

**Files:**
- Modify: `src/renderer/src/assets/styles/theme.css` (sezioni Focus Ring System, Focus-visible Reset, blocco light theme)
- Modify: componenti kit con `:focus-visible { outline: none }` (elenco allo step 3)

- [ ] **Step 1: Aggiornare la sezione "Focus Ring System" (`theme.css:335-342`)**

Sostituire il blocco con:
```css
/* ── Focus Ring System ─────────────────────────────────────── */
/* Visibile SOLO per navigazione da tastiera (:focus-visible).   */
:root {
  --focus-ring-color: rgba(232, 220, 200, 0.55);
  --focus-ring-width: 2px;
  --focus-ring-offset: 2px;
  --focus-ring: var(--focus-ring-width) solid var(--focus-ring-color);
}
```
Nota: `--focus-ring-shadow` viene rimosso — prima verificare i consumer: `Select-String -Path src -Pattern "focus-ring-shadow|--shadow-focus" -Recurse`. Se ha consumer, aggiornarli a usare outline (step 2) o mapparli a `0 0 0 var(--focus-ring-width) var(--focus-ring-color)`.

- [ ] **Step 2: Sostituire il reset globale (`theme.css:435-446`)**

```css
/* ── Focus-visible — Anello globale da tastiera ────────────── */
:focus-visible {
  outline: var(--focus-ring);
  outline-offset: var(--focus-ring-offset);
}

/* Il focus da mouse/touch non mostra l'anello */
:focus:not(:focus-visible) {
  outline: none;
}
```
`outline` (non box-shadow) così non confligge con le ombre dei componenti e segue il border-radius (Chromium/Electron lo supporta).

- [ ] **Step 3: Rimuovere i null-override nel kit**

```powershell
Select-String -Path src/renderer/src/components -Pattern "focus-visible" -Recurse -Context 0,2
```
Per ogni blocco `X:focus-visible { outline: none; }` che NON definisce uno stile visibile alternativo: eliminare il blocco (l'anello globale subentra). File noti nel kit: `UiButton.vue:116-118`, `UiIconButton.vue:108-110`, `UiBadge.vue:165-167`; controllare anche UiCard, UiCheckbox, UiContextMenu*, UiSegmented, UiSelect, UiToast, UiToggle e i componenti FUORI dal kit trovati dal grep. Se un componente definisce già un focus visibile proprio (es. un ring dedicato in UiCheckbox/UiToggle), lasciarlo.

- [ ] **Step 4: Variante light theme**

Nel blocco `[data-theme='light']` di `theme.css` (dopo la riga che rimappa `--accent` al Taupe Mocha), aggiungere:
```css
  --focus-ring-color: rgba(140, 106, 74, 0.55); /* Taupe Mocha ring on ivory */
```

- [ ] **Step 5: Verifica visiva da tastiera**

`npm run dev` → navigare SOLO con Tab/Shift+Tab in: sidebar, chat input, settings, un dialogo modale. Atteso: anello crema (taupe in light) visibile su ogni elemento focalizzato; NESSUN anello quando si clicca col mouse. Controllare anche che i dialoghi (`useModal`) intrappolino il focus come prima.

- [ ] **Step 6: Gate + commit**

```powershell
npm run typecheck; if ($?) { npm run lint }
git add -A; git commit -m "feat(ui): visible keyboard focus ring system (focus-visible, dual theme)"
```

### Task 1.2: `UiTextarea` (nuovo componente)

9 `<textarea>` nativi in 8 file senza wrapper condiviso. Speculare a UiInput (stessa API: label/hint/error/disabled/required/loading + `rows` e `autoGrow`).

**Files:**
- Create: `src/renderer/src/components/ui/UiTextarea.vue`
- Modify: `src/renderer/src/components/ui/index.ts` (aggiungere export)

- [ ] **Step 1: Creare il componente**

```vue
<script setup lang="ts">
/**
 * UiTextarea — Multiline input with the same states/a11y as UiInput.
 *
 *  - Real <label for> / <textarea id> association (auto id via useId).
 *  - aria-invalid + aria-describedby for error / hint.
 *  - `autoGrow` resizes the textarea to its content (up to maxRows).
 */
import { computed, ref, useId, watch, nextTick, onMounted } from 'vue'

export interface UiTextareaProps {
  modelValue?: string
  placeholder?: string
  label?: string
  hint?: string
  error?: string
  disabled?: boolean
  readonly?: boolean
  required?: boolean
  rows?: number
  /** Grow with content instead of showing a scrollbar. */
  autoGrow?: boolean
  /** Upper bound for autoGrow, in rows. */
  maxRows?: number
  maxlength?: number
  name?: string
  id?: string
  ariaLabel?: string
}

const props = withDefaults(defineProps<UiTextareaProps>(), {
  modelValue: '',
  placeholder: '',
  label: '',
  hint: '',
  error: '',
  disabled: false,
  readonly: false,
  required: false,
  rows: 3,
  autoGrow: false,
  maxRows: 10,
  maxlength: undefined,
  name: undefined,
  id: undefined,
  ariaLabel: undefined
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  focus: [event: FocusEvent]
  blur: [event: FocusEvent]
  keydown: [event: KeyboardEvent]
}>()

const autoId = useId()
const fieldId = computed(() => props.id ?? `ui-textarea-${autoId}`)
const errorId = computed(() => `${fieldId.value}-error`)
const hintId = computed(() => `${fieldId.value}-hint`)
const describedBy = computed(() => {
  if (props.error) return errorId.value
  if (props.hint) return hintId.value
  return undefined
})

const el = ref<HTMLTextAreaElement | null>(null)

function resize(): void {
  const node = el.value
  if (!node || !props.autoGrow) return
  node.style.height = 'auto'
  const lineHeight = parseFloat(getComputedStyle(node).lineHeight) || 20
  const max = props.maxRows * lineHeight
  node.style.height = `${Math.min(node.scrollHeight, max)}px`
  node.style.overflowY = node.scrollHeight > max ? 'auto' : 'hidden'
}

function onInput(e: Event): void {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}

watch(
  () => props.modelValue,
  () => void nextTick(resize)
)
onMounted(resize)
</script>

<template>
  <div
    class="ui-textarea"
    :class="{ 'ui-textarea--error': error, 'ui-textarea--disabled': disabled }"
  >
    <label v-if="label" :for="fieldId" class="ui-textarea__label">
      {{ label }}
      <span v-if="required" class="ui-textarea__required" aria-hidden="true">*</span>
    </label>
    <textarea
      :id="fieldId"
      ref="el"
      class="ui-textarea__field"
      :value="modelValue"
      :placeholder="placeholder"
      :disabled="disabled"
      :readonly="readonly"
      :required="required"
      :rows="rows"
      :maxlength="maxlength"
      :name="name"
      :aria-label="ariaLabel || undefined"
      :aria-invalid="!!error || undefined"
      :aria-describedby="describedBy"
      @input="onInput"
      @focus="emit('focus', $event)"
      @blur="emit('blur', $event)"
      @keydown="emit('keydown', $event)"
    />
    <p v-if="error" :id="errorId" class="ui-textarea__error" role="alert">{{ error }}</p>
    <p v-else-if="hint" :id="hintId" class="ui-textarea__hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.ui-textarea {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.ui-textarea__label {
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
  display: inline-flex;
  gap: var(--space-1);
}

.ui-textarea__required {
  color: var(--danger);
}

.ui-textarea__field {
  width: 100%;
  min-height: calc(var(--input-height-md) * 1.5);
  padding: var(--space-2) var(--space-3);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  resize: vertical;
  transition:
    background-color var(--duration-fast) var(--ease-out-quart),
    border-color var(--duration-fast) var(--ease-out-quart);
}

.ui-textarea__field::placeholder {
  color: var(--text-muted);
}

.ui-textarea:not(.ui-textarea--disabled):not(.ui-textarea--error) .ui-textarea__field:hover {
  border-color: var(--border-hover);
}

.ui-textarea:not(.ui-textarea--error) .ui-textarea__field:focus {
  border-color: var(--accent-border);
  outline: none;
}

.ui-textarea--error .ui-textarea__field {
  border-color: var(--danger-border);
}

.ui-textarea__error {
  font-size: var(--text-xs);
  color: var(--danger);
}

.ui-textarea__hint {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.ui-textarea--disabled {
  opacity: var(--opacity-disabled);
  pointer-events: none;
}

.ui-textarea--disabled .ui-textarea__field {
  background: var(--surface-inset);
  resize: none;
}
</style>
```
Nota: il `:focus` interno gestisce il bordo; l'anello da tastiera arriva dal ring globale (Task 1.1) su `:focus-visible`.

- [ ] **Step 2: Aggiungere al barrel** — in `index.ts` dopo la riga di UiInput: `export { default as UiTextarea } from './UiTextarea.vue'`

- [ ] **Step 3: Gate + commit**

```powershell
npm run typecheck; if ($?) { npm run lint }
git add -A; git commit -m "feat(ui): add UiTextarea (label/hint/error states, autoGrow)"
```

### Task 1.3: `UiChip` (nuovo componente)

Chip/tag/pill fatti a mano in 29 file. Distinzione dal kit esistente: **UiBadge = status non interattivo**, **UiChip = interattivo** (filtri, selezioni, tag rimovibili).

**Files:**
- Create: `src/renderer/src/components/ui/UiChip.vue`
- Modify: `src/renderer/src/components/ui/index.ts`

- [ ] **Step 1: Creare il componente**

```vue
<script setup lang="ts">
/**
 * UiChip — Interactive chip (filter, selectable tag, removable token).
 *
 * UiBadge is for non-interactive status; UiChip is a real <button>:
 * hover / active / selected / focus-visible / disabled states,
 * optional remove affordance (click on ✕ or Delete/Backspace key).
 */
export interface UiChipProps {
  /** Selected/pressed state (aria-pressed). */
  selected?: boolean
  disabled?: boolean
  /** Show a trailing ✕ and emit `remove`. */
  removable?: boolean
  size?: 'sm' | 'md'
  /** Accessible label for the remove affordance. */
  removeLabel?: string
}

const props = withDefaults(defineProps<UiChipProps>(), {
  selected: false,
  disabled: false,
  removable: false,
  size: 'sm',
  removeLabel: 'Rimuovi'
})

const emit = defineEmits<{
  click: [event: MouseEvent]
  remove: [event: Event]
}>()

function onKeydown(e: KeyboardEvent): void {
  if (props.removable && (e.key === 'Delete' || e.key === 'Backspace')) {
    e.preventDefault()
    emit('remove', e)
  }
}
</script>

<template>
  <button
    type="button"
    class="ui-chip"
    :class="[`ui-chip--${size}`, { 'ui-chip--selected': selected }]"
    :disabled="disabled"
    :aria-pressed="selected || undefined"
    @click="emit('click', $event)"
    @keydown="onKeydown"
  >
    <span v-if="$slots.icon" class="ui-chip__icon" aria-hidden="true">
      <slot name="icon" />
    </span>
    <span class="ui-chip__label"><slot /></span>
    <!-- span aria-hidden, non button: un button annidato in un button è HTML
         invalido. Da tastiera la rimozione passa per Delete/Backspace sul chip
         (onKeydown sopra); `removeLabel` resta per screen reader via title. -->
    <span
      v-if="removable"
      class="ui-chip__remove"
      :title="removeLabel"
      aria-hidden="true"
      @click.stop="emit('remove', $event)"
    >
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
        <path
          d="M2 2 L8 8 M8 2 L2 8"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-linecap="round"
        />
      </svg>
    </span>
  </button>
</template>

<style scoped>
.ui-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-secondary);
  font-family: var(--font-sans);
  font-weight: var(--weight-medium);
  white-space: nowrap;
  cursor: pointer;
  max-width: 100%;
  transition:
    background-color var(--duration-fast) var(--ease-out-quart),
    border-color var(--duration-fast) var(--ease-out-quart),
    color var(--duration-fast) var(--ease-out-quart);
}

.ui-chip:hover:not(:disabled) {
  background: var(--surface-hover);
  border-color: var(--border-hover);
  color: var(--text-primary);
}

.ui-chip:active:not(:disabled) {
  background: var(--surface-active);
}

.ui-chip:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
  pointer-events: none;
}

.ui-chip--selected {
  background: var(--accent-dim);
  border-color: var(--accent-border);
  color: var(--accent);
}

.ui-chip--selected:hover:not(:disabled) {
  background: var(--accent-light);
  color: var(--accent);
}

/* ── Sizes ────── */
.ui-chip--sm {
  padding: var(--space-0-5) var(--space-2);
  font-size: var(--text-2xs);
}

.ui-chip--md {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
}

.ui-chip__label {
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.ui-chip__icon {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.ui-chip__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  margin-inline-start: var(--space-0-5);
  border-radius: var(--radius-full);
  color: inherit;
  opacity: var(--opacity-medium);
  flex-shrink: 0;
  transition:
    background-color var(--duration-fast) var(--ease-out-quart),
    opacity var(--duration-fast) var(--ease-out-quart);
}

.ui-chip__remove:hover {
  background: var(--surface-hover);
  opacity: 1;
}
</style>
```

- [ ] **Step 2: Barrel** — `export { default as UiChip } from './UiChip.vue'` dopo UiBadge.

- [ ] **Step 3: Gate + commit**

```powershell
npm run typecheck; if ($?) { npm run lint }
git add -A; git commit -m "feat(ui): add UiChip interactive chip (selected/removable states)"
```

### Task 1.4: `UiSearchInput` (nuovo componente) + forward keydown in UiInput

Search bar (input + lente) ripetuta in 8 file. UiInput oggi non inoltra `keydown` (serve per Esc-to-clear).

**Files:**
- Modify: `src/renderer/src/components/ui/UiInput.vue` (emit keydown)
- Create: `src/renderer/src/components/ui/UiSearchInput.vue`
- Modify: `src/renderer/src/components/ui/index.ts`

- [ ] **Step 1: In `UiInput.vue` aggiungere l'evento keydown**

Nel blocco `defineEmits` (righe 59-63) aggiungere la riga:
```ts
  keydown: [event: KeyboardEvent]
```
e sull'`<input>` (dopo `@blur="emit('blur', $event)"` a riga 115) aggiungere:
```
        @keydown="emit('keydown', $event)"
```

- [ ] **Step 2: Creare `UiSearchInput.vue`**

I nomi icona sono nel registry: `search` e `close` esistono in `assets/icons.ts` (righe 74 e ~40).

```vue
<script setup lang="ts">
/**
 * UiSearchInput — Standard search field: leading lens, clear affordance,
 * Esc clears. Thin wrapper over UiInput so states/a11y stay in one place.
 */
import UiInput from './UiInput.vue'
import AppIcon from './AppIcon.vue'

export interface UiSearchInputProps {
  modelValue?: string
  placeholder?: string
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  /** Accessible label (there is usually no visible label on search fields). */
  ariaLabel?: string
  clearLabel?: string
}

const props = withDefaults(defineProps<UiSearchInputProps>(), {
  modelValue: '',
  placeholder: 'Cerca…',
  size: 'sm',
  disabled: false,
  ariaLabel: 'Cerca',
  clearLabel: 'Svuota ricerca'
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  clear: []
}>()

function clear(): void {
  if (!props.modelValue) return
  emit('update:modelValue', '')
  emit('clear')
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && props.modelValue) {
    e.stopPropagation()
    clear()
  }
}
</script>

<template>
  <UiInput
    class="ui-search"
    :model-value="modelValue"
    :placeholder="placeholder"
    :size="size"
    :disabled="disabled"
    :aria-label="ariaLabel"
    type="search"
    @update:model-value="emit('update:modelValue', $event)"
    @keydown="onKeydown"
  >
    <template #prefix>
      <AppIcon name="search" :size="14" />
    </template>
    <template #suffix>
      <button
        v-if="modelValue"
        type="button"
        class="ui-search__clear"
        :aria-label="clearLabel"
        @click="clear"
      >
        <AppIcon name="close" :size="12" />
      </button>
    </template>
  </UiInput>
</template>

<style scoped>
.ui-search__clear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-0-5);
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    color var(--duration-fast) var(--ease-out-quart),
    background-color var(--duration-fast) var(--ease-out-quart);
}

.ui-search__clear:hover {
  color: var(--text-primary);
  background: var(--surface-hover);
}
</style>

<!-- Nota esecutore: se il nome icona `close` non esistesse nel registry
     (verificare con: Select-String -Path src/renderer/src/assets/icons.ts -Pattern "close"),
     usare `circle-x` o aggiungere l'entry al registry. -->
```
Nasconde anche il pulsante nativo "x" di `type="search"` in Chromium? Chromium mostra il suo cancel button: aggiungere in `theme.css` (sezione Global Reset, dopo `ul { list-style: none }`):
```css
input[type='search']::-webkit-search-cancel-button {
  -webkit-appearance: none;
}
```

- [ ] **Step 3: Barrel** — `export { default as UiSearchInput } from './UiSearchInput.vue'` dopo UiInput.

- [ ] **Step 4: Gate + commit**

```powershell
npm run typecheck; if ($?) { npm run lint }
git add -A; git commit -m "feat(ui): add UiSearchInput (lens, clear, Esc) + UiInput keydown forwarding"
```

### Task 1.5: `UiSectionHeader` (nuovo componente)

Pattern titolo+descrizione+azioni ripetuto in 8 file (settings soprattutto).

**Files:**
- Create: `src/renderer/src/components/ui/UiSectionHeader.vue`
- Modify: `src/renderer/src/components/ui/index.ts`

- [ ] **Step 1: Creare il componente**

```vue
<script setup lang="ts">
/**
 * UiSectionHeader — Section title row: title + optional description on the
 * left, actions slot on the right. Standardizes the header pattern used
 * across settings panels and managers.
 */
export interface UiSectionHeaderProps {
  title: string
  description?: string
  size?: 'sm' | 'md'
  /** Heading level for a11y/document outline (rendered tag). */
  level?: 2 | 3 | 4
}

withDefaults(defineProps<UiSectionHeaderProps>(), {
  description: '',
  size: 'md',
  level: 3
})
</script>

<template>
  <div class="ui-section-header" :class="`ui-section-header--${size}`">
    <div class="ui-section-header__text">
      <component :is="`h${level}`" class="ui-section-header__title">{{ title }}</component>
      <p v-if="description" class="ui-section-header__description">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="ui-section-header__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.ui-section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  width: 100%;
}

.ui-section-header__text {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  min-width: 0;
}

.ui-section-header__title {
  margin: 0;
  font-family: var(--font-display);
  color: var(--text-primary);
  font-weight: var(--weight-medium);
}

.ui-section-header--md .ui-section-header__title {
  font-size: var(--text-md);
}

.ui-section-header--sm .ui-section-header__title {
  font-size: var(--text-sm);
}

.ui-section-header__description {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: var(--leading-relaxed);
}

.ui-section-header__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}
</style>
```

- [ ] **Step 2: Barrel + gate + commit**

```powershell
npm run typecheck; if ($?) { npm run lint }
git add -A; git commit -m "feat(ui): add UiSectionHeader (title/description/actions pattern)"
```

---

## FASE 2 — Migrazione al kit, area per area

**Regole di trasformazione comuni a tutti i task di questa fase** (la "mappa"):

| Pattern trovato | Sostituire con |
|---|---|
| `<button class="…">Testo</button>` con stile da CTA | `<UiButton variant="primary\|secondary\|ghost\|danger" size="sm\|md">Testo</UiButton>` secondo la gerarchia CTA |
| `<button>` icon-only (svg/AppIcon dentro, spesso con `title=`) | `<UiIconButton :label="…" variant="ghost\|subtle\|outlined" size="xs\|sm\|md" :active="…">` con `<AppIcon …/>` nello slot; rimuovere il `title=` (lo genera la label) |
| `<input>` di form con label | `<UiInput v-model="…" label="…" :error="…" hint="…">` |
| input di ricerca (con icona lente) | `<UiSearchInput v-model="…" />` |
| `<textarea>` | `<UiTextarea v-model="…" …/>` |
| empty-state manuale (icona+titolo+sub) | `<UiEmptyState icon="…" title="…" subtitle="…">` (+ slot `actions`) |
| spinner custom con `@keyframes spin` locale | `<AliceSpinner size="xs\|sm\|md" />` (variante `dots` negli spazi stretti) + eliminare keyframes locali |
| chip/tag statico di stato | `<UiBadge variant="…">` |
| chip/tag cliccabile/filtro/rimovibile | `<UiChip :selected="…" removable …>` |
| `title="…"` su nuovi elementi interattivi custom | `UiTooltip` o migrare a UiIconButton |

**Procedura standard per ogni task di quest'area** (ripetuta, qui una volta sola):
1. Grep dell'area per `<button`, `<input`, `<textarea`, `@keyframes`, `title=`, classi `chip|tag|pill|empty`.
2. Per ogni occorrenza applicare la mappa; per gli elementi bespoke applicare la "Regola bespoke" (linee guida) e in tal caso completare la matrice stati con token invece di migrare.
3. Cancellare il CSS locale rimasto orfano dopo la sostituzione (classi bottone/input/spinner non più referenziate).
4. Gate: `npm run typecheck; npm run lint; npx vitest run` + verifica visiva dell'area in `npm run dev` (light E dark theme).
5. Commit: `refactor(<area>): adopt UI kit (UiButton/UiIconButton/UiInput/...)`.

**Esempio lavorato completo** (vale come riferimento per tutti i task 2.x):

Prima (pattern tipico da ConversationList/TitleBar):
```vue
<button class="icon-btn" title="Elimina conversazione" @click="remove(conv.id)">
  <AppIcon name="trash" :size="14" />
</button>
<style scoped>
.icon-btn { display:flex; padding:4px; border:none; background:transparent;
  color:#adaba4; border-radius:6px; cursor:pointer; }
.icon-btn:hover { background: rgba(232,220,200,0.08); color:#eceae5; }
</style>
```
Dopo:
```vue
<UiIconButton label="Elimina conversazione" size="sm" @click="remove(conv.id)">
  <AppIcon name="trash" :size="14" />
</UiIconButton>
```
(import: `import { UiIconButton, AppIcon } from '../ui'` — path relativo secondo l'area, o `@renderer/components/ui`). Il CSS `.icon-btn` va rimosso.

### Task 2.1: Area `chat/`

**Files (hotspot dall'audit):**
- Modify: `src/renderer/src/components/chat/ChatInput.vue` (5 button)
- Modify: `src/renderer/src/components/chat/MessageBubble.vue` (5 button)
- Modify: `src/renderer/src/components/chat/CADViewer.vue` (5 button + spinner riga ~535)
- Modify: `src/renderer/src/components/chat/ContextBar.vue` (spinner riga ~252)
- Modify: `src/renderer/src/components/chat/MessageEditDialog.vue` (textarea → UiTextarea)
- Modify: `src/renderer/src/components/chat/AskUserPrompt.vue` (3 button → UiButton, conferma = `primary`, alternative = `secondary`)
- Modify: `src/renderer/src/components/chat/ToolConfirmationDialog.vue` — **restyle, non spostare**: è guidato da eventi WS e ha timer/risk-badge, resta un componente autonomo MA i suoi bottoni diventano UiButton (approve = `primary`, deny = `secondary`, stop = `danger`), il risk-badge diventa `UiBadge variant="warning|danger"`, e tutto il CSS locale passa a token. NON migrarlo dentro `useModal`.

- [ ] **Step 1-5:** procedura standard + esempio lavorato. Attenzione: il composer di ChatInput è bespoke (Regola bespoke) — migrare solo i bottoni funzionali attorno (send, stop, attach, tier selector), non ridisegnare il campo.
- [ ] **Commit:** `refactor(chat): adopt UI kit across chat surface`

### Task 2.2: `TitleBar` + area `sidebar/`

**Files:**
- Modify: `src/renderer/src/components/TitleBar.vue` (6 button + spinner riga ~871). Eccezione: i controlli finestra (min/max/close) sono bespoke Electron per design — tokenizzarli, non migrarli.
- Modify: `src/renderer/src/components/sidebar/ConversationList.vue` (7 button)
- Modify: `src/renderer/src/components/sidebar/AppSidebar.vue` (icon buttons di navigazione → UiIconButton con `active` sullo stato di rotta corrente)

- [ ] **Step 1-5:** procedura standard.
- [ ] **Commit:** `refactor(shell): adopt UI kit in TitleBar and sidebar`

### Task 2.3: Area `settings/` (la più densa)

**Files:**
- Modify: `src/renderer/src/views/SettingsView.vue` (5 input; search → UiSearchInput; section header → UiSectionHeader)
- Modify: `src/renderer/src/components/settings/KnowledgeGraphManager.vue` (7 button; empty state righe ~77/118 → UiEmptyState; search → UiSearchInput)
- Modify: `src/renderer/src/components/settings/MemoryManager.vue` (6 button; empty ~105; search)
- Modify: `src/renderer/src/components/settings/EmailSettings.vue` (8 input → UiInput; search)
- Modify: `src/renderer/src/components/settings/McpManager.vue` (empty ~27-32; spinner ~435)
- Modify: `src/renderer/src/components/settings/VectorStoreManager.vue` (empty ~39)
- Modify: `src/renderer/src/components/settings/PluginManagement.vue` (empty ~9)
- Modify: `src/renderer/src/components/settings/PermissionRulesManager.vue` (empty ~131/178)
- Modify: `src/renderer/src/components/settings/AgentPersonaSettings.vue` (empty ~88; 2 textarea → UiTextarea; search)
- Modify: `src/renderer/src/components/settings/ModelSelector.vue` / `ModelManager.vue` (search; button)
- Modify: `src/renderer/src/components/settings/TrellisSetupGuideModal.vue` (spinner ~211)
- Modify: `src/renderer/src/components/voice/VoiceSettings.vue` (5 input)

- [ ] **Step 1-5:** procedura standard. Qui il ritorno è massimo: 8 empty-state manuali → UiEmptyState, 4 search bar → UiSearchInput, decine di input.
- [ ] **Commit:** `refactor(settings): adopt UI kit (inputs, empty states, search, buttons)`

### Task 2.4: Area `horizon/` (superficie primaria — applicare la Regola bespoke)

**Files:**
- Modify: `src/renderer/src/components/horizon/HorizonCockpit.vue` (4 button)
- Modify: `src/renderer/src/components/horizon/HorizonStage.vue` (3 button; chip in stage)
- Modify: `src/renderer/src/components/horizon/HorizonHistory.vue` (3 button)
- Modify: `src/renderer/src/components/horizon/HorizonShelf.vue` (2 button)
- Modify: `src/renderer/src/components/horizon/HorizonComposer.vue` (textarea: SOLO se lo stile coincide con UiTextarea; il composer è il cuore editoriale → quasi certamente bespoke: tokenizzare e completare matrice stati)

- [ ] **Step 1-5:** procedura standard CON Regola bespoke esplicita: migrare i controlli funzionali (close, nav, azioni shelf/history → UiIconButton/UiButton ghost), NON toccare l'estetica della horizon line, dello stage e del composer. Ogni elemento lasciato bespoke deve uscire dal task con matrice stati completa (hover/active/focus-visible/disabled via token).
- [ ] **Commit:** `refactor(horizon): adopt UI kit for functional controls, tokenize bespoke elements`

### Task 2.5: Aree `email/`, `calendar/`, `voice/`, `home/`

**Files:**
- Modify: `src/renderer/src/components/email/InboxList.vue` (spinner ~285; chip cartelle; search)
- Modify: `src/renderer/src/components/email/EmailViewer.vue` (icon buttons)
- Modify: `src/renderer/src/components/email/EmailFoldersSidebar.vue` (chip → UiChip)
- Modify: `src/renderer/src/components/calendar/CalendarEventModal.vue` (4 input → UiInput; textarea → UiTextarea; già usa UiSelect)
- Modify: `src/renderer/src/components/voice/MicrophoneButton.vue` (spinner ~367; il bottone microfono in sé è bespoke: tokenizzare stati listening/speaking con i token `--listening/--speaking` già esistenti)
- Modify: `src/renderer/src/components/home/HomeComposer.vue` (textarea; vale la Regola bespoke come HorizonComposer)
- Modify: `src/renderer/src/components/home/HomeIntents.vue` (chip → UiChip)

- [ ] **Step 1-5:** procedura standard.
- [ ] **Commit:** `refactor(email,calendar,voice,home): adopt UI kit`

### Task 2.6: Aree `plugins/`, `services/`, `assistant/`

**Files:**
- Modify: `src/renderer/src/components/plugins/NetworkProbePanel.vue` (11 button, 9 input, spinner ~1214 — insieme alla tokenizzazione dimensionale della Fase 3, Task 3.2)
- Modify: `src/renderer/src/components/plugins/SearchResultsPanel.vue` (spinner ~257)
- Modify: `src/renderer/src/views/ServicesView.vue` (spinner ~387; button)
- Modify: `src/renderer/src/components/services/ServiceCard.vue` (chip stato → UiBadge con `dot`)
- Modify: `src/renderer/src/components/assistant/ImmersiveCADCanvas.vue` (8 button → UiIconButton/UiButton ghost)
- Modify: `src/renderer/src/components/whiteboard/ArtifactPreview3D.vue` (spinner ~207)

- [ ] **Step 1-5:** procedura standard.
- [ ] **Step finale fase 2 — verifica di copertura:**

```powershell
# I numeri devono essere crollati rispetto all'audit (199/56/12):
(Select-String -Path src/renderer/src/components, src/renderer/src/views -Pattern "<button" -Recurse | Where-Object { $_.Path -notmatch "\\ui\\" }).Count
(Select-String -Path src/renderer/src/components, src/renderer/src/views -Pattern "<input" -Recurse | Where-Object { $_.Path -notmatch "\\ui\\" }).Count
(Select-String -Path src/renderer/src/components, src/renderer/src/views -Pattern "@keyframes .*spin" -Recurse | Where-Object { $_.Path -notmatch "\\ui\\" }).Count
```
I residui devono essere SOLO elementi bespoke giustificati (annotarli in un commento del commit).
- [ ] **Commit:** `refactor(plugins,services): adopt UI kit — kit migration complete`

---

## FASE 3 — Tokenizzazione residua

### Task 3.1: Durate e easing di transizione a token

25 durate literal vs 9 a token (adozione ~26% — la peggiore).

- [ ] **Step 1: Censire**

```powershell
Select-String -Path src/renderer/src -Pattern "transition[^;]*\d+m?s" -Recurse | Where-Object { $_.Line -notmatch "var\(--" }
```
- [ ] **Step 2: Mappare** — 50ms→`--duration-instant`, 100-150ms→`--duration-fast`, 200-250ms→`--duration-normal`, 300ms→`--duration-moderate`, 500ms→`--duration-slow`, 700ms+→`--duration-slower`; easing letterali → `--ease-out-quart` (default) o il token `--ease-*` più vicino. NON cambiare i valori percepiti: scegliere il token col valore identico o più vicino.
- [ ] **Step 3: Gate + commit** — `refactor(styles): tokenize transition durations/easings`

### Task 3.2: Dimensioni nei pannelli plugin/services

- [ ] **Step 1:** in `NetworkProbePanel.vue` (22 font-size + 6 radius literal, es. righe 857/872/881: 13px/14px/11px), `SearchResultsPanel.vue` (10+7+3), `ServiceCard.vue` (8 radius), `ServicesView.vue`, `ModelSelector.vue`: sostituire font-size px con il token `--text-*` più vicino (11px→`--text-xs`, 13px→`--text-sm`, 14px→`--text-sm` o `--text-md` a seconda del contesto — confrontare visivamente), radius con `--radius-*`, box-shadow custom con `--shadow-*`.
- [ ] **Step 2: Gate + verifica visiva dei pannelli + commit** — `refactor(plugins,services): tokenize font sizes, radii, shadows`

### Task 3.3: Tokenizzare `code-blocks.css` (tema syntax highlight, 33 hex)

- [ ] **Step 1:** leggere `assets/styles/code-blocks.css` ed estrarre i ruoli sintattici dai selettori (keyword, string, comment, function, number, operator, tag, attribute, variable, punctuation, background, …).
- [ ] **Step 2:** in `theme.css` aggiungere una sezione:
```css
/* ── Code Syntax Tokens ────────────────────────────────────── */
:root {
  --code-fg: #d6d2c8;
  /* … un token --code-<ruolo> per ogni ruolo estratto, con il valore hex
     attuale identico (nessun cambiamento visivo in dark) … */
}
```
e nel blocco `[data-theme='light']` le controparti light (scegliere dalla palette light esistente mantenendo contrasto AA su `--bg-primary` light; verificare visivamente un blocco di codice in chat).
- [ ] **Step 3:** sostituire in `code-blocks.css` ogni hex con il suo `var(--code-*)`.
- [ ] **Step 4: Gate + verifica visiva (blocco codice in dark E light) + commit** — `refactor(styles): tokenize code syntax theme (dual theme)`

### Task 3.4: Bridge runtime per le palette JS (ECharts, xterm)

Le uniche palette hardcoded rimaste sono JS (non leggono CSS var): `ChartViewer.vue` (24 hex + rgba nella config ECharts), `TerminalPageView.vue` + `TerminalModule.vue` (tema xterm). Introdurre un helper che legge i token a runtime e reagisce al cambio tema.

**Files:**
- Create: `src/renderer/src/composables/useThemeTokens.ts`
- Modify: `src/renderer/src/components/chat/ChartViewer.vue`
- Modify: `src/renderer/src/views/TerminalPageView.vue`, `src/renderer/src/components/canvas/modules/TerminalModule.vue`

- [ ] **Step 1: Creare il composable**

```ts
/**
 * useThemeTokens — Legge CSS custom property a runtime per i consumer JS
 * (ECharts, xterm) che non possono usare var(--…) direttamente.
 * Si aggiorna quando cambia `data-theme` su <html>.
 */
import { onBeforeUnmount, ref, type Ref } from 'vue'

export function readToken(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}

export function readTokens<K extends string>(names: readonly K[]): Record<K, string> {
  const style = getComputedStyle(document.documentElement)
  return Object.fromEntries(names.map((n) => [n, style.getPropertyValue(n).trim()])) as Record<
    K,
    string
  >
}

/**
 * Ritorna una mappa reattiva token→valore che si rilegge al cambio tema.
 * Usare i valori dentro un watch per ricostruire la config della libreria.
 */
export function useThemeTokens<K extends string>(names: readonly K[]): Ref<Record<K, string>> {
  const tokens = ref(readTokens(names)) as Ref<Record<K, string>>
  const observer = new MutationObserver(() => {
    tokens.value = readTokens(names)
  })
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  onBeforeUnmount(() => observer.disconnect())
  return tokens
}
```

- [ ] **Step 2: ChartViewer** — sostituire la palette categoriale hardcoded e i colori della config (tooltip bg, axis line, split line) con valori da `useThemeTokens(['--accent', '--success', '--text-secondary', '--surface-2', '--border', …])`; per la palette categoriale derivare dai token esistenti dove c'è corrispondenza e mantenere gli hex senza token corrispondente come costanti locali DOCUMENTATE (una palette dati categoriale legittimamente non mappa 1:1 sui token UI — vedere anche la skill dataviz prima di ridisegnarla). Ricostruire le option ECharts in un `watch` sul ref dei token così il grafico segue il cambio tema.
- [ ] **Step 3: Terminali** — costruire il theme object xterm da token (`--surface-0`, `--text-primary`, `--accent`, colori ANSI: mantenere la palette ANSI GitHub-dark come costante locale documentata se non esistono token ANSI — creare token `--ansi-*` è opzionale, non richiesto).
- [ ] **Step 4: Gate + verifica visiva (chart e terminale in entrambi i temi) + commit** — `feat(frontend): runtime theme token bridge for ECharts/xterm`

---

## FASE 4 — Strutturale

### Task 4.1: Unificare il naming `canvas` → `workspace`

La stessa feature ha tre nomi: `components/canvas/`, `composables/workspace/`, `stores/workspace.ts`.

- [ ] **Step 1:** `git mv src/renderer/src/components/canvas src/renderer/src/components/workspace`
- [ ] **Step 2:** aggiornare tutti gli import (`Select-String -Path src -Pattern "components/canvas" -Recurse`), inclusi eventuali riferimenti in `commands/` e nei test.
- [ ] **Step 3:** gate completo (`typecheck`, `lint`, `vitest run`) + avvio app + commit — `refactor(frontend): rename components/canvas → components/workspace (naming unification)`

### Task 4.2: Ricollocare `ImmersiveCADCanvas` ed eliminare `assistant/`

- [ ] **Step 1:** `git mv src/renderer/src/components/assistant/ImmersiveCADCanvas.vue src/renderer/src/components/workspace/ImmersiveCADCanvas.vue` (è consumato da `HorizonStage.vue` e `workspace/modules/Cad3dModule.vue` — componente condiviso della feature workspace).
- [ ] **Step 2:** aggiornare i 2+ import; rimuovere la cartella `assistant/` ormai vuota.
- [ ] **Step 3:** gate + commit — `refactor(frontend): relocate ImmersiveCADCanvas, drop assistant/ folder`

### Task 4.3 (backlog, piani separati): decomposizione dei file giganti

NON in questo piano — ciascuno merita un piano proprio quando verrà toccato per feature:
- `NetworkProbePanel.vue` (1234 righe) → split script/sotto-componenti
- `MessageBubble.vue` (999) → estrarre versioning/tool sections
- `HorizonView.vue` (680, ~8 watcher) → estrarre `useHorizonScene()` sul modello di `WorkspaceView.vue`
- `TitleBar.vue` (917), `stores/chat.ts` (949)

Registrarli in `docs/ideas.md` o nel backlog di progetto al termine della Fase 4.

---

## Ordine di esecuzione e dipendenze

```
Fase 0 (0.1 → 0.4, indipendenti tra loro)
  └→ Fase 1 (1.1 focus ring PRIMA delle migrazioni; 1.2-1.5 indipendenti tra loro)
       └→ Fase 2 (2.1 → 2.6 in ordine; ogni task è un commit auto-consistente)
            └→ Fase 3 (3.1-3.4 indipendenti tra loro)
                 └→ Fase 4 (4.1 → 4.2; 4.3 backlog)
```

Ogni task termina con l'app funzionante: si può interrompere il programma a fine di qualunque task senza stato intermedio rotto.

## Criteri di completamento del programma

1. `npm run typecheck`, `npm run lint`, `npx vitest run` verdi.
2. Grep di copertura (fine Fase 2) con residui solo bespoke documentati.
3. Focus da tastiera visibile su tutta l'app, in entrambi i temi.
4. Nessun hex/rgba literal nel CSS dell'app fuori da `theme.css` (verifica: `Select-String -Path src/renderer/src -Pattern "#[0-9a-fA-F]{3,6}\b" -Recurse -Include *.vue,*.css` → solo costanti JS documentate di ECharts/xterm).
5. Verifica visiva completa delle superfici (chat, horizon, settings, email, calendar, workspace, servizi, terminale) in dark E light.
