"use strict";
// Run with: node --test tests/test_buff_preview_ui.js
// Drives the real preview-panel handler with an in-memory DOM: the unpacked buff table
// must turn into one click per layer on the four stat inputs.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "..");

const api = vm.runInNewContext(
  fs.readFileSync(path.join(root, "web/weather_view.js"), "utf8") + "\n" +
  fs.readFileSync(path.join(root, "web/battle_mechanics.js"), "utf8") + "\n" +
  fs.readFileSync(path.join(root, "web/battle.js"), "utf8") + "\nBattleData",
  {});

const dims = ["hp", "patk", "matk", "pdef", "mdef", "spd"];
const plain = (value) => JSON.parse(JSON.stringify(value));

function catalog() {
  return {
    snapshot_id: "fixture-v1",
    forms: [{ id: 100, title: "测试形态", types: ["普通系"] }, { id: 101, title: "对方形态", types: ["火系"] }],
    moves: { 7: { id: 7, name: { zh: "测试技能" } }, 7020620: { id: 7020620, name: { zh: "力量增效" } }, 7020680: { id: 7020680, name: { zh: "锐利眼神" } } },
    natures: [{ id: 22, name: { zh: "性格" }, up: "patk", down: "matk" }],
    details: { 100: { learnset: { pool: [7, 7020620, 7020680] }, form: { id: 100 } }, 101: { learnset: { pool: [7, 7020680] }, form: { id: 101 } } },
  };
}

const BUFFS = {
  "7020620": { move_id: 7020620, move_name: "力量增效", buffs: [{ buff_id: 20010010, name: "物攻等级提升", type: 1, target: "self", percents: { patk: 10 }, desc: "物攻+10%" }] },
  "7020680": { move_id: 7020680, move_name: "锐利眼神", buffs: [
    { buff_id: 20010011, name: "物防等级降低", type: 2, target: "opponent", percents: { pdef: -10 }, desc: "物防-10%" },
    { buff_id: 20010021, name: "魔防等级降低", type: 2, target: "opponent", percents: { mdef: -10 }, desc: "魔防-10%" },
  ] },
};

function harness(){
  class Node {
    constructor(tag = "div") { this.tagName = tag; this.children = []; this.value = ""; this.attributes = {}; this.classList = { add() {}, remove() {} }; }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return (this._text || "") + this.children.map((n) => n.textContent).join(""); }
    append(...children) { for (const child of children) { if (child.parentNode) { const siblings = child.parentNode.children, index = siblings.indexOf(child); if (index >= 0) siblings.splice(index, 1); } child.parentNode = this; this.children.push(child); } }
    replaceChildren(...children) { this._text = ""; this.children = [...children]; }
    setAttribute(key, value) { this.attributes[key] = value; }
    querySelectorAll(tag) { return this.children.flatMap((n) => [...(n.tagName === tag ? [n] : []), ...n.querySelectorAll(tag)]); }
    showModal() { this.open = true; }
    close() { this.open = false; }
  }
  const nodes = new Map();
  const get = (id) => { if (!nodes.has(id)) nodes.set(id, new Node()); return nodes.get(id); };
  const context = {
    fetch: async () => ({ ok: true, json: async () => ({ moves: BUFFS }) }),
    document: { getElementById: get, createElement: (tag) => new Node(tag), createTextNode: (text) => ({ textContent: String(text), children: [] }) },
    localStorage: { getItem: () => null, setItem() {} },
    crypto: { randomUUID: () => "buff-ui" },
    confirm: () => true,
    setTimeout: () => 0,
    clearTimeout: () => {},
  };
  const expose = `globalThis.ui={init(c,s,buffs){catalog=c;data=BattleData.create(c);currentSnapshot=c.snapshot_id;app={storage_version:2,session:data.session(s),templates:[],active_template_id:null};buffTable=buffs;refreshAdvice=()=>{};refreshPreview=()=>{};},renderPreviewBuffs,previewApplicableBuffs,get app(){return app}};`;
  vm.runInNewContext((fs.readFileSync(path.join(root, "web/weather_view.js"), "utf8") + "\n" + fs.readFileSync(path.join(root, "web/battle_mechanics.js"), "utf8") + "\n" + fs.readFileSync(path.join(root, "web/battle.js"), "utf8")).replace("  boot();", expose), context);
  return { ui: context.ui, get };
}

function session(){
  const mine = { member_id: "my", form_id: 100, nature_id: null, move_ids: [7020620, 7020680, 0, 0] };
  const theirs = { member_id: "opp", form_id: 101, nature_id: null, move_ids: [7, 0, 0, 0] };
  return {
    schema_version: 2, match_id: "match", revision: 0, snapshot_id: "fixture-v1",
    teams: { my: [mine], opponent: [theirs] }, rounds: [], opponent_beliefs: {},
    draft: { my: { active_member_id: "my" }, opponent: { active_member_id: "opp" } },
  };
}

test("one click adds one buff layer to the matching stat input", () => {
  const { ui, get } = harness();
  ui.init(catalog(), session(), BUFFS);
  ui.renderPreviewBuffs();
  const chips = get("preview-buffs").children.filter((n) => n.tagName === "button");
  assert.equal(chips.length, 3, "力量增效 + 锐利眼神的两条都要出现");
  const mine = chips.find((n) => /力量增效/.test(n.textContent));
  assert.ok(mine, "我方物攻 buff 必须出现");
  mine.onclick();
  assert.equal(get("preview-my-patk").value, "10");
  mine.onclick();
  assert.equal(get("preview-my-patk").value, "20", "第二次点击代表第二层");
});

test("enemy defence debuff lands on the opponent defence inputs as a negative percent", () => {
  const { ui, get } = harness();
  ui.init(catalog(), session(), BUFFS);
  ui.renderPreviewBuffs();
  const chips = get("preview-buffs").children.filter((n) => n.tagName === "button");
  const pdef = chips.find((n) => /锐利眼神/.test(n.textContent) && /物防/.test(n.textContent));
  const mdef = chips.find((n) => /锐利眼神/.test(n.textContent) && /魔防/.test(n.textContent));
  assert.ok(pdef && mdef, "我方降对方双防都要出现");
  pdef.onclick();
  assert.equal(get("preview-opp-pdef").value, "-10");
  mdef.onclick();
  assert.equal(get("preview-opp-mdef").value, "-10");
});

test("a debuff the opponent casts on us is not offered, because this panel only predicts our attack", () => {
  const { ui } = harness();
  const data = plain(session());
  data.teams.my[0].move_ids = [7, 0, 0, 0];
  data.teams.opponent[0].move_ids = [7020680, 0, 0, 0];
  ui.init(catalog(), data, BUFFS);
  assert.equal(ui.previewApplicableBuffs().length, 0);
});

test("skills without panel buffs are not offered", () => {
  const { ui } = harness();
  const data = plain(session());
  data.teams.my[0].move_ids = [7, 0, 0, 0];
  data.teams.opponent[0].move_ids = [7, 0, 0, 0];
  ui.init(catalog(), data, BUFFS);
  ui.renderPreviewBuffs();
  assert.equal(ui.previewApplicableBuffs().length, 0);
});
