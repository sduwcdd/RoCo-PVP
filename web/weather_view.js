"use strict";
/* Weather is derived from actions by the server. This module never changes real HP. */
(function(root){
  const names={rain:"雨天",sandstorm:"沙暴",blizzard:"暴风雪",snow:"雪天",thunder:"雷鸣",none:"无天气",unknown:"待核实"};
  const sides={a:"我方",b:"对方",my:"我方",opponent:"对方"};
  const list=value=>value==null?[]:Array.isArray(value)?value:[value];
  function title(weather){if(weather===null)return "无天气";if(!weather)return "天气尚未完成推演";return (weather.name||names[weather.kind]||weather.kind||"待核实")+(Number.isInteger(weather.remaining_rounds)?" · 剩余 "+weather.remaining_rounds+" 回合":" · 持续时间待核实");}
  function effects(weather){return list(weather?.effect_summary).filter(x=>typeof x==="string");}
  function affectedLines(values){return list(values).flatMap(v=>{if(typeof v==="string")return [v];if(!v)return [];const prefix=(sides[v.side||v.target_side]||"")+(v.name||v.member_name?" · "+(v.name||v.member_name):"");const descriptions=list(v.effects||v.effect_summary||v.summary||v.description).map(x=>typeof x==="string"?x:x?.description||x?.summary||"").filter(Boolean);return descriptions.map(x=>(prefix?prefix+"：":"")+x);});}
  function uncertaintyText(value){
    if(typeof value==="string")return value;
    if(!value||typeof value!=="object")return "天气规则依据不完整";
    const details=[value.message,value.reason,value.description,value.detail,value.text].filter(x=>typeof x==="string"&&x.trim());
    if(details.length)return [...new Set(details)].join("；");
    if(value.expected!==undefined||value.actual!==undefined)return "资料版本不一致：预期 "+(value.expected??"未知")+"，实际 "+(value.actual??"未知");
    return "待核实项："+(value.id||"未注明具体原因");
  }
  function eventText(event){
    const op=event?.op||event?.type;if(!op?.startsWith("weather."))return null;
    const weather=event.weather||event.after_weather||(typeof event.after==="object"?event.after:null),name=event.name||weather?.name||names[event.kind||weather?.kind||(typeof event.weather==="string"?event.weather:null)]||"天气";
    if(op==="weather.set")return "天气变为"+name+(Number.isInteger(weather?.remaining_rounds??event.remaining_rounds)?" · 持续 "+(weather?.remaining_rounds??event.remaining_rounds)+" 回合":"");
    if(op==="weather.tick")return name+"倒计时："+(event.before??event.remaining_before??"?")+" → "+(event.after??event.remaining_rounds??event.remaining_after??"?")+" 回合";
    if(op==="weather.extend")return name+"延长 "+(event.amount??event.after-event.before)+" 回合"+(event.response_success?"（应对成功）":"")+"："+event.before+" → "+event.after+" 回合";
    if(op==="weather.expired")return name+"结束";
    const target=sides[event.target_side||event.side]||"场上",status={freeze:"冻结",conductive:"引电",electric:"引电",induction:"引电",electricity:"引电"}[event.status]||event.status;
    if(op==="weather.effect"){
      let detail=event.message||event.description;
      if(!detail){if(event.immune)detail="属性免疫，未受影响";else if(event.effect_op==="status.clear")detail="离场清除"+(status||"天气状态")+(Number.isInteger(event.before)?" "+event.before+" 层":"");else if(event.effect_op==="conductive.damage")detail="引电放电，损失生命 "+event.amount;else if(event.effect_op==="freeze.exhaust")detail="冻结触发力竭";else if(event.effect_op==="hp.restore")detail="恢复生命 "+event.amount;else if(event.effect_op==="hp.damage")detail="损失生命 "+event.amount;else if(event.effect_op==="energy.reduce")detail="减少能量 "+event.amount;else if(status)detail="增加"+status+" "+(event.amount??event.layers??0)+" 层"+(Number.isInteger(event.after)?"（现有 "+event.after+" 层）":"");else detail="天气效果";}
      return target+" · "+name+"："+(event.predicted?"预计":"")+detail;
    }
    return event.message||name+"效果已结算";
  }
  function compactSession(session){
    const member=m=>Object.fromEntries(["member_id","form_id","move_ids","nature_id","nature_modifiers","talents","talent_selection","bloodline_id","max_energy","stats","name"].filter(k=>m[k]!==undefined).map(k=>[k,m[k]]));
    const teams=t=>Object.fromEntries(["my","opponent"].map(side=>[side,(t?.[side]||[]).map(member)]));
    return {match_id:session.match_id,snapshot_id:session.snapshot_id,opening_full_hp:session.opening_full_hp===true,teams:teams(session.teams),rounds:(session.rounds||[]).map(r=>({event_id:r.event_id,turn:r.turn,action_order:r.action_order,snapshot_id:r.snapshot_id,opening_full_hp:r.opening_full_hp===true,my:r.my,opponent:r.opponent,teams_snapshot:r.teams_snapshot?teams(r.teams_snapshot):undefined})),draft:Object.fromEntries(["my","opponent"].map(side=>[side,{active_member_id:session.draft?.[side]?.active_member_id||""}]))};
  }
  function createReplayModel({fetch:request,onChange=()=>{}}){
    let state={status:"idle",data:null,error:null,key:null},sequence=0,pending=null;const cache=new Map();
    function update(session,{force=false}={}){const payload=compactSession(session),key=JSON.stringify(payload);if(!force&&key===state.key&&["loading","ready"].includes(state.status))return pending||Promise.resolve(state.data);const token=++sequence;
      if(!force&&cache.has(key)){state={status:"ready",data:cache.get(key),error:null,key};onChange(state);return Promise.resolve(state.data);}
      state={status:"loading",data:null,error:null,key};onChange(state);
      pending=(async()=>{try{const response=await request("/api/weather/replay",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({session:payload})}),data=await response.json();if(token!==sequence)return null;if(!response.ok)throw Error(data.error||"天气推演请求失败");if(!data||!Object.hasOwn(data,"current")||!Array.isArray(data.frames))throw Error("天气推演结果不完整");cache.set(key,data);while(cache.size>10)cache.delete(cache.keys().next().value);state={status:"ready",data,error:null,key};onChange(state);return data;}catch(error){if(token===sequence){state={status:"error",data:null,error:error.message,key};onChange(state);}return null;}finally{if(token===sequence)pending=null;}})();return pending;
    }
    return {update,get state(){return state;}};
  }
  const api={title,effects,affectedLines,uncertaintyText,eventText,compactSession,createReplayModel};root.RocoWeatherView=api;if(typeof module!=="undefined"&&module.exports)module.exports=api;
})(typeof globalThis!=="undefined"?globalThis:this);
