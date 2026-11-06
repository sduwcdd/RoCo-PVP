local BattleUIModuleCmd = require("NewRoco.Modules.System.BattleUI.BattleUIModuleCmd")
local EventDispatcher = require("Common.EventDispatcher")
local ProtoCMD = require("Data.PB.ProtoCMD")
local VBattleField = require("NewRoco.Modules.Core.Battle.View.VBattleField")
local BattleRuntimeData = require("NewRoco.Modules.Core.Battle.Data.BattleRuntimeData")
local BattleInfoManager = require("NewRoco.Modules.Core.Battle.Entity.BattleInfo.BattleInfoManager")
local BattleObjectManager = require("NewRoco.Modules.Core.Battle.Entity.BattleObjectManager")
local BattlePawnManager = require("NewRoco.Modules.Core.Battle.View.BattlePawnManager")
local BattleFadeManager = require("NewRoco.Modules.Core.Battle.View.BattleFadeManager")
local BattleUtils = require("NewRoco.Modules.Core.Battle.Common.BattleUtils")
local BattleSeasonUtils = require("NewRoco.Modules.Core.Battle.Common.BattleSeasonUtils")
local BattleEvent = require("NewRoco.Modules.Core.Battle.Common.BattleEvent")
local BattleFsm = require("NewRoco.Modules.Core.Battle.Fsm.BattleFsm")
local InstantBattleFsm = require("NewRoco.Modules.Core.Battle.Fsm.InstantBattleFsm")
local SceneEvent = require("NewRoco.Modules.Core.Scene.Common.SceneEvent")
local DialogueModuleCmd = require("NewRoco.Modules.System.Dialogue.DialogueModuleCmd")
local DialogContext = require("NewRoco.Modules.System.TipsModule.DialogContext")
local TipObject = require("NewRoco.Modules.System.TipsModule.Utils.TipObject")
local TaskModuleEvent = require("NewRoco.Modules.Core.Task.TaskModuleEvent")
local TipEnum = require("NewRoco.Modules.System.TipsModule.Utils.TipEnum")
local EnvSystemModuleCmd = require("NewRoco.Modules.System.EnvSystem.EnvSystemModuleCmd")
local BattleResourceManager = require("NewRoco.Modules.Core.Battle.BattleCore.BattleResourceManager")
local LuaText = require("LuaText")
local BattleEnum = require("NewRoco.Modules.Core.Battle.Common.BattleEnum")
local BattleExitHelper = require("NewRoco.Modules.Core.Battle.Players.BattleExitHelper")
local HiddenComponent = require("NewRoco.Modules.Core.Scene.Component.Hidden.HiddenComponent")
local BattleConst = require("NewRoco.Modules.Core.Battle.Common.BattleConst")
local FsmEnum = require("NewRoco.Modules.Core.Fsm.FsmEnum")
local BattleCraneCameraDefine = require("NewRoco.Modules.Core.Battle.CraneCamera.BattleCraneCameraDefine")
local BattleSelectTarget = require("NewRoco.Modules.Core.Battle.BattleSelectTarget")
local NRCSDKManagerEnum = require("Core.Service.SDKManager.NRCSDKManagerEnum")
local TeleportLockEnum = require("NewRoco.Modules.Core.Scene.Component.RoleHP.TeleportLockEnum")
local LockWeatherReason = require("NewRoco.Modules.System.EnvSystem.LockWeatherReason")
local BattleTutorialGuideModuleEvent = require("NewRoco.Modules.System.BattleTutorialGuide.BattleTutorialGuideModuleEvent")
local DummyTable = require("Common.DummyTable")
local JsonUtils = require("Common.JsonUtils")
local PVPRankedMatchModuleUtils = require("NewRoco.Modules.System.PVPQualifier.PVPRankedMatchModuleUtils")
local BattleManager = Class()
BattleManager.DebugBattleHide = false
BattleManager.PerformType = "Perform"
BattleManager.RoundType = "Round"

function BattleManager:Ctor()
  EventDispatcher():Attach(self)
  self.battleRuntimeData = BattleRuntimeData()
  self.battleInfoManager = BattleInfoManager()
  self.debugEnv = {}
  self.isPreloadResWithoutWaiting = false
  self.ShouldWaitGlobalLoading = false
  self.isEnterActionWaitResDone = true
  self.stateFsm = nil
  self.curRound = 0
  self.RoundStartRecord = 0
  self.serverRound = 0
  self.AIRound = 1
  self.isInBattle = false
  self.isTeamSkipWaitLoad = false
  self.isSendWaiting = false
  self.isClear = true
  self._isBattleAgainPending = false
  if RocoEnv.IS_SHIPPING then
    self.isDefaultShowVisible = false
  else
    self.isDefaultShowVisible = true
  end
  self.curRandBgmStage = nil
  self.battleNetManager = _G.BattleNetManager
  self.vBattleField = VBattleField
  self.battleObjectManager = BattleObjectManager
  self.battlePawnManager = BattlePawnManager
  self.battleResourceManager = _G.BattleResourceManager
  self.battleFadeManager = BattleFadeManager()
  self.battleBgmSession = -1
  self.currentBgmId = -1
  self.AIHistoryInfo = {}
  self.EscapeContext = DialogContext()
  self.EscapeContext:SetContent(LuaText.ASK_ESCAPE_BATTLE):SetButtonText(LuaText.YES, LuaText.NO):SetMode(DialogContext.Mode.OK_CANCEL)
  self.turnPlayer = nil
  self.OnTickCurStep = 0
  self.OnTickMaxStep = 3
  self.CheerPetsWorldInfo = {}
  self.ComboSkillInfo = {}
  self.TeamBattleNotifyQueue = {}
  self.CurTeamBattlePerformNotify = nil
  self.LastSequencePerformNotify = nil
  self.LeaderChallengeGiveUp = nil
  self.IsOpenDepth = false
  _G.enableAdaptiveBattlePetPos = true
  self.isSkipEnterAction = false
  self.SelectTargetManager = BattleSelectTarget()
  _G.EnableRoundStartNotify = false
  BattleProfiler:Init()
end

function BattleManager:Init()
  if BattleConst.ForceWaterBattle then
    BattleConst.CanBattleEverywhere = true
    _G.ForceTestWaterSurfaceBattle = true
  end
  if not RocoEnv.IS_EDITOR or not _G.NRCEditorEntranceEnable then
    local GameInstance = UE4.UNRCPlatformGameInstance.GetInstance()
    if GameInstance then
      local curveXPath = "CurveFloat'/Game/ArtRes/Effects/Curve/Float1/CUR_Float_ComCam_Fx_X.CUR_Float_ComCam_Fx_X'"
      local curveX = GameInstance:GetRuntimeCacheObj(curveXPath)
      local curveYPath = "CurveFloat'/Game/ArtRes/Effects/Curve/Float1/CUR_Float_ComCam_Fx_Y.CUR_Float_ComCam_Fx_Y'"
      local curveY = GameInstance:GetRuntimeCacheObj(curveYPath)
    end
  end
  self.battleVisibilityUtils = require("NewRoco.Modules.Core.Battle.Common.BattleVisibilityUtils")()
  self.battleVisibilityUtils:Init(self)
  self:AddListeners()
end

function BattleManager.EditorInitBattleDepthCam(world, actors, pos)
  Log.Debug("BattleManager EditorInitBattleDepthCam:", actors:Length())
  BattleResourceManager:InitTable()
  local DepthCamCla = BattleResourceManager:LoadUClassOnEditor("/Game/NewRoco/Modules/Core/Battle/BattleDepthCam/BP_BattleDepthCam.BP_BattleDepthCam_C")
  local lst = {}
  for i = 1, actors:Length() do
    local actor = actors:Get(i)
    if actor then
      table.insert(lst, actor)
    end
  end
  local BattleDepthCam = UE4.UGameplayStatics.GetActorOfClass(world, DepthCamCla)
  if BattleDepthCam then
    BattleDepthCam:EditorMoveToBattleCenterPos(pos)
    BattleDepthCam:EditorSetHiddenActor(lst)
    BattleDepthCam:EditorUpdate()
  end
end

function BattleManager:InitBattleField()
  self.isClear = false
  self.curRound = 0
  self.RoundStartRecord = 0
  self.serverRound = 0
  self.AIRound = 1
  self.vBattleField:Init(self.battleRuntimeData.battleStartParam.battleInitInfo)
  self:CheckEnvDepth()
end

function BattleManager:CheckEnvDepth()
  if self.IsOpenDepth and not BattleUtils.IsTeam() then
    self:OpenDepthCfg(0.25)
  end
end

function BattleManager:SetTurnPlayer(player)
  self.turnPlayer = player
end

function BattleManager:GetTurnPlayer()
  return self.turnPlayer
end

function BattleManager:PrepareBattle()
  if not self.isPrepareBattle then
    self.isPrepareBattle = true
    self.PrepareTable = {self}
    _G.BattleEventCenter:Bind(self, BattleEvent.PET_SPAWNED, BattleEvent.PLAYER_SPAWNED, BattleEvent.PET_LOAD_MODE_LOVER, BattleEvent.PLAYER_LOAD_MODEL_OVER)
    self.battlePawnManager:Init(self.vBattleField)
    local init_info = BattleUtils.GetBattleInitInfo()
    if not init_info then
      Log.Error("BattleManager:PrepareBattle \230\136\152\229\156\186\229\136\157\229\167\139\229\140\150\230\149\176\230\141\174\231\169\186\228\186\134  \232\175\183\230\143\144\228\186\164\231\187\153\231\168\139\229\186\143jinfuwang")
      return
    end
    self.battlePawnManager:SetBattleInitInfo(BattleUtils.GetBattleInitInfo(), self.PrepareTable)
    self:LoadOver(self)
    self.vBattleField.battleCraneCamera:SetTickEnable(true)
  end
  return true
end

function BattleManager:OnBattleEvent(eventName, ...)
  if eventName == BattleEvent.PET_SPAWNED then
    self:LoadOver(...)
    return true
  elseif eventName == BattleEvent.PLAYER_SPAWNED then
    self:LoadOver(...)
    return true
  elseif eventName == BattleEvent.PET_LOAD_MODE_LOVER then
    self:LoadPetModelOver(...)
    return true
  elseif eventName == BattleEvent.PLAYER_LOAD_MODEL_OVER then
    self:LoadPlayerModelOver(...)
    return true
  end
end

function BattleManager:LoadOver(object)
  if #self.PrepareTable > 0 then
    for i, v in ipairs(self.PrepareTable) do
      if v == object then
        table.remove(self.PrepareTable, i)
        break
      end
    end
    if 0 == #self.PrepareTable then
      self:PrepareBattleOver()
    end
  end
end

function BattleManager:LoadPlayerModelOver(battlePlayer)
  for i, v in ipairs(self.PrepareTable) do
    if v == battlePlayer then
      battlePlayer:HidePlayer(true)
      battlePlayer:SetWaterPlatformVisible(false)
    end
  end
end

function BattleManager:LoadPetModelOver(pet)
  for i, v in ipairs(self.PrepareTable) do
    if v == pet and pet.model then
      pet:SetWaterPlatformVisible(false)
    end
  end
end

function BattleManager:OnRoundChangePet()
  self.stateFsm:SetProperty("RoundStateVar", _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_PET)
  self.stateFsm:SetProperty("isBlowBuff", true)
  self.stateFsm:SendEvent(BattleEvent.EnterSelectRidPet)
end

function BattleManager:PrepareBattleOver()
  _G.BattleEventCenter:UnBind(self)
  if self.battleRuntimeData.battleType == ProtoEnum.BattleType.BT_LEADERFIGHT or self.battleRuntimeData.battleType == ProtoEnum.BattleType.BT_DUNGEONBOSS or self.battleRuntimeData.battleType == ProtoEnum.BattleType.BT_BOSS_CHALLENGE then
    if self.vBattleField.battleCameraManager then
      self.vBattleField.battleCameraManager:ChangeSettingsBoss()
    end
  elseif self.battleRuntimeData.battleType == ProtoEnum.BattleType.BT_WORLDLEADER then
    if self.vBattleField.battleCameraManager then
      self.vBattleField.battleCameraManager:ChangeSettingsWorldBoss()
    end
  elseif BattleUtils.IsTeam() then
    if self.vBattleField.battleCameraManager then
      self.vBattleField.battleCameraManager:ChangeSettingsTeam()
    end
  elseif self.vBattleField.battleCameraManager then
    self.vBattleField.battleCameraManager:ChangeSettingsNormal()
  end
  if self.vBattleField.battleCameraManager then
    self.vBattleField.battleCameraManager:CalcPos()
  end
  self.PrepareOver = true
  if BattleUtils.IsTeam() or BattleUtils.IsDeepWater() then
    self.vBattleField:RefreshWaterBattleReflection()
  end
  local fadeInfo = self.battleRuntimeData.fadeInfo
  if fadeInfo and fadeInfo.enableCameraFadeRule then
    fadeInfo.cameraFadeRuleId = self.battleFadeManager:ApplyFadeRule(BattleUtils.FadeBattlePawnRule)
  end
  _G.NRCModuleManager:DoCmd(PlayerModuleCmd.SetFadeSpeed, BattleConst.BattleFadeSpeed)
  _G.BattleEventCenter:Dispatch(BattleEvent.PrepareBattleOver)
end

function BattleManager:HidePawn()
  if _G.EnableSpeedUpEnterBloodTeamBattle and BattleUtils.IsBloodTeam() then
    return
  end
  for i, v in ipairs(self.battlePawnManager:GetAllTeam(BattleEnum.Team.ENUM_TEAM)) do
    if v.player and v.player.model then
      v.player:HidePlayer()
    end
    if #v.pets > 0 then
      for _, p in pairs(v.pets) do
        if p.model and p.card:IsInBattle() then
          p:HidePet()
        end
      end
    end
  end
  for i, v in ipairs(self.battlePawnManager:GetAllTeam(BattleEnum.Team.ENUM_ENEMY)) do
    if v.player and v.player.model then
      v.player:HidePlayer()
    end
    if #v.pets > 0 then
      for _, p in pairs(v.pets) do
        if p.model and p.card:IsInBattle() then
          p:HidePet()
        end
      end
    end
  end
end

BattleManager.PvpBgmList = {
  [1] = {
    [1] = "Battle;Battle;Battle_Type;Boss;Boss;PVP;Battle_Stage;Stage_1",
    [2] = "Battle;Battle;Battle_Type;Boss;Boss;PVP;Battle_Stage;Stage_2"
  },
  [2] = {
    [1] = "Battle;Battle;Battle_Type;Boss;Boss;PVP_rank;Battle_Stage;Stage_1",
    [2] = "Battle;Battle;Battle_Type;Boss;Boss;PVP_rank;Battle_Stage;Stage_2"
  },
  [3] = {
    [1] = "Battle;Battle;Battle_Type;Boss;Boss;PVP_03;Battle_Stage;Stage_1",
    [2] = "Battle;Battle;Battle_Type;Boss;Boss;PVP_03;Battle_Stage;Stage_2"
  }
}

