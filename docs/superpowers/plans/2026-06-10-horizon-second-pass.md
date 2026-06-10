# Horizon Second Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the five reported Horizon problems — unreachable modules, off-style dossier, single-line composer, missing input-bar parity, illegible line states/tasks — reusing existing components and logic.

**Architecture:** A persistent `HorizonShelf` of mono medallions below the line summons the stage (artifacts) and pins the plan; the composer gains auto-grow + a `HorizonCockpit` rail that mounts the existing chat controls; attachment logic is extracted from `ChatInput.vue` into `useChatAttachments`; `HorizonHistory` adopts the app's floating-card shell; `HorizonLine` gains a state microlabel, any-mode notches and tuned motion signatures. `deriveSceneState`/`deriveLineMode` stay untouched.

**Tech Stack:** Vue 3 `<script setup lang="ts">`, Pinia, canvas 2D, vitest (pure `.ts` modules only — NEVER import `.vue` in specs). Frontend dir: `frontend/`; commands run from there. `HorizonScene.vue`/`HorizonColophon.vue` have uncommitted user edits — do not revert them; build on the working tree.

**Spec:** `docs/superpowers/specs/2026-06-10-horizon-second-pass-design.md`. Deviation from spec §3.5 noted: in `presenting` the line mode is `breathe` (per `deriveLineMode`), so the "quasi piatta" look comes from a new `attenuated` prop, not from the `flow` mode. The "alone oro" of the active tick stays monochrome on canvas (`--hz-line-rgb` only); the gold accent lives in the DOM label (Task 8).

---

### Task 1: `artifactLabel` (TDD)

**Files:**
- Modify: `frontend/src/renderer/src/composables/horizon/horizonArtifacts.ts`
- Test: `frontend/src/renderer/src/composables/horizon/horizonArtifacts.spec.ts` (append)

- [ ] **Step 1: Failing test** — append to the existing spec file:

```ts
describe('artifactLabel', () => {
  it('maps each kind to its editorial caption', () => {
    expect(artifactLabel('3d')).toBe('MODELLO')
    expect(artifactLabel('chart')).toBe('GRAFICO')
    expect(artifactLabel('whiteboard')).toBe('LAVAGNA')
  })
})
```

(add `artifactLabel` to the existing import from `./horizonArtifacts`)

- [ ] **Step 2: Run** `npx vitest run src/renderer/src/composables/horizon/horizonArtifacts.spec.ts` → FAIL (no export).

- [ ] **Step 3: Implement** — in `horizonArtifacts.ts` after `HorizonArtifact`:

```ts
/** Mono shelf caption per artifact kind (editorial Italian). */
export function artifactLabel(kind: HorizonArtifactKind): string {
  switch (kind) {
    case '3d':
      return 'MODELLO'
    case 'chart':
      return 'GRAFICO'
    case 'whiteboard':
      return 'LAVAGNA'
  }
}
```

- [ ] **Step 4: Run** same command → PASS.
- [ ] **Step 5: Commit** `git add` the two files; `git commit -m "feat(horizon): artifactLabel caption helper"`

---

### Task 2: `HorizonShelf` + view wiring + rising stage

**Files:**
- Create: `frontend/src/renderer/src/components/horizon/HorizonShelf.vue`
- Modify: `frontend/src/renderer/src/views/HorizonView.vue`

- [ ] **Step 1: Create `HorizonShelf.vue`:**

