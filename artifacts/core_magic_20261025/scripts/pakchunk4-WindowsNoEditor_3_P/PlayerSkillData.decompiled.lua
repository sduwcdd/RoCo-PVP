local PlayerSkillData = NRCClass()

function PlayerSkillData:Ctor()
  self.IsPlayerSkillSuccess = false
  self.BeginUsePlayerSkill = false
end

function PlayerSkillData:Reset()
  self.IsPlayerSkillSuccess = false
  self.BeginUsePlayerSkill = false
end

function PlayerSkillData:SetBeginUsePlayerSkill(_BeginUsePlayerSkill)
  self.BeginUsePlayerSkill = _BeginUsePlayerSkill
end

function PlayerSkillData:SetIsPlayerSkillSuccess(_IsPlayerSkillSuccess)
  self.IsPlayerSkillSuccess = _IsPlayerSkillSuccess
end

function PlayerSkillData:GetBeginUsePlayerSkill()
  return self.BeginUsePlayerSkill
end

function PlayerSkillData:GetIsPlayerSkillSuccess()
  return self.IsPlayerSkillSuccess
end

return PlayerSkillData
