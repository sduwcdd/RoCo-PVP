# 客户端主动换人门禁组件

日期：2026-10-26。范围仅为带显式运行时输入的主动换人研究片段；本组件不证明服务端执行相同校验，也不补造当前 PVP 冷却配置。

## 游戏文件依据

- `artifacts/unpack_probe_20261025/battle_analysis/pakchunk4-WindowsNoEditor_14_P/BattleUtils.luac.decompiled.lua`，SHA-256 `9a4615926d2ff4037198845943ec9952bde197a9169457e54dab0f6eb35ec4b9`：`CheckCanChangePet()`（578–598）读取 `exchange_initial_cold`、`roundIndex`、`lastChangePetRoundIndex`、`exchange_cold`；`GetPetBit()`（533–541）读取按32位分组的 `state_bits`；`GetCanChangePetConfig()`（2042–2047）对缺少的 `can_changepet` 使用0。
- 同文件的 `CheckIfChangePetBan()`（600–605）将 `PET_BIT_TYPE.BT_BAN_STATUS_CHANGE_PET` 传给 `GetPetBit()`。
- `artifacts/unpack_probe_20261025/battle_analysis/pakchunk4-WindowsNoEditor_27_P/ProtoEnum.luac.disassembly.txt`，SHA-256 `2785fe414873eeea8ae83d4000163eecab14b18dc49b4e23315b33a8d362ae5b`：`BT_BAN_STATUS_CHANGE_PET = 16`（36239–36242）。配合 `GetPetBit()` 可还原为首个状态字的 `1 << 16`。
- `artifacts/unpack_probe_20261025/battle_analysis/pakchunk4-WindowsNoEditor_3_P/RoundSwapAction.luac.decompiled.lua`，SHA-256 `135a263eecae3ee8b4ab438794ff59804629b9dc768c0eb86a7cc39d509ecf27`：换人界面逐只应用禁换状态位检查（75–90）。在本次检查的反编译脚本中，没有找到 `CheckCanChangePet()` 的调用点；不能把函数存在等同于确认它已用于每一种 PVP 换人入口。

现有解析的 `BATTLE_CONF` 表中未找到 `exchange_initial_cold` 或 `exchange_cold` 字段值；本轮可读的26个代表脚本中没有找到 `lastChangePetRoundIndex` 的赋值点。这不能证明其他未反编译客户端模块或在线服务端不存在这些赋值。因此冷却配置与上次换人回合的生产者仍未知。`can_changepet` 的字段虽在已解析 PVP 配置出现，但本组件不把模式配置扩展到未提供的战斗实例。

## 实现行为

`lab/switch_rules.py` 以来源文件哈希绑定门禁公式，并区分明确无上次换人（显式 `last_change_round_index: null` 或 `0`）与未提供观测。始终需要当前回合与初始冷却；只有存在非零上次换人回合时才需要 `exchange_cold`，与客户端在早退后才读取该值的分支一致。缺少当前回合、必需冷却值、模式权限、禁换状态或上次换人观测时返回 `unresolved`。状态位优先从游戏状态字解码；若调用者同时提供的布尔值与状态字矛盾，则拒绝该输入。

`lab/switch_runtime.py`、`lab/research_phases.py` 与 `lab/simulation.py` 仅在调用者包含 `switch_cooldown` 时运行此门禁。兼容无该对象的既有研究片段；这条旧路径依然不应用门禁，故完整对战标记继续为 false。门禁拒绝时不改局面、不产生活动事件。模拟引擎标记更新到 `composable-battle-20261026-4`，避免继续接受按旧版本准备的本地试战状态。

## 验证与边界

回归覆盖初始/重复冷却边界、模式禁用、禁换位、来源字节解析、输入缺失、显式空历史、客户端早退分支（尚未换人时不要求重复冷却）、状态字/布尔冲突及拒绝后的状态隔离。最终126项相关回归通过，具体测试命令与结果记录在工作台状态文件的 `latest_switch_gate_update` 字段。

本功能是客户端代码导出的规则实验，`real_game_verified=false`、`calibrated=false`、`training_eligible=false`。未确认在线版本、服务端实际校验、当前 PVP 模式冷却数值以及冷却字段写入时序；这些不影响已实现的来源门禁代码测试，但限制其游戏还原结论。
