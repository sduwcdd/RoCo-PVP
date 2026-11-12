"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../mobile/shared/index.html"), "utf8");
const script = html.split("<script>")[1].split("</script>")[0];

function element(dataset = {}) {
  const attributes = new Map();
  return {
    dataset, hidden: false, textContent: "", events: {},
    classList: { add() {}, toggle() {} },
    addEventListener(name, callback) { this.events[name] = callback; },
    setAttribute(name, value) { attributes.set(name, value); },
    hasAttribute(name) { return attributes.has(name); },
    removeAttribute(name) { attributes.delete(name); },
    set src(value) { attributes.set("src", value); },
    get src() { return attributes.get("src"); },
  };
}

function mobile(overlay = false) {
  const nodes = new Map([...html.matchAll(/\bid="([^"]+)"/g)].map(match => [match[1], element()]));
  const names = ["setup", "my", "enemy", "both", "history", "dex"];
  const pages = names.map(name => {
    const page = nodes.get(name + "-page");
    page.id = name + "-page";
    page.frames = name === "setup" ? [] : (name === "both" ? ["my", "enemy"] : [name])
      .map(side => element({ url: side === "dex" ? "/dex" : "/hud-duel?side=" + side }));
    page.empty = element();
    page.querySelectorAll = () => page.frames;
    page.querySelector = () => page.empty;
    return page;
  });
  const tabs = names.map(name => Object.assign(nodes.get(name + "-tab"), { dataset: { view: name } }));
  const frames = pages.flatMap(page => page.frames);
  const rounds = [element(), element(), element(), element(), element()];
  const messages = [element(), element(), element(), element()];
  let device = { state: "running", overlay_allowed: true };
  const status = { capture_running: true, battle_detected: true, battle_round: 3 };
  let offline = false;
  let heldResponse = null;
  const delays = [];
  const calls = [];
  const update = { state: "idle", busy: false, currentVersion: "0.10-internal", message: "点击检查更新" };
  const document = {
    body: element(),
    getElementById: id => nodes.get(id),
    querySelectorAll: selector => ({
      ".page": pages, "[data-view]": tabs, "[data-go]": [], iframe: frames,
      ".pip": [], ".round-label": rounds, ".empty-message": messages,
    })[selector] || [],
  };
  const context = vm.createContext({
    document, location: { search: overlay ? "?overlay=1" : "" },
    window: { Android: {
      status: () => JSON.stringify(device),
      updateStatus: () => JSON.stringify(update),
      checkUpdate: () => calls.push("check-update"),
      downloadUpdate: () => calls.push("download-update"),
      installUpdate: () => calls.push("install-update"),
      requestOverlay: () => calls.push("overlay"),
      stopCapture: () => calls.push("stop"),
      exportProtocolSamples: () => calls.push("export"),
      setMode: mode => { calls.push(mode); status.mode = mode; device.mode = mode; },
    }, addEventListener() {} },
    URLSearchParams, AbortController,
    setTimeout(callback, delay) { delays.push(delay); return 1; }, clearTimeout() {},
    fetch: async () => {
      if (offline) throw new Error("engine unavailable");
      if (heldResponse) { const response = heldResponse; heldResponse = null; return response; }
      return { ok: true, json: async () => status };
    },
  });
  // Keep startup side effects separate while exercising the actual page functions.
  vm.runInContext(script.slice(0, script.indexOf("if(android){try{apps=")), context);
  return {
    nodes, pages, rounds, calls, status, delays, update,
    run: code => vm.runInContext(code, context),
    pause() { device = { ...device, analysis_state: "paused", analysis_message: "解析已暂停，VPN 转发继续。" }; },
    resume() { device = { ...device, analysis_state: "running" }; },
    queue(depth) { device = { ...device, transport: { mirror_queue_depth: depth } }; },
    holdResponse() {
      let release;
      heldResponse = new Promise(resolve => {
        release = () => resolve({
          ok: true,
          json: async () => ({
            mode: "pve", capture_running: true,
            pve: { ready: true, enemy: { name: "过期响应" } },
          }),
        });
      });
      return release;
    },
    disconnect() { offline = true; },
  };
}

test("protocol sample export is available after game bytes are collected", async () => {
  const app = mobile();
  await app.run("refresh()");
  assert.equal(app.nodes.get("export-samples").disabled, true);
  app.run("parser.protocol_samples={active:true,game_flows:1,events:3,bytes:321,seconds_remaining:15}");
  await app.run("refresh()");
  assert.equal(app.nodes.get("export-samples").disabled, false);
  assert.match(app.nodes.get("sample-status").textContent, /15秒/);
  app.nodes.get("export-samples").events.click();
  assert.deepEqual(app.calls, ["export"]);
});

test("overlay uses the shared HUD and unloads inactive panels", async () => {
  const app = mobile(true);
  await app.run("refresh()");
  assert.equal(app.run("selected"), "my");
  assert.equal(app.pages[1].frames[0].src, "/hud-duel?side=my");
  app.run("showView('enemy')");
  assert.equal(app.pages[1].frames[0].src, undefined);
  assert.equal(app.pages[2].frames[0].src, "/hud-duel?side=enemy");
  app.run("showView('setup')");
  assert.equal(app.run("selected"), "enemy");
  app.nodes.get("overlay").events.click();
  assert.deepEqual(app.calls, ["overlay"]);
});

test("analysis pause stays distinct from VPN forwarding and clears stale battle panels", async () => {
  const app = mobile(true);
  await app.run("refresh()");
  app.pause();
  await app.run("refresh()");
  assert.equal(app.nodes.get("status-label").textContent, "分析暂停");
  assert.equal(app.nodes.get("connection-summary").textContent, "分析已暂停 · 游戏转发继续运行");
  assert.equal(app.nodes.get("connection-detail").textContent, "解析已暂停，VPN 转发继续。");
  assert.equal(app.nodes.get("start-label").textContent, "停止采集");
  assert.equal(app.pages[1].frames[0].hidden, true);
  assert.equal(app.pages[1].frames[0].src, undefined);
  assert.equal(app.rounds[0].textContent, "分析暂停");
  app.resume();
  await app.run("refresh()");
  assert.equal(app.nodes.get("status-label").textContent, "已连接");
  assert.equal(app.pages[1].frames[0].src, "/hud-duel?side=my");
});

test("native pause remains visible when the parser endpoint fails", async () => {
  const app = mobile(true);
  app.pause();
  app.disconnect();
  await app.run("refresh()");
  assert.equal(app.nodes.get("connection-banner").dataset.kind, "paused");
  assert.match(app.nodes.get("connection-summary").textContent, /游戏转发继续运行/);
  app.nodes.get("start").events.click();
  assert.deepEqual(app.calls, ["stop"]);
});

test("a lost parser response hides previous battle data and reports connection failure", async () => {
  const app = mobile(true);
  await app.run("refresh()");
  app.disconnect();
  await app.run("refresh()");
  assert.equal(app.nodes.get("status-pill").dataset.kind, "error");
  assert.equal(app.pages[1].frames[0].src, undefined);
  assert.equal(app.rounds[0].textContent, "连接中断");
});

test("PVE mode exposes connection and enemy tabs and unloads all PVP frames", async () => {
  const app = mobile(true);
  await app.run("refresh()");
  await app.run("setMode('pve')");
  assert.equal(app.run("selected"), "enemy");
  assert.equal(app.nodes.get("pve-panel").hidden, false);
  assert.equal(app.nodes.get("enemy-frames").hidden, true);
  for (const name of ["setup", "enemy"]) assert.equal(app.nodes.get(name + "-tab").hidden, false);
  for (const name of ["my", "both", "history", "dex"]) assert.equal(app.nodes.get(name + "-tab").hidden, true);
  for (const page of app.pages) for (const frame of page.frames) assert.equal(frame.src, undefined);
  app.run("showView('setup')");
  assert.equal(app.run("selected"), "setup");
  assert.equal(app.nodes.get("mode-select").value, "pve");
  app.run("showView('my')");
  assert.equal(app.run("selected"), "setup");
  await app.run("setMode('pvp')");
  assert.equal(app.nodes.get("pve-panel").hidden, true);
  assert.equal(app.pages[1].frames[0].src, "/hud-duel?side=my");
  assert.deepEqual(app.calls, ["pve", "pvp"]);
});

test("PVE renders the current creature facts and polls without loading the HUD", async () => {
  const app = mobile();
  app.status.mode = "pve";
  app.status.pve = { ready: true, generation: 1, enemy: {
    name: "测试精灵", icon: "/roco-pet-avatars-id/3004.png", natureName: "固执",
    natureUp: "物攻", natureDown: "魔攻", weightText: "12.5 kg", voiceText: "高音",
    medals: ["勋章甲（已确认）", "勋章乙（范围提示）"],
  } };
  await app.run("refresh()");
  assert.equal(app.nodes.get("pve-card").hidden, false);
  assert.equal(app.nodes.get("pve-name").textContent, "测试精灵");
  assert.equal(app.nodes.get("pve-icon").src, "/roco-pet-avatars-id/3004.png");
  assert.equal(app.nodes.get("pve-icon").hidden, false);
  assert.equal(app.nodes.get("pve-nature").textContent, "固执");
  assert.equal(app.nodes.get("pve-nature-up").textContent, "↑ 物攻");
  assert.equal(app.nodes.get("pve-nature-down").textContent, "↓ 魔攻");
  assert.equal(app.nodes.get("pve-weight").textContent, "12.5 kg");
  assert.equal(app.nodes.get("pve-voice").textContent, "高音");
  assert.equal(app.nodes.get("pve-medals").textContent, "勋章甲（已确认） · 勋章乙（范围提示）");
  assert.equal(app.delays.at(-1), 250);
  assert.ok(app.pages.every(page => page.frames.every(frame => frame.src === undefined)));
});

test("PVE clears the previous enemy while waiting, disconnected, or changing modes", async () => {
  const app = mobile();
  app.status.mode = "pve";
  app.status.pve = { ready: true, generation: 1, enemy: { name: "上一只精灵", icon: "/assets/pet.png" } };
  await app.run("refresh()");
  app.status.pve = { ready: false, generation: 2, enemy: null, notice: "等待下一只精灵" };
  await app.run("refresh()");
  assert.equal(app.nodes.get("pve-card").hidden, true);
  assert.equal(app.nodes.get("pve-name").textContent, "");
  assert.equal(app.nodes.get("pve-icon").src, undefined);
  assert.equal(app.nodes.get("pve-notice").textContent, "等待下一只精灵");
  app.status.pve = { ready: true, generation: 3, enemy: { name: "新的精灵" } };
  await app.run("refresh()");
  app.queue(1);
  await app.run("refresh()");
  assert.equal(app.nodes.get("pve-name").textContent, "");
  assert.match(app.nodes.get("pve-notice").textContent, /正在同步/);
  app.queue(0);
  await app.run("refresh()");
  const switching = app.run("setMode('pvp')");
  assert.equal(app.nodes.get("pve-name").textContent, "");
  await switching;
  await app.run("setMode('pve')");
  await app.run("refresh()");
  assert.equal(app.nodes.get("pve-name").textContent, "新的精灵");
  const release = app.holdResponse();
  const previousRequest = app.run("refresh()");
  await app.run("refresh()");
  await app.run("setMode('pvp')");
  release();
  await previousRequest;
  assert.equal(app.nodes.get("pve-name").textContent, "");
  assert.equal(app.run("mode"), "pvp");
  await app.run("setMode('pve')");
  app.disconnect();
  await app.run("refresh()");
  assert.equal(app.nodes.get("pve-card").hidden, true);
  assert.equal(app.nodes.get("pve-name").textContent, "");
  assert.match(app.nodes.get("pve-notice").textContent, /连接中断/);
});

test("mobile HUD puts skills ahead of the radar and keeps short panels touch sized", () => {
  const app = mobile(true);
  const frame = app.pages[1].frames[0];
  const injected = [];
  frame.src = frame.dataset.url;
  frame.contentDocument = {
    querySelector() { return null; },
    createElement() { return {}; },
    head: { append(node) { injected.push(node); } },
  };
  frame.events.load();
  const style = injected.find(node => node.textContent).textContent;
  assert.match(style, /#panel\{display:flex;flex-direction:column/);
  assert.match(style, /#panel>\.skills\{order:3\}/);
  assert.match(style, /#panel>\.stats-radar\{order:6\}/);
  assert.match(style, /#panel>\.physical-info\{order:7\}/);
  assert.match(style, /@media\(max-height:450px\)/);
  assert.match(style, /grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(style, /button,select,input\{min-height:44px!important\}/);
  assert.match(html, /\.overlay \.topbar,\.overlay \.view-header\{display:none\}/);
  assert.match(html, /\.overlay \.connection-banner\{height:28px/);
});

test("Android update UI exposes progress and retryable installation", () => {
  const app = mobile();
  app.run("renderUpdate()");
  assert.equal(app.nodes.get("app-update").hidden, false);
  assert.match(app.nodes.get("update-version").textContent, /0.10-internal/);
  app.nodes.get("check-update").events.click();
  assert.ok(app.calls.includes("check-update"));
  Object.assign(app.update, { state: "downloading", busy: true, versionCode: 11, versionName: "0.11-internal", progress: 42, downloaded: 42, size: 100 });
  app.run("renderUpdate()");
  assert.equal(app.nodes.get("update-progress").value, 42);
  assert.equal(app.nodes.get("check-update").disabled, true);
  assert.equal(app.nodes.get("install-update").hidden, true);
  Object.assign(app.update, { state: "ready", busy: false });
  app.run("renderUpdate()");
  assert.equal(app.nodes.get("install-update").hidden, false);
  app.nodes.get("install-update").events.click();
  assert.ok(app.calls.includes("install-update"));
  const overlay = mobile(true);
  overlay.run("renderUpdate()");
  assert.equal(overlay.nodes.get("app-update").hidden, true);
});
