local BattleUtils = require("NewRoco.Modules.Core.Battle.Common.BattleUtils")
local BattleEvent = require("NewRoco.Modules.Core.Battle.Common.BattleEvent")
local BattleEnum = require("NewRoco.Modules.Core.Battle.Common.BattleEnum")
local BattleRoundAction = require("NewRoco.Modules.Core.Battle.Fsm.Actions.Round.BattleRoundAction")
local FsmUtils = require("NewRoco.Modules.Core.Fsm.FsmUtils")
local BattleUIModuleCmd = require("NewRoco.Modules.System.BattleUI.BattleUIModuleCmd")
local Base = BattleRoundAction
local RoundSwapAction = Base:Extend("RoundSwapAction")
FsmUtils.MergeMembers(Base, RoundSwapAction, {
  {
    name = "CurrentSelectGuid",
    type = "number"
  }
})

function RoundSwapAction:Ctor(name, properties)
  Base.Ctor(self, name, properties)
  self:SetActionType(BattleActionBase.ActionType.ClientPlayerSelectAction)
end

function RoundSwapAction:OnEnter()
  self.CurrentPushbackReq = self.fsm:GetProperty("CurrentPushbackReq")
  self.CurrentSkill = self.fsm:GetProperty("CurrentSkill")
  Base.OnEnter(self)
  _G.BattleEventCenter:Bind(self, BattleEvent.BATTLE_CLICKED_CHANGEPET, BattleEvent.BATTLE_CLICKED_BAG_PET, BattleEvent.BATTLE_USE_PLAYERSKILL_SUCCESS, BattleEvent.BATTLE_CANCEL_USE_PLAYERSKILL, BattleEvent.PET_LOAD_MODE_LOVER)
  if self.CurrentEnemyPets and self.CurrentPlayer then
    for _, v in ipairs(self.CurrentEnemyPets) do
      v:SetLookAt(self.CurrentPlayer.model)
    end
  end
  if self.CurrentPlayer then
    local playerSkillPhase, activedPlayerSkillInfo = self.CurrentPlayer:GetPlayerSkillPhase()
    self.CurrentPlayer:ShowBag(true)
    if playerSkillPhase ~= BattleEnum.PlayerSkillPhase.NoSkill and playerSkillPhase ~= BattleEnum.PlayerSkillPhase.WaitingToPerform and activedPlayerSkillInfo:IsChangePetEffectType() then
      local Item = self:GetPlayerSkillItem()
      if Item then
        self.CurrentPlayer:TakeCompassWithID(Item.item_conf_id or 0)
      end
    elseif self.CurrentPet then
      self.CurrentPlayer:TakeBallWithCard(self.CurrentPet.card, BattleEnum.Operation.ENUM_CHANGE)
    end
  end
  self:ChangeMagicPet()
  local CurrentGuid = self:GetProperty("CurrentSelectGuid", 0)
  if 0 == CurrentGuid then
    return
  else
    self:OnClickBagPetIcon(CurrentGuid)
  end
end

function RoundSwapAction:GetPlayerSkillItem()
  local item = {}
  item.item_conf_id = 104000
  return item
end

function RoundSwapAction:ChangeMagicPet()
  if self.BattleManager.debugEnv and self.BattleManager.debugEnv.GmChangeMagicPet then
    local player = self.BattleManager.battlePawnManager.playerTeam.player
    local cards = player.deck.cards
    for _, v in ipairs(cards) do
      if v.petInfo and v.petInfo.battle_common_pet_info and self.BattleManager.debugEnv.GmChangeMagicPetData and v.petInfo.battle_common_pet_info.gid == self.BattleManager.debugEnv.GmChangeMagicPetData.gid then
        self:OnClickBagPet(v, self.CurrentPet)
        self.BattleManager.debugEnv.GmChangeMagicPet = nil
        self.BattleManager.debugEnv.GmChangeMagicPetData = nil
      end
    end
  end
end

