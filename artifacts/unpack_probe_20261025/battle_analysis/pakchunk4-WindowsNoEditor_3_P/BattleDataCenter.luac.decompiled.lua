local Class = _G.MakeSimpleClass
local BattlePerformEvent = require("NewRoco.Modules.Core.Battle.BattleCore.BattlePerformEvent")
local ProtoEnum = require("Data.PB.ProtoEnum")
local BattleEnum = require("NewRoco.Modules.Core.Battle.Common.BattleEnum")
local BattleEvent = require("NewRoco.Modules.Core.Battle.Common.BattleEvent")
local BattleUtils = require("NewRoco.Modules.Core.Battle.Common.BattleUtils")
local BattleConst = require("NewRoco.Modules.Core.Battle.Common.BattleConst")
local BuffUtils = require("NewRoco.Modules.Core.Battle.Entity.Components.Buff.BuffUtils")
local BattleDataCenter = Class("BattleDataCenter")

function BattleDataCenter:Ctor()
end

function BattleDataCenter:DoWrite(performInfo)
  if performInfo.sync_data then
    self:WriteSyncData(performInfo.sync_data, performInfo.type)
  end
  if performInfo.type == ProtoEnum.BattlePerformType.BPT_DAMAGE then
    local targetID = self:WriteDamageInfo(performInfo)
    local delaySeconds = 0
    if performInfo.cast_moment >= ProtoEnum.Buffbasetrigger_type.OnAttackHit then
      delaySeconds = BattleConst.Show.PetHpDelayChangeTimeOnAttackHit
    end
    local option = {
      petId = targetID,
      imme = false,
      delaySeconds = delaySeconds
    }
    self:Dispatch(BattlePerformEvent.HitBattlePet, option)
    if performInfo.sync_data and performInfo.sync_data.comm_sync_info then
      self:Dispatch(BattlePerformEvent.WishPowerChange, performInfo)
    end
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_HEAL then
    local targetID, change_value, sourceID
    targetID, sourceID, change_value = self:WriteHealInfo(performInfo.heal_info, performInfo.sync_data)
    local option = {
      petId = targetID,
      change_val = change_value,
      imme = false,
      sourceBuffOrSkillOrEffectId = sourceID
    }
    self:Dispatch(BattlePerformEvent.HealBattlePet, option)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_ENERGY then
    Log.Debug("BattleDataCenter EnergyChange:")
    self:SyncEnergy(performInfo.energy_info.source_id, performInfo.sync_data, performInfo.energy_info.isFly)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_DEATH then
    self:WriteDeathSyncInfo(performInfo.dead_info, performInfo.sync_data)
    if performInfo.sync_data and performInfo.sync_data.comm_sync_info then
      self:Dispatch(BattlePerformEvent.WishPowerChange, performInfo)
    end
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_ROLE_SKILL_CAST then
    self:HandleRoleSkillCast(performInfo)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_REVIVE then
    self:Dispatch(BattlePerformEvent.BattlePetRevive, performInfo.revive_info.target_id)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_BUFF_TRIGGER then
    self:HandleBuffTrigger(performInfo)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_BUFF_CHANGE then
    local battlePet, type, buff, syncData
    battlePet, type, buff, syncData = self:WriteBuffChangeInfo(performInfo.buff_change, performInfo.sync_data)
    if not battlePet then
      return
    end
    if not buff then
      Log.Error("BattleDataCenter buff change no buff ", performInfo.buff_change.target_id, performInfo.buff_change.buff_id)
      return
    end
    self:Dispatch(BattlePerformEvent.BuffChange, battlePet, type, buff, syncData)
    if ProtoEnum.BuffChangeType.BCT_REMOVE ~= type or ProtoEnum.BuffType.BFT_FREEZE == buff:GetBuffBaseOrder() then
    end
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_SP_ENERGY_CHANGE then
    self:WriteSPEnergyChangeInfo(performInfo.sp_energy_change)
    self:Dispatch(BattlePerformEvent.SpEnergyChange, performInfo.sp_energy_change)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_SP_ENERGY_TRIGGER then
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_USE_ITEM then
    if performInfo.sync_data then
      if performInfo.sync_data.role_sync_info then
        self:WriteItemUseInfoByRoleSyncInfo(performInfo.sync_data.role_sync_info)
      end
      self:SyncSkill(performInfo.sync_data)
    end
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_CATCH_PET then
    local catch = performInfo.catch_pet_info
    if catch.success then
      _G.NRCModeManager:DoCmd(_G.BattleUIModuleCmd.SetSelectRecoveryItem, nil)
    end
    if performInfo.sync_data and performInfo.sync_data.role_sync_info then
      self:WriteItemUseInfoByRoleSyncInfo(performInfo.sync_data.role_sync_info)
    end
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_NOTIFY_PERFORM then
    self:HandleNotifyPerform(performInfo)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_EFFECT_TRIGGER then
    local effect_trigger = performInfo.effect_trigger
    local effectConf = _G.DataConfigManager:GetEffectConf(effect_trigger.effect_id)
    if not effectConf then
      return
    end
    local order = effectConf.effect_order
    if order == ProtoEnum.EffectType.ET_CHANGE_SKILL and performInfo.sync_data and performInfo.sync_data.skill_change_sync_info then
      self:WriteSkillChangeInfo(performInfo.sync_data.skill_change_sync_info)
    end
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_BATTLER_HEAL then
    self:WriteIncreaseBlood(performInfo)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_SPECIAL_MOVE then
    self:WriteSpecialMoveInfo(performInfo)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_DATA_UPDATE then
    self:WriteDataUpdate(performInfo.data_update)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_PREPARE_TO_BATTLE then
    self:HandlePrepareToBattle(performInfo)
  elseif performInfo.type == ProtoEnum.BattlePerformType.BPT_SKILL_CAST and ProtoEnum.PET_SKILL_PERFORM_FLAG.PET_SKILL_PERFORM_FLAG_RESONANCE == performInfo.skill_cast.perform_flag then
    self:WriteResonance(performInfo)
  end
