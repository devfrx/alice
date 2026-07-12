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
 * The same component handles ``trellis`` (text-to-3D, port 8090),
 * ``trellis2`` (image-to-3D, port 8091) and ``trellis2multiview``
 * (multi-image-to-3D, port 8092); the dir-key and labels switch on
 * ``props.service.name``.
 */
import { computed, onMounted, ref } from 'vue'
import { useServicesStore, type ServiceSnapshot } from '../../stores/services'
import AppIcon from '../ui/AppIcon.vue'
import UiToggle from '../ui/UiToggle.vue'
import UiInput from '../ui/UiInput.vue'
import UiButton from '../ui/UiButton.vue'

const props = defineProps<{ service: ServiceSnapshot }>()
const emit = defineEmits<{
  (e: 'restart'): void
  (e: 'open-guide'): void
}>()

const store = useServicesStore()

const dirPath = ref('')
const enabled = ref(false)
const saving = ref(false)
const restarting = ref(false)
const stopping = ref(false)
const loading = ref(true)
const saveError = ref<string | null>(null)
const saveOk = ref(false)

const STATUS_LABELS: Record<string, string> = {
  up: 'Attivo',
  down: 'Spento',
  degraded: 'Degradato',
  starting: 'Avvio…'
}

type TrellisVariant = 'trellis' | 'trellis2' | 'trellis2multiview'
const variant = computed<TrellisVariant>(() => props.service.name as TrellisVariant)
const isV2 = computed(() => variant.value === 'trellis2')
const isMV = computed(() => variant.value === 'trellis2multiview')
const hasGuide = computed(() => isV2.value || isMV.value)

const dirKey = computed(() => {
  if (isMV.value) return 'trellis2multiview_dir'
  if (isV2.value) return 'trellis2_dir'
  return 'trellis_dir'
})
const variantLabel = computed(() => {
  if (isMV.value) return 'TRELLIS.2 Multi-view'
  if (isV2.value) return 'TRELLIS.2'
  return 'TRELLIS'
})
const tagline = computed(() => {
  if (isMV.value) return 'Multi-image-to-3D · porta 8092 · richiede setup compilazione'
  if (isV2.value) return 'Image-to-3D · porta 8091 · richiede setup compilazione'
  return 'Text-to-3D · porta 8090'
})
const placeholder = computed(() => {
  if (isMV.value) return 'C:\\path\\to\\TRELLIS.2.multiview'
  if (isV2.value) return 'C:\\path\\to\\TRELLIS.2'
  return 'C:\\path\\to\\TRELLIS-for-windows'
})

const statusClass = computed(() => `is-${props.service.status}`)
const statusLabel = computed(() => STATUS_LABELS[props.service.status] ?? props.service.status)
const isStarting = computed(() => props.service.status === 'starting')
const isStopped = computed(() => props.service.status === 'down')

onMounted(async () => {
  loading.value = true
  try {
    const cfg = await store.loadTrellisConfig(variant.value)
    enabled.value = Boolean(cfg.enabled ?? false)
    dirPath.value = (cfg[dirKey.value] as string) ?? ''
  } catch (e) {
    saveError.value = `Impossibile leggere la configurazione: ${(e as Error).message}`
  } finally {
    loading.value = false
  }
})

async function pickDir(): Promise<void> {
  const picked = await window.electron.fileOps.selectDirectory(dirPath.value || undefined)
  if (picked) dirPath.value = picked
}

async function save(): Promise<boolean> {
  saving.value = true
  saveError.value = null
  saveOk.value = false
  try {
    const payload: Record<string, unknown> = { enabled: enabled.value }
    payload[dirKey.value] = dirPath.value.trim() || undefined
    await store.configureTrellis(variant.value, payload)
    saveOk.value = true
    return true
  } catch (e) {
    saveError.value = (e as Error).message
    return false
  } finally {
    saving.value = false
  }
}

async function startOrRestart(): Promise<void> {
  if (isStarting.value) {
    await store.refresh()
    return
  }
  restarting.value = true
  saveError.value = null
  try {
    enabled.value = true
    const saved = await save()
    if (!saved) return
    await store.restart(props.service.name)
    await store.refresh()
  } catch (e) {
    saveError.value = (e as Error).message
  } finally {
    restarting.value = false
  }
}

