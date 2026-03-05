import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../views/HomeView.vue')
    },
    {
      path: '/chat',
      name: 'chat',
      component: () => import('../views/ChatView.vue')
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue')
    }
  ]
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
