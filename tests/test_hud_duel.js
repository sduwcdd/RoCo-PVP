"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");

function hud(side = "my", overrides = {}) {
  const html = fs.readFileSync(path.join(__dirname,"../web/hud_duel.html"),"utf8");
  let script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  script = script.replace("  poll();", "  globalThis.hudTest={radarChart,skillRows,activeIndex,extraDamageRows,render,panel,iconUrl,skillIconUrl,poll,skillPoolRows,poolResults,skillPoolCache,previewPoolSkill,historyRows,benchRow,previewTarget,targetKey,previewListening,listeningPanel,imageError:window.rocoImageError};").replace("  watchRevision();", "");
  const panel={dataset:{},scrollTop:0,querySelectorAll:()=>[]};
  const context = {URLSearchParams,location:{search:"?side="+side},document:{getElementById:()=>panel},window:{addEventListener(){}},setInterval(){},
    setTimeout(){return 1},clearTimeout(){},AbortController:class {constructor(){this.signal={}}abort(){}},...overrides};
  vm.runInNewContext(script,context);
  return context.hudTest;
}

test("protocol speciality is beside nature on both sides, absent data never becomes none",()=>{
  const entry={petId:401,name:'精灵',natureName:'开朗',level:60,moves:[],
    speciality:{id:101,confirmed:true,name:'奇袭',description:'投掷背袭'}};
  const snapshot={runtime:{sessionId:'speciality',myTeam:[entry],enemyTeam:[entry]}};
  for(const side of ['my','enemy']){
    const api=hud(side);api.render(snapshot);
    assert.match(api.panel.innerHTML,/class="tag-nature"[^>]*>开朗<\/span><span class="tag-speciality"[^>]*>奇袭<\/span>/);
    entry.speciality={rawId:0};api.render(snapshot);
    assert.doesNotMatch(api.panel.innerHTML,/class="tag-speciality"/);
    entry.speciality={id:1,confirmed:true,name:'无'};api.render(snapshot);
    assert.match(api.panel.innerHTML,/class="tag-speciality"[^>]*>无<\/span>/);
    entry.speciality={id:101,confirmed:true,name:'<奇袭>',description:'"<注释>'};api.render(snapshot);
    assert.match(api.panel.innerHTML,/&lt;奇袭&gt;/);
    entry.speciality={id:101,confirmed:true,name:'奇袭',description:'投掷背袭'};
  }
});

test("physical metrics and medal certainty render on both sides without inventing missing data",()=>{
  const entry={petId:401,name:'深蓝鲸',level:43,moves:[],physical:{
    height:{text:'2.01米'},weight:{text:'645.41千克'},voice:{text:'+48'},
    medals:[{attribute:'height',name:'小不点',status:'predicted'}]}};
  const snapshot={runtime:{sessionId:'physical',myTeam:[entry],enemyTeam:[entry]}};
  for(const side of ['my','enemy']){
    const api=hud(side);api.render(snapshot);
    assert.match(api.panel.innerHTML,/身高 2\.01米/);
    assert.match(api.panel.innerHTML,/体重 645\.41千克/);
    assert.match(api.panel.innerHTML,/音调参数 \+48/);
    assert.match(api.panel.innerHTML,/预计·小不点/);
    entry.physical.medals[0].status='confirmed';api.render(snapshot);
    assert.doesNotMatch(api.panel.innerHTML,/预计·小不点/);
    entry.physical.medals[0].status='predicted';
    const physical=entry.physical;delete entry.physical;api.render(snapshot);
    assert.doesNotMatch(api.panel.innerHTML,/class="physical-info"/);
    entry.physical=physical;
  }
});

test("world stars are explicit own-only assumptions and never shown for PVP",()=>{
  const api=hud();
  const entry={petId:1,name:'世界精灵',level:60,moves:[],natureStatsPolicy:{stars:10}};
  const snapshot={runtime:{sessionId:'world',mode:'world',myTeam:[entry],enemyTeam:[]}};
  api.render(snapshot);
  assert.match(api.panel.innerHTML,/data-world-stars/);
  assert.match(api.panel.innerHTML,/<option value="10" selected>10星/);
  entry.level=56;api.render(snapshot);
  assert.doesNotMatch(api.panel.innerHTML,/data-world-stars/);
  assert.match(api.panel.innerHTML,/未满60级按0星估计/);
  snapshot.runtime.mode='pvp';entry.level=60;api.render(snapshot);
  assert.doesNotMatch(api.panel.innerHTML,/data-world-stars/);
  const enemy=hud('enemy');snapshot.runtime.mode='world';snapshot.runtime.enemyTeam=[entry];enemy.render(snapshot);
  assert.doesNotMatch(enemy.panel.innerHTML,/data-world-stars/);
});

test("consumed attack forecast is separate from the current next attack",()=>{
  const api=hud();
  const html=api.skillRows({moves:[{slot:1,skillId:7150210,skillName:'风矢',damageNormalMin:495,damageNormalMax:728,
    recentCastEstimate:{round:11,normalMin:990,normalMax:1457}}]});
  assert.match(html,/最近R11本次/);
  assert.match(html,/990–1457/);
  assert.match(html,/当前\/下次/);
  assert.match(html,/495 ~ 728/);
  assert.match(api.historyRows({runtime:{battleHistory:[{kind:'damage',round:11,damage:1173,
    castEstimate:{normalMin:990,normalMax:1457}}]}}),/本次施放前预估 990–1457/);
});

