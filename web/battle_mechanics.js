"use strict";
// Observation bookkeeping only: response success must be explicitly observed by the user.
const BattleMechanics = (() => {
  const SIDES = ["my", "opponent"];
  const GENERATORS = {borrow:7020840, mind_read:7020850, rewrite:7020860};
  const object = x => !!x && typeof x === "object" && !Array.isArray(x);
  const copy = x => x == null ? x : JSON.parse(JSON.stringify(x));
  const same = (a,b) => String(a) === String(b);
  const own = (x,k) => object(x) && Object.hasOwn(x,k);
  const isSlot = x => Number.isInteger(x) && x >= 0 && x < 4;
  const members = (session,side) => Array.isArray(session?.teams?.[side]) ? session.teams[side] : [];
  const move = (catalog,id) => catalog?.moves?.[id];
  const ids = (values,catalog) => [...new Set((values || []).filter(id => Number.isSafeInteger(Number(id)) && Number(id)>0 && move(catalog,id)).map(Number))];
  function currentMoves(session,member) {
    const slots = own(session?.slot_overrides,member?.member_id) ? session.slot_overrides[member.member_id] : member?.move_ids;
    return Array.isArray(slots) ? [...slots] : [];
  }
  function learnset(catalog,member) {
    const pool = catalog?.details?.[member?.form_id]?.learnset || {};
    return ids(["pool","native","stones","legacy","legendary"].flatMap(k => (pool[k] || []).map(x => object(x) ? x.move ?? x.id : x)),catalog);
  }
  function evidence(meta,catalog) {
    return {source:copy(meta?.source ?? null),snapshot_id:meta?.snapshot_id ?? catalog?.snapshot_id ?? null,uncertainty:copy(meta?.uncertainty ?? null)};
  }
  function blocked(meta) {
    const reasons = Array.isArray(meta?.blockers) ? [...meta.blockers] : [];
    if (["blocked","unsupported","unresolved"].includes(meta?.status) && !reasons.length) reasons.push("此变化的候选池尚未确认");
    return reasons;
  }
  function pending(session,member) { return session?.pending_transforms?.[member?.member_id] || {}; }
  function getPool(catalog,metadata,session,side,member,mode,slot=null) {
    const result = {ids:[],source_slots:[],blockers:[]};
    if (!SIDES.includes(side) || !members(session,side).some(m => same(m.member_id,member?.member_id))) { result.blockers.push("技能来源成员不属于当前一方阵容"); return result; }
    if (slot !== null && !isSlot(slot)) { result.blockers.push("技能来源槽必须为 0–3"); return result; }
    const slots = currentMoves(session,member), transforms = pending(session,member);
    if (mode === "carried") {
      slots.forEach((id,i) => { if ((slot === null || slot === i) && !own(transforms,i) && move(catalog,id) && Number(id)>0) { result.ids.push(Number(id)); result.source_slots.push({member_id:member.member_id,slot:i,move_id:Number(id),mode}); } });
    } else if (mode === "temporary") {
      for (const [key,value] of Object.entries(transforms)) {
        const i = Number(key); if (!isSlot(i) || slot !== null && slot !== i) continue;
        const reasons = blocked(value); result.blockers.push(...reasons);
        result.source_slots.push({member_id:member.member_id,slot:i,move_id:value.base_id,base_id:value.base_id,mode,...evidence(value,catalog)});
        if (!reasons.length) result.ids.push(...ids(value.pool_ids,catalog));
      }
      if (!result.source_slots.length) result.blockers.push("此成员没有待使用的巧变技能槽");
    } else if (Object.hasOwn(GENERATORS,mode)) {
      const generatorId = GENERATORS[mode], meta = metadata?.generators?.[generatorId];
      if (!meta || meta.kind !== mode) { result.blockers.push("当前资料没有此技能生成方式的来源记录"); return result; }
      slots.forEach((id,i) => { if (same(id,generatorId) && !own(transforms,i) && (slot === null || slot === i)) result.source_slots.push({member_id:member.member_id,slot:i,move_id:Number(id),mode,...evidence(meta,catalog)}); });
      if (!result.source_slots.length) { result.blockers.push("当前四槽没有携带此生成技能"); return result; }
      result.blockers.push(...blocked(meta));
      if (!result.blockers.length) {
        if (mode === "borrow") result.ids = members(session,side).filter(m => !same(m.member_id,member.member_id)).flatMap(m => currentMoves(session,m).filter((id,i) => {
          if (!own(pending(session,m),i)) return true;
          result.blockers.push("队友 " + m.member_id + " 的槽 " + (i+1) + " 正在巧变，随机结果未知，已排除此槽并保留其他已知候选");
          return false;
        }));
        else if (mode === "mind_read") result.ids = members(session,side === "my" ? "opponent" : "my").flatMap(m => learnset(catalog,m));
        else result.ids = learnset(catalog,member).filter(id => !slots.some(carried => same(id,carried)));
      }
    } else result.blockers.push("未知技能选择方式");
    result.ids = ids(result.ids,catalog); result.blockers = [...new Set(result.blockers)];
    return result;
  }
  function validateState(session,catalog) {
    const all = SIDES.flatMap(side => members(session,side)), memberIds = new Set(all.map(m => m.member_id));
    if (memberIds.size !== all.length || all.some(m => typeof m.member_id !== "string" || ["__proto__","prototype","constructor"].includes(m.member_id))) throw Error("变化记录的成员标识无效或重复");
    const overrides = session?.slot_overrides ?? {}, transforms = session?.pending_transforms ?? {};
    if (!object(overrides) || !object(transforms)) throw Error("技能槽变化记录必须为对象");
    for (const [mid,slots] of Object.entries(overrides)) {
      if (!memberIds.has(mid) || !Array.isArray(slots) || slots.length !== 4 || slots.some(id => id !== 0 && (!Number.isSafeInteger(id) || !move(catalog,id)))) throw Error("当前技能槽变化记录无效");
    }
    for (const [mid,entries] of Object.entries(transforms)) {
      if (!memberIds.has(mid) || !object(entries)) throw Error("巧变记录的成员无效");
      const member = all.find(m => same(m.member_id,mid)), slots = currentMoves(session,member);
      for (const [key,p] of Object.entries(entries)) {
        if (!/^[0-3]$/.test(key) || !object(p) || !Number.isSafeInteger(p.base_id) || !move(catalog,p.base_id) || !same(slots[Number(key)],p.base_id) || !Array.isArray(p.pool_ids) || p.pool_ids.some(id => !Number.isSafeInteger(id) || !move(catalog,id)) || (p.blockers != null && !Array.isArray(p.blockers))) throw Error("巧变槽、原技能或候选池记录无效");
      }
    }
    return {slot_overrides:copy(overrides),pending_transforms:copy(transforms)};
  }
  function applyRound(session,round,metadata,catalog) {
    const out = {...validateState(session,catalog),events:[],warnings:[]}, proposals = [];
    if (!object(metadata?.transformations)) {
      out.warnings.push("技能变化来源资料未加载，未自动更新技能槽或巧变生命周期");
      return out;
    }
    const warn = (side,message) => out.warnings.push((side === "my" ? "我方：" : "对方：") + message);
    const original = {...session,slot_overrides:out.slot_overrides,pending_transforms:out.pending_transforms};
    function located(side,action,member,id) {
      const slot = action.generator_slot, slots = currentMoves(session,member);
      if (!isSlot(slot) || !same(slots[slot],id)) { warn(side,"缺少明确且匹配的来源技能槽，未修改技能槽"); return null; }
      if (slots.filter(value => same(value,id)).length !== 1) { warn(side,"多个技能槽含有相同技能，生命周期有歧义，未修改技能槽"); return null; }
      return slot;
    }
    for (const side of SIDES) {
      const action = round?.[side], otherSide = side === "my" ? "opponent" : "my", other = round?.[otherSide];
      if (!action || action.kind !== "move") continue;
      const member = members(session,side).find(m => same(m.member_id,action.member_id));
      if (!member || !move(catalog,action.move_id)) { warn(side,"行动成员或技能不在当前资料中"); continue; }
      const mode = action.skill_mode || "carried", pool = getPool(catalog,metadata,session,side,member,mode,action.generator_slot ?? null);
      if (!pool.ids.some(id => same(id,action.move_id))) { warn(side,"所选技能不属于当前来源池：" + (pool.blockers.join("；") || "请核对技能和来源槽")); continue; }
      const meta = metadata?.transformations?.[action.move_id];
      if (mode === "temporary") {
        const slot = action.generator_slot, p = pending(session,member)[slot];
        if (!isSlot(slot) || !p || !p.pool_ids.some(id => same(id,action.move_id))) { warn(side,"临时技能缺少明确巧变来源槽，未恢复原技能"); continue; }
        if (meta) { warn(side,"随机结果本身含巧变或槽替换，嵌套生命周期无法可靠定位，未自动恢复或变化"); continue; }
        proposals.push({side,member,slot,id:p.base_id,clear:true,type:"temporary_return",meta:p});
        continue;
      }
      if (!meta) continue;
      if (mode !== "carried") { warn(side,"借用、取念或复写结果含技能变化，无法可靠定位本体生命周期，未持久替换"); continue; }
      const sourceSlot = located(side,action,member,action.move_id); if (sourceSlot === null) continue;
      if (meta.kind === "clever_change") {
        if (meta.trigger?.event !== "after_use") { warn(side,"巧变触发条件未确认，未建立临时池"); continue; }
        proposals.push({side,member,slot:sourceSlot,type:"clever_change",meta,id:action.move_id});
      } else if (meta.kind === "slot_replace") {
        if (meta.trigger?.event !== "response_success" || action.response_success !== true) { warn(side,"尚未明确观察确认应对成功，未替换技能槽"); continue; }
        if (meta.trigger.choice_required && action.response_choice !== true) { warn(side,"尚未明确选择应对分支，未替换技能槽"); continue; }
        if (!other || other.kind !== "move" || !move(catalog,other.move_id)) { warn(side,"缺少对方本轮实际使用的技能，未替换技能槽"); continue; }
        const targetKind = move(catalog,other.move_id)?.kind, expected = meta.trigger.response_kind;
        if (!(expected === "attack" && ["physical","magical"].includes(targetKind) || expected === "status" && targetKind === "status")) { warn(side,"对方本轮技能类别与应对条件不符或未确认，未替换技能槽"); continue; }
        if (blocked(meta).length) { warn(side,blocked(meta).join("；")); continue; }
        if (meta.scope === "self_slot" && meta.replacement_source === "opponent_selected_skill") proposals.push({side,member,slot:sourceSlot,id:Number(other.move_id),type:"slot_replace",meta});
        else if (meta.scope === "opponent_slot" && move(catalog,meta.replacement_id)) {
          const target = members(session,otherSide).find(m => same(m.member_id,other.member_id));
          if (!target || (other.skill_mode || "carried") !== "carried") { warn(side,"敌方技能来自随机或临时来源，无法定位应替换的原槽"); continue; }
          const targetSlot = located(otherSide,other,target,other.move_id); if (targetSlot !== null) proposals.push({side,member:target,slot:targetSlot,id:Number(meta.replacement_id),type:"slot_replace",meta});
        } else warn(side,"槽替换目标或替换技能未确认，未修改技能槽");
      }
    }
    // All proposals use the pre-round snapshot. Overlapping writes never guess execution order.
    const collisions = new Set(proposals.filter((p,i) => proposals.some((q,j) => i !== j && same(p.member.member_id,q.member.member_id) && p.slot === q.slot)).map(p => p.member.member_id+":"+p.slot));
    for (const p of proposals) {
      const mid = p.member.member_id;
      if (collisions.has(mid+":"+p.slot)) { warn(p.side,"同回合多个变化作用于同一技能槽，顺序未确认，保留回合前状态"); continue; }
      if (p.type === "slot_replace" && own(pending(session,p.member),p.slot)) { warn(p.side,"目标技能槽仍有未结束巧变，未猜测覆盖顺序"); continue; }
      const info = evidence(p.meta,catalog);
      if (p.type === "clever_change") {
        const value = {base_id:p.id,pool_ids:ids(p.meta.pool_ids,catalog),...copy(p.meta),...info};
        // Never retain invalid candidates from metadata, and keep blocked pools visibly blocked.
        value.pool_ids = ids(p.meta.pool_ids,catalog); value.base_id = p.id;
        if (!value.pool_ids.length && !blocked(value).length) value.blockers = ["当前资料没有可确认的巧变候选技能"];
        if (!out.pending_transforms[mid]) out.pending_transforms[mid] = {};
        out.pending_transforms[mid][p.slot] = value;
      } else {
        if (!out.slot_overrides[mid]) {
          const slots = currentMoves(original,p.member);
          out.slot_overrides[mid] = Array.from({length:4},(_,i) => slots[i] ?? 0);
        }
        out.slot_overrides[mid][p.slot] = p.id;
        if (p.clear) { delete out.pending_transforms[mid][p.slot]; if (!Object.keys(out.pending_transforms[mid]).length) delete out.pending_transforms[mid]; }
      }
      out.events.push({kind:p.type,member_id:mid,slot:p.slot,move_id:p.id,...info});
    }
    out.warnings = [...new Set(out.warnings)]; return out;
  }
  return {currentMoves,getPool,applyRound,validateState};
})();
if (typeof globalThis !== "undefined") globalThis.BattleMechanics = BattleMechanics;
if (typeof module !== "undefined" && module.exports) module.exports = BattleMechanics;