```vue
<script setup lang="ts">
/**
 * HorizonShelf — the modules living just below the line: one mono medallion
 * per artifact (I · GRAFICO …) plus PIANO n/m when a plan exists. A
 * persistent presence, not a menu: click summons the stage / pins the plan.
 * While the stage is open the shelf doubles as its index (active = gold).
 */
import {
  artifactLabel,
  type HorizonArtifact
} from '../../composables/horizon/horizonArtifacts'
import { toRoman } from '../../composables/horizon/horizonScene'

withDefaults(
  defineProps<{
    artifacts: HorizonArtifact[]
    planTotal?: number
    planCompleted?: number
    /** Artifact shown on the open stage (gold); null = stage closed. */
    activeArtifactIndex?: number | null
    planPinned?: boolean
  }>(),
  { planTotal: 0, planCompleted: 0, activeArtifactIndex: null, planPinned: false }
)

const emit = defineEmits<{
  'open-artifact': [index: number]
  'toggle-plan': []
}>()
</script>

<template>
  <div v-if="artifacts.length > 0 || planTotal > 0" class="hz-shelf" aria-label="Moduli">
    <button
      v-for="(a, i) in artifacts"
      :key="i"
      class="hz-shelf__item"
      :class="{ 'hz-shelf__item--active': i === activeArtifactIndex }"
      :title="`Apri ${artifactLabel(a.kind).toLowerCase()}`"
      @click="emit('open-artifact', i)"
    >
      {{ toRoman(i + 1) }} · {{ artifactLabel(a.kind) }}
    </button>
    <button
      v-if="planTotal > 0"
      class="hz-shelf__item"
      :class="{ 'hz-shelf__item--active': planPinned }"
      title="Mostra il piano"
      @click="emit('toggle-plan')"
    >
      PIANO {{ planCompleted }}/{{ planTotal }}
    </button>
  </div>
</template>

<style scoped>
.hz-shelf {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
  animation: hz-shelf-breathe var(--hz-breath) ease-in-out infinite;
}

.hz-shelf__item {
  border: none;
  background: transparent;
  padding: 0;
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.25em;
  color: var(--hz-ink-faint);
  cursor: pointer;
  transition: color var(--hz-fade) ease;
}

.hz-shelf__item:hover {
  color: var(--hz-ink);
}

.hz-shelf__item--active {
  color: var(--hz-gold);
}

@keyframes hz-shelf-breathe {
  0%,
  100% {
    opacity: 0.85;
  }
  50% {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .hz-shelf {
    animation: none;
  }
}
</style>
```

- [ ] **Step 2: Wire into `HorizonView.vue`:**

Script additions:
- `import HorizonShelf from '../components/horizon/HorizonShelf.vue'`
- local state: `const planPinned = ref(false)` (under ANCHOR: local-state)
- interactions (under ANCHOR: interactions):

```ts
/** Shelf medallion → summon the stage on that artifact. */
function openArtifact(i: number): void {
  stageIndex.value = i
  stageOpen.value = true
}
```

- Esc chain in `onGlobalKeydown`: insert between the `historyOpen` branch and the final composer collapse:

```ts
    else if (planPinned.value) planPinned.value = false
```

- conversation-switch watch: add `planPinned.value = false` next to the existing resets.

Template changes (lower zone, ANCHOR: lower-zone):
- FIRST element of `#lower`, before `HorizonStage`:

```vue
        <HorizonShelf
          :artifacts="artifacts"
          :plan-total="planSteps.length"
          :plan-completed="plan.completed"
          :active-artifact-index="sceneState === 'presenting' ? stageIndex : null"
          :plan-pinned="planPinned"
          @open-artifact="openArtifact"
          @toggle-plan="planPinned = !planPinned"
        />
```

- Wrap `HorizonStage` in the rising transition:

```vue
        <Transition name="hz-rise">
          <HorizonStage
            v-if="sceneState === 'presenting'"
            v-model:active-index="stageIndex"
            :artifacts="artifacts"
            :cad-generation="cadGenerationInProgress"
            @close="stageOpen = false"
          />
        </Transition>
```

- `HorizonPlan` condition: `v-if="(sceneState === 'working' || planPinned) && planSteps.length > 0"`
- `HorizonLine` notch binding: `:notch-count="sceneState === 'working' || planPinned ? planSteps.length : 0"`

Style additions (view `<style scoped>`):

```css
.hz-rise-enter-active,
.hz-rise-leave-active {
  transition:
    transform var(--hz-morph) var(--ease-out-expo),
    opacity var(--hz-morph) ease;
}

.hz-rise-enter-from,
.hz-rise-leave-to {
  transform: translateY(48px);
  opacity: 0;
}
```

- [ ] **Step 3: Verify** `npm run typecheck` clean.
- [ ] **Step 4: Commit** `git commit -m "feat(horizon): shelf medallions summon stage and pin plan; stage rises from below the line"`

