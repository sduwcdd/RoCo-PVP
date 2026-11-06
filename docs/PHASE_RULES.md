# 回合阶段规则与联合行动计划

这些组件继续推进完整引擎，但当前仍不能完成一整个真实回合。计划组件只判断资格与阶段；后文的实验运行器可以执行明确限定的片段，但不能结算完整特性触发链或胜负，也不替代实战校准。规则绑定当前 BWIKI Terms 原文、修订哈希和数据快照；来源变动会拒绝继续套用旧语义。

## 入场、离场与印记

`lab/switch_rules.py` 区分主动换人、脱离、返场、紧急脱离和力竭下场。刚入场的当回合免疫前三种指定离场效果；不擅自扩大为不能主动换人。蓄力期间免疫离场效果，主动取消蓄力仍未核实。力竭下场不视为普通离场，因此不共用全部离场触发器。

印记按场上位置保留正负两个槽，各最多一种。跨换人复制保留全部来源信息，不能让双方或分支共享可变对象。相同槽中出现另一种印记时，覆盖机制未知，返回未解决并保留原值。极性、同种叠加和上限须由调用者显式提供实验参数，不当成已核实默认规则。

迅捷选择保留四槽，包括空槽；按原顺序寻找首个满足能量的迅捷技能。靠前候选的迅捷条件或最终费用未知时，不跳过它去选后面的技能。选择不等于执行入场技能。

## 应对与蓄力

`lab/action_rules.py` 支持明确的应对类别匹配和不同先手度排序。双应对同时成功、换人与技能混合排序、相同先手度下的速度及同速处理没有充分依据，返回可能顺序，不分配 50% 等虚构概率。

蓄力记录绑定技能游戏 ID、四槽索引、开始/释放回合、技能来源哈希及 Terms 来源。准备阶段不等于攻击释放；下一回合的 `ready` 仅表示时序就绪。记录保持不变，直到未来的实际技能执行器提交释放结果。过期记录、改槽、换技能或来源变化均拒绝释放。

## 双方共同前态

`lab/turn_plan.py` 的 `plan_joint_actions(catalog,state,actions)` 同时接收双方行动，只读取同一个前态。一方输入错误时，整份计划拒绝，不返回另一方的部分计划，也不修改输入状态。

输入状态包含快照、回合、双方阵容和在场槽；每个成员给出稳定 ID、具体形态、生命、能量、速度（可未知）、入场回合、禁足和蓄力记录、四个技能槽。技能行动必须显式给出当前**这个阶段**的已解析费用 `effective_cost` 与先手度 `effective_priority`。蓄力准备阶段的费用不能直接拿未来释放的基础费用替代。计划器不支付费用，输出标记这些值来自调用者的实验输入。

主动换人的计划保留印记。可选的目标 `swift_candidates` 必须与目标四槽逐位对应，再检查迅捷；缺少这份已解析元数据时仍列为未解决。技能描述未完整实现时，排序也不能假装应对能力为空而直接确定先后。

本机接口：`POST /api/rules/turn-plan`，请求体为 `{"state":...,"actions":{"a":...,"b":...}}`。该接口面向内部规则检查，不是策略观测；它接收完整状态，不能直接暴露给只应看到一方信息的模型。

响应包含来源、状态/行动哈希、双方计划、未解决项。`status=planned` 不意味着阵容合法或完整战斗可执行；`battle_executable`、`full_turn_executed`、`training_eligible`、`calibrated` 当前都为 false。

完整结算仍需补齐真实公式、时序、费用支付、离场清理、特性与场地触发、全部技能及胜负规则。现有网页继续记录用户实际行动，正式训练门槛保持关闭。

## 双方技能片段连续执行

`lab/action_runtime.py` 的 `execute_joint_actions(catalog, state, actions, context, *, damage_resolver=None)` 已把联合计划接到技能效果执行器。只有来源规则能确定唯一行动顺序时才执行；后手读取先手更新后的生命、能量和属性修正。当前支持已有技能解释器的普通片段，不实现换人、蓄力或防御技能。任何一步失败，返回双方行动前的原状态及空事件，不泄露先手的部分提交。

状态沿用计划器格式，并要求在场成员提供 `max_hp`、`max_energy`、`statuses` 与 `stat_modifiers`。精灵属性从具体 BWIKI 形态读取；已提供的属性若与来源冲突则拒绝。实验上下文必须明确 `mode="isolated_joint_action_experiment"`、完整的 `excluded_hooks`，以及 `fragments={"a":...,"b":...}` 两份现有技能片段上下文。各自绑定技能来源哈希、快照、操作顺序与必要政策；支付费用以行动中的 `effective_cost` 为准，不能与片段重复提供的费用冲突。

