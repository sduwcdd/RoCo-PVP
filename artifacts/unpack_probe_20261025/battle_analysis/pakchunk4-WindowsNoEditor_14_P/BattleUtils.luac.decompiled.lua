local DummyTable = require("Common.DummyTable")
local BattleUtils = {}
local PetUtils = require("NewRoco.Utils.PetUtils")
local Enum = require("Data.Config.Enum")
local ProtoCMD = require("Data.PB.ProtoCMD")
local BattleEnum = require("NewRoco.Modules.Core.Battle.Common.BattleEnum")
local BattleConst = require("NewRoco.Modules.Core.Battle.Common.BattleConst")
local ProtoEnum = require("Data.PB.ProtoEnum")
local BattleEvent = require("NewRoco.Modules.Core.Battle.Common.BattleEvent")
local BagModuleCmd = require("NewRoco.Modules.System.Bag.BagModuleCmd")
local PetMutationUtils = require("NewRoco.Utils.PetMutationUtils")
local LineTraceUtils = require("NewRoco.Modules.Core.Battle.Common.LineTraceUtils")
local BattleModuleCmd = require("NewRoco.Modules.Core.Battle.BattleModuleCmd")
local ProtoMessage = require("Data.PB.ProtoMessage")
local tcallForBattle = _G.tcallForBattle
local AbilityID = require("NewRoco.Modules.Core.Scene.Component.Ability.AbilityID")
local UIUtils = require("NewRoco.Utils.UIUtils")
local LockWeatherReason = require("NewRoco.Modules.System.EnvSystem.LockWeatherReason")
local RogueModuleUtils = require("NewRoco.Modules.System.BattleRogue.RogueModuleUtils")
BattleUtils.BallThresholdCalculateData = {}
BattleUtils.PCGCam = nil

function BattleUtils.CalculateCatchMonsterRate(ballId, monsterConfID, npcLevel, catchTimes, targetAIState, throwDist, dizzy, bMatchBallState, guaranteeRate, lastCatchTime)
  local DataConfigManager = _G.DataConfigManager
  if not ballId then
    Log.Error("BattleUtils CalculateCatchMonsterRate Error: BallId is nil")
    return nil
  end
  if not monsterConfID then
    Log.Error("BattleUtils CalculateCatchMonsterRate Error: monsterConfID is nil")
    return nil
  end
  if not npcLevel then
    Log.Error("BattleUtils CalculateCatchMonsterRate Error: npcLevel is nil")
    return nil
  end
  if not catchTimes then
    Log.Error("BattleUtils CalculateCatchMonsterRate Error: catchTimes is nil")
    return nil
  end
  do
    local ballCfg = DataConfigManager:GetBallConf(ballId)
    if not ballCfg then
      Log.ErrorFormat("BattleUtils CalculateCatchMonsterRate Error: BallCfg not found %d", ballId)
      return nil
    end
    local monsterCfg = DataConfigManager:GetMonsterConf(monsterConfID)
    if not monsterCfg then
      Log.Error("BattleUtils CalculateCatchMonsterRate Error: MonsterCfg not found")
      return nil
    end
    local monsterCatchConf = DataConfigManager:GetMonsterCatchConf(monsterConfID)
    if not monsterCatchConf then
      Log.Error("BattleUtils CalculateCatchMonsterRate Error: monsterCatchConf not found")
      return nil
    end
    local petBaseCfg = DataConfigManager:GetPetbaseConf(monsterCfg.base_id)
    if not petBaseCfg then
      Log.ErrorFormat("BattleUtils CalculateCatchMonsterRate Error: PetBaseCfg not found %d", monsterCfg.base_id)
      return nil
    end
    local probCalculateParam = DataConfigManager:GetGlobalConfigNumByKeyType("prob_calculate_param", _G.DataConfigManager.ConfigTableId.GLOBAL_CONFIG, 10000) or 10000
    local historyTimeMaximum = DataConfigManager:GetGlobalConfigNumByKeyType("history_time_maximum", _G.DataConfigManager.ConfigTableId.BATTLE_GLOBAL_CONFIG, 27)
    catchTimes = math.min(catchTimes, historyTimeMaximum, petBaseCfg.Catch_Threshold_Bonustime)
    local isInSneakState = false
    if 0 == targetAIState & _G.ProtoEnum.ThrowTargetNpcAIStatus.DETECTED_AVATAR or dizzy then
      isInSneakState = true
    end
    local throwProb = 0
    local ballActConf = _G.DataConfigManager:GetBallAct(ballId, true)
    if ballActConf then
      local calculatorDist = ballActConf.beyond_fly_distance
      if throwDist > calculatorDist then
        local addDist = throwDist - calculatorDist
        local addProb = ballActConf.fly_growth_coefficient
        local maxProb = ballActConf.fly_growth_max
        throwProb = math.min(addDist % addProb, maxProb / probCalculateParam)
      end
    end
    local sneakModify = BattleUtils.CalculateSneakModifyValue(false, isInSneakState, ballId, throwProb)
    local weatherType = _G.NRCModuleManager:DoCmd(EnvSystemModuleCmd.GetCurrentWeatherType)
    local ballThresholdData = {
      ballConfID = ballId,
      isInBattle = false,
      petID = monsterConfID,
      weatherID = weatherType,
      bMatchBallAIState = bMatchBallState
    }
    local ballThreshold = BattleUtils.CalculateBallThresholdBattle(ballThresholdData) / probCalculateParam
    local ballProb = BattleUtils.CalculateBallProb(ballThresholdData) / probCalculateParam
    local curHp = 1
    local handBookReward, totalAwardCatch, totalAwardPetCatchChange = _G.NRCModuleManager:DoCmd(_G.HandbookModuleCmd.GetPetHandbookCurrentProgressTaskReward, monsterCfg.base_id)
    local handBookCatchChangeProb = 0
    local handBookProb = 0
    handBookProb = totalAwardCatch / probCalculateParam
    handBookCatchChangeProb = totalAwardPetCatchChange / probCalculateParam
    local minThreshold = DataConfigManager:GetGlobalConfigNumByKeyType("CTT_min", _G.DataConfigManager.ConfigTableId.NPC_GLOBAL_CONFIG, 100)
    local calcThresholdBefore = monsterCatchConf.Catch_Threshold
    if probCalculateParam < calcThresholdBefore then
      calcThresholdBefore = probCalculateParam
    elseif minThreshold > calcThresholdBefore then
      calcThresholdBefore = minThreshold
    end
    local peerModify = BattleUtils.CalculatePeerModify() / probCalculateParam
    local petThreshold = calcThresholdBefore / probCalculateParam
    local seasonModify = 0
    local seasonProb = _G.NRCModeManager:DoCmd(_G.MagicManualModuleCmd.OnGetSeasonManualProbAdd)
    if seasonProb and seasonProb.season_adv_prob_add then
      seasonModify = seasonProb.season_adv_prob_add
    end
    local thresholdHp = BattleUtils.CalculatePetThresholdHp(petThreshold, ballThreshold, handBookProb, sneakModify, peerModify)
    return BattleUtils.CalculateFinalRate(ballId, monsterConfID, npcLevel, curHp, thresholdHp, handBookCatchChangeProb, ballProb, guaranteeRate, lastCatchTime, seasonModify)
  end
end

function BattleUtils.CalculateFinalRate(ballId, monsterConfID, npcLevel, curHpPercent, thresholdHp, handBookCatchChangeProb, calcBallProb, guaranteeRate, lastCatchTime, seasonModify)
  if nil == npcLevel then
    Log.Error("BattleUtils.CalculateFinalRate npcLevel == nil\239\188\140\232\175\183\230\163\128\230\159\165")
    npcLevel = 0
  end
  local DataConfigManager = _G.DataConfigManager
  local ballCfg = DataConfigManager:GetBallConf(ballId)
  if not ballCfg then
    Log.ErrorFormat("BattleUtils CalculateCatchMonsterRate Error: BallCfg not found %d", ballId)
    return nil
  end
  local monsterCfg = DataConfigManager:GetMonsterConf(monsterConfID)
  if not monsterCfg then
    Log.Error("BattleUtils CalculateCatchMonsterRate Error: MonsterCfg not found")
    return nil
  end
  seasonModify = seasonModify or 0
  local probCalculateParam = DataConfigManager:GetGlobalConfigNumByKeyType("prob_calculate_param", _G.DataConfigManager.ConfigTableId.GLOBAL_CONFIG, 10000) or 10000
  if not probCalculateParam then
    Log.Error("BattleUtils CalculateCatchMonsterRate Error: probCalculateParam not found")
    return nil
  end
  local ballProb = calcBallProb
  local curHp = curHpPercent
  local overThreshold = monsterCfg.Catch_difficulty_OverThreshold / probCalculateParam
  local catchHardA = DataConfigManager:GetBattleGlobalConfig("catch_handicap").num / probCalculateParam
  local levelParam = DataConfigManager:GetBattleGlobalConfig("level_modify").num / probCalculateParam
  local worldLevel = _G.DataModelMgr.PlayerDataModel:GetPlayerWorldLevel() + 1
  local petTopLevel = 0
  local worldLevelConf = DataConfigManager:GetWorldLevelConf(worldLevel)
  if worldLevelConf then
    petTopLevel = worldLevelConf.pet_top_level
  end
  local maxCatchRate = monsterCfg.catch_prob_max / probCalculateParam
  local guarantRetainTime = DataConfigManager:GetBattleGlobalConfig("catch_guarant_retain_time").num
  lastCatchTime = lastCatchTime or 0
  local timeInterval = _G.ZoneServer:GetServerTime() / 1000 - lastCatchTime
  local bZero = 0
  if guarantRetainTime < timeInterval then
    bZero = 0
  else
    bZero = 1
  end
  guaranteeRate = guaranteeRate / probCalculateParam
  local rate = 0
  if -1 ~= ballCfg.static_catch_rate then
    rate = ballCfg.static_catch_rate / probCalculateParam
  else
    rate = math.min(1, math.min((overThreshold + guaranteeRate * bZero) * ballProb + handBookCatchChangeProb + seasonModify, maxCatchRate) * math.min(1, catchHardA ^ (curHp / thresholdHp - 1)) / levelParam ^ math.max(0, npcLevel - petTopLevel))
  end
  if GlobalConfig.ShowCatchRate then
    Log.PrintScreenMsgRed("[\230\141\149\230\141\137\230\166\130\231\142\135]\230\136\144\229\138\159\231\142\135(%f) = MIN(1, MIN((\229\159\186\231\161\128\230\141\149\230\141\137\230\166\130\231\142\135:%f+\228\191\157\229\186\149\230\141\149\230\141\137\230\166\130\231\142\135:%f)*\231\144\131\231\167\141\228\191\174\230\173\163:%f+\229\155\190\233\137\180\230\166\130\231\142\135\228\191\174\230\173\163:%f+\232\181\155\229\173\163\230\137\139\229\134\140\230\166\130\231\142\135\228\191\174\230\173\163:%f, \230\156\128\229\164\167\230\141\149\230\141\137\231\142\135:%f)\n          * MIN(1, \229\133\168\229\177\128\230\141\149\230\141\137\233\154\190\229\186\166\229\184\184\230\149\176:%f^(\229\189\147\229\137\141\232\161\128\233\135\143HP:%f/\231\178\190\231\129\181\233\152\136\229\128\188HP:%f-1)) / (\231\173\137\231\186\167\228\191\174\230\173\163\229\143\130\230\149\176:%f^MAX(0\239\188\140\233\135\142\231\148\159\231\178\190\231\129\181\231\173\137\231\186\167:%f-\231\173\137\231\186\167\228\184\138\233\153\144:%f))", rate, overThreshold, guaranteeRate, ballProb, handBookCatchChangeProb, seasonModify, maxCatchRate, catchHardA, curHp, thresholdHp, levelParam, npcLevel, petTopLevel)
  end
  return rate
end

function BattleUtils.CalculatePetThresholdHp(petThreshold, ballThreshold, handBookProb, detectedProb, peerModify)
  local calcThreshold = math.min(1, (petThreshold + handBookProb) * (1 + ballThreshold + detectedProb + peerModify))
  if GlobalConfig.ShowCatchRate then
    Log.PrintScreenMsgRed("[\230\141\149\230\141\137\230\166\130\231\142\135]\231\178\190\231\129\181\233\152\136\229\128\188HP(%f) = math.min(1,(\229\159\186\231\161\128\233\152\136\229\128\188:%f + \229\155\190\233\137\180\233\152\136\229\128\188\228\191\174\230\173\163:%f) * (1 + \230\138\128\229\183\167\231\144\131\228\191\174\230\173\163:%f + \229\129\183\232\162\173\228\191\174\230\173\163:%f + \229\144\140\232\161\140\228\191\174\230\173\163:%f))", calcThreshold, petThreshold, handBookProb, ballThreshold, detectedProb, peerModify)
  end
  return calcThreshold
end

function BattleUtils.CalculateSneakModifyValue(isInBattle, isBackStabState, ballConfID, remoteHitModify)
  local sneakModifyResult = 0
  local ballDefaultSneakModify = 0
  local ballSneakModifyValue = 0
  if ballConfID then
    local probCalculateParam = DataConfigManager:GetGlobalConfigNumByKeyType("prob_calculate_param", _G.DataConfigManager.ConfigTableId.GLOBAL_CONFIG, 10000) or 10000
    local ballActConf = _G.DataConfigManager:GetBallAct(ballConfID, true)
    if ballActConf then
      ballDefaultSneakModify = (ballActConf and ballActConf.default_sneak_modify ~= "" and ballActConf.default_sneak_modify or 0) / probCalculateParam
      if isBackStabState then
        ballSneakModifyValue = (ballActConf and ballActConf.sneak_modify or 0) / probCalculateParam
      end
    end
  end
  sneakModifyResult = math.max(sneakModifyResult, ballDefaultSneakModify)
  sneakModifyResult = math.max(sneakModifyResult, ballSneakModifyValue)
  if not isInBattle and remoteHitModify then
    sneakModifyResult = math.max(sneakModifyResult, remoteHitModify)
  end
  if GlobalConfig.ShowCatchRate then
    Log.PrintScreenMsgRed("[\230\141\149\230\141\137\230\166\130\231\142\135]\229\129\183\232\162\173\228\191\174\230\173\163(%f): \231\137\185\229\174\154\231\144\131\229\129\183\232\162\173\228\191\174\230\173\163(%f), \231\138\182\230\128\129\229\129\183\232\162\173\228\191\174\230\173\163(%f) \229\177\128\229\164\150\232\191\156\232\183\157\231\166\187\229\129\183\232\162\173\228\191\174\230\173\163(%f)", sneakModifyResult, ballDefaultSneakModify, ballSneakModifyValue, remoteHitModify)
  end
  return sneakModifyResult
end

function BattleUtils.CalculateBallProb(data)
  if data.ballConfID == nil or nil == data.isInBattle then
    Log.Error("BattleUtils.CalculateBallThresholdBattle: ball threshold calculate data invalid")
    return 0
  end
  local ballCfg = _G.DataConfigManager:GetBallConf(data.ballConfID)
  if not ballCfg then
    Log.Error("BattleUtils.CalculateBallThresholdBattle: ball cfg can not be found with id:", data.ballID)
    return 0
  end
  if ballCfg.ball_type == ProtoEnum.BallType.BT_CONDITION then
    if BattleUtils.CalculateBallProb_CONDITION(data, ballCfg) then
      return ballCfg.ball_prob
    else
      return ballCfg.Noeffect_ball_prob
    end
  elseif ballCfg.ball_type == ProtoEnum.BallType.BT_NORMAL then
    if BattleUtils.CalculateBallProb_Normal(data, ballCfg) then
      return ballCfg.ball_prob
    else
      return ballCfg.Noeffect_ball_prob
    end
  elseif ballCfg.ball_type == ProtoEnum.BallType.BT_WEATHER then
    if BattleUtils.CalculateBallProb_WEATHER(data, ballCfg) then
      return ballCfg.ball_prob
    else
      return ballCfg.Noeffect_ball_prob
    end
  elseif ballCfg.ball_type == ProtoEnum.BallType.BT_PETSDT then
    if BattleUtils.CalculateBallProb_PETSDT(data, ballCfg) then
      return ballCfg.ball_prob
    else
      return ballCfg.Noeffect_ball_prob
    end
  elseif ballCfg.ball_type == ProtoEnum.BallType.BT_PETACT then
    if BattleUtils.CalculateBallProb_PETACT(data, ballCfg) then
      return ballCfg.ball_prob
    else
      return ballCfg.Noeffect_ball_prob
    end
  end
  return ballCfg.Noeffect_ball_prob
end

function BattleUtils.CalculateBallThresholdBattle(data)
  if data.ballConfID == nil or nil == data.isInBattle then
    Log.Error("BattleUtils.CalculateBallThresholdBattle: ball threshold calculate data invalid")
    return 0
  end
  local ballCfg = _G.DataConfigManager:GetBallConf(data.ballConfID)
  if not ballCfg then
    Log.Error("BattleUtils.CalculateBallThresholdBattle: ball cfg can not be found with id:", data.ballID)
    return 0
  end
  if ballCfg.ball_type == ProtoEnum.BallType.BT_CONDITION then
    if BattleUtils.CalculateBallThreshold_CONDITION(data, ballCfg) then
      return ballCfg.ball_threshold_modify
    else
      return ballCfg.Noeffect_threshold_modify or 0
    end
  elseif ballCfg.ball_type == ProtoEnum.BallType.BT_NORMAL then
    if BattleUtils.CalculateBallProb_Normal(data, ballCfg) then
      return ballCfg.ball_threshold_modify
    else
      return ballCfg.Noeffect_threshold_modify or 0
    end
  elseif ballCfg.ball_type == ProtoEnum.BallType.BT_WEATHER then
    if BattleUtils.CalculateBallProb_WEATHER(data, ballCfg) then
      return ballCfg.ball_threshold_modify
    else
      return ballCfg.Noeffect_threshold_modify or 0
    end
  elseif ballCfg.ball_type == ProtoEnum.BallType.BT_PETSDT then
    if BattleUtils.CalculateBallProb_PETSDT(data, ballCfg) then
      return ballCfg.ball_threshold_modify
    else
      return ballCfg.Noeffect_threshold_modify or 0
    end
  elseif ballCfg.ball_type == ProtoEnum.BallType.BT_PETACT then
    if BattleUtils.CalculateBallProb_PETACT(data, ballCfg) then
      return ballCfg.ball_threshold_modify
    else
      return ballCfg.Noeffect_threshold_modify or 0
    end
  end
  return 0
end

function BattleUtils.CalculateBallProb_Normal(data, ballCfg)
  return true
end

function BattleUtils.CalculateBallProb_PETACT(data, ballCfg)
  if data.isInBattle then
    if data.petID == nil then
      Log.Error("BattleUtils.CalculateBallThresholdBattle: BallType.BT_PETACT receive nil petID")
      return false
    end
    if nil == ballCfg.param_buff or 0 == #ballCfg.param_buff then
      return false
    end
    local card = _G.BattleManager.battlePawnManager:GetCardByGuid(data.petID)
    for _, param in ipairs(ballCfg.param_buff) do
      local buffs = card.petInfo.battle_inside_pet_info.buffs
      if buffs then
        for _, buff in ipairs(buffs) do
          local buffCfg = _G.DataConfigManager:GetBuffConf(buff.buff_id)
          if buffCfg then
            for _, sign in ipairs(buffCfg.buff_groupsigns) do
              if sign == param then
                return true
              end
            end
          end
        end
      else
        return false
      end
    end
  else
    if data.petID == nil then
      Log.Error("BattleUtils.CalculateBallThresholdBattle: BallType.BT_PETACT receive nil petID")
      return false
    end
    if nil == ballCfg.param_blackboard or 0 == #ballCfg.param_blackboard then
      return false
    end
    if data.bMatchBallAIState == true then
      return true
    end
  end
  return false
end

function BattleUtils.CalculateBallProb_PETSDT(data, ballCfg)
  if data.petID == nil then
    Log.Error("BattleUtils.CalculateBallThresholdBattle: BallType.BT_PETSDT receive nil petID")
    return false
  end
  local types = {}
  if data.isInBattle then
    local battlePet = _G.BattleManager.battlePawnManager:GetPetByGuid(data.petID)
    types = battlePet.card:GetPetType()
  else
    local petBaseId = _G.DataConfigManager:GetMonsterConf(data.petID).base_id
    types = _G.DataConfigManager:GetPetbaseConf(petBaseId).unit_type
  end
  for _, param in ipairs(ballCfg.param_skilldam) do
    for _, type in ipairs(types) do
      if type == param then
        return true
      end
    end
  end
  return false
end

function BattleUtils.CalculateBallProb_WEATHER(data, ballCfg)
  if data.weatherID == nil then
    Log.Error("BattleUtils.CalculateBallThresholdBattle: BallType.BT_WEATHER receive nil weatherID")
    return false
  end
  local curWeatherType = Enum.WeatherType.WT_NONE
  if data.isInBattle then
    local weatherConf = _G.DataConfigManager:GetWeatherConf(_G.BattleManager.battleRuntimeData.curWeatherID)
    if not weatherConf then
      Log.Error("\230\148\182\229\136\176\230\156\170\229\174\154\228\185\137\231\154\132weather_id:", _G.BattleManager.battleRuntimeData.curWeatherID)
      return false
    end
    curWeatherType = weatherConf.weather_type
  else
    curWeatherType = data.weatherID
  end
  for _, param in ipairs(ballCfg.param_weather) do
    if param == curWeatherType then
      return true
    end
  end
  return false
end

function BattleUtils.CalculateBallThreshold_MovementMode(data, ballCfg)
  if data.isInBattle then
    return false
  end
  return data.bMatchBallAIState
end

function BattleUtils.CalculateBallThreshold_PetSurface(data, ballCfg)
  if not data.isInBattle then
    return false
  end
  if ballCfg.param_surface == nil or 0 == #ballCfg.param_surface then
    return false
  end
  if nil == data.petID then
    Log.Error("BattleUtils.CalculateBallThreshold_PetSurface: receive nil petID")
    return false
  end
  local battlePet = _G.BattleManager.battlePawnManager:GetPetByGuid(data.petID)
  if not battlePet then
    return false
  end
  for _, param in ipairs(ballCfg.param_surface) do
    if param == ProtoEnum.PetSurfaceType.PST_WATER and BattleUtils.IsWaterBattle() and battlePet:GetCanSwimming() then
      return true
    end
  end
  return false
end

function BattleUtils.CalculateBallProb_CONDITION(data, ballCfg)
  return BattleUtils.CalculateBallProb_PETACT(data, ballCfg) or BattleUtils.CalculateBallProb_PETSDT(data, ballCfg) or BattleUtils.CalculateBallProb_WEATHER(data, ballCfg)
end

function BattleUtils.CalculateBallThreshold_CONDITION(data, ballCfg)
  return BattleUtils.CalculateBallProb_PETACT(data, ballCfg) or BattleUtils.CalculateBallProb_PETSDT(data, ballCfg) or BattleUtils.CalculateBallProb_WEATHER(data, ballCfg) or BattleUtils.CalculateBallThreshold_MovementMode(data, ballCfg) or BattleUtils.CalculateBallThreshold_PetSurface(data, ballCfg)
end

function BattleUtils.CalculatePeerModify()
  local peerModify = 0
  local localPlayer = NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  if localPlayer then
    local bAddPeerModify = localPlayer.statusComponent:HasStatus(ProtoEnum.WorldPlayerStatusType.WPST_HAND_IN_HAND) or localPlayer.statusComponent:HasStatus(ProtoEnum.WorldPlayerStatusType.WPST_HAND_IN_HAND_2P) or localPlayer.viewObj.BP_RideComponent:IsInDoubleRide()
    if bAddPeerModify then
      peerModify = DataConfigManager:GetBattleGlobalConfig("peer_modify").num
    end
  end
  return peerModify
end

function BattleUtils.CalculateCatchMonsterRateBattle(ballConfID, petGUID)
  local card = _G.BattleManager.battlePawnManager:GetCardByGuid(petGUID)
  if not card then
    Log.Error("BattleUtils.CalculateCatchMonsterRateBattle with wrong guid:", petGUID)
    return 0
  end
  if card.petInfo.battle_inside_pet_info.catch_info == nil then
    return 0
  end
  local data = {}
  data.ballConfID = ballConfID
  data.isInBattle = true
  data.petID = petGUID
  data.weatherID = _G.BattleManager.battleRuntimeData.curWeatherID
  local insidePetInfo = card.petInfo.battle_inside_pet_info
  local probCalculateParam = DataConfigManager:GetGlobalConfigNumByKeyType("prob_calculate_param", _G.DataConfigManager.ConfigTableId.GLOBAL_CONFIG, 10000) or 10000
  local ballProb = BattleUtils.CalculateBallProb(data) / probCalculateParam
  local ballThresholdBattle = BattleUtils.CalculateBallThresholdBattle(data) / probCalculateParam
  local petThreshold = insidePetInfo.catch_info.threshold / probCalculateParam
  local monsterBaseId = insidePetInfo.base_conf_id
  local handBookReward, totalAwardCatch, totalAwardPetCatchChange = _G.NRCModuleManager:DoCmd(_G.HandbookModuleCmd.GetPetHandbookCurrentProgressTaskReward, monsterBaseId)
  local handBookCatchChangeProb = 0
  local handBookProb = 0
  handBookProb = totalAwardCatch / probCalculateParam
  handBookCatchChangeProb = totalAwardPetCatchChange / probCalculateParam
  local isInSneakState = false
  local sneakBuffConf = _G.DataConfigManager:GetGlobalConfig("sneak_correction_battle")
  if sneakBuffConf and sneakBuffConf.str then
    local sneakBuffStrList = string.Split(sneakBuffConf.str, ";")
    for _, param in ipairs(sneakBuffStrList) do
      local buffs = card.petInfo.battle_inside_pet_info.buffs
      if buffs then
        for _, buff in ipairs(buffs) do
          local buffCfg = _G.DataConfigManager:GetBuffConf(buff.buff_id)
          if buffCfg then
            for _, sign in ipairs(buffCfg.buff_groupsigns) do
              if sign == Enum.BuffGroupSign[param] then
                isInSneakState = true
                break
              end
            end
          end
        end
        if isInSneakState then
          break
        end
      end
    end
  end
  local sneakModify = BattleUtils.CalculateSneakModifyValue(true, isInSneakState, ballConfID, 0)
  local peerModify = BattleUtils.CalculatePeerModify() / probCalculateParam
  local thresholdHP = BattleUtils.CalculatePetThresholdHp(petThreshold, ballThresholdBattle, handBookProb, sneakModify, peerModify)
  local monsterConfID = insidePetInfo.conf_id
  local level = card.petInfo.battle_common_pet_info.level
  local curHpPercent = card.hp / card.max_hp
  local catchGuaranteeRate = insidePetInfo.catch_guarantee_rate or 0
  local lastCatchTime = insidePetInfo.last_catch_time or 0
  local CurBattlePlayer = BattleManager.battlePawnManager and BattleManager.battlePawnManager.TeamatePlayer
  local seasonModify = CurBattlePlayer and CurBattlePlayer.roleInfo and CurBattlePlayer.roleInfo.base and CurBattlePlayer.roleInfo.base.season_adv_prob_add or 0
  return BattleUtils.CalculateFinalRate(ballConfID, monsterConfID, level, curHpPercent, thresholdHP, handBookCatchChangeProb, ballProb, catchGuaranteeRate, lastCatchTime, seasonModify)
end

function BattleUtils.GetEnemyTeamEnum(TeamEnum)
  if TeamEnum == BattleEnum.Team.ENUM_ENEMY then
    return BattleEnum.Team.ENUM_TEAM
  end
  return BattleEnum.Team.ENUM_ENEMY
end

function BattleUtils.GetInBattle(info)
  return BattleUtils.GetPetBit(info, ProtoEnum.PET_BIT_TYPE.BT_IN_BATTLE)
end

function BattleUtils.GetBeCatch(info)
  return BattleUtils.GetPetBit(info, ProtoEnum.PET_BIT_TYPE.BT_BATTLE_CATCHED)
end

function BattleUtils.GetIsBanSkill(info)
  return BattleUtils.GetPetBit(info, ProtoEnum.PET_BIT_TYPE.BT_BAN_ACTIVE_SKILL)
end

function BattleUtils.GetIsRidOf(info)
  return BattleUtils.GetPetBit(info, ProtoEnum.PET_BIT_TYPE.BT_BLOWED_DOWN)
end

function BattleUtils.GetHasCatchInfo(info)
  return BattleUtils.GetPetBit(info, ProtoEnum.PET_BIT_TYPE.BT_MONSTER_HAS_CATCH_INFO)
end

function BattleUtils.GetIsRunAway(info)
  return BattleUtils.GetPetBit(info, ProtoEnum.PET_BIT_TYPE.BT_BATTLE_RUN_AWAY)
end

function BattleUtils.GetIsPetPrepare(info)
  return BattleUtils.GetPetBit(info, ProtoEnum.PET_BIT_TYPE.BT_PET_PREPARE)