---

### Task 3: `HorizonLine` — microlabel, any-mode notches, attenuation, signatures

**Files:**
- Modify: `frontend/src/renderer/src/components/horizon/HorizonLine.vue`
- Modify: `frontend/src/renderer/src/views/HorizonView.vue`

- [ ] **Step 1: Props** — extend the props block:

```ts
    /** State microlabel at the line's right end ('' = hidden). */
    label?: string
    /** Flatten + fade the line (stage presenting). */
    attenuated?: boolean
    /** Notches drawn as completed (first N). */
    completedCount?: number
```

with defaults `label: '', attenuated: false, completedCount: 0`.

- [ ] **Step 2: Draw changes** in `draw()`:

a. Alpha: `const alpha = (props.dimmed ? 0.35 : 1) * (props.attenuated ? 0.55 : 1)`

b. breathe amplitude attenuates: `y = cy + Math.sin(t * 0.7 + f * Math.PI) * (props.attenuated ? 0.5 : 1.5) * env`

c. tense — stronger and biased upward (crest lifts):

```ts
        y =
          cy +
          env *
            levelSmooth *
            28 *
            (Math.sin(f * 26 + t * 9) * 0.6 + Math.sin(f * 53 - t * 13) * 0.4) -
          env * levelSmooth * 8
```

d. pulse — replace the twin from-center packets with one left→right crest plus two trailing echoes:

```ts
  if (props.mode === 'pulse' && !reducedMotion) {
    const phase = (t * 0.45) % 1
    const x = margin + phase * span
    ctx.save()
    ctx.fillStyle = `rgba(${lineRgb}, 0.95)`
    ctx.shadowColor = `rgba(${lineRgb}, 0.8)`
    ctx.shadowBlur = 10
    for (let e = 0; e < 3; e++) {
      const ex = x - e * 14
      if (ex < margin) continue
      ctx.globalAlpha = alpha * (0.8 - e * 0.28)
      ctx.fillRect(ex - 1.5, cy - 1.1, 3, 2.2)
    }
    ctx.restore()
  }
```

e. timeline/notches — draw whenever `notchCount > 0` (any mode); three visual states; spark only in timeline mode:

```ts
  if (props.notchCount > 0) {
    const fractions = notchPositions(props.notchCount)
    const offMode = props.mode !== 'timeline'
    ctx.save()
    ctx.globalAlpha = alpha * (offMode ? 0.5 : 1)
    fractions.forEach((p, i) => {
      const x = margin + p * span
      const active = i === props.activeIndex
      const done = !active && i < props.completedCount
      const a = active ? 1 : done ? 0.9 : 0.25
      const h = active ? 9 : done ? 8 : 5
      ctx!.strokeStyle = `rgba(${lineRgb}, ${a})`
      ctx!.lineWidth = active ? 1.4 : 1
      ctx!.beginPath()
      ctx!.moveTo(x, cy - h)
      ctx!.lineTo(x, cy + h)
      ctx!.stroke()
    })
    if (props.mode === 'timeline') {
      const clamped = Math.max(0, Math.min(props.activeIndex, fractions.length - 1))
      const target = fractions[clamped] ?? 0.5
      if (lastMode !== 'timeline') sparkX = target
      sparkX += (target - sparkX) * (reducedMotion ? 1 : 0.06)
      const sx = margin + sparkX * span
      const breathe = reducedMotion ? 1 : 0.75 + Math.sin(t * 3) * 0.25
      const g = ctx.createRadialGradient(sx, cy, 0, sx, cy, 11)
      g.addColorStop(0, `rgba(${lineRgb}, ${0.95 * breathe})`)
      g.addColorStop(1, `rgba(${lineRgb}, 0)`)
      ctx.fillStyle = g
      ctx.fillRect(sx - 11, cy - 11, 22, 22)
    }
    ctx.restore()
  }
```

(this REPLACES the existing `if (props.mode === 'timeline' && props.notchCount > 0)` block; `lastMode` bookkeeping stays at the end of `draw`). Update the reduced-motion watch array to include `props.label, props.attenuated, props.completedCount`.

