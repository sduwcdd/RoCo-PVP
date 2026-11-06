# 客户端战斗逻辑追踪（2026-10-25）

本轮复用已验证解包栈，新增读取 37 个 `pakchunk4` 包目录，选择性提取 15 个脚本，全部完整结构解析及反编译成功。安装目录只读；原始字节、转换后字节、字符串、反编译文件及 SHA-256 保留在 `artifacts/game_logic_followup_20261025`。各包索引校验、源字节区间前后哈希和文件属性检查均通过，见该目录 `manifest.json` 和 `dependency_directory_matches.json`。未执行游戏 Lua。

**结论：找到了完整配置枚举和更明确的客户端消费边界，尚未找到真实伤害计算公式或权威事件调度器。** 不能由这批客户端模块主要消费同步结果，推出完整结算一定只在服务端。

## 可以复用的新增文件

- `scripts/pakchunk4-WindowsNoEditor_27_P/Enum.luac.decompiled.lua`：`Data.Config.Enum` 的完整可读结果；应按各字段所引用枚举分别绑定，不能按数字巧合合并。
- `scripts/pakchunk4-WindowsNoEditor_3_P/GlobalConfig.luac.decompiled.lua`：第 99 行文件默认 `DisableBinData=false`，不证明运行中没有覆盖。
- 同目录 `BinDataManager.luac.decompiled.lua`：压缩二进制加载依赖；加载及缺省字段评估由本轮另一份来源审计负责。
- 同目录技能、状态和表现相关 12 个脚本，具体清单、候选包及输出哈希见 manifest。

以上路径相对 `artifacts/game_logic_followup_20261025`。使用最高数字补丁后缀选择候选，**尚未确认实际挂载优先级和在线覆盖**。`Enum` 候选来自补丁 27，其余 14 个来自补丁 3。

## 已查明的调用及数据流

### 技能消耗与可选择条件

`Skill:Init`（21–50 行）读取基础 `cd_round[1]`，但携带回合数据时，当前能耗来自 `skillRoundData.cost_energy`。`RefreshByServer`（53–66 行）用传入 `cd_round` 减当前回合偏移计算客户端倒计时，并更新下发能耗。

`CanCast`（77–126 行）检查禁用状态、客户端冷却和能量/生命条件；`display_hp` 路径中当前生命小于等于 `cost_hp` 时不能选。`IsCostEnergy`/`IsCostRoleHp`（133–138 行）绑定 `energy_rule` 与 `Enum.EnergyRule.ER_ROLEHP`。`GetInitEnergy`（141–143 行）才直接返回配置 `energy_cost[1]`。

这些证据适合说明客户端输入检查与动态消耗来源，不能直接决定选招后遭扣能时是否取消动作、实际扣款时点、生命边界的所有在线模式。局部 `or 0` 是该函数的缺省处理，不能扩展为整张配置表的缺省值规则。

`GetHighestDamage`/`GetDamageByDamageParamsAndPetId`（210–244 行）只读取下发 `skillData.damage_params`，未计算攻击、防御、克制、随机浮动或取整。

### 伤害表现

新增 `BattleDamagePlayer:ShowDamageNumber`（28 行起）使用现有 `performInfo.damage_info`，调用已有 `BattleDataCenter:WriteDamageInfo`，再发送 `HitBattlePet` 表现事件。

已有 `BattleDataCenter:WriteDamageInfo`（379–454 行）读取 `sync_data.pet_sync_info` 中的 `damage_result`、`hp_change`、`hp_result`。412、414 行的 `ceil` 将总伤害分配为多次显示；最后按给定的 `hp_result` 更新。这是**显示拆段取整，不是攻击/防御伤害公式**。`DoWrite`（14 行起）、`SyncEnergy`（327 行起）、`SyncSkill`（343 行起）同样消费同步结果。

### 效果、状态消费及有限参数绑定

`BattleEffectPlayer:Play`（31–105 行）在 `isPureLogicMode` 时直接结束，其余路径读取 `effect_trigger` 和结果参数用于弹字/动画。`effect_order` 与 `Enum.EffectType` 比较，可作为字段到枚举族的直接消费证据；没有能量转移或伤害计算。

能直接定位的一个参数是 `ET_ANIMATION` 的 `effect_param[1].params[1]`，在 91–100 行作为动画 ID。不能据此假设其他效果的第一参数也为动画或数值量。

`Buff:Refresh`（52 行起）复制传入 `caster_id`、`append_round`、`stack` 和描述参数；`BuffComponent:RefreshBuffs`/`ChangeBuffData`（135–236 行）按下发增删改协调本地状态，并未执行加层、衰减或伤害公式。

`BuffComponent:CheckIsSpecialBuff`（330–350 行）对 `BattleUtils.IsBuff152` 找到的基础状态，以 `buffbase_param[1].params[1]` 比较 `Enum.UIEffectTargetType` 的屏幕、精灵、全部技能目标，并分派 UI 事件。这是这一特定 UI 状态的参数证据，不能推广到全部基础状态。

已有 `SkillUtils`（89–122 行）提供 ID 分类：技能 `[200000,300000)` 或 `[7000000,8000000)`；状态 `[20000000,29999999]`；基础状态 `[2000000,2999999)`；效果 `[1000000,1999999]`。这里保留源码端点原样，不“修正”端点。这些是客户端辅助函数，不代替数据表实际存在性校验。

### 客户端通知顺序

已有 `BattleNetManager:ZoneBattleRoundStartNotify`（272–289 行）可将回合开始通知中的 `perform_cmd` 提取为先入缓存的表现通知，再缓存回合开始通知。`CacheNotify`（424–446 行）尾插通知；`ProcessMainProcess`（452 行起）在场景/状态就绪后调用 `ExecuteCachedNotify`；后者（542–581 行）取队首、移除、发送对应事件。

这是**客户端通知消费与播放顺序**；没有给出同速双方、状态与特性嵌套、替补入场或死亡处理的权威优先级。`BattleCmdQueue` 的 `Push`/`Pop` 等是空实现，不能拿名称作调度器证据。新增 `BattleRoundPlayEndCheck` 只复位镜头/遮罩等，不是回合结束结算器。

已有 `SkillUtils:GetSkillEventTime`/`ParseCmToEvent`（237–251 行）通过 `BattleConst.CmToSkillEventDict` 将某处 `castMoment` 映射到技能表现时间；这不建立它与所有配置 `cast_moment` 或 `trigger_type` 数值的一一对应。

## 本轮没有证据支持的结论

1. 精确伤害公式、修正乘区、随机分布及每一步取整。
2. 实际效果执行器如何解释全部 `effect_param`、`buffbase_param`、触发条件参数。
3. 真实结算队列与嵌套触发、双方同速、死亡/入场、能耗检查的顺序。
4. 全部结算是否在客户端或服务端；这里只检查了原有代表脚本及新增 15 个脚本，未逐个反编译搜索全部 603 个命中脚本，也未分析原生代码。
5. 当前候选文件就是运行时胜出的配置，或在线玩法完全使用该版本默认值。

下一步优先使用新增 `Data.Config.Enum` 建立有来源的字段枚举映射，保留未知参数顺序。若继续追踪客户端节点组装，可定向检查已知目录中的 `BattlePerformNode`、`BattlePerformNodeBase`、`BattleWaitRoundPlayAction` 与对应播放器；这些仍可能是表现分组，不能预先称为权威执行器。若出现原生函数调用，先保存调用边界，再决定是否有可读实现可查。

本轮没有自动覆盖现有有效规则，没有将配置可读/枚举命名计为完整对战可执行或实战已校准。
