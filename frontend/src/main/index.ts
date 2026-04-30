import { app, shell, BrowserWindow, ipcMain, Menu, MenuItem, dialog } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import { existsSync } from 'fs'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'

let mainWindow: BrowserWindow | null = null

// ─── Packaged backend lifecycle ────────────────────────────────────────
// In dev mode the backend is started by scripts/start-dev.ps1.  When the
// app is packaged we spawn the PyInstaller-frozen backend.exe shipped via
// extraResources (see frontend/electron-builder.yml) and tear it down on
// app.quit().  TODO Phase 1.5: electron-updater integration goes here.
let backendProcess: ChildProcess | null = null
let backendShuttingDown = false
const BACKEND_PORT = Number(process.env.BACKEND_PORT) || 8000
const BACKEND_HOST = '127.0.0.1'
const BACKEND_HEALTH_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}/api/health`
const BACKEND_STARTUP_TIMEOUT_MS = 30_000

/**
 * Resolve the absolute path to the bundled backend executable.
 * extraResources copies ``frontend/resources/backend/`` to
 * ``<install-dir>/resources/backend/`` (exposed via ``process.resourcesPath``).
 */
function resolveBackendExe(): string | null {
  if (!app.isPackaged) return null
  const exe = join(process.resourcesPath, 'backend', 'backend.exe')
  return existsSync(exe) ? exe : null
}

/**
 * Poll ``/api/health`` until the backend responds 200 or the deadline elapses.
 */
async function waitForBackendHealth(timeoutMs = BACKEND_STARTUP_TIMEOUT_MS): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (backendProcess && backendProcess.exitCode !== null) {
      console.error('[backend] exited prematurely with code', backendProcess.exitCode)
      return false
    }
    try {
      const res = await fetch(BACKEND_HEALTH_URL, { signal: AbortSignal.timeout(1500) })
      if (res.ok) return true
    } catch {
      // Not ready yet — keep polling.
    }
    await new Promise((r) => setTimeout(r, 400))
  }
  return false
}

/**
 * Spawn the packaged backend.exe (no-op in dev mode).  Resolves once the
 * health probe succeeds; rejects on failure so the caller can surface a
 * useful error to the user.
 */
async function startPackagedBackend(): Promise<void> {
  const exe = resolveBackendExe()
  if (!exe) return  // dev mode or missing binary — nothing to spawn
  console.log('[backend] spawning', exe, 'on', BACKEND_HOST + ':' + BACKEND_PORT)
  backendProcess = spawn(exe, ['--host', BACKEND_HOST, '--port', String(BACKEND_PORT)], {
    cwd: join(process.resourcesPath, 'backend'),
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true
  })
  backendProcess.stdout?.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`))
  backendProcess.stderr?.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`))
  backendProcess.on('exit', (code, signal) => {
    console.log(`[backend] exited code=${code} signal=${signal}`)
    backendProcess = null
    if (!backendShuttingDown) {
      // Backend died unexpectedly — tear the UI down so the user sees the
      // problem instead of a silently-broken window.
      app.quit()
    }
  })
  const healthy = await waitForBackendHealth()
  if (!healthy) {
    stopPackagedBackend()
    throw new Error(`Backend failed to become healthy within ${BACKEND_STARTUP_TIMEOUT_MS}ms`)
  }
}

/** Best-effort termination of the spawned backend process. */
function stopPackagedBackend(): void {
  if (!backendProcess) return
  backendShuttingDown = true
  try {
    backendProcess.kill()
  } catch (err) {
    console.warn('[backend] kill() failed', err)
  }
  backendProcess = null
}

function createWindow(): void {
  // Create the browser window (frameless for custom title bar).
  mainWindow = new BrowserWindow({
    width: 900,
    height: 670,
    show: false,
    frame: false,
    titleBarStyle: 'hidden',
    autoHideMenuBar: true,
    ...(process.platform === 'linux' ? { icon } : {}),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true,
      nodeIntegration: false,
      contextIsolation: true
    }
  })

  // --- Content Security Policy (dev-aware) --------------------------------
  // Hash allows the React Fast Refresh preamble injected by @vitejs/plugin-react
  const reactRefreshHash = "'sha256-Z2/iFzh9VMlVkEOar1f/oSHWwQk3ve1qk/C2WdsC4Xk='"
  // tldraw CDN for translations, fonts, and icons
  const tldrawCdn = 'https://cdn.tldraw.com'

  // Resolve the backend origin from the environment so a port fallback in
  // start-dev.ps1 (e.g. 8001 when 8000 is held by another process) is
  // automatically reflected in the CSP.  Falls back to localhost:8000.
  // Use 127.0.0.1 (not localhost) so the CSP matches the actual origin used
  // by the renderer; see services/api.ts for the same reasoning.
  const backendHttp = (process.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '')
  const backendWs = backendHttp.replace(/^http/, 'ws')

  const devCsp = [
    "default-src 'self'",
    `script-src 'self' blob: 'wasm-unsafe-eval' ${reactRefreshHash}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${backendHttp} ${tldrawCdn}`,
    `font-src 'self' data: ${tldrawCdn}`,
    `connect-src 'self' blob: ${backendWs} ${backendHttp} ws://localhost:5173 ${tldrawCdn}`,
    "object-src 'none'"
  ].join('; ')

  const prodCsp = [
    "default-src 'self'",
    "script-src 'self' blob: 'wasm-unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${backendHttp} ${tldrawCdn}`,
    `font-src 'self' data: ${tldrawCdn}`,
    `connect-src 'self' blob: ${backendWs} ${backendHttp} ${tldrawCdn}`,
    "object-src 'none'"
  ].join('; ')

  mainWindow.webContents.session.webRequest.onHeadersReceived((details, callback) => {
    callback({
      responseHeaders: {
        ...details.responseHeaders,
        'Content-Security-Policy': [is.dev ? devCsp : prodCsp]
      }
    })
  })

  mainWindow.on('ready-to-show', () => {
    mainWindow?.show()
  })

  // Null reference when window is destroyed — prevents calling methods on
  // a destroyed BrowserWindow (critical for macOS dock-click re-creation).
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // Forward maximize/unmaximize state to renderer for accurate title bar UI.
  mainWindow.on('maximize', () => {
    mainWindow?.webContents.send('window-maximized-change', true)
  })
  mainWindow.on('unmaximize', () => {
    mainWindow?.webContents.send('window-maximized-change', false)
  })

  mainWindow.webContents.setWindowOpenHandler((details) => {
    // Forward only safe external schemes to the OS handler; deny everything else.
    try {
      const url = new URL(details.url)
      if (url.protocol === 'http:' || url.protocol === 'https:' || url.protocol === 'mailto:') {
        shell.openExternal(details.url)
      }
    } catch {
      // Invalid URL — silently deny.
    }
    return { action: 'deny' }
  })

  // Block in-app navigation away from the renderer entry point. Any attempt to
  // navigate (e.g. malicious link click, drag-drop URL) is opened externally so
  // the renderer process can never load untrusted content.
  mainWindow.webContents.on('will-navigate', (event, navigationUrl) => {
    const currentUrl = mainWindow?.webContents.getURL() ?? ''
    try {
      const target = new URL(navigationUrl)
      const current = currentUrl ? new URL(currentUrl) : null
      // Allow same-origin navigation (HMR, hash routing) but block everything else.
      if (current && target.origin === current.origin) return
      event.preventDefault()
      if (target.protocol === 'http:' || target.protocol === 'https:') {
        shell.openExternal(navigationUrl)
      }
    } catch {
      event.preventDefault()
    }
  })

  // HMR for renderer base on electron-vite cli.
  // Load the remote URL for development or the local html file for production.
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }

  // Open DevTools automatically in dev mode
  if (is.dev) {
    mainWindow.webContents.openDevTools()
  }
}

