local BattlePerformEvent = require("NewRoco.Modules.Core.Battle.BattleCore.BattlePerformEvent")
local BattleEvent = require("NewRoco.Modules.Core.Battle.Common.BattleEvent")
local BattleObject = require("NewRoco.Modules.Core.Battle.Entity.BattleObject")
local HealthComponent = require("NewRoco.Modules.Core.Battle.Entity.Components.HP.HealthComponent")
local SkillComponent = require("NewRoco.Modules.Core.Battle.Entity.Components.Skill.SkillComponent")
local BuffComponent = require("NewRoco.Modules.Core.Battle.Entity.Components.Buff.BuffComponent")
local BuffAEffectPopupComponent = require("NewRoco.Modules.Core.Battle.Entity.Components.BuffEffectPopup.BuffAEffectPopupComponent")
local SeasonComponent = require("NewRoco.Modules.Core.Battle.Entity.Components.Season.SeasonComponent")
local HeadLookAtComponent = require("NewRoco.Modules.Core.Scene.Component.HeadLookAt.HeadLookAtComponent")
local TurnComponent = require("NewRoco.Modules.Core.Scene.Component.Movement.TurnComponent")
local ProtoEnum = require("Data.PB.ProtoEnum")
local BattleUtils = require("NewRoco.Modules.Core.Battle.Common.BattleUtils")
local SkillPlayer = require("NewRoco.Modules.Core.Battle.Common.SkillPlayer")
local BattleConst = require("NewRoco.Modules.Core.Battle.Common.BattleConst")
local BattleEnum = require("NewRoco.Modules.Core.Battle.Common.BattleEnum")
local PetUtils = require("NewRoco.Utils.PetUtils")
local SceneUtils = require("NewRoco.Modules.Core.Scene.Common.SceneUtils")
local BuffUtils = require("NewRoco.Modules.Core.Battle.Entity.Components.Buff.BuffUtils")
local BattlePetPerception = require("NewRoco.Modules.Core.Battle.Entity.Card.BattlePetPerception")
local LineTraceUtils = require("NewRoco.Modules.Core.Battle.Common.LineTraceUtils")
local BattleCraneCameraEvent = require("NewRoco.Modules.Core.Battle.CraneCamera.BattleCraneCameraEvent")
local PetMutationUtils = require("NewRoco.Utils.PetMutationUtils")
local Enum = require("Data.Config.Enum")
local Base = BattleObject
local BattleManager, PawnManager
local BattlePet = BattleObject:Extend("BattlePet")
local AfterAttackShowCmd = {}
AfterAttackShowCmd.ENUM_TYPE = {ChangePet = 0, Escape = 1}

function BattlePet:Ctor()
  Base.Ctor(self)
  BattleManager = _G.BattleManager
  PawnManager = _G.BattleManager.battlePawnManager
  self.perception = BattlePetPerception(self)
  self.health = self:AddComponent(HealthComponent(self))
  self.skillComponent = self:AddComponent(SkillComponent(self))
  self.buffComponent = self:AddComponent(BuffComponent(self))
  self.buffAEffectPopupComponent = self:AddComponent(BuffAEffectPopupComponent(self))
  self.seasonComponent = self:AddComponent(SeasonComponent(self))
  self.TurnComponent = self:AddComponent(TurnComponent(self))
  self.clickable = false
  self.MovementMode = 2
  self.isAnimable = true
  self.card = nil
  self.attackPlayers = {}
  self.buffPlayers = {}
  self.model = nil
  self.IsClickPetFrame = true
  self.IsHeadBack = false
  self.CanCatchAtTeamFight = false
  self.IsPerformBeDefeated = false
  self.IsPerformSpColor = false
  self.battlePetComponents = nil
  self.buffPos = UE4.FVector(0, 0, 0)
  self.isNeedLoad = true
  self.HasShieldThisAttack = false
  self.RandomMoveDetal = -1
  self.IsCanSwimming = false
  self.IsCanFly = false
  self.PlatFormActor = nil
  self.predictionHistoryInfos = {}
  self.UpdateFloorTimer = 0
  self.modelComponentCache = {}
  WeakTable(self.modelComponentCache)
end

function BattlePet:OnTick(deltaTime)
  if self.destroyed then
    return
  end
  if self.destroying then
    return
  end
  if self.isNeedLoad then
    return
  end
  local items = self.components:Items()
  for _, v in ipairs(items) do
    if v and v.enable then
      v:OnTick(deltaTime)
    end
  end
  if self:IsDead() then
    return
  end
  if self.card and self.card.petState:GetStuck() and self.card.petState.stuckPos then
    Log.Debug("StuckPos:", self.card.petState.stuckPos, self:GetName())
    if self.model and UE.UObject.IsValid(self.model) then
      self.model:K2_SetActorLocation(self.card.petState.stuckPos, false, nil, false)
    end
  end
  if self.RandomMoveDetal > 0 then
    self.RandomMoveDetal = self.RandomMoveDetal - deltaTime
    if self.RandomMoveDetal <= 0 then
      if not self:IsMoving() then
        local target = _G.BattleManager.vBattleField:GetPositionInEllipticRandom(self.card.petInfo.battle_inside_pet_info.cheers_tag)
        if target then
          self:MoveTo(target)
        end
      end
      BattleUtils.CheerPetsStartRandomMove()
    end
  end
  if self.MoveTarget then
    self.MoveTimeLimit = self.MoveTimeLimit - deltaTime
    if self.MoveTimeLimit <= 0 then
      self:MoveFail()
    end
  end
  self.UpdateFloorTimer = self.UpdateFloorTimer + deltaTime
  self:UpdateCurrentFloor()
  self.IsClickPetFrame = true
  self:TryRecoverClickTipUIInViewPort()
end

function BattlePet:UpdateCurrentFloor()
  if self.CacheFloorPos and self.UpdateFloorTimer <= BattleConst.UpdateFootDelta then
    return
  end
  if self.destroying or self.destroyed then
    return
  end
  if not self.model or not UE.UObject.IsValid(self.model) then
    return
  end
  self.UpdateFloorTimer = 0
  if self.model.CharacterMovement then
    local nowPos = self.model:K2_GetActorLocation()
    self.CacheFloorPos = nowPos
    local halfHeight = self.model:GetCurrentHalfHeight()
    self.model.CharacterMovement:K2_ComputeFloorDist(nowPos, halfHeight, halfHeight, self.model.CapsuleComponent:GetScaledCapsuleRadius(), self.model.CharacterMovement.CurrentFloor)
  end
end

function BattlePet:SetModel(model)
  self.model = model
  if not model then
    self.IsCanSwimming = false
    return
  end
  self.HeadLookAtComponent = self.model.BP_HeadLookAtComponent
  model.BattlePet = self
  self.card.BattlePet = self
  self.buffComponent.owner = self
  self.buffComponent:SetModel()
  if not self:IsWild() and not self:IsB1P1Pet() and self:IsNightMarePet() then
    PetMutationUtils.SetNightmareByIDMask(self.model)
  end
  local AnimComponent = self:GetAnimComponent()
  self.IsCanSwimming = self:IsAquatic()
  if AnimComponent and AnimComponent:HasAnimation("FlyHover") then
    self.IsCanFly = true
    Log.Debug("AnimComponent:HasAnimation(IsCanFly) true")
  else
    Log.Debug("AnimComponent:HasAnimation(IsCanFly) false")
  end
  model:EnableCanStandOnWaterSurface(BattleUtils.IsDeepWater())
  model:EnableCanStandUnderWater(self:GetCanSwimming())
  model:SetIsAquatic(self:GetCanSwimming())
  if BattleUtils.IsDeepWater() then
    self:InitPlatForm(BattleManager.vBattleField:GetWaterPlatform(self.teamEnm, self.card.posInField))
    self:SetWaterPlatformVisible(true)
    if BattleUtils.IsLavaBattle() and model.RocoBattleSwim then
      model.RocoBattleSwim.FxSwimBattleJump:Reset()
      model.RocoBattleSwim.FxSwimBattleIdle:Reset()
    end
  end
  if BattleUtils.IsTeam() or BattleUtils.IsDeepWater() then
    BattleManager.vBattleField:RefreshWaterBattleReflection()
  end
  self:ResetToBornPosition()
  self:InitPetRTPC()
end

function BattlePet:ActiveSwimComponent(bActive)
  if self.model and self.model.RocoBattleSwim then
    self.model.RocoBattleSwim:ActiveSwimComponent(bActive)
  end
end

function BattlePet:InitPlatForm(platForm)
  if platForm and self.model and self.model.RocoBattleSwim then
    self:ActiveSwimComponent(true)
    if self:GetCanSwimming() then
      self.model.RocoBattleSwim.BoneName = "locator_body"
    else
      self.model.RocoBattleSwim.HasPlatForm = true
      self:SetPlatFormPos(self.PlatFormPos)
      local platChange = SimpleDelegateFactory:CreateCallback(self, self.PlatFormStateChange)
      self.model.RocoBattleSwim.PlatFormStateChange:Add(self.model, platChange)
    end
    local capuseRadius = self.model.CapsuleComponent:GetScaledCapsuleRadius()
    if capuseRadius > _G.BattleManager.vBattleField.WaterPlatformRadius then
      local scale = capuseRadius / _G.BattleManager.vBattleField.WaterPlatformRadius
      platForm:SetActorScale3D(UE4.FVector(scale, scale, scale))
    else
      platForm:SetActorScale3D(UE4.FVector(1, 1, 1))
    end
    self.model.RocoBattleSwim.WaterHeight = _G.BattleManager.vBattleField.WaterHeight
    self.model.RocoBattleSwim.PlatFormFloat = platForm.RocoPlatFormFloat
  end
end

function BattlePet:SetPlatFormPos(posValue)
  self.PlatFormPos = posValue
  if not self:GetCanSwimming() and self.model and self.model.RocoBattleSwim then
    self.model.RocoBattleSwim.PlatFormPos = SceneUtils.ConvertAbsoluteToRelative(self.PlatFormPos)
  end
end

function BattlePet:ResetToBornPosition()
  if self.model then
    local rawTransform = _G.BattleManager.vBattleField:FindPetRawTransform(self.teamEnm, self.card.posInField or 1, self.card, false)
    if rawTransform and _G.enableAdaptiveBattlePetPos then
      self.model:Abs_K2_SetActorTransform(rawTransform, false, nil, false)
      _G.BattleManager.vBattleField:AdaptiveMyBattlePetPos(self.model)
    end
    self:PinOnTheGround()
  end
end

function BattlePet:SetWaterPlatformVisible(visible)
  if BattleUtils.IsDeepWater() then
    if visible then
      BattleManager.vBattleField:SetWaterPlatformVisible(self.teamEnm, self.card.posInField, self:GetCanSwimming())
    else
      BattleManager.vBattleField:SetWaterPlatformVisible(self.teamEnm, self.card.posInField, true)
    end
  end
end

function BattlePet:SwimSetLockIdle(value)
  if self.model and self.model.RocoBattleSwim then
    self.model.RocoBattleSwim.LockIdle = value
  end
end

function BattlePet:PlatFormStateChange()
  if BattleUtils.IsLavaBattle() then
    return
  end
  if self.model and self.model.RocoBattleSwim and self.model.RocoBattleSwim.PlatFormFloat then
    self.model.RocoBattleSwim.PlatFormFloat:StartJump()
  end
end

function BattlePet:SetOutLineMaterial()
  if BattleUtils.IsTeam() then
    return
  end
  if not self.model then
    return
  end
  if self.card.petState:GetPetIsInHide() then
    return
  end
  local xrayMat
  if self.teamEnm == BattleEnum.Team.ENUM_TEAM then
    xrayMat = self.model.TeamXRayMaterial
  else
    xrayMat = self.model.EnemyXRayMaterial
  end
  local world = UE4Helper.GetCurrentWorld()
  if UE.UObject.IsValid(xrayMat) and not xrayMat:IsA(UE.UMaterialInstanceDynamic) then
    local additionalName = xrayMat:GetName()
    xrayMat = UE4.UKismetMaterialLibrary.CreateDynamicMaterialInstance(world, xrayMat, additionalName)
  end
  UE4.UNRCStatics.SetRenderCustomDepth(self.model, xrayMat, nil, false)