function RoundSwapAction:OnClickBagPetIcon(gid)
  self.SelectMarkerManager:ClearSelection()
  self.SelectMarkerManager:ShowSelectMarkers(BattleEnum.SelectMarkerType.ENUM_MYSELF_ALLY)
  local playerSkillPhase, activedPlayerSkillInfo = self.CurrentPlayer:GetPlayerSkillPhase()
  local canChange = false
  if self.CurrentMyPets then
    for _, v in ipairs(self.CurrentMyPets) do
      if v.guid ~= gid and v.player == self.CurrentPlayer then
        if BattleUtils.CheckIfChangePetBan(v) then
          v:HideClickTipUI()
          v:SetClickable(false)
        else
          if v.model then
            v:PlayAnimByName("Show")
          end
          canChange = true
          if playerSkillPhase == BattleEnum.PlayerSkillPhase.NoSkill then
            v:SetHighlight(v.opState ~= BattleEnum.Operation.ENUM_CHANGE, true)
          elseif playerSkillPhase ~= BattleEnum.PlayerSkillPhase.WaitingToPerform and activedPlayerSkillInfo:IsChangePetEffectType() then
            v:SetHighlight(v.opState ~= BattleEnum.Operation.ENUM_CHANGE, true)
          end
          v:ShowClickTipUI(nil)
        end
      else
        v:HideClickTipUI()
        v:SetClickable(false)
      end
    end
  end
  local playerSkillPhase, activedPlayerSkillInfo = self.CurrentPlayer:GetPlayerSkillPhase()
  if playerSkillPhase ~= BattleEnum.PlayerSkillPhase.NoSkill and playerSkillPhase ~= BattleEnum.PlayerSkillPhase.WaitingToPerform and activedPlayerSkillInfo:IsChangePetEffectType() then
    local Item = self:GetPlayerSkillItem()
    if Item then
      self.CurrentPlayer:TakeCompassWithID(Item.item_conf_id or 0)
    end
  else
    local card = self.CurrentPlayer.team:GetCardByGuid(gid)
    self.CurrentPlayer:TakeBallWithCard(card, BattleEnum.Operation.ENUM_CHANGE)
  end
  if canChange then
    self:SetPetsDark(BattleEnum.Team.ENUM_ENEMY, true)
    self:ToggleDarkScene(true)
    self.fsm:SetProperty("CurrentSelectGuid", gid)
  else
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, string.format(LuaText.roundswapaction_1))
  end
end

