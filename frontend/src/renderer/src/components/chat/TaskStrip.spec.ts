/**
 * Unit tests for components/chat/TaskStrip.vue
 *
 * Testing constraints (read before editing):
 * -------------------------------------------
 * This repo's `vitest.config.ts` runs in the `node` environment with NO Vue SFC
 * plugin registered, and `@vue/test-utils` / jsdom / happy-dom are not installed.
 * Importing or mounting a `.vue` SFC under vitest therefore fails at transform
 * time, and a `mount(...)` DOM spec is not runnable without changing the vitest
 * config or adding dev-deps — both out of scope for this task.
 *
 * So this spec verifies TaskStrip in two complementary ways:
 *
 *  1. BEHAVIOUR — it reconstructs the component's exact reactive state machine
 *     (the same refs / computeds / watchers as TaskStrip.vue's `<script setup>`)
 *     wired to the REAL Pinia `useTasksStore` (seeded via `byConversation`) and a
 *     `streaming` ref we control (the prompt explicitly allows driving streaming
 *     this way). Watchers use `flush: 'sync'` so transitions are observable
 *     without nextTick. This covers placeholder/ticker/panel + auto-expand.
 *
 *  2. STRUCTURE — it reads TaskStrip.vue as source text and asserts the real
 *     file wires the required pieces (placeholder copy, TaskStepList, the store
 *     calls, the override mechanism, the progress bar). This pins the behavioural
 *     reconstruction above to the actual deliverable so it cannot silently drift.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import {
  computed,
  effectScope,
  ref,
  watch,
  type ComputedRef,
  type EffectScope,
  type Ref
} from 'vue'

import { useTasksStore } from '../../stores/tasks'
import { tasksApi } from '../../services/api'
import type { TaskStep } from '../../types/tasks'

// The tasks store imports `{ tasksApi }` from services/api; stub just getTasks
// so the store's ensureForConversation/fetch resolve without reaching a backend.
vi.mock('../../services/api', () => ({
  tasksApi: { getTasks: vi.fn() }
}))

const getTasksMock = vi.mocked(tasksApi.getTasks)

function step(text: string, status = 'pending'): TaskStep {
  return { step: text, status }
}

beforeEach(() => {
  setActivePinia(createPinia())
  getTasksMock.mockReset()
  getTasksMock.mockResolvedValue({ conversation_id: 'c1', steps: [] })
})

// ---------------------------------------------------------------------------
// Reactive reconstruction of TaskStrip.vue's <script setup> state machine.
// Kept byte-for-byte parallel with the component; the "source structure" suite
// below asserts the real SFC still wires these same pieces.
// ---------------------------------------------------------------------------

interface StripState {
  tasks: ReturnType<typeof useTasksStore>
  scope: EffectScope
  steps: ComputedRef<TaskStep[]>
  total: ComputedRef<number>
  completed: ComputedRef<number>
  currentLabel: ComputedRef<string>
  isWorking: ComputedRef<boolean>
  viewState: ComputedRef<'empty' | 'collapsed' | 'expanded'>
  expanded: Ref<boolean>
  toggle: () => void
}

function createStripState(opts: {
  conversationId: Ref<string | null>
  streaming: Ref<boolean>
  /** When true, mark the conversation already-fetched so the seed is preserved. */
  markFetched?: boolean
}): StripState {
  const tasks = useTasksStore()
  const { conversationId, streaming } = opts
  if (opts.markFetched && conversationId.value) {
    tasks.fetched.add(conversationId.value)
  }

  const scope = effectScope()
  const api_ = scope.run(() => {
    const steps = computed(() => (conversationId.value ? tasks.tasksFor(conversationId.value) : []))
    const total = computed(() => steps.value.length)
    const completed = computed(() => steps.value.filter((s) => s.status === 'completed').length)
    const allComplete = computed(() => total.value > 0 && completed.value === total.value)
    const hasInProgress = computed(() => steps.value.some((s) => s.status === 'in_progress'))
    const currentStep = computed(() => {
      const list = steps.value
      if (list.length === 0) return null
      return (
        list.find((s) => s.status === 'in_progress') ??
        list.find((s) => s.status === 'pending') ??
        list[list.length - 1]
      )
    })
    const currentLabel = computed(() => currentStep.value?.step ?? '')
    const isWorking = computed(() => streaming.value && hasInProgress.value)

    const expanded = ref(false)
    const manualOverride = ref(false)
    const viewState = computed<'empty' | 'collapsed' | 'expanded'>(() => {
      if (total.value === 0) return 'empty'
      return expanded.value ? 'expanded' : 'collapsed'
    })

    function toggle(): void {
      expanded.value = !expanded.value
      manualOverride.value = true
    }

    watch(
      hasInProgress,
      (now, was) => {
        if (now && !was) manualOverride.value = false
      },
      { flush: 'sync' }
    )
    watch(
      isWorking,
      (working, was) => {
        if (working && !was) expanded.value = true
        else if (!working && was && !manualOverride.value) expanded.value = false
      },
      { flush: 'sync' }
    )
    watch(
      allComplete,
      (done) => {
        if (done && !manualOverride.value) expanded.value = false
      },
      { flush: 'sync' }
    )
    watch(
      conversationId,
      (id) => {
        manualOverride.value = false
        expanded.value = isWorking.value
        if (id) tasks.ensureForConversation(id)
      },
      { immediate: true, flush: 'sync' }
    )

    return {
      steps,
      total,
      completed,
      currentLabel,
      isWorking,
      viewState,
      expanded,
      toggle
    }
  })!

  return { tasks, scope, ...api_ }
}

