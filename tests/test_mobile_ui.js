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
  const calls = [];
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
      requestOverlay: () => calls.push("overlay"),
      stopCapture: () => calls.push("stop"),
    }, addEventListener() {} },
    URLSearchParams, AbortController,
    setTimeout() { return 1; }, clearTimeout() {},
    fetch: async () => {
      if (offline) throw new Error("engine unavailable");
      return { ok: true, json: async () => status };
    },
  });
  // Keep startup side effects separate while exercising the actual page functions.
  vm.runInContext(script.slice(0, script.indexOf("if(android){try{apps=")), context);
  return {
    nodes, pages, rounds, calls,
    run: code => vm.runInContext(code, context),
    pause() { device = { ...device, analysis_state: "paused", analysis_message: "解析已暂停，VPN 转发继续。" }; },
    resume() { device = { ...device, analysis_state: "running" }; },
    disconnect() { offline = true; },
  };
}

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
