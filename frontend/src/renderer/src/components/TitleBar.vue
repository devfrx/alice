<script setup lang="ts">
/**
 * TitleBar.vue - Custom frameless window title bar for AL\CE.
 *
 * Provides a draggable region, native-style window controls, sidebar access,
 * and one compact service-status accordion refreshed on every open.
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useSettingsStore } from '../stores/settings'
import { useServicesStore, type ServiceSnapshot, type ServiceStatus } from '../stores/services'
import { useUIStore } from '../stores/ui'
import BrandWordmark from './branding/BrandWordmark.vue'
import AliceSpinner from './ui/AliceSpinner.vue'
import AppIcon from './ui/AppIcon.vue'
import UiIconButton from './ui/UiIconButton.vue'
import UiPopover from './ui/UiPopover.vue'
import type { AppIconName } from '../assets/icons'

const isMaximized = ref(false)
const serviceAccordionOpen = ref(false)
const refreshingServices = ref(false)
const lastRefreshAt = ref<Date | null>(null)
/** The service-status trigger button — UiPopover anchors to it. */
const serviceTriggerRef = ref<HTMLElement | null>(null)

const settingsStore = useSettingsStore()
const servicesStore = useServicesStore()
const uiStore = useUIStore()

const STATUS_LABELS: Record<ServiceStatus, string> = {
  up: 'Attivo',
  degraded: 'Degradato',
  down: 'Spento',
  starting: 'Avvio'
}

const STATUS_WEIGHT: Record<ServiceStatus, number> = {
  down: 0,
  degraded: 1,
  starting: 2,
  up: 3
}

const SERVICE_META: Record<string, { label: string; icon: AppIconName }> = {
  llm: { label: 'LM Studio', icon: 'server' },
  lmstudio: { label: 'LM Studio', icon: 'server' },
  stt: { label: 'Speech-to-Text', icon: 'mic' },
  tts: { label: 'Text-to-Speech', icon: 'volume' },
  vram: { label: 'VRAM Monitor', icon: 'cpu' },
  trellis: { label: 'TRELLIS', icon: 'box-3d' },
  trellis2: { label: 'TRELLIS 2', icon: 'box-3d' },
  trellis2multiview: { label: 'TRELLIS 2 MV', icon: 'box-3d' }
}

const windowControls = window.electron?.windowControls

const modelDisplayName = computed(() => {
  const model = settingsStore.activeModel
  if (!model) return settingsStore.settings?.llm?.model || 'Nessun modello'
  const name = model.display_name || model.name
  return name.length > 34 ? `${name.slice(0, 34)}...` : name
})

const hasActiveModel = computed(() => {
  return !!settingsStore.activeModel || !!settingsStore.settings?.llm?.model
})

const serviceCounts = computed(() => {
  const counts: Record<ServiceStatus, number> & { total: number } = {
    up: 0,
    degraded: 0,
    down: 0,
    starting: 0,
    total: servicesStore.services.length
  }
  for (const service of servicesStore.services) counts[service.status] += 1
  return counts
})

const overallStatus = computed<ServiceStatus>(() => {
  const counts = serviceCounts.value
  if (counts.down > 0 && counts.up === 0 && counts.degraded === 0 && counts.starting === 0)
    return 'down'
  if (counts.down > 0 || counts.degraded > 0) return 'degraded'
  if (counts.starting > 0 || settingsStore.isAnyOperationInProgress) return 'starting'
  if (counts.up > 0 || settingsStore.lmStudioConnected) return 'up'
  return 'down'
})

const serviceSummaryLabel = computed(() => {
  const counts = serviceCounts.value
  if (refreshingServices.value && counts.total === 0) return 'Aggiorno servizi'
  if (counts.total === 0) return settingsStore.lmStudioConnected ? 'LLM connesso' : 'Servizi'
  return `${counts.up}/${counts.total} servizi`
})

