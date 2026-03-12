<template>
  <div class="home-view">
    <AmbientBackground state="idle" :audio-level="0" :subtle="true" />

    <div class="home-view__content">
      <!-- Hero Section -->
      <div class="home-view__hero">
        <div class="home-view__logo" aria-hidden="true">
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
            <circle cx="24" cy="24" r="23" stroke="var(--accent)" stroke-width="1" opacity="0.3" />
            <circle cx="24" cy="24" r="16" stroke="var(--accent)" stroke-width="0.5" opacity="0.15" />
            <circle cx="24" cy="24" r="4" fill="var(--accent)" opacity="0.6" />
            <circle cx="24" cy="24" r="2" fill="var(--accent)" />
          </svg>
        </div>
        <h1 class="home-view__title">O.M.N.I.A.</h1>
        <p class="home-view__subtitle">Il tuo assistente IA personale</p>
      </div>

      <!-- Mode Cards -->
      <div class="home-view__modes">
        <button class="mode-card" :class="{ 'mode-card--active': uiStore.mode === 'assistant' }"
          @click="selectMode('assistant')">
          <div class="mode-card__icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="12" cy="12" r="10" />
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v4M12 18v4M2 12h4M18 12h4" opacity="0.3" />
            </svg>
          </div>
          <div class="mode-card__text">
            <h3 class="mode-card__title">Assistente</h3>
            <p class="mode-card__desc">Interazione vocale con visualizzazione IA</p>
          </div>
          <span class="mode-card__indicator" />
        </button>

        <button class="mode-card" :class="{ 'mode-card--active': uiStore.mode === 'hybrid' }"
          @click="selectMode('hybrid')">
          <div class="mode-card__icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <rect x="3" y="3" width="18" height="14" rx="2" />
              <path d="M7 21h10M12 17v4" opacity="0.4" />
              <circle cx="12" cy="10" r="2" />
            </svg>
          </div>
          <div class="mode-card__text">
            <h3 class="mode-card__title">Ibrido</h3>
            <p class="mode-card__desc">Chat testuale con presenza IA ambientale</p>
          </div>
          <span class="mode-card__indicator" />
        </button>
      </div>

      <!-- Start Button -->
      <button class="home-view__start" @click="start">
        Inizia
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>

      <!-- Keyboard Shortcut Hint -->
      <p class="home-view__hint">
        Premi <kbd>Invio</kbd> per iniziare
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
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

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter') {
    e.preventDefault()
    start()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.home-view {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  background: var(--surface-0);
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

/* ── Hero ──────────────────── */
.home-view__hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
}

.home-view__logo {
  opacity: 0.7;
}

.home-view__title {
  font-size: 2.2rem;
  letter-spacing: 0.3em;
  font-weight: var(--weight-light);
  color: var(--text-primary);
  line-height: 1;
}

.home-view__subtitle {
  font-size: var(--text-sm);
  color: var(--text-muted);
  letter-spacing: var(--tracking-wide);
}

/* ── Mode Cards ───────────── */
.home-view__modes {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 340px;
}

.mode-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
  position: relative;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.mode-card:hover {
  background: var(--surface-hover);
  border-color: var(--border-hover);
}

.mode-card--active {
  border-color: var(--accent-border);
  background: var(--surface-selected);
  color: var(--text-primary);
}

.mode-card--active .mode-card__icon {
  color: var(--accent);
}

.mode-card--active .mode-card__indicator {
  opacity: 1;
  transform: scale(1);
}

.mode-card__icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: var(--radius-md);
  background: var(--surface-2);
  color: var(--text-muted);
  transition: color var(--transition-fast), background var(--transition-fast);
}

.mode-card--active .mode-card__icon {
  background: var(--accent-dim);
}

.mode-card__text {
  flex: 1;
  min-width: 0;
}

.mode-card__title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: inherit;
  line-height: var(--leading-tight);
}

.mode-card__desc {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  line-height: var(--leading-snug);
  margin-top: 2px;
}

.mode-card__indicator {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
  opacity: 0;
  transform: scale(0);
  transition: opacity var(--transition-fast), transform var(--transition-fast);
}

/* ── Start Button ─────────── */
.home-view__start {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2-5) var(--space-6);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-pill);
  background: var(--accent-dim);
  color: var(--accent);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  letter-spacing: var(--tracking-wide);
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast);
}

.home-view__start:hover {
  background: var(--accent-light);
  border-color: var(--accent);
}

.home-view__start:active {
  transform: scale(0.97);
}

/* ── Hint ──────────────────── */
.home-view__hint {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  opacity: 0.5;
}

.home-view__hint kbd {
  display: inline-block;
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-radius: var(--radius-xs);
  background: var(--surface-2);
  font-family: var(--font-sans);
  font-size: var(--text-2xs);
  line-height: 1.4;
}
</style>
