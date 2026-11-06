# 状态百分比自动带出（2026-10-28）

技能结果预估面板原来要手填四个百分比（我方物攻/魔攻、对方物防/魔防）。本轮把解包里已经绑定的 BUFF 单位接到这四个输入上：**点一下加一层**，不再靠记忆换算。

## 数据链路

| 环节 | 文件 | 作用 |
|---|---|---|
| 技能 → BUFF 单位 | `data/rules/reviewed-modifier-source-units-1.json` | 已复核的 91 个技能，每个 BUFF 带分数单位（`patk: [10,100]` 即 +10%）与 `type`（1 增益 / 2 减益 / 3 其他 / 4 印记） |
| BUFF → 百分比 | `data/external/roco_buff_calc_map.json` | 220 条，补足单位里没有的字段（`phyAtkPercent` 等） |
| 作用方判定 | `data/external/skill.json` 的 `desc` | 描述里出现「敌方/对手」判为 opponent，出现「自己/自身/我方」判为 self |

新模块 `lab/buff_preview.py` 只暴露面板能理解的四个通道：物攻 `patk`、魔攻 `matk`、物防 `pdef`、魔防 `mdef`。速度、威力、受伤、连击类 BUFF 一律不进面板预估，避免偷偷改变伤害模型。

结果：**46 个技能**、**67 个可点单位**进入候选（`/api/buff/moves`）。

## 面板行为

- 面板输入框上方新增一行 chip，形如 `力量增效 → 我方 物攻 +10%`、`锐利眼神 → 对方 物防 -10%`。
- 点击一次代表一层：`+10` 变 `+20`；再点继续叠加。
- 归属按「谁被改」判定，不是按「谁施放」：
  - 我方给自己加攻 → 我方物攻框；
  - 我方降对方防 → 对方物防框（负值）；
  - 对方给自己加防 → 对方物防框；
  - 对方降我方攻 → 我方物攻框。
- 对方对我方施加减防（例如对方用锐利眼神）**不会出现在这里**——本面板只预测"我方打对方"，那条不在计算范围内。
- chip 只是快捷填充，输入框仍然可以直接改；改完照旧提交，口径不变：`有效面板 = 基础面板 × (1 + Σ%)`。

## 验证

| 层 | 命令 | 结果 |
|---|---|---|
| Python | `python -m unittest tests.test_buff_preview` | 7 / 7（力量增效 +10 物攻、魔法增效 +10 魔攻、锐利眼神 -10 双防且目标为 opponent、聒噪/防御不提供、未知技能返回空、+10% 等价于手填 10 的线性口径、通道白名单） |
| JS | `node --test tests\test_buff_preview_ui.js` | 4 / 4（点击一层/两层、双防负值落到对方框、对方对我方施加减防不出现、无面板 buff 技能不提供） |
| 全量 JS | 六个 suite | 114 / 114 |
| 全量 Python | `tests.test_buff_preview tests.test_lab_server tests.test_damage_preview` | 37 / 37 |
| HTTP | `scripts\_http_buff_check.py` | `/api/buff/moves` 返回 46 技能 / 4 通道；`/battle` 含 `preview-buffs` 容器与 `buff-chip` 样式 |

## 已知边界

- 只有 46 / 579 技能带四通道 BUFF 单位；其余技能的增益（速度、威力、受伤、连击）不在这块面板里。
- 层数需要玩家自己点（引擎侧的层数记录尚未回写到面板）；`add_max` 未做上限拦截。
- BUFF 的 `type` 只用于区分增益/减益显示，不参与计算。
- 所有百分比都按引擎的线性口径相加，不涉及叠乘。

## 复跑

```
python -m unittest tests.test_buff_preview -v
node --test tests\test_buff_preview_ui.js
python scripts\_http_buff_check.py     # 需要 8766 在跑
```