const servicePanelSubtitle = computed(() => {
  if (refreshingServices.value) return 'Aggiornamento in corso'
  if (servicesStore.error) return 'Ultimo aggiornamento non riuscito'
  if (!lastRefreshAt.value) return 'Stato locale'
  return `Aggiornato ${lastRefreshAt.value.toLocaleTimeString('it-IT', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })}`
})

const serviceRows = computed(() => {
  return [...servicesStore.services].sort((left, right) => {
    const byStatus = STATUS_WEIGHT[left.status] - STATUS_WEIGHT[right.status]
    if (byStatus !== 0) return byStatus
    return serviceLabel(left).localeCompare(serviceLabel(right), 'it')
  })
})

async function refreshServiceStatus(): Promise<void> {
  if (refreshingServices.value) return
  refreshingServices.value = true
  try {
    await servicesStore.refresh()
  } finally {
    lastRefreshAt.value = new Date()
    refreshingServices.value = false
  }
}

function toggleServiceAccordion(): void {
  serviceAccordionOpen.value = !serviceAccordionOpen.value
  if (serviceAccordionOpen.value) void refreshServiceStatus()
}

function serviceLabel(service: ServiceSnapshot): string {
  return SERVICE_META[service.name]?.label ?? service.name
}

function serviceIcon(service: ServiceSnapshot): AppIconName {
  return SERVICE_META[service.name]?.icon ?? 'server'
}

function statusClass(status: ServiceStatus): string {
  return `is-${status}`
}

function formatServiceKind(service: ServiceSnapshot): string {
  return service.kind === 'external_process' ? 'Processo' : 'Interno'
}

function formatLastCheck(service: ServiceSnapshot): string {
  if (!service.last_check) return ''
  try {
    return new Date(service.last_check).toLocaleTimeString('it-IT', {
      hour: '2-digit',
      minute: '2-digit'
    })
  } catch {
    return ''
  }
}

function handleMinimize(): void {
  windowControls?.minimize()
}

function handleMaximize(): void {
  windowControls?.maximize()
}

function handleClose(): void {
  windowControls?.close()
}

let unsubMaximize: (() => void) | undefined

onMounted(() => {
  unsubMaximize = windowControls?.onMaximizeChange((maximized: boolean) => {
    isMaximized.value = maximized
  })
  void refreshServiceStatus()
})

onUnmounted(() => {
  unsubMaximize?.()
})
</script>

