/**
 * Application router.
 *
 * Concerns are split:
 * - **Wiring layer** (MODE_ROUTES sync, lazy-import retry) — owned by the
 *   wiring/auth agent. Stable; only audit tweaks.
 * - **UX layer** (route meta, scrollBehavior, document.title, page transition)
 *   — owned by the frontend/layout agent.
 *
 * Route `meta` contract:
 *   - `title`    string — human-readable page title, used as the window title
 *                         suffix ("<Title> — AL\\CE"). Also usable as a
 *                         fallback aria-label by views.
 *   - `transition` string — transition name for the <router-view> wrapper.
 *                           Defaults to `DEFAULT_PAGE_TRANSITION` if missing.
 *
 * Deep-link routes:
 *   - `/notes/:id?` — optional note id, consumed by NotesPageView.
 *   - `/email/:id?` — optional email uid, consumed by EmailPageView.
 *   - `/calendar`   — optional `?date=YYYY-MM-DD` query (delegated to the
 *                     CalendarView component).
 */
import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteLocationNormalized, RouterScrollBehavior } from 'vue-router'
import { useUIStore, type UIMode } from '../stores/ui'

/** Route names that correspond to a UI mode. */
const MODE_ROUTES = new Set<string>(['assistant', 'hybrid'])

/** Window-title suffix shared by every page. */
const TITLE_SUFFIX = 'AL\\CE'

/** Default transition name when route meta does not specify one. */
export const DEFAULT_PAGE_TRANSITION = 'page-fade'

/**
 * Scroll behavior:
 * - Restore saved position on browser back/forward (native UX).
 * - Same-path navigation (hash-only / query-only) keeps current scroll so
 *   in-view tab switches and anchor changes are not hijacked.
 * - Otherwise scroll to top; honour `prefers-reduced-motion`.
 */
const scrollBehavior: RouterScrollBehavior = (to, from, savedPosition) => {
  if (savedPosition) return savedPosition
  if (to.path === from.path) return false
  const prefersReducedMotion =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
  return { top: 0, left: 0, behavior: prefersReducedMotion ? 'auto' : 'smooth' }
}

const router = createRouter({
  history: createWebHashHistory(),
  scrollBehavior,
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../views/HomeView.vue'),
      meta: { title: 'Home', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/assistant',
      name: 'assistant',
      component: () => import('../views/AssistantView.vue'),
      meta: { title: 'Assistente', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/hybrid',
      name: 'hybrid',
      component: () => import('../views/HybridView.vue'),
      meta: { title: 'Ibrido', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/calendar',
      name: 'calendar',
      component: () => import('../views/CalendarPageView.vue'),
      meta: { title: 'Calendario', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue'),
      meta: { title: 'Impostazioni', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/notes/:id?',
      name: 'notes',
      component: () => import('../views/NotesPageView.vue'),
      props: true,
      meta: { title: 'Note', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/email/:id?',
      name: 'email',
      component: () => import('../views/EmailPageView.vue'),
      props: true,
      meta: { title: 'Email', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/whiteboard',
      name: 'whiteboard',
      component: () => import('../views/WhiteboardPageView.vue'),
      meta: { title: 'Lavagna', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/assistant'
    }
  ]
})

// Keep UI mode store in sync with the current route.
// This ensures that navigating via sidebar <router-link>, browser back/forward,
// or programmatic router.push all update the mode — not just the ModeSwitcher.
router.afterEach((to) => {
  const name = to.name as string | undefined
  if (name && MODE_ROUTES.has(name)) {
    const uiStore = useUIStore()
    if (uiStore.mode !== name) {
      uiStore.setMode(name as UIMode)
    }
  }
})

// Mirror the active route meta into the window/document title so the Electron
// window chrome stays in sync with in-app navigation.
router.afterEach((to: RouteLocationNormalized) => {
  const title = (to.meta?.title as string | undefined)?.trim()
  document.title = title ? `${title} — ${TITLE_SUFFIX}` : TITLE_SUFFIX
})

// Retry failed dynamic imports once (handles Vite HMR / dep optimisation races).
const retriedPaths = new Set<string>()
router.onError((error, to) => {
  if (
    error.message.includes('Failed to fetch dynamically imported module') &&
    !retriedPaths.has(to.fullPath)
  ) {
    retriedPaths.add(to.fullPath)
    router.replace(to.fullPath)
  }
})

export default router
