local BattleEnum = require("NewRoco.Modules.Core.Battle.Common.BattleEnum")
local BattleConst = require("NewRoco.Modules.Core.Battle.Common.BattleConst")
local BattleUtils = require("NewRoco.Modules.Core.Battle.Common.BattleUtils")
local BattleSeasonUtils = require("NewRoco.Modules.Core.Battle.Common.BattleSeasonUtils")
local BattleStartParam = require("NewRoco.Modules.Core.Battle.Data.BattleStartParam")
local BattleExitParam = require("NewRoco.Modules.Core.Battle.Data.BattleExitParam")
local BattleSettleData = require("NewRoco.Modules.Core.Battle.Data.BattleSettleData")
local ServerData = require("Common.LocalServer.LocalBattleRSPTable")
local PlayerSkillData = require("NewRoco.Modules.Core.Battle.Data.PlayerSkillData")
local BattleNpc = require("NewRoco.Modules.Core.Battle.Entity.BattleNpc")
local BattleEvent = require("NewRoco.Modules.Core.Battle.Common.BattleEvent")
local StateCell = require("Common.StateCell")
local BattleRuntimeData = NRCClass()

function BattleRuntimeData:Ctor()
  self.battleStartParam = BattleStartParam()
  self.battleExitParam = BattleExitParam()
  self.battleSettleData = BattleSettleData()
  self.PlayerSkillManager = PlayerSkillData()
  self.battleMode = BattleEnum.BattleMode.Normal
  self.subBattleType = BattleEnum.SubBattleType.Single
  self.battleType = Enum.BattleType.BT_PVE
  self.enterBattleType = ProtoEnum.BattleEnterType.BET_CONTACT
  self.contactEnterType = BattleEnum.ContactEnterType.None
  self.operateType = BattleEnum.Operation.ENUM_NONE
  self.battle_id = 0
  self.roundIndex = 0
  self.pvpRoundLimit = 0
  self.seriesIndex = 0
  self.showRound = 0
  self.maxShowRound = 0
  self.catchInfo = nil
  self.fadeInfo = nil
  self.battleOnLookerInfo = nil
  self.observingInfo = nil
  self.finalBattleInfo = nil
  self.NearbyValidBattleLocation = nil
  self.teamBattleCenterTrans = nil
  self.NearbyValidBattleRotation = 0
  self.battleStartPlayerPos = nil
  self.battleStartEnemyPos = nil
  self.battleHideTreeDict = {}
  self.battleHideStaticMeshLst = {}
  self.battleHideNPCTypeObject = {}
  self.NpcIDs = nil
  self.backOperateType = BattleEnum.Operation.ENUM_NONE
  self.lastChangePetRoundIndex = 0
  self.startRoundSelectRoundIndex = 0
  self.zoneMap = nil
  self.petDeathAnimationPendingCnt = 0
  self.spEnergyElementList = {}
  self.evolutionPetName = nil
  self.evolutionResultName = nil
  self.evolutionAttrs = nil
  self.isEvolutionWaiting = false
  self.evolutionData = nil
  self.isWaitingRoleHP = false
  self.curWeatherID = nil
  self.curWeatherExpireRoundIndex = nil
  self.lastDeadNpcIdx = nil
  self.npc_escape = nil
  self.battleWaterType = ProtoEnum.WaterBattleType.WBT_NONE
  self.finalBattleData = nil
  self.b1PhantomPoint = 0
  self.cacheRidOfInfo = nil
  self.B1FBTempData = nil
  self.battleGrassInfo = {}
  self.widgetSpeed = {}
  self.widgetSpeed.MainWindowSubPanelItemOpenInterval = 0.04
  self.widgetSpeed.MainWindowSubPanelItemOpenAnimSpeedRate = 1
  self.widgetSpeed.TransmissionSpeedRate = 1
  self.widgetSpeed.RandomChangeSkillAnimSpeedRate = 1
  self.legendary_battle = nil
  self.legendary_battle_ticket_id = nil
  self.hpLevelInfo = {}
  local blood_pr_low = _G.DataConfigManager:GetBattleGlobalConfig("blood_pr_low")
  self.hpLevelInfo.BloodRedPercent = blood_pr_low.numList and blood_pr_low.numList[2] / 10000 or 0.2
  local blood_pr_middle = _G.DataConfigManager:GetBattleGlobalConfig("blood_pr_middle")
  self.hpLevelInfo.BloodYellowPercent = blood_pr_middle.numList and blood_pr_middle.numList[2] / 10000 or 0.5
  self.isObserver = false
  self.isBattleAgain = false
  self:InitMainWindowSubPanelItemOpenInterval()
  self:InitFantasticBackgroundPaths()
  self:InitStateCell()
end

function BattleRuntimeData:InitMainWindowSubPanelItemOpenInterval()
  do
    local intervalTimeConf = _G.DataConfigManager:GetBattleGlobalConfig("battle_interval_time")
    local numList = intervalTimeConf and intervalTimeConf.numList or {}
    local multiplier = BattleUtils.CalculateDividerByNumListFirstAndSecondItem(numList)
    self.widgetSpeed.MainWindowSubPanelItemOpenInterval = self.widgetSpeed.MainWindowSubPanelItemOpenInterval * multiplier
  end
  do
    local openSpeedConf = _G.DataConfigManager:GetBattleGlobalConfig("battle_duration_time")
    local numList = openSpeedConf and openSpeedConf.numList or {}
    local multiplier = BattleUtils.CalculateDividerByNumListFirstAndSecondItem(numList)
    self.widgetSpeed.MainWindowSubPanelItemOpenAnimSpeedRate = self.widgetSpeed.MainWindowSubPanelItemOpenAnimSpeedRate * multiplier
  end
  do
    local transmissionSpeedConf = _G.DataConfigManager:GetBattleGlobalConfig("battle_Transmission_speed")
    local numList = transmissionSpeedConf and transmissionSpeedConf.numList or {}
    local multiplier = BattleUtils.CalculateDividerByNumListFirstAndSecondItem(numList)
    self.widgetSpeed.TransmissionSpeedRate = self.widgetSpeed.TransmissionSpeedRate * multiplier
  end
  do
    local randomChangeSkillSpeedConf = _G.DataConfigManager:GetBattleGlobalConfig("battle_Random_speed")
    local numList = randomChangeSkillSpeedConf and randomChangeSkillSpeedConf.numList or {}
    local multiplier = BattleUtils.CalculateDividerByNumListFirstAndSecondItem(numList)
    self.widgetSpeed.RandomChangeSkillAnimSpeedRate = self.widgetSpeed.RandomChangeSkillAnimSpeedRate * multiplier
  end