<template>
  <header class="titlebar">
    <div class="titlebar__left">
      <UiIconButton
        class="titlebar__menu-btn"
        label="Apri sidebar"
        variant="ghost"
        size="sm"
        :active="uiStore.sidebarOpen"
        @click="uiStore.toggleSidebar"
      >
        <AppIcon name="hybrid-sidebar" :size="15" />
      </UiIconButton>
      <span class="titlebar__title">
        <BrandWordmark brand="alce" />
      </span>
    </div>

    <div class="titlebar__center">
      <div class="titlebar__service-menu">
        <button
          ref="serviceTriggerRef"
          class="titlebar__service-trigger"
          :class="statusClass(overallStatus)"
          type="button"
          aria-controls="titlebar-services-panel"
          :aria-expanded="serviceAccordionOpen"
          @click="toggleServiceAccordion"
        >
          <span class="titlebar__service-dot" />
          <AppIcon name="server" :size="13" />
          <span class="titlebar__service-summary">{{ serviceSummaryLabel }}</span>
          <AliceSpinner v-if="refreshingServices" size="xs" />
          <AppIcon
            name="chevron-down"
            :size="12"
            class="titlebar__service-chevron"
            :class="{ 'is-open': serviceAccordionOpen }"
          />
        </button>

        <UiPopover
          :open="serviceAccordionOpen"
          :anchor-el="serviceTriggerRef"
          placement="bottom"
          align="center"
          aria-label="Stato servizi"
          @update:open="serviceAccordionOpen = $event"
        >
          <section id="titlebar-services-panel" class="titlebar__service-panel">
            <header class="titlebar__service-panel-head">
              <div class="titlebar__service-heading">
                <span class="titlebar__service-title">Servizi locali</span>
                <span class="titlebar__service-subtitle">{{ servicePanelSubtitle }}</span>
              </div>
              <UiIconButton
                label="Aggiorna servizi"
                variant="outlined"
                size="sm"
                :loading="refreshingServices"
                @click.stop="refreshServiceStatus"
              >
                <AppIcon name="refresh-cw" :size="13" />
              </UiIconButton>
            </header>

            <div v-if="serviceCounts.total > 0" class="titlebar__service-stats">
              <span class="titlebar__stat titlebar__stat--up">
                <span>{{ serviceCounts.up }}</span>
                attivi
              </span>
              <span v-if="serviceCounts.starting" class="titlebar__stat titlebar__stat--starting">
                <span>{{ serviceCounts.starting }}</span>
                avvio
              </span>
              <span v-if="serviceCounts.degraded" class="titlebar__stat titlebar__stat--degraded">
                <span>{{ serviceCounts.degraded }}</span>
                degradati
              </span>
              <span v-if="serviceCounts.down" class="titlebar__stat titlebar__stat--down">
                <span>{{ serviceCounts.down }}</span>
                spenti
              </span>
            </div>

            <div v-if="servicesStore.error" class="titlebar__service-error" role="alert">
              <AppIcon name="alert-triangle" :size="13" />
              <span>{{ servicesStore.error }}</span>
            </div>

            <div
              v-if="refreshingServices && serviceRows.length === 0"
              class="titlebar__service-empty"
            >
              <AliceSpinner size="sm" />
              <span>Caricamento servizi...</span>
            </div>

            <ul v-else-if="serviceRows.length" class="titlebar__service-list">
              <li
                v-for="service in serviceRows"
                :key="service.name"
                class="titlebar__service-row"
                :class="statusClass(service.status)"
              >
                <span class="titlebar__service-row-icon">
                  <AppIcon :name="serviceIcon(service)" :size="14" />
                </span>
                <span class="titlebar__service-row-main">
                  <span class="titlebar__service-row-name">{{ serviceLabel(service) }}</span>
                  <span class="titlebar__service-row-meta">
                    <span>{{ formatServiceKind(service) }}</span>
                    <span v-if="formatLastCheck(service)">{{ formatLastCheck(service) }}</span>
                    <span
                      v-if="service.detail"
                      class="titlebar__service-row-detail"
                      :title="service.detail"
                    >
                      {{ service.detail }}
                    </span>
                  </span>
                </span>
                <span class="titlebar__service-row-status" :class="statusClass(service.status)">
                  <span class="titlebar__service-row-dot" />
                  {{ STATUS_LABELS[service.status] }}
                </span>
              </li>
            </ul>

            <div v-else class="titlebar__service-empty">
              <AppIcon name="server" :size="16" />
              <span>Nessun servizio registrato.</span>
            </div>

            <footer class="titlebar__model-footer">
              <AppIcon name="model-load" :size="13" />
              <span class="titlebar__model-label">Modello</span>
              <span
                class="titlebar__model-name"
                :class="{ 'titlebar__model-name--empty': !hasActiveModel }"
                :title="modelDisplayName"
              >
                {{ modelDisplayName }}
              </span>
            </footer>
          </section>
        </UiPopover>
      </div>
    </div>

    <div class="titlebar__right">
      <div class="titlebar__controls">
        <button
          class="titlebar__btn titlebar__btn--minimize"
          type="button"
          aria-label="Minimize"
          @click="handleMinimize"
        >
          <AppIcon name="win-minimize" :size="10" />
        </button>
        <button
          class="titlebar__btn titlebar__btn--maximize"
          type="button"
          :aria-label="isMaximized ? 'Restore' : 'Maximize'"
          @click="handleMaximize"
        >
          <AppIcon v-if="!isMaximized" name="win-maximize" :size="10" />
          <AppIcon v-else name="win-restore" :size="10" />
        </button>
        <button
          class="titlebar__btn titlebar__btn--close"
          type="button"
          aria-label="Close"
          @click="handleClose"
        >
          <AppIcon name="win-close" :size="10" />
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.titlebar {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--titlebar-height, 38px);
  min-height: var(--titlebar-height, 38px);
  background: transparent;
  backdrop-filter: blur(var(--glass-blur));
  z-index: var(--z-sticky);
  user-select: none;
  -webkit-app-region: drag;
}

