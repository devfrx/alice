/**
 * Tests for the sentence pacer: token stream → sentences committed at a
 * reading rhythm. Pure Vue reactivity + timers; no DOM.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { effectScope, ref, type EffectScope } from 'vue'

import { segmentSentences, useSentencePacer } from './useSentencePacer'

describe('segmentSentences', () => {
  it('splits complete sentences and keeps the unterminated rest', () => {
    expect(segmentSentences('Prima frase. Seconda frase! E poi')).toMatchObject({
      sentences: ['Prima frase.', 'Seconda frase!'],
      rest: 'E poi'
    })
  })

  it('treats ellipsis and ? as terminators', () => {
    expect(segmentSentences('Vediamo… Sicuro? ok').sentences).toEqual(['Vediamo…', 'Sicuro?'])
  })

  it('returns everything as rest when nothing terminates', () => {
    expect(segmentSentences('streaming senza fine')).toMatchObject({
      sentences: [],
      rest: 'streaming senza fine'
    })
  })
})

describe('useSentencePacer', () => {
  let scope: EffectScope

  beforeEach(() => {
    vi.useFakeTimers()
    scope = effectScope()
  })

  afterEach(() => {
    scope.stop()
    vi.useRealTimers()
  })

  it('commits one sentence per interval while streaming', async () => {
    const source = ref('')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    source.value = 'Una. Due. Tre.'
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Una.')
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Una. Due.')
  })

  it('flushes everything (including the rest) when streaming ends', async () => {
    const source = ref('Una. Due. E mezzo')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    await vi.advanceTimersByTimeAsync(300)
    streaming.value = false
    await vi.advanceTimersByTimeAsync(0)
    expect(pacer.displayed.value).toBe('Una. Due. E mezzo')
  })

  it('immediate mode mirrors the source (reduced motion)', async () => {
    const source = ref('Tutto. Subito.')
    const streaming = ref(true)
    const pacer = scope.run(() =>
      useSentencePacer(source, streaming, { intervalMs: 300, immediate: true })
    )!
    await vi.advanceTimersByTimeAsync(0)
    expect(pacer.displayed.value).toBe('Tutto. Subito.')
  })

  it('reset() clears the display for a new turn', async () => {
    const source = ref('Vecchia frase.')
    const streaming = ref(false)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!
    await vi.advanceTimersByTimeAsync(0)
    pacer.reset()
    expect(pacer.displayed.value).toBe('')
  })

  it('never drops the prefix before a non-terminating period (decimals)', async () => {
    const source = ref('')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    source.value = 'Il valore è 3.14 circa. Fine.'
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Il valore è 3.14 circa.')
  })

  it('preserves newlines/markdown structure in the paced display', async () => {
    const source = ref('')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    source.value = 'Prima riga.\n\nSeconda frase. Coda'
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Prima riga.')
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Prima riga.\n\nSeconda frase.')
  })

  it('turn boundary: source reset to empty clears and re-paces from one', async () => {
    const source = ref('Vecchia. Fine.')
    const streaming = ref(true)
    const pacer = scope.run(() => useSentencePacer(source, streaming, { intervalMs: 300 }))!

    await vi.advanceTimersByTimeAsync(600)
    streaming.value = false
    await vi.advanceTimersByTimeAsync(0)
    expect(pacer.displayed.value).toBe('Vecchia. Fine.')

    source.value = ''
    await vi.advanceTimersByTimeAsync(0)
    expect(pacer.displayed.value).toBe('')

    streaming.value = true
    source.value = 'Nuova. Seconda.'
    await vi.advanceTimersByTimeAsync(300)
    expect(pacer.displayed.value).toBe('Nuova.')
  })
})
