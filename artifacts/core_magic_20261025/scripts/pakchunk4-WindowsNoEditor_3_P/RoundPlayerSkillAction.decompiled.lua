local BattleEvent = require("NewRoco.Modules.Core.Battle.Common.BattleEvent")
local BattleEnum = require("NewRoco.Modules.Core.Battle.Common.BattleEnum")
local BattleRoundAction = require("NewRoco.Modules.Core.Battle.Fsm.Actions.Round.BattleRoundAction")
local FsmUtils = require("NewRoco.Modules.Core.Fsm.FsmUtils")
local BattleUtils = require("NewRoco.Modules.Core.Battle.Common.BattleUtils")
local Base = BattleRoundAction
local RoundPlayerSkillAction = Base:Extend("RoundPlayerSkillAction")
FsmUtils.MergeMembers(Base, RoundPlayerSkillAction, {})

function RoundPlayerSkillAction:Ctor(name, properties)
  Base.Ctor(self, name, properties)
  self:SetActionType(BattleActionBase.ActionType.ClientPlayerSelectAction)
end

function RoundPlayerSkillAction:OnEnter()
  Base.OnEnter(self)
  _G.BattleEventCenter:Bind(self, BattleEvent.BATTLE_CLICKED_PLAYERSKILL, BattleEvent.BATTLE_CLICKED_CANCELPLAYERSKILL, BattleEvent.BATTLE_CLICKED_PET)
  if self.CurrentEnemyPets and self.CurrentPlayer then
    for _, v in ipairs(self.CurrentEnemyPets) do
      v:SetLookAt(self.CurrentPlayer.model)
    end
  end
  if self.CurrentPlayer then
    self.CurrentPlayer:ShowBag(true)
    self.CurrentPlayer:HoldBag(true)
    local Item = self:GetItem()
    if Item then
      self.CurrentPlayer:TakeItemWithID(Item.item_conf_id or 0)
    end
  end
end

function RoundPlayerSkillAction:TryUseItem(itemData)
  if itemData.allowCnt <= 0 then
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, string.format(LuaText.roundplayerskillaction_1))
    return false
  elseif itemData.num <= 0 then
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, string.format(LuaText.roundplayerskillaction_2))
    return false
  elseif itemData.canCharge and itemData.remainCnt <= 0 then
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, _G.LuaText.alchemy_bottle_times_out)
    return false
  elseif itemData.ItemType == Enum.BagItemType.BI_PLAYERSKILL and itemData.playerMagicRemainCnt <= 0 then
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, LuaText.player_magic_use_time)
    return false
  elseif BattleUtils.IsPve() or BattleUtils.IsPvp() then
    local itemBattleCfg = _G.DataConfigManager:GetBattleItemConf(itemData.conf_id)
    if itemBattleCfg.use_effect_type_in_battle == ProtoEnum.BattleUseEffect.BE_HINTLEVEL then
      local tip = _G.DataConfigManager:GetLocalizationConf("Battle_Skill_Prediction_Ban").msg
      _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, tip)
      return false
    end
  end
  return true
end

function RoundPlayerSkillAction:TryUseItemOnPet(pet)
  if pet.card.petState:GetDrill() then
    local tip = _G.DataConfigManager:GetBattleGlobalConfig("drill_forbid_props").str
    tip = string.format(tip, pet.card.name)
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, tip)
    return false
  elseif pet.card.petState:GetStatic() then
    local tip = _G.DataConfigManager:GetBattleGlobalConfig("static_forbid_props").str
    tip = string.format(tip, pet.card.name)
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, tip)
    return false
  elseif pet.card.petState:GetMimic() then
    local tip = _G.DataConfigManager:GetBattleGlobalConfig("mimic_forbid_props").str
    tip = string.format(tip, pet.card.name)
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, tip)
    return false
  end
  local itemBattleCfg = _G.DataConfigManager:GetBattleItemConf(self.itemData.conf_id)
  if itemBattleCfg.use_effect_type_in_battle == ProtoEnum.BattleUseEffect.BE_HINTLEVEL and (BattleUtils.IsPvw() or BattleUtils.IsLeaderFight()) then
    local info = BattleUtils.GetSkillPredictionByPlayer(pet)
    if info.hint_level == _G.ProtoEnum.SkillHintLevel.LEVEL_F then
      local tip = _G.DataConfigManager:GetLocalizationConf("Battle_Skill_Prediction_Level_Min").msg
      _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, tip)
      return false
    elseif info.hint_level == _G.ProtoEnum.SkillHintLevel.LEVEL_S then
      local tip = _G.DataConfigManager:GetLocalizationConf("Battle_Skill_Prediction_Level_Max").msg
      _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, tip)
      return false
    end
  end
  return true
end

