import { resolve } from 'path'
import { defineConfig } from 'electron-vite'
import vueDevTools from 'vite-plugin-vue-devtools'
import react from '@vitejs/plugin-react'
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
    plugins: [react(), vue(), vueDevTools()],
    optimizeDeps: {
      include: ['markdown-it', 'highlight.js/lib/core', 'react', 'react-dom']
    }
  }
})
