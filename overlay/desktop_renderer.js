'use strict'
const $ = id => document.getElementById(id)
let polling = false
function text(id, value, kind) { $(id).textContent = value; if (kind) $(id).className = kind }
function number(value) { return value == null ? '—' : Number(value).toLocaleString('zh-CN') }
async function refresh() {
  if (polling) return
  polling = true
  try {
    const state = await window.rocoApp.invoke('status')
    if (state.error) throw Error(state.error)
    const cap = state.live.capture
    text('server-state', state.server.available ? '已连接' : '未连接', state.server.available ? 'good' : 'bad')
    text('server-detail', state.server.available ? '本机端口 ' + state.server.port + ' · ' + (state.server.owned ? 'APP管理' : '复用外部服务') : state.server.error || '请点击连接 / 启动')
    $('stop-service').disabled = !state.server.owned
    text('capture-state', state.relay.pending ? '正在处理抓包请求…' : state.relay.available ? '中继在线' : '中继未连接', state.relay.available ? 'good' : 'waiting')
    text('capture-detail', state.relay.available ? (state.relay.owned ? '正在使用APP已启动的抓包，无需再次管理员授权；可在此停止' : '已自动复用现有抓包，无需再次管理员授权；外部进程保持运行') : state.relay.result?.error || '首次启动需要管理员权限；已以管理员身份运行时不会重复弹窗')
    $('capture-start').disabled = state.relay.pending || state.relay.available
    $('capture-start').textContent = state.relay.available ? (state.relay.owned ? '抓包已启动' : '已复用现有抓包') : '开始抓包'
    $('capture-start').title = state.relay.available ? '现有中继已连接，无需再次启动或管理员授权' : '启动新的采集进程，必要时请求管理员授权'
    $('capture-stop').disabled = state.relay.pending || !state.relay.owned
    const ready = state.relay.available && (cap.key_hits > 0 || cap.parsed_business_records > 0 || state.live.hasBattle)
    text('game-state', !state.relay.available ? '等待抓包连接' : state.live.statusStale ? '工作台响应暂缓' : state.live.keyMissing ? '等待会话密钥' : state.live.hasBattle ? state.live.finished ? '上一局已结束' : '对局同步中' : ready ? '密钥就绪 · 等待对局' : '中继在线 · 等待对局数据', ready && !state.live.statusStale ? 'good' : 'waiting')
    text('game-detail', state.live.hint || (!state.relay.available ? '当前中继离线；下方为最近一次采集统计。' : state.live.hasBattle ? '第 ' + state.live.round + ' 回合 · 已接收 ' + state.live.events + ' 条事件' : '需要新密钥时，先启动抓包，再重新登录游戏。'))
    text('packets', number(cap.target_packets)); text('records', number(cap.parsed_business_records)); text('keys', number(cap.key_hits))
    text('hud-state', state.hudCount ? 'HUD进程已启动 · Ctrl+Alt+Q可关闭' : '左右双面板 · 生命 / 能量 / 配招 / 伤害范围')
    $('hud-close').disabled = !state.hudCount
    text('overall', ready ? '实战连接已就绪' : state.server.available ? '工作台已就绪' : '服务待启动')
    text('log', [state.logs.map(row => '[' + row.at + '] ' + row.kind + ' · ' + row.message).join('\n'), state.captureOutput].filter(Boolean).join('\n') || '暂无错误；等待连接事件。')
    if (state.lastError) text('notice', state.lastError, 'bad')
    else if ($('notice').className === 'bad') text('notice', '', 'good')
  } catch (e) { text('notice', e.message, 'bad') } finally { polling = false }
}
for (const id of ['start-service','stop-service','capture-start','capture-stop','hud-open','hud-close','workbench','browser','logs']) {
  $(id).addEventListener('click', async () => {
    $(id).disabled = true
    text('notice', id.startsWith('capture') ? '正在处理抓包请求；需要管理员权限时会弹出UAC…' : '正在处理…', 'waiting')
    try {
      const result = await window.rocoApp.invoke(id, id === 'capture-start' ? $('iface').value : undefined)
      if (result?.error) throw Error(result.error)
      text('notice', result.reused ? '已复用现有连接，无需再次管理员授权。' : '操作完成。连接状态会自动更新。', 'good')
    } catch (e) { text('notice', e.message, 'bad') } finally { $(id).disabled = false; refresh() }
  })
}
refresh(); setInterval(refresh, 2000)

let updatePolling = false
async function refreshUpdates () {
  if (updatePolling) return
  updatePolling = true
  try {
    const state = await window.rocoApp.invoke('update-status')
    if (state.error) throw Error(state.error)
    text('app-version', '当前版本 ' + state.version)
    text('update-status', state.message, state.stage === 'error' ? 'bad' : state.stage === 'ready' || state.stage === 'current' ? 'good' : 'waiting')
    $('update-check').disabled = state.busy || !state.installed
    $('update-download').disabled = state.busy || !state.installed || !state.availableVersion || state.canInstall
    $('update-install').disabled = state.busy || !state.canInstall
    $('update-progress').hidden = state.progress == null
    if (state.progress != null) $('update-progress').value = state.progress
  } catch (error) { text('update-status', error.message, 'bad') }
  finally { updatePolling = false }
}
for (const [id, action] of Object.entries({ 'update-check': 'update-check', 'update-download': 'update-download',
  'update-install': 'update-install', 'update-help': 'update-help' })) {
  $(id).addEventListener('click', async () => {
    $(id).disabled = true
    try {
      const request = window.rocoApp.invoke(action)
      if (id !== 'update-help') text('update-status', '正在处理，请稍候…', 'waiting')
      const result = await request
      if (result?.error) throw Error(result.error)
    } catch (error) { text('update-status', error.message, 'bad') }
    finally { $(id).disabled = false; refreshUpdates() }
  })
}
refreshUpdates(); setInterval(refreshUpdates, 1000)
