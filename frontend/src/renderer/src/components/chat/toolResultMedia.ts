/**
 * toolResultMedia.ts — Pure helpers for rendering tool-result media.
 *
 * The backend registers image tool results as artifacts (kind "image") and the
 * `tool.result` frame carries `artifact_id` + `content_type` into
 * {@link ToolActivity}. This module holds the (Vue-free, unit-testable) logic
 * that maps an activity onto a renderable artifact download URL.
 */

import { BASE_URL } from '../../services/api/http'
import type { ToolActivity } from '../../types/turn'

/** URL dell'immagine artifact di un tool result, o null se non renderizzabile. */
export function toolImageUrl(
  activity: Pick<ToolActivity, 'contentType' | 'artifactId'>
): string | null {
  if (!activity.artifactId) return null
  if (!activity.contentType?.startsWith('image/')) return null
  return `${BASE_URL}/artifacts/${activity.artifactId}/download`
}
