/**
 * Electron Detection and Utilities
 * 
 * This module provides utilities to detect if the app is running in Electron
 * and access Electron-specific APIs via the preload script.
 */

export interface ElectronAPI {
  getAppVersion: () => Promise<string>;
  getUserDataPath: () => Promise<string>;
  getDataPath: () => Promise<string>;
  getLogsPath: () => Promise<string>;
  getConfigPath: () => Promise<string>;
  restartApp: () => Promise<void>;
  platform: string;
  isDev: boolean;
}

/**
 * Check if running in Electron environment
 */
export function isElectron(): boolean {
  return !!(window as any).electronAPI;
}

/**
 * Get the Electron API if available
 */
export function getElectronAPI(): ElectronAPI | null {
  if (isElectron()) {
    return (window as any).electronAPI as ElectronAPI;
  }
  return null;
}

/**
 * Get app version (Electron or fallback)
 */
export async function getAppVersion(): Promise<string> {
  const api = getElectronAPI();
  if (api) {
    return await api.getAppVersion();
  }
  // Fallback for web mode
  return import.meta.env.VITE_APP_VERSION || '1.0.0-dev';
}

/**
 * Get user data path (Electron only)
 */
export async function getUserDataPath(): Promise<string | null> {
  const api = getElectronAPI();
  if (api) {
    return await api.getUserDataPath();
  }
  return null;
}

/**
 * Get data path (Electron only)
 */
export async function getDataPath(): Promise<string | null> {
  const api = getElectronAPI();
  if (api) {
    return await api.getDataPath();
  }
  return null;
}

/**
 * Get logs path (Electron only)
 */
export async function getLogsPath(): Promise<string | null> {
  const api = getElectronAPI();
  if (api) {
    return await api.getLogsPath();
  }
  return null;
}

/**
 * Get config path (Electron only)
 */
export async function getConfigPath(): Promise<string | null> {
  const api = getElectronAPI();
  if (api) {
    return await api.getConfigPath();
  }
  return null;
}

/**
 * Restart the app (Electron only)
 */
export async function restartApp(): Promise<void> {
  const api = getElectronAPI();
  if (api) {
    await api.restartApp();
  }
}

/**
 * Get platform information
 */
export function getPlatform(): string {
  const api = getElectronAPI();
  if (api) {
    return api.platform;
  }
  return navigator.platform;
}

/**
 * Check if in development mode
 */
export function isDevMode(): boolean {
  const api = getElectronAPI();
  if (api) {
    return api.isDev;
  }
  return import.meta.env.DEV;
}
