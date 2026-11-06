'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const { DesktopServices, fetchJson, electronEnv, waitForHud } = require('../overlay/desktop_services')
const { EventEmitter } = require('node:events')

test('tray exit awaits pending capture, preserves APP on denied stop, and waits for owned cleanup', async () => {
  const windows = [], trays = [], stopped = [], started = [], services = [], errors = [], captureCalls = []
  let denyStop = true, finishStop, invoke
  const hudChild = new EventEmitter()
  hudChild.stdout = new EventEmitter(); hudChild.exitCode = null
  hudChild.kill = () => { hudChild.killed = true; return true }
  class Window extends EventEmitter {
    constructor() { super(); windows.push(this); this.webContents = new EventEmitter(); this.webContents.setWindowOpenHandler = () => {}; this.hidden = false; this.destroyed = false }
    setMenuBarVisibility() {}
    async loadFile() {}
    isDestroyed() { return this.destroyed }
    hide() { this.hidden = true }
    restore() {}
    show() { this.hidden = false }
    focus() {}
    close() { const e = {preventDefault(){this.prevented = true}}; this.emit('close',e); if (!e.prevented) this.destroyed = true }
  }
  class Tray extends EventEmitter {
    constructor(icon) { super(); this.icon = icon; trays.push(this) }
    setToolTip(value) { this.tooltip = value }
    setContextMenu(value) { this.menu = value }
    destroy() { this.destroyed = true }
  }
  const app = new EventEmitter()
  Object.assign(app, {setName(){},setPath(){},getPath:()=>__dirname,disableHardwareAcceleration(){},
    commandLine:{appendSwitch(){}},requestSingleInstanceLock:()=>true,whenReady:()=>Promise.resolve(),
    quit() { const event = {preventDefault(){this.prevented = true}}; app.emit('before-quit',event); if (!event.prevented) windows[0].close() }})
  class Services {
    constructor() { services.push(this); this.ownedCapture = true }
    async ensureService() { started.push(true); this.server = {} }
    captureOwned() { return this.ownedCapture }
    async capture(mode) {
      captureCalls.push(mode)
      if (denyStop) throw Error('管理员授权被取消')
      await new Promise(resolve => { finishStop = resolve })
      this.ownedCapture = false
    }
    async stopService() { stopped.push(true); this.server = null }
    watch() {}
    log() {}
  }
  const electron = {app,BrowserWindow:Window,Tray,Menu:{buildFromTemplate:x=>x},ipcMain:{handle(_name,fn){invoke=fn}},shell:{},
    dialog:{showErrorBox(...args){errors.push(args)}}}
  const file = path.join(__dirname,'../overlay/desktop.js')
  vm.runInNewContext(fs.readFileSync(file,'utf8'), {__dirname:path.dirname(file),process:{argv:[]},
    require(name) { if(name==='electron')return electron; if(name==='node:child_process')return {spawn(){setImmediate(()=>hudChild.stdout.emit('data',Buffer.from('[duel] ready my\n[duel] ready enemy\n[duel] ready history\n')));return hudChild}}; if(name==='./desktop_services')return {DesktopServices:Services,electronEnv,waitForHud}; if(name==='./desktop_updater')return {DesktopUpdater:class {}}; return require(name) },setTimeout,clearTimeout})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(started.length,1); assert.equal(windows.length,1)
  assert.match(trays[0].icon,/dimo\.ico$/)
  windows[0].close()
  assert.equal(windows[0].hidden,true); assert.equal(windows[0].destroyed,false); assert.equal(stopped.length,0)
  trays[0].emit('double-click'); assert.equal(windows[0].hidden,false)
  windows[0].close(); app.emit('second-instance'); assert.equal(windows[0].hidden,false)
  await invoke({sender:windows[0].webContents},'hud-open')
  let finishStart
  services[0].captureOperation = new Promise(resolve => { finishStart = resolve })
  trays[0].menu.find(item=>item.label==='退出').click()
  await new Promise(resolve=>setImmediate(resolve))
  assert.deepEqual(captureCalls, []); assert.equal(windows[0].destroyed,false)
  services[0].captureOperation = null; finishStart()
  await new Promise(resolve=>setImmediate(resolve))
  assert.deepEqual(captureCalls, ['Stop']); assert.equal(errors.length,1)
  assert.match(errors[0].join(' '),/管理员授权被取消/)
  assert.equal(windows[0].destroyed,false); assert.equal(trays[0].destroyed,undefined)
  assert.equal(stopped.length,0)
  denyStop = false
  trays[0].menu.find(item=>item.label==='退出').click()
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(windows[0].destroyed,false); assert.equal(stopped.length,0)
  finishStop()
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(hudChild.killed,true); assert.equal(windows[0].destroyed,false); assert.equal(stopped.length,0)
  hudChild.exitCode=0; hudChild.emit('exit',0)
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(stopped.length,1); assert.equal(windows[0].destroyed,true); assert.equal(trays[0].destroyed,true)
  app.quit(); assert.equal(stopped.length,1)
})