end

function BattlePet:SetAttackRange(value)
  if not self.model then
    return
  end
  self.model.AttackRange = value
end

function BattlePet:LoadOther()
  local fTransfom = UE4.FTransform(UE4.FQuat(), UE4.FVector(0, 0, 0))
  local params = {}
  params.pet = self
  self.loadingOther = 1
  _G.BattleResourceManager:LoadActorAsyncWithParam(self, _G.UEPath.BP_BattlePetComponents, fTransfom, PriorityEnum.Passive_Battle_Pets, params, self.LoadOver)
end

function BattlePet:ProcessMimic()
  if self.card.mimicResourcePath then
    self.card.mimicResourcePath = nil
    if self.model and self.model.MimicActor then
      local mimic = self.model.MimicActor:GetChildActor()
      if mimic then
        mimic:SetMimicVisibility(true)
      end
    end
  end
end

function BattlePet:ResetModelPos()
  UE.UNRCCharacterUtils.SetCharacterMeshScale(self.model, self.card.resourceScale)
  self.perception:PinOnTheGround()
  self.battlePetComponents:K2_SetActorLocation(self.model:K2_GetActorLocation(), false, nil, false)
  self.model.RocoBattleSwim:RefreshHalfHeight()
end

function BattlePet:LoadOver(battlePetComponents)
  if self.destroyed or not self.model then
    Log.Warning("pet was destroyed when battlePetComponents lod over")
    return
  end
  self.battlePetComponents = battlePetComponents
  self.battlePetComponentsRef = UnLua.Ref(battlePetComponents)
  battlePetComponents:K2_AttachRootComponentToActor(self.model)
  battlePetComponents:K2_SetActorRelativeLocation(UE4.FVector(0, 0, 0), false, nil, false)
  if self.CacheNormalPos then
    battlePetComponents:K2_SetActorLocation(self.CacheNormalPos, false, nil, false)
    self.CacheNormalPos = nil
  end
  if battlePetComponents.BuffOffset then
    battlePetComponents.BuffOffset:K2_AttachTo(self.model:GetComponentByClass(UE4.UMeshComponent), "Root")
    battlePetComponents.BuffBox:K2_AttachTo(self.model:GetComponentByClass(UE4.UMeshComponent), "Root")
    battlePetComponents.BuffBox2D:K2_AttachTo(self.model:GetComponentByClass(UE4.UMeshComponent), "Root")
    battlePetComponents.BuffBoxWidget:RefreshAttachingPivotScale(self.model)
    battlePetComponents.BuffBox2DWidget:RefreshAttachingPivotScale(self.model)
    local isMimic, MimicType = self.card:CheckIsMimic()
    if isMimic and MimicType == ProtoEnum.BuffGroupSign.BGS_BATTLE_MIMIC then
      battlePetComponents.BuffBox:SetHiddenInGame(true, true)
      battlePetComponents.BuffBox2D:SetHiddenInGame(true, true)
    end
  end
  self:ReAttachClickTipUI()
  if battlePetComponents.SkillPredictionUIOffset then
    local attachName = BattleUtils.GetAttachPointNameByType(UE4.EFXAttachPointType.Head)
    battlePetComponents.SkillPredictionUIOffset:K2_AttachTo(self.model:GetComponentByClass(UE4.UMeshComponent), attachName)
    self.battlePetComponents.SkillPredictionUIOffset:K2_SetRelativeLocation(UE4.FVector(0, 0, 0), false, nil, false)
    self.battlePetComponents.SkillPredictionUI:K2_SetRelativeLocation(UE4.FVector(0, 0, 0), false, nil, false)
    if BattleUtils.IsBadge2DType() then
      local worldPos = self.battlePetComponents.SkillPredictionUI:K2_GetComponentLocation()
      local fixPos = worldPos
      local maxZ = 380
      local config = _G.DataConfigManager:GetRogueChallengeGlobalConfig("maxSkillPredictionZ")
      if config then
        maxZ = config.num
      end
      if maxZ < fixPos.Z then
        local needZ = 100
        config = _G.DataConfigManager:GetRogueChallengeGlobalConfig("rate_SkillPredictionY")
        if config then
          needZ = config.num
        end
        local needY = 50
        config = _G.DataConfigManager:GetRogueChallengeGlobalConfig("rate_SkillPredictionX")
        if config then
          needY = config.num
        end
        local overflow = fixPos.Z - maxZ
        local offset = UE4.FVector(0, overflow * needY / 100, -overflow * needZ / 100)
        Log.Info("SkillPredictionUI-Overflow", self.card.name, worldPos, overflow, offset)
        self.battlePetComponents.SkillPredictionUI:K2_SetRelativeLocation(offset, false, nil, false)
      end
      self.battlePetComponents.SkillPredictionUI:K2_DetachFromComponent(UE.EAttachmentRule.KeepWorld)
    end
    local CapsuleComponent = self.model and self.model.CapsuleComponent
    local radius = 50
    local halfHeight = 75
    local offsetXMultiplier = -15
    local offsetYMultiplier = -5
    if UE.UObject.IsValid(CapsuleComponent) then
      radius = CapsuleComponent:GetScaledCapsuleRadius()
      halfHeight = CapsuleComponent:GetScaledCapsuleHalfHeight()
    end
    local offsetX = offsetXMultiplier * math.sqrt(radius)
    local offsetY = offsetYMultiplier * math.sqrt(halfHeight)
    local SkillPredictionUI = self.battlePetComponents and self.battlePetComponents.SkillPredictionUIActor
    if UE.UObject.IsValid(SkillPredictionUI) then
      local prevPosition = SkillPredictionUI:GetRootPosition()
      local nextPosition = UE.FVector2D(offsetX, offsetY)
      SkillPredictionUI:SetRootPosition(nextPosition)
    end
  end
  if battlePetComponents.ClickTipUIOffset then
    local attachName = BattleUtils.GetAttachPointNameByType(UE4.EFXAttachPointType.Body)
    battlePetComponents.ClickTipUIOffset:K2_AttachTo(self.model:GetComponentByClass(UE4.UMeshComponent), attachName)
    self.battlePetComponents.ClickTipUIOffset:K2_SetRelativeLocation(UE4.FVector(0, 0, 0), false, nil, false)
    self.battlePetComponents.ClickTipUI:K2_SetRelativeLocation(UE4.FVector(0, 0, 0), false, nil, false)
  end
  if battlePetComponents.SelectMarker3dOffset then
    local attachName = BattleUtils.GetAttachPointNameByType(UE4.EFXAttachPointType.Pos)
    battlePetComponents.SelectMarker3dOffset:K2_AttachTo(self.model:GetComponentByClass(UE4.UMeshComponent), attachName)
    local trans = battlePetComponents.SelectMarker3dOffset:GetRelativeTransform()
    trans.Translation.Z = trans.Translation.Z + BattleConst.ModelOffset.SelectorMarker3dOffsetZ
    battlePetComponents.SelectMarker3dOffset:K2_SetRelativeLocationAndRotation(trans.Translation, trans.Rotation:ToRotator(), false, nil, false)
  end
  if battlePetComponents.CatchConsumeUI then
    battlePetComponents.CatchConsumeUI:K2_AttachTo(self.model:GetComponentByClass(UE4.UMeshComponent), "Root")
    local catchConsumeUIOffset = UE4.FVector(0, 0, -20)
    battlePetComponents.CatchConsumeUI:K2_SetRelativeLocation(catchConsumeUIOffset, false, nil, false)
  end
  if battlePetComponents.PetEvolutionBubbleUI then
    local attachName = BattleUtils.GetAttachPointNameByType(UE4.EFXAttachPointType.Head)
    battlePetComponents.PetEvolutionBubbleUI:K2_AttachTo(self.model:GetComponentByClass(UE4.UMeshComponent), attachName)
  end
  battlePetComponents.SelectMarker3d:SetVisibility(false)
  self:HidePreselectTips()
  if self.teamEnm == BattleEnum.Team.ENUM_TEAM then
    self:SetSelectMarkColorIndex(1)
  else
    self:SetSelectMarkColorIndex(0)
  end
  self.transparentSkill = SkillPlayer(self.model.RocoSkill, self.model, BattleConst.PetTransparent.Sequence)
  self.isNeedLoad = false
  local needAi = not BattleUtils.IsDeepWater() or self:GetCanSwimming() and self.card:WillMove()
  if needAi then
    self.model.AIControllerClass = battlePetComponents.BattleAI
  else
    self.model.AIControllerClass = nil
  end
  if self.model.SpawnDefaultController then
    self.model:SpawnDefaultController()
  end
  if BattleUtils.IsDeepWater() and self:GetCanSwimming() then
    self.model:SetActionMode(UE.EPetActionMode.Swim)
  end
  self:CheckPawnOver()
end

function BattlePet:ReAttachClickTipUI()
  if self.battlePetComponents and self.battlePetComponents.ClickTipUIOffset then
    local attachName = BattleUtils.GetAttachPointNameByType(UE4.EFXAttachPointType.Body)
    self.battlePetComponents.ClickTipUIOffset:K2_AttachTo(self.model:GetComponentByClass(UE4.UMeshComponent), attachName)
    self.battlePetComponents.ClickTipUIOffset:K2_SetRelativeLocation(UE4.FVector(0, 0, 0), false, nil, false)
    self.battlePetComponents.ClickTipUI:K2_SetRelativeLocation(UE4.FVector(0, 0, 0), false, nil, false)
  end
end

function BattlePet:ModifyClickTipUIPos(ModifyPos)
  if self.battlePetComponents and self.battlePetComponents.ClickTipUIOffset then
    local camera = _G.BattleManager.vBattleField.battleCraneCamera
    if camera and UE4.UObject.IsValid(camera.CameraActor) then
      self.battlePetComponents.ClickTipUIOffset:K2_AttachTo(camera.CameraActor:GetComponentByClass(UE4.UMeshComponent))
    end
    self.battlePetComponents.ClickTipUIOffset:Abs_K2_SetWorldLocation(ModifyPos, false, nil, false)
  end
end

function BattlePet:CheckPawnOver()
  if self.loadingOther > 0 then
    self.loadingOther = self.loadingOther - 1
    if 0 == self.loadingOther then
      _G.BattleEventCenter:Dispatch(BattleEvent.PET_SPAWNED, self)
      self.loadOver = true
      _G.NRCEventCenter:RegisterEvent("BattlePet.ShowClickTipUI", self, BattleCraneCameraEvent.BlendFuncFinish, self.CheckClickTipUIInViewPort)
    end
  end
end

function BattlePet:IsLoadOver()
  return self.loadOver
end

function BattlePet:OnPetClick()
  if self.clickable and self.IsClickPetFrame then
    self.IsClickPetFrame = false
    if self.battlePetComponents then
      self.battlePetComponents:PlayClickTipUI()
    else
      Log.Error("Exception: BattlePet:OnPetClick battlePetComponents is nil")
    end
    _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_CLICKED_PET, self)
  end
end

function BattlePet:PlayerClickEffect(pet)
  if self.battlePetComponents and self.battlePetComponents:IsShowClickUI() then
    if pet == self then
      self.battlePetComponents:PlayClickTipUI(self, self.OnClickOver)
    else
      self.battlePetComponents:PlayClickTipUI()
    end
  end
end

function BattlePet:OnClickOver()
  _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_CLICKED_PET, self)
end

function BattlePet:PlayShiNeng(type, NewTemplate)
  if self.battlePetComponents then
    if not self.battlePetComponents.Shineng then
      self.battlePetComponents.Shineng = self.battlePetComponents.ShinengPlayer:GetChildActor()
    end
    if self.battlePetComponents.Shineng then
      self.battlePetComponents.Shineng.ParticleSystem:SetTemplate(NewTemplate)
      if type then
        self.battlePetComponents.Shineng:ChangeByType(type)
      end
      self.battlePetComponents.Shineng.ParticleSystem:Activate(true)
    end
  end
