import { app, shell, BrowserWindow, ipcMain, Menu, MenuItem, dialog, session, type WebContents } from 'electron'
import { spawn, spawnSync, ChildProcess } from 'child_process'
import { existsSync, mkdirSync, appendFileSync } from 'fs'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'

let mainWindow: BrowserWindow | null = null

// Keep Electron runtime paths aligned with electron-builder's productName.
// Without this, app.getPath('userData') follows package.json's technical
// name (alice-frontend), which hides production logs in an unexpected folder.
app.setName('Alice')

// ─── Diagnostic logging ────────────────────────────────────────────────
// When Alice.exe is launched from Explorer it has no console attached, so
// any crash in the main process or any renderer/GPU subprocess vanishes
// silently — making "the app closed itself" reports impossible to debug.
// We mirror everything to a rolling log under userData so post-mortem
// inspection is always possible without re-launching from a terminal.
const LOG_DIR = join(app.getPath('userData'), 'logs')
const LOG_FILE = join(LOG_DIR, 'main.log')
try {
  mkdirSync(LOG_DIR, { recursive: true })
} catch {
  // best-effort: logging must never crash the app
}

function logToFile(level: string, args: unknown[]): void {
  try {
    const line = `${new Date().toISOString()} [${level}] ${args
      .map((a) => (a instanceof Error ? `${a.message}\n${a.stack ?? ''}` : typeof a === 'string' ? a : JSON.stringify(a)))
      .join(' ')}\n`
    appendFileSync(LOG_FILE, line)
  } catch {
    // swallow — never let logging cause a crash
  }
}

// Tee console.* through the file logger so messages survive even when no
// console is attached (typical for double-click launches from Explorer).
const _origLog = console.log.bind(console)
const _origWarn = console.warn.bind(console)
const _origError = console.error.bind(console)
console.log = (...args: unknown[]) => { logToFile('log', args); try { _origLog(...args) } catch { /* no console */ } }
console.warn = (...args: unknown[]) => { logToFile('warn', args); try { _origWarn(...args) } catch { /* no console */ } }
console.error = (...args: unknown[]) => { logToFile('error', args); try { _origError(...args) } catch { /* no console */ } }

// Catch-all: surface uncaught failures in the main process so the user
// can attach the log file to a bug report instead of seeing a silent exit.
process.on('uncaughtException', (err) => {
  console.error('[main] uncaughtException:', err)
})
process.on('unhandledRejection', (reason) => {
  console.error('[main] unhandledRejection:', reason)
})

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
const BACKEND_STARTUP_TIMEOUT_MS = 120_000
const EXISTING_BACKEND_STARTUP_TIMEOUT_MS = 90_000

function isTrustedRendererOrigin(requestingUrlOrOrigin: string): boolean {
  if (!requestingUrlOrOrigin) return false
  try {
    const parsed = new URL(requestingUrlOrOrigin)
    if (parsed.protocol === 'file:') return true
    if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
      return parsed.origin === new URL(process.env['ELECTRON_RENDERER_URL']).origin
    }
    return false
  } catch {
    if (requestingUrlOrOrigin === 'file://' || requestingUrlOrOrigin === 'null') {
      return true
    }
  }
  if (is.dev && process.env['ELECTRON_RENDERER_URL']) {
    try {
      return requestingUrlOrOrigin === new URL(process.env['ELECTRON_RENDERER_URL']).origin
    } catch {
      return false
    }
  }
  return false
}

function isMainWindowContents(contents: WebContents): boolean {
  return mainWindow !== null && contents.id === mainWindow.webContents.id
}

/**
 * Allow microphone capture only for Alice's own renderer.
 *
 * Electron's default media permission prompt is fragile in packaged Windows
 * builds launched from file://. Handling it explicitly keeps voice startup
 * deterministic and avoids native permission callbacks being invoked outside
 * our control.
 */
function configureMediaPermissions(): void {
  session.defaultSession.setPermissionRequestHandler((contents, permission, callback, details) => {
    if (permission !== 'media') {
      callback(false)
      return
    }
    callback(isMainWindowContents(contents) && isTrustedRendererOrigin(details.requestingUrl))
  })

  session.defaultSession.setPermissionCheckHandler((contents, permission, requestingOrigin) => {
    if (permission !== 'media') return false
    return contents !== null && isMainWindowContents(contents) && isTrustedRendererOrigin(requestingOrigin)
  })
}

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
 * Probe ``/api/health`` once with a short timeout.  Used to detect whether
 * an instance of the backend is already serving on ``BACKEND_PORT`` so we
 * can either reuse it (avoids the "address already in use" crash that
 * happens when a previous run leaked a backend.exe) or fail fast with a
 * clear message.
 */
async function probeBackendHealth(timeoutMs = 1500): Promise<boolean> {
  try {
    const res = await fetch(BACKEND_HEALTH_URL, { signal: AbortSignal.timeout(timeoutMs) })
    return res.ok
  } catch {
    return false
  }
}

