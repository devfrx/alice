import { getIconSvgString } from '../assets/icons'

/**
 * Composable for handling code block interactions (copy-to-clipboard).
 * Uses event delegation — attach the returned handler to the container
 * element that hosts v-html rendered markdown content.
 */
const COPY_ICON = getIconSvgString('copy', 16)
const CHECK_ICON = getIconSvgString('check', 16)

/** Tracks pending restore timers per copy button to prevent overlapping feedback. */
const restoreTimers = new WeakMap<HTMLElement, ReturnType<typeof setTimeout>>()

export function useCodeBlocks(): { handleCodeBlockClick: (event: MouseEvent) => Promise<void> } {
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