end

function BattleRuntimeData:SetIsBattleAgain(v)
  self.isBattleAgain = v and true or false
end

function BattleRuntimeData:IsBattleAgain()
  return self.isBattleAgain == true
end

function BattleRuntimeData:InitFantasticBackgroundPaths()
  local fantasticBackgroundPathsDefault = {}
  local FantasticBackgroundPathsDefaults = BattleConst and BattleConst.FantasticBackgroundPathsDefaults
  local FantasticBackgroundPathsDefaultFirst = FantasticBackgroundPathsDefaults and FantasticBackgroundPathsDefaults[1]
  table.copy(FantasticBackgroundPathsDefaultFirst, fantasticBackgroundPathsDefault)
  local fantasticUi1Conf = _G.DataConfigManager:GetBattleGlobalConfig("fantastic_ui1", true)
  local fantasticUi1ConfStr = fantasticUi1Conf and fantasticUi1Conf.str
  local dataAssetPath = fantasticBackgroundPathsDefault and fantasticBackgroundPathsDefault.dataAssetPath
  dataAssetPath = fantasticUi1ConfStr or dataAssetPath
  fantasticBackgroundPathsDefault.dataAssetPath = dataAssetPath
  self.fantasticBackgroundPathsDefault = fantasticBackgroundPathsDefault
end

function BattleRuntimeData:GetInitState()
  local initState = {}
  return initState
end

function BattleRuntimeData:InitStateCell()
  local initState = self:GetInitState()
  local cell = StateCell()
  self.stateCell = cell
  local initOption = {}
  initOption.initState = initState
  initOption.maxFlushCount = 5
  initOption.debugName = "BattleRuntimeData"
  cell:Init(initOption)
  local unsubscribe = cell:Subscribe(function(s)
    return s
  end, function(prev, curr)
    self:OnStateChanged(prev, curr)
  end)
  self.unsubscribeStateChangeFn = unsubscribe
end

function BattleRuntimeData:GetStateCell()
  local stateCell = self.stateCell
  return stateCell
end

function BattleRuntimeData:GetCurrAndNextState()
  local stateCell = self:GetStateCell()
  if stateCell then
    local currState, nextState = stateCell:GetCurrAndNext()
    return currState, nextState
  end
  return {}, {}
end

function BattleRuntimeData:SetState(nextState)
  local stateCell = self:GetStateCell()
  if stateCell then
    stateCell:Set(nextState)
  end
end

function BattleRuntimeData:SubscribeStateChange(listener, notifyImmediately)
  local stateCell = self:GetStateCell()
  
  local function unsubscribeFn()
  end
  
  if stateCell then
    local options = {}
    options.notifyImmediately = notifyImmediately
    unsubscribeFn = stateCell:Subscribe(function(s)
      return s
    end, listener, options)
  end
  return unsubscribeFn
end

function BattleRuntimeData:SubscribeStateChangeWithSelector(selector, listener, options)
  local stateCell = self:GetStateCell()
  
  local function unsubscribeFn()
  end
  
  if stateCell then
    unsubscribeFn = stateCell:Subscribe(selector, listener, options)
  end
  return unsubscribeFn
end

function BattleRuntimeData:OnStateChanged(prevState, currState)
  Log.Info("BattleRuntimeData:OnStateChanged")
end