end

function BattleDataCenter:WriteIncreaseBlood(performInfo)
  if performInfo and performInfo.battler_heal_info then
    local RoleInfo = performInfo.battler_heal_info
    local player = _G.BattleManager.battlePawnManager:GetPlayerByGuid(RoleInfo.uin)
    if player and RoleInfo.hp_result then
      if RoleInfo.hp_result then
        player.roleInfo.base.hp = RoleInfo.hp_result
      end
      if RoleInfo.black_hp_result then
        player.roleInfo.base.black_hp = RoleInfo.black_hp_result
      end
    end
  end
end

function BattleDataCenter:WriteSpecialMoveInfo(performInfo)
  local specialMoveInfo = performInfo.special_move
  if specialMoveInfo then
    local targetIndex = -1
    local battleRuntimeData = _G.BattleManager.battleRuntimeData
    local specialMoveInfoList = battleRuntimeData and battleRuntimeData.specialMoveInfoList or {}
    for i, moveInfo in ipairs(specialMoveInfoList) do
      if specialMoveInfo and moveInfo.pet_id == specialMoveInfo.pet_id then
        targetIndex = i
        break
      end
    end
    if -1 == targetIndex then
      table.insert(specialMoveInfoList, specialMoveInfo)
    else
      specialMoveInfoList[targetIndex] = specialMoveInfo
    end
  end
end

function BattleDataCenter:HandleNotifyPerform(performInfo)
  local tipInfo = performInfo.notify_perform
  if not tipInfo then
    return
  end
  if tipInfo.uin and tipInfo.uin > 0 and tipInfo.uin ~= BattleManager.battlePawnManager.TeamatePlayer.guid then
    return
  end
  if tipInfo.notify_type == ProtoEnum.BattleNotifyPerformType.BNPT_FIELD_REJECT_AURA then
    local aura_id = tipInfo.data[2]
    local aura_conf = _G.DataConfigManager:GetNpcAuraConf(aura_id)
    local tip = aura_conf.area_reject_tip
    local area_id = tipInfo.data[1]
    local content = BattleUtils.FindAreaDesc(area_id)
    _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, string.format(tip, content))
  elseif tipInfo.notify_type == ProtoEnum.BattleNotifyPerformType.BNPT_WEATHER_REJECT_AURA then
    local aura_id = tipInfo.data[2]
    local aura_conf = _G.DataConfigManager:GetNpcAuraConf(aura_id)
    local tip = aura_conf.weather_reject_tip
    local weatherType = tipInfo.data[1]
    local content = BattleUtils.FindWeatherName(weatherType)
    _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, string.format(tip, content))
  elseif tipInfo.notify_type == ProtoEnum.BattleNotifyPerformType.BNPT_BLOW_ADD_FAILED_LOOSE then
    local tips = _G.DataConfigManager:GetLocalizationConf("force_escape_illegal_tip4").msg
    _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, tips)
  elseif tipInfo.notify_type == ProtoEnum.BattleNotifyPerformType.BNPT_BLOW_ADD_FAILED then
    if not tipInfo.data then
      _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, "\231\178\190\231\129\181\230\151\160\230\179\149\231\166\187\229\156\186")
      Log.Error("BattleDataCenter:HandleNotifyPerform", table.tostring(tipInfo))
      return
    end
    local playerTeamName = ""
    local enemyTeamName = ""
    for i, v in ipairs(tipInfo.data) do
      local battlePet = _G.BattleManager.battlePawnManager:GetPetByGuid(tipInfo.data[i])
      if battlePet then
        local petName = battlePet.card.name
        if battlePet.teamEnm == BattleEnum.Team.ENUM_TEAM then
          local segment = string.IsNilOrEmpty(playerTeamName) and "" or ","
          playerTeamName = segment .. playerTeamName .. petName
        else
          local segment = string.IsNilOrEmpty(enemyTeamName) and "" or ","
          enemyTeamName = segment .. enemyTeamName .. petName
        end
      end
    end
    if not string.IsNilOrEmpty(playerTeamName) then
      local tips = _G.DataConfigManager:GetLocalizationConf("force_escape_illegal_tip2").msg
      _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, string.format(tips, playerTeamName))
    end
    if not string.IsNilOrEmpty(enemyTeamName) then
      local tips = _G.DataConfigManager:GetLocalizationConf("force_escape_illegal_tip").msg
      _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, string.format(tips, enemyTeamName))
    end
  elseif tipInfo.notify_type == ProtoEnum.BattleNotifyPerformType.BNPT_NIGHTMARE_SHIELD_BREAK then
    local curBattleId = BattleManager.battleRuntimeData:GetBattleConfID()
    local banId = _G.DataConfigManager:GetGlobalConfigNumByKeyType("S4_nightmare_season_battle", _G.DataConfigManager.ConfigTableId.BATTLE_GLOBAL_CONFIG, -1)
    if curBattleId ~= banId then
      local d = _G.DelayManager:DelaySeconds(1.5, function()
        _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LuaText.Nightmare_Elite_recovery, nil, nil, 3)
      end)
    end
  elseif tipInfo.notify_type == ProtoEnum.BattleNotifyPerformType.BNPT_COMMON then
    if tipInfo.tips_id then
      local LocalizationConf = _G.DataConfigManager:GetLocalizationConf(tipInfo.tips_id, true)
      if LocalizationConf then
        if tipInfo.params and #tipInfo.params > 0 then
          _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, string.format(LocalizationConf.msg, table.unpack(tipInfo.params)), nil, nil, 3)
        else
          _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LocalizationConf.msg, nil, nil, 3)
        end
      else
        Log.Error("zgx no key of LocalizationConf", tipInfo.tips_id)
      end
    end
  elseif tipInfo.notify_type == ProtoEnum.BattleNotifyPerformType.BNPT_BUFF_128 then
    local pet_close_buff_text_128_1HP_config = _G.DataConfigManager:GetLocalizationConf("pet_close_buff_text_128_1HP")
    local tips = pet_close_buff_text_128_1HP_config and pet_close_buff_text_128_1HP_config.msg or ""
    local battlePet = _G.BattleManager.battlePawnManager:GetPetByGuid(tipInfo.data[1])
    local name = ""
    if battlePet then
      name = battlePet.card.name
    end
    _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, string.format(tips, name))
  end
