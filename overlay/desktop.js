'use strict'
// Keep the existing overlay as a child entry; the desktop console owns only its own children.
if (process.argv.includes('--hud-only')) {
  require('./main.js')
} else {
  const { app, BrowserWindow, Tray, Menu, ipcMain, shell, dialog } = require('electron')
  const { spawn } = require('node:child_process')
  const path = require('node:path')
  const fs = require('node:fs')
  const { DesktopServices, electronEnv, waitForHud } = require('./desktop_services')
  const root = app.isPackaged ? path.dirname(process.execPath) : path.resolve(__dirname, '..')
  const icon = app.isPackaged ? path.join(__dirname, 'dimo.png') : path.join(root, 'web/assets/roco/pet-avatars/3004.png')
  let consoleWindow
  let tray
  let quitting = false
  let quitRequest = null
  let stoppingResources = null
  let updates
  function showConsole () {
    if (consoleWindow && !consoleWindow.isDestroyed()) {
      consoleWindow.restore(); consoleWindow.show(); consoleWindow.focus()
    }
  }
  const huds = new Set()
  const controller = new DesktopServices(root)
  app.setName('洛克PVP')
  app.setPath('userData', path.join(app.getPath('appData'), app.isPackaged ? 'RocoPVPDesktopRelease' : 'RocoPVPDesktop'))
  app.disableHardwareAcceleration()
  app.commandLine.appendSwitch('disable-gpu')
  app.commandLine.appendSwitch('in-process-gpu')
  if (!app.requestSingleInstanceLock()) {
    app.quit()
  } else {
    app.on('second-instance', showConsole)
    app.whenReady().then(async () => {
      const { DesktopUpdater } = require('./desktop_updater')
      updates = new DesktopUpdater({ app, log: (kind, message) => controller.log(kind, message),
        beforeInstall: stopOwnedResources })
      consoleWindow = new BrowserWindow({ width: 1120, height: 790, minWidth: 840, minHeight: 640,
        show: !process.argv.includes('--verify-desktop'),
        title: '洛克PVP · 连接控制台', icon, backgroundColor: '#f3f0e5',
        webPreferences: { preload: path.join(__dirname, 'desktop_preload.js'), nodeIntegration: false, contextIsolation: true, sandbox: true, devTools: !app.isPackaged } })
      consoleWindow.setMenuBarVisibility(false)
      tray = new Tray(fs.existsSync(path.join(__dirname, 'dimo.ico')) ? path.join(__dirname, 'dimo.ico') : icon)
      tray.setToolTip('洛克PVP · 双击打开，右键退出')
      tray.setContextMenu(Menu.buildFromTemplate([
        { label: '打开洛克PVP', click: showConsole },
        { type: 'separator' },
        { label: '退出', click: () => app.quit() }
      ]))
      tray.on('double-click', showConsole)
      consoleWindow.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
      consoleWindow.webContents.on('will-navigate', e => e.preventDefault())
      ipcMain.handle('desktop:invoke', async (event, action, payload) => {
        if (event.sender !== consoleWindow.webContents) throw Error('Unauthorized window')
        try {
          if ((quitRequest || stoppingResources) && action !== 'status') throw Error('正在停止APP服务，请稍候')
          if (action !== 'status') controller.lastError = ''
          if (action === 'status') return await controller.status([...huds].filter(child => child.hudReady).length)
          if (action === 'start-service') return await controller.ensureService()
          if (action === 'stop-service') { closeHud(); return controller.stopService() }
          if (action === 'capture-start') return await controller.capture('Start', payload)
          if (action === 'capture-stop') return await controller.capture('Stop')
          if (action === 'environment-check') return await controller.checkEnvironment()
          if (action === 'environment-report') {
            if (!controller.environmentReportPath) throw Error('请先完成环境检查')
            const error = await shell.openPath(controller.environmentReportPath)
            if (error) throw Error(error)
            return { ok: true }
          }
          if (action === 'hud-open') {
            await controller.ensureService()
            if (!huds.size) {
              const hudArgs = app.isPackaged ? ['--hud-only', '--disable-gpu', '--in-process-gpu'] : [__dirname, '--hud-only', '--no-sandbox', '--disable-gpu', '--disable-gpu-sandbox', '--in-process-gpu']
              const child = spawn(process.execPath, hudArgs, {
                cwd: root, windowsHide: true, env: electronEnv({ ROCO_HUD_MODE: 'duel', ROCO_HUD_PORT: String(controller.port) }), stdio: ['pipe', 'pipe', 'pipe'] })
              huds.add(child)
              controller.watch(child, 'HUD')
              child.on('exit', () => huds.delete(child))
              child.on('error', () => huds.delete(child))
              try { await waitForHud(child); child.hudReady = true } catch (error) { child.kill(); huds.delete(child); throw error }
            } else {
              for (const child of huds) if (child.hudReady && !child.stdin.destroyed) child.stdin.write('show\n')
            }
            return { ok: true }
          }
          if (action === 'hud-close') { closeHud(); return { ok: true } }
          if (action === 'workbench') {
            await controller.ensureService()
            const workbench = new BrowserWindow({ width: 1450, height: 950, title: '洛克PVP · 对战工作台', icon,
              show: !process.argv.includes('--verify-desktop'),
              webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, devTools: !app.isPackaged } })
            workbench.setMenuBarVisibility(false)
            workbench.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
            workbench.webContents.on('will-navigate', (event, url) => { if (!url.startsWith(controller.base + '/')) event.preventDefault() })
            await workbench.loadURL(controller.base + '/battle')
            return { ok: true }
          }
          if (action === 'browser') { await controller.ensureService(); await shell.openExternal(controller.base + '/battle'); return { ok: true } }
          if (action === 'logs') { await shell.openPath(controller.logsDir); return { ok: true } }
          if (action === 'update-status') { await updates.ready; return updates.snapshot() }
          if (action === 'update-check') return await updates.check()
          if (action === 'update-download') return await updates.update()
          if (action === 'update-install') return await updates.install()
          if (action === 'update-help') { await shell.openExternal('https://github.com/sduwcdd/RoCo-PVP/releases'); return { ok: true } }
          throw Error('Unknown action')
        } catch (error) { controller.log('错误', error.message); return { error: error.message } }
      })
      function closeHud() {
        for (const child of huds) {
          if (child.exitCode != null || child.signalCode) { huds.delete(child); continue }
          if (!child.killed && !child.kill()) throw Error('未能停止HUD进程，请重试退出')
        }
      }
      function stopOwnedResources() {
        if (stoppingResources) return stoppingResources
        stoppingResources = (async () => {
          // A pending Start may acquire an elevated child after quit was requested.
          if (controller.environmentCheckOperation) { try { await controller.environmentCheckOperation } catch (_) {} }
          if (controller.captureOperation) { try { await controller.captureOperation } catch (_) {} }
          if (controller.captureOwned()) await controller.capture('Stop')
          const children = [...huds]
          closeHud()
          await Promise.all(children.map(child => new Promise((resolve, reject) => {
            if (child.exitCode != null || child.signalCode) return resolve()
            const finish = error => {
              clearTimeout(timer); child.removeListener('exit', onExit); child.removeListener('error', onError)
              if (error) reject(error); else resolve()
            }
            const onExit = () => finish()
            const onError = error => finish(error)
            const timer = setTimeout(() => finish(Error('HUD尚未退出，请稍后重试退出')), 5000)
            child.once('exit', onExit); child.once('error', onError)
          })))
          if (controller.starting) { try { await controller.starting } catch (_) {} }
          if (controller.server) await controller.stopService()
        })().finally(() => { stoppingResources = null })
        return stoppingResources
      }
      app.on('before-quit', event => {
        if (quitting) return
        event.preventDefault()
        if (quitRequest) return
        quitRequest = stopOwnedResources().then(() => {
          quitting = true
          if (tray) { tray.destroy(); tray = null }
          app.quit()
        }).catch(error => {
          quitRequest = null
          controller.log('退出失败', error.message)
          showConsole()
          dialog.showErrorBox('洛克PVP尚未退出', '未能停止APP自己的后台进程：' + error.message + '\n请允许停止抓包的管理员授权后，再从托盘重试退出。')
        })
      })
      consoleWindow.on('close', e => {
        if (!quitting) { e.preventDefault(); consoleWindow.hide() }
      })
      await consoleWindow.loadFile(path.join(__dirname, 'desktop.html'))
      if (!process.argv.includes('--verify-desktop')) updates.start()
      if (!quitting) controller.ensureService().catch(error => controller.log('启动失败', error.message))
      if (process.argv.includes('--verify-desktop')) {
        await controller.ensureService()
        const state = await controller.status(huds.size)
        const rendererState = await consoleWindow.webContents.executeJavaScript('window.rocoApp.invoke("status")')
        const imageReady = await consoleWindow.webContents.executeJavaScript('document.querySelector("header img").naturalWidth > 0')
        if (!rendererState.server?.available || !imageReady) throw Error('发布控制台或图标未能完成加载')
        await consoleWindow.webContents.executeJavaScript('window.rocoApp.invoke("workbench")')
        const workbench = BrowserWindow.getAllWindows().find(w => w !== consoleWindow && w.webContents.getURL().startsWith(controller.base + '/battle'))
        if (!workbench) throw Error('工作台验证窗口未创建')
        let ready = false
        for (let attempt = 0; attempt < 40; attempt++) {
          const page = await workbench.webContents.executeJavaScript('({version:document.getElementById("version-label")?.textContent,error:document.getElementById("error-banner")?.hidden===false?document.getElementById("error-banner").textContent:""})')
          if (page.error) throw Error(page.error)
          if (page.version && page.version.includes('个形态') && page.version.includes('个技能')) { ready = true; break }
          await new Promise(resolve => setTimeout(resolve, 250))
        }
        if (!ready) throw Error('工作台图鉴及规则初始化未完成')
        const updateState = await consoleWindow.webContents.executeJavaScript('window.rocoApp.invoke("update-status")')
        const updatePanel = await consoleWindow.webContents.executeJavaScript('({message:document.getElementById("update-status").textContent,tokenInput:!!document.getElementById("update-token")})')
        if (updatePanel.tokenInput || updatePanel.message !== updateState.message) throw Error('公开更新设置未能完成渲染')
        fs.writeFileSync(path.join(controller.logsDir, 'desktop-verification.json'), JSON.stringify({ title: consoleWindow.getTitle(), server: state.server, rendererIpc: true, icon: imageReady, workbenchReady: ready, publicUpdateSettings: true, timestamp: new Date().toISOString() }, null, 2))
        app.quit()
      }
    }).catch(error => { dialog.showErrorBox('洛克PVP启动失败', error.message); app.quit() })
    app.on('window-all-closed', () => {}) // Explicit tray exit owns shutdown; a hidden console stays alive.
    app.on('activate', showConsole)
  }
}
