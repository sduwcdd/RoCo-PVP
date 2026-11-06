# 完整回合与伤害预测缺口审计（2026-10-25）

结论：目前的主要障碍是实现和接线尚未完成，不能笼统归因于用户没有提供规则或精灵数值。现有资料足以继续编写数值候选适配、常规行动串联、替补状态机和逐条技能/特性解释器。另有少量影响精确一致性的语义仍待核验，应分别标注和隔离，而不是阻止所有开发。本次只读核心代码及已有资料，未修改引擎、规则或用户记录。

## 六项责任明确的发现

1. **攻击 HTTP 接口没有连接伤害计算器，是明确的实现缺口。** `lab/server.py:164-166` 调用 `execute_joint_actions` 时没有传 `damage_resolver`，`lab/effect_runtime.py:175-179` 则强制要求可调用的解析器。所以即使提交完整精灵面板，当前接口仍会拒绝普通攻击。Python 扩展边界已经存在，可以编写服务器持有的版本化解析器及输入适配；不应要求用户再次口述全部规则，也不应把客户端传入的伤害当作预测。

2. **已有可复用的数值运算，尚未形成完整预测器。** `lab/numeric_candidates.py:163-215` 已实现两种有来源的 60 级单次名义伤害候选，`108-154` 已有面板候选；`lab/ruleset.py:92-123` 已能读取具体防守形态的属性组合倍率。可继续接通攻击/防御方向、面板、层数修正、威力、属性、本系及实际 HP 损失的适配和可追溯结果。仍需明确哪条版本政策生效，而非重新发明全部公式。实测调用 `arena_documented_damage60(100,102,75,1.25)` 与 Showdown 对应函数分别输出 **82、83**，差异来自候选的中间威力取整；候选输出明确没有实际 HP 裁剪、末端修正或最低伤害处理（`183-184`、`212-213`）。这证明可计算与候选分歧，不能证明当前游戏必为其中一条。

3. **完整回合在力竭和收尾阶段被代码主动截断。** `lab/action_runtime.py:136-137` 在任一技能导致任一在场成员 HP=0 时回滚双方行动；`lab/turn_plan.py:115-116` 拒绝零 HP 成员的普通行动，现有联合接口没有替补阶段入口。`action_runtime.py:160-167` 的动作→状态组合明确不做资源恢复、回合推进或胜负。可编码显式的待替补状态、合法候选、选择后续接及收尾状态机；未知的嵌套触发顺序可以单独作为版本政策。不能把现有事务回滚行为称为游戏规则。短探针将先手换为仅一个 damage 操作的技能 7020370，伤害回调返回对手剩余 HP，结果为 blocked，原因正是该力竭回滚，结果仍保留原 HP=300。

4. **旧引擎确有完整回合骨架，但不能直接当作可靠现成答案。** `src/battle.py:966-1060` 已有先后行动、力竭检查、自动替补、胜负检查、回合末与 turn+1；可参考控制流程和回调接口。其伤害式在 `269-300` 使用系数 0.9、本系 1.5、最终截断并最少 1，与现有数值候选和来源审计并不一致。应复用结构、逐条对照并替换无依据的数值/时序，不能直接把旧函数接到新网页后宣称真实一致。

5. **状态、特性和事件触发仍有大量明确的开发缺口。** `lab/effect_runtime.py:148-154` 只记录属性百分比项，没有把它们解析成有效属性；`159-162` 拒绝冻结和寄生；`lab/action_runtime.py:67-70` 要求排除全部特性/场地/印记等钩子。已有通用调度器与技能包装可复用（`lab/event_scheduler.py:63-80`、`lab/skill_execution.py:9-16`），但并不代表所有订阅器已实现。`docs/BWIKI_RULE_CORE.md:13` 记录 172/579 技能描述可编译、246 个特性全部未实现；这是代码覆盖不足，而不是用户没有交付这批描述。可以按已有结构化描述继续扩展执行器，并逐机制验证。

6. **剩余资料语义缺口必须具体列出。** 当前未确认的不是“所有规则”：`docs/verification/game-config-semantics-20261025.md:26` 指出 `BUFFBASE_CONF.trigger_type` 与 `SKILL_CONF.skill_result[].cast_moment` 尚无充分读取证据，不能将表现枚举同数字直接套用；`33` 的寄生参数链仍未唯一确定伤害基数、叠层和取整。`docs/verification/game-logic-trace-20261025.md:26,32,50` 表明已读脚本读取下发 `damage_params/hp_result`、拆分伤害显示与播放通知，尚未给出伤害算式或死亡/入场嵌套的权威优先级。`docs/verification/bwiki-numeric-followup-20261025.md:9,19` 具有历史灼烧与速度候选，但未唯一确认当前版本的全部取整。上述未知应绑定到受影响的具体路径；它们不阻止通用状态机和有版本标签的候选计算开发。

## 本次最小探针

