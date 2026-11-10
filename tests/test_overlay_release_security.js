'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
const { EventEmitter } = require('node:events')

function harness (packaged, env = {}) {
  const windows = [], switches = [], writes = [], reads = [], directories = []
  const ipcMain = new EventEmitter()
  let ready, quits = 0
  class Window extends EventEmitter {
    constructor (options) {
      super()
      this.options = options; this.bounds = { x: options.x, y: options.y, width: options.width, height: options.height }
      this.urls = []; this.destroyed = false
      this.webContents = new EventEmitter()
      Object.assign(this.webContents, {
        setWindowOpenHandler: handler => { this.openHandler = handler },
        session: {
          setPermissionRequestHandler: handler => { this.requestPermission = handler },
          setPermissionCheckHandler: handler => { this.checkPermission = handler }
        },
        executeJavaScript: async () => '', insertCSS: async () => '', getURL: () => this.urls.at(-1) || ''
      })
      windows.push(this)
    }
    isDestroyed () { return this.destroyed }
    isVisible () { return true }
    getBounds () { return { ...this.bounds } }
    setBounds (value) { this.bounds = { ...value } }
    getPosition () { return [this.bounds.x, this.bounds.y] }
    setAlwaysOnTop () {}
    setVisibleOnAllWorkspaces () {}
    setOpacity () {}
    setIgnoreMouseEvents (value) { this.through = value }
    show () {}
    hide () {}
    moveTop () {}
    focus () {}
    async loadURL (url) { this.urls.push(url) }
    async loadFile (file) { this.urls.push(file) }
    static getAllWindows () { return windows.filter(w => !w.destroyed) }
  }
  class Tray extends EventEmitter { setToolTip () {} setContextMenu () {} }
  const app = new EventEmitter()
  Object.assign(app, {
    isPackaged: packaged, getPath: () => 'C:\\Users\\fixture', quit: () => { quits++ },
    disableHardwareAcceleration () {}, commandLine: { appendSwitch: name => switches.push(name) },
    whenReady: () => ({ then: callback => { ready = callback } })
  })
  const electron = { app, BrowserWindow: Window, Tray, ipcMain, Menu: { buildFromTemplate: value => value },
    globalShortcut: { register () {}, unregisterAll () {} },
    screen: { getPrimaryDisplay: () => ({ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }),
      getDisplayMatching: () => ({ workArea: { x: 0, y: 0, width: 1920, height: 1080 } }),
      getCursorScreenPoint: () => ({ x: 10, y: 20 }) },
    nativeImage: { createFromPath: () => ({ isEmpty: () => true }), createEmpty: () => ({}) }, shell: { openExternal () {} } }
  const filename = path.join(__dirname, '../overlay/main.js')
  const context = vm.createContext({ __dirname: path.dirname(filename), URL, setTimeout, clearTimeout,
    console: { log () {}, error () {} },
    process: { env: { LOCALAPPDATA: 'C:\\LocalFixture', ...env }, argv: ['--hud-only'], stdin: { setEncoding () {}, on () {} } },
    require (name) {
      if (name === 'electron') return electron
      if (name === 'node:fs') return {
        readFileSync: file => { reads.push(file); return '{}' },
        writeFileSync: (file, value) => writes.push([file, value]), mkdirSync: file => directories.push(file)
      }
      if (name === 'node:http') return { get: (_url, _options, callback) => {
        callback({ statusCode: 200, resume () {} }); return new EventEmitter()
      } }
      return require(name)
    }
  })
  vm.runInContext(fs.readFileSync(filename, 'utf8'), context)
  return { context, windows, switches, writes, reads, directories, ipcMain, ready: () => ready(), quits: () => quits }
}

