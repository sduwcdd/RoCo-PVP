# 生命代能支付组件（2026-10-26）

新增 `lab/payment_runtime.py` 与 `data/rules/reviewed-health-payment-1.json`。本组件解决费用不足时的支付组合，不会把技能或特性的其他未实现效果视为已完成。

| 来源 | 游戏引用 | 已确认信息 |
| --- | --- | --- |
| 石头大餐200100 | 20240030→2024003 | BWIKI及游戏文本：不足1能量可消耗5%生命；base opcode24，第4参数500 |
| 盛宴280030 | 20240031→2024003 | 明确5%最大生命代替1能量；与石头大餐共享同一base |
| 骗局7180300、虚假破产7180330 | 20240040→2024004 | 技能自身的5%生命代能；base也是opcode24，第4参数500，第6参数1 |

`Enum.luac.decompiled.lua` 明确 `BFT_BLOOD_TO_ENERGY=24`。来源配置保留BWIKI记录、游戏技能/BUFF/BASE原行及hash，运行时核对目录内已提取文件hash和快照。特性来源还核对精灵形态到trait_id的绑定；转换技能来源核对对应技能行。已恢复的`SKILL_CONF`属性中只有`energy_cost`与`target_blood_limit`等相关字段，没有独立通用`costHP`字段；不能据此编造一般生命技能支付协议。

## 研究策略与未知边界

- 正常费用修正完成后，真实能量支付`min(总费用,当前能量)`；剩余缺能按最大生命×缺能×5%计算，合计后向下取整一次。不会补写或伪造能量。
- 石头大餐文本仅说“生命”；最大生命基数及basis-points单位为明确研究解释，盛宴共享base和其“最大生命”文本是旁证，仍不声称还原权威服务端公式。
- 正常能量充足时不扣HP。两个相同5%转换来源重叠时提供相同替代途径，不相加成10%。不同转换率拒绝，等待来源给出选择规则。
- 下取整得到0时拒绝，因为免费转换与至少扣1点的规则未确认。HP费用大于或等于现有HP时拒绝，因为致死支付是否合法尚未确认。
- 扣HP发生在原效果执行之前，便于后续已有动态HP条件读取实际资源。HP费用事件使用`hp.pay`，不会伪装成攻击伤害；生命损失触发链是否响应此成本仍未恢复。
- 盛宴低血吸血及其每段阈值时序不在本支付模块内；完整特性支持需要单独的对应组件，不应仅因本模块可计算盛宴支付就宣称盛宴已完整支持。

## 接口与事务

`quote(prepared,member,skill_id,total_cost)`返回来源与资源绑定的完整quote，主要字段为`paid_energy`、`paid_hp`、`total_cost`、`missing_energy`和`unrounded_hp`。规划器及原`energy.pay`使用`paid_energy`；原action保留总费用输入，执行前重新应用修正并重新报价。fragment context通过`health_payment`携带完整quote，且`resolved_energy_cost`必须等于`paid_energy`。

在现有组件dispatcher之外包装 `payment_runtime.preflight(...,preflight_base=dispatcher)` 和 `execute(...,execute_base=dispatcher)`。包装器核验来源、当前HP/能量、完整quote与支付费用，在副本扣HP后调用原dispatcher。原dispatcher仍只支付一次真实能量；失败返回原状态和空事件，成功额外插入一条`hp.pay`。quote只要资源或源发生变化就拒绝复用，不允许手改其字段。

## 定向验证

`python -m unittest tests.test_payment_runtime -q`：3项通过，1.375秒。覆盖351最大生命、缺3能产生52.65并下取整52；执行器看到实际扣HP后的248生命和0能量；HP/能量各扣一次；回调失败回滚；无trait但技能自带转换；禁用trait后的正常不足能量拒绝；致死和取整0拒绝；quote篡改和当前资源变化拒绝。无额外冒烟脚本、未修改游戏原文件、没有实战校准。