function BattleRuntimeData:SetBattleInitInfo(notify, isForbidResetData)
  if not isForbidResetData then
    self:Reset()
  end
  self.battleStartParam:SetBattleInitInfo(notify)
  _G.NRCModuleManager:DoCmd(_G.UpdateUIModuleCmd.SetBattleId, notify.init_info.battle_id)
  self.roundIndex = notify.round
  self.seriesIndex = notify.series_index or 0
  self.roundTime = notify.round_time
  self.isInActionTime = false
  self.NpcIDs = notify.npc_id
  self.ServerBattlePos = notify.battle_center
  self.ServerBattleRotate = notify.rotate
  self.ServerAvatarPt = notify.avatar_pt
  self.ServerNpcPt = notify.npc_pt
  self.battleWaterType = notify.water_battle_type
  self.max_round = notify.max_round
  self.legendary_battle = nil
  self.legendary_battle_ticket_id = nil
  self.battleCCMode = BattleSeasonUtils.GetEnemyCCModeByInitInfo(notify.init_info)
  if notify.init_info and notify.init_info.legendary_battle then
    self.legendary_battle = notify.init_info.legendary_battle
  end
  if notify.init_info and notify.init_info.player_team and notify.init_info.player_team[1] and notify.init_info.player_team[1].role_addi_info then
    self.legendary_battle_ticket_id = notify.init_info.player_team[1].role_addi_info.ticket_id
  end
  if notify.init_info and notify.init_info.observe_battle then
    self.isObserver = notify.init_info.observe_battle.is_observer
  else
    self.isObserver = false
  end
  if notify.npc_pt and self:CheckEnemyPosIsLegal(notify.npc_pt.pos) then
    if _G.UseNearbyLocationInsteadOfRealLocation then
      self.battleStartPlayerPos = NRCModeManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER).viewObj:Abs_K2_GetActorLocation()
    else
      self.battleStartPlayerPos = UE4.FVector(notify.avatar_pt.pos.x, notify.avatar_pt.pos.y, notify.avatar_pt.pos.z)
    end
    Log.Debug("UseNearbyLocationInsteadOfRealLocation:", UseNearbyLocationInsteadOfRealLocation, self.battleStartPlayerPos.X, self.battleStartPlayerPos.Y, self.battleStartPlayerPos.Z, notify.avatar_pt.pos.x)
    self.battleStartPlayerRotationYaw = not 0 and notify.avatar_pt.dir and notify.avatar_pt.dir.z / 10
    if _G.UseNearbyLocationInsteadOfRealLocation then
      self.battleStartEnemyPos = NRCModeManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER).viewObj:Abs_K2_GetActorLocation()
    else
      self.battleStartEnemyPos = UE4.FVector(notify.npc_pt.pos.x, notify.npc_pt.pos.y, notify.npc_pt.pos.z)
    end
    self.battleStartEnemyRotationYaw = not 0 and notify.npc_pt.dir and notify.npc_pt.dir.z / 10
    Log.Debug("BattleRuntimeData SetBattleInitInfo", self.battleStartPlayerPos, self.battleStartPlayerRotationYaw, self.battleStartEnemyPos, self.battleStartEnemyRotationYaw)
  else
    self.battleStartPlayerPos = NRCModeManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER).viewObj:Abs_K2_GetActorLocation()
    self.battleStartPlayerRotationYaw = 0
    self.battleStartEnemyPos = self.battleStartPlayerPos
    self.battleStartEnemyRotationYaw = 0
  end
  self.battleDebugEnemyPos = UE4.FVector(self.battleStartEnemyPos.X, self.battleStartEnemyPos.Y, self.battleStartEnemyPos.Z)
  local player = notify.init_info.player_team[1]
  local maxCatch = self.battleStartParam.battleCfg.use_ball_time or 0
  local catchTime = player and player.base.catch_counts or 0
  if not self.spEnergyElementList then
    self.spEnergyElementList = {}
  end
  self.catchInfo = {
    curUseBallId = 2,
    curUseBallGID = nil,
    curCatchTime = catchTime,
    maxCatchTime = maxCatch,
    catchedGid = {},
    catchInfo = nil,
    BackToCatch = false,
    lastCatchRatesClient = nil,
    lastCatchRatesServer = nil,
    IsGetColor = false,
    IsGetMemory = false,
    currentBallData = nil
  }
  self.fadeInfo = {
    enableCameraFadeRule = false,
    cameraFadeRuleId = nil,
    fadeObjectList = {}
  }
  self.battleOnLookerInfo = {
    onLookersSpawnExecuted = false,
    isOnLookersSpawnStarted = false,
    isOnLookerIdleAnimationStarted = false,
    OnLookersIdleAnimTimerHandlerMap = {}
  }
  self.observingInfo = {
    ObserverBriefInfoList = {},
    lastOperationType = nil
  }
  self.finalBattleInfo = {
    bossDeadBlackScreenSkillObject = nil,
    bossDeadBlackScreenSkillObjectRef = nil,
    isBossDead = false
  }
  self.specialMoveInfoList = {}
  self.resultUiState = {}
  if notify.init_info.observe_battle and notify.init_info.observe_battle.observer then
    table.copy(notify.init_info.observe_battle.observer, self.observingInfo.ObserverBriefInfoList)
  end
  self.evolutionPetName = nil
  self.evolutionResultName = nil
  self.evolutionAttrs = nil
  self.isEvolutionWaiting = false
  self.evolutionData = nil
  self.isWaitingRoleHP = false
  self:UpdateWeatherInfo(notify.weather_id, notify.weather_expire_round)
  self.lastDeadNpcIdx = nil
  self.playerPetNumber = 0
  self.enemyPetNumber = 0
  self.playerNumber = #notify.init_info.player_team
  self.enemyNumber = #notify.init_info.enemy_team
  self.npc_escape = nil
  self.battle_tasks = {}
  if notify.init_info.battle_tasks then
    for _, v in pairs(notify.init_info.battle_tasks) do
      self.battle_tasks[v.task_id] = v
    end
  end
  self.is_online_multiplayer = nil
  self.resonance_perform_count = 0
  if notify.init_info.b1_final_battle and notify.init_info.b1_final_battle.b1_phantom_point then
    self:SetB1PhantomPoint(notify.init_info.b1_final_battle.b1_phantom_point)
  end
  if BattleUtils.IsTerritoryTrialBattle() then
    local highestScore = BattleUtils.GetCurrentBattleTerritoryHighestScore()
    if self.resultUiState then
      self.resultUiState.prevHighestTerritoryTrialScore = highestScore
    end
  end
  self.battleConfig = _G.DataConfigManager:GetBattleConf(notify.init_info.battle_cfg_id[1])
  self:ProcessPlayerPetNumber(notify.init_info)
  self:RefreshSubBattleType()
  if BattleUtils.IsPvp() then
    UE4.UNRCStatics.EnableKnockback(false)
    BattleConst.MoveToLegalLocationWhenBlock = false
  end
  if ServerData.values.battleMode then
    UE4.UNRCStatics.EnableKnockback(false)
    BattleConst.MoveToLegalLocationWhenBlock = false
  end
  if BattleUtils.IsSky() or BattleUtils.IsDeepWater() then
    UE4.UNRCStatics.EnableKnockback(false)
    BattleConst.MoveToLegalLocationWhenBlock = false
  end
  UE4.UNRCStatics.EnableKnockback(false)
  BattleConst.MoveToLegalLocationWhenBlock = false
  self:ProcessBattleCenter()
  local liveId = notify and notify.live_id
  local cell = self:GetStateCell()
  local _, nextState = cell:GetCurrAndNext()
  nextState.isWatchingBroadcastBattle = liveId and liveId > 0
  cell:Set(nextState)
  BattleCoreEnv:InitEnv()
end

function BattleRuntimeData:UpdateBattleInitInfo(notify)
  self.roundTime = notify.round_time
  self:UpdateBattleState(notify.init_info.battle_state)
end

function BattleRuntimeData:UpdateWeatherInfo(weather_id, weather_expire_round)
  if self.curWeatherID ~= weather_id or self.curWeatherExpireRoundIndex ~= weather_expire_round then
    self.curWeatherID = weather_id
    self.curWeatherExpireRoundIndex = weather_expire_round
    local remain_round = self:GetWeatherRemainRound()
    _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_WEATHER_CHANGED, weather_id, remain_round)
  end
end

function BattleRuntimeData:GetWeatherRemainRound()
  if self.curWeatherExpireRoundIndex then
    return math.max(0, self.curWeatherExpireRoundIndex - self.roundIndex + 1)
  end
  return 0
end

function BattleRuntimeData:DebugUpdateWeatherInfo(weather_id, remain_round)
  self:UpdateWeatherInfo(weather_id, self.roundIndex + remain_round - 1)
end

function BattleRuntimeData:GetB1PhantomPoint()
  return self.b1PhantomPoint
end

function BattleRuntimeData:SetB1PhantomPoint(point)
  self.b1PhantomPoint = point
end

function BattleRuntimeData:SetPetNumber(playerPetNumber, enemyPetNumber)
  self.playerPetNumber = playerPetNumber
  self.enemyPetNumber = enemyPetNumber
end

function BattleRuntimeData:RefreshSubBattleType()
  self:RefreshSubBattleTypeWithPlayerAndPetNumber()
end

function BattleRuntimeData:RefreshSubBattleTypeWithPlayerAndPetNumber()
  if self.playerNumber > 1 or self.enemyNumber > 1 then
    self.subBattleType = BattleEnum.SubBattleType.MultiPlayer
    UE4.UNRCStatics.EnableKnockback(false)
    BattleConst.MoveToLegalLocationWhenBlock = false
  elseif self.enemyPetNumber > 1 or self.playerPetNumber > 1 then
    self.subBattleType = BattleEnum.SubBattleType.MultiPet
    UE4.UNRCStatics.EnableKnockback(false)
    BattleConst.MoveToLegalLocationWhenBlock = false
  else
    self.subBattleType = BattleEnum.SubBattleType.Single
    UE4.UNRCStatics.EnableKnockback(true)
    BattleConst.MoveToLegalLocationWhenBlock = true
  end
