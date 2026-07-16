/**
 * Format a conversation cost (OpenRouter credits, USD) for display.
 *
 * Tiny-but-nonzero costs render as "< $0.0001" instead of a misleading
 * "$0.0000" that reads as free.
 */
export function formatCost(cost: number): string {
  if (cost > 0 && cost < 0.0001) return '< $0.0001'
  return `$${cost.toFixed(4)}`
}
