local UMG_Weather_Tips_C = _G.NRCPanelBase:Extend("UMG_Weather_Tips_C")

function UMG_Weather_Tips_C:OnActive()
  self:OnAddEventListener()
  self:RefreshUI()
end

function UMG_Weather_Tips_C:OnDeactive()
end

function UMG_Weather_Tips_C:OnAddEventListener()
  self:AddButtonListener(self.HotArea, self.OnClickHotArea)
end

function UMG_Weather_Tips_C:OnTick()
end

function UMG_Weather_Tips_C:OnLogin()
end

function UMG_Weather_Tips_C:OnConstruct()
end

function UMG_Weather_Tips_C:OnDestruct()
end

function UMG_Weather_Tips_C:OnAnimationFinished(anim)
end

function UMG_Weather_Tips_C:OnClickHotArea()
  _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.CloseWeatherTips)
end

function UMG_Weather_Tips_C:GetTod()
  local envTod = 0
  local EnvSystem = _G.NRCModuleManager:GetModule("EnvSystemModule")
  if EnvSystem then
    envTod = math.floor(EnvSystem:GetCurrentTime() / 3600.0)
  else
    Log.Error("EnvSystem\232\142\183\229\143\150\229\164\177\232\180\165\239\188\140\230\136\152\230\150\151tod\229\183\178\231\166\129\231\148\168")
  end
  if envTod >= 0 and envTod < 4 then
    return 1
  elseif envTod >= 4 and envTod < 8 then
    return 2
  elseif envTod >= 8 and envTod < 12 then
    return 3
  else
    return 4
  end
end

function UMG_Weather_Tips_C:RefreshUI()
  self.HotArea:SetVisibility(UE4.ESlateVisibility.Collapsed)
  local weatherConf = _G.DataConfigManager:GetWeatherConf(_G.BattleManager.battleRuntimeData.curWeatherID)
  if not weatherConf then
    return
  end
  self.Text_GoodAndBad:SetText(weatherConf.name)
  local envTod = self:GetTod()
  local weatherDesc = _G.BattleUtils.FindWeatherDesc(weatherConf.weather_type, envTod)
  self.textBuffDesc:SetText(weatherDesc)
  self.WeatherIcon:SetPath(weatherConf.icon)
end

return UMG_Weather_Tips_C
