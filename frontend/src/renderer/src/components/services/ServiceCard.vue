<script setup lang="ts">
/**
 * ServiceCard — Generic status card for a managed service.
 *
 * Shows the live status badge, detail line, last health-check time and
 * action buttons.  When the service is `stt` or `tts` it expands a
 * collapsible model catalog with download buttons + progress bars.
 */
import { computed, ref } from 'vue'
import { useServicesStore, type ServiceSnapshot } from '../../stores/services'
import AppIcon from '../ui/AppIcon.vue'
import type { AppIconName } from '../../assets/icons'

const props = defineProps<{ service: ServiceSnapshot }>()
const emit = defineEmits<{ (e: 'restart'): void }>()

const store = useServicesStore()
const expanded = ref(false)

// ── Display metadata ─────────────────────────────────────────
const STATUS_LABELS: Record<string, string> = {
  up: 'Attivo',
  down: 'Spento',
  degraded: 'Degradato',
  starting: 'Avvio…',
}
const SERVICE_META: Record<
  string,
  { label: string; icon: AppIconName; tagline: string }
> = {
  llm: { label: 'LM Studio', icon: 'server', tagline: 'Modello linguistico locale' },
  stt: { label: 'Speech-to-Text', icon: 'mic', tagline: 'Trascrizione vocale (Whisper)' },
  tts: { label: 'Text-to-Speech', icon: 'volume', tagline: 'Sintesi vocale (Piper / XTTS)' },
  vram: { label: 'VRAM Monitor', icon: 'cpu', tagline: 'Telemetria GPU NVIDIA' },
}

const meta = computed(
  () =>
    SERVICE_META[props.service.name] ?? {
      label: props.service.name,
      icon: 'server' as AppIconName,
      tagline: '',
    },
)
const statusClass = computed(() => `is-${props.service.status}`)
const statusLabel = computed(
  () => STATUS_LABELS[props.service.status] ?? props.service.status,
)
const isStarting = computed(() => props.service.status === 'starting')

const isModelService = computed(
  () => props.service.name === 'stt' || props.service.name === 'tts',
)
const catalog = computed(() =>
  isModelService.value ? store.catalogs[props.service.name] ?? [] : [],
)
const installedCount = computed(() => catalog.value.filter((m) => m.installed).length)

function progressFor(modelId: string) {
  return store.downloads[`${props.service.name}:${modelId}`]
}
function pct(modelId: string): number {
  const p = progressFor(modelId)
  if (!p || p.total_bytes <= 0) return 0
  return Math.min(100, Math.round((p.downloaded_bytes / p.total_bytes) * 100))
}

const lastCheck = computed(() => {
  if (!props.service.last_check) return ''
  try {
    return new Date(props.service.last_check).toLocaleTimeString()
  } catch {
    return ''
  }
})

async function onDownload(modelId: string): Promise<void> {
  try {
    await store.downloadModel(props.service.name as 'stt' | 'tts', modelId)
  } catch (e) {
    console.error('[services] download failed', e)
  }
}