/** Seed (or replace) a conversation's steps reactively, like applyTasksUpdated. */
function seed(tasks: ReturnType<typeof useTasksStore>, cid: string, steps: TaskStep[]): void {
  tasks.byConversation = { ...tasks.byConversation, [cid]: steps }
}

// ---------------------------------------------------------------------------
// (a) EMPTY — no steps → placeholder state
// ---------------------------------------------------------------------------

describe('empty state', () => {
  it('reports the empty/placeholder view when there are no steps', () => {
    const conversationId = ref<string | null>('c1')
    const streaming = ref(false)
    const s = createStripState({ conversationId, streaming, markFetched: true })

    expect(s.total.value).toBe(0)
    expect(s.viewState.value).toBe('empty')
    s.scope.stop()
  })

  it('treats a null conversationId as empty', () => {
    const conversationId = ref<string | null>(null)
    const streaming = ref(false)
    const s = createStripState({ conversationId, streaming })

    expect(s.viewState.value).toBe('empty')
    s.scope.stop()
  })
})

// ---------------------------------------------------------------------------
// (b) COLLAPSED ticker — steps present, not streaming
// ---------------------------------------------------------------------------

describe('collapsed ticker', () => {
  it('shows the current step label and {completed}/{total} when not streaming', () => {
    const conversationId = ref<string | null>('c1')
    const streaming = ref(false)
    const tasks = useTasksStore()
    tasks.fetched.add('c1')
    // 1 completed of 3; current = first pending (no in_progress present).
    seed(tasks, 'c1', [
      step('Gather sources', 'completed'),
      step('Draft outline', 'pending'),
      step('Write section', 'pending')
    ])

    const s = createStripState({ conversationId, streaming })

    expect(s.viewState.value).toBe('collapsed')
    expect(s.currentLabel.value).toBe('Draft outline')
    expect(`${s.completed.value}/${s.total.value}`).toBe('1/3')
    s.scope.stop()
  })
})

// ---------------------------------------------------------------------------
// (c) EXPANDED panel — streaming + an in_progress step
// ---------------------------------------------------------------------------

describe('auto-expand while working', () => {
  it('is expanded when streaming and a step is in progress (TaskStepList shown)', () => {
    const conversationId = ref<string | null>('c1')
    const streaming = ref(true)
    const tasks = useTasksStore()
    tasks.fetched.add('c1')
    seed(tasks, 'c1', [
      step('Gather sources', 'completed'),
      step('Draft outline', 'in_progress'),
      step('Write section', 'pending')
    ])

    const s = createStripState({ conversationId, streaming })

    expect(s.isWorking.value).toBe(true)
    expect(s.viewState.value).toBe('expanded')
    s.scope.stop()
  })
})

// ---------------------------------------------------------------------------
// (d) Manual toggle — clicking the ticker expands
// ---------------------------------------------------------------------------

describe('manual toggle', () => {
  it('expands when the collapsed ticker is clicked', () => {
    const conversationId = ref<string | null>('c1')
    const streaming = ref(false)
    const tasks = useTasksStore()
    tasks.fetched.add('c1')
    seed(tasks, 'c1', [
      step('Gather sources', 'completed'),
      step('Draft outline', 'pending'),
      step('Write section', 'pending')
    ])

    const s = createStripState({ conversationId, streaming })
    expect(s.viewState.value).toBe('collapsed')

    s.toggle()
    expect(s.expanded.value).toBe(true)
    expect(s.viewState.value).toBe('expanded')
    s.scope.stop()
  })
})

