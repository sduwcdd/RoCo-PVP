# 固定位置、内槽置换与完整技能包交换（2026-10-26）

`lab/slot_runtime.py`及`data/rules/reviewed-slot-components-1.json`绑定主轴7070160、锁芯7070230、杠杆置换7070050和隐藏条款7180200的完整原文和安装效果；动态来源迁移复用`dynamic_skills.remap_member_slots`，传动仅在原函数局部加入固定位置约束，未覆盖其他印记改动。

主轴/锁芯使用1083001、Enum的`ET_INLAY=83`。它们的普通75物伤/75魔伤正常执行，当前携带位置成为不允许改变的索引。传动仍采用既有循环remove/insert研究规则，但逐步检查是否移动固定技能；碰撞时明确阻断，没有擅自采用绕过/跳过锁芯规则。

杠杆置换普通前段通过共用执行器回复2能量；内槽1/2（零起算）交换各自左右相邻位置。边槽0/3是否环绕没有来源，因此预检阻断；邻位固定技能会移动时也预检阻断，不能先得能量再失败。post-hook使用支付前选定位置的binding，允许临时聪明输出在原槽先还原后继续处理已证明的位置。

隐藏条款完整交换双方当前四槽。`carried_slot_owner`记录原技能包来源，`dynamic_skills.original_slots`、PRNG计数和历史pool_sources保持不变；live origins及其嵌套prior origins逐层重绑member/slot，重算hash并记录可审计transfer_history。旧原始技能包owner仍是原成员，不能改写成接收者原携带信息。聪明输出使用后返回时，先前复制/动态来源仍能在新持有者恢复。

历史补丁2明确1047002、1004076和20030330均指向result_target_type=2即敌方；1004076明确清除20880010/20880020，因而对方待释放charge在交换前取消，原charge完整记录在取消事件。尚不清楚的技能成本修正/活跃防御冷却转移，以及固定技能与整套跨成员交换的交互，均在支付前阻断；不把未知清理图冒充全部实现。

接入：`programs(prepared)`注册slot_components；fragment合入`research_context()`；支付前保存`preflight_selection(...,context=...)`到`context['_slot_selection_binding']`；普通前段和`transformation.after_action`之后、离场之前调用`after_skill(...,event_token=...,context=...)`，返回events并提交owned state。隐藏条款空前段需要既有sequence-payment许可slot_components。

本次5个定向用例中，新增3项槽位检查和旧生成蓄力移动回归通过；旧clever+transmission组合回归遭遇并行防御配置更新窗口的`Defense component configuration changed`，未计为通过，等待窗口稳定后只重跑该项。已通过范围涵盖位置锁/碰撞事务、内槽换位及边界拒绝、整包递归来源迁移、历史/PRNG不变、聪明返回、敌方charge取消、未知成本联动拒绝。无实战校准。