.titlebar__left {
  display: flex;
  align-items: center;
  height: 100%;
  flex-shrink: 0;
  gap: var(--space-2);
  padding-left: var(--space-1-5);
}

.titlebar__menu-btn {
  -webkit-app-region: no-drag;
}

.titlebar__title {
  font-family: var(--font-brand);
  font-size: 10px;
  font-weight: var(--weight-semibold);
  letter-spacing: 0;
  color: var(--text-muted);
  opacity: 0.68;
  padding-right: var(--space-3);
}

.titlebar__center {
  position: absolute;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  -webkit-app-region: no-drag;
}

.titlebar__service-menu {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.titlebar__service-trigger {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1-5);
  min-width: 166px;
  height: 28px;
  padding: 0 var(--space-2) 0 var(--space-2-5);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-secondary);
  cursor: pointer;
  box-shadow: var(--shadow-xs);
  transition:
    background 160ms ease,
    border-color 160ms ease,
    color 160ms ease,
    box-shadow 160ms ease;
}

.titlebar__service-trigger:hover,
.titlebar__service-trigger[aria-expanded='true'] {
  background: var(--surface-3);
  border-color: var(--border-hover);
  color: var(--text-primary);
  box-shadow: var(--shadow-sm);
}

.titlebar__service-dot {
  width: 6px;
  height: 6px;
  border-radius: var(--radius-full);
  background: currentColor;
  flex: 0 0 auto;
}

.titlebar__service-trigger.is-up .titlebar__service-dot {
  color: var(--success);
}

.titlebar__service-trigger.is-degraded .titlebar__service-dot {
  color: var(--warning);
}

.titlebar__service-trigger.is-down .titlebar__service-dot {
  color: var(--danger);
}

.titlebar__service-trigger.is-starting .titlebar__service-dot {
  color: var(--accent);
  animation: titlebar-dot-pulse 1.4s ease-in-out infinite;
}

.titlebar__service-summary {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  font-weight: var(--weight-semibold);
  letter-spacing: 0;
}

.titlebar__service-chevron {
  opacity: 0.72;
  transition: transform 160ms ease;
}

.titlebar__service-chevron.is-open {
  transform: rotate(180deg);
}

/* Content container only — UiPopover provides the floating chrome
   (surface, border, radius, shadow, positioning, no glass). */
.titlebar__service-panel {
  width: min(420px, calc(100vw - 48px));
  max-height: min(560px, calc(100vh - 72px));
  display: flex;
  flex-direction: column;
  gap: var(--space-2-5);
  padding: var(--space-1-5);
  overflow: hidden;
}

.titlebar__service-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.titlebar__service-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.titlebar__service-title {
  font-family: var(--font-display);
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  letter-spacing: 0;
}

.titlebar__service-subtitle {
  color: var(--text-muted);
  font-size: var(--text-xs);
  letter-spacing: 0;
}

.titlebar__service-stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1-5);
}

.titlebar__stat {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  min-height: 24px;
  padding: 0 var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  letter-spacing: 0;
}

.titlebar__stat span {
  color: var(--text-primary);
  font-weight: var(--weight-semibold);
}