end

function BattleDataCenter:HandleBuffTrigger(performInfo)
  local buff_trigger = performInfo.buff_trigger
  Log.Dump(buff_trigger, 4, "show me buffbase_ids:")
  if not buff_trigger.buffbase_ids then
    Log.Error("buff_trigger no  buffbase_ids, buffbase_ids is nil!!!")
    return
  end
  local buffBaseConf = _G.DataConfigManager:GetBuffbaseConf(buff_trigger.buffbase_ids[1])
  if buffBaseConf then
    local order = buffBaseConf.buffbase_order
    local needWritePopupInfo = true
    if ProtoEnum.BuffType.BFT_OBTAIN_TYPE == order then
      Log.Debug("BattleBuffPlayer HandleBuffCommand: obtain type")
      if performInfo.sync_data then
        local targetID, attrType, attrChange, attrResult = self:WriteObtainTypeInfo(performInfo.buff_trigger, performInfo.sync_data)
        self:Dispatch(BattlePerformEvent.ObtainType, targetID, attrType, attrChange, attrResult)
      end
    elseif ProtoEnum.BuffType.BFT_SPIKES == order then
      local tipId = tostring(buffBaseConf.buffbase_param[3].params[1])
      local Localization = _G.DataConfigManager:GetLocalizationConf(tipId, true)
      if Localization and Localization.msg then
        local showTip = Localization.msg
        local pet = _G.BattleManager.battlePawnManager:GetPetByGuid(buff_trigger.target_id)
        if pet then
          local txt = string.format(showTip, pet.card.name)
          _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, txt)
        else
          Log.Warning("zgx can't find pet", buff_trigger.target_id)
        end
      else
        Log.Warning("zgx LocalizationConf\231\188\186\229\176\145\233\133\141\231\189\174", tipId or "nil", buffBaseConf.id)
      end
    elseif ProtoEnum.BuffType.BFT_CHANGE_CATCH_VALUE == order then
      local targetID, result_value = self:WriteChangeCatchThresholdInfo(performInfo.buff_trigger, performInfo.sync_data)
      self:Dispatch(BattlePerformEvent.ChangeCatchThreshold, targetID, result_value)
    elseif ProtoEnum.BuffType.BFT_FREEZE == order then
      local guid = buff_trigger.target_id
      self:Dispatch(BattlePerformEvent.FrozenChange, guid)
    elseif ProtoEnum.BuffType.BFT_O_TWEENTYEIGHT == order and 1 == performInfo.buff_trigger.perform_type then
      needWritePopupInfo = false
    end
    if needWritePopupInfo then
      self:WriteBuffTriggerPopupInfo(performInfo.buff_trigger)
    end
  end
end

function BattleDataCenter:HandleRoleSkillCast(performInfo)
  local player = BattleManager.battlePawnManager:GetPlayerByGuid(performInfo.role_skill_cast.caster_uin)
  if not player then
    return
  end
  if not performInfo.sync_data or not performInfo.sync_data.item_sync_info then
    return
  end
  for i, v in ipairs(performInfo.sync_data.item_sync_info) do
    player:RefreshMagicItem(v)
  end
end