end

function BattleRuntimeData:UpdateBattleState(state)
  local info = self.battleStartParam.battleInitInfo
  if info then
    info.battle_state = state
  end
end

function BattleRuntimeData:ProcessBattleCenter()
  if _G.DebugBattleCenterHasDirtyData and BattleCenterDebugManager and BattleCenterDebugManager.ChangeConfs and BattleCenterDebugManager.ChangeConfs[self.battleConfig.id] then
    local pos = BattleCenterDebugManager.ChangeConfs[self.battleConfig.id].pos
    local rot = BattleCenterDebugManager.ChangeConfs[self.battleConfig.id].rot
    self.TeleportBattleCenter = UE4.FVector(math.floor(pos.X), math.floor(pos.Y), math.floor(pos.Z))
    self.ServerBattleRotate = math.floor(rot.Yaw)
    return
  end
  if RocoEnv.IS_EDITOR and self.battleConfig and self.battleConfig.id then
    local FilePath = UE.UBlueprintPathsLibrary.Combine({
      UE.UBlueprintPathsLibrary.ProjectSavedDir(),
      "TimeLineDebug.txt"
    })
    local ReadFile = io.open(FilePath, "r")
    if ReadFile then
      local idStr = tostring(self.battleConfig.id)
      local hasRecord = false
      for line in ReadFile:lines() do
        local trimmed = line:gsub("^%s+", ""):gsub("%s+$", "")
        if trimmed == idStr then
          hasRecord = true
          break
        end
      end
      ReadFile:close()
      if hasRecord and self.battleConfig.local_point and #self.battleConfig.local_point >= 3 then
        local pos = self.battleConfig.local_point
        self.TeleportBattleCenter = UE4.FVector(pos[1], pos[2], pos[3])
        if #pos >= 4 then
          self.ServerBattleRotate = pos[4]
        end
        return
      end
    end
  end
  if _G.EnableFakePVPRecord and not BattleUtils.IsTeam() and not BattleUtils.IsWeeklyChallenge() then
    if _G.BattleManager.debugEnv and _G.BattleManager.debugEnv.Pos then
      self.TeleportBattleCenter = _G.BattleManager.debugEnv.Pos
    else
      local BattleGlobalConfig = _G.DataConfigManager:GetBattleGlobalConfig("battle_mappoint_2")
      if BattleGlobalConfig and BattleGlobalConfig.numList and #BattleGlobalConfig.numList > 0 then
        self.TeleportBattleCenter = UE4.FVector(math.floor(BattleGlobalConfig.numList[2]), math.floor(BattleGlobalConfig.numList[3]), math.floor(BattleGlobalConfig.numList[4]))
      end
    end
    self.ServerBattleRotate = self.battleStartPlayerRotationYaw
    return
  end
  if _G.UseNearbyLocationInsteadOfRealLocation and not BattleUtils.IsTeam() and not BattleUtils.IsWeeklyChallenge() then
    self.TeleportBattleCenter = UE4.FVector(self.battleStartPlayerPos.x, self.battleStartPlayerPos.y, self.battleStartPlayerPos.z)
    self.ServerBattleRotate = self.battleStartPlayerRotationYaw
    return
  end
  Log.DebugFormat("BattleRuntimeData:ProcessBattleCenter FindBattleCenterByClient:%s, IsPvp:%s, IsTeam:%s, ServerBattlePos:%s, local_point:%s conf_id:%d", BattleConst.FindBattleCenterByClient, BattleUtils.IsPvp(), BattleUtils.IsTeam(), self.ServerBattlePos, self.battleConfig and self.battleConfig.local_point or nil, self.battleConfig and self.battleConfig.id or 0)
  if BattleConst.FindBattleCenterByClient then
    if BattleUtils.IsPvp() then
      if self.ServerBattlePos then
        self.TeleportBattleCenter = UE4.FVector(self.ServerBattlePos.x, self.ServerBattlePos.y, self.ServerBattlePos.z)
      end
    elseif BattleUtils.IsBloodTeam() or BattleUtils.IsBeastTeam() then
      self.TeleportBattleCenter = UE4.FVector(self.battleStartPlayerPos.X, self.battleStartPlayerPos.Y, 200000)
    elseif self.battleConfig and self.battleConfig.local_point and #self.battleConfig.local_point >= 3 then
      local pos = self.battleConfig.local_point
      self.TeleportBattleCenter = UE4.FVector(pos[1], pos[2], pos[3])
      if #pos >= 4 then
        self.ServerBattleRotate = pos[4]
      end
    elseif _G.BattleAutoTest.IsAutoBattle then
      self.TeleportBattleCenter = self.battleStartEnemyPos
    end
  elseif BattleUtils.IsBloodTeam() or BattleUtils.IsBeastTeam() then
    self.TeleportBattleCenter = FVectorZero
  elseif BattleUtils.IsWeeklyChallenge() or BattleUtils.IsTrainBattle() then
    self.TeleportBattleCenter = FVectorZero
  elseif self.ServerBattlePos then
    self.TeleportBattleCenter = UE4.FVector(self.ServerBattlePos.x, self.ServerBattlePos.y, self.ServerBattlePos.z)
  elseif self.battleConfig and self.battleConfig.local_point and #self.battleConfig.local_point >= 3 then
    local pos = self.battleConfig.local_point
    self.TeleportBattleCenter = UE4.FVector(pos[1], pos[2], pos[3])
    if #pos >= 4 then
      self.ServerBattleRotate = pos[4]
    end
  elseif _G.BattleAutoTest.IsAutoBattle then
    self.TeleportBattleCenter = self.battleStartEnemyPos
  end
end

function BattleRuntimeData:ProcessPlayerPetNumber(initInfo)
  local playerPetNumber = 0
  local enemyPetNumber = 0
  if self.battleConfig then
    playerPetNumber = self.battleConfig.challanger_unit_num * self.playerNumber
    enemyPetNumber = self.battleConfig.bechallanger_unit_num * self.enemyNumber
  end
  if BattleUtils.IsTerritoryTrialBattle() then
    local enemyTeamList = initInfo and initInfo.enemy_team
    local enemyTeam = enemyTeamList and enemyTeamList[1]
    local petList = enemyTeam and enemyTeam.pets or {}
    for i, petInfo in ipairs(petList) do
      local insideInfo = petInfo and petInfo.battle_inside_pet_info
      local trialInfo = insideInfo and insideInfo.trial_pet_info
      local isBoss = trialInfo and trialInfo.is_boss
      local inBattle = BattleUtils.GetInBattle(insideInfo) and not BattleUtils.GetIsPetPrepare(insideInfo)
      if isBoss and inBattle then
        enemyPetNumber = 1
      end
    end
  end
  self:SetPetNumber(playerPetNumber, enemyPetNumber)