- [ ] **Step 3: Microlabel** — template + CSS:

```vue
<template>
  <div class="hz-line" aria-hidden="true">
    <canvas ref="canvasRef" class="hz-line__canvas" />
    <Transition name="hz-line-fade">
      <span v-if="label" :key="label" class="hz-line__label">{{ label }}</span>
    </Transition>
  </div>
</template>
```

```css
.hz-line__label {
  position: absolute;
  right: 6%;
  bottom: calc(50% + 10px);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.3em;
  color: var(--hz-ink-faint);
  user-select: none;
}

.hz-line-fade-enter-active,
.hz-line-fade-leave-active {
  transition: opacity var(--hz-fade) ease;
}

.hz-line-fade-enter-from,
.hz-line-fade-leave-to {
  opacity: 0;
}
```

- [ ] **Step 4: View wiring** — in `HorizonView.vue` derived section:

```ts
/** Mono state microlabel at the line's right end (quiet stays mute). */
const lineLabel = computed(() => {
  if (voiceStore.isListening) return 'ASCOLTO'
  if (voiceStore.isProcessing) return 'ELABORO'
  if (sceneState.value === 'working')
    return planSteps.value.length > 0
      ? `LAVORO ${plan.value.activeIndex + 1} DI ${plan.value.total}`
      : 'LAVORO'
  if (sceneState.value === 'responding') return 'RISPONDO'
  if (sceneState.value === 'presenting') return 'OPERE'
  return ''
})
```

and bind on `HorizonLine`:

```vue
          :label="lineLabel"
          :attenuated="sceneState === 'presenting'"
          :completed-count="plan.completed"
```

- [ ] **Step 5: Verify** `npm run typecheck`; manual: line visibly different across listening/responding/working.
- [ ] **Step 6: Commit** `git commit -m "feat(horizon): line state microlabel, three-state notches in any mode, tuned motion signatures"`

---

### Task 4: extract `useChatAttachments`; refactor `ChatInput.vue`

**Files:**
- Create: `frontend/src/renderer/src/composables/useChatAttachments.ts`
- Modify: `frontend/src/renderer/src/components/chat/ChatInput.vue`

- [ ] **Step 1: Create the composable** (logic moved VERBATIM from ChatInput — see its current lines 89–99 and 167–258):

