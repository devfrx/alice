/**
 * Human-readable "time ago" label (it-IT) from an ISO timestamp.
 *
 * @param iso ISO 8601 timestamp string.
 * @param now Reference time in ms (defaults to `Date.now()`; injectable for tests).
 */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const diff = now - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'adesso'
  if (mins < 60) return `${mins} min fa`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h fa`
  const days = Math.floor(hours / 24)
  if (days === 1) return 'ieri'
  if (days < 30) return `${days}g fa`
  return new Date(iso).toLocaleDateString('it-IT')
}
