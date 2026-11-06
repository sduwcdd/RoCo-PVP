'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const vm = require('node:vm')
const fs = require('node:fs')
const path = require('node:path')
const { EventEmitter } = require('node:events')

function fixture ({ online = false, throwSpawn = false } = {}) {
  const root = path.resolve('capture-fixture'), logs = path.join('C:\\LocalFixture', 'RocoPVP', 'artifacts', 'app')
  const resultFile = path.join(logs, 'capture-result.json')
  const files = new Map([[path.join(root, 'resources', 'release.json'), '{"source_hash":"fixture"}'], [resultFile, '{"ok":true}']])
  const spawns = []
  const child = new EventEmitter()
  child.stdout = new EventEmitter(); child.stderr = new EventEmitter()
  const context = { module: { exports: {} }, Buffer, setTimeout, clearTimeout,
    process: { env: { LOCALAPPDATA: 'C:\\LocalFixture' } },
    require (name) {
      if (name === 'node:fs') return {
        readFileSync: file => { if (!files.has(file)) throw Error('missing'); return files.get(file) },
        mkdirSync () {}, appendFileSync () {}, rmSync: file => files.delete(file)
      }
      if (name === 'node:child_process') return { spawn (...args) {
        spawns.push(args); if (throwSpawn) throw Error('spawn failed'); return child
      } }
      if (name === 'node:http') return { get (_url, _options, callback) {
        const request = new EventEmitter()
        queueMicrotask(() => {
          if (!online) { request.emit('error', Error('offline')); return }
          const response = new EventEmitter(); response.statusCode = 200
          callback(response); response.emit('data', '{"status":"ok"}'); response.emit('end')
        })
        return request
      } }
      return require(name)
    }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../overlay/desktop_services.js'), 'utf8'), context)
  return { service: new context.module.exports.DesktopServices(root), child, spawns, files, resultFile, root }
}

test('healthy relay is reused without starting a helper or touching previous capture records', async () => {
  const f = fixture({ online: true })
  const result = await f.service.capture('Start')
  assert.equal(result.ok, true); assert.equal(result.reused, true)
  assert.equal(f.spawns.length, 0); assert.equal(f.service.capturePending, false)
  assert.equal(f.files.get(f.resultFile), '{"ok":true}')
})

test('fresh packaged start invokes capture-control and requires a fresh successful reply', async () => {
  for (const current of [null, { ok: false, error: '管理员授权被取消' }, { ok: true, state: 'starting' }]) {
    const f = fixture()
    const pending = f.service.capture('Start', 'WLAN')
    const failure = current?.ok ? null : assert.rejects(pending, current ? /管理员授权被取消/ : /未确认成功/)
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(f.spawns.length, 1)
    assert.equal(f.spawns[0][0], path.join(f.root, 'resources', 'backend', 'roco_backend.exe'))
    assert.deepEqual(Array.from(f.spawns[0][1]), ['capture-control', '--mode', 'Start', '--iface', 'WLAN'])
    assert.equal(f.spawns[0][2].windowsHide, true)
    assert.equal(f.files.has(f.resultFile), false, 'the previous result is discarded before invoking the helper')
    if (current) f.files.set(f.resultFile, JSON.stringify(current))
    f.child.emit('exit', current?.ok ? 0 : current ? 1 : 0)
    if (failure) await failure
    else assert.equal((await pending).ok, true)
    assert.equal(f.service.capturePending, false)
  }
})

test('synchronous launch failure clears pending state so the next click can retry', async () => {
  const f = fixture({ throwSpawn: true })
  await assert.rejects(f.service.capture('Start'), /spawn failed/)
  assert.equal(f.service.capturePending, false)
})
