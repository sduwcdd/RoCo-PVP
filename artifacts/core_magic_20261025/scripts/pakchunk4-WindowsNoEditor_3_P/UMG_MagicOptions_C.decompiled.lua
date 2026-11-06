local Base = require("NewRoco.TUI.BP_NRCItemBase_C")
local PlayerModuleEvent = require("NewRoco.Modules.Core.PlayerModule.PlayerModuleEvent")
local EnhancedInputModuleEvent = require("NewRoco.Modules.Core.EnhancedInput.EnhancedInputModuleEvent")
local AbilityHelperManager = require("NewRoco.Modules.Core.Scene.Component.Ability.AbilityHelperManager")
local AbilityErrorCode = require("NewRoco.Modules.Core.Scene.Component.Ability.AbilityErrorCode")
local UMG_MagicOptions_C = Base:Extend("UMG_MagicOptions_C")

function UMG_MagicOptions_C:OnConstruct()
  self:AddEventListener()
end

function UMG_MagicOptions_C:OnDestruct()
  _G.NRCEventCenter:UnRegisterEvent(self, EnhancedInputModuleEvent.KeyMappingsChanged, self.PCKeySetting)
end

function UMG_MagicOptions_C:AddEventListener()
  _G.NRCEventCenter:RegisterEvent("UMG_MagicOptions_C", self, EnhancedInputModuleEvent.KeyMappingsChanged, self.PCKeySetting)
end

function UMG_MagicOptions_C:OnItemUpdate(_data, datalist, index)
  self.uiData = _data
  self.index = index
  self.datalist = datalist
  self:UpdateItemInfo()
  local initIndex = self.index % 6
  self:PCKeySetting(initIndex)
end

function UMG_MagicOptions_C:UpdateItemInfo()
  if self.uiData and self.uiData.isEmpty then
    self.CanvasPanel_41:SetVisibility(UE4.ESlateVisibility.Collapsed)
    return
  else
    self.CanvasPanel_41:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
  end
  self:StopAllAnimations()
  self.ItemIcon:SetVisibility(UE4.ESlateVisibility.Collapsed)
  self.SelectedAnim_bg:SetVisibility(UE4.ESlateVisibility.Collapsed)
  local getEquipMagic = _G.NRCModuleManager:DoCmd(_G.BagModuleCmd.GetEquipMagicInfo)
  if self.uiData and self.uiData and self.uiData.id then
    local bagItemConf = _G.DataConfigManager:GetBagItemConf(self.uiData.id)
    if bagItemConf and bagItemConf.type == _G.Enum.BagItemType.BI_MAGIC then
      if getEquipMagic and getEquipMagic.gid == self.uiData.gid then
        self.SelectedAnim_bg:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
        self:PlayAnimation(self.Select)
      end
      if bagItemConf.TUIbutton_icon then
        self.ItemIcon:SetVisibility(UE4.ESlateVisibility.Visible)
        self.ItemIcon:SetPath(bagItemConf.TUIbutton_icon)
      end
    end
    self:IsConsumableMagic(bagItemConf)
  end
end

