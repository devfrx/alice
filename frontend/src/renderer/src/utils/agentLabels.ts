/**
 * agentLabels — Human-friendly Italian labels for agent loop entities.
 *
 * The backend exposes raw, snake_case identifiers (tool names, run
 * states, …) that are unsuitable for direct presentation to the user.
 * This module centralises the translation so every UI surface
 * (PlanCard, ActivitySidebar, MessageBubble micro-banner) speaks the
 * same language.
 */

import type { AgentRunState, StepStatus } from '../types/agent'

// ---------------------------------------------------------------------------
// Tool name → present-progressive Italian phrase
// ---------------------------------------------------------------------------

/**
 * Ordered list of (regex, label) pairs.  The first matching entry
 * wins, so more specific patterns come first.  All matches are
 * case-insensitive and operate on the raw tool name.
 */
const TOOL_PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/web[_-]?search/i, 'Cerco sul web'],
  [/web[_-]?(scrape|fetch|browse|read)/i, 'Apro la pagina'],
  [/(chart|plot|graph)[_-]?(generator|create|render)?/i, 'Genero un grafico'],
  [/memory[_-]?(remember|save|store|write|add)/i, 'Memorizzo'],
  [/memory[_-]?(search|recall|query|read|find)/i, 'Recupero dalla memoria'],
  [/file[_-]?read/i, 'Leggo il file'],
  [/file[_-]?write/i, 'Scrivo il file'],
  [/(code|python|shell|bash)[_-]?(exec|run|eval)?/i, 'Eseguo codice'],
  [/(image|img)[_-]?(gen|generate|create)/i, "Genero un'immagine"],
  [/whiteboard/i, 'Lavoro sulla lavagna'],
  [/calendar/i, 'Consulto il calendario'],
  [/email/i, 'Gestisco le email'],
  [/note/i, 'Prendo appunti'],
]

/**
 * Translate a backend tool name into a short Italian phrase suitable
 * for inline UI presentation.  Falls back to a Capitalised version of
 * the last underscore-separated segment when no pattern matches.
 *
 * @example
 *   humanizeTool('web_search_web_search') // → 'Cerco sul web'
 *   humanizeTool('mcp_custom_thing')      // → 'Thing'
 */
export function humanizeTool(name: string | null | undefined): string {
  if (!name) return ''
  for (const [pattern, label] of TOOL_PATTERNS) {
    if (pattern.test(name)) return label
  }
  const tail = name.split(/[_-]/).filter(Boolean).pop() ?? name
  return tail.charAt(0).toUpperCase() + tail.slice(1)
}

// ---------------------------------------------------------------------------
// Tool category buckets — used by the activity feed for stat counters
// ---------------------------------------------------------------------------

/** High-level bucket a tool name belongs to. */
export type ToolCategory =
  | 'search'
  | 'scrape'
  | 'memory'
  | 'chart'
  | 'code'
  | 'image'
  | 'whiteboard'
  | 'calendar'
  | 'email'
  | 'note'
  | 'file'
  | 'other'

const CATEGORY_PATTERNS: ReadonlyArray<readonly [RegExp, ToolCategory]> = [
  [/web[_-]?search/i, 'search'],
  [/web[_-]?(scrape|fetch|browse|read)/i, 'scrape'],
  [/memory/i, 'memory'],
  [/(chart|plot|graph)/i, 'chart'],
  [/(image|img)[_-]?(gen|generate|create)/i, 'image'],
  [/whiteboard/i, 'whiteboard'],
  [/calendar/i, 'calendar'],
  [/email/i, 'email'],
  [/note/i, 'note'],
  [/file[_-]?(read|write|list|search)/i, 'file'],
  [/(code|python|shell|bash|exec|run)/i, 'code'],
]

/**
 * Categorise a backend tool name into one of the well-known buckets
 * used for stat counters in the activity feed.
 */
export function toolCategory(name: string | null | undefined): ToolCategory {
  if (!name) return 'other'
  for (const [pattern, cat] of CATEGORY_PATTERNS) {
    if (pattern.test(name)) return cat
  }
  return 'other'
}

// ---------------------------------------------------------------------------
// Tool argument summarisation
// ---------------------------------------------------------------------------

/** Truncate a string to `max` chars, adding an ellipsis when cut. */
function _ellipsize(value: string, max = 80): string {
  const v = value.trim()
  return v.length > max ? `${v.slice(0, max - 1)}…` : v
}

/**
 * Render a single argument value for inline display.  Quotes strings,
 * collapses arrays/objects to a compact JSON snippet.
 */
function _renderValue(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return `"${value}"`
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return ''
  }
}

