const { app, BrowserWindow, Menu, Tray, shell, ipcMain } = require('electron');
const path = require('path');

const APP_URL = process.env.CLEANBROWSER_URL || 'http://localhost:8080';

let mainWindow = null;
let tray = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 600,
    title: 'CleanBrowser',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadURL(APP_URL);
  // Open external links in default browser, not inside Electron
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (!url.startsWith(APP_URL)) {
      shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'allow' };
  });
  mainWindow.on('closed', () => { mainWindow = null; });
}

function createTray() {
  // Tray icon — Phase 6 phase 1 uses default icon. Replace with assets/tray.png later.
  try {
    tray = new Tray(path.join(__dirname, 'assets', 'tray.png'));
  } catch (e) {
    console.warn('Tray icon missing; skipping tray.');
    return;
  }
  const ctx = Menu.buildFromTemplate([
    { label: 'Show CleanBrowser', click: () => mainWindow?.show() },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() },
  ]);
  tray.setToolTip('CleanBrowser');
  tray.setContextMenu(ctx);
}

app.whenReady().then(() => {
  createWindow();
  createTray();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

// IPC for future native features (notifications, file system, etc.)
ipcMain.handle('app-version', () => app.getVersion());