function UMG_MagicOptions_C:IsConsumableMagic(bagItemConf)
  if bagItemConf and bagItemConf.magic_id and 0 ~= bagItemConf.magic_id then
    self:SetSelectable(true)
    self.ItemIcon_Mask:SetVisibility(UE4.ESlateVisibility.Collapsed)
    local isEnough = false
    local bIsShowCornerMark = false
    local magicBaseConf = _G.DataConfigManager:GetMagicBaseConf(bagItemConf.magic_id)
    local abilityHelper = AbilityHelperManager.GetHelper(magicBaseConf.sceneability)
    self.NumText:SetVisibility(UE4.ESlateVisibility.Hidden)
    local costItem, costNum
    if magicBaseConf.cost_bag_item and magicBaseConf.cost_bag_item[1] and magicBaseConf.cost_bag_item[2] then
      costItem = magicBaseConf.cost_bag_item[1]
      costNum = magicBaseConf.cost_bag_item[2]
    elseif abilityHelper and abilityHelper.GetCurrentSubMagicId then
      local subMagicId = abilityHelper:GetCurrentSubMagicId()
      if subMagicId then
        local subMagicConf = _G.DataConfigManager:GetMagicBaseConf(subMagicId, true)
        if subMagicConf and subMagicConf.cost_bag_item and subMagicConf.cost_bag_item[1] and subMagicConf.cost_bag_item[2] then
          costItem = subMagicConf.cost_bag_item[1]
          costNum = subMagicConf.cost_bag_item[2]
        end
      end
    end
    if costItem and costNum then
      local costData = _G.NRCModuleManager:DoCmd(_G.BagModuleCmd.GetBagItemByID, costItem)
      if costData and costData.num then
        if costNum <= costData.num then
          isEnough = true
          local usableTimes = costData.num / costNum
          usableTimes = math.floor(usableTimes)
          local bShowCostItemNum = false
          local costBagItemConf = _G.DataConfigManager:GetBagItemConf(costItem)
          if costBagItemConf then
            bShowCostItemNum = 0 ~= costBagItemConf.show_quantity
          end
          if bShowCostItemNum then
            self.NumText:SetText(usableTimes)
            self.NumText:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
          else
            self.NumText:SetVisibility(UE4.ESlateVisibility.Hidden)
          end
          self.ItemIcon_Mask:SetPath(bagItemConf.TUIbutton_icon)
          self.ItemIcon_Mask:SetVisibility(UE4.ESlateVisibility.Collapsed)
          self.CornerMark:SetVisibility(UE4.ESlateVisibility.Collapsed)
          self.CornerMark:SetPath("PaperSprite'/Game/NewRoco/Modules/System/MainUI/Raw/Atlas/MainUI/Frames/img_Forbidden_png.img_Forbidden_png'")
        else
          isEnough = false
          self.NumText:SetVisibility(UE4.ESlateVisibility.Hidden)
          self.ItemIcon_Mask:SetPath(bagItemConf.TUIbutton_icon)
          self.ItemIcon_Mask:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
          self.CornerMark:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
          self.CornerMark:SetPath("PaperSprite'/Game/NewRoco/Modules/System/MainUI/Raw/Atlas/MainUI/Frames/img_InsufficientMaterial_png.img_InsufficientMaterial_png'")
          bIsShowCornerMark = true
        end
      else
        isEnough = false
        self.NumText:SetVisibility(UE4.ESlateVisibility.Hidden)
        self.ItemIcon_Mask:SetPath(bagItemConf.TUIbutton_icon)
        self.ItemIcon_Mask:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
        self.CornerMark:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
        self.CornerMark:SetPath("PaperSprite'/Game/NewRoco/Modules/System/MainUI/Raw/Atlas/MainUI/Frames/img_InsufficientMaterial_png.img_InsufficientMaterial_png'")
        bIsShowCornerMark = true
      end
    else
      isEnough = true
    end
    if abilityHelper then
      if abilityHelper.InitFromConf then
        abilityHelper:InitFromConf(bagItemConf.id, bagItemConf.magic_id, magicBaseConf.sceneability)
      end
      local localPlayer = _G.NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
      self.bIsBlock, self.MyAbilityErrorCode = abilityHelper:IsBlock(localPlayer)
      self.isBan = _G.NRCModuleManager:DoCmd(_G.MainUIModuleCmd.ExceptBanMyAbilityErrorCode, self.MyAbilityErrorCode)
      if (not self.bIsBlock or self.bIsBlock and not self.isBan) and isEnough then
        if not bIsShowCornerMark then
          self.CornerMark:SetVisibility(UE4.ESlateVisibility.Collapsed)
        end
        self:SetSelectable(true)
        self:SetClickable(true)
      else
        self.ItemIcon_Mask:SetVisibility(UE4.ESlateVisibility.Collapsed)
        self:SetSelectable(false)
        self:SetClickable(false)
        self.CornerMark:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
        self.NumText:SetVisibility(UE4.ESlateVisibility.Hidden)
        self.ItemIcon_Mask:SetPath(bagItemConf.TUIbutton_icon)
        self.ItemIcon_Mask:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
        return
      end
    end
  end