/**
 * Return the PID that owns ``BACKEND_PORT`` on loopback, if any.
 */
function getBackendPortOwnerPid(): number | null {
  if (process.platform !== 'win32') return null
  // ``netstat -ano -p tcp`` is available on every supported Windows SKU
  // and does not require admin.  Parsing its output is more reliable than
  // attempting to bind a probe socket from Node, which would race with
  // the actual spawn.
  const r = spawnSync('netstat', ['-ano', '-p', 'tcp'], {
    encoding: 'utf8',
    windowsHide: true,
  })
  if (r.status !== 0 || !r.stdout) return null
  const needle = `:${BACKEND_PORT}`
  for (const line of r.stdout.split(/\r?\n/)) {
    if (!line.includes('LISTENING') || !line.includes(needle)) continue
    const parts = line.trim().split(/\s+/)
    const localAddress = parts[1] ?? ''
    const pid = Number(parts[4])
    if (localAddress.endsWith(needle) && Number.isInteger(pid) && pid > 0) {
      return pid
    }
  }
  return null
}

/**
 * Best-effort termination of a stale process tree that owns BACKEND_PORT.
 */
function killProcessTree(pid: number): void {
  if (process.platform !== 'win32') return
  spawnSync('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true })
}

function logBackendChunk(stream: 'stdout' | 'stderr', chunk: Buffer): void {
  const text = chunk.toString('utf8').replace(/\r?\n$/, '')
  if (!text) return
  for (const line of text.split(/\r?\n/)) {
    if (line.trim()) console.log(`[backend:${stream}] ${line}`)
  }
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

  // Pre-flight: if a previous run left a healthy backend on the port we
  // simply reuse it instead of spawning a duplicate that would crash on
  // bind() with WinError 10048 and take the whole app down with it.
  if (await probeBackendHealth()) {
    console.log(`[backend] reusing existing instance on ${BACKEND_HOST}:${BACKEND_PORT}`)
    return
  }
  // Port bound but not healthy often means the user started backend.exe a
  // few seconds before Alice.  The packaged backend can take ~20-60s to
  // initialise STT/TTS/plugins, so wait before treating the owner as stale.
  const portOwnerPid = getBackendPortOwnerPid()
  if (portOwnerPid !== null) {
    console.warn(
      `[backend] port ${BACKEND_PORT} owned by pid ${portOwnerPid}; waiting for health`,
    )
    if (await waitForBackendHealth(EXISTING_BACKEND_STARTUP_TIMEOUT_MS)) {
      console.log(`[backend] reusing existing instance on ${BACKEND_HOST}:${BACKEND_PORT}`)
      return
    }
    console.warn(`[backend] killing stale backend port owner pid=${portOwnerPid}`)
    killProcessTree(portOwnerPid)
    await new Promise((r) => setTimeout(r, 750))
  }

  console.log('[backend] spawning', exe, 'on', BACKEND_HOST + ':' + BACKEND_PORT)
  backendShuttingDown = false
  backendProcess = spawn(exe, ['--host', BACKEND_HOST, '--port', String(BACKEND_PORT)], {
    cwd: join(process.resourcesPath, 'backend'),
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true
  })
  backendProcess.stdout?.on('data', (chunk: Buffer) => logBackendChunk('stdout', chunk))
  backendProcess.stderr?.on('data', (chunk: Buffer) => logBackendChunk('stderr', chunk))
  backendProcess.on('exit', (code, signal) => {
    console.log(`[backend] exited code=${code} signal=${signal}`)
    backendProcess = null
    if (!backendShuttingDown) {
      mainWindow?.webContents.send('backend-process-exited', { code, signal })
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
  const pid = backendProcess.pid
  try {
    if (process.platform === 'win32' && pid !== undefined) {
      killProcessTree(pid)
    } else {
      backendProcess.kill()
    }
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

  // Capture renderer / helper-process crashes that would otherwise close the
  // window without any visible error.  These are the usual suspects behind
  // "the app silently disappeared after a few seconds" reports.
  mainWindow.webContents.on('render-process-gone', (_e, details) => {
    console.error('[renderer] render-process-gone', details)
  })
  mainWindow.webContents.on('unresponsive', () => {
    console.error('[renderer] unresponsive')
  })
  mainWindow.webContents.on('responsive', () => {
    console.warn('[renderer] responsive again')
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

  // App-level crash hooks for GPU / utility / pepper-plugin sub-processes.
  // Without these, a GPU process death is invisible and the user just sees
  // the window vanish.
  app.on('child-process-gone', (_e, details) => {
    console.error('[app] child-process-gone', details)
  })
  app.on('render-process-gone', (_e, _wc, details) => {
    console.error('[app] render-process-gone', details)
  })
  configureMediaPermissions()

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