function BattleManager:GetCurBattleBGM()
  if not self.curRandBgmStage or 0 == self.curRandBgmStage then
    self.curRandBgmStage = math.random(1, #BattleManager.PvpBgmList)
  end
  local stage = 1
  if self:IsPvpFinalHp() then
    stage = 2
  end
  local answer = BattleManager.PvpBgmList[self.curRandBgmStage][stage]
  if not _G.BattleManager.battleRuntimeData then
    return answer
  end
  if not _G.BattleManager.battleRuntimeData.battleConfig then
    return answer
  end
  local battleId = _G.BattleManager.battleRuntimeData.battleConfig.id
  local seasonMusicConf = PVPRankedMatchModuleUtils.GetMusicConfByBattleId(battleId)
  if not seasonMusicConf then
    return answer
  end
  if 1 == stage and seasonMusicConf.bgm_step1 then
    return seasonMusicConf.bgm_step1
  elseif 2 == stage and seasonMusicConf.bgm_step2 then
    return seasonMusicConf.bgm_step2
  end
  return answer
end

function BattleManager:IsPvpFinalHp()
  local MyPlayer = self.battlePawnManager:GetPlayerMyTeam()
  if not MyPlayer then
    return false
  end
  local EnemyPlayer = self.battlePawnManager:GetPlayerEnemyTeam()
  if not EnemyPlayer then
    return false
  end
  if 1 == MyPlayer.roleInfo.base.hp and 1 == EnemyPlayer.roleInfo.base.hp then
    return true
  end
  return false
end

function BattleManager:CheckBattleBGM()
  if BattleUtils.IsPvp() or BattleUtils.IsPvpRank() then
    if self:IsPvpFinalHp() then
      local stateName = self:GetCurBattleBGM()
      _G.NRCAudioManager:BatchSetState(stateName)
    end
  elseif BattleUtils.IsBadgeBossType() then
    local EnemyPlayer = self.battlePawnManager:GetPlayerEnemyTeam()
    if EnemyPlayer and 1 == EnemyPlayer.roleInfo.base.hp then
      local BattleState = "Battle;Battle;Battle_Type;Badge_Challenge;Badge_Challenge_Battle;Grass_Challenge_Battle_Boss;Battle_Stage;Stage_2"
      _G.NRCAudioManager:BatchSetState(BattleState)
    end
  end
end

function BattleManager:PlayBattleBGM()
  if BattleUtils.IsPvp() or BattleUtils.IsPvpRank() then
    local stateName = self:GetCurBattleBGM()
    _G.NRCAudioManager:BatchSetState(stateName)
  elseif BattleUtils.IsFinalBattleP1() then
    if _G.BattleManager.battleRuntimeData.battleStartParam:IsReconnect() then
      local BattleState = "Battle;Battle;Battle_Type;A1EndWar;Battle_Stage;Stage_1"
      _G.NRCAudioManager:BatchSetState(BattleState)
    end
  elseif BattleUtils.IsFinalBattleP2() then
    local player = self.battlePawnManager:GetPlayerMyTeam()
    if player then
      if player.deck:HasInBattleCards() then
        local BattleState = "Battle;Battle;Battle_Type;A1EndWar;Battle_Stage;Stage_2"
        _G.NRCAudioManager:BatchSetState(BattleState)
      else
        local BattleState = "Battle;Battle;Battle_Type;A1EndWar;Battle_Stage;Standby"
        _G.NRCAudioManager:BatchSetState(BattleState)
      end
    end
  elseif BattleUtils.IsB1FinalBattleP1() then
    if _G.BattleManager.battleRuntimeData.battleStartParam:IsReconnect() then
      local BattleState = "Battle;Battle;Battle_Type;B1EndWar;Battle_Stage;Stage_1"
      _G.NRCAudioManager:BatchSetState(BattleState)
    end
  elseif BattleUtils.IsB1FinalBattleP2() then
    local BattleState = "Battle;Battle;Battle_Type;B1EndWar;Battle_Stage;Stage_2"
    _G.NRCAudioManager:BatchSetState(BattleState)
  elseif BattleUtils.IsB1FinalBattleP3() then
    local BattleState = "Battle;Battle;Battle_Type;B1EndWar;Battle_Stage;Stage_3"
    _G.NRCAudioManager:BatchSetState(BattleState)
  elseif BattleUtils.IsBadgeBossType() then
    local BattleState = "Battle;Battle;Battle_Type;Badge_Challenge;Badge_Challenge_Battle;Grass_Challenge_Battle_Boss;Battle_Stage;Stage_1"
    local EnemyPlayer = self.battlePawnManager:GetPlayerEnemyTeam()
    if EnemyPlayer and 1 == EnemyPlayer.roleInfo.base.hp then
      BattleState = "Battle;Battle;Battle_Type;Badge_Challenge;Badge_Challenge_Battle;Grass_Challenge_Battle_Boss;Battle_Stage;Stage_2"
    end
    _G.NRCAudioManager:BatchSetState(BattleState)
  else
    local config = BattleUtils.GetBattleConfig()
    local BattleState = string.format("Battle;Battle;%s", config.bgm_battle_state or "Battle_Type;Scene")
    _G.NRCAudioManager:BatchSetState(BattleState)
  end
end

function BattleManager:StopBattleBGM()
  _G.NRCAudioManager:SetStateByName("Battle", "None")
end

function BattleManager.ResetComboInfo(caster, pos)
  for guid, info in ipairs(_G.BattleManager.ComboSkillInfo) do
    local pet = BattlePawnManager:GetPetByGuid(guid)
    if pet and pet.model == caster then
      info.X = pos.X
      info.Y = pos.Y
      info.Z = pos.Z
      break
    end
  end
end

function BattleManager.CheckPetIsExist()
  local PawnManager = _G.BattleManager.battlePawnManager
  local pets = PawnManager:GetPlayerTeamPets()
  if not pets or 0 == #pets then
    return false
  end
  pets = PawnManager:GetEnemyAllPets()
  if not pets or 0 == #pets then
    return false
  end
  return true
end

function BattleManager.TransBattleCamera(TransCameraType, blendTime, blendFunc)
  if not BattleManager.CheckPetIsExist() then
    return
  end
  if not _G.BattleManager then
    return
  end
  if not _G.BattleManager.vBattleField then
    return
  end
  local CraneCamera = _G.BattleManager.vBattleField.battleCraneCamera
  if CraneCamera then
    local IsBindCamera = false
    if 0 == blendTime then
      blendFunc = nil
    end
    if blendFunc and blendTime > 0 then
      IsBindCamera = true
    end
    if TransCameraType == UE.ESkillBattleTransCamera.PlayerCatch then
      CraneCamera:ChangeToPlayerCatch(blendTime, blendFunc, nil, nil, IsBindCamera)
    elseif TransCameraType == UE.ESkillBattleTransCamera.PlayerEscape then
      CraneCamera:ChangeToPlayerEscape(blendTime, blendFunc, nil, nil, IsBindCamera)
    elseif TransCameraType == UE.ESkillBattleTransCamera.PlayerItem then
      CraneCamera:ChangeToPlayerItem(blendTime, blendFunc, nil, nil, IsBindCamera)
    elseif TransCameraType == UE.ESkillBattleTransCamera.PlayerSkill then
      CraneCamera:ChangeToPlayerPet(blendTime, blendFunc, nil, nil, nil, IsBindCamera)
    elseif TransCameraType == UE.ESkillBattleTransCamera.SkillPlayer then
      CraneCamera:ChangeToPlayerSkill(blendTime, blendFunc, nil, nil, nil, IsBindCamera)
    elseif TransCameraType == UE.ESkillBattleTransCamera.SkillPlayerMulti then
      CraneCamera:ChangeToPlayerSkillMulti(blendTime, blendFunc, nil, nil, nil, IsBindCamera)
    else
      CraneCamera:ChangeToPlayerPet(blendTime, blendFunc, nil, nil, nil, IsBindCamera)
    end
  end
end

function BattleManager.TransNewBattleCamera(TransCameraType, blendTime, blendFunc)
  if not BattleManager.CheckPetIsExist() then
    return
  end
  if not _G.BattleManager then
    return
  end
  if not _G.BattleManager.vBattleField then
    return
  end
  local CraneCamera = _G.BattleManager.vBattleField.battleCraneCamera
  if CraneCamera then
    local IsBindCamera = false
    if blendFunc and blendTime > 0 then
      IsBindCamera = true
    end
    if TransCameraType == UE4.EBattleCameraTags.PlayerCatch then
      CraneCamera:ChangeToPlayerCatch(blendTime, blendFunc, nil, nil, IsBindCamera)
    elseif TransCameraType == UE4.EBattleCameraTags.PlayerEscape then
      CraneCamera:ChangeToPlayerEscape(blendTime, blendFunc, nil, nil, IsBindCamera)
    elseif TransCameraType == UE4.EBattleCameraTags.PlayerItemToTeam then
      CraneCamera:ChangeToPlayerItem(blendTime, blendFunc, nil, nil, IsBindCamera)
    elseif TransCameraType == UE4.EBattleCameraTags.PlayerPet or TransCameraType == UE.EBattleCameraTags.A1FBSSelectSkillP2_Pet1 then
      CraneCamera:ChangeToPlayerPet(blendTime, blendFunc, nil, nil, nil, IsBindCamera)
    elseif TransCameraType == UE.ESkillBattleTransCamera.PlayerSkill or TransCameraType == UE.EBattleCameraTags.A1FBPerformSkillP2 then
      CraneCamera:ChangeToPlayerSkill(blendTime, blendFunc, nil, nil, nil, IsBindCamera)
    elseif TransCameraType == UE.ESkillBattleTransCamera.PlayerSkillMult then
      CraneCamera:ChangeToPlayerSkillMulti(blendTime, blendFunc, nil, nil, nil, IsBindCamera)
    else
      CraneCamera:ChangeToPlayerPet(blendTime, blendFunc, nil, nil, nil, IsBindCamera)
    end
  end
end

function BattleManager:IsBattleTypeAdaptEnterSky()
  return self.battleRuntimeData:GetEnterBattleType() == ProtoEnum.BattleEnterType.BET_CONTACT or self.battleRuntimeData:GetEnterBattleType() == ProtoEnum.BattleEnterType.BET_THROW or BattleUtils.IsTeam()
end

function BattleManager:ModifySceneSpotLight(isShow)
  if BattleUtils.IsFinalBattle() then
    local localPlayer = _G.NRCModuleManager:DoCmd(_G.PlayerModuleCmd.GET_LOCAL_PLAYER)
    if not localPlayer then
      return
    end
    local SpotLightActor = localPlayer.viewObj.SpotLightActor
    if SpotLightActor then
      SpotLightActor.bNumb = isShow
    end
    local LightsArray = UE4.UGameplayStatics.GetAllActorsOfClassWithTag(localPlayer.viewObj, UE4.AEnvSpotLightActor, "SceneLight")
    local Lights = LightsArray and LightsArray:ToTable()
    if Lights and #Lights > 0 then
      Lights[1]:SetActorHiddenInGame(not isShow)
    end
    Log.Debug("BattleManager:ModifySceneSpotLight", isShow)
  end
end

function BattleManager:GetTssSdkCoreDataAndReportDefault()
  _G.NRCSDKManager:GetTssSdkCoreDataAndReport(NRCSDKManagerEnum.AntiCheatSendType.Default, self.battleRuntimeData:GetBattleID())
end

function BattleManager:AddReportData2Timer()
  if not self.LoopTssReportTimer then
    Log.Debug("[BattleManager:AddReportData2Timer] Add timer2")
    self.LoopTssReportTimer = _G.TimerManager:CreateTimer(self, "GetTssSdkCoreDataAndReportDefault", math.maxinteger, self.GetTssSdkCoreDataAndReportDefault, nil, 60)
  end
end

function BattleManager:RemoveReportData2Timer()
  if self.LoopTssReportTimer then
    Log.Debug("[BattleManager:RemoveReportData2Timer] Remove timer2")
    _G.TimerManager:RemoveTimer(self.LoopTssReportTimer)
    self.LoopTssReportTimer = nil
  end
end

function BattleManager:ClearBattleFsmCache()
  local function ClearProperty(fsmObj)
    local properties = fsmObj.properties
    
    if properties then
      for name, actor in pairs(properties) do
        if UE.UObject.IsValid(actor) and actor.IsA and actor:IsA(UE4.AActor) then
          actor:K2_DestroyActor()
        end
      end
    end
  end
  
  local function ClearFsm(fsm)
    if fsm then
      if fsm.states then
        for i = 1, #fsm.states do
          local state = fsm.states[i]
          if state and state.actions then
            for j = 1, #state.actions do
              local action = state.actions[j]
              if action then
                ClearProperty(action)
              end
            end
            ClearProperty(state)
          end
        end
      end
      ClearProperty(fsm)
    end
  end
  
  ClearFsm(self.stateFsm)
  ClearFsm(self.instantFsm)
  ClearFsm(self.teamBattlePerformFsm)
end

function BattleManager:EnterBattle()
  self.isPrepareBattle = false
  self:StopFocusTimer()
  BattleBudget:EnterBattle()
  NRCModuleManager:DoCmd(BattleUIModuleCmd.ClearWidgetDict)
  self.CmdSyncNotifys = {}
  local localPlayer = _G.NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  self.EnterBattleStateBit = BattleUtils.GetCurrentPlayerEnterSate()
  if localPlayer:IsInTogetherMove() then
    if localPlayer.viewObj then
      local rideComp = localPlayer.viewObj.BP_RideComponent
      if rideComp then
        rideComp:TryChangeToLink()
        localPlayer:StopRide(true, nil)
      end
    end
  elseif 0 == self.EnterBattleStateBit & BattleEnum.EnterBattleState.InSky and not BattleUtils.IsSpecialNoPc() and localPlayer.viewObj then
    local rideComp = localPlayer.viewObj.BP_RideComponent
    if rideComp then
      localPlayer:StopRide(true, nil)
    end
  end
  localPlayer:ForceSendMoveReq(false, nil)
  _G.NRCSDKManager:GetTssSdkCoreDataAndReport(NRCSDKManagerEnum.AntiCheatSendType.EnterBattle, self.battleRuntimeData:GetBattleID())
  self:AddReportData2Timer()
  NRCModuleManager:DoCmd(FunctionBanModuleCmd.AddCondition, Enum.PlayerConditionType.PCT_BATTLE)
  local battleRuntimeData = self.battleRuntimeData
  if BattleUtils.IsWatchingBroadcastBattle(battleRuntimeData) then
    NRCModuleManager:DoCmd(FunctionBanModuleCmd.AddCondition, Enum.PlayerConditionType.PCT_NPC_SHOWDOWN_WATCHING)
  end
  NRCModeManager:DoCmd(BattleUIModuleCmd.CloseAIVisible)
  self:ModifySceneSpotLight(true)
  NRCModeManager:DoCmd(PlayerModuleCmd.CLOSE_LOCAL_PLAYER_Collision, true)
  NRCEventCenter:RegisterEvent("BattleManager", self, SceneEvent.BigWorldPrepared, self.OnWorldPrepared)
  self.battleObjectManager:EnterBattle()
  if false then
    Log.Error("using new battle fsm")
    local BattleFsmInitRouter = require("NewRoco.Modules.Core.Battle.Fsm.BattleFsmInitRouter")
    self.fsmRouter = BattleFsmInitRouter()
    self.fsmRouter:InitBattleFsmByType()
    self.stateFsm = self.fsmRouter:GetFsm()
    BattleProfiler:RegisterFsm(self.stateFsm)
  else
    self.stateFsm = BattleFsm()
    BattleProfiler:RegisterFsm(self.stateFsm)
    self.stateFsm:Play()
  end
  self.IsReadyForExit = false
  self.IsShowAppearanceAtStart = nil
  _G.NRCModuleManager:DoCmd(PlayerModuleCmd.PlayerEnterBattle, localPlayer)
  _G.NRCModeManager:DoCmd(EnvSystemModuleCmd.OnEnterBattle)
  _G.NRCModeManager:DoCmd(MarkerModuleCmd.EnterBattle)
  _G.NRCModeManager:DoCmd(_G.NPCModuleCmd.RecycleAllThrowPets, _G.ProtoEnum.RecycleThrowPetReason.RTPR_Battle)
  _G.NRCEventCenter:DispatchEvent(TaskModuleEvent.BattleStart)
  _G.NRCModeManager:DoCmd(_G.WorldCombatModuleCmd.SetInBattle, true, self.battleRuntimeData.NpcIDs)
  NRCModuleManager:DoCmd(PlayerModuleCmd.LockTeleport, TeleportLockEnum.LockType.BATTLE)
  BattleUtils.ToggleInput(false)
  BattleUtils.ToggleMove(false)
  self.isPureLogicMode = false
  self.isClear = false
  self.isSendWaiting = false
  self.isInBattle = true
  self.ShouldWaitGlobalLoading = false
  self.PrepareOver = false
  self.IsRevertPawnPos = false
  if not self.battleRuntimeData:IsBattleAgain() then
    self.TeleportBackPos = nil
  end
  self.AIHistoryInfo = {}
  self.TeamBattleNotifyQueue = {}
  self.IsMeetNewPet = false
  self.IsTeamBossToCatch = false
  self.bDirectUpdateUI = false
  if _G.UpdateManager then
    _G.UpdateManager:Register(self)
  end
  _G.NRCModuleManager:DoCmd(MainUIModuleCmd.CloseCompass, false)
  self.performNodeRef = {}
  WeakTable(self.performNodeRef)
  if BattleUtils.IsFinalBattleP1() then
    UE4.UNRCStatics.FreezeWorldCompositionForLua(1)
  end
  if BattleUtils.IsTeam() then
    UE.UNRCStatics.ExecConsoleCommand("r.AllowOcclusionQueries 0")
  end
  BattleLevelHelper:OnEnterBattle()
  NRCEventCenter:RegisterEvent("BattleManager", self, NRCGlobalEvent.OnApplicationWillEnterBackground, self.OnApplicationWillEnterBackground)
  NRCEventCenter:RegisterEvent("BattleManager", self, NRCGlobalEvent.OnApplicationHasEnteredForeground, self.OnApplicationHasEnteredForeground)
  UE4.UNRCStatics.CloseAdaptiveAdjust()
end

function BattleManager:OnApplicationWillEnterBackground()
  Log.Debug("BattleManager:OnApplicationWillEnterBackground")
  self.enterBackgroundTime = os.msTime()
  if self.turnPlayer then
    self.turnPlayer.performPlayer.IsStopTickTimeout = true
  end
end

function BattleManager:OnApplicationHasEnteredForeground()
  Log.Debug("BattleManager:OnApplicationHasEnteredForeground")
  self.enterForegroundTime = os.msTime()
  if self.turnPlayer then
    self.turnPlayer.performPlayer.IsStopTickTimeout = false
  end
end

function BattleManager:ClearBattle()
  self:LeaveBattle()
  self:AfterBattleOver()
end

function BattleManager:PreLeaveBattle()
end

function BattleManager:OpenTaskBlackScreen()
  if not BattleUtils.ContainTaskPerformControl(Enum.TaskBattlePerformanceControl.TBPC_EXIT_BLACK) then
    return
  end
  local PotentialTaskID = self.battleRuntimeData:GetPotentialTaskID()
  Log.Debug("BattleManager:OpenTaskBlackScreen2", PotentialTaskID)
  if not PotentialTaskID then
    return
  end
  self.ShouldWaitGlobalLoading = true
  local hasBattleLoading = BattleUtils.HasBattleLoading()
  local bBattleResultConditionMeet = true
  local TaskConfig = _G.DataConfigManager:GetTaskConf(PotentialTaskID, true)
  if TaskConfig and #TaskConfig.task_condition > 0 then
    local condition = TaskConfig.task_condition[1]
    if condition and condition.type == Enum.TaskKeyType.TKT_STATE_OPTION then
      for _, option_id in ipairs(condition.data1) do
        local OptionConf = _G.DataConfigManager:GetNpcOptionConf(option_id)
        if OptionConf and OptionConf.action.action_type == Enum.ActionType.ACT_BATTLE then
          local BattleID = tonumber(OptionConf.action.action_param2)
          if self.battleRuntimeData and self.battleRuntimeData.battleConfig and BattleID == self.battleRuntimeData.battleConfig.id and 1 == tonumber(OptionConf.action.action_param5) and (not self.battleRuntimeData.battleSettleData or not self.battleRuntimeData.battleSettleData:BattleIsWin()) then
            bBattleResultConditionMeet = false
          end
        end
      end
    end
  end
  Log.Debug("BattleManager:OpenTaskBlackScreen3", PotentialTaskID, bBattleResultConditionMeet)
  if bBattleResultConditionMeet then
    _G.NRCModuleManager:DoCmd(BlackScreenModuleCmd.OpenGlobalBlackScreenIfNeed, PotentialTaskID, not hasBattleLoading)
  end
end

function BattleManager:LeaveBattle()
  if not _G.DisableSpeedUpBattleLoad then
    UE4.UNRCStatics.ExecConsoleCommand("s.HeavyToRenderThreadPostLoadMask 7")
    UE4.UNRCStatics.ChangeLevelStreamingMode(0)
  end
  NRCModuleManager:DoCmd(PlayerModuleCmd.UnLockTeleport, TeleportLockEnum.LockType.BATTLE)
  _G.NRCModuleManager:DoCmd(_G.PlayerModuleCmd.ReloadAvatar, PlayerModuleCmd.AvatarUnloadReason.Battle)
  self:OpenTaskBlackScreen()
  self.isPreloadResWithoutWaiting = false
  self.isEnterActionWaitResDone = true
  self.IsShowAppearanceAtStart = nil
  self:ClearProperty()
  BattleProfiler:LeaveBattle()
  _G.BlockRoundStartNotify = false
  self:ClearBattleFsmCache()
  if BattleUtils.IsReplayMode() then
    BattleReplayCachePool:ClearCache()
  end
  Log.Debug("--------------  BattleManager LeaveBattle Start")
  _G.NRCSDKManager:GetTssSdkCoreDataAndReport(NRCSDKManagerEnum.AntiCheatSendType.LeaveBattle, self.battleRuntimeData:GetBattleID())
  self:RemoveReportData2Timer()
  _G.NRCModuleManager:DoCmd(_G.BattleTutorialGuideModuleCmd.ClearGuide)
  if BattleUtils.IsB1FinalBattle() then
    _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.SetB1P3FirstRoundGuideState, nil)
  end
  if BattleUtils.IsB1FinalBattleP3() then
    _G.NRCModuleManager:DoCmd(_G.B1FinalBattleModuleCmd.CloseTwoScreenDialogue)
    _G.NRCModuleManager:DoCmd(_G.B1FinalBattleModuleCmd.ClearDialogueCamera)
  end
  if BattleUtils.IsFinalBattle() then
    UE4.UNRCStatics.FreezeWorldCompositionForLua(0)
    if _G.NRCModuleManager:DoCmd(_G.DialogueModuleCmd.HasDialogue) then
      _G.NRCModuleManager:DoCmd(_G.DialogueModuleCmd.CloseDialogueInBattle)
    end
  end
  self:ModifySceneSpotLight(false)
  if not self.isInBattle then
    Log.Error("[#error:E001]zgx call LeaveBattle, but isInBattle is false")
    return
  end
  BattleReplayCachePool:BattleExit()
  BattleReplayCachePool:StopRecordBattle()
  NRCEventCenter:UnRegisterEvent(self, NRCGlobalEvent.OnApplicationWillEnterBackground, self.OnApplicationWillEnterBackground)
  NRCEventCenter:UnRegisterEvent(self, NRCGlobalEvent.OnApplicationHasEnteredForeground, self.OnApplicationHasEnteredForeground)
  self.CmdSyncNotifys = {}
  self.isInBattle = false
  self.IsReadyForExit = false
  self.IsRevertPawnPos = false
  self.EnterSleepAnim = nil
  self.CheerPetsWorldInfo = {}
  self.ComboSkillInfo = {}
  self.TeamBattleNotifyQueue = {}
  self.CurTeamBattlePerformNotify = nil
  self.LastSequencePerformNotify = nil
  self.curRandBgmStage = nil
  self.bDirectUpdateUI = false
  self.SelectTargetManager:Clear()
  self.Target = BattleUtils.GetTraceNpc()
  if self.Target then
    self.Target.npc:LeaveBattle()
  end
  self.Target = nil
  UE4.USkillRecordLibrary.ReleaseAllSkill()
  self:StopBattleBGM()
  self:CloseDepthCfg()
  _G.BattleBulletTimeManager:ClearAll()
  local npcInfos = self.battleRuntimeData:GetAllNPCs()
  if npcInfos then
    for _, npcInfo in ipairs(npcInfos) do
      local npc = npcInfo.npc
      if npc then
        npc:SetVisibleForBattleReason(true)
        if npc.AIComponent then
          npc.AIComponent:UnlockForBattleReason()
        end
      end
    end
  else
    Log.Debug("BattleManager:LeaveBattle Can't Restore TraceNPC")
  end
  if not BattleUtils.IsPve() or not BattleUtils.IsBattleWin(self.battleRuntimeData.battleExitParam:GetLastTurnSettleResult()) then
    BattleUtils.FocusPlayer()
  end
  if BattleUtils.IsWorldLeaderFight() then
    local battle_tag = ProtoMessage:newSpaceActionTag_Battle()
    battle_tag.battle_id = self.battleRuntimeData.battle_id
    NRCModuleManager:DoCmd(SceneModuleCmd.ConsumeCachedBattleTag, battle_tag)
    _G.NRCModuleManager:DoCmd(MainUIModuleCmd.UpdateEquipMagicItemInfo, true)
  end
  if _G.UpdateManager then
    _G.UpdateManager:UnRegister(self)
  end
  if self.instantFsm then
    self.instantFsm:Stop()
    self.instantFsm = nil
  end
  if self.teamBattlePerformFsm then
    self.teamBattlePerformFsm:Stop()
    self.teamBattlePerformFsm = nil
  end
  if self.CacheSequencer then
    self.CacheSequencer:Stop()
    self.CacheSequencer = nil
  end
  UE4.UNRCStatics.ClearBulletTimePool()
  BattleSkillManager:ReleaseAllRequest()
  BattleSkillManager:ClearCache()
  BattleSkillManager:ClearLocalPlayerSkill()
  BattleBudget:PushTask(nil, function()
    self.battleFadeManager:LeaveBattle()
    self.vBattleField:LeaveBattle()
    self.battleObjectManager:LeaveBattle()
    self:RemoveAllListeners()
    self.isClear = true
    NRCModeManager:DoCmd(PlayerModuleCmd.HIDE_ALL, false)
    _G.NRCModuleManager:DoCmd(_G.EnvSystemModuleCmd.LockWeather, Enum.WeatherType.WT_NONE, LockWeatherReason.Battle)
  end)
  self.battlePawnManager:LeaveBattleDelay()
  BattleBudget:PushTask(nil, function()
    _G.BattlePlayerPool:Clear()
  end)
  self.battleRuntimeData.ServerBattlePos = nil
  if self.turnPlayer then
    self.turnPlayer:DestroyPerformPlayer()
    self.turnPlayer:ClearData()
    self.turnPlayer = nil
  end
  BattleUtils.GetBattleUIModule().data:ClearProcessCmd()
  self.EscapeContext:SetCallback(nil, nil)
  BattleBudget:PushTask(nil, function()
    self.battleResourceManager:UnLoadPreloadAsset()
    self.battleResourceManager:UnLoadAssetByType(BattleResourceManager.UnloadType.END_GAME)
    self.battleResourceManager:UnLoadAssetByType(BattleResourceManager.UnloadType.TIME)
    self.battleResourceManager:ReleaseAllCastSkillObject()
    self.battleResourceManager:ClearUClass()
    self.battleResourceManager:ClearRequestPool()
    self.battlePawnManager:ClearRequestDict()
  end)
  UE4Helper.SetEnableWorldRendering(nil)
  BattleUtils.ToggleInput(true)
  NRCModeManager:DoCmd(MarkerModuleCmd.LeaveBattle)
  NRCModeManager:DoCmd(BattleUIModuleCmd.WaitingRecycleMain)
  BattleBudget:PushTask(nil, function()
    NRCModeManager:DoCmd(BattleUIModuleCmd.CloseMainSubPanel)
  end)
  BattleBudget:PushTask(nil, function()
    NRCModeManager:DoCmd(BattleUIModuleCmd.CloseMain)
  end)
  NRCModeManager:DoCmd(BattleUIModuleCmd.CloseBattleUIBackpackTips)
  NRCModeManager:DoCmd(BattleUIModuleCmd.OpenPetCatchPanel, false)
  NRCModeManager:DoCmd(BattleUIModuleCmd.OpenGetItemsPanel, false)
  NRCModeManager:DoCmd(BattleUIModuleCmd.ClosePVPValueNumberPanel)
  NRCModeManager:DoCmd(BattleUIModuleCmd.CloseBattleBloodPulse)
  _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.CloseAllBattleChatRelatedUI, true)
  NRCModuleManager:DoCmd(BagModuleCmd.ClearBattleInfo)
  NRCModeManager:DoCmd(PlayerModuleCmd.CLOSE_LOCAL_PLAYER_Collision, false)
  NRCModeManager:DoCmd(_G.WorldCombatModuleCmd.SetInBattle, false, self.battleRuntimeData.NpcIDs)
  _G.NRCModeManager:DoCmd(TipsModuleCmd.Tips_CloseItemTips)
  _G.NRCModeManager:DoCmd(BattleUIModuleCmd.HideBattlePopupPanel)
  _G.NRCModeManager:DoCmd(BattleUIModuleCmd.CloseSkillTips)
  _G.NRCModeManager:DoCmd(BattleUIModuleCmd.CloseRoleHpCriticalTipPanel)
  _G.NRCModuleManager:DoCmdAsync(nil, BattleUIModuleCmd.CloseRoleHpDefeatedTipPanel)
  if not _G.NRCModuleManager:DoCmd(DialogueModuleCmd.HasDialogue) then
    NRCModeManager:GetCurMode():RevertPanelEnableStateByLayer(_G.Enum.UILayerType.UI_LAYER_MAIN)
  end
  NRCModeManager:GetCurMode():RevertPanelEnableStateByLayer(_G.Enum.UILayerType.UI_LAYER_DIALOGUE)
  NRCModeManager:GetCurMode():RevertPanelEnableStateByLayer(_G.Enum.UILayerType.UI_LAYER_TOP)
  NRCModeManager:GetCurMode():RevertPanelEnableStateByLayer(_G.Enum.UILayerType.UI_LAYER_FULLSCREEN)
  NRCModeManager:DoCmd(MainUIModuleCmd.TryOpenMainPanel)
  if BattleUtils.IsTrainBattle() and _G.BattleManager.battleRuntimeData and _G.BattleManager.battleRuntimeData.battleConfig then
    local battleId = _G.BattleManager.battleRuntimeData.battleConfig.id
    _G.NRCModeManager:DoCmd(BattleUIModuleCmd.SetTeachBattleId, battleId)
  end
  BattleBudget:PushDelayTask(nil, function()
    NRCModeManager:DoCmd(NPCModuleCmd.LeaveBattle)
  end)
  BattleBudget:PushDelayTask(nil, function()
    NRCModuleManager:DoCmd(FunctionBanModuleCmd.RemoveCondition, Enum.PlayerConditionType.PCT_BATTLE)
    NRCModuleManager:DoCmd(FunctionBanModuleCmd.RemoveCondition, Enum.PlayerConditionType.PCT_NPC_SHOWDOWN_WATCHING)
    _G.NRCEventCenter:DispatchEvent(BattleEvent.FunctionBanRemoveBattleType)
  end)
  local localPlayer = _G.NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  if localPlayer and localPlayer.viewObj then
    SkillUtils.ClearSkillObj(localPlayer.viewObj.RocoSkill)
  end
  _G.NRCModuleManager:DoCmd(PlayerModuleCmd.PlayerLeftBattle, localPlayer)
  NRCModuleManager:DoCmd(BattleUIModuleCmd.ClearWidgetDict)
  NRCModeManager:DoCmd(BattleUIModuleCmd.CloseAIVisible)
  local settleData = self.battleRuntimeData.battleSettleData
  local data
  if settleData and settleData.data and settleData.data.settle_info then
    data = settleData.data.settle_info
  end
  NRCEventCenter:DispatchEvent(TaskModuleEvent.BattleOver, data)
  NRCModeManager:DoCmd(EnvSystemModuleCmd.OnLeaveBattle)
  NRCEventCenter:UnRegisterEvent(self, SceneEvent.BigWorldPrepared, self.OnWorldPrepared)
  if BattleUtils.IsTeam() then
    NRCModuleManager:DoCmd(_G.TeamBattleModuleCmd.OnBattleEnd)
    NRCModuleManager:DoCmd(_G.LegendaryBattleModuleCmd.OnBattleEnd)
    UE.UNRCStatics.ExecConsoleCommand("r.AllowOcclusionQueries 1")
  end
  BattleLog:OnExitBattle()
  _G.NRCModuleManager:DoCmd(_G.LevelSelectionModuleCmd.BattleFinishedOpenLeveBattleSilhouette)
  local fadeInfo = self.battleRuntimeData.fadeInfo
  if fadeInfo and fadeInfo.cameraFadeRuleId then
    self.battleFadeManager:RemoveFadeRule(fadeInfo.cameraFadeRuleId)
  end
  BattleBudget:PushTask(nil, function()
    BattleUtils.RecoveryRideStatus(self.battleRuntimeData.battleSettleData:GetRideId())
    self.battleRuntimeData:Clear()
    self.battleInfoManager:Clear()
  end)
  BattleEventCenter:UnbindAll()
  NRCEventCenter:DispatchEvent(BattleEvent.LeaveBattle)
  BattleNetManager:Clear()
  BattleBudget:PushTask(nil, function()
    UE4.UNRCStatics.ReleaseUnuseSlateRenderResource()
  end)
  BattleBudget:PushDelayTask(nil, function()
    BattleBudget:GC(false)
  end)
  Log.Debug("--------------  BattleManager LeaveBattle End")
  BattleBudget:LeaveBattle()
  UE4.UNRCStatics.EnableAdaptiveAdjust()
