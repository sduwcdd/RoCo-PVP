local SkillUtils = {}
local BattleConst = require("NewRoco.Modules.Core.Battle.Common.BattleConst")
local ProtoEnum = require("Data.PB.ProtoEnum")
local BuffUtils = require("NewRoco.Modules.Core.Battle.Entity.Components.Buff.BuffUtils")
local PriorityEnum = require("PriorityEnum")
local BattleUtils = require("NewRoco.Modules.Core.Battle.Common.BattleUtils")
local Enum = require("Data.Config.Enum")
local DummyTable = require("Common.DummyTable")
SkillUtils.hitAnimationName = {
  "hit1",
  "hit2",
  "hit3",
  "Hit1",
  "Hit2",
  "Hit3",
  "HIT1",
  "HIT2",
  "HIT3"
}
SkillUtils.AnimationPriority = {
  Die = {50},
  Attack1 = {10, Interrupt = 30},
  Attack2 = {10, Interrupt = 30},
  Skill1 = {20},
  Skill2 = {21},
  Skill3 = {22},
  SYHPVPWin = {27},
  Attack1Start = {20},
  Attack11 = {20},
  Attack1End = {20},
  Skill1Start = {20},
  Skill1Loop = {20},
  Skill1Loop1 = {20},
  Skill1Loop2 = {20},
  Skill1Trans1 = {20},
  Skill1End = {20},
  Skill2Start = {20},
  Skill2Loop1 = {20},
  Skill2Loop2 = {20},
  Skill2Loop3 = {20},
  Skill2Trans = {20},
  Skill2Trans1 = {20},
  Skill2Trans2 = {20},
  Skill2End = {20},
  Skill3Start = {20},
  Skill3Loop = {20},
  Skill3Loop1 = {20},
  Skill3Loop2 = {20},
  Skill3Trans = {20},
  Skill3End = {20},
  Hit1 = {10},
  Hit2 = {10},
  Hit3 = {10},
  Hurt = {10},
  Stun = {10},
  Happy = {2},
  Sad = {2},
  Shock = {2},
  Show = {2},
  Anger = {2},
  Fear = {2},
  Alert = {2},
  SleepStand = {2}
}

function SkillUtils.GetAnimStartPriority(AniName)
  if string.IsNilOrEmpty(AniName) then
    return 1
  end
  local cfg = SkillUtils.AnimationPriority[AniName]
  return cfg and cfg[1] or 1
end

function SkillUtils.GetAnimInterruptPriority(AniName)
  if string.IsNilOrEmpty(AniName) then
    return 1
  end
  local cfg = SkillUtils.AnimationPriority[AniName]
  if cfg then
    return cfg[1] + (cfg.Interrupt or 0)
  end
  return 1
end

function SkillUtils:CheckAnimCanPlay(waitPlay, curPlay)
  return SkillUtils.GetAnimStartPriority(waitPlay) >= SkillUtils.GetAnimInterruptPriority(curPlay)
end

function SkillUtils.IsSkill(id)
  if not id then
    return false
  end
  if id >= 200000 and id < 300000 or id >= 7000000 and id < 8000000 then
    return true
  else
    return false
  end
end

function SkillUtils.IsBuff(id)
  if id >= 20000000 and id <= 29999999 then
    return true
  else
    return false
  end
end

function SkillUtils.IsBuffBase(id)
  if id >= 2000000 and id < 2999999 then
    return true
  else
    return false
  end
end

function SkillUtils.IsEffect(id)
  if id >= 1000000 and id <= 1999999 then
    return true
  else
    return false
  end
end

