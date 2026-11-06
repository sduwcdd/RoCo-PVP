'use strict'
const path = require('path')
const root = path.resolve(__dirname, '..')
for (const key of ['ROCO_APP_DIR', 'ROCO_BACKEND_DIR', 'ROCO_RELEASE_META_DIR', 'ROCO_INSTALLER_OUTPUT', 'ROCO_APP_VERSION']) {
  if (!process.env[key]) throw new Error(`Use scripts/build_updatable.py: ${key} is missing`)
}
module.exports = {
  appId: 'com.sduwcdd.rocopvp', productName: '洛克PVP',
  artifactName: 'RocoPVP-Setup-${version}.${ext}',
  directories: { app: process.env.ROCO_APP_DIR, output: process.env.ROCO_INSTALLER_OUTPUT },
  extraMetadata: { version: process.env.ROCO_APP_VERSION, main: 'desktop.js' },
  electronVersion: '45.2.1', electronDist: path.join(root, 'artifacts/release-tools/node_modules/electron/dist'),
  asar: true, npmRebuild: false,
  files: ['package.json', 'desktop.js', 'desktop_services.js', 'desktop_preload.js', 'desktop_renderer.js',
    'desktop_updater.js', 'update_config.json', 'desktop.css', 'main.js', 'preload.js',
    'offline.html', 'dimo.ico', 'desktop.html', 'dimo.png'],
  extraResources: [
    { from: process.env.ROCO_BACKEND_DIR, to: 'backend', filter: ['**/*'] },
    { from: process.env.ROCO_RELEASE_META_DIR, to: '.', filter: ['release.json', 'licenses/**/*'] }
  ],
  win: { target: [{ target: 'nsis', arch: ['x64'] }], icon: path.join(root, 'overlay/dimo.ico'),
    executableName: '洛克PVP', verifyUpdateCodeSignature: false },
  nsis: { oneClick: true, perMachine: false, allowElevation: false,
    deleteAppDataOnUninstall: false, createDesktopShortcut: true, createStartMenuShortcut: true },
  publish: [{ provider: 'github', owner: 'sduwcdd', repo: 'RoCo-PVP', private: false }]
}
