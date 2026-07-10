/**
 * Shared HTTP core for the per-domain REST clients (services/api/<domain>.ts).
 *
 * Owns the backend base URL, the generic `request` wrapper (JSON, timeout,
 * ApiError), URL resolution helpers and the startup readiness gate.
 */

/**
 * Error thrown by {@link request} on a non-2xx HTTP response.
 *
 * Extends the native `Error` so existing callers that catch `Error` or read
 * `.message` are unaffected, while carrying the HTTP `status` so callers that
 * need to branch on it (e.g. detecting a 409 `scope_locked` conflict) can.
 */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

/** Backend host (without /api), configurable via VITE_API_BASE_URL env var.
 *  Default uses 127.0.0.1 (not `localhost`) because on Windows Electron's
 *  fetch resolves `localhost` to ::1 first; the backend binds to 127.0.0.1
 *  only, so IPv6 connections are refused and the startup health probe
 *  would loop forever. */
const BACKEND_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

/** Base URL for all REST calls. */
export const BASE_URL = `${BACKEND_BASE}/api`

/** Backend host root (without /api), used to resolve relative asset URLs. */
export const BACKEND_HOST = BACKEND_BASE

/**
 * Resolve a backend-relative path (e.g. `/uploads/...`) to an absolute URL.
 * Passes through URLs that are already absolute or blob/data URIs.
 * Rejects any path containing URL-encoded traversal sequences.
 */
export function resolveBackendUrl(path: string): string {
  if (!path) return path
  if (
    path.startsWith('http://') ||
    path.startsWith('https://') ||
    path.startsWith('blob:') ||
    path.startsWith('data:')
  ) {
    // Only allow absolute URLs pointing to the known backend host.
    if (path.startsWith('http://') || path.startsWith('https://')) {
      try {
        const url = new URL(path)
        const backend = new URL(BACKEND_HOST)
        if (url.origin !== backend.origin) {
          console.warn('[resolveBackendUrl] Rejected external URL:', path)
          return ''
        }
      } catch {
        return ''
      }
    }
    return path
  }
  // Reject path traversal attempts
  if (path.includes('..')) {
    console.warn('[resolveBackendUrl] Rejected path traversal:', path)
    return ''
  }
  return `${BACKEND_HOST}${path.startsWith('/') ? '' : '/'}${path}`
}

/** Default HTTP request timeout (ms). Long enough for slow LLM/model endpoints. */
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000

/**
 * Compose an external AbortSignal with an internal timeout signal.
 * Returns the combined signal plus a cleanup function that clears the timer.
 */
function withTimeout(
  external: AbortSignal | undefined,
  timeoutMs: number,
): { signal: AbortSignal; cleanup: () => void } {
  const ctrl = new AbortController()
  const onAbort = (): void => { ctrl.abort((external as AbortSignal & { reason?: unknown }).reason) }
  if (external) {
    if (external.aborted) ctrl.abort((external as AbortSignal & { reason?: unknown }).reason)
    else external.addEventListener('abort', onAbort, { once: true })
  }
  const timer = setTimeout(() => ctrl.abort(new DOMException('Request timeout', 'TimeoutError')), timeoutMs)
  return {
    signal: ctrl.signal,
    cleanup: () => {
      clearTimeout(timer)
      external?.removeEventListener('abort', onAbort)
    },
  }
}

/**
 * Generic fetch wrapper with JSON parsing, timeout and error handling.
 *
 * @typeParam T - Expected response body type.
 * @param endpoint - Path appended to {@link BASE_URL} (must start with `/`).
 * @param options  - Standard `RequestInit` overrides; pass `signal` for cancellation.
 * @param timeoutMs - Per-request timeout in ms (default {@link DEFAULT_REQUEST_TIMEOUT_MS}).
 * @returns Parsed JSON body cast to `T`.
 * @throws {ApiError} On non-2xx status codes (carries the HTTP `status`).
 * @throws {Error} On network failure, timeout, or abort.
 */
export async function request<T>(
  endpoint: string,
  options?: RequestInit,
  timeoutMs: number = DEFAULT_REQUEST_TIMEOUT_MS,
): Promise<T> {
  const { headers: customHeaders, signal: externalSignal, ...fetchOptions } = options ?? {}
  const isJsonBody = !!fetchOptions.body && typeof fetchOptions.body === 'string'
  const { signal, cleanup } = withTimeout(externalSignal ?? undefined, timeoutMs)
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${endpoint}`, {
      ...fetchOptions,
      signal,
      headers: {
        ...(isJsonBody ? { 'Content-Type': 'application/json' } : {}),
        ...(customHeaders as Record<string, string>)
      }
    })
  } finally {
    cleanup()
  }

  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new ApiError(response.status, `API Error ${response.status}: ${response.statusText} — ${body}`)
  }

  if (response.status === 204 || response.headers.get('content-length') === '0') {
    return undefined as T
  }

  return response.json()
}

// ---------------------------------------------------------------------------
// Backend readiness gate
// ---------------------------------------------------------------------------

/**
 * Poll the backend health endpoint until it responds, then resolve.
 * Used at startup to gate all API/WS connections until the server is up.
 *
 * @param intervalMs - Polling interval in milliseconds (default 1 s).
 * @param signal - Optional AbortSignal for cancellation.
 * @returns `true` once the backend is reachable.
 */
export async function waitForBackend(
  intervalMs = 1000,
  signal?: AbortSignal,
): Promise<boolean> {
  while (!signal?.aborted) {
    try {
      const res = await fetch(`${BASE_URL}/health`, { signal })
      if (res.ok) return true
    } catch {
      // Backend not up yet — continue polling
    }
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, intervalMs)
      signal?.addEventListener('abort', () => { clearTimeout(timer); resolve() }, { once: true })
    })
  }
  return false
}
