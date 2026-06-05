<script setup lang="ts">
/**
 * ChatPanel — Anchored-but-convertible chat surface for the tiling workspace.
 *
 * Reuses the existing chat UI rather than rebuilding it: the message thread is
 * `MessageBubble` + `StreamingIndicator` (both driven directly from
 * `stores/chat`), and the composer is the existing `ChatInput`, wired to the
 * global chat API provided by App.vue via `ChatApiKey` injection. Because all
 * data flows through the store/injection, this panel is fully functional
 * anywhere it is mounted under App (anchored column OR a tiling leaf).
 *
 * A compact header exposes a single toggle that anchors the chat or converts
 * it into a tile via the workspace store.
 */
import { computed, inject, nextTick, ref, watch } from 'vue'
import MessageBubble from '../chat/MessageBubble.vue'
import StreamingIndicator from '../chat/StreamingIndicator.vue'
import ChatInput from '../chat/ChatInput.vue'
import ToolConfirmationDialog from '../chat/ToolConfirmationDialog.vue'
import MessageEditDialog from '../chat/MessageEditDialog.vue'
import AppIcon from '../ui/AppIcon.vue'
import UiIconButton from '../ui/UiIconButton.vue'
import ModuleLauncher from './ModuleLauncher.vue'
import { ChatApiKey } from '../../composables/useChat'
import { useVoice } from '../../composables/useVoice'
import { useChatStore } from '../../stores/chat'
import { useWorkspaceStore } from '../../stores/workspace'

const props = defineProps<{
  /** Optional conversation hint — reserved for future per-tile conversations. */
  conversationId?: string | null
  /**
   * When true the panel is hosted inside a ModulePanel (tiled mode) which
   * already supplies a header with a title and close button. Suppressing the
   * built-in header avoids a double-header layout.
   */
  embedded?: boolean
}>()

const chatStore = useChatStore()
const workspaceStore = useWorkspaceStore()
const chatApi = inject(ChatApiKey, null)

// Graceful no-ops if the injection is unavailable (keeps the panel renderable
// in isolation / tests without crashing).
const _noop = (): void => {}
const _asyncNoop = async (): Promise<void> => {}
const send = chatApi?.sendMessage ?? _asyncNoop
const isConnected = chatApi?.isConnected ?? ref(false)
const stopGeneration = chatApi?.stopGeneration ?? _noop
const editMessage = chatApi?.editMessage ?? _asyncNoop
const respondToConfirmation = chatApi?.respondToConfirmation ?? _noop

const {
  startListening,
  stopListening,
  cancelProcessing,
  audioDevices,
  selectedDeviceId,
  refreshDevices
} = useVoice()

const messagesContainer = ref<HTMLElement | null>(null)

// ── Edit dialog ─────────────────────────────────────────────────────────────
const editingMessageId = ref<string | null>(null)
const editingContent = ref('')

function startEdit(messageId: string): void {
  if (chatStore.isStreamingCurrentConversation) return
  const msg = chatStore.messages.find((m) => m.id === messageId)
  if (!msg || msg.role !== 'user') return
  editingMessageId.value = messageId
  editingContent.value = msg.content
}

function submitEdit(newContent: string): void {
  const msgId = editingMessageId.value
  editingMessageId.value = null
  editingContent.value = ''
  if (msgId) editMessage(msgId, newContent)
}

function cancelEdit(): void {
  editingMessageId.value = null
  editingContent.value = ''
}

function handleVersionSwitch(versionGroupId: string, versionIndex: number): void {
  chatStore.switchVersion(versionGroupId, versionIndex)
}

async function handleBranch(messageId: string): Promise<void> {
  if (chatStore.isStreamingCurrentConversation) return
  await chatStore.branchConversation(messageId)
}

async function handleSend(content: string, attachments: File[]): Promise<void> {
  await send(content, undefined, attachments)
}

const pendingConfirmationsList = computed(() => Object.values(chatStore.pendingConfirmations))

// ── Auto-scroll ─────────────────────────────────────────────────────────────
function scrollConversation(): void {
  nextTick(() => {
    if (messagesContainer.value)
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  })
}

watch(
  () => [chatStore.messages.length, chatStore.currentStreamContent],
  () => scrollConversation()
)

// ── Header: active conversation title ────────────────────────────────────────
/**
 * Title shown on the left of the blended header. Reads the active
 * conversation's `title` from the chat store; falls back to a sensible
 * default when the conversation is untitled (new/empty draft).
 */
const conversationTitle = computed<string>(() => {
  const title = chatStore.currentConversation?.title?.trim()
  return title || 'Nuova chat'
})

// ── Anchor / tile toggle ─────────────────────────────────────────────────────
const isAnchored = computed<boolean>(() => workspaceStore.chatMode === 'anchored')