function BattleDataCenter:HandlePrepareToBattle(performInfo)
  local battleRuntimeData = _G.BattleManager.battleRuntimeData
  local battlePawnManager = _G.BattleManager.battlePawnManager
  local vBattleField = _G.BattleManager.vBattleField
  local prepare_to_battle = performInfo and performInfo.prepare_to_battle
  local petIdList = prepare_to_battle and prepare_to_battle.pet_id or {}
  local bossPetId
  for i, petId in ipairs(petIdList) do
    local battleCard = battlePawnManager and battlePawnManager:GetCardByGuid(petId)
    local inPrepare = battleCard and battleCard:IsPetInPrepareZone()
    local petInfo = battleCard and battleCard.petInfo
    local insideInfo = petInfo and petInfo.battle_inside_pet_info
    local trialInfo = insideInfo and insideInfo.trial_pet_info
    local isBoss = trialInfo and trialInfo.is_boss
    if isBoss and not inPrepare then
      bossPetId = petId
    end
  end
  if bossPetId then
    local prevPlayerPetNumber = battleRuntimeData.playerPetNumber
    local nextEnemyPetNumber = 1
    if battleRuntimeData then
      battleRuntimeData:SetPetNumber(prevPlayerPetNumber, nextEnemyPetNumber)
      battleRuntimeData:RefreshSubBattleType()
      if vBattleField then
        vBattleField:RefreshPosModeWithPlayerAndPetNumber()
      end
    end
  end
end

function BattleDataCenter:SyncEnergy(sourceId, syncData, isFly)
  if syncData and syncData.pet_sync_info then
    for _, v in pairs(syncData.pet_sync_info) do
      local petId, change_value = self:WriteEnergyInfo(v)
      if change_value > 0 then
        self:Dispatch(BattlePerformEvent.GainEnergy, petId, change_value, sourceId, isFly)
      else
        self:Dispatch(BattlePerformEvent.CostEnergy, petId, change_value, sourceId)
      end
      if BattleUtils.IsB1FinalBattleP2() or BattleUtils.IsB1FinalBattleP3() then
        _G.BattleEventCenter:Dispatch(BattleEvent.B1BattleRefreshSkillItem)
      end
    end
  end
end

function BattleDataCenter:SyncSkill(syncData)
  if syncData.skill_sync_info then
    for i, v in pairs(syncData.skill_sync_info) do
      local battleCard = self:GetBattleCard(v.pet_id)
      local skillData = battleCard:GetDisplaySkills()
      for _, skill in ipairs(skillData) do
        if skill.id == v.skill_id then
          if v.cost_energy_result then
            skill.cost_energy = v.cost_energy_result
          end
          if v.cast_cnt_result then
            skill.cast_cnt = v.cast_cnt_result
          end
          if v.damage_param_result and skill.damage_params then
            for _, damage in ipairs(skill.damage_params) do
              if damage.pet_id == v.damage_param_pet_id then
                damage.damage_param = v.damage_param_result
              end
            end
          end
          self:Dispatch(BattlePerformEvent.SkillSync, v.skill_id)
        end
      end
    end
  end
end

function BattleDataCenter:PlayDead(battlePet)
  Log.Debug("BattleDataCenter playdie2")
end

function BattleDataCenter:Dispatch(eventName, ...)
  Log.Debug("BattleDataCenter Dispatch:", eventName, ...)
  BattleEventCenter:Dispatch(eventName, ...)
end

function BattleDataCenter:WriteDamageInfo(performInfo)
  local damage_info = performInfo.damage_info
  local syncData = performInfo.sync_data
  local battleCard = self:GetBattleCard(damage_info.target_id)
  local battlePet = self:GetBattlePet(damage_info.target_id)
  local dmgValue = 0
  local damage_result = 0
  local hp_change = 0
  local hp_result = 0
  local shield_change
  local shield_result = 0
  for _, petSyncInfo in ipairs(syncData.pet_sync_info) do
    if petSyncInfo.pet_id == damage_info.target_id then
      if petSyncInfo.damage_result then
        damage_result = petSyncInfo.damage_result
      end
      if petSyncInfo.hp_change then
        hp_change = petSyncInfo.hp_change
      end
      if petSyncInfo.hp_result then
        hp_result = petSyncInfo.hp_result
      end
      if petSyncInfo.attr_change and (petSyncInfo.attr_type == _G.ProtoEnum.AttributeType.AT_NIGHTMARE_SHIELD or petSyncInfo.attr_type == _G.ProtoEnum.AttributeType.AI_BOX_SHIELD) then
        shield_change = petSyncInfo.attr_change
        shield_result = petSyncInfo.attr_result
      end
    end
  end
  if damage_info.multiAttackNumber and damage_info.multiAttackNumber > 1 then
    dmgValue = damage_result
    damage_info.curDamageNumber = damage_info.curDamageNumber + 1
  else
    local perDamage = damage_result / damage_info.totalDamageNumber
    local lastDamage = math.ceil(damage_info.curDamageNumber * perDamage)
    damage_info.curDamageNumber = damage_info.curDamageNumber + 1
    local nowDamage = math.ceil(damage_info.curDamageNumber * perDamage)
    dmgValue = nowDamage - lastDamage
    if battleCard then
      if damage_info.curDamageNumber < damage_info.totalDamageNumber then
        if nil ~= shield_change and 0 == hp_change then
          local cur_shield_result = math.max(battleCard.shield - dmgValue, 0)
          shield_change = cur_shield_result - battleCard.shield
        else
          local cur_hp_result = math.max(battleCard.hp - dmgValue, 0)
          hp_change = cur_hp_result - battleCard.hp
        end
      elseif damage_info.curDamageNumber == damage_info.totalDamageNumber and damage_info.totalDamageNumber > 1 then
        if nil ~= shield_change and 0 == hp_change then
          shield_change = shield_result - battleCard.shield
        else
          hp_change = hp_result - battleCard.hp
        end
      end
    end
  end
  if battlePet then
    if nil ~= shield_change then
      battlePet:TookShieldDamage(dmgValue, shield_change, damage_info)
      if battlePet.health.shield <= 0 then
        battlePet:TookDamage(dmgValue, hp_change, damage_info, false)
      end
    else
      battlePet:TookDamage(dmgValue, hp_change, damage_info)
    end
  elseif battleCard then
    if nil ~= shield_change then
      battleCard:ShieldChange(shield_change)
      if battlePet.health.shield <= 0 then
        battleCard:HpChange(hp_change)
      end
    else
      battleCard:HpChange(hp_change)
    end
  end
  return damage_info.target_id, dmgValue
