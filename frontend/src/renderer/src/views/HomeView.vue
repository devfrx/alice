<template>
  <div class="home-view" aria-label="Home">
    <header class="home-view__landing-header" aria-label="Brand">
      <div class="home-view__brand-lockup">
        <span class="home-view__brand-word">
          <BrandWordmark brand="alce" />
        </span>
      </div>
    </header>

    <main class="home-view__intro" aria-label="Intro">
      <span class="home-view__ghost home-view__ghost--alce" aria-hidden="true">
        <BrandWordmark brand="alce" />
      </span>

      <section class="home-view__copy" aria-label="Alice">
        <p class="home-view__kicker">01 / local runtime / private memory</p>

        <h1 class="home-view__title" aria-label="AL\CE">
          <span class="home-view__title-line">
            <BrandWordmark brand="alce" />
          </span>
        </h1>

        <p class="home-view__lede">
          Agente locale per modello, strumenti, voce e memoria. Alice lavora sullo stesso
          computer dei tuoi file.
        </p>

        <div class="home-view__actions" aria-label="Avvio">
          <div class="home-view__mode-toggle" role="radiogroup" aria-label="Modalita">
            <button v-for="option in modeOptions" :key="option.mode" class="home-view__mode-btn"
              :class="{ 'home-view__mode-btn--active': uiStore.mode === option.mode }" type="button" role="radio"
              :aria-checked="uiStore.mode === option.mode" @click="selectMode(option.mode)">
              <span class="home-view__mode-icon">
                <AppIcon :name="option.icon" :size="15" />
              </span>
              <span>{{ option.label }}</span>
            </button>
          </div>

          <button class="home-view__start" type="button" @click="start">
            <span>{{ startLabel }}</span>
            <AppIcon name="chevron-right" :size="13" />
          </button>
        </div>
      </section>

      <figure class="home-view__portrait" aria-hidden="true">
        <img :src="aliceImageUrl" alt="" decoding="async" />
      </figure>

      <ol class="home-view__ledger" aria-label="Capacita">
        <li v-for="(capability, index) in capabilities" :key="capability.label" class="home-view__ledger-entry">
          <span class="home-view__ledger-index">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="home-view__ledger-dot" aria-hidden="true" />
          <span class="home-view__ledger-text">
            <span class="home-view__ledger-label">{{ capability.label }}</span>
            <span class="home-view__ledger-detail">{{ capability.detail }}</span>
          </span>
        </li>
      </ol>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import BrandWordmark from '../components/branding/BrandWordmark.vue'
import AppIcon from '../components/ui/AppIcon.vue'
import type { AppIconName } from '../assets/icons'
import { useUIStore, type UIMode } from '../stores/ui'

const uiStore = useUIStore()
const router = useRouter()
const aliceImageUrl = new URL('../assets/logos/brand/alice_header.png', import.meta.url).href

interface ModeOption {
  mode: UIMode
  label: string
  icon: AppIconName
}

interface Capability {
  label: string
  detail: string
}

const modeOptions: ModeOption[] = [
  { mode: 'assistant', label: 'Assistente', icon: 'orb' },
  { mode: 'hybrid', label: 'Ibrido', icon: 'hybrid-panel' },
]

const capabilities: Capability[] = [
  { label: 'Modello locale', detail: 'LM Studio / streaming' },
  { label: 'Tool loop', detail: 'plugin / MCP / desktop' },
  { label: 'Voce', detail: 'STT / TTS locali' },
  { label: 'Memoria', detail: 'note / file / embeddings' },
  { label: 'Output', detail: 'CAD / grafici / lavagna' },
]

const startLabel = computed(() =>
  uiStore.mode === 'assistant' ? 'Apri Assistente' : 'Apri Ibrido',
)

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
  --home-portrait: url('../assets/logos/brand/alice_header.png');

  position: relative;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  width: 100%;
  height: 100%;
  padding: var(--space-6) var(--space-8) var(--space-8);
  background: var(--surface-0);
  color: var(--text-primary);
  overflow: hidden;
}

.home-view::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: var(--z-base);
  background:
    repeating-linear-gradient(90deg,
      transparent 0,
      transparent 9.5rem,
      var(--white-faint) 9.5rem,
      var(--white-faint) calc(9.5rem + 1px)),
    linear-gradient(to right, var(--surface-0) 16%, transparent 64%, var(--surface-0) 100%);
  opacity: 0.52;
  pointer-events: none;
}

