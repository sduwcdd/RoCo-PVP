'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const vm = require('node:vm')
const { DesktopUpdater } = require('../overlay/desktop_updater')

function fixture (t, installed = true) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'roco-updater-'))
  t.after(() => {
    assert.equal(path.dirname(dir), os.tmpdir())
    assert.ok(path.basename(dir).startsWith('roco-updater-'))
    fs.rmSync(dir, { recursive: true, force: true })
  })
  const events = [], logs = [], updater = new EventEmitter()
  updater.setFeedURL = feed => { updater.feed = feed }
  updater.checkForUpdates = async () => { updater.emit('checking-for-update'); updater.emit('update-available', { version: '1.2.0' }) }
  updater.downloadUpdate = async () => { updater.emit('download-progress', { percent: 43 }); updater.emit('update-downloaded', { version: '1.2.0' }) }
  updater.quitAndInstall = (...args) => events.push(['install', ...args])
  const app = { isPackaged: installed, getPath: () => dir, getVersion: () => '1.1.0' }
  const create = beforeInstall => new DesktopUpdater({ app, getUpdater: () => updater,
    beforeInstall: beforeInstall || (async () => { events.push(['cleanup']) }), log: (...args) => logs.push(args) })
  return { create, updater, dir, events, logs }
}

test('public update lifecycle is anonymous, validates before install, then cleans up and restarts', async t => {
  const f = fixture(t), c = f.create()
  await c.ready
  await assert.rejects(c.install(), /校验完成/)
  await c.check()
  assert.equal(f.updater.feed.repo, 'RoCo-PVP'); assert.equal(f.updater.feed.private, false)
  assert.equal(Object.hasOwn(f.updater.feed, 'token'), false)
  assert.equal(f.updater.autoInstallOnAppQuit, false)
  await c.download(); assert.equal(c.snapshot().canInstall, true)
  await c.install(); assert.deepEqual(f.events, [['cleanup'], ['install', true, true]])
})

test('startup checks without downloading and one action downloads, cleans up and installs', async t => {
  const f = fixture(t), c = f.create()
  await c.start()
  assert.equal(c.snapshot().stage, 'available')
  assert.deepEqual(f.events, [])
  await c.update()
  assert.deepEqual(f.events, [['cleanup'], ['install', true, true]])
})

test('one-click check handles the current version and refuses an unverified download', async t => {
  const f = fixture(t), c = f.create()
  f.updater.checkForUpdates = async () => f.updater.emit('update-not-available')
  await c.update()
  assert.equal(c.snapshot().stage, 'current')
  assert.deepEqual(f.events, [])
  f.updater.checkForUpdates = async () => f.updater.emit('update-available', { version: '1.2.0' })
  await c.check()
  f.updater.downloadUpdate = async () => {}
  await assert.rejects(c.update(), /尚未完成校验/)
  assert.deepEqual(f.events, [])
})

test('startup network failure stays visible and can be retried', async t => {
  const f = fixture(t), c = f.create()
  f.updater.checkForUpdates = async () => { throw Error('network timeout') }
  await c.start()
  assert.equal(c.snapshot().stage, 'error')
  assert.match(c.snapshot().message, /timeout/)
  f.updater.checkForUpdates = async () => f.updater.emit('update-available', { version: '1.2.0' })
  await c.update()
  assert.deepEqual(f.events, [['cleanup'], ['install', true, true]])
})

test('download excludes duplicate operations and a capture-stop failure preserves a verified retry', async t => {
  const f = fixture(t); let unblock
  const c = f.create(async () => { throw Error('采集未退出') }); await c.ready; await c.check()
  f.updater.downloadUpdate = () => new Promise(resolve => { unblock = () => { f.updater.emit('update-downloaded', { version: '1.2.0' }); resolve() } })
  const pending = c.download(); await new Promise(resolve => setImmediate(resolve))
  await assert.rejects(c.check(), /正在进行/)
  assert.equal(c.snapshot().busy, true)
  unblock(); await pending
  await assert.rejects(c.install(), /采集未退出/)
  assert.equal(c.snapshot().canInstall, true); assert.deepEqual(f.events, [])
})

test('development mode never overwrites source and retired preview credentials are removed', async t => {
  const f = fixture(t, false)
  const old = path.join(f.dir, 'update-token.bin'); fs.writeFileSync(old, 'old-preview-ciphertext')
  const c = f.create(); await c.ready
  assert.equal(fs.existsSync(old), false)
  await assert.rejects(c.check(), /开发版/)
  assert.equal(Object.hasOwn(c.snapshot(), 'configured'), false)
  assert.deepEqual(f.events, [])
})

test('public settings render using only elements that actually exist after credential controls are removed', async () => {
  const folder = path.join(__dirname, '../overlay')
  const html = fs.readFileSync(path.join(folder, 'desktop.html'), 'utf8')
  const elements = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], {
    textContent: '', className: '', value: '', addEventListener () {}
  }]))
  const state = { version: '1.1.1', installed: true, stage: 'idle', busy: false, canInstall: false,
    progress: null, availableVersion: null, message: '点击检查更新' }
  const service = { live: { capture: {} }, server: {}, relay: {}, logs: [], hudCount: 0 }
  vm.runInNewContext(fs.readFileSync(path.join(folder, 'desktop_renderer.js'), 'utf8'), {
    document: { getElementById: id => elements.get(id) || null }, setInterval () {},
    window: { rocoApp: { invoke: async action => action === 'update-status' ? state : service } }
  })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(elements.get('update-status').textContent, state.message)
  assert.equal(elements.get('app-version').textContent, '当前版本 1.1.1')
  assert.equal(elements.has('update-token'), false)
  assert.equal(elements.get('update-check').disabled, false)
})
