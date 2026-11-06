'use strict'
const fs = require('node:fs')
const path = require('node:path')
const config = require('./update_config.json')

class DesktopUpdater {
  constructor ({ app, beforeInstall, log = () => {}, getUpdater = () => require('electron-updater').autoUpdater }) {
    this.app = app; this.beforeInstall = beforeInstall; this.log = log; this.operation = null
    // Remove credentials left by the retired private-update preview, without reading them.
    fs.rmSync(path.join(app.getPath('userData'), 'update-token.bin'), { force: true })
    this.state = { version: app.isPackaged ? app.getVersion() : config.version, installed: Boolean(app.isPackaged),
      stage: 'idle', availableVersion: null, progress: null, canInstall: false,
      message: app.isPackaged ? '点击检查更新' : '开发版直接加载本地源码；在线安装更新请使用安装版。' }
    if (app.isPackaged) {
      this.updater = getUpdater()
      Object.assign(this.updater, { autoDownload: false, autoInstallOnAppQuit: false, allowDowngrade: false,
        allowPrerelease: false, disableDifferentialDownload: true, autoRunAppAfterInstall: true, logger: null })
      this.updater.on('checking-for-update', () => this.set('checking', '正在检查新版本…'))
      this.updater.on('update-available', info => {
        this.info = info; this.state.availableVersion = info.version
        this.set('available', '发现新版本 ' + info.version + '，可下载更新')
      })
      this.updater.on('update-not-available', () => { this.info = null; this.state.availableVersion = null; this.set('current', '当前已是最新版本') })
      this.updater.on('download-progress', data => {
        this.state.progress = Math.max(0, Math.min(100, Number(data.percent) || 0))
        this.set('downloading', '正在下载 ' + this.state.progress.toFixed(0) + '%')
      })
      this.updater.on('update-downloaded', info => {
        this.info = info; this.state.availableVersion = info.version; this.state.progress = 100; this.state.canInstall = true
        this.set('ready', '下载和校验完成，可以安装并重启')
      })
      this.updater.on('error', error => this.fail(error))
    }
    this.ready = Promise.resolve()
  }
  set (stage, message) { this.state.stage = stage; this.state.message = message }
  snapshot () { return { ...this.state, busy: Boolean(this.operation) } }
  safeError (error) {
    let message = String(error?.message || error)
    message = message.replace(/(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+/g, '[hidden]')
      .replace(/(authorization["'\s:]+)(?:bearer|token)\s+[^\s",}]+/gi, '$1[hidden]')
    if (/403|404|not found|LATEST_VERSION_NOT_FOUND/i.test(message)) return '暂时无法读取公开更新版本，请检查网络或稍后重试'
    return '更新失败：' + message.slice(0, 350)
  }
  fail (error) { const message = this.safeError(error); this.set('error', message); this.log('更新', message) }
  async exclusive (task) {
    await this.ready
    if (this.operation) throw Error('更新操作正在进行，请稍候')
    this.operation = Promise.resolve().then(task)
    try { return await this.operation } catch (error) { this.fail(error); throw Error(this.state.message) }
    finally { this.operation = null }
  }
  configureFeed () {
    if (!this.updater) throw Error('开发版不覆盖本地源码，请使用安装版进行在线更新')
    this.updater.setFeedURL({ provider: 'github', owner: config.owner, repo: config.repo, private: false })
  }
  async check () {
    return this.exclusive(async () => {
      this.configureFeed(); this.info = null; this.state.availableVersion = null; this.state.progress = null; this.state.canInstall = false
      await this.updater.checkForUpdates(); return this.snapshot()
    })
  }
  async download () {
    return this.exclusive(async () => {
      this.configureFeed()
      if (!this.info || !['available', 'error'].includes(this.state.stage)) throw Error('请先检查并选择可用的新版本')
      this.set('downloading', '正在开始下载…'); this.state.progress = 0
      await this.updater.downloadUpdate(); return this.snapshot()
    })
  }
  async install () {
    return this.exclusive(async () => {
      if (!this.updater || !this.state.canInstall) throw Error('更新尚未下载和校验完成')
      this.set('installing', '正在关闭本APP的抓包及窗口，安装后会重新启动…')
      try { await this.beforeInstall() }
      catch (error) { this.set('ready', '尚未关闭本APP的采集或后台，更新未安装；请重试'); throw error }
      this.updater.quitAndInstall(true, true)
      return this.snapshot()
    })
  }
}
module.exports = { DesktopUpdater }
