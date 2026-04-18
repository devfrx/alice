import { app, shell, BrowserWindow, ipcMain, Menu, MenuItem } from 'electron'
import { join } from 'path'
import { electronApp, optimizer, is } from '@electron-toolkit/utils'
import icon from '../../resources/icon.png?asset'

let mainWindow: BrowserWindow | null = null

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
  const devCsp = [
    "default-src 'self'",
    `script-src 'self' blob: 'wasm-unsafe-eval' ${reactRefreshHash}`,
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: http://localhost:8000 ${tldrawCdn}`,
    `font-src 'self' data: ${tldrawCdn}`,
    `connect-src 'self' blob: ws://localhost:8000 http://localhost:8000 ws://localhost:5173 ${tldrawCdn}`,
    "object-src 'none'"
  ].join('; ')

  const prodCsp = [
    "default-src 'self'",
    "script-src 'self' blob: 'wasm-unsafe-eval'",
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: http://localhost:8000 ${tldrawCdn}`,
    `font-src 'self' data: ${tldrawCdn}`,
    `connect-src 'self' blob: ws://localhost:8000 http://localhost:8000 ${tldrawCdn}`,
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
app.whenReady().then(() => {
  // Set app user model id for windows
  electronApp.setAppUserModelId('com.alice.app')

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

// In this file you can include the rest of your app's specific main process
// code. You can also put them in separate files and require them here.