```ts
/**
 * useChatAttachments — pending image attachments for a chat composer:
 * file-picker handling, drag&drop, clipboard paste, blob-URL thumbnails and
 * cleanup. Extracted from ChatInput.vue so the Horizon cockpit reuses the
 * exact same behaviour.
 */
import { onBeforeUnmount, ref, type Ref } from 'vue'

export interface ChatAttachmentsApi {
  pendingFiles: Ref<File[]>
  isDragOver: Ref<boolean>
  addFiles: (files: File[]) => void
  removeFile: (file: File) => void
  clearAllFiles: () => void
  getThumbnail: (file: File) => string
  handleFileSelect: (event: Event) => void
  handleDragEnter: (event: DragEvent) => void
  handleDragOver: (event: DragEvent) => void
  handleDragLeave: () => void
  handleDrop: (event: DragEvent) => void
  handlePaste: (event: ClipboardEvent) => void
}

/**
 * @param options.accept Gate for accepting image files (e.g. active model
 *   supports vision). Evaluated at add time.
 */
export function useChatAttachments(options: { accept: () => boolean }): ChatAttachmentsApi {
  const pendingFiles = ref<File[]>([])
  const isDragOver = ref(false)
  const dragCounter = ref(0)
  const thumbnailUrls = ref<Map<File, string>>(new Map())

  function addFiles(files: File[]): void {
    const imageFiles = files.filter((f) => f.type.startsWith('image/'))
    if (!options.accept() && imageFiles.length > 0) return
    for (const file of imageFiles) {
      pendingFiles.value.push(file)
      const url = URL.createObjectURL(file)
      thumbnailUrls.value.set(file, url)
    }
  }

  function removeFile(file: File): void {
    const url = thumbnailUrls.value.get(file)
    if (url) URL.revokeObjectURL(url)
    thumbnailUrls.value.delete(file)
    pendingFiles.value = pendingFiles.value.filter((f) => f !== file)
  }

  function clearAllFiles(): void {
    for (const url of thumbnailUrls.value.values()) {
      URL.revokeObjectURL(url)
    }
    thumbnailUrls.value.clear()
    pendingFiles.value = []
  }

  function getThumbnail(file: File): string {
    return thumbnailUrls.value.get(file) ?? ''
  }

  function handleFileSelect(event: Event): void {
    const input = event.target as HTMLInputElement
    if (input.files) {
      addFiles(Array.from(input.files))
    }
    input.value = ''
  }

  function handleDragEnter(event: DragEvent): void {
    event.preventDefault()
    dragCounter.value++
    isDragOver.value = true
  }

  function handleDragOver(event: DragEvent): void {
    event.preventDefault()
  }

  function handleDragLeave(): void {
    dragCounter.value--
    if (dragCounter.value === 0) isDragOver.value = false
  }

  function handleDrop(event: DragEvent): void {
    event.preventDefault()
    dragCounter.value = 0
    isDragOver.value = false
    if (event.dataTransfer?.files) {
      addFiles(Array.from(event.dataTransfer.files))
    }
  }

  function handlePaste(event: ClipboardEvent): void {
    const items = event.clipboardData?.items
    if (!items) return
    const imageFiles: File[] = []
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile()
        if (file) imageFiles.push(file)
      }
    }
    if (imageFiles.length > 0) {
      event.preventDefault()
      addFiles(imageFiles)
    }
  }

  onBeforeUnmount(() => clearAllFiles())

  return {
    pendingFiles,
    isDragOver,
    addFiles,
    removeFile,
    clearAllFiles,
    getThumbnail,
    handleFileSelect,
    handleDragEnter,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handlePaste
  }
}
```

- [ ] **Step 2: Refactor `ChatInput.vue`** — delete the moved state (`pendingFiles`, `isDragOver`, `dragCounter`, `thumbnailUrls`) and functions (`addFiles`, `removeFile`, `clearAllFiles`, `getThumbnail`, `handleFileSelect`, `handleDragEnter`, `handleDragOver`, `handleDragLeave`, `handleDrop`, `handlePaste`, the `onBeforeUnmount(() => clearAllFiles())`), replace with:

```ts
import { useChatAttachments } from '../../composables/useChatAttachments'

const {
  pendingFiles,
  isDragOver,
  removeFile,
  clearAllFiles,
  getThumbnail,
  handleFileSelect,
  handleDragEnter,
  handleDragOver,
  handleDragLeave,
  handleDrop,
  handlePaste
} = useChatAttachments({ accept: () => supportsVision.value })
```

Template, `defineExpose`, `fileInputRef`/`openFilePicker` stay untouched (`onBeforeUnmount` import can drop if now unused).

- [ ] **Step 3: Verify** `npm run typecheck` + `npx vitest run` (all green; behavior identical).
- [ ] **Step 4: Commit** `git commit -m "refactor(chat): extract useChatAttachments from ChatInput (no behavior change)"`

---

### Task 5: composer multiline

**Files:**
- Modify: `frontend/src/renderer/src/components/horizon/HorizonComposer.vue`

- [ ] **Step 1: Auto-grow + alignment switch.** Script additions:

```ts
const multiline = ref(false)

/** Grow with content up to ~5 lines, then scroll; left-align once wrapped. */
function autoResize(): void {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  const lineH = parseFloat(getComputedStyle(el).lineHeight) || 33
  el.style.height = `${Math.min(el.scrollHeight, lineH * 5)}px`
  multiline.value = el.scrollHeight > lineH * 1.5
}

watch(text, () => nextTick(autoResize))
```

In the `active` watch, after `inputRef.value?.focus()` add `autoResize()`; in the inactive branch add `multiline.value = false`. In `seed()` after focus add `autoResize()`. Also expose submit for the cockpit (Task 6):