end

function BattleUtils.GetPetBit(info, index)
  local num = math.floor(index / 32) + 1
  local move = index % 32
  if info and info.state_bits and info.state_bits[num] then
    return info.state_bits[num] & 1 << move > 0
  else
    return false
  end
end

function BattleUtils.GetPetBitNew(info, index)
  if info then
    return info.state_bit & 1 << index > 0
  else
    return false
  end
end

function BattleUtils.GetBit(state_bit, index)
  if not state_bit then
    return false
  end
  return state_bit & 1 << index > 0
end

function BattleUtils.CheckCanCatchMonster()
  if not BattleUtils.IsCatchBattleMode() then
    Log.Error("not in catch mode")
    return false
  end
  local hasBall = _G.NRCModeManager:DoCmd(_G.BagModuleCmd.CheckHasBagItemByType, Enum.BagItemType.BI_PET_BALL)
  if not hasBall then
    return false, _G.LuaText.CATCH_INFO_PETBALL_NUM_NO_ENOUGH
  end
  local catchData = _G.BattleManager.battleRuntimeData and _G.BattleManager.battleRuntimeData.catchInfo
  if not catchData then
    Log.Error("catch data is nil")
    return false
  end
  if catchData.curCatchTime <= 0 then
    return false, _G.LuaText.CATCH_INFO_CATCH_TIME_OVER
  end
  return true
end

function BattleUtils.CheckCanChangePet()
  local exchange_initial_cooldown = BattleUtils.GetBattleConfig().exchange_initial_cold
  local currentRound = _G.BattleManager.battleRuntimeData and _G.BattleManager.battleRuntimeData.roundIndex
  if exchange_initial_cooldown >= currentRound then
    local coolDownRes = exchange_initial_cooldown - currentRound + 1
    return false, string.format(_G.LuaText.Battle_Cant_Change_Pet, coolDownRes)
  end
  local lastChangeRound = _G.BattleManager.battleRuntimeData.lastChangePetRoundIndex
  if not lastChangeRound then
    return true
  end
  if 0 == lastChangeRound then
    return true
  end
  local exchange_cooldown = BattleUtils.GetBattleConfig().exchange_cold
  if currentRound <= lastChangeRound + exchange_cooldown then
    local coolDownRes = lastChangeRound + exchange_cooldown - currentRound + 1
    return false, string.format(_G.LuaText.Battle_Cant_Change_Pet, coolDownRes)
  end
  return true
end

function BattleUtils.CheckIfChangePetBan(pet)
  if not pet then
    return false
  end
  return BattleUtils.GetPetBit(pet.card.petInfo.battle_inside_pet_info, ProtoEnum.PET_BIT_TYPE.BT_BAN_STATUS_CHANGE_PET)
end

function BattleUtils.CheckIfSkillBan(pet)
  if not pet then
    return true
  end
  return BattleUtils.GetPetBit(pet.card.petInfo.battle_inside_pet_info, ProtoEnum.PET_BIT_TYPE.BT_BAN_STATUS_SKILL)
end

function BattleUtils.CheckIfSkillTypeBan(pet, skill)
  if not pet then
    return true
  end
  local bitType
  local damageType = skill.skillData.damage_type or skill.config.damage_type
  if damageType == Enum.DamageType.DT_NONE then
    bitType = ProtoEnum.PET_BIT_TYPE.BT_BAN_STATUS_NON_DAM_SKILL
  elseif damageType == Enum.DamageType.DT_PHY then
    bitType = ProtoEnum.PET_BIT_TYPE.BT_BAN_STATUS_PHY_DAM_SKILL
  elseif damageType == Enum.DamageType.DT_SPC then
    bitType = ProtoEnum.PET_BIT_TYPE.BT_BAN_STATUS_SPE_DAM_SKILL
  else
    return true
  end
  return BattleUtils.GetPetBit(pet.card.petInfo.battle_inside_pet_info, bitType)
end

function BattleUtils.CheckIfSkillFeverBan(pet, skill)
  if pet and pet.card and pet.card.petState:IsFever() and not skill:IsFeverSkill() and skill:IsNormalSkill() then
    return true
  end
  return false
end

function BattleUtils.CheckIfSkillLegendaryBan(pet, skill)
  if skill.skillData.state == ProtoEnum.SkillState.SKILL_LEGENDARY_INVALID then
    return true
  end
  return false
end

function BattleUtils.CheckIfSkillLegendaryTimeLimitBan(pet, skill)
  if skill.skillData.state == ProtoEnum.SkillState.SKILL_LEGENDARY_LIMIT then
    return true
  end
  return false
end

function BattleUtils.CheckIfSkillTeamBan(pet, skill)
  if skill.skillData.state == ProtoEnum.SkillState.SKILL_TEAM_INVALID then
    return true
  end
  return false
end

function BattleUtils.CheckIfSkillB1FinalBan(pet, skill)
  if skill.skillData.state == ProtoEnum.SkillState.SKILL_B1_FORBID then
    return true
  end
  return false
end

function BattleUtils.CheckIfSkillEnvBan(pet, skill)
  if BattleUtils.IsDeepWater() then
    return 1 == skill.config.env_ban
  end
  return false
end

function BattleUtils.GetChangeToBattleShowWindowID(config)
  if not config.screen_show_res or config.screen_show_res == "" then
    return require("NewRoco.Modules.Core.Battle.Common.BattleConst").Show.ChangeToBattleDefaultShow
  else
    return config.screen_show_res
  end
end

function BattleUtils.GetPetBallPath(petData)
  local ballId = petData.ball_id
  if not ballId or 0 == ballId then
    ballId = _G.DataConfigManager:GetBattleGlobalConfig("base_prob_ball_id").num
  end
  local ballCfg = _G.DataConfigManager:GetBallConf(ballId)
  if not ballCfg then
    Log.ErrorFormat("\229\146\149\229\153\156\231\144\131\233\133\141\231\189\174\228\184\186\231\169\186 %d", ballId)
    return ""
  end
  if not ballCfg.fx_source then
    Log.ErrorFormat("\229\146\149\229\153\156\231\144\131\233\133\141\231\189\174\228\184\186\231\169\186 %d", ballId)
    return ""
  end
  local modelConf = _G.DataConfigManager:GetModelConf(ballCfg.fx_source)
  if modelConf and modelConf.path then
    return modelConf.path
  else
    Log.ErrorFormat("\229\146\149\229\153\156\231\144\131\233\133\141\231\189\174\228\184\186\231\169\186 %d", ballId)
    return ""
  end
end

function BattleUtils.PlayDefaultTargetCamera(target_pet_id, owner, callback)
  local TeamEnum = _G.BattleManager.battlePawnManager:GetTeamByPetGuid(target_pet_id)
  if TeamEnum == BattleEnum.Team.ENUM_TEAM then
    _G.BattleManager.vBattleField.battleFieldActor:PlayAnim(BattleConst.SkillID.PlayStageBuffCameraShow, owner, callback)
  else
    _G.BattleManager.vBattleField.battleFieldActor:PlayAnim(BattleConst.SkillID.PlayStageAttackCameraShow, owner, callback)
  end
end

function BattleUtils.GetBattleUIModule()
  return NRCModuleManager:GetModule("BattleUIModule")
end

function BattleUtils.HasBattleLoading()
  local module = BattleUtils.GetBattleUIModule()
  if module then
    return module:HasPanel("BattleLoading")
  else
    return false
  end
end

function BattleUtils.HasPVPPrepare()
  return NRCModuleManager:DoCmd(BattleUIModuleCmd.GetPVP_PreparePanelState)
end

function BattleUtils.GetLoadingUIModule()
  return NRCModuleManager:GetModule("LoadingUIModule")
end

function BattleUtils.HasFastLoading()
  local module = BattleUtils.GetLoadingUIModule()
  if module then
    local loadingUI = module:GetPanel("UMG_FastLoadingUI")
    if loadingUI and loadingUI:GetVisibility() == UE4.ESlateVisibility.Visible then
      return true
    else
      return false
    end
  else
    return false
  end
end

function BattleUtils.GetSceneModule()
  return NRCModuleManager:GetModule("SceneModule")
end

function BattleUtils.GetNPCModule()
  return NRCModuleManager:GetModule("NPCModule")
end

function BattleUtils.GetPlayer()
  return NRCModuleManager:DoCmd(_G.PlayerModuleCmd.GET_LOCAL_PLAYER)
end

function BattleUtils.SetPlayerSkmTickable(value)
  do return end
  local localPlayer = BattleUtils.GetPlayer()
  if localPlayer and localPlayer.viewObj then
    localPlayer.viewObj.Mesh:SetComponentTickEnabled(value)
  end
end

function BattleUtils.SetPlayerVisible(player, visible)
  if not player then
    return
  end
  player:SetVisible(visible)
end

function BattleUtils.GetPlayerModel()
  local Player = BattleUtils.GetPlayer()
  return Player and Player.viewObj
end

function BattleUtils.GetTraceNpc()
  local NPC, id = _G.BattleManager.battleRuntimeData:GetCurrentNPC()
  if not NPC then
    return nil
  end
  local Cache = {}
  Cache.id = id
  Cache.npc = NPC
  Cache.transform = NPC:GetActorTransform()
  Cache.config = NPC.config
  return Cache
end

function BattleUtils.GetAllTraceNpc()
  local npcs = _G.BattleManager.battleRuntimeData:GetAllNPCs()
  if not npcs then
    return nil
  end
  local Caches = {}
  for _, v in ipairs(npcs) do
    local Cache = {}
    Cache.id = v.id
    Cache.npc = v.npc
    Cache.transform = v.npc:GetActorTransform()
    Cache.config = v.npc.config
    table.insert(Caches, Cache)
  end
  return Caches
end

function BattleUtils.ClearTraceNpc()
end

function BattleUtils.HasUI(name)
  if string.IsNilOrEmpty(name) then
    return false
  end
  local Module = BattleUtils.GetBattleUIModule()
  return Module and Module:HasPanel(name) or false
end

function BattleUtils.IsOpeningUI(name)
  if string.IsNilOrEmpty(name) then
    return false
  end
  local Module = BattleUtils.GetBattleUIModule()
  return Module and Module:IsPanelInOpening(name) or false
end

function BattleUtils.HasMainWindow()
  if BattleUtils.IsTeam() then
    return BattleUtils.HasUI("BattleMain") and BattleUtils.HasUI("UMG_Pet_GroupWarfare")
  else
    return BattleUtils.HasUI("BattleMain")
  end
end

function BattleUtils.IsMainWindowReady()
  if not BattleUtils.HasMainWindow() then
    return false
  end
  local mainWindow = BattleUtils.GetMainWindow()
  if mainWindow then
    return mainWindow:IsFullyConstructed()
  end
  return false
end

function BattleUtils.HasEnterWindow()
  return BattleUtils.HasUI("BattleEnter")
end

function BattleUtils.GetUI(name)
  if string.IsNilOrEmpty(name) then
    return nil
  end
  local Module = BattleUtils.GetBattleUIModule()
  if Module and Module:HasPanel(name) then
    return Module:GetPanel(name)
  end
  return false
end

function BattleUtils.GetMainWindow()
  return BattleUtils.GetUI("BattleMain")
end

function BattleUtils.GetEnterWindow()
  return BattleUtils.GetUI("BattleEnter")
end

function BattleUtils.IsChangeToRunAway()
  local mainWindow = BattleUtils.GetMainWindow()
  return mainWindow and mainWindow.UMG_Battle_Operate and mainWindow.UMG_Battle_Operate.changeToRunAway or false
end

function BattleUtils.GetSkillPathByResId(id)
  if not id then
    return nil
  end
  local SkillResConf = DataConfigManager:GetSkillResConf(id, true)
  if SkillResConf then
    return SkillResConf.res_id
  end
end

function BattleUtils.GetSkillClass(id)
  if not id then
    return nil
  end
  local SkillResConf = DataConfigManager:GetSkillResConf(id, true)
  if not SkillResConf then
    return nil
  end
  local Klass = BattleResourceManager:LoadUClass(SkillResConf.res_id)
  if 791201 == id then
    Klass = BattleResourceManager:LoadUClass(_G.BattleConst.Define.CATCH_SKILL)
  end
  return Klass
end

function BattleUtils.GetSkillClassBySkillId(id)
  local SkillConf = _G.SkillUtils.GetSkillConf(id, true)
  if not SkillConf then
    return nil
  end
  local Klass = BattleSkillManager:GetLoadedClass(SkillConf.res_id)
  return Klass
end

function BattleUtils.FocusPlayer(Time)
  local Player = BattleUtils.GetPlayer()
  if not Player then
    return
  end
  Player:GetUEController():ReleaseRocoCamera(Time or 0, nil, nil, true)
end

function BattleUtils.RequestPlayerCam()
  local Player = BattleUtils.GetPlayer()
  if not Player then
    return
  end
  local Location, Rotation, FOV = Player:GetUEController().PlayerCameraManager:GetBigWorldCameraFinalPOV()
  local cam = Player:GetUEController():RequestRocoCamera(0)
  local KamComp = cam:GetComponentByClass(UE4.UCameraComponent)
  KamComp:K2_SetWorldLocationAndRotation(Location, Rotation, false, nil, false)
  return cam
end

function BattleUtils.GetAttachPointNameByType(PointType)
  local tranMap = {
    [UE4.EFXAttachPointType.Pos] = "locator_pos",
    [UE4.EFXAttachPointType.WeaponFX] = "locator_weapon_fx",
    [UE4.EFXAttachPointType.RightHand] = "locator_right_hand",
    [UE4.EFXAttachPointType.Foot] = "locator_foot",
    [UE4.EFXAttachPointType.LeftHand] = "locator_left_hand",
    [UE4.EFXAttachPointType.Hurt] = "locator_hurt",
    [UE4.EFXAttachPointType.Head] = "locator_head",
    [UE4.EFXAttachPointType.LeftFoot] = "locator_left_foot",
    [UE4.EFXAttachPointType.RightFoot] = "locator_right_foot",
    [UE4.EFXAttachPointType.Hp] = "locator_hp",
    [UE4.EFXAttachPointType.Body] = "locator_body",
    [UE4.EFXAttachPointType.LBall] = "locator_L_ball",
    [UE4.EFXAttachPointType.RBall] = "locator_R_ball"
  }
  return tranMap[PointType]
end

function BattleUtils.ToggleInput(enabled)
  local localPlayer = NRCModeManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  if localPlayer then
    localPlayer.inputComponent:SetInputEnable({
      name = "BattleUtils"
    }, enabled, "Battle")
  end
end

function BattleUtils.ToggleMove(enabled)
  local localPlayer = NRCModeManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  if localPlayer then
    localPlayer:PausePlayerMovement(BattleUtils, not enabled)
    if not enabled then
      localPlayer:Stop()
    end
  end
end

function BattleUtils.IsPve()
  return BattleUtils.HasEnemyPlayer() and BattleUtils.IsPveType() or _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_ASSISTBOSSFIGHT
end

function BattleUtils.IsPveType()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_PVE or _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_PVC or _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_CRUCIAL or _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_PLOT or _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_TRAIN_BATTLE
end

function BattleUtils.IsOnlyPve()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_PVE
end

function BattleUtils.IsSpecialDelayPve()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_PVESPECIAL
end

function BattleUtils.IsLeaderFight()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_LEADERFIGHT or _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_DUNGEONBOSS or _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_BOSS_CHALLENGE
end

function BattleUtils.IsWorldLeaderFight()
  local battleType = _G.BattleManager.battleRuntimeData.battleType
  return battleType == Enum.BattleType.BT_WORLDLEADER or battleType == Enum.BattleType.BT_BOSS_CHALLENGE
end

function BattleUtils.IsTeam()
  return BattleUtils.IsBloodTeam() or BattleUtils.IsBeastTeam() or BattleUtils.IsStoryTeam()
end

function BattleUtils.IsRunAwayFree()
  return BattleUtils.IsWorldLeaderFight() or BattleUtils.IsTeam()
end

function BattleUtils.IsBloodTeam()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_TEAM_BATTLE
end

function BattleUtils.IsBeastTeam()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_LEGENDARY_BATTLE
end

function BattleUtils.IsStoryTeam()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_STORY_TEAM_BATTLE
end

function BattleUtils.IsJiaerBeastTeam()
  if not BattleUtils.IsBeastTeam() then
    return false
  end
  local battleConfig = _G.BattleManager.battleRuntimeData.battleConfig
  return battleConfig and battleConfig.legendary_sub_type == Enum.LegendarySubType.LST_JIAER
end

function BattleUtils.IsWeeklyChallenge()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_WEEKLY_CHALLENGE
end

function BattleUtils.IsTrainBattle()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_TRAIN_BATTLE
end

function BattleUtils.IsSeasonBoss()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_SEASONBOSS
end

function BattleUtils.isInSkillAutoTest()
  local ctrl = _G.BattleManager.battleRuntimeData.battleDebugControl
  if not ctrl then
    return false
  end
  if _G.BattleDebugMode then
    return ctrl.debugMode == _G.BattleDebugMode.AutoTest or ctrl.debugMode == _G.BattleDebugMode.TestPlaySkill
  end
  return false
end

function BattleUtils.IsInBattleTest()
  return _G.BattleManager.battleRuntimeData.battleDebugControl and _G.BattleManager.battleRuntimeData.battleDebugControl.isInBattleTest
end

function BattleUtils.IsAutoPlayPath()
  local ctrl = _G.BattleManager.battleRuntimeData.battleDebugControl
  if not ctrl then
    return false
  end
  if _G.BattleDebugMode then
    return ctrl.debugMode == _G.BattleDebugMode.RunTimeSkillAutoPlay
  end
  return false
end

function BattleUtils.IsWorldLeaderRewardRound()
  local initInfo = _G.BattleManager.battleRuntimeData.battleStartParam.battleInitInfo
  if initInfo and initInfo.world_leader_fight_info then
    return BattleUtils.IsWorldLeaderFight() and initInfo.world_leader_fight_info.execution_round
  end
end

function BattleUtils.GetWorldLeaderRewardCount()
  if BattleUtils.IsWorldLeaderRewardRound() and not BattleUtils.IsChangeToRunAway() then
    return _G.BattleManager.battleRuntimeData.battleStartParam.battleInitInfo.world_leader_fight_info.boss_register_skill_cnt or 1
  end
  return 1
end

function BattleUtils.GetWorldLeaderRewardPercent()
  local initInfo = _G.BattleManager.battleRuntimeData.battleStartParam.battleInitInfo
  if initInfo and initInfo.world_leader_fight_info then
    return _G.BattleManager.battleRuntimeData.battleStartParam.battleInitInfo.world_leader_fight_info.execution_trigger or 0
  end
  return 0
end

function BattleUtils.CanEnterWorldLeaderReward()
  local initInfo = _G.BattleManager.battleRuntimeData.battleStartParam.battleInitInfo
  if initInfo and initInfo.world_leader_fight_info then
    return _G.BattleManager.battleRuntimeData.battleStartParam.battleInitInfo.world_leader_fight_info.execution_trigger_available or false
  end
  return false
end

function BattleUtils.IsTeammatePlayerHasBall()
  local player = _G.BattleManager.battlePawnManager.TeamatePlayer
  local IsHasBall = false
  if player then
    local itemData = player.itemInfo or {}
    for _, v in ipairs(itemData) do
      if v.num > 0 and v.item_type == ProtoEnum.BagItemType.BI_PET_BALL then
        IsHasBall = true
        break
      end
    end
  end
  return IsHasBall
end

function BattleUtils.TeamIsCanCatch()
  if BattleUtils.IsBloodTeam() then
    if _G.NRCModeManager:DoCmd(BattleUIModuleCmd.IsSelectRecoveryItemEnough) and BattleUtils.IsTeammatePlayerHasBall() then
      return true
    end
  elseif BattleUtils.IsBeastTeam() then
    return true
  elseif BattleUtils.IsStoryTeam() then
    return false
  end
  return false
end

function BattleUtils.IsFinalBattleP1()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_AONE_FINAL_BATTLE_P1
end

function BattleUtils.IsFinalBattleP2()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_AONE_FINAL_BATTLE_P2
end

function BattleUtils.IsFinalBattle()
  return BattleUtils.IsFinalBattleP1() or BattleUtils.IsFinalBattleP2()
end

function BattleUtils.IsB1FinalBattleP1()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_FINAL_BATTLE_B1_STATE1
end

function BattleUtils.IsB1FinalBattleP2()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_FINAL_BATTLE_B1_STATE2
end

function BattleUtils.IsB1FinalBattleP3()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_FINAL_BATTLE_B1_STATE3
end

function BattleUtils.IsB1FinalBattle()
  return BattleUtils.IsB1FinalBattleP1() or BattleUtils.IsB1FinalBattleP2() or BattleUtils.IsB1FinalBattleP3()
end

function BattleUtils.CanCatchAtTeamFight()
  local enemies = _G.BattleManager.battlePawnManager:GetInFieldAllPet(BattleEnum.Team.ENUM_ENEMY)
  for _, v in ipairs(enemies) do
    if v.CanCatchAtTeamFight == true then
      return true
    end
  end
  return false
end

function BattleUtils.IsPlayerSelectCatchInBeast()
  local player = _G.BattleManager.battlePawnManager.TeamatePlayer
  if player and player.roleInfo then
    return 0 ~= player.roleInfo.base.state_bit & 1 << ProtoEnum.BATTLER_BIT_TYPE.BT_CAN_CATCH_BOSS
  end
  return false
end

function BattleUtils.IsBossPerformDegrade()
  local Boss = _G.BattleManager.battlePawnManager:GetTeamPet(BattleEnum.Team.ENUM_ENEMY, 1)
  if Boss then
    return Boss.CachePetBaseId == Boss.card.petBaseConf.id
  else
    return true
  end
end

function BattleUtils.IsBossPerformBeDefeated()
  local Boss = _G.BattleManager.battlePawnManager:GetTeamPet(BattleEnum.Team.ENUM_ENEMY, 1)
  if Boss then
    return Boss.IsPerformBeDefeated
  else
    return true
  end
end

function BattleUtils.IsBossPerformSpColor()
  local Boss = _G.BattleManager.battlePawnManager:GetTeamPet(BattleEnum.Team.ENUM_ENEMY, 1)
  if Boss then
    return Boss.IsPerformSpColor
  else
    return true
  end
end

function BattleUtils.HasEnemyPlayer()
  if not BattleUtils.GetBattleInitInfo() then
    return nil
  end
  local teams = BattleUtils.GetBattleInitInfo().enemy_team
  local ret = false
  for i = 1, #teams do
    ret = ret or 0 ~= BattleUtils.GetPlayerModelId(teams[i])
  end
  return ret
end

function BattleUtils.ShowPvpWaitSupplyPetTips()
  if BattleUtils.IsPvp() then
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, _G.LuaText.round_select_pet_tip, 99)
    _G.BattleManager.battleRuntimeData:SetEnemyOnThinking(true)
  end
end

function BattleUtils.IsSupplyPetState()
  local player = _G.BattleManager.battlePawnManager.TeamatePlayer
  if player and player:NeedSupplyPet() then
    return true
  end
  return false
end

function BattleUtils.IsMultiPlayerBattle()
  return BattleManager.battleRuntimeData.subBattleType == BattleEnum.SubBattleType.MultiPlayer
end

function BattleUtils.IsMultiPetBattle()
  return BattleManager.battleRuntimeData.subBattleType == BattleEnum.SubBattleType.MultiPet
end

function BattleUtils.IsMultiBattle()
  return BattleUtils.IsMultiPlayerBattle() or BattleUtils.IsMultiPetBattle()
end

function BattleUtils.IsPvp()
  return PetUtils.IsPvp()
end

function BattleUtils.IsPvpWithForm()
  local battleType = _G.BattleManager.battleRuntimeData.battleType
  local EBattleType = Enum.BattleType
  return battleType == EBattleType.BT_PVP_SRANDARD or battleType == EBattleType.BT_PVP_RANDOM or battleType == EBattleType.BT_PVP_WATER or battleType == EBattleType.BT_PVP_INSECT or battleType == EBattleType.BT_PVP_RANK or battleType == EBattleType.BT_PVP_THREE or battleType == EBattleType.BT_PVP_SCARE or battleType == EBattleType.BT_PVP_GAME1 or battleType == EBattleType.BT_PVP_GAME2 or battleType == EBattleType.BT_PVP_GAME3 or battleType == EBattleType.BT_PVP_GAME4
end

function BattleUtils.IsPvpRank()
  local battleType = _G.BattleManager.battleRuntimeData.battleType
  local EBattleType = Enum.BattleType
  return battleType == EBattleType.BT_PVP_RANK
end

function BattleUtils.IsPvpStandard()
  local battleType = _G.BattleManager.battleRuntimeData.battleType
  local EBattleType = Enum.BattleType
  return battleType == EBattleType.BT_PVP_SRANDARD
end

function BattleUtils.IsPvpScare()
  local battleType = _G.BattleManager.battleRuntimeData.battleType
  local EBattleType = Enum.BattleType
  return battleType == EBattleType.BT_PVP_SCARE
end

function BattleUtils.IsPvpRandom()
  local battleType = _G.BattleManager.battleRuntimeData.battleType
  local EBattleType = Enum.BattleType
  return battleType == EBattleType.BT_PVP_RANDOM
end

function BattleUtils.IsPvpThree()
  local battleType = _G.BattleManager.battleRuntimeData.battleType
  local EBattleType = Enum.BattleType
  return battleType == EBattleType.BT_PVP_THREE
end

function BattleUtils.IsPvpScare()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_PVP_SCARE
end

function BattleUtils.IsPvpCanBattleAgain()
  local battleType = _G.BattleManager.battleRuntimeData.battleType
  local EBattleType = Enum.BattleType
  return battleType == EBattleType.BT_PVP or battleType == EBattleType.BT_PVP_SRANDARD or battleType == EBattleType.BT_PVP_RANDOM or battleType == EBattleType.BT_PVP_WATER or battleType == EBattleType.BT_PVP_INSECT or battleType == EBattleType.BT_PVP_THREE or battleType == EBattleType.BT_PVP_GAME1 or battleType == EBattleType.BT_PVP_GAME2 or battleType == EBattleType.BT_PVP_GAME3 or battleType == EBattleType.BT_PVP_GAME4
end

function BattleUtils.IsNpcChallenge()
  local battleType = _G.BattleManager.battleRuntimeData.battleType
  local EBattleType = Enum.BattleType
  return battleType == EBattleType.BT_NPC_CHALLENGE
end

function BattleUtils.IsLeaderChallenge()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_BOSS_CHALLENGE
end

function BattleUtils.IsCrowdBattle()
  return BattleUtils.Is1VN() or BattleUtils.Is1V1V1()
end

function BattleUtils.Is1VN()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_1VN
end

function BattleUtils.Is1V1V1()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_1V1V1
end

function BattleUtils.IsPvw()
  return not BattleUtils.IsPve() and not BattleUtils.IsLeaderFight() and not BattleUtils.IsPvp()
end

function BattleUtils.IsTerritoryTrialBattle()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_TERRITORY_TRIAL
end

function BattleUtils.IsMultiMode()
  return _G.BattleManager.battleRuntimeData.subBattleType == BattleEnum.SubBattleType.MultiPet or _G.BattleManager.battleRuntimeData.subBattleType == BattleEnum.SubBattleType.MultiPlayer
end

function BattleUtils.IsReplayMode()
  return _G.BattleManager.battleRuntimeData.battleMode == BattleEnum.BattleMode.Replay
end

function BattleUtils.IsFriendAssist()
  return not BattleUtils.IsNpcAssist() and not BattleUtils.IsTeam() and not BattleUtils.IsB1FinalBattleP3() and 2 == #BattleManager.battlePawnManager.AllPlayerTeam
end

function BattleUtils.IsSpecialNoPc()
  return _G.BattleManager.battleRuntimeData.battleType == Enum.BattleType.BT_PVE_NO_PC
end

function BattleUtils.IsNpcAssist()
  local battleConf = BattleUtils.GetBattleConfig()
  local npc_battle_ally_list = battleConf and battleConf.npc_battle_ally_list or DummyTable
  local npc_battle_ally_list_count = #npc_battle_ally_list
  local battleManager = _G.BattleManager
  local battlePawnManager = battleManager and battleManager.battlePawnManager
  local allPlayerTeam = battlePawnManager and battlePawnManager.AllPlayerTeam or DummyTable
  local allPlayerTeamCount = #allPlayerTeam
  local isNpcAssist = npc_battle_ally_list_count > 0 and 2 == allPlayerTeamCount
  if BattleUtils.IsStoryTeam() then
    return false
  end
  return isNpcAssist
end

function BattleUtils.NpcAssistType()
  if BattleUtils.IsNpcAssist() then
    local playerTeams = _G.BattleManager.battlePawnManager:GetAllTeam(BattleEnum.Team.ENUM_TEAM)
    if #playerTeams >= 2 then
      if 0 == playerTeams[1].player.roleInfo.base.npc_id then
        return BattleEnum.NpcAssistType.WithPet
      else
        return BattleEnum.NpcAssistType.WithNpc
      end
    end
  end
  return BattleEnum.NpcAssistType.None
