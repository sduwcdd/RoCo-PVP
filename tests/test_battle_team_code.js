"use strict";
// Run with: node --test tests/test_battle_team_code.js
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const root = path.resolve(__dirname, "..");
const api = vm.runInNewContext((fs.readFileSync(path.join(root,"web/weather_view.js"),"utf8")+"\n"+fs.readFileSync(path.join(root,"web/battle_mechanics.js"),"utf8")+"\n"+fs.readFileSync(path.join(root,"web/battle.js"),"utf8"))+"\nBattleData",{});
const dims = ["hp","patk","matk","pdef","mdef","spd"];
const plain = value => JSON.parse(JSON.stringify(value));
function catalog(){return {snapshot_id:"fixture-v1",forms:[{id:100,title:"测试形态"},{id:101,title:"其他形态"}],moves:{7:{id:7,name:{zh:"测试技能"}},8:{id:8,name:{zh:"条件技能"}}},natures:[{id:22,name:{zh:"方向匹配的性格"},up:"patk",down:"matk"}],details:{100:{learnset:{pool:[7]}},101:{learnset:{pool:[7]}}}};}
function result(){return {raw_code:"B~Bfixture",protocol_version:1,team_type_id:11,core_magic:{id:104002,name:"愿力强化",source:"user_verified_examples"},snapshot_id:"fixture-v1",source_version:"fixture",protocol_source:{url:"https://roco-showdown.com/teams",official_protocol:false},raw_fields:{version:"B~"},format_valid:true,importable:true,training_eligible:false,issues:[{category:"unverified",code:"duplicate_talent_markers",member_slot:1,message:"重复标记，待核实"}],members:[{slot:1,form_id:100,form_name:"测试形态",bloodline_id:19,nature_id:2,nature:{original:{id:2,bwiki_id:22,name:"方向匹配的性格",up:"patk",down:"matk"},modifiers:{up_id:1,down_id:6},final:{up:"hp",down:"spd"}},raw_talent_markers:[80,80,80],raw_fields:{talents:["BQ","BQ","BQ"]},move_ids:[7,0,8,0],moves:[],importable:true}]};}
function imported(){return api.create(catalog()).importCode(result(),"opponent",()=>"new-member")[0];}
function session(m){return {schema_version:2,match_id:"match",revision:0,snapshot_id:"fixture-v1",teams:{my:[m],opponent:[]},rounds:[],opponent_beliefs:{}};}
test("four slots retain empty positions, raw duplicate markers, and no invented IVs",()=>{
  const m=imported();assert.deepEqual(plain(m.move_ids),[7,0,8,0]);assert.deepEqual(plain(m.code_provenance.original_member.raw_talent_markers),[80,80,80]);assert.deepEqual(plain(m.talents),Object.fromEntries(dims.map(d=>[d,null])));assert.equal(m.training_eligible,false);assert.equal(m.code_provenance.training_eligible,false);assert.deepEqual(plain(m.confirmed.moves),[]);assert.equal(m.confirmed.nature,false);
});
test("nature uses the BWIKI mapped ID without losing protocol ID or modifiers",()=>{
  const m=imported();assert.equal(m.nature_id,22);assert.equal(m.code_provenance.original_member.nature_id,2);assert.deepEqual(plain(m.nature_modifiers),{up_id:1,down_id:6});assert.equal(m.bloodline_id,19);assert.equal(m.form_id,100);
});
test("protocol evidence and raw team fields survive session/template/JSON roundtrip",()=>{
  const d=api.create(catalog()),m=imported(),store={storage_version:2,session:session(m),templates:[{id:"template",name:"固定队",team:[m],snapshot_id:"fixture-v1",updated_at:"2026-10-25"}],active_template_id:"template"};
  const saved=d.storage(JSON.parse(JSON.stringify(store)));for(const entry of [saved.session.teams.my[0],saved.templates[0].team[0]]){assert.deepEqual(plain(entry.move_ids),[7,0,8,0]);assert.equal(entry.code_provenance.raw_code,"B~Bfixture");assert.equal(entry.code_provenance.protocol_source.official_protocol,false);assert.equal(entry.code_provenance.raw_fields.version,"B~");assert.equal(entry.code_provenance.edited_since_import,false);}
});
test("manual edits preserve original evidence, become divergent, and cannot enable training",()=>{
  const d=api.create(catalog()),m=plain(imported());m.move_ids=[0,7,8,0];m.bloodline_id=4;m.talents.patk=10;m.training_eligible=true;m.code_provenance.training_eligible=true;
  const changed=d.member(m,"my",0);assert.deepEqual(plain(changed.move_ids),[0,7,8,0]);assert.equal(changed.code_provenance.edited_since_import,true);assert.equal(changed.training_eligible,false);assert.equal(changed.code_provenance.original_member.bloodline_id,19);assert.equal(changed.code_provenance.original_configuration.talents.patk,null);
});
test("known database conflict stays visible and is not silently repaired",()=>{
  const r=result();r.issues.push({category:"database_conflict",member_slot:1,code:"bloodline_mismatch",message:"血脉不符"});const m=api.create(catalog()).importCode(r,"my",()=>"id")[0];assert.deepEqual(plain(m.move_ids),[7,0,8,0]);assert.equal(m.bloodline_id,19);assert.equal(m.code_provenance.issues.at(-1).category,"database_conflict");
});
test("unknown skill, duplicate filled slots, format errors and user-confirmed errors block import",()=>{
  const d=api.create(catalog());for(const mutate of [r=>r.members[0].move_ids=[7,0,999,0],r=>r.members[0].move_ids=[7,7,0,0],r=>r.format_valid=false,r=>r.issues.push({category:"user_confirmed_error",message:"已确认错误"})]){const r=result();mutate(r);assert.throws(()=>d.importCode(r,"my",()=>"id"));}
});
test("a changed snapshot cannot be imported from a stale preview",()=>{
  const r=result();r.snapshot_id="old";assert.throws(()=>api.create(catalog()).importCode(r,"my",()=>"id"),/快照/);
});
test("ordinary manual members cannot bypass the learning range using a boolean flag",()=>{
  const d=api.create(catalog());assert.throws(()=>d.member({form_id:100,nature_id:null,move_ids:[8,0,0,0],training_eligible:false},"my",0),/学习资料/);const empty=d.member({form_id:100,nature_id:null,move_ids:[0,0,0,0]},"my",0);assert.deepEqual(plain(empty.confirmed.moves),[]);
});
test("damaged provenance fails explicitly instead of silently discarding evidence",()=>{
  const m=plain(imported());delete m.code_provenance.original_configuration;assert.throws(()=>api.create(catalog()).member(m,"my",0),/来源记录/);
});
test("legacy short move arrays still load with their original order",()=>{
  const m=api.create(catalog()).member({form_id:100,nature_id:null,move_ids:[7]},"my",0);assert.deepEqual(plain(m.move_ids),[7]);
});

function beliefCandidate(id,moves,posterior,known=true){return {id,moves,posterior,move_slots_known:known,nature_id:22,talents:Object.fromEntries(dims.map(d=>[d,10]))};}
function candidateBelief(candidates){return {status:"ok",probability_source:"candidate_prior",population_statistics:false,candidates};}
test("joint beliefs preserve sparse slot order and empty probability without treating zero as a skill",()=>{
  const d=api.create(catalog()),input=candidateBelief([beliefCandidate("a",[8,0,7,0],.75),beliefCandidate("b",[7,0,8,0],.25)]);
  const b=d.belief(input);assert.deepEqual(plain(b.candidates[0].moves),[8,0,7,0]);
  assert.equal(b.move_slots_known,true);assert.equal(b.move_marginals.some(m=>m.move_id===0),false);
  assert.deepEqual(plain(b.move_slot_marginals[0]),{slot:0,options:[{move_id:8,probability:.75},{move_id:7,probability:.25}]});
  assert.deepEqual(plain(b.move_slot_marginals[1].options),[{move_id:0,probability:1}]);
  assert.deepEqual(plain(d.belief(plain(b)).candidates),plain(b.candidates));
});
test("unknown legacy belief order stays unknown through persistence and partial candidates suppress positional probabilities",()=>{
  const d=api.create(catalog()),c=beliefCandidate("old",[7,8,0,0],1);delete c.move_slots_known;
  const b=d.belief(candidateBelief([c]));assert.equal(b.move_slots_known,false);assert.equal(b.move_slot_marginals,null);
  assert.equal(d.belief(plain(b)).move_slots_known,false);
  const partial=d.belief(candidateBelief([beliefCandidate("partial",[8,7],.5,false),beliefCandidate("full",[7,0,8,0],.5)]));
  assert.equal(partial.move_slot_marginals,null);assert.deepEqual(plain(partial.candidates[0].moves),[8,7]);
});
test("belief adapter rejects overflow and duplicate skills without fixing them",()=>{
  const d=api.create(catalog());
  for(const moves of [[7,0,8,0,0],[7,7,0,0],[999,0,0,0]])assert.throws(()=>d.belief(candidateBelief([beliefCandidate("bad",moves,1)])));
  assert.throws(()=>d.belief(candidateBelief([beliefCandidate("short",[7],1)])),/四槽/);
  assert.deepEqual(plain(d.belief(candidateBelief([beliefCandidate("empty",[0,0,0,0],1)])).move_marginals),[]);
});

