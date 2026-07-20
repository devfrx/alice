/**
 * Pure-TS line-based diff for the edit-preview confirmation UI.
 *
 * Contract:
 * - Both inputs are normalized `\r\n` -> `\n` BEFORE splitting into lines
 *   (the backend may send a CRLF `old_string`).
 * - The diff is computed with a classic LCS dynamic program over the line
 *   arrays: lines present on both sides (in the LCS) become `context`,
 *   lines only in `oldStr` become `removed`, lines only in `newStr` become
 *   `added`. Rows are emitted in natural diff order — for a changed block
 *   the `removed` lines come before the `added` lines, interleaved with
 *   surrounding `context` rows.
 * - Anti-O(n^2) cap: if EITHER side has more than `MAX_LCS_LINES` lines, the
 *   function skips the DP entirely and falls back to an honest "no context
 *   computed" diff: every old line as `removed`, followed by every new line
 *   as `added`.
 * - Empty-string edge case (deliberate, pinned by tests): `''.split('\n')`
 *   yields `['']`, i.e. one empty line, not zero lines. So
 *   `computeLineDiff('', '')` returns a single `{ kind: 'context', text: '' }`
 *   row rather than an empty array. This is not expected to occur for a real
 *   edit preview (the backend rejects an empty `old_string`), but the module
 *   must never crash on it and the behavior is fixed by a test.
 */

/** One rendered row of the line diff. */
export interface DiffRow {
  kind: 'context' | 'removed' | 'added'
  text: string
}

/** Lines beyond this count, on either side, bypass the O(n*m) LCS DP. */
const MAX_LCS_LINES = 400

/**
 * Normalize CRLF to LF, then split into lines.
 *
 * A lone `\r` (not followed by `\n`) is left untouched by design — it is not
 * a line separator, and treating it as one would diverge from how the
 * backend/editors split `old_string`/`new_string` into lines.
 */
function toLines(value: string): string[] {
  return value.replace(/\r\n/g, '\n').split('\n')
}

/** Full-blocks fallback used when either side exceeds `MAX_LCS_LINES`. */
function fallbackDiff(oldLines: string[], newLines: string[]): DiffRow[] {
  const rows: DiffRow[] = []
  for (const text of oldLines) rows.push({ kind: 'removed', text })
  for (const text of newLines) rows.push({ kind: 'added', text })
  return rows
}

/**
 * Diff two strings line-by-line using LCS, normalizing CRLF first.
 *
 * See the module docstring for the full contract (cap, fallback, and the
 * deliberate empty-string edge case).
 */
export function computeLineDiff(oldStr: string, newStr: string): DiffRow[] {
  const oldLines = toLines(oldStr)
  const newLines = toLines(newStr)

  if (oldLines.length > MAX_LCS_LINES || newLines.length > MAX_LCS_LINES) {
    return fallbackDiff(oldLines, newLines)
  }

  const m = oldLines.length
  const n = newLines.length

  // Classic LCS length table: dp[i][j] = LCS length of oldLines[i..] vs
  // newLines[j..]. (m+1) x (n+1) of numbers; bounded by (MAX_LCS_LINES+1)^2.
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array<number>(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] =
        oldLines[i] === newLines[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  // Backtrack from (0, 0) forward, walking whichever branch the DP took.
  const rows: DiffRow[] = []
  let i = 0
  let j = 0
  while (i < m && j < n) {
    if (oldLines[i] === newLines[j]) {
      rows.push({ kind: 'context', text: oldLines[i] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      // Tie-break: `>=` prefers consuming the old side, so in a changed
      // block all `removed` rows are emitted before the `added` rows
      // (the "removed-first" order promised in the module contract).
      rows.push({ kind: 'removed', text: oldLines[i] })
      i++
    } else {
      rows.push({ kind: 'added', text: newLines[j] })
      j++
    }
  }
  while (i < m) {
    rows.push({ kind: 'removed', text: oldLines[i] })
    i++
  }
  while (j < n) {
    rows.push({ kind: 'added', text: newLines[j] })
    j++
  }

  return rows
}