test('packaged duel keeps three local panes, sandbox, and disables debug environment entry points', async () => {
  const h = harness(true, { ROCO_HUD_MODE: 'duel', ROCO_HUD_PORT: '8767', ROCO_SHOT: 'https://external.invalid', ROCO_HUD_PAGE: '@external.invalid' })
  await h.ready()
  assert.equal(h.windows.length, 3)
  assert.deepEqual(h.windows.map(w => w.urls[0]), ['my', 'enemy', 'history'].map(side => 'http://127.0.0.1:8767/hud-duel?side=' + side))
  assert.ok(!h.switches.includes('no-sandbox')); assert.ok(!h.switches.includes('disable-gpu-sandbox'))
  assert.ok(h.switches.includes('disable-gpu-compositing'))
  for (const w of h.windows) {
    assert.equal(w.options.webPreferences.sandbox, true)
    assert.equal(w.options.webPreferences.nodeIntegration, false)
    assert.equal(w.options.webPreferences.devTools, false)
  }
  await assert.rejects(h.context.captureOnce('https://external.invalid', 'ignored.png'), /unavailable/)
  assert.equal(h.windows.length, 3)
  h.ipcMain.emit('overlay:close', { sender: {} }); assert.equal(h.quits(), 0)
  for (const w of h.windows) h.ipcMain.emit('overlay:close', { sender: w.webContents })
  assert.equal(h.quits(), 3)
  h.windows[0].destroyed = true
  h.ipcMain.emit('overlay:close', { sender: h.windows[0].webContents }); assert.equal(h.quits(), 3)
})

test('HUD blocks foreign navigation, redirects, popups, webviews, and permissions', async () => {
  const h = harness(true, { ROCO_HUD_MODE: 'duel' }); await h.ready()
  for (const w of h.windows) {
    assert.equal(w.openHandler({ url: 'https://external.invalid' }).action, 'deny')
    assert.equal(w.checkPermission(), false)
    let allowed
    w.requestPermission(w.webContents, 'media', value => { allowed = value }); assert.equal(allowed, false)
    for (const name of ['will-navigate', 'will-redirect', 'will-frame-navigate']) {
      for (const url of ['https://external.invalid', 'http://127.0.0.1:8766.external.invalid/', 'http://127.0.0.1:8767/',
        'http://localhost:8766/', 'http://user@127.0.0.1:8766/', 'file:///secret', 'data:text/html,test']) {
        let prevented = false
        w.webContents.emit(name, { url, preventDefault () { prevented = true } }, name === 'will-frame-navigate' ? undefined : url)
        assert.equal(prevented, true, name + ': ' + url)
      }
      let prevented = false
      w.webContents.emit(name, { url: 'http://127.0.0.1:8766/hud-duel?side=my', preventDefault () { prevented = true } })
      assert.equal(prevented, false)
    }
    let prevented = false
    w.webContents.emit('will-attach-webview', { preventDefault () { prevented = true } })
    assert.equal(prevented, true)
  }
})

test('single HUD validates IPC senders and writes packaged state outside the application archive', async () => {
  const h = harness(true, { ROCO_HUD_PAGE: '@external.invalid' }); await h.ready()
  await new Promise(resolve => setImmediate(resolve))
  const w = h.windows[0]
  assert.equal(w.urls[0], 'http://127.0.0.1:8766/hud-pro')
  const before = { ...w.bounds }
  for (const channel of ['fold', 'through', 'reload', 'split', 'close']) h.ipcMain.emit('overlay:' + channel, { sender: {} })
  assert.deepEqual(w.bounds, before); assert.equal(h.quits(), 0); assert.equal(h.writes.length, 0)
  h.ipcMain.emit('overlay:fold', { sender: w.webContents }); assert.equal(w.bounds.height, 17)
  h.ipcMain.emit('overlay:through', { sender: w.webContents }); assert.equal(w.through, true)
  h.ipcMain.emit('overlay:split', { sender: w.webContents })
  assert.ok(h.writes.length > 0)
  assert.equal(h.writes[0][0], path.join('C:\\LocalFixture', 'RocoPVP', 'overlay-state.json'))
  assert.equal(h.directories[0], path.join('C:\\LocalFixture', 'RocoPVP'))
  h.ipcMain.emit('overlay:close', { sender: w.webContents }); assert.equal(h.quits(), 1)
})