end

function BattleManager:SendBattleFinish(isForce)
  if self.battleRuntimeData.battleSettleData.IsReceiveFinish or isForce then
    _G.BattleNetManager:SendBattlePlayerExitReq()
  end
end

function BattleManager:AfterBattleOver(isForce)
  _G.IsEnterBattleByDebug = nil
  if self.stateFsm then
    self.stateFsm:Stop()
    self.stateFsm = nil
  end
  NRCModuleManager:DoCmdAsync({}, BattleUIModuleCmd.CloseLoading)
  NRCModeManager:DoCmd(BattleUIModuleCmd.CloseTransformLoadingUI)
  _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.CloseSkipTheCutscene, true)
  if not self:IsBattleAgainPending() then
    self.TeleportBackPos = nil
    self.EnvActorZ = nil
    BattleUtils.ToggleMove(true)
    self:SendBattleFinish(isForce)
  end
  _G.ZoneServer:Resume("Battle")
  NRCEventCenter:DispatchEvent(BattleEvent.BattleOver)
  if not _G.NRCModuleManager:DoCmd(DialogueModuleCmd.HasDialogue) then
    NRCModeManager:GetCurMode():RevertPanelEnableStateByLayer(_G.Enum.UILayerType.UI_LAYER_MAIN)
  end
end

function BattleManager:OpenBattleEnterWindow()
  NRCModuleManager:DoCmd(BattleUIModuleCmd.OpenEnter)
end

function BattleManager:CloseBattleEnterWindow()
  NRCModuleManager:DoCmd(BattleUIModuleCmd.CloseEnter)
end

function BattleManager:OpenBattleMainWindow()
  NRCModuleManager:DoCmd(BattleUIModuleCmd.OpenMain)
end

function BattleManager:CloseBattleMainWindow()
  NRCModuleManager:DoCmd(BattleUIModuleCmd.CloseMain)
end

function BattleManager:OpenBattleAdditionalTarget()
  local taskInfo = _G.BattleManager.battleRuntimeData:GetBattleTaskInfo()
  local NpcChallengeInfo = self:GetBattleNpcChallengeInfo()
  if taskInfo then
    _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.OpenBattleAdditionalTarget, taskInfo, NpcChallengeInfo)
  end
end

function BattleManager:GetBattleBuffId()
  local npcChallengeInfo = self.battleRuntimeData:GetBattleNpcChallengeInfo()
  local buffId = npcChallengeInfo and npcChallengeInfo.buff_id or nil
  if not buffId or 0 == buffId then
    return nil
  end
  return buffId
end

function BattleManager:HideBattleAdditionalTarget()
  _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.HideBattleAdditionalTarget)
end

function BattleManager:CloseBattleAdditionalTarget()
  _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.CloseBattleAdditionalTarget)
end

function BattleManager:ShutDown()
  Log.Debug("BattleManger:ShutDown!!!")
  self.battleNetManager:ShutDown()
  if not self.isClear then
    self:ClearBattle()
  end
end

function BattleManager:OnTick(deltaTime)
  if self.isInBattle then
    self.battleObjectManager:OnTick(deltaTime)
    self.battleResourceManager:OnTick(deltaTime)
    self.battleFadeManager:OnTick(deltaTime)
    if self.bDirectUpdateUI then
      self.bDirectUpdateUI = false
      local ignoreOptions = self.directUpdateUIIgnoreOptions
      self.directUpdateUIIgnoreOptions = nil
      _G.BattleEventCenter:Dispatch(BattleEvent.DIRECT_UPDATE_UI, ignoreOptions)
    end
  end