function SkillUtils.SpeedUpSkillEndEvent(skillObj)
  local endTime = 0
  if not skillObj then
    return endTime
  end
  local isPrePlay = _G.BattleManager.stateFsm:GetProperty("IsPreplay")
  local resonance_perform_count = _G.BattleManager.battleRuntimeData:GetResonancePerform()
  if isPrePlay and resonance_perform_count <= 0 and BattleUtils.IsSpeedPreplay() then
    local actions = skillObj:GetAllActions()
    local hasEnd = false
    for i = 1, actions:Length() do
      local action = actions:Get(i)
      if action:IsA(UE4.URocoSkillObjLuaCallbackAction) then
        if action.SkillLuaEvent == UE4.ERocoSkillLuaEventType.TriggerBeHit then
          action:SetStartTime(0.06666666666666667)
        elseif action.SkillLuaEvent == UE4.ERocoSkillLuaEventType.PreEnd then
          hasEnd = true
          endTime = action:GetEndTime()
          action:SetStartTime(0.1)
        end
      end
    end
    if not hasEnd then
      endTime = skillObj:GetLength()
      skillObj:BindLuaEvent(0.1, "PreEnd")
    end
  end
  return endTime
end

function SkillUtils.GetSkillHitPoints(skill)
  local logicHitPoints = {}
  local animHitPoints = {}
  local actions = skill:GetAllActions()
  for i = 1, actions:Length() do
    local action = actions:Get(i)
    if action:IsA(UE4.URocoSkillObjLuaCallbackAction) then
      if action.SkillLuaEvent == UE4.ERocoSkillLuaEventType.TriggerBeHit then
        table.insert(logicHitPoints, action:GetStartTime())
      end
    elseif action:IsA(UE4.URocoPetPlayAnimationAction) then
      if action.m_petAnimType == UE4.EBattlePetAnimType.Hurt or action.m_petAnimType == UE4.EBattlePetAnimType.Hitdown or action.m_petAnimType == UE4.EBattlePetAnimType.Float then
        table.insert(animHitPoints, action:GetStartTime())
      end
    elseif action:IsA(UE4.URocoPlayAnimationByName) then
      if action.AnimName == "Hit1" or action.AnimName == "Hit2" or action.AnimName == "Hit3" then
        table.insert(animHitPoints, action:GetStartTime())
      end
    elseif action:IsA(UE4.URocoStepBackAction) and ("Hit1" == action.StepbackAnimName or "Hit2" == action.StepbackAnimName or "Hit3" == action.StepbackAnimName) then
      table.insert(animHitPoints, action:GetStartTime())
    end
  end
  return logicHitPoints, animHitPoints
end

function SkillUtils.BindAnimationHits(skillObj, logic, animation)
  local minTime = math.maxinteger
  if animation and #animation > 0 then
    for _, time in ipairs(animation) do
      skillObj:BindLuaEvent(time, "AnimationHit")
      minTime = math.min(minTime, time)
    end
  elseif logic then
    for _, time in ipairs(logic) do
      skillObj:BindLuaEvent(time, "AnimationHit")
      minTime = math.min(minTime, time)
    end
  else
    skillObj:BindLuaEvent(0, "AnimationHit")
    minTime = 0
  end
  SkillUtils.SetupSkillActions(skillObj, minTime)
end

function SkillUtils.SetupSkillActions(skillObj, time)
  time = time or 0
  local Actions = skillObj:GetAllActions()
  for i = 1, Actions:Length() do
    local action = Actions:Get(i)
    local Executor = action.DefaultExecuteActorInfo
    if Executor.ActorType == UE4.ERocoSkillActorType.DynamicTarget and (action:IsA(UE4.URocoPetPlayAnimationAction) or action:IsA(UE4.URocoCharacterMaterialModifyAction)) then
      Log.DebugFormat("Set %s disable", tostring(action.Object))
      skillObj:OverrideActionEnable(action, false)
    end
  end
end

