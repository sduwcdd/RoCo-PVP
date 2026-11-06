// 洛克 PVP HUD —— 贴游戏半透明悬浮窗（Electron 主进程）
//
// 为什么用 Electron：HUD 面板本身是 HTML/CSS（照抄自第三方「青空洛克PVP助手」的
// WebView2 面板），Electron 能在 Windows 上做真正带 alpha 合成的透明无边框窗口，
// 而 Qt WebEngine 在 WA_TranslucentBackground 下不绘制网页内容（已实测）。
//
// 数据来源仍是本工程的服务：http://127.0.0.1:<port>/hud
// 网页版原样保留，本程序只是同一页面的桌面容器。

const { app, BrowserWindow, Tray, Menu, ipcMain, globalShortcut, screen, nativeImage, shell } = require('electron')
const path = require('node:path')
const fs = require('node:fs')
const http = require('node:http')

const PORT = Number(process.env.ROCO_HUD_PORT || 8766)
if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) throw Error('Invalid HUD port')
const HUD_ORIGIN = new URL('http://127.0.0.1:' + PORT).origin
// 默认加载第三方原版 HUD 页（/hud-pro）：它比我们自己那版更贴近游戏内观感，
// 数据由服务端注入的 hud_bridge.js 从 /api/hud/snapshot 转写进 localStorage。
// 想回到自制页面就设 ROCO_HUD_PAGE=/hud。
const HUD_PAGE = (!app.isPackaged && process.env.ROCO_HUD_PAGE) || '/hud-pro'
const HUD_URL = 'http://127.0.0.1:' + PORT + HUD_PAGE
const STATE_FILE = app.isPackaged
  ? path.join(process.env.LOCALAPPDATA || path.join(app.getPath('home'), 'AppData', 'Local'), 'RocoPVP', 'overlay-state.json')
  : path.join(__dirname, 'state.json')
const DEFAULT_SIZE = { width: 1200, height: 292 }

const state = readState()
let win = null
let tray = null
let collapsedHeight = 0
let clickThrough = false

function readState () {
  try {
    const data = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'))
    return (data && typeof data === 'object') ? data : {}
  } catch (err) {
    return {}
  }
}

function writeState (patch) {
  Object.assign(state, patch)
  try {
    if (app.isPackaged) fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true })
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 1), 'utf8')
  } catch (err) {
    // 状态文件写不了不影响使用
  }
}

function serviceReady () {
  return new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:' + PORT + '/api/status', { timeout: 1200 }, (res) => {
      res.resume()
      resolve(res.statusCode === 200)
    })
    req.on('error', () => resolve(false))
    req.on('timeout', () => { req.destroy(); resolve(false) })
  })
}

function guardHudWindow (target) {
  const contents = target.webContents
  contents.setWindowOpenHandler(() => ({ action: 'deny' }))
  const guardNavigation = (event, url) => {
    try {
      const destination = new URL(url || event.url)
      if (destination.origin === HUD_ORIGIN && !destination.username && !destination.password) return
    } catch (_) {}
    event.preventDefault()
  }
  contents.on('will-navigate', guardNavigation)
  contents.on('will-frame-navigate', guardNavigation)
  contents.on('will-redirect', guardNavigation)
  contents.on('will-attach-webview', event => event.preventDefault())
  contents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
  contents.session.setPermissionCheckHandler(() => false)
}