end

function BattleManager:AddListeners()
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_ENTER_NOTIFY, self.OnEnterBattleNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_PRE_PLAY_NOTIFY, self.OnBattlePrePlayNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_ROUND_START_NOTIFY, self.OnBattleRoundStartNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_INSTANT_PERFORM_NOTIFY, self.OnBattleInstantPerformNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_CMD_SYNC_NOTIFY, self.OnBattleCmdSyncNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_PERFORM_START_NOTIFY, self.OnBattlePerformNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_ROLE_LEAVE_NOTIFY, self.OnBattlePlayerLeaveNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_FINISH_NOTIFY, self.OnBattleFinishNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_AI_SELECT_SKILL_NOTIFY, self.OnBattleAISelectSkillNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_EMOJI_NOTIFY, self.OnBattleEmojiNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_PK_AGAIN_NOTIFY, self.OnBattlePKAgainNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_FORCE_FINISH_NOTIFY, self.OnBattleForceFinishNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_PVP_PERFORM_START_NOTIFY, self.OnBattlePvpPerformStartNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_OBSERVER_CHANGE_NOTIFY, self.OnBattleObserverChangeNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_OBSERVER_KICKED_OUT_NOTIFY, self.OnBattleObserverKickedOutNotify)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_LIVE_DANMU_NTY, self.OnBattleLiveDanmuNty)
  self.battleNetManager:AddEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_ACTIVITY_SHOW_DOWN_CHANGE_NOTIFY, self.OnActivityShowDownChangeNotify)
  NRCEventCenter:RegisterEvent("BattleManager", self, SceneEvent.PlayerTeleportFinish, self.OnPlayerTeleportFinish)
end

function BattleManager:OnPlayerTeleportFinish()
  self.playerTeleportFinished = true
end

function BattleManager:RemoveListeners()
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_ENTER_NOTIFY, self.OnEnterBattleNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_PRE_PLAY_NOTIFY, self.OnBattlePrePlayNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_INSTANT_PERFORM_NOTIFY, self.OnBattleInstantPerformNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_CMD_SYNC_NOTIFY, self.OnBattleCmdSyncNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_ROUND_START_NOTIFY, self.OnBattleRoundStartNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_PERFORM_START_NOTIFY, self.OnBattlePerformNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_ROLE_LEAVE_NOTIFY, self.OnBattlePlayerLeaveNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_FINISH_NOTIFY, self.OnBattleFinishNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_AI_SELECT_SKILL_NOTIFY, self.OnBattleAISelectSkillNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_EMOJI_NOTIFY, self.OnBattleEmojiNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_PVP_PERFORM_START_NOTIFY, self.OnBattlePvpPerformStartNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_OBSERVER_CHANGE_NOTIFY, self.OnBattleObserverChangeNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_OBSERVER_KICKED_OUT_NOTIFY, self.OnBattleObserverKickedOutNotify)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_LIVE_DANMU_NTY, self.OnBattleLiveDanmuNty)
  self.battleNetManager:RemoveEventListener(self, ProtoCMD.ZoneSvrCmd.ZONE_ACTIVITY_SHOW_DOWN_CHANGE_NOTIFY, self.OnActivityShowDownChangeNotify)
end

function BattleManager:SetBeastSkipWaitLoad(value)
  self.isTeamSkipWaitLoad = value
end

function BattleManager:OnSkipWaitLoadNotify(notify)
  if self.isTeamSkipWaitLoad then
    return
  end
  if notify and notify.skip_uin ~= _G.DataModelMgr.PlayerDataModel:GetPlayerUin() then
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, LuaText.challenge_again_teammate_skip)
  end
  self:SetBeastSkipWaitLoad(true)
  _G.BattleEventCenter:Dispatch(BattleEvent.SkipWaitLoad, notify)
  NRCModuleManager:DoCmd(BattleUIModuleCmd.OpenSkipTheCutscene)
end

function BattleManager:SetIsBattleAgainPending(v)
  self._isBattleAgainPending = v and true or false
end

function BattleManager:ConsumeIsBattleAgainPending()
  local v = self._isBattleAgainPending or false
  self._isBattleAgainPending = false
  return v
end

function BattleManager:IsBattleAgainPending()
  return self._isBattleAgainPending
end

function BattleManager:OnEnterBattleNotify(notify)
  Log.Msg("BattleProfiler:OnEnterBattleNotify \230\148\182\229\136\176\232\191\155\229\133\165\230\136\152\230\150\151\229\155\158\229\140\133")
  BattleBudget:ProcessAll()
  local isBattleAgain = self:ConsumeIsBattleAgainPending()
  self:SetSeqNumber(notify.data_seq_num)
  self.isPreloadResWithoutWaiting = false
  self.isEnterActionWaitResDone = true
  self.isSkipEnterAction = false
  self.isTeamSkipWaitLoad = isBattleAgain
  self.EnterBattleStateBit = BattleEnum.EnterBattleState.Default
  BattleUtils.UnLockCam()
  BattleProfiler:CheckPoint(BattleProfilerCheckPoint.BattleEnterNotify)
  LoadingProfiler:CheckPoint(LoadingProfilerCheckPoint.Battle_StartBattle)
  if not _G.DisableSpeedUpBattleLoad then
    UE4.UNRCStatics.ChangeLevelStreamingMode(1)
    UE4.UNRCStatics.ExecConsoleCommand("s.HeavyToRenderThreadPostLoadMask 0")
  end
  self:SetPlayerDataModelBattleState(1)
  BattleExitHelper:ResetData()
  self.SelectTargetManager:Clear()
  self.battleRuntimeData:SetBattleID(notify.init_info.battle_id)
  self.battleRuntimeData.battleType = notify.battle_mode
  self.battleRuntimeData.battleSettleData.IsReceiveFinish = false
  self.battleRuntimeData.IsCatchSuccessInBloodTeam = false
  self.battleRuntimeData:SetEnterBattleType(notify.enter_battle_type)
  self.battleRuntimeData:SetBattleNpcChallengeInfo(notify.init_info.pve_info)
  if notify.init_info.pve_info and notify.init_info.pve_info.guide_id then
    _G.NRCModuleManager:DoCmd(_G.BattleTutorialGuideModuleCmd.ClearGuide)
    _G.NRCEventCenter:DispatchEvent(BattleTutorialGuideModuleEvent.EnterBattleTutorialGuideEvent, notify.init_info.pve_info.guide_id)
  end
  local bIsIgnoreFadeOut
  if _G.BattleUtils.IsTrainBattle() then
    bIsIgnoreFadeOut = true
  end
  _G.NRCModuleManager:DoCmd(_G.EnvSystemModuleCmd.LockWeather, notify.weather_id, LockWeatherReason.Battle, bIsIgnoreFadeOut)
  self:SetPotentialTaskID(notify)
  BattleReplayCachePool:StartCache(self.battleRuntimeData.battle_id)
  if BigMapModuleCmd then
    NRCModeManager:DoCmd(BigMapModuleCmd.CloseWorldMap)
    UE4Helper.SetEnableWorldRendering(true)
  end
  self.battleInfoManager:Clear()
  self.battleRuntimeData:SetBattleInitInfo(notify)
  self.battleRuntimeData:SetIsBattleAgain(isBattleAgain)
  self.vBattleField:SetupCraneCamera()
  self:EnterBattle()
  NRCModeManager:GetCurMode():DisablePanelByLayer(_G.Enum.UILayerType.UI_LAYER_TOP)
  NRCModeManager:GetCurMode():DisablePanelByLayer(_G.Enum.UILayerType.UI_LAYER_MAIN)
  NRCModeManager:GetCurMode():DisablePanelByLayer(_G.Enum.UILayerType.UI_LAYER_DIALOGUE)
  NRCModeManager:GetCurMode():DisablePanelByLayer(_G.Enum.UILayerType.UI_LAYER_FULLSCREEN)
  NRCModeManager:GetCurMode():ClosePanelByLayer(_G.Enum.UILayerType.UI_LAYER_POPUP)
  if not BattleUtils.IsBloodTeam() then
    BattleLevelHelper:CancelBloodTeamLevelStream()
  end
  _G.NRCSDKManager:SetEnterBattle()
end

function BattleManager:SetPotentialTaskID(notify)
  local PotentialTaskID
  if notify.init_info.battle_cfg_id and #notify.init_info.battle_cfg_id > 0 then
    local BattleID = notify.init_info.battle_cfg_id[1]
    local TaskIDs = _G.DataConfigManager:GetBattleUsedByTaskConf(BattleID, true)
    if TaskIDs then
      for _, TaskID in ipairs(TaskIDs.task_id) do
        local Task = NRCModuleManager:DoCmd(TaskModuleCmd.getTaskByID, TaskID)
        local bValidTask = nil ~= Task or _ == #TaskIDs.task_id
        if bValidTask then
          PotentialTaskID = TaskID
          break
        end
      end
    end
  end
  Log.Debug("BattleManager:SetPotentialTaskID", notify.init_info.battle_cfg_id, PotentialTaskID)
  self.battleRuntimeData:SetPotentialTaskID(PotentialTaskID)
end

function BattleManager:OnBattlePrePlayNotify(notify)
  Log.Debug("zgx BattleStreamLog  ReceivePacket  PacketName:ZoneBattlePrePlayNotify")
  self:SetSeqNumber(notify.perform_cmd.seq_num)
  _G.BattleEventCenter:Dispatch(BattleEvent.MULTI_PLAYER_TIP_CHANGE)
  self.stateFsm:SetProperty("Flows", notify.perform_cmd)
  self.stateFsm:SetProperty("SettleInfo", notify.settle_info)
  if BattleUtils.IsFinalBattleP1() and not self.battleRuntimeData.battleStartParam:IsReconnect() then
    notify.perform_cmd.IsFastPlay = true
    self.stateFsm:SetProperty("IsMySelfPerform", false)
  else
    self.stateFsm:SetProperty("IsMySelfPerform", true)
  end
  local needSpeedPreplay = true
  if notify and notify.perform_cmd then
    for i, v in ipairs(notify.perform_cmd.perform_info) do
      if v.type == ProtoEnum.BattlePerformType.BPT_AI then
        if v.ai_perform and v.ai_perform.type == ProtoEnum.AIPerformType.AI_PERFORM_CAM then
          needSpeedPreplay = false
        end
      elseif v.type == ProtoEnum.BattlePerformType.BPT_DEATH then
        needSpeedPreplay = false
      elseif v.type == ProtoEnum.BattlePerformType.BPT_DAMAGE then
        needSpeedPreplay = false
      end
    end
  end
  if needSpeedPreplay then
    self.stateFsm:SetProperty("IsPreplay", true)
  end
  self.stateFsm:SendEvent(BattleEvent.EnterPrePlay)
end

function BattleManager:OnBattleRoundStartNotify(notify)
  if notify and notify.perform_cmd then
    self:SetSeqNumber(notify.perform_cmd.seq_num)
  end
  LoadingProfiler:CheckPoint(LoadingProfilerCheckPoint.Battle_RoundStart)
  if not _G.EnableRoundStartNotify then
    _G.BattleManager.tempCachePlayerTeam = notify.state_info.player_team
    _G.BattleManager.tempCacheEnemyTeam = notify.state_info.enemy_team
  end
  Log.Debug("zgx BattleStreamLog  ReceivePacket  PacketName:ZoneBattleRoundStartNotify  BattleRound:", notify.state_info.round, notify.state_type)
  if not self.isInBattle then
    Log.Error("BattleManager:OnBattleRoundStartNotify: battle dont start")
    return
  end
  if BattleUtils.IsTeam() then
    self.LastSequencePerformNotify = nil
    if 0 == #self.TeamBattleNotifyQueue then
      self:SyncRoundStartData(notify)
      self:GoToRoundStartNextState(notify)
    elseif self.serverRound <= notify.state_info.round then
      local data = {}
      data.type = BattleManager.RoundType
      data.notify = notify
      table.insert(self.TeamBattleNotifyQueue, data)
    end
  else
    self:SyncRoundStartData(notify)
    self:GoToRoundStartNextState(notify)
  end
  if _G.NRCModuleManager:DoCmd(_G.DialogueModuleCmd.HasDialogue) then
    _G.NRCModuleManager:DoCmd(_G.DialogueModuleCmd.CloseDialogueInBattle)
  end
  _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_ROUND_START)
  if self.serverRound >= notify.state_info.round then
    Log.Debug("zgx \230\148\182\229\136\176\228\186\134\228\185\139\229\137\141\229\155\158\229\144\136\231\154\132notify!!!", self.serverRound, notify.state_info.round)
  else
    self.serverRound = notify.state_info.round
  end
end

function BattleManager:SyncRoundBasicData(notify)
  local isInitRound = notify.state_info.round == self.battleRuntimeData.roundIndex and (self.curRound ~= notify.state_info.round or notify.isFromBattleEnter == true)
  local oldRound = self.curRound
  self:SyncCurRound(notify.state_info.round)
  local bloodPetSkills = notify.perform_cmd and notify.perform_cmd.blood_pet_skills
  self:_TeamBattleChooseSkill(isInitRound, oldRound, bloodPetSkills)
  BattleSeasonUtils.OnRoundStart(isInitRound, oldRound, notify)
  self.battleInfoManager:ClearAllExpiredPushPopInfoForRoundStart(notify.state_info.round)
  self.RoundStartRecord = notify.state_info.round
  local stateInfo = notify.state_info
  self:SyncRoundStartDataBefore(notify)
  self:SyncRoundFBBattleData(notify)
  self:SyncRoundStartDataAfter(notify)
  self:CheckBattleDataUpdate(notify.perform_cmd)
  self.ShowOpTips = true
  self.battlePawnManager:RefreshBattleField(stateInfo)
  self.battleResourceManager:UnLoadAssetByType(BattleResourceManager.UnloadType.ROUND_START)
  if _G.EnableRoundStartNotify then
    local player = stateInfo.player_team[1]
    if player then
      Log.Debug("Update Player Catch Time Count", self.battleRuntimeData.catchInfo.curCatchTime, player.base.catch_counts)
      self.battleRuntimeData.catchInfo.curCatchTime = player.base.catch_counts
    end
  else
    self.battleRuntimeData.catchInfo.curCatchTime = self.battleRuntimeData.battleStartParam.battleCfg.use_ball_time
  end
  NRCModuleManager:DoCmd(BattleUIModuleCmd.UpdateRound, notify.state_info.round)
  local multiPlayerTipChangeContext = {isRoundStart = true}
  _G.BattleEventCenter:Dispatch(BattleEvent.MULTI_PLAYER_TIP_CHANGE, multiPlayerTipChangeContext)
  local roundLimit
  if BattleUtils.IsPvp() then
    if notify.state_info.is_player_dishonesty and not notify.state_info.is_enemy_dishonesty then
      local config = BattleUtils.GetBattleConfig()
      local roundPetTimeout = config.round_pet_timeout or 30
      local roundPetTimeoutMilliseconds = roundPetTimeout * 1000
      local pvpCountDown = _G.DataConfigManager:GetBattleGlobalConfig("pvp_countdown").num
      local pvpCountDownMilliseconds = pvpCountDown * 1000
      _G.BattleEventCenter:Dispatch(BattleEvent.START_PVP_ROUND_TIME, notify.state_info.round_time - roundPetTimeoutMilliseconds + pvpCountDownMilliseconds)
    else
      _G.BattleEventCenter:Dispatch(BattleEvent.START_PVP_ROUND_TIME, notify.state_info.round_time)
    end
    roundLimit = stateInfo.pvp_round_limit
  elseif BattleUtils.IsTerritoryTrialBattle() then
    local battleConfig = BattleUtils.GetBattleConfig()
    local battleMaxRound = battleConfig and battleConfig.max_round or 9999
    local currentRound = self:GetCurRound() or 0
    roundLimit = battleMaxRound - currentRound + 1
  end
  if roundLimit then
    self:CheckPvpRoundLimit(roundLimit)
  end
  if notify.guide_id then
    _G.NRCModuleManager:DoCmd(_G.BattleTutorialGuideModuleCmd.ClearGuide)
    _G.NRCEventCenter:DispatchEvent(BattleTutorialGuideModuleEvent.EnterBattleTutorialGuideEvent, notify.guide_id)
  end
end

function BattleManager:SyncRoundStartDataBefore(notify)
  local stateInfo = notify.state_info
  self.battleRuntimeData.lastChangePetRoundIndex = stateInfo.last_change_pet_round
  self.battleRuntimeData.battleStartParam.series_index = notify.state_info.series_index
  self.battleRuntimeData.battleStartParam.battleInitInfo.world_leader_fight_info = stateInfo.world_leader_fight_info
  self.battleRuntimeData.startRoundSelectRoundStateType = notify.state_type
  self.battleRuntimeData:SetNpcAutoEscapeInfo(notify.state_info.npc_escape)
  self.battleRuntimeData.pvpRoundLimit = stateInfo.pvp_round_limit
  self.battleRuntimeData:SetIsJumpAiPerform(false)
end

function BattleManager:SyncRoundFBBattleData(notify)
  local stateInfo = notify.state_info
  if stateInfo.final_battle_data then
    self.battleRuntimeData.finalBattleData = stateInfo.final_battle_data
  end
  if stateInfo.b1_final_battle_data then
    self.battleRuntimeData.b1FinalBattleData = stateInfo.b1_final_battle_data
  end
  _G.BattleManager.battleRuntimeData:SetFBP1ToP2State(nil)
  if stateInfo.b1_final_battle_data and stateInfo.b1_final_battle_data.b1_phantom_point then
    self.battleRuntimeData:SetB1PhantomPoint(stateInfo.b1_final_battle_data.b1_phantom_point)
  end
