"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const html = fs.readFileSync(path.join(__dirname, "../mobile/shared/pvp-panel.html"), "utf8");
const script = html.split("<script>")[1].split("</script>")[0];

function events(target = {}) {
  const listeners = new Map();
  return Object.assign(target, {
    addEventListener(name, callback) { listeners.set(name, callback); },
    removeEventListener(name, callback) { if (listeners.get(name) === callback) listeners.delete(name); },
    emit(name) { if (listeners.has(name)) listeners.get(name)(); },
  });
}

function panelPage(search = "?side=my") {
  const timers = new Map(), observers = [], heights = [], appended = [];
  const panel = { scrollHeight: 140, scrollTop: 20, innerHTML: "original HUD" };
  const fetch = () => { throw Error("wrapper must not fetch"); };
  const childWindow = events({
    fetch,
    getComputedStyle: () => ({ borderTopWidth: "1px", borderBottomWidth: "1px" }),
  });
  const doc = {
    getElementById: id => id === "panel" ? panel : null,
    querySelector: () => null,
    createElement: tagName => ({ tagName }),
    head: { appendChild: node => appended.push(node) },
  };
  const frame = events({ contentDocument: doc, contentWindow: childWindow });
  const window = events({ Android: { setContentHeight: value => heights.push(value) } });
  class Observer {
    constructor(callback) { this.callback = callback; this.disconnected = false; observers.push(this); }
    observe(target, options) { this.target = target; this.options = options; }
    disconnect() { this.disconnected = true; }
  }
  let nextTimer = 0;
  vm.runInNewContext(script, {
    window, document: { getElementById: () => frame }, location: { search }, URLSearchParams,
    ResizeObserver: Observer, MutationObserver: Observer,
    setTimeout(callback, delay) { assert.equal(delay, 32); timers.set(++nextTimer, callback); return nextTimer; },
    clearTimeout: id => timers.delete(id),
    fetch,
    setInterval() { throw Error("wrapper must not start a polling loop"); },
  });
  return {
    frame, window, panel, observers, timers, heights, appended, childWindow, fetch,
    flush() {
      const pending = [...timers.values()];
      timers.clear();
      pending.forEach(callback => callback());
    },
  };
}

test("panel URL accepts only the three HUD sides and adds no backend polling", () => {
  for (const side of ["my", "enemy", "history"]) {
    const page = panelPage("?side=" + side);
    assert.equal(page.frame.src, "/hud-duel?side=" + side);
    page.frame.emit("load");
    page.flush();
    assert.equal(page.childWindow.fetch, page.fetch);
    assert.equal(page.panel.innerHTML, "original HUD");
    assert.equal(page.panel.scrollTop, 20);
  }
  for (const query of ["", "?side=MY", "?side=both", "?side=https://example.com", "?side=enemy%26other=1"]) {
    assert.equal(panelPage(query).frame.src, "/hud-duel?side=my");
  }
});

test("transparent wrapper injects compact styles and a mobile viewport without reordering HUD", () => {
  const page = panelPage("?side=history");
  page.frame.emit("load");
  const viewport = page.appended.find(node => node.tagName === "meta");
  assert.equal(viewport.name, "viewport");
  assert.equal(viewport.content, "width=device-width,initial-scale=1");
  assert.match(html, /name="viewport" content="width=device-width,initial-scale=1"/);
  assert.match(html, /iframe \{[^}]*height: 100%;[^}]*background: transparent;/);
  const css = page.appended.find(node => node.tagName === "style").textContent;
  assert.match(css, /#panel, #panel\[data-side="history"\] \{ flex: 0 0 auto; min-height: 0;/);
  assert.match(css, /background: transparent !important/);
  assert.match(css, /\.avatar, \.bench img \{ width: 32px; height: 32px;/);
  assert.match(css, /min-height: 32px/);
  assert.doesNotMatch(css, /\border\s*:/);
  assert.equal(page.observers[0].target, page.panel);
  assert.equal(page.observers[1].options.subtree, true);
  assert.equal(page.observers[1].options.characterData, true);
});

test("natural CSS height follows content growth and shrinkage through one debounced report", () => {
  const page = panelPage();
  page.frame.emit("load");
  assert.equal(page.timers.size, 1);
  page.flush();
  assert.deepEqual(page.heights, [142]);
  page.panel.scrollHeight = 480;
  for (let i = 0; i < 4; i++) {
    page.observers.forEach(observer => observer.callback());
    page.window.emit("resize");
    page.childWindow.emit("resize");
  }
  assert.equal(page.timers.size, 1);
  page.flush();
  assert.deepEqual(page.heights, [142, 482]);
  page.window.emit("resize");
  page.flush();
  assert.equal(page.heights.length, 2);
  page.panel.scrollHeight = 60;
  page.observers[1].callback();
  page.flush();
  assert.deepEqual(page.heights, [142, 482, 62]);
  assert.equal(page.timers.size, 0);
});

test("invalid heights are rejected and history uses the same natural-height reporting", () => {
  const page = panelPage("?side=history");
  page.frame.emit("load");
  page.flush();
  for (const height of [NaN, Infinity, -Infinity, -2, -20]) {
    page.panel.scrollHeight = height;
    page.observers[0].callback();
    page.flush();
  }
  assert.deepEqual(page.heights, [142]);
  page.panel.scrollHeight = 3000;
  page.observers[1].callback();
  page.flush();
  assert.deepEqual(page.heights, [142, 3002]);
});

test("iframe reload and pagehide disconnect observers and cancel pending reports", () => {
  const page = panelPage();
  page.frame.emit("load");
  const firstObservers = [...page.observers];
  page.frame.emit("load");
  assert.ok(firstObservers.every(observer => observer.disconnected));
  assert.equal(page.timers.size, 1);
  page.flush();
  assert.deepEqual(page.heights, [142]);
  page.observers.at(-1).callback();
  assert.equal(page.timers.size, 1);
  page.window.emit("pagehide");
  assert.ok(page.observers.every(observer => observer.disconnected));
  assert.equal(page.timers.size, 0);
  page.observers.forEach(observer => observer.callback());
  page.window.emit("resize");
  page.childWindow.emit("resize");
  page.frame.emit("load");
  assert.equal(page.timers.size, 0);
  page.flush();
  assert.deepEqual(page.heights, [142]);
});
