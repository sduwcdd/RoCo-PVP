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
