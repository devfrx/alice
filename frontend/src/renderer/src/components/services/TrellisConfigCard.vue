<script setup lang="ts">
/**
 * TrellisConfigCard — Status + configuration card for Trellis / Trellis2.
 *
 * Differs from the generic `ServiceCard` because:
 *  - These services need a directory picker bound to a local clone.
 *  - The first start is a 30-60min compile, so we expose an in-app guide.
 *  - Configuration writes go through `cfg_svc.set("<name>.X", value)` via
 *    the parametric ``POST /api/services/<name>/configure`` endpoint.
 *
 * The same component handles both ``trellis`` (text-to-3D, port 8090) and
 * ``trellis2`` (image-to-3D, port 8091); the dir-key and labels switch on
 * ``props.service.name``.
 */
import { computed, onMounted, ref } from 'vue'
import {
  useServicesStore,
  type ServiceSnapshot,
} from '../../stores/services'
import AppIcon from '../ui/AppIcon.vue'

const props = defineProps<{ service: ServiceSnapshot }>()
const emit = defineEmits<{
  (e: 'restart'): void
  (e: 'open-guide'): void
}>()

const store = useServicesStore()

const dirPath = ref('')
const enabled = ref(false)
const saving = ref(false)
const loading = ref(true)
const saveError = ref<string | null>(null)
const saveOk = ref(false)

const STATUS_LABELS: Record<string, string> = {
  up: 'Attivo',
  down: 'Spento',
  degraded: 'Degradato',
  starting: 'Avvio…',
}

const isV2 = computed(() => props.service.name === 'trellis2')
const dirKey = computed(() => (isV2.value ? 'trellis2_dir' : 'trellis_dir'))
const variantLabel = computed(() => (isV2.value ? 'TRELLIS.2' : 'TRELLIS'))
const tagline = computed(() =>
  isV2.value
    ? 'Image-to-3D · porta 8091 · richiede setup compilazione'
    : 'Text-to-3D · porta 8090',
)
const placeholder = computed(() =>
  isV2.value ? 'C:\\path\\to\\TRELLIS.2' : 'C:\\path\\to\\TRELLIS-for-windows',
)

const statusClass = computed(() => `is-${props.service.status}`)
const statusLabel = computed(
  () => STATUS_LABELS[props.service.status] ?? props.service.status,
)
const isStarting = computed(() => props.service.status === 'starting')

onMounted(async () => {
  loading.value = true
  try {
    const cfg = await store.loadTrellisConfig(
      props.service.name as 'trellis' | 'trellis2',
    )
    enabled.value = Boolean(cfg.enabled ?? false)
    dirPath.value = (cfg[dirKey.value] as string) ?? ''
  } catch (e) {
    saveError.value = `Impossibile leggere la configurazione: ${(e as Error).message}`
  } finally {
    loading.value = false
  }
})

async function pickDir(): Promise<void> {
  const picked = await window.electron.fileOps.selectDirectory(
    dirPath.value || undefined,
  )
  if (picked) dirPath.value = picked
}