function RoundPlayerSkillAction:OnClickedItem(itemData)
  Log.Debug("RoundPlayerSkillAction:OnClickedItem")
  self.itemData = itemData
  self.SelectMarkerManager:ClearSelection()
  self.SelectMarkerManager:HideTipTime()
  self.SelectMarkerManager:HideClickTipUI()
  self:ResetRestPets()
  if not self:TryUseItem(itemData) then
    self:ResetPetsLight()
    self:SetEnemyPetHighlight(false)
    self:SetTeamPetHighlight(false)
    self:ToggleDarkScene(false)
    return
  end
  local itemBattleCfg = _G.DataConfigManager:GetBattleItemConf(itemData.conf_id)
  Log.Dump(itemBattleCfg)
  if 1 == itemBattleCfg.legally_used_object then
    self.SelectMarkerManager:ShowSelectMarkers(BattleEnum.SelectMarkerType.ENUM_ALLY)
    local restPets = self.CurrentPlayer.team.RestPets
    if self.CurrentTeamPets then
      for i, v in pairs(self.CurrentTeamPets) do
        local player = v
        if restPets[i] then
          player:SetClickable(false)
          player:HideTipTime()
        else
          player:SetHighlight(true, true)
          player:ShowClickTipUI()
          player:SetClickable(true)
          player:ShowTipTime(itemData.allowCnt, BattleEnum.Operation.ENUM_ITEM)
        end
      end
      self:SetEnemyPetHighlight(false)
      self:ToggleDarkScene(true)
    end
  elseif 2 == itemBattleCfg.legally_used_object then
    if itemBattleCfg.use_effect_type_in_battle == ProtoEnum.BattleUseEffect.BE_HINTLEVEL then
      self.SelectMarkerManager:ShowSelectMarkers(BattleEnum.SelectMarkerType.ENUM_ENEMY)
      self:SetEnemyPetHighlight(false)
      if self.CurrentEnemyPets then
        for _, enemy in pairs(self.CurrentEnemyPets) do
          if enemy:CanBePredicted() and enemy.card:IsCanSelect() then
            enemy:ShowTipTime(itemData.allowCnt, BattleEnum.Operation.ENUM_ITEM)
            enemy:SetHighlight(true, true)
            enemy:ShowClickTipUI()
          end
        end
      end
    else
      self.SelectMarkerManager:ShowSelectMarkers(BattleEnum.SelectMarkerType.ENUM_ENEMY)
      if self.CurrentEnemyPets then
        for _, enemy in pairs(self.CurrentEnemyPets) do
          if enemy.card:IsCanSelect() then
            enemy:SetHighlight(true, true)
            enemy:ShowClickTipUI()
            enemy:ShowTipTime(itemData.allowCnt, BattleEnum.Operation.ENUM_ITEM)
          end
        end
      end
    end
    if self.CurrentEnemyPets then
      self:SetTeamPetHighlight(false)
      self:SetRestPetHighlight(false)
      self:ToggleDarkScene(true)
    end
  else
    Log.ErrorFormat("legally object should be team or enemy, %d", itemBattleCfg.legally_used_object)
  end
  self.CurrentPlayer:ShowBag(false)
  self.CurrentPlayer:HoldBag(true)
  self.CurrentPlayer:TakeItemWithID(itemData.conf_id or 0)
end

function RoundPlayerSkillAction:SetRestPetHighlight(highlight)
  if not self.BattleManager.battlePawnManager then
    return
  end
  if not self.BattleManager.battlePawnManager.playerTeam then
    return
  end
  local restPets = self.BattleManager.battlePawnManager.playerTeam.RestPets
  for _, v in pairs(restPets) do
    v:SetHighlight(highlight)
  end
end

function RoundPlayerSkillAction:OnPetClicked(Pet)
  Log.Debug("RoundPlayerSkillAction:OnPetClicked")
  if not self:TryUseItemOnPet(Pet) then
    return
  end
  self:ResetPetsLight()
  self:ToggleDarkScene(false)
  Pet:SetHighlight(false)
  self:ResetRestPets()
  self.SelectMarkerManager:HideClickTipUI()
  self.SelectMarkerManager:ClearSelection()
  if not self:TryUseItem(self.itemData) then
    return
  end
  local BattleRoundFlowReqList = {}
  local BattleRoundFlowReq = {}
  local req = BattleNetManager:BuildBattleCmdPushbackReq()
  req.req_type = _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_USE_ITEM
  BattleRoundFlowReq.req_type = _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_USE_ITEM
  BattleRoundFlowReq.use_item = {}
  BattleRoundFlowReq.use_item.target_pet_id = Pet.card.guid
  BattleRoundFlowReq.use_item.item_id = self.itemData.id
  BattleRoundFlowReq.use_item.player_id = self.CurrentPlayer.guid
  BattleRoundFlowReq.use_item.target_pet_pos = Pet.card.pos
  table.insert(BattleRoundFlowReqList, BattleRoundFlowReq)
  req.req = BattleRoundFlowReqList
  self:SendPushbackReq(req)
end

function RoundPlayerSkillAction:GetItem()
  local Item = {}
  Item.item_conf_id = 10000011
  return Item
end

function RoundPlayerSkillAction:ResetRestPets()
  if not self.BattleManager.battlePawnManager then
    return
  end
  if not self.BattleManager.battlePawnManager.playerTeam then
    return
  end
  local restPets = self.BattleManager.battlePawnManager.playerTeam.RestPets
  for _, v in pairs(restPets) do
    v:SetDark(false)
    v:HideClickTipUI()
    v:SetClickable(false)
    v:HideTipTime()
    v:SetHighlight(false)
    v:HideRestraintUI()
  end
end

function RoundPlayerSkillAction:OnExit()
  _G.BattleEventCenter:UnBind(self)
  self.SelectMarkerManager:ClearSelection()
  self.SelectMarkerManager:HideTipTime()
  self.SelectMarkerManager:HideClickTipUI()
  self:ResetPetsLight()
  self:SetTeamPetHighlight(false)
  self:ResetRestPets()
  Base.OnExit(self)
end

function RoundPlayerSkillAction:OnBattleEvent(eventName, ...)
  if eventName == BattleEvent.BATTLE_CLICKED_PLAYERSKILL then
    self:OnClickedItem(...)
    return true
  elseif eventName == BattleEvent.BATTLE_CLICKED_CANCELPLAYERSKILL then
  elseif eventName == BattleEvent.BATTLE_CLICKED_PET then
    self:OnPetClicked(...)
    return true
  end
end

return RoundPlayerSkillAction