```ts
/** Programmatic send (cockpit send button). */
function submit(): void {
  const t = text.value.trim()
  if (t && !props.disabled) {
    emit('send', t)
    text.value = ''
  }
}

defineExpose({ seed, submit })
```

and add a paste pass-through emit: `const emit = defineEmits<{ send: [text: string]; paste: [event: ClipboardEvent] }>()`.

- [ ] **Step 2: Template** — textarea gains:

```vue
      :class="{ 'hz-composer__input--multi': multiline }"
      @input="autoResize"
      @paste="(e) => emit('paste', e)"
```

- [ ] **Step 3: CSS** — on `.hz-composer__input` add `overflow-y: auto; scrollbar-width: thin;` and:

```css
.hz-composer__input--multi {
  text-align: left;
}
```

- [ ] **Step 4: Verify** typecheck; manual: paste a long paragraph → grows to 5 lines, left-aligned, scrolls beyond.
- [ ] **Step 5: Commit** `git commit -m "fix(horizon): composer auto-grows multiline and left-aligns wrapped text"`

---

### Task 6: `HorizonCockpit` — input-bar parity

**Files:**
- Create: `frontend/src/renderer/src/components/horizon/HorizonCockpit.vue`
- Modify: `frontend/src/renderer/src/views/HorizonView.vue`

- [ ] **Step 1: Create `HorizonCockpit.vue`:**

