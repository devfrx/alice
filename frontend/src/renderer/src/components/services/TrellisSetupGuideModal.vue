<script setup lang="ts">
/**
 * TrellisSetupGuideModal — Inline guide for the Trellis2 build process.
 *
 * Fetches the markdown walkthrough from
 * `GET /api/services/trellis2/setup-guide` (proxied by the
 * `loadTrellisGuide` action) and renders it inside a centred modal.
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useServicesStore } from '../../stores/services'
import { renderMarkdown } from '../../composables/useMarkdown'
import AppIcon from '../ui/AppIcon.vue'

const emit = defineEmits<{ (e: 'close'): void }>()

const store = useServicesStore()
const html = ref('')
const loading = ref(true)
const error = ref<string | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const md = await store.loadTrellisGuide()
    html.value = renderMarkdown(md)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function onKey(ev: KeyboardEvent): void {
  if (ev.key === 'Escape') emit('close')
}

onMounted(() => {
  void load()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <div
    class="guide-modal"
    role="dialog"
    aria-modal="true"
    aria-labelledby="trellis-guide-title"
    @click.self="emit('close')"
  >
    <section class="guide-modal__panel">
      <header class="guide-modal__head">
        <div class="guide-modal__head-left">
          <span class="guide-modal__icon-wrap">
            <AppIcon name="box-3d" :size="16" />
          </span>
          <div class="guide-modal__title-block">
            <h2 id="trellis-guide-title" class="guide-modal__title">
              Setup TRELLIS.2
            </h2>
            <span class="guide-modal__subtitle">
              Guida passo-passo alla compilazione locale
            </span>
          </div>
        </div>
        <button
          class="guide-modal__close"
          type="button"
          aria-label="Chiudi"
          @click="emit('close')"
        >
          <AppIcon name="x" :size="16" />
        </button>
      </header>

      <div class="guide-modal__body">
        <div v-if="loading" class="guide-modal__state">
          <AppIcon name="refresh-cw" :size="16" class="is-spinning" />
          <span>Carico la guida…</span>
        </div>
        <div
          v-else-if="error"
          class="guide-modal__state guide-modal__state--error"
        >
          <AppIcon name="alert-triangle" :size="16" />
          <div class="guide-modal__state-body">
            <strong>Impossibile caricare la guida</strong>
            <span>{{ error }}</span>
          </div>
        </div>
        <article
          v-else
          class="guide-modal__markdown"
          v-html="html"
        />
      </div>
    </section>
  </div>
</template>

<style scoped>
/* ── Backdrop + container ────────────────────────────────────── */
.guide-modal {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: var(--black-heavy);
  backdrop-filter: blur(6px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-4);
  animation: guide-fade 160ms ease;
}
@keyframes guide-fade {
  from { opacity: 0; }
  to { opacity: 1; }
}
.guide-modal__panel {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: min(880px, 100%);
  max-height: min(86vh, 880px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow:
    0 16px 48px rgba(0, 0, 0, 0.5),
    0 4px 12px rgba(0, 0, 0, 0.3);
  animation: guide-pop 180ms cubic-bezier(0.2, 0.8, 0.3, 1);
}
@keyframes guide-pop {
  from { opacity: 0; transform: translateY(8px) scale(0.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}

/* ── Header ──────────────────────────────────────────────────── */
.guide-modal__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border);
  background: var(--surface-1);
}
.guide-modal__head-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
}
.guide-modal__icon-wrap {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-dim);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  color: var(--accent);
}
.guide-modal__title-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.guide-modal__title {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
}
.guide-modal__subtitle {
  font-size: var(--text-xs);
  color: var(--text-muted);
}
.guide-modal__close {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background 120ms ease, color 120ms ease, border-color 120ms ease;
}
.guide-modal__close:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
  border-color: var(--border);
}