test("damage prediction provenance survives display-summary roundtrip without claiming calibration",()=>{
  const d=api.create(catalog()),input=candidateBelief([beliefCandidate("a",[7,0,8,0],1)]);
  Object.assign(input,{damage_likelihood_models:["uniform_integer_range","explicit_discrete_pmf"],
    damage_prediction_sources:[{id:"caller-model",snapshot_id:"fixture-v1",verified:false}],prediction_verified:false});
  const b=d.belief(input),again=d.belief(plain(b));
  assert.deepEqual(plain(again.damage_prediction_sources),input.damage_prediction_sources);
  assert.deepEqual(plain(again.damage_likelihood_models),input.damage_likelihood_models);
  assert.equal(again.prediction_verified,false);assert.equal(again.snapshot_id,"fixture-v1");
  input.damage_prediction_sources[0].verified=true;assert.throws(()=>d.belief(input),/未验证/);
});
test("damage evidence cannot mix snapshots or inject a verified prediction claim",()=>{
  const d=api.create(catalog()),input=candidateBelief([beliefCandidate("a",[7,0,8,0],1)]);
  input.damage_prediction_sources=[{id:"one",snapshot_id:"fixture-v1",verified:false},{id:"two",snapshot_id:"old",verified:false}];
  assert.throws(()=>d.belief(input),/快照/);
  input.damage_prediction_sources.pop();input.snapshot_id="old";assert.throws(()=>d.belief(input),/快照/);
  delete input.snapshot_id;input.prediction_verified=true;assert.throws(()=>d.belief(input),/已验证/);
});
test("display-underflow candidates are retained as possible and suppress positional certainty",()=>{
  const d=api.create(catalog()),input=candidateBelief([beliefCandidate("a",[7,0,8,0],1)]);
  input.underflowed_candidate_ids=["tiny-but-possible"];
  const b=d.belief(input);assert.equal(b.move_slots_known,false);assert.equal(b.move_slot_marginals,null);
  assert.deepEqual(plain(d.belief(plain(b)).underflowed_candidate_ids),["tiny-but-possible"]);
  input.underflowed_candidate_ids.push("tiny-but-possible");assert.throws(()=>d.belief(input),/重复/);
});

test("PMF provenance cannot disappear and a displayed positive candidate cannot claim underflow",()=>{
  const d=api.create(catalog()),input=candidateBelief([beliefCandidate("a",[7,0,8,0],1)]);
  input.damage_likelihood_models=["explicit_discrete_pmf"];assert.throws(()=>d.belief(input),/来源/);
  input.damage_likelihood_models=[];input.damage_prediction_sources=[{id:"model",snapshot_id:"fixture-v1",verified:false}];assert.throws(()=>d.belief(input),/来源/);
  input.damage_prediction_sources=[];input.underflowed_candidate_ids=["a"];assert.throws(()=>d.belief(input),/冲突/);
});

test("team-code selection deduplicates markers and marks ten as a user default, never a decoded IV",()=>{
  const m=imported();assert.deepEqual(plain(m.talent_selection),{selected:[],values:{},value_sources:{},selection_source:"team_code_markers",default_value:10});
  assert.equal(m.code_provenance.edited_since_import,false);assert.equal(m.confirmed.talents.patk,false);
  assert.deepEqual(plain(m.code_provenance.original_member.raw_talent_markers),[80,80,80]);assert.equal(m.code_provenance.issues[0].code,"duplicate_talent_markers");
  const dup=api.create(catalog()).importCode(result(),"my",()=>"dup")[0];
  assert.deepEqual(plain(dup.talent_selection.selected),[],"重复标记不代表三个维度，不能默认成物攻+10");
  assert.equal(plain(dup.talents).patk,null,"重复标记不得把十写进资质");
  const r=result();r.members[0].raw_talent_markers=[79,81,84];
  assert.deepEqual(plain(api.create(catalog()).importCode(r,"my",()=>"three")[0].talent_selection.selected),["hp","matk","spd"]);
  r.members[0].raw_talent_markers=[0,0,0];assert.deepEqual(plain(api.create(catalog()).importCode(r,"my",()=>"empty")[0].talent_selection.selected),[]);
});
test("selection roundtrip leaves historical six-dimensional values and confirmation intact",()=>{
  const d=api.create(catalog()),m=plain(imported());m.talents=Object.fromEntries(dims.map((dim,i)=>[dim,i+20]));m.talent_selection={selected:["patk","matk","spd"],values:{patk:10,matk:8,spd:10},value_sources:{patk:"user_default",matk:"user_entered",spd:"user_default"},selection_source:"user_selected",default_value:10};
  const saved=d.storage({storage_version:2,session:session(m),templates:[{id:"s",name:"三项配置",team:[m],snapshot_id:"fixture-v1",updated_at:"2026-10-25"}],active_template_id:"s"});
  for(const entry of [saved.session.teams.my[0],saved.templates[0].team[0]]){assert.deepEqual(plain(entry.talents),m.talents);assert.deepEqual(plain(entry.talent_selection),m.talent_selection);assert.equal(entry.code_provenance.edited_since_import,true);assert.deepEqual(plain(entry.confirmed.talents),m.confirmed.talents);}
  const old=plain(m);delete old.talent_selection;assert.equal(d.member(old,"my",0).talent_selection,undefined);
});
test("selection validation rejects duplicate, unknown, overflow, invented unselected values, and invalid defaults",()=>{
  const base=plain(imported().talent_selection);
  for(const change of [s=>s.selected.push("patk"),s=>s.selected=["hp","patk","matk","spd"],s=>s.selected=["evil"],s=>s.values.hp=10,s=>s.values.patk=9,s=>s.values.patk=-1,s=>s.values.patk=10.5,s=>s.value_sources.patk="decoded",s=>s.default_value=20]){const s=plain(base);change(s);assert.throws(()=>api.talentSelection(s));}
  const custom=plain(base);custom.selected=["patk"];custom.values.patk=15;custom.value_sources.patk="user_entered";assert.equal(api.talentSelection(custom).values.patk,15);
});
function observedSession(damage=127,hp=24){const d=api.create(catalog()),m=d.member({member_id:"my",form_id:100,nature_id:null,move_ids:[7]},"my",0),s=session(m);s.teams.opponent=[d.member({member_id:"opp",form_id:101,nature_id:null,move_ids:[7]},"opponent",0)];s.rounds=[{event_id:"r1",recorded_at:"2026-10-25T00:00:00Z",turn:1,note:"",my:{member_id:"my",form_id:100,slot:0,kind:"charge",received_damage:damage,remaining_hp_percent:hp},opponent:{member_id:"opp",form_id:101,slot:0,kind:"charge",received_damage:null,remaining_hp_percent:null}}];return s;}
test("integer HP percentages and damage survive rounds and drafts without exact HP inference",()=>{
  const d=api.create(catalog()),s=observedSession();s.draft={my:{active_member_id:"my",received_damage:43,remaining_hp_percent:1},opponent:{}};
  const saved=d.session(s),again=d.session(plain(saved));assert.equal(again.rounds[0].my.remaining_hp_percent,24);assert.equal(again.rounds[0].my.received_damage,127);assert.equal(Object.hasOwn(again.rounds[0].my,"remaining_hp"),false);assert.equal(again.draft.my.remaining_hp_percent,1);assert.equal(again.draft.my.received_damage,43);
  for(const hp of [-1,100.01,NaN,Infinity,"42"]){const bad=observedSession(127,hp);assert.throws(()=>d.session(bad),/百分比/);}
  assert.throws(()=>d.session(observedSession(12.5)),/整数/);for(const hp of [0,100,null])assert.equal(d.session(observedSession(0,hp)).rounds[0].my.remaining_hp_percent,hp);
});
test("old absolute HP remains absolute through both schema versions and can coexist with new percentages",()=>{
  const d=api.create(catalog());for(const version of [1,2]){const s=observedSession();s.schema_version=version;delete s.rounds[0].my.remaining_hp_percent;s.rounds[0].my.remaining_hp=150;s.draft={my:{active_member_id:"my",remaining_hp:90},opponent:{}};
    const saved=d.session(s),again=d.session(plain(saved));assert.equal(again.rounds[0].my.remaining_hp,150);assert.equal(again.rounds[0].my.remaining_hp_unit,"legacy_absolute");assert.equal(again.rounds[0].my.remaining_hp_percent,null);if(version===2){assert.equal(again.draft.my.remaining_hp,90);assert.equal(again.draft.my.remaining_hp_percent,null);}
  }
  const s=observedSession();s.rounds[0].my.remaining_hp=75;const saved=d.session(s);assert.equal(saved.rounds[0].my.remaining_hp,75);assert.equal(saved.rounds[0].my.remaining_hp_percent,24);
});
test("only my fully confirmed four nonempty slots lock the action list",()=>{
  const m={move_ids:[7,8,9,10],confirmed:{moves:[10,7,9,8]}};
  assert.equal(api.confirmedMoves("my",m),true);assert.equal(api.confirmedMoves("opponent",m),false);assert.equal(api.confirmedMoves("my",{...m,move_ids:[7,0,9,10]}),false);assert.equal(api.confirmedMoves("my",{...m,confirmed:{moves:[7,8,9]}}),false);assert.equal(api.confirmedMoves("my",null),false);
});

