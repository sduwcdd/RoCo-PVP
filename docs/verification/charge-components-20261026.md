# 蓄力组合组件与历史层数依据（2026-10-26）

`lab/charge_program_adapter.py` 增补来源绑定配置 `data/rules/reviewed-charge-components-1.json`，由 `lab/charge_runtime.py` 解释组件；没有运行时技能名、完整句子或后缀特判。原有纯伤害升龙咆哮继续走共用效果执行器。

| 技能 | 本次支持 | 留存依据 |
| --- | --- | --- |
| 7100130 吹炎 | 应对状态成功时170→340，失败仍170；释放支付一次 | BWIKI术语1015；游戏1031113指向7100131，变体威力340；配置与快照行hash绑定 |
| 7100140 怨力打击 | 蓄力期间真实对手攻击事件追踪；单一明确来袭威力×3；无攻击时基础威力1 | BWIKI完整技能声明；20880020→2088002，opcode88参数`[2] / [30000] / [20010800]` |
| 7100170 龙吟 | 双攻各15层×10%，速度8层×10；复用已有萌发额外增益层策略 | 独立历史补丁2技能原始`buff_group_level=15/15/8`、对应字节span及BUFFBASE行 |

历史层数来源为 `artifacts/strength_buff_probe_20261025/mirror/versions/pakchunk4-WindowsNoEditor_2_P/SKILL_CONF.json`，同一记录也留存在 `artifacts/game_layer_references_mirror_patch2_20261025/layer_references.json` 的 `resource-group-c40d72d37c3c43a12b3f`。配置保存技能原行、字段偏移/字节、每层基元、资源声明及hash。资源组明确记录部分表schema来自其他补丁，属于人工选择且长度验证过的解析候选，不代表客户端实际挂载顺序。

基础包龙吟的旧文本与层数是双攻100%/速度60及10/10/6；补丁2为150%/80及15/15/8。补丁3文本也是150%/80，但schema没有层数字段。本实现没有给补丁3记录填15/15/8；执行配置明确选择补丁2层数与BWIKI的相符声明，两个版本原始字段分别保留。历史配置、BWIKI及共用运行时来源任一变更均需重新审查。

## 明确的研究策略与限制

- 蓄力先建立记录，下一回合释放；释放支付一次。顺序与阶段沿用现有V2命名研究策略，未恢复权威服务端调度。
- 只有已经提交的物理/魔法攻击产生对敌`damage`事件才记录来袭；零HP损失的攻击事件仍算受到攻击，这是显式策略。状态、毒、印记附带伤害不会被误当成对方攻击技能威力。
- 来袭威力取共用解析器送入伤害resolver的已解析`power`，不以HP损失倒推。多段相同威力可消歧；多个不同来袭威力在释放前阻断，因为现有来源没有给出取首个、末个、最大或求和的选择规则。未擅自添加公式。
- 固定速度单独记录到`charge_flat_modifiers`，在速度百分比项及取整之后、现有印记速度项之前累加；没有改写基础速度。双攻继续记录独立有理数百分比项，面板/伤害公式仍是现有研究策略。
- 本次不声称完整解释游戏BUFF图、当前线上覆盖或实战校准；训练资格保持false。

## 接入点

1. `research_phases._preflight_component/_execute_component` 对带`charge_components`的程序调用`charge_runtime.preflight/execute`。
2. 每个实际技能已提交、相对状态已写回后，对受攻击的活动成员调用`observe_attack(member, skill_id=..., skill_kind=..., turn=..., events=fragment['events'], action_token=...)`；附加返回事件。token按回合、行动位置及行动方唯一。
3. `_effective_speed`在`marks.modify_speed`前调用`charge_runtime.modify_speed`。
4. 现有simulation已加载charge adapter结果；其他直接V2入口可通过已有`program_overrides`传入，或纳入reviewed-program缓存。

## 定向验证

运行5个用例，全部通过：`tests.test_charge_components`的3项，另加adapter的来源图保留与来源/程序篡改拒绝两项（6.780秒）。涵盖170/340、单次付款、无受击/90×3、状态事件排除、多段事件去重、不同来袭威力拒绝、15/15/8、固定速度+80、输入不变及程序修改拒绝。没有进行额外的长时试战或实战校准。

随后在同一龙吟用例内增加固定速度账本校验：错误技能ID、source hash、每层增量及伪造层数均拒绝；2层萌发使速度增量变为100，按施加时印记快照及已有层数policy复算。该单项重跑通过（1.244秒），没有增加测试用例。