每个事件保留队伍、成员、技能槽、技能 ID、来源哈希和操作前后值。Python 调用可显式提供未校准伤害解析函数，其输入是相对当前行动者的状态副本；函数收到的上下文附 `actor_side`、`actor_member_id`、`opponent_member_id`。这不构成游戏伤害公式。HTTP 接口 `POST /api/rules/execute-actions` 不接受可执行函数，也不会把用户传来的伤害值当作预测公式：无伤害公式的攻击返回阻断；双方使用“徒长”等非伤害技能可进行片段实验。

返回 `applied` 只代表两次片段成功，不会推进回合数、恢复每回合资源、结算状态或天气、处理力竭或判断胜负。出现生命归零时整对回滚；已有冻结层数也会阻断，因为冻结的即时力竭阈值尚未实现。所有输出仍明确 `full_turn_executed=false`、`battle_executable=false`、`training_eligible=false`。这些实验不能作为正式训练对局。

## 大量重复实验时复用规则

`lab.prepared_rules.PreparedRules(catalog)` 将一次读取的来源快照绑定到一个可复用对象。它复用精灵/技能索引、行动和切换规则、编译后的技能；不缓存战斗状态、行动、伤害回调或执行结果。每次返回的计划与事件仍为独立副本。

```python
from lab.prepared_rules import PreparedRules

rules = PreparedRules(catalog)  # 每个工作进程构造一次；不是训练认证。
plan = rules.plan(state, actions)
result = rules.execute(state, actions, experiment_context,
                       damage_resolver=explicit_experimental_resolver)
```

原有 `plan_joint_actions(catalog, ...)` 和 `execute_joint_actions(catalog, ...)` 接口继续可用，也可将第一个参数换成上述对象。普通网页请求仍会核对当前图鉴文件，不使用进程级图鉴缓存。单技能查询只复制被请求的程序，完整 `programs()` 查询仍返回完整独立副本。

规则初始化与首次编译使用实例内的锁，支持多个线程共用固定规则、各自传入不同局面。不要深拷贝或序列化规则对象本身；多进程工作者各自用图鉴构造。外部原始图鉴后续变化不会改变已准备对象；更新快照须显式创建新对象。即使快照名称相同，内容发生变化也会得到不同内容哈希，原技能上下文不会绕过来源检查。

本机单一构造测试场景（双方“徒长”，不含完整回合）优化前未开启性能分析的两次执行中位数约 1.641 秒。优化后规则构造约 0.840 秒，首次执行约 0.053 秒，100 次预热执行中位数约 0.00124 秒；所有输出与保存的优化前结果逐项相等。不同输入、机器、触发链和完整对战不在该测量范围内，不能据此宣称训练吞吐或游戏表现。原始输入、前后结果及逐次时间见 `verification/rule-reuse-before-20261025.json`、`verification/rule-reuse-benchmark-20261025.json`。

上述性能证据来自编译器 v2，历史原始记录未改写。升级 v3 后程序与计划哈希包含新的编译器版本，不能再要求它们等于旧版身份。当前回归分别检查：同一版本中即时构造与复用对象的全部输出（包括所有哈希）相等；历史示例保留状态、事件和来源的语义对照，仅排除明确发生版本变化的 `plan_hash` 与事件 `program_hash`。这一调整不改变旧性能结论的版本范围。


## 回合末状态片段及与行动的组合

`lab/status_runtime.py` 的 `execute_status_phase(catalog_or_prepared, state, context, *, damage_resolver=None)` 使用同一份图鉴与联合局面，处理在场成员的中毒和灼烧。Terms 1001/1002 给出 3% 毒系伤害、2% 火系伤害及灼烧半数衰减；程序核对术语唯一性、全文和已审查的来源哈希。它不会把中毒印记当成中毒状态，也不会处理后备精灵、印记、天气或特性。

上下文必须包含 `mode="isolated_status_phase_experiment"`、`snapshot_id`、`catalog_content_hash`、完整 `excluded_hooks`、空 `unresolved_dependencies`，以及 `operation_order="damage_then_decay_experiment"`。`schedule` 是调用者明确选择的 `[{"side":"a","status":"poison"}, ...]`，必须恰好覆盖所有在场正层数的中毒/灼烧各一次；不默认双方顺序或毒烧顺序。`status_policy` 必须为 `{"immunity":"reject_existing_immune_status","burn_decay_rounding":"exact"}`，取整也可显式选 `floor` 或 `ceil`。这些顺序与取整是实验选择，并非当前游戏已确认规则。