function RoundSwapAction:OnClickBagPet(Card, pet)
  Log.Debug("BattleRoundSelectAction:OnClickBagPet")
  local infieldPetCard = pet and pet.card
  local isValidIfInfieldPetHasBuff145 = self:IsUpPetValidIfInfieldPetHasBuff145(Card, infieldPetCard)
  if not isValidIfInfieldPetHasBuff145 then
    self:ShowBuff145NotMatchTips()
    return
  end
  self.pet = pet
  self.Card = Card
  if not self.CurrentPet then
    Log.Error("BattleRoundSelectAction:OnChangePet - cur pet is nil")
    return
  end
  if self.CurrentMyPets then
    for _, v in ipairs(self.CurrentMyPets) do
      v:ShowOperation(true)
      v:ShowActiveState(false)
    end
  end
  self:ResetPetsLight()
  self:ToggleDarkScene(false)
  self.SelectMarkerManager:ClearSelection()
  self.SelectMarkerManager:HideClickTipUI()
  if self.CurrentMyPets then
    for _, v in ipairs(self.CurrentMyPets) do
      v:SetHighlight(false)
    end
  end
  local skillPhase, skillData = self.CurrentPlayer:GetPlayerSkillPhase()
  Log.Debug(skillPhase, "RoundSwapAction:OnClickBagPet")
  if skillPhase == BattleEnum.PlayerSkillPhase.TryToPetActive and skillData:IsChangePetEffectType() then
    local BattleRoundFlowReqList = {}
    local BattleRoundFlowReq = {}
    local req = BattleNetManager:BuildBattleCmdPushbackReq()
    req.req_type = _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_ROLE_MAGIC
    BattleRoundFlowReq.req_type = _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_ROLE_MAGIC
    BattleRoundFlowReq.magic_op = {}
    BattleRoundFlowReq.magic_op.target_pet_id = pet.card.guid
    BattleRoundFlowReq.magic_op.target_pet_pos = pet.card.pos
    BattleRoundFlowReq.magic_op.up_pet_id = Card.guid
    table.insert(BattleRoundFlowReqList, BattleRoundFlowReq)
    req.req = BattleRoundFlowReqList
    skillData:SetClickPetAndUpPet(pet, Card)
    self:SendPushbackReq(req)
  else
    self.fsm:SetProperty("WillChangePet", true)
    local restPets = self.CurrentPet.team.RestPets
    if restPets[pet.card.pos] then
      pet = restPets[pet.card.pos]
    end
    if skillPhase == BattleEnum.PlayerSkillPhase.WaitingToPerform and skillData:IsChangePetEffectType() then
      local ClickPet, UpPet = skillData:GetClickPetAndUpPet()
      pet = UpPet
    end
    local BattleRoundFlowReqList = {}
    local BattleRoundFlowReq = {}
    local req = BattleNetManager:BuildBattleCmdPushbackReq()
    req.req_type = _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_CHANGE_PET
    BattleRoundFlowReq.req_type = _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_CHANGE_PET
    BattleRoundFlowReq.change_pet = {}
    BattleRoundFlowReq.change_pet.rest_pet_id = pet.guid
    BattleRoundFlowReq.change_pet.battle_pet_id = Card.guid
    BattleRoundFlowReq.change_pet.player_id = self.CurrentPet.player.guid
    table.insert(BattleRoundFlowReqList, BattleRoundFlowReq)
    req.req = BattleRoundFlowReqList
    Log.Dump(req, nil, "BattleRoundSelectAction:OnChangePet")
    self:SendPushbackReq(req)
    self:CheckRoleHp(BattleRoundFlowReq.change_pet)
  end
end

function RoundSwapAction:UsePlayerSkillSuccess()
  local skillPhase, skillData = self.CurrentPlayer:GetPlayerSkillPhase()
  local rest_pet_id = self.pet.guid
  local battle_pet_id = self.Card.guid
  local player_id = self.CurrentPlayer.guid
  skillData:Play(self.CurrentPlayer, rest_pet_id, battle_pet_id, player_id)
  self.CurrentPlayer:SetPlayerSkill(BattleEnum.PlayerSkillPhase.WaitingToPerform)
end

function RoundSwapAction:PetLoadModeLover()
  if not self.CurrentPlayer then
    return
  end
  local skillPhase, skillData = self.CurrentPlayer:GetPlayerSkillPhase()
  if skillPhase == BattleEnum.PlayerSkillPhase.WaitingToPerform and skillData:IsChangePetEffectType() then
    local BattlePet = _G.BattleManager.battlePawnManager:GetPetByGuid(self.Card.guid)
    skillData:PlayLinkEffect(BattlePet, self.OnSkillChangedCallback)
  end
end

function RoundSwapAction:OnSkillChangedCallback()
  _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_PLAY_PLAYERSKILL_SUCCESS)
end

function RoundSwapAction:CheckRoleHp(req)
  local hp = self.BattleManager.battlePawnManager:GetPlayerMyTeam().roleInfo.base.hp
  local hp_need = 0
  local id = req.battle_pet_id
  local card = self.BattleManager.battlePawnManager:GetPlayerMyTeam().deck:GetCardByGuid(id)
  local baseID = card.petInfo.battle_common_pet_info.base_conf_id
  local baseConf = _G.DataConfigManager:GetPetbaseConf(baseID)
  if not baseConf then
    Log.Error("Pet base ID not found: ", baseID)
    self:Finish()
    return
  end
  hp_need = hp_need + baseConf.consume_role_hp
  if hp > hp_need then
    _G.NRCModeManager:DoCmd(BattleUIModuleCmd.CloseBattleRedPanel)
  else
    _G.NRCModeManager:DoCmd(BattleUIModuleCmd.OpenBattleRedPanel)
  end
end

