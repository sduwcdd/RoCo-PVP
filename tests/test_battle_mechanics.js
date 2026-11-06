"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const api = require("../web/battle_mechanics.js");
const clone = x => JSON.parse(JSON.stringify(x));
function fixture() {
  const all = [1,2,3,4,5,6,7,8,9,10,7020840,7020850,7020860,7021220,7090440,7060150,7060260,7060230];
  const catalog = {snapshot_id:"fixture",moves:Object.fromEntries(all.map(id => [id,{id,kind:id===4?"status":"physical"}])),details:{100:{learnset:{pool:[1,2,3,4,5],native:[{move:6}],stones:[{move:7}],legacy:[{move:8}],legendary:[{move:9}]}},101:{learnset:{pool:[4,10]}}}};
  const metadata = {generators:Object.fromEntries(Object.entries({borrow:7020840,mind_read:7020850,rewrite:7020860}).map(([kind,id])=>[id,{kind,source:{fixture:true}}])),transformations:{7021220:{kind:"clever_change",scope:"catalog_filtered",trigger:{event:"after_use"},pool_ids:[3,4],source:{url:"fixture-source"},uncertainty:["候选而非精确池"]},7090440:{kind:"clever_change",trigger:{event:"after_use"},pool_ids:[],status:"blocked",blockers:["冻结候选缺证"]},7060150:{kind:"slot_replace",scope:"self_slot",replacement_source:"opponent_selected_skill",trigger:{event:"response_success",response_kind:"attack",choice_required:false}},7060260:{kind:"slot_replace",scope:"opponent_slot",replacement_id:7060230,trigger:{event:"response_success",response_kind:"status",choice_required:true}}}};
  const session = {teams:{my:[{member_id:"m",form_id:100,move_ids:[7020840,7020850,7020860,1]},{member_id:"ally",form_id:101,move_ids:[2,3,0,0]}],opponent:[{member_id:"o",form_id:101,move_ids:[4,5,6,0]}]},slot_overrides:{},pending_transforms:{}};
  return {catalog,metadata,session};
}
const action = (id,slot=0,extra={}) => ({kind:"move",member_id:"m",move_id:id,generator_slot:slot,skill_mode:"carried",...extra});
function apply(f,my,opponent) { return api.applyRound(f.session,{my,opponent},f.metadata,f.catalog); }
test("three generator pools have distinct scope and require the current carried source",()=>{
  const f=fixture(),m=f.session.teams.my[0],pool=mode=>api.getPool(f.catalog,f.metadata,f.session,"my",m,mode);
  assert.deepEqual(pool("borrow").ids,[2,3]);
  assert.deepEqual(pool("mind_read").ids,[4,10]);
  assert.deepEqual(pool("rewrite").ids,[2,3,4,5,6,7,8,9]);
  f.session.slot_overrides.m=[1,2,3,4];assert.equal(pool("borrow").ids.length,0);assert.match(pool("borrow").blockers.join(),/没有携带/);
  assert.equal(pool("made_up").ids.length,0);
});
test("borrow uses teammates' current replacements and the actor is excluded",()=>{
  const f=fixture();f.session.slot_overrides.ally=[5,6,0,0];assert.deepEqual(api.getPool(f.catalog,f.metadata,f.session,"my",f.session.teams.my[0],"borrow").ids,[5,6]);
  const slots=api.currentMoves(f.session,f.session.teams.my[1]);slots[0]=99;assert.equal(f.session.slot_overrides.ally[0],5);
});
test("clever change records the exact slot, retains original configuration and restores after temporary use",()=>{
  const f=fixture();f.session.teams.my[0].move_ids=[1,0,7021220,2];const before=clone(f.session);
  let out=apply(f,action(7021220,2));assert.deepEqual(f.session,before);assert.equal(out.pending_transforms.m[2].base_id,7021220);assert.equal(out.pending_transforms.m[2].source.url,"fixture-source");assert.deepEqual(out.pending_transforms.m[2].uncertainty,["候选而非精确池"]);
  f.session={...f.session,...out};let pool=api.getPool(f.catalog,f.metadata,f.session,"my",f.session.teams.my[0],"carried");assert.deepEqual(pool.ids,[1,2]);
  assert.deepEqual(api.getPool(f.catalog,f.metadata,f.session,"my",f.session.teams.my[0],"temporary",2).ids,[3,4]);
  out=apply(f,action(3,2,{skill_mode:"temporary"}));assert.deepEqual(out.slot_overrides.m,[1,0,7021220,2]);assert.deepEqual(out.pending_transforms,{});assert.deepEqual(f.session.teams.my[0].move_ids,before.teams.my[0].move_ids);
});
test("blocked clever change remains pending without opening the whole catalog",()=>{
  const f=fixture();f.session.teams.my[0].move_ids=[7090440,0,0,0];const out=apply(f,action(7090440));f.session={...f.session,...out};
  const p=api.getPool(f.catalog,f.metadata,f.session,"my",f.session.teams.my[0],"temporary");assert.deepEqual(p.ids,[]);assert.match(p.blockers.join(),/冻结/);assert.ok(out.pending_transforms.m[0]);assert.deepEqual(api.getPool(f.catalog,f.metadata,f.session,"my",f.session.teams.my[0],"carried").ids,[]);
});
test("mirror needs observed response success and validates the target category",()=>{
  const f=fixture();f.session.teams.my[0].move_ids=[0,7060150,1,2];const other=action(5,1,{member_id:"o"});
  let out=apply(f,action(7060150,1),other);assert.deepEqual(out.slot_overrides,{});assert.match(out.warnings.join(),/应对成功/);
  out=apply(f,action(7060150,1,{response_success:true}),other);assert.deepEqual(out.slot_overrides.m,[0,5,1,2]);
  out=apply(f,action(7060150,1,{response_success:true}),{...other,move_id:4});assert.deepEqual(out.slot_overrides,{});assert.match(out.warnings.join(),/类别/);
});
test("lens response requires the chosen response branch, and replaces the opponent's exact slot",()=>{
  const f=fixture();f.session.teams.my[0].move_ids=[7060260,0,1,2];const other=action(4,0,{member_id:"o"});
  let out=apply(f,action(7060260,0,{response_success:true}),other);assert.deepEqual(out.slot_overrides,{});
  out=apply(f,action(7060260,0,{response_success:true,response_choice:true}),other);assert.deepEqual(out.slot_overrides.o,[7060230,5,6,0]);
  out=apply(f,action(7060260,0,{response_success:true,response_choice:true}),{...other,generator_slot:undefined});assert.deepEqual(out.slot_overrides,{});assert.match(out.warnings.join(),/来源技能槽/);
});
test("missing source slots and repeated source IDs do not guess lifecycle",()=>{
  const f=fixture();f.session.teams.my[0].move_ids=[7021220,7021220,1,0];let out=apply(f,action(7021220));assert.deepEqual(out.pending_transforms,{});assert.match(out.warnings.join(),/多个技能槽/);
  f.session.teams.my[0].move_ids=[7021220,0,1,0];out=apply(f,action(7021220,0,{generator_slot:undefined}));assert.deepEqual(out.pending_transforms,{});assert.match(out.warnings.join(),/来源技能槽/);
});
test("randomly generated transformations never replace generator bodies",()=>{
  const f=fixture();f.session.slot_overrides.ally=[7021220,1,0,0];const out=apply(f,action(7021220,0,{skill_mode:"borrow"}));assert.deepEqual(out.slot_overrides,f.session.slot_overrides);assert.deepEqual(out.pending_transforms,{});assert.match(out.warnings.join(),/无法可靠定位/);
});
test("temporary selection requires its exact origin and rejects nested transformations",()=>{
  const f=fixture();f.session.teams.my[0].move_ids=[7021220,1,0,0];f.session.pending_transforms={m:{0:{base_id:7021220,pool_ids:[3,7021220]}}};
  let out=apply(f,action(3,0,{skill_mode:"temporary",generator_slot:undefined}));assert.ok(out.pending_transforms.m[0]);assert.match(out.warnings.join(),/来源槽/);
  out=apply(f,action(7021220,0,{skill_mode:"temporary"}));assert.ok(out.pending_transforms.m[0]);assert.match(out.warnings.join(),/嵌套生命周期/);
});
test("state validation rejects foreign members, malformed arrays and unknown candidate IDs",()=>{
  const f=fixture();f.session.slot_overrides.foreign=[1,2,3,4];assert.throws(()=>api.validateState(f.session,f.catalog));
  f.session.slot_overrides={m:[1]};assert.throws(()=>api.validateState(f.session,f.catalog));
  f.session.slot_overrides={};f.session.pending_transforms={m:{0:{base_id:7020840,pool_ids:[999]}}};assert.throws(()=>api.validateState(f.session,f.catalog));
});
test("round result isolates pending source evidence and preexisting override arrays",()=>{
  const f=fixture();f.session.slot_overrides.m=[7021220,1,0,0];let out=apply(f,action(7021220));out.slot_overrides.m[1]=99;out.pending_transforms.m[0].source.url="changed";assert.equal(f.session.slot_overrides.m[1],1);assert.equal(f.metadata.transformations[7021220].source.url,"fixture-source");
});
test("simultaneous writes to the same slot preserve the entire pre-round slot",()=>{
  const f=fixture();f.session.teams.my[0].move_ids=[7060150,1,0,0];f.session.teams.opponent[0].move_ids=[7060260,2,0,0];
  f.metadata.transformations[7060260].trigger.response_kind="attack";
  const out=apply(f,action(7060150,0,{response_success:true}),action(7060260,0,{member_id:"o",response_success:true,response_choice:true}));
  assert.deepEqual(out.slot_overrides,{});assert.equal(out.events.length,0);assert.match(out.warnings.join(),/同回合多个变化/);
});
test("missing transformation metadata produces a visible blocker without modifying state",()=>{
  const f=fixture();const out=api.applyRound(f.session,{my:action(1,3)},undefined,f.catalog);
  assert.deepEqual(out.slot_overrides,{});assert.deepEqual(out.pending_transforms,{});assert.match(out.warnings.join(),/来源资料未加载/);
});
test("new overrides pad short manual configurations to exactly four slots",()=>{
  const f=fixture();f.session.teams.my[0].move_ids=[7060150];
  let out=apply(f,action(7060150,0,{response_success:true}),action(5,1,{member_id:"o"}));
  assert.deepEqual(out.slot_overrides.m,[5,0,0,0]);assert.doesNotThrow(()=>api.validateState({...f.session,...out},f.catalog));
  f.session.teams.my[0].move_ids=[7021220];f.session.pending_transforms={m:{0:{base_id:7021220,pool_ids:[3]}}};
  out=apply(f,action(3,0,{skill_mode:"temporary"}));assert.deepEqual(out.slot_overrides.m,[7021220,0,0,0]);assert.deepEqual(out.pending_transforms,{});assert.doesNotThrow(()=>api.validateState({...f.session,...out},f.catalog));
});
test("borrow omits unknown teammate clever-change slots but retains known candidates",()=>{
  const f=fixture();f.session.teams.my[1].move_ids=[7021220,3,0,0];f.session.pending_transforms={ally:{0:{base_id:7021220,pool_ids:[4,5]}}};
  const pool=api.getPool(f.catalog,f.metadata,f.session,"my",f.session.teams.my[0],"borrow");
  assert.deepEqual(pool.ids,[3]);assert.match(pool.blockers.join(),/随机结果未知/);assert.match(pool.blockers.join(),/保留其他已知候选/);
});