.home-view::after {
  content: '';
  position: absolute;
  inset: auto 0 0;
  z-index: var(--z-base);
  height: 36%;
  background: linear-gradient(to bottom, transparent, var(--surface-0));
  pointer-events: none;
}

.home-view__landing-header {
  position: relative;
  z-index: var(--z-sticky);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  pointer-events: none;
}

.home-view__landing-header>* {
  pointer-events: auto;
}

.home-view__brand-lockup {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-primary);
  font-size: var(--text-md);
  line-height: 1;
  opacity: 0.86;
}

.home-view__brand-word {
  display: inline-flex;
}

.home-view__intro {
  position: relative;
  z-index: var(--z-raised);
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 0.62fr);
  grid-template-areas:
    'copy portrait'
    'ledger ledger';
  align-content: center;
  column-gap: clamp(var(--space-8), 5vw, var(--space-16));
  row-gap: clamp(var(--space-6), 5vh, var(--space-10));
  min-height: 0;
  width: min(var(--content-width-xl), 100%);
  margin-inline: auto;
  padding-block: clamp(var(--space-8), 7vh, var(--space-14)) 0;
}

.home-view__ghost {
  position: absolute;
  z-index: -1;
  display: inline-flex;
  color: var(--text-primary);
  line-height: 1;
  pointer-events: none;
  opacity: 0.04;
  white-space: nowrap;
}

.home-view__ghost--alce {
  top: -2vh;
  left: 18%;
  font-size: clamp(7rem, 17vw, 14rem);
  transform: translateX(-12%);
}

.home-view__copy {
  grid-area: copy;
  position: relative;
  z-index: 4;
  align-self: center;
  display: grid;
  gap: var(--space-5);
  max-width: 820px;
}

.home-view__kicker {
  margin: 0;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  letter-spacing: var(--tracking-wider);
  line-height: var(--leading-tight);
  text-transform: uppercase;
}

.home-view__title {
  display: grid;
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: clamp(5.8rem, 15vw, 12rem);
  font-weight: var(--weight-semibold);
  letter-spacing: 0;
  line-height: 0.82;
}

.home-view__title-line {
  display: block;
}

.home-view__lede {
  max-width: 34rem;
  margin: 0;
  color: var(--text-secondary);
  font-size: clamp(var(--text-md), 1.55vw, var(--text-xl));
  line-height: var(--leading-snug);
  letter-spacing: 0;
}

.home-view__actions {
  display: inline-grid;
  grid-template-columns: minmax(240px, 300px) minmax(154px, auto);
  align-items: center;
  gap: var(--space-2);
  width: fit-content;
  max-width: 100%;
}

.home-view__mode-toggle {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: stretch;
  min-width: 0;
  min-height: 42px;
  background: color-mix(in srgb, var(--surface-1) 76%, transparent);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 4px;
  gap: 4px;
  box-shadow: var(--shadow-xs);
}

.home-view__mode-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1-5);
  width: 100%;
  min-width: 0;
  min-height: 32px;
  padding: 0 var(--space-2);
  border: 1px solid transparent;
  border-radius: calc(var(--radius-sm) - 1px);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  cursor: pointer;
  letter-spacing: 0;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast),
    box-shadow var(--transition-fast);
}

.home-view__mode-btn:hover {
  color: var(--text-primary);
}

.home-view__mode-btn:focus-visible {
  outline: none;
}

.home-view__mode-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  color: var(--text-muted);
  transition: color var(--transition-fast);
}

.home-view__mode-btn:hover .home-view__mode-icon {
  color: var(--text-secondary);
}

.home-view__mode-btn--active {
  background: var(--surface-2);
  border-color: color-mix(in srgb, var(--accent-border) 72%, var(--border));
  color: var(--text-primary);
  box-shadow:
    var(--shadow-xs),
    inset 0 1px 0 var(--white-subtle);
}

.home-view__mode-btn--active .home-view__mode-icon {
  color: var(--accent);
}

.home-view__start {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-width: 154px;
  width: 100%;
  min-height: 42px;
  padding: 0 var(--space-4);
  border: 1px solid color-mix(in srgb, var(--accent-border) 82%, var(--border));
  border-radius: var(--radius-sm);
  background: color-mix(in srgb, var(--accent-dim) 72%, var(--surface-2));
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  cursor: pointer;
  letter-spacing: 0;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast);
}