test('capture ownership covers the health-check phase and rejects concurrent control', async () => {
  const service = Object.create(DesktopServices.prototype)
  let finish
  service._capture = () => new Promise(resolve => { finish = resolve })
  const starting = service.capture('Start')
  assert.ok(service.captureOperation)
  await assert.rejects(service.capture('Stop'),/管理员授权或进程启动/)
  finish({ok:true}); await starting
  assert.equal(service.captureOperation,null)
})

test('HUD success requires both sides and top history, and detects early exit', async () => {
  const child = new EventEmitter(); child.stdout = new EventEmitter()
  let ready = false
  const waiting = waitForHud(child, 1000).then(() => { ready = true })
  child.stdout.emit('data', Buffer.from('[duel] ready my\n'))
  await new Promise(resolve => setImmediate(resolve)); assert.equal(ready, false)
  child.stdout.emit('data', Buffer.from('[duel] rea'))
  child.stdout.emit('data', Buffer.from('dy enemy\n'))
  await new Promise(resolve => setImmediate(resolve)); assert.equal(ready, false)
  child.stdout.emit('data', Buffer.from('[duel] ready history\n')); await waiting; assert.equal(ready, true)
  const failed = new EventEmitter(); failed.stdout = new EventEmitter()
  const rejection = assert.rejects(waitForHud(failed, 1000), /显示完成前退出/)
  failed.emit('exit', 1); await rejection
})

test('Electron children remove the RUN_AS_NODE variable rather than setting an empty value', () => {
  const env = electronEnv({ ELECTRON_RUN_AS_NODE: '', ROCO_HUD_PORT: '8767' })
  assert.equal(Object.hasOwn(env, 'ELECTRON_RUN_AS_NODE'), false)
  assert.equal(env.ROCO_HUD_PORT, '8767')
})

test('HTTP diagnostics distinguish a healthy JSON endpoint from an unavailable port', async () => {
  const server = http.createServer((req, res) => { res.setHeader('Content-Type', 'application/json'); res.end('{"mode":"research"}') })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = 'http://127.0.0.1:' + server.address().port
  try { assert.equal((await fetchJson(address)).mode, 'research') } finally { await new Promise(resolve => server.close(resolve)) }
  await assert.rejects(fetchJson(address))
})

test('stop waits for the owned process to exit and reconnect waits for stop', async () => {
  const service = Object.create(DesktopServices.prototype)
  service.server = null
  await assert.rejects(service.stopService(), /外部启动/)
  let stopped = 0
  const child = new EventEmitter(); child.exitCode = null
  child.kill = () => { stopped++; return true }
  service.server = child; service.lastError = '旧错误'
  const stopping = service.stopService()
  let started = false
  service._startService = async () => { assert.equal(service.server, null); started = true; return { ok: true } }
  const starting = service.ensureService()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(started, false)
  assert.equal(service.server, child)
  child.exitCode = 0; child.emit('exit', 0)
  assert.equal((await stopping).ok, true)
  await starting
  assert.equal(stopped, 1)
  assert.equal(service.server, null)
  assert.equal(service.lastError, '')
})