end

function BattlePet:TurnToBack()
  if not self.IsHeadBack then
    local rotation = self.InitRotator
    self.model:K2_SetActorRotation(UE4.FRotator(rotation.Pitch, rotation.Yaw + 180, rotation.Roll), false)
    self.IsHeadBack = true
  end
end

function BattlePet:OperateSelectMarker3dWithAnimation(bShow)
  if self.battlePetComponents then
    if not self.battlePetComponents.marker then
      self.battlePetComponents.marker = self.battlePetComponents.SelectMarker3d:GetChildActor()
    end
    if self.battlePetComponents.marker then
      if bShow then
        self.battlePetComponents.marker:Open()
      else
        self.battlePetComponents.marker:Close()
      end
    end
  end
end

function BattlePet:ShowSelectMarker3d(bShow)
  if self.battlePetComponents then
    self.battlePetComponents:ShowSelectMarker3d(bShow)
  end
end

function BattlePet:Spawn(guid, card, params)
  self.guid = guid
  self.card = card
  self.index = params.index
  self.team = params.team
  self.player = params.player
  self.teamEnm = params.team.teamEnm
  local battleManager = _G.BattleManager
  if not battleManager then
    return
  end
  self:InitByCard(card)
  self:AddListener()
  if not self.isNeedLoad then
    _G.BattleEventCenter:Dispatch(BattleEvent.PET_SPAWNED, self)
  end
  self:SetAttachPoint()
end

function BattlePet:PlayAnimByName(animName, rate, position, BlendInTime, BlendOutTime, LoopCount, endPosition)
  if not self.buffComponent:IsCanPlayAnimation(animName) then
    return 0
  end
  if BattleLog.IsSubSwitchEnabled(BattleLog.LogType.Anim) then
    local actorName = "Unknown"
    if self.model then
      actorName = self.model:GetFullName() or "Unknown"
    end
    local curAnimName = "None"
    local animComp = self:GetAnimComponent()
    if animComp and animComp.GetCurAnimNameWithCheck then
      curAnimName = animComp:GetCurAnimNameWithCheck() or "None"
    end
    BattleLog.Warning(BattleLog.LogType.Anim, string.format("BattlePet:PlayAnimByName - \229\189\147\229\137\141\229\138\168\231\148\187: %s, \232\166\129\230\146\173\230\148\190\231\154\132\229\138\168\231\148\187: %s, Pet: %s", curAnimName, animName, actorName))
  end
  if self.model then
    return self.model:PlayAnimByName(animName, rate, position, BlendInTime, BlendOutTime, LoopCount, endPosition)
  end
  return 0
end

function BattlePet:SetAnimable(boo)
  self.isAnimable = boo
end

function BattlePet:SetPetType(battle_attr)
  self.card:SetPetType(battle_attr)
end

function BattlePet:InitOp()
  self.opState = BattleEnum.Operation.ENUM_NONE
  Log.Debug("zgx No op InitOp", self.card.name, self.guid)
end

function BattlePet:SetOp(op)
  self.opState = op
  Log.Debug("zgx No op SetOp", op, self.card.name, self.guid)
end

function BattlePet:SetOpParam(param)
  self.opParam = param
end

function BattlePet:UpdateOpState(petInfo)
  self:UpdateOpStateByReq(petInfo.req)
end

function BattlePet:UpdateOpStateByReq(req)
  Log.Debug("zgx No op UpdateOpStateByReq", self.card.name, self.guid)
  if req then
    if req.req_type == _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_CAST_SKILL then
      self:SetOp(BattleEnum.Operation.ENUM_SKILL)
      self:SetOpParam(req.cast_skill)
    elseif req.req_type == _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_CHANGE_PET then
      self:SetOp(BattleEnum.Operation.ENUM_CHANGE)
      self:SetOpParam(req.change_pet)
    elseif req.req_type == _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_IDLE then
      self:SetOp(BattleEnum.Operation.ENUM_SKILL)
    elseif req.req_type == _G.ProtoEnum.BATTLE_REQ_TYPE.CMD_ROLE_MAGIC then
      self:SetOp(BattleEnum.Operation.ENUM_PLAYERSKILL)
    else
      self:InitOp()
    end
  else
    self:InitOp()
  end
end

function BattlePet:InitByCard(card)
  for i = 1, self.components:Size() do
    local comp = self.components:Get(i)
    if comp then
      comp:InitByCard(card)
    end
  end
  self:UpdateEscapeInfo()
  self:UpdateOpState(card.petInfo)
end

function BattlePet:UpdateByCard(card, needRefresh)
  if not self:IsDead() and self.components and self.components:Size() > 0 then
    for i = 1, self.components:Size() do
      local comp = self.components:Get(i)
      if comp then
        comp:UpdateByCard(card, needRefresh)
      end
    end
  end
  self:UpdateEscapeInfo()
  self:UpdateOpState(card.petInfo)
end

function BattlePet:UpdateLocalRoundPerformInfo()
  local worldPos = PetUtils.GetBattlePetSocketPosition3D(self)
  self.buffPos = worldPos
end

function BattlePet:ReplaceByServer(petInfo)
  self.card:ReplaceByServer(petInfo)
end

function BattlePet:OverwriteByServer(petInfo)
  self.card:OverwriteByServer(petInfo)
end

function BattlePet:RefreshByServer()
  self.card:RefreshByServer()
  self:UpdateByCard(self.card)
end

function BattlePet:RefreshSkillByServer(skills)
  self.card:RefreshSkillByServer(skills)
  self:UpdateByCard(self.card)
end

function BattlePet:OnEnterBattleSettlementState()
  self:ChangeBuffVisibility(false)
  self:ShowActiveState(false)
  self:ShowOperation(false)
end

function BattlePet:AddListener()
  _G.BattleEventCenter:Bind(self, BattlePerformEvent.ObtainType, BattleEvent.BATTLE_STATE_SETTLEMENT, BattleEvent.PlayClickEffect, BattlePerformEvent.TurnPlayComplete, BattleEvent.ROUND_START)
end

function BattlePet:RemoveListener()
  _G.BattleEventCenter:UnBind(self)
end

function BattlePet:OnBattleEvent(eventName, ...)
  if eventName == BattlePerformEvent.ObtainType then
    local targetID, attrType, attrChange, attrResult = ...
    if self.guid == targetID then
      local battle_attr = self.card.petInfo.battle_inside_pet_info.battle_attr
      battle_attr[attrType + 1] = attrResult
      self:SetPetType(battle_attr)
      _G.BattleEventCenter:Dispatch(BattleEvent.PET_TYPES_CHANGED, self.guid)
    end
    return true
  elseif eventName == BattleEvent.BATTLE_STATE_SETTLEMENT then
    self:OnEnterBattleSettlementState()
    return true
  elseif eventName == BattleEvent.PlayClickEffect then
    self:PlayerClickEffect(...)
    return true
  elseif eventName == BattlePerformEvent.TurnPlayComplete then
    self:DedupBuffPopupQueue()
    return true
  elseif eventName == BattleEvent.ROUND_START then
    self:TurnEndBuffModeAnimQue()
    return true
  end
end

function BattlePet:OnSelectCallback()
  _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_PET_CMD_FINISHED, self)
end

function BattlePet:ShowActiveState(bShow)
  if self.battlePetComponents then
    self.battlePetComponents:ShowActiveState(bShow)
  end
  _G.BattleEventCenter:Dispatch(BattleEvent.PET_TURN_IS_UP, bShow)
end

function BattlePet:ShowOperation(bShow)
  if self.battlePetComponents then
    self.battlePetComponents:ShowOperation(bShow)
  end
end

function BattlePet:GetPlayer()
  return self.player
end

function BattlePet:GetCard()
  return self.card
end

function BattlePet:ShowPopup(Info, target, callback)
  self.card:ShowPopup(Info, target, callback)
end

function BattlePet:HidePopup(target, callback)
  self.card:HidePopup(target, callback)
end

function BattlePet:TookDamage(damage, serverHpChange, damage_info, ifDamageNumber)
  if self:IsDead() then
    return
  end
  if not damage then
    return
  end
  self.health:TookDamage(damage, serverHpChange)
  if false == ifDamageNumber then
  else
    self:DamageNumber(damage, false, damage_info)
  end
  if self.health.hp <= 0 then
  end
end

function BattlePet:TookShieldDamage(damage, serverShieldChange, damage_info)
  if self:IsDead() then
    return
  end
  if not damage then
    return
  end
  self.health:TookShieldDamage(damage, serverShieldChange)
  self:DamageNumber(damage, false, damage_info)
end

function BattlePet:StealEnergy()
  local BattleMain = BattleUtils.GetMainWindow()
  BattleMain.needProcessEnergyTrack = true
end

function BattlePet:AddEnergy()
  local BattleMain = BattleUtils.GetMainWindow()
  BattleMain.needProcessEnergyTrack = true
end

function BattlePet:Die(deadInfo)
  if not self.card.petState:GetDead() then
    self:ChangeBuffVisibility(false)
    self.card:Die(deadInfo)
    self.buffComponent:OnPetDie()
    Log.Debug("\231\178\190\231\129\181\230\173\187\228\186\161 ", self.guid)
    _G.BattleEventCenter:Dispatch(BattleEvent.BATTLE_PET_DIE, self)
  end
end

function BattlePet:GotHealing(healing)
  if self:IsDead() then
    return
  end
  if not healing then
    healing = 0
    Log.Error("\231\178\190\231\129\181\230\129\162\229\164\141Hp\231\154\132\229\128\188\228\184\186nil")
  end
  self.health:GotHealing(healing)
  self:DamageNumber(healing, true)
end

function BattlePet:ChangeBuffVisibility(flag)
  if self:IsDead() then
    return
  end
  if self.battlePetComponents then
    if flag then
      self.battlePetComponents:ShowBuffs()
    else
      self.battlePetComponents:HideBuffs()
    end
  end
end

function BattlePet:SetPopupVisibility(flag)
  if self.battlePetComponents then
    self.battlePetComponents:SetPopupWidgetVisibility(flag)
  end
end

function BattlePet:CatchedSuccess()
  self.buffComponent:RemoveBuffs(false)
  self:ChangeBuffVisibility(false)
  if self:IsDead() then
    return
  end
  self.health:CatchPet()
  self.team.player.deck.cards[self.card.CardIndex].hp = self.health.hp
  self.card.petState:SetDead(true)
  Log.Debug("\231\178\190\231\129\181\232\162\171\230\141\149\230\141\137 ", self.guid)
  self.team:RecallPet(self)
end

function BattlePet:IsDead()
  if self.card then
    return self.card.petState:GetDead()
  end
  return true
end

function BattlePet:GetDeadType()
  if self.card then
    return self.card.petState:GetDeadType()
  end
  return ProtoEnum.BattleDeadInfo.DeadType.NORMAL_DEAD
end

function BattlePet:DamageNumber(num, isHealing, damage_info)
  if not damage_info or 1 == damage_info.curDamageNumber then
    self.buffAEffectPopupComponent:PopupDamageNumber(num, isHealing, damage_info)
  else
    self.buffAEffectPopupComponent:ReplayDamageNumber(num, damage_info)
  end
end

function BattlePet:PopupBuff(buffInfo, attachOrTrigger)
  self.buffAEffectPopupComponent:PopupBuff(buffInfo.buff_id, attachOrTrigger)
end

function BattlePet:PopupBuffByAttachOrTrigger(buff_id, isAttach)
  Log.Debug("Buff popup by attach or trigger: ", buff_id, isAttach)
  if not BuffUtils.IsShowBuffOrLetter(self.card, _G.DataConfigManager:GetBuffConf(buff_id)) then
    return
  end
  self.buffAEffectPopupComponent:PopupBuff(buff_id, isAttach)
end

