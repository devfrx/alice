<template>
  <div class="home-view">
    <AmbientBackground state="idle" :audio-level="0" :subtle="true" />

    <div class="home-view__content">
      <div class="home-view__header">
        <h1 class="home-view__title">O.M.N.I.A.</h1>
        <p class="home-view__subtitle">Orchestrated Modular Network for Intelligent Automation</p>
      </div>

      <div class="home-view__modes">
        <button class="mode-card" :class="{ 'mode-card--active': uiStore.mode === 'assistant' }"
          @click="selectMode('assistant')">
          <div class="mode-card__icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="12" r="10" />
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" opacity="0.4" />
            </svg>
          </div>
          <h3 class="mode-card__title">Assistente</h3>
          <p class="mode-card__desc">Interazione vocale con visualizzazione IA</p>
        </button>

        <button class="mode-card" :class="{ 'mode-card--active': uiStore.mode === 'hybrid' }"
          @click="selectMode('hybrid')">
          <div class="mode-card__icon">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="8" r="6" />
              <path d="M21 20a2 2 0 0 1-2 2H7l-4 4V16a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" opacity="0.5" />
            </svg>
          </div>
          <h3 class="mode-card__title">Ibrido</h3>
          <p class="mode-card__desc">Chat con presenza IA ambientale</p>
        </button>
      </div>

      <button class="home-view__start" @click="start">
        Inizia
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import AmbientBackground from '../components/assistant/AmbientBackground.vue'
import { useUIStore, type UIMode } from '../stores/ui'

const uiStore = useUIStore()
const router = useRouter()

function selectMode(mode: UIMode): void {
  uiStore.setMode(mode)
}

function start(): void {
  router.push({ name: uiStore.mode })
}
</script>

<style scoped>
.home-view {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-primary);
  overflow: hidden;
}

.home-view__content {
  position: relative;
  z-index: 2;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-8);
}

.home-view__header {
  text-align: center;
}

.home-view__title {
  font-size: var(--text-3xl);
  letter-spacing: var(--tracking-widest);
  font-weight: var(--weight-light);
  text-shadow: var(--accent-text-glow);
  margin-bottom: var(--space-2);
}

.home-view__subtitle {
  font-size: var(--text-md);
  color: var(--text-secondary);
  opacity: 0.6;
}

.home-view__modes {
  display: flex;
  gap: var(--space-4);
}

.mode-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-6) var(--space-8);
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.3s ease;
  min-width: 200px;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.mode-card:hover {
  background: rgba(255, 255, 255, 0.04);
  border-color: var(--border-hover);
  transform: translateY(-2px);
}

.mode-card--active {
  border-color: var(--accent-border);
  background: var(--accent-dim);
  color: var(--text-primary);
  box-shadow: 0 0 20px var(--accent-glow);
}

.mode-card--active .mode-card__icon {
  color: var(--accent);
}

.mode-card__icon {
  color: var(--text-muted);
  transition: color 0.3s;
}

.mode-card__title {
  font-size: var(--text-md);
  font-weight: var(--weight-medium);
  color: inherit;
}

.mode-card__desc {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-align: center;
  max-width: 120px;
  line-height: var(--leading-snug);
}

.home-view__start {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-8);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-pill);
  background: var(--accent-dim);
  color: var(--accent);
  font-size: var(--text-md);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition: all 0.3s ease;
  letter-spacing: var(--tracking-wide);
}

.home-view__start:hover {
  background: var(--accent-light);
  border-color: var(--accent);
  box-shadow: 0 0 24px var(--accent-glow);
  transform: translateY(-1px);
}
</style>