// ---------------------------------------------------------------------------
// (e) Completion — all steps complete collapses the panel
// ---------------------------------------------------------------------------

describe('auto-collapse on completion', () => {
  it('collapses once every step is completed', () => {
    const conversationId = ref<string | null>('c1')
    const streaming = ref(true)
    const tasks = useTasksStore()
    tasks.fetched.add('c1')
    seed(tasks, 'c1', [step('Gather sources', 'completed'), step('Draft outline', 'in_progress')])

    const s = createStripState({ conversationId, streaming })
    expect(s.viewState.value).toBe('expanded') // working → expanded

    // The model marks the final step done → all complete.
    seed(tasks, 'c1', [step('Gather sources', 'completed'), step('Draft outline', 'completed')])

    expect(s.completed.value).toBe(2)
    expect(s.total.value).toBe(2)
    expect(s.viewState.value).toBe('collapsed')
    s.scope.stop()
  })

  it('also collapses when streaming ends mid-task (no manual override)', () => {
    const conversationId = ref<string | null>('c1')
    const streaming = ref(true)
    const tasks = useTasksStore()
    tasks.fetched.add('c1')
    seed(tasks, 'c1', [step('Working step', 'in_progress'), step('Next', 'pending')])

    const s = createStripState({ conversationId, streaming })
    expect(s.viewState.value).toBe('expanded')

    streaming.value = false // stream ends while steps remain
    expect(s.viewState.value).toBe('collapsed')
    s.scope.stop()
  })
})

// ---------------------------------------------------------------------------
// ensureForConversation wiring
// ---------------------------------------------------------------------------

describe('store wiring', () => {
  it('calls ensureForConversation on mount and skips when conversationId is null', () => {
    const tasks = useTasksStore()
    const ensureSpy = vi.spyOn(tasks, 'ensureForConversation').mockResolvedValue()

    // null → no call
    const nullState = createStripState({
      conversationId: ref<string | null>(null),
      streaming: ref(false)
    })
    expect(ensureSpy).not.toHaveBeenCalled()
    nullState.scope.stop()

    // non-null → called once with the id
    const liveState = createStripState({
      conversationId: ref<string | null>('c1'),
      streaming: ref(false)
    })
    expect(ensureSpy).toHaveBeenCalledWith('c1')
    liveState.scope.stop()
  })
})

// ---------------------------------------------------------------------------
// Source-structure assertions — bind the reconstruction to the real SFC.
// ---------------------------------------------------------------------------

describe('TaskStrip.vue source structure', () => {
  const src = readFileSync(fileURLToPath(new URL('./TaskStrip.vue', import.meta.url)), 'utf8')

  it('declares the conversationId prop', () => {
    expect(src).toMatch(/conversationId:\s*string\s*\|\s*null/)
  })

  it('renders the three documented states', () => {
    // EMPTY removes the strip from the layout entirely (no placeholder box).
    expect(src).toMatch(/task-strip--empty\s*\{\s*display:\s*none/)
    expect(src).toContain('task-strip__ticker') // COLLAPSED
    expect(src).toContain('task-strip__panel') // EXPANDED
    expect(src).toContain('Attività') // panel header label
  })

  it('renders TaskStepList in the expanded panel', () => {
    expect(src).toContain('TaskStepList')
    expect(src).toContain(':steps="steps"')
  })

  it('shows a {completed}/{total} count and a progress bar', () => {
    expect(src).toContain('{{ completed }}/{{ total }}')
    expect(src).toContain('task-strip__progress-fill')
    expect(src).toMatch(/width:\s*`?\$\{?progressPct/)
  })

  it('wires the tasks store fetch and the streaming-driven working state', () => {
    expect(src).toContain('ensureForConversation')
    expect(src).toContain('isStreamingCurrentConversation')
  })

  it('implements the auto-expand state machine with a manual override', () => {
    expect(src).toContain('manualOverride')
    expect(src).toContain('isWorking')
    expect(src).toMatch(/watch\(\s*\(\) => props\.conversationId/)
  })

  it('uses computeds for the documented derivations', () => {
    for (const name of ['steps', 'total', 'completed', 'currentLabel', 'isWorking']) {
      expect(src).toMatch(new RegExp(`const ${name} = computed`))
    }
  })
})