end

function UMG_MagicOptions_C:OnItemSelected(_bSelected)
  local getEquipMagic = _G.NRCModuleManager:DoCmd(_G.BagModuleCmd.GetEquipMagicInfo)
  if self.uiData and self.uiData.gid then
    if getEquipMagic and getEquipMagic.gid == self.uiData.gid then
      if not _bSelected then
        self.SelectedAnim_bg:SetVisibility(UE4.ESlateVisibility.Collapsed)
      end
    else
      self:StopAllAnimations()
      local itemConf = _G.DataConfigManager:GetBagItemConf(self.uiData.id)
      if _bSelected then
        if itemConf.type == _G.Enum.BagItemType.BI_MAGIC then
          local bagItemConf = _G.DataConfigManager:GetBagItemConf(getEquipMagic.id)
          local abilityID = 0
          local magicConf = _G.DataConfigManager:GetMagicBaseConf(bagItemConf.magic_id, true)
          if magicConf then
            abilityID = magicConf.sceneability
            self._abilityHelper = AbilityHelperManager.GetHelper(abilityID)
            self.localPlayer = _G.NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
            local buff = self._abilityHelper:GetBuff(self.localPlayer)
            if buff and not buff.waitCasting then
              self.ItemIcon:SetVisibility(UE4.ESlateVisibility.Visible)
              self.SelectedAnim_bg:SetVisibility(UE4.ESlateVisibility.SelfHitTestInvisible)
              UE4.UNRCAudioManager.Get():PlaySound2DAuto(1305, "UMG_SimpleListItemTemplate_C:OnItemSelected")
              self:PlayAnimation(self.Select)
              _G.NRCModuleManager:DoCmd(BagModuleCmd.SetEquipMagicInfo, self.uiData, true)
              self:ResetAimState()
              _G.NRCModuleManager:DoCmd(MainUIModuleCmd.ReThrowMagic)
            end
          end
        end
      else
        self.SelectedAnim_bg:SetVisibility(UE4.ESlateVisibility.Collapsed)
      end
    end
  end
end

function UMG_MagicOptions_C:ResetAimState()
  self.localPlayer = _G.NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  local CurrentVitra = _G.NRCModeManager:DoCmd(MainUIModuleCmd.GetCurrentVitra)
  self.localPlayer.vitalityComponent:RecoverVitalityByValue(CurrentVitra)
  local player = NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  if player then
    player:SendEvent(PlayerModuleEvent.ON_END_THROW, false)
    player:SendEvent(PlayerModuleEvent.ON_RETURN_MAGIC_COST)
    if player.statusComponent:HasStatus(ProtoEnum.WorldPlayerStatusType.WPST_MAGIC) then
      _G.NRCModuleManager:DoCmd(MainUIModuleCmd.AbilitySlotChangeMagicLimit)
      player.statusComponent:RemoveStatus(ProtoEnum.WorldPlayerStatusType.WPST_MAGIC)
    end
  end
  _G.NRCModuleManager:GetModule("MainUIModule"):DispatchEvent(MainUIModuleEvent.UI_SHOW_AIM_JOYSTICK, false)
  _G.NRCModuleManager:DoCmd(MainUIModuleCmd.ShowAutoLockIcon, true)
end

function UMG_MagicOptions_C:IsMessageMagic()
  local bagItemConf = _G.DataConfigManager:GetBagItemConf(self.uiData.id)
  local magicBaseConf = _G.DataConfigManager:GetMagicBaseConf(bagItemConf.magic_id)
  if magicBaseConf.magic_type == Enum.SceneMagicType.SMT_CREATE_MAGIC_MASSAGE then
    return true
  else
    return false
  end
