import { createRouter, createWebHashHistory } from 'vue-router'
import { useUIStore, type UIMode } from '../stores/ui'

/** Route names that correspond to a UI mode. */
const MODE_ROUTES = new Set<string>(['assistant', 'hybrid'])

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../views/HomeView.vue')
    },
    {
      path: '/assistant',
      name: 'assistant',
      component: () => import('../views/AssistantView.vue')
    },
    {
      path: '/hybrid',
      name: 'hybrid',
      component: () => import('../views/HybridView.vue')
    },
    {
      path: '/calendar',
      name: 'calendar',
      component: () => import('../views/CalendarPageView.vue')
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue')
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