end

function BattleRuntimeData:CheckEnemyPosIsLegal(location)
  return location and (0 ~= location.x or 0 ~= location.y or 0 ~= location.z)
end

function BattleRuntimeData:Clear()
  self:ClearEvolutionCachedData()
  self:Reset()
  self:SetBattleMode(BattleEnum.BattleMode.Normal)
end

function BattleRuntimeData:Reset()
  self.operateType = BattleEnum.Operation.ENUM_NONE
  self.backOperateType = BattleEnum.Operation.ENUM_NONE
  self.battleCCMode = nil
  self.roundIndex = 0
  self.seriesIndex = 0
  self.roundTime = 0
  self.catchInfo = nil
  self.battleStartPlayerPos = nil
  self.battleStartPlayerRotationYaw = 0
  self.battleStartEnemyPos = nil
  self.battleStartEnemyRotationYaw = 0
  self.lastChangePetRoundIndex = 0
  self.startRoundSelectRoundIndex = 0
  self.petDeathAnimationPendingCnt = 0
  self.evolutionPetName = nil
  self.evolutionResultName = nil
  self.evolutionAttrs = nil
  self.isEvolutionWaiting = false
  self.subBattleType = nil
  self.evolutionData = nil
  self.isWaitingRoleHP = false
  self:UpdateWeatherInfo(nil, nil)
  self.lastDeadNpcIdx = nil
  self.npc_escape = nil
  self.battleConfig = nil
  self.teamBattleCenterTrans = nil
  self.TeleportBattleCenter = nil
  self.observingInfo = {
    ObserverBriefInfoList = {},
    lastOperationType = nil
  }
  self.specialMoveInfoList = {}
  table.clear(self.battleHideTreeDict)
  table.clear(self.battleHideStaticMeshLst)
  table.clear(self.battleHideNPCTypeObject)
  table.clear(self.spEnergyElementList)
  self.battleStartParam:Reset()
  self.battleExitParam:Reset()
  self.battleSettleData:Reset()
  self.PlayerSkillManager:Reset()
  self.fadeInfo = {
    enableCameraFadeRule = false,
    cameraFadeRuleId = nil,
    fadeObjectList = {}
  }
  self.finalBattleInfo = {bossDeadBlackScreenSkillObject = nil, bossDeadBlackScreenSkillObjectRef = nil}
  self:ClearCacheRidOf()
  self:RemoveB1P1BallActor()
  self.B1FBTempData = nil
  self.resultUiState = nil
  self.battle_tasks = {}
  self.is_online_multiplayer = nil
  self.isObserver = false
  self.jiaerSkillBlackToWhite = nil
  self.jiaerSkillWhiteToBlack = nil
  local stateCell = self:GetStateCell()
  local initState = self:GetInitState()
  if stateCell and initState then
    stateCell:Set(initState)
  end
end

function BattleRuntimeData:ResetAllData()
end

function BattleRuntimeData:HasValidNPC()
  if not self.NpcIDs then
    return false, nil
  end
  for _, id in ipairs(self.NpcIDs) do
    if 0 ~= id then
      local NPC = _G.NRCModuleManager:DoCmd(_G.NPCModuleCmd.GetNpcByServerID, id)
      if NPC then
        return true, NPC
      end
    end
  end
  return false, nil
end

function BattleRuntimeData:GetCurrentNPC()
  if not self.NpcIDs then
    return nil
  end
  local id = self.NpcIDs[self.seriesIndex + 1]
  if not id or 0 == id then
    return nil
  end
  local npc = _G.NRCModuleManager:DoCmd(_G.NPCModuleCmd.GetNpcByServerID, id)
  return npc, id
end

function BattleRuntimeData:GetNPCByIdx(idx)
  if not self.NpcIDs then
    return nil
  end
  local index = idx or 1
  local id = self.NpcIDs[index]
  if not id or 0 == id then
    return nil
  end
  local npc = _G.NRCModuleManager:DoCmd(_G.NPCModuleCmd.GetNpcByServerID, id)
  return npc, id
end

function BattleRuntimeData:GetAllNPCs()
  local npcInfos = {}
  if self.NpcIDs then
    for i = 1, #self.NpcIDs do
      local npc, id = self:GetNPCByIdx(i)
      if npc then
        table.insert(npcInfos, {npc = npc, id = id})
      end
    end
  end
  return npcInfos
end

function BattleRuntimeData:GetPetConfIDByGuid(petID)
  local battlePet = BattleManager.battlePawnManager:GetPetByGuid(petID)
  if battlePet then
    return battlePet.card.petInfo.battle_inside_pet_info.base_conf_id
  end
end

function BattleRuntimeData:SetBattleID(value)
  self.battle_id = tonumber(value)
end

function BattleRuntimeData:GetBattleID()
  return self.battle_id
end

function BattleRuntimeData:SetPotentialTaskID(PotentialTaskID)
  self.PotentialTaskID = PotentialTaskID
end

function BattleRuntimeData:GetPotentialTaskID()
  return self.PotentialTaskID
end

function BattleRuntimeData:SetBattleMode(battleMode)
  self.battleMode = battleMode
end

function BattleRuntimeData:GetBattleMode()
  return self.battleMode
end

function BattleRuntimeData:GetSubBattleType()
  return self.subBattleType
end

function BattleRuntimeData:SetEnterBattleType(battleEnterType)
  self.enterBattleType = battleEnterType
end

function BattleRuntimeData:GetEnterBattleType()
  return self.enterBattleType
end

function BattleRuntimeData:SetContactEnterType(enterType)
  self.contactEnterType = enterType
end

function BattleRuntimeData:GetContactEnterType()
  return self.contactEnterType
end

function BattleRuntimeData:IsInReplayMode()
  return self.battleMode == BattleEnum.BattleMode.Replay
end

