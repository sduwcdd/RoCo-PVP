"use strict";
/*
 * 验证照抄过来的第三方 HUD（web/hud.html）在拿到本工作台的局面快照后能真正渲染：
 * 用最小 DOM stub 在 node 里执行它的内联脚本，断言血量、技能、头像都被填上。
 * 快照结构与 battle.js 的 publishHudSnapshot() 一一对应。
 */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const ROOT = path.resolve(__dirname, "..");

function makeNode(tag = "div") {
  const node = {
    tagName: tag,
    className: "",
    textContent: "",
    title: "",
    alt: "",
    src: "",
    hidden: false,
    role: "",
    dataset: {},
    children: [],
    style: {},
    appendChild(child) {
      if (child && child.tagName === "fragment") { this.children.push(...child.children); return child; }
      this.children.push(child);
      return child;
    },
    append(...kids) { for (const kid of kids) this.children.push(kid); },
    replaceChildren(...kids) { this.children = kids; },
    setAttribute(name, value) { this[name] = value; },
    addEventListener() {},
    querySelector(selector) { return node.__child(selector); },
    querySelectorAll() { return node.children; },
    __child(selector) {
      node.__cache = node.__cache || new Map();
      if (!node.__cache.has(selector)) {
        const child = makeNode();
        node.__cache.set(selector, child);
        node.children.push(child);
      }
      return node.__cache.get(selector);
    },
  };
  return node;
}

function makeSandbox(snapshot, files) {
  const roots = new Map();
  const document = {
    getElementById(id) {
      if (!roots.has(id)) roots.set(id, makeNode());
      return roots.get(id);
    },
    querySelector(selector) {
      if (!roots.has(selector)) roots.set(selector, makeNode());
      return roots.get(selector);
    },
    createElement(tag) { return makeNode(tag); },
    createDocumentFragment() { return makeNode("fragment"); },
  };
  const store = new Map();
  store.set("roco.battleHud.combatRuntime.v71", JSON.stringify(snapshot.runtime));
  store.set("roco.battleHud.state.v52", JSON.stringify(snapshot.state));
  store.set("roco.battleHud.recognizedEnemyTeam.v52", JSON.stringify(snapshot.enemyPreview));
  const localStorage = {
    getItem(key) { return store.has(key) ? store.get(key) : null; },
    setItem(key, value) { store.set(key, String(value)); },
    removeItem(key) { store.delete(key); },
  };
  const sandbox = {
    document,
    localStorage,
    console,
    Map, Set, JSON, Math, Number, String, Array, Object, Promise, Date, RegExp,
    setTimeout() {},
    setInterval() {},
    clearInterval() {},
    fetch: (url) => {
      const name = String(url).split("/").pop();
      const body = files[name];
      return Promise.resolve({ ok: body != undefined, json: () => Promise.resolve(body || {}) });
    },
    window: {
      addEventListener() {},
      setInterval() {},
      setTimeout() {},
      crypto: { randomUUID: () => "test-uuid" },
      screenX: 0,
      screenY: 0,
    },
  };
  sandbox.window.document = document;
  sandbox.window.localStorage = localStorage;
  sandbox.globalThis = sandbox;
  return { sandbox, roots, store };
}

function extractScript() {
  const html = fs.readFileSync(path.join(ROOT, "web", "hud.html"), "utf8");
  const start = html.indexOf("<script>");
  const end = html.lastIndexOf("</script>");
  assert.ok(start > 0 && end > start, "hud.html 必须包含内联脚本");
  return html.slice(start + "<script>".length, end);
}

const move = (id, title, power, energy, type, category) => ({
  id, skill_id: id, skillId: id, skillName: title, moveName: title, name: title,
  power, energy_cost: energy, move_type: type, move_category: category,
});