end

function BattleDataCenter:WriteDeathSyncInfo(dead_info, syncData)
  if not syncData then
    return
  end
  Log.Debug("BattleDataCenter WriteDeathSyncInfo:")
  local battleCard = self:GetBattleCard(dead_info.target_id)
  if battleCard then
    local player = battleCard.owner
    if player and syncData.role_sync_info then
      for _, v in ipairs(syncData.role_sync_info) do
        if v.role_uin == player.guid then
          player.roleInfo.base.hp = v.hp_result
        end
      end
    end
  end
end

function BattleDataCenter:WriteHealInfo(heal_info, syncData)
  if not syncData.pet_sync_info then
    return
  end
  local battlePet = self:GetBattlePet(heal_info.target_id)
  local healValue = syncData.pet_sync_info[1].hp_change
  if battlePet then
    battlePet:GotHealing(healValue)
  else
    local petId = heal_info.target_id
    local petCard = _G.BattleManager.battlePawnManager:GetCardByGuid(petId)
    if petCard then
      petCard:HpChange(healValue)
    else
      Log.Error("WriteHealInfo Card is nil;")
    end
  end
  self:SyncSkill(syncData)
  return heal_info.target_id, heal_info.source_id, healValue
end

function BattleDataCenter:WriteEnergyInfo(petSyncInfo)
  Log.Debug("BattleDataCenter WriteEnergyInfo:", petSyncInfo.energy_change, petSyncInfo.energy_result)
  local petId = petSyncInfo.pet_id
  local battlePetCard = _G.BattleManager.battlePawnManager:GetCardByGuid(petId)
  local change_value = petSyncInfo.energy_change or 0
  if 0 ~= change_value and battlePetCard then
    if BattleUtils.IsB1FinalBattleP2() or BattleUtils.IsB1FinalBattleP3() then
      _G.BattleManager.battleRuntimeData:SetB1PhantomPoint(petSyncInfo.energy_result)
    else
      battlePetCard:SetEnergy(petSyncInfo.energy_result)
    end
  end
  return petId, change_value
end

function BattleDataCenter:WriteObtainTypeInfo(buff_trigger, syncData)
  if not syncData then
    Log.Error("BattleDataCenter WriteObtainTypeInfo syncData is nil[#error:E001]")
    return
  end
  local attrType = syncData.pet_sync_info[1].attr_type
  local attrChange = syncData.pet_sync_info[1].attr_change
  local attrResult = syncData.pet_sync_info[1].attr_result
  return buff_trigger.target_id, attrType, attrChange, attrResult
end

function BattleDataCenter:WriteChangeCatchThresholdInfo(buff_trigger, syncData)
  local result_value = syncData.pet_sync_info[1].catch_threshold_result
  return buff_trigger.target_id, result_value
end

function BattleDataCenter:WriteShowLettersInfo(show_letters, syncData)
end

function BattleDataCenter:WriteSPEnergyChangeInfo(sp_energy_change)
  return BattleManager.battleRuntimeData:ModifySpEnergyList(sp_energy_change)
end

function BattleDataCenter:WriteSPEnergyTriggerInfo(sp_energy_trigger, sync_data)
end

function BattleDataCenter:WriteBuffChangeInfo(buff_change, sync_data)
  local battlePet = self:GetBattlePet(buff_change.target_id)
  if not battlePet then
    local battleCard = self:GetBattleCard(buff_change.target_id)
    if battleCard then
      battleCard:ChangeBuffData(buff_change, sync_data)
    else
      Log.Debug("zgx BuffChange no pet!!", buff_change.target_id or "nil")
    end
    return nil, nil, nil, nil
  end
  if buff_change.type == ProtoEnum.BuffChangeType.BCT_ADD and battlePet.buffComponent:GetBuff(buff_change.buff_id) then
    Log.Error("zgx \230\156\172\229\186\148\232\175\165\228\191\174\230\148\185\231\154\132buff  \230\156\141\229\138\161\229\153\168\229\141\180\228\184\139\229\143\145\228\186\134\230\150\176\229\162\158", buff_change.buff_id)
    buff_change.type = ProtoEnum.BuffChangeType.BCT_CHANGE
  end
  local buff, syncData = battlePet.buffComponent:ChangeBuffData(buff_change, sync_data)
  battlePet.card:ChangeBuffData(buff_change, sync_data)
  if buff_change.type ~= ProtoEnum.BuffChangeType.BCT_REMOVE and sync_data.pet_sync_info then
    for i = 1, #sync_data.pet_sync_info do
      local data = sync_data.pet_sync_info[i]
      local tmpPet = self:GetBattlePet(data.pet_id)
      if battlePet == tmpPet and buff_change.buff_id == data.buff_id and data.buff_stack_change then
        local isAttach = false
        if data.buff_stack_change > 0 then
          isAttach = true
        end
        battlePet:PopupBuffByAttachOrTrigger(buff_change.buff_id, isAttach)
      end
    end
  end
  return battlePet, buff_change.type, buff, syncData