end

function UMG_MagicOptions_C:IsVideoMagic()
  local bagItemConf = _G.DataConfigManager:GetBagItemConf(self.uiData.id)
  local magicBaseConf = _G.DataConfigManager:GetMagicBaseConf(bagItemConf.magic_id)
  if magicBaseConf.magic_type == Enum.SceneMagicType.SMT_CREATE_MAGIC_VIDEO then
    return true
  else
    return false
  end
end

function UMG_MagicOptions_C:IsCreateMagic()
  local bagItemConf = _G.DataConfigManager:GetBagItemConf(self.uiData.id)
  local magicBaseConf = _G.DataConfigManager:GetMagicBaseConf(bagItemConf.magic_id)
  if magicBaseConf.magic_type == Enum.SceneMagicType.SMT_CREATE then
    return true
  else
    return false
  end
end

function UMG_MagicOptions_C:PCKeySetting(pcIndex)
  if SystemSettingModuleCmd then
    local InputAction = string.format("IA_SelectPetStart_%s", pcIndex)
    local text, image = _G.NRCModuleManager:DoCmd(SystemSettingModuleCmd.GetMappingKeyUIName, InputAction)
    if "" ~= image then
      self.Text_PCKey:SetImageMode(image)
    else
      self.Text_PCKey:SetText(text)
    end
    self.Text_PCKey:SetKeyVisibility(true)
  end
end

function UMG_MagicOptions_C:IsPCMode()
  return UE.UGameplayStatics.GetGameInstance(self):IsPCMode()
end

function UMG_MagicOptions_C:OnItemClicked(bClicked)
  if not self.selectable then
    if self.MyAbilityErrorCode == AbilityErrorCode.DUNGEON_BAN then
      _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LuaText.TryCastMagic_WrongScene)
    elseif self.MyAbilityErrorCode == AbilityErrorCode.AREA_BAN then
      _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LuaText.TryCastMagic_WrongScene)
    elseif self.MyAbilityErrorCode == AbilityErrorCode.BAG_ITEM_NOT_ENOUGH then
      if self:IsVideoMagic() then
        _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LuaText.mark_video_lack_of_item)
      else
        _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LuaText.TryCastMagic_InsufficientMaterial)
      end
    elseif self.MyAbilityErrorCode == AbilityErrorCode.STORY_BAN then
      if self:IsMessageMagic() then
        _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LuaText.magic_message_status_fobbiden)
      end
    elseif self.MyAbilityErrorCode == AbilityErrorCode.FUNC_BAN then
      _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LuaText.TryCastMagic_Create_LitteGame)
    elseif self.MyAbilityErrorCode == AbilityErrorCode.GAME_BAN then
      if self:IsMessageMagic() or self:IsVideoMagic() then
        local retCode = ProtoEnum.MOBA_RET.FeedSvrErr.ERR_FEEDSVR_AREA_NOT_ALLOW_CREATE_FEED
        local Key = string.format("Error_Code_%d", retCode)
        local ErrorText = _G.DataConfigManager:GetLocalizationConf(Key, true)
        ErrorText = ErrorText and ErrorText.msg
        _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, ErrorText)
      else
        _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LuaText.TryCastMagic_Create_LitteGame)
      end
    elseif self.MyAbilityErrorCode == AbilityErrorCode.VISIT_BAN then
      if self:IsMessageMagic() then
        local ErrorText = _G.DataConfigManager:GetLocalizationConf("magic_message_multiplayer_fobbiden").msg
        _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, ErrorText)
      elseif self:IsCreateMagic() then
        local ErrorText = _G.DataConfigManager:GetLocalizationConf("Error_Code_50251").msg
        _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, ErrorText)
      end
    elseif self.MyAbilityErrorCode == AbilityErrorCode.FORBID_PARENT then
      _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, LuaText.child_magic_not_choose)
    end
    return false
  end
  return true
end

return UMG_MagicOptions_C