function BattleRuntimeData:ModifySpEnergyList(sp_energy_change)
  if sp_energy_change.type == ProtoEnum.BattleSpEnergyChange.SP_ENERGY_CHANGE_TYPE.SP_ENERGY_ADD then
    if #self.spEnergyElementList <= BattleConst.SpEnergy.SpEnergyElementMax then
      table.insert(self.spEnergyElementList, sp_energy_change.ele)
    else
      Log.Error("add element when list count >= 6")
    end
  elseif sp_energy_change.type == ProtoEnum.BattleSpEnergyChange.SP_ENERGY_CHANGE_TYPE.SP_ENERGY_REMOVE then
    for i, v in ipairs(self.spEnergyElementList) do
      if v.dam_type == sp_energy_change.ele.dam_type then
        table.remove(self.spEnergyElementList, i)
      end
    end
  elseif sp_energy_change.type == ProtoEnum.BattleSpEnergyChange.SP_ENERGY_CHANGE_TYPE.SP_ENERGY_CHANGE then
    for i, v in ipairs(self.spEnergyElementList) do
      if v.dam_type == sp_energy_change.ele.dam_type then
        v.stack = sp_energy_change.ele.stack
      end
    end
  elseif sp_energy_change.type == ProtoEnum.BattleSpEnergyChange.SP_ENERGY_CHANGE_TYPE.SP_ENERGY_REPLACE then
    if #self.spEnergyElementList <= BattleConst.SpEnergy.SpEnergyElementMax then
      table.insert(self.spEnergyElementList, sp_energy_change.ele)
    end
    for i, v in ipairs(self.spEnergyElementList) do
      if v.dam_type == sp_energy_change.replaced_dam_type then
        table.remove(self.spEnergyElementList, i)
      end
    end
  else
    Log.Error("sp_energy_change operate type with null")
  end
end

function BattleRuntimeData:GetSpEnergyStackByType(type)
  for _, v in ipairs(self.spEnergyElementList) do
    if v.dam_type == type then
      return v.stack
    end
  end
  return 0
end

function BattleRuntimeData:GetSpEnergyPosByType(type)
  local posIndex = 0
  for _, v in ipairs(self.spEnergyElementList) do
    if v.dam_type == type then
      return posIndex
    end
    posIndex = posIndex + 1
  end
  return posIndex
end

function BattleRuntimeData:GetNewSkillBySpEnergy(skill)
  if skill and skill.skillData then
    local newSkillId = skill.skillData.sp_energy_skill
    if newSkillId and newSkillId > 0 then
      return _G.DataConfigManager:GetSkillConf(newSkillId) or skill.config
    end
  end
  if skill then
    return skill.config
  end
end

function BattleRuntimeData:GetDamageBySpEnergy(skillConf)
  if not self.spEnergyElementList or 0 == #self.spEnergyElementList then
    return skillConf.dam_para[1]
  end
  for _, v in ipairs(self.spEnergyElementList) do
    if v.dam_type == skillConf.skill_dam_type then
      local fieldConf = _G.DataConfigManager:GetFieldLayerConf(v.stack)
      if fieldConf then
        local addPercent = fieldConf.power_up / 10000
        return math.floor(skillConf.dam_para[1] + skillConf.dam_para[1] * addPercent)
      end
    end
  end
  return skillConf.dam_para
end

function BattleRuntimeData:SetEvolutionPetInfo(id)
  self.evolutionPetName = _G.BattleManager.battlePawnManager:GetInFieldPet(BattleEnum.Team.ENUM_TEAM).card.name
end

function BattleRuntimeData:SetEvolutionSelectActionInfo(evolutionData)
  self.evolutionData = evolutionData
end

function BattleRuntimeData:SetPvpPlayerPerformData(battlePerformInfo)
  self.pvpPlayerPerformData = battlePerformInfo
end

function BattleRuntimeData:GetPvpPlayerPerformData()
  return self.pvpPlayerPerformData
end

function BattleRuntimeData:SetEvolutionResultInfo(petName, attrs)
  self.evolutionResultName = petName
  self.evolutionAttrs = attrs
end

function BattleRuntimeData:ClearEvolutionPetInfo()
  self.evolutionData = nil
  self.evolutionResultName = nil
  self.evolutionPetName = nil
  self.evolutionAttrs = nil
end

function BattleRuntimeData:ClearEvolutionNewPet()
  if self.evolutionNewModel then
    self.evolutionNewModel:K2_DestroyActor()
    self.evolutionNewModel = nil
  end
end

function BattleRuntimeData:ClearEvolutionCachedData()
  self:ClearEvolutionPetInfo()
end

function BattleRuntimeData:ConstructSendFlowFinishData()
  local pet_positions = {}
  local battleFieldCenter = ProtoMessage:newPosition()
  local battleFieldRadius
  local pets = BattleManager.battlePawnManager:GetAllPets()
  for i = 1, #pets do
    local pet = pets[i]
    if pet.model and pet.card:IsExistAtField() and UE.UObject.IsValid(pet.model) then
      local loc = pet.model:Abs_K2_GetActorLocation()
      local posi = {}
      posi.pet_id = pet.guid
      posi.pos = ProtoMessage:newPosition()
      if loc then
        posi.pos.x = math.ceil(loc.X)
        posi.pos.y = math.ceil(loc.Y)
        posi.pos.z = math.ceil(loc.Z - pet:GetHalfHeight())
        Log.Debug("BattleRuntimeData show pet loc:", loc, pet.guid)
      end
      table.insert(pet_positions, posi)
    end
  end
  local center = BattleManager.vBattleField:GetBattleFieldCenter()
  battleFieldCenter.x = math.ceil(center.X)
  battleFieldCenter.y = math.ceil(center.Y)
  battleFieldCenter.z = math.ceil(center.Z)
  battleFieldRadius = BattleManager.vBattleField:GetBattleFieldRadius()
  return pet_positions, battleFieldCenter, battleFieldRadius
end

function BattleRuntimeData:GetValidObserverPointIndexList()
  local indexAList = {}
  local battleOnLookerInfo = self.battleOnLookerInfo
  local validOnLookerPointEnumMap = battleOnLookerInfo and battleOnLookerInfo.validOnLookerPointEnumMap or {}
  local IndexToAttachPointEnumA = BattleNpc and BattleNpc.IndexToAttachPointEnumA or {}
  for index, pointEnum in ipairs(IndexToAttachPointEnumA) do
    local isValid = validOnLookerPointEnumMap and validOnLookerPointEnumMap[pointEnum]
    if isValid then
      table.insert(indexAList, index)
    end
  end
  return indexAList
end

function BattleRuntimeData:SetNpcAutoEscapeInfo(npc_escape)
  self.npc_escape = npc_escape
end

function BattleRuntimeData:GetNpcAutoEscapeInfo()
  return self.npc_escape
end

