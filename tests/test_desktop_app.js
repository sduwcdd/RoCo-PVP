'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const { DesktopServices, fetchJson, electronEnv, waitForHud, tail } = require('../overlay/desktop_services')
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

test('child logs retain split UTF-8 characters independently on stdout and stderr', () => {
  const child = new EventEmitter()
  child.stdout = new EventEmitter(); child.stderr = new EventEmitter()
  const entries = [], service = Object.create(DesktopServices.prototype)
  service.log = (kind, message) => { if (message) entries.push([kind, message]) }
  service.watch(child, '工作台')
  const stdout = Buffer.from('工作台：http://127.0.0.1:8766，中文正常')
  const stderr = Buffer.from('错误日志也正常')
  child.stdout.emit('data', stdout.subarray(0, 2))
  child.stderr.emit('data', stderr.subarray(0, 1))
  child.stdout.emit('data', stdout.subarray(2))
  child.stderr.emit('data', stderr.subarray(1))
  child.stdout.emit('end'); child.stderr.emit('end')
  assert.deepEqual(entries, [['工作台', stdout.toString('utf8')], ['工作台', stderr.toString('utf8')]])
})

test('log tails preserve UTF-8 boundaries and defer a character still being written', () => {
  const os = require('node:os')
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'roco-log-encoding-'))
  const file = path.join(folder, 'capture.log')
  try {
    fs.writeFileSync(file, '中'.repeat(3000) + '\n最后一行\n')
    const output = tail(file)
    assert.doesNotMatch(output, /\uFFFD/)
    assert.match(output, /最后一行/)
    fs.writeFileSync(file, Buffer.concat([Buffer.from('正常日志'), Buffer.from([0xe4, 0xb8])]))
    assert.equal(tail(file), '正常日志')
    fs.appendFileSync(file, Buffer.from([0xad]))
    assert.equal(tail(file), '正常日志中')
  } finally {
    assert.equal(path.dirname(folder), os.tmpdir())
    fs.rmSync(folder, { recursive: true })
  }
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

const environmentReport = {
  schema: 'npcap-environment-1', collected_at: '2026-11-07T06:22:05Z',
  analysis: { npcap_state: 'running', anti_npcap_detection: 'unknown', game_processes: [{ Id: 1 }],
    anti_cheat_name_candidates: [{ section: 'drivers', Name: '<ACE-CORE>', State: 'Running' }],
    npcap_related_events: [{ Time: '2026-11-07', ProviderName: 'SCM', Id: 7045, Message: 'Npcap installed', failure_or_block_wording: false }],
    query_errors: [], limits: ['每个通道最新300条'] },
  observations: { processes: { status: 'ok', items: [] } }
}

function environmentService(release) {
  const calls = [], callbacks = [], exported = { exports: {} }
  let report = structuredClone(environmentReport)
  const filename = path.join(__dirname, '../overlay/desktop_services.js')
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    module: exported, process: { env: { LOCALAPPDATA: 'C:\\EnvironmentFixture' } },
    require(name) {
      if (name === 'node:child_process') return { execFile: (...args) => { calls.push(args); callbacks.push(args[3]) } }
      if (name === 'node:fs') return {
        mkdirSync() {}, existsSync: () => true, appendFileSync() {},
        readFileSync: file => JSON.stringify(file.endsWith('release.json') ? release ? { version: '1.1.6' } : null : report)
      }
      return require(name)
    }
  })
  return { service: new exported.exports.DesktopServices('C:\\EnvironmentApp'), calls, callbacks, setReport: value => { report = value } }
}

test('environment checking shares concurrent requests and supports source and packaged backends', async () => {
  for (const release of [false, true]) {
    const h = environmentService(release)
    const request = h.service.checkEnvironment()
    assert.equal(h.service.checkEnvironment(), request)
    assert.equal(h.calls.length, 1)
    assert.equal(h.calls[0][1][0], release ? 'environment-check' : path.join('C:\\EnvironmentApp', 'scripts/check_npcap_environment.py'))
    assert.equal(h.calls[0][2].windowsHide, true)
    h.callbacks[0](null)
    assert.equal((await request).report.analysis.anti_npcap_detection, 'unknown')
    assert.ok(h.service.environmentReportPath.endsWith('.json'))
    assert.equal(h.service.environmentCheckOperation, null)
    const partial = structuredClone(environmentReport)
    partial.analysis.query_errors.push({ section: 'System', error: 'Access denied' })
    h.setReport(partial)
    const retry = h.service.checkEnvironment()
    h.callbacks[1](Object.assign(Error('partial'), { code: 2 }))
    assert.equal((await retry).report.analysis.query_errors.length, 1)
    const failure = h.service.checkEnvironment()
    h.callbacks[2](Object.assign(Error('timeout'), { killed: true }))
    await assert.rejects(failure, /超时/)
    assert.equal(h.service.environmentReportPath, null)
    assert.equal(h.service.environmentCheckOperation, null)
  }
})

test('environment button renders unknown capability, partial query errors and retry failures', async () => {
  const nodes = new Map(), calls = []
  const get = id => { if (!nodes.has(id)) nodes.set(id, { className: '', addEventListener(_event, callback) { this.click = callback } }); return nodes.get(id) }
  let finish, fail = false
  const state = { server: {}, relay: {}, live: { capture: {} }, logs: [] }
  const context = { document: { getElementById: get }, setInterval() {}, window: { rocoApp: { invoke(action) {
    calls.push(action)
    if (action === 'status') return Promise.resolve(state)
    if (action === 'environment-check') return fail ? Promise.resolve({ error: '后端不可用' }) : new Promise(resolve => { finish = resolve })
    return Promise.resolve({})
  } } } }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../overlay/desktop_renderer.js'), 'utf8'), context)
  const request = get('environment-check').click()
  assert.equal(get('environment-check').disabled, true)
  assert.equal(get('environment-result').hidden, true)
  const report = structuredClone(environmentReport)
  report.analysis.query_errors.push({ section: 'System', error: 'Access denied' })
  finish({ ok: true, report }); await request
  assert.match(get('environment-status').textContent, /部分查询未完成.*无法确认/)
  assert.match(get('environment-summary').textContent, /驱动运行中.*游戏 运行中/)
  assert.match(get('environment-details').textContent, /<ACE-CORE>.*Running/)
  assert.match(get('environment-details').textContent, /Access denied/)
  assert.equal(get('environment-details').innerHTML, undefined)
  assert.equal(get('environment-details-container').open, true)
  assert.equal(get('environment-report').disabled, false)
  await get('environment-report').click()
  assert.ok(calls.includes('environment-report'))
  fail = true; await get('environment-check').click()
  assert.match(get('environment-status').textContent, /检查未完成.*后端不可用/)
  assert.equal(get('environment-check').disabled, false)
  assert.equal(get('environment-report').disabled, true)
  assert.equal(get('environment-result').hidden, true)
})