function createWindow () {
  const area = screen.getPrimaryDisplay().workArea
  const width = Math.min(Number(state.width) || DEFAULT_SIZE.width, area.width - 30)
  const height = Math.min(Number(state.height) || DEFAULT_SIZE.height, area.height - 30)
  const x = Number.isFinite(state.x) ? Math.min(Math.max(state.x, area.x), area.x + area.width - width)
                                      : Math.round(area.x + (area.width - width) / 2)
  const y = Number.isFinite(state.y) ? Math.min(Math.max(state.y, area.y), area.y + area.height - height)
                                      : area.y + 8

  win = new BrowserWindow({
    width: width,
    height: height,
    x: x,
    y: y,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    hasShadow: false,
    resizable: true,
    movable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    thickFrame: false,
    useContentSize: true,
    title: '洛克 PVP HUD',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged,
      backgroundThrottling: false
    }
  })
  guardHudWindow(win)

  win.setAlwaysOnTop(true, 'screen-saver')
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  if (Number(state.opacity) > 0) win.setOpacity(Math.min(1, Math.max(0.35, state.opacity)))
  // 自查用：把窗口矩形与屏幕工作区打在日志里，判断有没有跑出屏幕。
  console.log('[overlay] bounds ' + JSON.stringify(win.getBounds()) +
              ' workArea ' + JSON.stringify(area) + ' split=' + Boolean(state.split))

  loadHud()

  if (state.follow) snapToTopCenter()

  win.on('moved', persistBounds)
  win.on('resized', persistBounds)
  win.on('closed', () => { win = null })
}

function persistBounds () {
  if (!win || win.isDestroyed()) return
  const b = win.getBounds()
  writeState({ x: b.x, y: b.y, width: b.width, height: b.height })
}

async function loadHud () {
  if (!win || win.isDestroyed()) return
  const ok = await serviceReady()
  if (!win || win.isDestroyed()) return
  if (ok) {
    win.loadURL(hudUrl())
    win.webContents.once('did-finish-load', () => applyOverlayChrome())
  } else {
    win.loadFile(path.join(__dirname, 'offline.html'))
    setTimeout(loadHud, 2500)
  }
}

// 原版页面有两种排布：默认「我方一行 / 敌方一行」，split=1 是「左我方 / 右敌方」。
function hudUrl () {
  if (!state.split || HUD_PAGE.indexOf('/hud-pro') < 0) return HUD_URL
  return HUD_URL + (HUD_URL.indexOf('?') >= 0 ? '&' : '?') + 'split=1'
}

function toggleSplit () {
  state.split = !state.split
  writeState({ split: Boolean(state.split) })
  if (!win || win.isDestroyed()) return
  // 左右两栏需要更宽：每侧至少 110+244+232+边距，两块并排 ≈ 1250px 起。
  if (state.split) {
    const b = win.getBounds()
    if (b.width < 1380) {
      const area = screen.getPrimaryDisplay().workArea
      const width = Math.min(1400, area.width - 20)
      // 加宽后必须重新夹住横向位置，否则右边会跑到屏幕外，顶部条的按钮也会被裁掉。
      const x = Math.max(area.x, Math.min(b.x, area.x + area.width - width))
      win.setBounds({ x: x, y: b.y, width: width, height: b.height })
      persistBounds()
    }
  }
  loadHud()
}