end

function BattleManager:SyncRoundStartDataAfter(notify)
  self:SyncAllReqNotify()
end

function BattleManager:SyncRoundStartData(notify)
  if self:CheckFBSwitchBattleCfg(notify) then
    self:SyncRoundStartDataBefore(notify)
    self:SyncRoundFBBattleData(notify)
    self:SyncRoundStartDataAfter(notify)
  else
    self:SyncRoundBasicData(notify)
  end
end

function BattleManager:SyncCurRound(round)
  if self.curRound ~= round then
    self.curRound = round
    _G.BattleEventCenter:Dispatch(BattleEvent.Replay_RefreshRoundIdx, self.curRound)
  end
  self.AIRound = round
  self.battleRuntimeData.roundIndex = round
end

function BattleManager:_TeamBattleChooseSkill(isInitRound, oldRound, blood_pet_skills)
  if BattleUtils.IsTeam() or BattleUtils.IsB1FinalBattleP3() then
    if isInitRound then
      self:UpdateBloodPetSkills(self.battleRuntimeData.battleStartParam.battleInitInfo.blood_pet_skills, self.curRound)
      if blood_pet_skills then
        self:UpdateBloodPetSkills(blood_pet_skills, self.curRound)
      end
    else
      if oldRound ~= self.curRound then
        _G.BattleEventCenter:Dispatch(BattleEvent.PLAYER_PERFORM_OVER, oldRound)
      end
      if blood_pet_skills then
        self:UpdateBloodPetSkills(blood_pet_skills, self.curRound)
      end
    end
  end
end

function BattleManager:UpdateBloodPetSkills(blood_pet_skills, round)
  if BattleUtils.IsJiaerBeastTeam() then
    self:ModifyBloodPetSkills(blood_pet_skills)
  end
  _G.BattleEventCenter:Dispatch(BattleEvent.PLAYER_CHOOSE_SKILL, blood_pet_skills, round)
end

function BattleManager:InitJiaerSkillCache()
  if self.battleRuntimeData.jiaerSkillBlackToWhite then
    return
  end
  local whiteJiaerBaseId = _G.DataConfigManager:GetGlobalConfigNumByKeyType("legendary_battle_jiaer_white_id", _G.DataConfigManager.ConfigTableId.BATTLE_GLOBAL_CONFIG, 0)
  local blackJiaerBaseId = _G.DataConfigManager:GetGlobalConfigNumByKeyType("legendary_battle_jiaer_black_id", _G.DataConfigManager.ConfigTableId.BATTLE_GLOBAL_CONFIG, 0)
  if 0 == whiteJiaerBaseId or 0 == blackJiaerBaseId then
    Log.Warning("BattleManager:InitJiaerSkillCache BATTLE_GLOBAL_CONFIG\228\184\173\229\138\160\229\176\148base_id\233\133\141\231\189\174\228\184\141\229\173\152\229\156\168")
    return
  end
  self.battleRuntimeData.whiteJiaerBaseId = whiteJiaerBaseId
  self.battleRuntimeData.blackJiaerBaseId = blackJiaerBaseId
  local whiteConf = _G.DataConfigManager:GetBloodMonsterSkillbankConf(whiteJiaerBaseId)
  local blackConf = _G.DataConfigManager:GetBloodMonsterSkillbankConf(blackJiaerBaseId)
  if not whiteConf or not blackConf then
    Log.Warning("BattleManager:InitJiaerSkillCache \233\133\141\231\189\174\232\161\168\230\149\176\230\141\174\228\184\141\229\173\152\229\156\168")
    return
  end
  local blackToWhite = {}
  local whiteToBlack = {}
  local skill_group_num = 4
  for groupIdx = 1, skill_group_num do
    local whiteSkills = whiteConf["skill_group_" .. groupIdx]
    local blackSkills = blackConf["skill_group_" .. groupIdx]
    if whiteSkills and #whiteSkills > 0 and blackSkills and #blackSkills > 0 then
      local minLen = math.min(#whiteSkills, #blackSkills)
      for skillIdx = 1, minLen do
        local whiteSkillId = whiteSkills[skillIdx]
        local blackSkillId = blackSkills[skillIdx]
        if whiteSkillId and whiteSkillId > 0 and blackSkillId and blackSkillId > 0 then
          blackToWhite[blackSkillId] = whiteSkillId
          whiteToBlack[whiteSkillId] = blackSkillId
        end
      end
    end
  end
  self.battleRuntimeData.jiaerSkillBlackToWhite = blackToWhite
  self.battleRuntimeData.jiaerSkillWhiteToBlack = whiteToBlack
  Log.Dump(self.battleRuntimeData.jiaerSkillBlackToWhite, 5, "jiaerSkillBlackToWhite")
end

function BattleManager:ModifyBloodPetSkills(blood_pet_skills)
  if not blood_pet_skills or not blood_pet_skills.skills then
    return
  end
  self:InitJiaerSkillCache()
  if not self.battleRuntimeData.jiaerSkillBlackToWhite then
    return
  end
  local bossPet = self.battlePawnManager:GetFirstPet(BattleEnum.Team.ENUM_ENEMY)
  if not (bossPet and bossPet.card) or not bossPet.card.petBaseConf then
    return
  end
  local bossBaseId = bossPet.card.petBaseConf.id
  local mappingTable
  if bossBaseId == self.battleRuntimeData.blackJiaerBaseId then
    mappingTable = self.battleRuntimeData.jiaerSkillWhiteToBlack
  elseif bossBaseId == self.battleRuntimeData.whiteJiaerBaseId then
    mappingTable = self.battleRuntimeData.jiaerSkillBlackToWhite
  else
    return
  end
  for _, skillInfo in ipairs(blood_pet_skills.skills) do
    if skillInfo.skill_id and mappingTable[skillInfo.skill_id] then
      skillInfo.skill_id = mappingTable[skillInfo.skill_id]
    end
  end
  if blood_pet_skills.pkinfo and blood_pet_skills.pkinfo.skill_id and mappingTable[blood_pet_skills.pkinfo.skill_id] then
    blood_pet_skills.pkinfo.skill_id = mappingTable[blood_pet_skills.pkinfo.skill_id]
  end
end

function BattleManager:CheckFBSwitchBattleCfg(notify)
  if self:NeedP1SwitchToP2(notify) then
    self.stateFsm:SetProperty("roundStarNotify", notify)
    self.stateFsm:SendEvent(BattleEvent.FinalBattleToP2)
    return true
  end
  if self:NeedB1P1SwitchToP2(notify) then
    self.stateFsm:SetProperty("roundStarNotify", notify)
    self.stateFsm:SendEvent(BattleEvent.B1FinalBattleToP2)
    return true
  end
  if self:NeedB1P2SwitchToP3(notify) then
    self.stateFsm:SetProperty("roundStarNotify", notify)
    self.stateFsm:SendEvent(BattleEvent.B1FinalBattleToP3)
    return true
  end
  return false
end

function BattleManager:NeedP1SwitchToP2(notify)
  if BattleUtils.IsFinalBattleP1() then
    local finalBattleData = notify.state_info.final_battle_data
    if finalBattleData and finalBattleData.P2_battle_cfg_id and finalBattleData.switch_to_p2 then
      local battleCfg = _G.DataConfigManager:GetBattleConf(finalBattleData.P2_battle_cfg_id)
      if battleCfg then
        return true
      end
    end
  end
  return false
end

function BattleManager:NeedB1P1SwitchToP2(notify)
  if BattleUtils.IsB1FinalBattleP1() then
    local finalBattleData = notify.state_info.b1_final_battle_data
    if finalBattleData and finalBattleData.P2_battle_cfg_id and finalBattleData.switch_to_p2 then
      local battleCfg = _G.DataConfigManager:GetBattleConf(finalBattleData.P2_battle_cfg_id)
      if battleCfg then
        return true
      end
    end
  end
  return false
end

function BattleManager:NeedB1P2SwitchToP3(notify)
  if BattleUtils.IsB1FinalBattleP2() then
    local finalBattleData = notify.state_info.b1_final_battle_data
    if finalBattleData and finalBattleData.P3_battle_cfg_id and finalBattleData.switch_to_p3 then
      local battleCfg = _G.DataConfigManager:GetBattleConf(finalBattleData.P3_battle_cfg_id)
      if battleCfg then
        return true
      end
    end
  end
  return false
end

function BattleManager:CheckP2NeedSupply()
  if BattleUtils.IsFinalBattleP2() then
    local player = self.battlePawnManager:GetPlayerMyTeam()
    if player and not player.deck:HasInBattleCards() then
      return true
    end
  end
end

function BattleManager:CheckB1P3FinalSkill(notify)
  if BattleUtils.IsB1FinalBattleP3() then
    local finalBattleData = notify.state_info.b1_final_battle_data
    if finalBattleData and finalBattleData.p3_ulti_skill then
      return true
    end
  end
end

function BattleManager:GoToRoundStartNextState(notify)
  if self:NeedP1SwitchToP2(notify) then
    return
  end
  if self:CheckP2NeedSupply() then
    self.stateFsm:SendEvent(BattleEvent.FinalBattleToP2)
    return
  end
  if self:NeedB1P1SwitchToP2(notify) then
    return
  end
  if self:NeedB1P2SwitchToP3(notify) then
    return
  end
  if self:CheckB1P3FinalSkill(notify) then
    if self.stateFsm:GetActiveStateName() == BattleEnum.StateNames.B1FinalBattleP3FinalSkill then
      return
    end
    self.stateFsm:SendEvent(BattleEvent.B1FBP3FinalSkill)
    return
  end
  if BattleUtils.IsWatchingBattle() then
    local battleMainWindow = BattleUtils.GetMainWindow()
    if battleMainWindow then
      battleMainWindow:SwitchToWatchBattleMode()
    end
  end
  BattleConst.UpdateFootDelta = 99999999
  if self:CheckTeamSupplyPet() and notify.state_type ~= _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_CATCH then
    if not self:CheckActiveState(BattleEnum.StateNames.SwapSelect) then
      self.stateFsm:SetProperty("isTeamSupply", true)
      self.stateFsm:SendEvent(BattleEvent.EnterSwapSelect)
    end
    return
  end
  self.stateFsm:SetProperty("RoundStateVar", notify.state_type)
  if notify.state_type == _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_PET then
    if notify.state_info.npc_escape and 0 ~= #notify.state_info.npc_escape then
      Log.Debug("\231\173\137\229\190\133\231\142\169\229\174\182\229\164\132\231\144\134npc\232\135\170\229\138\168\233\128\131\232\183\145")
      self.stateFsm:SendEvent(BattleEvent.EnterNpcAutoEscape)
    else
      if notify.is_ridOf then
        self.stateFsm:SetProperty("isBlowBuff", true)
      end
      self.stateFsm:SendEvent(BattleEvent.EnterSwapSelect)
    end
  elseif notify.state_type == _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_ROUND_SELECT_PET then
    local player = _G.BattleManager.battlePawnManager.TeamatePlayer
    if player and player:NeedSupplyPet() and player.deck:HasPetBeRidOf() then
      self.stateFsm:SetProperty("isBlowBuff", true)
      self.stateFsm:SendEvent(BattleEvent.EnterSelectRidPet)
      return
    end
    self.stateFsm:SendEvent(BattleEvent.EnterWaitOther)
    BattleUtils.ShowPvpWaitSupplyPetTips()
  elseif notify.state_type == _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_CMD or notify.state_type == _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_CATCH then
    if notify.state_info.npc_escape and 0 ~= #notify.state_info.npc_escape then
      Log.Debug("\231\173\137\229\190\133\231\142\169\229\174\182\229\164\132\231\144\134npc\232\135\170\229\138\168\233\128\131\232\183\145")
      self.stateFsm:SendEvent(BattleEvent.EnterNpcAutoEscape)
    else
      Log.Debug("\231\173\137\229\190\133\231\142\169\229\174\182\229\143\145\233\128\129\230\140\135\228\187\164")
      if notify.state_type == _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_CATCH then
        local allPlayerTeam = self.battlePawnManager.AllPlayerTeam
        for _, team in ipairs(allPlayerTeam) do
          if team ~= self.battlePawnManager.playerTeam then
            team.player:HidePlayer(true)
            team:QuitBattle()
          end
        end
        self.IsTeamBossToCatch = true
        local pets = self.battlePawnManager:GetInFieldAllPet(BattleEnum.Team.ENUM_ENEMY)
        for _, v in ipairs(pets) do
          v.CanCatchAtTeamFight = true
          v.buffComponent:RemoveBuffs(true)
          v.buffComponent:ClearBuff()
        end
        if BattleUtils.IsBloodTeam() then
          if BattleUtils.IsBossPerformBeDefeated() then
            if self:CheckActiveState(BattleEnum.StateNames.RoundSelect) then
              _G.BattleEventCenter:Dispatch(BattleEvent.TEAM_BATTLE_CATCH)
              return
            end
          else
            self.stateFsm:SendEvent(BattleEvent.EnterTeamCatch)
            return
          end
        elseif BattleUtils.IsBeastTeam() then
          if BattleUtils.IsPlayerSelectCatchInBeast() then
            NRCModeManager:DoCmd(BattleUIModuleCmd.CloseTransformLoadingUI)
            _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.CloseSkipTheCutscene)
            if self:CheckActiveState(BattleEnum.StateNames.RoundSelect) then
              _G.BattleEventCenter:Dispatch(BattleEvent.TEAM_BATTLE_CATCH)
              return
            end
          else
            self.stateFsm:SendEvent(BattleEvent.EnterTeamBeastDefeat)
            return
          end
        end
        _G.BattleEventCenter:Dispatch(BattleEvent.TEAM_BATTLE_CATCH)
      else
        self:CheckForMultiBattleRunAway()
      end
      if self.IsRevertPawnPos then
        self.IsRevertPawnPos = false
        self.stateFsm:SendEvent(BattleEvent.EnterRevertTeamBattle)
      elseif not self:CheckActiveState(BattleEnum.StateNames.RoundSelect) then
        self.stateFsm:SendEvent(BattleEvent.EnterRoundSelect)
      end
    end
  elseif notify.state_type == _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_EVOLUTION then
    local stateInfo = notify and notify.state_info
    local evolution_data_list = stateInfo and stateInfo.evolution_data or {}
    if evolution_data_list and #evolution_data_list > 0 then
      Log.Debug("\231\173\137\229\190\133\231\142\169\229\174\182\232\191\155\229\140\150")
      self.battleRuntimeData:SetEvolutionSelectActionInfo(evolution_data_list)
      self.stateFsm:SendEvent(BattleEvent.EnterEvolutionSelect)
    else
      Log.Error("[BattleManager] notify.state_type \228\184\186 BATTLE_STATE_SELECT_EVOLUTION \229\141\180\230\178\161\230\156\137 evolution_data \230\149\176\230\141\174\239\188\140\232\175\183\230\163\128\230\159\165")
    end
  else
    Log.Debug("unknow state type : ", notify.state_type)
  end
end

function BattleManager:CheckTeamSupplyPet()
  if not BattleUtils.IsTeam() then
    return false
  end
  local player = self.battlePawnManager:GetPlayerMyTeam()
  if player then
    local canSupplyPet = player:GetStateBit(ProtoEnum.BATTLER_BIT_TYPE.BT_BATTLER_TEAM_PVE_CAN_PET)
    return canSupplyPet and player:NeedSupplyPet()
  end
end

function BattleManager:CheckForMultiBattleRunAway()
  if BattleUtils.IsRunAwayFree() then
    local mainWindow = BattleUtils.GetMainWindow()
    if mainWindow then
      local pets = _G.BattleManager.battlePawnManager:GetCanSelectPetsByPlayer(self.battlePawnManager.TeamatePlayer)
      if pets and #pets > 0 then
        if mainWindow.UMG_Battle_Operate.changeToRunAway then
          mainWindow:RefreshOperatePanel()
          if self:CheckActiveState(BattleEnum.StateNames.RoundSelect) then
            _G.BattleEventCenter:Dispatch(BattleEvent.UPDATE_DATA, pets[1])
            _G.BattleEventCenter:Dispatch(BattleEvent.LEAVE_ESCAPE_STATE)
            local oldOpType = self.battleRuntimeData.operateType
            if oldOpType ~= BattleEnum.Operation.ENUM_NONE then
              mainWindow:ChangePanelByOperateType(oldOpType, true, true)
            end
          end
        end
      elseif self:CheckActiveState(BattleEnum.StateNames.SwapSelect) then
        mainWindow:RefreshOperatePanel()
      elseif not mainWindow.UMG_Battle_Operate.changeToRunAway then
        mainWindow:SwitchToRunAway()
      end
    end
  end
end