.home-view__start:hover {
  background: color-mix(in srgb, var(--accent-light) 72%, var(--surface-2));
  border-color: var(--border-hover);
  color: var(--accent-hover);
}

.home-view__start:active {
  transform: scale(0.97);
}

.home-view__portrait {
  grid-area: portrait;
  position: relative;
  z-index: 1;
  align-self: stretch;
  justify-self: end;
  width: min(42vw, 540px);
  min-width: 280px;
  min-height: min(56vh, 560px);
  margin: 0;
  overflow: hidden;
  pointer-events: none;
}

.home-view__portrait::before {
  content: '';
  position: absolute;
  inset: 0;
  z-index: 2;
  background:
    linear-gradient(to right, var(--surface-0) 0%, transparent 26%),
    linear-gradient(to bottom, transparent 68%, var(--surface-0) 100%);
}

.home-view__portrait img {
  position: absolute;
  right: -7%;
  top: 50%;
  z-index: 1;
  width: auto;
  height: 108%;
  max-width: none;
  transform: translateY(-50%);
  object-fit: contain;
  filter: grayscale(42%) contrast(1.05) brightness(0.88);
  mix-blend-mode: luminosity;
  opacity: 0.86;
  -webkit-mask-image: linear-gradient(90deg, transparent 0%, #000 18%, #000 80%, transparent 100%);
  mask-image: linear-gradient(90deg, transparent 0%, #000 18%, #000 80%, transparent 100%);
}

.home-view__ledger {
  grid-area: ledger;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.home-view__ledger-entry {
  display: grid;
  grid-template-columns: auto 8px minmax(0, 1fr);
  align-items: start;
  gap: var(--space-2);
  min-height: 92px;
  padding: var(--space-3) var(--space-4);
  border-right: 1px solid var(--border);
}

.home-view__ledger-entry:last-child {
  border-right: none;
}

.home-view__ledger-index {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--text-2xs);
  letter-spacing: var(--tracking-wide);
  line-height: var(--leading-tight);
}

.home-view__ledger-dot {
  width: 6px;
  height: 6px;
  margin-top: 3px;
  border-radius: var(--radius-full);
  background: var(--accent);
}

.home-view__ledger-text {
  display: grid;
  gap: var(--space-1);
  min-width: 0;
}

.home-view__ledger-label {
  color: var(--text-primary);
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--weight-semibold);
  letter-spacing: 0;
  line-height: var(--leading-tight);
}

.home-view__ledger-detail {
  color: var(--text-secondary);
  font-size: var(--text-xs);
  letter-spacing: 0;
  line-height: var(--leading-snug);
}

:global([data-theme='light']) .home-view__portrait img {
  filter: grayscale(24%) contrast(1.02) brightness(1.02);
  mix-blend-mode: multiply;
  opacity: 0.78;
}

@media (max-width: 680px) {
  .home-view {
    padding: var(--space-4) var(--space-5) var(--space-5);
  }

  .home-view__landing-header {
    align-items: flex-start;
  }

  .home-view__intro {
    grid-template-columns: 1fr;
    grid-template-areas:
      'copy'
      'ledger';
    align-content: end;
    row-gap: var(--space-6);
    padding-block: var(--space-8) 0;
  }

  .home-view__ghost--alce {
    top: 2vh;
    left: 0;
  }

  .home-view__title {
    font-size: clamp(3.8rem, 18vw, 6.5rem);
  }

  .home-view__lede {
    max-width: 26rem;
  }

  .home-view__portrait {
    position: absolute;
    right: -28%;
    top: 8%;
    width: min(78vw, 420px);
    min-height: 50vh;
    opacity: 0.3;
  }

  .home-view__actions {
    width: min(360px, 100%);
    grid-template-columns: 1fr;
  }

  .home-view__mode-toggle,
  .home-view__start {
    width: 100%;
  }

  .home-view__mode-btn {
    flex: 1 1 0;
    min-width: 0;
  }

  .home-view__ledger {
    grid-template-columns: 1fr;
  }

  .home-view__ledger-entry {
    min-height: 0;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }

  .home-view__ledger-entry:last-child {
    border-bottom: none;
  }
}

@media (prefers-reduced-motion: reduce) {

  .home-view__start,
  .home-view__mode-btn {
    transition: none;
  }
}
</style>