function RoundSwapAction:OnExit()
  self.fsm:SetProperty("CurrentSelectGuid", 0)
  _G.BattleEventCenter:UnBind(self)
  self.CurrentPlayer:RecallBall()
  self:ResetPetsLight()
  if self.CurrentMyPets then
    for _, v in ipairs(self.CurrentMyPets) do
      v:SetHighlight(false)
    end
  end
  self.CurrentPushbackReq = nil
  self.CurrentSkill = nil
  Base.OnExit(self)
end

function RoundSwapAction:CancelUsePlayerSkill()
  _G.BattleManager.battleRuntimeData.operateType = BattleEnum.Operation.ENUM_ITEM
  self:SendFsmEventInfo(BattleEvent.RoundEvent.EnterItem)
  self.CurrentPlayer:SetPlayerSkill(BattleEnum.PlayerSkillPhase.NoSkill)
end

function RoundSwapAction:SendFsmEventInfo(curEvent)
  if curEvent then
    self.fsm:SendEvent(curEvent)
    self.fsm:SetProperty("StateEvent", curEvent)
  end
end

function RoundSwapAction:IsUpPetValidIfInfieldPetHasBuff145(upPetCard, infieldPetCard)
  local inFieldPetInfo = infieldPetCard and infieldPetCard.petInfo
  local inFieldInsideInfo = inFieldPetInfo and inFieldPetInfo.battle_inside_pet_info
  local buff145SourcePetId = inFieldInsideInfo and inFieldInsideInfo.buff145_source_pet
  local isGenerateByBuff145 = buff145SourcePetId and buff145SourcePetId > 0
  local upPetInfoId = upPetCard and upPetCard.guid
  local isNotValid = isGenerateByBuff145 and buff145SourcePetId ~= upPetInfoId
  local isValid = not isNotValid
  if isValid then
    local currMyPets = self.CurrentMyPets or {}
    local currMyPetsCount = #currMyPets
    if currMyPetsCount > 1 then
      local upPetInfo = upPetCard and upPetCard.petInfo
      local upInsideInfo = upPetInfo and upPetInfo.battle_inside_pet_info
      local upBuff145SourcePetId = upInsideInfo and upInsideInfo.buff145_source_pet
      local upIsGenerateByBuff145 = upBuff145SourcePetId and upBuff145SourcePetId > 0
      local infieldPetInfoId = infieldPetCard and infieldPetCard.guid
      isNotValid = upIsGenerateByBuff145 and upBuff145SourcePetId ~= infieldPetInfoId
      isValid = not isNotValid
    end
  end
  return isValid
end

function RoundSwapAction:ShowBuff145NotMatchTips()
  local currMyPets = self.CurrentMyPets or {}
  local currMyPetsCount = #currMyPets
  Log.Info("RoundSwapAction:OnClickBagPet: The in field pet has buff145 and the up pet is not the source pet if it.")
  local buff145SwapErrorTextConf = _G.DataConfigManager:GetLocalizationConf("buff _145_1", true)
  if currMyPetsCount > 1 then
    buff145SwapErrorTextConf = _G.DataConfigManager:GetLocalizationConf("buff _145_2", true)
  end
  local buff145SwapErrorText = buff145SwapErrorTextConf and buff145SwapErrorTextConf.msg
  _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, buff145SwapErrorText)
end

function RoundSwapAction:OnBattleEvent(eventName, ...)
  if eventName == BattleEvent.BATTLE_CLICKED_CHANGEPET then
    self:OnClickBagPet(...)
    return true
  elseif eventName == BattleEvent.BATTLE_CLICKED_BAG_PET then
    self:OnClickBagPetIcon(...)
    return true
  elseif eventName == BattleEvent.BATTLE_USE_PLAYERSKILL_SUCCESS then
    self:UsePlayerSkillSuccess()
    return true
  elseif eventName == BattleEvent.BATTLE_CANCEL_USE_PLAYERSKILL then
    self:CancelUsePlayerSkill()
    return true
  elseif eventName == BattleEvent.PET_LOAD_MODE_LOVER then
    self:PetLoadModeLover()
    return true
  end
end

return RoundSwapAction
