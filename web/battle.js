"use strict";
// Pure validation boundary: no game mechanics or population probabilities are invented.
const BattleData = (() => {
  const DIMS=["hp","patk","matk","pdef","mdef","spd"];
  const LABELS={hp:"生命",patk:"物攻",matk:"魔攻",pdef:"物防",mdef:"魔防",spd:"速度"};
  const BLOODLINES=["未指定","普通","草","火","水","光","地","冰","龙","电","毒","虫","武","翼","萌","幽","恶","机械","幻","首领"];
  const MODIFIERS=[null,"hp","patk","matk","pdef","mdef","spd"];
  const CORE_MAGICS={104001:"光合治愈",104002:"愿力强化",104007:"进化之力"};
  // 愿力冲击公共面板参数来自解包技能表 SKILL_CONF 7700001–7700019：19 条系别变体除
  // skill_result.effect_id 外完全一致（威力 80 / 能耗 2 / 优先级 5 / 单体），7700006 标为废弃。
  // 变体到系别的归属尚未解析，因此这里只记录公共参数与变体范围，不指定具体 skill_id。
  const WISH_STRIKE={name:"愿力冲击",power:80,energy:2,priority:5,variant_ids:[7700001,7700002,7700003,7700004,7700005,7700007,7700008,7700009,7700010,7700011,7700012,7700013,7700014,7700015,7700016,7700017,7700018,7700019],source:"SKILL_CONF 7700001-7700019",variant_resolved:false};
  // 用户口径例外（未经游戏文件核对）：迪莫使用进化之力时，除形态进化外还把首槽替换为愿力冲击。
  const CORE_MAGIC_USER_NOTES=[{form_ids:[3004],magic_id:104007,rule:"also_replace_first_slot",source:"user_statement",verified:false}];
  const BLOODLINE_TINTS=["#8d8c7e","#9a9a92","#4f8a52","#b4553f","#3f7ba8","#c3a53a","#93704a","#4a8fa0","#6a5f9e","#c9a227","#7a5a94","#6f8f3f","#a8503f","#57789c","#c07f9c","#5b5f86","#6b5566","#7d7f84","#7b6ca8","#9c6b28"];
  const SIDES=["my","opponent"],ORIGINS=["carried","copied","borrowed","generated","unknown"];
  const clone=x=>JSON.parse(JSON.stringify(x)),same=(a,b)=>String(a)===String(b);
  const name=x=>x?.title||(typeof x?.name==="string"?x.name:x?.name?.zh)||String(x?.id??"未知");
  const zh=x=>typeof x==="string"?x:x?.zh||"",object=x=>!!x&&typeof x==="object"&&!Array.isArray(x);
  function text(x,label,max=200,empty=false){if(typeof x!=="string"||x.length>max||(!empty&&!x.trim()))throw Error(label+"格式无效");return x;}
  function integer(x,label,nullable=true){if(nullable&&(x===null||x===undefined||x===""))return null;if(typeof x!=="number"||!Number.isSafeInteger(x)||x<0)throw Error(label+"必须为非负整数或未知");return x;}
  function probability(x){if(typeof x!=="number"||!Number.isFinite(x)||x<0||x>1)throw Error("概率必须为 0–1 的有限数值");return x;}
  function hpPercent(x){if(x===null||x===undefined||x==="")return null;if(typeof x!=="number"||!Number.isInteger(x)||x<0||x>100)throw Error("剩余生命百分比必须为 0–100 的整数（0 表示倒下）");return x;}
  function exactHp(input,partial=false){const remaining=integer(input.remaining_hp_exact,"我方剩余血量"),maximum=integer(input.max_hp_exact,"我方总血量");if(!partial&&(remaining===null)!==(maximum===null))throw Error("我方剩余血量和总血量必须同时填写");if(maximum!==null&&maximum<1)throw Error("我方总血量必须大于 0");if(remaining!==null&&maximum!==null&&remaining>maximum)throw Error("我方剩余血量不能超过总血量");return {remaining_hp_exact:remaining,max_hp_exact:maximum};}
  function coreMagic(x){if(x===null||x===undefined||x==="")return null;const id=integer(x,"核心魔法",false);if(!Object.hasOwn(CORE_MAGICS,id))throw Error("暂不支持记录该核心魔法");return id;}
  function energy(x,label="能量"){if(x===null||x===undefined||x==="")return null;if(typeof x!=="number"||!Number.isInteger(x)||x<0||x>10)throw Error(label+"必须为 0–10 的整数");return x;}
  function hpFields(input){const raw=input.remaining_hp_percent,fractional=typeof raw==="number"&&Number.isFinite(raw)&&raw>=0&&raw<=100&&!Number.isInteger(raw),out={remaining_hp_percent:hpPercent(fractional?null:raw)},old=integer(input.remaining_hp,"旧版绝对生命"),legacy=input.legacy_remaining_hp_percent??(fractional?raw:null);if(legacy!==null){if(typeof legacy!=="number"||!Number.isFinite(legacy)||legacy<0||legacy>100)throw Error("旧版百分比观测格式无效");out.legacy_remaining_hp_percent=legacy;}if(old!==null){out.remaining_hp=old;out.remaining_hp_unit="legacy_absolute";}return out;}
  function openingTeams(session){return session.rounds[0]?.teams_snapshot||(session.opening_full_hp===true||!session.rounds.length&&!session.legacy_payload?session.teams:null);}
  function latestHpObservations(session,side){const out=new Map(),initial=openingTeams(session);for(const m of initial?.[side]||[])out.set(m.member_id,{value:100,status:"initial",turn:0});for(const r of session.rounds){const a=r[side];if(!a)continue;const mid=a.hp_observed_member_id||(a.kind!=="switch"?a.member_id:null);if(!mid)continue;if(side==="my"&&Number.isInteger(a.remaining_hp_exact)&&Number.isInteger(a.max_hp_exact)&&a.max_hp_exact>0&&a.remaining_hp_exact<=a.max_hp_exact)out.set(mid,{value:a.remaining_hp_exact===0?0:Math.max(1,Math.ceil(a.remaining_hp_exact/a.max_hp_exact*100)),exact_remaining:a.remaining_hp_exact,exact_max:a.max_hp_exact,status:"observed",turn:r.turn});else if(Number.isInteger(a.remaining_hp_percent)&&a.remaining_hp_percent>=0&&a.remaining_hp_percent<=100)out.set(mid,{value:a.remaining_hp_percent,status:"observed",turn:r.turn});else if((a.received_damage>0&&a.remaining_hp_percent==null&&a.remaining_hp_exact==null&&out.get(mid)?.status==="initial")||a.legacy_remaining_hp_percent!=null||a.remaining_hp!=null||typeof a.remaining_hp_percent==="number"&&!Number.isInteger(a.remaining_hp_percent))out.set(mid,{value:null,status:"needs_confirmation",turn:r.turn});}return out;}
  function latestEnergyObservations(session,side){const out=new Map(),initial=openingTeams(session);for(const m of initial?.[side]||[])out.set(m.member_id,{value:10,status:"initial",turn:0});for(const r of session.rounds){const a=r[side];if(!a)continue;const mid=a.kind==="switch"?a.target_member_id:a.member_id;if(!mid)continue;if(Number.isInteger(a.remaining_energy)&&a.remaining_energy>=0&&a.remaining_energy<=10)out.set(mid,{value:a.remaining_energy,status:"recorded",turn:r.turn});else out.set(mid,{value:null,status:"needs_confirmation",turn:r.turn});}return out;}
  const WEATHER_NAMES={unknown:"未确认",none:"无天气",rain:"雨天",sandstorm:"沙暴",blizzard:"暴风雪",thunder:"雷鸣"};
  function weatherObservation(input){if(input==null)return null;if(!object(input)||!Object.hasOwn(WEATHER_NAMES,input.kind))throw Error("天气记录无效");const remaining=integer(input.remaining_rounds,"天气剩余回合");if(remaining!==null&&remaining>99)throw Error("天气剩余回合过大");return {kind:input.kind,remaining_rounds:["none","unknown"].includes(input.kind)?null:remaining,source:"user_observation"};}
  function mechanicFields(input){const mode=input.skill_mode||"carried";if(!["carried","borrow","mind_read","rewrite","temporary"].includes(mode))throw Error("技能选择方式无效");const slot=integer(input.generator_slot,"技能来源槽");if(slot!==null&&slot>3)throw Error("技能来源槽无效");for(const key of ["response_success","response_choice"])if(input[key]!==undefined&&typeof input[key]!=="boolean")throw Error("应对确认值无效");return {skill_mode:mode,generator_slot:slot,response_success:input.response_success===true,response_choice:input.response_choice===true};}
  function talentSelection(input){
    if(input==null)return null;
    if(!object(input)||!Array.isArray(input.selected)||input.selected.length>3||new Set(input.selected).size!==input.selected.length||input.selected.some(d=>!DIMS.includes(d))||!object(input.values)||!object(input.value_sources)||!["team_code_markers","user_selected"].includes(input.selection_source)||input.default_value!==10)throw Error("三选六个体设置无效");
    if(Object.keys(input.values).some(d=>!input.selected.includes(d))||Object.keys(input.value_sources).some(d=>!input.selected.includes(d)))throw Error("未选维度不能填写个体加成");
    const out={selected:[...input.selected],values:{},value_sources:{},selection_source:input.selection_source,default_value:10};
    for(const d of input.selected){out.values[d]=integer(input.values[d],"所选个体加成",false);if(!["user_default","user_entered"].includes(input.value_sources[d])||input.value_sources[d]==="user_default"&&out.values[d]!==10)throw Error("个体默认值来源无效");out.value_sources[d]=input.value_sources[d];}return out;
  }
  function selectionFromMarkers(input){const valid=(input?.raw_talent_markers||[]).map(v=>Number(v)).filter(v=>Number.isInteger(v)&&v>=79&&v<=84),allDefault=valid.length>1&&valid.every(v=>v===valid[0]),selected=allDefault?[]:[...new Set(valid.map(v=>DIMS[v-79]))];return talentSelection({selected,values:Object.fromEntries(selected.map(d=>[d,10])),value_sources:Object.fromEntries(selected.map(d=>[d,"user_default"])),selection_source:"team_code_markers",default_value:10});}
  function firstSlotReplacement(magicId,formId){if(!magicId)return null;if(magicId===104002)return {...WISH_STRIKE};const note=CORE_MAGIC_USER_NOTES.find(n=>n.magic_id===magicId&&n.form_ids.map(String).includes(String(formId)));return note&&note.rule==="also_replace_first_slot"?{...WISH_STRIKE,user_note:true}:null;}
  function effectiveDirections(member,natures){
    const nature=natures?.get(String(member?.nature_id)),up=MODIFIERS[member?.nature_modifiers?.up_id]||nature?.up||null,down=MODIFIERS[member?.nature_modifiers?.down_id]||nature?.down||null;
    return {up,down,complete:!!up&&!!down&&up!==down};
  }
  function hpPanel(base,displayTalent,up,down){
    if(!Number.isInteger(base)||base<1||!Number.isInteger(displayTalent)||displayTalent<0||displayTalent>10||!up||!down||up===down)return null;
    const multiplier=up==="hp"?1.2:down==="hp"?.9:1,growth=Math.fround(base*.01)+displayTalent*6*.005,core=Math.round(Math.fround(170*growth+70));
    return Math.round(core*multiplier+100);
  }
  function configuredMaxHp(member,form,natures){
    const selection=member?.talent_selection,directions=effectiveDirections(member,natures);
    if(!selection||selection.selected?.length!==3||!directions.complete)return null;
    const displayTalent=selection.selected.includes("hp")?selection.values.hp:0;
    return hpPanel(form?.stats?.hp,displayTalent,directions.up,directions.down);
  }
  function reverseHpConfigurations(target,form,selection,fixed={}){
    if(!Number.isInteger(target)||target<1||!Number.isInteger(form?.stats?.hp)||!selection)return [];
    const upIds=fixed.up_id?[fixed.up_id]:MODIFIERS.slice(1).map((_,i)=>i+1),downIds=fixed.down_id?[fixed.down_id]:MODIFIERS.slice(1).map((_,i)=>i+1);
    const hpSelected=selection.selected?.includes("hp"),hpExcluded=selection.selected?.length===3&&!hpSelected,value=selection.values?.hp,talents=hpSelected?(Number.isInteger(value)&&value>=0&&value<=10?[value]:[]):hpExcluded?[null]:[null,...Array.from({length:11},(_,i)=>i)];
    const out=[];
    for(const up_id of upIds)for(const down_id of downIds){if(up_id===down_id)continue;for(const talent of talents){const hp=hpPanel(form.stats.hp,talent??0,MODIFIERS[up_id],MODIFIERS[down_id]);if(hp===target)out.push({up_id,down_id,hp_talent_selected:talent!==null,hp_talent_value:talent,hp});}}
    return out;
  }
  function confirmedMoves(side,m){return side==="my"&&m?.move_ids?.length===4&&m.move_ids.every(id=>id!==0&&m.confirmed?.moves?.some(x=>same(x,id)));}
  function configuredMoves(side,m){return side==="my"&&m?.move_ids?.length===4&&m.move_ids.every(id=>id!=null&&Number(id)>0);}
  // BWIKI snapshot: 借用 / 取念 / 复写 generate skills outside the carried slots.
  function temporaryMoves(m){return m?.move_ids?.some(id=>[7020840,7020850,7020860].includes(Number(id)))||false;}
  function create(catalog){
    if(!object(catalog)||!Array.isArray(catalog.forms)||!object(catalog.moves))throw Error("图鉴数据尚未就绪");
    const forms=new Map(catalog.forms.map(x=>[String(x.id),x])),natures=new Map((catalog.natures||[]).map(x=>[String(x.id),x]));
    const form=id=>forms.get(String(id)),move=id=>Object.hasOwn(catalog.moves,String(id))?catalog.moves[String(id)]:undefined;
    function sources(id){
      const l=catalog.details?.[id]?.learnset||{},out=new Map();
      const add=(mid,label)=>{if(mid==null)return;const k=String(mid);if(!out.has(k))out.set(k,{id:mid,labels:[]});if(!out.get(k).labels.includes(label))out.get(k).labels.push(label);};
      for(const x of l.pool||[])add(object(x)?x.move??x.id:x,"技能池");
      for(const x of l.stones||[])add(object(x)?x.move??x.id:x,"技能石");
      for(const x of l.legacy||[])add(x.move,"传承 · "+(x.bloodline||"未注明")+"血脉（需核对）");
      for(const x of l.legendary||[])add(x.move,"特殊技能（需核对条件）");
      for(const x of l.native||[])add(x.move,"自然习得"+(x.level!=null?" Lv."+x.level:"")+(x.stage!=null?" / "+x.stage+"阶":""));
      return [...out.values()];
    }
    function requireForm(id){const f=form(id);if(!f)throw Error("当前图鉴中找不到精灵："+String(id));return f.id;}
    function requireMove(id){const m=move(id);if(!m)throw Error("当前图鉴中找不到技能："+String(id));return m.id;}
    function requireNature(id){if(id==null||id==="")return null;const n=natures.get(String(id));if(!n)throw Error("当前资料中找不到性格："+String(id));return n.id;}
    function talents(input){const out={};if(input!=null&&!object(input))throw Error("个体资质格式无效");for(const d of DIMS)out[d]=integer(input?.[d],LABELS[d]);if(input&&Object.keys(input).some(k=>!DIMS.includes(k)))throw Error("存在未知个体资质维度");return out;}
    function codeProvenance(input){
      if(input==null)return null;
      if(!object(input)||input.kind!=="team_code"||!object(input.original_member)||!object(input.original_configuration)||!Array.isArray(input.original_configuration.move_ids)||!Array.isArray(input.issues)||JSON.stringify(input).length>500000)throw Error("阵容码来源记录无效或过大");
      text(input.raw_code,"原始阵容码",1000);text(input.snapshot_id,"阵容码资料快照",200);
      const out=clone(input);out.training_eligible=false;return out;
    }
    function codeConfiguration(input){const out={form_id:input.form_id,nature_id:input.nature_id??null,bloodline_id:input.bloodline_id??null,nature_modifiers:input.nature_modifiers||{up_id:0,down_id:0},move_ids:input.move_ids.map(x=>x==null?0:x),talents:talents(input.talents)};if(input.talent_selection!=null)out.talent_selection=talentSelection(input.talent_selection);return out;}
    function importCode(result,side,idFactory){
      if(!object(result)||result.format_valid!==true||result.importable!==true||!Array.isArray(result.members)||!result.members.length||result.members.length>6||!Array.isArray(result.issues))throw Error("阵容码存在不能导入的问题；请先核对解析结果");
      if(result.snapshot_id!==catalog.snapshot_id)throw Error("解析快照与当前网页不同，请重新解析");
      if(result.issues.some(i=>["format_error","user_confirmed_error"].includes(i.category)))throw Error("存在格式错误或用户已确认的错误，不能导入");
      return result.members.map((m,i)=>{
        if(m.importable!==true||!Array.isArray(m.move_ids)||m.move_ids.length!==4)throw Error("成员或技能槽不可导入");
        const conf={form_id:m.form_id,nature_id:m.nature?.original?.bwiki_id??(m.nature_id===0?null:m.nature_id),bloodline_id:m.bloodline_id,nature_modifiers:clone(m.nature?.modifiers||{up_id:0,down_id:0}),move_ids:[...m.move_ids],talents:Object.fromEntries(DIMS.map(d=>[d,null])),talent_selection:selectionFromMarkers(m)};
        const provenance={kind:"team_code",raw_code:result.raw_code,protocol_version:result.protocol_version,team_type_id:result.team_type_id,core_magic:clone(result.core_magic),snapshot_id:result.snapshot_id,source_version:result.source_version??null,protocol_source:clone(result.protocol_source||{}),raw_fields:clone(result.raw_fields||{}),sources:clone(result.sources||result.provenance||{}),original_member:clone(m),issues:clone(result.issues),original_configuration:clone(conf),training_eligible:false,edited_since_import:false};
        return member({...conf,member_id:idFactory(),talent_note:"所选项默认 10 为用户设置默认值，非阵容码解出的资质；未选维度未知。",confirmed:{nature:false,talents:Object.fromEntries(DIMS.map(d=>[d,false])),moves:[]},code_provenance:provenance},side,i);
      });
    }
    function member(input,side,index,legacy=false){
      if(!object(input))throw Error("阵容成员格式无效");const fid=requireForm(input.form_id);
      if(!Array.isArray(input.move_ids)||input.move_ids.length>4)throw Error("初始配招最多 4 个技能槽");
      const moves=input.move_ids.map(x=>x===0||x===null?0:requireMove(x)),filled=moves.filter(x=>x!==0);if(new Set(filled.map(String)).size!==filled.length)throw Error("初始配招不能重复");
      const provenance=codeProvenance(input.code_provenance),original=provenance?.original_member;
      const learned=new Set(sources(fid).map(x=>String(x.id)));if(filled.some(m=>!learned.has(String(m)))&&!(original&&same(original.form_id,fid)&&Array.isArray(original.move_ids)&&filled.every(id=>learned.has(String(id))||original.move_ids.some(old=>same(old,id)))))throw Error("初始配招不在当前学习资料中，请核对快照");
      const nid=requireNature(input.nature_id),ts=talents(input.talents),confirmed={nature:false,talents:{},moves:[]},c=input.confirmed;
      const modifiers=input.nature_modifiers??{up_id:0,down_id:0};if(!object(modifiers))throw Error("后天性格修正无效");for(const k of ["up_id","down_id"])if(integer(modifiers[k],"性格修正",false)>6)throw Error("未知性格修正编号");
      const explicitDirections=modifiers.up_id>0&&modifiers.down_id>0&&modifiers.up_id!==modifiers.down_id;
      if(c!==undefined&&!object(c))throw Error("确认状态格式无效");
      if(c){if(typeof c.nature!=="boolean"||!object(c.talents)||!Array.isArray(c.moves))throw Error("确认状态必须逐项明确");
        confirmed.nature=c.nature;if(c.nature&&nid===null&&!explicitDirections)throw Error("增减方向不完整，不能标为已确认");
        for(const d of DIMS){if(typeof c.talents[d]!=="boolean"||c.talents[d]&&ts[d]===null)throw Error("个体确认状态无效");confirmed.talents[d]=c.talents[d];}
        confirmed.moves=c.moves.map(requireMove);if(new Set(confirmed.moves.map(String)).size!==confirmed.moves.length||confirmed.moves.some(m=>!moves.some(v=>same(m,v))))throw Error("确认配招与所填配招不一致");
      }else{confirmed.nature=!legacy&&side==="my"&&nid!==null;for(const d of DIMS)confirmed.talents[d]=!legacy&&side==="my"&&ts[d]!==null;confirmed.moves=!legacy&&side==="my"?[...filled]:[];}
      const mid=input.member_id?text(input.member_id,"成员标识"):"legacy-"+side+"-"+index+"-"+fid;
      if(["__proto__","constructor","prototype"].includes(mid))throw Error("成员标识使用保留名称");
      const bloodline=input.bloodline_id==null?null:integer(input.bloodline_id,"血脉编号",false);if(bloodline!==null&&bloodline>19)throw Error("未知血脉编号");
      const out={member_id:mid,form_id:fid,nature_id:nid,bloodline_id:bloodline,nature_modifiers:{up_id:modifiers.up_id,down_id:modifiers.down_id},talents:ts,talent_note:input.talent_note===undefined?"":text(input.talent_note,"资质备注",500,true),move_ids:moves,confirmed};
      if(input.talent_selection!=null)out.talent_selection=talentSelection(input.talent_selection);
      const markerValues=(original?.raw_talent_markers||[]).map(v=>Number(v)).filter(v=>Number.isInteger(v)&&v>=79&&v<=84);
      if(out.talent_selection?.selection_source==="team_code_markers"&&markerValues.length>1&&markerValues.every(v=>v===markerValues[0]))out.talent_selection=talentSelection({selected:[],values:{},value_sources:{},selection_source:"team_code_markers",default_value:10});
      if(provenance){provenance.edited_since_import=JSON.stringify(codeConfiguration(out))!==JSON.stringify(codeConfiguration(provenance.original_configuration));out.code_provenance=provenance;out.training_eligible=false;}
      return out;
    }
    function team(input,side,legacy=false){if(!Array.isArray(input)||input.length>6)throw Error("每方最多 6 只精灵");const out=input.map((m,i)=>member(m,side,i,legacy));if(new Set(out.map(m=>m.member_id)).size!==out.length)throw Error("成员标识重复");return out;}
    function action(input,side,teams,legacy=false){
      if(!object(input)||!["move","charge","switch","unknown"].includes(input.kind))throw Error("行动格式无效");
      const fid=requireForm(input.form_id),slot=integer(input.slot,"阵容位置",false);if(slot>=6)throw Error("阵容位置无效");
      const known=teams[side].find((m,i)=>same(m.form_id,fid)&&i===slot);
      const out={member_id:input.member_id?text(input.member_id,"行动成员标识"):known?.member_id||"legacy-"+side+"-"+slot+"-"+fid,form_id:fid,slot,kind:input.kind,received_damage:integer(input.received_damage,"伤害"),energy_before:energy(input.energy_before,"行动前能量"),remaining_energy:energy(input.remaining_energy,"行动后能量"),core_magic_id:coreMagic(input.core_magic_id),evolution_target_form_id:input.evolution_target_form_id==null||input.evolution_target_form_id===""?null:requireForm(input.evolution_target_form_id),first_slot_replaced:null,...hpFields(input),...exactHp(input)};
      if(out.evolution_target_form_id!=null&&out.core_magic_id!==104007)throw Error("进化形态只能随进化之力记录");
      {const replacement=firstSlotReplacement(out.core_magic_id,fid);if(replacement){out.first_slot_replaced={name:replacement.name,power:replacement.power,energy:replacement.energy,priority:replacement.priority,variant_resolved:replacement.variant_resolved,user_note:replacement.user_note===true,original_first_slot:input.original_first_slot==null||input.original_first_slot===""?null:requireMove(input.original_first_slot)};}}
      if(side==="opponent"&&(out.remaining_hp_exact!==null||out.max_hp_exact!==null))throw Error("对方血量只记录整数百分比");
      if(input.kind==="move"){Object.assign(out,mechanicFields(input));out.move_id=requireMove(input.move_id);out.origin=legacy?"unknown":input.origin||"unknown";if(!ORIGINS.includes(out.origin))throw Error("技能来源无效");if(input.confirmed_carried!==undefined&&typeof input.confirmed_carried!=="boolean")throw Error("原配招确认状态无效");out.confirmed_carried=!legacy&&input.confirmed_carried===true;if(out.confirmed_carried!==(out.origin==="carried"))throw Error("原携带技能必须显式确认，临时技能不能确认原携带");}
      if(input.kind==="switch"){out.target_form_id=requireForm(input.target_form_id);out.target_slot=integer(input.target_slot,"换入位置",false);if(out.target_slot>=6||out.target_slot===slot)throw Error("换入位置无效");out.target_member_id=input.target_member_id?text(input.target_member_id,"换入成员标识"):teams[side].find((m,i)=>i===out.target_slot&&same(m.form_id,out.target_form_id))?.member_id||"legacy-"+side+"-"+out.target_slot+"-"+out.target_form_id;}
      if(input.hp_observed_member_id!=null){out.hp_observed_member_id=text(input.hp_observed_member_id,"血量观测成员");if(out.hp_observed_member_id!==out.member_id&&out.hp_observed_member_id!==out.target_member_id)throw Error("血量观测成员与行动无关");}
      return out;
    }
    function marginal(values,key,validator,total=true){
      if(!Array.isArray(values)||values.length>10000)throw Error("候选边缘分布格式无效");const seen=new Set();
      const out=values.map(v=>{if(!object(v))throw Error("候选条目格式无效");const id=validator(v[key]);if(id===null||seen.has(String(id)))throw Error("候选条目未知或重复");seen.add(String(id));return {[key]:id,probability:probability(v.probability)};});
      if(total&&out.length&&Math.abs(out.reduce((s,v)=>s+v.probability,0)-1)>1e-6)throw Error("边缘概率未归一化");return out;
    }
    function belief(input){
      if(!object(input)||(input.probability_source!=="candidate_prior"&&!(input.status==="prior_not_established"&&input.probability_source===null))||input.population_statistics!==false)throw Error("概率必须明确来自候选先验，不能冒充人群统计");
      if(!["ok","consistent","updated","ready","model_mismatch","prior_not_established"].includes(input.status))throw Error("候选推断状态无效");
      const m=object(input.marginals)?input.marginals:input;
      const out={status:input.status,probability_source:"candidate_prior",population_statistics:false,nature_marginal:marginal(m.nature_marginal||[],"nature_id",requireNature),talent_marginals:{},move_marginals:marginal(m.move_marginals||[],"move_id",requireMove,false),candidates:[],last_event_id:input.last_event_id==null?null:text(input.last_event_id,"候选事件"),snapshot_id:input.snapshot_id==null?null:text(input.snapshot_id,"候选快照")};
      if(input.prediction_verified!==undefined&&input.prediction_verified!==false)throw Error("不能把外部预测标为已验证");
      out.prediction_verified=false;
      const models=input.damage_likelihood_models??[],sources=input.damage_prediction_sources??[],tiny=input.underflowed_candidate_ids??[];
      if(!Array.isArray(models)||new Set(models).size!==models.length||models.some(v=>!["uniform_integer_range","explicit_discrete_pmf"].includes(v)))throw Error("伤害预测类型无效");
      if(!Array.isArray(sources)||sources.length>5000||!Array.isArray(tiny)||tiny.length>5000)throw Error("伤害来源或候选精度记录无效");
      out.damage_likelihood_models=[...models];out.damage_prediction_sources=[];
      const sourceKeys=new Set(),sourceSnapshots=new Set();
      for(const source of sources){
        if(!object(source)||source.verified!==false||Object.keys(source).some(k=>!["id","snapshot_id","verified"].includes(k)))throw Error("伤害来源必须保留未验证状态");
        const id=text(source.id,"伤害预测来源"),sid=text(source.snapshot_id,"伤害预测快照"),key=JSON.stringify([id,sid]);
        if(sourceKeys.has(key))throw Error("伤害预测来源重复");sourceKeys.add(key);sourceSnapshots.add(sid);
        out.damage_prediction_sources.push({id,snapshot_id:sid,verified:false});
      }
      if(sourceSnapshots.size>1||out.snapshot_id&&[...sourceSnapshots].some(sid=>sid!==out.snapshot_id))throw Error("伤害预测不能混用不同快照");
      if(models.includes("explicit_discrete_pmf")!==(sources.length>0))throw Error("离散伤害分布必须同时保留预测来源");
      if(out.snapshot_id===null&&sourceSnapshots.size===1)out.snapshot_id=[...sourceSnapshots][0];
      out.underflowed_candidate_ids=tiny.map(id=>text(id,"极小概率候选"));
      if(new Set(out.underflowed_candidate_ids).size!==tiny.length)throw Error("极小概率候选重复");
      if(m.talent_marginals&&!object(m.talent_marginals))throw Error("个体候选格式无效");
      for(const d of Object.keys(m.talent_marginals||{})){if(!DIMS.includes(d))throw Error("候选存在未知资质维度");out.talent_marginals[d]=marginal(m.talent_marginals[d],"value",v=>integer(v,"候选资质",false));}
      if(input.candidates!==undefined){
        if(!Array.isArray(input.candidates)||input.candidates.length>5000)throw Error("联合候选过多或格式无效");
        const seen=new Set();
        for(const c of input.candidates){
          const id=text(c.id,"候选标识");if(seen.has(id))throw Error("候选标识重复");seen.add(id);
          const ts=talents(c.talents);if(DIMS.some(d=>ts[d]===null))throw Error("联合候选必须给出六维资质");
          const nid=requireNature(c.nature_id);if(nid===null)throw Error("联合候选必须给出性格");
          if(!Array.isArray(c.moves)||c.moves.length>4)throw Error("联合候选最多四个有序技能槽；旧候选需核对，不能自动截断");
          const ms=c.moves.map(id=>id===0?0:requireMove(id)),filled=ms.filter(id=>id!==0);
          if(new Set(filled.map(String)).size!==filled.length)throw Error("联合候选配招重复");
          if(c.move_slots_known!==undefined&&typeof c.move_slots_known!=="boolean")throw Error("候选槽位确认状态无效");
          const slotsKnown=c.move_slots_known===true;
          if(slotsKnown&&ms.length!==4)throw Error("已知槽位必须完整保留四槽，包括空槽");
          out.candidates.push({id,nature_id:nid,talents:ts,moves:ms,move_slots_known:slotsKnown,posterior:probability(c.posterior)});
        }
        if(out.candidates.length&&Math.abs(out.candidates.reduce((s,c)=>s+c.posterior,0)-1)>1e-6)throw Error("联合候选概率未归一化");
      }
      if(out.candidates.some(c=>c.posterior>0&&out.underflowed_candidate_ids.includes(c.id)))throw Error("极小概率标记与已显示候选冲突");
      out.move_slots_known=false;out.move_slot_marginals=null;
      if(out.candidates.length){
        const sum=(key,entries)=>{const map=new Map();for(const [value,p]of entries)map.set(String(value),{[key]:value,probability:(map.get(String(value))?.probability||0)+p});return [...map.values()];};
        out.nature_marginal=sum("nature_id",out.candidates.map(c=>[c.nature_id,c.posterior]));
        for(const d of DIMS)out.talent_marginals[d]=sum("value",out.candidates.map(c=>[c.talents[d],c.posterior]));
        out.move_marginals=sum("move_id",out.candidates.flatMap(c=>c.moves.filter(id=>id!==0).map(id=>[id,c.posterior])));
        const positive=out.candidates.filter(c=>c.posterior>0);
        out.move_slots_known=positive.length>0&&positive.every(c=>c.move_slots_known)&&out.underflowed_candidate_ids.length===0;
        if(out.move_slots_known)out.move_slot_marginals=Array.from({length:4},(_,slot)=>({slot,options:sum("move_id",positive.map(c=>[c.moves[slot],c.posterior]))}));
      }
      if(Array.isArray(input.events)&&input.events.length){const id=input.events.at(-1)?.event_id;if(typeof id==="string")out.last_event_id=text(id,"候选事件");}
      out.posterior_scope=input.status==="model_mismatch"?"last_consistent_evidence":"all_evidence";
      return out;
    }
    function draft(input,teams){
      const out={note:"",weather_observation:weatherObservation(input?.weather_observation),my:{},opponent:{}};if(input!==undefined&&!object(input))throw Error("草稿格式无效");out.note=input?.note===undefined?"":text(input.note,"草稿备注",2000,true);
      for(const side of SIDES){const d=input?.[side]||{};if(!object(d))throw Error("行动草稿格式无效");const mid=d.active_member_id||"",target=d.target_member_id||"";if(mid&&!teams[side].some(m=>m.member_id===mid)||target&&!teams[side].some(m=>m.member_id===target))throw Error("草稿精灵不在阵容中");const kind=d.kind||"move",origin=d.origin||"unknown";if(!["move","charge","switch","unknown"].includes(kind)||!ORIGINS.includes(origin))throw Error("草稿行动或来源无效");out[side]={...mechanicFields(d),active_member_id:mid,kind,origin,all_moves:d.all_moves===true,move_id:d.move_id==null||d.move_id===""?null:requireMove(d.move_id),target_member_id:target,received_damage:integer(d.received_damage,"草稿伤害"),remaining_energy:energy(d.remaining_energy,"草稿行动后能量"),core_magic_id:coreMagic(d.core_magic_id),evolution_target_form_id:d.evolution_target_form_id==null||d.evolution_target_form_id===""?null:requireForm(d.evolution_target_form_id),...hpFields(d),...exactHp(d,true)};if(side==="opponent"&&(out[side].remaining_hp_exact!==null||out[side].max_hp_exact!==null))throw Error("对方血量只记录整数百分比");if(Object.hasOwn(d,"hp_observed_member_id")){const observed=d.hp_observed_member_id;if(observed!=null&&(!teams[side].some(m=>m.member_id===observed)))throw Error("草稿血量观测成员不在阵容中");out[side].hp_observed_member_id=observed==null?null:text(observed,"草稿血量观测成员");}}
      return out;
    }
    function session(input){
      if(!object(input)||![1,2].includes(input.schema_version)||!object(input.teams)||!Array.isArray(input.rounds)||input.rounds.length>2000)throw Error("对局格式无效或记录过多");
      const legacy=input.schema_version===1,teams={};for(const side of SIDES)teams[side]=team(input.teams[side],side,legacy);
      const allMembers=[...teams.my,...teams.opponent];if(new Set(allMembers.map(m=>m.member_id)).size!==allMembers.length)throw Error("双方成员标识必须唯一");
      const out={schema_version:2,match_id:input.match_id?text(input.match_id,"对局标识"):"migrated-"+(input.snapshot_id||"unknown"),revision:integer(input.revision??0,"局面版本",false),snapshot_id:input.snapshot_id==null?null:text(input.snapshot_id,"资料快照"),teams,rounds:[],opponent_beliefs:{},draft:draft(legacy?undefined:input.draft,teams)};
      if(input.opening_full_hp!==undefined&&typeof input.opening_full_hp!=="boolean")throw Error("开局血量依据无效");out.opening_full_hp=input.opening_full_hp??(input.rounds.length===0&&!input.legacy_payload&&!legacy);Object.assign(out,BattleMechanics.validateState({...input,teams},catalog));
      if(legacy||input.legacy_payload!==undefined){const original=legacy?input:input.legacy_payload;if(!object(original)||JSON.stringify(original).length>4*1024*1024)throw Error("旧版原始记录过大或无效");out.legacy_payload=clone(original);}
      const ids=new Set();for(const r of input.rounds){if(!object(r))throw Error("回合格式无效");const id=text(r.event_id,"回合标识");if(ids.has(id))throw Error("重复回合标识");ids.add(id);text(r.recorded_at,"记录时间");if(!Number.isFinite(Date.parse(r.recorded_at)))throw Error("记录时间无效");const turn=integer(r.turn??out.rounds.length+1,"回合序号",false);if(turn<1||turn<=(out.rounds.at(-1)?.turn||0))throw Error("回合序号必须递增");
        let ts=null;if(r.teams_snapshot!=null){if(!object(r.teams_snapshot))throw Error("历史配置快照无效");ts={};for(const side of SIDES)ts[side]=team(r.teams_snapshot[side],side,false);}
        const rr={event_id:id,recorded_at:r.recorded_at,turn,snapshot_id:r.snapshot_id==null?out.snapshot_id:text(r.snapshot_id,"回合快照"),note:text(r.note??"","回合备注",2000,true),teams_snapshot:ts,configuration_provenance:ts?"recorded_at_turn":"legacy_configuration_unknown"};
        for(const side of SIDES){rr[side]=action(r[side],side,ts||teams,legacy);if(ts){const a=rr[side],m=ts[side][a.slot];if(!m||m.member_id!==a.member_id||!same(m.form_id,a.form_id))throw Error("行动与历史配置快照不符");if(a.kind==="switch"){const t=ts[side][a.target_slot];if(!t||t.member_id!==a.target_member_id||!same(t.form_id,a.target_form_id))throw Error("换入与历史配置快照不符");}}}
        rr.opening_full_hp=r.opening_full_hp===true;rr.weather_observation=weatherObservation(r.weather_observation);
        if(r.mechanics_before!=null){if(!ts)throw Error("技能变化缺少回合配置快照");rr.mechanics_before=BattleMechanics.validateState({...r.mechanics_before,teams:ts},catalog);}
        if(r.mechanics_after!=null){if(!ts)throw Error("技能变化缺少回合配置快照");rr.mechanics_after=BattleMechanics.validateState({...r.mechanics_after,teams:ts},catalog);}
        if(r.mechanic_events!=null){if(!Array.isArray(r.mechanic_events)||JSON.stringify(r.mechanic_events).length>500000)throw Error("技能变化事件过大");rr.mechanic_events=clone(r.mechanic_events);}
        if(r.mechanic_warnings!=null){if(!Array.isArray(r.mechanic_warnings))throw Error("技能变化提示无效");rr.mechanic_warnings=r.mechanic_warnings.map(v=>text(v,"变化提示",2000,true));}
        if(r.energy_events!=null){if(!Array.isArray(r.energy_events)||JSON.stringify(r.energy_events).length>100000)throw Error("能量事件无效或过大");rr.energy_events=clone(r.energy_events);}
        out.rounds.push(rr);
      }
      if(input.opponent_beliefs!==undefined){if(!object(input.opponent_beliefs))throw Error("对方候选格式无效");for(const [mid,b] of Object.entries(input.opponent_beliefs)){if(!teams.opponent.some(m=>m.member_id===mid))throw Error("候选引用未知成员");out.opponent_beliefs[mid]=belief(b);}}
      return out;
    }
    function storage(input){
      if(!object(input)||input.storage_version!==2||!Array.isArray(input.templates)||input.templates.length>100)throw Error("存档格式无效");
      const out={storage_version:2,session:session(input.session),templates:[],active_template_id:null},ids=new Set();
      for(const t of input.templates){if(!object(t))throw Error("阵容模板无效");const id=text(t.id,"模板标识");if(ids.has(id))throw Error("模板标识重复");ids.add(id);out.templates.push({id,name:text(t.name,"模板名称",60),team:team(t.team,"my"),snapshot_id:t.snapshot_id==null?null:text(t.snapshot_id,"模板快照"),updated_at:text(t.updated_at,"模板保存时间")});}
      if(input.active_template_id!=null){if(!ids.has(input.active_template_id))throw Error("当前模板标识无效");out.active_template_id=input.active_template_id;}return out;
    }
    return {form,move,natures,sources,member,team,belief,session,storage,draft,importCode,codeConfiguration};
  }
  return {create,DIMS,LABELS,BLOODLINES,BLOODLINE_TINTS,MODIFIERS,SIDES,ORIGINS,CORE_MAGICS,CORE_MAGIC_USER_NOTES,WISH_STRIKE,firstSlotReplacement,clone,same,name,zh,integer,probability,hpPercent,exactHp,coreMagic,energy,talentSelection,selectionFromMarkers,effectiveDirections,hpPanel,configuredMaxHp,reverseHpConfigurations,confirmedMoves,configuredMoves,temporaryMoves,latestHpObservations,latestEnergyObservations,WEATHER_NAMES,weatherObservation,mechanicFields};
})();

