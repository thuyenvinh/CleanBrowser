const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('cleanbrowserDesktop', {
  getVersion: () => ipcRenderer.invoke('app-version'),
  platform: process.platform,
});
