/**
 * useChatAttachments — pending image attachments for a chat composer:
 * file-picker handling, drag&drop, clipboard paste, blob-URL thumbnails and
 * cleanup. Extracted from ChatInput.vue so the Horizon cockpit reuses the
 * exact same behaviour.
 */
import { onBeforeUnmount, ref, type Ref } from 'vue'

export interface ChatAttachmentsApi {
  pendingFiles: Ref<File[]>
  isDragOver: Ref<boolean>
  addFiles: (files: File[]) => void
  removeFile: (file: File) => void
  clearAllFiles: () => void
  getThumbnail: (file: File) => string
  handleFileSelect: (event: Event) => void
  handleDragEnter: (event: DragEvent) => void
  handleDragOver: (event: DragEvent) => void
  handleDragLeave: () => void
  handleDrop: (event: DragEvent) => void
  handlePaste: (event: ClipboardEvent) => void
}

/**
 * @param options.accept Gate for accepting image files (e.g. the active
 *   model supports vision). Evaluated at add time.
 */
export function useChatAttachments(options: { accept: () => boolean }): ChatAttachmentsApi {
  const pendingFiles = ref<File[]>([])
  const isDragOver = ref(false)
  const dragCounter = ref(0)
  const thumbnailUrls = ref<Map<File, string>>(new Map())

  /** Add image files to the pending list and generate thumbnails. */
  function addFiles(files: File[]): void {
    const imageFiles = files.filter((f) => f.type.startsWith('image/'))
    if (!options.accept() && imageFiles.length > 0) return
    for (const file of imageFiles) {
      pendingFiles.value.push(file)
      const url = URL.createObjectURL(file)
      thumbnailUrls.value.set(file, url)
    }
  }

  /** Remove a single pending file and revoke its thumbnail URL. */
  function removeFile(file: File): void {
    const url = thumbnailUrls.value.get(file)
    if (url) URL.revokeObjectURL(url)
    thumbnailUrls.value.delete(file)
    pendingFiles.value = pendingFiles.value.filter((f) => f !== file)
  }

  /** Clear all pending files and revoke every thumbnail URL. */
  function clearAllFiles(): void {
    for (const url of thumbnailUrls.value.values()) {
      URL.revokeObjectURL(url)
    }
    thumbnailUrls.value.clear()
    pendingFiles.value = []
  }

  /** Get the blob thumbnail URL for a given file. */
  function getThumbnail(file: File): string {
    return thumbnailUrls.value.get(file) ?? ''
  }

  /** Handle files selected via a hidden `<input type="file">`. */
  function handleFileSelect(event: Event): void {
    const input = event.target as HTMLInputElement
    if (input.files) {
      addFiles(Array.from(input.files))
    }
    // Reset so the same file can be selected again
    input.value = ''
  }

  /** @internal */
  function handleDragEnter(event: DragEvent): void {
    event.preventDefault()
    dragCounter.value++
    isDragOver.value = true
  }

  /** @internal */
  function handleDragOver(event: DragEvent): void {
    event.preventDefault()
  }

  /** @internal */
  function handleDragLeave(): void {
    dragCounter.value--
    if (dragCounter.value === 0) isDragOver.value = false
  }

  /** @internal */
  function handleDrop(event: DragEvent): void {
    event.preventDefault()
    dragCounter.value = 0
    isDragOver.value = false
    if (event.dataTransfer?.files) {
      addFiles(Array.from(event.dataTransfer.files))
    }
  }

  /** Intercept paste events and extract image data from the clipboard. */
  function handlePaste(event: ClipboardEvent): void {
    const items = event.clipboardData?.items
    if (!items) return
    const imageFiles: File[] = []
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.type.startsWith('image/')) {
        const file = item.getAsFile()
        if (file) imageFiles.push(file)
      }
    }
    if (imageFiles.length > 0) {
      event.preventDefault()
      addFiles(imageFiles)
    }
  }

  onBeforeUnmount(() => clearAllFiles())

  return {
    pendingFiles,
    isDragOver,
    addFiles,
    removeFile,
    clearAllFiles,
    getThumbnail,
    handleFileSelect,
    handleDragEnter,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handlePaste
  }
}
