import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'
import { electronAPI } from '@electron-toolkit/preload'

/** Window control API exposed to the renderer process */
const windowControls = {
  /** Minimize the application window */
  minimize: (): void => ipcRenderer.send('window-minimize'),
  /** Toggle maximize/restore of the application window */
  maximize: (): void => ipcRenderer.send('window-maximize'),
  /** Close the application window */
  close: (): void => ipcRenderer.send('window-close'),
  /** Register a callback for maximize/unmaximize state changes. Returns cleanup fn. */
  onMaximizeChange: (callback: (maximized: boolean) => void): (() => void) => {
    const handler = (_e: IpcRendererEvent, maximized: boolean): void => { callback(maximized) }
    ipcRenderer.on('window-maximized-change', handler)
    return (): void => { ipcRenderer.removeListener('window-maximized-change', handler) }
  }
}

const fileOps = {
  /** Open the system file explorer with the given file selected. */
  showInFolder: (filePath: string): void => ipcRenderer.send('show-in-folder', filePath),
  /** Open a native directory picker.  Resolves to the chosen path or null. */
  selectDirectory: (defaultPath?: string): Promise<string | null> =>
    ipcRenderer.invoke('select-directory', defaultPath)
}

// Use `contextBridge` APIs to expose Electron APIs to
// renderer only if context isolation is enabled, otherwise
// just add to the DOM global.
if (process.contextIsolated) {
  try {
    contextBridge.exposeInMainWorld('electron', { ...electronAPI, windowControls, fileOps })
  } catch (error) {
    console.error(error)
  }
} else {
  // @ts-ignore (define in dts)
  window.electron = { ...electronAPI, windowControls, fileOps }
}