end

function BattleUtils.IsDeepWater()
  return BattleUtils.IsWaterBattle() or BattleUtils.IsLavaBattle()
end

function BattleUtils.IsWaterBattle()
  if UE4.UNRCStatics.IsEditorDeepWater() then
    return true
  end
  if _G.ForceTestWaterSurfaceBattle then
    BattleConst.CanBattleEverywhere = true
    return true
  end
  return _G.BattleManager.battleRuntimeData.battleWaterType == ProtoEnum.WaterBattleType.WBT_DEEP
end

function BattleUtils.IsLavaBattle()
  if UE4.UNRCStatics.IsEditorDeepWater() then
    return true
  end
  if _G.ForceTestWaterSurfaceBattle then
    BattleConst.CanBattleEverywhere = true
    return true
  end
  return _G.BattleManager.battleRuntimeData.battleWaterType == ProtoEnum.WaterBattleType.WBT_LAVA
end

function BattleUtils.IsSky()
  return BattleConst.EnableSkyBattle
end

function BattleUtils.IsSpeedPreplay()
  return BattleUtils.IsPvp() or BattleUtils.IsPveType() or BattleUtils.IsNpcChallenge() or BattleUtils.IsCrowdBattle()
end

function BattleUtils.IsNeedG6PreCheck()
  do return false end
  return not BattleUtils.IsPvp() and not BattleUtils.IsWeeklyChallenge()
end

function BattleUtils.GetBadgeChallengeBattleInfo()
  if _G.BattleManager.battleRuntimeData and _G.BattleManager.battleRuntimeData.battleStartParam then
    local battleInitInfo = _G.BattleManager.battleRuntimeData.battleStartParam.battleInitInfo
    if battleInitInfo then
      return battleInitInfo.grass_trial_battle_info
    end
  end
  return nil
end

function BattleUtils.GetBadgeChallengeEventType()
  local battleInfo = BattleUtils.GetBadgeChallengeBattleInfo()
  if battleInfo then
    return battleInfo.event_type
  end
  return nil
end

function BattleUtils.IsBadge2DType()
  local eventType = BattleUtils.IsBadgeChallenge()
  if eventType then
    return eventType ~= ProtoEnum.EventType.ET_BOSS_FIGHT
  end
  return false
end

function BattleUtils.IsBadgeNPCType()
  return BattleUtils.IsBadgeChallenge() == ProtoEnum.EventType.ET_NPC_FIGHT
end

function BattleUtils.IsBadgeBossType()
  return BattleUtils.IsBadgeChallenge() == ProtoEnum.EventType.ET_BOSS_FIGHT
end

function BattleUtils.IsBadgeChallenge()
  return _G.BattleManager:IsInBattle() and BattleUtils.GetBadgeChallengeEventType()
end

function BattleUtils.NeedBadgeDisplayPet()
  local eventType = BattleUtils.IsBadgeChallenge()
  if eventType then
    return eventType == ProtoEnum.EventType.ET_MONSTER_NORMAL or eventType == ProtoEnum.EventType.ET_MONSTER_LEADER
  end
  return false
end

function BattleUtils.GetSkillIdToForkRoadBuffIdList(buffInfoList)
  buffInfoList = buffInfoList or DummyTable
  local skillIdToForkRoadBuffIdList = {}
  for i, buffInfo in ipairs(buffInfoList) do
    local baseSkillId = buffInfo and buffInfo.sk_data_id
    baseSkillId = _G.SkillUtils.CheckSkillId(baseSkillId)
    local mergedSkillId = buffInfo and buffInfo.merged_skill_id
    mergedSkillId = _G.SkillUtils.CheckSkillId(mergedSkillId)
    local buffId = buffInfo and buffInfo.buff_id
    if mergedSkillId and mergedSkillId > 0 then
      local list = skillIdToForkRoadBuffIdList and mergedSkillId and skillIdToForkRoadBuffIdList[mergedSkillId] or {}
      table.insert(list, buffId)
      if skillIdToForkRoadBuffIdList and mergedSkillId then
        skillIdToForkRoadBuffIdList[mergedSkillId] = list
      end
    elseif baseSkillId then
      local list = skillIdToForkRoadBuffIdList and baseSkillId and skillIdToForkRoadBuffIdList[baseSkillId] or {}
      table.insert(list, buffId)
      if skillIdToForkRoadBuffIdList and baseSkillId then
        skillIdToForkRoadBuffIdList[baseSkillId] = list
      end
    end
  end
  return skillIdToForkRoadBuffIdList
end

function BattleUtils.GetRecordFusedSkillDesc(data)
  if BattleUtils.IsBadgeChallenge() and data and data.skill_id then
    local skillData = {}
    local skillId = data and data.skill_id
    local baseSkillId = skillId and _G.SkillUtils.CheckSkillId(skillId)
    local grassTrailSkillInfo = data and data.grass_trial_skill_info
    local mergedSkillIdList = grassTrailSkillInfo and grassTrailSkillInfo.merged_skill_ids or {}
    skillData.base_skill_id = baseSkillId
    skillData.merged_skill_ids = mergedSkillIdList
    local forkRoadCastRecord = data.fork_road
    local forkRoadFace = forkRoadCastRecord and forkRoadCastRecord.fork_road_face
    local buffInfoList = forkRoadCastRecord and forkRoadCastRecord.buff_info_list
    local skillIdToForkRoadBuffIdList = BattleUtils.GetSkillIdToForkRoadBuffIdList(buffInfoList)
    return RogueModuleUtils.GetFusedSkillDesc(skillData, skillIdToForkRoadBuffIdList, forkRoadFace)
  end
  return nil
end

function BattleUtils.GetRoundFusedSkillDesc(data)
  if data and BattleUtils.IsBadgeChallenge() then
    local skillData = {}
    local skillId = data and data.skill_id
    local baseSkillId = skillId and _G.SkillUtils.CheckSkillId(skillId)
    local grassTrailSkillInfo = data and data.grass_trial_skill_info
    local mergedSkillIdList = grassTrailSkillInfo and grassTrailSkillInfo.merged_skill_ids or {}
    skillData.base_skill_id = baseSkillId
    skillData.merged_skill_ids = mergedSkillIdList
    return RogueModuleUtils.GetFusedSkillDesc(skillData)
  end
  return nil
end

function BattleUtils.GetRoundFusedSkillDescForkFace(data, forkRoadFaceData, forkRoadFace)
  if data and BattleUtils.IsBadgeChallenge() then
    local skillData = {}
    local skillId = data and data.skill_id
    local baseSkillId = skillId and _G.SkillUtils.CheckSkillId(skillId)
    local grassTrailSkillInfo = data and data.grass_trial_skill_info
    local mergedSkillIdList = grassTrailSkillInfo and grassTrailSkillInfo.merged_skill_ids or {}
    skillData.base_skill_id = baseSkillId
    skillData.merged_skill_ids = mergedSkillIdList
    local forkRoadEnhanceInfoList = forkRoadFaceData and forkRoadFaceData.fork_road_enhance_info or DummyTable
    local buffInfoList = {}
    for i, forkRoadEnhanceInfo in ipairs(forkRoadEnhanceInfoList) do
      local buffInfo = forkRoadEnhanceInfo and forkRoadEnhanceInfo.buff_info
      if buffInfo then
        table.insert(buffInfoList, buffInfo)
      end
    end
    local skillIdToForkRoadBuffIdList = BattleUtils.GetSkillIdToForkRoadBuffIdList(buffInfoList)
    return RogueModuleUtils.GetFusedSkillDesc(skillData, skillIdToForkRoadBuffIdList, forkRoadFace)
  end
  return nil
end

function BattleUtils.HideBadgeNearMeshActor(hide)
  local PropsActors = UE.UActorTagSubSystem.GetActorsByTag(_G.UE4Helper.GetCurrentWorld(), "GrassTrialNearMeshActor")
  for i = 1, PropsActors:Length() do
    local OneActor = PropsActors:Get(i)
    if UE.UObject.IsValid(OneActor) then
      OneActor:SetActorHiddenInGame(hide)
    end
  end
end

function BattleUtils.GetPetTypes(battle_inside_pet_info)
  return PetUtils.GetPetTypes(battle_inside_pet_info)
end

function BattleUtils.GetPetDefaultTypes(baseID)
  local conf = _G.DataConfigManager:GetPetbaseConf(baseID)
  local attrs = {
    0,
    0,
    0
  }
  if conf and conf.unit_type then
    for i = 1, 3 do
      if conf.unit_type[i] then
        attrs[i] = conf.unit_type[i]
      end
    end
  end
  return attrs
end

function BattleUtils.GetBattleType(battleID)
  local conf = _G.DataConfigManager.GetBattleConf(battleID)
  Log.Debug("BattleUtils GetBattleType:", battleID)
  return conf.type
end

function BattleUtils.GenerateRoundStartNotify(EnterNotify)
  if not EnterNotify then
    return nil
  end
  local State = EnterNotify.init_info.battle_state
  if State ~= _G.ProtoEnum.BATTLEFIELD_STATE.BATTLEFIELD_STATE_ROUND_PET and State ~= _G.ProtoEnum.BATTLEFIELD_STATE.BATTLEFIELD_STATE_ROUND_CMD and State ~= _G.ProtoEnum.BATTLEFIELD_STATE.BATTLEFIELD_STATE_CATCH then
    return nil
  end
  _G.BattleManager.battleRuntimeData.battleStartParam:SetBattleInitInfo(EnterNotify)
  _G.BattleManager.battleRuntimeData:SetBattleInitInfo(EnterNotify, true)
  local StartParam = _G.BattleManager.battleRuntimeData.battleStartParam
  local RuntimeData = _G.BattleManager.battleRuntimeData
  local fakeNotify = ProtoMessage:newZoneBattleRoundStartNotify()
  fakeNotify.state_info = ProtoMessage:newBattleStateInfo()
  if State == _G.ProtoEnum.BATTLEFIELD_STATE.BATTLEFIELD_STATE_ROUND_PET then
    fakeNotify.state_type = _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_PET
  elseif State == _G.ProtoEnum.BATTLEFIELD_STATE.BATTLEFIELD_STATE_CATCH then
    fakeNotify.state_type = _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_CATCH
  elseif State == _G.ProtoEnum.BATTLEFIELD_STATE.BATTLEFIELD_STATE_ROUND_EVOLUTION then
    fakeNotify.state_type = _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_EVOLUTION
  else
    fakeNotify.state_type = _G.ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_CMD
  end
  fakeNotify.perform_cmd = ProtoMessage:newBattlePerformCmd()
  fakeNotify.perform_cmd.seq_num = EnterNotify.data_seq_num
  local index = 1
  for i = 1, #EnterNotify.init_info.player_team do
    fakeNotify.perform_cmd.perform_info[index] = {
      type = ProtoEnum.BattlePerformType.BPT_DATA_UPDATE,
      data_update = {
        battler = EnterNotify.init_info.player_team[i]
      }
    }
    index = index + 1
  end
  for i = 1, #EnterNotify.init_info.enemy_team do
    fakeNotify.perform_cmd.perform_info[index] = {
      type = ProtoEnum.BattlePerformType.BPT_DATA_UPDATE,
      data_update = {
        battler = EnterNotify.init_info.enemy_team[i]
      }
    }
    index = index + 1
  end
  for i = 1, #EnterNotify.init_info.others do
    fakeNotify.perform_cmd.perform_info[index] = {
      type = ProtoEnum.BattlePerformType.BPT_DATA_UPDATE,
      data_update = {
        other = EnterNotify.init_info.others[i]
      }
    }
    index = index + 1
  end
  fakeNotify.state_info.round = RuntimeData.roundIndex
  fakeNotify.state_info.round_time = RuntimeData.roundTime
  fakeNotify.state_info.player_team = StartParam.battleInitInfo.player_team
  fakeNotify.state_info.enemy_team = StartParam.battleInitInfo.enemy_team
  fakeNotify.state_info.world_leader_fight_info = StartParam.battleInitInfo.world_leader_fight_info
  fakeNotify.state_info.evolution_data = StartParam.battleInitInfo.evolution_data
  fakeNotify.state_info.b1_final_battle_data = StartParam.battleInitInfo.b1_final_battle
  fakeNotify.isFromBattleEnter = true
  return fakeNotify
end

BattleUtils.EnergyTrackType = {DirectFly = 1, BounceAndFly = 2}

function BattleUtils.SimulateEnterNotify(roundNotify, selfPlayID)
  if not roundNotify then
    return nil
  end
  if not roundNotify.perform_cmd or 0 == #roundNotify.perform_cmd.perform_info then
    return nil
  end
  local StartParam = _G.BattleManager.battleRuntimeData.battleStartParam
  local RuntimeData = _G.BattleManager.battleRuntimeData
  local fakeNotify = ProtoMessage:newZoneBattleEnterNotify()
  local state_info = roundNotify.state_info
  local newBattleCfgId = 0
  if BattleUtils.IsB1FinalBattleP1() then
    newBattleCfgId = roundNotify.state_info.b1_final_battle_data.P2_battle_cfg_id
    state_info.b1_final_battle_data = roundNotify.state_info.b1_final_battle_data
    state_info.b1_final_battle_data.b1_phantom_point = 1000
  elseif BattleUtils.IsB1FinalBattleP2() then
    newBattleCfgId = roundNotify.state_info.b1_final_battle_data.P3_battle_cfg_id
    state_info.b1_final_battle_data = roundNotify.state_info.b1_final_battle_data
  elseif BattleUtils.IsFinalBattleP1() then
    newBattleCfgId = roundNotify.state_info.final_battle_data.P2_battle_cfg_id
    state_info.final_battle_data = roundNotify.state_info.final_battle_data
  end
  local battleCfg = _G.DataConfigManager:GetBattleConf(newBattleCfgId)
  fakeNotify.battle_mode = battleCfg.type
  fakeNotify.round = state_info.round
  fakeNotify.series_index = state_info.series_index
  fakeNotify.encountered = StartParam.encountered
  fakeNotify.init_info = StartParam.battleInitInfo
  fakeNotify.init_info.battle_id = state_info.battle_id
  fakeNotify.init_info.battle_cfg_id = {newBattleCfgId}
  fakeNotify.init_info.player_team = {}
  fakeNotify.init_info.enemy_team = {}
  for i, v in ipairs(roundNotify.perform_cmd.perform_info) do
    if v.data_update and v.data_update.battler then
      if v.data_update.uin == selfPlayID or 0 == v.data_update.battler.base.side then
        table.insert(fakeNotify.init_info.player_team, v.data_update.battler)
      else
        table.insert(fakeNotify.init_info.enemy_team, v.data_update.battler)
      end
    end
  end
  fakeNotify.init_info.final_battle_data = state_info.final_battle_data
  fakeNotify.init_info.b1_final_battle = state_info.b1_final_battle_data
  fakeNotify.avatar_pt = RuntimeData.ServerAvatarPt
  fakeNotify.npc_pt = RuntimeData.ServerNpcPt
  fakeNotify.npc_id = RuntimeData.NpcIDs
  fakeNotify.is_reconnect = false
  fakeNotify.enter_battle_type = RuntimeData.enterBattleType
  fakeNotify.battle_center = RuntimeData.ServerBattlePos
  fakeNotify.curWeatherID = RuntimeData.battleWaterType
  fakeNotify.water_battle_type = RuntimeData.battleWaterType
  fakeNotify.max_round = RuntimeData.max_round
  fakeNotify.rotate = RuntimeData.ServerBattleRotate
  return fakeNotify
end

function BattleUtils.ProcessEnergyTrack(startPos, energyView, energyTrackType, num, caller, completeCallback, startMoveId)
  if 0 == num then
    return
  end
  local BattleMain = BattleUtils.GetMainWindow()
  if num < 0 then
    local effectNum = -num
    BattleMain.processEnergyTrackCount = BattleMain.processEnergyTrackCount + 1
    BattleMain.needProcessEnergyTrack = true
    BattleResourceManager:LoadWidgetAsync(nil, BattleConst.UI.UMG_Battle_EnergyTrack, nil, function(_caller, retUmg)
      retUmg.isAdd = false
      BattleMain.DamageNumber:AddChildtoCanvas(retUmg)
      retUmg:DecreaseFly(energyView, effectNum, caller, completeCallback)
    end, nil, BattleMain)
  elseif num > 0 then
    BattleMain.processEnergyTrackCount = BattleMain.processEnergyTrackCount + num
    BattleMain.needProcessEnergyTrack = true
    energyView.FlyingEnergy = energyView.FlyingEnergy + num
    startMoveId = startMoveId or 0
    for i = 1, num do
      BattleResourceManager:LoadWidgetAsync(nil, BattleConst.UI.UMG_Battle_EnergyTrack, nil, function(_caller, retUmg)
        _G.NRCAudioManager:PlaySound2DAuto(1098, "BattleUtils.ProcessEnergyTrack")
        retUmg:SetMovingModeFromList(i + startMoveId)
        retUmg.isAdd = true
        BattleMain.DamageNumber:AddChildtoCanvas(retUmg)
        if energyTrackType == BattleUtils.EnergyTrackType.DirectFly then
          retUmg:DirectFly(startPos, energyView, caller, completeCallback)
        elseif energyTrackType == BattleUtils.EnergyTrackType.BounceAndFly then
          retUmg:BounceAndFly(startPos, energyView, caller, completeCallback)
        else
          Log.Error("Wrong energy track type defined")
        end
      end, nil, BattleMain)
    end
  end
end

function BattleUtils.OnProcessEnergyTrackComplete()
  local BattleMain = BattleUtils.GetMainWindow()
  if BattleMain.processEnergyTrackCount <= 0 then
    Log.Error("BattleUtils: complete with below zero track count")
    BattleMain.processEnergyTrackCount = 1
  end
  BattleMain.processEnergyTrackCount = BattleMain.processEnergyTrackCount - 1
  if 0 == BattleMain.processEnergyTrackCount then
    BattleMain.needProcessEnergyTrack = false
    _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_PROCESS_ENERGY_TRACK_END)
  end
end

function BattleUtils.GetPetWithID(id)
  local pet = _G.BattleManager.battlePawnManager:GetPetByGuid(id)
  return pet
end

function BattleUtils.ModifyPetDeathPendingCnt(isAdd)
  local runtimeData = _G.BattleManager.battleRuntimeData
  local changeNum = -1
  if isAdd then
    changeNum = 1
  end
  runtimeData.petDeathAnimationPendingCnt = runtimeData.petDeathAnimationPendingCnt + changeNum
  Log.Debug(runtimeData.petDeathAnimationPendingCnt)
  if runtimeData.petDeathAnimationPendingCnt < 0 then
    runtimeData.petDeathAnimationPendingCnt = 0
    Log.Error("pet death animation pending count below 0")
  elseif 0 == runtimeData.petDeathAnimationPendingCnt then
    _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_PET_DEATH_PENDING_ANIMATION_FINISH)
  end
end

function BattleUtils.CheckPetDeathPendingCntClear()
  local runtimeData = _G.BattleManager.battleRuntimeData
  if 0 == runtimeData.petDeathAnimationPendingCnt then
    return true
  else
    return false
  end
end

function BattleUtils.SetBattlePetCollisionState(teamFlag, isNoCollision)
  for _, v in ipairs(_G.BattleManager.battlePawnManager:GetInFieldAllPet(teamFlag)) do
    if v and UE.UObject.IsValid(v.model) then
      if isNoCollision then
        v:HidePet()
        v.model:SetActorEnableCollision(false)
        local root = v.model:K2_GetRootComponent()
        if root then
          root:SetCollisionProfileName("NoCollision")
        end
      else
        v.model:SetActorEnableCollision(true)
        local root = v.model:K2_GetRootComponent()
        if root then
          root:SetCollisionProfileName("NPCCharacter")
        end
      end
    end
  end
end

function BattleUtils.SetBattlePlayerCollisionState(teamFlag, isNoCollision)
  for _, v in ipairs(_G.BattleManager.battlePawnManager:GetAllTeam(teamFlag)) do
    local player = v.player
    if player and player.model then
      local rootComponent = player.model:K2_GetRootComponent()
      if rootComponent then
        if isNoCollision then
          player:HidePlayer()
          player.model:SetActorEnableCollision(false)
          rootComponent:SetCollisionProfileName("NoCollision")
        else
          player.model:SetActorEnableCollision(true)
          rootComponent:SetCollisionProfileName("NPCCharacter")
        end
      end
    end
  end
end

function BattleUtils.SetPetScale(BattlePet)
  local BaseConfId = BattlePet.card.petInfo.battle_common_pet_info.base_conf_id
  local PetBaseConf = _G.DataConfigManager:GetPetbaseConf(BaseConfId)
  if PetBaseConf then
    local _petBaseCfg = PetBaseConf
    local modelScale = _petBaseCfg.petpage_ui_percentage and _petBaseCfg.petpage_ui_percentage > 0 and _petBaseCfg.petpage_ui_percentage or 1
    local OffsetVector = UE4.FVector(0, 0, 0)
    local OriHeight = BattlePet.model:GetHalfHeight()
    if BattlePet.card.petInfo.battle_common_pet_info then
      local heightModelScale = PetMutationUtils.GetHeightModelScaleByPetData(BattlePet.card.petInfo.battle_common_pet_info)
      modelScale = modelScale * heightModelScale
      OffsetVector.Z = OffsetVector.Z - OriHeight
      Log.Debug(OffsetVector, modelScale, OriHeight, "BattleUtils.SetPetScale scaleOffset")
    end
    local DefaultScale = BattlePet.model:GetClass():GetDefaultObject().Mesh.RelativeScale3D.X
    Log.Debug(DefaultScale, "BattleUtils.SetPetScale DefaultScale")
    UE.UNRCCharacterUtils.SetCharacterMeshScale(BattlePet.model, modelScale * DefaultScale)
    local Root = BattlePet.model:K2_GetRootComponent()
    local height = Root:GetScaledCapsuleHalfHeight()
    local location = BattlePet.model:K2_GetActorLocation()
    location.Z = location.Z + height
    BattlePet.model:K2_SetActorLocation(location, false, nil, false)
    local PetLocation = BattlePet.model:Abs_K2_GetActorLocation()
    PetLocation = PetLocation + OffsetVector
    Log.Debug(OffsetVector, "BattleUtils.SetPetScale OffsetVector")
    BattlePet.model:Abs_K2_SetActorLocation_WithoutHit(PetLocation)
  end
end

function BattleUtils.SetModelOffset(BattlePet, _offset, modelScale)
  if BattlePet then
    local height = (BattlePet.model:GetHalfHeight() + _offset.Z) * (modelScale or 1)
    local CurPetLocation = BattlePet.model:Abs_K2_GetActorLocation()
    local NewPetLocation = UE4.FVector(CurPetLocation.X + _offset.X, CurPetLocation.Y + _offset.Y, height)
    Log.Debug(NewPetLocation, "BattleUtils.SetModelOffset")
    BattlePet.model:Abs_K2_SetActorLocation_WithoutHit(NewPetLocation)
  end
end

function BattleUtils.SetTeamCollisionState(teamFlag, isNoCollision)
  BattleUtils.SetBattlePetCollisionState(teamFlag, isNoCollision)
end

function BattleUtils.IsSinglePlayerMode()
  if _G.BattleManager.battleRuntimeData.subBattleType == BattleEnum.SubBattleType.Single then
    return true
  end
  return false
end

function BattleUtils.GetBattleConfig()
  local cfg = _G.BattleManager.battleRuntimeData.battleStartParam.battleCfg
  return cfg
end

function BattleUtils.GetBattleRuleIds()
  local answer = {}
  local BattleConf = BattleUtils.GetBattleConfig()
  local battleRules = BattleConf and BattleConf.battle_rule or nil
  if battleRules then
    for _, id in pairs(battleRules) do
      if 0 ~= id then
        table.insert(answer, id)
      end
    end
  end
  local npc_challenge_info = _G.BattleManager:GetBattleNpcChallengeInfo()
  if npc_challenge_info and npc_challenge_info.rule_ids then
    for _, id in pairs(npc_challenge_info.rule_ids) do
      if 0 ~= id then
        table.insert(answer, id)
      end
    end
  end
  local BadgeChallengeRules = BattleUtils.GetBadgeChallengeRuleIds()
  for _, id in pairs(BadgeChallengeRules) do
    if 0 ~= id then
      table.insert(answer, id)
    end
  end
  if BattleUtils.IsBadgeChallenge() then
    local rule_ids = {}
    for _, ruleId in pairs(answer) do
      local ruleConf = _G.DataConfigManager:GetBattleRuleConf(ruleId)
      if ruleConf and not string.IsNilOrEmpty(ruleConf.desc) then
        table.insert(rule_ids, ruleId)
      end
    end
    answer = rule_ids
  end
  return answer
end

function BattleUtils.GetBadgeChallengeRuleIds()
  local answer = {}
  if BattleUtils.IsBadgeChallenge() and _G.BattleManager:IsInBattle(true) then
    local battleInitInfo = BattleUtils.GetBadgeChallengeBattleInfo()
    if battleInitInfo then
      local global_rule = battleInitInfo.global_rule
      if global_rule then
        for _, effectId in pairs(global_rule) do
          if 0 ~= effectId then
            local EffectConf = _G.DataConfigManager:GetGrassTrialEffectConf(effectId)
            if EffectConf and EffectConf.battle_effect then
              for _, ruleId in pairs(EffectConf.battle_effect) do
                if 0 ~= ruleId then
                  table.insert(answer, ruleId)
                end
              end
            end
          end
        end
      end
    end
  end
  return answer
end

function BattleUtils.GetBattleInitInfo()
  local info = _G.BattleManager.battleRuntimeData.battleStartParam.battleInitInfo
  return info
end

function BattleUtils.IsBattleServeWaitingLoad()
  local info = _G.BattleManager.battleRuntimeData.battleStartParam.battleInitInfo
  if info and (info.battle_state == ProtoEnum.BATTLEFIELD_STATE.BATTLEFIELD_STATE_WAIT_LOAD or info.battle_state == ProtoEnum.BATTLEFIELD_STATE.BATTLEFIELD_STATE_ROUND_NPC_AI) then
    return true
  end
  return false
end

function BattleUtils.GetEnemyPetBlood()
  local initInfo = BattleUtils.GetBattleInitInfo()
  if initInfo and initInfo.enemy_team then
    for _, enemy in ipairs(initInfo.enemy_team) do
      for _, pet in ipairs(enemy.pets) do
        if BattleUtils.GetInBattle(pet.battle_inside_pet_info) then
          return pet.battle_common_pet_info.blood_id
        end
      end
    end
  end
end

function BattleUtils.IsCatchBattleMode()
  if _G.GlobalConfig.DebugOpenUI then
    return false
  end
  local battleConfig = BattleUtils.GetBattleConfig()
  if battleConfig and battleConfig.can_catch_or_not then
    return 1 == BattleUtils.GetBattleConfig().can_catch_or_not
  end
  return false
end

function BattleUtils.IsUseItemBattleMode()
  local battleStartParam = _G.BattleManager.battleRuntimeData.battleStartParam
  if battleStartParam then
    local isForbidItem = battleStartParam:CheckInitState(ProtoEnum.BATTLEFIELD_BIT_TYPE.BT_FORBID_ITEM)
    local isForbidMagic = battleStartParam:CheckInitState(ProtoEnum.BATTLEFIELD_BIT_TYPE.BT_FORBID_ITEM_ROLE_MAGIC)
    if isForbidItem and isForbidMagic then
      return false
    end
  end
  return true
end

function BattleUtils.IsUseFourUIInStoryTeam()
  local battleStartParam = _G.BattleManager.battleRuntimeData.battleStartParam
  if battleStartParam:IsReconnect() then
    return false
  end
  if battleStartParam and battleStartParam.battleInitInfo and battleStartParam.battleInitInfo.story_team_battle_info then
    return battleStartParam.battleInitInfo.story_team_battle_info.enable_enter_anim
  end
  return true
end

function BattleUtils.GetEnemyIsCCModePet(enemy)
  local card = enemy.card
  local maxShield = card and card:GetMaxShield()
  if maxShield then
    return maxShield > 0
  end
  return false
end

function BattleUtils.GetAnyEnemyIsCCModePet()
  local anyEnemyIsNightMare = false
  local enemies = _G.BattleManager.battlePawnManager:GetInFieldAllPet(BattleEnum.Team.ENUM_ENEMY)
  for _, enemy in ipairs(enemies) do
    if BattleUtils.GetEnemyIsCCModePet(enemy) then
      anyEnemyIsNightMare = true
      break
    end
  end
  return anyEnemyIsNightMare
end

function BattleUtils.GetEnemyHasCCModeShield(enemy)
  local card = enemy and enemy.card
  local maxShield = card and card:GetMaxShield()
  local shield = card and card:GetShield()
  if maxShield then
    return shield and shield > 0 or false
  end
  return false
end