.titlebar__stat--up {
  color: var(--success);
}

.titlebar__stat--starting {
  color: var(--accent);
}

.titlebar__stat--degraded {
  color: var(--warning);
}

.titlebar__stat--down {
  color: var(--danger);
}

.titlebar__service-error,
.titlebar__service-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 42px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-1);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  letter-spacing: 0;
}

.titlebar__service-error {
  justify-content: flex-start;
  border-color: var(--danger-border);
  background: var(--danger-faint);
  color: var(--danger);
}

.titlebar__service-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  max-height: 342px;
  overflow-y: auto;
  padding-right: var(--space-0-5);
}

.titlebar__service-row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--space-2);
  min-height: 46px;
  padding: var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-1);
}

.titlebar__service-row.is-down {
  border-color: var(--danger-border);
}

.titlebar__service-row.is-degraded {
  border-color: var(--warning-border);
}

.titlebar__service-row.is-starting {
  border-color: var(--accent-border);
}

.titlebar__service-row-icon {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-secondary);
}

.titlebar__service-row-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.titlebar__service-row-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  letter-spacing: 0;
  line-height: var(--leading-tight);
}

.titlebar__service-row-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-width: 0;
  color: var(--text-muted);
  font-size: var(--text-2xs);
  letter-spacing: 0;
  line-height: var(--leading-tight);
}

.titlebar__service-row-detail {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-size: var(--text-2xs);
  letter-spacing: 0;
}

.titlebar__service-row-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-1);
  min-width: 76px;
  min-height: 24px;
  padding: 0 var(--space-2);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-secondary);
  font-size: var(--text-2xs);
  font-weight: var(--weight-semibold);
  letter-spacing: 0;
}

.titlebar__service-row-status.is-up {
  background: var(--success-light);
  color: var(--success);
}

.titlebar__service-row-status.is-degraded {
  background: var(--warning-bg);
  color: var(--warning);
}

.titlebar__service-row-status.is-down {
  background: var(--danger-faint);
  color: var(--danger);
}

.titlebar__service-row-status.is-starting {
  background: var(--accent-dim);
  color: var(--accent);
}

.titlebar__service-row-dot {
  width: 5px;
  height: 5px;
  border-radius: var(--radius-full);
  background: currentColor;
}

.titlebar__model-footer {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  min-height: 30px;
  padding: 0 var(--space-2-5);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-inset);
  color: var(--text-secondary);
  font-size: var(--text-xs);
  letter-spacing: 0;
}

.titlebar__model-label {
  color: var(--text-muted);
}

.titlebar__model-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-weight: var(--weight-medium);
}

.titlebar__model-name--empty {
  color: var(--text-muted);
}

.titlebar__right {
  display: flex;
  align-items: center;
  height: 100%;
  flex-shrink: 0;
}

.titlebar__controls {
  display: flex;
  height: 100%;
  -webkit-app-region: no-drag;
}

.titlebar__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 100%;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition:
    background 100ms ease,
    color 100ms ease;
}

.titlebar__btn:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.titlebar__btn:active {
  background: var(--surface-active);
}

.titlebar__btn--close:hover {
  background: var(--danger);
  color: var(--text-primary);
}

.titlebar__btn--close:active {
  background: var(--danger);
  color: var(--text-primary);
  filter: brightness(0.9);
}

@keyframes titlebar-dot-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }

  50% {
    opacity: 0.45;
    transform: scale(0.84);
  }
}

@media (max-width: 680px) {
  .titlebar__title {
    display: none;
  }

  .titlebar__service-trigger {
    min-width: 136px;
  }

  .titlebar__service-summary {
    max-width: 88px;
  }

  .titlebar__service-panel {
    width: min(380px, calc(100vw - 20px));
  }
}

@media (prefers-reduced-motion: reduce) {
  .titlebar__service-trigger,
  .titlebar__service-chevron {
    transition: none;
  }
}
</style>
