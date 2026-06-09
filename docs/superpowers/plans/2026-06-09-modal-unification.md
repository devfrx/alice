# Modal Overlay Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Remove 5 components' worth of bespoke `Teleport`+overlay modal shells (8 overlays) by routing them through the existing `useModal` system (`composables/useModal.ts` + `components/ModalContainer.vue`).

**Architecture:** Two target shapes. (1) Simple text confirmations → `useModal().confirm({ type: 'danger' })`, deleting the inline overlay entirely. (2) Rich form/content dialogs → extract the inner card into a standalone component that emits `'close'`, rendered via `useModal().openCustom({ component, props, title?, width? })`. The reference implementation is `components/calendar/CalendarEventModal.vue` + its caller `components/plugins/CalendarView.vue`.

**Tech Stack:** Vue 3.5 (`<script setup lang="ts">`), TypeScript, scoped CSS + design tokens, electron-vite.

> **Testing note:** No component-test harness exists (vitest is store-only; no `@vue/test-utils`). Verification gate per task = `npm run typecheck` + `npm run lint` (no NEW errors) from `frontend/`, plus the described manual smoke. Run all `npm` from `frontend/`.

> **Scoped OUT (decided with user):** `components/chat/ToolConfirmationDialog.vue` is intentionally NOT migrated. It carries a 3-value `respond(executionId, approved, remember)` emit, a 60s auto-reject countdown, and is mounted from two parents at once — the `useModal` singleton cannot host it without losing the remember-choice/countdown or risking the critical tool-confirmation path. It remains a standalone Teleport dialog.

---

## The established pattern (reference: CalendarEventModal + CalendarView)

**Content component** (`CalendarEventModal.vue`):
```ts
const props = defineProps<{ /* data forwarded by openCustom */ }>()
const emit = defineEmits<{ close: [result: boolean] }>()
// ... does its own store/API work, then:
emit('close', true)   // success
emit('close', false)  // cancel
```
Its root element is the dialog **card** (NOT an overlay — `ModalContainer` supplies the overlay, focus trap, scroll lock, Escape/Enter, and centering). It does NOT import `Teleport` and does NOT render a fixed-position backdrop.

**Caller** (`CalendarView.vue`):
```ts
import { useModal } from '../../composables/useModal'
const { openCustom } = useModal()
const saved = await openCustom({
  component: CalendarEventModal,
  props: { editingEvent, initialForm },
  title: '…',
  width: '480px',
})
if (saved) await fetchEvents()
```
`ModalContainer` wires `@close="close"` onto the custom component, so `emit('close', result)` resolves the `openCustom` promise.

**Escape/Enter:** `ModalContainer` already handles Escape (→ `close(false)`) and Enter globally. Extracted components MUST remove their own `window`/overlay keydown listeners for Escape to avoid double handling. Keep only special keys that ModalContainer doesn't own (e.g. Ctrl/Cmd+Enter to submit).

---

## Task 1: MemoryManager internal confirm → `useModal().confirm`

**Files:** Modify `frontend/src/renderer/src/components/settings/MemoryManager.vue`

The component has an inline confirm overlay driven by `confirmAction = ref<(() => Promise<void>) | null>(null)` + `confirmMessage` (around lines 153, 105). Three openers: `confirmDelete(entry)`, `confirmClearSession()`, `confirmClearAll()`; closers `cancelConfirm()` / `executeConfirm()`.

- [ ] **Step 1:** Add import + composable.
```ts
import { useModal } from '../../composables/useModal'
// in setup:
const { confirm } = useModal()
```

- [ ] **Step 2:** Replace each of the three openers so they `await confirm(...)` and run the action directly, removing the deferred-action ref pattern. Example for delete (replicate the existing message text for each):
```ts
async function confirmDelete(entry: /* existing type */): Promise<void> {
    const ok = await confirm({
        title: 'Elimina memoria',
        message: `…existing confirmMessage text for this entry…`,
        type: 'danger',
        confirmText: 'Elimina',
    })
    if (!ok) return
    await store.deleteMemory(entry.id)   // keep the exact existing action + any store.loadStats() follow-up
}
```
Apply the same shape to `confirmClearSession` (action `store.clearSessionMemory` + follow-ups) and `confirmClearAll` (action `store.clearAllMemory` + follow-ups). Preserve the EXACT messages and the EXACT store calls/follow-ups currently in `executeConfirm`.