function BattlePet:ShowBuffs(buffInfo)
end

function BattlePet:SetClickable(flag)
  self.clickable = flag
  self:ToggleClickable(flag)
end

function BattlePet:ApplyItem(itemID, callbackOwner, completeCallback)
  self.applyItemComplete = completeCallback
  self.applyItemCompleteOwner = callbackOwner
  local itemConf = _G.DataConfigManager:GetBattleItemConf(itemID)
  if not itemConf or not self.model then
    Log.ErrorFormat("No item conf found %d", itemID)
    self:OnApplyItemEnd()
    return
  end
  local itemPath = itemConf.resource_usage_path
  if not itemPath then
    self:OnApplyItemEnd()
    return
  end
  BattleResourceManager:LoadClassAsync(self, itemPath, self.OnClassLoad)
end

function BattlePet:OnClassLoad(skillClass)
  local skillApplyItem = self.model.RocoSkill:AddSkillObjFromClassAndReturn(skillClass)
  skillApplyItem:SetPassive(true)
  skillApplyItem:SetCaster(self.model)
  skillApplyItem:RegisterEventCallback("Start", self, self.OnApplyItemStart)
  skillApplyItem:RegisterEventCallback("PreEnd", self, self.OnApplyItemEnd)
  skillApplyItem:RegisterEventCallback("End", self, self.OnApplyItemEnd)
  skillApplyItem:RegisterEventCallback("Interrupt", self, self.OnApplyItemEnd)
  skillApplyItem:RegisterEventCallback("StartFailed", self, self.OnApplyItemEnd)
  self:PlaySkillObject(skillApplyItem)
end

function BattlePet:OnApplyItemStart()
end

function BattlePet:OnApplyItemEnd()
  local Callback = self.applyItemComplete
  local Owner = self.applyItemCompleteOwner
  if Callback then
    Callback(Owner)
  end
end

function BattlePet:OnRecall()
  if self.destroyed then
    return
  end
  if self.destroying then
    return
  end
  Log.Debug("BattlePet:OnRecall ", self.guid)
  if self.health then
    self.card.hp = self.health.hp or 0
  end
  self:Destroy()
end

function BattlePet:StopAllSkill()
  if UE4.UObject.IsValid(self.model) and UE4.UObject.IsValid(self.model.RocoSkill) then
    local rocoSkill = self.model.RocoSkill
    rocoSkill:StopCurrentSkill()
    if self.destroyed or self.destroyModel then
      return
    end
    if UE4.UObject.IsValid(rocoSkill) then
      rocoSkill:StopAllPassiveSkill()
    end
  end
end

function BattlePet:ClearSkill()
  if UE4.UObject.IsValid(self.model) and UE4.UObject.IsValid(self.model.RocoSkill) then
    local rocoSkill = self.model.RocoSkill
    rocoSkill:StopCurrentSkill()
    if self.destroyed or self.destroyModel then
      return
    end
    if UE4.UObject.IsValid(rocoSkill) then
      rocoSkill:StopAllPassiveSkill()
    end
    if self.destroyed or self.destroyModel then
      return
    end
    if UE4.UObject.IsValid(rocoSkill) then
      rocoSkill:ClearSkillObj()
    end
  end
end

function BattlePet:DestroyDelay()
  self:Destroy()
end

function BattlePet:Destroy()
  Log.Debug("BattlePet:Destroy ", self.guid)
  if self.destroyed then
    return
  end
  if self.destroying then
    return
  end
  self.destroying = true
  _G.BattleEventCenter:Dispatch(BattleEvent.PET_DISTROYED, self)
  if self.card and self.card.owner == self then
    self.card.BattlePet = nil
  end
  if self.HighlightPlayer then
    self.HighlightPlayer:Destroy()
    self.HighlightPlayer:UnBindRef()
    self.HighlightPlayer = nil
  end
  if self.DarkPlayer then
    self.DarkPlayer:Destroy()
    self.DarkPlayer:UnBindRef()
    self.DarkPlayer = nil
  end
  if self.card and self.card:CheckIsMimic(true) then
    self.card:RefreshResource()
    self.card:RefreshName(self.card.petInfo)
  end
  self:HideClickTipUI()
  self:ClearMove()
  self:ClearSkill()
  self:RemoveListener()
  self:StopHighlight()
  self:StopChangeEffect()
  self.buffComponent:OnBattlePetDestroy()
  if self.transparentSkill then
    self.transparentSkill:Destroy()
    self.transparentSkill:UnBindRef()
    self.transparentSkill = nil
  end
  self.JumpSkillObj = nil
  self.JumpOverCaller = nil
  self.JumpOverCallBack = nil
  _G.NRCEventCenter:UnRegisterEvent(self, BattleCraneCameraEvent.BlendFuncFinish, self.CheckClickTipUIInViewPort)
  if self.battlePetComponents then
    if UE.UObject.IsValid(self.battlePetComponents) then
      Log.Debug("show me battlepet battlePetComponents:", self.battlePetComponents)
      if self.battlePetComponents.PopupUIFather then
        self.battlePetComponents.PopupUIFather:ClearChildren()
      end
      self.battlePetComponents:Reset()
      UnLua.Unref(self.battlePetComponents)
      self.battlePetComponentsRef = nil
      if self.battlePetComponents.K2_DestroyActor then
        self.battlePetComponents:K2_DestroyActor()
      else
        Log.Error("Can't find K2_DestroyActor", self.card.name)
        UE4.UNRCStatics.DumpFClassDesc("ABP_BattlePetComponents_C")
      end
    else
      Log.Error("Not Valid", self.card.name)
    end
    self.battlePetComponents = nil
  else
    Log.Debug("battlePetComponents is nil already")
  end
  self.destroyModel = true
  if self.model then
    if self.model:IsValid() then
      if self.model:IsValidLowLevelFast() then
        if self.model:IsValidLowLevel() then
          Log.Debug("Clear pet model ReleaseResource", self.card.name)
          if self.model.mesh then
            self.model.mesh:ReleaseResource()
            self.model.mesh:ReleaseClass()
          end
          if self.model.K2_DestroyActor then
            self.model:K2_DestroyActor()
          else
            Log.Error("Can't find K2_DestroyActor", self.card.name)
          end
        else
          Log.Error("Not Valid At Low Level", self.card.name)
        end
      else
        Log.Error("Not Valid At Low Level Fast", self.card.name)
      end
    else
      Log.Error("Not Valid", self.card.name)
    end
    local tempModelToDestroy = self.model
    self.model = nil
    tempModelToDestroy:Release()
  else
    Log.Debug("Model is nil already")
  end
  self.health = nil
  self.HighlightContex = nil
  self.destroying = false
  Base.Destroy(self)
  if self.team then
    self.team:RemovePet(self)
  end
end

function BattlePet:ChangeOperation(path)
  if self.battlePetComponents then
    self.battlePetComponents:ChangeOperation(path)
  else
    Log.Error("BattlePetController:ChangeOperation battlePetComponents is nil" .. path)
  end
end

function BattlePet:ShowClickTipUI(data)
  if self.battlePetComponents then
    self.battlePetComponents:ShowClickTipUI(data)
    _G.BattleManager.SelectTargetManager:AddSelectTarget(self, data)
    self.isShowedClickTipUI = true
  end
end

function BattlePet:CheckClickTipUIInViewPort()
  if not (self and self.battlePetComponents and self.model) or not UE4.UObject.IsValid(self.model) then
    return false
  end
  local battleCraneCamera = _G.BattleManager.vBattleField and _G.BattleManager.vBattleField.battleCraneCamera or nil
  if not battleCraneCamera then
    return false
  end
  if battleCraneCamera:GetBlendCameraIng() then
    return false
  end
  local ModifyPos
  if not BattleUtils.CheckPetInViewPort(self) then
    ModifyPos = BattleUtils.GetVirtualPetPos(self)
  end
  if ModifyPos then
    self:ModifyClickTipUIPos(ModifyPos)
    self.needRecover_For_CheckClickTipUI = true
    return false
  else
    self.needRecover_For_CheckClickTipUI = false
    self:ReAttachClickTipUI()
    return true
  end
end

function BattlePet:TryRecoverClickTipUIInViewPort()
  if self.needRecover_For_CheckClickTipUI and self.isShowedClickTipUI then
    local bInViewport = BattleUtils.CheckPetInViewPort(self)
    if bInViewport then
      local bAttached = self:CheckClickTipUIInViewPort()
      if bAttached then
        self.needRecover_For_CheckClickTipUI = false
      end
    end
  end
end

function BattlePet:ShowRestraintUI(skill, selectAdditionalInfo)
  if self.battlePetComponents and skill:IsShowRestraint() then
    self.battlePetComponents:ShowRestraint(skill, selectAdditionalInfo)
  end
end

function BattlePet:HideRestraintUI()
  if self.battlePetComponents then
    self.battlePetComponents:HideRestraintUI()
  end
end

function BattlePet:HidePet(hideBuff)
  if self.model and UE4.UObject.IsValid(self.model) then
    self.model:SetActorHiddenInGame(true)
    if hideBuff or nil == hideBuff then
      self:ChangeBuffVisibility(false)
    end
  end
end

function BattlePet:ShowPet(showBuff)
  if self.model then
    self.model:SetActorHiddenInGame(false)
    if showBuff or nil == showBuff then
      self:ChangeBuffVisibility(true)
    end
  end
  self:SetWaterPlatformVisible(true)
end

function BattlePet:SetPetVisibility(isShow)
  local skeletalComp = self.model:GetComponentByClass(UE4.USkeletalMeshComponent)
  if skeletalComp then
    skeletalComp:SetVisibility(isShow)
  end
  if isShow then
    self:ShowPet()
  else
    self:HidePet()
  end
end

function BattlePet:HideClickTipUI()
  if not self.isShowedClickTipUI then
    return
  end
  if self.battlePetComponents then
    self.battlePetComponents:HideClickTipUI()
    _G.BattleManager.SelectTargetManager:RemoveSelectTarget(self)
    self.isShowedClickTipUI = false
  end
end

function BattlePet:ShowCatchRate(rate)
  if self.battlePetComponents then
    self.battlePetComponents:ShowCatchRate(rate)
  end
end

function BattlePet:HideCatchRate()
  if self.battlePetComponents then
    self.battlePetComponents:HideCatchRate()
  end
end

function BattlePet:ShowTipTime(time, operateType, params)
  if self.battlePetComponents then
    self.battlePetComponents:ShowTipTime(time, operateType, params)
  end
end

function BattlePet:HideTipTime()
  if self.battlePetComponents then
    self.battlePetComponents:HideTipTime()
  end
end

function BattlePet:PrepareSkill(CastParam)
  return BattleSkillManager:PrepareSkill(self, self.model.RocoSkill, CastParam)
end

function BattlePet:CastPreparedSkill()
  Log.Debug("battlepet CastPreparedSkill")
  self.model.RocoSkill:CancelSkill(self.preparedSkillObj, UE4.ESkillActionResult.SkillActionResultSuccessful)
  self.model.RocoSkill:PlaySkill(self.preparedSkillObj)
  self.preparedSkillObj = nil
end

function BattlePet:CommonCast(CastParam)
  return BattleSkillManager:CommonCast(self, self.model.RocoSkill, CastParam)
end

function BattlePet:CancelSkill(reason)
  if not UE4.UObject.IsValid(self.model) then
    return
  end
  if not self.model.RocoSkill then
    return
  end
  reason = reason or UE4.ESkillActionResult.SkillActionResultInterrupted
  local activeSkill = self.model.RocoSkill:GetActiveSkill()
  if activeSkill then
    Log.Error("\230\173\163\229\156\168\233\135\138\230\148\190\230\138\128\232\131\189\239\188\140\232\162\171\229\188\186\232\161\140\230\137\147\230\150\173:", activeSkill:GetName())
    self.model.RocoSkill:CancelSkill(activeSkill, reason)
  end
end

