/*
 * Bridge between this workbench and the carried-over in-game HUD page (/hud).
 *
 * The HUD was written for a WebView2 host: it reads roco.battleHud.* keys from
 * localStorage every 50ms and never talks to a network. That stays untouched.
 * This file only translates the snapshot the workbench publishes under its own
 * namespace (roco.workbench.hud.v1) into the keys the HUD expects, so both
 * pages can stay exactly as they are and still show the same battle.
 */
(function () {
  "use strict";

  var SOURCE_KEY = "roco.workbench.hud.v1";
  var RUNTIME_KEY = "roco.battleHud.combatRuntime.v71";
  var STATE_KEY = "roco.battleHud.state.v52";
  var ENEMY_KEY = "roco.battleHud.recognizedEnemyTeam.v52";
  var last = null;

  function write(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
      /* quota or private mode: the HUD simply keeps its previous frame */
    }
  }

  function sync() {
    var raw = null;
    try {
      raw = localStorage.getItem(SOURCE_KEY);
    } catch (error) {
      return;
    }
    if (!raw || raw === last) return;
    last = raw;
    var snapshot;
    try {
      snapshot = JSON.parse(raw);
    } catch (error) {
      return;
    }
    if (!snapshot || typeof snapshot !== "object") return;
    if (snapshot.runtime) write(RUNTIME_KEY, snapshot.runtime);
    if (snapshot.state) write(STATE_KEY, snapshot.state);
    write(ENEMY_KEY, snapshot.enemyPreview || { enemyTeam: [] });
  }

  sync();
  window.setInterval(sync, 250);

  // 桌面悬浮 HUD（Electron 窗口）与本浏览器不共享 localStorage，
  // 工作台会把同一份快照 POST 到 /api/hud/publish，这里轮询取回再转写。
  var lastRemoteAt = 0;
  function pollRemote() {
    try {
      fetch("/api/hud/snapshot", { cache: "no-store" }).then(function (response) {
        return response.ok ? response.json() : null;
      }).then(function (data) {
        if (!data || !data.payload || !data.at || data.at <= lastRemoteAt) return;
        lastRemoteAt = data.at;
        write(SOURCE_KEY, data.payload);
      }).catch(function () {});
    } catch (error) {}
  }
  pollRemote();
  window.setInterval(pollRemote, 1500);
})();