function BattleUtils.GetAllEnemyHasCCModeShield()
  local enemies = _G.BattleManager.battlePawnManager:GetInFieldAllPet(BattleEnum.Team.ENUM_ENEMY)
  local enemyHasNightMareShieldCount = 0
  for _, enemy in ipairs(enemies) do
    if BattleUtils.GetEnemyHasCCModeShield(enemy) then
      enemyHasNightMareShieldCount = enemyHasNightMareShieldCount + 1
    end
  end
  local allEnemyCount = #enemies
  local allEnemyHasNightMareShield = allEnemyCount == enemyHasNightMareShieldCount
  return allEnemyHasNightMareShield
end

function BattleUtils.RefreshCliSimplePetMutationTypeDataByConfig(simpleBattlePet)
  local card = simpleBattlePet and _G.BattleManager.battlePawnManager:GetCardByGuid(simpleBattlePet.pet_id)
  local isNightmareValue = card and card:GetMonsterConfigIsNightmareValue()
  local extraMutationDiffType = isNightmareValue and BattleConst.MonsterIsNightmareValueToMutationDiffType[isNightmareValue]
  if extraMutationDiffType then
    local newMutationTypeValue = simpleBattlePet.mutation
    newMutationTypeValue = newMutationTypeValue | extraMutationDiffType
    simpleBattlePet.mutation = newMutationTypeValue
  end
end

function BattleUtils.IsEscapeBattleMode()
  if _G.GlobalConfig.DebugOpenUI then
    return false
  end
  local useItemMode = 1 == BattleUtils.GetBattleConfig().can_escape
  return useItemMode
end

function BattleUtils.GetCanChangePetConfig()
  if _G.GlobalConfig.DebugOpenUI then
    return 0
  end
  local changePetMode = BattleUtils.GetBattleConfig().can_changepet or 0
  return changePetMode
end

function BattleUtils.GetChangePetTipKey(key)
  return "cant_change_pet" .. string.format("%02d", key)
end

function BattleUtils.IsCanChangePetBattleMode()
  return BattleUtils.GetCanChangePetConfig() > 0
end

function BattleUtils.IsBattleWin(resultRaw)
  if not resultRaw then
    return nil
  end
  return resultRaw & ProtoEnum.BATTLE_RESULT_TYPE.TRUE_BATTLE_RESULT_WIN > 0
end

function BattleUtils.GetCatchRate(infos, pet)
  if not pet then
    return 0
  end
  if not infos then
    return 0
  end
  local BaseID = pet.card.config.base_id
  for _, info in ipairs(infos) do
    if info.pet_base_id == BaseID then
      return info.catch_probability / 100
    end
  end
  return 0
end

function BattleUtils.GetShakeTimes(SuccessRate, bIsSuccess)
  local MaxShakeTimes = 5
  local DistributionConf = _G.DataConfigManager:GetBattleGlobalConfig("ball_shake_times_param")
  local Distribution = (DistributionConf and DistributionConf.num or 10000) / 10000
  local HaltChance = 1 - (SuccessRate / 100.0) ^ (1.0 / Distribution)
  if GlobalConfig.ShowShakeHaltRate then
    Log.Error("\229\136\134\229\184\131\229\143\130\230\149\176:", Distribution)
  end
  if bIsSuccess then
    if GlobalConfig.ShowShakeHaltRate then
      Log.Error("\231\178\190\231\129\181\230\138\150\229\138\168\229\129\156\230\173\162\230\166\130\231\142\135\228\184\186:", HaltChance)
    end
    return MaxShakeTimes
  else
    local ShakeTimes = 0
    for i = 1, MaxShakeTimes do
      local rand = math.random()
      if HaltChance < rand then
        ShakeTimes = ShakeTimes + 1
      end
      if GlobalConfig.ShowShakeHaltRate then
        Log.Error(i, "\230\138\150\229\138\168", rand, HaltChance)
      end
    end
    return ShakeTimes
  end
end

function BattleUtils.IsCatchRateInvalidLow(catch_prob)
  if nil == catch_prob then
    return false
  end
  local catchLow = _G.DataConfigManager:GetBattleGlobalConfig("catch_pr_low").numList
  if nil == catchLow[1] or nil == catchLow[2] then
    return false
  end
  return catch_prob < catchLow[2] / 10000 and catch_prob >= catchLow[1] / 10000
end

function BattleUtils.GetCatchRateGrade(catch_prob)
  catch_prob = catch_prob or 0
  local catchGrade = 1
  local catchLow = _G.DataConfigManager:GetBattleGlobalConfig("catch_pr_low").numList
  local catchMiddle = _G.DataConfigManager:GetBattleGlobalConfig("catch_pr_middle").numList
  local catchHigh = _G.DataConfigManager:GetBattleGlobalConfig("catch_pr_high").numList
  if catch_prob <= catchLow[2] / 10000.0 and catch_prob >= catchLow[1] / 10000.0 then
    catchGrade = 1
  elseif catch_prob <= catchMiddle[2] / 10000.0 and catch_prob >= catchMiddle[1] / 10000.0 then
    catchGrade = 2
  elseif catch_prob <= catchHigh[2] / 10000.0 and catch_prob >= catchHigh[1] / 10000.0 then
    catchGrade = 3
  end
  return catchGrade
end

function BattleUtils.GetCatchRateAnim(catch_prob)
  local grade = BattleUtils.GetCatchRateGrade(catch_prob)
  local str = ""
  if 1 == grade then
    str = _G.DataConfigManager:GetBattleGlobalConfig("low_catch_prob_show").str
  elseif 2 == grade then
    str = _G.DataConfigManager:GetBattleGlobalConfig("middle_catch_prob_show").str
  elseif 3 == grade then
    str = _G.DataConfigManager:GetBattleGlobalConfig("high_catch_prob_show").str
  end
  return str
end

function BattleUtils.GetCatchRateInvalidLowEnemyPets(ball_conf_id)
  local enemies = _G.BattleManager.battlePawnManager:GetInFieldAllPet(BattleEnum.Team.ENUM_ENEMY)
  local petLst
  for _, enemy in ipairs(enemies) do
    local catchRate = BattleUtils.CalculateCatchMonsterRateBattle(ball_conf_id, enemy.guid)
    if BattleUtils.IsCatchRateInvalidLow(catchRate) then
      petLst = petLst or {}
      table.insert(petLst, enemy.card.petInfo.battle_inside_pet_info.base_conf_id)
    end
  end
  return petLst
end

function BattleUtils.GetCatchRateInvalidEnemyPets(ball_conf_id)
  local enemies = _G.BattleManager.battlePawnManager:GetInFieldAllPet(BattleEnum.Team.ENUM_ENEMY)
  local petLst
  local catchRateGrade = 1
  for _, enemy in ipairs(enemies) do
    local catchRate = BattleUtils.CalculateCatchMonsterRateBattle(ball_conf_id, enemy.guid)
    catchRateGrade = BattleUtils.GetCatchRateGrade(catchRate)
    if catchRateGrade < 3 then
      petLst = petLst or {}
      table.insert(petLst, enemy.card.petInfo.battle_inside_pet_info.base_conf_id)
    end
  end
  return petLst, catchRateGrade
end

function BattleUtils.CheckIsBlockNotifyWhenLoading(protoCmdId)
  if protoCmdId == ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_FINISH_NOTIFY or protoCmdId == ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_CMD_SYNC_NOTIFY or protoCmdId == ProtoCMD.ZoneSvrCmd.ZONE_BATTLE_ENTER_NOTIFY then
    return false
  else
    return true
  end
end

function BattleUtils.CheckIsPlayerPetsAllDead()
  local pets = _G.BattleManager.battlePawnManager:GetInFieldAllPet(BattleEnum.Team.ENUM_TEAM)
  if 0 == #pets or nil == pets then
    return true
  end
  for i, pet in ipairs(pets) do
    if pet.card.hp > 0 then
      return false
    end
  end
  return true
end

function BattleUtils.ReplaceSubString(input, pattern, replacement)
  local _, count = string.gsub(input, pattern, pattern)
  local realCount = 0
  if count < #replacement then
    realCount = count
  else
    realCount = #replacement
  end
  local output = input
  for i = 1, realCount do
    output = string.gsub(output, pattern, replacement[i], 1)
  end
  return output
end

function BattleUtils.FindWeatherDesc(weather_type, available_time_enum)
  if 0 == weather_type and 0 == available_time_enum then
    return nil
  end
  local weatherConf = _G.DataConfigManager:GetWeatherConf(weather_type)
  if weatherConf then
    local tod_param = weatherConf.tod_param
    for i, tod in ipairs(tod_param) do
      if tod.available_time_enum == available_time_enum then
        return tod.des
      end
    end
  end
  return nil
end

function BattleUtils.FindWeatherName(weather_type)
  if 0 == weather_type then
    return nil
  end
  local weatherConf = _G.DataConfigManager:GetWeatherConf(weather_type)
  if weatherConf then
    return weatherConf.name
  end
  return nil
end

function BattleUtils.FindAreaDesc(id)
  if 0 == id then
    return nil
  end
  local areaTagConf = _G.DataConfigManager:GetAreaTagConf(id)
  if areaTagConf then
    return areaTagConf.editor_name
  end
  return nil
end

function BattleUtils.CheckIsNeedTeleport()
  local notifyLst = _G.NRCModuleManager:DoCmd(PlayerModuleCmd.GetCachedTeleportNotify)
  if notifyLst then
    return true
  end
  return false
end

function BattleUtils.IsWaitingForEnergy()
  local BattleMain = BattleUtils.GetMainWindow()
  if not BattleMain then
    return false
  end
  if BattleMain and BattleMain.needProcessEnergyTrack then
    return true
  end
  return false
end

function BattleUtils.IsWaitingForDeath()
  local runtimeData = _G.BattleManager.battleRuntimeData
  if 0 == runtimeData.petDeathAnimationPendingCnt then
    return false
  else
    return true
  end
end

function BattleUtils.IsWaitingForEvolution()
  if _G.BattleManager.battleRuntimeData.isEvolutionWaiting then
    return true
  end
  return false
end

function BattleUtils.IsWaitingForRewardRoundEffect()
  return false
end

function BattleUtils.EnableSkillPrediction()
  local pawnMgr = _G.BattleManager.battlePawnManager
  if BattleUtils.IsBadgeChallenge() or not BattleUtils.HasEnemyPlayer() then
    local enemies = pawnMgr:GetInFieldAllPet(BattleEnum.Team.ENUM_ENEMY)
    if enemies then
      for _, enemy in ipairs(enemies) do
        enemy:ShowSkillPrediction()
      end
    end
  elseif BattleUtils.IsPve() then
    local allTeams = pawnMgr:GetAllTeam(BattleEnum.Team.ENUM_ENEMY)
    if allTeams then
      for i, v in pairs(allTeams) do
        local enemyPlayer = v.player
        if enemyPlayer then
          enemyPlayer:TryShowSkillPrediction()
        end
      end
    end
  end
end

function BattleUtils.DisableSkillPrediction()
  local pawnMgr = _G.BattleManager.battlePawnManager
  if BattleUtils.IsBadgeChallenge() or not BattleUtils.HasEnemyPlayer() then
    local enemies = pawnMgr:GetInFieldAllPet(BattleEnum.Team.ENUM_ENEMY)
    for _, enemy in ipairs(enemies) do
      enemy:HideSkillPrediction()
    end
  elseif BattleUtils.IsPve() then
    local allTeams = pawnMgr:GetAllTeam(BattleEnum.Team.ENUM_ENEMY)
    for i, v in pairs(allTeams) do
      local enemyPlayer = v.player
      if enemyPlayer then
        enemyPlayer:HideSkillPrediction()
      end
    end
  end
end

function BattleUtils.GetPlayerUin()
  return _G.DataModelMgr.PlayerDataModel:GetPlayerUin()
end

function BattleUtils.GetSkillPredictionByPlayer(pet)
  local infos = pet.card.petInfo.battle_inside_pet_info.ai_skill_info
  local uin = BattleUtils.GetPlayerUin()
  if BattleUtils.IsReplayMode() then
    local player = _G.BattleManager.battlePawnManager.TeamatePlayer
    uin = player.roleInfo.base.role_uin
  end
  if BattleUtils.IsTerritoryTrialBattle() or BattleUtils.IsBadgeChallenge() then
    infos = {}
    local battleCard = pet and pet.card
    local petInfo = battleCard and battleCard.petInfo
    local insideInfo = petInfo and petInfo.battle_inside_pet_info
    local req = petInfo and petInfo.req
    local type = req and req.req_type
    if type == _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_CAST_SKILL then
      local castSkill = req and req.cast_skill
      local skillId = castSkill and castSkill.skill_id
      local aiInfo = ProtoMessage:newBattleAISelectSkillInfo()
      aiInfo.uin = uin
      aiInfo.skill_id = skillId
      aiInfo.no_show = false
      aiInfo.show_skill_id = skillId
      aiInfo.hint_level = ProtoEnum.SkillHintLevel.LEVEL_INVALID
      aiInfo.npc_hint_mode = ProtoEnum.ShowType.ST_DIRECT
      table.insert(infos, aiInfo)
    end
  end
  if infos then
    for _, v in ipairs(infos) do
      if v.uin == uin then
        return v
      end
    end
  end
  return nil
end

function BattleUtils.GetMSB(num)
  if 0 == num then
    return 0
  end
  for i = 32, 1, -1 do
    if num & 1 << i > 0 then
      return i
    end
  end
  return 0
end

function BattleUtils.GetSkillTypePath(type, damage_type)
  if type == Enum.SkillType.ST_DAMAGE then
    if damage_type == Enum.DamageType.DT_SPC then
      return LuaText.umg_pet_skill_tips_1, "PaperSprite'/Game/NewRoco/Modules/System/BattleUI/Raw/Atlas/PetSystem/Frames/ui_pet_attribute_04_png.ui_pet_attribute_04_png'"
    else
      return LuaText.umg_pet_skill_tips_1, "PaperSprite'/Game/NewRoco/Modules/System/BattleUI/Raw/Atlas/PetSystem/Frames/ui_pet_attribute_02_png.ui_pet_attribute_02_png'"
    end
  elseif type == Enum.SkillType.ST_DEFEND then
    return LuaText.umg_pet_skill_tips_2, "PaperSprite'/Game/NewRoco/Modules/System/BattleUI/Raw/Atlas/PetSystem/Frames/AT_DEFENSE_png.AT_DEFENSE_png'"
  else
    return LuaText.umg_pet_skill_tips_3, "PaperSprite'/Game/NewRoco/Modules/System/BattleUI/Raw/Atlas/PetSystem/Frames/AT_CLASSIFICATION_png.AT_CLASSIFICATION_png'"
  end
end

function BattleUtils:IsMonster(petID)
  return false
end

function BattleUtils:GetPetBaseIDByPetID(petID)
  local petConf = _G.DataConfigManager:GetPetConf(petID)
  return petConf.base_id
end

function BattleUtils:GetSkillRestraint(skillData)
  if skillData and skillData.restraint_types then
    local result = 0
    local totalPetNum = 0
    local checkPetNum = 0
    local doubleRestraintAnyPet = false
    local restraintAnyPet = false
    local weakToPetCount = 0
    local doubleWeakToPetCount = 0
    local restraintTypeNonePetCount = 0
    for _, v in ipairs(skillData.restraint_types) do
      local card = _G.BattleManager.battlePawnManager:GetCardByGuid(v.pet_id)
      if nil == card then
      else
        if BattleUtils.IsPartialShow(card) then
          restraintTypeNonePetCount = restraintTypeNonePetCount + 1
        else
          checkPetNum = checkPetNum + 1
          if v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINT_ONE then
            restraintAnyPet = true
          elseif v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINT_TWO or v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINT_THREE then
            restraintAnyPet = true
            doubleRestraintAnyPet = true
          elseif v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINTED_ONE then
            weakToPetCount = weakToPetCount + 1
          elseif v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINTED_TWO or v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINTED_THREE then
            weakToPetCount = weakToPetCount + 1
            doubleWeakToPetCount = doubleWeakToPetCount + 1
          else
            restraintTypeNonePetCount = restraintTypeNonePetCount + 1
          end
        end
        totalPetNum = totalPetNum + 1
      end
    end
    local isWeakToAllPet = weakToPetCount == totalPetNum
    local isDoubleWeakToAllPet = doubleWeakToPetCount == totalPetNum
    local restraintTypeNoneToAnyPet = restraintTypeNonePetCount > 0
    if checkPetNum <= 0 then
      return BattleEnum.TypeRestraint.ENUM_NONE
    end
    if doubleRestraintAnyPet then
      return BattleEnum.TypeRestraint.ENUM_RESTRAINT_DOUBLE
    elseif restraintAnyPet then
      return BattleEnum.TypeRestraint.ENUM_RESTRAINT
    elseif restraintTypeNoneToAnyPet then
      return BattleEnum.TypeRestraint.ENUM_NORMAL
    elseif isWeakToAllPet and not isDoubleWeakToAllPet then
      return BattleEnum.TypeRestraint.ENUM_WEAK
    elseif isDoubleWeakToAllPet then
      return BattleEnum.TypeRestraint.ENUM_WEAK_DOUBLE
    end
    return BattleEnum.TypeRestraint.ENUM_NONE
  end
  return BattleEnum.TypeRestraint.ENUM_NONE
end

function BattleUtils:GetSkillRestraintByPetId(skillData, petId)
  if skillData and skillData.restraint_types then
    for _, v in ipairs(skillData.restraint_types) do
      if v.pet_id == petId then
        local card = _G.BattleManager.battlePawnManager:GetCardByGuid(v.pet_id)
        if nil == card then
        elseif not BattleUtils.IsPartialShow(card) then
          if v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINT_ONE then
            return BattleEnum.TypeRestraint.ENUM_RESTRAINT
          elseif v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINT_TWO or v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINT_THREE then
            return BattleEnum.TypeRestraint.ENUM_RESTRAINT_DOUBLE
          elseif v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINTED_ONE then
            return BattleEnum.TypeRestraint.ENUM_WEAK
          elseif v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINTED_TWO or v.restraint_type == ProtoEnum.SkillRestraintType.SRT_RESTRAINTED_THREE then
            return BattleEnum.TypeRestraint.ENUM_WEAK_DOUBLE
          else
            return BattleEnum.TypeRestraint.ENUM_NORMAL
          end
        else
          return BattleEnum.TypeRestraint.ENUM_NORMAL
        end
      end
    end
  end
  return BattleEnum.TypeRestraint.ENUM_NORMAL
end

function BattleUtils.GetSkillCatchGradeValueByPetId(skillData, petId)
  local restraintType = BattleUtils:GetSkillRestraintByPetId(skillData, petId)
  return BattleUtils.TypeRestraintToCatchGrade(restraintType)
end

function BattleUtils.TypeRestraintToCatchGrade(typeRestraint)
  if typeRestraint == BattleEnum.TypeRestraint.ENUM_WEAK or typeRestraint == BattleEnum.TypeRestraint.ENUM_WEAK_DOUBLE then
    return 1
  elseif typeRestraint == BattleEnum.TypeRestraint.ENUM_NORMAL then
    return 2
  elseif typeRestraint == BattleEnum.TypeRestraint.ENUM_RESTRAINT or typeRestraint == BattleEnum.TypeRestraint.ENUM_RESTRAINT_DOUBLE then
    return 3
  end
  return 2
end

function BattleUtils:IsFirstMeetAllEnemyPet(player)
  if not PetUtils.CheckPlayerFirstMeetPetFunctionEnable() then
    return false
  end
  local isFirstMeet = true
  if player and player.roleInfo and player.roleInfo.base then
    local noMetPets = player.roleInfo.base.first_seen_pets or {}
    local allPet = {}
    if player.teamEnm == BattleEnum.Team.ENUM_TEAM then
      allPet = _G.BattleManager.battlePawnManager:GetEnemyAllPets()
    else
      allPet = _G.BattleManager.battlePawnManager:GetTeamAllPets()
    end
    for _, v in pairs(allPet) do
      if v.teamEnm ~= player.teamEnm and not table.contains(noMetPets, v.guid) then
        isFirstMeet = false
      end
    end
  end
  if BattleUtils.IsPvp() then
    isFirstMeet = false
  end
  return isFirstMeet
end

function BattleUtils:RestartBattleState(targets, buffConf)
  for _, target in ipairs(targets) do
    if buffConf then
      for i, v in ipairs(buffConf.buff_groupsigns) do
        target.buffComponent:RestartBattleState(v)
      end
    else
      target.buffComponent:RestartBattleState()
    end
  end
end

function BattleUtils.CheckPetStateByBGS(buffs, bgs)
  for _, buff in ipairs(buffs) do
    local buffConf = _G.DataConfigManager:GetBuffConf(buff.buff_id)
    if buffConf then
      for _, sign in ipairs(buffConf.buff_groupsigns) do
        if sign == bgs then
          return true
        end
      end
    end
  end
  return false
end

function BattleUtils.GetNavInvalidPos(point, startPoint)
  local navPoint, bResult = UE4.UNavigationSystemV1.Abs_K2_ProjectPointToNavigation(UE4Helper.GetCurrentWorld(), point)
  if not bResult or not navPoint then
    return point
  else
    return navPoint
  end
end

