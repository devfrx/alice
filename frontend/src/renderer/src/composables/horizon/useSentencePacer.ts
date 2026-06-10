/**
 * useSentencePacer — turns a raw streaming text ref into sentence-paced
 * display text: while `streaming` is true, complete sentences are committed
 * one per interval (reading rhythm); when streaming flips false everything
 * (including any unterminated tail) is flushed at once.
 *
 * `immediate: true` (reduced motion) mirrors the source verbatim.
 *
 * Contract: `source` must only append within a turn, or reset to '' at a turn
 * boundary.
 */
import { onScopeDispose, ref, watch, type Ref } from 'vue'

/** Split text into terminated sentences + the unterminated rest. */
export function segmentSentences(text: string): {
  sentences: string[]
  rest: string
  /** End offset (exclusive) of each sentence in the ORIGINAL string. */
  ends: number[]
} {
  const sentences: string[] = []
  const ends: number[] = []
  const re = /[^.!?…]*[.!?…]+(?:\s+|$)/g
  let consumed = 0
  for (const m of text.matchAll(re)) {
    sentences.push(m[0].trim())
    consumed = (m.index ?? 0) + m[0].length
    ends.push(consumed)
  }
  return { sentences, rest: text.slice(consumed).trim(), ends }
}

export interface SentencePacerOptions {
  /** Gap between committed sentences (ms). Default 350. */
  intervalMs?: number
  /** Mirror the source verbatim (prefers-reduced-motion). Default false. */
  immediate?: boolean
}

export interface SentencePacer {
  /** The paced text to display. */
  displayed: Ref<string>
  /** Clear for a new turn. */
  reset: () => void
}

export function useSentencePacer(
  source: Ref<string>,
  streaming: Ref<boolean>,
  options: SentencePacerOptions = {},
): SentencePacer {
  const intervalMs = options.intervalMs ?? 350
  const displayed = ref('')
  /** Number of sentences currently shown. */
  let shown = 0
  let timer: ReturnType<typeof setInterval> | null = null

  function stopTimer(): void {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  function flush(): void {
    stopTimer()
    displayed.value = source.value
    shown = segmentSentences(source.value).sentences.length
  }

  function commitNext(): void {
    const { ends } = segmentSentences(source.value)
    if (shown < ends.length) {
      shown += 1
      displayed.value = source.value.slice(0, ends[shown - 1]).trimEnd()
    }
    if (!streaming.value) flush()
  }

  /**
   * Starts the interval on first call; subsequent calls are no-ops.
   * The first sentence appears after one full interval — an intentional
   * reading "breath" before text materializes.
   */
  function ensureTimer(): void {
    if (!timer) timer = setInterval(commitNext, intervalMs)
  }

  watch(
    [source, streaming],
    ([text, isStreaming]) => {
      if (options.immediate) {
        displayed.value = text
        return
      }
      if (text === '') {
        // New turn begins with an empty stream.
        stopTimer()
        displayed.value = ''
        shown = 0
        return
      }
      if (isStreaming) ensureTimer()
      else flush()
    },
    { immediate: true },
  )

  function reset(): void {
    stopTimer()
    displayed.value = ''
    shown = 0
  }

  onScopeDispose(stopTimer)

  return { displayed, reset }
}