// 页面本身是给浏览器标签写的；这里补上“拖动条 + 不挡游戏”的桌面外壳行为。
function applyOverlayChrome () {
  const isPro = String(win.webContents.getURL()).indexOf('/hud-pro') >= 0
  // 自制 HUD 页要撑满窗口；第三方原版页自己就是 1024×224 居中布局，只能补透明与上边距。
  const pageCss = isPro ? [
    'html, body { background: transparent !important; }',
    'body { padding-top: 18px !important; box-sizing: border-box !important; }'
  ] : [
    'html { background: transparent !important; }',
    'body { background: transparent !important; margin-top: 16px !important;',
    '       padding: 6px !important; height: calc(100% - 16px) !important; }',
    // 网页版把面板钉在 1024px 宽（浏览器标签里居中好看）；悬浮窗要撑满窗口，
    // 否则四个技能槽会被裁掉。
    '.hud { width: 100% !important; height: 100% !important; }'
  ]
  const css = pageCss.concat([
    '#roco-overlay-strip { position: fixed; top: 0; left: 0; right: 0; height: 16px;',
    '  display: flex; align-items: center; gap: 8px; padding: 0 8px;',
    '  box-sizing: border-box; background: rgba(38,52,64,0.55);',
    '  border-top-left-radius: 6px; border-top-right-radius: 6px;',
    '  color: rgba(235,245,252,0.9); font: 12px/1 "Microsoft YaHei", sans-serif;',
    '  -webkit-app-region: drag; z-index: 2147483000; user-select: none; }',
    '#roco-overlay-strip .spacer { flex: 1; }',
    '#roco-overlay-strip button { -webkit-app-region: no-drag; height: 12px;',
    '  padding: 0 6px; border: none; border-radius: 3px;',
    '  background: rgba(255,255,255,0.14); color: inherit; font: inherit; cursor: pointer; }',
    '#roco-overlay-strip button:hover { background: rgba(255,255,255,0.3); }',
    '#roco-overlay-strip button.on { background: rgba(255,214,102,0.9); color: #2f2b24; }',
    '#roco-overlay-strip #roco-close { background: rgba(214,69,60,0.85); color: #fff;',
    '  font-weight: 700; padding: 0 8px; }',
    '#roco-overlay-strip #roco-close:hover { background: rgba(238,86,76,1); }'
  ]).join('\n')

  win.webContents.insertCSS(css).catch(() => {})
  win.webContents.executeJavaScript(`
    (function () {
      if (document.getElementById('roco-overlay-strip')) return 'exists';
      var strip = document.createElement('div');
      strip.id = 'roco-overlay-strip';
      strip.innerHTML = '<span>洛克 PVP HUD · 拖动移动</span><span class="spacer"></span>' +
        '<button id="roco-split" title="左我方 / 右敌方 两栏（原版是上下两行）">分栏</button>' +
        '<button id="roco-fold" title="只留拖动条">折叠</button>' +
        '<button id="roco-through" title="鼠标事件穿透到游戏（Ctrl+Alt+L）">穿透</button>' +
        '<button id="roco-reload" title="重新加载">刷新</button>' +
        '<button id="roco-close" title="关闭悬浮窗（Ctrl+Alt+Q）">× 关闭</button>';
      document.body.appendChild(strip);
      var splitBtn = strip.querySelector('#roco-split');
      if (splitBtn && ${state.split ? 'true' : 'false'}) splitBtn.classList.add('on');
      splitBtn.addEventListener('click', function (e) {
        e.stopPropagation(); window.rocoOverlay.split();
      });
      strip.querySelector('#roco-fold').addEventListener('click', function (e) {
        e.stopPropagation(); window.rocoOverlay.fold();
      });
      strip.querySelector('#roco-through').addEventListener('click', function (e) {
        e.stopPropagation(); window.rocoOverlay.through();
      });
      strip.querySelector('#roco-reload').addEventListener('click', function (e) {
        e.stopPropagation(); window.rocoOverlay.reload();
      });
      strip.querySelector('#roco-close').addEventListener('click', function (e) {
        e.stopPropagation(); window.rocoOverlay.close();
      });
      return document.getElementById('roco-close') ? 'injected:close-ok' : 'injected:no-close';
    })()
  `).then(function (r) {
    // 启动日志里能直接看到按钮是否注入成功（排查"关不掉"时就靠这一行）。
    console.log('[overlay] chrome ' + r)
  }).catch(function (e) { console.log('[overlay] chrome failed: ' + e.message) })
}

function setClickThrough (enabled) {
  clickThrough = Boolean(enabled)
  if (!win || win.isDestroyed()) return
  win.setIgnoreMouseEvents(clickThrough, { forward: true })
  if (!clickThrough) {
    win.setAlwaysOnTop(true, 'screen-saver')
    win.focus()
  }
  updateTrayMenu()
  win.webContents.executeJavaScript(
    "var b = document.getElementById('roco-through'); if (b) b.classList.toggle('on', " +
    (clickThrough ? 'true' : 'false') + ');'
  ).catch(() => {})
}

function snapToTopCenter () {
  if (!win || win.isDestroyed()) return
  const area = screen.getPrimaryDisplay().workArea
  const b = win.getBounds()
  win.setBounds({
    x: Math.round(area.x + (area.width - b.width) / 2),
    y: area.y + 8,
    width: b.width,
    height: b.height
  })
  persistBounds()
}