function BattleUtils.CheerPetsStartRandomMove()
  if not BattleUtils.IsCrowdBattle() then
    return
  end
  local Cheers = _G.BattleManager.battlePawnManager:GetEnemyAllCheerPets()
  if Cheers and #Cheers > 0 then
    local select = math.random(1, #Cheers)
    if Cheers[select] then
      Cheers[select]:StartRandomMove()
    end
  end
end

function BattleUtils.CheerPetsStopRandomMove()
  if not BattleUtils.IsCrowdBattle() then
    return
  end
  local Cheers = _G.BattleManager.battlePawnManager:GetEnemyAllCheerPets()
  for _, pet in ipairs(Cheers) do
    pet:StopRandomMove()
  end
end

function BattleUtils.CheerPetsPerform(performType)
  if not BattleUtils.IsCrowdBattle() then
    return
  end
  local cheers = _G.BattleManager.battlePawnManager:GetEnemyAllCheerPets()
  for _, v in ipairs(cheers) do
    local chara = v.card.petBaseConf.substitute_character
    local animName = BattleConst.CheerPetPerformConfig[chara][performType]
    if animName then
      v:PlayAnimByName(animName, 1, -1, 0, 0, 1, -1)
    end
  end
end

function BattleUtils.IsBattleAIStatus(status, returnString)
  local stateString
  status = tonumber(status)
  if nil == status then
    return false
  end
  if status & 1 << ProtoEnum.BattleAIStatus.BAS_SLEEP > 0 then
    if returnString then
      stateString = "Sleep"
    end
    return true, stateString
  elseif status & 1 << ProtoEnum.BattleAIStatus.BAS_DRILL > 0 then
    if returnString then
      stateString = "Drill"
    end
    return true, stateString
  elseif status & 1 << ProtoEnum.BattleAIStatus.BAS_STATIC > 0 then
    if returnString then
      stateString = "Static"
    end
    return true, stateString
  elseif status & 1 << ProtoEnum.BattleAIStatus.BAS_MIMIC > 0 then
    if returnString then
      stateString = "Mimic"
    end
    return true, stateString
  elseif status & 1 << ProtoEnum.BattleAIStatus.BAS_HIDE > 0 then
    if returnString then
      stateString = "Hide"
    end
    return true, stateString
  elseif status & 1 << ProtoEnum.BattleAIStatus.BAS_HANGING > 0 then
    if returnString then
      stateString = "Hanging"
    end
    return true, stateString
  elseif BattleUtils.IsStunStatus(status) then
    if returnString then
      stateString = "Stun"
    end
    return true, stateString
  end
  return false
end

function BattleUtils.IsNightmareKeep(status)
  status = tonumber(status)
  if nil == status then
    return false
  end
  if status & 1 << ProtoEnum.BattleAIStatus.BAS_NIGHTMARE_KEEP > 0 then
    return true
  end
  return false
end

function BattleUtils.IsStunStatus(status)
  if status & 1 << ProtoEnum.BattleAIStatus.BAS_MAGIC_STUN > 0 or status & 1 << ProtoEnum.BattleAIStatus.BAS_MAGIC_STUN_1 > 0 or status & 1 << ProtoEnum.BattleAIStatus.BAS_MAGIC_STUN_2 > 0 or status & 1 << ProtoEnum.BattleAIStatus.BAS_MAGIC_STUN_3 > 0 or status & 1 << ProtoEnum.BattleAIStatus.BAS_MAGIC_STUN_4 > 0 then
    return true
  end
  return false
end

function BattleUtils.EnableDotSubSystem()
  local dotSubSystem = UE.USubsystemBlueprintLibrary.GetGameInstanceSubsystem(UE4Helper.GetCurrentWorld(), UE.UDotsModuleSubsystem)
end

function BattleUtils.DisableDotSubSystem()
  local dotSubSystem = UE.USubsystemBlueprintLibrary.GetGameInstanceSubsystem(UE4Helper.GetCurrentWorld(), UE.UDotsModuleSubsystem)
end

function BattleUtils.LoadResAsyncMaterial(Material)
  local MaterialAsset = LoadObject(Material)
  return MaterialAsset
end

function BattleUtils.ShowAllPetPlatForm()
  if BattleUtils.IsDeepWater() then
    local playerTeams = _G.BattleManager.battlePawnManager:GetAllTeam(BattleEnum.Team.ENUM_TEAM)
    local enemyTeams = _G.BattleManager.battlePawnManager:GetAllTeam(BattleEnum.Team.ENUM_ENEMY)
    for _, v in ipairs(playerTeams) do
      if #v.pets > 0 then
        for _, p in pairs(v.pets) do
          if p.model and p.card:IsExistAtField() then
            p:SetWaterPlatformVisible(true)
          end
        end
      end
    end
    for _, v in ipairs(enemyTeams) do
      if #v.pets > 0 then
        for _, p in pairs(v.pets) do
          if p.model and p.card:IsExistAtField() then
            p:SetWaterPlatformVisible(true)
          end
        end
      end
    end
  end
end

function BattleUtils.SetSkillNoWaitTilLoading(skill)
  local actions = skill:GetAllActions()
  for i = 1, actions:Length() do
    local action = actions:Get(i)
    if action.m_Enable and action:IsA(UE.URocoConditionControllerAction) then
      action.bWaitTilLoadingDone = false
    end
  end
end

function BattleUtils.IsWildEnemy()
  return BattleManager.battleRuntimeData.battleStartParam.isSeriesFight
end

function BattleUtils.GetWildSupplySkillRes(BattleConf)
  local MonsterConf = _G.DataConfigManager:GetMonsterConf(BattleConf.pos1[1])
  local PetBaseConf = _G.DataConfigManager:GetPetbaseConf(MonsterConf.base_id)
  local needReplace = true
  local quality = PetBaseConf.quality
  local lastChar
  if quality == _G.Enum.PetQuality.PQ_BLUE then
    lastChar = "1"
  elseif quality == _G.Enum.PetQuality.PQ_PURPLE then
    lastChar = "2"
  elseif quality == _G.Enum.PetQuality.PQ_ORANGE then
    lastChar = "3"
  end
  local NewRes = BattleConf.show_res
  if needReplace then
    NewRes = string.sub(NewRes, 1, -2)
    NewRes = string.format("%s%s", NewRes, lastChar)
  end
  return NewRes
end

function BattleUtils.GetCurrentBattleConf()
  local BattleStartParam = BattleManager.battleRuntimeData.battleStartParam
  if not BattleStartParam then
    return nil
  end
  local SeriesIndex = BattleStartParam.series_index or 0
  local ConfIDs = BattleStartParam.battleCfgIds
  if not ConfIDs then
    return nil
  end
  local ConfID = ConfIDs[SeriesIndex + 1]
  if not ConfID then
    return nil
  end
  return _G.DataConfigManager:GetBattleConf(ConfID)
end

function BattleUtils.CheckBattleFieldState(init_info)
  return BattleUtils.CheckTeamData(init_info.player_team) and BattleUtils.CheckTeamData(init_info.enemy_team)
end

function BattleUtils.GetBattleFieldActor()
  local battleFieldActor = BattleManager.vBattleField.battleFieldActor
  if not UE4.UObject.IsValid(battleFieldActor) then
    battleFieldActor = _G.NRCModuleManager:DoCmd(BattleModuleCmd.GetCurrentBattleFieldActor)
  end
  if not UE4.UObject.IsValid(battleFieldActor) then
    return nil
  end
  return battleFieldActor
end

function BattleUtils.CheckTeamData(roleInfo)
  local myPetPos = 0
  for playerPos, v in ipairs(roleInfo or DummyTable) do
    local player = BattleManager.battlePawnManager:GetPlayerByGuid(v.base.role_uin)
    if player then
      if v.magic_op_info and player.roleInfo.magic_op_info and player.roleInfo.magic_op_info.state ~= v.magic_op_info.state then
        return false
      end
      for petPos, pet in ipairs(v.pets or DummyTable) do
        local bInBattleField = BattleUtils.GetInBattle(pet.battle_inside_pet_info)
        local battlePet = BattleManager.battlePawnManager:GetPetByGuid(pet.battle_inside_pet_info.pet_id)
        if battlePet and bInBattleField then
          pet.posInField = myPetPos + (pet.battle_inside_pet_info.pos <= 0 and 1 or pet.battle_inside_pet_info.pos)
          if not BattleUtils.CheckPetData(pet, battlePet, bInBattleField) then
            return false
          end
        elseif bInBattleField or battlePet then
          return false
        end
      end
    else
      Log.Debug("zgx \230\137\190\228\184\141\229\136\176PLAYER", v.base.role_uin)
      return false
    end
    myPetPos = player.team.capacity * playerPos
  end
  return true
end

function BattleUtils.ChangeBattleRtpc(SkillCaster)
  if BattleManager and BattleManager.isInBattle and SkillCaster then
    local pet = BattleManager.battlePawnManager:GetBattlePetByActor(SkillCaster)
    if pet then
      if pet.teamEnm == BattleEnum.Team.ENUM_TEAM then
        if pet.player == BattleManager.battlePawnManager.TeamatePlayer then
          UE4.UAudioManager.SetGlobalRTPC("Pet_TurnBased_Battle", 1, "BattleUtils.ChangeBattleRtpc", 0)
        else
          UE4.UAudioManager.SetGlobalRTPC("Pet_TurnBased_Battle", 2, "BattleUtils.ChangeBattleRtpc", 0)
        end
      else
        UE4.UAudioManager.SetGlobalRTPC("Pet_TurnBased_Battle", 3, "BattleUtils.ChangeBattleRtpc", 0)
      end
    else
      local player = BattleManager.battlePawnManager:GetBattlePlayerByActor(SkillCaster)
      if player then
        if player.teamEnm == BattleEnum.Team.ENUM_TEAM then
          if player == BattleManager.battlePawnManager.TeamatePlayer then
            UE4.UAudioManager.SetGlobalRTPC("Pet_TurnBased_Battle", 1, "BattleUtils.ChangeBattleRtpc", 0)
          else
            UE4.UAudioManager.SetGlobalRTPC("Pet_TurnBased_Battle", 2, "BattleUtils.ChangeBattleRtpc", 0)
          end
        else
          UE4.UAudioManager.SetGlobalRTPC("Pet_TurnBased_Battle", 3, "BattleUtils.ChangeBattleRtpc", 0)
        end
      end
    end
  end
end

function BattleUtils.CheckPetData(petInfo, battlePet, bInBattleField)
  local battleInfo = petInfo.battle_inside_pet_info
  local hp = PetUtils.GetHP(battleInfo)
  local isDead = hp <= 0
  if isDead ~= battlePet:IsDead() then
    Log.Debug("zgx \230\173\187\228\186\161\231\138\182\230\128\129\228\184\141\229\144\140", battlePet.card.name)
    return false
  end
  if not battlePet.card:IsInBattle() then
    Log.Debug("zgx \230\173\187\228\186\161\228\184\138\229\156\186\228\184\141\229\144\140", battlePet.card.name)
    return false
  end
  local bBeCatch = BattleUtils.GetBeCatch(battleInfo)
  if bBeCatch ~= battlePet.card:IsBeCatch() then
    Log.Debug("zgx \230\141\149\230\141\137\231\138\182\230\128\129\228\184\141\229\144\140", battlePet.card.name)
    return false
  end
  if bInBattleField and petInfo.posInField ~= battlePet.card.posInField then
    Log.Debug("zgx \228\189\141\231\189\174\228\184\141\229\144\140", battlePet.card.name)
    return false
  end
  local serveBaseId = petInfo.battle_inside_pet_info.base_conf_id or 0
  local clientBaseId = battlePet.card.petBaseConf and battlePet.card.petBaseConf.id or 0
  if clientBaseId ~= serveBaseId then
    Log.Debug("zgx base id \230\156\137\229\143\152\229\140\150", battlePet.card.name)
    return false
  end
  local newBuffs = petInfo.battle_inside_pet_info.buffs or {}
  local oldBuffs = battlePet.card.petInfo.battle_inside_pet_info.buffs or {}
  if #newBuffs ~= #oldBuffs then
    Log.Debug("zgx buff\230\149\176\231\155\174\228\184\141\229\144\140", battlePet.card.name)
    return false
  end
  return true
end

function BattleUtils.GetHPForPerform(battle_inside_pet_info)
  local battlePet = BattleManager.battlePawnManager:GetPetByGuid(battle_inside_pet_info.pet_id)
  if battlePet and battlePet.health then
    return battlePet.health:GetHp()
  end
  local card = BattleManager.battlePawnManager:GetCardByGuid(battle_inside_pet_info.pet_id)
  if card then
    return card:GetHp()
  end
  return PetUtils.GetHP(battle_inside_pet_info)
end

function BattleUtils.GetHPPercentForPerform(battle_inside_pet_info)
  local max = PetUtils.GetMaxHP(battle_inside_pet_info)
  local hp = BattleUtils.GetHPForPerform(battle_inside_pet_info)
  return PetUtils._DoGetPercent(hp, max)
end

function BattleUtils.CheckPetInViewPort(battlePet)
  local camera = _G.BattleManager.vBattleField.battleCraneCamera
  if camera and UE4.UObject.IsValid(camera.CameraActor) then
    local camPos = camera.CameraActor:Abs_K2_GetActorLocation()
    local petPos = battlePet:GetActorLocation()
    local Dist = UE4.FVector.Dist(camPos, petPos)
    if Dist > 10000 then
      Log.Debug("BattleUtils.CheckPetInViewPort \232\182\133\229\135\186\232\140\131\229\155\1801")
      return false
    end
    local viewportSize = UE4.UWidgetLayoutLibrary.GetViewportSize(UE4Helper.GetCurrentWorld())
    local ProjMat = UE4.FMatrix()
    UE4.UNRCStatics.CalculateViewProjectionMatrix(camera.CameraComponent, ProjMat)
    local ProPos = UE4.UNRCStatics.Abs_ProjectWorldToScreenHidden(petPos, viewportSize.X, viewportSize.Y, ProjMat)
    Log.Debug("BattleUtils.CheckPetInViewPort \230\152\160\229\176\132\231\154\132\229\157\144\230\160\135=", ProPos, "\229\177\143\229\185\149\229\157\144\230\160\135viewportSize=", viewportSize)
    if ProPos.X < viewportSize.X * 0.1 or ProPos.X > viewportSize.X * 0.9 or ProPos.Y < viewportSize.Y * 0.1 or ProPos.Y > viewportSize.Y * 0.9 then
      Log.Debug("BattleUtils.CheckPetInViewPort \232\182\133\229\135\186\232\140\131\229\155\1802")
      return false
    else
      Log.Debug("BattleUtils.CheckPetInViewPort \230\173\163\229\184\184\232\140\131\229\155\180")
      return true
    end
  else
    return false
  end
end

function BattleUtils.GetVirtualPetPos(battlePet)
  local XRatio, YRatio
  if battlePet.teamEnm == BattleEnum.Team.ENUM_TEAM then
    XRatio, YRatio = 0.4, 0.65
  else
    XRatio, YRatio = 0.7, 0.65
  end
  if battlePet.index then
    XRatio = (battlePet.index - 1) * 0.1 + XRatio
  end
  local playerController = UE4.UGameplayStatics.GetPlayerController(UE4Helper.GetCurrentWorld(), 0)
  local viewportSize = UE4.UWidgetLayoutLibrary.GetViewportSize(UE4Helper.GetCurrentWorld())
  local ScreenPos = UE4.FVector2D(viewportSize.X * XRatio, viewportSize.Y * YRatio)
  local WorldPos = UE4.FVector()
  local WorldDir = UE4.FVector()
  local ans = UE.UGameplayStatics.Abs_DeprojectScreenToWorld(playerController, ScreenPos, WorldPos, WorldDir)
  if ans then
    local LineEnd = WorldPos + WorldDir * 500
    return LineEnd
  end
  return nil
end

function BattleUtils.CheckPlayerEnterBattleInSky()
  local Player = BattleUtils.GetPlayer()
  if Player and Player.viewObj then
    if Player.viewObj.BP_RideComponent:IsInDoubleRide() then
      return false
    end
    local Mode = Player.viewObj.CharacterMovement.MovementMode
    local isRiding = Player.statusComponent:HasStatus(Enum.WorldPlayerStatusType.WPST_RIDEALL)
    if Mode == UE.EMovementMode.MOVE_Falling or Mode == UE.EMovementMode.MOVE_Flying or isRiding then
      local BATTLE_GLOBAL_CONFIG = _G.DataConfigManager:GetTable(_G.DataConfigManager.ConfigTableId.BATTLE_GLOBAL_CONFIG)
      local checkHeight = BATTLE_GLOBAL_CONFIG:GetData("battle_in_the_air_height").num
      local playerPos = Player:GetActorLocation()
      local lineBegin = UE4.FVector(playerPos.X, playerPos.Y, playerPos.Z + Player:GetHalfHeight())
      local lineEnd = UE4.FVector(lineBegin.X, lineBegin.Y, lineBegin.Z - checkHeight)
      if LineTraceUtils.IsHitWorldStatic(lineBegin, lineEnd, {
        [0] = Player.viewObj
      }) or LineTraceUtils.HitWaterSurface(lineBegin, lineEnd, {
        [0] = Player.viewObj
      }) then
        return false
      else
        return true
      end
    end
  end
  return false
end

function BattleUtils.FadeBattlePawnRule(context)
  local fadeMeshList = {}
  local fadeInfo = _G.BattleManager.battleRuntimeData.fadeInfo
  if next(fadeInfo.fadeObjectList) == nil then
    return fadeMeshList
  end
  local battleCraneCamera = _G.BattleManager.vBattleField.battleCraneCamera
  if not (battleCraneCamera and battleCraneCamera.CameraActor) or not battleCraneCamera.CameraComponent then
    return fadeMeshList
  end
  for i, fadeObject in ipairs(fadeInfo.fadeObjectList) do
    if UE4.UObject.IsValid(fadeObject) and fadeObject:IsA(UE.ACharacter) then
      local rootComponent = fadeObject:K2_GetRootComponent()
      if rootComponent then
        rootComponent:SetCollisionObjectType(UE4.ECollisionChannel.ECC_Pawn)
        rootComponent:SetCollisionEnabled(UE.ECollisionEnabled.QueryOnly)
      end
    end
  end
  local cameraLookPosition = battleCraneCamera.CameraActor:Abs_K2_GetActorLocation()
  local cameraComponentLocation = battleCraneCamera.CameraComponent:Abs_K2_GetComponentLocation()
  local traceObjectTypes = {
    UE4.ECollisionChannel.ECC_Pawn
  }
  local hitResults, isHit
  local drawDebugTrace = UE4.EDrawDebugTrace.None
  if BattleConst.NpcAssistFadeTraceShowDebugLine then
    drawDebugTrace = UE4.EDrawDebugTrace.ForOneFrame
  end
  hitResults, isHit = UE4.UKismetSystemLibrary.Abs_SphereTraceMultiForObjects(UE4Helper.GetCurrentWorld(), cameraComponentLocation, cameraLookPosition, BattleConst.NpcAssistFadeTraceRadius, traceObjectTypes, true, {}, drawDebugTrace, nil, true, UE4.FLinearColor(1, 0, 1, 1), UE4.FLinearColor(1, 1, 0, 1))
  local hitResultList = hitResults:ToTable()
  
  local function findInFadeObjectList(actor)
    for i, fadeObject in ipairs(fadeInfo.fadeObjectList) do
      if UE4.UObject.IsValid(fadeObject) and fadeObject:IsA(UE.AActor) then
        if actor == fadeObject then
          return fadeObject
        end
      elseif UE4.UObject.IsValid(fadeObject) and fadeObject:IsA(UE.UMeshComponent) and actor == fadeObject:GetOwner() then
        return fadeObject
      end
    end
    return nil
  end
  
  for i, hitResult in ipairs(hitResultList) do
    local fadeObject = findInFadeObjectList(hitResult.Actor)
    if fadeObject then
      fadeMeshList[fadeObject] = {
        targetAlpha = 0,
        defaultAlpha = 1,
        originalAlpha = 1
      }
    end
  end
  return fadeMeshList
end

function BattleUtils.BattleOnLookerInComingFadeRule(context)
  local fadeMeshList = {}
  local fadeInfo = _G.BattleManager.battleRuntimeData.fadeInfo
  if next(fadeInfo.fadeObjectList) == nil then
    return fadeMeshList
  end
  
  local function findInFadeObjectList(actor)
    for i, fadeObject in ipairs(fadeInfo.fadeObjectList) do
      if UE4.UObject.IsValid(fadeObject) and fadeObject:IsA(UE.AActor) then
        if actor == fadeObject then
          return fadeObject
        end
      elseif UE4.UObject.IsValid(fadeObject) and fadeObject:IsA(UE.UMeshComponent) and actor == fadeObject:GetOwner() then
        return fadeObject
      end
    end
    return nil
  end
  
  local battleOnLookers = _G.BattleManager.battlePawnManager:GetAllBattleOnLookers()
  for i, battleOnLooker in ipairs(battleOnLookers) do
    local fadeObject = findInFadeObjectList(battleOnLooker.model)
    if fadeObject then
      fadeMeshList[fadeObject] = {
        targetAlpha = 1,
        defaultAlpha = 1,
        originalAlpha = 0,
        lerpSpeed = 0.5
      }
    end
  end
  return fadeMeshList
end

function BattleUtils.GetFBCallNameMagicId()
  return DataConfigManager:GetGlobalConfigNumByKeyType("a1_finalbattle_magic_ID1", _G.DataConfigManager.ConfigTableId.BATTLE_GLOBAL_CONFIG, 7010075)
end

function BattleUtils.GetFBCallArthurMagicId()
  return DataConfigManager:GetGlobalConfigNumByKeyType("a1_finalbattle_magic_ID2", _G.DataConfigManager.ConfigTableId.BATTLE_GLOBAL_CONFIG, 7010076)
end

function BattleUtils.CheckFinalBattleEnergyIsFull()
  local finalBattleData = _G.BattleManager.battleRuntimeData.finalBattleData
  if not finalBattleData then
    return false
  end
  if BattleUtils.IsFinalBattleP1() then
    return finalBattleData.is_final_battle_energy_full
  else
    return false
  end
end

function BattleUtils.IsAssignMagicItem(ItemConfigId, magicSkillId)
  local BagItemConf = _G.DataConfigManager:GetBagItemConf(ItemConfigId)
  if BagItemConf then
    local PlayerMagicConf = _G.DataConfigManager:GetPlayerMagicConf(BagItemConf.player_skill_id)
    if PlayerMagicConf and PlayerMagicConf.skill_id == magicSkillId then
      return true
    end
  end
  return false
end

function BattleUtils.GetPlayerModelId(roleInfo)
  if BattleUtils.IsPlayerUseHumanResByBit(roleInfo.base.state_bit) then
    if roleInfo.base.sex == ProtoEnum.ESexValue.SEX_MALE then
      return BattleConst.Human_Male
    else
      return BattleConst.Human_Female
    end
  else
    local npcCfg = _G.DataConfigManager:GetNpcConf(roleInfo.base.npc_id or 0, true)
    if npcCfg then
      return npcCfg.model_conf
    end
  end
  return 0
end

function BattleUtils.IsPlayerUseHumanRes(player)
  if not player then
    return false
  end
  local stateBit = player.roleInfo.base.state_bit
  return BattleUtils.IsPlayerUseHumanResByBit(stateBit)
end

function BattleUtils.IsPlayerUseHumanResByBit(bit)
  if not bit then
    return false
  end
  return bit & 1 << ProtoEnum.BATTLER_BIT_TYPE.BT_BATTLER_HUMAN > 0 or bit & 1 << ProtoEnum.BATTLER_BIT_TYPE.BT_NPC_IS_USE_HUMAN > 0
end

function BattleUtils.GetHyperLinkIds(inputString)
  local pattern = "<desc_id=(%d+)>"
  local ids = {}
  local vis = {}
  for id in string.gmatch(inputString, pattern) do
    if not vis[id] then
      table.insert(ids, id)
      vis[id] = true
      local descNote = _G.DataConfigManager:GetDescNoteConf(tonumber(id))
      local childIds = BattleUtils.GetChildIds(descNote.desc, vis)
      for _, childId in pairs(childIds) do
        table.insert(ids, childId)
      end
    end
  end
  return ids
end

function BattleUtils.GetChildIds(inputString, vis)
  local pattern = "<desc_id=(%d+)>"
  local ids = {}
  for id in string.gmatch(inputString, pattern) do
    if not vis[id] then
      table.insert(ids, id)
      vis[id] = true
      local descNote = _G.DataConfigManager:GetDescNoteConf(tonumber(id))
      local childIds = BattleUtils.GetChildIds(descNote.desc, vis)
      for _, childId in pairs(childIds) do
        table.insert(ids, childId)
      end
    end
  end
  return ids
end

function BattleUtils.IsWatchingBattle()
  return BattleManager.battleRuntimeData.isObserver
end

function BattleUtils.IsWatchingBroadcastBattle(battleRuntimeData)
  local stateCell = battleRuntimeData and battleRuntimeData:GetStateCell()
  if stateCell then
    local state = stateCell:Get()
    local isWatchingBroadcastBattle = state and state.isWatchingBroadcastBattle
    return isWatchingBroadcastBattle
  end
  return false
end

function BattleUtils.BattleOperationIsAllowInCurrentWatchingBattleMode(index)
  if not BattleUtils.IsWatchingBattle() then
    return true
  end
  local playerSettings = _G.NRCModuleManager:DoCmd(_G.SystemSettingModuleCmd.GetPlayerSettings)
  if not playerSettings then
    return false
  end
  local observeMode = BattleUtils.GetObserveModeFromSystemSettings(playerSettings)
  if observeMode == ProtoEnum.ObserveBattleMode.OBM_MODE_1 then
    if _G.BattleManager:GetCurrentStateName() == BattleEnum.StateNames.SwapSelect then
      return index == BattleEnum.Operation.ENUM_CHANGE
    end
    return index == BattleEnum.Operation.ENUM_SKILL or index == BattleEnum.Operation.ENUM_CHANGE
  else
    return false
  end
end

function BattleUtils.SetParticleKeyForSkillObj(petModel, skillObj, key)
  if key then
    local blackBoard = skillObj:GetBlackboard()
    if blackBoard then
      blackBoard:SetValueAsString(key, key)
    end
  end
  skillObj:AddIndividualKey(petModel, key or "")
end

function BattleUtils.SetParticleKeyForCastSkillObject(petModel, skillObj, key)
  if key then
    skillObj:AddBlackStringValue(key, key)
  end
  skillObj:AddActorKey(petModel, key or "")
end

function BattleUtils.IsLeaderChallengeDungeon(dungeonId)
  if not dungeonId or 0 == dungeonId then
    return false
  end
  local leaderDungeonId = _G.DataConfigManager:GetChallengeGlobalConf(1).num
  return dungeonId == leaderDungeonId
end

function BattleUtils.IsBattleFieldLevelReady()
  return _G.NRCModuleManager:DoCmd(BattleModuleCmd.GetBattleFieldLevelIsReady)
end

function BattleUtils.HideScenePawns()
  local Caches = BattleUtils.GetAllTraceNpc()
  if Caches then
    for _, Cache in ipairs(Caches) do
      if Cache and Cache.npc then
        if Cache.npc.AIComponent then
          Cache.npc.AIComponent:LockForBattleReason()
        end
        Cache.npc:SetVisibleForBattleReason(false)
      end
    end
  end
  NRCModeManager:DoCmd(PlayerModuleCmd.HIDE_LOCAL_PLAYER, true)
  BattleUtils.SetPlayerSkmTickable(false)
  NRCModeManager:DoCmd(NPCModuleCmd.EnterBattle, BattleManager.battleRuntimeData.NearbyValidBattleLocation, BattleConst.Define.BattleFieldRange)
  BattleUtils.PinOnTheGroundForAllPawn()
end

function BattleUtils.HideOutOfBattlePawns()
  local Caches = BattleUtils.GetAllTraceNpc()
  if Caches then
    for _, Cache in ipairs(Caches) do
      if Cache and Cache.npc then
        if Cache.npc.AIComponent then
          Cache.npc.AIComponent:LockForBattleReason()
        end
        Cache.npc:SetVisibleForBattleReason(false)
      end
    end
  end
  NRCModeManager:DoCmd(PlayerModuleCmd.HIDE_LOCAL_PLAYER, true)
  NRCModeManager:DoCmd(PlayerModuleCmd.HIDE_OTHER_PLAYER, true)
  BattleUtils.SetPlayerSkmTickable(false)
  local battleCenter = BattleManager.battleRuntimeData.NearbyValidBattleLocation
  local battleFieldRange = _G.BattleManager.vBattleField:GetBattleFieldRange()
  NRCModeManager:DoCmd(NPCModuleCmd.EnterBattle, battleCenter, battleFieldRange)
  BattleUtils.PinOnTheGroundForAllPawn()
end

function BattleUtils.GetBuffResByBuffIdAndType(buff_id, perform_type)
  local BuffConf = _G.DataConfigManager:GetBuffConf(buff_id, true)
  if BuffConf then
    local BuffRes = BuffConf["res_id_" .. perform_type]
    if BuffRes then
      return BuffRes
    end
  end
end

function BattleUtils.GetGrassChangeTypes()
  local NRCBigWorldPreloader = _G.NRCBigWorldPreloader
  local dataAsset = NRCBigWorldPreloader and NRCBigWorldPreloader:Get(BattleConst.ChangeGrassConfigurationPathKeyName)
  local GrassChangeMap = dataAsset and dataAsset.GrassChangeMap
  local GrassChangeMapLuaTable = GrassChangeMap and GrassChangeMap:ToTable() or {}
  local GrassChangeTypes = {}
  for sourceSmSoftPath, targetSmSoftPath in pairs(GrassChangeMapLuaTable) do
    local sourceSmPath = sourceSmSoftPath and sourceSmSoftPath.AssetPathName or ""
    local targetSmPath = targetSmSoftPath and targetSmSoftPath.AssetPathName or ""
    if string.IsNilOrEmpty(sourceSmPath) or string.IsNilOrEmpty(targetSmPath) then
    else
      local GrassChangeType = {}
      GrassChangeType.sourceSmPath = sourceSmPath
      GrassChangeType.targetSmPath = targetSmPath
      table.insert(GrassChangeTypes, GrassChangeType)
    end
  end
  return GrassChangeTypes
end

function BattleUtils.PrepareBattleGrassResList()
  local FVector = UE4.FVector
  local TArray = UE4.TArray
  local TMap = UE4.TMap
  local UNRCStatics = UE4.UNRCStatics
  local World = _G.UE4Helper.GetCurrentWorld()
  local absBattleCenter = _G.BattleManager.battleRuntimeData.TeleportBattleCenter
  absBattleCenter = absBattleCenter or UE4.FVector(0, 0, 0)
  local worldOrigin = FVector(World:GetWorldOriginX(), World:GetWorldOriginY(), World:GetWorldOriginZ())
  local battleCenter = absBattleCenter - worldOrigin
  local hideGrassRadius = BattleConst.HideObjectParam.HideGrassDist / 4
  local searchExtent = FVector(hideGrassRadius, hideGrassRadius, BattleConst.HideObjectParam.HideGrassDist)
  local foliageActors = UE4.UGameplayStatics.GetAllActorsOfClass(World, UE.AInstancedFoliageActor)
  local landscapeProxies = UE4.UGameplayStatics.GetAllActorsOfClass(World, UE.ALandscapeProxy)
  local validHismFromFoliageActors = TArray(UE.UHierarchicalInstancedStaticMeshComponent)
  local validHismFromLandscapeProxies = TArray(UE.UHierarchicalInstancedStaticMeshComponent)
  local sourcePathToTargetPath = TMap("", "")
  local GrassChangeTypes = BattleUtils.GetGrassChangeTypes()
  GrassChangeTypes = GrassChangeTypes or DummyTable
  for i, v in ipairs(GrassChangeTypes) do
    sourcePathToTargetPath:Add(v.sourceSmPath, v.targetSmPath)
  end
  UNRCStatics.CollectNearbyBattleGrassHism(battleCenter, absBattleCenter, searchExtent, sourcePathToTargetPath, foliageActors, landscapeProxies, validHismFromFoliageActors, validHismFromLandscapeProxies)
  local foliageHismToTargetStaticMeshPath = TMap(UE.UHierarchicalInstancedStaticMeshComponent, "")
  local landscapeHismToTargetStaticMeshPath = TMap(UE.UHierarchicalInstancedStaticMeshComponent, "")
  UNRCStatics.CollectNearbyBattleGrassInfo(sourcePathToTargetPath, validHismFromFoliageActors, validHismFromLandscapeProxies, foliageHismToTargetStaticMeshPath, landscapeHismToTargetStaticMeshPath)
  local foliageHismToTargetStaticMeshPathTable = foliageHismToTargetStaticMeshPath:ToTable()
  local landscapeHismToTargetStaticMeshPathTable = landscapeHismToTargetStaticMeshPath:ToTable()
  local targetStaticMeshPathSet = {}
  for k, v in pairs(foliageHismToTargetStaticMeshPathTable) do
    targetStaticMeshPathSet[v] = true
  end
  for k, v in pairs(landscapeHismToTargetStaticMeshPathTable) do
    targetStaticMeshPathSet[v] = true
  end
  local grassStaticMeshPathList = {}
  for k, v in pairs(targetStaticMeshPathSet) do
    table.insert(grassStaticMeshPathList, k)
  end
  local foliageActorsTable = foliageActors:ToTable()
  local battleRuntimeData = _G.BattleManager.battleRuntimeData
  battleRuntimeData.battleGrassInfo.FoliageActorList = foliageActorsTable
  battleRuntimeData.battleGrassInfo.GrassStaticMeshPathList = grassStaticMeshPathList
  battleRuntimeData.battleGrassInfo.foliageHismToTargetStaticMeshPathTable = foliageHismToTargetStaticMeshPathTable
  battleRuntimeData.battleGrassInfo.landscapeHismToTargetStaticMeshPathTable = landscapeHismToTargetStaticMeshPathTable
end

function BattleUtils.ComputeTeamPetScale(curHeight, normalMin, normalMax, bossMin, bossMax)
  if curHeight < normalMin then
    curHeight = normalMin
  elseif normalMax < curHeight then
    curHeight = normalMax
  end
  local normalRange = math.max(normalMax - normalMin, 0.1)
  local bossRange = math.max(bossMax - bossMin, 0.1)
  local temp = (curHeight - normalMin) / normalRange * bossRange
  return (bossMin + temp) / curHeight
end

function BattleUtils.GetBloodTeamPetScale(curHeight)
  if _G.BattleManager.debugEnv.closeBloodTeamScaleCompute then
    return 1
  end
  if curHeight <= 0.01 then
    return 1
  end
  local normal = _G.DataConfigManager:GetBattleGlobalConfig("blood_team_battle_normal_model_scale").numList
  local boss = _G.DataConfigManager:GetBattleGlobalConfig("blood_team_battle_boss_model_scale").numList
  return BattleUtils.ComputeTeamPetScale(curHeight, normal[1], normal[2], boss[1], boss[2])
end

function BattleUtils.GetBeastTeamPetScale()
  local teamScale = DataConfigManager:GetGlobalConfigNumByKeyType("battle_model_scale_blood", _G.DataConfigManager.ConfigTableId.BATTLE_GLOBAL_CONFIG, 10000) / 10000
  return teamScale
end

function BattleUtils.IsBuffBaseIdIsBuff93AndParams5Is5(buffBaseId)
  local buffBaseConf = buffBaseId and _G.DataConfigManager:GetBuffbaseConf(buffBaseId, true)
  local buffbaseOrder = buffBaseConf and buffBaseConf.buffbase_order
  if buffbaseOrder == Enum.BuffType.BFT_NINETY_THREE then
    local buffbase_param = buffBaseConf and buffBaseConf.buffbase_param
    local param5 = buffbase_param and buffbase_param[5]
    local param5Value = param5 and param5.params and param5.params[1]
    if 5 == param5Value then
      return true
    end
  end
  return false
end

function BattleUtils.IsBuff152(buff_id)
  local buff_conf = _G.DataConfigManager:GetBuffConf(buff_id, true)
  if buff_conf and buff_conf.buff_base_ids then
    for _, base_id in ipairs(buff_conf.buff_base_ids) do
      local buff_base_conf = _G.DataConfigManager:GetBuffbaseConf(base_id, true)
      if buff_base_conf and ProtoEnum.BuffType.BFT_O_FIFTYTWO == buff_base_conf.buffbase_order then
        return true, base_id
      end
    end
  end
  return false, nil
end

function BattleUtils.CollectBuff93EnhanceInfo(buffBaseIdList, buffBaseIdToStackMap)
  buffBaseIdToStackMap = buffBaseIdToStackMap or DummyTable
  local skillEnhanceInfos = {}
  for i, buffBaseId in ipairs(buffBaseIdList) do
    local buffBaseConf = _G.DataConfigManager:GetBuffbaseConf(buffBaseId)
    local buffbase_param = buffBaseConf and buffBaseConf.buffbase_param
    local param11 = buffbase_param and buffbase_param[11]
    local tip_id = param11 and param11.params and param11.params[1]
    local skillEnhanceInfo = ProtoMessage:newSkillEnhanceInfo()
    skillEnhanceInfo.buff_id = 0
    skillEnhanceInfo.buffbase_id = buffBaseId
    local stack = buffBaseIdToStackMap[buffBaseId] or 1
    skillEnhanceInfo.stack = stack
    skillEnhanceInfo.tip_id = tip_id
    table.insert(skillEnhanceInfos, skillEnhanceInfo)
  end
  return skillEnhanceInfos
end

function BattleUtils.SkillEnhanceInfoToSkillDamageType(enhance_info)
  local buffBaseId = enhance_info and enhance_info.buffbase_id
  local buffBaseConf = buffBaseId and _G.DataConfigManager:GetBuffbaseConf(buffBaseId)
  local order = buffBaseConf and buffBaseConf.buffbase_order
  if order == Enum.BuffType.BFT_STRENGTHEN_THE_SKILL then
    return Enum.SkillDamType.SDT_INSECT
  elseif order == Enum.BuffType.BFT_NINETY_THREE then
    return Enum.SkillDamType.SDT_ELECTRIC
  end
end

function BattleUtils.PreProcessEnhanceInfo(enhance_info, contextPetCard)
  local battlePetCard = contextPetCard
  local battlePetInfo = battlePetCard and battlePetCard.petInfo
  local battlePetInsideInfo = battlePetInfo and battlePetInfo.battle_inside_pet_info
  local triggeredBuff93List = battlePetInsideInfo and battlePetInsideInfo.triggered_buffs or DummyTable
  local triggeredBuff93BaseIdToStackMap = {}
  local new_enhance_info = {}
  for i, enhance in ipairs(enhance_info) do
    local buffBaseId = enhance.buffbase_id
    if BattleUtils.IsBuffBaseIdIsBuff93AndParams5Is5(buffBaseId) then
      for j, triggeredBuff in ipairs(triggeredBuff93List) do
        local triggeredBuffBaseId = triggeredBuff and triggeredBuff.buffbase_id
        local currValue = triggeredBuffBaseId and triggeredBuff93BaseIdToStackMap[triggeredBuffBaseId] or 0
        local triggeredBuffValue = 1
        local nextValue = currValue + triggeredBuffValue
        triggeredBuff93BaseIdToStackMap[triggeredBuffBaseId] = nextValue
      end
    end
    table.insert(new_enhance_info, enhance)
  end
  local buff93BaseIdList = {}
  for buffBaseId, _ in pairs(triggeredBuff93BaseIdToStackMap) do
    table.insert(buff93BaseIdList, buffBaseId)
  end
  local extra_enhance_info = BattleUtils.CollectBuff93EnhanceInfo(buff93BaseIdList, triggeredBuff93BaseIdToStackMap)
  for i, info in ipairs(extra_enhance_info) do
    table.insert(new_enhance_info, info)
  end
  return new_enhance_info
end

function BattleUtils.CheckCmdNeedPerform(notify)
  if notify then
    if BattleManager:NeedP1SwitchToP2(notify) or BattleManager:CheckP2NeedSupply() then
      return false
    end
    if BattleManager:NeedB1P1SwitchToP2(notify) or BattleManager:NeedB1P2SwitchToP3(notify) then
      return false
    end
    if notify.perform_cmd and notify.perform_cmd.perform_info then
      for i, v in ipairs(notify.perform_cmd.perform_info) do
        if v.type ~= ProtoEnum.BattlePerformType.BPT_DATA_UPDATE then
          return true
        end
      end
    end
  end
  return false
end

function BattleUtils.PreloadResOutsideBattle()
end

function BattleUtils.PreloadPveResOutsideBattle()
  Log.Error("BattleUtils.PreloadPveResOutsideBattle")
  
  local function PrepareBattlePlayer(spawnData)
    local roleID = BattleUtils.GetPlayerModelId(spawnData)
    local modelConf = _G.DataConfigManager:GetModelConf(roleID)
    if modelConf then
      local modelPath = modelConf.path
      local params = {}
      params.index = 1
      params.team = BattleEnum.Team
      params.player = nil
      params.inBattle = true
      self.loadResCount = self.loadResCount + 1
      Log.Error("BattlePreparePveResAction:PrepareBattlePlayer:", modelPath)
      _G.BattleResourceManager:PreloadAssetAsync(self, modelPath, self.PawnPlayerOver, self.PawnPlayerFailed)
    end
  end
  
  local function PreloadAssetCallBack()
  end
  
  loadResCount = 0
  NRCPanelManager:PreloadPanel("/Game/NewRoco/Modules/Core/Battle/UMG_EntryHud")
  preloadResList = {
    _G.UEPath.BP_BattleFieldConf,
    _G.UEPath.UMG_Battle_Buff
  }
  for i = 1, #preloadResList do
    loadResCount = loadResCount + 1
    _G.BattleResourceManager:LoadResAsync(nil, preloadResList[i], PreloadAssetCallBack, PreloadAssetCallBack)
  end
  resList = {
    BattleConst.PveEnter.TwoPlayerSkill_C,
    BattleConst.PveEnter.TwoEnemySkill_C
  }
  _G.BattleSkillManager:PreLoadRes(resList, false)
end

function BattleUtils.CheckIsReconnect()
  if BattleManager.battleRuntimeData.battleStartParam:IsReconnect() then
    return true
  end
  return false
end

function BattleUtils.ResetPlayerPosition()
  if not BattleManager:IsInBattle() then
    return
  end
  
  local function resetTeamPawnsPosition(teamEnum)
    for _, v in ipairs(BattleManager.battlePawnManager:GetAllTeam(teamEnum)) do
      if v.player and v.player.model then
        local RightPosTransForm = BattleManager.battlePawnManager.VBattleField:GetPositionInBattleMap(v.teamEnm, v.player.posInField, true)
        if RightPosTransForm then
          v.player.model:Abs_K2_SetActorTransform_WithoutHit(RightPosTransForm)
          v.player:PinOnTheGround()
        end
      end
      if #v.pets > 0 then
        for _, p in pairs(v.pets) do
          if p.model and p.card:IsExistAtField() then
            local RightPosTransForm = BattleManager.battlePawnManager.VBattleField:GetPositionInBattleMap(p.teamEnm, p.card.posInField)
            if RightPosTransForm then
              p.model:Abs_K2_SetActorTransform_WithoutHit(RightPosTransForm)
              p:PinOnTheGround()
            end
          end
        end
      end
    end
  end
  
  resetTeamPawnsPosition(BattleEnum.Team.ENUM_TEAM)
  resetTeamPawnsPosition(BattleEnum.Team.ENUM_ENEMY)
end

function BattleUtils.ShowAndResetPlayer()
  if not BattleManager:IsInBattle() then
    return
  end
  for i, v in ipairs(BattleManager.battlePawnManager:GetAllTeam(BattleEnum.Team.ENUM_TEAM)) do
    if v.player and v.player.model then
      v.player:ShowPlayer()
      local sceneComp = v.player.model:GetComponentByClass(UE4.USceneComponent)
      if sceneComp then
        sceneComp:SetVisibility(true)
      end
      v.player.model:TryHelmetOn()
      if v.player.battlePlayerComponents then
        v.player.battlePlayerComponents:HideMark()
      end
    end
    if #v.pets > 0 then
      for _, p in pairs(v.pets) do
        if p.model and p.card:IsExistAtField() then
          p:ShowPet()
        end
      end
    end
  end
  for i, v in ipairs(BattleManager.battlePawnManager:GetAllTeam(BattleEnum.Team.ENUM_ENEMY)) do
    if v.player and v.player.model then
      v.player:ShowPlayer()
      local sceneComp = v.player.model:GetComponentByClass(UE4.USceneComponent)
      if sceneComp then
        sceneComp:SetVisibility(true)
      end
      if v.player.battlePlayerComponents then
        v.player.battlePlayerComponents:HideMark()
      end
    end
    if #v.pets > 0 then
      for _, p in pairs(v.pets) do
        if p.model and p.card:IsExistAtField() then
          p:ShowPet()
        end
      end
    end
  end
  BattleUtils.ResetPlayerPosition()
end

function BattleUtils.OverlayEnhanceInfo(enhance_info)
  local has = {}
  local Res = {}
  for i, enhance in ipairs(enhance_info) do
    if enhance.tip_id > 0 then
      if not has[enhance.tip_id] then
        local newSkillEnhanceInfo = {}
        table.copy(enhance, newSkillEnhanceInfo)
        Res[#Res + 1] = newSkillEnhanceInfo
        has[newSkillEnhanceInfo.tip_id] = #Res
      else
        Res[has[enhance.tip_id]].stack = Res[has[enhance.tip_id]].stack + enhance.stack
      end
    end
  end
  return Res
end

function BattleUtils.IsPetCanCastFastWindSkill(card)
  local currentStateType = _G.BattleManager.battleRuntimeData.startRoundSelectRoundStateType
  if currentStateType == ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_SELECT_PET or currentStateType == ProtoEnum.BATTLE_STATE_NOTIFY_TYPE.BATTLE_STATE_ROUND_SELECT_PET then
    return false
  end
  local battlePets = _G.BattleManager.battlePawnManager:GetTeamAllPets()
  local petInfo = card and card.petInfo
  local insidePetInfo = petInfo and petInfo.battle_inside_pet_info
  local petId = insidePetInfo and insidePetInfo.pet_id
  if not petId then
    return false
  end
  for i, battlePet in ipairs(battlePets) do
    local battlePetCard = battlePet.card
    local battlePetInfo = battlePetCard and battlePetCard.petInfo
    local battlePetInsideInfo = battlePetInfo and battlePetInfo.battle_inside_pet_info
    local canCastFastWindSkillPetUniList = battlePetInsideInfo and battlePetInsideInfo.has_fast_skill_pets or {}
    for _, petUni in ipairs(canCastFastWindSkillPetUniList) do
      if petUni == petId then
        return true
      end
    end
  end
  return false
end

function BattleUtils.IsMainWindowChangingBetweenSubPanels()
  local mainWindow = BattleUtils.GetMainWindow()
  if UE.UObject.IsValid(mainWindow) then
    return mainWindow:IsChangingBetweenSubPanels()
  end
  return false
end

function BattleUtils.GetMainWindowSubPanelItemOpenOrderTable(itemList)
  local order = {}
  if BattleUtils.IsMainWindowChangingBetweenSubPanels() then
    for i, item in ipairs(itemList) do
      order[#itemList - i + 1] = item
    end
  else
    for i, item in ipairs(itemList) do
      order[i] = item
    end
  end
  return order
end

function BattleUtils.PinOnTheGroundForAllPawn()
  if not BattleManager:IsInBattle() then
    return
  end
  local players = BattleManager.battlePawnManager:GetAllPlayers()
  for _, player in ipairs(players) do
    player:PinOnTheGround()
  end
  local pets = BattleManager.battlePawnManager:GetAllPets()
  for _, pet in ipairs(pets) do
    pet:PinOnTheGround()
  end
end

function BattleUtils.HasLockChangePetState(battlePet)
  if not battlePet or not battlePet.buffComponent then
    return false
  end
  if not battlePet.buffComponent.buffs then
    return false
  end
  local buffs = battlePet.buffComponent.buffs
  for _, buff in ipairs(buffs) do
    local buffBaseOrder = buff:GetBuffBaseOrder()
    if buffBaseOrder == Enum.BuffType.BFT_BAN then
      return true
    end
  end
  return false
end

function BattleUtils.GetBossPetBaseRuleParams(Pet)
  local ItemLeaderTokenData = require("NewRoco.Modules.System.BattleUI.Res.ItemOperation.UMG_BattleLeaderTokenItem_C").Data
  local matchedItems = {}
  local bossPeIds = Pet.card.petBaseConf.bosspetbase_id_arry
  local bossPetEvolutionIds = Pet.card.petBaseConf.bosspetbase_rule_param
  local bossPetBaseRule = Pet.card.petBaseConf.bosspetbase_rule
  if 2 == bossPetBaseRule and bossPeIds and bossPetEvolutionIds and #bossPeIds ~= #bossPetEvolutionIds then
    Log.Error("\233\166\150\233\162\134\228\191\161\231\137\169\232\191\155\229\140\150\233\133\141\231\189\174\229\188\130\229\184\184,\230\163\128\230\159\165PETBASE_CONF\233\133\141\231\189\174\239\188\140 id=", Pet.card.petBaseConf.id, "bosspetbase_id_arry\233\149\191\229\186\166=", #bossPeIds, "bosspetbase_rule_param\233\149\191\229\186\166=", #bossPetEvolutionIds)
    return
  end
  local player = _G.BattleManager.battlePawnManager.TeamatePlayer
  if not player then
    Log.Error("ShowEvolutionaryToken player is nil")
    return
  end
  local hasEvoItems = player:GetItemsByType(Enum.BagItemType.BI_BOSS_EVO)
  if bossPetEvolutionIds and hasEvoItems and bossPeIds then
    local ItemMap = {}
    for _, itemInfo in ipairs(hasEvoItems) do
      ItemMap[itemInfo.item_conf_id] = itemInfo
    end
    for index, Id in ipairs(bossPetEvolutionIds) do
      local itemInfo = ItemMap[Id]
      local petId = bossPeIds[index]
      if itemInfo then
        local BagItemConf = _G.DataConfigManager:GetBagItemConf(itemInfo.item_conf_id)
        if BagItemConf then
          table.insert(matchedItems, ItemLeaderTokenData(itemInfo.item_id, itemInfo.item_conf_id, itemInfo.gid, itemInfo.num, itemInfo.is_charge, itemInfo.remain_use_cnt, itemInfo.max_use_cnt, itemInfo.allow_use_cnt, BagItemConf.type, itemInfo.battle_use_time_remain, itemInfo.battle_use_time_max, petId))
        end
      end
    end
  end
  return matchedItems
end

function BattleUtils.TryUseItem(itemData)
  if itemData.canCharge and itemData.remainCnt <= 0 then
    local text = _G.LuaText.alchemy_bottle_times_out or ""
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, text)
    return false
  elseif itemData.allowUseCntInBattle and itemData.allowUseCntInBattle <= 0 then
    local text = _G.LuaText.bottle_time_tip or ""
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, text)
    return false
  elseif itemData.allowCnt and itemData.allowCnt <= 0 then
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, LuaText.rounditemaction_2)
    return false
  elseif itemData.num and itemData.num <= 0 then
    _G.NRCModuleManager:DoCmd(_G.TipsModuleCmd.TopHud_ShowTips, LuaText.rounditemaction_3)
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

function BattleUtils.ContainTaskPerformControl(ControlType)
  local battleConf = BattleUtils.GetBattleConfig()
  if battleConf then
    return table.contains(battleConf.task_battle_performance_control, ControlType)
  end
  return false
end

function BattleUtils.CloseBattleAndTaskBlackLoading()
  if BattleUtils.ContainTaskPerformControl(Enum.TaskBattlePerformanceControl.TBPC_ENTER_BLACK) then
    _G.NRCEventCenter:DispatchEvent(NRCGlobalEvent.CLOSE_BLACK_SCREEN)
    if BattleUtils.HasUI("BattleLoading") then
      _G.NRCModuleManager:DoCmd(BattleUIModuleCmd.SetForbidCloseLoading, nil)
      local asyncData = {
        owner = self,
        callback = function()
          _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.ForceCloseLoading)
        end
      }
      NRCModuleManager:DoCmdAsync(asyncData, BattleUIModuleCmd.CloseLoading)
    else
      _G.NRCModuleManager:DoCmd(_G.BattleUIModuleCmd.ForceCloseLoading)
    end
  end