const SNAPSHOT = {
  schema: "workbench-hud-1",
  runtime: {
    sessionId: "match-1", battleId: "match-1",
    myTeam: [
      { memberId: "m1", id: 3004, iconId: 3004, rosterIndex: 0, side: "my", petName: "迪莫", name: "迪莫", hpPercent: 100, currentHp: 332, maxHp: 332, stats: { hp: 332 }, moves: [move(7020480, "旋转突击", 35, 3, "普通系", "物理")], selectedMoves: [], move_pool: [], monster: { base_hp: 65, base_spd: 33, main_type: "普通系", move_pool: [] } },
      { memberId: "m2", id: 3001, iconId: 3001, rosterIndex: 1, side: "my", petName: "喵喵", name: "喵喵", hpPercent: 100, currentHp: 250, maxHp: 250, stats: { hp: 250 }, moves: [], selectedMoves: [], move_pool: [], monster: { base_hp: 65 } },
    ],
    enemyTeam: [
      { memberId: "e1", id: 3001, iconId: 3001, rosterIndex: 0, side: "enemy", petName: "喵喵", name: "喵喵", hpPercent: 82, currentHp: 205, maxHp: 250, stats: { hp: 250 }, moves: [], selectedMoves: [], move_pool: [], monster: { base_hp: 65 } },
    ],
    active: { my: { rosterIndex: 0 }, enemy: { rosterIndex: 0 } },
    hp: { my: { hpAfter: 332, percent: 100 }, enemy: { hpAfter: 205, percent: 82 } },
    observedEnemyMoves: { "喵喵": ["旋转突击"] },
    battleTimeline: [
      { side: "my", kind: "action", turn: 1, activePetName: "迪莫", skillName: "旋转突击" },
      { side: "enemy", kind: "action", turn: 1, activePetName: "喵喵", skillName: "旋转突击" },
    ],
  },
  state: { myTeam: [], enemyTeam: [], myActiveIndex: 0, enemyActiveIndex: 0 },
  enemyPreview: { enemyTeam: [] },
};
SNAPSHOT.state.myTeam = SNAPSHOT.runtime.myTeam;
SNAPSHOT.state.enemyTeam = SNAPSHOT.runtime.enemyTeam;
SNAPSHOT.enemyPreview.enemyTeam = SNAPSHOT.runtime.enemyTeam;

test("HUD 在拿到工作台快照后渲染出双方血量、技能与头像", async () => {
  const files = {
    "roco_buff_calc_map.json": JSON.parse(fs.readFileSync(path.join(ROOT, "data", "external", "roco_buff_calc_map.json"), "utf8")),
    "buff.json": JSON.parse(fs.readFileSync(path.join(ROOT, "data", "external", "buff.json"), "utf8")),
  };
  const { sandbox, roots } = makeSandbox(SNAPSHOT, files);
  vm.createContext(sandbox);
  vm.runInContext(extractScript(), sandbox, { filename: "hud.html" });
  await new Promise((resolve) => setImmediate(resolve));

  const myRegion = roots.get('[data-side="my"]');
  const enemyRegion = roots.get('[data-side="enemy"]');
  assert.ok(myRegion && enemyRegion, "页面必须存在两侧区域");

  const text = (region, key) => region.querySelector(`[data-stat="${key}"]`).textContent;
  assert.equal(text(myRegion, "currentHp"), "332", "我方当前血量必须来自快照");
  assert.equal(text(myRegion, "hpRange"), "332", "我方满血值必须来自工作台算出的面板");
  assert.equal(text(enemyRegion, "currentHp"), "205", "对方当前血量必须来自快照");
  assert.equal(text(enemyRegion, "hpRange"), "250", "对方满血值必须来自快照");

  const skillsHost = myRegion.querySelector('[data-role="skills"]');
  assert.ok(skillsHost.children.length >= 1, "我方技能列表必须渲染出条目");

  const avatar = myRegion.querySelector('[data-role="avatar"]');
  assert.match(avatar.src, /\/roco-pet-avatars-id\/3004\.png$/, "头像必须走 petbase id 路径");

  const bench = myRegion.querySelector('[data-role="bench"]');
  assert.ok(bench.children.length >= 1, "替补席必须渲染出第二只精灵");
});

test("HUD 对空快照不抛异常（工作台未开局时）", async () => {
  const empty = {
    runtime: { myTeam: [], enemyTeam: [], active: {}, hp: {}, observedEnemyMoves: {}, battleTimeline: [] },
    state: { myTeam: [], enemyTeam: [], myActiveIndex: 0, enemyActiveIndex: 0 },
    enemyPreview: { enemyTeam: [] },
  };
  const { sandbox } = makeSandbox(empty, {});
  vm.createContext(sandbox);
  assert.doesNotThrow(() => vm.runInContext(extractScript(), sandbox, { filename: "hud.html" }));
});
