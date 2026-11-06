'use strict'
const { contextBridge, ipcRenderer } = require('electron')
const allowed = new Set(['status', 'start-service', 'stop-service', 'capture-start', 'capture-stop', 'hud-open', 'hud-close', 'workbench', 'browser', 'logs', 'update-status', 'update-check', 'update-download', 'update-install', 'update-help'])
contextBridge.exposeInMainWorld('rocoApp', { invoke: (action, value) => {
  if (!allowed.has(action)) return Promise.reject(Error('Unsupported action'))
  return ipcRenderer.invoke('desktop:invoke', action, value)
} })