end

function BattleDataCenter:WriteBuffTriggerPopupInfo(buff_trigger)
  local battlePet = self:GetBattlePet(buff_trigger.target_id)
  if not battlePet then
    return nil, nil, nil, nil
  end
  battlePet:PopupBuffByAttachOrTrigger(buff_trigger.buff_id, false)
end

function BattleDataCenter:WriteSyncData(syncData, type)
  Log.Dump(syncData, 6, "BattleDataCenter WriteSyncData syncData:")
  self:WriteRoleSyncInfo(syncData.role_sync_info)
  self:WritePetSyncInfo(syncData.pet_sync_info, type)
  self:WriteSkillSyncInfo(syncData.skill_sync_info)
  self:WriteSkillChangeInfo(syncData.skill_change_sync_info)
  self:WriteCommSyncInfo(syncData.comm_sync_info)
  self:WritePetInfo(syncData.pet_info)
end

function BattleDataCenter:WriteDataUpdate(data_update)
  if not data_update then
    Log.Error("BattleDataCenter:WriteDataUpdate data_update is nil")
    return
  end
  if data_update.battler then
    local role_uin = data_update.battler.base.role_uin
    local player = _G.BattleManager.battlePawnManager:GetPlayerByGuid(role_uin)
    if player then
      player:ReplaceByServer(data_update.battler)
    end
  end
  if data_update.pet then
    local petInfo = data_update and data_update.pet
    local updateSucceed = BattleDataCenter.WriteDataUpdate_Pet(petInfo)
    if not updateSucceed then
      local uin = data_update and data_update.uin
      local battlePlayer = _G.BattleManager.battlePawnManager:GetPlayerByGuid(uin)
      local deck = battlePlayer and battlePlayer.deck
      if deck then
        local petInfoList = {petInfo}
        deck:IncrementalRefreshByServer(petInfoList)
      end
    end
  end
  if data_update.pet_skill and data_update.pet_skill.skills then
    local battlePetCard = _G.BattleManager.battlePawnManager:GetCardByGuid(data_update.pet_skill.pet_id)
    local battlePet = battlePetCard and battlePetCard.BattlePet or nil
    if battlePet then
      battlePet:RefreshSkillByServer(data_update.pet_skill.skills)
    elseif battlePetCard then
      battlePetCard:RefreshSkillByServer(data_update.pet_skill.skills)
    end
  end
  if data_update.item then
    local role_uin = data_update.uin
    local player = _G.BattleManager.battlePawnManager:GetPlayerByGuid(role_uin)
    if player then
      player:RefreshItemByServer(data_update.item)
    end
  end
  if data_update.role_magic then
    local role_uin = data_update.uin
    local player = _G.BattleManager.battlePawnManager:GetPlayerByGuid(role_uin)
    if player then
      player:UpdateMagicInfo(data_update.role_magic)
    end
  end
  if data_update.role_simple then
    local role_uin = data_update.uin
    local player = _G.BattleManager.battlePawnManager:GetPlayerByGuid(role_uin)
    if player then
      player:SetPetNum(data_update.role_simple.pet_num)
      player:SetDeadPetNum(data_update.role_simple.dead_pet_num)
      player:SetRandomPetCount(data_update.role_simple.random_pet_num)
      player:SetDeadRandomPetCount(data_update.role_simple.dead_random_pet_num)
      player:SetBuff145PetCount(data_update.role_simple.buff145_pet_num)
      player:SetDeadBuff145PetCount(data_update.role_simple.dead_buff145_pet_num)
      player:SetStateBit(data_update.role_simple.state_bit)
      player:SetFreeCatch(data_update.role_simple.free_catch)
      BattleEventCenter:Dispatch(BattleEvent.UI_UPDATE_PETNUM, player)
    end
  end
  if data_update.other then
    local player = _G.BattleManager.battlePawnManager:GetPlayerByGuid(data_update.other.role_uin)
    if player then
      _G.BattleManager.battleInfoManager:HandleBattleOtherRoleInfo(data_update.other, player.teamEnm)
    end
  end
end

function BattleDataCenter.WriteDataUpdate_Pet(pet)
  local battlePetCard = _G.BattleManager.battlePawnManager:GetCardByGuid(pet.battle_inside_pet_info.pet_id)
  local battlePet = battlePetCard and battlePetCard.BattlePet or nil
  if battlePet then
    battlePet:ReplaceByServer(pet)
    battlePet:RefreshByServer()
    return true
  elseif battlePetCard then
    battlePetCard:ReplaceByServer(pet)
    battlePetCard:RefreshByServer()
    return true
  end
  return false
