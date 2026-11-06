local BuffUtils = {}
local Enum = require("Data.Config.Enum")
local BattleEnum = require("NewRoco.Modules.Core.Battle.Common.BattleEnum")
local BattleConst = require("NewRoco.Modules.Core.Battle.Common.BattleConst")
local ProtoEnum = require("Data.PB.ProtoEnum")
local BattleEvent = require("NewRoco.Modules.Core.Battle.Common.BattleEvent")
local BagModuleCmd = require("NewRoco.Modules.System.Bag.BagModuleCmd")

function BuffUtils.IsDebuff(buffCfg)
  return buffCfg.type == ProtoEnum.BuffGroupType.BGT_DEBUFF
end

function BuffUtils.GetBuffRemainTime(buff_id, append_round)
  local buff_conf = _G.DataConfigManager:GetBuffConf(buff_id)
  if buff_conf.type == ProtoEnum.BuffGroupType.BGT_AREA then
    return -1
  end
  local group_reduce = buff_conf.buff_group_reduce[1]
  if group_reduce.reduce_type == Enum.BuffReduceType.BRT_ROUND or group_reduce.reduce_type == Enum.BuffReduceType.BRT_LAYER_ROUND then
    if group_reduce.reduce_param[1] == 999 and 0 == group_reduce.reduce_param[2] then
      return -1
    else
      local roundIndex = 1
      if _G.BattleManager.battleRuntimeData.roundIndex then
        roundIndex = _G.BattleManager.battleRuntimeData.roundIndex
      end
      local timer = group_reduce.reduce_param[1] + append_round - roundIndex
      return timer
    end
  end
  return -1
end

function BuffUtils.IsShowBuffOrLetter(card, buffConfig)
  if card and buffConfig and card.petState:GetMimic() then
    if buffConfig.buff_list_priority >= 5 then
      return false
    end
    for _, v in ipairs(buffConfig.buff_groupsigns) do
      if v == ProtoEnum.BuffGroupSign.BGS_SPE then
        return false
      end
    end
  end
  return true
end

function BuffUtils.GetAllBuff132AttrListFromPet(pet)
  local buffComponent = pet and pet.buffComponent
  local allBuff132 = buffComponent and buffComponent:GetAllBuffsByOrderType(ProtoEnum.BuffType.BFT_O_THIRTYTWO) or {}
  local attrMap = {}
  local attrList = {}
  for i, buff in ipairs(allBuff132) do
    local buff_data = buff.buffInfo.buff_data or {}
    for i, attr in ipairs(buff_data) do
      attrMap[attr] = true
    end
  end
  for attr, _ in pairs(attrMap) do
    table.insert(attrList, attr)
  end
  return attrList
end

function BuffUtils.IsGatherBuff(buffId)
  local buff_conf = _G.DataConfigManager:GetBuffConf(buffId)
  if not buff_conf then
    return false
  end
  for i, v in pairs(buff_conf.buff_groupsigns) do
    if v == Enum.BuffGroupSign.BGS_GATHER then
      return true
    end
  end
  return false
end

function BuffUtils.IsGatherBuffEx(hasSendGatherInfo, battlePet)
  if nil ~= hasSendGatherInfo then
    return hasSendGatherInfo
  end
  return battlePet.card.petState:GetGather()
end

function BuffUtils.IsRidOfBuff(buffId)
  return BuffUtils.CheckBuffType(buffId, ProtoEnum.BuffType.BFT_PET_TRANSE)
end

function BuffUtils.IsFreezeBuff(buffId)
  return BuffUtils.CheckBuffType(buffId, ProtoEnum.BuffType.BFT_FREEZE)
end

function BuffUtils.CheckBuffType(buffId, BuffType)
  local buffBaseConf = BuffUtils.FindFirstBuffBaseConfByBuffType(buffId, BuffType)
  return nil ~= buffBaseConf
end

function BuffUtils.FindFirstBuffBaseConfByBuffType(buffId, BuffType)
  local buff_conf = _G.DataConfigManager:GetBuffConf(buffId)
  if not buff_conf then
    return nil
  end
  for i, buffBaseId in pairs(buff_conf.buff_base_ids) do
    local buffBaseConf = _G.DataConfigManager:GetBuffbaseConf(buffBaseId)
    if buffBaseConf and BuffType == buffBaseConf.buffbase_order then
      return buffBaseConf
    end
  end
  return nil
end

function BuffUtils.IsParallelBuff(buffId)
  local ids = DataConfigManager:GetBattleGlobalConfig("parallel_buff_list").numList
  for i, v in ipairs(ids) do
    if buffId == v then
      return true
    end
  end
  return false
end

function BuffUtils.MaxParallelBuffTime()
  local time = DataConfigManager:GetBattleGlobalConfig("parallel_buff_show_time").num or 1000
  return time / 1000
end

function BuffUtils.IsNameInvisibleBuff(buffId)
  local id = DataConfigManager:GetBattleGlobalConfig("a1_finalbattle_name_buff_ID").num
  if id == buffId then
    return true
  else
    return false
  end
end

function BuffUtils.IsPetHasPlayerSkillBuff(battlePet)
  if nil == battlePet then
    return false
  end
  local buffs = battlePet.buffComponent:GetAllBuffsByOrderType(Enum.BuffType.BFT_O_TWEENTYNINE)
  return #buffs > 0
end

function BuffUtils.IsPetHasBuffByType(battlePet, orderType)
  if not battlePet or not battlePet.buffComponent then
    return false
  end
  return battlePet.buffComponent:IsExistBuffsByOrderType(orderType)
end

return BuffUtils