function BattlePet:GetCurrentActiveSkill()
  if not UE4.UObject.IsValid(self.model) then
    return
  end
  if not self.model.RocoSkill then
    return
  end
  return self.model.RocoSkill:GetActiveSkill()
end

function BattlePet:CancelSkillBySkillObject(skillObject, reason)
  if not skillObject then
    return
  end
  if not UE4.UObject.IsValid(self.model) then
    return
  end
  if not self.model.RocoSkill then
    return
  end
  reason = reason or UE4.ESkillActionResult.SkillActionResultInterrupted
  Log.Error("\230\173\163\229\156\168\233\135\138\230\148\190\230\138\128\232\131\189\239\188\140\232\162\171\229\188\186\232\161\140\230\137\147\230\150\173:", skillObject:GetName())
  self.model.RocoSkill:CancelSkill(skillObject, reason)
end

function BattlePet:ShowForInterrupt()
  if self.model then
    self.model:SetActorHiddenInGame(false)
    self.model.Mesh:SetVisibility(true)
  end
end

function BattlePet:OnSkillEvent(event, skill)
  if "CameraFollow" == event then
    self:CallCamera(skill, "OutPos")
  elseif "CameraCalc" == event then
    self:CallCameraCalc(skill, "OutPos")
  end
end

function BattlePet:CallCamera(skill, Key)
  local FauxPet = skill:GetBlackboard():GetValueAsVector(Key)
  local FauxPet2 = skill:GetBlackboard():GetValueAsVector(Key .. "Ori")
  local CasterRaw = skill:GetBlackboard():GetValueAsObject("CasterRaw")
  local FauxPetWorldPos = SceneUtils.ConvertRelativeToAbsolute(FauxPet)
  local FauxPetWorldPos2 = SceneUtils.ConvertRelativeToAbsolute(FauxPet2)
  if FauxPetWorldPos.X <= 0.1 or FauxPetWorldPos.Y <= 0.1 then
    if FauxPetWorldPos2.X <= 0.1 or FauxPetWorldPos2.Y <= 0.1 then
      return
    end
    FauxPet = FauxPet2
    FauxPetWorldPos = FauxPetWorldPos2
  end
  if FauxPet and 0 == FauxPet.X and 0 == FauxPet.Y then
    FauxPet = FauxPet2
    FauxPetWorldPos = FauxPetWorldPos2
  end
  local battlePos = _G.BattleManager.vBattleField.battleFieldActor:Abs_K2_GetActorLocation()
  local dist = FauxPetWorldPos:Dist(battlePos)
  if dist >= 1500 then
    Log.Error("BattlePet:CallCamera \233\149\156\229\164\180\229\129\143\231\167\187\232\183\157\231\166\187\229\188\130\229\184\184\239\188\129\239\188\129\239\188\129\239\188\129 \229\129\143\231\167\187\228\184\186", dist)
    return
  end
  local CameraDelta = 0.55
  local teamPet = BattleManager.battlePawnManager:GetTeamPet(BattleEnum.Team.ENUM_TEAM, 1)
  if teamPet and CasterRaw == teamPet.model then
    if FauxPet then
      BattleManager.vBattleField.battleCameraManager:LatentFollow(CameraDelta, nil, FauxPet, UE4.EViewTargetBlendFunction.VTBlend_Cubic, 1, true, nil, false, true, false)
    end
  elseif FauxPet then
    BattleManager.vBattleField.battleCameraManager:LatentFollow(CameraDelta, FauxPet, nil, UE4.EViewTargetBlendFunction.VTBlend_Cubic, 1, true, nil, false, false, true)
  end
end

function BattlePet:CallCameraCalc(skill, Key)
  local FauxPet = skill:GetBlackboard():GetValueAsVector(Key)
  local FauxPetWorldPos = SceneUtils.ConvertRelativeToAbsolute(FauxPet)
  if FauxPetWorldPos.X <= 0 or FauxPetWorldPos.Y <= 0 then
    return
  end
  local battlePos = _G.BattleManager.vBattleField.battleFieldActor:Abs_K2_GetActorLocation()
  local dist = FauxPetWorldPos:Dist(battlePos)
  if dist >= 1500 then
    Log.Error("BattlePet:CallCamera \233\149\156\229\164\180\229\129\143\231\167\187\232\183\157\231\166\187\229\188\130\229\184\184\239\188\129\239\188\129\239\188\129\239\188\129 \229\129\143\231\167\187\228\184\186", dist)
    return
  end
  local CasterRaw = skill:GetBlackboard():GetValueAsObject("CasterRaw")
  if CasterRaw == BattleManager.battlePawnManager:GetTeamPet(BattleEnum.Team.ENUM_TEAM, 1).model then
    if FauxPet then
      BattleManager.vBattleField.battleCameraManager:CalcPos(nil, FauxPet, false, true, false)
    end
  elseif FauxPet then
    BattleManager.vBattleField.battleCameraManager:CalcPos(FauxPet, nil, false, false, true)
  end
end

function BattlePet:PlaySkillByPath(skillPath, caller, finishCb, CastSkill)
  BattleResourceManager:LoadClassAsyncWithParam(self, skillPath, self.PlaySkillWithClass, nil, caller, finishCb, CastSkill)
end

function BattlePet:PlaySkill(skillID, caller, finishCb, CastSkill)
  local SkillResConf = DataConfigManager:GetSkillResConf(skillID)
  if not SkillResConf then
    Log.ErrorFormat("BattlePet:PlaySKill Error Class not found %s", tostring(skillID))
    if finishCb then
      finishCb(caller)
    end
    return nil
  end
  BattleResourceManager:LoadClassAsyncWithParam(self, SkillResConf.res_id, self.PlaySkillWithClass, nil, caller, finishCb, CastSkill)
end

function BattlePet:PlaySkillWithClass(skillClass, caller, finishCb, CastSkill)
  if not skillClass then
    if finishCb then
      finishCb(caller)
    end
    return
  end
  local skillObj = self.model.RocoSkill:AddSkillObjFromClassAndReturn(skillClass)
  if skillObj then
    local pawnManager = _G.BattleManager.battlePawnManager
    skillObj:SetCaster(self.model)
    local targetPets = CastSkill.TargetPets
    local petModels = {}
    if targetPets then
      for i = 1, #targetPets do
        if targetPets[i].model then
          table.insert(petModels, targetPets[i].model)
        end
      end
    end
    skillObj:SetTargets(petModels)
    skillObj:SetCharacters(pawnManager:GetAllPawnActorForSkill())
    if CastSkill then
      if CastSkill.OnStopBulletTime then
        skillObj:RegisterEventCallback("StopBulletTime", CastSkill.CallbackOwner, CastSkill.OnStopBulletTime)
      end
      skillObj:SetPassive(CastSkill.IsPassive)
      if CastSkill.CompleteCallback then
        skillObj:RegisterEventCallback("End", CastSkill.CallbackOwner, CastSkill.CompleteCallback)
        skillObj:RegisterEventCallback("PreEnd", CastSkill.CallbackOwner, CastSkill.CompleteCallback)
      end
      if CastSkill.OnSkillBreakCallback then
        skillObj:RegisterEventCallback("Interrupt", CastSkill.CallbackOwner, CastSkill.OnSkillBreakCallback)
      elseif CastSkill.CompleteCallback then
        skillObj:RegisterEventCallback("Interrupt", CastSkill.CallbackOwner, CastSkill.CompleteCallback)
      end
      if CastSkill.OnStartFailedCallback then
        skillObj:RegisterEventCallback("StartFailed", CastSkill.CallbackOwner, CastSkill.OnStartFailedCallback)
      elseif CastSkill.CompleteCallback then
        skillObj:RegisterEventCallback("StartFailed", CastSkill.CallbackOwner, CastSkill.CompleteCallback)
      end
      if CastSkill.ExtraEvents then
        for name, callBack in pairs(CastSkill.ExtraEvents) do
          skillObj:RegisterEventCallback(name, CastSkill.CallbackOwner, callBack)
        end
      end
    end
    self.model.RocoSkill:LoadAndPlaySkill(skillObj)
  end
end

function BattlePet:ClearNightmareEffect()
  if self.destroyed or self.destroying then
    return
  end
  local mutation_type = self.card.petInfo.battle_common_pet_info.mutation_type
  if PetMutationUtils.GetMutationValue(mutation_type, _G.Enum.MutationDiffType.MDT_CHAOS) then
    PetMutationUtils.RemoveNightmareFirstMutation(self.model)
  end
  if PetMutationUtils.GetMutationValue(mutation_type, _G.Enum.MutationDiffType.MDT_CHAOS_TWO) then
    PetMutationUtils.RemoveNightmareSecondMutation(self.model)
  end
  if PetMutationUtils.GetMutationValue(mutation_type, _G.Enum.MutationDiffType.MDT_CHAOS_THREE) then
    PetMutationUtils.RemoveNightmareByIDMask(self.model)
  end
end

function BattlePet:PlaySkillObject(Skill)
  if self.model.RocoSkill:GetActiveSkill() then
    Log.Error("Current skill is: ", self.model.RocoSkill:GetActiveSkill():GetDisplayName())
  end
  Log.Debug("Next skill is: ", Skill:GetDisplayName())
  self.model.RocoSkill:LoadAndPlaySkill(Skill)
end

function BattlePet:PlayChangeEffect()
  self:ShowTransparent(false)
  local skillClass = BattleResourceManager:GetCacheAssetDirect(BattleConst.ChangePetEffect)
  if not skillClass then
    Log.DebugFormat("ChangePetEffect Skill Class not found %s", BattleConst.ChangePetEffect)
    return
  end
  if self.changeSkill then
    self.model.RocoSkill:CancelSkill(self.changeSkill, UE4.ESkillActionResult.SkillActionResultInterrupted)
  end
  local skillObj = self.model.RocoSkill:AddSkillObjFromClassAndReturn(skillClass)
  if not skillObj then
    Log.DebugFormat("Highlight Skill Object not found %s", BattleConst.ChangePetEffect)
    return
  end
  skillObj:SetPassive(true)
  skillObj:SetCaster(self.model)
  skillObj:RegisterEventCallback("End", self, self.ChangeEffectOver)
  skillObj:RegisterEventCallback("Interrupt", self, self.ChangeEffectOver)
  skillObj:RegisterEventCallback("StartFailed", self, self.ChangeEffectOver)
  self.model.RocoSkill:LoadAndPlaySkill(skillObj)
  self.changeSkill = skillObj
end

function BattlePet:ChangeEffectOver()
  self:StopChangeEffect()
end

function BattlePet:StopChangeEffect()
  if self.model and self.model.RocoSkill and self.changeSkill then
    self.model.RocoSkill:CancelSkill(self.changeSkill, UE4.ESkillActionResult.SkillActionResultInterrupted)
  end
  self.changeSkill = nil
end

function BattlePet:SetTurnTo(target, immediately, animName, targetPos)
  if not (not self.destroyed and not self.card.petState:GetBackStab() and _G.BattleManager.battlePawnManager.VBattleField) or self.destroying then
    return
  end
  self.IsHeadBack = false
  if self.model and UE4.UObject.IsValid(self.model) then
    local aPos = self.model:Abs_K2_GetActorLocation()
    local rot = self.model:K2_GetActorRotation()
    local bPos
    if target and target.model and target.card then
      local RightPosTransForm = BattleManager.battlePawnManager.VBattleField:GetPositionInBattleMap(target.teamEnm, target.card.posInField)
      bPos = RightPosTransForm and RightPosTransForm.Translation
    elseif targetPos then
      bPos = targetPos
    end
    if not bPos or not aPos then
      Log.Error("zgx target is not valid")
      return
    end
    local dir = bPos - aPos
    local Rot = self.InitRotator
    if dir then
      dir.Z = 0
    end
    if dir and UE.FVector.IsNearlyZero(dir, 0.01) then
      Log.Warning("BattlePet:SetTurnTo  bPos - aPos is nearly zero")
      return
    end
    if dir then
      Rot = dir:ToRotator():Clamp()
    end
    if Rot then
      local detal = math.abs(Rot.Yaw - rot.Yaw)
      if detal < BattleConst.Define.BattlePetRotationErrorCheck then
        return
      elseif immediately then
        if self.model.ClearTargetRotator then
          self.model:ClearTargetRotator()
          self.model:K2_SetActorRotation(Rot, true)
        end
      elseif self.model.LerpToRotation then
        self.model:LerpToRotation(Rot)
        self.model:SetBpRotateRate(UE4.FRotator(360, 360, 360))
        if animName then
          self:PlayAnimByName(animName, 1, -1, 0, 0, 1, -1)
        end
      elseif self.model.ClearTargetRotator then
        self.model:ClearTargetRotator()
        self.model:K2_SetActorRotation(Rot, true)
      end
    end
  end