/** Pretty-print a URL by stripping protocol and trailing slash. */
function _shortUrl(url: string): string {
  return url.replace(/^https?:\/\//, '').replace(/\/$/, '')
}

/**
 * Pick the first non-empty value among `keys` from an args object.
 * Returns the raw value (not stringified).
 */
function _pick(args: Record<string, unknown>, keys: string[]): unknown {
  for (const k of keys) {
    const v = args[k]
    if (v !== undefined && v !== null && v !== '') return v
  }
  return undefined
}

/**
 * Build a single-line, human-readable summary of a tool's arguments.
 * Italian, ≤ ~80 chars.  The exact format depends on the tool — well
 * known tools get a hand-tailored summary; everything else falls back
 * to the first 1-2 string fields joined as `k: v · k: v`.
 *
 * @example
 *   summarizeToolArgs('web_search', { query: 'tendenze player count' })
 *   // → 'query: "tendenze player count"'
 *   summarizeToolArgs('web_scrape', { url: 'https://steamdb.info/charts/' })
 *   // → 'url: steamdb.info/charts'
 */
export function summarizeToolArgs(
  toolName: string,
  args: Record<string, unknown>,
): string {
  const cat = toolCategory(toolName)

  if (cat === 'search') {
    const q = _pick(args, ['query', 'q', 'search_query', 'text'])
    if (typeof q === 'string') return _ellipsize(`query: "${q}"`)
  }

  if (cat === 'scrape') {
    const u = _pick(args, ['url', 'href', 'link', 'page'])
    if (typeof u === 'string') return _ellipsize(`url: ${_shortUrl(u)}`)
  }

  if (cat === 'memory') {
    const cat2 = _pick(args, ['category', 'kind', 'type'])
    const scope = _pick(args, ['scope', 'memory_type', 'tier'])
    const parts: string[] = []
    if (typeof cat2 === 'string') parts.push(`category: ${cat2}`)
    if (typeof scope === 'string') parts.push(scope)
    if (parts.length) return _ellipsize(parts.join(' · '))
    const q = _pick(args, ['query', 'text'])
    if (typeof q === 'string') return _ellipsize(`"${q}"`)
  }

  if (cat === 'chart') {
    if (/update/i.test(toolName)) {
      const id = _pick(args, ['chart_id', 'id'])
      if (typeof id === 'string') {
        const short = id.length > 10 ? `${id.slice(0, 8)}…` : id
        return _ellipsize(`chart_id: ${short}`)
      }
    }
    const t = _pick(args, ['title', 'titolo', 'name'])
    if (typeof t === 'string') return _ellipsize(`titolo: "${t}"`)
    const ct = _pick(args, ['chart_type', 'type'])
    if (typeof ct === 'string') return _ellipsize(`tipo: ${ct}`)
  }

  if (cat === 'whiteboard') {
    const id = _pick(args, ['board_id', 'whiteboard_id', 'id'])
    if (typeof id === 'string') {
      const short = id.length > 10 ? `${id.slice(0, 8)}…` : id
      return _ellipsize(`board: ${short}`)
    }
    const t = _pick(args, ['title', 'name'])
    if (typeof t === 'string') return _ellipsize(`titolo: "${t}"`)
  }

  if (cat === 'file') {
    const p = _pick(args, ['path', 'file_path', 'filename'])
    if (typeof p === 'string') return _ellipsize(`path: ${p}`)
  }

  if (cat === 'code') {
    const c = _pick(args, ['code', 'script', 'command'])
    if (typeof c === 'string') {
      const single = c.replace(/\s+/g, ' ').trim()
      return _ellipsize(single, 80)
    }
  }

  // Generic fallback — first 1-2 string-ish fields.
  const parts: string[] = []
  for (const [k, v] of Object.entries(args)) {
    if (parts.length >= 2) break
    if (v === null || v === undefined || v === '') continue
    if (typeof v === 'object') continue
    const rendered = _renderValue(v)
    if (rendered) parts.push(`${k}: ${rendered}`)
  }
  return _ellipsize(parts.join(' · '))
}

// ---------------------------------------------------------------------------
// Step status → short status word
// ---------------------------------------------------------------------------

const STATUS_LABELS: Record<StepStatus, string> = {
  pending: 'In attesa',
  in_progress: 'In corso',
  done: 'Completato',
  retry: 'Da rifare',
  failed: 'Fallito',
  skipped: 'Saltato',
}

/** Italian word describing a step's current visual status. */
export function humanizeStatus(status: StepStatus): string {
  return STATUS_LABELS[status] ?? status
}

// ---------------------------------------------------------------------------
// Run state → conversational subtitle
// ---------------------------------------------------------------------------

/**
 * Build the dynamic sidebar subtitle for an in-flight or completed
 * run.  Speaks in first person, mirroring an assistant's voice.
 *
 * @param state         Current `AgentRun.state`.
 * @param currentStep   0-based current step pointer.
 * @param totalSteps    Total step count (0 means "unknown yet").
 */
export function humanizeRunSubtitle(
  state: AgentRunState,
  currentStep: number,
  totalSteps: number,
): string {
  switch (state) {
    case 'planning':
      return 'Sto pianificando…'
    case 'running':
      if (totalSteps > 0) {
        const cur = Math.min(currentStep + 1, totalSteps)
        return `Sto eseguendo il passo ${cur} di ${totalSteps}`
      }
      return 'Sto lavorando…'
    case 'asked_user':
      return 'Aspetto una tua risposta'
    case 'done':
      if (totalSteps > 0) {
        return totalSteps === 1
          ? 'Ho completato il piano.'
          : `Ho completato ${totalSteps} passi.`
      }
      return 'Ho finito.'
    case 'failed':
      return 'Mi sono fermato per un errore.'
    case 'cancelled':
      return 'Ho annullato l\u2019operazione.'
    default:
      return ''
  }
}