function toggleFold () {
  if (!win || win.isDestroyed()) return
  const b = win.getBounds()
  if (collapsedHeight === 0) {
    collapsedHeight = b.height
    win.setBounds({ x: b.x, y: b.y, width: b.width, height: 17 })
    win.webContents.executeJavaScript("document.documentElement.style.visibility='hidden'").catch(() => {})
  } else {
    win.setBounds({ x: b.x, y: b.y, width: b.width, height: collapsedHeight })
    collapsedHeight = 0
    win.webContents.executeJavaScript("document.documentElement.style.visibility='visible'").catch(() => {})
  }
}

function updateTrayMenu () {
  if (!tray) return
  const visible = win && !win.isDestroyed() && win.isVisible()
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: visible ? '隐藏 HUD' : '显示 HUD', click: function () { toggleVisible() } },
    { label: '点击穿透', type: 'checkbox', checked: clickThrough, click: function () { setClickThrough(!clickThrough) } },
    { label: '左我方 / 右敌方（分栏）', type: 'checkbox', checked: Boolean(state.split), click: function () { toggleSplit() } },
    { label: '贴屏幕顶部居中', click: function () { snapToTopCenter() } },
    { label: '重新加载页面', click: function () { loadHud() } },
    { type: 'separator' },
    { label: '打开网页版工作台', click: function () { shell.openExternal('http://127.0.0.1:' + PORT + '/battle') } },
    { label: '退出', click: function () { app.quit() } }
  ]))
}

function toggleVisible () {
  if (!win || win.isDestroyed()) return
  if (win.isVisible()) win.hide()
  else win.show()
  updateTrayMenu()
}

function createTray () {
  const iconPath = path.join(__dirname, '..', 'vendor', '洛克PVP助手', 'app', 'assets', 'software-logo-pet-card.png')
  let icon = nativeImage.createFromPath(iconPath)
  if (icon.isEmpty()) icon = nativeImage.createEmpty()
  else icon = icon.resize({ width: 16, height: 16 })
  tray = new Tray(icon)
  tray.setToolTip('洛克 PVP HUD')
  updateTrayMenu()
  tray.on('double-click', function () { toggleVisible() })
}

function fromMainHud (event) {
  return win && !win.isDestroyed() && event.sender === win.webContents
}
ipcMain.on('overlay:fold', function (event) { if (fromMainHud(event)) toggleFold() })
ipcMain.on('overlay:through', function (event) { if (fromMainHud(event)) setClickThrough(!clickThrough) })
ipcMain.on('overlay:reload', function (event) { if (fromMainHud(event)) loadHud() })
ipcMain.on('overlay:split', function (event) { if (fromMainHud(event)) toggleSplit() })
ipcMain.on('overlay:close', function (event) {
  // Duel panes use the same close button without creating the single-HUD window.
  if (fromMainHud(event) || duelWins.some(w => !w.isDestroyed() && event.sender === w.webContents)) app.quit()
})

// 本机 GPU 进程初始化会失败（Electron 报 0xC0000135，GPU process isn't usable），
// 透明窗口在软件合成下一样工作，所以直接关硬件加速。
app.disableHardwareAcceleration()
// Also apply launcher flags here so an already-running console can launch corrected HUD windows.
if (!app.isPackaged) {
  app.commandLine.appendSwitch('no-sandbox')
  app.commandLine.appendSwitch('disable-gpu-sandbox')
}
app.commandLine.appendSwitch('enable-transparent-visuals')
app.commandLine.appendSwitch('disable-gpu-compositing')
app.commandLine.appendSwitch('disable-features', 'CalculateNativeWinOcclusion')

