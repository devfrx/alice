/**
 * Unit tests for components/settings/toolPicker.ts
 *
 * Pure-function tests (vitest node env, no component mount) covering the
 * catalog filtering rules of the tool picker (case-insensitive match on
 * name/label/plugin, name-prefix matches ranked before substring matches,
 * alphabetical tie-break, limit cap) and the keyboard-highlight navigation
 * (`moveHighlight` wrap-around).
 */
import { describe, it, expect } from 'vitest'

import type { ToolCatalogEntry } from '../../types/permission'
import { filterCatalog, moveHighlight } from './toolPicker'

/** Minimal catalog entry factory — only `name`/`label`/`plugin` matter here. */
function entry(name: string, label = name, plugin = 'test_plugin'): ToolCatalogEntry {
  return {
    name,
    plugin,
    label,
    description: `${name} description`,
    capabilities: [],
    risk_level: 'safe',
    requires_confirmation: false,
    mcp_server: null
  }
}

describe('filterCatalog', () => {
  const catalog: ToolCatalogEntry[] = [
    entry('write_text_file', 'Scrivi file', 'pc_automation'),
    entry('read_text_file', 'Leggi file', 'pc_automation'),
    entry('run_terminal_command', 'Terminale', 'terminal'),
    entry('search_files', 'Cerca file', 'file_search'),
    entry('web_search', 'Ricerca web', 'web')
  ]

  it('matches case-insensitively on name', () => {
    const out = filterCatalog(catalog, 'RUN_TERM')
    expect(out.map((e) => e.name)).toEqual(['run_terminal_command'])
  })

  it('matches case-insensitively on label', () => {
    const out = filterCatalog(catalog, 'terminale')
    expect(out.map((e) => e.name)).toContain('run_terminal_command')
  })

  it('matches case-insensitively on plugin', () => {
    const out = filterCatalog(catalog, 'pc_automation')
    expect(out.map((e) => e.name).sort()).toEqual(['read_text_file', 'write_text_file'])
  })

  it('ranks name-prefix matches before substring matches', () => {
    // "sea" is a prefix of search_files.name and a substring of web_search.name.
    const out = filterCatalog(catalog, 'sea')
    expect(out.map((e) => e.name)).toEqual(['search_files', 'web_search'])
  })

  it('breaks ties alphabetically by name within each rank', () => {
    const out = filterCatalog(catalog, 'file')
    // No name starts with "file" except none; file_search plugin + names containing "file".
    // All are substring-tier → pure alphabetical order by name.
    expect(out.map((e) => e.name)).toEqual(['read_text_file', 'search_files', 'write_text_file'])
  })

  it('returns the first `limit` entries alphabetically for an empty query', () => {
    const out = filterCatalog(catalog, '')
    expect(out.map((e) => e.name)).toEqual([
      'read_text_file',
      'run_terminal_command',
      'search_files',
      'web_search',
      'write_text_file'
    ])
  })

  it('treats a whitespace-only query as empty', () => {
    const out = filterCatalog(catalog, '   ')
    expect(out.map((e) => e.name)).toEqual([
      'read_text_file',
      'run_terminal_command',
      'search_files',
      'web_search',
      'write_text_file'
    ])
  })

  it('never returns more than `limit` results', () => {
    const many = Array.from({ length: 30 }, (_, i) => entry(`tool_${String(i).padStart(2, '0')}`))
    expect(filterCatalog(many, '', 12)).toHaveLength(12)
    expect(filterCatalog(many, 'tool', 5)).toHaveLength(5)
  })

  it('respects a custom limit smaller than the match count', () => {
    const out = filterCatalog(catalog, 'file', 2)
    expect(out.map((e) => e.name)).toEqual(['read_text_file', 'search_files'])
  })

  it('returns [] when nothing matches', () => {
    expect(filterCatalog(catalog, 'zzz_no_match')).toEqual([])
  })

  it('returns [] on an empty catalog', () => {
    expect(filterCatalog([], 'anything')).toEqual([])
    expect(filterCatalog([], '')).toEqual([])
  })
})

describe('moveHighlight', () => {
  it('moves forward', () => {
    expect(moveHighlight(0, 1, 3)).toBe(1)
    expect(moveHighlight(1, 1, 3)).toBe(2)
  })

  it('moves backward', () => {
    expect(moveHighlight(2, -1, 3)).toBe(1)
  })

  it('wraps forward past the end', () => {
    expect(moveHighlight(2, 1, 3)).toBe(0)
  })

  it('wraps backward past the start', () => {
    expect(moveHighlight(0, -1, 3)).toBe(2)
  })

  it('enters the list from no-highlight (-1): down → first, up → last', () => {
    expect(moveHighlight(-1, 1, 3)).toBe(0)
    expect(moveHighlight(-1, -1, 3)).toBe(2)
  })

  it('returns -1 for an empty list', () => {
    expect(moveHighlight(-1, 1, 0)).toBe(-1)
    expect(moveHighlight(0, -1, 0)).toBe(-1)
  })
})