end

function BattleUtils.GetChangePetPathBySuit(player, battlePetInfo)
  if not player then
    return
  end
  if BattleUtils.IsTeam() and player.guid ~= _G.BattleManager.battlePawnManager.TeamatePlayer.guid then
    return BattleConst.TeamNpcHuanChong
  end
  local petData = battlePetInfo and battlePetInfo.battle_inside_pet_info
  local petBaseId = petData and petData.base_conf_id
  local changeResId, suitResId
  local fashionData = player and player.FashionData
  local suitConf = fashionData and fashionData.suitConf
  if suitConf then
    _, suitResId = BattleUtils.GetFashionPerformBySuitConf(suitConf, petBaseId)
  end
  local bondConfs = fashionData and fashionData.bondConfs or {}
  local ssSetting, ssPerformResId, asPerformResId, asSetting
  local matchBondList = BattleUtils.GetBondMatchInfoWithBondDataAndBattlePetInfo(bondConfs, battlePetInfo)
  for _, v in ipairs(matchBondList) do
    local bondConf = v and v.bondConf
    local bondPerformId = bondConf and bondConf.perform_id
    local quality = v and v.quality
    local setting = v and v.setting
    if quality == _G.Enum.FashionBondQuality.FBQ_SS then
      local bondCalloutSkill = bondConf and bondConf.bond_callout_skill or 0
      if bondCalloutSkill > 0 then
        ssPerformResId = bondCalloutSkill
        ssSetting = setting
      end
    else
      local fashionPerformConf, resId = BattleUtils.GetFashionPerformById(bondPerformId, petBaseId)
      if fashionPerformConf then
        asPerformResId = resId
        asSetting = setting
      end
    end
  end
  local as_change_action_in_battle = asSetting and asSetting.change_action_in_battle
  if nil == as_change_action_in_battle then
    as_change_action_in_battle = true
  end
  if not as_change_action_in_battle then
    asPerformResId = nil
  end
  local ss_change_action_in_battle = ssSetting and ssSetting.change_action_in_battle
  if nil == ss_change_action_in_battle then
    ss_change_action_in_battle = true
  end
  if not ss_change_action_in_battle then
    ssPerformResId = nil
  end
  local isSsSettingPriority = ssSetting and ssSetting.is_priority
  local bondResId = asPerformResId or ssPerformResId
  if isSsSettingPriority and ssPerformResId then
    bondResId = ssPerformResId
  end
  if suitResId then
    changeResId = suitResId
  elseif bondResId then
    changeResId = bondResId
  end
  if changeResId then
    local changePath = BattleUtils.GetSkillPathByResId(changeResId)
    if changePath then
      return changePath
    end
  end
  return player.FashionData:GetHuanChong(petBaseId)
end

function BattleUtils.GetFashionPerformBySuitConf(suitConf, petBaseId)
  if not suitConf or not suitConf.perform_id then
    return
  end
  return BattleUtils.GetFashionPerformById(suitConf.perform_id, petBaseId)
end

function BattleUtils.GetFashionPerformById(performId, petBaseId)
  local PerformConf = _G.DataConfigManager:GetFashionPerformConf(performId, true)
  if PerformConf then
    if table.contains(PerformConf.petbase1_id, petBaseId) then
      return PerformConf, PerformConf.suiteffect1_callout_skill
    end
    if table.contains(PerformConf.petbase2_id, petBaseId) then
      return PerformConf, PerformConf.suiteffect2_callout_skill
    end
    if table.contains(PerformConf.petbase3_id, petBaseId) then
      return PerformConf, PerformConf.suiteffect3_callout_skill
    end
    for i, v in ipairs(PerformConf.petbase4_id) do
      if v == petBaseId and PerformConf.suiteffect4_callout_skill then
        if i <= #PerformConf.suiteffect4_callout_skill then
          return PerformConf, PerformConf.suiteffect4_callout_skill[i]
        elseif #PerformConf.suiteffect4_callout_skill >= 1 then
          return PerformConf, PerformConf.suiteffect4_callout_skill[1]
        end
      end
    end
  end
end

function BattleUtils.GetFashionPerformInfoByPerformConfAndPetBaseConf(suitPerformConf, petBaseConf)
  local HuanChongPath, HuanChongSuitId, PvpOverPath, PvpOverSuitId
  local petBaseId = petBaseConf and petBaseConf.id
  local petbase1_id = suitPerformConf and suitPerformConf.petbase1_id or {}
  local petbase2_id = suitPerformConf and suitPerformConf.petbase2_id or {}
  local petbase3_id = suitPerformConf and suitPerformConf.petbase3_id or {}
  local petbase4_id = suitPerformConf and suitPerformConf.petbase4_id or {}
  local suiteffect1_callout_skill = suitPerformConf and suitPerformConf.suiteffect1_callout_skill
  local suiteffect2_callout_skill = suitPerformConf and suitPerformConf.suiteffect2_callout_skill
  local suiteffect3_callout_skill = suitPerformConf and suitPerformConf.suiteffect3_callout_skill
  local suiteffect4_callout_skill = suitPerformConf and suitPerformConf.suiteffect4_callout_skill
  local suiteffect3_win_skill = suitPerformConf and suitPerformConf.suiteffect3_win_skill
  local suiteffect4_win_skill = suitPerformConf and suitPerformConf.suiteffect4_win_skill
  local suitPerformConfId = suitPerformConf and suitPerformConf.id
  if table.contains(petbase1_id, petBaseId) then
    local changePath = BattleUtils.GetSkillPathByResId(suiteffect1_callout_skill)
    if changePath then
      HuanChongPath = changePath
      HuanChongSuitId = suitPerformConfId
    end
  elseif table.contains(petbase2_id, petBaseId) then
    local changePath = BattleUtils.GetSkillPathByResId(suiteffect2_callout_skill)
    if changePath then
      HuanChongPath = changePath
      HuanChongSuitId = suitPerformConfId
    end
  elseif table.contains(petbase3_id, petBaseId) then
    local changePath = BattleUtils.GetSkillPathByResId(suiteffect3_callout_skill)
    if changePath then
      HuanChongPath = changePath
      HuanChongSuitId = suitPerformConfId
    end
    changePath = BattleUtils.GetSkillPathByResId(suiteffect3_win_skill)
    if changePath then
      PvpOverPath = changePath
      PvpOverSuitId = suitPerformConfId
    end
  elseif table.contains(petbase4_id, petBaseId) then
    local changePath
    for i, v in ipairs(petbase4_id) do
      if v == petBaseId and suiteffect4_callout_skill then
        if i <= #suiteffect4_callout_skill then
          changePath = BattleUtils.GetSkillPathByResId(suiteffect4_callout_skill[i])
        elseif #suiteffect4_callout_skill >= 0 then
          changePath = BattleUtils.GetSkillPathByResId(suiteffect4_callout_skill[1])
        end
        if changePath then
          HuanChongPath = changePath
          HuanChongSuitId = suitPerformConfId
        end
        break
      end
    end
    changePath = BattleUtils.GetSkillPathByResId(suiteffect4_win_skill)
    if changePath then
      PvpOverPath = changePath
      PvpOverSuitId = suitPerformConfId
    end
  end
  return HuanChongPath, HuanChongSuitId, PvpOverPath, PvpOverSuitId
end

function BattleUtils.GetCustomizeConditionKeyValue(customizeType, playerSelectedIndex)
  local index = playerSelectedIndex
  if not playerSelectedIndex or playerSelectedIndex <= 0 then
    index = _G.SkillUtils.CustomizeTypeDefaultIndex(customizeType)
  end
  local conditionKey = _G.SkillUtils.CustomizeTypeToString(customizeType)
  local conditionValue = _G.SkillUtils.GetCustomizeAnimName(customizeType, index)
  local battleConfig = _G.BattleManager.battleRuntimeData and _G.BattleManager.battleRuntimeData.battleConfig
  Log.DebugFormat("[PlayerAnimationCustomize] customizeType={0}, playerIndex={1}, index={2}, battleConfig={3}, conditionKey={4}, conditionValue={5}", customizeType, playerSelectedIndex, index, battleConfig and battleConfig.id or "nil", conditionKey, conditionValue)
  return conditionKey, conditionValue
end

function BattleUtils.GetBondMatchInfoWithBondDataAndBattlePetInfo(bondDataList, petInfo)
  bondDataList = bondDataList or {}
  local petData = petInfo and petInfo.battle_inside_pet_info
  local petBaseConfId = petData and petData.base_conf_id
  local petBaseConf = _G.DataConfigManager:GetPetbaseConf(petBaseConfId, true)
  local bloodId = petData and petData.blood_id
  local matchBondList = {}
  for _, v in ipairs(bondDataList) do
    local bondConf = v and v.bondConf
    local bondPerformId = bondConf and bondConf.perform_id
    if bondConf then
      local quality = v and v.quality
      if quality == _G.Enum.FashionBondQuality.FBQ_SS then
        local bondUnitType = bondConf and bondConf.pet_skill_type
        local unitTypes = petBaseConf and petBaseConf.unit_type or {}
        local skillDamTypeList = {}
        local bloodIdToSkillDamType = PetUtils.GetSkillDamTypeByPetBloodType(bloodId)
        table.insert(skillDamTypeList, bloodIdToSkillDamType)
        for i, unitType in ipairs(unitTypes) do
          table.insert(skillDamTypeList, unitType)
        end
        local matchUnitType = skillDamTypeList and bondUnitType and table.contains(skillDamTypeList, bondUnitType)
        local setting = v and v.setting
        local change_action_in_battle = setting and setting.change_action_in_battle
        local enableChange = not setting or false ~= change_action_in_battle
        if matchUnitType and enableChange then
          local bondCalloutSkill = bondConf and bondConf.bond_callout_skill or 0
          if bondCalloutSkill > 0 then
            table.insert(matchBondList, v)
          end
        end
      else
        local fashionPerformConf = BattleUtils.GetFashionPerformById(bondPerformId, petBaseConfId)
        if fashionPerformConf then
          table.insert(matchBondList, v)
        end
      end
    end
  end
  return matchBondList
end

function BattleUtils.IsPlayerCanSeeTarget()
  local Target = BattleUtils.GetTraceNpc()
  if not (Target and Target.npc) or not UE.UObject.IsValid(Target.npc.viewObj) then
    return false
  end
  local localPlayer = NRCModeManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  if not localPlayer or not UE.UObject.IsValid(localPlayer.viewObj) then
    return false
  end
  local beginX, beginY, beginZ = localPlayer.viewObj:Abs_K2_GetActorLocation_XYZ()
  local beginLocation = UE.FVector(beginX, beginY, beginZ + 100)
  local endX, endY, endZ = Target.npc.viewObj:Abs_K2_GetActorLocation_XYZ()
  local endLocation = UE.FVector(endX, endY, endZ + 100)
  local distance = (beginX - endX) * (beginX - endX) + (beginY - endY) * (beginY - endY)
  if distance > 1000000 then
    return false
  end
  local hitResult = LineTraceUtils.HitWorldStaticMesh(beginLocation, endLocation, {
    Target.npc.viewObj,
    localPlayer.viewObj
  })
  if hitResult then
    Log.Debug("BattlePiecesTeamEnterPerform:IsPlayerCanSeeTarget can find target NPC, but player can not see it.", hitResult.Actor)
  end
  return nil == hitResult
end

function BattleUtils.TryReplaceSkillPathIfCameraAnimCollided(skillPath, skillPath_Fallback)
  local skillClass
  if skillPath then
    skillClass = BattleSkillManager:GetLoadedClass(skillPath)
    if BattleUtils.IsNeedG6PreCheck() and UE4.UObject.IsValid(skillClass) and skillPath_Fallback then
      local skillClass_Fallback = BattleSkillManager:GetLoadedClass(skillPath_Fallback)
      if skillClass_Fallback and UE4.UObject.IsValid(skillClass) then
        local center = BattleManager.vBattleField.battleFieldActor:GetTransform()
        local bPassed = UE4.RocoSkillUtils.PreCheckG6SkillForCollision(skillClass, center, _G.UE4Helper.GetCurrentWorld())
        if not bPassed then
          skillClass = skillClass_Fallback
          skillPath = skillPath_Fallback
        end
      end
    end
  else
    skillPath = skillPath_Fallback
    if skillPath then
      skillClass = BattleSkillManager:GetLoadedClass(skillPath)
    end
  end
  return skillPath, skillClass
end

function BattleUtils.IsEnterCatchInTeamBattle()
  local battleStartParam = _G.BattleManager.battleRuntimeData.battleStartParam
  if battleStartParam and battleStartParam:CheckInitState(ProtoEnum.BATTLEFIELD_BIT_TYPE.BT_BEAST_REENTRY_CATCH) then
    return true
  end
  return false
end

function BattleUtils.GetContactEnterType(TargetPet)
  local TargetPet2 = BattleManager.battleRuntimeData:GetCurrentNPC()
  local speedThreshold = _G.DataConfigManager:GetBattleGlobalConfig("velocity_difference_threshold").num
  local localPlayer = NRCModeManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  local contactType
  if localPlayer.IsTurnToTarget and not TargetPet.IsTurnToTarget then
    contactType = BattleEnum.ContactEnterType.PlayerHit
  elseif not localPlayer.IsTurnToTarget and TargetPet.IsTurnToTarget then
    contactType = BattleEnum.ContactEnterType.PetHit
  elseif localPlayer.TouchBattleVel < TargetPet.TouchBattleVel - speedThreshold then
    contactType = BattleEnum.ContactEnterType.PetHit
  elseif localPlayer.TouchBattleVel > TargetPet.TouchBattleVel + speedThreshold then
    contactType = BattleEnum.ContactEnterType.PlayerHit
  else
    contactType = BattleEnum.ContactEnterType.HitTogether
  end
  localPlayer.TouchBattleVel = nil
  TargetPet.TouchBattleVel = nil
  localPlayer.IsTurnToTarget = nil
  TargetPet.IsTurnToTarget = nil
  return contactType
