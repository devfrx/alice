<script setup lang="ts">
import { ref, computed } from 'vue'
import { api } from '../../services/api'

interface SearchResult {
  title: string
  url: string
  snippet: string
}

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ close: []; 'use-text': [text: string] }>()

const query = ref('')
const results = ref<SearchResult[]>([])
const loading = ref(false)
const error = ref('')
const scrapedTexts = ref<Record<number, string>>({})
const scrapingMap = ref<Record<number, boolean>>({})
const expandedMap = ref<Record<number, boolean>>({})
const scrapeErrors = ref<Record<number, string>>({})

const resultCount = computed(() => results.value.length)

async function search(): Promise<void> {
  const q = query.value.trim()
  if (!q) return
  loading.value = true
  error.value = ''
  results.value = []
  scrapedTexts.value = {}
  expandedMap.value = {}
  try {
    const res = await api.executePluginTool<SearchResult[]>(
      'web_search', 'web_search', { query: q }
    )
    if (res.success) {
      results.value = res.content
    } else {
      error.value = res.error_message ?? 'Errore durante la ricerca'
    }
  } catch {
    error.value = 'Impossibile contattare il server'
  } finally {
    loading.value = false
  }
}

async function scrape(idx: number, url: string): Promise<void> {
  if (scrapedTexts.value[idx]) {
    expandedMap.value[idx] = !expandedMap.value[idx]
    return
  }
  scrapingMap.value[idx] = true
  delete scrapeErrors.value[idx]
  try {
    const res = await api.executePluginTool<string>(
      'web_search', 'web_scrape', { url }
    )
    if (res.success) {
      scrapedTexts.value[idx] = res.content
      expandedMap.value[idx] = true
    } else {
      scrapeErrors.value[idx] = res.error_message ?? 'Scrape fallito'
    }
  } catch (err) {
    console.error('Scrape failed:', err)
    scrapeErrors.value[idx] = 'Impossibile eseguire lo scrape'
  } finally {
    delete scrapingMap.value[idx]
  }
}

function openUrl(url: string): void {
  try {
    const parsed = new URL(url)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      window.open(url, '_blank')
    }
  } catch {
    // Invalid URL, ignore
  }
}
</script>

<template>
  <Transition name="panel-slide">
    <aside v-if="visible" class="search-panel">
      <header class="search-panel__header">
        <span class="search-panel__title">
          🔍 Web Search
          <span v-if="resultCount" class="search-panel__badge">{{ resultCount }}</span>
        </span>
        <button class="search-panel__close" @click="emit('close')">✕</button>
      </header>

      <div class="search-panel__input-wrap">
        <input v-model="query" class="search-panel__input" type="text" placeholder="Cerca sul web..."
          @keydown.enter="search" />
      </div>

      <div class="search-panel__body">
        <!-- Loading -->
        <div v-if="loading" class="search-panel__status">
          <span class="search-panel__spinner" />Ricerca in corso…
        </div>

        <!-- Error -->
        <div v-else-if="error" class="search-panel__status search-panel__status--error">
          ⚠️ {{ error }}
        </div>

        <!-- Empty -->
        <div v-else-if="!results.length" class="search-panel__status">
          Cerca qualcosa…
        </div>

        <!-- Results -->
        <div v-else class="search-panel__results">
          <article v-for="(r, i) in results" :key="i" class="search-panel__card">
            <a class="search-panel__card-title" @click.prevent="openUrl(r.url)">
              {{ r.title }}
            </a>
            <span class="search-panel__card-url">{{ r.url }}</span>
            <p class="search-panel__card-snippet">{{ r.snippet }}</p>
            <div class="search-panel__card-actions">
              <button class="search-panel__btn" :disabled="!!scrapingMap[i]" @click="scrape(i, r.url)">
                {{ scrapingMap[i] ? '⏳' : expandedMap[i] ? '▼ Chiudi' : '📄 Scrape' }}
              </button>
              <button v-if="scrapedTexts[i]" class="search-panel__btn search-panel__btn--accent"
                @click="emit('use-text', scrapedTexts[i])">
                ➜ Usa in chat
              </button>
            </div>
            <div v-if="scrapeErrors[i]" class="search-panel__scrape-error">
              ⚠️ {{ scrapeErrors[i] }}
            </div>
            <Transition name="scrape-expand">
              <pre v-if="expandedMap[i] && scrapedTexts[i]" class="search-panel__scraped">{{ scrapedTexts[i] }}</pre>
            </Transition>
          </article>
        </div>
      </div>
    </aside>
  </Transition>
</template>

<style scoped>
.search-panel {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: 360px;
  display: flex;
  flex-direction: column;
  background: var(--bg-primary);
  border-left: 1px solid var(--border);
  z-index: var(--z-dropdown);
  color: var(--text-primary);
  font-size: 13px;
}

.search-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
}

.search-panel__title {
  font-weight: 600;
  font-size: 14px;
}

.search-panel__badge {
  margin-left: 6px;
  padding: 1px 7px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
  background: var(--accent);
  color: var(--bg-primary);
}

.search-panel__close {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 16px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
}

.search-panel__close:hover {
  background: rgba(255, 255, 255, 0.08);
}

.search-panel__input-wrap {
  padding: 10px 14px 6px;
}

.search-panel__input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 13px;
  outline: none;
}

.search-panel__input:focus {
  border-color: var(--accent);
}

.search-panel__body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 14px;
}

.search-panel__status {
  text-align: center;
  padding: 32px 0;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

.search-panel__status--error {
  color: var(--accent);
}

.search-panel__spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid var(--text-secondary);
  border-top-color: transparent;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.search-panel__results {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.search-panel__card {
  padding: 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  transition: border-color 0.15s;
}

.search-panel__card:hover {
  border-color: var(--accent);
}

.search-panel__card-title {
  font-weight: 600;
  color: var(--accent);
  cursor: pointer;
  text-decoration: none;
  display: block;
  margin-bottom: 2px;
  line-height: 1.3;
}

.search-panel__card-title:hover {
  text-decoration: underline;
}

.search-panel__card-url {
  display: block;
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 4px;
}

.search-panel__card-snippet {
  margin: 0;
  font-size: 12px;
  color: var(--text-secondary);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.search-panel__card-actions {
  display: flex;
  gap: 6px;
  margin-top: 8px;
}

.search-panel__btn {
  padding: 3px 8px;
  border-radius: 4px;
  border: none;
  font-size: 11px;
  background: var(--bg-tertiary);
  color: var(--text-primary);
  cursor: pointer;
  transition: opacity 0.15s;
}

.search-panel__btn:hover {
  opacity: 0.8;
}

.search-panel__btn:disabled {
  opacity: 0.5;
  cursor: wait;
}

.search-panel__btn--accent {
  background: var(--accent);
  color: var(--bg-primary);
}

.search-panel__scrape-error {
  margin-top: 6px;
  font-size: 11px;
  color: var(--accent);
}

.search-panel__scraped {
  margin: 8px 0 0;
  padding: 8px;
  border-radius: 4px;
  background: var(--bg-primary);
  font-size: 11px;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--text-secondary);
}

/* Slide transition */
.panel-slide-enter-active,
.panel-slide-leave-active {
  transition: transform 0.2s ease;
}

.panel-slide-enter-from,
.panel-slide-leave-to {
  transform: translateX(100%);
}

/* Scrape expand */
.scrape-expand-enter-active,
.scrape-expand-leave-active {
  transition: max-height 0.2s ease, opacity 0.2s;
}

.scrape-expand-enter-from,
.scrape-expand-leave-to {
  max-height: 0;
  opacity: 0;
  overflow: hidden;
}
</style>
