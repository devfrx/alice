<template>
  <div class="home-view" aria-label="Home">
    <AmbientBackground state="idle" :audio-level="0" :subtle="true" />

    <div class="home-view__content">
      <!-- Branding -->
      <div class="home-view__brand">
        <h1 class="home-view__title">AL\CE</h1>
        <p class="home-view__tagline">Adaptive Learning Interface for Computing & Execution</p>
      </div>

      <!-- Mode toggle -->
      <div class="home-view__mode-toggle">
        <button class="home-view__mode-btn" :class="{ 'home-view__mode-btn--active': uiStore.mode === 'assistant' }"
          @click="selectMode('assistant')">
          <AppIcon name="orb" :size="16" :stroke-width="1.5" />
          Assistente
        </button>
        <button class="home-view__mode-btn" :class="{ 'home-view__mode-btn--active': uiStore.mode === 'hybrid' }"
          @click="selectMode('hybrid')">
          <AppIcon name="hybrid-home" :size="16" :stroke-width="1.5" />
          Ibrido
        </button>
      </div>

      <!-- Start CTA -->
      <button class="home-view__start" @click="start">
        Inizia
        <AppIcon name="chevron-right" :size="12" :stroke-width="2.5" />
      </button>

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
import AppIcon from '../components/ui/AppIcon.vue'
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
  z-index: var(--z-raised);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-6);
}

/* ── Brand ──────────────────── */
.home-view__brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-1-5);
}

.home-view__title {
  font-family: var(--font-display);
  font-size: clamp(2rem, 5vw, 3rem);
  letter-spacing: 0.3em;
  font-weight: 600;
  color: var(--accent);
  line-height: 1;
}

.home-view__tagline {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  letter-spacing: var(--tracking-wide);
  opacity: 0.6;
}

/* ── Mode toggle (pill) ────── */
.home-view__mode-toggle {
  display: flex;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: 3px;
  gap: 2px;
}

.home-view__mode-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 18px;
  border: none;
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  cursor: pointer;
  letter-spacing: 0.02em;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.home-view__mode-btn:hover {
  color: var(--text-secondary);
}

.home-view__mode-btn--active {
  background: var(--surface-3);
  color: var(--text-primary);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}

.home-view__mode-btn--active svg {
  color: var(--accent);
}

/* ── Start CTA ─────────────── */
.home-view__start {
  display: flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: 7px 28px;
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-pill);
  background: transparent;
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
  background: var(--accent-dim);
  border-color: var(--accent);
}

.home-view__start:active {
  transform: scale(0.97);
}

/* ── Hint ──────────────────── */
.home-view__hint {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  opacity: 0.4;
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