end

function BattleUtils.CalcPursue(Player, NPC)
  local function GetAngleAsCosine(key)
    local Conf = _G.DataConfigManager:GetBattleGlobalConfig(key)
    
    local Angle = 30
    if Conf and Conf.num then
      Angle = Conf.num
    end
    return math.cos(Angle)
  end
  
  local function GetNum(key)
    local Conf = _G.DataConfigManager:GetBattleGlobalConfig(key)
    local Num = 30
    if Conf and Conf.num then
      Num = Conf.num
    end
    return Num
  end
  
  local PlayerView = Player and Player.viewObj
  if PlayerView.BP_RideComponent.RidePet then
    PlayerView = PlayerView.BP_RideComponent.RidePet
  end
  local NPCView = NPC and NPC.viewObj
  if not PlayerView or not NPCView then
    return false, false
  end
  local PComp = PlayerView.CharacterMovement
  local NComp = NPCView.CharacterMovement
  local PVel = PComp.Velocity
  local NVel = NComp.Velocity
  local PVelNorm = UE.FVector(PVel.X, PVel.Y, 0)
  local NVelNorm = NPCView:GetActorForwardVector()
  PVelNorm:Normalize()
  local PlayerLoc = PlayerView:K2_GetActorLocation()
  local NPCLoc = NPCView:K2_GetActorLocation()
  local P2NDir = NPCLoc - PlayerLoc
  local N2PDir = PlayerLoc - NPCLoc
  P2NDir.Z = 0
  N2PDir.Z = 0
  P2NDir:Normalize()
  N2PDir:Normalize()
  local CosP2N = PVelNorm:Dot(P2NDir)
  local CosN2P = NVelNorm:Dot(N2PDir)
  local PlayerPursue = CosP2N >= 1 - P2NAbs
  local NPCPursue = CosN2P >= 1 - N2PAbs
  if PlayerPursue or NPCPursue then
    Player.TouchBattleVel = PVel:Size()
    Player.IsTurnToTarget = PlayerPursue
    NPC.TouchBattleVel = NVel:Size()
    NPC.IsTurnToTarget = NPCPursue
  end
  if PlayerPursue and NPCPursue then
    local PSpeed = PVel:Size()
    local NSpeed = NVel:Size()
    if PSpeed > NSpeed + VDiffThreshold then
      NPCPursue = false
    elseif PSpeed < NSpeed - VDiffThreshold then
      PlayerPursue = false
    end
  end
  return PlayerPursue, NPCPursue
end

function BattleUtils.CalculateDividerByNumListFirstAndSecondItem(numList)
  local first = numList[1] or 1
  local second = numList[2] or 1
  local divider = first / second
  return divider
end

function BattleUtils.CheckCondition_126282472()
  local bInBattle = _G.BattleManager:IsInBattle()
  if bInBattle then
    local battleType = _G.BattleManager.battleRuntimeData.battleType
    local battleTypeConf = _G.DataConfigManager:GetBattleTypeConf(battleType, true)
    if battleTypeConf and battleTypeConf.is_show_information ~= nil then
      return battleTypeConf.is_show_information
    end
  end
  return true
end

function BattleUtils.CheckConditionSpeed()
  local bInBattle = _G.BattleManager:IsInBattle()
  if bInBattle then
    if BattleUtils.IsBadgeChallenge() then
      return true
    end
    local battleType = _G.BattleManager.battleRuntimeData.battleType
    local battleTypeConf = _G.DataConfigManager:GetBattleTypeConf(battleType, true)
    if battleTypeConf and battleTypeConf.is_show_information ~= nil then
      return battleTypeConf.is_show_information
    end
  end
  return false
end

function BattleUtils.CheckCondition_LocallyHide()
  local bInBattle = _G.BattleManager:IsInBattle()
  if bInBattle then
    return false
  end
  return true
end

function BattleUtils.CheckCondition_128223171()
  return not _G.BattleManager:IsInBattle()
end

function BattleUtils.IsPartialShow(card)
  if card then
    return card.IsFirstMeet or card.petState:GetMimic(true)
  end
  return false
end

function BattleUtils.LockCam(reason)
  if BattleManager.vBattleField and BattleManager.vBattleField.battleCraneCamera then
    BattleManager.vBattleField.battleCraneCamera:LockCamera(reason)
  end
end

function BattleUtils.UnLockCam()
  if BattleManager.vBattleField and BattleManager.vBattleField.battleCraneCamera then
    BattleManager.vBattleField.battleCraneCamera:UnlockCamera()
  end
end

function BattleUtils.IgnoreLocking(value)
  if BattleManager.vBattleField and BattleManager.vBattleField.battleCraneCamera then
    BattleManager.vBattleField.battleCraneCamera:IgnoreLocking(value)
  end
end

function BattleUtils.GetCurEnvActor()
  local Instance = UE.UNRCPlatformGameInstance.GetInstance()
  local EnvSys = Instance and Instance:GetWorldSubSystem()
  if EnvSys then
    return EnvSys:GetEnvActor()
  end
end

function BattleUtils.SetLockEnvActor(lock)
  Log.Debug("zgx BattleUtils.SetLockEnvActor:", lock)
  local Instance = UE.UNRCPlatformGameInstance.GetInstance()
  local EnvSys = Instance and Instance:GetWorldSubSystem()
  if EnvSys then
    EnvSys:SetLockChangeEnvActor(lock)
  end
end

function BattleUtils.TeleportEnvActorInZ(zValue)
  local Instance = UE.UNRCPlatformGameInstance.GetInstance()
  local EnvSys = Instance and Instance:GetWorldSubSystem()
  if EnvSys then
    local CurEnvActor = EnvSys:GetEnvActor()
    if CurEnvActor then
      local rootComponent = CurEnvActor:K2_GetRootComponent()
      if rootComponent then
        if zValue then
          rootComponent:SetMobility(UE4.EComponentMobility.Movable)
          local pos = CurEnvActor:Abs_K2_GetActorLocation()
          BattleManager.EnvActorZ = pos.Z
          CurEnvActor:Abs_K2_SetActorLocation(UE.FVector(pos.X, pos.Y, zValue), false, nil, false)
        end
        CurEnvActor.IsUseCertainTodVolume = true
      end
    end
  end
end

function BattleUtils.ForceRefreshEnvTodParams()
  local Instance = UE.UNRCPlatformGameInstance.GetInstance()
  local EnvSys = Instance and Instance:GetWorldSubSystem()
  if not EnvSys then
    return
  end
  local curTime = EnvSys:GetGameTime()
  local nudgeTime = (curTime + 0.2) % 24
  Log.Debug("zgx BattleUtils.ForceRefreshEnvTodParams:", curTime, nudgeTime)
  EnvSys:SetGameTime(nudgeTime, true, true)
  EnvSys:SetGameTime(curTime, true, true)
end

function BattleUtils.GetSeqByUinFormNotify(playerId, notify)
  if not playerId then
    return 0
  end
  for _, v in ipairs(notify.init_info.player_team) do
    if v.base.role_uin == playerId then
      return v.seq_num or 0
    end
  end
  for _, v in ipairs(notify.init_info.enemy_team) do
    if v.base.role_uin == playerId then
      return v.seq_num or 0
    end
  end
  return 0
end

function BattleUtils.GetServerWaitRoundSeqByNotify(player, notify)
  if not notify then
    return BattleUtils.GetServerWaitRoundSeqByPlayer(player)
  end
  local battlerUin = player and player.roleInfo and player.roleInfo.base.role_uin
  local result = 0
  if not battlerUin then
    battlerUin = notify and notify.init_info.battler_uin
    result = BattleUtils.GetSeqByUinFormNotify(battlerUin, notify)
    if 0 == result then
      local playerInfo = _G.DataModelMgr.PlayerDataModel:GetPlayerInfo()
      local briefInfo = playerInfo and playerInfo.brief_info
      battlerUin = briefInfo and briefInfo.uin
      result = BattleUtils.GetSeqByUinFormNotify(battlerUin, notify)
    end
  else
    result = BattleUtils.GetSeqByUinFormNotify(battlerUin, notify)
  end
  if 0 == result then
    result = notify.data_seq_num
  end
  return result
end

function BattleUtils.SafeCallUObject(objectInUE4, funcName, ...)
  if objectInUE4 and UE4.UObject.IsValid(objectInUE4) then
    local func = objectInUE4[funcName]
    if not func then
      Log.Error("BattleUtils:SafeCallUObject funcName is invalid=", funcName)
      return
    end
    local bOK, ret1_or_err, ret2_or_tracestack = tcallForBattle(objectInUE4, objectInUE4[funcName])
    if not bOK then
      Log.Error("BattleUtils:SafeCallUObject funcName=", funcName, " error=", ret1_or_err, " tracestack=", ret2_or_tracestack)
    end
    return ret1_or_err, ret2_or_tracestack
  end
end

function BattleUtils.GetServerWaitRoundSeqByPlayer(player)
  if player and player.roleInfo then
    return player.roleInfo.seq_num or 0
  end
  return 0
end

function BattleUtils.IsBanFantasticSkillInRankPvp(currentTeamType)
  if currentTeamType == _G.Enum.PlayerTeamType.PTT_PVP_BATTLE_4 then
    local playerSettings = _G.NRCModuleManager:DoCmd(_G.SystemSettingModuleCmd.GetPlayerSettings)
    local pvpSetting = playerSettings and playerSettings.pvp
    local openRank = pvpSetting and pvpSetting.open_rank
    local battleType = openRank and Enum.BattleType.BT_PVP_RANK or Enum.BattleType.BT_PVP_SRANDARD
    local battlePvpConf = _G.NRCModuleManager:DoCmd(BattleModuleCmd.GetPvpConfByBattleType, battleType)
    local isOpenCheckConfNum = battlePvpConf and battlePvpConf.pvp_rank_is_open_limit_fantastic or 0
    local isOpenCheck = 1 == isOpenCheckConfNum
    return isOpenCheck
  else
    return false
  end
end

function BattleUtils.EvaluateHpLevel(hpPercent)
  local hpLevelInfo = _G.BattleManager.battleRuntimeData.hpLevelInfo
  local BloodRedPercent = hpLevelInfo and hpLevelInfo.BloodRedPercent or 0
  local BloodYellowPercent = hpLevelInfo and hpLevelInfo.BloodYellowPercent or 0
  if hpPercent <= BloodRedPercent then
    return BattleEnum.HpLevelType.Red
  elseif hpPercent <= BloodYellowPercent then
    return BattleEnum.HpLevelType.Yellow
  else
    return BattleEnum.HpLevelType.Green
  end
end

function BattleUtils.GetSeasonLegendaryID()
  if _G.BattleManager.battleRuntimeData and _G.BattleManager.battleRuntimeData.legendary_battle and 0 ~= _G.BattleManager.battleRuntimeData.legendary_battle.season_battle_id then
    return _G.BattleManager.battleRuntimeData.legendary_battle.season_battle_id
  end
  return nil
end

function BattleUtils.GetLegendaryTicketID()
  if _G.BattleManager.battleRuntimeData and _G.BattleManager.battleRuntimeData.legendary_battle_ticket_id then
    return _G.BattleManager.battleRuntimeData.legendary_battle_ticket_id
  end
  return nil
end

function BattleUtils.GetLegendaryBattleID()
  if _G.BattleManager.battleRuntimeData and _G.BattleManager.battleRuntimeData.legendary_battle and _G.BattleManager.battleRuntimeData.legendary_battle.legendary_battle_id and 0 ~= _G.BattleManager.battleRuntimeData.legendary_battle.legendary_battle_id then
    return _G.BattleManager.battleRuntimeData.legendary_battle.legendary_battle_id
  end
  return nil
end

function BattleUtils.IsTriggerAppearanceInField(AppearanceMode)
  if BattleManager.IsShowAppearanceAtStart ~= nil then
    return BattleManager.IsShowAppearanceAtStart
  end
  local BattleType = _G.BattleManager.battleRuntimeData.battleType
  if AppearanceMode == BattleEnum.CheckAppearanceMode.LimitByBattleMode and not BattleUtils.IsPveType() and BattleType ~= Enum.BattleType.BT_PVP and BattleType ~= Enum.BattleType.BT_PVP_SCARE and BattleType ~= Enum.BattleType.BT_1VN and BattleType ~= Enum.BattleType.BT_1V1V1 and BattleType ~= Enum.BattleType.BT_PVP_RANDOM and BattleType ~= Enum.BattleType.BT_PVP_SRANDARD and BattleType ~= Enum.BattleType.BT_PVP_WATER and BattleType ~= Enum.BattleType.BT_PVP_INSECT and BattleType ~= Enum.BattleType.BT_PVP_RANK and BattleType ~= Enum.BattleType.BT_PVP_THREE and BattleType ~= Enum.BattleType.BT_ASSISTBOSSFIGHT and BattleType ~= Enum.BattleType.BT_PVP_GAME1 and BattleType ~= Enum.BattleType.BT_PVP_GAME2 then
    BattleManager.IsShowAppearanceAtStart = false
    return BattleManager.IsShowAppearanceAtStart
  end
  if BattleUtils.IsPvp() or BattleUtils.IsPveType() or BattleType == Enum.BattleType.BT_ASSISTBOSSFIGHT then
    BattleManager.IsShowAppearanceAtStart = true
    return BattleManager.IsShowAppearanceAtStart
  end
  if BattleUtils.IsBadgeChallenge() then
    BattleManager.IsShowAppearanceAtStart = true
    return BattleManager.IsShowAppearanceAtStart
  end
  local teams = _G.BattleManager.battlePawnManager.AllPlayerTeam
  if teams then
    for _, v in ipairs(teams) do
      if v and v.player:IsTriggerAppearance() then
        BattleManager.IsShowAppearanceAtStart = true
        return BattleManager.IsShowAppearanceAtStart
      end
    end
  end
  teams = _G.BattleManager.battlePawnManager.AllEnemyTeam
  if teams then
    for _, v in ipairs(teams) do
      if v and v.player:IsTriggerAppearance() then
        BattleManager.IsShowAppearanceAtStart = true
        return BattleManager.IsShowAppearanceAtStart
      end
    end
  end
  BattleManager.IsShowAppearanceAtStart = false
  return BattleManager.IsShowAppearanceAtStart
end

function BattleUtils.GetObserveModeFromSystemSettings(playerSettings)
  local pvp = playerSettings and playerSettings.pvp
  local observe_battle = pvp and pvp.observe_battle
  local mode = observe_battle and observe_battle.mode
  return mode
end

function BattleUtils.ModifyAllowObserveInPlayerSettings(prevPlayerSettings, nextAllow)
  local nextAllowFriendWatchBattle = nextAllow
  local nextDeny = not nextAllowFriendWatchBattle
  local prevPvp = prevPlayerSettings and prevPlayerSettings.pvp
  local prevObserveBattle = prevPvp and prevPvp.observe_battle
  local prevDeny = prevObserveBattle and prevObserveBattle.deny
  if prevDeny == nextDeny then
    return prevPlayerSettings
  end
  local nextPlayerSettings = {}
  if prevPlayerSettings then
    table.copy(prevPlayerSettings, nextPlayerSettings)
  end
  local nextPvp = {}
  if prevPvp then
    table.copy(prevPvp, nextPvp)
  end
  local nextObserveBattle = {}
  if prevObserveBattle then
    table.copy(prevObserveBattle, nextObserveBattle)
  end
  nextObserveBattle.deny = nextDeny
  nextPvp.observe_battle = nextObserveBattle
  nextPlayerSettings.pvp = nextPvp
  return nextPlayerSettings
end

function BattleUtils.ModifyObserveModeInPlayerSettings(prevPlayerSettings, nextMode)
  local prevPvp = prevPlayerSettings and prevPlayerSettings.pvp
  local prevObserveBattle = prevPvp and prevPvp.observe_battle
  local prevMode = prevObserveBattle and prevObserveBattle.mode
  if prevMode == nextMode then
    return prevPlayerSettings
  end
  local nextPlayerSettings = {}
  if prevPlayerSettings then
    table.copy(prevPlayerSettings, nextPlayerSettings)
  end
  local nextPvp = {}
  if prevPvp then
    table.copy(prevPvp, nextPvp)
  end
  local nextObserveBattle = {}
  if prevObserveBattle then
    table.copy(prevObserveBattle, nextObserveBattle)
  end
  nextObserveBattle.mode = nextMode
  nextPvp.observe_battle = nextObserveBattle
  nextPlayerSettings.pvp = nextPvp
  return nextPlayerSettings
end

function BattleUtils.IsSkipRecycleBall()
  local battleConf = BattleUtils.GetBattleConfig()
  if battleConf then
    local SpecialConf = _G.DataConfigManager:GetBattleGlobalConfig("no_pet_battle")
    if SpecialConf and SpecialConf.numList and table.contains(SpecialConf.numList, battleConf.id) then
      return true
    end
  end
  return false
end

function BattleUtils.EndBattleByNpc()
  local battleConf = BattleUtils.GetBattleConfig()
  if battleConf then
    return 1 == battleConf.battle_end_no_npc
  end
  return false
end

function BattleUtils.CheckMyPlayerItemRemainCount(ItemId)
  local team = _G.BattleManager.battlePawnManager:GetTeam(BattleEnum.Team.ENUM_TEAM)
  if not team then
    return false
  end
  local player = team.player
  if not player then
    return false
  end
  local item = player:TryGetItem(ItemId)
  if item then
    return item.remain_use_cnt > 0
  end
  return false
end

function BattleUtils.IsDeathExist(card)
  if card and card.isMonster and card.config and card.config.death_exist and card.config.death_exist >= 1 then
    return card.config.death_exist
  end
end

function BattleUtils.IsCurrentBattleCanBeWatch()
  if BattleUtils.IsBadge2DType() then
    return false
  end
  local battleInitInfo = BattleUtils.GetBattleInitInfo()
  local battleConfIdList = battleInitInfo and battleInitInfo.battle_cfg_id or {}
  local battleConfId = battleConfIdList and battleConfIdList[1] or 0
  local canBeWatchBattle = BattleUtils.IsBattleConfigIdCanBeWatch(battleConfId)
  return canBeWatchBattle
end

function BattleUtils.IsBattleConfigIdCanBeWatch(battleConfId)
  local battleConf = _G.DataConfigManager:GetBattleConf(battleConfId, true)
  local battleType = battleConf and battleConf.type
  local battleTypeConf = battleType and _G.DataConfigManager:GetBattleTypeConf(battleType)
  local battleConfigCanNotWatchValue = battleConf and battleConf.cancel_watch
  local battleConfigCanNotWatch = 1 == battleConfigCanNotWatchValue
  local canBeWatchBattle = battleTypeConf and battleTypeConf.is_watch_battle or false
  if battleConfigCanNotWatch then
    canBeWatchBattle = false
  end
  return canBeWatchBattle
end

function BattleUtils.GetTerritoryBattleConf()
  local battleConf = BattleUtils.GetBattleConfig()
  local battleConfId = battleConf and battleConf.id
  local territoryTrialChallengeConfList = _G.DataConfigManager:GetAllByName("TERRITORY_TRIAL_CHALLENGE_CONF")
  territoryTrialChallengeConfList = territoryTrialChallengeConfList or {}
  local targetTerritoryTrialChallengeConf
  for i, territoryTrialChallengeConf in pairs(territoryTrialChallengeConfList) do
    local territoryTrialChallengeConfBattleId = territoryTrialChallengeConf and territoryTrialChallengeConf.battle
    if territoryTrialChallengeConfBattleId == battleConfId then
      targetTerritoryTrialChallengeConf = territoryTrialChallengeConf
      break
    end
  end
  local targetTerritoryTrialConfId = targetTerritoryTrialChallengeConf and targetTerritoryTrialChallengeConf.id
  local territoryTrialConfList = _G.DataConfigManager:GetAllByName("TERRITORY_TRIAL_CONF")
  territoryTrialConfList = territoryTrialConfList or {}
  local targetTerritoryTrialConf
  for i, territoryTrialConf in pairs(territoryTrialConfList) do
    local territoryTrialConfChallengeIdList = territoryTrialConf and territoryTrialConf.challenge_id or {}
    local territoryTrialConfChallengeId = territoryTrialConfChallengeIdList and territoryTrialConfChallengeIdList[1]
    if targetTerritoryTrialConfId == territoryTrialConfChallengeId then
      targetTerritoryTrialConf = territoryTrialConf
      break
    end
  end
  return targetTerritoryTrialConf
end

function BattleUtils.GetCurrentBattleTerritoryHighestScore()
  local targetTerritoryTrialConf = BattleUtils.GetTerritoryBattleConf()
  local targetTerritoryTrialConfChallengeIdList = targetTerritoryTrialConf and targetTerritoryTrialConf.challenge_id or {}
  local targetTerritoryTrialConfChallengeId = targetTerritoryTrialConfChallengeIdList and targetTerritoryTrialConfChallengeIdList[1]
  local TerritoryTrialActivityObjectList = _G.NRCModuleManager:DoCmd(ActivityModuleCmd.GetActivityInstByType, _G.ProtoEnum.ActivityType.ATP_TERRITORY_TRIAL)
  TerritoryTrialActivityObjectList = TerritoryTrialActivityObjectList or {}
  local TerritoryTrialActivityObject
  for i, currentTerritoryTrialActivityObject in ipairs(TerritoryTrialActivityObjectList) do
    local activityData = currentTerritoryTrialActivityObject and currentTerritoryTrialActivityObject:GetActivityData()
    local trialInfo = activityData and activityData.trial_info
    local challengeId = trialInfo and trialInfo.challenge_id
    if challengeId == targetTerritoryTrialConfChallengeId then
      TerritoryTrialActivityObject = currentTerritoryTrialActivityObject
      break
    end
  end
  local activityData = TerritoryTrialActivityObject and TerritoryTrialActivityObject:GetActivityData()
  local trialInfo = activityData and activityData.trial_info
  local highestScore = trialInfo and trialInfo.highest_score or 0
  return highestScore
end

function BattleUtils.IsResonance()
  return BattleUtils.IsPve() and 2 == _G.BattleManager.battleRuntimeData.playerPetNumber and 2 == _G.BattleManager.battleRuntimeData.enemyPetNumber
end

function BattleUtils.IsHighValuePet(pet_info)
  return UIUtils.DoCheckIsHighValuePet(pet_info.battle_common_pet_info.mutation_type)
end

function BattleUtils.IsOwnerPet(pet_info)
  return pet_info.battle_inside_pet_info.owner_uin == _G.DataModelMgr.PlayerDataModel.playerInfo.brief_info.uin
end

function BattleUtils.GetPvpScoreItemInfo(seasonId)
  seasonId = seasonId or _G.NRCModuleManager:DoCmd(_G.PVPRankedMatchModuleCmd.CmdGetCurSeasonId)
  local seasonConf = _G.DataConfigManager:GetPvpRankSeasonConf(seasonId, true)
  local vItemType = seasonConf and seasonConf.vitem or BattleConst.PvpScoreItemType
  local moneyCount = _G.DataModelMgr.PlayerDataModel:GetVItemCount(vItemType) or 0
  return {
    {
      moneyType = vItemType,
      sum = moneyCount,
      IsShowBuyIcon = false
    }
  }
end

function BattleUtils.SetPvpScoreItemIcon(image, seasonId)
  seasonId = seasonId or _G.NRCModuleManager:DoCmd(_G.PVPRankedMatchModuleCmd.CmdGetCurSeasonId)
  local seasonConf = _G.DataConfigManager:GetPvpRankSeasonConf(seasonId, true)
  local moneyType = seasonConf and seasonConf.vitem or BattleConst.PvpScoreItemType
  local iconPath
  if moneyType < 100000 then
    local vItemsConf = _G.DataConfigManager:GetVisualItemConf(moneyType)
    iconPath = vItemsConf and vItemsConf.iconPath
  else
    local bagItemConf = _G.DataConfigManager:GetBagItemConf(moneyType)
    iconPath = bagItemConf and bagItemConf.icon
  end
  if UE.UObject.IsValid(image) and iconPath then
    image:SetPath(iconPath)
  end
end

function BattleUtils.SetPvpScoreIcon(image)
  if image then
    local moneyType = tonumber(BattleConst.PvpScoreCoinType)
    if moneyType < 100000 then
      local vItemsConf = _G.DataConfigManager:GetVisualItemConf(moneyType)
      if vItemsConf then
        image:SetPath(vItemsConf.iconPath)
      end
    else
      local bagItemConf = _G.DataConfigManager:GetBagItemConf(moneyType)
      if bagItemConf then
        image:SetPath(bagItemConf.icon)
      end
    end
  end
end

function BattleUtils.GetCurrentPlayerEnterSate()
  local state = BattleEnum.EnterBattleState.Default
  local localPlayer = _G.NRCModuleManager:DoCmd(PlayerModuleCmd.GET_LOCAL_PLAYER)
  if localPlayer and localPlayer.statusComponent:HasStatus(ProtoEnum.WorldPlayerStatusType.WPST_SWIMMING) then
    state = state | BattleEnum.EnterBattleState.InSwim
  end
  if BattleUtils.CheckPlayerEnterBattleInSky() then
    state = state | BattleEnum.EnterBattleState.InSky
  end
  return state
end

function BattleUtils.RecoveryRideStatus(ridePetGid)
  if ridePetGid > 0 then
    local localPlayer = BattleUtils.GetPlayer()
    if localPlayer then
      local ridePet = localPlayer:GetPetByGid(ridePetGid)
      local WithPartner = (localPlayer:IsLogicStatus(_G.Enum.SpaceActorLogicStatus.SALS_HOLD_HANDS_LEADER) or localPlayer:IsLogicStatus(_G.Enum.SpaceActorLogicStatus.SALS_HOLD_HANDS_GUEST)) and 1 or 0
      local WithPet = localPlayer.statusComponent:HasStatus(Enum.WorldPlayerStatusType.WPST_RIDEALL) and 1 or 0
      local WaitOther, variant, extraData = localPlayer.LogicStatusComponent:GetStatus(ProtoEnum.SpaceActorLogicStatus.SALS_WAIT_FOR_OTHERS) and 1 or 0
      if ridePet and 0 == WithPartner and 0 == WithPet and 0 == WaitOther then
        local helper = AbilityHelperManager.GetHelper(AbilityID.RIDE_ALL)
        if helper then
          helper:HandleStatus(localPlayer, ridePet)
        end
      end
    end
  end
end

function BattleUtils.GetLocalDebugTime()
  local time = os.date("%Y-%m-%d %H:%M:%S")
  return time
end

function BattleUtils.ForceUpdateIndexMap()
  local Instance = UE.UNRCPlatformGameInstance.GetInstance()
  local IndexMapSys = Instance and Instance:GetIndexMapStreamingSystem()
  if IndexMapSys then
    IndexMapSys:ForceDoUpdate(Instance:GetWorld())
  end
end

function BattleUtils.HideAllPlayerChatBubbles()
  local players = BattleManager.battlePawnManager:GetAllPlayers()
  for i, player in pairs(players) do
    if player.model then
      _G.NRCModuleManager:DoCmd(_G.FriendModuleCmd.OnCmdSwitchChatBubbles, player.model, false)
    end
  end
end

function BattleUtils.FixClickByVolatileOnPC(InWidget)
  if RocoEnv.PLATFORM ~= "PLATFORM_WINDOWS" then
    return
  end
  if InWidget.bIsVolatile then
    return
  end
  InWidget:ForceVolatile(true)
end

function BattleUtils.DirectUpdateUI(ignoreOptions)
  if BattleManager:IsInBattle(true) then
    BattleManager.bDirectUpdateUI = true
    if ignoreOptions then
      if not BattleManager.directUpdateUIIgnoreOptions then
        BattleManager.directUpdateUIIgnoreOptions = {}
      end
      local opts = BattleManager.directUpdateUIIgnoreOptions
      if ignoreOptions.ignoreHp then
        if not opts.ignoreHp then
          opts.ignoreHp = {}
        end
        for _, petId in ipairs(ignoreOptions.ignoreHp) do
          opts.ignoreHp[petId] = true
        end
      end
    end
  end
end

function BattleUtils.GetFantasticBackgroundPathWithPetAndSkill(petId, skillId)
  local battleManager = _G.BattleManager
  local battlePawnManager = battleManager and battleManager.battlePawnManager
  local card = battlePawnManager and battlePawnManager:GetCardByGuid(petId)
  local skillRoundDataList = card and card.skillRoundData or {}
  local skillRoundData
  local checkSkillId = _G.SkillUtils.CheckSkillId(skillId)
  for i, skillRoundDataItem in ipairs(skillRoundDataList) do
    local skillRoundDataItemId = skillRoundDataItem and skillRoundDataItem.skill_id
    if skillRoundDataItemId and skillRoundDataItemId == checkSkillId then
      skillRoundData = skillRoundDataItem
    end
  end
  local seasonId = skillRoundData and skillRoundData.season_id
  local checkedSkillId = skillRoundData and skillRoundData.skill_id
  return BattleUtils.GetFantasticBackgroundPathWithSkillAndSeason(checkedSkillId, seasonId)