function BattleRuntimeData:SetEnemyOnThinking(isThinking)
  self.enemyThinking = isThinking
end

function BattleRuntimeData:GetEnemyOnThinking()
  return self.enemyThinking
end

function BattleRuntimeData:SetWorldLeaderShowInfo(worldRelativeTransform, worldCameraFov)
  self.worldRelativeTransform = worldRelativeTransform
  self.worldCameraFov = worldCameraFov
end

function BattleRuntimeData:GetWorldLeaderShowInfo()
  return self.worldRelativeTransform, self.worldCameraFov
end

function BattleRuntimeData:SetWorldLeaderShowSkill(worldLeaderShowSkill)
  self.worldLeaderShowSkill = worldLeaderShowSkill
  if worldLeaderShowSkill then
    self.worldLeaderShowHitSkillPlayed = true
  end
end

function BattleRuntimeData:GetWorldLeaderShowSkill()
  return self.worldLeaderShowSkill
end

function BattleRuntimeData:IsWorldLeaderShowHitSkillPlayed()
  return self.worldLeaderShowHitSkillPlayed == true
end

function BattleRuntimeData:ResetWorldLeaderShowHitSkillPlayed()
  self.worldLeaderShowHitSkillPlayed = false
end

function BattleRuntimeData:StopWorldLeaderShowSkill()
  if self.worldLeaderShowSkill and UE.UObject.IsValid(self.worldLeaderShowSkill) then
    local blackBoard = self.worldLeaderShowSkill.Blackboard
    if blackBoard then
      blackBoard:SetValueAsBool("RemoveWorldLeaderShow", false)
    end
    self.worldLeaderShowSkill = nil
  end
end

function BattleRuntimeData:SetOnSelectWorldLeaderSkill(isOn)
  self.isOnSelectWorldLeaderSkill = isOn
end

function BattleRuntimeData:GetOnSelectWorldLeaderSkill()
  return self.isOnSelectWorldLeaderSkill
end

function BattleRuntimeData:IsOnBattleTest()
  local ctrl = self.battleDebugControl
  if not ctrl then
    return false
  end
  if ctrl.isInBattleTest then
    return true
  end
  if _G.BattleDebugMode then
    return ctrl.debugMode == _G.BattleDebugMode.AutoTest
  end
  return false
end

function BattleRuntimeData:SetFBP1DialogPet(battlePet)
  self.FBP1DialogPet = battlePet
end

function BattleRuntimeData:GetFBP1DialogPet()
  return self.FBP1DialogPet
end

function BattleRuntimeData:SetFBP1SupplyInfo(supplyCount)
  self.FBP1SupplyCount = supplyCount
end

function BattleRuntimeData:GetFBP1IsSupplyEnd()
  if self.FBP1SupplyCount then
    self.FBP1SupplyCount = self.FBP1SupplyCount - 1
    return self.FBP1SupplyCount <= 0
  end
  return true
end

function BattleRuntimeData:SetBattleNpcChallengeInfo(NpcChallengeInfo)
  self.NpcChallengeInfo = NpcChallengeInfo
end

function BattleRuntimeData:GetBattleNpcChallengeInfo()
  return self.NpcChallengeInfo
end

function BattleRuntimeData:GetBattleTaskInfo()
  return self.NpcChallengeInfo and self.NpcChallengeInfo.task_infos or nil
end

function BattleRuntimeData:UpdateBattleTaskInfo(TaskInfo)
  local battleTaskInfo = self.NpcChallengeInfo and self.NpcChallengeInfo.task_infos or nil
  if not battleTaskInfo then
    return
  end
  local curMap = {}
  for index, curInfo in pairs(battleTaskInfo) do
    curMap[curInfo.task_id] = index
  end
  for _, info in pairs(TaskInfo) do
    if curMap[info.task_id] then
      battleTaskInfo[curMap[info.task_id]] = info
    end
  end
end

function BattleRuntimeData:SetFBP1ToP2State(state)
  if BattleUtils.IsFinalBattle() then
    self.IsWaitRoundFlowFinishRSP = state
  end
end

function BattleRuntimeData:IsFBInP1ToP2()
  return BattleUtils.IsFinalBattle() and self.IsWaitRoundFlowFinishRSP and 1 == self.IsWaitRoundFlowFinishRSP
end

function BattleRuntimeData:IsFBWaitRoundFlowFinishRSP()
  return BattleUtils.IsFinalBattle() and self.IsWaitRoundFlowFinishRSP and 2 == self.IsWaitRoundFlowFinishRSP
end

function BattleRuntimeData:SetIsJumpAiPerform(isJump)
  self.jumpAiPerform = isJump
end

function BattleRuntimeData:IsJumpAiPerform()
  return self.jumpAiPerform
end

function BattleRuntimeData:SetIsDelayRiOf(isDelay)
  self.delayRiOf = isDelay
end

function BattleRuntimeData:IsDelayRiOf()
  return self.delayRiOf
end

function BattleRuntimeData:AddCacheRidOfBuffTrigger(buffTrigger)
  if not self.cacheRidOfInfo then
    self.cacheRidOfInfo = {}
  end
  if not self.cacheRidOfInfo.buffTriggers then
    self.cacheRidOfInfo.buffTriggers = {}
  end
  table.insert(self.cacheRidOfInfo.buffTriggers, buffTrigger)
end

function BattleRuntimeData:GetCacheRidOfBuffTrigger()
  return self.cacheRidOfInfo and self.cacheRidOfInfo.buffTriggers
end

function BattleRuntimeData:SetParallelShowTime(showTime)
  if not self.cacheRidOfInfo then
    self.cacheRidOfInfo = {}
  end
  local currentTime = self.cacheRidOfInfo.showTime or 0
  self.cacheRidOfInfo.showTime = math.max(showTime, currentTime)
end

function BattleRuntimeData:GetParallelShowTime()
  return self.cacheRidOfInfo and self.cacheRidOfInfo.showTime or 0
end

function BattleRuntimeData:SetHasPetReturn(petId)
  if not self.cacheRidOfInfo then
    self.cacheRidOfInfo = {}
  end
  if not self.cacheRidOfInfo.returnPetIds then
    self.cacheRidOfInfo.returnPetIds = {}
  end
  table.insert(self.cacheRidOfInfo.returnPetIds, petId)
end

function BattleRuntimeData:GetHasPetReturn(petId)
  if self.cacheRidOfInfo and self.cacheRidOfInfo.returnPetIds then
    for i, v in ipairs(self.cacheRidOfInfo.returnPetIds) do
      if petId == v then
        return true
      end
    end
  end
  return false
end