function toggleAnchor(): void {
  if (isAnchored.value) workspaceStore.tileChat()
  else workspaceStore.anchorChat()
}
</script>

<template>
  <div class="chat-panel">
    <header v-if="!embedded" class="chat-panel__header">
      <span class="chat-panel__title" :title="conversationTitle">{{ conversationTitle }}</span>
      <div class="chat-panel__actions">
        <ModuleLauncher :conversation-id="props.conversationId ?? null" />
        <UiIconButton
          :label="isAnchored ? 'Apri come pannello' : 'Ancora chat'"
          size="xs"
          variant="ghost"
          @click="toggleAnchor"
        >
          <AppIcon :name="isAnchored ? 'external-link' : 'pin'" :size="13" />
        </UiIconButton>
      </div>
    </header>

    <div ref="messagesContainer" class="chat-panel__messages">
      <div
        v-if="!chatStore.messages.length && !chatStore.isStreamingCurrentConversation"
        class="chat-panel__empty"
      >
        <AppIcon name="message" :size="22" />
        <span>Inizia a scrivere</span>
      </div>

      <MessageBubble
        v-for="msg in chatStore.messages"
        :key="msg.id"
        :message="msg"
        :version-count="msg.version_group_id ? chatStore.getVersionCount(msg.version_group_id) : 1"
        :active-version-index="
          msg.version_group_id ? chatStore.getActiveVersionIndex(msg.version_group_id) : 0
        "
        :edit-disabled="chatStore.isStreamingCurrentConversation"
        :branch-disabled="chatStore.isStreamingCurrentConversation"
        @edit="startEdit"
        @switch-version="handleVersionSwitch"
        @branch="handleBranch"
      />

      <div v-if="chatStore.isStreamingCurrentConversation" class="chat-panel__streaming">
        <StreamingIndicator
          :content="chatStore.currentStreamContent"
          :thinking-content="chatStore.currentThinkingContent"
        />
      </div>
    </div>

    <div class="chat-panel__input">
      <ChatInput
        :disabled="chatStore.isStreamingCurrentConversation"
        :is-connected="isConnected"
        :is-streaming="chatStore.isStreamingCurrentConversation"
        :audio-devices="audioDevices"
        :selected-device-id="selectedDeviceId"
        @send="handleSend"
        @stop="stopGeneration"
        @voice-start="startListening"
        @voice-stop="stopListening"
        @voice-cancel-processing="cancelProcessing"
        @refresh-devices="refreshDevices"
        @select-device="
          (id) => {
            selectedDeviceId = id
          }
        "
      />
    </div>

    <ToolConfirmationDialog
      v-if="pendingConfirmationsList.length > 0"
      :key="pendingConfirmationsList[0].executionId"
      :confirmation="pendingConfirmationsList[0]"
      @respond="respondToConfirmation"
    />

    <MessageEditDialog
      v-if="editingMessageId"
      :original-content="editingContent"
      @submit="submitEdit"
      @cancel="cancelEdit"
    />
  </div>
</template>

<style scoped>
/*
 * Anchored chat blends directly with the workspace background: no card border,
 * radius, shadow or distinct surface. Module tiles stay cards; the chat melts
 * into the surface. When embedded inside a ModulePanel the panel supplies the
 * card chrome, so the same transparent root is correct there too.
 */
.chat-panel {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: transparent;
  border: none;
  border-radius: 0;
  box-shadow: none;
  overflow: hidden;
}

/* Slim blended header — no card chrome, just a hairline under it. */
.chat-panel__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: var(--panel-header-height, 36px);
  flex-shrink: 0;
  padding: 0 var(--space-2) 0 var(--space-3);
  border-bottom: 1px solid var(--border);
  background: transparent;
}

.chat-panel__title {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-panel__actions {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  flex-shrink: 0;
}

.chat-panel__messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-2);
  scroll-behavior: smooth;
}

.chat-panel__messages::-webkit-scrollbar {
  width: 3px;
}

.chat-panel__messages::-webkit-scrollbar-track {
  background: transparent;
}

.chat-panel__messages::-webkit-scrollbar-thumb {
  background: var(--surface-3);
  border-radius: var(--radius-xs);
}

.chat-panel__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: var(--space-2);
  color: var(--text-muted);
  opacity: 0.5;
  font-size: var(--text-xs);
}

.chat-panel__streaming {
  padding: var(--space-1) var(--space-2);
}

.chat-panel__streaming :deep(.bubble-row) {
  justify-content: flex-start;
  margin-bottom: 0;
}

.chat-panel__streaming :deep(.streaming-bubble) {
  max-width: 100%;
  padding: 0;
}

.chat-panel__input {
  flex-shrink: 0;
}
</style>