end

function BattlePet:ResetRotation(immediately, animName)
  if not (not self.destroyed and not self.card.petState:GetBackStab() and _G.BattleManager.battlePawnManager.VBattleField) or self.destroying then
    return
  end
  self.IsHeadBack = false
  if BattleUtils.Is1V1V1() and self.teamEnm == BattleEnum.Team.ENUM_ENEMY and not self.card.petInfo.battle_inside_pet_info.is_player_enemy then
    local Pets = _G.BattleManager.battlePawnManager:GetCanSelectAllPet(self.teamEnm)
    if #Pets > 1 then
      local aPos = _G.BattleManager.vBattleField:GetBattleFieldCenter()
      local HalfHeight = self:GetHalfHeight()
      aPos.Z = aPos.Z + HalfHeight
      local bPos
      for _, p in ipairs(Pets) do
        if not self.card:IsCheerPet() then
          if p ~= self then
            bPos = p:GetActorLocation()
            break
          end
        elseif not p.card:IsMyCheer(self.card) then
          bPos = p:GetActorLocation()
          break
        end
      end
      bPos = bPos or aPos
      local lookPos = UE.FVector(0.2 * bPos.X + 0.8 * aPos.X, 0.2 * bPos.Y + 0.8 * aPos.Y, HalfHeight)
      self:SetTurnTo(nil, immediately, animName, lookPos)
      return
    end
  end
  local enemyPets = _G.BattleManager.battlePawnManager:GetCanSelectAllPet(BattleUtils.GetEnemyTeamEnum(self.teamEnm))
  if 1 == #enemyPets and enemyPets[1].model then
    self:SetTurnTo(enemyPets[1], immediately, animName)
  else
    for _, v in ipairs(enemyPets) do
      if BattleUtils.IsFinalBattleP1() then
        if 2 == v.card.posInField then
          self:SetTurnTo(v, immediately, animName)
          return
        end
      elseif BattleUtils.IsB1FinalBattleP3() then
        if 1 == v.card.posInField then
          self:SetTurnTo(v, immediately, animName)
          return
        end
      elseif self.card.posInField == v.card.posInField then
        self:SetTurnTo(v, immediately, animName)
        return
      end
    end
    if self.InitRotator then
      if immediately then
        if self.model.ClearTargetRotator then
          self.model:ClearTargetRotator()
        end
        self.model:K2_SetActorRotation(self.InitRotator, true)
      elseif self.model.LerpToRotation then
        self.model:LerpToRotation(self.InitRotator)
        self.model:SetBpRotateRate(UE4.FRotator(360, 360, 360))
        if animName then
          self:PlayAnimByName(animName, 1, -1, 0, 0, 1, -1)
        end
      end
    end
  end
end

function BattlePet:GetTurnToTarget()
  if not (not self.destroyed and not self.card.petState:GetBackStab() and _G.BattleManager.battlePawnManager.VBattleField) or self.destroying then
    return nil
  end
  local enemyPets = _G.BattleManager.battlePawnManager:GetCanSelectAllPet(BattleUtils.GetEnemyTeamEnum(self.teamEnm))
  if 1 == #enemyPets and enemyPets[1].model then
    return enemyPets[1]
  else
    for _, v in ipairs(enemyPets) do
      if BattleUtils.IsFinalBattleP1() then
        if 2 == v.card.posInField then
          return v
        end
      elseif BattleUtils.IsB1FinalBattleP3() then
        if 1 == v.card.posInField then
          return v
        end
      elseif self.card.posInField == v.card.posInField then
        return v
      end
    end
  end
end

function BattlePet:HeadLookTick(deltaTime)
end

function BattlePet:SetLookAt(target, immediately)
  if BattleUtils.Is1V1V1() or BattleUtils.IsFinalBattle() or BattleUtils.IsTeam() then
    return
  end
  if self.buffComponent and self.buffComponent.petState and not self.buffComponent.petState:CanPlayAnim() then
    return
  end
  if not self.model then
    return
  end
  if UE4.UObject.IsValid(self.HeadLookAtComponent) then
    self.HeadLookAtComponent:ResetAutoLookAt()
    local specialConfig = BattleConst.LookAtSpecialConfig and BattleConst.LookAtSpecialConfig[self.CachePetBaseId]
    if specialConfig and target then
      local pitch = specialConfig[1] or 0
      local yaw = specialConfig[2] or 0
      self.HeadLookAtComponent:SetAutoLookAtParam(UE4.ELookAtParamType.Head, nil, UE4.ELookAtMode.None, "", pitch, yaw)
      self.HeadLookAtComponent:ActiveAutoLookAt(immediately, "Bip001-Neck", false, true)
    elseif target then
      self.HeadLookAtComponent:SetAutoLookAtParam(UE4.ELookAtParamType.Head, target)
      self.HeadLookAtComponent:ActiveAutoLookAt(immediately, "Bip001-Neck", false, true)
    end
  end
end

function BattlePet:ResetLookAt()
  if UE4.UObject.IsValid(self.HeadLookAtComponent) then
    self.HeadLookAtComponent:ResetAutoLookAt()
  end
end

function BattlePet:ToggleClickable(clickable)
  if clickable then
    self.CollideType = UE4.ECollisionEnabled.QueryOnly
  else
    self.CollideType = UE4.ECollisionEnabled.NoCollision
  end
  if self.MoveTarget then
    return
  end
  if self.model and UE4.UObject.IsValid(self.model) and self.model:IsA(UE.ARocoCharacter) then
    local CapsuleComponent = self.model.CapsuleComponent
    local ActionArea = self.model.ActionArea
    if CapsuleComponent and self.modelComponentCache[CapsuleComponent] ~= self.CollideType then
      self.modelComponentCache[CapsuleComponent] = self.CollideType
      CapsuleComponent:SetCollisionEnabled(self.CollideType)
    end
    if ActionArea and self.modelComponentCache[ActionArea] ~= self.CollideType then
      self.modelComponentCache[ActionArea] = self.CollideType
      ActionArea:SetCollisionEnabled(self.CollideType)
    end
  end
  self.CacheFloorPos = nil
end

function BattlePet:SetHighlight(needHighlight, isLasting)
  isLasting = isLasting or false
  if self.destroyed then
    return
  end
  if not self.model then
    return
  end
  if self.isHighlight == needHighlight then
    return
  end
  self.isHighlight = needHighlight
  if self.isHighlight then
    self:ShowTransparent(false)
    self:StartHighlight(BattleConst.Highlight.PetStart, isLasting)
  else
    self:StopHighlight()
  end
end

function BattlePet:StartHighlight(name, isLasting)
  if not name then
    return
  end
  if not self.isHighlight and self.highlightSkill then
    Log.DebugFormat("Highlight Skill Already playing %s", name)
    return
  end
  if self.DarkPlayer then
    self.DarkPlayer.isPlaying = false
    self.DarkPlayer:Stop()
  end
  local promise = BattleResourceManager:LoadUClassAsync(self, name, FPartial(self.HighlightSkillLoadSucc, self, name, isLasting))
end

function BattlePet:HighlightSkillLoadSucc(name, isLasting, skillClass)
  self:DelayHighLight(name, skillClass, isLasting)
end

function BattlePet:DelayHighLight(name, skillClass, isLasting)
  if not (self.model and self.model.RocoSkill) or not self.isHighlight then
    return
  end
  if not isLasting then
    if self.highlightSkill then
      self.model.RocoSkill:CancelSkill(self.highlightSkill, UE4.ESkillActionResult.SkillActionResultInterrupted)
    end
    local skillObj = self.model.RocoSkill:AddSkillObjFromClassAndReturn(skillClass)
    if not skillObj then
      Log.DebugFormat("Highlight Skill Object not found %s", name)
      return
    end
    skillObj:SetPassive(true)
    skillObj:SetCaster(self.model)
    skillObj:SetAdditions("Name", name)
    self.model.RocoSkill:LoadAndPlaySkill(skillObj)
    self.highlightSkill = skillObj
  else
    if not self.HighlightPlayer then
      self.HighlightPlayer = SkillPlayer(self.model.RocoSkill, self.model, BattleConst.PetHighlightLoop.Sequence)
    end
    if self.HighlightPlayer.isPlaying then
      return
    end
    self.HighlightPlayer:Toggle(true)
  end
end

function BattlePet:StopHighlight()
  if self.model and self.model.RocoSkill and self.highlightSkill then
    self.model.RocoSkill:CancelSkill(self.highlightSkill, UE4.ESkillActionResult.SkillActionResultInterrupted)
  end
  if self.HighlightPlayer then
    self.HighlightPlayer:Toggle(false)
  end
  self.highlightSkill = nil
  self.HighlightContex = nil
end

function BattlePet:SetDark(needDark)
  if self.destroyed then
    return
  end
  self.isDark = needDark
  if self.isDark then
    self:ToggleDark(true)
  else
    self:ToggleDark(false)
  end
end

function BattlePet:ToggleDark(on)
  if not self.model or not self.model.RocoSkill then
    return
  end
  if not self.DarkPlayer then
    if on then
      self.DarkPlayer = SkillPlayer(self.model.RocoSkill, self.model, BattleConst.CharacterDark.Sequence)
    else
      return
    end
  end
  self.DarkPlayer:Toggle(on)
end

function BattlePet:ShowTransparent(needTransparent, activeImmediately)
  if self.destroyed then
    return
  end
  if not self.transparentSkill then
    Log.Error("Battle Pet transparentSkill is nil")
    return
  end
  if needTransparent then
    self:SetHighlight(false)
  end
  self.transparentSkill:Toggle(needTransparent)
  if activeImmediately and self.transparentSkill.Current then
    self.transparentSkill.Current:ForceUpdateAction()
  end
end

function BattlePet:SetScale(scale)
  Log.DebugFormat("Setting scale of %s to %f", self.card.name, scale)
  if self.model then
    self.model:SetActorScale3D(UE4.FVector(scale, scale, scale))
  end
end

function BattlePet:SetGhost(isGhost)
  if self.destroyed then
    return
  end
  if not self.model then
    return
  end
  if self.isGhost == isGhost then
    return
  end
  self.isGhost = isGhost
end

function BattlePet:AllowCatch()
  if not BattleUtils.GetHasCatchInfo(self.card.petInfo.battle_inside_pet_info) then
    return true
  end
  local CatchPercent = self.card.petInfo.battle_inside_pet_info.catch_info.threshold / 10000
  local HealthPercent = self.health:GetHp() / self.health:GetMaxHp()
  return CatchPercent > HealthPercent
end

function BattlePet:UpdateEscapeInfo()
  _G.BattleEventCenter:Dispatch(BattleEvent.PET_RUNAWAY_CHANGE, self.card.petInfo.battle_inside_pet_info.escape_info)
end

function BattlePet:IsWild()
  return 0 == self.card.petInfo.battle_common_pet_info.gid
end

function BattlePet:IsNightMarePet()
  return self.card.petInfo.battle_common_pet_info.blood_id == Enum.PetBloodType.PBT_NIGHTMARE
end

function BattlePet:IsB1P1Pet()
  return BattleUtils.IsB1FinalBattleP1() and self.teamEnm == BattleEnum.Team.ENUM_ENEMY
end

function BattlePet:Hide()
  if self.model then
    self.model:SetActorScale3D(_G.FVectorZero)
  end