- [ ] **Step 3:** Delete the now-dead pieces: the `confirmAction` + `confirmMessage` refs, `cancelConfirm`, `executeConfirm`, the `v-if="confirmAction"` Teleport/overlay block in the template, and the `.mem-confirm-overlay` / `.mem-confirm` CSS (around lines 554-586).

- [ ] **Step 4:** `npm run typecheck && npm run lint`. Smoke: Settings → Memory; trigger delete / clear-session / clear-all → custom danger modal; Cancel aborts, Confirm runs the action and refreshes stats.

- [ ] **Step 5:** Commit `refactor(settings): MemoryManager confirms via useModal`.

---

## Task 2: KnowledgeGraphManager delete-confirm → `useModal().confirm`

**Files:** Modify `frontend/src/renderer/src/components/settings/KnowledgeGraphManager.vue`

Same inline `confirmAction`/`confirmMessage` pattern (around lines 293-294, overlay "D"). Openers: `confirmDeleteEntity(name)`, `confirmDeleteObservation(entityName, obs)`, `confirmDeleteRelation(rel)`.

- [ ] **Step 1:** Add `useModal` import + `const { confirm } = useModal()`.

- [ ] **Step 2:** Convert the three delete openers to `await confirm({ type: 'danger', message: <existing text>, confirmText: 'Elimina' })` then run the exact existing store action (`store.deleteEntities` / `store.deleteObservations` / `store.deleteRelations` — use whatever the current `executeConfirm` calls). Preserve messages and follow-up reloads.

- [ ] **Step 3:** Delete the delete-confirm `confirmAction`/`confirmMessage` refs, `cancelConfirm`/`executeConfirm`, and the confirm `v-if` Teleport block. Do NOT yet delete the shared `.kg-overlay`/`.kg-dialog` CSS — overlays A/B/C still use it until Tasks 5-7; the final cleanup happens in Task 7.

- [ ] **Step 4:** `npm run typecheck && npm run lint`. Smoke: Settings → Knowledge graph; delete an entity/observation/relation → danger modal works.

- [ ] **Step 5:** Commit `refactor(settings): KnowledgeGraphManager delete-confirm via useModal`.

---

## Task 3: TrellisSetupGuideModal → `openCustom`

**Files:** Modify `frontend/src/renderer/src/components/services/TrellisSetupGuideModal.vue` and its only caller `frontend/src/renderer/src/views/ServicesView.vue`.

Current: parent `v-if="showGuide"` renders the component, which owns the `.guide-modal` fixed overlay and a `window` keydown→`emit('close')`. Props `{ service }`, emit `close()` (void).

