/**
 * Re-export the canonical markdown renderer from composables/useMarkdown.
 *
 * Previously this file contained a lightweight regex-based renderer.
 * It is now unified with the full-featured markdown-it + highlight.js
 * renderer to ensure consistent rendering across all components
 * (chat messages, streaming indicators, and assistant responses).
 */
export { renderMarkdown } from '../composables/useMarkdown'