end

function BattlePet:GetPetID()
  return self.card.petInfo.battle_common_pet_info.base_conf_id
end

function BattlePet:GetPetGid()
  return self.card.petInfo.battle_common_pet_info.gid
end

function BattlePet:GetName()
  if self.model then
    return self.model:GetName()
  else
    return "no model"
  end
end

function BattlePet:IsSame(battlePet)
  Log.Dump(battlePet, 1, "battlePet::::")
  Log.Debug("BattlePet IsSame:", self.guid, battlePet.guid)
  return self.guid == battlePet.guid
end

function BattlePet:SetEnergy(value)
  if self.card then
    self.card:SetEnergy(value)
  end
end

function BattlePet:GetEnergy()
  if BattleUtils.IsB1FinalBattleP2() or BattleUtils.IsB1FinalBattleP3() then
    local curPoint = _G.BattleManager.battleRuntimeData:GetB1PhantomPoint()
    return curPoint
  end
  return self.card.petInfo.battle_common_pet_info.energy
end

function BattlePet:GetMaxEnergy()
  local card = self.card
  local petInfo = card and card.petInfo
  local insideInfo = petInfo and petInfo.battle_inside_pet_info
  local maxEnergy = insideInfo and insideInfo.max_energy or 10
  return maxEnergy
end

function BattlePet:SetAttachPoint()
  if self.teamEnm == BattleEnum.Team.ENUM_TEAM then
    self:SetTeamAttachPoint()
  else
    self:SetEnemyAttachPoint()
  end
end

function BattlePet:SetTeamAttachPoint()
  if BattleUtils.IsTeam() then
    if 1 == self.card.posInField then
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_TeamPlayerPet1
    elseif 2 == self.card.posInField then
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_TeamPlayerPet2
    elseif 3 == self.card.posInField then
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_TeamPlayerPet3
    else
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_TeamPlayerPet4
    end
  elseif BattleUtils.IsFinalBattleP1() then
    if 1 == self.card.posInField then
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_A1FinalP1PlayerPet1
    elseif 2 == self.card.posInField then
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_A1FinalP1PlayerPet2
    elseif 3 == self.card.posInField then
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_A1FinalP1PlayerPet3
    else
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_A1FinalP1PlayerPet1
    end
  elseif BattleUtils.IsB1FinalBattleP1() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_B1FinalP1PlayerPet1
  elseif BattleUtils.IsB1FinalBattleP2() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_B1FinalP2PlayerPet1
  elseif BattleUtils.IsB1FinalBattleP3() then
    if 1 == self.card.posInField then
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_B1FinalP3PlayerPet1
    elseif 2 == self.card.posInField then
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_B1FinalP3PlayerPet2
    elseif 3 == self.card.posInField then
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_B1FinalP3PlayerPet3
    else
      self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_B1FinalP3PlayerPet4
    end
  elseif self.card.posInField >= 2 or self.card:IsCheerPet() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_2V2PlayerPet2
  elseif 1 == _G.BattleManager.battleRuntimeData.playerPetNumber then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_1V1PlayerPet1
  else
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_2V2PlayerPet1
  end
end

function BattlePet:SetEnemyAttachPoint()
  if BattleUtils.IsTeam() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_TeamEnemyPet1
  elseif BattleUtils.IsFinalBattleP1() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_A1FinalP1EnemyPet1
  elseif BattleUtils.IsFinalBattleP2() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_A1FinalP2EnemyPet1
  elseif BattleUtils.IsB1FinalBattleP1() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_B1FinalP1EnemyPet1
  elseif BattleUtils.IsB1FinalBattleP2() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_B1FinalP2EnemyPet1
  elseif BattleUtils.IsB1FinalBattleP3() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_B1FinalP3EnemyPet1
  elseif self.card.posInField >= 2 or self.card:IsCheerPet() then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_2v2EnemyPet2
  elseif 1 == _G.BattleManager.battleRuntimeData.enemyPetNumber then
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_1v1EnemyPet1
  else
    self.AttachPoint = UE4.EBattleFieldAttachPoint.Pos_2v2EnemyPet1
  end
end

function BattlePet:GetAttachPoint()
  return self.AttachPoint
end

function BattlePet:GetPosInField()
  local posMap = BattleManager.vBattleField:GetTeamPositionMap(self.teamEnm)
  if self.card:IsInBattle() then
    return posMap:Get(self.card.posInField):Abs_K2_GetActorLocation()
  else
    Log.Error("\230\179\168\230\132\143\239\188\154\231\178\190\231\129\181\228\184\141\229\156\168\230\136\152\229\156\186\228\184\138")
    return FVectorZero
  end
end

function BattlePet:ShowSkillPrediction()
  local info = BattleUtils.GetSkillPredictionByPlayer(self)
  if info and info.no_show == false and self.battlePetComponents and info.hint_level ~= ProtoEnum.SkillHintLevel.LEVEL_F then
    if self.card.petState:GetMimic() then
      return
    end
    if info.show_word then
      if not self.IsShowSkillPrediction then
        self.IsShowSkillPrediction = true
        local worldConfig = _G.DataConfigManager:GetAiWordConf(info.word_conf_id)
        if worldConfig and worldConfig.hint_info[info.word_conf_index + 1] then
          local wordInfo = worldConfig.hint_info[info.word_conf_index + 1]
          if wordInfo.action then
            self:PlayAnimByName(wordInfo.action, 1, 0, 0, 0, 1, 0)
          end
        end
      end
    else
      self:UpdateSkillPrediction(info)
      self.battlePetComponents:ShowSkillPredictionUI()
    end
  end
end

function BattlePet:HideSkillPrediction()
  if self.battlePetComponents then
    self.battlePetComponents:HideSkillPredictionUI()
  end
end

function BattlePet:UpdateSkillPrediction(info)
  self.battlePetComponents:UpdateSkillPredictionUI(info)
end

function BattlePet:CanBePredicted()
  local info = BattleUtils.GetSkillPredictionByPlayer(self)
  if info then
    if self.card.petState:GetMimic() then
      return false
    end
    if info.hint_level ~= ProtoEnum.SkillHintLevel.LEVEL_S and info.hint_level ~= ProtoEnum.SkillHintLevel.LEVEL_F then
      return true
    end
  end
  return false
end

function BattlePet:PinOnTheGround()
  self.perception:PinOnTheGround()
end

function BattlePet:GetHalfHeight()
  if self.model and UE4.UObject.IsValid(self.model) and self.model.GetHalfHeight then
    return self.model:GetHalfHeight()
  end
  Log.Warning("BattlePet:GetHalfHeight, trying to call a nil GetHalfHeight on model")
  return 0
end

function BattlePet:SetIKEnable(boo)
  local result = self.perception:SetIKEnable(boo)
  return result
end

function BattlePet:GetCanSwimming()
  return self.IsCanSwimming
end

function BattlePet:IsAquatic()
  if self.card:CheckIsMimic() then
    return false
  end
  local petBaseConf = self.card:GetPetBaseConfThroughMimic()
  if not petBaseConf or 1 ~= petBaseConf.can_swim then
    return false
  end
  local modelId = petBaseConf.model_conf or 0
  local modelConf = DataConfigManager:GetModelConf(modelId, true)
  if not modelConf then
    return false
  end
  if table.contains(modelConf.pet_habitat_flag, Enum.HABITAT_FLAG.HAB_WATER) and BattleUtils.IsWaterBattle() or table.contains(modelConf.pet_habitat_flag, Enum.HABITAT_FLAG.HAB_LAVA) and BattleUtils.IsLavaBattle() then
    return true
  end
  return false
end

function BattlePet:GetCanFly()
  return self.IsCanFly
end

function BattlePet:ChangeCollideToMove()
  if not UE4.UObject.IsValid(self.model) then
    return
  end
  if self.model.CapsuleComponent then
    self.model.CapsuleComponent:SetCollisionProfileName("NPCCharacterFree")
  else
    Log.Error("battle pet model lost CapsuleComponent: ", self.card.name)
  end
  if self.model.ActionArea then
    self.model.ActionArea:SetCollisionProfileName("NoCollision")
  end
  if self.model.CharacterMovement then
    self.model.CharacterMovement.MaxWalkSpeed = 600
    self.model.CharacterMovement:SetComponentTickEnabled(true)
    self.model.CharacterMovement:SetOverridenMoveAnim(self.MovementMode)
  end
end

function BattlePet:IsMoving()
  return self.MoveTarget ~= nil or nil ~= self.RealMoveTarget
end

function BattlePet:MoveTo(TargetPosition, IsJumpWhenFail, CallBack, ...)
  if self.destroying or self.destroyed then
    Log.Error("zgx BattlePet that was destroyed can not move")
    return
  end
  if self.MoveToProxyObj then
    self.MoveToProxyObj = nil
    self.model:GetController():StopMovement()
  end
  self.RealMoveTarget = UE.FVector(TargetPosition.X, TargetPosition.Y, TargetPosition.Z)
  self.MoveTarget = BattleUtils.GetNavInvalidPos(TargetPosition, self.model:Abs_K2_GetActorLocation())
  self.MoveTimeLimit = 6
  self:ChangeCollideToMove()
  self.MoveCallBack = CallBack
  self.IsJumpWhenFail = IsJumpWhenFail
  self.MoveCallBackParam = {
    ...
  }
  local control = self.model:GetController()
  if not (self.model and nil ~= self.model.AIControllerClass and control) or not self.MoveTarget then
    self:MoveFail()
    return
  end
  local pos = UE4.FVector(self.MoveTarget.X, self.MoveTarget.Y, self.MoveTarget.Z)
  pos = SceneUtils.ConvertAbsoluteToRelative(pos)
  self.MoveToProxyObj = UE4.UAIBlueprintHelperLibrary.CreateMoveToProxyObject(UE4Helper.GetCurrentWorld(), control:K2_GetPawn(), pos, nil, BattleConst.AcceptanceRadius)
  local handlerSuccess = SimpleDelegateFactory:CreateCallback(self, self.MoveSuccess)
  self.MoveToProxyObj.OnSuccess:Add(self.model, handlerSuccess)
  local handlerFail = SimpleDelegateFactory:CreateCallback(self, self.MoveFail)
  self.MoveToProxyObj.OnFail:Add(self.model, handlerFail)
end

function BattlePet:MoveSuccess(MovementResult)
  if self.model.CapsuleComponent then
    self.model.CapsuleComponent:SetCollisionProfileName("NPCCharacter")
  end
  self:ClearMove()
  self.MoveTarget = nil
  if self.model.CharacterMovement then
    self.model.CharacterMovement.MaxWalkSpeed = 0
    self.model.CharacterMovement:SetComponentTickEnabled(false)
  end
  local CurPos = self:GetActorLocation()
  if self.RealMoveTarget then
    local TargetPos = UE.FVector(self.RealMoveTarget.X, self.RealMoveTarget.Y, CurPos.Z)
    if CurPos:Dist(TargetPos) > 100 and self.IsJumpWhenFail then
      local JumpTarget = UE4.UNRCStatics.PinActorOnGround(nil, self.model, SceneUtils.ConvertAbsoluteToRelative(self.RealMoveTarget), self.model)
      self:JumpToLocation(JumpTarget, self, self.RecoverMoveState)
      return
    end
  end
  self:RecoverMoveState()
end

function BattlePet:MoveFail(MovementResult)
  self:ClearMove()
  self.MoveTarget = nil
  if self.model and UE.UObject.IsValid(self.model.CharacterMovement) then
    self.model.CharacterMovement.MaxWalkSpeed = 0
    self.model.CharacterMovement:SetComponentTickEnabled(false)
  end
  local CurPos = self:GetActorLocation()
  if self.RealMoveTarget then
    local TargetPos = UE.FVector(self.RealMoveTarget.X, self.RealMoveTarget.Y, CurPos.Z)
    if CurPos:Dist(TargetPos) > 100 and self.IsJumpWhenFail then
      local JumpTarget = UE4.UNRCStatics.PinActorOnGround(nil, self.model, SceneUtils.ConvertAbsoluteToRelative(self.RealMoveTarget), self.model)
      self:JumpToLocation(JumpTarget, self, self.RecoverMoveState)
      return
    end
  end
  self:RecoverMoveState()