现有毒系中毒、火系灼烧会阻断，因为图鉴的“免疫此效果”不足以确定存量状态是清除、免伤还是不衰减。已有冻结、寄生亦会阻断，不能跳过其尚未明确的力竭阈值或来源关系。缺失策略、奇数灼烧配 `exact`、重复/遗漏结算项等均在任何伤害回调前拒绝。

伤害回调接收独立的 `(descriptor, joint_state, context)` 副本。描述保留百分比有理数、层数、伤害属性、目标成员及完整术语来源；百分比与层数不会由执行器擅自相乘。回调返回最终整数实际生命损失，执行器不再乘克制或取整，不推断最大生命基数或历史 1000 上限。后一个回调看到前一个结算后的当前局面。每项事件记录生命和层数前后值、灼烧剩余层数的未取整分数及所选策略。

`execute_action_status_sequence` 位于 `lab/action_runtime.py`，也可通过 `PreparedRules.execute_action_status_sequence` 调用。它要求 `mode="isolated_action_status_sequence"`、`phase_order="actions_then_status_experiment"`、`actions_context` 与 `status_context`，依次运行双方技能与状态片段。状态日程针对两次技能之后的局面，包含本次新施加的状态；遗漏新状态会使两阶段一起回滚。任何状态伤害失败、产生力竭或有未处理依赖，也会撤销此前技能效果及支付。两个解析器分别由 `damage_resolver` 和 `status_damage_resolver` 提供，均应为纯函数；外部副作用不能通过返回原状态撤销。

接口 `POST /api/rules/execute-statuses` 和 `POST /api/rules/execute-action-status-sequence` 提供同样的验证边界。HTTP 不接收可执行解析器，也不会把请求中的观察伤害或预测值用作公式，所以非零状态伤害仍会阻断。空状态片段可以验证并原样返回，但不代表完整回合末成功。

组合成功仍不推进回合、不恢复自然资源、不判胜，`full_turn_executed`、`end_of_turn_executed`、`battle_executable`、`training_eligible`、`calibrated` 均为 false。任一伤害导致生命归零会整体回滚，等待完整力竭触发链。来源缺口和实验假设保留在结果中；本功能没有被作为正式模拟训练入口。


## 主动换人的位置变化实验

`lab/switch_runtime.py` 的 `execute_switch_fragment(catalog_or_prepared, state, side, target_slot, context)` 把离场资格与入场检查接到状态变更；也可通过 `PreparedRules.execute_switch_fragment` 或 `POST /api/rules/execute-switch` 调用。该片段只处理主动换人，不推断换人与对方技能的先后顺序，不处理强制离场、返场、随机替补或力竭后的替换。

调用者须明确提供 `mode="isolated_voluntary_switch_experiment"`、`snapshot_id`、`catalog_content_hash`、完整 `excluded_hooks`、空 `unresolved_dependencies`、`cleanup_policy="retain_member_fields_experiment"`、`swift_policy="intrinsic_source_only_experiment"`，以及对应目标四槽的 `incoming_effective_costs`（空槽为 null；非空槽为已解析非负整数费用或未知 null）。这里的保留字段与仅考虑技能自身迅捷都是实验前提，不是游戏离场清理、动态赋予迅捷已经查明。

可选输入 `switch_cooldown` 会额外应用客户端换人资格检查。解包的 `BattleUtils.CheckCanChangePet()` 显示初始冷却条件为 `exchange_initial_cold >= roundIndex` 时禁止；若存在非零 `lastChangePetRoundIndex`，则 `roundIndex <= lastChangePetRoundIndex + exchange_cold` 时禁止。`BattleUtils.GetPetBit()` 与 `ProtoEnum.PET_BIT_TYPE` 显示禁换位为 16，位组按 Lua 一基索引读取。规则会优先从提供的 `battle_inside_pet_info.state_bits` 解出禁换位，并拒绝它与单独 `ban_change_pet` 输入冲突的情况。该资格函数在已提取脚本中的实际调用链、这些配置值在当前 PVP 的运行时值及服务器是否执行相同检查均未确认；因此不能据此宣称游戏全局换人规则已经完整实现。