function BattleRuntimeData:ClearCacheRidOf()
  self.cacheRidOfInfo = nil
  self.delayRiOf = false
end

function BattleRuntimeData:LoadWeekChallengeLevelStream()
end

function BattleRuntimeData:LoadB1LevelStream()
  if not self.levelStreaming then
    local scenePath = "/Game/ArtRes/Level/Game/Plot/B1/Plot_B1_FinalBattle/Plot_B1_FinalBattle_Release"
    self:LoadLevelStream(scenePath, self.TeleportBattleCenter, true)
  end
end

function BattleRuntimeData:LoadLevelStream(scenePath, battleStartPlayerPos, shouldBeVisible)
  battleStartPlayerPos = battleStartPlayerPos or FVectorZero
  local LevelStreaming = BattleManager.vBattleField:LoadBattleLevel(scenePath, battleStartPlayerPos, UE.FRotator())
  if LevelStreaming then
    LevelStreaming:SetShouldBeVisible(shouldBeVisible)
    self.levelStreaming = LevelStreaming
    self.levelStreamingRef = UnLua.Ref(LevelStreaming)
    LevelStreaming.OnLevelLoaded:Add(LevelStreaming, function(level)
      self.isLevelLoad = true
    end)
  end
end

function BattleRuntimeData:CancelLevelStream()
  if self.levelStreaming then
    if self.levelStreamingRef and UE.UObject.IsValid(self.levelStreamingRef) then
      UnLua.Unref(self.levelStreamingRef)
    end
    self.levelStreamingRef = nil
    self.levelStreaming:SetShouldBeLoaded(false)
  end
  self.levelStreaming = nil
  self.isLevelLoad = false
end

function BattleRuntimeData:ResetLevelData()
  self.levelStreaming:SetShouldBeVisible(true)
  self.levelStreaming = nil
  self.isLevelLoad = false
end

function BattleRuntimeData:GetIsLevelLoad()
  return self.isLevelLoad and self.levelStreaming
end

function BattleRuntimeData:SetB1P1BallActor(ballActor)
  if not self.B1FBTempData then
    self.B1FBTempData = {}
  end
  if UE.UObject.IsValid(ballActor) then
    self.B1FBTempData.b1P1BallActor = ballActor
    UnLua.Ref(ballActor)
  end
end

function BattleRuntimeData:GetB1P1BallActor()
  if self.B1FBTempData and self.B1FBTempData.b1P1BallActor then
    return self.B1FBTempData.b1P1BallActor
  end
end

function BattleRuntimeData:RemoveB1P1BallActor()
  if not self.B1FBTempData then
    return
  end
  if self.B1FBTempData.b1P1BallActor and UE.UObject.IsValid(self.B1FBTempData.b1P1BallActor) then
    UnLua.Unref(self.B1FBTempData.b1P1BallActor)
    self.B1FBTempData.b1P1BallActor:K2_DestroyActor()
    self.B1FBTempData.b1P1BallActor = nil
  end
end

function BattleRuntimeData:CacheB1P1LevelSequence(levelSequenceActor)
  if not self.B1FBTempData then
    self.B1FBTempData = {}
  end
  self.B1FBTempData.P1LevelSequence = levelSequenceActor
end

function BattleRuntimeData:RemoveB1P1LevelSequence()
  if not self.B1FBTempData then
    return
  end
  if not self.B1FBTempData.P1LevelSequence then
    return
  end
  self.B1FBTempData.P1LevelSequence:Stop()
  self.B1FBTempData.P1LevelSequence = nil
end

function BattleRuntimeData:CachedPlayerMeshTrans(meshTrans)
  if not self.B1FBTempData then
    self.B1FBTempData = {}
  end
  self.B1FBTempData.CachedPlayerMeshTrans = meshTrans
end

function BattleRuntimeData:GetCachedPlayerMeshTrans()
  if self.B1FBTempData and self.B1FBTempData.CachedPlayerMeshTrans then
    return self.B1FBTempData.CachedPlayerMeshTrans
  end
end

function BattleRuntimeData:CacheB1P2LevelSequence(levelSequenceActor)
  if not self.B1FBTempData then
    self.B1FBTempData = {}
  end
  self.B1FBTempData.P2LevelSequence = levelSequenceActor
end

function BattleRuntimeData:RemoveB1P2LevelSequence()
  if not self.B1FBTempData then
    return
  end
  if not self.B1FBTempData.P2LevelSequence then
    return
  end
  self.B1FBTempData.P2LevelSequence:Stop()
  self.B1FBTempData.P2LevelSequence = nil
end

function BattleRuntimeData:IsShowFlowerTask()
  return not self.is_online_multiplayer and self:GetBattleTasksCount() > 0
end

function BattleRuntimeData:IsShowFlowerTaskCatchTip()
  if not self:IsShowFlowerTask() then
    return false
  end
  for _, v in pairs(self.battle_tasks) do
    if ProtoEnum.BattleTaskState.BTS_FAIL == v.task_state then
      return false
    end
  end
  return true
end

function BattleRuntimeData:GetBattleTasks()
  return self.battle_tasks
end

function BattleRuntimeData:GetBattleTasksCount()
  local count = 0
  for _, _ in pairs(self.battle_tasks) do
    count = count + 1
  end
  return count
end

function BattleRuntimeData:UpdateBattleTasks(battle_tasks)
  for _, v in pairs(battle_tasks) do
    self.battle_tasks[v.task_id] = v
  end
end

function BattleRuntimeData:AddResonancePerform()
  self.resonance_perform_count = self.resonance_perform_count + 1
end

function BattleRuntimeData:ReduceResonancePerform()
  self.resonance_perform_count = self.resonance_perform_count - 1
end

function BattleRuntimeData:GetResonancePerform()
  return self.resonance_perform_count
end

function BattleRuntimeData:SetRestartInfo(finishNotify)
  local settleInfo = finishNotify and finishNotify.settle_info
  local interactNpcId = settleInfo and settleInfo.interact_npc_id
  local interactNpcOption = settleInfo and settleInfo.npc_option_id
  local restartBattleInfo = {}
  restartBattleInfo.npcId = interactNpcId
  restartBattleInfo.optionId = interactNpcOption
  self.restartBattleInfo = restartBattleInfo
end

function BattleRuntimeData:GetRestartInfo()
  local restartBattleInfo = self.restartBattleInfo
  return restartBattleInfo
end

function BattleRuntimeData:ClearRestartInfo()
  self.restartBattleInfo = nil
end

function BattleRuntimeData:GetBattleConfID()
  return self.battleConfig and self.battleConfig.id or 0
end

return BattleRuntimeData