function BattleManager:OnBattleCmdSyncNotify(notify)
  if BattleUtils.IsTeam() and self.IsTeamBossToCatch then
    return
  end
  local opPlayer = self.battlePawnManager:GetPlayerByGuid(notify.player_uin)
  if not opPlayer then
    return
  end
  Log.Debug("zgx No op OnBattleCmdSyncNotify")
  self:CacheReqNotify(notify)
  if opPlayer.teamEnm == BattleEnum.Team.ENUM_TEAM then
    if notify.player_uin ~= self.battlePawnManager:GetPlayerMyTeam().guid then
      Log.Debug("zgx No op OnBattleCmdSyncNotify \233\152\159\229\143\139\230\147\141\228\189\156\239\188\129\239\188\129")
      if notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CATCH_PET then
        opPlayer:SetOp(BattleEnum.Operation.ENUM_CATCH)
      elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CAST_SKILL then
        local battlePet = self.battlePawnManager:GetPetByGuid(notify.req.cast_skill.caster_pet_id)
        if battlePet then
          battlePet:SetOp(BattleEnum.Operation.ENUM_SKILL)
        end
      elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_ROLE_MAGIC then
        local battlePet = self.battlePawnManager:GetPetByGuid(notify.req.magic_op.target_pet_id)
        if battlePet then
          battlePet:SetOp(BattleEnum.Operation.ENUM_PLAYERSKILL)
        end
      elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CHANGE_PET then
        local battlePet = self.battlePawnManager:GetPetByGuid(notify.req.change_pet.rest_pet_id)
        if battlePet then
          battlePet:SetOp(BattleEnum.Operation.ENUM_CHANGE)
        else
        end
      elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_USE_ITEM then
        local item = DataConfigManager:GetBagItemConf(notify.req.use_item.item_id, true)
        if item then
        else
        end
      end
    else
      Log.Debug("zgx No op OnBattleCmdSyncNotify \232\135\170\229\183\177\230\147\141\228\189\156")
      if notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CAST_SKILL or notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CHANGE_PET or notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CATCH_PET or notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_ROLE_MAGIC then
        if notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CATCH_PET then
          opPlayer:SetOp(BattleEnum.Operation.ENUM_CATCH)
        end
        local team = self.battlePawnManager:GetAllTeam(BattleEnum.Team.ENUM_TEAM)
        if BattleUtils.IsPvp() or team and #team > 1 then
          local ignorePet
          if notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CAST_SKILL then
            ignorePet = {
              notify.req.cast_skill.caster_pet_id
            }
          elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_ROLE_MAGIC then
            ignorePet = {
              notify.req.magic_op.target_pet_id
            }
          elseif notify.req.change_pet then
            ignorePet = {
              notify.req.change_pet.rest_pet_id
            }
          end
          if self.battlePawnManager.TeamatePlayer:IsRoundDone(ignorePet) and 0 == self.stateFsm:GetEventNumber() and (self:CheckActiveState(BattleEnum.StateNames.RoundSelect) or self:CheckActiveState(BattleEnum.StateNames.SwapSelect)) and not self.stateFsm:GetNextStateName() then
            Log.Debug("zgx No op \230\136\145\230\150\185\231\178\190\231\129\181\230\147\141\228\189\156\229\174\140\230\136\144 \232\191\155\229\133\165\232\161\168\230\131\133\230\181\129\231\168\139(\230\147\141\228\189\156\229\144\140\230\173\165\229\141\143\232\174\174\233\135\140)")
            self.stateFsm:Resume()
            self.stateFsm:SendEvent(BattleEvent.EnterWaitOther)
          end
        else
          _G.BattleEventCenter:Dispatch(BattleEvent.MULTI_PLAYER_TIP_CHANGE)
        end
      end
    end
  else
    Log.Debug("zgx No op OnBattleCmdSyncNotify \230\149\140\230\150\185\230\147\141\228\189\156")
    if BattleUtils.IsPvp() then
      if notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CAST_SKILL then
        local battlePet = self.battlePawnManager:GetPetByGuid(notify.req.cast_skill.caster_pet_id)
        if battlePet then
          battlePet:SetOp(BattleEnum.Operation.ENUM_SKILL)
        end
      elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_ROLE_MAGIC then
        local battlePet = self.battlePawnManager:GetPetByGuid(notify.req.magic_op.target_pet_id)
        if battlePet then
          battlePet:SetOp(BattleEnum.Operation.ENUM_PLAYERSKILL)
        end
      elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CHANGE_PET then
        local battlePet = self.battlePawnManager:GetPetByGuid(notify.req.change_pet.rest_pet_id)
        if battlePet then
          battlePet:SetOp(BattleEnum.Operation.ENUM_CHANGE)
        end
      elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CATCH_PET then
        opPlayer:SetOp(BattleEnum.Operation.ENUM_CATCH)
      end
      local enemyTeams = self.battlePawnManager:GetAllTeam(BattleEnum.Team.ENUM_ENEMY)
      if enemyTeams then
        for _, v in pairs(enemyTeams) do
          if not v.player:IsRoundDone() then
            return
          end
        end
        _G.BattleEventCenter:Dispatch(BattleEvent.MULTI_PLAYER_TIP_CHANGE)
      end
    end
    if not opPlayer:IsRealPlayer() then
      if notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CAST_SKILL then
        if not self.AIHistoryInfo[self.AIRound] then
          self.AIHistoryInfo[self.AIRound] = {}
        end
        table.insert(self.AIHistoryInfo[self.AIRound], {
          type = "UseSkill",
          petId = notify.req.cast_skill.caster_pet_id,
          skillId = notify.req.cast_skill.skill_id
        })
      elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CHANGE_PET then
        if not self.AIHistoryInfo[self.AIRound] then
          self.AIHistoryInfo[self.AIRound] = {}
        end
        table.insert(self.AIHistoryInfo[self.AIRound], {
          type = "ChangePet",
          oldPets = {
            notify.req.change_pet.rest_pet_id
          },
          newPets = {
            notify.req.change_pet.battle_pet_id
          }
        })
      end
      _G.BattleEventCenter:Dispatch(BattleEvent.RECORD_AI_OP)
    end
  end
end

function BattleManager:CacheReqNotify(notify)
  if not self.CmdSyncNotifys then
    self.CmdSyncNotifys = {}
  end
  table.insert(self.CmdSyncNotifys, notify)
end

function BattleManager:SyncAllReqNotify()
  local players = self.battlePawnManager:GetAllPlayers()
  for i, v in pairs(players) do
    v:UpdateOpState(v.roleInfo)
  end
  if not self.CmdSyncNotifys then
    return
  end
  local cmdCount = #self.CmdSyncNotifys
  for i = 1, cmdCount do
    local notify = self.CmdSyncNotifys[i]
    local opPlayer = self.battlePawnManager:GetPlayerByGuid(notify.player_uin)
    if not opPlayer then
      return
    end
    local isLast = i == cmdCount
    if opPlayer.teamEnm == BattleEnum.Team.ENUM_TEAM then
      if notify.player_uin ~= self.battlePawnManager:GetPlayerMyTeam().guid then
        self:RrefreshPetOpState(notify, isLast)
      else
        self:ClearPetOpState(notify)
      end
    else
      self:RrefreshPetOpState(notify, isLast)
    end
  end
  self.CmdSyncNotifys = {}
end

function BattleManager:RrefreshPetOpState(notify, isLast)
  local petID
  if notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CAST_SKILL then
    petID = notify.req.cast_skill.caster_pet_id
  elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CHANGE_PET then
    petID = notify.req.change_pet.battle_pet_id
  elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_SKILL_STATE then
    petID = notify.req.skill_state.caster_pet_id
  elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_ROLE_MAGIC then
    petID = notify.req.magic_op.target_pet_id
  elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_IDLE then
    petID = notify.req.idle.caster_pet_id
  end
  local pet = self.battlePawnManager:GetPetByGuid(petID)
  if pet then
    pet:UpdateByCard(pet.card, isLast)
    pet:UpdateEscapeInfo()
    pet:UpdateOpStateByReq(notify.req)
  end
end

function BattleManager:ClearPetOpState(notify)
  local petID
  if notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CAST_SKILL then
    petID = notify.req.cast_skill.caster_pet_id
  elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_CHANGE_PET then
    petID = notify.req.change_pet.battle_pet_id
  elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_SKILL_STATE then
    petID = notify.req.skill_state.caster_pet_id
  elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_ROLE_MAGIC then
    petID = notify.req.magic_op.target_pet_id
  elseif notify.req.req_type == ProtoEnum.BATTLE_REQ_TYPE.CMD_IDLE then
    petID = notify.req.idle.caster_pet_id
  end
  local pet = self.battlePawnManager:GetPetByGuid(petID)
  if pet then
    notify.req.req_type = 0
    pet:UpdateOpStateByReq(notify.req)
  end
end

function BattleManager:OnBattleInstantPerformNotify(notify)
  Log.Debug("zgx BattleStreamLog  ReceivePacket  PacketName:ZoneBattleInstantPerformNotify")
  self:SetSeqNumber(notify.perform_cmd.seq_num)
  local battler_info = notify.settle_info and notify.settle_info.last_damage_info
  if self.battleRuntimeData and battler_info then
    self.battleRuntimeData.battleSettleData:SetBattlerInfo(battler_info)
  end
  if not notify.flow_data then
    notify.flow_data = {
      flow = {}
    }
  end
  if not self.instantFsm then
    self.instantFsm = InstantBattleFsm()
  else
    self.instantFsm:Stop()
  end
  self.instantFsm:SetProperty("Flows", notify.perform_cmd)
  self.instantFsm:SetProperty("SettleInfo", notify.settle_info)
  self.instantFsm:SetProperty("NpcDelay", notify.has_npc_delay)
  if self:IsSelfInstantPerform(notify) then
    self.battleNetManager:StopHandleNotify("start instantFsm at OnBattleInstantPerformNotify")
    self.instantFsm:SetProperty("IsSelfPerform", true)
    self.stateFsm:Resume()
    self.stateFsm:SendEvent(BattleEvent.EnterInstantPlay)
  else
    self.instantFsm:SetProperty("IsSelfPerform", false)
    self.instantFsm:Play()
  end
end

function BattleManager:IsSelfInstantPerform(notify)
  if BattleUtils.IsFinalBattleP1() then
    return false
  end
  if notify.perform_cmd and notify.perform_cmd.perform_info and #notify.perform_cmd.perform_info > 0 then
    for i, perform in ipairs(notify.perform_cmd.perform_info) do
      if perform.use_item and perform.use_item.player_id then
        return perform.use_item.player_id == self.battlePawnManager:GetPlayerMyTeam().guid
      end
      if perform.catch_pet_info and perform.catch_pet_info.player_id then
        return perform.catch_pet_info.player_id == self.battlePawnManager:GetPlayerMyTeam().guid
      end
      if perform.role_skill_cast and perform.role_skill_cast.caster_uin then
        return perform.role_skill_cast.caster_uin == self.battlePawnManager:GetPlayerMyTeam().guid
      end
    end
  end
  return false
end

function BattleManager:CheckBattleDataUpdate(perform_cmd)
  if perform_cmd then
    local perform_info = perform_cmd.perform_info
    if perform_info then
      for i = 1, #perform_info do
        if perform_info[i].type == ProtoEnum.BattlePerformType.BPT_DATA_UPDATE then
          BattleDataCenter:WriteDataUpdate(perform_info[i].data_update)
        end
      end
    end
  end
end

function BattleManager:CheckIsMySelfPerformTeamBattle(notify)
  local petCard
  if notify.perform_cmd.blood_pet_skills then
    if notify.perform_cmd.blood_pet_skills.pkinfo then
      petCard = self.battlePawnManager:GetCardByGuid(notify.perform_cmd.blood_pet_skills.pkinfo.attack_pet_id)
    elseif notify.perform_cmd.blood_pet_skills.story_team_pk_info then
      for _, pkinfo in ipairs(notify.perform_cmd.blood_pet_skills.story_team_pk_info) do
        local tempCard = self.battlePawnManager:GetCardByGuid(pkinfo.attack_pet_id)
        if tempCard and tempCard.owner == self.battlePawnManager.TeamatePlayer then
          petCard = tempCard
          break
        end
      end
    end
  else
    if self.LastSequencePerformNotify and self.LastSequencePerformNotify.IsSelfPerform then
      notify.IsSelfPerform = true
      notify.NeedChangeState = true
      return
    elseif notify.perform_cmd.IsFromRoundStart and not self.LastSequencePerformNotify then
      notify.IsSelfPerform = true
      notify.NeedChangeState = true
      return
    end
    Log.Warning("[#warning:W004]zgx ZoneBattlePerformStartNotify pkinfo is nil!!! ")
  end
  if petCard and petCard.owner == self.battlePawnManager.TeamatePlayer then
    notify.IsSelfPerform = true
    notify.NeedChangeState = true
  else
    notify.IsSelfPerform = false
    notify.HasSelfPerform = false
    notify.HasLenSkill = false
    for _, v in ipairs(notify.perform_cmd.perform_info) do
      if v.type == ProtoEnum.BattlePerformType.BPT_REVIVE then
        local revivePet = self.battlePawnManager:GetCardByGuid(v.revive_info.caster_id)
        if revivePet and revivePet.owner == self.battlePawnManager.TeamatePlayer then
          notify.HasSelfPerform = true
          notify.NeedChangeState = true
        end
      elseif v.type == ProtoEnum.BattlePerformType.BPT_DEATH then
        local diePet = self.battlePawnManager:GetCardByGuid(v.dead_info.target_id)
        if diePet and diePet.owner == self.battlePawnManager.TeamatePlayer then
          notify.IsSelfPerform = true
          notify.NeedChangeState = true
          return
        end
      elseif v.type == ProtoEnum.BattlePerformType.BPT_AI then
        local ai_perform = v.ai_perform
        if ai_perform and (ai_perform.type == ProtoEnum.AIPerformType.AI_PERFORM_CAM or ai_perform.type == ProtoEnum.AIPerformType.AI_PERFORM_DIALOG) then
          notify.IsSelfPerform = true
          notify.NeedChangeState = true
          return
        end
      elseif v.type == ProtoEnum.BattlePerformType.BPT_CHANGE_PET then
        if v.change_pet and v.change_pet.player_id and v.change_pet.player_id == self.battlePawnManager.TeamatePlayer.guid then
          notify.IsSelfPerform = true
          notify.NeedChangeState = true
        end
      elseif v.type == ProtoEnum.BattlePerformType.BPT_SUPPLY_PET and v.supply_pet and v.supply_pet.player_id and v.supply_pet.player_id == self.battlePawnManager.TeamatePlayer.guid then
        notify.IsSelfPerform = true
        notify.NeedChangeState = true
      end
    end
  end
end

function BattleManager:CheckActiveState(stateName)
  if not self.stateFsm then
    return false
  end
  return self.stateFsm:GetActiveStateName() == stateName
end

function BattleManager:CheckCanPerform(notify)
  if self.IsTeamBossToCatch and notify.perform_cmd and notify.perform_cmd.perform_info then
    local perform_info = notify.perform_cmd.perform_info
    if 0 == #perform_info then
      return false
    elseif 1 == #perform_info and perform_info[1].type == ProtoEnum.BattlePerformType.BPT_CMD_FAILED then
      return false
    end
  end
  return true
end