test('development preserves state path, page override, GPU workaround and devtools', async () => {
  const h = harness(false, { ROCO_HUD_PAGE: '/hud' }); await h.ready()
  await new Promise(resolve => setImmediate(resolve))
  assert.ok(h.switches.includes('no-sandbox')); assert.ok(h.switches.includes('disable-gpu-sandbox'))
  assert.equal(h.windows[0].options.webPreferences.devTools, true)
  assert.equal(h.windows[0].urls[0], 'http://127.0.0.1:8766/hud')
  assert.equal(h.reads[0], path.join(__dirname, '../overlay/state.json'))
})

test('duel windows fit each side independently, clamp to the screen and retain width while dragging', async () => {
  const h = harness(true, { ROCO_HUD_MODE: 'duel' }); await h.ready()
  const [my, enemy, history] = h.windows
  const fit = (window, height) => h.ipcMain.emit('overlay:content-height', { sender: window.webContents }, height)
  fit(my, 260.2); fit(enemy, 500)
  assert.equal(my.bounds.height, 261); assert.equal(enemy.bounds.height, 500)
  assert.equal(my.bounds.width, 300)
  fit(my, 10000); assert.equal(my.bounds.height, 1056)
  fit(my, 180); assert.equal(my.bounds.height, 180)
  const before = { ...my.bounds }
  for (const value of [NaN, Infinity, -1, 0, 23, '300', null]) fit(my, value)
  h.ipcMain.emit('overlay:content-height', { sender: {} }, 500)
  assert.deepEqual(my.bounds, before)
  const historyHeight = history.bounds.height
  fit(history, 40); assert.equal(history.bounds.height, historyHeight)
  h.ipcMain.emit('overlay:drag', { sender: my.webContents }, 'start')
  fit(my, 400); assert.equal(my.bounds.height, 180)
  h.ipcMain.emit('overlay:drag', { sender: my.webContents }, 'end')
  assert.equal(my.bounds.height, 400)
  h.ipcMain.emit('overlay:drag', { sender: my.webContents }, 'start')
  h.ipcMain.emit('overlay:drag', { sender: my.webContents }, 'move')
  h.ipcMain.emit('overlay:drag', { sender: my.webContents }, 'end')
  assert.equal(my.bounds.width, 300); assert.equal(my.bounds.height, 400)
})

test('preload reports natural panel height after content changes and excludes the history pane', () => {
  const source = fs.readFileSync(path.join(__dirname, '../overlay/preload.js'), 'utf8')
  function preload (side) {
    const listeners = {}, frames = [], messages = [], observers = []
    const panel = { scrollHeight: 140 }, body = {}
    class Observer {
      constructor (callback) { this.callback = callback; observers.push(this) }
      observe (target) { assert.equal(target, panel) }
    }
    vm.runInNewContext(source, {
      require: () => ({ contextBridge: { exposeInMainWorld () {} }, ipcRenderer: { send: (...args) => messages.push(args) } }),
      window: { addEventListener: (name, callback) => { listeners[name] = callback } },
      document: { body, getElementById: () => panel }, location: { pathname: '/hud-duel', search: '?side=' + side },
      URLSearchParams, ResizeObserver: Observer, MutationObserver: Observer,
      requestAnimationFrame: callback => frames.push(callback),
      getComputedStyle: target => target === body ? { paddingTop: '18px', paddingBottom: '6px' } : { borderTopWidth: '1px', borderBottomWidth: '1px' }
    })
    listeners.DOMContentLoaded()
    return { frames, messages, observers, panel }
  }
  const h = preload('enemy')
  h.frames.shift()(); assert.deepEqual(h.messages, [['overlay:content-height', 166]])
  h.panel.scrollHeight = 400
  for (const observer of h.observers) observer.callback()
  assert.equal(h.frames.length, 1)
  h.frames.shift()(); assert.equal(h.messages.at(-1)[1], 426)
  h.panel.scrollHeight = 90; h.observers[0].callback(); h.frames.shift()()
  assert.equal(h.messages.at(-1)[1], 116)
  h.observers[0].callback(); h.frames.shift()(); assert.equal(h.messages.length, 3)
  assert.equal(preload('history').frames.length, 0)
})