// This method will be called when Electron has finished
// initialization and is ready to create browser windows.
// Some APIs can only be used after this event occurs.
app.whenReady().then(async () => {
  // Set app user model id for windows
  electronApp.setAppUserModelId('com.alice.app')

  // Packaged builds: start the bundled backend before creating any window
  // so the renderer never races the API.  In dev mode this is a no-op and
  // the user is expected to have ``scripts/start-dev.ps1`` running.
  try {
    await startPackagedBackend()
  } catch (err) {
    console.error('[backend] startup failed:', err)
    // TODO Phase 1.5: surface this via a native dialog + first-run wizard.
  }

  // Default open or close DevTools by F12 in development
  // and ignore CommandOrControl + R in production.
  // see https://github.com/alex8088/electron-toolkit/tree/master/packages/utils
  app.on('browser-window-created', (_, window) => {
    optimizer.watchWindowShortcuts(window)
  })

  // IPC handlers (registered once to avoid duplicates on macOS window re-creation)
  ipcMain.on('window-minimize', () => mainWindow?.minimize())
  ipcMain.on('window-maximize', () => {
    if (!mainWindow) return
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize()
    } else {
      mainWindow.maximize()
    }
  })
  ipcMain.on('window-close', () => mainWindow?.close())
  ipcMain.on('show-in-folder', (_event, filePath: unknown) => {
    if (typeof filePath === 'string' && filePath.length > 0) {
      shell.showItemInFolder(filePath)
    }
  })

  // Native directory picker — used by the Services view (Trellis config).
  ipcMain.handle('select-directory', async (_event, defaultPath?: string) => {
    if (!mainWindow) return null
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Seleziona cartella',
      properties: ['openDirectory'],
      defaultPath: typeof defaultPath === 'string' ? defaultPath : undefined,
    })
    if (result.canceled || result.filePaths.length === 0) return null
    return result.filePaths[0]
  })

  // Native context menu for text selection and editable fields.
  // Without this handler Electron shows no context menu at all on right-click,
  // making copy/paste inaccessible via mouse.
  app.on('browser-window-created', (_, win) => {
    win.webContents.on('context-menu', (_e, params) => {
      const menu = new Menu()

      // Spelling suggestions (when available)
      if (params.dictionarySuggestions.length > 0) {
        for (const suggestion of params.dictionarySuggestions) {
          menu.append(new MenuItem({
            label: suggestion,
            click: () => win.webContents.replaceMisspelling(suggestion),
          }))
        }
        menu.append(new MenuItem({ type: 'separator' }))
      }

      // Edit actions — shown when text is selected or the target is editable
      if (params.isEditable) {
        menu.append(new MenuItem({ role: 'undo', label: 'Annulla' }))
        menu.append(new MenuItem({ role: 'redo', label: 'Ripeti' }))
        menu.append(new MenuItem({ type: 'separator' }))
        menu.append(new MenuItem({ role: 'cut', label: 'Taglia', enabled: params.editFlags.canCut }))
        menu.append(new MenuItem({ role: 'copy', label: 'Copia', enabled: params.editFlags.canCopy }))
        menu.append(new MenuItem({ role: 'paste', label: 'Incolla', enabled: params.editFlags.canPaste }))
        menu.append(new MenuItem({ role: 'selectAll', label: 'Seleziona tutto' }))
      } else if (params.selectionText.trim().length > 0) {
        menu.append(new MenuItem({ role: 'copy', label: 'Copia', enabled: params.editFlags.canCopy }))
        menu.append(new MenuItem({ type: 'separator' }))
        menu.append(new MenuItem({ role: 'selectAll', label: 'Seleziona tutto' }))
      }

      if (menu.items.length > 0) {
        menu.popup({ window: win })
      }
    })
  })

  createWindow()

  app.on('activate', function () {
    // On macOS it's common to re-create a window in the app when the
    // dock icon is clicked and there are no other windows open.
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

// Quit when all windows are closed, except on macOS. There, it's common
// for applications and their menu bar to stay active until the user quits
// explicitly with Cmd + Q.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

// Make sure the spawned backend is reaped when the app is exiting, no
// matter which path triggered the shutdown (window close, Cmd+Q, OS
// signal, unhandled exception in the main process).
app.on('before-quit', () => {
  stopPackagedBackend()
})
app.on('will-quit', () => {
  stopPackagedBackend()
})

// In this file you can include the rest of your app's specific main process
// code. You can also put them in separate files and require them here.
