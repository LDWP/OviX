/**
 * OviX Desktop - Preload Script
 * 
 * This script runs before the renderer process and provides
 * a secure bridge between the main process and the renderer.
 * It exposes only the necessary APIs via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron');

// Expose protected methods that allow the renderer process to use
// the ipcRenderer without exposing the entire object
contextBridge.exposeInMainWorld('electronAPI', {
  // App information
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),
  
  // Paths
  getUserDataPath: () => ipcRenderer.invoke('get-user-data-path'),
  getDataPath: () => ipcRenderer.invoke('get-data-path'),
  getLogsPath: () => ipcRenderer.invoke('get-logs-path'),
  getConfigPath: () => ipcRenderer.invoke('get-config-path'),
  
  // App control
  restartApp: () => ipcRenderer.invoke('restart-app'),
  
  // Platform detection
  platform: process.platform,
  isDev: process.env.NODE_ENV === 'development' || process.argv.includes('--dev')
});

// Log that preload script has loaded
console.log('OviX Desktop preload script loaded');
