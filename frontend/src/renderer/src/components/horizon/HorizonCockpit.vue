<script setup lang="ts">
/**
 * HorizonCockpit — the controls rail that materializes under the serif
 * composer: the full chat-input capability set (attachments, models, scope,
 * tools, permission tier, context, mic, send/stop) REUSING the shared chat
 * components as-is. Horizon contributes only the transparent shell.
 */
import { computed, ref } from 'vue'
import ModelSelector from '../settings/ModelSelector.vue'
import ChatToolControls from '../chat/ChatToolControls.vue'
import PermissionTierSelector from '../chat/PermissionTierSelector.vue'
import ScopeIndicator from '../chat/ScopeIndicator.vue'
import MicrophoneButton from '../voice/MicrophoneButton.vue'
import ContextBar from '../chat/ContextBar.vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import { useChatAttachments } from '../../composables/useChatAttachments'
import { formatCost } from '../../utils/formatCost'
import { useChatStore } from '../../stores/chat'
import { useSettingsStore } from '../../stores/settings'
import { useVoiceStore } from '../../stores/voice'
import type { AudioDevice } from '../../composables/useVoice'

defineProps<{
  isStreaming: boolean
  audioDevices: AudioDevice[]
  selectedDeviceId: string
}>()

const emit = defineEmits<{
  send: []
  stop: []
  'voice-start': []
  'voice-stop': []
  'voice-cancel-processing': []
  'refresh-devices': []
  'select-device': [deviceId: string]
}>()

const chatStore = useChatStore()
const settingsStore = useSettingsStore()
const voiceStore = useVoiceStore()

const supportsVision = computed(() => settingsStore.activeModel?.capabilities.vision ?? false)

const att = useChatAttachments({ accept: () => supportsVision.value })
const fileInputRef = ref<HTMLInputElement | null>(null)

/** Open the native file picker. */
function openFilePicker(): void {
  fileInputRef.value?.click()
}

defineExpose({
  pendingFiles: att.pendingFiles,
  clearAllFiles: att.clearAllFiles,
  handlePaste: att.handlePaste
})
</script>

<template>
  <div
    class="hz-cockpit"
    @dragenter="att.handleDragEnter"
    @dragover="att.handleDragOver"
    @dragleave="att.handleDragLeave"
    @drop="att.handleDrop"
  >
    <div v-if="att.pendingFiles.value.length > 0" class="hz-cockpit__thumbs">
      <div
        v-for="file in att.pendingFiles.value"
        :key="file.name + file.size + file.lastModified"
        class="hz-cockpit__thumb"
      >
        <img :src="att.getThumbnail(file)" :alt="file.name" :title="file.name" />
        <button
          class="hz-cockpit__thumb-rm"
          aria-label="Rimuovi allegato"
          @click="att.removeFile(file)"
        >
          <AppIcon name="x" :size="10" :stroke-width="2.5" />
        </button>
      </div>
    </div>
    <!-- hz-cockpit__thumb-rm stays bespoke: 16px overlay badge on a 44px
         thumbnail, below the kit's smallest icon-button size (xs, 24px) —
         migrating would enlarge it and regress the thumbnail strip. See
         the identical, already-migrated precedent in ChatInput.vue. -->

    <input
      ref="fileInputRef"
      type="file"
      accept="image/*"
      multiple
      class="hz-cockpit__file-input"
      @change="att.handleFileSelect"
    />

    <div class="hz-cockpit__rail">
      <UiIconButton
        size="sm"
        variant="ghost"
        :disabled="!supportsVision"
        :label="supportsVision ? 'Allega immagine' : 'Il modello attivo non supporta immagini'"
        @click="openFilePicker"
      >
        <AppIcon name="paperclip" :size="13" />
      </UiIconButton>

      <ModelSelector model-type="llm" />
      <ScopeIndicator :conversation-id="chatStore.currentConversation?.id ?? null" />
      <ChatToolControls />
      <PermissionTierSelector />

      <ContextBar
        :context-info="chatStore.contextInfo"
        :is-compressing="chatStore.isCompressingContext"
      />

      <span
        v-if="chatStore.conversationCost != null"
        class="hz-cockpit__cost"
        :title="'Costo conversazione (crediti OpenRouter)'"
      >
        {{ formatCost(chatStore.conversationCost) }}
      </span>

      <MicrophoneButton
        v-if="voiceStore.isReady"
        :available="voiceStore.sttAvailable"
        :connected="voiceStore.connected"
        :audio-devices="audioDevices"
        :selected-device-id="selectedDeviceId"
        @start-recording="emit('voice-start')"
        @stop-recording="emit('voice-stop')"
        @cancel-processing="emit('voice-cancel-processing')"
        @refresh-devices="emit('refresh-devices')"
        @select-device="(id) => emit('select-device', id)"
      />

      <UiIconButton
        v-if="isStreaming"
        class="hz-cockpit__stop"
        size="sm"
        variant="ghost"
        tone="danger"
        label="Interrompi generazione"
        @click="emit('stop')"
      >
        <AppIcon name="stop" :size="13" />
      </UiIconButton>
      <UiIconButton v-else size="sm" variant="ghost" label="Invia messaggio" @click="emit('send')">
        <AppIcon name="send" :size="13" />
      </UiIconButton>
    </div>
  </div>
</template>

<style scoped>
.hz-cockpit {
  width: min(72%, 720px);
  margin-bottom: clamp(12px, 2vh, 24px);
}

.hz-cockpit__thumbs {
  display: flex;
  justify-content: center;
  gap: var(--space-2);
  padding-bottom: var(--space-2);
}

.hz-cockpit__thumb {
  position: relative;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-md);
  overflow: hidden;
  border: 1px solid var(--border);
}

.hz-cockpit__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.hz-cockpit__thumb-rm {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 16px;
  height: 16px;
  border-radius: var(--radius-full);
  background: var(--surface-4);
  border: 1px solid var(--border);
  color: var(--text-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
  transition:
    border-color var(--duration-fast) var(--ease-out-quart),
    color var(--duration-fast) var(--ease-out-quart),
    transform var(--duration-fast) var(--ease-out-quart);
}

.hz-cockpit__thumb-rm:hover {
  border-color: var(--border-hover);
  color: var(--danger);
}

.hz-cockpit__thumb-rm:active {
  transform: scale(0.88);
}

.hz-cockpit__file-input {
  display: none;
}

.hz-cockpit__cost {
  font-size: var(--text-2xs);
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
  flex-shrink: 0;
  user-select: none;
}

.hz-cockpit__rail {
  display: flex;
  align-items: center;
  justify-content: center;
  flex-wrap: wrap;
  gap: var(--space-2);
  padding-top: var(--space-2);
  border-top: 1px solid rgba(var(--hz-line-rgb), 0.18);
}

/* hz-cockpit__stop overrides the UiIconButton default color so the icon
   reads danger-red at rest (streaming is happening now); tone="danger" on
   the component still drives the hover tint. The .ui-icon-btn compound
   (0,3,0 with the scope attribute) beats the kit base deterministically,
   regardless of CSS chunk-load order. */
.hz-cockpit__stop.ui-icon-btn {
  color: var(--danger);
}
</style>