function SkillUtils.SetEarlyEnd(Skill)
  local Actions = Skill:GetAllActions()
  local EndTime = -1
  for Index, Action in tpairs(Actions) do
    if not Action:IsA(UE4.URocoPlayAnimationByName) then
    elseif Action.DefaultEnableCondition == UE4.ERocoSkillCondition.None then
    elseif Action.DefaultExecuteActorInfo.ActorType ~= UE4.ERocoSkillActorType.DefaultCaster then
    else
      EndTime = Action:GetStartTime()
      break
    end
  end
  if -1 == EndTime then
    return
  end
  Skill:BindLuaEvent(EndTime, "PreEnd")
end

function SkillUtils.GetSkillName(skillID)
  local skillConf = _G.DataConfigManager.GetSkillConf(skillID)
  if skillConf then
    return skillConf.name
  end
  return "Unknown"
end

function SkillUtils.GetSkillEventTime(castMoment, skillPath)
  local skillObj = UE4.USkillRecordLibrary.AnalyzeSkill(skillPath).Object
  if skillObj then
    local map = UE4.UNRCStatics.EventTimes(skillObj)
    local event = SkillUtils.ParseCmToEvent(castMoment)
    local time = map:Find(event)
    return time
  else
    return nil
  end
end

function SkillUtils.ParseCmToEvent(castMoment)
  return BattleConst.CmToSkillEventDict[castMoment]
end

function SkillUtils.SkillObjHasLuaEvent(skillObj, eventType)
  local actions = skillObj:GetAllActions()
  for i = 1, actions:Length() do
    local action = actions:Get(i)
    if action:IsA(UE4.URocoSkillObjLuaCallbackAction) and action.SkillLuaEvent == eventType then
      return true
    end
  end
  return false
end

function SkillUtils.GetBeHitAction(skillObj)
  local result = {}
  local actions = skillObj:GetAllActions()
  for i = 1, actions:Length() do
    local action = actions:Get(i)
    if action.m_Enable and action:IsA(UE4.URocoPlayAnimationByName) and action.DefaultExecuteActorInfo.ActorType == UE4.ERocoSkillActorType.DynamicTarget and table.contains(SkillUtils.hitAnimationName, action.AnimName) then
      table.insert(result, action)
    end
  end
  return result
end

function SkillUtils.SkillObjGetLuaEvent(skillObj, eventType)
  local result = {}
  local actions = skillObj:GetAllActions()
  for i = 1, actions:Length() do
    local action = actions:Get(i)
    if action.m_Enable and action:IsA(UE4.URocoSkillObjLuaCallbackAction) and action.SkillLuaEvent == eventType then
      table.insert(result, action)
    end
  end
  return result
end

function SkillUtils.SkillObjGetLuaEventStartTime(skillObj, eventType)
  local actions = skillObj:GetAllActions()
  for i = 1, actions:Length() do
    local action = actions:Get(i)
    if action.m_Enable and action:IsA(UE4.URocoSkillObjLuaCallbackAction) and action.SkillLuaEvent == eventType then
      return action:GetStartTime()
    end
  end
  return skillObj:GetLength()
end

function SkillUtils.GetSkillResID(skillID)
  local skillConf = SkillUtils.GetSkillConf(skillID)
  if skillConf and skillConf.res_id then
    return skillConf.res_id, true
  end
  return "Unknown", false
end

function SkillUtils.GetBuffResID(buffID, performType)
  performType = performType or 0
  local buffConf = _G.DataConfigManager:GetBuffConf(buffID)
  local buffConfIdx = "res_id_" .. performType
  if 3 == performType then
    return "Unknown", false
  end
  if buffConf and buffConf[buffConfIdx] then
    return buffConf[buffConfIdx], true
  end
  return "Unknown", false
end

function SkillUtils.IsRemoteSkill(SkillObject)
  if SkillObject then
    local actions = SkillObject:GetAllActions()
    for i = 1, actions:Length() do
      local action = actions:Get(i)
      if action.m_Enable and action:IsA(UE4.URocoRootMotionAnimationAction) then
        return false
      end
    end
  end
  return true
end