async function save(): Promise<void> {
  saving.value = true
  saveError.value = null
  saveOk.value = false
  try {
    const payload: Record<string, unknown> = { enabled: enabled.value }
    payload[dirKey.value] = dirPath.value.trim() || undefined
    await store.configureTrellis(
      props.service.name as 'trellis' | 'trellis2',
      payload,
    )
    saveOk.value = true
  } catch (e) {
    saveError.value = (e as Error).message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <article class="trellis-card" :class="statusClass">
    <header class="trellis-card__head">
      <div class="trellis-card__icon-wrap">
        <AppIcon name="box-3d" :size="18" />
      </div>
      <div class="trellis-card__title-block">
        <h3 class="trellis-card__name">{{ variantLabel }}</h3>
        <span class="trellis-card__tagline">{{ tagline }}</span>
      </div>
      <div class="trellis-card__status" :class="statusClass">
        <span class="trellis-card__status-dot" :class="{ 'is-pulsing': isStarting }" />
        <span>{{ statusLabel }}</span>
      </div>
    </header>

    <p v-if="service.detail" class="trellis-card__detail">{{ service.detail }}</p>

    <div class="trellis-card__form">
      <label class="trellis-card__field">
        <span class="trellis-card__label">Cartella {{ variantLabel }}</span>
        <div class="trellis-card__input-row">
          <input
            v-model="dirPath"
            class="trellis-card__input"
            type="text"
            :placeholder="placeholder"
            spellcheck="false"
            :disabled="loading"
          />
          <button
            class="btn btn--ghost btn--icon"
            type="button"
            :disabled="loading"
            :title="`Sfoglia per la cartella ${variantLabel}`"
            @click="pickDir"
          >
            <AppIcon name="folder" :size="13" />
            <span>Sfoglia</span>
          </button>
        </div>
        <span class="trellis-card__hint">
          Percorso del clone locale del repository.
        </span>
      </label>

      <label class="trellis-card__toggle">
        <input
          v-model="enabled"
          type="checkbox"
          class="trellis-card__checkbox"
          :disabled="loading"
        />
        <span class="trellis-card__toggle-track" aria-hidden="true">
          <span class="trellis-card__toggle-knob" />
        </span>
        <span class="trellis-card__toggle-label">
          <span class="trellis-card__toggle-title">Abilita servizio</span>
          <span class="trellis-card__toggle-desc">
            Quando attivo, AL\CE può avviare automaticamente il processo.
          </span>
        </span>
      </label>
    </div>

    <div v-if="saveError" class="trellis-card__alert trellis-card__alert--error">
      <AppIcon name="alert-triangle" :size="13" />
      <span>{{ saveError }}</span>
    </div>
    <div v-if="saveOk" class="trellis-card__alert trellis-card__alert--ok">
      <AppIcon name="check" :size="13" />
      <span>Configurazione salvata.</span>
    </div>

    <div class="trellis-card__actions">
      <button
        class="btn btn--accent"
        type="button"
        :disabled="saving || loading"
        @click="save"
      >
        <AppIcon name="check" :size="13" />
        <span>{{ saving ? 'Salvo…' : 'Salva' }}</span>
      </button>
      <button class="btn btn--ghost" type="button" @click="emit('restart')">
        <AppIcon name="refresh-ccw" :size="13" />
        <span>Avvia / Riavvia</span>
      </button>
      <button
        v-if="isV2"
        class="btn btn--ghost btn--right"
        type="button"
        @click="emit('open-guide')"
      >
        <AppIcon name="alert-circle" :size="13" />
        <span>Guida setup</span>
      </button>
    </div>
  </article>
</template>

<style scoped>
/* ── Card shell ──────────────────────────────────────────────── */
.trellis-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  padding: var(--space-5);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  transition: background 140ms ease, border-color 140ms ease;
}
.trellis-card:hover {
  background: var(--surface-2);
  border-color: var(--border-hover);
}
.trellis-card::before {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: var(--radius-lg);
  pointer-events: none;
  border-left: 2px solid transparent;
  transition: border-color 140ms ease;
}
.trellis-card.is-up::before { border-left-color: var(--success); }
.trellis-card.is-degraded::before { border-left-color: var(--warning); }
.trellis-card.is-down::before { border-left-color: var(--danger); }
.trellis-card.is-starting::before { border-left-color: var(--accent); }

/* ── Header ──────────────────────────────────────────────────── */
.trellis-card__head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}
.trellis-card__icon-wrap {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--accent-dim);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-md);
  color: var(--accent);
}
.trellis-card__title-block {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.trellis-card__name {
  margin: 0;
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  letter-spacing: var(--tracking-tight);
  line-height: var(--leading-tight);
}
.trellis-card__tagline {
  font-size: var(--text-xs);
  color: var(--text-muted);
  line-height: var(--leading-tight);
}

/* ── Status pill ─────────────────────────────────────────────── */
.trellis-card__status {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-pill);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  text-transform: uppercase;
  letter-spacing: var(--tracking-wide);
}
.trellis-card__status-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
}
.trellis-card__status-dot.is-pulsing {
  animation: status-pulse 1.4s ease-in-out infinite;
}
@keyframes status-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.85); }
}
.trellis-card__status.is-up { background: var(--success-light); color: var(--success); }
.trellis-card__status.is-degraded { background: var(--warning-bg); color: var(--warning); }
.trellis-card__status.is-down { background: var(--danger-faint); color: var(--danger); }
.trellis-card__status.is-starting { background: var(--accent-dim); color: var(--accent); }