```vue
<script setup lang="ts">
/**
 * HorizonCockpit — the controls rail that materializes under the serif
 * composer: the same capabilities as the workspace ChatInput (attachments,
 * models, scope, tools, permission tier, context, mic, send/stop) REUSING
 * those components as-is. Horizon contributes only the transparent shell.
 */
import { computed, ref } from 'vue'
import ModelSelector from '../settings/ModelSelector.vue'
import ChatToolControls from '../chat/ChatToolControls.vue'
import PermissionTierSelector from '../chat/PermissionTierSelector.vue'
import ScopeIndicator from '../chat/ScopeIndicator.vue'
import MicrophoneButton from '../voice/MicrophoneButton.vue'
import ContextBar from '../chat/ContextBar.vue'
import AppIcon from '../ui/AppIcon.vue'
import { useChatAttachments } from '../../composables/useChatAttachments'
import { useChatStore } from '../../stores/chat'
import { useSettingsStore } from '../../stores/settings'
import { useVoiceStore } from '../../stores/voice'
import type { AudioDevice } from '../../composables/useVoice'

defineProps<{
  isStreaming: boolean
  audioDevices: AudioDevice[]
  selectedDeviceId: string
}>()

const emit = defineEmits<{
  send: []
  stop: []
  'voice-start': []
  'voice-stop': []
  'voice-cancel-processing': []
  'refresh-devices': []
  'select-device': [deviceId: string]
}>()

const chatStore = useChatStore()
const settingsStore = useSettingsStore()
const voiceStore = useVoiceStore()

const supportsVision = computed(
  () => settingsStore.activeModel?.capabilities.vision ?? false
)

const att = useChatAttachments({ accept: () => supportsVision.value })
const fileInputRef = ref<HTMLInputElement | null>(null)

function openFilePicker(): void {
  fileInputRef.value?.click()
}

defineExpose({
  pendingFiles: att.pendingFiles,
  clearAllFiles: att.clearAllFiles,
  handlePaste: att.handlePaste
})
</script>

<template>
  <div
    class="hz-cockpit"
    @dragenter="att.handleDragEnter"
    @dragover="att.handleDragOver"
    @dragleave="att.handleDragLeave"
    @drop="att.handleDrop"
  >
    <div v-if="att.pendingFiles.value.length > 0" class="hz-cockpit__thumbs">
      <div
        v-for="file in att.pendingFiles.value"
        :key="file.name + file.size + file.lastModified"
        class="hz-cockpit__thumb"
      >
        <img :src="att.getThumbnail(file)" :alt="file.name" :title="file.name" />
        <button
          class="hz-cockpit__thumb-rm"
          aria-label="Rimuovi allegato"
          @click="att.removeFile(file)"
        >
          <AppIcon name="x" :size="10" :stroke-width="2.5" />
        </button>
      </div>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      accept="image/*"
      multiple
      class="hz-cockpit__file-input"
      @change="att.handleFileSelect"
    />

    <div class="hz-cockpit__rail">
      <button
        class="hz-cockpit__ghost"
        :disabled="!supportsVision"
        :title="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
        :aria-label="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
        @click="openFilePicker"
      >
        <AppIcon name="paperclip" :size="13" />
      </button>

      <ModelSelector model-type="llm" />
      <ScopeIndicator :conversation-id="chatStore.currentConversation?.id ?? null" />
      <ChatToolControls />
      <PermissionTierSelector />

      <ContextBar
        :context-info="chatStore.contextInfo"
        :is-compressing="chatStore.isCompressingContext"
      />

      <MicrophoneButton
        v-if="voiceStore.isReady"
        :available="voiceStore.sttAvailable"
        :connected="voiceStore.connected"
        :audio-devices="audioDevices"
        :selected-device-id="selectedDeviceId"
        @start-recording="emit('voice-start')"
        @stop-recording="emit('voice-stop')"
        @cancel-processing="emit('voice-cancel-processing')"
        @refresh-devices="emit('refresh-devices')"
        @select-device="(id) => emit('select-device', id)"
      />

      <button
        v-if="isStreaming"
        class="hz-cockpit__ghost hz-cockpit__stop"
        aria-label="Interrompi generazione"
        @click="emit('stop')"
      >
        <AppIcon name="stop" :size="13" />
      </button>
      <button
        v-else
        class="hz-cockpit__ghost"
        aria-label="Invia messaggio"
        @click="emit('send')"
      >
        <AppIcon name="send" :size="13" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.hz-cockpit {
  width: min(72%, 720px);
  margin-bottom: clamp(12px, 2vh, 24px);
}

.hz-cockpit__thumbs {
  display: flex;
  justify-content: center;
  gap: var(--space-2);
  padding-bottom: var(--space-2);
}

.hz-cockpit__thumb {
  position: relative;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--border);
}

.hz-cockpit__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.hz-cockpit__thumb-rm {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 16px;
  height: 16px;
  border-radius: var(--radius-full);
  background: var(--surface-4);
  border: 1px solid var(--border);
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
}

.hz-cockpit__file-input {
  display: none;
}

.hz-cockpit__rail {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid var(--border);
}

.hz-cockpit__ghost {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--hz-ink-dim);
  cursor: pointer;
  transition:
    color var(--hz-fade) ease,
    background var(--hz-fade) ease;
}

.hz-cockpit__ghost:hover:not(:disabled) {
  background: var(--surface-hover);
  color: var(--hz-ink);
}

.hz-cockpit__ghost:disabled {
  opacity: var(--opacity-disabled);
  cursor: not-allowed;
}

.hz-cockpit__stop {
  color: var(--danger);
}
</style>
```

- [ ] **Step 2: View wiring (`HorizonView.vue`).**

Script:
- `import HorizonCockpit from '../components/horizon/HorizonCockpit.vue'`
- extend the `useVoice()` destructure with `audioDevices, selectedDeviceId, refreshDevices`
- `const cockpitRef = ref<InstanceType<typeof HorizonCockpit> | null>(null)`
- replace `handleComposerSend`:

```ts
/** Sends typed text (+ pending cockpit attachments); collapses the composer. */
async function handleComposerSend(content: string): Promise<void> {
  const files = cockpitRef.value ? [...cockpitRef.value.pendingFiles] : []
  cockpitRef.value?.clearAllFiles()
  composerActive.value = false
  await send(content, undefined, files.length > 0 ? files : undefined).catch(console.error)
}
```

- forward composer paste to the cockpit:

```ts
function handleComposerPaste(e: ClipboardEvent): void {
  cockpitRef.value?.handlePaste(e)
}
```

Template (upper zone): `HorizonComposer` gains `@paste="handleComposerPaste"`; immediately AFTER it:

```vue
        <Transition name="hz-soft">
          <HorizonCockpit
            v-if="composerActive"
            ref="cockpitRef"
            :is-streaming="chatStore.isStreamingCurrentConversation"
            :audio-devices="audioDevices"
            :selected-device-id="selectedDeviceId"
            @send="composerRef?.submit()"
            @stop="stopGeneration"
            @voice-start="startListening"
            @voice-stop="stopListening"
            @voice-cancel-processing="cancelProcessing"
            @refresh-devices="refreshDevices"
            @select-device="(id) => (selectedDeviceId = id)"
          />
        </Transition>
```

(Note: `selectedDeviceId` from `useVoice` is a writable `Ref` — assignment is the existing selection mechanism.)

- [ ] **Step 3: Verify** `npm run typecheck`; manual smoke: cockpit appears with composer, attach an image, change tier, open tools, send with attachment.
- [ ] **Step 4: Commit** `git commit -m "feat(horizon): composer cockpit — full input-bar parity reusing workspace controls"`

---

### Task 7: dossier card shell

**Files:**
- Modify: `frontend/src/renderer/src/components/horizon/HorizonHistory.vue` (style only)

- [ ] **Step 1: Replace `.hz-history` block:**

```css
.hz-history {
  position: absolute;
  top: calc(var(--titlebar-height, 38px) + 8px);
  left: 12px;
  bottom: 8px;
  width: min(420px, 86vw);
  display: flex;
  flex-direction: column;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 20px;
  box-shadow: var(--panel-shadow, var(--shadow-md));
  z-index: var(--z-overlay);
  overflow: hidden;
}
```

and extend the drawer transition with a fade:

```css
.hz-drawer-enter-active,
.hz-drawer-leave-active {
  transition:
    transform var(--hz-fade) var(--ease-out-expo),
    opacity var(--hz-fade) ease;
}

.hz-drawer-enter-from,
.hz-drawer-leave-to {
  transform: translateX(-24px);
  opacity: 0;
}
```

(the full `-100%` slide fights the floating-card look; a short slide + fade matches the app's panels)

- [ ] **Step 2: Verify** typecheck (no script change) + manual: STORIA opens a floating card.
- [ ] **Step 3: Commit** `git commit -m "style(horizon): dossier adopts the app floating-card shell"`

---

### Task 8: plan labels rework

**Files:**
- Modify: `frontend/src/renderer/src/components/horizon/HorizonPlan.vue`

- [ ] **Step 1: Template** — replace the labels block (drop the `v-show` ≤6 rule and `shortLabel`):

```vue
    <div class="hz-plan__labels">
      <span
        v-for="(s, i) in steps"
        :key="i"
        class="hz-plan__label"
        :class="{
          'hz-plan__label--active': i === activeIndex,
          'hz-plan__label--done': s.status === 'completed'
        }"
        :style="{ left: `${positions[i] * 100}%` }"
        :title="s.step"
      >
        {{ i === activeIndex ? s.step : '·' }}
      </span>
    </div>
```

Script: delete `shortLabel` (and its TaskStep import stays — still used by props).

- [ ] **Step 2: CSS** — labels height to 22px; active label readable:

```css
.hz-plan__labels {
  position: relative;
  height: 22px;
  margin: 8px 6% 0;
}

.hz-plan__label--active {
  color: var(--hz-gold);
  font-size: 10px;
  max-width: 40ch;
  overflow: hidden;
  text-overflow: ellipsis;
}
```

(base `.hz-plan__label` keeps 8.5px mono/faint/nowrap/translateX(-50%))

- [ ] **Step 3: Verify** typecheck; manual: working state shows the full active step in gold, dots elsewhere.
- [ ] **Step 4: Commit** `git commit -m "feat(horizon): plan shows full active step label; markers elsewhere"`

---

### Task 9: final verification

- [ ] `npm run typecheck` — clean.
- [ ] `npm run lint` — zero NEW findings vs baseline.
- [ ] `npx vitest run` — all green (existing + Task 1).
- [ ] Smoke checklist (spec §5): shelf medallions; stage rises and re-opens from shelf; plan pinned in quiet; multiline composer; cockpit attach/tier/tools/model/mic; dossier card; line labels in listening/responding/working; signatures distinct.
- [ ] Commit anything outstanding.