function SkillUtils.SetRangedMultiAtkTimes(skill, times)
  if not skill then
    return
  end
  if times < 0 then
    times = 1
  end
  Log.Debug("SkillUtils.SetRangedMultiAtkTimes", times, skill:GetName())
  if skill.Blackboard.SetValueAsBool then
    skill.Blackboard:SetValueAsBool("MultiAtk", true)
  else
    Log.Debug("SkillUtils.SetRangedMultiAtkTimes SetValueAsBool\231\169\186\239\188\159\239\188\159\239\188\159 ", table.tostring(skill.Blackboard))
  end
  local actions = skill:GetAllActions()
  for i = 1, actions:Length() do
    local action = actions:Get(i)
    if action:IsA(UE4.URocoTimeGotoAction) then
      Log.Debug("SkillUtils.SetRangedMultiAtkTimes:", action:GetName(), times)
      action:SetBranchJumpTimesBlackBoardType("MultiAtk", times)
    end
  end
end

function SkillUtils.IsMultiAttackType(castMoment)
  return castMoment >= ProtoEnum.Buffbasetrigger_type.OnAttackHit
end

function SkillUtils.ScanEnergyPerform(performNode, targetId)
  if not performNode then
    return
  end
  local performLst = performNode.performPlayer.performLst
  for _, v in pairs(performLst) do
    if v:GetPerformType() == ProtoEnum.BattlePerformType.BPT_ENERGY and v:GetGroupID() == performNode:GetGroupID() then
      local sourceId = v:GetPerformData().source_id
      if sourceId and sourceId == targetId and not v:IsPerformed() and not v:IsPerforming() then
        v.performInfo.cast_moment = ProtoEnum.Buffbasetrigger_type.OnFlyEnergy
      end
    end
  end
end

function SkillUtils.ClearSkillObj(skillComp)
  if skillComp then
    skillComp:StopCurrentSkill()
    skillComp:ClearAllPassiveSkillObjs()
    skillComp:ClearSkillObj()
  end
end

function SkillUtils.GetSkillConf(skill_id, ignoreLog)
  return _G.DataConfigManager:GetSkillConf(SkillUtils.CheckSkillId(skill_id), ignoreLog)
end

function SkillUtils.IsEqualSkill(instSkillId, skillId)
  return SkillUtils.CheckSkillId(instSkillId) == skillId
end

function SkillUtils.CheckSkillId(skill_id)
  if SkillUtils.IsSkill(skill_id) then
    return skill_id
  end
  return SkillUtils.InstSkillIdToCfgId(skill_id)
end

function SkillUtils.InstSkillIdToCfgId(instSkillId)
  return math.floor(instSkillId / 100)
end

function SkillUtils.IsGatherSkill(skillId)
  local skillConf = SkillUtils.GetSkillConf(skillId)
  if skillConf and skillConf.skill_result and #skillConf.skill_result > 0 then
    local buffId = skillConf.skill_result[1].effect_id
    if SkillUtils.IsBuff(buffId) and BuffUtils.IsGatherBuff(buffId) then
      return true
    end
  end
  return false
end

function SkillUtils.IsCollectEnergySkill(skillId)
  local skill_id = SkillUtils.CheckSkillId(skillId)
  if 7000010 == skill_id or 7000030 == skill_id or 7000040 == skill_id or 7000050 == skill_id then
    return true
  end
  return false
end

function SkillUtils.GetGatherFakeSkillId()
  return DataConfigManager:GetGlobalConfigNumByKeyType("charging_skill_id", _G.DataConfigManager.ConfigTableId.BATTLE_GLOBAL_CONFIG, 7100100)
end