/* ── Detail line ─────────────────────────────────────────────── */
.trellis-card__detail {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  background: var(--surface-inset);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: var(--leading-snug);
  word-break: break-word;
}

/* ── Form ────────────────────────────────────────────────────── */
.trellis-card__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}
.trellis-card__field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1-5);
}
.trellis-card__label {
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--text-secondary);
  letter-spacing: var(--tracking-tight);
}
.trellis-card__hint {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  line-height: var(--leading-snug);
}
.trellis-card__input-row {
  display: flex;
  gap: var(--space-2);
}
.trellis-card__input {
  flex: 1 1 auto;
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  background: var(--bg-input);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: var(--text-xs);
  font-family: ui-monospace, 'SF Mono', 'Cascadia Code', monospace;
  transition: border-color 120ms ease, background 120ms ease;
}
.trellis-card__input::placeholder { color: var(--text-muted); }
.trellis-card__input:focus {
  outline: none;
  border-color: var(--accent-border);
  background: var(--surface-2);
}
.trellis-card__input:disabled { opacity: 0.6; }

/* ── Toggle ──────────────────────────────────────────────────── */
.trellis-card__toggle {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--surface-inset);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: border-color 120ms ease;
}
.trellis-card__toggle:hover { border-color: var(--border-hover); }
.trellis-card__checkbox {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}
.trellis-card__toggle-track {
  position: relative;
  flex: 0 0 auto;
  width: 30px;
  height: 18px;
  background: var(--surface-3);
  border-radius: var(--radius-pill);
  transition: background 160ms ease;
  margin-top: 2px;
}
.trellis-card__toggle-knob {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 14px;
  height: 14px;
  background: var(--text-secondary);
  border-radius: var(--radius-full);
  transition: transform 160ms ease, background 160ms ease;
}
.trellis-card__checkbox:checked + .trellis-card__toggle-track {
  background: var(--accent-medium);
}
.trellis-card__checkbox:checked + .trellis-card__toggle-track .trellis-card__toggle-knob {
  transform: translateX(12px);
  background: var(--accent);
}
.trellis-card__checkbox:focus-visible + .trellis-card__toggle-track {
  box-shadow: 0 0 0 2px var(--accent-border);
}
.trellis-card__toggle-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.trellis-card__toggle-title {
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  color: var(--text-primary);
}
.trellis-card__toggle-desc {
  font-size: var(--text-2xs);
  color: var(--text-muted);
  line-height: var(--leading-snug);
}

/* ── Alerts ──────────────────────────────────────────────────── */
.trellis-card__alert {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  line-height: var(--leading-snug);
}
.trellis-card__alert--error {
  background: var(--danger-faint);
  color: var(--danger);
  border: 1px solid var(--danger-border);
}
.trellis-card__alert--ok {
  background: var(--success-light);
  color: var(--success);
  border: 1px solid var(--success-border);
}

/* ── Buttons ─────────────────────────────────────────────────── */
.trellis-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}
.btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1-5);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  font-weight: var(--weight-medium);
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn--ghost {
  background: var(--surface-2);
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
.btn--icon { flex: 0 0 auto; }
.btn--right { margin-left: auto; }
</style>