if(typeof document!=="undefined") (() => {
  const KEY="roco_pvp.battle.v2",OLD="roco-pvp-field-notes-v1";
  const {DIMS,LABELS,BLOODLINES,BLOODLINE_TINTS,MODIFIERS,SIDES,CORE_MAGICS,CORE_MAGIC_USER_NOTES,WISH_STRIKE,firstSlotReplacement,clone,same,name,zh}=BattleData;
  const $=id=>document.getElementById(id),uid=()=>crypto.randomUUID();
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const button=(text,fn,cls="small")=>{const b=el("button",text,cls);b.type="button";b.onclick=()=>guard(fn);return b;};
  const option=(value,text)=>{const o=el("option",text);o.value=value;return o;};
  const field=(label,node)=>{const x=el("label",null,"field");x.append(el("span",label),node);return x;};
  const pct=x=>(x*100).toLocaleString("zh-CN",{maximumFractionDigits:1})+"%";
  const originNames={unknown:"来源未确认",carried:"确认原携带",copied:"复制",borrowed:"借用",generated:"临时生成"};
  let catalog,data,app,currentSnapshot,blocked=false,lastSaved=null,editor=null,adviceToken=0,unavailableReason=null,damageInference={members:[],blockers:[]},damageInferenceKey=null,damageInferenceToken=0,damageInferenceTimer=null;
  let toastTimer;
  const expandedMembers=new Set();
  function toast(s){$("toast").textContent=s;$("toast").classList.add("visible");clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("toast").classList.remove("visible"),4500);}
  function guard(fn){try{const r=fn();if(r?.catch)r.catch(e=>toast(e.message));}catch(e){toast(e.message);}}
  async function json(url){const r=await fetch(url,{cache:"no-store"});if(!r.ok)throw Error("服务请求失败："+r.status);return r.json();}
  function fresh(my=[]){const s={opening_full_hp:true,schema_version:2,match_id:uid(),revision:0,snapshot_id:currentSnapshot,teams:{my:clone(my),opponent:[]},rounds:[],opponent_beliefs:{}};s.draft=data.draft(undefined,s.teams);return s;}
  function download(value,filename){const blob=new Blob([typeof value==="string"?value:JSON.stringify(value,null,2)],{type:"application/json"}),u=URL.createObjectURL(blob),a=el("a");a.href=u;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(u),5000);}
  function writable(){if(blocked)throw Error("存档保护已开启。请先导出当前内容，再按提示恢复或刷新页面。");}
  function persist(change=true){writable();if(localStorage.getItem(KEY)!==lastSaved){protect("存档已在其他页面变化，本页暂停覆盖。",null);throw Error("请导出当前页面后刷新。");}if(change)app.session.revision++;const valid=data.storage(app),raw=JSON.stringify(valid);try{localStorage.setItem(KEY,raw);}catch(e){protect("浏览器未能保存："+e.message,null);throw e;}lastSaved=raw;adviceToken++;if(unavailableReason)showUnavailable();else $("advice-content").replaceChildren(el("p","局面已更新，原建议已失效。","advice-note"),button("刷新建议",refreshAdvice));}
  function showUnavailable(){$("model-badge").textContent="尚未训练";const reason=el("h3","策略模型尚未训练，暂无行动建议。");reason.title=unavailableReason;$("advice-content").replaceChildren(reason,el("p","训练完成后显示行动概率与可能后果。","advice-note"));}
  function protect(message,raw){blocked=true;const b=$("error-banner");b.hidden=false;b.replaceChildren(el("strong",message),el("p","原始存档保持不变。导出备份后可刷新页面；无法解析的存档不会被新内容覆盖。"));
    const controls=el("div",null,"recovery-actions");if(raw!=null)controls.append(button("导出原始存档",()=>download(raw,"roco-recovery.json")));
    controls.append(button("导出当前页面",()=>download(app.session,"roco-current-session.json")));
    if(raw!=null)controls.append(button("备份原存档并开始新档",()=>{if(!confirm("将在独立备份键保留原始存档，并开始新档。继续？"))return;localStorage.setItem(KEY+".recovery."+Date.now(),raw);lastSaved=localStorage.getItem(KEY);blocked=false;app={storage_version:2,session:fresh(),templates:[],active_template_id:null};persist(false);b.hidden=true;render();},"danger small"));
    b.append(controls);
  }
  function load(){app={storage_version:2,session:fresh(),templates:[],active_template_id:null};let raw=null;try{raw=localStorage.getItem(KEY);if(raw!==null){app=data.storage(JSON.parse(raw));lastSaved=raw;}else{const old=localStorage.getItem(OLD);if(old){app.session=data.session(JSON.parse(old));app.session.match_id=uid();toast("已读取旧手札副本，原内容保留在 legacy_payload；旧存档不会被改写。");}persist(false);}}catch(e){protect("存档读取失败："+e.message,raw??localStorage.getItem(OLD));}}
  function directionLabel(nid,mods){const n=data.natures.get(String(nid)),up=MODIFIERS[mods?.up_id]||n?.up,down=MODIFIERS[mods?.down_id]||n?.down;return (LABELS[up]||"未知")+"↑ / "+(LABELS[down]||"未知")+"↓";}
  function top(a){return [...(a||[])].sort((a,b)=>b.probability-a.probability)[0];}
  function usableBelief(m){const b=app.session.opponent_beliefs[m.member_id];if(!b)return null;if(["model_mismatch","prior_not_established"].includes(b.status))return null;if(b.snapshot_id&&b.snapshot_id!==currentSnapshot)return null;return b;}
  function fact(label,value,confirmed,p){const row=el("div",null,"fact-row "+(confirmed?"confirmed":"uncertain"));row.append(el("span",label,"fact-label"),el("span",value));if(p!=null)row.append(el("small",pct(p),"fact-prob"));else if(confirmed)row.append(el("small","已确认","fact-prob"));return row;}
  function active(side){return app.session.teams[side].find(m=>m.member_id===app.session.draft[side].active_member_id);}
  function bloodlineBadge(id){const known=id!==null&&id!==undefined&&BLOODLINES[id]!=null;const badge=el("span",known?BLOODLINES[id]:"血脉未填","blood-badge"+(known?"":" empty"));if(known)badge.setAttribute("style","background:"+(BLOODLINE_TINTS[id]||BLOODLINE_TINTS[0]));badge.setAttribute("title",known?"血脉 "+BLOODLINES[id]+"（"+id+"）":"尚未填写血脉");return badge;}
  function evolutionCandidates(formId){const f=data.form(formId);if(!f)return [];const base=name(f),number=f.number;return catalog.forms.filter(x=>!same(x.id,f.id)&&same(x.number,number)&&(name(x).includes(base)||base.includes(name(x)))).map(x=>({id:x.id,name:name(x)}));}
  function usedMoves(side,mid){const all=new Map();for(const r of app.session.rounds){const a=r[side];if(a.member_id!==mid||a.kind!=="move")continue;const k=String(a.move_id);if(!all.has(k))all.set(k,{id:a.move_id,origins:new Set(),carried:false});all.get(k).origins.add(a.origin||"unknown");all.get(k).carried ||= a.confirmed_carried===true;}return [...all.values()];}
  function damageResult(mid){return damageInference.members?.find(row=>row.member_id===mid);}
  async function refreshDamageInference(key){const token=++damageInferenceToken;try{const response=await fetch("/api/inference/damage",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session:app.session})}),payload=await response.json();if(token!==damageInferenceToken||key!==damageInferenceKey)return;if(!response.ok)throw Error(payload.error||"伤害反推服务不可用");if(!Array.isArray(payload.members)||!Array.isArray(payload.blockers))throw Error("伤害反推结果格式无效");damageInference=payload;}catch(error){if(token===damageInferenceToken)damageInference={members:[],blockers:[error.message]};}if(token===damageInferenceToken)renderTeam("opponent");}
  function scheduleDamageInference(){if(typeof window==="undefined")return;const key=JSON.stringify({snapshot_id:app.session.snapshot_id,teams:app.session.teams,rounds:app.session.rounds});if(key===damageInferenceKey)return;damageInferenceKey=key;clearTimeout(damageInferenceTimer);damageInferenceTimer=setTimeout(()=>refreshDamageInference(key),0);}
  function moveIcon(id){const img=document.createElement("img");img.className="move-icon";img.alt="";img.loading="lazy";img.src="/roco-skill-icons/"+encodeURIComponent(id)+".png";img.onerror=()=>img.remove();return img;}
  function renderTeam(side){const wrap=$(side+"-team");wrap.replaceChildren();const team=app.session.teams[side],observations=BattleData.latestHpObservations(app.session,side),energies=BattleData.latestEnergyObservations(app.session,side);$(side+"-count").textContent=team.length+"/6";$("add-"+side).disabled=team.length>=6;
    for(const [idx,m] of team.entries()){const f=data.form(m.form_id),b=side==="opponent"?usableBelief(m):null,card=el("article",null,"member"+(active(side)?.member_id===m.member_id?" is-active":"")),head=el("div",null,"member-head");
      const portrait=el("img",null,"portrait");portrait.src="/roco-pet-avatars-id/"+encodeURIComponent(f.id)+".png";portrait.alt="";portrait.loading="lazy";portrait.onerror=()=>{portrait.onerror=null;try{const u=new URL(f.portrait_url||"");if(u.protocol==="https:"&&u.hostname==="patchwiki.biligame.com"){portrait.src=u.href;return;}}catch{}portrait.remove();};head.append(portrait);
      const title=el("div",null,"member-title");title.append(el("strong",(idx+1)+". "+name(f)));const types=el("div");for(const t of f.types||[])types.append(el("span",t,"type"));types.append(bloodlineBadge(m.bloodline_id));title.append(types);head.append(title);card.append(head);
      let hp=observations.get(m.member_id);const configuredMax=side==="my"?BattleData.configuredMaxHp(m,f,data.natures):null;if(hp?.status==="initial"&&configuredMax!=null)hp={...hp,exact_remaining:configuredMax,exact_max:configuredMax};const known=["observed","initial"].includes(hp?.status),en=energies.get(m.member_id),health=el("div",null,"member-health"),caption=el("div",null,"hp-caption"),track=el("div",null,"hp-track"),fill=el("div",null,"hp-fill"),hpText=known?(hp.exact_max!=null?hp.exact_remaining+" / "+hp.exact_max+" · "+hp.value+"%":hp.value===0?"0% · 已倒下":hp.value+"%"):hp?"血量待重新确认":"血量未知";caption.append(el("strong",hpText),el("small",hp?.status==="initial"?"开局满血":hp?"最近记录 · 第 "+hp.turn+" 回合":"尚无血量记录"));track.setAttribute("aria-label",name(f)+"最近记录血量");if(known){track.setAttribute("role","progressbar");track.setAttribute("aria-valuemin","0");track.setAttribute("aria-valuemax","100");track.setAttribute("aria-valuenow",String(hp.value));}fill.setAttribute("style","width:"+(known?hp.value:0)+"%");track.append(fill);health.append(caption,track,el("span",en?.value==null?"能量待确认":"能量 "+en.value+"/10","member-energy"));card.append(health);
      const controls=el("div",null,"member-tools");controls.append(button("编辑",()=>openEditor(side,m.member_id)),button(active(side)?.member_id===m.member_id?"当前在场":"设为在场",()=>{writable();if(app.session.draft[side].active_member_id!==m.member_id){clearDraftHp(app.session.draft[side]);clearDraftEnergy(app.session.draft[side]);}app.session.draft[side].active_member_id=m.member_id;app.session.draft[side].move_id=null;app.session.draft[side].skill_mode="carried";app.session.draft[side].generator_slot=null;persist();render();}),button("移除",()=>{writable();if(!confirm("移除此成员？已记录回合保留原配置。"))return;app.session.teams[side]=team.filter(x=>x.member_id!==m.member_id);delete app.session.slot_overrides?.[m.member_id];delete app.session.pending_transforms?.[m.member_id];delete app.session.opponent_beliefs[m.member_id];const d=app.session.draft[side];if(d.active_member_id===m.member_id){d.active_member_id="";d.move_id=null;}if(d.target_member_id===m.member_id)d.target_member_id="";persist();render();},"small quiet"));card.append(controls);
      const config=el("div",null,"member-config"),joint=b?.candidates.length?[...b.candidates].sort((a,b)=>b.posterior-a.posterior)[0]:null,nc=m.confirmed.nature,nt=top(b?.nature_marginal),nid=nc?m.nature_id:joint?.nature_id??nt?.nature_id??m.nature_id;
      if(side==="my")config.append(fact("增减方向",directionLabel(m.nature_id,m.nature_modifiers),nc));
      else config.append(fact("性格",nid==null?"未知":name(data.natures.get(String(nid)))+(nc?"":joint?" · 联合候选":nt?" · 单项推测":m.code_provenance?" · 码内配置":" · 手填假设"),nc,nc||joint?null:nt?.probability));
      if(side!=="my"&&(m.nature_modifiers?.up_id||m.nature_modifiers?.down_id))config.append(fact("后天修正",directionLabel(m.nature_id,m.nature_modifiers),false));
      if(joint)config.append(el("small","未确认字段来自同一完整候选 · 联合概率 "+pct(joint.posterior),"inference-note uncertain"));
      const ts=el("div",null,"talent-grid");if(m.talent_selection){const s=m.talent_selection;config.append(el("small","个体三选六 · "+s.selected.length+" / 3"+(s.selected.length<3?" · 尚待补选":""),"inference-note"));for(const d of DIMS)ts.append(fact(LABELS[d],s.selected.includes(d)?s.values[d]+(s.value_sources[d]==="user_default"?" · 用户默认":" · 手动设置"):"未选 / 未知",false));config.append(ts);if(DIMS.some(d=>m.talents[d]!==null)){const old=el("details");old.append(el("summary","历史六维资质（原样保留）"),el("p",DIMS.map(d=>LABELS[d]+" "+(m.talents[d]??"未知")).join(" / ")));config.append(old);}}else{for(const d of DIMS){const c=m.confirmed.talents[d],t=top(b?.talent_marginals[d]),v=c?m.talents[d]:joint?.talents[d]??t?.value??m.talents[d];ts.append(fact(LABELS[d],v==null?"未知":String(v),c,c||joint?null:t?.probability));}config.append(ts);}
      const chips=el("div",null,"move-chips");BattleMechanics.currentMoves(app.session,m).forEach((mid,i)=>{const pending=app.session.pending_transforms?.[m.member_id]?.[i],changed=!!app.session.slot_overrides?.[m.member_id]&&!same(mid,m.move_ids[i]),c=changed||m.confirmed.moves.some(x=>same(x,mid));const chipLabel=(i+1)+" · "+(mid===0?"空槽":name(data.move(mid))+" · "+(pending?"巧变结果待选择":changed?"本局替换":c?"确认携带":m.code_provenance?"码内配置":"手填假设")),chip=el("span",null,"move-chip "+(c?"confirmed":"uncertain")),icon=mid?moveIcon(mid):null;if(icon)chip.append(icon);chip.append(el("span",chipLabel));chips.append(chip);});if(!m.move_ids.length)chips.append(el("span","原配招未知","uncertain"));config.append(chips);
      if(m.code_provenance){const p=m.code_provenance,details=el("details",null,"code-provenance");details.append(el("summary",(p.edited_since_import?"已手动修改 · 原码保留":"阵容码配置 · 未经完整验证")+" · 禁入正式训练"));details.append(el("p","原始标记："+JSON.stringify(p.original_member.raw_talent_markers)+"；完整资质未知。"),el("p","原性格："+(p.original_member.nature?.original?.name||"未指定")+"；原后天修正："+JSON.stringify(p.original_member.nature?.modifiers)),el("p","核心魔法："+(p.core_magic?.name||"名称待核实")+"（"+p.core_magic?.id+"） · 队伍类型 "+p.team_type_id),el("p","快照："+p.snapshot_id));for(const issue of p.issues.filter(x=>x.member_slot==null||x.member_slot===p.original_member.slot))details.append(el("p",issue.message));details.append(button("查看原始解析",()=>download(p,"roco-code-source-"+m.member_id+".json")));config.append(details);}
      const used=usedMoves(side,m.member_id);for(const v of used)config.append(el("div",name(data.move(v.id))+" · 100% 已使用 · "+(v.carried?"确认原携带":[...v.origins].map(x=>originNames[x]).join(" / ")),"move-chip used"));
      if(b){const ms=[...b.move_marginals].sort((x,y)=>y.probability-x.probability);if(ms.length){config.append(el("small","技能携带的单项概率（不代表一套配招）","inference-note"));const list=el("div",null,"move-chips");for(const v of ms)if(!m.confirmed.moves.some(x=>same(x,v.move_id)))list.append(el("span",name(data.move(v.move_id))+" "+pct(v.probability),"move-chip uncertain"));config.append(list);}
        if(b.candidates.length){const c=[...b.candidates].sort((x,y)=>y.posterior-x.posterior)[0],conflict=(nc&&!same(c.nature_id,m.nature_id))||DIMS.some(d=>m.confirmed.talents[d]&&c.talents[d]!==m.talents[d])||m.confirmed.moves.some(x=>!c.moves.some(y=>same(x,y)));const details=el("details",null,"uncertain");details.append(el("summary","最高联合候选 · "+pct(c.posterior)+(conflict?" · 与确认信息冲突":"")));details.append(el("p",name(data.natures.get(String(c.nature_id)))+"；"+DIMS.map(d=>LABELS[d]+" "+c.talents[d]).join(" / ")+"；"+c.moves.map(x=>x===0?"空槽":name(data.move(x))).join("、")));config.append(details);}
        if(b.damage_likelihood_models.length)config.append(el("p","伤害概率由调用方提供，尚未实战校准。"+(b.damage_likelihood_models.includes("uniform_integer_range")?"历史伤害区间按均匀分布计算。":""),"inference-note"));
        if(b.underflowed_candidate_ids.length)config.append(el("p","另有极小概率候选未显示；它们尚未被排除，显示的 100% 不代表绝对确定。","inference-note"));
        config.append(el("p","条件于导入候选先验，不是热门阵容统计。"+(app.session.rounds.length&&b.last_event_id!==app.session.rounds.at(-1).event_id?"尚未根据最新回合重算。":""),"inference-note"));
      }else if(side==="opponent"){const raw=app.session.opponent_beliefs[m.member_id];config.append(el("p",raw?"候选与当前记录或资料不一致，暂停显示概率。":"尚无候选先验，性格、资质和配招概率未知。","inference-note"));}
      const inferred=side==="opponent"?damageResult(m.member_id):null;if(inferred){const detail=el("details",null,"uncertain");detail.append(el("summary",inferred.status==="ready"?"伤害反推 · "+inferred.combination_count+" 种可能组合":"伤害反推 · 当前公式无匹配组合"));for(const observation of inferred.observations)detail.append(el("p","第 "+observation.turn+" 回合 · "+observation.move_name+" · "+(observation.role==="attacker"?"由挨打反推 ":"由打对方反推 ")+LABELS[observation.dimension]+" · 伤害 "+observation.observed_damage));for(const group of inferred.groups){const values=Object.entries(group.talent_value_options).map(([dim,options])=>LABELS[dim]+" "+options.join(" / ")).join("；");const cases=el("details");cases.append(el("summary",group.nature_name+"："+values+"（"+group.combination_count+" 种）"));for(const c of group.selection_cases||[])cases.append(el("p","选择 "+c.selected.map(d=>LABELS[d]).join(" / ")+"："+Object.entries(c.value_options).map(([d,vs])=>LABELS[d]+" ["+vs.join(" / ")+"]").join("；")+"（"+c.combination_count+" 种，三项取值任意组合）"));detail.append(cases);}detail.append(el("small","已列出全部相容性格、三选六方案及数值组合；未观测项保留全部可能，未选项与选中为0分开。天梯占比不能当作这些组合的联合概率，因此不虚构概率。","inference-note"),el("small","当前按项目保存的60级五星候选公式反推；未记录的天气、能力变化、特性或减伤会造成无匹配或错误候选。","inference-note"));config.append(detail);}
      // Keep the full evidence view intact; the default card is a battle overview.
      const compact=el("div",null,"member-overview"),meta=el("div",null,"member-meta");
      const natureText=side==="my"?directionLabel(m.nature_id,m.nature_modifiers):nid==null?"性格未知":name(data.natures.get(String(nid)));
      const natureSummary=el("span",natureText+(!nc&&(joint||nt)?" "+pct(joint?.posterior??nt.probability):""),"compact-nature "+(nc?"confirmed":"uncertain"));
      natureSummary.title=joint?"最高联合候选 · "+pct(joint.posterior):"性格 · "+natureText;
      meta.append(natureSummary);
      const selection=m.talent_selection;
      const talentText=selection?selection.selected.map(d=>LABELS[d]+selection.values[d]).join(" / "):DIMS.filter(d=>(m.confirmed.talents[d]?m.talents[d]:joint?.talents[d]??top(b?.talent_marginals[d])?.value??m.talents[d])!=null).map(d=>LABELS[d]+(m.confirmed.talents[d]?m.talents[d]:joint?.talents[d]??top(b?.talent_marginals[d])?.value??m.talents[d])).join(" / ");
      const talentSummary=el("span",null,"compact-talents");talentSummary.title=talentText||"资质未知";const visibleDims=selection?selection.selected:DIMS.filter(d=>(m.confirmed.talents[d]?m.talents[d]:joint?.talents[d]??top(b?.talent_marginals[d])?.value??m.talents[d])!=null);visibleDims.forEach((d,i)=>{if(i)talentSummary.append(el("span"," / "));const v=selection?selection.values[d]:m.confirmed.talents[d]?m.talents[d]:joint?.talents[d]??top(b?.talent_marginals[d])?.value??m.talents[d];talentSummary.append(el("span",LABELS[d]+v,m.confirmed.talents[d]?"confirmed":"uncertain"));});if(!visibleDims.length)talentSummary.append(el("span","资质未知","uncertain"));meta.append(talentSummary);
      const overviewMoves=el("div",null,"overview-moves"),slots=BattleMechanics.currentMoves(app.session,m);
      for(let i=0;i<4;i++){const carried=slots[i]||0,mid=carried||joint?.moves?.[i]||0,seen=used.some(v=>same(v.id,mid)),confirmed=!!carried&&(m.confirmed.moves.some(x=>same(x,mid))||!!app.session.slot_overrides?.[m.member_id]&&!same(mid,m.move_ids[i]));const chip=el("span",(i+1)+"·"+(mid?name(data.move(mid)):"空槽")+(seen?" ✓":""),"overview-move "+(confirmed?"confirmed":"uncertain"));chip.title=(mid?name(data.move(mid)):"空槽")+(seen?" · 已使用":"")+(!carried&&mid?" · 最高联合候选 "+pct(joint.posterior):"");overviewMoves.append(chip);}
      compact.append(meta,overviewMoves);
      const details=el("details",null,"member-details"),summary=el("summary","详情");summary.setAttribute("aria-label",name(f)+"配置详情");details.append(summary,config,controls.lastChild);details.open=expandedMembers.has(m.member_id);details.ontoggle=()=>{if(details.open)expandedMembers.add(m.member_id);else expandedMembers.delete(m.member_id);};
      head.append(controls);health.title=caption.textContent;card.append(compact,details);wrap.append(card);
    }
    if(side==="opponent"&&damageInference.blockers?.length){const detail=el("details",null,"mechanic-hint");detail.append(el("summary","未用于伤害反推的记录 · "+damageInference.blockers.length));for(const value of damageInference.blockers)detail.append(el("p",value));wrap.append(detail);}
    for(let i=team.length;i<6;i++)wrap.append(button("+ 添加第 "+(i+1)+" 只精灵",()=>openEditor(side),"slot-add"));
  }
  function renderTemplates(){const select=$("template-select");select.replaceChildren(option("","选择阵容模板"));for(const t of app.templates)select.append(option(t.id,t.name));select.value=app.active_template_id||"";}
  function clearDraftHp(d){d.remaining_hp_percent=null;d.remaining_hp_exact=null;d.max_hp_exact=null;delete d.remaining_hp;delete d.remaining_hp_unit;delete d.legacy_remaining_hp_percent;delete d.hp_observed_member_id;}
  function clearDraftEnergy(d){d.remaining_energy=null;}
  function mutateDraft(side,key,value,rerender=false){writable();const d=app.session.draft[side];if(["kind","target_member_id"].includes(key)&&d[key]!==value){clearDraftHp(d);clearDraftEnergy(d);}if(key==="response_success"&&d[key]!==value){clearDraftEnergy(d);clearDraftEnergy(app.session.draft[side==="my"?"opponent":"my"]);}d[key]=value;persist();if(rerender)render();else refreshAdvice();}
  function energyProjection(){const out={events:[]};for(const side of SIDES){const d=app.session.draft[side],member=d.kind==="switch"?app.session.teams[side].find(m=>m.member_id===d.target_member_id):active(side),before=member?BattleData.latestEnergyObservations(app.session,side).get(member.member_id)?.value:null;let after=before;const replacement=member?firstSlotReplacement(d.core_magic_id,member.form_id):null,slots=member?BattleMechanics.currentMoves(app.session,member):[],hitsFirst=!!(replacement&&d.kind==="move"&&same(d.move_id,slots[0]));if(after!=null&&d.kind==="move"&&data.move(d.move_id)){const cost=hitsFirst?replacement.energy:BattleData.integer(data.move(d.move_id).energy??0,"技能基础能耗",false);after=Math.max(0,after-cost);}else if(after!=null&&d.kind==="charge")after=Math.min(10,after+5);out[side]={member_id:member?.member_id??null,before,after,first_slot_replaced:hitsFirst?replacement:null,first_slot_move:slots[0]??0};}
    for(const side of SIDES){const d=app.session.draft[side],meta=d.kind==="move"&&d.response_success?catalog.action_mechanics?.response_energy?.[d.move_id]:null;if(!meta)continue;for(const effect of meta.effects||[]){const target=effect.target==="opponent"?(side==="my"?"opponent":"my"):side,entry=out[target];if(entry.after==null)continue;const before=entry.after;if(effect.op==="energy.reduce")entry.after=Math.max(0,before-effect.amount);else if(effect.op==="energy.restore")entry.after=Math.min(10,before+effect.amount);else continue;out.events.push({source_side:side,target_side:target,skill_id:d.move_id,op:effect.op,amount:effect.amount,before,after:entry.after,when:"response.success",policy:meta.policy});}}
    for(const side of SIDES)if(app.session.draft[side].remaining_energy!=null)out[side].after=BattleData.energy(app.session.draft[side].remaining_energy,"行动后能量");return out;
  }
  const modeNames={borrow:"借用",mind_read:"取念",rewrite:"复写",temporary:"临时技能（巧变）"};
  function configuredCoreMagic(side){const ids=[...new Set(app.session.teams[side].map(m=>m.code_provenance?.core_magic?.id).filter(id=>Object.hasOwn(CORE_MAGICS,id)))];return ids.length===1?ids[0]:null;}
  function configuredHpMember(side,d=app.session.draft[side]){return d.kind==="switch"?app.session.teams[side].find(m=>m.member_id===d.target_member_id):active(side);}
  function configuredHpMax(side,d=app.session.draft[side]){const m=configuredHpMember(side,d);return side==="my"&&m?BattleData.configuredMaxHp(m,data.form(m.form_id),data.natures):null;}
  function selectionPool(side,m,d){const mode=d.skill_mode||"carried",pool=BattleMechanics.getPool(catalog,catalog.action_mechanics,app.session,side,m,mode,mode==="carried"?null:d.generator_slot??null);if(side==="opponent"&&mode==="carried"&&m)pool.ids=[...new Set([...pool.ids,...data.sources(m.form_id).map(x=>x.id)])];return pool;}
  function renderAction(side){const wrap=$(side+"-action"),d=app.session.draft[side],team=app.session.teams[side];wrap.replaceChildren(el("h3",side==="my"?"我方行动":"对方行动"));const current=el("select");current.append(option("","选择当前在场精灵"));for(const m of team)current.append(option(m.member_id,name(data.form(m.form_id))));current.value=d.active_member_id;current.onchange=()=>guard(()=>{writable();clearDraftHp(d);clearDraftEnergy(d);d.active_member_id=current.value;d.move_id=null;d.skill_mode="carried";d.generator_slot=null;persist();render();});wrap.append(field("当前在场",current));
    const kind=el("select");for(const [id,label]of [["move","使用技能"],["charge","聚能（+5）"],["switch","换人"],["unknown","行动未知"]])kind.append(option(id,label));kind.value=d.kind;kind.onchange=()=>guard(()=>mutateDraft(side,"kind",kind.value,true));wrap.append(field("实际行动",kind));
    if(d.kind==="move"){
      const m=active(side),mode=d.skill_mode||"carried",modes=el("div",null,"skill-modes");
      for(const [key,label] of Object.entries(modeNames)){const available=BattleMechanics.getPool(catalog,catalog.action_mechanics,app.session,side,m,key);if(!available.source_slots.length)continue;const check=el("input");check.type="checkbox";check.checked=mode===key;check.onchange=()=>guard(()=>{writable();d.skill_mode=check.checked?key:"carried";d.generator_slot=null;d.move_id=null;d.response_success=false;d.response_choice=false;persist();render();});const row=el("label",null,"checkline");row.append(check,el("span",label));modes.append(row);}
      if(modes.children.length)wrap.append(modes);
      const pool=selectionPool(side,m,d),slots=m?BattleMechanics.currentMoves(app.session,m):[];
      if(mode!=="carried"){const hints={borrow:"仅队友当前携带的技能（不含自己）",mind_read:"对方全队学习技能池的并集",rewrite:"自己的学习池，排除当前携带技能",temporary:"仅此前巧变对应的候选池；使用后恢复原槽"};wrap.append(el("small",hints[mode],"mechanic-hint"));}
      for(const message of pool.blockers)if(m)wrap.append(el("small",message,"mechanic-hint"));
      const sources=mode==="carried"?pool.source_slots.filter(x=>same(x.move_id,d.move_id)):BattleMechanics.getPool(catalog,catalog.action_mechanics,app.session,side,m,mode).source_slots;
      if(sources.length>1){const source=el("select");source.append(option("","选择来源技能槽"));for(const x of sources)source.append(option(x.slot,"槽 "+(x.slot+1)+" · "+name(data.move(x.move_id))));source.value=d.generator_slot??"";source.onchange=()=>guard(()=>{writable();d.generator_slot=source.value===""?null:Number(source.value);if(mode!=="carried")d.move_id=null;persist();render();});wrap.append(field("来源技能槽",source));}
      const select=el("select");select.append(option("","选择实际使用的技能"));const replacementNow=firstSlotReplacement(d.core_magic_id,m?.form_id);for(const id of pool.ids)if(data.move(id)){const idx=slots.findIndex(x=>same(x,id)),replaced=side==="my"&&mode==="carried"&&!!replacementNow&&idx===0;select.append(option(id,(side==="my"&&mode==="carried"?"槽 "+(idx+1)+" · ":"")+name(data.move(id))+(replaced?" → "+replacementNow.name+"（本回合替换）":"")));}select.value=pool.ids.some(id=>same(id,d.move_id))?d.move_id??"":"";
      select.onchange=()=>guard(()=>{writable();clearDraftEnergy(d);clearDraftEnergy(app.session.draft[side==="my"?"opponent":"my"]);d.move_id=select.value===""?null:data.move(select.value).id;d.origin="unknown";d.response_success=false;d.response_choice=false;if(mode==="carried")d.generator_slot=null;persist();render();});wrap.append(field(mode==="carried"?(side==="my"?"当前携带技能（按槽位）":"对方实际使用的技能"):modeNames[mode]+" · 实际随机技能",select));
      if(mode==="temporary")for(const x of pool.source_slots)if(x.uncertainty?.length)wrap.append(el("small","巧变池含历史文件或目录候选，当前版本范围待核对。","mechanic-hint"));
      const transform=catalog.action_mechanics?.transformations?.[d.move_id],responseEnergy=catalog.action_mechanics?.response_energy?.[d.move_id];if(transform?.kind==="slot_replace"){
        if(transform.trigger.choice_required){const choice=el("input");choice.type="checkbox";choice.checked=d.response_choice;choice.onchange=()=>guard(()=>mutateDraft(side,"response_choice",choice.checked));const row=el("label",null,"checkline");row.append(choice,el("span","本轮选择应对替换分支"));wrap.append(row);}
      }
      if(transform?.kind==="slot_replace"||responseEnergy){const response=el("input");response.type="checkbox";response.checked=d.response_success;response.onchange=()=>guard(()=>mutateDraft(side,"response_success",response.checked,true));const row=el("label",null,"checkline");row.append(response,el("span",responseEnergy?"实际应对成功，按已审核规则结算能量":"实际应对成功，记录时更新对应技能槽"));wrap.append(row);}
    }else if(d.kind==="switch"){const target=el("select");target.append(option("","选择换入精灵"));for(const m of team)if(m.member_id!==d.active_member_id)target.append(option(m.member_id,name(data.form(m.form_id))));target.value=d.target_member_id;target.onchange=()=>guard(()=>mutateDraft(side,"target_member_id",target.value,true));wrap.append(field("换入",target));}
    const configuredMagic=configuredCoreMagic(side),magic=el("select");magic.append(option("","本回合不使用"));for(const [id,label]of Object.entries(CORE_MAGICS))magic.append(option(id,label));magic.value=d.core_magic_id??"";magic.onchange=()=>guard(()=>{writable();if(Number(magic.value)!==104007)d.evolution_target_form_id=null;mutateDraft(side,"core_magic_id",magic.value===""?null:BattleData.coreMagic(Number(magic.value)),true);});wrap.append(field("本回合额外使用核心魔法",magic));
    const magicActor=active(side),replacement=firstSlotReplacement(d.core_magic_id,magicActor?.form_id);
    if(replacement){const slots=magicActor?BattleMechanics.currentMoves(app.session,magicActor):[],box=el("div",null,"core-magic-effect");box.append(el("strong","本回合技能栏首槽替换为【"+replacement.name+"】"));box.append(el("small","威力 "+replacement.power+" / 能耗 "+replacement.energy+" / 优先级 "+replacement.priority+" · 原首槽 "+(slots[0]?name(data.move(slots[0])):"空槽")+(replacement.user_note?" · 用户口径例外，未经游戏文件核对":""),"mechanic-hint"));box.append(el("small","解包技能表中 19 个系别变体共用同一面板参数，变体归属未解析，因此只记录公共参数、不写入具体技能 ID。","mechanic-hint"));wrap.append(box);}
    if(d.core_magic_id===104007){const candidates=evolutionCandidates(magicActor?.form_id);if(!candidates.length)wrap.append(el("small","该精灵目前没有可匹配的进化形态候选：同编号形态未在快照中找到。","mechanic-hint"));else{const pick=el("select");pick.append(option("","选择进化形态"));for(const c of candidates)pick.append(option(c.id,c.name));pick.value=d.evolution_target_form_id??"";pick.onchange=()=>guard(()=>mutateDraft(side,"evolution_target_form_id",pick.value===""?null:Number(pick.value)));wrap.append(field("进化形态（本场战斗）",pick));wrap.append(el("small","候选取自同编号形态；进化链与首领信物激活条件未经游戏文件核对。","mechanic-hint"));}}
    if(configuredMagic)wrap.append(el("small","阵容码配置："+CORE_MAGICS[configuredMagic]+"；核心魔法与普通行动分别记录。","mechanic-hint"));
    let originField=null;
    if(d.kind==="move"&&side==="opponent"&&(d.skill_mode||"carried")==="carried"){const origin=el("select");for(const [id,label]of Object.entries(originNames))origin.append(option(id,label));origin.value=d.origin;origin.onchange=()=>guard(()=>mutateDraft(side,"origin",origin.value));originField=field("对方技能来源",origin);}
    const metrics=el("div",null,"optional-grid"),projected=energyProjection()[side],configuredMax=configuredHpMax(side,d),hpInputs=side==="my"?[["remaining_hp_exact",d.kind==="switch"?"换入后剩余血量":"剩余血量"],["max_hp_exact","总血量"]]:[["remaining_hp_percent",d.kind==="switch"?"换入后血量 (%)":"剩余血量 (%)"]];for(const [key,label]of [["received_damage","受到伤害"],...hpInputs]){const input=el("input");input.type="number";input.min=key==="max_hp_exact"?"1":"0";input.step="1";if(key==="remaining_hp_percent")input.max="100";if(key==="remaining_energy")input.max="10";if(key==="remaining_hp_exact"&&d.max_hp_exact!=null)input.max=String(d.max_hp_exact);input.placeholder="未知";input.value=key==="remaining_energy"?(d[key]??projected.after??""):key==="max_hp_exact"?(d[key]??configuredMax??""):(d[key]??"");const sync=()=>{if(!input.checkValidity())return;if(["remaining_hp_percent","remaining_hp_exact","max_hp_exact"].includes(key))delete d.hp_observed_member_id;const value=input.value===""?null:key==="remaining_hp_percent"?BattleData.hpPercent(Number(input.value)):key==="remaining_energy"?BattleData.energy(Number(input.value),label):BattleData.integer(Number(input.value),label);if(["remaining_hp_exact","max_hp_exact"].includes(key))BattleData.exactHp({...d,[key]:value},true);mutateDraft(side,key,value);};input.oninput=()=>guard(sync);input.onchange=()=>guard(()=>{if(input.reportValidity())sync();});metrics.append(field(label,input));}if(originField)metrics.append(originField);wrap.append(metrics);if(configuredMax!=null&&d.max_hp_exact==null)wrap.append(el("small","总血量已按当前种族值、性格和三项资质配置计算为 "+configuredMax+"。","inference-note"));if(projected.before!=null&&d.remaining_energy==null)wrap.append(el("small","能量自动推算："+projected.before+" → "+projected.after+(projected.first_slot_replaced?"（首槽按替换后的【"+projected.first_slot_replaced.name+"】"+projected.first_slot_replaced.energy+"费计入）":"")+"；以对局能量栏为准，不手填。","inference-note"));if(d.legacy_remaining_hp_percent!=null&&d.remaining_hp_percent==null)wrap.append(el("small","历史血量待重新确认；请重新填写游戏当前显示值。原观测已保留。","inference-note"));if(d.remaining_hp!=null)wrap.append(el("small","legacy 历史绝对生命："+d.remaining_hp+"（原值保留）","inference-note"));
  }
  function actionFromDraft(side,projection=energyProjection()){const d=app.session.draft[side],team=app.session.teams[side],m=active(side);if(!m)throw Error((side==="my"?"我方":"对方")+"尚未选择在场精灵");const derivedMax=d.remaining_hp_exact!=null?configuredHpMax(side,d):null,replacementNow=firstSlotReplacement(d.core_magic_id,m.form_id),a={member_id:m.member_id,form_id:m.form_id,slot:team.indexOf(m),kind:d.kind,received_damage:d.received_damage,remaining_hp_percent:BattleData.hpPercent(d.remaining_hp_percent),energy_before:projection[side].before,remaining_energy:projection[side].after,core_magic_id:BattleData.coreMagic(d.core_magic_id),evolution_target_form_id:d.evolution_target_form_id??null,first_slot_replaced:replacementNow?{name:replacementNow.name,power:replacementNow.power,energy:replacementNow.energy,priority:replacementNow.priority,variant_resolved:replacementNow.variant_resolved,user_note:replacementNow.user_note===true,original_first_slot:projection[side].first_slot_move||null}:null,original_first_slot:projection[side].first_slot_move||null,...BattleData.exactHp({...d,max_hp_exact:d.max_hp_exact??derivedMax})};for(const key of ["remaining_hp","remaining_hp_unit","legacy_remaining_hp_percent"])if(d[key]!=null)a[key]=d[key];
    if(d.kind==="move"){const mode=d.skill_mode||"carried",pool=selectionPool(side,m,d);if(!data.move(d.move_id)||!pool.ids.some(id=>same(id,d.move_id)))throw Error("请选择当前来源池中的实际使用技能");const sources=mode==="carried"?pool.source_slots.filter(x=>same(x.move_id,d.move_id)):pool.source_slots;const slot=d.generator_slot??(sources.length===1?sources[0].slot:null);if((mode!=="carried"||side==="my"&&catalog.action_mechanics?.transformations?.[d.move_id])&&slot===null)throw Error("请选择技能变化的来源槽位");const origin=mode==="borrow"?"borrowed":mode==="mind_read"?"copied":mode!=="carried"?"generated":side==="my"?(m.move_ids.some(id=>same(id,d.move_id))?"carried":"generated"):d.origin;Object.assign(a,{move_id:d.move_id,origin,confirmed_carried:origin==="carried",...BattleData.mechanicFields({...d,generator_slot:slot})});}
    if(d.kind==="switch"){const t=team.find(x=>x.member_id===d.target_member_id);if(!t||t===m)throw Error("请选择有效的换入精灵");Object.assign(a,{target_member_id:t.member_id,target_form_id:t.form_id,target_slot:team.indexOf(t)});}const observed=Object.hasOwn(d,"hp_observed_member_id")?d.hp_observed_member_id:d.kind==="switch"?a.target_member_id:m.member_id;if(observed)a.hp_observed_member_id=observed;return a;
  }
  function record(){writable();if(!$("round-form").reportValidity())return;const s=app.session,projection=energyProjection(),r={event_id:uid(),recorded_at:new Date().toISOString(),turn:(s.rounds.at(-1)?.turn||0)+1,snapshot_id:currentSnapshot,note:s.draft.note||"",teams_snapshot:clone(s.teams),configuration_provenance:"recorded_at_turn",opening_full_hp:s.opening_full_hp===true,mechanics_before:BattleMechanics.validateState(s,catalog),energy_events:projection.events};
    for(const side of SIDES)r[side]=actionFromDraft(side,projection);
    const changes=BattleMechanics.applyRound(s,r,catalog.action_mechanics,catalog);r.mechanics_after={slot_overrides:changes.slot_overrides,pending_transforms:changes.pending_transforms};r.mechanic_events=changes.events;r.mechanic_warnings=changes.warnings;Object.assign(s,clone(r.mechanics_after));s.rounds.push(r);s.draft.note="";s.draft.weather_observation=null;
    for(const side of SIDES){const d=s.draft[side];d.received_damage=null;d.remaining_hp_percent=null;d.remaining_hp_exact=null;d.max_hp_exact=null;d.remaining_energy=null;d.core_magic_id=null;d.evolution_target_form_id=null;delete d.remaining_hp;delete d.remaining_hp_unit;delete d.legacy_remaining_hp_percent;delete d.hp_observed_member_id;d.origin="unknown";d.skill_mode="carried";d.generator_slot=null;d.response_success=false;d.response_choice=false;d.move_id=null;if(r[side].kind==="switch"){d.active_member_id=r[side].target_member_id;d.target_member_id="";}}persist();render();toast("已记录实际回合、核心魔法、血量、能量与技能槽变化。");}
  let weatherModel=null;const weatherHistoryNodes=new Map();
  function weatherText(value){return RocoWeatherView.title(value);}
  function weatherDetails(container,value,affected){const effects=RocoWeatherView.effects(value);for(const line of [...effects,...RocoWeatherView.affectedLines(affected).filter(line=>!effects.some(effect=>line.endsWith(effect)))])container.append(el("p",line,"weather-effect"));}
  function paintWeather(state){const wrap=$("weather-controls");wrap.replaceChildren(el("strong","场上天气 · 随行动自动更新"));
    if(state.status!=="ready"){const text=state.status==="error"?"天气暂未完成推演："+state.error:"正在按已记录行动推演天气…";wrap.append(el("p",text,"weather-status"));for(const node of weatherHistoryNodes.values())node.replaceChildren(el("small",text));return;}
    const result=state.data;wrap.append(el("p",weatherText(result.current),"weather-current"));weatherDetails(wrap,result.current,result.affected);
    if(result.uncertainty?.length){const detail=el("details",null,"mechanic-hint");detail.append(el("summary","天气依据与待核实项"));for(const value of result.uncertainty)detail.append(el("p",RocoWeatherView.uncertaintyText(value)));wrap.append(detail);}
    for(const [id,node] of weatherHistoryNodes){const frame=result.frames.find(f=>f.event_id===id);node.replaceChildren();if(!frame){node.append(el("small","天气：该回合尚未完成推演"));continue;}node.append(el("p","回合后天气："+weatherText(frame.after)));for(const event of frame.events||[]){const text=RocoWeatherView.eventText(event);if(text)node.append(el("small",text,"weather-event"));}weatherDetails(node,null,frame.affected);}
  }
  function renderWeather(){if(!weatherModel)weatherModel=RocoWeatherView.createReplayModel({fetch:(...args)=>fetch(...args),onChange:paintWeather});const pending=weatherModel.update(app.session);paintWeather(weatherModel.state);return pending;}
  function actionLabel(a){let s=name(data.form(a.form_id))+" · ";s+=a.kind==="move"?name(data.move(a.move_id))+(a.skill_mode&&a.skill_mode!=="carried"?"（"+modeNames[a.skill_mode]+"）":a.origin==="carried"?"":"（"+originNames[a.origin||"unknown"]+"）"):a.kind==="switch"?"换入 "+name(data.form(a.target_form_id)):a.kind==="charge"?"聚能（+5）":"行动未知";if(a.core_magic_id)s+=" / 核心魔法 "+CORE_MAGICS[a.core_magic_id];if(a.first_slot_replaced)s+=" / 首槽替换为 "+a.first_slot_replaced.name+"（威力 "+a.first_slot_replaced.power+" · 能耗 "+a.first_slot_replaced.energy+(a.first_slot_replaced.user_note?" · 用户口径":"")+"）";if(a.evolution_target_form_id)s+=" / 进化形态 "+name(data.form(a.evolution_target_form_id));if(a.energy_before!=null&&a.remaining_energy!=null)s+=" / 能量 "+a.energy_before+" → "+a.remaining_energy+"（"+(a.remaining_energy-a.energy_before>=0?"+":"")+(a.remaining_energy-a.energy_before)+"）";else if(a.remaining_energy!=null)s+=" / 行动后能量 "+a.remaining_energy;if(a.received_damage!=null)s+=" / 受伤 "+a.received_damage;if(a.remaining_hp_exact!=null&&a.max_hp_exact!=null)s+=" / "+(a.kind==="switch"?"换入血量 ":"剩余生命 ")+a.remaining_hp_exact+" / "+a.max_hp_exact;else if(a.remaining_hp_percent!=null&&Number.isInteger(a.remaining_hp_percent))s+=" / "+(a.kind==="switch"?(a.hp_observed_member_id===a.target_member_id?"换入血量 ":a.hp_observed_member_id===a.member_id?"换出血量 ":"历史血量（归属待确认） "):"剩余生命 ")+a.remaining_hp_percent+"%";if(a.legacy_remaining_hp_percent!=null&&a.remaining_hp_percent==null||typeof a.remaining_hp_percent==="number"&&!Number.isInteger(a.remaining_hp_percent))s+=" / 历史血量待重新确认（原观测已保留）";if(a.remaining_hp!=null)s+=" / legacy 历史绝对生命 "+a.remaining_hp;return s;}
  function history(){weatherHistoryNodes.clear();const s=app.session;$("round-count").textContent=s.rounds.length+" 回合";$("next-round").textContent="第 "+((s.rounds.at(-1)?.turn||0)+1)+" 回合";$("undo-round").disabled=!s.rounds.length;const wrap=$("round-history");wrap.replaceChildren();if(!s.rounds.length)wrap.append(el("p","尚无实际回合记录。","empty"));for(const r of [...s.rounds].reverse()){const n=el("article",null,"round");n.append(el("strong","第 "+r.turn+" 回合 · "+new Date(r.recorded_at).toLocaleString("zh-CN"),"round-top"),el("p","我方："+actionLabel(r.my)),el("p","对方："+actionLabel(r.opponent)));for(const event of r.energy_events||[]){const target=event.target_side==="my"?"我方":"对方",verb=event.op==="energy.restore"?"恢复":"额外失去";n.append(el("p",name(data.move(event.skill_id))+"：应对成功，"+target+verb+" "+event.amount+" 能量（"+event.before+" → "+event.after+"）","energy-event"));}const weather=el("div",null,"round-weather");weather.append(el("small","正在推演本回合天气…"));weatherHistoryNodes.set(r.event_id,weather);n.append(weather);if(r.weather_observation){const legacy=el("details",null,"mechanic-hint");legacy.append(el("summary","旧版手填天气（仅存档）"),el("p",weatherText(r.weather_observation)));n.append(legacy);}for(const event of r.mechanic_events||[]){const who=Object.values(r.teams_snapshot||{}).flat().find(m=>m.member_id===event.member_id);n.append(el("p",(who?name(data.form(who.form_id)):"精灵")+" · 槽 "+(event.slot+1)+"："+(event.kind==="clever_change"?"已进入巧变，待选择实际结果":event.kind==="temporary_return"?"恢复 "+name(data.move(event.move_id)):"替换为 "+name(data.move(event.move_id)))));}for(const warning of r.mechanic_warnings||[])n.append(el("small",warning,"mechanic-hint"));if(r.note)n.append(el("p",r.note,"round-note"));n.append(el("small",(r.teams_snapshot?"已保存当时完整配置":"旧记录：当时完整配置未知")+" · 资料 "+(r.snapshot_id||"未知")));wrap.append(n);}}
  function undo(){writable();const s=app.session;if(!s.rounds.length||!confirm("撤销最近一条实际记录？将恢复行动草稿及本轮之前的技能槽变化。"))return;const r=s.rounds.pop();if(r.mechanics_before){const ids=new Set(SIDES.flatMap(side=>s.teams[side].map(m=>m.member_id)));for(const key of ["slot_overrides","pending_transforms"])s[key]=Object.fromEntries(Object.entries(clone(r.mechanics_before[key])).filter(([mid])=>ids.has(mid)));}s.draft.note=r.note;s.draft.weather_observation=r.weather_observation||null;for(const side of SIDES){const a=r[side],t=s.teams[side];s.draft[side]={...BattleData.mechanicFields(a),active_member_id:t.some(m=>m.member_id===a.member_id)?a.member_id:"",kind:a.kind,origin:a.origin||"unknown",all_moves:true,move_id:a.move_id??null,target_member_id:t.some(m=>m.member_id===a.target_member_id)?a.target_member_id:"",received_damage:a.received_damage,remaining_hp_percent:a.remaining_hp_percent,remaining_hp_exact:a.remaining_hp_exact,max_hp_exact:a.max_hp_exact,remaining_energy:a.remaining_energy,core_magic_id:a.core_magic_id,evolution_target_form_id:a.evolution_target_form_id??null,hp_observed_member_id:t.some(m=>m.member_id===(a.hp_observed_member_id??a.member_id))?(a.hp_observed_member_id??(a.kind==="switch"?null:a.member_id)):null};if(a.legacy_remaining_hp_percent!=null)s.draft[side].legacy_remaining_hp_percent=a.legacy_remaining_hp_percent;if(a.remaining_hp!=null)Object.assign(s.draft[side],{remaining_hp:a.remaining_hp,remaining_hp_unit:"legacy_absolute"});}persist();render();}
  async function refreshAdvice(){const token=++adviceToken,context={snapshot_id:currentSnapshot,match_id:app.session.match_id,revision:app.session.revision},wrap=$("advice-content");try{const reply=await json("/api/advice");if(token!==adviceToken)return;wrap.replaceChildren();if(!Array.isArray(reply.actions))throw Error("建议格式无效");
      if(!reply.actions.length){unavailableReason=reply.reason||"策略模型尚未训练";showUnavailable();return;}unavailableReason=null;
      if(!reply.model||!reply.context||Object.keys(context).some(k=>reply.context[k]!==context[k]))throw Error("建议未绑定当前局面，已拒绝显示");
      const actions=reply.actions.map(a=>{if(typeof a.id!=="string"||typeof a.label!=="string"||!Array.isArray(a.outcomes))throw Error("动作建议格式无效");BattleData.probability(a.probability);for(const o of a.outcomes){if(typeof o.label!=="string")throw Error("后果格式无效");BattleData.probability(o.probability);}return a;});if(Math.abs(actions.reduce((s,a)=>s+a.probability,0)-1)>1e-6)throw Error("动作概率未归一化");
      $("model-badge").textContent="模型建议";for(const a of actions){const n=el("article",null,"advice-action");n.append(el("strong",a.label),el("span",pct(a.probability),"prob"));for(const o of a.outcomes)n.append(el("p",o.label+" · "+pct(o.probability)));wrap.append(n);}
    }catch(e){if(token!==adviceToken)return;$("model-badge").textContent="建议不可用";wrap.replaceChildren(el("p",e.message,"advice-note"));}}
  // ---- 技能结果预估（裸伤害）：面板+威力+属性克制+本系，其余一律不计入 ----

  let previewToken=0,previewLastBody="";
  function previewActiveIds(){return {a:app.session.draft.my.active_member_id||"",b:app.session.draft.opponent.active_member_id||""};}
  function previewActiveSlots(){const out={};for(const [side,key] of [["my","a"],["opponent","b"]]){const mid=app.session.draft[side].active_member_id||"";if(!mid)continue;const index=app.session.teams[side].findIndex(m=>m.member_id===mid);if(index>=0)out[key]=index;}return out;}
  function previewStatNumber(id){const raw=String($(id).value||"").trim();if(!raw)return null;const value=Number(raw);if(!Number.isFinite(value))throw Error("状态修正必须填数字");return value;}
  function previewStatTerms(){const terms={a:{},b:{}};const put=(side,stat,id)=>{const value=previewStatNumber(id);if(value)terms[side][stat]=value;};put("a","patk","preview-my-patk");put("a","matk","preview-my-matk");put("b","pdef","preview-opp-pdef");put("b","mdef","preview-opp-mdef");const out={};if(Object.keys(terms.a).length)out.a=terms.a;if(Object.keys(terms.b).length)out.b=terms.b;return out;}
  function previewPayload(ids,slots){const percent={};for(const [side,key] of [["my","a"],["opponent","b"]]){const mid=ids[key];if(!mid)continue;const obs=BattleData.latestHpObservations(app.session,side).get(mid);if(obs&&Number.isInteger(obs.value))percent[key]=obs.value;}const body={teams:{my:app.session.teams.my,opponent:app.session.teams.opponent},settings:catalog.pvp_rules.settings,active_slot:slots,hp_percent:percent};const terms=previewStatTerms();if(Object.keys(terms).length)body.stat_terms=terms;return body;}
  function previewPanel(value){return Math.round(Number(value)*10)/10;}
  function previewPercent(value){return (Math.round(Number(value)*10)/10).toFixed(1)+"%";}
  function previewRow(row,defenderMax){
    const node=el("div",null,"preview-row"),hits=row.hit_count||1;
    node.append(el("span","槽"+(row.slot+1),"pr-slot"),el("span",row.name,"pr-name"));
    const meta=[row.type,row.kind==="physical"?"物伤":"魔伤","威力 "+row.power,"能耗 "+(row.energy_cost??"?")];
    if(hits>1)meta.push(hits+" 连击");
    if(row.attack_stat_modifier_percent!=null)meta.push("攻面板 "+row.attack_panel_base+"→"+previewPanel(row.attack_panel));
    if(row.defense_stat_modifier_percent!=null)meta.push("守面板 "+row.defense_panel_base+"→"+previewPanel(row.defense_panel));
    node.append(el("span",meta.join(" · "),"pr-meta"));
    const dmg=el("span",null,"pr-dmg");dmg.append(document.createTextNode("→ 伤害 "),el("strong",String(row.damage)));
    if(hits>1)dmg.append(el("span","（"+hits+" × 每段 "+row.per_hit_damage+"）","pr-hits"));
    node.append(dmg);
    node.append(el("span","对方剩 "+row.defender_hp_after+"/"+defenderMax+"（"+previewPercent(row.defender_hp_after_percent)+"）"+(row.lethal?" · 可击倒":"")+" · "+(row.affordable?"":"能量不足")+((row.type_multiplier.numerator!==row.type_multiplier.denominator?" · 克制 "+row.type_multiplier.numerator+"/"+row.type_multiplier.denominator:"")+(row.same_type_bonus!==1?" · 本系 ×"+row.same_type_bonus:"")),"pr-after"));
    return node;
  }
  function previewOtherRow(entry,cls,reason){
    const node=el("div",null,"preview-row "+cls);
    node.append(el("span","槽"+(entry.slot+1),"pr-slot"),el("span",entry.name,"pr-name"),el("span",[entry.type,entry.kind==="physical"?"物伤":"魔法"].filter(Boolean).join(" · ")+" · "+reason,"pr-meta"));
    return node;
  }
  async function refreshPreview(){
    const token=++previewToken,wrap=$("preview-content"),badge=$("preview-badge"),line=$("preview-matchup");
    const ids=previewActiveIds(),slots=previewActiveSlots();
    if(!app.session.teams.my.length||!app.session.teams.opponent.length){badge.textContent="等待阵容";line.textContent="双方各添加至少一只精灵后显示预估。";wrap.replaceChildren();return;}
    if(!ids.a||!ids.b||slots.a===undefined||slots.b===undefined){badge.textContent="等待在场";line.textContent="先在两侧选定在场精灵。";wrap.replaceChildren();previewLastBody="";return;}
    const body=JSON.stringify(previewPayload(ids,slots));
    if(body===previewLastBody)return;
    previewLastBody=body;
    badge.textContent="计算中…";
    try{
      const response=await fetch("/api/preview/damage",{method:"POST",headers:{"Content-Type":"application/json"},body});
      const payload=await response.json();
      if(token!==previewToken)return;
      if(!response.ok)throw Error(payload.error||"预估服务不可用");
      if(!Array.isArray(payload.results)||!payload.attacker||!payload.defender)throw Error("预估结果格式无效");
      const attacker=payload.attacker,defender=payload.defender;
      badge.textContent="裸伤害 · 未校准";
      line.textContent="我方 "+attacker.name+" "+attacker.hp+"/"+attacker.max_hp+" · 能量 "+attacker.energy+"/"+(attacker.max_energy??"?")+"   →   对方 "+defender.name+" "+defender.hp+"/"+defender.max_hp;
      const rows=[];
      for(const row of payload.results)rows.push(previewRow(row,defender.max_hp));
      for(const entry of payload.non_damage_slots||[])rows.push(previewOtherRow(entry,"nondamage","本预估只覆盖直接伤害技能"));
      for(const entry of payload.blocked_slots||[])rows.push(previewOtherRow(entry,"blocked",entry.reason||"无法预估"));
      if(!rows.length)rows.push(el("p","我方在场精灵没有可用技能槽。","empty"));
      wrap.replaceChildren(...rows);
      const notes=(payload.warnings||[]).slice(0,2);
      if(notes.length)wrap.append(el("p",notes.join("；"),"preview-note"));
    }catch(error){
      if(token!==previewToken)return;
      previewLastBody="";
      badge.textContent="预估不可用";
      line.textContent="";
      wrap.replaceChildren(el("p",error.message,"preview-note"));
    }
  }
  // ---- 照抄 HUD 的数据出口 ----
  // 第三方 HUD（/hud）只认 roco.battleHud.* 这组键。这里把工作台局面翻译成同一份契约，
  // 发布到本工作台自己的命名空间，由 /hud_bridge.js 转写，双方代码都不必改。
  let hudSnapshotSignature="";
  function hudMoveItem(id){const mv=data.move(id);if(!mv)return null;const title=name(mv);return {id:mv.id??id,skill_id:mv.id??id,skillId:mv.id??id,skillName:title,moveName:title,name:title,power:Number.isFinite(mv.power)?mv.power:null,energy_cost:Number.isFinite(mv.energy)?mv.energy:null,move_type:mv.type??null,move_category:mv.kind==="physical"?"物理":mv.kind==="magical"?"魔法":mv.kind==="status"?"状态":"防御"};}
  function hudTeamEntry(side,m,index){const form=data.form(m.form_id)||{},maxHp=BattleData.configuredMaxHp(m,form,data.natures),obs=BattleData.latestHpObservations(app.session,side).get(m.member_id),percent=obs&&Number.isFinite(obs.value)?obs.value:null,currentHp=Number.isFinite(maxHp)&&percent!=null?Math.max(0,Math.round(maxHp*percent/100)):null,moves=(m.move_ids||[]).filter(id=>id).map(hudMoveItem).filter(Boolean),title=name(form);return {memberId:m.member_id,id:form.id??m.form_id,iconId:form.id??m.form_id,petBaseId:form.id??m.form_id,rosterIndex:index,side:side==="my"?"my":"enemy",petName:title,name:title,hpPercent:percent,currentHp,maxHp:Number.isFinite(maxHp)?maxHp:null,stats:Number.isFinite(maxHp)?{hp:maxHp}:{},moves,selectedMoves:moves,move_pool:moves,monster:{base_hp:form.stats?.hp??null,base_spd:form.stats?.spd??null,main_type:form.types?.[0]??null,sub_type:form.types?.[1]??null,move_pool:moves}};}
  function hudObserved(side,team){const out={};for(const e of team)if(e.petName)out[e.petName]=[];const add=(pet,moveId)=>{const title=data.move(moveId)?name(data.move(moveId)):"";if(!pet||!title||["聚能","蓄力"].includes(title))return;out[pet]=out[pet]||[];if(!out[pet].includes(title))out[pet].push(title);};for(const m of app.session.teams[side]||[])for(const id of m.confirmed?.moves||[])add(name(data.form(m.form_id)),id);for(const r of app.session.rounds||[]){const a=r[side];if(a&&a.move_id)add(name(data.form(a.form_id)),a.move_id);}return out;}
  function hudSideHp(entry){if(!entry)return null;if(entry.currentHp!=null)return {hpAfter:entry.currentHp,percent:entry.hpPercent??null};if(entry.hpPercent!=null)return {percent:entry.hpPercent};return null;}
  function publishHudSnapshot(){
    try{
      const session=app.session,my=(session.teams.my||[]).map((m,i)=>hudTeamEntry("my",m,i)),enemy=(session.teams.opponent||[]).map((m,i)=>hudTeamEntry("opponent",m,i));
      const findActive=(list,side)=>Math.max(0,list.findIndex(e=>e.memberId===active(side)?.member_id));
      const myIndex=findActive(my,"my"),enemyIndex=findActive(enemy,"opponent"),timeline=[];
      for(const r of session.rounds||[])for(const side of SIDES){const a=r[side];if(!a||!a.form_id)continue;timeline.push({side:side==="my"?"my":"enemy",kind:"action",turn:r.turn,activePetName:name(data.form(a.form_id)),skillName:a.move_id?name(data.move(a.move_id)):null});}
      const snapshot={schema:"workbench-hud-1",note:"由本工作台发布，字段名照抄第三方 HUD 契约，不含任何隐藏配置。",
        runtime:{sessionId:session.match_id,battleId:session.match_id,myTeam:my,enemyTeam:enemy,active:{my:{rosterIndex:myIndex},enemy:{rosterIndex:enemyIndex}},hp:{my:hudSideHp(my[myIndex]),enemy:hudSideHp(enemy[enemyIndex])},observedEnemyMoves:hudObserved("opponent",enemy),battleTimeline:timeline},
        state:{myTeam:my,enemyTeam:enemy,myActiveIndex:myIndex,enemyActiveIndex:enemyIndex},enemyPreview:{enemyTeam:enemy}};
      const signature=JSON.stringify(snapshot);
      if(signature===hudSnapshotSignature)return;
      hudSnapshotSignature=signature;
      localStorage.setItem("roco.workbench.hud.v1",signature);
      // 桌面悬浮 HUD 是独立进程，读不到本页 localStorage，所以顺手中转到服务端内存。
      try{fetch("/api/hud/publish",{method:"POST",headers:{"Content-Type":"application/json"},body:signature,keepalive:true}).catch(()=>{});}catch(error){}
    }catch(error){/* HUD 快照失败不影响工作台主流程 */}
  }
  // ---- 状态百分比自动带出 ----
  // 解包数据里每个技能都绑定了 BUFF 单位（物攻+10% 这种是 1 层）。面板只认四个通道，
  // 所以这里只挑能让"我方攻击面板 / 对方防御面板"变化的那些，点一下往对应输入框累加一层。
  let buffTable=null,buffLoading=false;
  function loadBuffTable(){
    if(buffTable||buffLoading)return;
    if(typeof fetch!=="function"){buffTable={};return;}
    buffLoading=true;fetch("/api/buff/moves").then(r=>r.ok?r.json():null).then(data=>{buffTable=(data&&data.moves)||{};buffLoading=false;if(typeof renderPreviewBuffs==="function")renderPreviewBuffs();}).catch(()=>{buffTable={};buffLoading=false;});
  }
  function previewApplicableBuffs(){
    const out=[];
    if(!buffTable)return out;
    for(const [side,key,role] of [["my","a","mine"],["opponent","b","theirs"]]){
      const member=active(side);
      if(!member)continue;
      for(const mid of BattleMechanics.currentMoves(app.session,member)){
        const entry=buffTable[String(mid)];
        if(!entry)continue;
        for(const buff of entry.buffs||[]){
          for(const stat of ["patk","matk","pdef","mdef"]){
            const percent=buff.percents?.[stat];
            if(!percent)continue;
            const attacking=stat==="patk"||stat==="matk";
            const applies=role==="mine"?(buff.target==="self"&&attacking||buff.target==="opponent"&&!attacking):(buff.target==="self"&&!attacking||buff.target==="opponent"&&attacking);
            if(!applies)continue;
            // 面板所属方看的是"谁被改"，不是"谁施放"：降对方防 -> 对方防御面板(b)。
            const panelSide=buff.target==="opponent"?(role==="mine"?"b":"a"):key;
            out.push({side:panelSide,stat,percent,move_id:mid,move_name:entry.move_name,buff_name:buff.name,desc:buff.desc});
          }
        }
      }
    }
    return out;
  }
  function previewBuffInput(item){
    if(item.side==="a")return $(item.stat==="patk"?"preview-my-patk":"preview-my-matk");
    return $(item.stat==="pdef"?"preview-opp-pdef":"preview-opp-mdef");
  }
  function previewBuffLabel(item){
    const who=item.side==="a"?"我方":"对方";
    const what={patk:"物攻",matk:"魔攻",pdef:"物防",mdef:"魔防"}[item.stat];
    const sign=item.percent>0?"+":"";
    return who+" "+what+" "+sign+(Math.round(item.percent*10)/10)+"%";
  }
  function renderPreviewBuffs(){
    const host=$("preview-buffs");
    if(!host)return;
    loadBuffTable();
    host.replaceChildren();
    if(!buffTable){host.append(el("span","正在读取解包状态表…","preview-hint"));return;}
    const items=previewApplicableBuffs();
    if(!items.length){host.append(el("span","当前双方技能里没有影响攻防面板的状态（速度、威力、连击类不进面板预估）。","preview-hint"));return;}
    host.append(el("span","点一下加一层：","preview-hint"));
    for(const item of items){
      const chip=button(item.move_name+" → "+previewBuffLabel(item),()=>{const node=previewBuffInput(item);if(!node)return;const current=Number(node.value||0)||0;node.value=String(Math.round((current+item.percent)*10)/10);refreshPreview();},"buff-chip");
      chip.title=(item.buff_name+"（"+item.desc+"）").replace(/<[^>]*>/g,"");
      host.append(chip);
    }
  }
  function render(){renderTemplates();for(const side of SIDES){renderTeam(side);renderAction(side);}history();renderWeather();scheduleDamageInference();const mismatch=app.session.snapshot_id!==currentSnapshot;$("version-banner").hidden=!mismatch;$("version-banner").textContent="本局来源快照 "+(app.session.snapshot_id||"未知")+"，当前资料 "+currentSnapshot+"。旧记录保持原样；新记录使用当前资料，请核对差异。";refreshAdvice();refreshPreview();publishHudSnapshot();renderPreviewBuffs();}
  // ---- 天梯使用率快照：按真实玩家配置填充 ----
  // 数据来自解包客户端自己的 pet/stat 接口（2026-09-28 快照）。填充只写进编辑框，
  // 用户点"保存到阵容"前不会改动存档；缺失的维度保持原样，不猜值。
  const ladderCache=new Map();
  async function ladderFetch(url){const r=await fetch(url);if(!r.ok){const body=await r.json().catch(()=>({}));throw Error(body.error||"天梯接口不可用");}return r.json();}
  async function ladderBuildFor(form){
    const key=String(form.id);
    if(ladderCache.has(key))return ladderCache.get(key);
    let build=null,error=null;
    try{build=await ladderFetch("/api/usage/pet?id="+encodeURIComponent(form.id));}
    catch(first){
      try{const list=await ladderFetch("/api/usage/pets?q="+encodeURIComponent(name(form))+"&limit=8");const hit=(list.pets||[]).find(p=>String(p.base_id)===String(form.id))||(list.pets||[])[0];if(hit)build=await ladderFetch("/api/usage/pet?id="+encodeURIComponent(hit.base_id)+"&form="+encodeURIComponent(form.id));}catch(second){error=String(second?.message||first?.message||second);}
    }
    if(!build)error=error||"天梯快照里没有这只精灵";
    const out={build,error};ladderCache.set(key,out);return out;
  }
  function ladderNote(text,isError){const node=$("ladder-note");if(!node)return;node.textContent=text;node.classList.toggle("error",!!isError);}
  async function applyLadder(form){
    if(!form)return;
    ladderNote("正在读取天梯快照…");
    const {build,error}=await ladderBuildFor(form);
    if(!build){ladderNote(error||"天梯快照里没有这只精灵",true);return;}
    const dims=(build.talent_ranking||[]).slice(0,3).map(row=>row.dimension),values={},sources={};
    for(const d of dims){values[d]=10;sources[d]="user_default";}
    const selection=BattleData.talentSelection({selected:dims,values,value_sources:sources,selection_source:"user_selected",default_value:10});
    const moves=[...(build.moves||[])];while(moves.length<4)moves.push(0);
    editor.nature_id=build.nature?.id??null;
    if(build.nature?.up&&build.nature?.down)editor.nature_modifiers={up_id:Math.max(0,MODIFIERS.indexOf(build.nature.up)),down_id:Math.max(0,MODIFIERS.indexOf(build.nature.down))};
    editor.bloodline_id=build.bloodline?.id??null;
    editor.talent_selection=selection;
    editor.talents=Object.fromEntries(DIMS.map(d=>[d,null]));
    editor.move_ids=moves;editor.hp_constraint=null;editor.hp_manual=null;editor.confirmationChanged=true;
    renderEditor();
    const parts=[];
    if(build.nature)parts.push("性格 "+build.nature.name+" "+(build.nature.percent??"?")+"%");
    if(build.bloodline)parts.push("血脉 "+build.bloodline.name+" "+(build.bloodline.percent??"?")+"%");
    if(build.bloodline_note)parts.push(build.bloodline_note);
    parts.push("个体 "+dims.map(d=>LABELS[d]).join("/"));
    parts.push("技能 "+moves.filter(id=>id!==0).map(id=>name(data.move(id))).join("/"));
    const collected=build.provenance?.collected_at?String(build.provenance.collected_at).slice(0,10):"日期未知";
    ladderNote("已按天梯快照（"+collected+"）填充："+parts.join(" · ")+"。未保存前不写入阵容。");
  }
  function openEditor(side,mid=null){writable();const m=app.session.teams[side].find(x=>x.member_id===mid);if(!m&&app.session.teams[side].length>=6)throw Error("每方最多 6 只");const directions=m?BattleData.effectiveDirections(m,data.natures):{up:null,down:null};editor={side,mid,form_id:m?.form_id??null,nature_id:m?.nature_id??null,talents:clone(m?.talents||Object.fromEntries(DIMS.map(d=>[d,null]))),talent_selection:clone(m?.talent_selection||BattleData.selectionFromMarkers(m?.code_provenance?.original_member)),talent_note:m?.talent_note||"",bloodline_id:m?.bloodline_id??null,nature_modifiers:{up_id:MODIFIERS.indexOf(directions.up)>0?MODIFIERS.indexOf(directions.up):0,down_id:MODIFIERS.indexOf(directions.down)>0?MODIFIERS.indexOf(directions.down):0},code_provenance:m?.code_provenance?clone(m.code_provenance):null,move_ids:Array.from({length:4},(_,i)=>m?.move_ids?.[i]??0),original:m?clone(m):null,confirmationChanged:false,hp_manual:null,hp_constraint:null,page:0};
    $("editor-side").textContent=side==="my"?"我方固定阵容":"对方阵容";$("editor-title").textContent=m?"编辑精灵":"添加精灵";$("picker-search").value="";$("move-search").value="";$("member-dialog").showModal();renderPicker();renderEditor();}
  function renderPicker(){const q=$("picker-search").value.trim().toLowerCase(),list=catalog.forms.filter(f=>(name(f)+" "+f.number+" "+f.id).toLowerCase().includes(q)),size=12;editor.page=Math.min(editor.page,Math.max(0,Math.ceil(list.length/size)-1));const wrap=$("picker-results");wrap.replaceChildren();for(const f of list.slice(editor.page*size,(editor.page+1)*size)){const b=button(name(f),()=>{if(editor.form_id!=null&&!same(f.id,editor.form_id)&&(editor.move_ids.some(x=>x!==0)||editor.nature_id!=null)&&!confirm("更换精灵将清空编辑框内的配置。原存档在保存前不会变化。"))return;editor.form_id=f.id;editor.nature_id=null;editor.talents=Object.fromEntries(DIMS.map(d=>[d,null]));editor.talent_selection=BattleData.selectionFromMarkers(null);editor.talent_note="";editor.move_ids=[0,0,0,0];editor.bloodline_id=null;editor.nature_modifiers={up_id:0,down_id:0};editor.original=null;editor.confirmationChanged=true;renderPicker();renderEditor();},"pick-card"+(same(editor.form_id,f.id)?" selected":""));wrap.append(b);}
    $("picker-pager").replaceChildren(button("上一页",()=>{editor.page=Math.max(0,editor.page-1);renderPicker();}),el("span",(editor.page+1)+" / "+Math.max(1,Math.ceil(list.length/size))+" · "+list.length+" 项"),button("下一页",()=>{editor.page=Math.min(Math.ceil(list.length/size)-1,editor.page+1);renderPicker();}));}
  function editorHpMember(){return {nature_id:editor.nature_id,nature_modifiers:editor.nature_modifiers,talent_selection:editor.talent_selection};}
  function clearHpReverse(){editor.hp_manual=null;editor.hp_constraint=null;editor.confirmationChanged=true;}
  function applyHpCandidate(candidate,target){const s=editor.talent_selection;editor.nature_modifiers={up_id:candidate.up_id,down_id:candidate.down_id};if(candidate.hp_talent_selected){if(!s.selected.includes("hp"))s.selected.push("hp");s.values.hp=candidate.hp_talent_value;s.value_sources.hp=candidate.hp_talent_value===10?"user_default":"user_entered";}else{s.selected=s.selected.filter(d=>d!=="hp");delete s.values.hp;delete s.value_sources.hp;}s.selection_source="user_selected";editor.hp_manual=target;editor.hp_constraint={up_id:candidate.up_id,down_id:candidate.down_id,hp_selected:candidate.hp_talent_selected,hp_value:candidate.hp_talent_value};editor.confirmationChanged=true;renderEditor();}
  function renderHpEditor(f,wrap){const calculated=BattleData.configuredMaxHp(editorHpMember(),f,data.natures),box=el("div",null,"editor-exact-hp"),label=el("label",null,"field"),input=el("input");input.type="number";input.min="1";input.step="1";input.placeholder="输入当前满血数值";input.setAttribute("aria-label","当前生命具体数值");input.value=editor.hp_manual??calculated??"";label.append(el("span","当前生命具体数值"),input);box.append(label);
    const status=el("small",calculated!=null?"按当前增减方向与三项个体计算 · "+calculated:editor.hp_manual!=null?"按输入值反推配置":"选择三项个体并填写增减方向后自动计算","editor-hp-status");box.append(status);
    if(editor.hp_constraint)box.append(button("清除反向限制",()=>{clearHpReverse();renderEditor();},"quiet small"));
    const choices=el("div",null,"hp-reverse-choices");
    input.oninput=()=>{const target=Number(input.value);if(input.value===""){editor.hp_manual=null;wrap.replaceChildren();renderHpEditor(f,wrap);return;}if(!Number.isInteger(target)||target<1){editor.hp_manual=target;choices.replaceChildren(el("small","生命数值必须为正整数。","notice error"));return;}editor.hp_manual=target;const candidates=BattleData.reverseHpConfigurations(target,f,editor.talent_selection,editor.nature_modifiers);if(candidates.length===1){applyHpCandidate(candidates[0],target);return;}choices.replaceChildren();if(!candidates.length)choices.append(el("small","当前已确定的增减方向或个体选择与该生命值冲突。"));else{choices.append(el("small","找到 "+candidates.length+" 种相容配置，请选择："));for(const c of candidates)choices.append(button(LABELS[MODIFIERS[c.up_id]]+"↑ / "+LABELS[MODIFIERS[c.down_id]]+"↓ · "+(c.hp_talent_selected?"生命个体 "+c.hp_talent_value:"生命未选"),()=>applyHpCandidate(c,target),"small"));}};
    wrap.append(box,choices);
  }
  function renderEditor(){const f=data.form(editor.form_id);$("editor-detail").hidden=!f;$("save-member").disabled=!f;if(!f)return;const summary=$("editor-summary"),stats=el("div",null,"editor-stat-copy"),hp=el("div",null,"editor-hp-wrap");stats.append(el("h3",name(f)),el("p","种族值："+DIMS.map(d=>LABELS[d]+" "+(f.stats?.[d]??"待核验")).join(" / ")));summary.replaceChildren(stats,hp);renderHpEditor(f,hp);$("apply-ladder").onclick=()=>applyLadder(f);const blood=$("editor-bloodline");blood.replaceChildren(option("","未填写"));BLOODLINES.forEach((label,i)=>blood.append(option(i,label+"（"+i+"）")));blood.value=editor.bloodline_id??"";blood.onchange=()=>editor.bloodline_id=blood.value===""?null:Number(blood.value);
    for(const key of ["up_id","down_id"]){const select=$("editor-modifier-"+key);select.replaceChildren(option(0,"尚未确定"));MODIFIERS.slice(1).forEach((dim,i)=>select.append(option(i+1,LABELS[dim])));select.value=editor.nature_modifiers[key];select.disabled=!!editor.hp_constraint;select.onchange=()=>{clearHpReverse();editor.nature_modifiers[key]=Number(select.value);renderEditor();};}
    const codeNote=$("editor-code-note"),notes=[],provenance=editor.code_provenance;if(provenance){if(editor.talent_selection.selected.some(d=>editor.talent_selection.value_sources[d]==="user_default"))notes.push("个体默认10来自用户设置，不是码内解出的数值。");if(editor.talent_selection.selected.length<3&&provenance.issues.some(i=>i.code==="duplicate_talent_markers"&&(i.member_slot==null||i.member_slot===provenance.original_member.slot)))notes.push("原码含重复个体标记，请按实际配置补选。");if(editor.move_ids.every(id=>id!==0)&&!editor.move_ids.every(id=>editor.original?.confirmed.moves.some(x=>same(x,id))))notes.push("己方行动默认只显示已配置的四招；未填写的字段在对战台显示为待确认。");}codeNote.hidden=!notes.length;codeNote.textContent=notes.join(" ");
    renderTalents();renderMoves();}
  function renderTalents(){const t=$("editor-talents"),s=editor.talent_selection;t.replaceChildren();$("editor-talent-count").textContent=s.selected.length+" / 3"+(s.selected.length<3?" · 待补选":"");for(const d of DIMS){const row=el("div",null,"field"),label=el("label",null,"checkline"),check=el("input");check.type="checkbox";check.checked=s.selected.includes(d);check.disabled=d==="hp"&&!!editor.hp_constraint||!check.checked&&s.selected.length===3;check.onchange=()=>{clearHpReverse();s.selection_source="user_selected";if(check.checked){s.selected.push(d);s.values[d]=10;s.value_sources[d]="user_default";}else{s.selected=s.selected.filter(x=>x!==d);delete s.values[d];delete s.value_sources[d];}renderEditor();};label.append(check,el("span",LABELS[d]));row.append(label);if(check.checked){const input=el("input");input.type="number";input.min="0";input.max="10";input.step="1";input.required=true;input.disabled=d==="hp"&&!!editor.hp_constraint;input.setAttribute("aria-label",LABELS[d]+"个体加成");input.value=s.values[d];const source=el("small",s.value_sources[d]==="user_default"?"默认 10":"手动设置");input.oninput=()=>{clearHpReverse();s.values[d]=input.value===""?null:Number(input.value);s.value_sources[d]="user_entered";source.textContent="手动设置";const wrap=$("editor-summary").children[1];wrap.replaceChildren();renderHpEditor(data.form(editor.form_id),wrap);};row.append(input,source);}else row.append(el("small","未选 / 未知"));t.append(row);}if(DIMS.some(d=>editor.talents[d]!==null)){const old=el("details");old.append(el("summary","历史六维资质保留"),el("p",DIMS.map(d=>LABELS[d]+" "+(editor.talents[d]??"未知")).join(" / ")));t.append(old);}}
  function renderMoves(){const slots=$("chosen-slots");slots.replaceChildren();editor.move_ids.forEach((id,i)=>{const row=el("div",null,"chosen-slot");row.append(el("span",String(i+1),"slot-number"),el("strong",id===0?"空槽":name(data.move(id))));if(i>0)row.append(button("↑",()=>{[editor.move_ids[i-1],editor.move_ids[i]]=[editor.move_ids[i],editor.move_ids[i-1]];renderMoves();}));if(i<3)row.append(button("↓",()=>{[editor.move_ids[i+1],editor.move_ids[i]]=[editor.move_ids[i],editor.move_ids[i+1]];renderMoves();}));if(id!==0)row.append(button("清空",()=>{editor.move_ids[i]=0;renderMoves();},"quiet small"));slots.append(row);});$("move-count").textContent=editor.move_ids.filter(x=>x!==0).length+"/4 · 空槽保留位置";const q=$("move-search").value.trim(),wrap=$("editor-moves");wrap.replaceChildren();for(const src of data.sources(editor.form_id)){const m=data.move(src.id);if(!m||!(name(m)+" "+zh(m.desc)).includes(q))continue;const label=el("label",null,"skill-option"),check=el("input");check.type="checkbox";check.checked=editor.move_ids.some(x=>same(x,m.id));check.disabled=!check.checked&&!editor.move_ids.includes(0);check.onchange=()=>{if(check.checked){const slot=editor.move_ids.indexOf(0);if(slot>=0)editor.move_ids[slot]=m.id;}else editor.move_ids=editor.move_ids.map(x=>same(x,m.id)?0:x);renderMoves();};const body=el("div");body.append(el("strong",name(m)),el("p",zh(m.desc)||"描述待核验","skill-desc"),el("small",src.labels.join(" / "),"skill-source"));label.append(check,body);wrap.append(label);}}
  function saveMember(){writable();for(const input of $("editor-talents").querySelectorAll("input"))if(!input.reportValidity())return;if(editor.side==="my"&&editor.talent_selection.selected.length!==3)throw Error("我方个体须从六项中选择三项；重复阵容码标记不代表多个维度，请补选。对方未知配置可暂留未选项。");const directions=editor.nature_modifiers;if(editor.side==="my"&&(!directions.up_id||!directions.down_id||directions.up_id===directions.down_id))throw Error("请为我方选择不同的增益方向和减益方向，以计算具体生命数值。");const original=editor.original,directionsComplete=directions.up_id>0&&directions.down_id>0&&directions.up_id!==directions.down_id,c={nature:false,talents:{},moves:[]};if(original&&!editor.confirmationChanged){c.nature=original.confirmed.nature&&same(editor.nature_id,original.nature_id);for(const d of DIMS)c.talents[d]=original.confirmed.talents[d]&&editor.talents[d]===original.talents[d];c.moves=editor.move_ids.filter(id=>original.confirmed.moves.some(x=>same(x,id)));}else{c.nature=directionsComplete;for(const d of DIMS)c.talents[d]=editor.talents[d]!=null;c.moves=editor.move_ids.filter(x=>x!==0);}
    const team=app.session.teams[editor.side],idx=team.findIndex(x=>x.member_id===editor.mid),sameSpecies=idx>=0&&same(team[idx].form_id,editor.form_id),m=data.member({member_id:sameSpecies?editor.mid:uid(),form_id:editor.form_id,nature_id:editor.nature_id,talents:editor.talents,talent_selection:editor.talent_selection,talent_note:editor.talent_note,move_ids:editor.move_ids,bloodline_id:editor.bloodline_id,nature_modifiers:editor.nature_modifiers,code_provenance:editor.code_provenance,confirmed:c},editor.side,0);if(idx<0)team.push(m);else{if(!same(team[idx].form_id,m.form_id)||JSON.stringify(team[idx].move_ids)!==JSON.stringify(m.move_ids)){delete app.session.slot_overrides?.[team[idx].member_id];delete app.session.pending_transforms?.[team[idx].member_id];}team[idx]=m;}const d=app.session.draft[editor.side];if(d.active_member_id===editor.mid){d.active_member_id=m.member_id;d.move_id=null;}if(d.target_member_id===editor.mid)d.target_member_id=m.member_id;delete app.session.opponent_beliefs[editor.mid];persist();$("member-dialog").close();render();}
  const issueLabels={format_error:"格式错误",user_confirmed_error:"用户已确认的错误",database_conflict:"当前数据库冲突",unverified:"待核实"};
  let codeResults=[],codeSelection=0,codeRequest=0;
  function selectedCode(){return codeResults[codeSelection]?.result;}
  function invalidateCode(){codeRequest++;codeResults=[];$("code-results").replaceChildren();$("code-query-status").replaceChildren();$("code-entry").replaceChildren();$("code-entry-field").hidden=true;$("code-import").disabled=true;$("code-export").disabled=true;$("code-ack").checked=false;}
  function updateCodeImport(){const result=selectedCode();$("code-import").disabled=!(result?.importable===true&&result.format_valid===true&&$("code-ack").checked);}
  function previewCode(){const r=selectedCode(),wrap=$("code-results");wrap.replaceChildren();$("code-ack").checked=false;updateCodeImport();if(!r)return;
    wrap.append(el("h3",r.format_valid?"字段解析完成 · 合法性需单独核验":"未通过格式校验"),el("p","协议 "+(r.protocol_version??"未知")+" · 队伍类型编号 "+(r.team_type_id??"未知")+"（含义待核实） · 快照 "+(r.snapshot_id||"未知"),"section-note"));
    if(r.core_magic)wrap.append(el("p","核心魔法："+(r.core_magic.name||"名称待核实")+" · 原始 ID "+r.core_magic.id));
    const issues=el("div",null,"code-issues");for(const category of Object.keys(issueLabels)){const items=(r.issues||[]).filter(x=>x.category===category);if(!items.length)continue;const section=el(category==="unverified"?"details":"section",null,"code-issue-group "+category);if(category==="unverified"){const keys=new Set(items.map(x=>x.code)),summary=[];if(keys.has("full_talents_unknown")||keys.has("duplicate_talent_markers"))summary.push("完整资质未知");if(keys.has("learning_conditions_unverified"))summary.push("等级或解锁条件不足");if(keys.has("code_version_unknown"))summary.push("资料版本未提供");if(keys.has("team_type_meaning_unknown"))summary.push("队伍类型含义未知");if(!summary.length)summary.push("仍有信息需要核对");section.append(el("summary",issueLabels[category]+" · "+items.length+" 项 · "+summary.join("；")+"（展开查看）"));}else section.append(el("h3",issueLabels[category]+" · "+items.length));for(const i of items){section.append(el("p",i.message));const detail=el("details");detail.append(el("summary","字段、原码结果与依据"),el("pre",JSON.stringify({member_slot:i.member_slot,field:i.field,raw_value:i.raw_value,evidence:i.evidence},null,2)));section.append(detail);}issues.append(section);}wrap.append(issues);
    const members=el("div",null,"code-members");for(const m of r.members||[]){const card=el("article",null,"code-member");card.append(el("h3",m.slot+". "+(m.form_name||"未知精灵")+" · ID "+m.form_id),el("p","血脉："+(m.bloodline_name||"未知")+" · ID "+m.bloodline_id));
      const n=m.nature||{};card.append(el("p","原性格："+(n.original?.name||"未指定")+" · ID "+m.nature_id+" · "+(LABELS[n.original?.up]||"未知")+"↑ / "+(LABELS[n.original?.down]||"未知")+"↓"),el("p","后天修正原值："+JSON.stringify(n.modifiers||{})+" → "+(LABELS[n.final?.up]||"未知")+"↑ / "+(LABELS[n.final?.down]||"未知")+"↓"));
      const slots=el("ol",null,"code-slots");for(const [index,id] of (m.move_ids||[]).entries()){const move=m.moves?.[index];slots.append(el("li",(id===0?"空槽":(move?.name||"未知技能")+" · ID "+id)+"（槽 "+(index+1)+"）"));}card.append(slots,el("p","原始个体加成标记："+JSON.stringify(m.raw_talent_markers)+"；完整六维资质未知。"));members.append(card);}wrap.append(members);
    wrap.append(el("p",r.importable?"可导入为研究配置。问题与原始字段会一起保留，完整资质保持未知，禁止进入正式训练。":"当前结果不可导入；不会替换精灵、血脉、性格或技能。请核对问题后重新解析。","code-warning"));
    const raw=el("details");raw.append(el("summary","查看完整解析与原始字段"),el("pre",JSON.stringify(r,null,2)));wrap.append(raw);$("code-export").disabled=false;
  }
  function codeMode(){const library=$("team-code-mode").value==="library";invalidateCode();$("team-code-title").textContent=library?"识别对方阵容":"解析阵容码";$("code-input-label").textContent=library?"已知的对方精灵（输入一只即可，多只同时匹配）":"原始阵容码（支持多行，每行一条）";$("team-code-input").placeholder=library?"例如：雪灵、斑枭；逐步补充已知精灵以缩小范围":"粘贴阵容码，保留 ~ 等原始字符";$("code-parse").textContent=library?"查询阵容库":"解析并校验";$("code-target").disabled=library;if(library)$("code-target").value="opponent";$("code-library-note").hidden=!library;}
  async function parseCodeInput(){const value=$("team-code-input").value,library=$("team-code-mode").value==="library";invalidateCode();if(!value.length)throw Error(library?"请输入至少一只已知精灵":"请粘贴一条或多条阵容码，每行一条");const token=++codeRequest;$("code-parse").disabled=true;$("code-results").replaceChildren(el("p",library?"正在匹配已存阵容库…":"正在逐条解析与核对 BWIKI…"));try{const response=await fetch(library?"/api/opponent/search":"/api/team-codes/parse",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text:value})}),payload=await response.json();if(token!==codeRequest)return;if(!response.ok)throw Error(payload.error||"解析服务不可用");if(library){if(!Array.isArray(payload.matches))throw Error("阵容匹配返回格式无效");codeResults=payload.matches;const status=$("code-query-status");status.append(el("p","匹配 "+payload.matched_teams+" / "+payload.total_teams+" 套阵容；多只精灵按同时包含筛选。","code-warning"));if(payload.notice)status.append(el("p",payload.notice,"section-note"));for(const issue of payload.query?.issues||[])status.append(el("p",(issueLabels[issue.category]||"提示")+"："+issue.message,"danger"));for(const member of payload.query?.members||[])if(member.candidates?.length>1)status.append(el("p",String(member.raw_input)+" 可指："+member.candidates.map(x=>x.title+"（ID "+x.id+"）").join("、")+"。请修改输入，指定具体形态。"));}else codeResults=payload.results;
      if(!Array.isArray(codeResults)||codeResults.length>200)throw Error("解析返回格式无效");codeSelection=0;$("code-entry").replaceChildren();codeResults.forEach((entry,i)=>$("code-entry").append(option(i,(library?"库中":"第 ")+entry.line+" 行 · "+(entry.result.members||[]).map(m=>m.form_name||m.form_id).join("、")+" · "+(entry.result.importable?"可研究导入":"需处理问题"))));$("code-entry-field").hidden=codeResults.length===0;previewCode();if(!codeResults.length)$("code-results").append(el("p",library?"没有可选阵容。请核对精灵形态或减少筛选条件；不会生成虚构队伍。":"没有可解析的阵容码。","code-warning"));
    }catch(e){if(token===codeRequest){$("code-results").replaceChildren(el("p",e.message,"danger"));throw e;}}finally{$("code-parse").disabled=false;}}
  function importCodeSelection(){writable();const result=selectedCode();if(!$("code-ack").checked)throw Error("请先阅读并确认研究导入说明");const side=$("code-target").value;if(!SIDES.includes(side))throw Error("导入目标无效");const team=data.importCode(result,side,uid);for(const old of app.session.teams[side]){delete app.session.slot_overrides?.[old.member_id];delete app.session.pending_transforms?.[old.member_id];}app.session.teams[side]=team;app.session.draft[side]=data.draft(undefined,app.session.teams)[side];if(side==="opponent")app.session.opponent_beliefs={};else app.active_template_id=null;persist();$("team-code-dialog").close();render();toast("已导入研究配置：四槽、原始标记和问题均保留；未进入正式训练。");}
  function bind(){
    $("open-team-code").onclick=()=>guard(()=>{writable();$("team-code-mode").value="code";codeMode();$("team-code-input").value="";$("team-code-dialog").showModal();});$("open-opponent-search").onclick=()=>guard(()=>{writable();$("team-code-mode").value="library";codeMode();$("team-code-input").value="";$("team-code-dialog").showModal();});$("team-code-mode").onchange=()=>{codeMode();$("team-code-input").value="";};$("close-team-code").onclick=()=>$("team-code-dialog").close();$("team-code-input").oninput=invalidateCode;$("code-parse").onclick=()=>guard(parseCodeInput);$("code-entry").onchange=()=>{codeSelection=Number($("code-entry").value);previewCode();};$("code-ack").onchange=updateCodeImport;$("code-import").onclick=()=>guard(importCodeSelection);$("code-export").onclick=()=>download(selectedCode(),"roco-team-code-analysis.json");
    for(const side of SIDES)$("add-"+side).onclick=()=>guard(()=>openEditor(side));
    $("close-editor").onclick=()=>$("member-dialog").close();$("picker-search").oninput=()=>{editor.page=0;renderPicker();};$("move-search").oninput=renderMoves;$("save-member").onclick=()=>guard(saveMember);
    $("round-form").onsubmit=e=>{e.preventDefault();guard(record);};$("undo-round").onclick=()=>guard(undo);
    $("save-template").onclick=()=>guard(()=>{writable();const n=$("template-name").value.trim();if(!n||n.length>60)throw Error("请填写 1–60 字的模板名称");if(!app.session.teams.my.length)throw Error("请先添加我方阵容");const old=app.templates.find(t=>t.name===n);if(old&&!confirm("替换同名模板“"+n+"”？"))return;const t={id:old?.id||uid(),name:n,team:clone(app.session.teams.my),snapshot_id:currentSnapshot,updated_at:new Date().toISOString()};if(old)app.templates[app.templates.indexOf(old)]=t;else app.templates.push(t);app.active_template_id=t.id;persist();renderTemplates();refreshAdvice();toast("模板已保存");});
    $("load-template").onclick=()=>guard(()=>{writable();const t=app.templates.find(t=>t.id===$("template-select").value);if(!t)throw Error("请先选择模板");if(!confirm("用“"+t.name+"”替换当前我方阵容？历史记录保持原配置。"))return;for(const old of app.session.teams.my){delete app.session.slot_overrides?.[old.member_id];delete app.session.pending_transforms?.[old.member_id];}app.session.teams.my=clone(t.team);app.session.draft.my=data.draft(undefined,app.session.teams).my;app.active_template_id=t.id;persist();render();});
    $("delete-template").onclick=()=>guard(()=>{writable();const t=app.templates.find(t=>t.id===$("template-select").value);if(!t)throw Error("请先选择模板");if(!confirm("永久删除模板“"+t.name+"”？当前阵容不受影响。"))return;app.templates=app.templates.filter(x=>x.id!==t.id);if(app.active_template_id===t.id)app.active_template_id=null;persist();renderTemplates();refreshAdvice();});
    $("export-session").onclick=()=>download(app.session,"roco-session-"+app.session.match_id+".json");$("import-session").onclick=()=>$("import-file").click();
    $("import-file").onchange=()=>guard(async()=>{writable();const file=$("import-file").files[0];$("import-file").value="";if(!file)return;if(file.size>8*1024*1024)throw Error("文件超过 8 MB");const raw=JSON.parse(await file.text()),s=data.session(raw);if(!confirm("导入会替换当前对局，阵容模板保留。请先导出需要保留的对局。继续？"))return;app.session=s;app.session.match_id=uid();persist();render();toast("对局已导入；模板与旧手札未覆盖。");});
    $("new-match").onclick=()=>guard(()=>{writable();if(!confirm("开始新对局并清空当前对手与回合记录？我方阵容和模板保留。"))return;app.session=fresh(app.session.teams.my);persist();render();});
    for(const id of ["preview-my-patk","preview-my-matk","preview-opp-pdef","preview-opp-mdef"]){const node=$(id);if(node)node.oninput=()=>{try{previewStatTerms();}catch(error){$("preview-badge").textContent="修正格式无效";$("preview-content").replaceChildren(el("p",error.message,"preview-note"));return;}refreshPreview();};}
    window.addEventListener("storage",e=>{if(e.key===KEY&&e.newValue!==lastSaved)protect("另一页面已更新存档，本页暂停保存，避免覆盖。",null);});
  }
  async function boot(){try{const results=await Promise.all([json("/api/catalog"),json("/api/status"),json("/api/action-mechanics"),json("/api/pvp/rules")]);catalog={...results[0],action_mechanics:results[2],pvp_rules:results[3]};data=BattleData.create(catalog);currentSnapshot=catalog.snapshot_id||results[1].snapshot_id;if(!currentSnapshot)throw Error("当前资料缺少快照标识");$("version-label").textContent="BWIKI · "+(catalog.source_version||results[1].source_version||"")+" · "+catalog.forms.length+" 个形态 / "+Object.keys(catalog.moves).length+" 个技能";load();bind();render();window.RocoSimulation?.mount({catalog,rules:catalog.pvp_rules,readSession:()=>clone(app.session)});}catch(e){$("error-banner").hidden=false;$("error-banner").textContent="页面初始化失败："+e.message+"。未覆盖已有存档。";}}
  boot();
})();