/* ── Body ────────────────────────────────────────────────────── */
.guide-modal__body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: var(--space-5) var(--space-6);
  background: var(--surface-2);
}
.guide-modal__state {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4);
  color: var(--text-secondary);
  font-size: var(--text-sm);
}
.guide-modal__state--error {
  color: var(--danger);
  background: var(--danger-faint);
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-md);
}
.guide-modal__state-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.guide-modal__state-body strong {
  font-weight: var(--weight-semibold);
}
.is-spinning {
  animation: guide-spin 0.9s linear infinite;
}
@keyframes guide-spin {
  to { transform: rotate(360deg); }
}

/* ── Markdown content ────────────────────────────────────────── */
.guide-modal__markdown {
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  color: var(--text-primary);
}
.guide-modal__markdown :deep(h1),
.guide-modal__markdown :deep(h2),
.guide-modal__markdown :deep(h3),
.guide-modal__markdown :deep(h4) {
  margin: var(--space-5) 0 var(--space-2);
  color: var(--text-primary);
  font-weight: var(--weight-semibold);
  letter-spacing: var(--tracking-tight);
}
.guide-modal__markdown :deep(h1) {
  font-size: var(--text-xl);
  margin-top: 0;
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--border);
}
.guide-modal__markdown :deep(h2) {
  font-size: var(--text-lg);
  padding-top: var(--space-2);
}
.guide-modal__markdown :deep(h3) { font-size: var(--text-md); }
.guide-modal__markdown :deep(h4) { font-size: var(--text-sm); }
.guide-modal__markdown :deep(p) {
  margin: 0 0 var(--space-3);
  color: var(--text-secondary);
}
.guide-modal__markdown :deep(ul),
.guide-modal__markdown :deep(ol) {
  margin: 0 0 var(--space-3);
  padding-left: var(--space-5);
  color: var(--text-secondary);
}
.guide-modal__markdown :deep(li) { margin: var(--space-1) 0; }
.guide-modal__markdown :deep(a) {
  color: var(--accent);
  text-decoration: none;
  border-bottom: 1px solid var(--accent-border);
  transition: color 120ms ease, border-color 120ms ease;
}
.guide-modal__markdown :deep(a:hover) {
  color: var(--accent-vivid);
  border-bottom-color: var(--accent);
}
.guide-modal__markdown :deep(code) {
  font-family: ui-monospace, 'SF Mono', 'Cascadia Code', monospace;
  font-size: 0.92em;
  background: var(--surface-3);
  color: var(--accent);
  padding: 2px 6px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border);
}
.guide-modal__markdown :deep(pre) {
  margin: 0 0 var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow-x: auto;
  font-size: var(--text-xs);
  line-height: var(--leading-snug);
}
.guide-modal__markdown :deep(pre code) {
  background: transparent;
  border: none;
  padding: 0;
  color: var(--text-primary);
  font-size: inherit;
}
.guide-modal__markdown :deep(blockquote) {
  margin: 0 0 var(--space-3);
  padding: var(--space-2) var(--space-4);
  background: var(--surface-1);
  border-left: 2px solid var(--accent-border);
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  font-style: italic;
}
.guide-modal__markdown :deep(hr) {
  margin: var(--space-5) 0;
  border: none;
  border-top: 1px solid var(--border);
}
.guide-modal__markdown :deep(strong) {
  color: var(--text-primary);
  font-weight: var(--weight-semibold);
}
.guide-modal__markdown :deep(table) {
  width: 100%;
  margin: 0 0 var(--space-3);
  border-collapse: collapse;
  font-size: var(--text-xs);
}
.guide-modal__markdown :deep(th),
.guide-modal__markdown :deep(td) {
  padding: var(--space-2) var(--space-3);
  text-align: left;
  border-bottom: 1px solid var(--border);
}
.guide-modal__markdown :deep(th) {
  color: var(--text-primary);
  font-weight: var(--weight-semibold);
  background: var(--surface-1);
}
.guide-modal__markdown :deep(td) {
  color: var(--text-secondary);
}
</style>