function BattleManager:FilterPvpPlayerPerformData(battlePerformInfo)
  if #battlePerformInfo > 0 then
    local result = {}
    for _, performInfo in pairs(battlePerformInfo) do
      if performInfo.pvp_perform then
        table.insert(result, performInfo.pvp_perform)
      end
    end
    if #result > 0 then
      local index = math.random(1, #result)
      return result[index]
    else
      return nil
    end
  end
end

function BattleManager:OnBattlePvpPerformStartNotify(notify)
  self.battleRuntimeData:SetPvpPlayerPerformData(notify.perform_cmd.perform_info)
  local battlePerformInfo = notify.perform_cmd.perform_info
  local pvpPlayerPerformData = self:FilterPvpPlayerPerformData(battlePerformInfo)
  if pvpPlayerPerformData then
    local pvpSkillPath = BattleConst.PvpPlayerPerform[pvpPlayerPerformData.type]
    if BattleUtils.IsPvp() and pvpSkillPath then
      self.ShakeResRequest = NRCResourceManager:LoadResAsync(self, pvpSkillPath, 255, self.resCacheTime, function(caller, resRequest, asset)
        self:OnPvpClassLoad(asset, pvpPlayerPerformData, pvpPlayerPerformData.type)
      end, function(caller, resRequest, errMsg)
      end)
    end
  end
end

function BattleManager:OnPvpClassLoad(skillClass, pvpPlayerPerformData, Type)
  if not skillClass then
    return
  end
  local MyPlayer = self.battlePawnManager:GetPlayerMyTeam()
  local EnemyPlayer = self.battlePawnManager:GetPlayerEnemyTeam()
  if not MyPlayer or not EnemyPlayer then
    return
  end
  local caster, target
  if MyPlayer.guid == pvpPlayerPerformData.uin then
    caster = MyPlayer.model
    target = EnemyPlayer.model
  elseif EnemyPlayer.guid == pvpPlayerPerformData.uin then
    caster = EnemyPlayer.model
    if 1 == Type or 3 == Type then
      target = nil
    else
      target = MyPlayer.model
    end
  else
    return
  end
  if not caster or not UE.UObject.IsValid(caster) then
    return
  end
  local SkillComponent = caster.RocoSkill
  MyPlayer:StopAll()
  SkillComponent:ClearAllPassiveSkillObjs()
  local Skill = SkillComponent:AddSkillObjFromClassAndReturn(skillClass)
  if Skill then
    Skill:SetCaster(caster)
    if target then
      Skill:SetTargets({target})
    end
    Skill:SetPassive(true)
    SkillComponent:LoadAndPlaySkill(Skill)
  end
end

function BattleManager:OnBattlePerformNotify(notify)
  if not self.isInBattle then
    Log.Error("BattleManager:OnBattlePerformNotify: battle dont start")
    return
  end
  self:SetSeqNumber(notify.perform_cmd.seq_num)
  Log.Debug("zgx BattleStreamLog  ReceivePacket  PacketName:ZoneBattlePerformStartNotify", notify.perform_cmd.round)
  if BattleUtils.IsTeam() then
    self:CheckIsMySelfPerformTeamBattle(notify)
    local performCmd = notify and notify.perform_cmd
    local IsFromRoundStart = performCmd and performCmd.IsFromRoundStart
    if not IsFromRoundStart then
      self:UpdateBloodPetSkills(notify.perform_cmd.blood_pet_skills, notify.perform_cmd.round)
    end
    self.LastSequencePerformNotify = notify
    local data = {}
    data.type = BattleManager.PerformType
    data.notify = notify
    table.insert(self.TeamBattleNotifyQueue, data)
    self:TryStartTeamBattlePerform()
  else
    self:SyncCurRound(notify.perform_cmd.round)
    local performCmd = notify and notify.perform_cmd
    local IsFromRoundStart = performCmd and performCmd.IsFromRoundStart
    if not IsFromRoundStart then
      self.battleInfoManager:ClearAllExpiredPushPopInfoForPerformStart(notify.perform_cmd.round)
    end
    self:BattlePerformSync(notify)
  end
end

function BattleManager:TeamBattlePerformFinish(cmds)
  BattleBudget:Pause()
  if self.CurTeamBattlePerformNotify and self.CurTeamBattlePerformNotify.perform_cmd == cmds then
    if #self.TeamBattleNotifyQueue > 0 then
      table.remove(self.TeamBattleNotifyQueue, 1)
      local data = self.TeamBattleNotifyQueue[1]
      if data and data.type == BattleManager.RoundType then
        table.remove(self.TeamBattleNotifyQueue, 1)
        self:SyncRoundStartData(data.notify)
        if self.CurTeamBattlePerformNotify.NeedChangeState or self:CheckTeamSupplyPet() or BattleUtils.IsStoryTeam() or data.notify.state_type == _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_CATCH then
          self:GoToRoundStartNextState(data.notify)
        end
      end
    end
    self.CurTeamBattlePerformNotify = nil
    self:TryStartTeamBattlePerform()
  end
end

function BattleManager:TryStartTeamBattlePerform()
  if not self.CurTeamBattlePerformNotify and #self.TeamBattleNotifyQueue > 0 then
    if not self.teamBattlePerformFsm then
      self.teamBattlePerformFsm = InstantBattleFsm()
    end
    local data = self.TeamBattleNotifyQueue[1]
    local notify = data and data.notify
    local type = data and data.type
    local performCmd = notify and notify.perform_cmd
    local round = performCmd and performCmd.round
    local IsFromRoundStart = performCmd and performCmd.IsFromRoundStart
    local IsSelfPerform = notify and notify.IsSelfPerform
    while data and data.type == BattleManager.RoundType do
      table.remove(self.TeamBattleNotifyQueue, 1)
      self:SyncRoundStartData(data.notify)
      self:GoToRoundStartNextState(data.notify)
      if #self.TeamBattleNotifyQueue > 0 then
        data = self.TeamBattleNotifyQueue[1]
      else
        data = nil
        break
      end
    end
    if type == BattleManager.PerformType and not IsFromRoundStart then
      self.battleInfoManager:ClearAllExpiredPushPopInfoForPerformStart(round)
    end
    if type == BattleManager.PerformType and IsFromRoundStart and round then
      local isInitRound = round == self.battleRuntimeData.roundIndex and self.curRound ~= round
      local oldRound = self.curRound
      self:SyncCurRound(round)
      local bloodPetSkills = notify.perform_cmd and notify.perform_cmd.blood_pet_skills
      self:_TeamBattleChooseSkill(isInitRound, oldRound, bloodPetSkills)
    end
    if data then
      self.CurTeamBattlePerformNotify = data.notify
      if self:CheckCanPerform(data.notify) then
        if data.notify.IsSelfPerform then
          self:BattlePerformSync(data.notify)
        else
          self:BattlePerformAsync(data.notify)
        end
      else
        self:TeamBattlePerformFinish(data.notify.perform_cmd)
      end
    end
  end
end

function BattleManager:BattlePerformSync(notify)
  if not notify.flow_data then
    notify.flow_data = {
      flow = {}
    }
  end
  if self.AIRound <= self.curRound then
    self.AIRound = self.AIRound + 1
  end
  if _G.DebugForceEvolution then
    for i = 1, #notify.flow_data.flow do
      local perform_cmd = notify.flow_data.flow[i].perform_cmd
      if perform_cmd then
        Log.Dump(perform_cmd)
        if perform_cmd.is_battle_finished and notify.settle_info then
          Log.Debug("\229\188\186\229\136\182\228\191\174\230\148\185\230\149\176\230\141\174")
          notify.settle_info.is_evolution_complete = true
          notify.settle_info.evolution_base_id = 3007
        end
      end
    end
  end
  _G.BattleEventCenter:Dispatch(BattleEvent.MULTI_PLAYER_TIP_CHANGE)
  self.stateFsm:SetProperty("Flows", notify.perform_cmd)
  self.stateFsm:SetProperty("SettleInfo", notify.settle_info)
  self.stateFsm:SetProperty("IsMySelfPerform", true)
  self.stateFsm:SetProperty("IsFromRoundStart", notify.perform_cmd.IsFromRoundStart or false)
  self.stateFsm:Resume()
  self.stateFsm:SendEvent(BattleEvent.EnterRoundPlay)
end

function BattleManager:BattlePerformAsync(notify)
  if not notify.flow_data then
    notify.flow_data = {
      flow = {}
    }
  end
  if self.AIRound <= self.curRound then
    self.AIRound = self.AIRound + 1
  end
  self.teamBattlePerformFsm:Stop()
  self.teamBattlePerformFsm:SetProperty("Flows", notify.perform_cmd)
  self.teamBattlePerformFsm:SetProperty("SettleInfo", notify.settle_info)
  self.teamBattlePerformFsm:SetProperty("NpcDelay", false)
  self.teamBattlePerformFsm:SetProperty("IsSelfPerform", notify.IsSelfPerform)
  self.teamBattlePerformFsm:SetProperty("IsFromRoundStart", notify.perform_cmd.IsFromRoundStart or false)
  self.teamBattlePerformFsm:Play()
end

function BattleManager:OnBattleEmojiNotify(notify)
  local player = self.battlePawnManager:GetPlayerByGuid(notify.src_uin)
  local animName = _G.DataConfigManager:GetBattleGlobalConfig("battle_trainer_action_boy_" .. tostring(notify.emoji)).str
  local path = _G.DataConfigManager:GetBattleGlobalConfig("battle_trainer_emoji" .. tostring(notify.emoji)).str
  player.model:PlayAnimByName(animName, 1, 0, 0, 0, 1)
  player.model:ShowEmoji(path, player.teamEnm, 1.5)
end

function BattleManager:OnBattleAISelectSkillNotify(notify)
  local pet = BattleUtils.GetPetWithID(notify.pet_id)
  local uin = BattleUtils.GetPlayerUin()
  if pet then
    if uin == notify.skill_info.uin then
      pet.card.petInfo.battle_inside_pet_info.ai_skill_info = {
        notify.skill_info
      }
    end
    if BattleUtils.IsPve() and pet.player then
      pet.player.IsShowSkillPrediction = false
      pet.player:UpdateSkillPrediction()
    end
  end
end

function BattleManager:OnBattlePlayerLeaveNotify(notify)
  Log.Debug("zgx BattleStreamLog  ReceivePacket  PacketName:BattlePlayerLeaveNotify")
  self:SetSeqNumber(notify.seq_num)
  local player = self.battlePawnManager:GetPlayerByGuid(notify.player_uin)
  if player == self.battlePawnManager.TeamatePlayer then
    return
  end
  if player == self.battlePawnManager.EnemyPlayer and BattleUtils.IsPvp() then
    return
  end
  if player then
    player:RunAwayBattle(notify.reason)
  end
end

function BattleManager:OnBattlePKAgainNotify(notify)
  local player = self.battlePawnManager:GetPlayerByGuid(notify.uin)
  if player then
    if notify.pk_again then
      player.roleInfo.base.state_bit = player.roleInfo.base.state_bit | 1 << ProtoEnum.BATTLER_BIT_TYPE.BT_BATTLER_PK_AGAIN
    end
    _G.BattleEventCenter:Dispatch(BattleEvent.PK_AGAIN, notify)
  else
    Log.Warning("[#warning:W004]zgx there is no player ", notify.uin)
  end
end

function BattleManager:ResetBattleState(notify)
  local playerInfo = _G.DataModelMgr.PlayerDataModel:GetPlayerInfo()
  if playerInfo and playerInfo.brief_info and playerInfo.brief_info.battle_brief then
    playerInfo.brief_info.battle_brief.battle_state = 0
  end
  NRCEventCenter:DispatchEvent(BattleEvent.BattleStateOver)
end

function BattleManager:OnBattleFinishNotify(notify)
  Log.Debug("zgx BattleStreamLog  ReceivePacket  PacketName:ZoneBattleFinishNotify", notify.settle_info.result)
  self:SetPlayerDataModelBattleState(0)
  if not self.isInBattle then
    Log.Error("[#error:E001]zgx BattleManager:OnBattleFinishNotify: battle dont start")
    return
  end
  _G.NRCModuleManager:DoCmd(MainUIModuleCmd.SetThrowHitTestInvisible, false)
  local isLogin = _G.NRCModuleManager:DoCmd(_G.OnlineModuleCmd.GetLoginState)
  if isLogin then
    local player = _G.NRCModuleManager:DoCmd(_G.PlayerModuleCmd.GET_LOCAL_PLAYER)
    if player then
      player:AddBattleFinishChecker(notify)
      if player.viewObj then
        local playPosition = player:GetActorLocation()
        playPosition.Z = playPosition.Z + player.viewObj:GetHalfHeight()
        UE4.UNRCStatics.PinActorOnGround(nil, player.viewObj, playPosition, player.viewObj)
      end
    end
  end
  if notify.settle_info.catch_info then
    _G.DataModelMgr.PlayerDataModel:UpdateCatchInfo(notify.settle_info.catch_info)
  end
  self:RevertWorldPlayer()
  self.battleRuntimeData.battleSettleData:SetData(notify)
  self.battleRuntimeData:SetRestartInfo(notify)
  if self.battleRuntimeData.battleType == ProtoEnum.BattleType.BT_LEADERFIGHT and self.battleRuntimeData.battleSettleData:BattleResult() == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_WIN_DEFEAT then
    _G.NRCModuleManager:DoCmd(TipsModuleCmd.Tips_ShowPropTips, TipObject.FromLeaderFight(notify, TipEnum.TipObjectType.LeaderFight), ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_FINISH_NOTIFY)
  end
  self.EscapeContext:Close()
  local battleCraneCamera = _G.BattleManager.vBattleField.battleCraneCamera
  if battleCraneCamera then
    battleCraneCamera:StopShake(true)
  end
  _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_STATE_SETTLEMENT)
  self.stateFsm:Resume()
  local battleRuntimeData = self.battleRuntimeData
  if BattleUtils.IsWatchingBattle() and not BattleUtils.IsPvp() then
    self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
  elseif BattleUtils.IsPvp() then
    if BattleUtils.IsWatchingBattle() then
      self.stateFsm:SendEvent(BattleEvent.EnterPVPOver)
    elseif BattleUtils.IsPvpRank() or BattleUtils.IsPvpStandard() then
      self.stateFsm:SendEvent(BattleEvent.EnterPVPRankOver)
    else
      self.stateFsm:SendEvent(BattleEvent.EnterPVPOver)
    end
  elseif BattleUtils.ContainTaskPerformControl(Enum.TaskBattlePerformanceControl.TBPC_EXIT_BLACK) then
    self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
  elseif BattleUtils.IsNpcChallenge() then
    self.stateFsm:SendEvent(BattleEvent.EnterNpcChallengeOver)
  elseif BattleUtils.IsTerritoryTrialBattle() then
    self.stateFsm:SendEvent(BattleEvent.EnterTerritoryTrialOver)
  elseif BattleUtils.IsWeeklyChallenge() then
    self.stateFsm:SendEvent(BattleEvent.EnterWeeklyChallengeOver)
  elseif BattleUtils.IsTrainBattle() then
    self.stateFsm:SendEvent(BattleEvent.EnterTrainBattleOver)
  elseif BattleUtils.IsWatchingBroadcastBattle(battleRuntimeData) then
    self.stateFsm:SendEvent(BattleEvent.EnterShowDownGuessOver)
  elseif BattleUtils.IsLeaderChallenge() then
    local battleResult = self.battleRuntimeData.battleSettleData:BattleResult()
    if battleResult == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_RUNAWAY then
      if self:GetLeaderChallengeGiveUp() then
        self.stateFsm:SendEvent(BattleEvent.EnterNpcChallengeOver)
      else
        self.stateFsm:SendEvent(BattleEvent.EnterRunAwayLeadFight)
      end
      self:SetLeaderChallengeGiveUp(flase)
    elseif battleResult == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_LOSE or battleResult == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_LOSE_HP then
      if self.battleRuntimeData.battleSettleData:GetBattleSettleRemainHp() > 0 then
        self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
      else
        self.stateFsm:SendEvent(BattleEvent.EnterNpcChallengeOver)
      end
    elseif battleResult == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_WIN_DEFEAT or battleResult == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_WIN then
      self.stateFsm:SendEvent(BattleEvent.EnterNpcChallengeOver)
    else
      self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
    end
  elseif BattleUtils.IsBloodTeam() then
    self.stateFsm:SendEvent(BattleEvent.EnterBloodTeamBattleOver)
  elseif BattleUtils.IsBeastTeam() then
    self.stateFsm:SendEvent(BattleEvent.EnterBeastTeamBattleOver)
  elseif BattleUtils.IsStoryTeam() then
    self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
  elseif BattleExitHelper.IsPlayerSkillEscape() then
    BattleExitHelper.ClearPlayerSkillEscape()
    self.stateFsm:SendEvent(BattleEvent.EnterPlayerSkillEscape)
  elseif self.battleRuntimeData.battleSettleData:BattleResult() == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_WIN_CATCH then
    self.stateFsm:SendEvent(BattleEvent.EnterCatchSuccess)
  elseif BattleExitHelper.IsFinishHandleSeamless() then
    BattleExitHelper.ClearFinishHandleSeamless()
    _G.BattleEventCenter:Dispatch(BattleEvent.GetBattleFinish)
    if self.stateFsm and (self:CheckActiveState(BattleEnum.StateNames.Standby) or self.stateFsm:GetNextStateName() == BattleEnum.StateNames.Standby) then
      self.stateFsm:SendEvent(BattleEvent.DirectOverBattle)
    end
  elseif BattleUtils.IsBadgeChallenge() then
    self.stateFsm:SendEvent(BattleEvent.EnterBadge2DOver)
  elseif self.battleRuntimeData.battleSettleData:BattleResult() == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_MONSTER_RUNAWAY then
    if BattleUtils.IsPve() then
      self.stateFsm:SendEvent(BattleEvent.EnterEnemyNpcEscape)
    else
      self:ShowEscapeTip()
      self.stateFsm:SendEvent(BattleEvent.EnterEnemyEscape)
    end
  elseif BattleUtils.IsWorldLeaderFight() then
    if self.battleRuntimeData.battleSettleData:BattleResult() == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_RUNAWAY then
      self.stateFsm:SendEvent(BattleEvent.EnterRunAwayLeadFight)
    elseif self.battlePawnManager:IsSkipWorldLeaderSeamless() then
      if BattleUtils.CheckIsNeedTeleport() then
        self.stateFsm:SendEvent(BattleEvent.EnterFailOver)
      else
        self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
      end
    else
      self.stateFsm:SendEvent(BattleEvent.EnterWorldLeaderSeamlessOver)
    end
  elseif BattleExitHelper.IsFinishPveSeamless() then
    BattleExitHelper.ClearFinishPveSeamless()
    self.stateFsm:SendEvent(BattleEvent.DirectOverBattle)
  elseif self.battleRuntimeData.battleSettleData:BattleResult() == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_LOSE_HP or self.battleRuntimeData.battleSettleData:BattleResult() == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_LOSE or self.battleRuntimeData.battleSettleData:BattleResult() == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_RUNAWAY then
    if BattleUtils.CheckIsNeedTeleport() then
      self.stateFsm:SendEvent(BattleEvent.EnterFailOver)
    else
      self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
    end
  elseif BattleUtils.IsFinalBattleP2() then
    if (notify.settle_info.result == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_WIN or notify.settle_info.result == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_WIN_DEFEAT or notify.settle_info.result == ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_WIN_HP) and _G.ProtoMessage.newHasP2Win then
      local List = _G.ProtoMessage:newHasP2Win()
      List.HasWin = 1
      _G.DataModelMgr.RemoteStorage:Set("HasP2Win", ".Next.HasP2Win", List)
    end
    self.stateFsm:SendEvent(BattleEvent.ExitBattle)
  elseif BattleUtils.IsB1FinalBattleP3() then
    self.stateFsm:SendEvent(BattleEvent.ExitBattle)
  else
    Log.Debug("BattleManager:OnBattleFinishNotify NormalOver")
    self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
  end
  _G.NRCSDKManager:SetLeaveBattle()
end

function BattleManager:OnBattleForceFinishNotify(notify)
  self:SetPlayerDataModelBattleState(0)
  if self.isInBattle and self.stateFsm and not self:GetLeaderChallengeGiveUp() then
    if BattleUtils.IsWatchingBattle() then
      local observedBattleEndStringConfig = _G.DataConfigManager:GetBattleGlobalConfig("observed_battle_end_tip")
      local observedBattleEndString = observedBattleEndStringConfig and observedBattleEndStringConfig.str or ""
      _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, observedBattleEndString, 3)
    end
    self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
  end
