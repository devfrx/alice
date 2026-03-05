<script setup lang="ts">
/**
 * ChatView.vue — Full chat view with message history, streaming
 * indicator, and an input area.
 *
 * Auto-scrolls on new messages.  Creates a blank conversation on
 * mount when none is active.
 */
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import ChatInput from '../components/chat/ChatInput.vue'
import MessageBubble from '../components/chat/MessageBubble.vue'
import StreamingIndicator from '../components/chat/StreamingIndicator.vue'
import { useChat } from '../composables/useChat'
import { useChatStore } from '../stores/chat'

const chatStore = useChatStore()
const { sendMessage: send, isConnected, stopGeneration } = useChat()

/** Template ref for the scrollable message container. */
const messagesContainer = ref<HTMLElement | null>(null)

/** Whether the scroll-to-bottom button is visible. */
const showScrollButton = ref(false)

/**
 * Scroll the message container to the bottom.
 * Skips the scroll when the user has scrolled up to read history,
 * unless `force` is true (e.g. after the user sends a message).
 */
function scrollToBottom(force = false): void {
  const el = messagesContainer.value
  if (!el) return
  if (!force) {
    const threshold = 100
    if (el.scrollHeight - el.scrollTop - el.clientHeight > threshold) return
  }
  nextTick(() => {
    if (el) el.scrollTop = el.scrollHeight
  })
}

/** Track scroll position to show/hide the scroll-to-bottom button. */
function handleScroll(): void {
  const el = messagesContainer.value
  if (!el) return
  const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
  showScrollButton.value = distanceFromBottom > 200
}

/** Handle a send event from the ChatInput component. */
async function handleSend(content: string, attachments: File[]): Promise<void> {
  await send(content, undefined, attachments)
  scrollToBottom(true)
}

// Auto-scroll whenever the message list or streaming content changes.
watch(
  () => [chatStore.messages.length, chatStore.currentStreamContent, chatStore.currentThinkingContent],
  () => scrollToBottom()
)

// On mount: ensure a conversation exists so the user can start chatting.
onMounted(() => {
  if (!chatStore.currentConversation) {
    chatStore.createConversation()
  }
  scrollToBottom()
  messagesContainer.value?.addEventListener('scroll', handleScroll)
})

onUnmounted(() => {
  messagesContainer.value?.removeEventListener('scroll', handleScroll)
})
</script>

<template>
  <div class="chat-view">
    <!-- Messages area -->
    <div ref="messagesContainer" class="chat-view__messages">
      <!-- Empty state -->
      <div v-if="chatStore.messages.length === 0 && !chatStore.isStreaming" class="chat-view__empty">
        <div class="chat-view__empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1"
            stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 6v6l4 2" />
          </svg>
        </div>
        <p class="chat-view__empty-title">O.M.N.I.A.</p>
        <p class="chat-view__empty-sub">Il tuo assistente è pronto. Scrivi un messaggio per iniziare.</p>
      </div>

      <!-- Message list -->
      <MessageBubble v-for="msg in chatStore.messages" :key="msg.id" :message="msg" />

      <!-- Streaming response -->
      <StreamingIndicator v-if="chatStore.isStreaming" :content="chatStore.currentStreamContent"
        :thinking-content="chatStore.currentThinkingContent" />

      <!-- Scroll to bottom button -->
      <Transition name="scroll-btn">
        <button v-if="showScrollButton" class="chat-view__scroll-btn" aria-label="Scorri in fondo"
          @click="scrollToBottom(true)">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
      </Transition>
    </div>

    <!-- Input -->
    <ChatInput :disabled="false" :is-connected="isConnected" :is-streaming="chatStore.isStreaming"
      @send="handleSend" @stop="stopGeneration" />
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* ----------------------------------------------- Messages area */
.chat-view__messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  scroll-behavior: smooth;
}

/* Custom dark scrollbar */
.chat-view__messages::-webkit-scrollbar {
  width: 6px;
}

.chat-view__messages::-webkit-scrollbar-track {
  background: transparent;
}

.chat-view__messages::-webkit-scrollbar-thumb {
  background: rgba(201, 168, 76, 0.1);
  border-radius: 3px;
}

.chat-view__messages::-webkit-scrollbar-thumb:hover {
  background: rgba(201, 168, 76, 0.2);
}

/* ----------------------------------------------- Empty state */
.chat-view__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 12px;
  opacity: 0.45;
  user-select: none;
}

.chat-view__empty-icon {
  color: var(--accent);
  opacity: 0.6;
  animation: emptyBreathing 3s ease-in-out infinite;
}

.chat-view__empty-title {
  font-size: 1.6rem;
  font-weight: 200;
  letter-spacing: 0.25em;
  color: var(--text-primary);
  text-shadow: 0 0 30px rgba(201, 168, 76, 0.15);
}

.chat-view__empty-sub {
  font-size: 0.85rem;
  color: var(--text-secondary);
  max-width: 320px;
  text-align: center;
  line-height: 1.5;
}

/* ------------------------------------------ Scroll-to-bottom button */
.chat-view__scroll-btn {
  position: sticky;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--border-hover);
  background: var(--bg-tertiary);
  color: var(--accent);
  cursor: pointer;
  box-shadow: var(--shadow-md);
  transition: background 0.2s ease, border-color 0.2s ease;
  z-index: 10;
}

.chat-view__scroll-btn:hover {
  background: var(--bg-secondary);
  border-color: var(--accent-border);
}

/* Scroll button enter/leave transition */
.scroll-btn-enter-active,
.scroll-btn-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}

.scroll-btn-enter-from,
.scroll-btn-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(8px);
}

/* ------------------------------------------ Empty state animation */
@keyframes emptyBreathing {
  0%, 100% {
    transform: translateY(0);
    opacity: 0.6;
  }
  50% {
    transform: translateY(-4px);
    opacity: 0.9;
  }
}
</style>
