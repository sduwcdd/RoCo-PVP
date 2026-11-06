# 能量上限读取位置已定位：优先运行时 max_energy，缺失时为 10

2026-10-25。本轮读取和提取游戏客户端脚本，未修改模拟器、主对话文档或游戏安装文件。

## 直接代码

原包：`pakchunk4-WindowsNoEditor_3_P.pak`。

原路径：`../../../NRC/Content/ScriptC/NewRoco/Modules/Core/Battle/Entity/BattlePet.luac`。

解码反编译结果 `utils/raw/pakchunk4-WindowsNoEditor_3_P/NRC/Content/ScriptC/NewRoco/Modules/Core/Battle/Entity/BattlePet.decompiled.lua:1859`：

```lua
function BattlePet:GetMaxEnergy()
  local card = self.card
  local petInfo = card and card.petInfo
  local insideInfo = petInfo and petInfo.battle_inside_pet_info
  local maxEnergy = insideInfo and insideInfo.max_energy or 10
  return maxEnergy
end
```

即优先读取该精灵对战状态中的 `max_energy`；字段缺失时返回 10。这个函数没有读取 `character_max_energy`，也没有把 9 加一。Lua 中数字 0 为真值，因此该回退不是把 max_energy=0 变成 10。

为排除仅依赖高级反编译输出，本轮另用反汇编核对同一函数：读取 `max_energy` 后存在 `loadi r4 10` 回退分支，随后返回 r4。详见 `GetMaxEnergy.disassembled.txt` 和 `bytecode_check.json`。

## 运行时值来源

1. 既有提取结果 `unpack_probe_20261025/battle_analysis/pakchunk4-WindowsNoEditor_3_P/BattleDataCenter.luac.decompiled.lua:699` 的 `WritePetSyncInfo` 处理同步信息。
2. 第 718 行读取 `data.max_energy`，第 720 行调用 `battleCard:SetMaxEnergy(maxEnergy)`。
3. 本轮 `raw/pakchunk4-WindowsNoEditor_3_P/NRC/Content/ScriptC/NewRoco/Modules/Core/Battle/Entity/Card/BattleCard.decompiled.lua:126` 的 setter 将缺失值按 0 处理、限制不小于 0，写入 `battle_inside_pet_info.max_energy`，然后调用 `OverwriteByServer`。
4. `BattlePet:GetMaxEnergy()` 读取上述字段，缺失时返回 10。

`BattleCard:SetEnergy` 在第 118 行起只对负值归零，没有在此将能量截断到 9 或 10；这不能替代服务器的能量恢复/上限计算规则。

## 结论与边界

- 已确认：客户端宠物上限 getter 的默认值明确是 10，并支持使用同步过来的实际 max_energy。
- 已确认：此前 `character_max_energy.num=9` 的配置值不能据此 getter 认定为精灵上限；该 getter 没有读取它。
- 待核实：9 的具体消费者和用途；服务器如何生成初始 max_energy，以及突破上限等机制如何改变它。
- 这不是“全部服务端结算已复刻”的证明，但已足以纠正“文件证明普通精灵能量上限为 9”的说法。用户先前确认普通上限 10，与这个客户端默认值一致。

## 来源留存

`script_manifest.json` 和 `utils/script_manifest.json` 保存原包、资源路径、原始文件哈希、原始读取范围及未变化校验、解码完成信息和反编译输出哈希。原始字节码及标准化中间文件在对应 raw 目录。字节码只解析，未执行。