function SkillUtils.GetUniqueExtraDamageTypes(extraDamTypeType)
  local Hash = {}
  local res = {}
  if not extraDamTypeType then
    return res
  end
  for i, Type in ipairs(extraDamTypeType) do
    if Type.values then
      for j, value in ipairs(Type.values) do
        if not Hash[value] then
          res[#res + 1] = value
          Hash[value] = true
        end
      end
    end
  end
  return res
end

function SkillUtils.IsSkillInFirstTurnState(skill, pet)
  local card = pet and pet.card
  local petInfo = card and card.petInfo
  local inside_pet_info = petInfo and petInfo.battle_inside_pet_info
  local is_b93_active = inside_pet_info and inside_pet_info.is_b93_active
  if not is_b93_active then
    return false
  end
  if not skill or not skill.skill_id then
    return false
  end
  local skillData = skill.skillData
  local enhance_info = skillData and skillData.enhance_info or {}
  local finalEnhanceInfo = BattleUtils.PreProcessEnhanceInfo(enhance_info, card)
  finalEnhanceInfo = BattleUtils.OverlayEnhanceInfo(finalEnhanceInfo)
  if finalEnhanceInfo then
    for i, enhanceInfo in ipairs(finalEnhanceInfo) do
      if enhanceInfo.tip_id and enhanceInfo.tip_id > 0 then
        local buffBaseId = enhanceInfo.buffbase_id
        local buffBaseConf = _G.DataConfigManager:GetBuffbaseConf(buffBaseId)
        local buffbase_order = buffBaseConf and buffBaseConf.buffbase_order
        if buffbase_order == ProtoEnum.BuffType.BFT_NINETY_THREE then
          return true
        end
      end
    end
  end
  return false
end

function SkillUtils.PreLoadSkillIconRes(skillId)
  skillId = _G.SkillUtils.CheckSkillId(skillId)
  local skillConf = _G.SkillUtils.GetSkillConf(skillId, true)
  local iconPath = skillConf and skillConf.icon
  local resCacheTime = 20
  if iconPath then
    _G.BattleResourceManager:PreloadAssetAsync(nil, iconPath, function()
      Log.Info("SkillUtils.PreLoadSkillIconRes success", skillId)
    end, function()
      Log.Info("SkillUtils.PreLoadSkillIconRes failed", skillId)
    end, resCacheTime, PriorityEnum.Passive_Battle_Panel)
  end
end

function SkillUtils.CreatePetSkillRoundDataFromSkillConf(skillConf)
  if not skillConf then
    return nil
  end
  local skillRoundData = _G.ProtoMessage:newPetSkillRoundData()
  skillRoundData.id = skillConf.id
  skillRoundData.skill_id = skillConf.id
  skillRoundData.type = skillConf.type
  skillRoundData.damage_type = skillConf.skill_dam_type
  skillRoundData.cd_round = skillConf.cd_round
  if skillConf.energy_cost and #skillConf.energy_cost > 0 then
    skillRoundData.cost_energy = skillConf.energy_cost[1]
    skillRoundData.raw_cost_energy = skillConf.energy_cost[1]
  end
  return skillRoundData
end

function SkillUtils.IsSkillIsAspiration(skill, pet)
  local skillData = skill and skill.skillData
  local skillId = skillData and skillData.skill_id
  local card = pet and pet.card
  local owner = card and card.owner
  local roleInfo = owner and owner.roleInfo
  local magicOpInfo = roleInfo and roleInfo.magic_op_info
  local playerSkillId = magicOpInfo and magicOpInfo.player_skill_id
  local SkillConf = playerSkillId and _G.SkillUtils.GetSkillConf(playerSkillId, true)
  local skillResult = SkillConf and SkillConf.skill_result
  local firstSkillResult = skillResult and skillResult[1]
  local effectId = firstSkillResult and firstSkillResult.effect_id
  local effectConf = _G.DataConfigManager:GetEffectConf(effectId, true)
  local effectOrderType = effectConf and effectConf.effect_order
  if effectOrderType ~= Enum.EffectType.ET_ROLE_CHANGE_SKILL then
    return false
  end
  local skillIdList = magicOpInfo and magicOpInfo.skill_id or {}
  for i, skillIdInList in ipairs(skillIdList) do
    if skillIdInList == skillId then
      return true
    end
  end
  return false
end

function SkillUtils.SkillHasCameraAction(skillObj)
  local actions = skillObj:GetAllActions()
  for i = 1, actions:Length() do
    local action = actions:Get(i)
    if SkillUtils.IsACameraAction(action) then
      return true
    end
  end
  return false
end

function SkillUtils.IsACameraAction(skillAction)
  if skillAction then
    local actionClass = skillAction:GetClass()
    if actionClass then
      local actionClassName = actionClass:GetName()
      if string.find(actionClassName, "Camera") then
        return true
      end
    end
  end
  return false
end

function SkillUtils.GetCustomizeAnimName(type, index)
  local conf = _G.NRCModuleManager:DoCmd(_G.SystemSettingModuleCmd.GetRoleAnimationCfgByType, type)
  if conf then
    local animationData = conf.animation_list[index]
    if animationData then
      return animationData.animation
    end
  end
  return nil
end

function SkillUtils.CustomizeTypeDefaultIndex(type)
  if type == Enum.PlayerAnimationCustomizeType.PACT_PVE_WIN_NORMAL then
    return _G.DataConfigManager:GetRoleGlobalConfig("player_pact_pve_win_normal_default").num
  elseif type == Enum.PlayerAnimationCustomizeType.PACT_PVP_LOSE_NORMAL then
    return _G.DataConfigManager:GetRoleGlobalConfig("player_pact_pvp_lose_normal_default").num
  elseif type == Enum.PlayerAnimationCustomizeType.PACT_ALCHEMY_PANEL then
    return _G.DataConfigManager:GetRoleGlobalConfig("player_pact_alchemy_panel_default").num
  end
  Log.Warning("Unknown PlayerAnimationCustomizeType", type)
  return 1
end

function SkillUtils.CustomizeTypeToString(type)
  for name, value in pairs(Enum.PlayerAnimationCustomizeType) do
    if value == type then
      return name
    end
  end
  return ""
end

local PATTERN_BEGIN_SELF_CLOSE = "<span%s+fork_road=\"begin\"%s*/>"
local PATTERN_BEGIN_EMPTY = "<span%s+fork_road=\"begin\"%s*></>"
local PATTERN_END_SELF_CLOSE = "<span%s+fork_road=\"end\"%s*/>"
local PATTERN_END_EMPTY = "<span%s+fork_road=\"end\"%s*></>"
local PATTERN_OR = "<span%s+fork_road=\"or\"%s*>.-</>"

local function FindEarliest(text, searchFrom, ...)
  local bestS, bestE
  for i = 1, select("#", ...) do
    local pattern = select(i, ...)
    local s, e = string.find(text, pattern, searchFrom)
    if s and (not bestS or bestS > s) then
      bestS, bestE = s, e
    end
  end
  return bestS, bestE
end

local function FindBegin(text, searchFrom)
  return FindEarliest(text, searchFrom, PATTERN_BEGIN_SELF_CLOSE, PATTERN_BEGIN_EMPTY)
end

local function FindEnd(text, searchFrom)
  return FindEarliest(text, searchFrom, PATTERN_END_SELF_CLOSE, PATTERN_END_EMPTY)
end

local function FindOr(text, searchFrom)
  return string.find(text, PATTERN_OR, searchFrom)
end

function SkillUtils.PreProcessForkRoadDescription(skillDescription, activeForkRoadFace)
  skillDescription = skillDescription or ""
  local isFaceA = activeForkRoadFace == ProtoEnum.ForkRoadFace.FORK_ROAD_FACE_A
  local isFaceB = activeForkRoadFace == ProtoEnum.ForkRoadFace.FORK_ROAD_FACE_B
  if not isFaceA and not isFaceB then
    return skillDescription
  end
  local result = {}
  local cursor = 1
  local len = #skillDescription
  while cursor <= len do
    local beginS, beginE = FindBegin(skillDescription, cursor)
    if not beginS then
      table.insert(result, string.sub(skillDescription, cursor))
      break
    end
    local endS, endE = FindEnd(skillDescription, beginE + 1)
    if not endS then
      table.insert(result, string.sub(skillDescription, cursor))
      break
    end
    local orS, orE = FindOr(skillDescription, beginE + 1)
    if orS and endS < orS then
      orS, orE = nil, nil
    end
    if cursor < beginS then
      table.insert(result, string.sub(skillDescription, cursor, beginS - 1))
    end
    if isFaceA then
      local aContentEnd = orS and orS - 1 or endS - 1
      if aContentEnd >= beginE + 1 then
        table.insert(result, string.sub(skillDescription, beginE + 1, aContentEnd))
      end
    elseif orE then
      local bContentStart = orE + 1
      local bContentEnd = endS - 1
      if bContentStart <= bContentEnd then
        table.insert(result, string.sub(skillDescription, bContentStart, bContentEnd))
      end
    end
    local nextCursor = endE + 1
    if cursor >= nextCursor then
      break
    end
    cursor = nextCursor
  end
  return table.concat(result)
end

local ShareDescriptionRule = {
  None = 0,
  All = 1,
  OnlyFaceA = 2,
  OnlyFaceB = 3
}

function SkillUtils.GenerateForkRoadDescriptionWithForkRoadData(skillDescriptionBase, forkRoadData, activeForkRoadFace)
  local faceA = forkRoadData and forkRoadData.face_a
  local faceB = forkRoadData and forkRoadData.face_b
  local description = ""
  if activeForkRoadFace == ProtoEnum.ForkRoadFace.FORK_ROAD_FACE_A then
    description = SkillUtils.GenerateForkRoadDescriptionWithForkRoadFaceData(skillDescriptionBase, faceA, activeForkRoadFace)
  elseif activeForkRoadFace == ProtoEnum.ForkRoadFace.FORK_ROAD_FACE_B then
    description = SkillUtils.GenerateForkRoadDescriptionWithForkRoadFaceData(skillDescriptionBase, faceB, activeForkRoadFace)
  end
  return description
end

function SkillUtils.GenerateForkRoadDescriptionWithForkRoadFaceData(skillDescriptionBase, forkRoadFadeData, activeForkRoadFace)
  local forkRoadEnhanceInfoList = forkRoadFadeData and forkRoadFadeData.fork_road_enhance_info or DummyTable
  local enhanceInfoList = {}
  for i, forkRoadEnhanceInfo in ipairs(forkRoadEnhanceInfoList) do
    local enhanceInfo = forkRoadEnhanceInfo and forkRoadEnhanceInfo.enhance_info
    table.insert(enhanceInfoList, enhanceInfo)
  end
  local buffIdList = {}
  for i, enhanceInfo in ipairs(enhanceInfoList) do
    local buffId = enhanceInfo and enhanceInfo.buff_id
    table.insert(buffIdList, buffId)
  end
  return SkillUtils.GenerateForkRoadDescriptionWithBuffIdList(skillDescriptionBase, buffIdList, activeForkRoadFace)
end

function SkillUtils.GenerateForkRoadDescriptionWithBuffIdList(skillDescriptionBase, buffIdList, activeForkRoadFace)
  local shareDescription = skillDescriptionBase
  local descriptionList = {}
  local shareDescriptionFromBuff
  local diffPathsDescriptionConfIdSet = {}
  for i, buffId in ipairs(buffIdList) do
    local buffConfig = _G.DataConfigManager:GetBuffConf(buffId, true)
    local buffBaseId = buffConfig and buffConfig.buff_base_ids and buffConfig.buff_base_ids[1]
    local buffBaseConf = buffConfig and _G.DataConfigManager:GetBuffbaseConf(buffConfig.buff_base_ids[1])
    local buffBaseOrder = buffBaseConf and buffBaseConf.buffbase_order
    local buffbase_param = buffBaseConf and buffBaseConf.buffbase_param
    if buffBaseOrder == Enum.BuffType.BFT_O_FIFTY then
      local param12 = buffbase_param and buffbase_param[12]
      local param12List = param12 and param12.params
      local param12Value = param12List and param12List[1]
      local diffPathsDescriptionConfId = param12Value
      local diffPathsDescriptionConf = _G.DataConfigManager:GetDifPathsDescConf(diffPathsDescriptionConfId, true)
      if diffPathsDescriptionConf then
        local confId = diffPathsDescriptionConf and diffPathsDescriptionConf.id
        if confId and diffPathsDescriptionConfIdSet then
          diffPathsDescriptionConfIdSet[confId] = true
        end
      end
    end
  end
  for confId, _ in pairs(diffPathsDescriptionConfIdSet) do
    local diffPathsDescriptionConf = _G.DataConfigManager:GetDifPathsDescConf(confId, true)
    local currShareDescription = diffPathsDescriptionConf and diffPathsDescriptionConf.shared_desc or ""
    local descriptionA = diffPathsDescriptionConf and diffPathsDescriptionConf.A_desc
    local descriptionB = diffPathsDescriptionConf and diffPathsDescriptionConf.B_desc
    local shareDescriptionRule = diffPathsDescriptionConf and diffPathsDescriptionConf.shared_desc_rule
    local allowReplaceBaseDescription = shareDescriptionRule == ShareDescriptionRule.All or activeForkRoadFace == ProtoEnum.ForkRoadFace.FORK_ROAD_FACE_A and shareDescriptionRule == ShareDescriptionRule.OnlyFaceA or activeForkRoadFace == ProtoEnum.ForkRoadFace.FORK_ROAD_FACE_B and shareDescriptionRule == ShareDescriptionRule.OnlyFaceB
    if allowReplaceBaseDescription then
      shareDescriptionFromBuff = currShareDescription
    end
    if activeForkRoadFace == ProtoEnum.ForkRoadFace.FORK_ROAD_FACE_A then
      table.insert(descriptionList, descriptionA)
    elseif activeForkRoadFace == ProtoEnum.ForkRoadFace.FORK_ROAD_FACE_B then
      table.insert(descriptionList, descriptionB)
    end
  end
  if shareDescriptionFromBuff then
    shareDescription = shareDescriptionFromBuff
  end
  table.insert(descriptionList, 1, shareDescription)
  local finalDescription = table.concat(descriptionList)
  return finalDescription
end

function SkillUtils.GetFusedEnergyCost(skillData)
  if BattleUtils.IsBadgeChallenge() and skillData and skillData.grass_trial_skill_info then
    return skillData.grass_trial_skill_info.fused_energy_cost
  end
  return nil
end

function SkillUtils.GetFusedPower(skillData)
  if BattleUtils.IsBadgeChallenge() and skillData and skillData.grass_trial_skill_info then
    return skillData.grass_trial_skill_info.fused_power
  end
  return nil
end

function SkillUtils.CheckSkillRoundDataFlag(skillData, flagType)
  local flag = skillData and skillData.flag or 0
  local result = flag & flagType > 0
  return result
end

function SkillUtils.IsSkillRoundDataIsChangeOrCleverShift(skillData)
  local Flag = ProtoEnum.PetSkillRoundData.FLAG
  local isBuff132 = SkillUtils.CheckSkillRoundDataFlag(skillData, Flag.FLAG_OBTAINED_BY_BUFF_132)
  local isBuff146 = SkillUtils.CheckSkillRoundDataFlag(skillData, Flag.FLAG_OBTAINED_BY_BUFF_146)
  return isBuff132 or isBuff146
end

return SkillUtils
