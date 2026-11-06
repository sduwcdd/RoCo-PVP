# 星陨参数 20 的本地证据审计

结论：现有文件可以确认星陨的触发条件、层数消耗和参数原值 `20`，不能确认它的单位或伤害公式。不得把 `20 × 层数` 标成已解码的真实伤害。

## 已确认的来源链

- `artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/BUFF_CONF.json:57425`：20940010 星陨印记，`buff_base_ids=[2094001]`、`add_max=99`，描述为受到非幻系技能攻击时消耗全部层数并受到额外幻系伤害。
- 同文件 `:57452`：20940011 引用相同 base；不同显示角标不能证明不同伤害公式。
- `artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/BUFFBASE_CONF.json:92344`：2094001 的 `buffbase_order=94`，唯一参数为 `buffbase_param[0].params=[20]`。字段没有单位、倍率、属性、攻防参与方式或取整说明。
- 同文件 `:111320`：另一条 order 94 的 2999100 参数依次为 `[2]、[1]、[100]、[9]`。对应 `BUFF_CONF.json:80163` 的 29991000 名为“新增buff94”、描述“星陨”、最大层数 20。其参数数量不同，不能据此反推普通星陨的第一参数含义。
- `artifacts/unpack_probe_20261025/battle_analysis/pakchunk4-WindowsNoEditor_27_P/ProtoEnum.luac.disassembly.txt:55827` 只将 `BFT_NINETY_FOUR` 映射到 94，没有参数语义。
- `artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/BATTLE_GLOBAL_CONFIG.json:3125` 存在 `starfall.numList=[1,24,-24]`，没有字段说明；不能拿它填补伤害公式。

## 检索范围与剩余缺口

本次检索该 battle_analysis 目录现有 25 个 `*.decompiled.lua` 及协议枚举反汇编，搜索 `2094001`、`BFT_NINETY_FOUR`、`starfall` 和大小写变体，未找到 order 94 的执行或伤害计算实现。`BuffUtils` 提供通用配置查找和显示剩余回合，不能解释参数 20。

缺少 order 94 的执行实现、参数 schema 或可复现且控制攻防/层数/属性的对战伤害观测。当前运行时应继续要求专用实验伤害 resolver；若采用 `20 × 层数` 假设，必须作为显式未校准政策，禁止将它自动升格成源码规则或训练可用能力。

本审计只记录已有本地文件，不改变 `mark_runtime` 的阻断边界。