async function captureOnce (target, out) {
  if (app.isPackaged) throw Error('Debug capture is unavailable in packaged builds')
  // 自查用：把工作台渲染成 PNG，便于在没有浏览器自动化时检查排版。
  const shot = new BrowserWindow({ width: Number(process.env.ROCO_SHOT_W) || 1700,
                                   height: Number(process.env.ROCO_SHOT_H) || 1320,
                                   show: false,
                                   webPreferences: { backgroundThrottling: false, contextIsolation: true, nodeIntegration: false, sandbox: true } })
  try {
    // 加时间戳绕过 Chromium 的磁盘缓存，否则改了 HTML 也会截到旧版。
    const bust = target + (target.indexOf('?') >= 0 ? '&' : '?') + 't=' + Date.now()
    await shot.loadURL(bust)
    await new Promise(function (resolve) { setTimeout(resolve, 9000) })
    const image = await shot.capturePage()
    fs.mkdirSync(path.dirname(out), { recursive: true })
    fs.writeFileSync(out, image.toPNG())
    console.log('shot saved', out, JSON.stringify(image.getSize()))

    if (process.env.ROCO_DIAG) {
      const diag = await shot.webContents.executeJavaScript(`(() => {
        const q = (s) => document.querySelector(s)
        const box = (el) => el ? { t: Math.round(el.getBoundingClientRect().top),
                                     b: Math.round(el.getBoundingClientRect().bottom),
                                     h: Math.round(el.getBoundingClientRect().height) } : null
        const rp = q('.record-panel')
        const cc = q('.center-column')
        return JSON.stringify({
          center: box(cc), centerScroll: cc ? cc.scrollHeight : null,
          record: box(rp), recordScroll: rp ? rp.scrollHeight : null,
          recordOverflow: rp ? getComputedStyle(rp).overflow : null,
          form: box(q('#round-form')), grid: box(q('.round-grid')),
          mySide: box(q('#my-action')), myOpt: box(q('#my-action .optional-grid')),
          opSide: box(q('#opponent-action')), opOpt: box(q('#opponent-action .optional-grid')),
          historyPanel: box(q('.history') ? q('.history').closest('.panel') : null)
        }, null, 1)
      })()`)
      console.log('diag', diag)
    }
  } catch (error) {
    console.error('shot failed', error && error.message)
  } finally {
    shot.destroy()
  }
}