// Exercise the actual UI handlers with an in-memory DOM; no browser storage is touched.
function uiHarness(input,c=catalog(),request=async()=>({ok:true,json:async()=>({current:null,frames:[]})})){
  class Node {
    constructor(tag="div"){this.tagName=tag;this.children=[];this.value="";this.attributes={};this.classList={add(){},remove(){}};}
    set textContent(value){this._text=String(value);this.children=[];}
    get textContent(){return (this._text||"")+this.children.map(n=>n.textContent).join("");}
    get lastChild(){return this.children.at(-1)||null;}
    append(...children){for(const child of children){if(child.parentNode){const siblings=child.parentNode.children,index=siblings.indexOf(child);if(index>=0)siblings.splice(index,1);}child.parentNode=this;this.children.push(child);}}
    replaceChildren(...children){this._text="";this.children=[...children];}
    setAttribute(key,value){this.attributes[key]=value;}
    querySelectorAll(tag){return this.children.flatMap(n=>[...(n.tagName===tag?[n]:[]),...n.querySelectorAll(tag)]);}
    checkValidity(){if(this.type!=="number"||this.value==="")return true;const v=Number(this.value);return Number.isFinite(v)&&v>=Number(this.min??0)&&(this.max===undefined||v<=Number(this.max))&&(this.step==="any"||Number.isInteger(v));}
    reportValidity(){return true;}
    showModal(){this.open=true;}
    close(){this.open=false;}
  }
  const nodes=new Map(),storage=new Map();let serial=0;
  const get=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
  const context={fetch:request,document:{getElementById:get,createElement:tag=>new Node(tag),createTextNode:text=>({textContent:String(text),children:[]})},localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v)},crypto:{randomUUID:()=>"ui-"+(++serial)},confirm:()=>true,setTimeout:()=>0,clearTimeout:()=>{}};
  const expose=`globalThis.ui={init(c,s){catalog=c;data=BattleData.create(c);currentSnapshot=c.snapshot_id;app={storage_version:2,session:data.session(s),templates:[],active_template_id:null};refreshAdvice=()=>{};},setDamageInference(value){damageInference=value;},renderAction,renderTeam,renderWeather,history,actionFromDraft,openEditor,saveMember,record,undo,actionLabel,fresh,refreshPreview,get app(){return app},get editor(){return editor}};`;
  vm.runInNewContext((fs.readFileSync(path.join(root,"web/weather_view.js"),"utf8")+"\n"+fs.readFileSync(path.join(root,"web/battle_mechanics.js"),"utf8")+"\n"+fs.readFileSync(path.join(root,"web/battle.js"),"utf8")).replace("  boot();",expose),context);context.ui.init(c,input);return {ui:context.ui,get,storage};
}
test("actual action UI restricts confirmed own moves in slot order and retains opponent learning-range observation",()=>{
  const c=catalog();for(const id of [9,10,11])c.moves[id]={id,name:{zh:"技能"+id}};c.details[100].learnset.pool=[7,8,9,10,11];
  const m=api.create(c).member({member_id:"my",form_id:100,nature_id:null,move_ids:[10,7,9,8]},"my",0),s=session(m);s.teams.opponent=[{...plain(m),member_id:"opp"}];s.draft={my:{active_member_id:"my",all_moves:true},opponent:{active_member_id:"opp",all_moves:true}};
  const {ui,get}=uiHarness(s,c);ui.renderAction("my");let wrap=get("my-action");assert.equal(wrap.querySelectorAll("input").filter(n=>n.type==="checkbox").length,0);assert.deepEqual(wrap.querySelectorAll("select")[2].children.map(n=>n.value),["",10,7,9,8]);
  ui.renderAction("opponent");wrap=get("opponent-action");assert.equal(wrap.querySelectorAll("input").filter(n=>n.type==="checkbox").length,0);assert.ok(wrap.querySelectorAll("select")[2].children.some(n=>n.value===11));
  const metrics=wrap.querySelectorAll("input").filter(n=>n.type==="number");assert.equal(metrics[0].step,"1");assert.equal(metrics[1].max,"100");assert.equal(metrics[1].step,"1");
});
test("actual editor defaults selected items to ten, requires own three choices, and preserves old six values",()=>{
  const m=plain(imported());m.member_id="my";m.talents=Object.fromEntries(dims.map((d,i)=>[d,i+21]));const {ui,get}=uiHarness(session(m));ui.openEditor("my","my");
  assert.equal(Object.keys(ui.editor.talent_selection.values).length,0,"重复标记解析为空选择，不再自动给物攻10");assert.equal(get("editor-talents").querySelectorAll("input").filter(n=>n.type==="number").length,0);assert.throws(()=>ui.saveMember(),/选择三项/);assert.equal(ui.app.session.revision,0);
  for(const index of [0,1,5]){const check=get("editor-talents").children[index].children[0].children[0];check.checked=true;check.onchange();}
  const mat=get("editor-talents").children[1].querySelectorAll("input").find(n=>n.type==="number");mat.value="8";mat.oninput();ui.editor.confirmationChanged=true;ui.saveMember();
  const saved=ui.app.session.teams.my[0];assert.deepEqual(plain(saved.talent_selection.selected),["hp","patk","spd"]);assert.equal(saved.talent_selection.values.patk,8);assert.equal(saved.talent_selection.value_sources.patk,"user_entered");assert.deepEqual(plain(saved.talents),m.talents);assert.deepEqual(plain(saved.code_provenance.original_member.raw_talent_markers),[80,80,80]);
  const opp={...m,member_id:"opponent"},s=session(m);s.teams.opponent=[opp];const h=uiHarness(s);h.ui.openEditor("opponent","opponent");h.ui.saveMember();assert.equal(h.ui.app.session.teams.opponent[0].talent_selection.selected.length,0,"对方重复标记保存后不得凭空生成物攻10");
});
test("actual record, undo, and replay labels retain percent, integer damage, and legacy absolute values separately",()=>{
  const s=observedSession();s.rounds=[];s.draft={my:{active_member_id:"my",kind:"charge",received_damage:127,remaining_hp_percent:24,remaining_hp:150},opponent:{active_member_id:"opp",kind:"charge",received_damage:25,remaining_hp_percent:90}};
  const {ui,get}=uiHarness(s);ui.renderAction("my");assert.match(get("my-action").textContent,/legacy.*150/);ui.record();const a=ui.app.session.rounds[0].my;assert.equal(a.remaining_hp_percent,24);assert.equal(a.remaining_hp,150);assert.match(ui.actionLabel(a),/24%.*legacy.*150/);assert.equal(ui.app.session.draft.my.remaining_hp_percent,null);assert.equal(ui.app.session.draft.my.remaining_hp,undefined);
  ui.undo();assert.equal(ui.app.session.rounds.length,0);assert.equal(ui.app.session.draft.my.remaining_hp_percent,24);assert.equal(ui.app.session.draft.my.remaining_hp,150);assert.equal(ui.app.session.draft.my.received_damage,127);
});
test("round UI records the three requested core magics and separates own exact HP from opponent percent HP",()=>{
  const s=observedSession();s.rounds=[];s.draft={my:{active_member_id:"my",kind:"charge",core_magic_id:104001,remaining_hp_exact:395,max_hp_exact:500},opponent:{active_member_id:"opp",kind:"charge",core_magic_id:104007,remaining_hp_percent:79}};const {ui,get}=uiHarness(s);ui.renderAction("my");ui.renderAction("opponent");
  for(const side of ["my","opponent"]){const text=get(side+"-action").textContent;assert.match(text,/光合治愈/);assert.match(text,/愿力强化/);assert.match(text,/进化之力/);}assert.match(get("my-action").textContent,/剩余血量.*总血量/);assert.doesNotMatch(get("my-action").textContent,/剩余血量 \(%\)/);assert.match(get("opponent-action").textContent,/剩余血量 \(%\)/);
  ui.record();const round=ui.app.session.rounds[0];assert.equal(round.my.core_magic_id,104001);assert.equal(round.opponent.core_magic_id,104007);assert.match(ui.actionLabel(round.my),/核心魔法 光合治愈.*395 \/ 500/);assert.match(ui.actionLabel(round.opponent),/核心魔法 进化之力.*79%/);ui.renderTeam("my");ui.renderTeam("opponent");assert.match(get("my-team").textContent,/395 \/ 500 · 79%/);assert.match(get("opponent-team").textContent,/79%/);assert.doesNotThrow(()=>api.create(catalog()).session(plain(ui.app.session)));
  ui.undo();assert.equal(ui.app.session.draft.my.core_magic_id,104001);assert.equal(ui.app.session.draft.my.remaining_hp_exact,395);assert.equal(ui.app.session.draft.my.max_hp_exact,500);
});
test("configured own talents and nature show exact HP with percent and supply the round maximum",()=>{
  const c=catalog();c.forms[0].stats={hp:105};c.forms[1].stats={hp:80};const d=api.create(c),selection={selected:["hp","patk","spd"],values:{hp:10,patk:10,spd:10},value_sources:{hp:"user_default",patk:"user_default",spd:"user_default"},selection_source:"user_selected",default_value:10};
  const mine=d.member({member_id:"my",form_id:100,nature_id:22,nature_modifiers:{up_id:0,down_id:0},talent_selection:selection,move_ids:[7]} ,"my",0),s=session(mine);s.teams.opponent=[d.member({member_id:"opp",form_id:101,nature_id:null,move_ids:[7]},"opponent",0)];s.draft=d.draft({my:{active_member_id:"my",kind:"charge"},opponent:{active_member_id:"opp",kind:"charge"}},s.teams);
  assert.equal(api.configuredMaxHp(mine,c.forms[0],d.natures),400);const {ui,get}=uiHarness(s,c);ui.renderTeam("my");ui.renderTeam("opponent");assert.match(get("my-team").textContent,/400 \/ 400 · 100%/);assert.doesNotMatch(get("opponent-team").textContent,/\d+ \/ \d+/);
  ui.renderAction("my");const inputs=get("my-action").querySelectorAll("input").filter(n=>n.type==="number");assert.equal(inputs[2].value,400);inputs[1].value="395";inputs[1].oninput();ui.record();assert.equal(ui.app.session.rounds[0].my.remaining_hp_exact,395);assert.equal(ui.app.session.rounds[0].my.max_hp_exact,400);ui.renderTeam("my");assert.match(get("my-team").textContent,/395 \/ 400 · 99%/);
});
test("explicit gain and loss directions replace the nature-name field and calculate exact HP",()=>{
  const c=catalog();c.forms[0].stats={hp:105};const d=api.create(c),selection={selected:["hp","patk","spd"],values:{hp:10,patk:10,spd:10},value_sources:{hp:"user_default",patk:"user_default",spd:"user_default"},selection_source:"user_selected",default_value:10};
  const member=d.member({member_id:"my",form_id:100,nature_id:null,nature_modifiers:{up_id:1,down_id:6},talent_selection:selection,move_ids:[7],confirmed:{nature:true,talents:Object.fromEntries(dims.map(x=>[x,false])),moves:[7]}} ,"my",0);
  assert.equal(api.configuredMaxHp(member,c.forms[0],d.natures),460);assert.doesNotMatch(fs.readFileSync(path.join(root,"web/battle_workspace.html"),"utf8"),/id="editor-nature"/);
  const {ui,get}=uiHarness(session(member),c);ui.openEditor("my","my");assert.match(get("editor-summary").textContent,/当前生命具体数值.*460/);assert.equal(get("editor-modifier-up_id").value,1);assert.equal(get("editor-modifier-down_id").value,6);
});
test("manual exact HP reverse-fill locks the uniquely determined directions and HP talent state",()=>{
  const c=catalog();c.forms[0].stats={hp:105};const d=api.create(c),selection={selected:["patk","matk","spd"],values:{patk:10,matk:10,spd:10},value_sources:{patk:"user_default",matk:"user_default",spd:"user_default"},selection_source:"user_selected",default_value:10};
  const member=d.member({member_id:"my",form_id:100,nature_id:null,nature_modifiers:{up_id:1,down_id:6},talent_selection:selection,move_ids:[7]},"my",0),expected=api.configuredMaxHp(member,c.forms[0],d.natures),h=uiHarness(session(member),c);h.ui.openEditor("my","my");const hpInput=h.get("editor-summary").querySelectorAll("input").find(x=>x.attributes["aria-label"]==="当前生命具体数值");hpInput.value=String(expected);hpInput.oninput();
  assert.deepEqual(plain(h.ui.editor.hp_constraint),{up_id:1,down_id:6,hp_selected:false,hp_value:null});assert.equal(h.get("editor-modifier-up_id").disabled,true);assert.equal(h.get("editor-modifier-down_id").disabled,true);const hpCheck=h.get("editor-talents").children[0].querySelectorAll("input").find(x=>x.type==="checkbox");assert.equal(hpCheck.checked,false);assert.equal(hpCheck.disabled,true);
  const ambiguous=api.reverseHpConfigurations(api.hpPanel(105,0,"patk","matk"),c.forms[0],{selected:[],values:{}},{});assert.ok(ambiguous.length>1);assert.ok(ambiguous.some(x=>x.hp_talent_selected===false));assert.ok(ambiguous.some(x=>x.hp_talent_selected===true&&x.hp_talent_value===0));
});
test("opponent card lists every damage-compatible nature and talent value group without invented probabilities",()=>{
  const s=observedSession(),{ui,get}=uiHarness(s);ui.setDamageInference({blockers:[],members:[{member_id:"opp",status:"ready",combination_count:3,observations:[{turn:1,move_name:"虹光冲击",role:"attacker",dimension:"matk",observed_damage:88}],groups:[{nature_id:2,nature_name:"固执",talent_value_options:{matk:[6,7]},combination_count:2},{nature_id:22,nature_name:"胆小",talent_value_options:{matk:[4]},combination_count:1}]}]});ui.renderTeam("opponent");const text=get("opponent-team").textContent;assert.match(text,/伤害反推 · 3 种可能组合/);assert.match(text,/固执：魔攻 6 \/ 7/);assert.match(text,/胆小：魔攻 4/);assert.match(text,/不虚构概率/);
});
test("input events immediately synchronize both sides before submit without needing change or blur",()=>{
  const s=observedSession();s.rounds=[];s.draft={my:{active_member_id:"my",kind:"charge"},opponent:{active_member_id:"opp",kind:"charge"}};const {ui,get}=uiHarness(s);
  ui.renderAction("my");let inputs=get("my-action").querySelectorAll("input").filter(n=>n.type==="number");for(const [input,value] of [[inputs[0],"38"],[inputs[1],"360"],[inputs[2],"500"]]){input.reportValidity=()=>{throw Error("input must not show a validation popup");};input.value=value;input.oninput();}assert.equal(ui.app.session.draft.my.received_damage,38);assert.equal(ui.app.session.draft.my.remaining_hp_exact,360);assert.equal(ui.app.session.draft.my.max_hp_exact,500);
  ui.renderAction("opponent");inputs=get("opponent-action").querySelectorAll("input").filter(n=>n.type==="number");for(const [input,value] of [[inputs[0],"18"],[inputs[1],"79"]]){input.reportValidity=()=>{throw Error("input must not show a validation popup");};input.value=value;input.oninput();}assert.equal(ui.app.session.draft.opponent.received_damage,18);assert.equal(ui.app.session.draft.opponent.remaining_hp_percent,79);
  ui.record();assert.equal(ui.app.session.rounds[0].my.received_damage,38);assert.equal(ui.app.session.rounds[0].my.remaining_hp_exact,360);assert.equal(ui.app.session.rounds[0].my.max_hp_exact,500);assert.equal(ui.app.session.rounds[0].opponent.received_damage,18);assert.equal(ui.app.session.rounds[0].opponent.remaining_hp_percent,79);assert.match(ui.actionLabel(ui.app.session.rounds[0].my),/38.*360 \/ 500/);
});
test("input synchronization ignores invalid interim numeric values and supports clearing an observation",()=>{
  const s=observedSession();s.draft={my:{active_member_id:"my",kind:"charge"},opponent:{active_member_id:"opp",kind:"charge",received_damage:38,remaining_hp_percent:72}};const {ui,get}=uiHarness(s);ui.renderAction("opponent");const [damage,hp]=get("opponent-action").querySelectorAll("input").filter(n=>n.type==="number");damage.value="1.5";damage.oninput();hp.value="101";hp.oninput();assert.equal(ui.app.session.draft.opponent.received_damage,38);assert.equal(ui.app.session.draft.opponent.remaining_hp_percent,72);damage.value="";damage.oninput();hp.value="0.125";hp.oninput();assert.equal(ui.app.session.draft.opponent.received_damage,null);assert.equal(ui.app.session.draft.opponent.remaining_hp_percent,72);hp.value="0";hp.oninput();assert.equal(ui.app.session.draft.opponent.remaining_hp_percent,0);
});
test("new HP input accepts only integer boundaries while legacy fractional observations migrate losslessly",()=>{
  for(const value of [0,1,99,100,null])assert.equal(api.hpPercent(value),value);
  for(const value of [-1,101,.5,72.5,NaN,Infinity,"72"])assert.throws(()=>api.hpPercent(value),/整数/);
  const d=api.create(catalog()),s=observedSession(38,72.5);s.draft={my:{active_member_id:"my",remaining_hp_percent:23.75},opponent:{}};
  const migrated=d.session(s),again=d.session(plain(migrated));assert.equal(again.rounds[0].my.remaining_hp_percent,null);assert.equal(again.rounds[0].my.legacy_remaining_hp_percent,72.5);assert.equal(again.draft.my.remaining_hp_percent,null);assert.equal(again.draft.my.legacy_remaining_hp_percent,23.75);
  assert.deepEqual(plain(api.latestHpObservations(again,"my").get("my")),{value:null,status:"needs_confirmation",turn:1});
  const {ui,get}=uiHarness(s);ui.renderAction("my");ui.renderTeam("my");assert.match(ui.actionLabel(ui.app.session.rounds[0].my),/待重新确认/);assert.doesNotMatch(ui.actionLabel(ui.app.session.rounds[0].my),/72\.5/);assert.doesNotMatch(get("my-action").textContent,/23\.75/);assert.match(get("my-team").textContent,/血量待重新确认/);assert.doesNotMatch(get("my-team").textContent,/72\.5/);
});
test("HP observations are isolated by member ID and side, and newer legacy evidence invalidates an older integer",()=>{
  const rounds=[{turn:1,my:{member_id:"a",kind:"charge",remaining_hp_percent:100},opponent:{member_id:"enemy",kind:"charge",remaining_hp_percent:90}},{turn:2,my:{member_id:"b",kind:"charge",remaining_hp_percent:60}},{turn:3,my:{member_id:"a",kind:"charge",remaining_hp_percent:null,received_damage:999}},{turn:4,my:{member_id:"b",kind:"charge",remaining_hp_percent:0}}];
  let own=api.latestHpObservations({rounds},"my");assert.equal(own.get("a").value,100);assert.equal(own.get("a").turn,1);assert.equal(own.get("b").value,0);assert.equal(own.has("enemy"),false);assert.equal(api.latestHpObservations({rounds},"opponent").get("enemy").value,90);
  rounds.push({turn:5,my:{member_id:"a",kind:"charge",remaining_hp:null,legacy_remaining_hp_percent:72.5}});own=api.latestHpObservations({rounds},"my");assert.equal(own.get("a").status,"needs_confirmation");assert.equal(own.get("a").turn,5);
  rounds.push({turn:6,my:{member_id:"b",kind:"charge",remaining_hp:150}});assert.equal(api.latestHpObservations({rounds},"my").get("b").status,"needs_confirmation");
});
test("switch HP belongs to the incoming member; switching back and undo preserve each member's last observation",()=>{
  const d=api.create(catalog()),s=observedSession(0,72);s.teams.my.push(d.member({member_id:"my2",form_id:101,nature_id:null,move_ids:[7]},"my",1));s.draft={my:{active_member_id:"my",kind:"switch",target_member_id:"my2",remaining_hp_exact:40,max_hp_exact:100},opponent:{active_member_id:"opp",kind:"charge",remaining_hp_percent:90}};
  const {ui,get}=uiHarness(s);ui.renderAction("my");assert.match(get("my-action").textContent,/换入后剩余血量.*总血量/);ui.record();let action=ui.app.session.rounds.at(-1).my;assert.equal(action.member_id,"my");assert.equal(action.hp_observed_member_id,"my2");assert.equal(action.target_member_id,"my2");assert.match(ui.actionLabel(action),/换入血量 40 \/ 100/);
  let observations=api.latestHpObservations(ui.app.session,"my");assert.equal(observations.get("my").value,72);assert.equal(observations.get("my2").value,40);assert.equal(api.latestHpObservations(ui.app.session,"opponent").get("opp").value,90);
  Object.assign(ui.app.session.draft.my,{kind:"switch",target_member_id:"my",remaining_hp_exact:30,max_hp_exact:100});ui.record();assert.equal(api.latestHpObservations(ui.app.session,"my").get("my").value,30);assert.equal(api.latestHpObservations(ui.app.session,"my").get("my2").value,40);
  ui.undo();observations=api.latestHpObservations(ui.app.session,"my");assert.equal(observations.get("my").value,72);assert.equal(observations.get("my2").value,40);ui.undo();observations=api.latestHpObservations(ui.app.session,"my");assert.equal(observations.get("my").value,72);assert.equal(observations.has("my2"),false);
  ui.renderTeam("my");const cards=get("my-team").children;assert.match(cards[0].textContent,/72%.*最近记录 · 第 1 回合/);assert.match(cards[1].textContent,/血量未知/);assert.equal(cards[0].children[1].children[1].attributes["aria-valuenow"],"72");assert.equal(cards[1].children[1].children[1].attributes["aria-valuenow"],undefined);
});
test("legacy switch HP with no attribution never guesses either member, including undo and re-record",()=>{
  const d=api.create(catalog()),s=observedSession(0,72);s.teams.my.push(d.member({member_id:"my2",form_id:101,nature_id:null,move_ids:[7]},"my",1));Object.assign(s.rounds[0].my,{kind:"switch",target_member_id:"my2",target_form_id:101,target_slot:1,remaining_hp_percent:40});
  const saved=d.session(s);assert.equal(api.latestHpObservations(saved,"my").size,0);const {ui}=uiHarness(saved);assert.match(ui.actionLabel(ui.app.session.rounds[0].my),/归属待确认/);ui.undo();assert.equal(ui.app.session.draft.my.hp_observed_member_id,null);ui.record();assert.equal(ui.app.session.rounds[0].my.hp_observed_member_id,undefined);assert.equal(api.latestHpObservations(ui.app.session,"my").get("my").value,100);assert.equal(api.latestHpObservations(ui.app.session,"my").get("my2").value,100);
  const bad=plain(saved);bad.rounds[0].my.hp_observed_member_id="opp";assert.throws(()=>d.session(bad),/血量观测成员/);
});
test("all cards have HP tracks, drafts do not change them, and new matches and templates contain no battle HP",()=>{
  const s=observedSession(38,72),{ui,get}=uiHarness(s);ui.renderTeam("my");ui.renderTeam("opponent");assert.equal(get("my-team").children[0].children[1].children[1].attributes["aria-valuenow"],"72");assert.match(get("opponent-team").children[0].textContent,/血量未知/);
  Object.assign(ui.app.session.draft.my,{active_member_id:"my",kind:"charge",remaining_hp_percent:1});ui.renderTeam("my");assert.equal(get("my-team").children[0].children[1].children[1].attributes["aria-valuenow"],"72");
  const template={id:"no-battle-hp",name:"阵容",team:plain(ui.app.session.teams.my),snapshot_id:"fixture-v1",updated_at:"2026-10-25"};const saved=api.create(catalog()).storage({storage_version:2,session:ui.app.session,templates:[template],active_template_id:template.id});assert.doesNotMatch(JSON.stringify(saved.templates),/remaining_hp|hp_observed_member_id|legacy_remaining/);
  ui.app.session=ui.fresh(ui.app.session.teams.my);assert.equal(api.latestHpObservations(ui.app.session,"my").get("my").value,100);ui.renderTeam("my");assert.match(get("my-team").children[0].textContent,/开局满血/);assert.equal(get("my-team").children[0].children[1].children[1].attributes["aria-valuenow"],"100");
});
test("changing the HP subject clears only the draft observation instead of attaching it to another member",()=>{
  const d=api.create(catalog()),s=observedSession(0,72);s.teams.my.push(d.member({member_id:"my2",form_id:101,nature_id:null,move_ids:[7]},"my",1));s.draft={my:{active_member_id:"my",kind:"switch",target_member_id:"my2",remaining_hp_percent:40,hp_observed_member_id:"my2"},opponent:{}};
  const {ui,get}=uiHarness(s);ui.renderAction("my");const current=get("my-action").querySelectorAll("select")[0];current.value="my2";current.onchange();assert.equal(ui.app.session.draft.my.remaining_hp_percent,null);assert.equal(ui.app.session.draft.my.hp_observed_member_id,undefined);assert.equal(api.latestHpObservations(ui.app.session,"my").get("my").value,72);
  Object.assign(ui.app.session.draft.my,{kind:"switch",target_member_id:"my",remaining_hp_percent:30});ui.renderAction("my");const kind=get("my-action").querySelectorAll("select")[1];kind.value="charge";kind.onchange();assert.equal(ui.app.session.draft.my.remaining_hp_percent,null);
});
const completeCatalog=()=>{const c=catalog();for(const id of [9,10,11,7020840,7020850,7020860])c.moves[id]={id,name:{zh:"技能"+id}};c.details[100].learnset.pool=[7,8,9,10,11,7020840,7020850,7020860];c.action_mechanics={generators:{7020840:{kind:"borrow"},7020850:{kind:"mind_read"},7020860:{kind:"rewrite"}},transformations:{},weather:{},response_energy:{}};return c;};
test("imported unconfirmed own four slots stay narrow even with stale all_moves and survive reload",()=>{
  const c=completeCatalog(),d=api.create(c),r=result();r.members[0].move_ids=[10,7,9,8];const m=d.importCode(r,"my",()=>"mine")[0],s=session(m);s.draft={my:{active_member_id:"mine",all_moves:true,move_id:11},opponent:{}};
  for(const saved of [s,plain(d.session(s))]){const {ui,get}=uiHarness(saved,c);ui.renderAction("my");const controls=get("my-action").querySelectorAll("select");assert.deepEqual(controls[2].children.map(n=>n.value),["",10,7,9,8]);assert.equal(controls[2].value,"");assert.equal(get("my-action").querySelectorAll("input").filter(n=>n.type==="checkbox").length,0);assert.deepEqual(plain(ui.app.session.teams.my[0].confirmed.moves),[]);assert.throws(()=>ui.record(),/实际使用技能/);}
});
test("separate generator checkboxes use their own bounded pool and collapse to carried slots",()=>{
  for(const special of [7020840,7020850,7020860]){const c=completeCatalog(),d=api.create(c),m=d.member({member_id:"mine",form_id:100,nature_id:null,move_ids:[10,special,7,8]},"my",0),s=session(m);s.teams.my.push(d.member({member_id:"ally",form_id:100,nature_id:null,move_ids:[11]},"my",1));s.teams.opponent=[d.member({member_id:"opp",form_id:100,nature_id:null,move_ids:[7]},"opponent",0)];s.draft={my:{active_member_id:"mine",all_moves:true},opponent:{}};const {ui,get}=uiHarness(s,c);ui.renderAction("my");const ids=()=>get("my-action").querySelectorAll("select")[2].children.map(n=>n.value);assert.deepEqual(ids(),["",10,special,7,8]);let toggle=get("my-action").querySelectorAll("input").find(n=>n.type==="checkbox");assert.equal(toggle.checked,false);toggle.checked=true;toggle.onchange();assert.ok(ids().includes(11));if(special===7020840)assert.deepEqual(ids(),["",11]);if(special===7020860)assert.ok(!ids().includes(10));toggle=get("my-action").querySelectorAll("input").find(n=>n.type==="checkbox");toggle.checked=false;toggle.onchange();assert.deepEqual(ids(),["",10,special,7,8]);}
});
test("incomplete own slots show only the configured nonempty moves",()=>{
  const c=completeCatalog(),m=api.create(c).member({member_id:"mine",form_id:100,nature_id:null,move_ids:[7,0,8,0]},"my",0),s=session(m);s.draft={my:{active_member_id:"mine"},opponent:{}};const {ui,get}=uiHarness(s,c);ui.renderAction("my");assert.deepEqual(get("my-action").querySelectorAll("select")[2].children.map(n=>n.value),["",7,8]);
});
function mechanicHarness(kind){
  const c=completeCatalog();c.moves[7].kind="defense";c.moves[8].kind="physical";
  c.action_mechanics.transformations[7]=kind==="clever"?{kind:"clever_change",trigger:{event:"after_use"},pool_ids:[8,9],status:"supported",source:{fixture:true}}:{kind:"slot_replace",scope:"self_slot",trigger:{event:"response_success",response_kind:"attack"},replacement_source:"opponent_selected_skill",status:"supported"};
  const d=api.create(c),m=d.member({member_id:"mine",form_id:100,nature_id:null,move_ids:[7,9,10,11]},"my",0),s=session(m);m.confirmed.moves=[];s.teams.opponent=[d.member({member_id:"opp",form_id:100,nature_id:null,move_ids:[8]},"opponent",0)];s.draft={my:{active_member_id:"mine",kind:"move",move_id:7},opponent:{active_member_id:"opp",kind:kind==="clever"?"charge":"move",move_id:8}};return {...uiHarness(s,c),c};
}
test("own carried source is automatic without a source selector or promoting configuration certainty",()=>{
  const {ui,get}=mechanicHarness("mirror");ui.renderAction("my");assert.equal(get("my-action").querySelectorAll("select").length,4);assert.doesNotMatch(get("my-action").textContent,/技能来源：/);const action=ui.actionFromDraft("my");assert.equal(action.origin,"carried");assert.equal(action.confirmed_carried,true);assert.equal(action.generator_slot,0);assert.deepEqual(plain(ui.app.session.teams.my[0].confirmed.moves),[]);
});
test("observed response updates current four slots, persists, and undo restores slots without changing templates",()=>{
  const {ui,get,c}=mechanicHarness("mirror");ui.renderAction("my");const response=get("my-action").querySelectorAll("input").find(n=>n.type==="checkbox");response.checked=true;response.onchange();const original=plain(ui.app.session.teams.my[0]);ui.record();assert.deepEqual(plain(ui.app.session.slot_overrides.mine),[8,9,10,11]);assert.deepEqual(plain(ui.app.session.teams.my[0]),original);assert.equal(ui.app.session.rounds[0].mechanic_events[0].kind,"slot_replace");assert.deepEqual(get("my-action").querySelectorAll("select")[2].children.map(n=>n.value),["",8,9,10,11]);const loaded=api.create(c).session(plain(ui.app.session));assert.deepEqual(plain(loaded.slot_overrides.mine),[8,9,10,11]);ui.undo();assert.deepEqual(plain(ui.app.session.slot_overrides),{});assert.equal(ui.app.session.draft.my.move_id,7);assert.equal(ui.app.session.draft.my.response_success,true);
});
test("clever-change selected result uses only pending pool and returns original slot after use",()=>{
  const {ui,get,c}=mechanicHarness("clever");ui.record();assert.equal(ui.app.session.pending_transforms.mine[0].base_id,7);assert.ok(!get("my-action").querySelectorAll("select")[2].children.some(n=>n.value===7));const toggle=get("my-action").querySelectorAll("input").find(n=>n.type==="checkbox");toggle.checked=true;toggle.onchange();let choose=get("my-action").querySelectorAll("select")[2];assert.deepEqual(choose.children.map(n=>n.value),["",8,9]);choose.value=8;choose.onchange();ui.record();assert.equal(ui.app.session.pending_transforms.mine,undefined);assert.equal(ui.app.session.slot_overrides.mine[0],7);assert.equal(ui.app.session.rounds[1].my.origin,"generated");assert.equal(ui.app.session.rounds[1].my.generator_slot,0);assert.ok(get("my-action").querySelectorAll("select")[2].children.some(n=>n.value===7));assert.doesNotThrow(()=>api.create(c).session(plain(ui.app.session)));ui.undo();assert.equal(ui.app.session.pending_transforms.mine[0].base_id,7);assert.equal(ui.app.session.draft.my.skill_mode,"temporary");
});
test("weather UI derives readonly state and history from replay, without writing manual weather",async()=>{
  const c=completeCatalog(),s=observedSession();s.rounds=[];s.draft={weather_observation:{kind:"rain",remaining_rounds:8},my:{active_member_id:"my",kind:"charge"},opponent:{active_member_id:"opp",kind:"charge"}};
  const requests=[];const request=async(url,options)=>{const payload=JSON.parse(options.body).session;requests.push(payload);return {ok:true,json:async()=>({current:payload.rounds.length?{kind:"blizzard",remaining_rounds:7,effect_summary:["回合末叠加 2 层冻结"]}:null,frames:payload.rounds.map(r=>({event_id:r.event_id,after:{kind:"blizzard",remaining_rounds:7},events:[{op:"weather.tick",kind:"blizzard",before:8,after:7}]}))})};};
  const {ui,get}=uiHarness(s,c,request);await ui.renderWeather();assert.match(get("weather-controls").textContent,/无天气/);assert.equal(get("weather-controls").querySelectorAll("select").length,0);assert.equal(get("weather-controls").querySelectorAll("input").length,0);
  ui.record();await ui.renderWeather();assert.equal(ui.app.session.rounds[0].weather_observation,undefined);assert.match(get("weather-controls").textContent,/暴风雪.*剩余 7 回合/);assert.match(get("round-history").textContent,/8 → 7/);assert.equal(requests.filter(x=>x&&x.rounds).at(-1).rounds[0].weather_observation,undefined,"天气回放请求不应带手填天气；伤害预估请求不是天气回放");
  ui.undo();await ui.renderWeather();assert.match(get("weather-controls").textContent,/无天气/);assert.equal(ui.app.session.rounds.length,0);
});
test("old manual weather stays archived but cannot override automatic weather",async()=>{
  const s=observedSession();s.rounds[0].weather_observation={kind:"rain",remaining_rounds:8};const {ui,get}=uiHarness(s);ui.history();await ui.renderWeather();assert.match(get("round-history").textContent,/旧版手填天气（仅存档）/);assert.match(get("weather-controls").textContent,/无天气/);assert.equal(ui.app.session.rounds[0].weather_observation.kind,"rain");
});
test("opening full HP applies to both teams without overwriting old uncertain observations",()=>{
  const s=observedSession();s.rounds=[];const {ui,get}=uiHarness(s);for(const side of ["my","opponent"]){ui.renderTeam(side);assert.match(get(side+"-team").textContent,/100%.*开局满血/);}const prior=observedSession(5,72.5);assert.equal(api.latestHpObservations(prior,"my").get("my").status,"needs_confirmation");
});
test("opening energy is 10 and reviewed response energy is calculated, recorded, and displayed",()=>{
  const c=completeCatalog();c.moves[7]={id:7,name:{zh:"惊吓盒子"},energy:3,kind:"physical"};c.moves[8]={id:8,name:{zh:"力量增效"},energy:3,kind:"status"};c.details[101].learnset.pool=[8];c.action_mechanics.response_energy[7]={response_kinds:["status"],policy:"fixture",effects:[{op:"energy.reduce",target:"opponent",amount:6,event:"after.damage",when:"response.success"}]};const d=api.create(c),s=observedSession();
  s.rounds=[];s.opening_full_hp=true;s.teams.opponent[0]=d.member({member_id:"opp",form_id:101,nature_id:null,move_ids:[8]},"opponent",0);s.draft={my:{active_member_id:"my",kind:"move",move_id:7,response_success:true},opponent:{active_member_id:"opp",kind:"move",move_id:8}};
  const {ui,get}=uiHarness(s,c);ui.renderTeam("my");ui.renderTeam("opponent");assert.match(get("my-team").textContent,/100%.*能量 10\/10/);assert.match(get("opponent-team").textContent,/100%.*能量 10\/10/);ui.record();const round=ui.app.session.rounds[0];assert.equal(round.my.energy_before,10);assert.equal(round.my.remaining_energy,7);assert.equal(round.opponent.energy_before,10);assert.equal(round.opponent.remaining_energy,1);assert.deepEqual(plain(round.energy_events[0]),{source_side:"my",target_side:"opponent",skill_id:7,op:"energy.reduce",amount:6,before:7,after:1,when:"response.success",policy:"fixture"});assert.match(ui.actionLabel(round.my),/能量 10 → 7/);ui.history();assert.match(get("round-history").textContent,/惊吓盒子.*额外失去 6 能量.*7 → 1/);assert.doesNotThrow(()=>d.session(plain(ui.app.session)));
});
test("untouched opening members retain full bars after turn while reported damage without percent invalidates only that baseline",()=>{
  const c=completeCatalog(),d=api.create(c),s=observedSession();s.rounds=[];s.teams.my.push(d.member({member_id:"bench",form_id:100,nature_id:null,move_ids:[7]},"my",1));s.draft={my:{active_member_id:"my",kind:"charge",received_damage:12},opponent:{active_member_id:"opp",kind:"charge"}};const {ui}=uiHarness(s,c);ui.record();const obs=api.latestHpObservations(ui.app.session,"my");assert.equal(obs.get("bench").value,100);assert.equal(obs.get("my").status,"needs_confirmation");const loaded=d.session(plain(ui.app.session));assert.equal(api.latestHpObservations(loaded,"my").get("bench").value,100);
});
test("observing an opponent transformation without knowing its slot records evidence without inventing a slot",()=>{
  const {ui,c}=mechanicHarness("mirror");ui.app.session.teams.opponent[0].move_ids=[];ui.app.session.draft.my={active_member_id:"mine",kind:"charge"};Object.assign(ui.app.session.draft.opponent,{move_id:7,response_success:true});ui.record();assert.equal(ui.app.session.rounds[0].opponent.move_id,7);assert.equal(ui.app.session.rounds[0].opponent.generator_slot,null);assert.deepEqual(plain(ui.app.session.slot_overrides),{});assert.doesNotThrow(()=>api.create(c).session(plain(ui.app.session)));
});
test("HP-only reverse fill never offers a life-changing direction when the HP talent is already fixed",()=>{
  const c=catalog();c.forms[0].stats={hp:105};const d=api.create(c),selection={selected:["hp","patk","spd"],values:{hp:10,patk:10,spd:10},value_sources:{hp:"user_default",patk:"user_default",spd:"user_default"},selection_source:"user_selected",default_value:10};
  const member=d.member({member_id:"my",form_id:100,nature_id:null,nature_modifiers:{up_id:0,down_id:0},talent_selection:selection,move_ids:[7]},"my",0);
  const candidates=api.reverseHpConfigurations(api.hpPanel(105,10,"patk","matk"),c.forms[0],selection,{});
  assert.ok(candidates.length>1);
  for(const candidate of candidates){assert.equal(candidate.hp_talent_selected,true);assert.equal(candidate.hp_talent_value,10);assert.notEqual(api.MODIFIERS[candidate.up_id],"hp");assert.notEqual(api.MODIFIERS[candidate.down_id],"hp");}
  const {ui,get}=uiHarness(session(member),c);ui.openEditor("my","my");
  const hpInput=get("editor-summary").querySelectorAll("input").find(x=>x.attributes["aria-label"]==="当前生命具体数值");hpInput.value="400";hpInput.oninput();
  assert.equal(ui.editor.hp_constraint,null);
  const choices=get("editor-summary").children[1].children[1],picks=choices.children.filter(n=>n.tagName==="button");
  assert.ok(picks.length>1);assert.match(choices.textContent,/找到 \d+ 种相容配置/);
  assert.ok(picks.every(button=>!/生命↑|生命↓/.test(button.textContent)));
  picks[0].onclick();
  assert.equal(ui.editor.hp_constraint.hp_selected,true);assert.equal(ui.editor.hp_constraint.hp_value,10);
  assert.notEqual(api.MODIFIERS[ui.editor.hp_constraint.up_id],"hp");assert.notEqual(api.MODIFIERS[ui.editor.hp_constraint.down_id],"hp");
  const hpCheck=get("editor-talents").children[0].querySelectorAll("input").find(x=>x.type==="checkbox");
  assert.equal(hpCheck.checked,true);assert.equal(hpCheck.disabled,true);
  assert.equal(get("editor-modifier-up_id").disabled,true);assert.equal(get("editor-modifier-down_id").disabled,true);
  assert.match(get("editor-summary").textContent,/按当前增减方向与三项个体计算 · 400/);
});
test("an HP value that contradicts the fixed directions does not silently rewrite them",()=>{
  const c=catalog();c.forms[0].stats={hp:105};const d=api.create(c),selection={selected:["hp","patk","spd"],values:{hp:10,patk:10,spd:10},value_sources:{hp:"user_default",patk:"user_default",spd:"user_default"},selection_source:"user_selected",default_value:10};
  const member=d.member({member_id:"my",form_id:100,nature_id:null,nature_modifiers:{up_id:1,down_id:6},talent_selection:selection,move_ids:[7]},"my",0);
  const {ui,get}=uiHarness(session(member),c);ui.openEditor("my","my");
  const hpInput=get("editor-summary").querySelectorAll("input").find(x=>x.attributes["aria-label"]==="当前生命具体数值");hpInput.value="401";hpInput.oninput();
  assert.equal(ui.editor.hp_constraint,null);
  assert.equal(ui.editor.nature_modifiers.up_id,1);assert.equal(ui.editor.nature_modifiers.down_id,6);
  assert.equal(get("editor-modifier-up_id").disabled,false);assert.equal(get("editor-modifier-down_id").disabled,false);
  assert.equal(ui.editor.talent_selection.values.hp,10);
});
test("stored sessions keep the old duplicated-marker selection out of force after reload",()=>{
  const legacy=plain(imported());
  legacy.talent_selection={selected:["patk"],values:{patk:10},value_sources:{patk:"user_default"},selection_source:"team_code_markers",default_value:10};
  legacy.talents.patk=10;
  const migrated=api.create(catalog()).member(legacy,"opponent",0);
  assert.deepEqual(plain(migrated.talent_selection.selected),[],"旧的重复标记选择在载入时必须清空");
  assert.equal(migrated.talents.patk,10,"历史六维原值保留，不被篡改");
  const keep=plain(legacy);keep.code_provenance.original_member.raw_talent_markers=[79,81,84];keep.talent_selection={selected:["hp","matk","spd"],values:{hp:10,matk:10,spd:10},value_sources:{hp:"user_default",matk:"user_default",spd:"user_default"},selection_source:"team_code_markers",default_value:10};
  assert.deepEqual(plain(api.create(catalog()).member(keep,"opponent",0).talent_selection.selected),["hp","matk","spd"],"非重复标记的解出结果不受影响");
});
function dimoCatalog(){const c=catalog();c.forms=[{id:3004,number:"001",title:"迪莫",types:["光系"]},{id:5025,number:"001",title:"圣光迪莫"},{id:5026,number:"001",title:"圣草迪莫"},{id:5027,number:"001",title:"圣火迪莫"},{id:5028,number:"001",title:"圣水迪莫"}];c.moves[7]={id:7,name:{zh:"炎打"},energy:3};c.details={3004:{learnset:{pool:[7]}}};return c;}
function energyRound(side,member_id,form_id){return {event_id:"r-"+side,recorded_at:"2026-10-25T00:00:00Z",turn:1,note:"",[side]:{member_id,form_id,slot:0,kind:"charge",remaining_energy:10}};}
test("wish enhancement replaces the first slot with wish strike and charges its two energy",()=>{
  const c=dimoCatalog(),d=api.create(c),m=d.member({member_id:"my",form_id:3004,nature_id:null,move_ids:[7]},"my",0),o=d.member({member_id:"opp",form_id:3004,nature_id:null,move_ids:[7]},"opponent",0),s=session(m);
  s.teams.opponent=[o];s.rounds=[{...energyRound("my","my",3004),opponent:{member_id:"opp",form_id:3004,slot:0,kind:"charge",remaining_energy:10}}];
  s.draft=d.draft({my:{active_member_id:"my",kind:"move",move_id:7,core_magic_id:104002},opponent:{active_member_id:"opp",kind:"charge"}},s.teams);
  const {ui,get}=uiHarness(s,c);ui.renderAction("my");const text=get("my-action").textContent;
  assert.match(text,/首槽替换为【愿力冲击】/);assert.match(text,/威力 80 \/ 能耗 2 \/ 优先级 5/);assert.match(text,/原首槽 炎打/);
  assert.match(text,/本回合替换/);
  ui.record();const a=ui.app.session.rounds.at(-1).my;
  assert.equal(a.first_slot_replaced.name,"愿力冲击");assert.equal(a.first_slot_replaced.power,80);assert.equal(a.first_slot_replaced.original_first_slot,7);assert.equal(a.first_slot_replaced.variant_resolved,false);
  assert.equal(a.remaining_energy,8,"按愿力冲击 2 费计，而不是原技能炎打的 3 费");
  assert.match(ui.actionLabel(a),/首槽替换为 愿力冲击（威力 80 · 能耗 2）/);
});
test("evolution magic lists same-number forms and the dimo exception also replaces the first slot",()=>{
  const c=dimoCatalog(),d=api.create(c),m=d.member({member_id:"my",form_id:3004,nature_id:null,move_ids:[7]},"my",0),o=d.member({member_id:"opp",form_id:3004,nature_id:null,move_ids:[7]},"opponent",0),s=session(m);
  s.teams.opponent=[o];
  s.draft=d.draft({my:{active_member_id:"my",kind:"charge",core_magic_id:104007,evolution_target_form_id:5025},opponent:{active_member_id:"opp",kind:"charge"}},s.teams);
  const {ui,get}=uiHarness(s,c);ui.renderAction("my");
  const picks=get("my-action").querySelectorAll("select").map(n=>n.children.map(c=>String(c.value))).find(values=>values.includes("5025"));
  assert.ok(picks,"进化形态候选必须包含圣光迪莫 · 实际渲染："+get("my-action").textContent);assert.ok(picks.includes("5028"));
  assert.match(get("my-action").textContent,/首槽替换为【愿力冲击】/);assert.match(get("my-action").textContent,/用户口径/);
  ui.record();const a=ui.app.session.rounds.at(-1).my;
  assert.equal(a.evolution_target_form_id,5025);assert.equal(a.core_magic_id,104007);assert.equal(a.first_slot_replaced.user_note,true);
  assert.match(ui.actionLabel(a),/进化形态 圣光迪莫/);
  assert.equal(a.first_slot_replaced.original_first_slot,7,"迪莫例外同样保留原首槽");
  assert.throws(()=>d.session({...session(m),rounds:[{event_id:"r9",recorded_at:"2026-10-25T00:00:00Z",turn:1,note:"",my:{member_id:"my",form_id:3004,slot:0,kind:"charge",core_magic_id:104002,evolution_target_form_id:5025},opponent:null}]}),/进化形态只能随进化之力记录/);
});
test("team cards carry a bloodline badge and the manual after-action energy input is gone",()=>{
  const c=dimoCatalog(),d=api.create(c);
  const mine=d.member({member_id:"my",form_id:3004,nature_id:null,bloodline_id:19,move_ids:[7]},"my",0),other=d.member({member_id:"opp",form_id:3004,nature_id:null,move_ids:[7]},"opponent",0),s=session(mine);
  s.teams.opponent=[other];s.draft=d.draft({my:{active_member_id:"my",kind:"move",move_id:7},opponent:{active_member_id:"opp",kind:"move",move_id:7}},s.teams);
  const {ui,get}=uiHarness(s,c);ui.renderTeam("my");ui.renderTeam("opponent");
  const filled=get("my-team").querySelectorAll("span").filter(n=>n.attributes?.title?.startsWith("血脉 "));
  assert.equal(filled.length,1);assert.match(filled[0].textContent,/首领/);assert.match(filled[0].attributes.style,/background:/);
  const empty=get("opponent-team").querySelectorAll("span").filter(n=>n.attributes?.title==="尚未填写血脉");
  assert.equal(empty.length,1);assert.match(empty[0].textContent,/血脉未填/);
  assert.doesNotMatch(get("opponent-team").textContent,/血脉（/,"血脉不再作为回退文字重复出现");
  ui.renderAction("my");ui.renderAction("opponent");
  assert.equal(get("my-action").querySelectorAll("input").filter(n=>n.type==="number").length,3,"我方只有伤害、剩余血量、总血量");
  assert.equal(get("opponent-action").querySelectorAll("input").filter(n=>n.type==="number").length,2,"对方只有伤害与血量百分比");
  assert.doesNotMatch(get("my-action").textContent,/行动后能量/);assert.doesNotMatch(get("opponent-action").textContent,/行动后能量/);
});

