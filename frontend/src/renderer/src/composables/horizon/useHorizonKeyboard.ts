// composables/horizon/useHorizonKeyboard.ts
/**
 * useHorizonKeyboard — global key capture for the Horizon desk.
 *
 * Esc walks the interrupt chain: TTS → streaming → composer → focused
 * window (focus release only — Esc NEVER closes windows, spec §6.9).
 * Any printable first character materializes the composer (Jarvis entry),
 * unless the keystroke originates inside an input, a dialog, a desk window
 * or the dock (spec §6.7 — typing in the terminal must stay in the terminal).
 */
import { onBeforeUnmount, onMounted } from 'vue'
import type { Ref } from 'vue'

export interface HorizonKeyboardDeps {
  /** A global modal owns the keyboard (useModal state). */
  modalVisible: () => boolean
  /** A pending confirmation / ask_user owns the keyboard. */
  sceneDimmed: () => boolean
  composerActive: Ref<boolean>
  isSpeaking: () => boolean
  isStreaming: () => boolean
  cancelSpeak: () => void
  stopGeneration: () => void
  seedComposer: (ch: string) => void
  hasFocusedWindow: () => boolean
  blurWindows: () => void
}

export function useHorizonKeyboard(deps: HorizonKeyboardDeps): void {
  function onGlobalKeydown(e: KeyboardEvent): void {
    if (e.isComposing) return
    if (deps.modalVisible()) return
    if (deps.sceneDimmed()) return
    if (e.key === 'Escape') {
      if (deps.isSpeaking()) deps.cancelSpeak()
      else if (deps.isStreaming()) deps.stopGeneration()
      else if (deps.composerActive.value) deps.composerActive.value = false
      else if (deps.hasFocusedWindow()) deps.blurWindows()
      return
    }
    if (deps.composerActive.value) return
    const tgt = e.target as HTMLElement | null
    if (
      tgt?.closest(
        'input, textarea, select, button, [contenteditable="true"], [role="dialog"], .desk-window, .desk-dock'
      )
    )
      return
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault()
      deps.composerActive.value = true
      deps.seedComposer(e.key)
    }
  }

  onMounted(() => window.addEventListener('keydown', onGlobalKeydown))
  onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKeydown))
}
