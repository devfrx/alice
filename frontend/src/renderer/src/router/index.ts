/**
 * Application router.
 *
 * Route `meta` contract:
 *   - `title`    string — human-readable page title, used as the window title
 *                         suffix ("<Title> — AL\\CE"). Also usable as a
 *                         fallback aria-label by views.
 *   - `transition` string — transition name for the <router-view> wrapper.
 *                           Defaults to `DEFAULT_PAGE_TRANSITION` if missing.
 *
 * Deep-link routes:
 *   - `/email/:id?` — optional email uid, consumed by EmailPageView.
 *   - `/calendar`   — optional `?date=YYYY-MM-DD` query (delegated to the
 *                     CalendarView component).
 *
 * Since Fase 6 Horizon (`/assistant`) is the only chat surface: the retired
 * Workspace/Hybrid routes redirect there so old deep links keep resolving.
 */
import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteLocationNormalized, RouterScrollBehavior } from 'vue-router'

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
      redirect: '/assistant'
    },
    {
      // Legacy named redirect: keeps old `#/home` deep links and
      // `{ name: 'home' }` fallbacks resolving to the primary surface.
      path: '/home',
      name: 'home',
      redirect: '/assistant'
    },
    {
      // Workspace retired (Fase 6) — Horizon is the only chat surface.
      path: '/workspace',
      redirect: '/assistant'
    },
    {
      path: '/assistant',
      name: 'assistant',
      component: () => import('../views/HorizonView.vue'),
      meta: { title: 'Assistente', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      // HybridView retired — redirect to the primary surface.
      path: '/hybrid',
      redirect: '/assistant'
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
      path: '/board',
      name: 'board',
      component: () => import('../views/ArtifactBoardView.vue'),
      meta: { title: 'Bacheca', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/terminal',
      name: 'terminal',
      component: () => import('../views/TerminalPageView.vue'),
      meta: { title: 'Terminale', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/services',
      name: 'services',
      component: () => import('../views/ServicesView.vue'),
      meta: { title: 'Servizi', transition: DEFAULT_PAGE_TRANSITION }
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/assistant'
    }
  ]
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