function fmtMb(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`
  return `${Math.round(mb)} MB`
}
</script>

<template>
  <article class="service-card" :class="statusClass">
    <header class="service-card__head">
      <div class="service-card__icon-wrap">
        <AppIcon :name="meta.icon" :size="18" />
      </div>
      <div class="service-card__title-block">
        <h3 class="service-card__name">{{ meta.label }}</h3>
        <span v-if="meta.tagline" class="service-card__tagline">{{ meta.tagline }}</span>
      </div>
      <div class="service-card__status" :class="statusClass">
        <span class="service-card__status-dot" :class="{ 'is-pulsing': isStarting }" />
        <span class="service-card__status-label">{{ statusLabel }}</span>
      </div>
    </header>

    <p v-if="service.detail" class="service-card__detail">{{ service.detail }}</p>

    <dl class="service-card__meta">
      <div class="service-card__meta-row">
        <dt>Tipo</dt>
        <dd class="service-card__meta-tag">
          {{ service.kind === 'external_process' ? 'Processo esterno' : 'Interno' }}
        </dd>
      </div>
      <div v-if="lastCheck" class="service-card__meta-row">
        <dt>Verificato</dt>
        <dd>{{ lastCheck }}</dd>
      </div>
      <div v-if="service.backoff_attempts > 0" class="service-card__meta-row">
        <dt>Tentativi</dt>
        <dd class="service-card__meta-warn">{{ service.backoff_attempts }}</dd>
      </div>
    </dl>

    <div class="service-card__actions">
      <button class="btn btn--ghost" type="button" @click="emit('restart')">
        <AppIcon name="refresh-ccw" :size="13" />
        <span>Riavvia</span>
      </button>
      <button
        v-if="isModelService"
        class="btn btn--ghost"
        type="button"
        :aria-expanded="expanded"
        @click="expanded = !expanded"
      >
        <AppIcon :name="expanded ? 'chevron-up' : 'chevron-down'" :size="13" />
        <span>{{ expanded ? 'Nascondi' : 'Modelli' }}</span>
        <span v-if="catalog.length" class="btn__counter">
          {{ installedCount }}/{{ catalog.length }}
        </span>
      </button>
    </div>

    <section v-if="expanded && isModelService" class="service-card__models">
      <div v-if="!catalog.length" class="service-card__empty">
        Nessun modello disponibile in catalogo.
      </div>
      <ul v-else class="model-list">
        <li
          v-for="m in catalog"
          :key="m.model_id"
          class="model-row"
          :class="{ 'is-installed': m.installed }"
        >
          <div class="model-row__head">
            <div class="model-row__title">
              <span class="model-row__name">{{ m.display_name }}</span>
              <span v-if="m.installed" class="model-row__chip model-row__chip--installed">
                <AppIcon name="check" :size="10" />
                <span>Installato</span>
              </span>
            </div>
            <span class="model-row__size">{{ fmtMb(m.size_mb) }}</span>
          </div>

          <p v-if="m.description" class="model-row__desc">{{ m.description }}</p>

          <div v-if="progressFor(m.model_id)" class="model-row__progress">
            <div
              class="bar"
              :class="{
                'bar--error': progressFor(m.model_id)?.phase === 'error',
                'bar--done': progressFor(m.model_id)?.phase === 'completed',
              }"
            >
              <div class="bar__fill" :style="{ width: pct(m.model_id) + '%' }" />
            </div>
            <span class="model-row__pct">
              {{
                progressFor(m.model_id)?.phase === 'completed'
                  ? 'Completato'
                  : progressFor(m.model_id)?.phase === 'error'
                    ? 'Errore'
                    : pct(m.model_id) + '%'
              }}
            </span>
          </div>

          <div v-if="!m.installed" class="model-row__actions">
            <button
              class="btn btn--small btn--accent"
              type="button"
              :disabled="
                !!progressFor(m.model_id) &&
                progressFor(m.model_id)?.phase === 'downloading'
              "
              @click="onDownload(m.model_id)"
            >
              <AppIcon name="download" :size="12" />
              <span>{{
                progressFor(m.model_id)?.phase === 'downloading' ? 'In corso…' : 'Scarica'
              }}</span>
            </button>
          </div>
        </li>
      </ul>
    </section>
  </article>
</template>

<style scoped>
/* ── Card shell ──────────────────────────────────────────────── */
.service-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-2-5);
  padding: var(--space-4);
  background: color-mix(in srgb, var(--surface-1) 86%, var(--surface-0));
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: var(--shadow-xs);
  transition: background 140ms ease, border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
}
.service-card:hover {
  background: var(--surface-1);
  border-color: var(--border-hover);
  box-shadow: var(--shadow-sm);
}
.service-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: var(--space-3);
  bottom: var(--space-3);
  pointer-events: none;
  width: 2px;
  border-radius: var(--radius-pill);
  background: transparent;
  transition: background 140ms ease;
}
.service-card.is-up::before { background: var(--success); }
.service-card.is-degraded::before { background: var(--warning); }
.service-card.is-down::before { background: var(--danger); }
.service-card.is-starting::before { background: var(--accent); }

/* ── Header ──────────────────────────────────────────────────── */
.service-card__head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}
.service-card__icon-wrap {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-secondary);
}
.service-card__title-block {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.service-card__name {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  letter-spacing: 0;
  line-height: var(--leading-tight);
}
.service-card__tagline {
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: var(--leading-tight);
}

/* ── Status pill ─────────────────────────────────────────────── */
.service-card__status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-1) var(--space-2);
  border-radius: 8px;
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  text-transform: uppercase;
  letter-spacing: var(--tracking-wide);
}
.service-card__status-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
}
.service-card__status-dot.is-pulsing {
  animation: status-pulse 1.4s ease-in-out infinite;
}
@keyframes status-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.85); }
}
.service-card__status.is-up {
  background: var(--success-light);
  color: var(--success);
}
.service-card__status.is-degraded {
  background: var(--warning-bg);
  color: var(--warning);
}
.service-card__status.is-down {
  background: var(--danger-faint);
  color: var(--danger);
}
.service-card__status.is-starting {
  background: var(--accent-dim);
  color: var(--accent);
}

/* ── Body ────────────────────────────────────────────────────── */
.service-card__detail {
  margin: 0;
  padding: var(--space-2) var(--space-2-5);
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: var(--leading-snug);
  word-break: break-word;
}
.service-card__meta {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin: 0;
  padding: 0;
  font-size: var(--text-xs);
}
.service-card__meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-2);
}
.service-card__meta dt {
  color: var(--text-muted);
  font-weight: var(--weight-normal);
}
.service-card__meta dd {
  margin: 0;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}
.service-card__meta-tag {
  font-size: var(--text-2xs);
  text-transform: uppercase;
  letter-spacing: var(--tracking-wide);
  color: var(--text-muted) !important;
}
.service-card__meta-warn {
  color: var(--warning) !important;
  font-weight: var(--weight-semibold);
}

/* ── Buttons ─────────────────────────────────────────────────── */
.service-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: auto;
  padding-top: var(--space-1);
}
.btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-1-5) var(--space-3);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  border-radius: 8px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}
.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.btn--ghost {
  background: transparent;
  color: var(--text-secondary);
  border-color: var(--border);
}
.btn--ghost:hover:not(:disabled) {
  background: var(--surface-3);
  color: var(--text-primary);
  border-color: var(--border-hover);
}
.btn--accent {
  background: var(--accent-dim);
  color: var(--accent);
  border-color: var(--accent-border);
}
.btn--accent:hover:not(:disabled) {
  background: var(--accent-medium);
  border-color: var(--accent-strong);
}
.btn--small {
  padding: var(--space-1) var(--space-2-5);
  font-size: var(--text-2xs);
}
.btn__counter {
  margin-left: var(--space-1);
  padding: 0 var(--space-1-5);
  font-size: var(--text-2xs);
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
  background: var(--surface-1);
  border-radius: 6px;
}

/* ── Models panel ────────────────────────────────────────────── */
.service-card__models {
  margin-top: var(--space-2);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border);
}
.service-card__empty {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-align: center;
  padding: var(--space-3);
}
.model-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.model-row {
  padding: var(--space-2-5) var(--space-3);
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: 8px;
  transition: background 120ms ease, border-color 120ms ease;
}
.model-row:hover { border-color: var(--border-hover); }
.model-row.is-installed {
  background: var(--success-faint);
  border-color: var(--success-border);
}
.model-row__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-2);
}
.model-row__title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  min-width: 0;
}
.model-row__name {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
  word-break: break-word;
}
.model-row__chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 2px var(--space-1-5);
  border-radius: 6px;
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  text-transform: uppercase;
  letter-spacing: var(--tracking-wide);
}
.model-row__chip--installed {
  background: var(--success-medium);
  color: var(--success);
  border: 1px solid var(--success-border);
}
.model-row__size {
  flex: 0 0 auto;
  font-size: var(--text-2xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  letter-spacing: var(--tracking-tight);
}
.model-row__desc {
  margin: var(--space-1-5) 0 0;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: var(--leading-snug);
}
.model-row__progress {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
.bar {
  flex: 1;
  height: 4px;
  background: var(--surface-inset);
  border-radius: var(--radius-pill);
  overflow: hidden;
}
.bar__fill {
  height: 100%;
  background: var(--accent);
  border-radius: var(--radius-pill);
  transition: width 220ms ease;
}
.bar--done .bar__fill { background: var(--success); }
.bar--error .bar__fill { background: var(--danger); }
.model-row__pct {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  min-width: 60px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.model-row__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--space-2);
}
</style>