- [ ] **Step 1 (component):** Make it openCustom content:
  - Root element becomes the guide **panel/card** (`.guide-modal__panel`); remove the outer `.guide-modal` fixed-overlay wrapper.
  - Change emit to `defineEmits<{ close: [result: boolean] }>()`; the close button emits `emit('close', false)`.
  - Remove the component's own `window.addEventListener('keydown', …)` Escape handler and its `onBeforeUnmount` removal (ModalContainer owns Escape). Keep the `onMounted` `store.loadTrellisGuide(service)` call.
  - Delete `.guide-modal` overlay CSS; keep the panel/content CSS (it's now the root).

- [ ] **Step 2 (caller ServicesView):** Replace the template usage (around line 263) and the `showGuide` ref flow with an imperative open:
```ts
import { useModal } from '../composables/useModal'
import TrellisSetupGuideModal from '../components/services/TrellisSetupGuideModal.vue'
const { openCustom } = useModal()
async function openGuide(svc: TrellisGuideService): Promise<void> {
    await openCustom({ component: TrellisSetupGuideModal, props: { service: svc }, width: '720px' })
}
```
Point the existing trigger (was `guideService.value = svc; showGuide.value = true`) at `openGuide(svc)`. Remove the `showGuide` ref and the `<TrellisSetupGuideModal v-if=… />` from the template.

- [ ] **Step 3:** `npm run typecheck && npm run lint`. Smoke: Services → open a Trellis setup guide → modal opens centered, markdown loads, Escape and the close button both dismiss.

- [ ] **Step 4:** Commit `refactor(services): TrellisSetupGuideModal via useModal.openCustom`.

---

## Task 4: MessageEditDialog → `openCustom` (callback-prop for the edited string)

**Files:** Modify `frontend/src/renderer/src/components/chat/MessageEditDialog.vue` and BOTH callers: `frontend/src/renderer/src/views/AssistantView.vue` and `frontend/src/renderer/src/components/canvas/ChatPanel.vue`.

Current: parent `v-if="editingMessageId"`; props `{ originalContent }`; emits `submit(content)` / `cancel()`. The string payload cannot ride `openCustom`'s boolean resolve, so pass an `onSubmit` callback prop; the component performs submit then emits `close`.

- [ ] **Step 1 (component):** New contract:
```ts
const props = defineProps<{
    originalContent: string
    onSubmit: (content: string) => void | Promise<void>
}>()
const emit = defineEmits<{ close: [result: boolean] }>()
// handleSubmit: await props.onSubmit(text); emit('close', true)
// cancel: emit('close', false)
```
  - Root becomes the `.edit-dialog` card; remove `<Teleport>` and the `.edit-overlay` fixed wrapper + its `@keyframes` overlay/card animations (ModalContainer animates).
  - Keep the textarea auto-focus-at-end (`onMounted`) and auto-resize.
  - Keep Ctrl/Cmd+Enter → submit. REMOVE the component's own Escape handling (ModalContainer owns it); Escape will resolve `close(false)`.

- [ ] **Step 2 (each caller):** Replace `startEdit`/`submitEdit`/`cancelEdit` + the `v-if` template usage with an imperative open that supplies the existing edit API call as the callback:
```ts
import { useModal } from '<correct relative path>/composables/useModal'
import MessageEditDialog from '<correct relative path>/chat/MessageEditDialog.vue'
const { openCustom } = useModal()
async function startEdit(messageId: string, content: string): Promise<void> {
    await openCustom({
        component: MessageEditDialog,
        props: {
            originalContent: content,
            onSubmit: async (newContent: string) => {
                await chatApi.editMessage(messageId, newContent)  // EXACT existing submit logic from submitEdit
            },
        },
        title: 'Modifica messaggio',
        width: '560px',
    })
}
```
Remove the `editingMessageId` / `editingContent` refs, the old `submitEdit`/`cancelEdit`, and the `<MessageEditDialog v-if=… />` block in each caller. Wire the existing edit trigger to the new `startEdit(messageId, content)`. **Replicate the exact existing submit side-effects** (whatever `submitEdit` did — API call, store update, scroll, etc.) inside the `onSubmit` callback.

- [ ] **Step 3:** `npm run typecheck && npm run lint`. Smoke: in BOTH AssistantView and the canvas ChatPanel — edit a message → modal opens, textarea focused; Ctrl+Enter submits and the edit persists; Cancel and Escape both dismiss without editing.

- [ ] **Step 4:** Commit `refactor(chat): MessageEditDialog via useModal.openCustom`.

---

## Task 5: Extract `KgCreateEntityDialog` → `openCustom`

**Files:** Create `frontend/src/renderer/src/components/settings/KgCreateEntityDialog.vue`; modify `frontend/src/renderer/src/components/settings/KnowledgeGraphManager.vue`.

Overlay "A": `showCreateEntity` ref; form (Name, Type, Observations textarea); submit `onCreate()` → `store.createEntities(...)`.

- [ ] **Step 1 (new component):** Move the form markup (the inner `.kg-dialog` card content of overlay A) into a new component whose root is the card. Contract:
```ts
const emit = defineEmits<{ close: [result: boolean] }>()
const store = useKnowledgeGraphStore()   // use the actual store import used in KnowledgeGraphManager
// local form refs (name, type, observations)
// onCreate: await store.createEntities(...); emit('close', true)
// cancel button: emit('close', false)
```
Move the relevant `.kg-field`/`.kg-input`/`.kg-textarea` styles needed by this form into the new component's scoped CSS (copy, don't share). Do NOT include any `.kg-overlay`/`.kg-dialog` wrapper — the card is the root.

- [ ] **Step 2 (KnowledgeGraphManager):** Replace the `showCreateEntity = true` trigger with:
```ts
const result = await openCustom({ component: KgCreateEntityDialog, title: 'Nuova entità', width: '480px' })
if (result) await store.loadGraph()   // use the EXACT post-create refresh the component currently does
```
Remove the `showCreateEntity` ref, `onCreate`, the entity-form local refs, and the overlay-A `v-if` Teleport block from KnowledgeGraphManager. (`openCustom` already imported in Task 2 — if not, add it.)