async function stopService(): Promise<void> {
  stopping.value = true
  saveError.value = null
  saveOk.value = false
  try {
    await store.stop(props.service.name)
    await store.refresh()
  } catch (e) {
    saveError.value = (e as Error).message
  } finally {
    stopping.value = false
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
          <UiInput
            v-model="dirPath"
            class="trellis-card__input"
            type="text"
            size="md"
            :placeholder="placeholder"
            :disabled="loading"
          />
          <UiButton variant="ghost" size="md" :disabled="loading" @click="pickDir">
            <template #icon>
              <AppIcon name="folder" :size="13" />
            </template>
            Sfoglia
          </UiButton>
        </div>
        <span class="trellis-card__hint"> Percorso del clone locale del repository. </span>
      </label>

      <UiToggle
        v-model="enabled"
        :disabled="loading"
        label="Abilita servizio"
        hint="Quando attivo, AL\CE può avviare automaticamente il processo."
      />
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
      <UiButton
        variant="primary"
        size="sm"
        :disabled="saving || restarting || stopping || loading"
        @click="save"
      >
        <template #icon>
          <AppIcon name="check" :size="13" />
        </template>
        {{ saving ? 'Salvo…' : 'Salva' }}
      </UiButton>
      <UiButton
        variant="secondary"
        size="sm"
        :disabled="saving || restarting || stopping || loading || isStarting"
        @click="startOrRestart"
      >
        <template #icon>
          <AppIcon name="refresh-ccw" :size="13" />
        </template>
        {{ restarting || isStarting ? 'Avvio…' : 'Avvia / Riavvia' }}
      </UiButton>
      <UiButton
        variant="secondary"
        size="sm"
        :disabled="saving || restarting || stopping || loading || isStopped"
        @click="stopService"
      >
        <template #icon>
          <AppIcon name="stop" :size="13" />
        </template>
        {{ stopping ? 'Spengo…' : 'Spegni' }}
      </UiButton>
      <UiButton
        v-if="hasGuide"
        variant="ghost"
        size="sm"
        class="trellis-card__guide-btn"
        @click="emit('open-guide')"
      >
        <template #icon>
          <AppIcon name="alert-circle" :size="13" />
        </template>
        Guida setup
      </UiButton>
    </div>
  </article>
</template>

<style scoped>
/* ── Card shell ──────────────────────────────────────────────── */
.trellis-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: var(--shadow-xs);
  transition:
    background var(--duration-fast) ease,
    border-color var(--duration-fast) ease,
    box-shadow var(--duration-fast) ease;
}
.trellis-card:hover {
  background: var(--surface-2);
  border-color: var(--border-hover);
  box-shadow: var(--shadow-sm);
}
.trellis-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: var(--space-3);
  bottom: var(--space-3);
  pointer-events: none;
  width: 2px;
  border-radius: var(--radius-pill);
  background: transparent;
  transition: background var(--duration-fast) ease;
}
.trellis-card.is-up::before {
  background: var(--success);
}
.trellis-card.is-degraded::before {
  background: var(--warning);
}
.trellis-card.is-down::before {
  background: var(--danger);
}
.trellis-card.is-starting::before {
  background: var(--accent);
}

/* ── Header ──────────────────────────────────────────────────── */
.trellis-card__head {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
}
.trellis-card__icon-wrap {
  flex: 0 0 auto;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-2);
  border-radius: 8px;
  color: var(--text-secondary);
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
  letter-spacing: 0;
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
  border-radius: 8px;
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
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.5;
    transform: scale(0.85);
  }
}
.trellis-card__status.is-up {
  background: var(--success-light);
  color: var(--success);
}
.trellis-card__status.is-degraded {
  background: var(--warning-bg);
  color: var(--warning);
}
.trellis-card__status.is-down {
  background: var(--danger-faint);
  color: var(--danger);
}
.trellis-card__status.is-starting {
  background: var(--accent-dim);
  color: var(--accent);
}

/* ── Detail line ─────────────────────────────────────────────── */
.trellis-card__detail {
  margin: 0;
  padding: var(--space-2) var(--space-2-5);
  background: var(--surface-0);
  border-radius: 8px;
  font-size: var(--text-xs);
  color: var(--text-secondary);
  line-height: var(--leading-snug);
  word-break: break-word;
}

/* ── Form ────────────────────────────────────────────────────── */
.trellis-card__form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2-5);
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
}
/* Compound override on the kit's own root class (per UI kit rules): this
   field shows a filesystem path, so it keeps the subtle input surface and
   monospace type instead of UiInput's defaults. */
.trellis-card__input.ui-input :deep(.ui-input__wrapper) {
  background: var(--bg-input);
}
.trellis-card__input.ui-input :deep(.ui-input__field) {
  font-family: var(--font-mono);
}

/* ── Alerts ──────────────────────────────────────────────────── */
.trellis-card__alert {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: 8px;
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
/* Compound override on the kit's own root class (per UI kit rules): pushes
   the tertiary "Guida setup" action to the far right of the actions row. */
.trellis-card__guide-btn.ui-btn {
  margin-left: auto;
}
</style>
