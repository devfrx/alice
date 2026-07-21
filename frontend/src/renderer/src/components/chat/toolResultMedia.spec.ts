/**
 * Unit tests for components/chat/toolResultMedia.ts
 *
 * Pure-function tests (vitest node env, no component mount). They cover the
 * artifact-image URL resolution for tool results: an image content type plus
 * an artifact id yields the download URL, anything else yields null.
 */
import { describe, it, expect } from 'vitest'

import { BASE_URL } from '../../services/api/http'
import { toolImageUrl } from './toolResultMedia'

describe('toolImageUrl', () => {
  it('builds the artifact download URL for an image result with an artifact id', () => {
    expect(toolImageUrl({ contentType: 'image/png', artifactId: 'abc-123' })).toBe(
      `${BASE_URL}/artifacts/abc-123/download`
    )
  })

  it('returns null for a non-image content type even with an artifact id', () => {
    expect(toolImageUrl({ contentType: 'text/plain', artifactId: 'abc-123' })).toBeNull()
  })

  it('returns null for an image content type without an artifact id', () => {
    expect(toolImageUrl({ contentType: 'image/jpeg' })).toBeNull()
  })

  it('returns null when both content type and artifact id are absent', () => {
    expect(toolImageUrl({})).toBeNull()
  })
})