在项目根目录以 `E:/miniconda3/python.exe -` 执行内存脚本，复用 `tests.test_action_runtime.JointActionRuntimeTests` 的现有构造 fixture，不运行整个测试套件，不生成临时脚本：

```python
from tests.test_action_runtime import JointActionRuntimeTests
from lab.action_runtime import execute_joint_actions
from lab.numeric_candidates import arena_documented_damage60, showdown_documented_damage60

JointActionRuntimeTests.setUpClass()
t = JointActionRuntimeTests()
t.setUp()
for name, resolver in [('missing', None), ('one', lambda p,s,c: 1)]:
    r = execute_joint_actions(t.catalog, t.state, t.actions, t.context,
                              damage_resolver=resolver)
    print(name, r['status'], r['blockers'], r['state']['turn'], r['full_turn_executed'])

t.state['teams']['a']['members'][1]['skill_slots'][1] = 7020370
t.context['fragments']['a'] = t.fragment(7020370)
r = execute_joint_actions(t.catalog, t.state, t.actions, t.context,
    damage_resolver=lambda p,s,c: s[p['target']]['hp'])
print('lethal', r['status'], r['blockers'], r['state']['teams']['b']['members'][1]['hp'])
print(arena_documented_damage60(100,102,75,1.25)['nominal_damage'],
      showdown_documented_damage60(100,102,75,1.25)['nominal_damage'])
```

实际输出要点：无解析器 blocked；常量 1 解析器 applied，但 turn 仍为 2、full_turn_executed=false；致命伤 blocked 且保留原 HP=300；两个名义伤害候选为 82/83。常量解析器仅证明接线边界，绝非有效伤害公式。

可信度：98/100（当前源码行为和本次短探针）。已确认：上述接口缺口、现存计算与回合骨架、具体回滚行为。待核实：当前真实游戏采用的完整数值和触发时序，已有本地材料尚不能唯一裁定。疑似编造：无。

## 审计后的渐进实现

新增 `lab/research_battle.py` 的 `execute_research_turn(catalog,state,actions,context,*,damage_resolver=None,program_overrides=None)` 和 `choose_research_replacements(catalog,state,selections,context)`。旧的严格 isolated 接口与默认行为保持不变。外层 context 使用 `mode="research_battle_experiment"`、`policy="ordinary_skills_faint_skip_manual_replacement_v1"`，并沿用完整 `excluded_hooks` 与双方 `fragments` 协议。

- 已完成的每个普通技能分别提交。后手出现费用不足、解析器错误或其他阻断时，保留先手已经发生的生命/能量/属性变化及事件，返回具体 blocker 和 `committed_actions`，不将事务回滚伪装为游戏规则。部分阻断状态的 `research_battle.phase="blocked"` 阻止误重放，须显式校正状态后再运行。
- 致命伤提交；显式 `stop_remaining_skill_on_exhaustion_experiment` 策略停止剩余技能效果和剩余连击，后续行动槽跳过。该停止策略仅由 research 入口注入，普通 `execute_effects/execute_skill` 默认仍严格回滚。
- `pending_replacements={"b":[0,2]}` 表示 b 的合法存活后备槽；`selections={"b":0}` 必须一次选齐全部待替补方。替补保留成员和印记状态并记录入场回合，不执行未知入场钩子。普通回合因 KO 等待替补，完成替补后才推进 turn；导入局面起初已倒下时，替补不额外推进回合。
- HP 存活判定下无存活成员则结束，双方均无存活成员为 draw。未实现复活、队伍魔力与真实胜负特殊规则，均记录为实验政策的 unresolved；回合末状态、天气、特性、场地及资源恢复也明确排除。
- 服务器持有的受信任 `program_overrides` 可映射整数游戏技能 ID 到编译程序，不允许客户端上传任意程序。文件来源程序保持独立 `game-file:<source_id>` 快照，核验可覆盖标志、来源证据摘要与完整程序摘要，片段必须绑定其文件政策；事件保留文件来源快照，不伪装为 BWIKI 来源。

验证：新增 `tests.test_research_battle` **14 项**，覆盖普通回合确定性、KO、后手跳过、技能与连击停止、双方待替补、非法替补、胜负、已提交进度、后手费用不足、隔离、动态组件和文件程序摘要。与本轮其他代理的 `tests.test_research_api`、`tests.test_research_damage` 合计 **30 项通过，14.370 秒**。此前严格 `tests.test_action_runtime`、`tests.test_effect_runtime`、`tests.test_rule_config` 合计 **93 项通过，66.714 秒**；`tests.test_skill_execution` **12 项通过，6.760 秒**。均为构造数据的实现回归，未声称实战校准。未留下临时冒烟脚本。

当前 `full_turn_executed`、`battle_executable`、`training_eligible`、`calibrated` 和 `real_game_verified` 仍为 false；实验闭环是否完成通过单独的 `research_turn_executed` 与 `turn_advanced` 表达。前面的审计描述的是实现前的严格路径，本节是独立 opt-in 路径的新增进展。