end

function BattleManager:OnBattleObserverChangeNotify(notify)
  if not self.isInBattle then
    return
  end
  if not notify.enter_observer then
    notify.enter_observer = {}
  end
  if not notify.leave_observer then
    notify.leave_observer = {}
  end
  _G.NRCModeManager:DoCmd(_G.BattleUIModuleCmd.HandleObserverChangeNotify, notify)
  _G.BattleEventCenter:Dispatch(BattleEvent.PVP_OBSERVER_CHANGE, notify.enter_observer)
  local fashionInfoList = notify.observer_appearance_info or {}
  self.battlePawnManager:SetBattlePlayerInspectorData(fashionInfoList)
end

function BattleManager:OnBattleObserverKickedOutNotify(notify)
  self:SetPlayerDataModelBattleState(0)
  if self.isInBattle then
    if self.stateFsm then
      self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
    end
    local kickOutStringConfig = _G.DataConfigManager:GetBattleGlobalConfig("pvp_battlewatch_character3")
    local kickOutString = kickOutStringConfig and kickOutStringConfig.str or ""
    _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, kickOutString, 3)
  end
end

function BattleManager:OnBattleLiveDanmuNty(notify)
  local items = notify and notify.items or DummyTable
  local bulletCommentsItemDataList = {}
  for i, item in ipairs(items) do
    local content = item and item.content
    if not string.IsNilOrEmpty(content) then
      local danmakuEmojiConfigId = tonumber(content)
      if danmakuEmojiConfigId then
        local itemData = {}
        itemData.danmakuEmojiConfigId = danmakuEmojiConfigId
        itemData.sendTimeMs = item and item.send_time_ms
        table.insert(bulletCommentsItemDataList, itemData)
      end
    end
  end
  _G.NRCModuleManager:DoCmd(BattleUIModuleCmd.AddBulletComments, bulletCommentsItemDataList)
end

function BattleManager:OnActivityShowDownChangeNotify(notify)
  local isInBattle = self:IsInBattle()
  if isInBattle then
    local runtimeData = self.battleRuntimeData
    if runtimeData then
      local _, nextState = runtimeData:GetCurrAndNextState()
      nextState.showDownGuessSettleInfo = notify
      runtimeData:SetState(nextState)
    end
  end
end

function BattleManager:ShowEscapeTip()
  local pets = self.battlePawnManager:GetAllPets()
  if pets then
    for _, pet in pairs(pets) do
      if pet.teamEnm == BattleEnum.Team.ENUM_ENEMY and pet.card.hp > 0 then
        _G.NRCModuleManager:DoCmd(TipsModuleCmd.TopHud_ShowTips, string.format(_G.LuaText.battle_escape_tip, pet.card.name), 3)
        break
      end
    end
  end
end

function BattleManager:RevertWorldPlayer()
  if self.WorldPlayerInitPos then
    local localPlayer = _G.NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
    localPlayer:SetActorLocation(self.WorldPlayerInitPos)
    localPlayer.viewObj:SetActorTickEnabled(true)
    self.WorldPlayerInitPos = nil
  end
end

function BattleManager:OnWorldPrepared(isRelogin)
  Log.Debug("zgx BattleManager:OnWorldPrepared", self.isInBattle, self.stateFsm)
  if self.isInBattle and self.stateFsm then
    BattleUtils.UnLockCam()
    local dataModelMgr = _G.DataModelMgr
    local playerDataModel = dataModelMgr and dataModelMgr.PlayerDataModel
    local isBattle = playerDataModel and playerDataModel:GetPlayerIsInBattle()
    Log.Debug("zgx BattleManager:OnWorldPrepared isBattle:", isBattle)
    if not isBattle then
      Log.Warning("BattleManager \229\164\132\228\186\142\230\136\152\230\150\151\228\184\173\239\188\140\228\189\134\230\156\141\229\138\161\229\153\168\231\138\182\230\128\129\229\183\178\232\132\177\231\166\187\230\136\152\230\150\151  \233\156\128\232\166\129\229\188\186\232\161\140\233\148\128\230\175\129BattleManager")
      Log.Debug("BattleManager:OnWorldPrepared isBattle Resume")
      if self.stateFsm then
        local activeStateName = self.stateFsm:GetActiveStateName()
        if "FinalBattleOver" == activeStateName then
          return
        end
      end
      self.stateFsm:Resume()
      self.stateFsm:SendEvent(BattleEvent.EnterNormalOver)
    elseif self.TeleportBackPos then
      local teleportBattleCenter = self.battleRuntimeData.TeleportBattleCenter
      local localPlayer = _G.NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
      if teleportBattleCenter and localPlayer then
        local currentPlayerLocation = localPlayer:GetActorLocation()
        local FVector = UE.FVector
        local currentPlayerDistanceFromBattleCenter = FVector.Dist(currentPlayerLocation, teleportBattleCenter)
        if currentPlayerDistanceFromBattleCenter > 500 then
          localPlayer:SetActorLocation(teleportBattleCenter)
        end
      end
    end
  end
end

function BattleManager:InitBattleEvent()
end

function BattleManager:ChangeOperateMode(enum)
  Log.Debug("BattleManager:ChangeOperateMode", enum)
  NRCModuleManager:DoCmd(BattleUIModuleCmd.ChangeOperateMode, enum)
  self.battleRuntimeData.operateType = enum
end

function BattleManager:GetCurrentStateName()
  if not self.stateFsm then
    return ""
  end
  return self.stateFsm:GetActiveStateName()
end

function BattleManager:GetCurRound()
  return self.curRound
end

function BattleManager:GetRoundStartRecord()
  return self.RoundStartRecord
end

function BattleManager:OnLogout()
  if self.battleNetManager then
    self.battleNetManager:ClearCachedNotify()
  end
end

function BattleManager:IsInBattle(onlyClient)
  if self.isInBattle or onlyClient then
    return self.isInBattle
  end
  if self.stateFsm then
    return true
  end
  if _G.DataModelMgr and _G.DataModelMgr.PlayerDataModel then
    local playerInfo = _G.DataModelMgr.PlayerDataModel:GetPlayerInfo()
    if playerInfo and playerInfo.brief_info and playerInfo.brief_info.battle_brief and playerInfo.brief_info.battle_brief.battle_state and playerInfo.brief_info.battle_brief.battle_state > 0 then
      return true
    end
  end
  return false
end

function BattleManager:GetCraneCamera()
  return self.vBattleField.CraneCamera
end

function BattleManager:GetAidRotationCam()
  return self.vBattleField.AidRotationCam
end

function BattleManager:GetEnvComponent()
  local World = _G.UE4Helper.GetCurrentWorld()
  local foundActors = UE4.UGameplayStatics.GetAllActorsOfClassWithTag(World, UE4.AEnvSystemActor, "EnvActorCraneCamera")
  if 0 == foundActors:Length() then
    return nil
  end
  local envActor = foundActors:Get(1)
  return envActor:GetComponentByClass(UE.UPostProcessComponent)
end

function BattleManager:OpenDepthCfg(DepthOfFieldScale, DepthOfFieldNear, DepthOfFieldFar)
  local ProcessComp = self:GetEnvComponent()
  if not ProcessComp then
    return
  end
  local PostProcessSettings = ProcessComp.Settings
  PostProcessSettings.bOverride_MobileHQGaussian = true
  PostProcessSettings.bMobileHQGaussian = true
  PostProcessSettings.bOverride_DepthOfFieldFocalRegion = true
  PostProcessSettings.DepthOfFieldFocalRegion = 1000
  PostProcessSettings.bOverride_DepthOfFieldNearTransitionRegion = true
  PostProcessSettings.DepthOfFieldNearTransitionRegion = DepthOfFieldNear or 500
  PostProcessSettings.bOverride_DepthOfFieldFarTransitionRegion = true
  PostProcessSettings.DepthOfFieldFarTransitionRegion = DepthOfFieldFar or 3000
  PostProcessSettings.bOverride_DepthOfFieldScale = true
  PostProcessSettings.DepthOfFieldScale = DepthOfFieldScale or 0.25
  PostProcessSettings.bOverride_DepthOfFieldNearBlurSize = true
  PostProcessSettings.DepthOfFieldNearBlurSize = 0
  PostProcessSettings.bOverride_DepthOfFieldFarBlurSize = true
  PostProcessSettings.DepthOfFieldFarBlurSize = 15
  PostProcessSettings.bOverride_DepthOfFieldOcclusion = true
  PostProcessSettings.DepthOfFieldOcclusion = 0.4
end

function BattleManager:CloseDepthCfg()
  local ProcessComp = self:GetEnvComponent()
  if not ProcessComp then
    return
  end
  ProcessComp.EnableDepthOfField = false
  local PostProcessSettings = ProcessComp.Settings
  PostProcessSettings.bOverride_MobileHQGaussian = false
  PostProcessSettings.bOverride_DepthOfFieldFocalRegion = false
  PostProcessSettings.bOverride_DepthOfFieldNearTransitionRegion = false
  PostProcessSettings.bOverride_DepthOfFieldNearBlurSize = false
  PostProcessSettings.bOverride_DepthOfFieldScale = false
  PostProcessSettings.bOverride_DepthOfFieldNearBlurSize = false
  PostProcessSettings.bOverride_DepthOfFieldFarBlurSize = false
  PostProcessSettings.bOverride_DepthOfFieldOcclusion = false
end

function BattleManager:FocusRocoCamera()
  BattleUtils.FocusPlayer()
end

function BattleManager:CheckPvpRoundLimit(RoundLimit)
  if RoundLimit and 0 ~= RoundLimit then
    local key = "pvp_ddl_tips" .. RoundLimit
    local strConf = _G.DataConfigManager:GetLocalizationConf(key, true)
    local str = strConf and strConf.msg or ""
    if str and string.len(str) > 0 then
      _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.OpenBattle_Round_StartAndDisplayRestRound, RoundLimit)
    end
  end
end

function BattleManager:GetPvpRoundLimit()
  return self.battleRuntimeData.pvpRoundLimit
end

function BattleManager.BattleLightSwitch(LevelName)
  if string.len(LevelName) > 0 then
    _G.NRCModuleManager:DoCmd(_G.SceneModuleCmd.SwitchDynamicLevel, LevelName)
  end
end

function BattleManager.ChangeCameraTagInG6Editor(TeamPets, EnemyPets, TeamPlayers, EnemyPlayers, PreviewCameraActor, CameraTag, CenterLocation, EditorWorld)
  local G6Actors = {
    TeamPets = {},
    EnemyPets = {},
    TeamPlayers = {},
    EnemyPlayers = {},
    PreviewCameraActor = PreviewCameraActor,
    CenterLocation = CenterLocation
  }
  for i = 1, TeamPets:Length() do
    local pet = TeamPets:Get(i)
    if pet then
      table.insert(G6Actors.TeamPets, pet)
    end
  end
  for i = 1, EnemyPets:Length() do
    local pet = EnemyPets:Get(i)
    if pet then
      table.insert(G6Actors.EnemyPets, pet)
    end
  end
  for i = 1, TeamPlayers:Length() do
    local pet = TeamPlayers:Get(i)
    if pet then
      table.insert(G6Actors.TeamPlayers, pet)
    end
  end
  for i = 1, EnemyPlayers:Length() do
    local pet = EnemyPlayers:Get(i)
    if pet then
      table.insert(G6Actors.EnemyPlayers, pet)
    end
  end
  local BattleCraneCamera = require("NewRoco.Modules.Core.Battle.CraneCamera.BattleCraneCamera")
  local battleCraneCamera = BattleCraneCamera()
  battleCraneCamera:InitEffectValueFuncMap()
  local endPos, Dir, fov, SpringArmLength = battleCraneCamera:ResetCameraInG6SkillEditor(G6Actors, CameraTag)
  return endPos.X, endPos.Y, endPos.Z, Dir.Pitch, Dir.Yaw, Dir.Roll, fov, SpringArmLength
end

function BattleManager:GetBattleNpcChallengeInfo()
  return self.battleRuntimeData:GetBattleNpcChallengeInfo()
end

function BattleManager:ReturnCameraFromDialogue()
  local CraneCamera = self.vBattleField.battleCraneCamera
  if CraneCamera then
    local curStateName = self.stateFsm:GetActiveStateName()
    if BattleUtils.IsFinalBattleP1() and curStateName == BattleEnum.StateNames.PrePlay then
      CraneCamera:PetSelectIndexUpdate(2)
      CraneCamera:ChangeToPlayerPet(0)
    elseif curStateName == BattleEnum.StateNames.SwapPlay then
      if BattleUtils.IsFinalBattleP1() then
        if not _G.BattleManager.battleRuntimeData:GetFBP1IsSupplyEnd() then
          return
        end
        _G.BattleManager.battleRuntimeData:SetFBP1SupplyInfo(nil)
      end
      CraneCamera:PetSelectIndexUpdate(1)
      CraneCamera:ChangeToPlayerPet(0)
    else
      CraneCamera:ChangeToPlayerSkill(0)
    end
  end
end

function BattleManager:PreChangeCameraOnRoundPlayFinish()
  if BattleUtils.IsFinalBattleP1() and not self.CacheSequencer and self:CheckActiveState(BattleEnum.StateNames.PrePlay) then
    local CraneCamera = self.vBattleField.battleCraneCamera
    if CraneCamera then
      CraneCamera:PetSelectIndexUpdate(2)
      CraneCamera:ChangeToPlayerPet(0)
    end
  end
end

function BattleManager:SetLeaderChallengeGiveUp(State)
  self.LeaderChallengeGiveUp = State
end

function BattleManager:SetPlayerDataModelBattleState(state)
  local playerInfo = _G.DataModelMgr.PlayerDataModel:GetPlayerInfo()
  if playerInfo and playerInfo.brief_info and playerInfo.brief_info.battle_brief then
    playerInfo.brief_info.battle_brief.battle_state = state
  end
end

function BattleManager:GetLeaderChallengeGiveUp()
  return self.LeaderChallengeGiveUp
end

function BattleManager.GetIsInBattle()
  return BattleManager:IsInBattle()
end

function BattleManager:SetQuicklyCatch(value, changeCamera)
end

function BattleManager:SetProperty(name, value)
  if not self.cacheFsmValue then
    self.cacheFsmValue = {}
  end
  self.cacheFsmValue[name] = value
end

function BattleManager:ClearProperty()
  self.cacheFsmValue = {}
end

function BattleManager:StartFocus(SceneCharacter, isBack, aiStatus)
  if _G.EnableSpeedUpNearbyEnterPreview then
    _G.NRCEventCenter:DispatchEvent(BattleEvent.BattleStartFocus)
    if not self.focusPet then
      local BattleThrowBallEnterFocusPet = require("NewRoco.Modules.Core.Battle.Scene.BattleThrowBallEnterFocusPet")
      self.focusPet = BattleThrowBallEnterFocusPet()
      self.focusPet:DoFocus(SceneCharacter, isBack, aiStatus)
    else
      self.focusPet:DoFocus(SceneCharacter, isBack, aiStatus)
    end
  end
end

function BattleManager:StopFocus()
  if self.focusPet then
    self.focusPet:releaseFocus()
  end
end

function BattleManager:StopFocusTimer()
  if self.focusPet then
    self.focusPet:StopTimer()
  end
end

function BattleManager:PauseFocusTimer()
  if self.focusPet then
    self.focusPet:PauseTimer()
  end
end

function BattleManager:ResumeFocusTimer()
  if self.focusPet then
    self.focusPet:ResumeTimer()
  end
end

function BattleManager:IsFocusingPet()
  if self.focusPet then
    return self.focusPet:IsFocusing()
  end
  return false
end

function BattleManager:StopFocusTimeout()
  if self.focusPet then
    self.focusPet.timeoutCounter:Stop()
  end
end

function BattleManager:SetSeqNumber(value)
  if not value then
    return
  end
  self.ClientSeqNumber = value
end

function BattleManager:GetSeqNumber()
  return self.ClientSeqNumber
end

function BattleManager:SetReceiveSeqNumber(value)
  if not value then
    return
  end
  self.ReceiveSeqNumber = value
  BattleEventCenter:Dispatch(BattleEvent.RECEIVE_SERVER_SEQ, value)
end

function BattleManager:GetReceiveSeqNumber()
  return self.ReceiveSeqNumber
end

function BattleManager:SaveCraneCameraTemporaryPosData()
  if _G.BattleManager.vBattleField.battleCraneCamera then
    _G.BattleManager.vBattleField.battleCraneCamera:CacheTemporaryPosData()
  end
end

function BattleManager:ClearCraneCameraTemporaryPosData()
  if _G.BattleManager.vBattleField.battleCraneCamera then
    _G.BattleManager.vBattleField.battleCraneCamera:CacheTemporaryPosData()
  end
end

function BattleManager:CheckSeqNumber(serverSeqNumber)
  if not serverSeqNumber or not self.ClientSeqNumber then
    return false
  end
  if serverSeqNumber < self.ClientSeqNumber then
    Log.Error("[#error:E001]zgx \230\150\173\231\186\191\233\135\141\232\191\158 \229\143\145\231\148\159\228\184\165\233\135\141\233\148\153\232\175\175!!!")
  end
  return serverSeqNumber == self.ClientSeqNumber
end

function BattleManager:IsReceiveNextProcessSeq()
  if not self.ReceiveSeqNumber or not self.ClientSeqNumber then
    return false
  end
  return self.ReceiveSeqNumber > self.ClientSeqNumber
end

return BattleManager
