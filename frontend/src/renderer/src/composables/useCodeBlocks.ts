/**
 * Composable for handling code block interactions (copy-to-clipboard).
 * Uses event delegation — attach the returned handler to the container
 * element that hosts v-html rendered markdown content.
 */
const COPY_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'
const CHECK_ICON = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>'

/** Tracks pending restore timers per copy button to prevent overlapping feedback. */
const restoreTimers = new WeakMap<HTMLElement, ReturnType<typeof setTimeout>>()

export function useCodeBlocks() {
  async function handleCodeBlockClick(event: MouseEvent): Promise<void> {
    // Find the closest .code-block-copy button from the click target
    const target = (event.target as HTMLElement).closest('.code-block-copy') as HTMLElement | null
    if (!target) return

    const encoded = target.getAttribute('data-code')
    if (!encoded) return

    try {
      const code = decodeURIComponent(escape(atob(encoded)))
      await navigator.clipboard.writeText(code)

      // Cancel any pending restore timer for this button
      const existing = restoreTimers.get(target)
      if (existing) clearTimeout(existing)

      // Visual feedback
      const label = target.querySelector('.code-block-copy__label')
      const svg = target.querySelector('svg')
      if (label && svg) {
        label.textContent = 'Copiato!'
        svg.outerHTML = CHECK_ICON
        target.classList.add('code-block-copy--copied')

        const timer = setTimeout(() => {
          restoreTimers.delete(target)
          label.textContent = 'Copia'
          const currentSvg = target.querySelector('svg')
          if (currentSvg) currentSvg.outerHTML = COPY_ICON
          target.classList.remove('code-block-copy--copied')
        }, 2000)
        restoreTimers.set(target, timer)
      }
    } catch (err) {
      console.error('[useCodeBlocks] Failed to copy code:', err)
    }
  }

  return { handleCodeBlockClick }
}