该门禁要求调用者显式提供运行时当前回合、初始/重复冷却值、当前模式 `can_changepet` 和活动精灵的禁换信息。`last_change_round_index` 也必须显式出现；明确的 `null` 对应客户端 `if not lastChangeRound` 分支（尚无上次换人），与完全缺失的观测不同。任何必需观测缺失时返回 `unresolved` 并阻止这次研究片段，不再从模拟器回合或默认“未禁换”推测。整个 `switch_cooldown` 输入本身仍是可选的：调用者不传时，旧的主动换人研究片段保持原行为，不代表已应用完整客户端门禁。

`SwitchRules.skill_swift_metadata` 从其独立保存的 Skills 数据读取技能，核对 Skills 来源哈希与完整规范化技能集合的内容哈希。已审查的六个无条件迅捷技能标为自身迅捷；月影交错的历史条件保持未知；疾风连袭虽然提及迅捷，但“重复释放迅捷技能”不等于自身具有迅捷。四个位置及空槽原样保留，不依赖成员自行提交的 `swift_candidates` 布尔声明。外部特性、增益赋予迅捷仍在本片段排除范围内。

选择器仍按四槽顺序检查：遇到可能满足能量的靠前未知项就阻断；首个可用迅捷一旦选中，必须执行其已支持的完整技能片段；当前已发布配置中完整支持的固有迅捷仍只有翼击，但执行入口已统一为通用技能调度，其他未支持配置仍会阻断，不能跳过它提交位置变更。已明确费用不足的迅捷可以按来源规则排除；没有适用迅捷时只执行位置变更；翼击的实验入场执行见下文。

无适用迅捷且所有前置检查通过时，唯一状态修改是本方 `active_slot` 和新在场成员的 `entered_turn`。资源、状态、属性修正、技能顺序、自定义字段、后备成员和场上印记保留独立副本。印记继承会附来源，但印记效果没有在此触发。出场/入场成员的蓄力、相关成员的冻结或寄生、力竭、来源或类型冲突、禁足阻止离场等都明确拒绝。不会自动清除状态来制造“合法”换人。

事件记录离场/入场成员 ID、槽位、前后入场回合、印记来源及迅捷检查证据。后续状态消费者能识别新在场成员，并据新的入场回合应用本回合离场效果免疫；这不意味着允许同一真实回合换人后再额外行动。失败返回原局面与空事件；成功也保持 `full_switch_executed=false`、`full_turn_executed=false`、`training_eligible=false`，并列出离场清理、触发链与完整配招合法性等未完成项。


### 已选中翼击的入场攻击实验

`execute_switch_fragment(..., damage_resolver=...)` 与 PreparedRules 同名接口现可执行被原技能槽顺序选中的翼击。原有上下文之外，须显式声明 `entry_timing="after_position_change_experiment"` 并提供 `entry_skill_context`（现有 isolated_skill_experiment 的来源、快照、操作顺序、排除钩子及伤害政策）。这只是可检查的实验时点，不证明真实游戏所有入场钩子的顺序。

入场费用取选择器使用的 `incoming_effective_costs`，不从来源基础费用偷填。若技能上下文又指定 `resolved_energy_cost`，必须与该值一致。费用由新入场精灵支付一次；伤害解析器读取更新后的入场回合、已支付能量、新在场成员 ID 和当前对手。没有适用迅捷时不会调用所传解析器。首个迅捷未支持、条件未知或缺少其效果所需政策/解析器时均拒绝，不跳到后面的翼击。

成功事件先记录位置变更，再记录带有 `origin="entry_swift"` 的费用和伤害事件；保留技能槽、游戏 ID、双方成员身份、程序来源及实验时点。任何伤害解析异常、非法返回、资源冲突或生命归零均回滚位置、入场回合、费用和全部伤害，返回原局面及空事件。原始输入、解析器收到的副本和其他模拟结果互不污染。

HTTP 接口仍不接收伤害函数，也不把请求中的伤害数值当作公式。当前选中翼击的 HTTP 请求在缺少已审查伤害解析器时阻断，Python 可以做明确标为未校准的组件实验。普通手动使用翼击无需伪造入场事件，只作为一次普通攻击执行。所有完整换人、完整回合及正式训练标记仍为 false；离场清理、外部迅捷变更、入场/离场特性与力竭链继续待实现和实战校准。


机制架构第一阶段：手动使用与入场技能共用 `skill_execution.execute_skill`，不再把迅捷限定为单个 damage 操作。更多组件可由数据配置组合，但来源、技能完整性与效果运行器的阻断条件继续有效。通用嵌套事件框架不意味着实际特性/印记链已经接入，详见 [RULE_ARCHITECTURE.md](RULE_ARCHITECTURE.md)。
