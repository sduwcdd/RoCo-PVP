local UMG_BloodMagic_C = _G.NRCPanelBase:Extend("UMG_BloodMagic_C")

function UMG_BloodMagic_C:OnActive(Action)
  self:PlayAnimation(self.In)
  self.BtnClose.OnClicked:Add(self, self.OnClicked)
  if Action then
    self.action = Action
    local BagItemId = tonumber(self.action.BagItemId)
    if BagItemId then
      local BagItemConf = _G.DataConfigManager:GetBagItemConf(BagItemId)
      if BagItemConf then
        local TempTitle = _G.DataConfigManager:GetLocalizationConf("get_blood_magic").msg
        if TempTitle then
          self.ResonanceMagicTitle:SetText(string.format(TempTitle, BagItemConf.Name))
          self.ResonanceMagicIcon:SetPath(BagItemConf.big_icon)
        end
      end
    end
  end
end

function UMG_BloodMagic_C:OnClicked()
  if self.Out then
    self:PlayAnimation(self.Out)
  else
    self:OnAnimationFinished(self.Out)
  end
end

function UMG_BloodMagic_C:OnAnimationFinished(Anim)
  if Anim == self.Out then
    self.action:CloseMagicUmg()
    _G.NRCModuleManager:DoCmd(_G.DialogueModuleCmd.CloseBloodMagic)
  end
end

return UMG_BloodMagic_C