end

function BattleUtils.GetFantasticBackgroundPathWithSkillAndSeason(skillId, seasonId)
  local battleManager = _G.BattleManager
  local runtimeData = battleManager and battleManager.battleRuntimeData
  local fantasticBackgroundPathsDefault = runtimeData and runtimeData.fantasticBackgroundPathsDefault
  local NRCModuleManager = _G.NRCModuleManager
  local battleUiModule = NRCModuleManager and NRCModuleManager:GetModule("BattleUIModule")
  local battleUiModuleData = battleUiModule and battleUiModule.data
  local fantasticBackgroundPathOverride = battleUiModuleData and battleUiModuleData.__fantasticBackgroundPathOverride
  local overridePaths
  if fantasticBackgroundPathOverride then
    overridePaths = BattleConst.FantasticBackgroundPathsDefaults[fantasticBackgroundPathOverride]
    if not overridePaths then
      seasonId = fantasticBackgroundPathOverride
    end
  end
  if overridePaths then
    fantasticBackgroundPathsDefault = overridePaths
  end
  local squareNm3 = fantasticBackgroundPathsDefault and fantasticBackgroundPathsDefault.squareNm3
  local stripNm3 = fantasticBackgroundPathsDefault and fantasticBackgroundPathsDefault.stripNm3
  local cloudNm3 = fantasticBackgroundPathsDefault and fantasticBackgroundPathsDefault.cloudNm3
  local cloudNm5 = fantasticBackgroundPathsDefault and fantasticBackgroundPathsDefault.cloudNm5
  local cloudNor4 = fantasticBackgroundPathsDefault and fantasticBackgroundPathsDefault.cloudNor4
  local cloudNor5 = fantasticBackgroundPathsDefault and fantasticBackgroundPathsDefault.cloudNor5
  local dataAssetPath = fantasticBackgroundPathsDefault and fantasticBackgroundPathsDefault.dataAssetPath
  local seasonConf = _G.DataConfigManager:GetSeasonConf(seasonId, true)
  local season_skill_ui = seasonConf and seasonConf.season_skill_ui
  if season_skill_ui and not overridePaths then
    dataAssetPath = season_skill_ui
  end
  local NRCBigWorldPreloader = _G.NRCBigWorldPreloader
  local dataAsset = NRCBigWorldPreloader and NRCBigWorldPreloader:Get(dataAssetPath)
  if UE.UObject.IsValid(dataAsset) then
    local ui_item_nm_3 = dataAsset and dataAsset.ui_item_nm_3
    squareNm3 = ui_item_nm_3 and ui_item_nm_3.AssetPathName or squareNm3
    local ui_popup_nm_3 = dataAsset and dataAsset.ui_popup_nm_3
    stripNm3 = ui_popup_nm_3 and ui_popup_nm_3.AssetPathName or stripNm3
    local ui_equipment_nm_3 = dataAsset and dataAsset.ui_equipment_nm_3
    cloudNm3 = ui_equipment_nm_3 and ui_equipment_nm_3.AssetPathName or cloudNm3
    local ui_equipment_nm_5 = dataAsset and dataAsset.ui_equipment_nm_5
    cloudNm5 = ui_equipment_nm_5 and ui_equipment_nm_5.AssetPathName or cloudNm5
    local ui_equipment_nor_4 = dataAsset and dataAsset.ui_equipment_nor_4
    cloudNor4 = ui_equipment_nor_4 and ui_equipment_nor_4.AssetPathName or cloudNor4
    local ui_equipment_nor_5 = dataAsset and dataAsset.ui_equipment_nor_5
    cloudNor5 = ui_equipment_nor_5 and ui_equipment_nor_5.AssetPathName or cloudNor5
  end
  local paths = {
    squareNm3 = squareNm3,
    stripNm3 = stripNm3,
    cloudNm3 = cloudNm3,
    cloudNm5 = cloudNm5,
    cloudNor4 = cloudNor4,
    cloudNor5 = cloudNor5
  }
  return paths
end

BattleUtils.DialogueTransformCache = nil

function BattleUtils.CacheBeforeDialogue()
  local battleManager = _G.BattleManager
  if not battleManager or not battleManager:IsInBattle() then
    return
  end
  local battlePawnManager = battleManager.battlePawnManager
  if not battlePawnManager then
    return
  end
  BattleUtils.DialogueTransformCache = {
    pets = {},
    players = {}
  }
  local allPets = battlePawnManager:GetAllPets()
  for _, pet in ipairs(allPets) do
    if pet and pet.model then
      local petCache = {
        id = pet.id,
        transform = pet.model:Abs_GetTransform()
      }
      BattleUtils.DialogueTransformCache.pets[pet.guid] = petCache
    end
  end
  local teamPlayer = battlePawnManager:GetPlayerMyTeam()
  local enemyPlayer = battlePawnManager:GetPlayerEnemyTeam()
  local players = {teamPlayer, enemyPlayer}
  for _, player in ipairs(players) do
    if player and player.model then
      local playerCache = {
        id = player.id,
        transform = player.model:Abs_GetTransform()
      }
      BattleUtils.DialogueTransformCache.players[player.guid] = playerCache
    end
  end
  BattleLog.Debug(BattleLog.LogType.Player, "BattleUtils.CacheBeforeDialogue: \229\183\178\231\188\147\229\173\152\229\175\185\232\175\157\229\137\141\229\156\186\228\184\138\231\178\190\231\129\181\229\146\140\232\167\146\232\137\178\231\154\132Transform\228\191\161\230\129\175")
end

function BattleUtils.ResetFromDialogue(shouldRestartBuff)
  local battleManager = _G.BattleManager
  if not battleManager or not battleManager:IsInBattle() then
    return
  end
  local battlePawnManager = battleManager.battlePawnManager
  if not battlePawnManager then
    return
  end
  if not BattleUtils.DialogueTransformCache then
    BattleLog.Debug(BattleLog.LogType.Player, "BattleUtils.ResetFromDialogue: \230\178\161\230\156\137\230\137\190\229\136\176\231\188\147\229\173\152\239\188\140\232\183\179\232\191\135\232\191\152\229\142\159")
    return
  end
  if BattleUtils.DialogueTransformCache.pets then
    for petId, petCache in pairs(BattleUtils.DialogueTransformCache.pets) do
      local pet = battlePawnManager:GetPetByGuid(petId)
      if pet and pet.model then
        if petCache.transform then
          pet.model:Abs_K2_SetActorTransform(petCache.transform, false, nil, false)
        end
        pet.model:SetHiddenMask(false, UE4.EPlayerForceHiddenType.Dialogue)
        pet:ResetLookAt()
      end
    end
  end
  if BattleUtils.DialogueTransformCache.players then
    for playerId, playerCache in pairs(BattleUtils.DialogueTransformCache.players) do
      local player = battlePawnManager:GetPlayerByGuid(playerId)
      if player and player.model then
        if playerCache.transform then
          player.model:Abs_K2_SetActorTransform(playerCache.transform, false, nil, false)
        end
        player.model:SetHiddenMask(false, UE4.EPlayerForceHiddenType.Dialogue)
        local DialogueUtils = require("NewRoco.Modules.System.Dialogue.DialogueUtils")
        DialogueUtils.StopLookAt(player)
        DialogueUtils.StopTurn(player)
      end
    end
  end
  BattleUtils.DialogueTransformCache = nil
  if shouldRestartBuff then
    local allPets = battlePawnManager:GetAllPets()
    BattleUtils:RestartBattleState(allPets)
  end
  BattleLog.Debug(BattleLog.LogType.Player, "BattleUtils.ResetFromDialogue: \230\136\152\230\150\151\229\175\185\232\175\157\231\187\147\230\157\159\239\188\140\229\183\178\228\187\142\231\188\147\229\173\152\232\191\152\229\142\159\231\178\190\231\129\181\229\146\140\232\167\146\232\137\178Transform\228\191\161\230\129\175")
end

function BattleUtils.ClearDialogueTransformCache()
  BattleUtils.DialogueTransformCache = nil
end

function BattleUtils.NeedOpenA1BattleTutorial()
  if not BattleUtils.IsFinalBattle() then
    return false
  end
  local roundIndex = _G.BattleManager.battleRuntimeData.roundIndex or 0
  if 2 ~= roundIndex then
    return false
  end
  local team = _G.BattleManager.battlePawnManager:GetTeam(BattleEnum.Team.ENUM_TEAM)
  local player = team and team.player
  local itemData = player and player.itemInfo or {}
  for _, item in ipairs(itemData) do
    if item.item_type == ProtoEnum.BagItemType.BI_PLAYERSKILL then
      local chargeOk = not item.is_charge or not ((item.remain_use_cnt or 0) <= 0)
      local battleRemainOk = (item.battle_use_time_remain or 0) > 0
      if chargeOk and battleRemainOk then
        return true
      end
    end
  end
  return false
end

function BattleUtils.AppendIdToLocalDebugFile(id)
  if nil == id then
    Log.Error("AppendIdToLocalFile id is nil")
    return false
  end
  local FilePath = UE.UBlueprintPathsLibrary.Combine({
    UE.UBlueprintPathsLibrary.ProjectSavedDir(),
    "TimeLineDebug.txt"
  })
  local idStr = tostring(id)
  local ReadFile = io.open(FilePath, "r")
  if ReadFile then
    for line in ReadFile:lines() do
      local trimmed = line:gsub("^%s+", ""):gsub("%s+$", "")
      if trimmed == idStr then
        ReadFile:close()
        return true
      end
    end
    ReadFile:close()
  end
  local File = io.open(FilePath, "a")
  if not File then
    Log.Error("AppendIdToLocalFile open file failed, path = " .. tostring(FilePath))
    return false
  end
  File:write(idStr .. "\n")
  File:close()
  return true
end

function BattleUtils.ImmediateChangeWeatherForBattle(weatherId)
  _G.NRCModuleManager:DoCmd(_G.EnvSystemModuleCmd.LockWeather, weatherId, LockWeatherReason.Battle, true)
end

function BattleUtils.IsBattleFsmInSelectOp(fsm)
  fsm = fsm or _G.BattleManager.stateFsm
  local fsmState = fsm and fsm:GetActiveStateName()
  return fsmState == BattleEnum.StateNames.SwapSelect or fsmState == BattleEnum.StateNames.RoundSelect or fsmState == BattleEnum.StateNames.SelectRidPet
end

function BattleUtils.GetActionFKey(actionName)
  local keyName = _G.NRCModuleManager:DoCmd(_G.EnhancedInputModuleCmd.GetMappingKey, actionName)
  if not keyName or "" == keyName then
    return nil
  end
  return UE.EKeys[keyName]
end

function BattleUtils.IsFKeyDown(Key)
  if not Key then
    return false
  end
  local pc = UE.UGameplayStatics.GetPlayerController(_G.UE4Helper.GetCurrentWorld(), 0)
  return pc and pc:IsInputKeyDown(Key) or false
end

function BattleUtils.IsActionKeyDown(actionName)
  local key = BattleUtils.GetActionFKey(actionName)
  return BattleUtils.IsFKeyDown(key)
end

function BattleUtils.SetCustomDepth(Actor, Depth)
  if not UE4.UObject.IsValid(Actor) then
    return
  end
  local Comps = Actor:K2_GetComponentsByClass(UE.UMeshComponent)
  for _, Comp in tpairs(Comps) do
    if not Comp:IsA(UE.UWidgetComponent) then
      BattleUtils.SetCompCustomDepth(Comp, Depth)
    end
  end
  local ChildActorComps = Actor:K2_GetComponentsByClass(UE.UChildActorComponent)
  for _, Comp in tpairs(ChildActorComps) do
    if Comp:IsA(UE.UChildActorComponent) then
      local childActor = Comp:GetChildActor()
      if UE4.UObject.IsValid(childActor) then
        BattleUtils.SetCustomDepth(childActor, Depth)
      end
    end
  end
end

function BattleUtils.SetCompCustomDepth(Comp, Depth)
  if not Comp or not UE.UObject.IsValid(Comp) then
    return
  end
  if nil == Depth then
    Comp:SetRenderCustomDepth(false)
    Comp:SetCustomDepthStencilValue(0)
  else
    Comp:SetRenderCustomDepth(true)
    Comp:SetCustomDepthStencilValue(Depth)
    Log.Debug("[BattleUtils] SetCompCustomDepth", Depth)
  end
end

local StaticMeshBoundVecCacheMin = UE.FVector()
local StaticMeshBoundVecCacheMax = UE.FVector()

function BattleUtils.GetStaticMeshComponentRadius(staticMeshComponent)
  local radius = 50
  if UE.UObject.IsValid(staticMeshComponent) then
    staticMeshComponent:GetLocalBounds(StaticMeshBoundVecCacheMin, StaticMeshBoundVecCacheMax)
    local dx = StaticMeshBoundVecCacheMax.X - StaticMeshBoundVecCacheMin.X
    local dy = StaticMeshBoundVecCacheMax.Y - StaticMeshBoundVecCacheMin.Y
    radius = math.sqrt(dx * dx + dy * dy) * 0.5
  end
  return radius
end

function BattleUtils.GetStaticMeshComponentHalfHeight(staticMeshComponent)
  local halfHeight = 50
  if UE.UObject.IsValid(staticMeshComponent) then
    staticMeshComponent:GetLocalBounds(StaticMeshBoundVecCacheMin, StaticMeshBoundVecCacheMax)
    halfHeight = math.abs(StaticMeshBoundVecCacheMax.Z - StaticMeshBoundVecCacheMin.Z) * 0.5
  end
  return halfHeight
end

function BattleUtils.FindPlayerInfoByPetId(petId)
  if not petId then
    return nil
  end
  local runtimeData = _G.BattleManager and _G.BattleManager.battleRuntimeData
  local startParam = runtimeData and runtimeData.battleStartParam
  local initInfo = startParam and startParam.battleInitInfo
  local createUin = initInfo and initInfo.battler_uin
  if not initInfo then
    return nil
  end
  
  local function findInTeam(team, teamEnum)
    if not team then
      return nil
    end
    for _, roleInfo in ipairs(team) do
      for _, petInfo in ipairs(roleInfo.pets or {}) do
        if petInfo.battle_inside_pet_info and petInfo.battle_inside_pet_info.pet_id == petId then
          return roleInfo
        end
      end
    end
  end
  
  local ret = findInTeam(initInfo.player_team, BattleEnum.Team.ENUM_TEAM) or findInTeam(initInfo.enemy_team, BattleEnum.Team.ENUM_ENEMY)
  if ret then
    local selfUin = ret.base and ret.base.role_uin
    if selfUin then
      return ret, selfUin == createUin
    else
      return ret, false
    end
  end
end

function BattleUtils.GetBattleCenterInfoByTag(tag)
  local BattleCenterTable = UE4.UGameplayStatics.GetAllActorsOfClassWithTag(_G.UE4Helper.GetCurrentWorld(), UE4.AActor, tag):ToTable()
  if BattleCenterTable and #BattleCenterTable > 0 then
    if #BattleCenterTable > 1 then
      Log.Error("ZGX \230\136\152\229\156\186\228\188\160\233\128\129\228\184\173\230\137\190\229\136\176\229\164\154\228\184\170LevelBattleCenter\239\188\129\239\188\129\239\188\129 \232\175\183\230\163\128\230\159\165\233\133\141\231\189\174\231\154\132\233\128\137\231\130\185\230\152\175\229\144\166\230\173\163\231\161\174!!!")
    end
    local BattleCenter = BattleCenterTable[1]
    local centerPos = BattleCenter:Abs_K2_GetActorLocation()
    _G.BattleManager.battleRuntimeData.TeleportBattleCenter = centerPos
    _G.BattleManager.battleRuntimeData.ServerBattleRotate = BattleCenter:K2_GetActorRotation().Yaw
    _G.BattleManager.battleRuntimeData.teamBattleCenterTrans = BattleCenter:Abs_GetTransform()
    return true
  end
  return false
end

function BattleUtils.GetMimicBaseIdFromPetInfo(insidePetInfo)
  local buffs = insidePetInfo and insidePetInfo.buffs or DummyTable
  local petBaseConfId
  for _, buff in ipairs(buffs) do
    local buffId = buff and buff.buff_id
    local buffConf = _G.DataConfigManager:GetBuffConf(buffId)
    local buffGroupSigns = buffConf and buffConf.buff_groupsigns or DummyTable
    local buffStack = buff and buff.stack or 0
    local buffData = buff and buff.buff_data
    for _, sign in ipairs(buffGroupSigns) do
      if sign == ProtoEnum.BuffGroupSign.BGS_BATTLE_MIMIC and buffStack > 0 then
        local mimicPetId = buffData and buffData[1]
        local petConf = mimicPetId and _G.DataConfigManager:GetPetConf(mimicPetId, true)
        if petConf then
          petBaseConfId = petConf and petConf.base_id
          break
        end
      end
    end
  end
  return petBaseConfId
end

function BattleUtils.GetPetBaseIdWithMimic(player, petInfo)
  local petBaseConf = BattleUtils.GetPetBaseConfWithMimic(player, petInfo)
  return petBaseConf and petBaseConf.id
end

function BattleUtils.GetPetBaseConfWithMimic(player, petInfo)
  local insidePetInfo = petInfo and petInfo.battle_inside_pet_info
  local isMimic, MimicType = PetUtils.DoCheckIsMimic(insidePetInfo)
  local baseConfId = insidePetInfo and insidePetInfo.base_conf_id
  local petBaseConf = _G.DataConfigManager:GetPetbaseConf(baseConfId)
  if isMimic and MimicType == ProtoEnum.BuffGroupSign.BGS_BATTLE_MIMIC then
    local teamEnm = player and player.teamEnm
    local isTeam = teamEnm == BattleEnum.Team.ENUM_TEAM
    local isMyself = player and player:IsMyself()
    if isTeam and isMyself then
      local mimicBaseId = BattleUtils.GetMimicBaseIdFromPetInfo(insidePetInfo)
      petBaseConf = mimicBaseId and _G.DataConfigManager:GetPetbaseConf(mimicBaseId, true)
    end
  end
  return petBaseConf
end

function BattleUtils.ResolveAppearanceData(player, petInfo)
  local defaultHuanChong = BattleConst.HuanChong
  local defaultEnemyZhaoHuan = BattleConst.EnemyZhaoHuan
  local defaultEnemyHuanChong = BattleConst.EnemyHuanChong
  local defaultPVPOver = BattleConst.PVPOver
  local defaultWeeklyChallengeOver = BattleConst.LeaderChallengeWinOver
  if player then
    local roleInfo = player.roleInfo
    local roleBase = roleInfo and roleInfo.base
    local stateBit = roleBase and roleBase.state_bit
    if roleInfo and not BattleUtils.IsPlayerUseHumanResByBit(stateBit) then
      defaultHuanChong = BattleConst.NPCHuanChong
    end
  end
  local fashionData = player and player.FashionData
  local suitConf = fashionData and fashionData.suitConf
  local insidePetInfo = petInfo and petInfo.battle_inside_pet_info
  local isMimic, MimicType = PetUtils.DoCheckIsMimic(insidePetInfo)
  local isMimicState = isMimic and MimicType == ProtoEnum.BuffGroupSign.BGS_BATTLE_MIMIC
  local petBaseConfId = insidePetInfo and insidePetInfo.base_conf_id
  local petBaseConf = _G.DataConfigManager:GetPetbaseConf(petBaseConfId)
  local teamEnm = player and player.teamEnm
  local isTeam = teamEnm == BattleEnum.Team.ENUM_TEAM
  local suitPerformConf
  if suitConf then
    suitPerformConf = BattleUtils.GetFashionPerformBySuitConf(suitConf, petBaseConfId)
  end
  local bondConfs = fashionData and fashionData.bondConfs or {}
  local ssBondConf, ssSetting, matchedSSBondInfo, asBondConf, asPerformConf, asSetting
  local matchBondList = BattleUtils.GetBondMatchInfoWithBondDataAndBattlePetInfo(bondConfs, petInfo)
  for _, v in ipairs(matchBondList) do
    local bondConf = v and v.bondConf
    local bondPerformId = bondConf and bondConf.perform_id
    local quality = v and v.quality
    local setting = v and v.setting
    if quality == _G.Enum.FashionBondQuality.FBQ_SS then
      matchedSSBondInfo = {}
      matchedSSBondInfo.matchedSSBondConf = bondConf
      matchedSSBondInfo.matchedSSBondSetting = setting
      local bondCalloutSkill = bondConf and bondConf.bond_callout_skill or 0
      local bondCalloutSkillPath = BattleUtils.GetSkillPathByResId(bondCalloutSkill)
      if bondCalloutSkillPath then
        ssSetting = setting
        ssBondConf = bondConf
      end
    else
      local fashionPerformConf = BattleUtils.GetFashionPerformById(bondPerformId, petBaseConfId)
      if fashionPerformConf then
        asPerformConf = fashionPerformConf
        asSetting = setting
        asBondConf = bondConf
      end
    end
  end
  local suitHuanChong, suitHuanchongSuiId, suitPvpOver, suitPVPOverSuiId
  suitHuanChong, suitHuanchongSuiId, suitPvpOver, suitPVPOverSuiId = BattleUtils.GetFashionPerformInfoByPerformConfAndPetBaseConf(suitPerformConf, petBaseConf)
  local asPerformSuitHuanChong, asPerformSuitHuanchongSuiId
  local asPerformHuanchongBondId = asBondConf and asBondConf.id
  local asPerformSuitPvpOver, asPerformSuitPVPOverSuiId
  local asPerformPVPOverBondId = asBondConf and asBondConf.id
  asPerformSuitHuanChong, asPerformSuitHuanchongSuiId, asPerformSuitPvpOver, asPerformSuitPVPOverSuiId = BattleUtils.GetFashionPerformInfoByPerformConfAndPetBaseConf(asPerformConf, petBaseConf)
  local as_change_action_in_battle = asSetting and asSetting.change_action_in_battle
  if nil == as_change_action_in_battle then
    as_change_action_in_battle = true
  end
  if not as_change_action_in_battle then
    asPerformSuitHuanChong = nil
    asPerformSuitHuanchongSuiId = nil
    asPerformHuanchongBondId = nil
  end
  local as_change_action_win_battle = asSetting and asSetting.change_action_win_battle
  if nil == as_change_action_win_battle then
    as_change_action_win_battle = true
  end
  if not as_change_action_win_battle then
    asPerformSuitPvpOver = nil
    asPerformSuitPVPOverSuiId = nil
    asPerformPVPOverBondId = nil
  end
  local bond_callout_skill = ssBondConf and ssBondConf.bond_callout_skill
  local ssPerformHuanChong = BattleUtils.GetSkillPathByResId(bond_callout_skill)
  local ssPerformHuanchongBondId = ssBondConf and ssBondConf.id
  local ss_change_action_in_battle = ssSetting and ssSetting.change_action_in_battle
  if nil == ss_change_action_in_battle then
    ss_change_action_in_battle = true
  end
  if not ss_change_action_in_battle then
    ssPerformHuanChong = nil
    ssPerformHuanchongBondId = nil
  end
  local ssIsPriority = ssSetting and ssSetting.is_priority
  local bondPerformSuitHuanChong, bondPerformSuitHuanchongSuiId, bondPerformSuitHuanchongBondId, bondPerformSuitPvpOver, bondPerformSuitPVPOverSuiId, bondPerformSuitPVPOverBondId
  bondPerformSuitHuanChong = asPerformSuitHuanChong or ssPerformHuanChong
  bondPerformSuitHuanchongBondId = asPerformHuanchongBondId or ssPerformHuanchongBondId
  bondPerformSuitHuanchongSuiId = asPerformSuitHuanchongSuiId
  if ssIsPriority and ssPerformHuanChong then
    bondPerformSuitHuanChong = ssPerformHuanChong
    bondPerformSuitHuanchongBondId = ssPerformHuanchongBondId
    bondPerformSuitHuanchongSuiId = nil
  end
  bondPerformSuitPvpOver = asPerformSuitPvpOver
  bondPerformSuitPVPOverBondId = asPerformPVPOverBondId
  bondPerformSuitPVPOverSuiId = asPerformSuitPVPOverSuiId
  local HuanChong, EnemyZhaoHuan, EnemyHuanChong, HuanchongSuiId, HuanchongBondId, PVPOver, PVPOverSuiId, PVPOverBondId, WeeklyChallengeOver
  if suitHuanChong then
    HuanChong = suitHuanChong
    EnemyZhaoHuan = suitHuanChong
    EnemyHuanChong = suitHuanChong
    HuanchongSuiId = suitHuanchongSuiId
  elseif bondPerformSuitHuanChong then
    HuanChong = bondPerformSuitHuanChong
    EnemyZhaoHuan = bondPerformSuitHuanChong
    EnemyHuanChong = bondPerformSuitHuanChong
    HuanchongSuiId = bondPerformSuitHuanchongSuiId
    HuanchongBondId = bondPerformSuitHuanchongBondId
  end
  HuanChong = HuanChong or defaultHuanChong
  EnemyZhaoHuan = EnemyZhaoHuan or defaultEnemyZhaoHuan
  EnemyHuanChong = EnemyHuanChong or defaultEnemyHuanChong
  HuanchongSuiId = HuanchongSuiId or -1
  HuanchongBondId = HuanchongBondId or -1
  if isMimicState and not isTeam then
    HuanChong = defaultHuanChong
    EnemyZhaoHuan = defaultEnemyZhaoHuan
    EnemyHuanChong = defaultEnemyHuanChong
    HuanchongSuiId = -1
    HuanchongBondId = -1
  end
  if suitPvpOver then
    PVPOver = suitPvpOver
    PVPOverSuiId = suitPVPOverSuiId
    WeeklyChallengeOver = suitPvpOver
  elseif bondPerformSuitPvpOver then
    PVPOver = bondPerformSuitPvpOver
    PVPOverSuiId = bondPerformSuitPVPOverSuiId
    WeeklyChallengeOver = bondPerformSuitPvpOver
    PVPOverBondId = bondPerformSuitPVPOverBondId
  end
  PVPOver = PVPOver or defaultPVPOver
  WeeklyChallengeOver = WeeklyChallengeOver or defaultWeeklyChallengeOver
  PVPOverSuiId = PVPOverSuiId or -1
  PVPOverBondId = PVPOverBondId or -1
  return {
    HuanChong = HuanChong,
    EnemyZhaoHuan = EnemyZhaoHuan,
    EnemyHuanChong = EnemyHuanChong,
    HuanchongSuiId = HuanchongSuiId,
    HuanchongBondId = HuanchongBondId,
    PVPOver = PVPOver,
    PVPOverSuiId = PVPOverSuiId,
    PVPOverBondId = PVPOverBondId,
    WeeklyChallengeOver = WeeklyChallengeOver,
    matchedSSBondInfo = matchedSSBondInfo
  }
end

function BattleUtils.GetHuanChongPath(player, petInfo, ignoreSuit)
  local data = BattleUtils.ResolveAppearanceData(player, petInfo)
  return BattleUtils.RouteHuanChongPath(player, data, ignoreSuit)
end

function BattleUtils.RouteHuanChongPath(player, data, ignoreSuit)
  local skillPath
  local teamEnm = player and player.teamEnm
  if teamEnm == BattleEnum.Team.ENUM_TEAM then
    if ignoreSuit then
      local defaultHuanChong = BattleConst.HuanChong
      local roleInfo = player and player.roleInfo
      local roleBase = roleInfo and roleInfo.base
      local stateBit = roleBase and roleBase.state_bit
      if roleInfo and not BattleUtils.IsPlayerUseHumanResByBit(stateBit) then
        defaultHuanChong = BattleConst.NPCHuanChong
      end
      skillPath = defaultHuanChong
    else
      skillPath = data and data.HuanChong
    end
  elseif ignoreSuit then
    skillPath = BattleConst.EnemyHuanChong
  else
    skillPath = data and data.EnemyHuanChong
  end
  if BattleUtils.IsTeam() then
    local BattleManager = _G.BattleManager
    local battlePawnManager = BattleManager and BattleManager.battlePawnManager
    local teamMatePlayer = battlePawnManager and battlePawnManager.TeamatePlayer
    local teamMatePlayerGuid = teamMatePlayer and teamMatePlayer.guid
    local playerGuid = player and player.guid
    if playerGuid and playerGuid ~= teamMatePlayerGuid then
      skillPath = BattleConst.TeamNpcHuanChong
    end
  end
  return skillPath
end

function BattleUtils.CheckIsBattleAgain(notify)
  local oldBattleConf = BattleUtils.GetBattleConfig()
  local oldBattleId = oldBattleConf and oldBattleConf.id
  local newBattleId = notify and notify.init_info.battle_cfg_id and notify.init_info.battle_cfg_id[1]
  if oldBattleId == newBattleId and not notify.is_reconnect then
    return true
  end
  return false
end

return BattleUtils