app.whenReady().then(async function () {
  const shotTarget = !app.isPackaged && process.env.ROCO_SHOT
  if (shotTarget) {
    const url = shotTarget.startsWith('http') ? shotTarget : 'http://127.0.0.1:' + PORT + '/' + shotTarget
    await captureOnce(url, process.env.ROCO_SHOT_OUT || path.join(__dirname, '..', 'artifacts', 'shot.png'))
    app.quit()
    return
  }

  // 对局双窗模式：屏幕左侧「我方」、右侧「敌方」各一条竖面板，中间让给游戏。
  if (process.env.ROCO_HUD_MODE === 'duel' || state.mode === 'duel') {
    await runDuel()
    return
  }

  createWindow()
  createTray()

  globalShortcut.register('Control+Alt+H', function () { toggleVisible() })
  globalShortcut.register('Control+Alt+L', function () { setClickThrough(!clickThrough) })
  globalShortcut.register('Control+Alt+F', function () { snapToTopCenter() })
  globalShortcut.register('Control+Alt+S', function () { toggleSplit() })
  // 最重要的一个：不管窗口被拖到哪、是否开过穿透，这个键都能彻底关掉悬浮窗。
  globalShortcut.register('Control+Alt+Q', function () { console.log('[overlay] hotkey quit'); app.quit() })

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', function () { app.quit() })
app.on('will-quit', function () { globalShortcut.unregisterAll() })

// ---------------------------------------------------------------------------
// 对局双窗（duel）：照着第三方原版做「左我方 / 右敌方」两条贴边竖面板。
// 用两个独立窗口而不是一个大窗口，中间区域完全不受遮挡，也不用做区域穿透。
// ---------------------------------------------------------------------------
const DUEL_WIDTH = 300
const DUEL_GAP = 10
let duelWins = []
let duelThrough = false
let duelDrag = null

ipcMain.on('overlay:drag', function (event, phase) {
  const target = duelWins.find(w => !w.isDestroyed() && w.webContents === event.sender)
  if (!target || duelThrough) return
  if (phase === 'start') duelDrag = { target, cursor: screen.getCursorScreenPoint(), position: target.getPosition(), size: { ...target.duelSize } }
  else if (duelDrag && duelDrag.target === target) {
    if (phase === 'move') {
      const cursor = screen.getCursorScreenPoint()
      // Native getBounds/setPosition accumulates invisible frame pixels at Windows 150% scaling.
      target.setBounds({ x: duelDrag.position[0] + cursor.x - duelDrag.cursor.x,
        y: duelDrag.position[1] + cursor.y - duelDrag.cursor.y, ...duelDrag.size })
    } else if (phase === 'end') duelDrag = null
  }
})

function duelBounds (side) {
  const area = screen.getPrimaryDisplay().workArea
  if (side === 'history') {
    const width = Math.min(640, Math.max(260, area.width - DUEL_WIDTH * 2 - 40))
    return { x: area.x + Math.round((area.width - width) / 2), y: area.y + 8,
      width, height: Math.min(210, Math.max(120, Math.floor(area.height / 3))) }
  }
  const width = Math.min(DUEL_WIDTH, Math.max(200, Math.floor(area.width / 4)))
  const height = Math.max(1, area.height - 24)
  const y = area.y + 12
  const x = side === 'my'
    ? area.x + DUEL_GAP
    : area.x + area.width - width - DUEL_GAP
  return { x: x, y: y, width: width, height: height }
}

function injectDuelChrome (target, side) {
  const label = side === 'history' ? '回合记录' : side === 'my' ? '我方' : '敌方'
  const accent = side === 'history' ? 'rgba(38,80,72,0.9)' : side === 'my' ? 'rgba(46,120,180,0.85)' : 'rgba(178,74,56,0.85)'
  const css = [
    'html, body { background: transparent !important; }',
    '#roco-duel-strip { position: fixed; top: 0; left: 0; right: 0; height: 16px;',
    '  display: flex; align-items: center; gap: 6px; padding: 0 6px;',
    '  box-sizing: border-box; background: ' + accent + ';',
    '  border-top-left-radius: 8px; border-top-right-radius: 8px;',
    '  color: #fff; font: 12px/1 "Microsoft YaHei", sans-serif;',
    '  -webkit-app-region: no-drag; cursor: move; touch-action: none; z-index: 2147483000; user-select: none; }',
    '#roco-duel-strip .spacer { flex: 1; }',
    '#roco-duel-strip button { -webkit-app-region: no-drag; height: 12px; padding: 0 7px;',
    '  border: none; border-radius: 3px; background: rgba(255,255,255,0.2);',
    '  color: #fff; font: inherit; font-weight: 700; cursor: pointer; }',
    '#roco-duel-strip button:hover { background: rgba(255,255,255,0.38); }',
    '#roco-duel-strip #roco-duel-close { background: rgba(214,69,60,0.95); }'
  ].join('\n')

  target.webContents.insertCSS(css).catch(() => {})
  target.webContents.executeJavaScript(`
    (function () {
      if (document.getElementById('roco-duel-strip')) return 'exists';
      var strip = document.createElement('div');
      strip.id = 'roco-duel-strip';
      strip.innerHTML = '<span>${label} · 拖动</span><span class="spacer"></span>' +
        '<button id="roco-duel-close" title="关闭HUD（Ctrl+Alt+Q）">×</button>';
      document.body.appendChild(strip);
      var pointer = null;
      strip.addEventListener('pointerdown', function (e) {
        if (e.button !== 0 || e.target.closest('button')) return;
        e.preventDefault(); pointer = e.pointerId;
        strip.setPointerCapture(pointer); window.rocoOverlay.drag('start');
      });
      strip.addEventListener('pointermove', function (e) {
        if (e.pointerId === pointer) window.rocoOverlay.drag('move');
      });
      function endDrag(e) {
        if (e && e.pointerId !== pointer) return;
        if (pointer !== null) { pointer = null; window.rocoOverlay.drag('end'); }
      }
      strip.addEventListener('pointerup', endDrag);
      strip.addEventListener('pointercancel', endDrag);
      strip.addEventListener('lostpointercapture', endDrag);
      window.addEventListener('blur', function () { endDrag(); });
      strip.querySelector('#roco-duel-close').addEventListener('click', function (e) {
        e.stopPropagation(); window.rocoOverlay.close();
      });
      return 'injected:duel-${side}';
    })()
  `).then(function (r) { console.log('[duel] chrome ' + r) })
   .catch(function (e) { console.log('[duel] chrome failed: ' + e.message) })
}

function createDuelWindow (side) {
  const b = duelBounds(side)
  const w = new BrowserWindow({
    show: !process.argv.includes('--verify-hud'),
    x: b.x, y: b.y, width: b.width, height: b.height,
    frame: false,
    transparent: true,
    backgroundColor: '#00000000',
    hasShadow: false,
    resizable: false,
    movable: true,
    skipTaskbar: true,
    alwaysOnTop: true,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    thickFrame: false,
    useContentSize: true,
    title: '洛克 PVP ' + (side === 'history' ? '回合记录' : side === 'my' ? '我方' : '敌方'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged,
      backgroundThrottling: false
    }
  })
  guardHudWindow(w)
  w.duelSize = { width: b.width, height: b.height }
  w.duelSide = side
  w.setBounds(b)
  w.setAlwaysOnTop(true, 'screen-saver')
  w.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  w.loadURL('http://127.0.0.1:' + PORT + '/hud-duel?side=' + side)
  w.webContents.once('did-finish-load', function () { injectDuelChrome(w, side) })
  w.webContents.once('did-finish-load', function () {
    if (!process.argv.includes('--verify-hud')) { w.show(); w.moveTop() }
    console.log('[duel] ready ' + side)
  })
  w.webContents.on('did-fail-load', function (_event, code, description) { console.error('[duel] load failed ' + side + ': ' + code + ' ' + description) })
  w.webContents.on('render-process-gone', function (_event, details) { console.error('[duel] renderer gone ' + side + ': ' + details.reason) })
  console.log('[duel] ' + side + ' bounds ' + JSON.stringify(w.getBounds()))
  return w
}

function setDuelThrough (enabled) {
  duelThrough = Boolean(enabled)
  duelDrag = null
  duelWins.forEach(function (w) {
    if (w && !w.isDestroyed()) w.setIgnoreMouseEvents(duelThrough, { forward: true })
  })
}

async function runDuel () {
  const ok = await serviceReady()
  if (!ok) console.log('[duel] 服务未就绪，先起 python -m lab.server --port ' + PORT)
  duelWins = [createDuelWindow('my'), createDuelWindow('enemy'), createDuelWindow('history')]
  if (process.argv.includes('--verify-hud')) {
    await Promise.all(duelWins.map(w => new Promise((resolve, reject) => {
      w.webContents.once('did-finish-load', resolve)
      w.webContents.once('did-fail-load', (_event, code, description) => reject(Error(code + ' ' + description)))
    })))
    const states = await Promise.all(duelWins.map(w => w.webContents.executeJavaScript('document.readyState')))
    console.log('[duel] verification ' + JSON.stringify(states))
    app.quit()
    return
  }
  if (process.argv.includes('--hud-only')) {
    process.stdin.setEncoding('utf8')
    process.stdin.on('data', function (command) {
      if (command.trim() === 'show') duelWins.forEach(function (w) { if (!w.isDestroyed()) { w.show(); w.moveTop() } })
    })
  }
  if (!process.argv.includes('--hud-only')) createTray()

  globalShortcut.register('Control+Alt+L', function () { setDuelThrough(!duelThrough) })
  globalShortcut.register('Control+Alt+F', function () {
    duelWins.forEach(function (w, index) {
      if (!w || w.isDestroyed()) return
      const bounds = duelBounds(w.duelSide || (index === 0 ? 'my' : 'enemy'))
      w.duelSize = { width: bounds.width, height: bounds.height }
      w.setBounds(bounds)
    })
  })
  globalShortcut.register('Control+Alt+Q', function () { console.log('[overlay] hotkey quit'); app.quit() })

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) {
      duelWins = [createDuelWindow('my'), createDuelWindow('enemy'), createDuelWindow('history')]
    }
  })
}
