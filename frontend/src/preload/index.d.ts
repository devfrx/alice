import { ElectronAPI } from '@electron-toolkit/preload'

/** API for controlling the native window from the renderer process */
interface WindowControls {
  /** Minimize the application window */
  minimize: () => void
  /** Toggle maximize/restore of the application window */
  maximize: () => void
  /** Close the application window */
  close: () => void
  /** Register a callback for maximize/unmaximize state changes. Returns cleanup fn. */
  onMaximizeChange: (callback: (maximized: boolean) => void) => () => void
}

/** File operations exposed to the renderer process */
interface FileOps {
  /** Open the system file explorer with the given file selected. */
  showInFolder: (filePath: string) => void
  /** Open a native directory picker and resolve to the selected path. */
  selectDirectory: (defaultPath?: string) => Promise<string | null>
}

declare global {
  interface Window {
    electron: ElectronAPI & { windowControls: WindowControls; fileOps: FileOps }
  }
}