test('a failed stop preserves ownership and reports failure', async () => {
  const service = Object.create(DesktopServices.prototype)
  const child = new EventEmitter(); child.exitCode = null; child.kill = () => false
  service.server = child
  await assert.rejects(service.stopService(), /未能停止/)
  assert.equal(service.server, child)
})

test('connecting clears old errors and automatically restarts an owned stale service', async t => {
  const root = fs.mkdtempSync(path.join(require('node:os').tmpdir(), 'roco-desktop-test-'))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  fs.mkdirSync(path.join(root, 'lab')); fs.writeFileSync(path.join(root, 'lab', 'server.py'), '# fixture')
  const hash = require('node:crypto').createHash('sha256').update('server.py\0').update('# fixture').digest('hex')
  let sourceHash = hash
  const server = http.createServer((req, res) => { res.end(JSON.stringify({ mode: 'research', desktop_support: { source_hash: sourceHash, workspace: root } })) })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  t.after(() => new Promise(resolve => server.close(resolve)))
  const service = new DesktopServices(root); service.base = 'http://127.0.0.1:' + server.address().port
  service.lastError = '服务源码已更新，请先停止APP自己的服务再重新连接'
  assert.equal((await service.ensureService()).ok, true)
  assert.equal(service.lastError, '')
  service.server = {}; sourceHash = 'old-version'
  let restarts = 0
  service.log = () => {}
  service._stopOwnedService = async () => { restarts++; service.server = null; sourceHash = hash }
  assert.equal((await service.ensureService()).ok, true)
  assert.equal(restarts, 1)
  assert.equal(service.lastError, '')
})

test('desktop renderer shows offline, key-missing, and connected states and invokes explicit actions', async () => {
  const nodes = new Map(), calls = []
  const get = id => { if (!nodes.has(id)) nodes.set(id, { textContent: '', value: 'WLAN', addEventListener(event, fn) { this.click = fn } }); return nodes.get(id) }
  let state = { server: { available: true, owned: false, port: 8766 }, relay: { available: false, owned: false },
    live: { capture: {}, hasBattle: false, events: 0 }, hudCount: 0, logs: [] }
  const context = { document: { getElementById: get }, setInterval() {}, window: { rocoApp: { async invoke(action, value) { calls.push([action, value]); return action === 'status' ? state : { ok: true } } } } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../overlay/desktop_renderer.js'), 'utf8'), context)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(get('capture-state').textContent, '中继未连接')
  assert.equal(get('stop-service').disabled, true)
  state = { ...state, relay: { available: true }, live: { capture: { target_packets: 12, key_hits: 0 }, keyMissing: true, hint: '请重新登录游戏' } }
  await context.refresh()
  assert.equal(get('game-state').textContent, '等待会话密钥')
  assert.equal(get('capture-start').disabled, true)
  assert.equal(get('capture-start').textContent, '已复用现有抓包')
  assert.match(get('capture-detail').textContent, /无需再次管理员授权/)
  assert.match(get('capture-start').title, /无需再次启动/)
  assert.match(get('game-detail').textContent, /重新登录/)
  state.live.capture.key_hits = 1; state.live.keyMissing = false; state.live.hasBattle = true; state.live.round = 3
  await context.refresh()
  assert.equal(get('game-state').textContent, '对局同步中')
  state.live.statusStale=true; state.live.hint='工作台状态请求暂缓，正在重试；不是游戏重新建连。'
  await context.refresh();assert.equal(get('game-state').textContent,'工作台响应暂缓');assert.equal(get('keys').textContent,'1')
  state.live.statusStale=false;state.live.hint=''
  await get('workbench').click()
  assert.ok(calls.some(row => row[0] === 'workbench'))
  state.lastError = '服务源码已更新，请先停止APP自己的服务再重新连接'
  await context.refresh(); assert.equal(get('notice').className, 'bad')
  state.lastError = ''
  await context.refresh(); assert.equal(get('notice').textContent, '')
  assert.equal(get('notice').className, 'good')
})