end

function BattleDataCenter:WriteRoleSyncInfo(role_sync_info)
  if role_sync_info then
    for i = 1, #role_sync_info do
      local data = role_sync_info[i]
      local player = _G.BattleManager.battlePawnManager:GetPlayerByGuid(data.role_uin)
      if player then
        if data.role_energy_result then
          player.roleInfo.base.role_energy = data.role_energy_result
        end
        if data.hp_result then
          player.roleInfo.base.hp = data.hp_result
        end
        if data.pvp_score_result then
          player.roleInfo.base.pvp_score = data.pvp_score_result
        end
        if data.black_hp_result then
          player.roleInfo.base.black_hp = data.black_hp_result
        end
        if data.legend_skill_cast_num then
          player.roleInfo.base.legend_skill_cast_num = data.legend_skill_cast_num
        end
      end
    end
  end
end

function BattleDataCenter:WritePetSyncInfo(pet_sync_info, type)
  if pet_sync_info then
    local changeAttrPets = {}
    local changedKillAtHpPetGuidList = {}
    for i = 1, #pet_sync_info do
      local data = pet_sync_info[i]
      if data.pet_id then
        local battleCard = self:GetBattleCard(data.pet_id)
        if battleCard then
          if data.pos then
            battleCard.pos = data.pos
          end
          if data.state_bit_results and data.state_bit_change_pos then
            battleCard.petInfo.battle_inside_pet_info.state_bits = data.state_bit_results
            battleCard:RefreshStateBit(battleCard.petInfo.battle_inside_pet_info)
          end
          if data.energy_result then
            battleCard:SetEnergy(data.energy_result)
          end
          local maxEnergy = data and data.max_energy
          if maxEnergy and battleCard then
            battleCard:SetMaxEnergy(maxEnergy)
          end
          if data.cheers_tag then
            battleCard.petInfo.battle_inside_pet_info.cheers_tag = data.cheers_tag
          end
          if data.revive_round then
            battleCard.petInfo.battle_inside_pet_info.revive_round = data.revive_round
          end
          if data.revive_rounds then
            battleCard.petInfo.battle_inside_pet_info.revive_rounds = data.revive_rounds
          end
          if data.charging_skill_id then
            battleCard.petInfo.battle_inside_pet_info.charging_skill_id = data.charging_skill_id
          end
          if data.hp_change and data.hp_result then
            battleCard:RefreshAttrItemByServer(ProtoEnum.AttributeType.AT_HPCUR, data.hp_result)
          end
          if data.attr_change and data.attr_type then
            battleCard.petInfo.battle_inside_pet_info.battle_attr[data.attr_type + 1] = data.attr_result
            battleCard:RefreshAttr(battleCard.petInfo.battle_inside_pet_info)
            if battleCard.BattlePet and battleCard.BattlePet.health then
              if type == ProtoEnum.BattlePerformType.BPT_DAMAGE or type == ProtoEnum.BattlePerformType.BPT_HEAL then
                battleCard.BattlePet.health:InitAttr(battleCard)
              else
                battleCard.BattlePet.health:UpdateByCard(battleCard)
              end
            end
            changeAttrPets[battleCard.guid] = true
          end
          if data.instant_kill_result then
            local petInfo = battleCard and battleCard.petInfo
            local battle_inside_pet_info = petInfo and petInfo.battle_inside_pet_info
            if battle_inside_pet_info and not battle_inside_pet_info.kill_info then
              battle_inside_pet_info.kill_info = {}
            end
            local kill_info = battle_inside_pet_info and battle_inside_pet_info.kill_info
            if kill_info then
              kill_info.kill_at_hp = data.instant_kill_result
              changedKillAtHpPetGuidList[battleCard.guid] = true
            end
          end
          if data.triggered_buffs then
            local petInfo = battleCard and battleCard.petInfo
            local battle_inside_pet_info = petInfo and petInfo.battle_inside_pet_info
            if battle_inside_pet_info then
              battle_inside_pet_info.triggered_buffs = data.triggered_buffs
            end
          end
          if data.mutation_type then
            local petInfo = battleCard and battleCard.petInfo
            local battle_common_pet_info = petInfo and petInfo.battle_common_pet_info
            if battle_common_pet_info then
              battle_common_pet_info.mutation_type = data.mutation_type
            end
          end
        end
      end
    end
    for k, _ in pairs(changeAttrPets) do
      local option = {
        petId = k,
        change_val = 0,
        imme = false
      }
      self:Dispatch(BattlePerformEvent.PetHpChange, option)
    end
    for guid, _ in pairs(changedKillAtHpPetGuidList) do
      self:Dispatch(BattlePerformEvent.FrozenChange, guid)
    end
  end
end