- [ ] **Step 3:** `npm run typecheck && npm run lint`. Smoke: Knowledge graph → "New entity" → form modal; create works and the graph refreshes; Cancel/Escape dismiss.

- [ ] **Step 4:** Commit `refactor(settings): extract KgCreateEntityDialog via openCustom`.

---

## Task 6: Extract `KgCreateRelationDialog` → `openCustom`

**Files:** Create `frontend/src/renderer/src/components/settings/KgCreateRelationDialog.vue`; modify `KnowledgeGraphManager.vue`.

Overlay "B": `showCreateRelation` ref; form (From `UiSelect`, Relation Type input, To `UiSelect`); submit → `store.createRelations(...)`. The selects need entity options — pass them as a prop.

- [ ] **Step 1 (new component):** Root = card. Props: the entity option list the selects need (e.g. `entities: UiSelectOption[]` — match the shape the current overlay builds). Emit `close: [result: boolean]`. Import `UiSelect`. `onCreateRelation`: `await store.createRelations(...)`; `emit('close', true)`; cancel → `emit('close', false)`. Copy needed `.kg-field`/etc. styles.

- [ ] **Step 2 (KnowledgeGraphManager):** Trigger becomes:
```ts
const result = await openCustom({
    component: KgCreateRelationDialog,
    props: { entities: /* the same options the inline overlay used */ },
    title: 'Nuova relazione', width: '480px',
})
if (result) await store.loadGraph()
```
Remove the `showCreateRelation` ref, `onCreateRelation`, relation-form refs, and overlay-B Teleport block.

- [ ] **Step 3:** `npm run typecheck && npm run lint`. Smoke: "New relation" → selects populated, create works, graph refreshes; Cancel/Escape dismiss.

- [ ] **Step 4:** Commit `refactor(settings): extract KgCreateRelationDialog via openCustom`.

---

## Task 7: Extract `KgAddObservationDialog` → `openCustom` + final KG CSS cleanup

**Files:** Create `frontend/src/renderer/src/components/settings/KgAddObservationDialog.vue`; modify `KnowledgeGraphManager.vue`.

Overlay "C": `showAddObservation` ref + `observationTarget` + `newObservationText`; opened by `openAddObservation(entityName)` (from an EntityCard `@add-observation`); submit → `store.addObservations(target, contents)`.

- [ ] **Step 1 (new component):** Root = card. Props: `entityName: string`. Emit `close: [result: boolean]`. Local `text` ref (one observation per line). `onAdd`: parse lines, `await store.addObservations(entityName, contents)`, `emit('close', true)`; cancel → `emit('close', false)`. Copy needed styles.

- [ ] **Step 2 (KnowledgeGraphManager):** `openAddObservation` becomes:
```ts
async function openAddObservation(entityName: string): Promise<void> {
    const result = await openCustom({
        component: KgAddObservationDialog,
        props: { entityName },
        title: `Aggiungi osservazione · ${entityName}`, width: '480px',
    })
    if (result) await store.loadGraph()
}
```
Remove `showAddObservation`, `observationTarget`, `newObservationText`, `onAddObservation`, and overlay-C Teleport block.

- [ ] **Step 3 (CSS cleanup):** Now that overlays A-D are all gone, delete the shared `.kg-overlay`, `.kg-dialog`, `.kg-dialog__title`, `.kg-dialog__message`, `.kg-dialog__actions` rules (around lines 638-656) and any now-orphaned `.kg-field`/`.kg-input`/`.kg-textarea` rules no longer referenced anywhere in KnowledgeGraphManager. Run `grep -n "kg-overlay\|kg-dialog\|kg-field\|kg-input\|kg-textarea" frontend/src/renderer/src/components/settings/KnowledgeGraphManager.vue` and remove rules with no remaining template usage.

- [ ] **Step 4:** `npm run typecheck && npm run lint`. Smoke: Add-observation flow works; verify the other KG dialogs (entity/relation/delete) still look/behave correctly after CSS cleanup.

- [ ] **Step 5:** Commit `refactor(settings): extract KgAddObservationDialog + drop shared KG overlay CSS`.

---

## Task 8: Extract `ModelLoadDialog` → `openCustom`

**Files:** Create `frontend/src/renderer/src/components/settings/ModelLoadDialog.vue`; modify `frontend/src/renderer/src/components/settings/ModelManager.vue`.