end

function BattlePet:JumpToLocation(targetPoint, Caller, CallBack)
  local skillComponent = self.model.RocoSkill
  if not skillComponent then
    CallBack(Caller)
    return
  end
  if self.JumpSkillObj then
    Log.Error("zgx pet is playing Jump already!! ", self.card.name)
    skillComponent:CancelSkill(self.JumpSkillObj, UE4.ESkillActionResult.SkillActionResultInterrupted)
    self:JumpOver(nil, self.JumpSkillObj)
  end
  local g6SkillClass = BattleResourceManager:GetCacheAssetDirect(BattleConst.AI_BattlePetJumpToLocation_C)
  local BattlePet2 = self:GetTurnToTarget()
  local skillObj = skillComponent:AddSkillObjFromClassAndReturn(g6SkillClass)
  skillObj:SetCaster(self.model)
  if BattlePet2 and BattlePet2.model then
    skillObj:SetTargets({
      BattlePet2.model
    })
  elseif _G.BattleManager.battlePawnManager.VBattleField then
    local posActor = _G.BattleManager.battlePawnManager.VBattleField:GetPositionActorInBattleMap(BattleEnum.Team.ENUM_ENEMY, 1)
    if posActor then
      skillObj:SetTargets({posActor})
    else
      skillObj:SetTargets({
        self.model
      })
    end
  else
    skillObj:SetTargets({
      self.model
    })
  end
  skillObj:SetPassive(true)
  skillObj:RegisterEventCallback("End", self, self.JumpOver)
  skillObj:RegisterEventCallback("Interrupt", self, self.JumpOver)
  skillObj:RegisterEventCallback("StartFailed", self, self.JumpOver)
  self.JumpTarget = UE4.FVector(targetPoint.X, targetPoint.Y, targetPoint.Z)
  self.JumpOverCaller = Caller
  self.JumpOverCallBack = CallBack
  self.JumpSkillObj = skillObj
  local Blackboard = skillObj:GetBlackboard()
  Blackboard:SetValueAsVector("TargetLocation", targetPoint)
  Blackboard:SetValueAsInt("MaxMoveTime", 1)
  skillComponent:LoadAndPlaySkill(skillObj)
end

function BattlePet:JumpOver(name, skill)
  if self.JumpSkillObj and skill == self.JumpSkillObj then
    local CurPos = self:GetActorLocation()
    if self.JumpTarget and self.model then
      local TargetPos = UE.FVector(self.JumpTarget.X, self.JumpTarget.Y, CurPos.Z)
      if CurPos:Dist(TargetPos) > 100 then
        self.model:K2_SetActorLocation(self.JumpTarget, false, nil, false)
      end
    end
    if self.JumpOverCallBack then
      self.JumpOverCallBack(self.JumpOverCaller)
    end
    self.JumpOverCaller = nil
    self.JumpOverCallBack = nil
    self.JumpTarget = nil
    self.JumpSkillObj = nil
    self:ResetRotation()
  end
end

function BattlePet:RecoverMoveState()
  self:SetClickable(self.clickable)
  if self.MoveCallBack then
    self.MoveCallBack(table.unpack(self.MoveCallBackParam))
  end
  self.MoveCallBack = nil
  self.MoveCallBackParam = nil
  self.IsJumpWhenFail = nil
  self.RealMoveTarget = nil
  self:ResetRotation()
end

function BattlePet:ClearMove()
  if self.MoveToProxyObj then
    self.MoveToProxyObj:Release()
    self.MoveToProxyObj = nil
  end
end

function BattlePet:StartRandomMove()
  self.RandomMoveDetal = math.random(5, 10)
  self.MovementMode = 1
end

function BattlePet:StopRandomMove()
  self.RandomMoveDetal = -1
  self.MovementMode = 2
end

function BattlePet:BindAttackPlayer(atkPlayer)
  table.insert(self.attackPlayers, atkPlayer)
end

function BattlePet:UnbindAttackPlayer(atkPlayer)
  for k, v in pairs(self.attackPlayers) do
    if v == atkPlayer then
      table.remove(self.attackPlayers, k)
    end
  end
end

function BattlePet:BindBuffPlayer(buffPlayer)
  table.insert(self.buffPlayers, buffPlayer)
end

function BattlePet:UnbindBuffPlayer(buffPlayer)
  for k, v in pairs(self.buffPlayers) do
    if v == buffPlayer then
      table.remove(self.buffPlayers, k)
    end
  end
end

function BattlePet:ShowPreselectTips()
  if self.battlePetComponents and self.model then
    local groundPos = LineTraceUtils.GetPointValidLocationByLine(self:GetActorLocation(), self:GetHalfHeight())
    if self.battlePetComponents.SelectMarker3dOffsetPC then
      self.battlePetComponents.SelectMarker3dOffsetPC:Abs_K2_SetWorldLocation(groundPos, false, nil, false)
    end
    self.battlePetComponents:ShowSelectMarker3dPC(true)
    self.battlePetComponents:ShowSelectSureKeyUI(true)
    self:RefreshSelectSureKeyUI()
  end
end

function BattlePet:HidePreselectTips()
  if self.battlePetComponents then
    self.battlePetComponents:ShowSelectMarker3dPC(false)
    self.battlePetComponents:ShowSelectSureKeyUI(false)
  end
end

function BattlePet:RefreshSelectSureKeyUI()
  if self.battlePetComponents then
    self.battlePetComponents:RefreshSelectSureKeyUI()
  end
end

function BattlePet:PlayAnim(animName, rate, position, BlendInTime, BlendOutTime, LoopCount, endPosition)
  if not self.buffComponent:IsCanPlayAnimation(animName) then
    return 0
  end
  Log.Warning(self.card.name .. "  play AnimationName ", animName)
  self.lastAnimSkill = nil
  return self.model:PlayAnimByName(animName, rate, position, BlendInTime, BlendOutTime, LoopCount, endPosition)
end

function BattlePet:StopAnim(Name, blendOutTime, LinkedTag)
  local AnimComp = self:GetAnimComponent()
  if AnimComp then
    blendOutTime = blendOutTime or 0
    LinkedTag = LinkedTag or "None"
    return AnimComp:StopAnimByName(Name, blendOutTime, LinkedTag)
  else
    Log.Warning("[SceneCharacter:StopAnim] cant find URocoAnimComponent")
  end
  return false
end

function BattlePet:GetAnimComponent()
  if not self.model then
    return
  end
  if not self.model.GetAnimComponent then
    return
  end
  local AnimComp = self.model:GetAnimComponent()
  if AnimComp then
    return AnimComp
  end
  AnimComp = self.model:GetComponentByClass(UE4.URocoAnimComponent)
  return AnimComp
end

function BattlePet:StopAllMontage(BlendOut)
  local AnimComp = self:GetAnimComponent()
  if AnimComp and UE.UObject.IsValid(AnimComp) then
    return AnimComp:StopAllMontage(BlendOut or 0.1)
  end
  return false
end

function BattlePet:DoHeadMotion(MotionType)
  if not self.model then
    Log.Error("No view")
    return
  end
  if MotionType == Enum.HeadMotion.Nod and self.model.Event_Action_Yes then
    self.model:Event_Action_Yes()
  elseif MotionType == Enum.HeadMotion.Shake and self.model.Event_Action_No then
    self.model:Event_Action_No()
  elseif MotionType == Enum.HeadMotion.Lookup and self.model.Event_Action_Lookup then
    self.model:Event_Action_Lookup()
  end
end

function BattlePet:GetActorTransform()
  if self.model then
    return self.model:Abs_GetTransform()
  end
  return UE4.FTransform()
end

function BattlePet:GetActorLocation()
  if self.model and UE4.UObject.IsValid(self.model) then
    return self.model:Abs_K2_GetActorLocation()
  end
  return UE4.FVector(0, 0, 0)
end

function BattlePet:GetActorRotation()
  if self.model then
    return self.model:K2_GetActorRotation()
  end
  return UE4.FRotator(0, 0, 0)
end

function BattlePet:GetActorScale3D()
  if self.model then
    return self.model:GetActorScale3D()
  end
  return UE4.FVector(1, 1, 1)
end

function BattlePet:SetSelectMarkColorIndex(index)
  local PcSelectActor = self.battlePetComponents.SelectMarker3dPC:GetChildActor()
  if UE4.UObject.IsValid(PcSelectActor) then
    PcSelectActor.colorIndex = index
    PcSelectActor:OnChangeColor()
  end
end

function BattlePet:GetAttrType()
  return BattleConst.BloodType2AttrType[self.card:GetBloodId()]
end

function BattlePet:GetBallPath()
  return self.card:GetBallPath()
end

function BattlePet:InitPetRTPC()
  if not self.model then
    return
  end
  if self.card and self.card.petInfo and self.card.petInfo.battle_common_pet_info then
    local voice = self.card.petInfo.battle_common_pet_info.voice or 0
    _G.NRCAudioManager:SetEmitterRTPC("Pet_Vo_Pitch", voice, self.model)
    if self.card.owner and self.card.owner.roleInfo and self.card.owner.roleInfo.base and self.card.petInfo.battle_inside_pet_info then
      Log.Debug("BattlePet:InitPetRTPC('Pet_Vo_Pitch',", voice, ")  userName:", self.card.owner.roleInfo.base.name, " petPos:", self.card.petInfo.battle_inside_pet_info.pos)
    end
  else
  end
  if BattleUtils.IsTeam() then
    if self.teamEnm == BattleEnum.Team.ENUM_ENEMY then
      if BattleUtils.IsBloodTeam() or BattleUtils.IsStoryTeam() then
        _G.NRCAudioManager:SetEmitterRTPC("Pet_Battle_Team", 3, self.model)
      else
        _G.NRCAudioManager:SetEmitterRTPC("Pet_Battle_Team", 4, self.model)
      end
    elseif self.player == BattleManager.battlePawnManager.TeamatePlayer then
      _G.NRCAudioManager:SetEmitterRTPC("Pet_Battle_Team", 1, self.model)
    else
      _G.NRCAudioManager:SetEmitterRTPC("Pet_Battle_Team", 2, self.model)
    end
  elseif self.card and self.card.petState:GetNightmare() then
    _G.NRCAudioManager:SetEmitterRTPC("Pet_Battle_Ruzhan", 2, self.model)
  else
    _G.NRCAudioManager:SetEmitterRTPC("Pet_Battle_Ruzhan", 1, self.model)
  end
end

function BattlePet:DedupBuffPopupQueue()
  if self.buffAEffectPopupComponent then
    self.buffAEffectPopupComponent:DedupBuffPopupQueue()
  end
end

function BattlePet:TurnEndBuffModeAnimQue()
  if self.battlePetComponents and UE4.UObject.IsValid(self.battlePetComponents) then
    self.battlePetComponents:TurnEndBuffModeAnimQue()
  end
end

function BattlePet:GetHeadLookAtComponent()
  return self.model and self.model.BP_HeadLookAtComponent
end

function BattlePet:GetMimicStaticMesh()
  local model = self.model
  local MimicActorComponent = model and model.MimicActor
  local MimicStaticMesh
  if UE.UObject.IsValid(MimicActorComponent) then
    local MimicActor = MimicActorComponent:GetChildActor()
    if UE.UObject.IsValid(MimicActor) then
      local StaticMesh = MimicActor.StaticMesh
      if UE.UObject.IsValid(StaticMesh) then
        MimicStaticMesh = StaticMesh
      end
    end
  end
  return MimicStaticMesh
end

function BattlePet:RefreshCapsuleInfo()
  if self.battlePetComponents and UE4.UObject.IsValid(self.battlePetComponents) then
    self.battlePetComponents:UpdateCapsuleInfo()
  end
end

return BattlePet