test("independent stars remain visible beside the snow bear combined normal-star forecast",()=>{
  const html=hud().extraDamageRows({traitDamagePreview:{damageByKind:{physical:{minimum:80,maximum:90}}},
    attackMarkDamage:[{markId:1035,name:'普通星陨',damage:20},
      {markId:1035,name:'星陨印记（独立）',independent:true,damage:40}]});
  assert.match(html,/星陨印记（独立）/);assert.doesNotMatch(html,/普通星陨/);
});

test("non-damaging skills are distinguished from blocked damage estimates",()=>{
  const api=hud();
  const html=api.skillRows({moves:[
    {slot:1,skillId:7050210,skillName:'天洪',damageNormalMin:231,damageNormalMax:283},
    {slot:2,skillId:7150220,skillName:'回旋风暴',damageNote:'缺少威力历史'},
    {slot:3,skillId:7130210,skillName:'贮藏',damageNonDamaging:true},
    {slot:4,skillId:7020800,skillName:'血气',damageNonDamaging:true}]});
  assert.match(html,/231 ~ 283/);
  assert.match(html,/title="缺少威力历史">待确认/);
  assert.equal((html.match(/无直接伤害/g)||[]).length,2);
});

test("missing cumulative history is visible without opening a tooltip",()=>{
  const html=hud().skillRows({moves:[
    {slot:1,skillId:7020570,skillName:'能量刃',damageNote:'应对历史不完整：中途观战（第10回合接入）'},
    {slot:2,skillId:7110230,skillName:'落雷',damageNote:'入场历史不完整：技能槽发生变化'}]});
  assert.match(html,/第10回合接入）">中途观战<\/span>/);
  assert.match(html,/技能槽发生变化">历史不完整<\/span>/);
});

test("tailwind damage branches replace the combined range and preserve response branches",()=>{
  for(const side of ['my','enemy']) {
    const api=hud(side), quote=n=>({normalMin:n,normalMax:n,perHitMin:n,perHitMax:n,hits:1});
    const html=api.skillRows({moves:[{slot:1,skillId:7020410,skillName:'音爆',damageNormalMin:100,damageNormalMax:150,
      damageTraitScenarios:[{...quote(100),label:'未触发顺风',triggered:false},{...quote(150),label:'触发顺风',triggered:true}],
      damageResponse:{traitScenarios:[{...quote(200),triggered:false},{...quote(300),triggered:true}]}}]});
    assert.match(html,/未触发顺风 <\/small>100/);
    assert.match(html,/触发顺风 <\/small>150/);
    assert.match(html,/未触发顺风·应对 <\/small>200/);
    assert.match(html,/触发顺风·应对 <\/small>300/);
    assert.doesNotMatch(html,/100 ~ 150/);
  }
});

test("listening selector is on demand, lists public options and never keeps stale damage",async()=>{
  const calls=[], move={slot:4,skillId:7140190,skillName:'听桥',damageCounterPreview:true};
  const api=hud('my',{fetch:async(url,init)=>{
    assert.equal(url,'/api/hud/preview-target');const request=JSON.parse(init.body);calls.push(request);
    return {ok:true,json:async()=>({snapshotToken:'now',counterOptions:[
      {value:'move:7020410',label:'音爆'},{value:'wish:抵抗',label:'愿力冲击·抵抗'},
      {value:'wish:正常',label:'愿力冲击·正常'},{value:'wish:克制',label:'愿力冲击·克制'},
      {value:'wish:3倍克制',label:'愿力冲击·3倍克制',disabled:true}],
      ...(request.counterSkillId?{selectionLabel:'音爆',estimate:{perHitMin:234,perHitMax:234,hits:1},note:'仅应对成功'}:{})})};
  }});
  const snapshot={runtime:{sessionId:'bridge',snapshotToken:'now',myTeam:[{petId:1,moves:[move]}],
    enemyTeam:[{petId:401,moves:[{slot:1,skillId:7020410,skillName:'音爆'}]}],active:{my:{rosterIndex:0},enemy:{rosterIndex:0}}}};
  api.render(snapshot);assert.equal(calls.length,0);assert.match(api.panel.innerHTML,/选择技能<\/button>/);
  await api.previewListening(move,null);assert.equal(calls.length,1);
  assert.equal(calls[0].targetPetId,401);assert.equal(calls[0].previewMode,'listening');
  assert.match(api.panel.innerHTML,/愿力冲击·3倍克制（不适用）/);
  await api.previewListening(move,'move:7020410');assert.equal(calls[1].counterSkillId,7020410);
  assert.match(api.panel.innerHTML,/听桥反击 234/);
  snapshot.runtime.snapshotToken='next';api.render(snapshot);
  assert.match(api.panel.innerHTML,/状态已更新，请重新选择/);assert.doesNotMatch(api.panel.innerHTML,/听桥反击 234/);
});

test("snow bear trait damage appears beside energy before skills on both sides without duplicate stars",()=>{
  for(const side of ['my','enemy']) {
    const api=hud(side),entry={petId:1,name:'月牙雪熊',energy:6,maxEnergy:10,
      traitDamagePreview:{trigger:'非幻系攻击引爆一次',damageByKind:{physical:{minimum:80,maximum:90}}},
      attackMarkDamage:[{markId:1035,name:'星陨印记',damage:20}]};
    api.render({runtime:{sessionId:'snow-bear',myTeam:[entry],enemyTeam:[entry]}});
    const html=api.panel.innerHTML;
    assert.match(html,/特性伤害估计：<b>80～90<\/b>/);
    assert.ok(html.indexOf('特性伤害估计')<html.indexOf('class="active-energy"'));
    assert.ok(html.indexOf('class="active-energy"')<html.indexOf('class="skills"'));
    assert.doesNotMatch(html,/命中敌方 · 星陨/);
    entry.traitDamagePreview=null;api.render({runtime:{sessionId:'snow-bear',myTeam:[entry],enemyTeam:[entry]}});
    assert.doesNotMatch(api.panel.innerHTML,/特性伤害估计/);
    assert.match(api.panel.innerHTML,/命中敌方 · 星陨/);
  }
});

test("missing nature rewrite fields do not label the original nature as current confirmed nature",()=>{
  const api=hud('enemy'),entry={petId:401,name:'窃光蚊',natureName:'慎重',natureOverrideKnown:{up:false,down:false}};
  const snapshot={runtime:{sessionId:'nature-unknown',enemyTeam:[entry]}};
  api.render(snapshot);
  assert.match(api.panel.innerHTML,/原性格：慎重；后天方向未下发/);
  assert.match(api.panel.innerHTML,/>性格待确认<\/span>/);
  entry.configurationInference={known_nature:{up:'hp'}};api.render(snapshot);
  assert.match(api.panel.innerHTML,/>↑生命<\/span>/);
  assert.doesNotMatch(api.panel.innerHTML,/>慎重<\/span>/);
});

test("both HUD sides follow authoritative runtime positions before the legacy state fallback",()=>{
  const snapshot={runtime:{active:{my:{rosterIndex:2},enemy:{rosterIndex:4}}},state:{myActiveIndex:0,enemyActiveIndex:0}};
  assert.equal(hud("my").activeIndex(snapshot),2);
  assert.equal(hud("enemy").activeIndex(snapshot),4);
  assert.equal(hud("my").activeIndex({state:{myActiveIndex:3}}),3);
});

test("known spectator HP displays 1 percent and missing current HP is neither full nor fainted",()=>{
  const api=hud('enemy');
  const p={petId:405,name:'火羽',currentHp:1,maxHp:354,hpPercent:1};
  const snap={runtime:{sessionId:'watch',enemyTeam:[p],active:{enemy:{rosterIndex:0}}}};
  api.render(snap);assert.match(api.panel.innerHTML,/1 \/ 354/);assert.match(api.panel.innerHTML,/>1%/);assert.doesNotMatch(api.panel.innerHTML,/>100%/);
  p.currentHp=null;p.hpPercent=null;api.render(snap);
  assert.match(api.panel.innerHTML,/hp-track unknown/);assert.match(api.panel.innerHTML,/\? \/ 354/);assert.doesNotMatch(api.panel.innerHTML,/>0%|>100%|NaN%/);
});

test("enemy radar shows species stats and a bounded estimate rather than missing stats or a fake midpoint",()=>{
  const ranges={hp:[300,400],phyAtk:[100,200],magAtk:[90,180],phyDef:[80,160],magDef:[70,140],spd:[60,120]};
  const rendered=hud("enemy").radarChart({panelStatRanges:ranges,raceStats:{hp:100,phyAtk:90,magAtk:80,phyDef:70,magDef:60,spd:50},raceStatsSource:"BWIKI种族值"});
  assert.match(rendered,/100–200/);assert.doesNotMatch(rendered,/图鉴种族值|物攻90/);
  assert.match(rendered,/估计范围/);assert.match(rendered,/stroke-dasharray/);assert.doesNotMatch(rendered,/六维未下发/);
});

test("both HUD bars overlay server frozen HP and color the parenthesized threshold",()=>{
  for(const side of ['my','enemy']){
    const api=hud(side),entry={petId:1,name:'精灵',currentHp:337,maxHp:461,frozenHp:138};
    const snapshot={runtime:{sessionId:'freeze',myTeam:[entry],enemyTeam:[entry]}};
    api.render(snapshot);
    assert.match(api.panel.innerHTML,/<b>337<span class="hp-frozen">（138）<\/span> \/ 461<\/b>/);
    const width=Number(api.panel.innerHTML.match(/class="hp-frozen-fill" style="width:([\d.]+)%/)[1]);
    assert.ok(Math.abs(width-138*100/461)<1e-9);
    assert.match(api.panel.innerHTML,/aria-label="冻结生命 138"/);
    entry.frozenHp=0;api.render(snapshot);
    assert.doesNotMatch(api.panel.innerHTML,/hp-frozen/);assert.match(api.panel.innerHTML,/337 \/ 461/);
    entry.frozenHp=999;api.render(snapshot);
    assert.match(api.panel.innerHTML,/hp-frozen-fill" style="width:100%/);
    entry.currentHp=0;api.render(snapshot);
    assert.doesNotMatch(api.panel.innerHTML,/hp-frozen-fill/);
  }
});

test("only established talents are yellow; nature is under the name with correction hover, without solver UI",()=>{
  const api=hud(),entry={petId:1,name:"布灵布灵",maxHp:400,currentHp:400,natureName:"急躁",natureUp:"spd",natureDown:"mdef",
    natureOriginalUp:"spd",natureOriginalDown:"pdef",natureRewritten:true,
    naturedStats:{hp:400,phyAtk:200,magAtk:150,phyDef:150,magDef:180,spd:200},configurationInference:{
      known_talents:{hp:{selected:true,values:[10]},patk:{selected:true,values:[8]},spd:{selected:true,values:[10]}},
      groups:[{nature_name:"平和",combination_count:1210}],panel_fit:[{observed:999}],observations:[{damage:999}]}};
  const radar=api.radarChart(entry);
  assert.equal((radar.match(/font-size="11.5" fill="#ffd75e"/g)||[]).length,3);
  assert.match(radar,/<title>已确定个体加点 8<\/title>物攻/);
  api.render({runtime:{sessionId:"x",myTeam:[entry],active:{my:{rosterIndex:0}}}});
  assert.match(api.panel.innerHTML,/布灵布灵/);assert.match(api.panel.innerHTML,/原方向 ↑速度 ↓物防；修正后 ↑速度 ↓魔防/);
  assert.doesNotMatch(api.panel.innerHTML,/1210|平和|三项加点|下发六维|逐条伤害|模型核对|配置反推/);
  const html=fs.readFileSync(path.join(__dirname,"../web/hud_duel.html"),"utf8");
  assert.doesNotMatch(html,/selection_cases|panel_fit|inferenceRows/);
});

test("enemy nature shows original directions while corrections remain in the hover",()=>{
  const api=hud('enemy');
  const entry={petId:1,name:'精灵',natureName:'开朗',natureUp:'spd',natureDown:'matk',
    natureOriginalUp:'spd',natureOriginalDown:'matk',moves:[]};
  const snapshot={runtime:{sessionId:'enemy-nature',enemyTeam:[entry]}};
  api.render(snapshot);
  assert.match(api.panel.innerHTML,/>开朗 ↑速度 ↓魔攻<\/span>/);
  entry.natureRewritten=true;entry.natureUp='hp';entry.natureDown='mdef';
  api.render(snapshot);
  assert.match(api.panel.innerHTML,/>原性格 开朗 ↑速度 ↓魔攻<\/span>/);
  assert.match(api.panel.innerHTML,/原方向 ↑速度 ↓魔攻；修正后 ↑生命 ↓魔防/);
  entry.natureOverrideKnown={up:false,down:false};entry.natureUp=null;entry.natureDown=null;
  api.render(snapshot);
  assert.match(api.panel.innerHTML,/>原性格 开朗 ↑速度 ↓魔攻<\/span>/);
  assert.match(api.panel.innerHTML,/原性格：开朗 ↑速度 ↓魔攻；后天方向未下发/);
  entry.configurationInference={known_nature:{up:'hp',down:'pdef'}};api.render(snapshot);
  assert.match(api.panel.innerHTML,/>原性格 开朗 ↑速度 ↓魔攻<\/span>/);
  assert.match(api.panel.innerHTML,/当前已确认 ↑生命 ↓物防/);
  delete entry.natureOriginalUp;delete entry.natureOriginalDown;
  entry.configurationInference={known_nature:{up:'hp',down:'pdef'}};
  api.render(snapshot);
  assert.match(api.panel.innerHTML,/>↑生命 ↓物防<\/span>/);
  assert.doesNotMatch(api.panel.innerHTML,/>原性格 开朗 ↑生命/);
});

test("polling preserves the open wish preview and scroll only for the same active pet",()=>{
  const api=hud("enemy"), detail={dataset:{inferenceKey:"wish"},open:true};
  const snapshot={runtime:{sessionId:"test",enemyTeam:[{petId:401,name:"敌方",maxHp:400,currentHp:300}],active:{enemy:{rosterIndex:0}}}};
  api.render(snapshot);api.panel.scrollTop=80;
  api.panel.querySelectorAll=selector=>selector.indexOf('data-inference-key')>=0?[detail]:[];
  api.render(snapshot);
  assert.equal(detail.open,true);assert.equal(api.panel.scrollTop,80);
  snapshot.runtime.enemyTeam[0].petId=402;
  api.render(snapshot);
  assert.equal(detail.open,false);assert.equal(api.panel.scrollTop,0);
});

test("all radar grid rings are convex six-sided polygons",()=>{
  const rendered=hud().radarChart({naturedStats:{hp:398,phyAtk:96,phyDef:189,magAtk:206,magDef:236,spd:165}});
  const rings=[...rendered.matchAll(/<polygon points="([^"]+)"/g)].slice(0,3);
  assert.equal(rings.length,3);
  for(const ring of rings){
    const points=ring[1].split(" ").map(x=>x.split(",").map(Number));
    assert.equal(points.length,6);
    const cross=points.map((p,i)=>{const q=points[(i+1)%6],r=points[(i+2)%6];return(q[0]-p[0])*(r[1]-q[1])-(q[1]-p[1])*(r[0]-q[0]);});
    assert.ok(cross.every(x=>x>0)||cross.every(x=>x<0),"grid must not self-intersect");
  }
});

test("HUD renders a single damage or uncertainty interval without confusing it with critical damage",()=>{
  const api=hud();
  const exact=api.skillRows({moves:[{name:"攻击",damageNormal:120,damageCritical:240,lethal:true,oneShot:true}]});
  assert.match(exact,/120/);assert.doesNotMatch(exact,/暴 240/);
  assert.match(exact,/class="ohko"[^>]*>秒！/);assert.doesNotMatch(exact,/估计≥余血|可击倒/);
  const ranged=api.skillRows({moves:[{name:"攻击",damageNormalMin:80,damageNormalMax:160,damageBasis:"性格与个体候选"}]});
  assert.match(ranged,/80 ~ 160/);assert.match(ranged,/性格与个体候选/);
  assert.doesNotMatch(ranged,/秒！/);
  const html=fs.readFileSync(path.join(__dirname,"../web/hud_duel.html"),"utf8");
  assert.doesNotMatch(html,/crit-badge|暴击时（×2）|暴 ' \+/);
});

test("multi-hit renders per-hit times count and mark or wish rows stay outside four slots",()=>{
  const api=hud();
  const rendered=api.skillRows({moves:[{name:"连击",damageNormal:500,damageHits:5,damagePerHitMin:100,damagePerHitMax:100}]});
  assert.match(rendered,/100×5/);assert.match(rendered,/5连击/);
  const extra=api.extraDamageRows({attackMarkDamage:[{name:"星陨印记",perLayerPower:20,layers:5,damage:100}],
    markDamage:[{name:"中毒印记",trigger:"本回合末",layers:2,damage:24}],
    wishPreview:{skillName:"愿力冲击（草）",note:"替换首槽预览",estimate:{normalMin:80,normalMax:100}}});
  assert.match(extra,/命中敌方 · 星陨印记：100/);assert.match(extra,/不随连击重复/);assert.doesNotMatch(extra,/20×5=100/);
  assert.match(extra,/本回合末 24伤害/);assert.match(extra,/愿力冲击/);assert.doesNotMatch(extra,/当前选择愿力/);
  assert.match(extra,/80–100/);assert.doesNotMatch(extra,/空技能槽/);
});

test("response estimates share one skill row, keep ranges and hit counts, and never display crit",()=>{
  const api=hud();
  const rendered=api.skillRows({moves:[{name:"鸩毒",damageNormal:100,damageCritical:200,
    damageResponse:{perHitMin:150,perHitMax:180,hits:3,oneShot:true}}]});
  assert.equal((rendered.match(/class="skill"/g)||[]).length,1);
  assert.match(rendered,/未应对/);assert.match(rendered,/应对/);
  assert.match(rendered,/150–180\)×3/);assert.match(rendered,/秒！/);
  assert.doesNotMatch(rendered,/暴击|>200</);
  assert.match(api.skillRows({moves:[{name:"测试",damageNormal:10,damageResponse:{reason:"缺少能量"}}]}),/待核实/);
});

test("compact core preview shows response and actual matchup types with empty impossible rows",()=>{
  const api=hud();
  const own=api.extraDamageRows({coreMagicSkillId:7010020,wishPreview:{skillName:'愿力冲击（机械）',estimate:{normalMin:140,normalMax:167,response:{normalMin:350,normalMax:417}}}});
  assert.match(own,/140–167/);assert.match(own,/350–417/);assert.doesNotMatch(own,/当前选择愿力|不含应对/);
  assert.match(api.extraDamageRows({coreMagicSkillId:7010070,coreMagicName:'进化之力'}),/核心魔法 · 进化之力/);
  const enemy=api.extraDamageRows({wishScenarios:{rows:[{label:'克制',types:['草系','水系'],normalMin:100,normalMax:150,response:{normalMin:250,normalMax:375}},
    {label:'3倍克制',types:[],normalMin:null,normalMax:null,response:{normalMin:null,normalMax:null}}]}});
  assert.match(enemy,/title="草系、水系"/);assert.match(enemy,/3倍克制<\/td><td><\/td><td><\/td>/);
});

test("reserve bars include frozen HP and energy; target forecasts only request after selection",async()=>{
  let calls=0,request;
  const api=hud('my',{fetch:async(url,options)=>{calls++;request=JSON.parse(options.body);assert.equal(url,'/api/hud/preview-target');return {ok:true,json:async()=>({targetName:'替补',estimate:{normalMin:30,normalMax:40},snapshotToken:3})}}});
  const move={slot:1,skillId:7040370,name:'火焰箭'}, actor={petId:1,name:'我方',energy:7,maxEnergy:10,moves:[move]};
  const target={petId:402,name:'替补',currentHp:100,maxHp:200,frozenHp:50,energy:4,alive:true};
  const snapshot={runtime:{sessionId:'test',snapshotToken:3,myTeam:[actor],enemyTeam:[{petId:401},target],active:{my:{rosterIndex:0},enemy:{rosterIndex:0}}}};
  api.render(snapshot);assert.equal(calls,0);assert.match(api.panel.innerHTML,/能量 <b>7 \/ 10/);assert.match(api.panel.innerHTML,/target-toggle/);
  const bench=api.benchRow([actor,target],0);assert.match(bench,/hp-frozen-fill/);assert.match(bench,/⚡4/);assert.match(bench,/50%/);assert.match(bench,/100（50）\/200/);
  await api.previewTarget(api.targetKey(move),move,402);
  assert.equal(calls,1);assert.equal(request.targetPetId,402);assert.equal(request.snapshotToken,3);assert.match(api.panel.innerHTML,/30–40/);
  snapshot.runtime.snapshotToken=4;api.render(snapshot);assert.equal(calls,1);assert.match(api.panel.innerHTML,/状态已更新/);
});

test("different choice damage stays in one slot and renders two labeled branches",()=>{
  const rendered=hud().skillRows({moves:[{name:"下注",damageNormalMin:100,damageNormalMax:200,
    damageChoices:[{label:"选择一",note:"使用后生命-10%",perHitMin:125,perHitMax:135,hits:1},
                   {label:"选择二",perHitMin:185,perHitMax:185,hits:1,response:{perHitMin:210,perHitMax:210,hits:1}}]}]});
  assert.equal((rendered.match(/class="skill"/g)||[]).length,1);
  assert.match(rendered,/选择一/);assert.match(rendered,/125–135/);
  assert.match(rendered,/选择二/);assert.match(rendered,/185/);assert.match(rendered,/选择二·应对/);
  assert.doesNotMatch(rendered,/100 ~ 200/);
});

test("HUD makes one cached request per poll and cannot accumulate overlapping requests",async()=>{
  let count=0,finish;
  const reply={ok:true,json:async()=>({payload:null,state:{relay_ok:true},at:1})};
  const pending=new Promise(resolve=>{finish=resolve});
  const api=hud('my',{fetch:(url)=>{assert.match(url,/^\/api\/hud\/snapshot(?:\?after=1)?$/);count++;return count===1?pending:Promise.resolve(reply)}});
  const first=api.poll();api.poll();assert.equal(count,1);
  finish(reply);await first;await api.poll();assert.equal(count,2);
});

test("icons use current form and normalized wire skill IDs; transient failures retry twice",()=>{
  const timers=[],api=hud('my',{setTimeout:fn=>{timers.push(fn);return 1}});
  assert.equal(api.iconUrl({petBaseId:3776}),'/roco-pet-avatars-id/3776.png');
  assert.equal(api.iconUrl({stageBaseConfId:3004,petBaseId:5026}),'/roco-pet-avatars-id/3004.png');
  assert.equal(api.skillIconUrl({skillId:706026000}),'/roco-skill-icons/7060260.png');
  const img={dataset:{},style:{},isConnected:true,src:'/roco-pet-avatars-id/3776.png',getAttribute(){return this.src}};
  api.imageError(img);timers.shift()();assert.match(img.src,/retry=1/);
  api.imageError(img);timers.shift()();assert.match(img.src,/retry=2/);
  api.imageError(img);assert.equal(img.style.visibility,'hidden');assert.equal(timers.length,0);
});

test("both HUD drag strips use a move cursor and captured pointer dragging without swallowing close", async()=>{
  const source=fs.readFileSync(path.join(__dirname,"../overlay/main.js"),"utf8");
  const code=source.slice(source.indexOf("function injectDuelChrome"),source.indexOf("function createDuelWindow"));
  for(const side of ["my","enemy","history"]){
    const handlers={},calls=[];let injected="",css="";
    const strip={querySelector:()=>({addEventListener(){}}),addEventListener:(name,fn)=>{handlers[name]=fn},setPointerCapture:id=>calls.push(["capture",id])};
    const context={console,document:{getElementById:()=>null,createElement:()=>strip,body:{appendChild(){}}},window:{addEventListener(){},rocoOverlay:{drag:p=>calls.push(p)}}};
    vm.runInNewContext(code,context);
    context.injectDuelChrome({webContents:{insertCSS:c=>{css=c;return Promise.resolve()},executeJavaScript:s=>{injected=s;return Promise.resolve()}}},side);
    assert.match(css,/no-drag; cursor: move;/);
    assert.match(css,/cursor: pointer/);
    vm.runInNewContext(injected,context);
    const pointer={button:0,pointerId:7,target:{closest:()=>null},preventDefault(){}};
    handlers.pointerdown(pointer);handlers.pointermove(pointer);handlers.pointerup(pointer);handlers.pointermove(pointer);
    assert.deepEqual(calls,[["capture",7],"start","move","end"]);
    calls.length=0;handlers.pointerdown({...pointer,target:{closest:()=>({})}});
    assert.equal(calls.length,0);
  }
});

test("knockout damage stays historical and missing pre-knockout data is explicit",()=>{
  const api=hud();
  const rows=api.skillRows({moves:[{skillId:7040370,name:'火焰箭',damageNormal:120,damageBeforeKnockout:true}]});
  assert.match(rows,/120/);assert.match(rows,/力竭前/);assert.doesNotMatch(rows,/待确认|秒！/);
  const missing=api.skillRows({moves:[{skillId:7040370,name:'火焰箭',damageNote:'未记录这组对战精灵力竭前的伤害估计',damageBeforeKnockoutMissing:true}]});
  assert.match(missing,/无力竭前记录/);assert.doesNotMatch(missing,/待确认/);
});

test("enemy skill query searches the learnset separately from observed four slots",()=>{
  const api=hud('enemy'),data={skills:[{skillId:7040200,name:'吹火',type:'火系',energy:1,power:50,
    description:'每次使用后威力+20',sources:[{category:'legacy',bloodline:'火',level:15}]}]};
  const rows=api.skillPoolRows({petBaseId:3003},data);
  assert.match(rows,/技能查询/);assert.match(rows,/非对方已携带/);assert.match(rows,/等级≥15/);
  assert.match(api.poolResults(data,'威力\+20'),/吹火/);
  assert.doesNotMatch(api.poolResults(data,'水系'),/吹火/);
  assert.doesNotMatch(api.skillRows({moves:[],petBaseId:3003}),/吹火/);
});

test("enemy learnset click previews current opposing active without adding an observed slot",async()=>{
  const handlers={},calls=[],button={dataset:{poolSkill:'7040200',skillName:'吹火'}};
  const input={addEventListener(){},value:''};
  const details={dataset:{skillQuery:'3003'},addEventListener:(name,fn)=>{handlers[name]=fn},contains:b=>b===button,
    querySelector:selector=>selector==='input'?input:{addEventListener(){}}};
  const panel={dataset:{},scrollTop:0,querySelectorAll:selector=>selector==='details[data-skill-query]'?[details]:[]};
  const api=hud('enemy',{document:{getElementById:()=>panel},fetch:async(url,init)=>{
    assert.equal(url,'/api/hud/preview-target');calls.push(JSON.parse(init.body));
    return {ok:true,json:async()=>({snapshotToken:7,hypothetical:true,targetName:'我方在场',note:'假设携带',
      estimate:{normalMin:123,normalMax:145,response:{normalMin:246,normalMax:290}}})};
  }});
  const enemy={petId:401,petBaseId:3003,moves:[]};
  const snapshot={runtime:{sessionId:'pool',snapshotToken:7,enemyTeam:[enemy],myTeam:[{petId:1},{petId:2}],
    active:{enemy:{rosterIndex:0},my:{rosterIndex:1}}}};
  api.skillPoolCache[3003]={skills:[{skillId:7040200,name:'吹火'}]};
  api.render(snapshot);assert.equal(calls.length,0);assert.match(api.panel.innerHTML,/data-pool-skill="7040200"/);
  await handlers.click({target:{closest:()=>button}});
  assert.deepEqual(calls,[{sessionId:'pool',snapshotToken:7,side:'enemy',actorPetId:401,targetPetId:2,
    skillId:7040200,slot:null,previewMode:'skill-pool'}]);
  assert.match(api.panel.innerHTML,/假设试算 · 吹火/);assert.match(api.panel.innerHTML,/123–145 \/ 应对 246–290/);
  assert.match(api.panel.innerHTML,/aria-pressed="true"/);assert.equal(enemy.moves.length,0);
  assert.equal((api.skillRows(enemy).match(/未观测/g)||[]).length,4);
  snapshot.runtime.snapshotToken=8;api.render(snapshot);
  assert.match(api.panel.innerHTML,/状态已更新，请重新选择/);assert.doesNotMatch(api.panel.innerHTML,/123–145/);
  assert.equal(calls.length,1);
});

test("learnset previews discard out-of-order replies and hide late stale estimates",async()=>{
  const pending=[];
  const api=hud('enemy',{fetch:()=>new Promise(resolve=>pending.push(resolve))});
  const snapshot={runtime:{sessionId:'race',snapshotToken:'one',enemyTeam:[{petId:401,petBaseId:3003}],
    myTeam:[{petId:1}],active:{my:{rosterIndex:0},enemy:{rosterIndex:0}}}};
  const reply=n=>({ok:true,json:async()=>({snapshotToken:'one',estimate:{normalMin:n,normalMax:n}})});
  api.render(snapshot);
  const first=api.previewPoolSkill(10,'先选',3003),second=api.previewPoolSkill(20,'后选',3003);
  pending[1](reply(222));await second;pending[0](reply(111));await first;
  assert.match(api.panel.innerHTML,/假设试算 · 后选/);assert.match(api.panel.innerHTML,/222/);
  assert.doesNotMatch(api.panel.innerHTML,/111/);
  const third=api.previewPoolSkill(30,'再选',3003);
  snapshot.runtime.snapshotToken='two';api.render(snapshot);pending[2](reply(333));await third;
  assert.match(api.panel.innerHTML,/状态已更新，请重新选择/);assert.doesNotMatch(api.panel.innerHTML,/333/);
  snapshot.runtime.sessionId='new-session';api.render(snapshot);
  assert.doesNotMatch(api.panel.innerHTML,/假设试算 · 再选/);
});

test("learnset preview keeps calculation errors visible and escaped",async()=>{
  const api=hud('enemy',{fetch:async()=>({ok:false,json:async()=>({error:'尚缺<面板>'})})});
  api.render({runtime:{sessionId:'error',snapshotToken:1,enemyTeam:[{petId:401,petBaseId:3003}],myTeam:[{petId:1}]}});
  await api.previewPoolSkill(10,'<候选>',3003);
  assert.match(api.panel.innerHTML,/假设试算 · &lt;候选&gt;：尚缺&lt;面板&gt;/);
});

test("top history shows full session, switches, both skills and each hit's exact damage",()=>{
  const api=hud('history');
  const runtime={sessionId:'one',round:3,battleHistory:[
    {round:1,kind:'battle_enter',text:'进入对局'},
    {round:2,kind:'skill_cast',side:0,petName:'火神',skillName:'吹火'},
    {round:2,kind:'damage',side:0,casterName:'火神',targetName:'咔咔鸟',skillName:'吹火',damage:59,damageFinal:10},
    {round:3,kind:'switch',side:1,petName:'水灵'},
    {round:3,kind:'form_change',side:0,text:'雪影娃娃 → 雪影冰灵'},
    {round:3,kind:'skill_cast',side:1,petName:'水灵',skillName:'水弹'}],battleTimeline:[]};
  api.render({runtime});
  assert.match(api.panel.innerHTML,/火神 使用 吹火/);assert.match(api.panel.innerHTML,/水灵 上场/);
  assert.match(api.panel.innerHTML,/59 伤害/);assert.match(api.panel.innerHTML,/实际扣血 10/);
  assert.match(api.panel.innerHTML,/水灵 使用 水弹/);
  assert.match(api.panel.innerHTML,/雪影娃娃 → 雪影冰灵/);
  assert.doesNotMatch(api.panel.innerHTML,/六维|技能查询/);
});

test("history reports durable local archival and never hides a write failure",()=>{
  const api=hud('history');
  api.render({runtime:{round:5,battleHistory:[{kind:'battle_enter',round:3,text:'进入对局 · 我方 6 只 / 敌方 6 只'}],
    replayArchive:{enabled:true,error:''}}});
  assert.match(api.panel.innerHTML,/已存本地/);assert.match(api.panel.innerHTML,/敌方 6 只/);
  assert.match(api.panel.innerHTML,/从第3回合开始观测/);
  api.render({runtime:{round:5,battleHistory:[],replayArchive:{enabled:false,error:'disk full'}}});
  assert.match(api.panel.innerHTML,/保存失败/);assert.doesNotMatch(api.panel.innerHTML,/已存本地/);
});

test("history window defaults to the top center and shares HUD launch lifecycle",()=>{
  const source=fs.readFileSync(path.join(__dirname,'../overlay/main.js'),'utf8');
  const code=source.slice(source.indexOf('function duelBounds'),source.indexOf('function injectDuelChrome'));
  const context={DUEL_WIDTH:300,DUEL_GAP:10,screen:{getPrimaryDisplay:()=>({workArea:{x:0,y:0,width:1600,height:900}})}};
  vm.runInNewContext(code,context);
  const bounds=context.duelBounds('history');
  assert.equal(bounds.y,8);assert.equal(bounds.x*2+bounds.width,1600);
  assert.ok(bounds.x>context.duelBounds('my').width);assert.ok(bounds.height<=210);
  for(const side of ['my','enemy']){
    const pane=context.duelBounds(side);
    assert.equal(pane.width,300);assert.equal(pane.height,876);assert.equal(pane.y,12);
    assert.ok(pane.y+pane.height<=900);
  }
  assert.match(source,/createDuelWindow\('my'\), createDuelWindow\('enemy'\), createDuelWindow\('history'\)/);
});

test("HUD drag IPC moves only the sender's own window and stops on end or click-through",()=>{
  const source=fs.readFileSync(path.join(__dirname,"../overlay/main.js"),"utf8");
  assert.match(source.slice(source.indexOf('async function runDuel')),/if \(!process.argv.includes\('--hud-only'\)\) createTray\(\)/);
  const start=source.indexOf("let duelWins = []"),end=source.indexOf("function duelBounds",start);
  let listener,cursor={x:20,y:40};const moves=[],sender={};
  const window={isDestroyed:()=>false,webContents:sender,getPosition:()=>[100,200],duelSize:{width:268,height:780},setBounds:b=>moves.push([b.x,b.y,b.width,b.height])};
  const context={ipcMain:{on:(name,fn)=>{if(name==='overlay:drag')listener=fn}},screen:{getCursorScreenPoint:()=>cursor}};
  vm.runInNewContext(source.slice(start,end)+"\nglobalThis.setWindows = w => { duelWins=w }; globalThis.through=()=>{duelThrough=true};",context);
  context.setWindows([window]);listener({sender:{}},"start");listener({sender:{}},"move");assert.equal(moves.length,0);
  listener({sender},"start");cursor={x:35,y:37};listener({sender},"move");assert.deepEqual(moves,[[115,197,268,780]]);
  for(let i=0;i<40;i++){cursor={x:35+i,y:37+i};listener({sender},"move");}
  assert.ok(moves.every(b=>b[2]===268&&b[3]===780));
  const moved=moves.length;
  listener({sender},"end");listener({sender},"move");assert.equal(moves.length,moved);
  context.through();listener({sender},"start");listener({sender},"move");assert.equal(moves.length,moved);
});