Load-config dialog: `showLoadDialog` + `loadDialogModel`; controls = context-length slider, VRAM estimate, Flash-Attention `UiCheckbox` (added in Phase 1), Cancel/Load. `confirmLoad()` → `settingsStore.loadModel(name, config)`; error currently shown in a banner OUTSIDE the dialog → must move INSIDE the extracted component.

- [ ] **Step 1 (new component):** Props: `model: LMStudioModel` (the non-null `loadDialogModel`). Emit `close: [result: boolean]`. Move into it: the slider + `estimatedVram` computed + range derived from the model, the `UiCheckbox` for `loadFlashAttention`, and a LOCAL `errorMessage` ref shown inside the card. `confirmLoad`: `try { await settingsStore.loadModel(model.name, config); emit('close', true) } catch (e) { errorMessage.value = … }`. Cancel → `emit('close', false)`. Remove the component's own `window` Escape listener logic. Copy the `.mm-dialog*` control styles into this component; do NOT bring the `.mm-overlay` or `.dialog-enter/leave` transition classes (ModalContainer supplies overlay + transition).

- [ ] **Step 2 (ModelManager):** `openLoadDialog(model)` becomes:
```ts
async function openLoadDialog(model: LMStudioModel): Promise<void> {
    await openCustom({ component: ModelLoadDialog, props: { model }, title: `Carica · ${model.name}`, width: '480px' })
}
```
Remove `showLoadDialog`, `loadDialogModel`, `closeLoadDialog`, `confirmLoad`, `onDialogKeydown` + its watch/`onBeforeUnmount`, the dialog `v-if` Teleport block, and the now-dead `.mm-overlay`/`.mm-dialog*`/`.dialog-enter*`/`.dialog-leave*` CSS. Keep `loadFlashAttention` only if still referenced elsewhere; otherwise move it into the new component. Keep the outside error banner ONLY if it's used by non-dialog flows; if it was solely for load errors, remove it (errors now live inside the dialog).

- [ ] **Step 3:** `npm run typecheck && npm run lint`. Smoke: Settings → Models → Load on a model → modal with slider/VRAM/Flash-Attention; a failed load shows the error inside the modal; success closes it; Cancel/Escape dismiss.

- [ ] **Step 4:** Commit `refactor(settings): extract ModelLoadDialog via openCustom`.

---

## Task 9: Final verification sweep

**Files:** none.

- [ ] **Step 1:** Confirm no bespoke modal overlays remain in the migrated files:
```
grep -rn "guide-modal\|edit-overlay\|mem-confirm\|kg-overlay\|mm-overlay" frontend/src/renderer/src
```
Expected: no matches (ToolConfirmationDialog's `.confirm-overlay` is intentionally still present and is fine).

- [ ] **Step 2:** Confirm `Teleport` now appears in the migrated files ONLY where intended. Run:
```
grep -rln "Teleport to=\"body\"" frontend/src/renderer/src
```
Expected remaining: `ModalContainer.vue`, `ToolConfirmationDialog.vue` (scoped out), and any unrelated pre-existing ones (e.g. UiPopover/UiContextMenu/UiToast/voice overlays) — but NOT TrellisSetupGuideModal, MessageEditDialog, MemoryManager, KnowledgeGraphManager, ModelManager.

- [ ] **Step 3:** `npm run typecheck && npm run lint` (no new errors vs. baseline).

- [ ] **Step 4:** Commit any sweep fixes: `chore(settings): finalize modal unification`.

---

## Self-Review notes

- **Coverage:** 8 in-scope overlays → Tasks 1-8; ToolConfirmationDialog explicitly scoped out (documented). Reference pattern captured up top.
- **Ordering:** low-risk confirm swaps first (1-2), then self-contained openCustom extractions (3,5,6,7,8), with the dual-parent MessageEditDialog (4) handled carefully; KG shared CSS deleted only after all KG overlays are gone (Task 7).
- **Highest-risk task is 4** (two callers, string return via callback prop) — smoke BOTH AssistantView and ChatPanel.
- **Watch items for implementers:** (a) get relative import paths right per caller location; (b) replicate EXACT existing store/API side-effects and post-action refreshes inside the new components/callbacks; (c) remove each component's own Escape listener (ModalContainer owns it) but KEEP Ctrl/Cmd+Enter submit; (d) don't delete shared KG CSS until Task 7.
