// 把页面里的按钮接到主进程；上下文隔离下只能暴露最小接口。
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('rocoOverlay', {
  fold: () => ipcRenderer.send('overlay:fold'),
  through: () => ipcRenderer.send('overlay:through'),
  reload: () => ipcRenderer.send('overlay:reload'),
  split: () => ipcRenderer.send('overlay:split'),
  drag: phase => { if (['start', 'move', 'end'].includes(phase)) ipcRenderer.send('overlay:drag', phase) },
  // 关闭是用户最基本的需求：顶部条的 × 和 Ctrl+Alt+Q 都走这里。
  close: () => ipcRenderer.send('overlay:close')
})

window.addEventListener('DOMContentLoaded', () => {
  if (location.pathname !== '/hud-duel' || new URLSearchParams(location.search).get('side') === 'history') return
  const panel = document.getElementById('panel')
  if (!panel) return
  let scheduled = false
  let lastHeight = 0
  function scheduleFit () {
    if (scheduled) return
    scheduled = true
    requestAnimationFrame(() => {
      scheduled = false
      const bodyStyle = getComputedStyle(document.body)
      const panelStyle = getComputedStyle(panel)
      const height = Math.ceil(panel.scrollHeight + parseFloat(panelStyle.borderTopWidth) +
        parseFloat(panelStyle.borderBottomWidth) + parseFloat(bodyStyle.paddingTop) + parseFloat(bodyStyle.paddingBottom))
      if (Number.isFinite(height) && height > 0 && height !== lastHeight) {
        lastHeight = height
        ipcRenderer.send('overlay:content-height', height)
      }
    })
  }
  new ResizeObserver(scheduleFit).observe(panel)
  new MutationObserver(scheduleFit).observe(panel, { childList: true, subtree: true, attributes: true, characterData: true })
  window.addEventListener('resize', scheduleFit)
  scheduleFit()
})