function BattleDataCenter:WriteSkillSyncInfo(skill_sync_info)
  if skill_sync_info then
    for _, info in pairs(skill_sync_info) do
      local petId = info.pet_id
      local battleCard = _G.BattleManager.battlePawnManager:GetCardByGuid(petId)
      if battleCard then
        local skillRoundDatas = battleCard.skillRoundData or {}
        for _, data in ipairs(skillRoundDatas) do
          if data.id == info.skill_id then
            if info.damage_param_pet_id and info.damage_param_result and data.damage_params then
              local isWrited = false
              if not data.damage_params then
                data.damage_params = {}
              end
              for _, damage in ipairs(data.damage_params) do
                if damage.pet_id == info.damage_param_pet_id then
                  damage.damage_param = info.damage_param_result
                  isWrited = true
                end
              end
              if not isWrited then
                local damageParam = _G.ProtoMessage:newDamageParam()
                damageParam.pet_id = info.damage_param_pet_id
                damageParam.damage_param = info.damage_param_result
              end
            end
            if info.cast_cnt_result then
              data.cast_cnt = info.cast_cnt_result
            end
            if info.cost_energy_result then
              data.cost_energy = info.cost_energy_result
            end
            if info.display_hp_result ~= nil then
              data.display_hp = info.display_hp_result
            end
            if info.sp_energy_skill then
              data.sp_energy_skill = info.sp_energy_skill
            end
            if info.hp_per_energy then
              data.hp_per_energy = info.hp_per_energy
            end
            if info.cost_hp_result then
              data.cost_hp = info.cost_hp_result
            end
            if info.state then
              data.state = info.state
            end
            if info.damage_type then
              data.damage_type = info.damage_type
            end
          end
        end
        local skillComponent = battleCard.BattlePet and battleCard.BattlePet.skillComponent
        if skillComponent and UE.UObject.IsValid(skillComponent) then
          skillComponent:UpdateByCard(battleCard)
        end
      end
    end
  end
end

function BattleDataCenter:WriteSkillChangeInfo(skill_change_sync_info)
  if skill_change_sync_info then
    for _, info in pairs(skill_change_sync_info) do
      local petId = info.pet_id
      local battleCard = _G.BattleManager.battlePawnManager:GetCardByGuid(petId)
      if battleCard and battleCard.skillRoundData then
        for key, data in ipairs(battleCard.skillRoundData) do
          if data.id == info.skill_id then
            battleCard.skillRoundData[key] = info.skill_data
            local skillComponent = battleCard.BattlePet and battleCard.BattlePet.skillComponent
            if skillComponent and UE.UObject.IsValid(skillComponent) then
              skillComponent:UpdateByCard(battleCard)
            end
            break
          end
        end
      end
    end
  end
end

function BattleDataCenter:WriteCommSyncInfo(comm_sync_info)
  if comm_sync_info then
    local battleRuntimeData = _G.BattleManager.battleRuntimeData
    for i = 1, #comm_sync_info do
      local data = comm_sync_info[i]
      local initInfo = BattleUtils.GetBattleInitInfo()
      if initInfo.final_battle and data.final_battle_energy_result then
        initInfo.final_battle.final_battle_energy = data.final_battle_energy_result
      end
      if data.b1_phantom_point_result then
        battleRuntimeData:SetB1PhantomPoint(data.b1_phantom_point_result)
      end
    end
  end
end

function BattleDataCenter:WritePetInfo(pet_info)
  if pet_info then
    for i = 1, #pet_info do
      local data = pet_info[i]
      local battleCard = self:GetBattleCard(data.battle_inside_pet_info.pet_id)
      if battleCard then
        if battleCard.BattlePet then
          battleCard.BattlePet:OverwriteByServer(data)
          battleCard.BattlePet:RefreshByServer()
        else
          battleCard:OverwriteByServer(data)
          battleCard:RefreshByServer()
        end
      end
    end
  end
end

function BattleDataCenter:WriteItemSyncInfo(item_sync_info)
end

function BattleDataCenter:WriteItemUseInfoByRoleSyncInfo(role_sync_info)
  if role_sync_info then
    for _, v in ipairs(role_sync_info) do
      local player = _G.BattleManager.battlePawnManager:GetPlayerByGuid(v.role_uin)
      if player then
        local itemData = player.itemInfo or {}
        for _, item in ipairs(itemData) do
          if item.item_id == v.item_id then
            item.num = v.item_num
            item.remain_use_cnt = v.remain_use_cnt
            item.allow_use_cnt = v.allow_use_cnt
            item.battle_use_time_max = v.battle_use_time_max
            item.battle_use_time_remain = v.battle_use_time_remain
            item.allow_use_cnt_inbattle = v.allow_use_cnt_inbattle
          end
        end
      end
    end
  end
end

function BattleDataCenter:WriteResonance(performInfo)
  local card = self:GetBattleCard(performInfo.skill_cast.caster_id)
  if card then
    card.petInfo.battle_inside_pet_info.feature_resonance = card.petInfo.battle_inside_pet_info.feature_resonance or {}
    card.petInfo.battle_inside_pet_info.feature_resonance.skill_id = performInfo.skill_cast.skill_id
  end
end

function BattleDataCenter:GetBattlePet(petID)
  return BattleManager.battlePawnManager:GetPetByGuid(petID)
end

function BattleDataCenter:GetBattleCard(petID)
  return BattleManager.battlePawnManager:GetCardByGuid(petID)
end

function BattleDataCenter:HandleBuff()
end

function BattleDataCenter:TrySetValue(from, to)
end

return BattleDataCenter
