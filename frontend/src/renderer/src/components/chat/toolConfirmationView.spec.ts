/**
 * Unit tests for components/chat/toolConfirmationView.ts
 *
 * Pure-function tests (vitest node env, no component mount). Cover the three
 * body modes (diff / write-preview / args), suffix-based tool-name matching,
 * the malformed-args fallbacks, and the honest write-preview truncation
 * (40-line and 2000-char caps).
 */
import { describe, it, expect } from 'vitest'

import { buildConfirmationBody } from './toolConfirmationView'

describe('buildConfirmationBody', () => {
  describe('diff mode (edit_text_file)', () => {
    it('edit with old_string/new_string strings -> diff body', () => {
      const body = buildConfirmationBody('file_search_edit_text_file', {
        path: 'C:/tmp/a.txt',
        old_string: 'a\nold\nc',
        new_string: 'a\nnew\nc'
      })
      expect(body).toEqual({
        mode: 'diff',
        path: 'C:/tmp/a.txt',
        replaceAll: false,
        rows: [
          { kind: 'context', text: 'a' },
          { kind: 'removed', text: 'old' },
          { kind: 'added', text: 'new' },
          { kind: 'context', text: 'c' }
        ]
      })
    })

    it('matches by suffix, so a renamed namespace still previews', () => {
      const body = buildConfirmationBody('other_ns_edit_text_file', {
        old_string: 'x',
        new_string: 'y'
      })
      expect(body.mode).toBe('diff')
    })

    it('replace_all: true -> replaceAll flag set', () => {
      const body = buildConfirmationBody('file_search_edit_text_file', {
        path: 'p',
        old_string: 'x',
        new_string: 'y',
        replace_all: true
      })
      expect(body).toMatchObject({ mode: 'diff', replaceAll: true })
    })

    it('non-boolean replace_all is not treated as true', () => {
      const body = buildConfirmationBody('file_search_edit_text_file', {
        old_string: 'x',
        new_string: 'y',
        replace_all: 'yes'
      })
      expect(body).toMatchObject({ mode: 'diff', replaceAll: false })
    })

    it('missing path -> empty string path', () => {
      const body = buildConfirmationBody('file_search_edit_text_file', {
        old_string: 'x',
        new_string: 'y'
      })
      expect(body).toMatchObject({ mode: 'diff', path: '' })
    })

    it('non-string path -> empty string path', () => {
      const body = buildConfirmationBody('file_search_edit_text_file', {
        path: 42,
        old_string: 'x',
        new_string: 'y'
      })
      expect(body).toMatchObject({ mode: 'diff', path: '' })
    })

    it('CRLF old_string passes through computeLineDiff normalization (no \\r in rows)', () => {
      const body = buildConfirmationBody('file_search_edit_text_file', {
        old_string: 'a\r\nold',
        new_string: 'a\nnew'
      })
      expect(body).toMatchObject({
        mode: 'diff',
        rows: [
          { kind: 'context', text: 'a' },
          { kind: 'removed', text: 'old' },
          { kind: 'added', text: 'new' }
        ]
      })
    })

    it('edit without old_string -> args fallback', () => {
      const body = buildConfirmationBody('file_search_edit_text_file', {
        path: 'p',
        new_string: 'y'
      })
      expect(body).toEqual({
        mode: 'args',
        json: JSON.stringify({ path: 'p', new_string: 'y' }, null, 2)
      })
    })

    it('non-string old_string (number) -> args fallback', () => {
      const body = buildConfirmationBody('file_search_edit_text_file', {
        old_string: 7,
        new_string: 'y'
      })
      expect(body.mode).toBe('args')
    })

    it('non-string new_string -> args fallback', () => {
      const body = buildConfirmationBody('file_search_edit_text_file', {
        old_string: 'x',
        new_string: null
      })
      expect(body.mode).toBe('args')
    })
  })

  describe('write-preview mode (write_text_file)', () => {
    it('write with string content -> write-preview body, untruncated', () => {
      const body = buildConfirmationBody('file_search_write_text_file', {
        path: 'C:/tmp/b.txt',
        content: 'hello\nworld'
      })
      expect(body).toEqual({
        mode: 'write-preview',
        path: 'C:/tmp/b.txt',
        preview: 'hello\nworld',
        truncated: false
      })
    })

    it('matches by suffix, so a renamed namespace still previews', () => {
      const body = buildConfirmationBody('other_ns_write_text_file', { content: 'x' })
      expect(body.mode).toBe('write-preview')
    })

    it('50 short lines -> first 40 lines, truncated true', () => {
      const lines = Array.from({ length: 50 }, (_, i) => `line ${i}`)
      const body = buildConfirmationBody('file_search_write_text_file', {
        path: 'p',
        content: lines.join('\n')
      })
      expect(body.mode).toBe('write-preview')
      if (body.mode !== 'write-preview') return
      expect(body.truncated).toBe(true)
      expect(body.preview).toBe(lines.slice(0, 40).join('\n'))
    })

    it('single 3000-char line -> first 2000 chars, truncated true', () => {
      const body = buildConfirmationBody('file_search_write_text_file', {
        path: 'p',
        content: 'x'.repeat(3000)
      })
      expect(body.mode).toBe('write-preview')
      if (body.mode !== 'write-preview') return
      expect(body.truncated).toBe(true)
      expect(body.preview).toBe('x'.repeat(2000))
    })

    it('exactly 40 lines and under 2000 chars -> not truncated', () => {
      const content = Array.from({ length: 40 }, (_, i) => `l${i}`).join('\n')
      const body = buildConfirmationBody('file_search_write_text_file', { content })
      expect(body).toMatchObject({ mode: 'write-preview', preview: content, truncated: false })
    })

    it('exactly 40 lines WITH trailing newline -> not truncated, preview unchanged', () => {
      const content = Array.from({ length: 40 }, (_, i) => `l${i}`).join('\n') + '\n'
      const body = buildConfirmationBody('file_search_write_text_file', { content })
      expect(body).toMatchObject({ mode: 'write-preview', preview: content, truncated: false })
    })

    it('41 lines with trailing newline -> first 40 lines, truncated true', () => {
      const lines = Array.from({ length: 41 }, (_, i) => `l${i}`)
      const body = buildConfirmationBody('file_search_write_text_file', {
        content: lines.join('\n') + '\n'
      })
      expect(body).toMatchObject({
        mode: 'write-preview',
        preview: lines.slice(0, 40).join('\n'),
        truncated: true
      })
    })

    it('write without content -> args fallback', () => {
      const body = buildConfirmationBody('file_search_write_text_file', { path: 'p' })
      expect(body).toEqual({ mode: 'args', json: JSON.stringify({ path: 'p' }, null, 2) })
    })

    it('non-string content -> args fallback', () => {
      const body = buildConfirmationBody('file_search_write_text_file', {
        path: 'p',
        content: ['a', 'b']
      })
      expect(body.mode).toBe('args')
    })
  })

  describe('args mode (everything else)', () => {
    it('unrelated tool -> pretty-printed JSON of args', () => {
      const args = { url: 'https://example.com', depth: 2 }
      expect(buildConfirmationBody('web_search_fetch', args)).toEqual({
        mode: 'args',
        json: JSON.stringify(args, null, 2)
      })
    })

    it('null args -> "{}"', () => {
      expect(buildConfirmationBody('anything', null)).toEqual({ mode: 'args', json: '{}' })
    })

    it('undefined args -> "{}"', () => {
      expect(buildConfirmationBody('anything', undefined)).toEqual({ mode: 'args', json: '{}' })
    })

    it('edit-suffixed tool with null args -> args fallback, not diff', () => {
      expect(buildConfirmationBody('file_search_edit_text_file', null)).toEqual({
        mode: 'args',
        json: '{}'
      })
    })

    it('tool name merely containing (not ending with) the suffix -> args', () => {
      const body = buildConfirmationBody('edit_text_file_extra', {
        old_string: 'x',
        new_string: 'y'
      })
      expect(body.mode).toBe('args')
    })
  })
})
