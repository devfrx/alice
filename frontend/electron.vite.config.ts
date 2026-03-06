import { resolve } from 'path'
import { defineConfig } from 'electron-vite'
import vueDevTools from 'vite-plugin-vue-devtools'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  main: {},
  preload: {},
  renderer: {
    resolve: {
      alias: {
        '@renderer': resolve('src/renderer/src')
      }
    },
    plugins: [vue(),vueDevTools()],
    optimizeDeps: {
      include: ['markdown-it', 'highlight.js/lib/core']
    }
  }
})