test("the workbench exposes a naked damage preview right below the advice card",()=>{
  const html=fs.readFileSync(path.join(root,"web/battle_workspace.html"),"utf8");
  const js=fs.readFileSync(path.join(root,"web/battle.js"),"utf8");
  assert.match(html,/id="preview-panel"/);
  assert.ok(html.indexOf('id="preview-panel"')>html.indexOf('id="advice-content"'),"preview sits below the advice card");
  assert.ok(html.indexOf('id="preview-panel"')<html.indexOf('class="panel record-panel"'),"preview sits above the round recorder");
  assert.match(html,/防御减伤请按/);
  assert.match(js,/\/api\/preview\/damage/);
  assert.match(js,/refreshAdvice\(\);refreshPreview\(\);/);
  assert.match(js,/active_slot:slots/);
  assert.match(html,/连击按段数逐段取整后求和/,"panel states the multi-hit policy");
  assert.match(js,/hit_count/,"preview row reads the hit count");
  assert.match(js,/pr-hits/,"preview row shows the per-hit split");
  assert.ok(!/remaining_energy/.test(js.slice(js.indexOf("function previewPayload"),js.indexOf("function previewPercent"))),"preview must not reuse the removed manual energy input");
});
test("the preview panel renders the per-hit split of a multi-hit skill",async()=>{
  const c=catalog();c.moves[12]={id:12,name:{zh:"旋转突击"},kind:"physical",power:35,energy:2};c.details[100]={learnset:{pool:[12]}};
  const m=api.create(c).member({member_id:"my",form_id:100,nature_id:null,move_ids:[12,0,0,0]},"my",0);
  const s=session(m);s.teams.opponent=[{...plain(m),member_id:"opp"}];
  s.draft={my:{active_member_id:"my",all_moves:true,kind:"charge"},opponent:{active_member_id:"opp",all_moves:true,kind:"charge"}};
  const hit={nominal_damage:19,applied:19,index:0};
  const preview={attacker:{name:"测试形态",hp:400,max_hp:400,energy:10,max_energy:30},defender:{name:"测试形态",hp:332,max_hp:332},
    results:[{slot:0,name:"旋转突击",type:"普通系",kind:"physical",power:35,energy_cost:2,hit_count:3,hit_count_source:"wiki_desc_parsed",
      per_hit_power:11.666666666666666,per_hit_damage:19,hits_executed:3,hits_detail:[hit,hit,hit],damage:57,applied_damage:57,
      defender_hp_before:332,defender_hp_after:275,defender_hp_after_percent:82.8,lethal:false,affordable:true,
      type_multiplier:{numerator:1,denominator:1},same_type_bonus:1}],non_damage_slots:[],blocked_slots:[],warnings:[],excluded_effects:[]};
  const {ui,get}=uiHarness(s,c,async url=>({ok:true,json:async()=>String(url).includes("preview/damage")?preview:{current:null,frames:[]}}));
  await ui.refreshPreview();
  const text=get("preview-content").textContent;
  assert.match(text,/3 连击/,"meta line names the hit count");
  assert.match(text,/→ 伤害 57/);
  assert.match(text,/3 × 每段 19/,"per-hit split is shown next to the total");
  assert.match(text,/对方剩 275\/332/);
  assert.equal(get("preview-badge").textContent,"裸伤害 · 未校准");
});
test("the preview forwards the manual stat terms and shows the scaled panel",async()=>{
  const c=catalog();c.moves[12]={id:12,name:{zh:"旋转突击"},kind:"physical",power:35,energy:2};c.details[100]={learnset:{pool:[12]}};
  const m=api.create(c).member({member_id:"my",form_id:100,nature_id:null,move_ids:[12,0,0,0]},"my",0);
  const s=session(m);s.teams.opponent=[{...plain(m),member_id:"opp"}];
  s.draft={my:{active_member_id:"my",all_moves:true,kind:"charge"},opponent:{active_member_id:"opp",all_moves:true,kind:"charge"}};
  const preview={attacker:{name:"测试形态",hp:400,max_hp:400,energy:10,max_energy:30},defender:{name:"测试形态",hp:332,max_hp:332},
    results:[{slot:0,name:"旋转突击",type:"普通系",kind:"physical",power:35,energy_cost:2,hit_count:1,hit_count_source:"single_hit_default",
      per_hit_power:35,per_hit_damage:38,hits_executed:1,hits_detail:[{nominal_damage:38,applied:38,index:0}],damage:38,applied_damage:38,
      defender_hp_before:332,defender_hp_after:294,defender_hp_after_percent:88.6,lethal:false,affordable:true,
      attack_stat:"patk",attack_panel:414,attack_panel_base:207,attack_stat_modifier_percent:100,
      defense_stat:"pdef",defense_panel:166,defense_panel_base:166,defense_stat_modifier_percent:null,
      type_multiplier:{numerator:1,denominator:1},same_type_bonus:1}],non_damage_slots:[],blocked_slots:[],warnings:[],excluded_effects:[]};
  const calls=[];
  const {ui,get}=uiHarness(s,c,async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>String(url).includes("preview/damage")?preview:{current:null,frames:[]}};});
  get("preview-my-patk").value="100";
  get("preview-opp-mdef").value="";
  await ui.refreshPreview();
  const text=get("preview-content").textContent;
  assert.match(text,/攻面板 207→414/,"the scaled panel is named next to the damage");
  const body=JSON.parse(calls.at(-1).options.body);
  assert.deepEqual(body.stat_terms,{a:{patk:100}},"only filled fields are sent");
  get("preview-my-patk").value="";
  get("preview-opp-pdef").value="-30";
  await ui.refreshPreview();
  assert.deepEqual(JSON.parse(calls.at(-1).options.body).stat_terms,{b:{pdef:-30}});
});