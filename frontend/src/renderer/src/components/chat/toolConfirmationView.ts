/**
 * View-model builder for the tool-confirmation dialog body (spec §6.2).
 *
 * Pure presentation logic, extracted from ToolConfirmationDialog.vue so it is
 * testable in the vitest node env (no component mount). Decides how the tool
 * arguments are rendered:
 *
 * - `diff` — exact-string edit confirmations (`*edit_text_file` with string
 *   `old_string`/`new_string`) render as a red/green line diff.
 * - `write-preview` — file writes (`*write_text_file` with string `content`)
 *   render a truncated preview of the content to be written.
 * - `args` — everything else keeps the raw pretty-printed JSON (the dialog's
 *   historical behavior).
 *
 * Tool names are matched by SUFFIX (`endsWith`), not equality, so a plugin
 * namespace rename does not silently kill the preview. Malformed args
 * (missing/non-string fields, null/undefined args) always fall back to the
 * honest `args` mode — never a broken or misleading preview.
 *
 * No wire fields are involved: this is FE-only presentation over the existing
 * confirmation frame.
 */
import type { ToolMeta } from '../../types/turn'
import { computeLineDiff, type DiffRow } from './editDiff'

/** Discriminated union of the three dialog body renderings. */
export type ConfirmationBody =
  | { mode: 'diff'; path: string; rows: DiffRow[]; replaceAll: boolean }
  | { mode: 'write-preview'; path: string; preview: string; truncated: boolean }
  | { mode: 'args'; json: string }

/** Write previews stop at whichever cap trips first. */
const WRITE_PREVIEW_MAX_LINES = 40
const WRITE_PREVIEW_MAX_CHARS = 2000

/** Extract a display path from args — empty string when absent or non-string. */
function pathOf(args: Record<string, unknown>): string {
  return typeof args.path === 'string' ? args.path : ''
}

/**
 * Truncate write content to the first 40 lines or first 2000 characters,
 * whichever cap trips first. `truncated` is honest: true only when something
 * was actually cut.
 */
function buildWritePreview(content: string): { preview: string; truncated: boolean } {
  let preview = content
  let truncated = false

  const lines = preview.split('\n')
  // A trailing newline makes split() yield a phantom empty last element —
  // drop it so exactly-40-lines-plus-newline is not reported as truncated.
  if (lines[lines.length - 1] === '') lines.pop()
  if (lines.length > WRITE_PREVIEW_MAX_LINES) {
    preview = lines.slice(0, WRITE_PREVIEW_MAX_LINES).join('\n')
    truncated = true
  }
  if (preview.length > WRITE_PREVIEW_MAX_CHARS) {
    preview = preview.slice(0, WRITE_PREVIEW_MAX_CHARS)
    truncated = true
  }

  return { preview, truncated }
}

/**
 * Build the confirmation-dialog body for a pending tool confirmation.
 *
 * Args:
 *     toolName: Full (namespaced) tool name from the confirmation frame.
 *     args: Tool arguments from the frame; tolerated null/undefined.
 *
 * Returns:
 *     The `ConfirmationBody` describing how the dialog should render the args.
 */
export function buildConfirmationBody(
  toolName: string,
  args: Record<string, unknown> | null | undefined
): ConfirmationBody {
  if (
    toolName.endsWith('edit_text_file') &&
    args != null &&
    typeof args.old_string === 'string' &&
    typeof args.new_string === 'string'
  ) {
    return {
      mode: 'diff',
      path: pathOf(args),
      rows: computeLineDiff(args.old_string, args.new_string),
      replaceAll: args.replace_all === true
    }
  }

  if (toolName.endsWith('write_text_file') && args != null && typeof args.content === 'string') {
    const { preview, truncated } = buildWritePreview(args.content)
    return { mode: 'write-preview', path: pathOf(args), preview, truncated }
  }

  return { mode: 'args', json: JSON.stringify(args ?? {}, null, 2) }
}

/* ── Tool provenance (tool_meta, spec §6.1) ──
 * Informative only: the operational authority stays with the frame's
 * `riskLevel` — these labels never drive approve/reject behavior. */

/**
 * Origin badge label — `MCP · <server>` for MCP tools, `MCP` when the server
 * name is missing, null for native tools or absent meta.
 */
export function buildMcpBadgeLabel(meta: ToolMeta | undefined): string | null {
  if (meta?.origin !== 'mcp') return null
  return meta.server ? `MCP · ${meta.server}` : 'MCP'
}

/**
 * Transparency warning — null when not needed. Differentiated: a tool without
 * annotations vs a server whose annotations are present but not trusted
 * (`trust_annotations: false`) get a truthful, distinct message. Unknown
 * (absent) flags never warn — only an explicit `false` does.
 */
export function buildFallbackWarning(meta: ToolMeta | undefined): string | null {
  if (meta?.annotated === false) return 'Tool non annotato: trattato come distruttivo'
  if (meta?.trusted === false) return 'Annotazioni non attendibili: trattato come distruttivo'
  return null
}
