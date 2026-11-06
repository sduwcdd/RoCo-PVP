'use strict'
const fs = require('node:fs')
const path = require('node:path')
const http = require('node:http')
const crypto = require('node:crypto')
const { spawn } = require('node:child_process')

function readJson(file) { try { return JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '')) } catch (_) { return null } }
function electronEnv(overrides = {}) {
  const env = { ...process.env, ...overrides }
  delete env.ELECTRON_RUN_AS_NODE
  return env
}
function waitForHud(child, timeout = 15000) {
  return new Promise((resolve, reject) => {
    const sides = new Set()
    let output = ''
    const timer = setTimeout(() => finish(Error('HUD页面未能完成显示，请查看HUD日志')), timeout)
    function finish(error) {
      clearTimeout(timer); child.stdout.removeListener('data', onData); child.removeListener('exit', onExit); child.removeListener('error', onError)
      if (error) reject(error); else resolve()
    }
    function onData(chunk) {
      output = (output + chunk.toString()).slice(-8000)
      for (const match of output.matchAll(/\[duel\] ready (my|enemy|history)\b/g)) sides.add(match[1])
      if (sides.size === 3) finish()
    }
    function onExit(code) { finish(Error('HUD在显示完成前退出，exit=' + code)) }
    function onError(error) { finish(error) }
    child.stdout.on('data', onData); child.once('exit', onExit); child.once('error', onError)
  })
}
function tail(file) {
  let fd
  try {
    fd = fs.openSync(file, 'r')
    const size = fs.fstatSync(fd).size, buffer = Buffer.alloc(Math.min(size, 8000))
    fs.readSync(fd, buffer, 0, buffer.length, Math.max(0, size - buffer.length))
    return buffer.toString('utf8').split(/\r?\n/).slice(-15).join('\n').replace(/(key_(?:hex|ascii)\s*=\s*)\S+/gi, '$1[hidden]')
  } catch (_) { return '' } finally { if (fd != null) fs.closeSync(fd) }
}
function fetchJson(url) {
  return new Promise((resolve, reject) => {
    const req = http.get(url, { timeout: 2000 }, res => {
      let body = ''
      res.on('data', chunk => { body += chunk; if (body.length > 3000000) req.destroy(Error('Response too large')) })
      res.on('end', () => { try { if (res.statusCode !== 200) throw Error('HTTP ' + res.statusCode); resolve(JSON.parse(body)) } catch (e) { reject(e) } })
    })
    req.on('timeout', () => req.destroy(Error('连接超时')))
    req.on('error', reject)
  })
}
class DesktopServices {
  constructor(root) {
    this.root = root; this.port = Number(process.env.ROCO_APP_PORT || 8766)
    this.release = readJson(path.join(root, 'resources', 'release.json'))
    this.base = 'http://127.0.0.1:' + this.port
    this.logsDir = this.release ? path.join(process.env.LOCALAPPDATA, 'RocoPVP', 'artifacts', 'app') : path.join(root, 'artifacts', 'app'); fs.mkdirSync(this.logsDir, { recursive: true })
    this.python = this.release ? path.join(root, 'resources', 'backend', 'roco_backend.exe') : path.join(root, '.venv-rkpp', 'Scripts', 'python.exe')
    this.ps = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
    this.server = null; this.starting = null; this.stopping = null; this.capturePending = false; this.entries = []; this.lastError = ''
  }
  log(kind, message) {
    const value = String(message).split(/\r?\n/).filter(line => !/"GET \/api\/(status|live\/battle) HTTP\/1\.1" 200/.test(line)).join('\n').replace(/(key_(?:hex|ascii)\s*=\s*)\S+/gi, '$1[hidden]').trim().slice(-4000)
    if (!value) return
    const entry = { at: new Date().toLocaleTimeString('zh-CN'), kind, message: value }
    this.entries.push(entry); this.entries = this.entries.slice(-80)
    fs.appendFileSync(path.join(this.logsDir, 'desktop.log'), JSON.stringify(entry) + '\n')
    if (['错误', '启动失败', '异常'].includes(kind)) this.lastError = value
  }
  watch(child, kind) {
    child.stdout?.on('data', b => this.log(kind, b.toString('utf8')))
    child.stderr?.on('data', b => this.log(kind, b.toString('utf8')))
    child.on('error', e => this.log('错误', kind + ': ' + e.message))
    child.on('exit', code => this.log(code ? '异常' : '进程退出', kind + ' exit=' + code))
  }
  async ensureService() {
    if (this.stopping) await this.stopping
    if (this.starting) return this.starting
    this.starting = this._startService().finally(() => { this.starting = null })
    return this.starting
  }
  async _startService() {
    const hash = crypto.createHash('sha256')
    if (!this.release) {
      for (const name of fs.readdirSync(path.join(this.root, 'lab')).filter(name => name.endsWith('.py')).sort()) {
        hash.update(name + '\0'); hash.update(fs.readFileSync(path.join(this.root, 'lab', name)))
      }
    }
    const currentHash = this.release ? this.release.source_hash : hash.digest('hex')
    const resourceRoot = this.release ? path.join(this.root, 'resources', 'backend', '_internal') : this.root
    const matches = status => status.mode === 'research' && status.desktop_support?.source_hash === currentHash &&
      typeof status.desktop_support.workspace === 'string' && path.resolve(status.desktop_support.workspace).toLowerCase() === resourceRoot.toLowerCase()
    for (let attempt = 0; attempt < 15; attempt++) {
      let status
      try { status = await fetchJson(this.base + '/api/status') } catch (_) { break }
      if (matches(status)) { this.lastError = ''; return { ok: true, reused: !this.server } }
      if (this.server) {
        this.log('更新', '检测到工作台源码更新，自动重启APP管理的后台服务。')
        await this._stopOwnedService()
        continue
      }
      this.log('连接', '端口 ' + this.port + ' 由旧版或其他服务占用，使用下一空闲端口；原服务保持运行。')
      this.port++; this.base = 'http://127.0.0.1:' + this.port
      if (attempt === 14) throw Error('没有可用的本地工作台端口')
    }
    if (!fs.existsSync(this.python)) throw Error('项目Python环境缺失：' + this.python)
    if (this.server && this.server.exitCode === null) throw Error('服务正在启动，请稍候')
    const child = spawn(this.python, this.release ? ['server', '--port', String(this.port)] : ['-u', '-m', 'lab.server', '--port', String(this.port)], {
      cwd: this.root, windowsHide: true, env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' }, stdio: ['ignore', 'pipe', 'pipe'] })
    this.server = child; this.watch(child, '工作台')
    child.on('exit', () => { if (this.server === child) this.server = null })
    for (let i = 0; i < 40; i++) {
      await new Promise(resolve => setTimeout(resolve, 250))
      if (child.exitCode !== null) throw Error('工作台启动失败，请查看日志')
      try { const status = await fetchJson(this.base + '/api/status'); if (matches(status)) { this.lastError = ''; return { ok: true, reused: false } } } catch (_) {}
    }
    throw Error('服务启动超时，请查看日志')
  }
  stopService() {
    if (this.stopping) return this.stopping
    this.stopping = this._stopService().finally(() => { this.stopping = null })
    return this.stopping
  }
  async _stopService() {
    if (this.starting) { try { await this.starting } catch (_) {} }
    return this._stopOwnedService()
  }
  async _stopOwnedService() {
    if (!this.server) throw Error('当前服务由APP外部启动，APP不会结束外部进程')
    const child = this.server
    if (child.exitCode === null && !child.signalCode) {
      await new Promise((resolve, reject) => {
        const finish = error => {
          clearTimeout(timer); child.removeListener('exit', onExit); child.removeListener('error', onError)
          if (error) reject(error); else resolve()
        }
        const onExit = () => finish()
        const onError = error => finish(error)
        const timer = setTimeout(() => finish(Error('工作台尚未退出，请稍后重试停止服务')), 5000)
        child.once('exit', onExit); child.once('error', onError)
        try { if (!child.kill()) finish(Error('未能停止APP工作台进程，请查看日志')) } catch (error) { finish(error) }
      })
    }
    if (this.server === child) this.server = null
    this.lastError = ''
    return { ok: true }
  }
  receipt() { return readJson(path.join(this.logsDir, 'capture-owner.json')) }
  captureOwned() { return Boolean(this.receipt()?.pid) }
  capture(mode, iface = 'WLAN') {
    if (this.captureOperation) return Promise.reject(Error('正在等待管理员授权或进程启动，请稍候'))
    const operation = this._capture(mode, iface)
    this.captureOperation = operation
    return operation.finally(() => { if (this.captureOperation === operation) this.captureOperation = null })
  }
  async _capture(mode, iface) {
    if (this.capturePending) throw Error('正在等待管理员授权或进程启动，请稍候')
    if (mode === 'Stop' && !this.captureOwned()) throw Error('没有APP启动的抓包进程；外部进程只显示状态')
    if (mode === 'Start') {
      try {
        await fetchJson('http://127.0.0.1:8765/health')
        this.lastError = ''
        return { ok: true, reused: true }
      } catch (_) {}
    }
    if (typeof iface !== 'string' || !iface.trim() || iface.length > 128 || /[\r\n\0]/.test(iface)) throw Error('网卡名称无效')
    const resultFile = path.join(this.logsDir, 'capture-result.json')
    // An old result must not turn this helper's failure (or missing reply) into success.
    fs.rmSync(resultFile, { force: true })
    this.capturePending = true
    return new Promise((resolve, reject) => {
      const program = this.release ? this.python : this.ps
      const args = this.release ? ['capture-control', '--mode', mode, '--iface', iface] : ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path.join(this.root, 'scripts', 'desktop_capture.ps1'), '-Mode', mode, '-IfaceEncoded', Buffer.from(iface, 'utf8').toString('base64')]
      let child
      try {
        child = spawn(program, args, { cwd: this.root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
      } catch (error) { this.capturePending = false; reject(error); return }
      this.watch(child, '抓包控制')
      child.on('error', error => { this.capturePending = false; reject(error) })
      child.on('exit', code => {
        this.capturePending = false
        const result = readJson(resultFile)
        if (code !== 0 || result?.ok !== true) reject(Error(result?.error || '采集助手未确认成功；请查看抓包控制日志。使用其他管理员账号授权时，请在同一Windows账号下运行APP。'))
        else resolve({ ok: true })
      })
    })
  }
  async status(hudCount = 0) {
    const [service, live, relay] = await Promise.all([
      fetchJson(this.base + '/api/status').catch(e => ({ error: e.message })),
      fetchJson(this.base + '/api/live/battle?state=1').catch(e => ({ error: e.message })),
      fetchJson('http://127.0.0.1:8765/health').catch(e => ({ error: e.message }))])
    if (live.state) this.lastLiveState = live.state
    const state = live.state || this.lastLiveState || {}
    const receipt = this.receipt()
    return { server: { available: service.mode === 'research', owned: Boolean(this.server), port: this.port, error: service.error, revision: service.engine_revision },
      relay: { available: !relay.error, owned: this.captureOwned(), pending: this.capturePending, error: relay.error, result: readJson(path.join(this.logsDir, 'capture-result.json')) },
      live: { hasBattle: state.has_battle, round: state.round, finished: state.finished, capture: state.capture || {}, keyMissing: state.key_missing,
        hint: live.error ? '工作台状态请求暂缓，正在重试；不是游戏重新建连。' : state.hint || '',
        error: live.error || state.last_error || '', statusStale: Boolean(live.error), events: state.events_seen || 0,
        processingMs: state.processing_ms, backlogPending: state.backlog_pending },
      captureOutput: receipt ? [tail(receipt.stdout), tail(receipt.stderr)].filter(Boolean).join('\n') : '',
      hudCount, lastError: this.lastError, logs: this.entries.slice(-35) }
  }
}
module.exports = { DesktopServices, fetchJson, readJson, electronEnv, waitForHud }
