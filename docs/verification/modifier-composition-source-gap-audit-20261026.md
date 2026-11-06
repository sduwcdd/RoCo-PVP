# Modifier / composed-skill source gap audit

Scope: mechanism/effect/modifier ledger/choice/defense/duration/interrupt/forced-switch composition. This is source-backed research implementation, not a current-server equivalence claim. Generated 2026-10-26.

## Final requested six

| Skill | Extracted evidence | Implemented behavior / policy boundary |
|---|---|---|
| 7180190 恶意逃离 | response variant7180191; BUFF20320400→BASE2032039 kind[2,3], cost+4, rest1;20480060 detach | Source-bound attack-only cost before existing detach path; current skill kind query, not all-skill cost. Existing explicit replacement/forced transaction policy retained. |
| 7021120 嗜痛 | response7021121;20190190→2019019 triggers four20010010 + four20010020 | Each positive actual attack hit gives both attacks+40%; each hit is separate under named policy, before next hit. Zero actual loss does not trigger. |
| 7020810 无畏之心 | response7020811;20110140→2011014 reduction100%, absorb flag1; energy_rule4 [5,2,1] | Heal actual source-matched prevented damage; resolver.explain receipt required, never inferred from HP loss. Permanent self-cost+2 once per successful response. |
| 7140160 破防 | response7140161;20620020→2062004 order62; both defense debuffs | Both defenses-70%; cooldown bound to actual declared enemy skill for the next two turns. Whether application turn counts is explicitly experimental. |
| 7021160 摇篮曲 | response7021161;20320240;20060040;1003001 | All-skill enemy cost+3; matched uncommitted defense interruption and absolute next-turn stun. Already-committed action is not rolled back. |
| 7030270 芳香诱引 | response7030271;20450050;20060040;1003001 | Self hits+2; same matched defense interruption and next-turn stun. |

All whole catalog records and reachable extracted references are retained in reviewed component JSON. Identity/hash validation remains enabled. Missing callbacks or target skill context block explicitly rather than degrading to a partial effect.

## Remaining boundaries

- Supported source data is not equivalent to executable whole-description coverage. The inventory below preserves original compiler blockers; it does not label every remaining skill as requiring user input.
- Complex additional elemental damage (e.g.7190460), guard transferred to the next entrant (7130220), and damage-received-dependent scopes require corresponding event/runtime semantics rather than deleting immunity, traits, or branch effects.
- Adjacent-slot power/cost queries are owned by another integration agent; this report does not duplicate that work. Choice/history/mark coverage may continue changing concurrently.
- Existing ambiguous BUFF-ID classification cannot be counted as multiple actual kinds: buff_kind_ids explicitly blocks ambiguous source sets. Known singleton IDs are counted across stat/flat/cost/lifesteal/timed ledgers.
- 7130210 effective-vs-base cost and7070220 extra transmission timing remain named research policies, with source evidence retained. They are not represented as verified game rules.

## Current whole-program inventory

Weather setter/extension and weather-attack overrides are included, avoiding the earlier false unsupported weather count.

At generation: 96 entries remained uncompiled in the merged current program view.

| ID | Name | Whole description | Existing blocker (diagnostic, not a source-gap conclusion) | Source hash |
|---|---|---|---|---|
| 7020550 | 魔能爆 | 造成魔伤，使用时消耗所有能量，消耗越高，伤害越高。 | description_not_fully_supported | 477fb9b6d1f20283e5a95a918afffce0a3c4f7ce44e2b7d010eb7dc94517f6f2 |
| 7020660 | 激怒 | 敌方除本回合使用的技能，其他技能能耗+3，持续3回合。 | description_not_fully_supported | 947ee4001eceddbc9609d4c2f38939d58c2e41db7087f436f66acc5a69475fba |
| 7020770 | 退化 | 敌方获得1层萌化。 | description_not_fully_supported; unresolved_desc_notes | 728183c3a132c74ab46928a2b1f4481e580d5cc539665a896916a2c5d678fe82 |
| 7020800 | 血气 | 减伤60%，应对攻击：本回合受到致命伤害时，保留1生命值。 | description_not_fully_supported; unresolved_desc_notes | b03b1120a82f8480ee10e6efc892017374b478a8b2fcc62463ef40329fd669db |
| 7020840 | 借用 | 每回合随机变成己方队伍中其他精灵的技能。 | description_not_fully_supported | e6a5b2c3a3c04f44bff9582bba55de1994fcc78950611e4a72b65a053d2dbe8f |
| 7020850 | 取念 | 每回合随机变成敌方任意精灵的技能，且该技能能耗-2。 | description_not_fully_supported | 9b1ed3554f7def3388f1dc2a406a01e697e7287cac59088c06e7a35b5a6bc540 |
| 7020860 | 复写 | 每回合随机变成自己未携带的技能，且该技能能耗-2。 | description_not_fully_supported | b633403af24010b253e28f8c0cdec9ecd0e769ff60f589d95568337a99da8600 |
| 7020990 | 吨位压制 | 造成物伤，敌方体重越低，本次技能威力越高。 | description_not_fully_supported | 6a9cb1052a43da920bf84f3afb0027c1efbd1d72122689d50783db9d4aa91c8d |
| 7021000 | 以重制重 | 造成物伤，敌方体重越高，本次技能威力越高。 | description_not_fully_supported | 15b44a515be0b1afd1e56039a33d820191958aa8098122bfc33f3eca4d297a20 |
| 7021170 | 倾泻 | 造成魔伤，若本次攻击未被防御技能应对，则驱散双方所有印记。 | description_not_fully_supported; unresolved_desc_notes | 3931b4cdecdced07ee15eac66e3d0247edfdd077360f7eede173fd34d951e79c |
| 7021230 | 友谊满溢 | 造成魔伤，选择：每次使用后威力永久+20或应对状态时本次技能威力+100%。 | description_not_fully_supported; unresolved_desc_notes | 97bfc077463825df86521db6b3bca987c47e39fc1a7b74eb4729ab6df4155131 |
| 7040680 | 焚尽 | 驱散自己所有印记，每驱散1层，获得物攻+50%。巧变：火系攻击技能。 | description_not_fully_supported; unresolved_desc_notes | a61cd991e263fd57c34b4105b45972e1cc3e56e748a8622594c5914296d8b5ec |
| 7050280 | 水环 | 减伤60%，应对攻击：自己获得全技能能耗-2。 | description_not_fully_supported; unresolved_desc_notes | 891e2685716c51458b6cf536d650c2ff8533d129918ad632de6e6cd546539443 |
| 7050510 | 清洗 | 驱散自己的减益，自己每有1层减益，本技能能耗-1，巧变：水系攻击技能。 | description_not_fully_supported; unresolved_desc_notes | 318d3e499e415dd11c073f10635521f92f599bd19dce36f235bfd18860860366 |
| 7060120 | 过曝 | 造成魔伤，每使用过1个其他系别技能，本技能威力永久+30。 | description_not_fully_supported | 5ef5f049a98bdb078467757a1707f5fac3fd748cc1533d1d7825422d17d698ad |
| 7060130 | 折射 | 造成魔伤，携带其他系别技能会给本技能带来不同效果。 | unresolved_effect_details | 850709371e81ceea9409c3f19c48823d2859ab52e93344b232aa11728f965f0d |
| 7060140 | 漫反射 | 每种系别中的至多1个技能，威力+35。 | description_not_fully_supported | 170ac35cd6e22d0799cd242868504c9d083b223de0026b2e6f6ef659bc0a788f |
| 7060260 | 透镜实验 | 造成物伤，选择：敌方携带光系技能时威力+50或应对状态时被应对的技能变为透射。 | description_not_fully_supported; unresolved_desc_notes | 231ba70a3c4e609edabed3dd5e08c305e0b96b4c01869d5a2c1dea48f7fba5a2 |
| 7060270 | 色散 | 造成魔伤，对混血精灵造成伤害+50%。 | description_not_fully_supported; unresolved_desc_notes | 27c43c9e2dab70c208abef770154cfc64924e754ae0055d80b581ae06dedc074 |
| 7060280 | 分光 | 自己获得魔攻+20%，己方队伍中精灵每有1个不同的系别，额外获得魔攻+10%。 | description_not_fully_supported | 23d4e968ac1d8352a1d1242c60190d5a88b45f2a6f01ae4e9cb7abbd54f360df |
| 7070020 | 齿轮扭矩 | 造成物伤，每回合位置发生变化时，本技能威力永久+15。 | description_not_fully_supported | d94ced3c25b24c9549f275f216ea21065089c3333df41a2b3bcaac98c585c612 |
| 7070060 | 轴承支撑 | 主动：本技能被动永久额外-1能耗，被动：两侧技能能耗-1，传动1。 | description_not_fully_supported; unresolved_desc_notes | 8d392bae8dcf060d4f16cd590f41be7d960ed9d61948859214169faae3b876e4 |
| 7070070 | 联动装置 | 使用后两侧技能的威力永久+20，应对防御：变为威力永久+30。 | description_not_fully_supported; unresolved_desc_notes | a3802728137604dff00525d7cb84c2df9f23d80c1baca7b83593a69c51500006 |
| 7070080 | 能量守恒 | 减伤80%，应对攻击：两侧技能能耗永久-1。 | description_not_fully_supported; unresolved_desc_notes | 49681cdcabb9731ea863db859340f5f39cd5320b0213736fbb3739bdeca373a2 |
| 7070170 | 啮合传递 | 自己获得速度+30，本技能位于1号或3号位时额外获得物攻+80%，传动1。 | description_not_fully_supported; unresolved_desc_notes | bc5d70f426c67c664e23bdd9d951049206f3e5f63d903e1092269f189952204a |
| 7070250 | 减压阀 | 主动：本技能被动永久额外+20威力，被动：两侧技能威力+10，传动1。 | description_not_fully_supported; unresolved_desc_notes | 75ef10d07ad66fdedb73aa8a06a9eab6f89db1dc7f6ead6180bee68c76a99b72 |
| 7070260 | 排气 | 敌方获得威力-20，自己每受到1次抵抗伤害（不含连击），敌方额外获得威力-20，使用后重置。 | description_not_fully_supported | 08533303b2b02182eb1f3f841fdc9c80bce27fcc31fb269aec2d1c5f7a4c0f7c |
| 7070270 | 相位移动 | 减伤50%，本技能位于1号位或3号位时，额外减伤40%，应对攻击，传动1。 | description_not_fully_supported; unresolved_desc_notes | b8e490c0777c8526edb16e1065ccb68405ff133acebccb9a16ab4d210a868ff3 |
| 7070290 | 过山车 | 使己方队伍中的所有精灵携带的技能跨精灵向下移动1个位置，巧变：机械系技能。 | description_not_fully_supported; unresolved_desc_notes | 096554f95a987ac1fa982638f0923cdd28bea12f3f9db9436b8134e6aee025a5 |
| 7080230 | 硬化 | 减伤90%，若上次使用攻击技则本技能能耗-2，应对攻击。 | description_not_fully_supported; unresolved_desc_notes | f2f799fd5dfe178a4011a7e46c96baf30b9f082315b328d6b7808e170d092578 |
| 7080320 | 鸣沙陷阱 | 造成物伤，物防比敌方越高，本次技能威力越高。 | unresolved_effect_details | 9f7cc3a2602d6502c7b308307a20032fa68fc2b3ee3e32ab23c022086f19a21d |
| 7090190 | 霜天 | 敌方获得1层冻结，且每有1层冻结获得全技能能耗+1。 | description_not_fully_supported; unresolved_desc_notes | bdeb72b52754663c106ebaedad4f2b5a4711ca96a4ec4455784fee3651a2adf7 |
| 7090360 | 冰锋横扫 | 造成魔伤，本技能威力等于敌方精灵技能总能耗的10倍。 | description_not_fully_supported | 3eae09713bf76b1e422f00e0dfbdefe08072c164c92704bb0281a924429becad |
| 7090440 | 寒潮 | 造成魔伤，敌方获得1层冻结，应对状态：额外获得4层冻结，巧变：冻结相关技能。 | description_not_fully_supported; unresolved_desc_notes | 780ceb1b757aad46e1defa5baae35f5dff865e00484d2ffcc113e0294e494784 |
| 7100250 | 龙血 | 减伤70%，本技能可以在蓄力状态下使用，应对攻击：下次技能无需蓄力。 | description_not_fully_supported; unresolved_desc_notes | 2243f3863e0bc9bb91cb30bf91808265f9e8d4c5cb5c61babcc899315e24d182 |
| 7100300 | 龙守望 | 下次技能无需蓄力，本技能可在蓄力状态下使用。选择：本次能耗-1或应对防御时打断，敌方下回合获得眩晕。 | description_not_fully_supported; unresolved_desc_notes | 89f58b28752ff533b1c2cece530c398057f0b1cd977ba7515d6e5f424d205010 |
| 7110240 | 雷暴 | 造成魔伤，迸发：本技能获得所有生效过的迸发，每获得1种，本技能能耗+1，威力+10。 | description_not_fully_supported; unresolved_desc_notes | 7cc1a70745b25a3cda55696851a9b011cf667c497dcc1b8ac681c1cc2b27a54d |
| 7110250 | 麻痹 | 敌方先手-1，应对防御：额外使敌方获得双攻-70%。 | description_not_fully_supported; unresolved_desc_notes | 8f66a76d8e1d5509b2206d59baac91626d095ff3479c92fc3f28ecd5775fc37a |
| 7110350 | 双联脉冲 | 造成魔伤，迸发：本技能使用次数+1。 | description_not_fully_supported; unresolved_desc_notes | a61737d8fa350e4a0cf52bf91e951a57ebb0f5320281e568c360491246273183 |
| 7110360 | 过载回路 | 回合结束自己返场，下回合所选技能使用次数+1。 | description_not_fully_supported; unresolved_desc_notes | 1885717ce459a89a8ee790e7d7fe080222b2b99a787d5e5022e54e597815f08e |
| 7110380 | 感电 | 造成魔伤，每离场1次，本技能使用次数永久+1。 | description_not_fully_supported; unresolved_desc_notes | 5fc14d1c08d1bf916a0a1f8d0bcdb1b254f7cd2b90d05a1d122b4914823e37ef |
| 7110420 | 电磁偏转 | 减伤70%，应对攻击：下回合所选技能使用次数+1。 | description_not_fully_supported; unresolved_desc_notes | b286fcce74d3bb46e9251c79a44d243fc762d385013eff4787e4361880bb4f3a |
| 7110460 | 踏雷 | 自己回合结束时返场，携带的攻击技能下回合获得1个已触发过的迸发效果，应对防御：改为获得所有触发过的迸发效果。 | description_not_fully_supported; unresolved_desc_notes | 0bb01036912be3d3ea4537b41f7919480593534976b52649a86540a6a65dda44 |
| 7120110 | 感染病 | 造成魔伤，若击败敌方则将中毒转化为中毒印记。 | description_not_fully_supported; unresolved_desc_notes | c42636b8a0f1353ca0a3557992700ed6c9080cd4ba9bbb1ee5e9b001bbd4bdfd |
| 7130220 | 掩护 | 减伤70%，紧急脱离，应对攻击：下个入场精灵获得减伤。 | description_not_fully_supported; unresolved_desc_notes | 972b2a5ba32486d41358f4f8a308ce536f2e7bac670cc3e114a90634b68c8be1 |
| 7130290 | 翅刃 | 造成物伤，驱散敌方所有印记，应对状态：改为偷取印记。 | description_not_fully_supported; unresolved_desc_notes | a2868f6b4d42b970fef224243c0938bc8989273a78f1ad156a4beb564c8feb68 |
| 7130320 | 虫结阵 | 减伤80%，应对攻击：己方队伍获得1次随机奉献。 | description_not_fully_supported; unresolved_desc_notes | 294d07c58c5461605f848dec4d50452184d9a973ca17a697ce54cadfb2fe6a91 |
| 7130360 | 信息素 | 己方队伍获得1次随机奉献，若上回合双方有精灵使用地系技能，额外获得3次随机奉献。 | description_not_fully_supported; unresolved_desc_notes | 1cf5d6012af670f99f4ee18f30ce831242c6715b52b0600f5c58728cc29ae226 |
| 7130370 | 迁飞扩散 | 造成物伤，若敌方本回合更换精灵，己方队伍获得3次随机奉献。 | description_not_fully_supported; unresolved_desc_notes | 749cf53763f116e48bc5becde849bd52156f18c4143c816876c77f49d4daec9f |
| 7140130 | 截拳 | 造成物伤，应对状态：造成打断，回复被打断技能能耗的能量。 | description_not_fully_supported; unresolved_desc_notes | 6b44d6c3a7c80396ecd78e622f84de27bee2cfd1122ef474aecffbf3bae73120 |
| 7140170 | 气沉丹田 | 自己回复60%生命，获得物攻+130%，每次应对后本技能能耗-3，使用后能耗重置。 | description_not_fully_supported | f31f2616353a3438ae1d63f6fda6b54e2c082d49e2062c389cbf40f7c358d4ac |
| 7140180 | 硬门 | 应对攻击：打断被应对技能，并造成90威力物伤。 | description_not_fully_supported; unresolved_desc_notes | 2ef8aa19d18807fc5822ff6d9507f9008218659130b7a7f2bd44b59377a8ffde |
| 7140190 | 听桥 | 减伤60%，应对攻击：对敌方造成武系物理伤害，威力与被应对技能相等。 | description_not_fully_supported; unresolved_desc_notes | dc4e3ef684c08f495f6c3548460d26909fe63ba1fa3657a035125aa4c4af6a71 |
| 7140330 | 马步 | 本技能先手-1，选择：若自己生命低于20%，回复60%生命或若自己生命高于80%，获得物攻+150%。 | description_not_fully_supported; unresolved_desc_notes | 7931e6d835a7ce2c0fba0ba4f1565768966cedee36a27d665cc0b6449ea1f6c4 |
| 7150170 | 疾风涡轮 | 造成物伤，无法主动使用，在使用3次翼系技能后会自动使用此技能。 | description_not_fully_supported | e263a1d26a4ad57353c29fb941e8227d759b38c49cb601322e18efbb9a06fe0d |
| 7150250 | 闪击 | 造成物伤，速度比敌方越高，本次技能威力越高。 | unresolved_effect_details | 6effe85dd80e63160833c3be0bf2bc96ef2c5b8f80d53034dbcbe669490cf45f |
| 7150320 | 疾风连袭 | 释放自己释放过的迅捷技能，其能耗之和的二分之一加至本技能能耗，每次使用后能耗+1。 | description_not_fully_supported | c1ad0240d70e55ab198b1170757a116083743e2700b95d2e542c301e2edc47a9 |
| 7150360 | 试飞 | 造成物伤，2连击。选择：每次使用后本技能威力永久+10或连击数永久+1。 | description_not_fully_supported; unresolved_desc_notes | d004b3aa6ce353d46adc26b623b69064d067f4cf747a4d098ecec858ab3a3186 |
| 7150400 | 月影交错 | 造成物伤，2连击，若上回合双方有精灵使用幻系技能，本技能获得迅捷。 | description_not_fully_supported; unresolved_desc_notes | b5259a6c3fd78f47957ab97afd5f1dedb5a84868e7d8c50f809d49756342a318 |
| 7160140 | 超级糖果 | 造成物伤，自己获得萌化：本次技能威力+60。 | description_not_fully_supported; unresolved_desc_notes | 6b096a15eff40f00b66e23a1fcc21e8a8135a608ad106eda6ad14c690fe868ee |
| 7160150 | 砂糖弹球 | 造成物伤，双方体重差越大，本次技能威力越高。 | unresolved_effect_details | 1c8d3cc0da6e25edf8802cdbc6bab8d991caa2cf43cff11c9cf899993ba968a2 |
| 7160170 | 示弱 | 自己获得萌化：速度永久+130。 | description_not_fully_supported; unresolved_desc_notes | 63b0611190cccc58ee186fa0e0525171009b84b9c4a7fde8c27936b3e4e8abc2 |
| 7160180 | 赤子之心 | 自己获得萌化：全技能能耗永久-2。 | description_not_fully_supported; unresolved_desc_notes | 40c8fbde5ff3d8e0d74c20396a6028ab8e936f5dce960b0d3835b218526144af |
| 7160190 | 反弹 | 将自己的萌化转移给敌方。 | description_not_fully_supported; unresolved_desc_notes | b183cc0bed4c1bfb4e06e8d2f5da63ef7e4cfbe09408f629489b6997f4d0d4e7 |
| 7160200 | 甜心续航 | 自己和敌方获得萌化：回复40%生命。 | description_not_fully_supported; unresolved_desc_notes | 184ef7b56cbba30236fa7d0061c9f1079506337b0b19c04b5661932a3b0b54f1 |
| 7160250 | 撒娇 | 造成魔伤，3连击。自己获得萌化：全技能威力永久+10。 | description_not_fully_supported; unresolved_desc_notes | ec251ebbf207a291c579a7725276cfc8202fea3bab165b696c736d8aba0e6ec2 |
| 7160280 | 月光合奏 | 造成物伤，1连击，双方携带的所有精灵每有1层萌化，本次技能连击数+1。 | description_not_fully_supported; unresolved_desc_notes | d1f048ca2ce113c2293d7c6ac1fe28f48286e1d91f3c23de3bce98a62dd0cba5 |
| 7160290 | 捧杀 | 减伤90%，应对攻击：敌方获得1层萌化。 | description_not_fully_supported; unresolved_desc_notes | 7fdb2a57feb4ef89cc8a82d6e5266b6100044caba43d8c0b5fe6628418ef7e54 |
| 7160330 | 拆礼物 | 造成物伤，若敌方有萌化，本次技能威力+100。 | description_not_fully_supported; unresolved_desc_notes | 5819de1dab07c88e193329d1350d1b963e927ac6d8199f1a2f25430716f031c0 |
| 7160360 | 转圈圈 | 造成魔伤，若敌方本回合更换精灵，本次攻击使敌方获得萌化。 | description_not_fully_supported; unresolved_desc_notes | 67e56b80cf96504eecae844d469b949f7c8b853d927980fa4a2c99a4184c957e |
| 7160370 | 蹦跶 | 造成魔伤，自己有减益时本技能能耗-1，选择：自己获得萌化或解除萌化。 | description_not_fully_supported; unresolved_desc_notes | 87009a20aeda3735df58399c242ae450fc4e0c54f6c1bbf852c4dfe65faa0203 |
| 7160400 | 做好事 | 造成魔伤，自己每使用过1次选择技能，自己获得3层随机永久属性增益，使用后重置。 | description_not_fully_supported; unresolved_desc_notes | f970c1575d31fd6b812e5d9e108000f20912219134c233142e2e50c282ce2d7a |
| 7170310 | 吃独食 | 造成魔伤，自己每使用过1次选择技能，敌方获得3层随机永久属性减益，使用后重置。 | description_not_fully_supported; unresolved_desc_notes | 95821d288366833f81fd48989e9ae416fd597859f0fc34a01802372fd8897684 |
| 7180300 | 骗局 | 造成魔伤，能量不足时，消耗5%生命代替1能量。 | description_not_fully_supported | 4876b7d8c070f402dd6d434c31a8fbcd8558adbb56cab2f04c61387b072b6c58 |
| 7180330 | 虚假破产 | 减伤80%，能量不足时，消耗5%生命代替1能量，应对攻击。 | description_not_fully_supported; unresolved_desc_notes | d3cfe304073c1e4a66dd56ea41fcbb0e8ac6cd2358e695383dbb143df6740933 |
| 7180350 | 伪造账单 | 若敌方本回合回复生命，改为失去2倍（含溢出的回复量）。先手+1。 | description_not_fully_supported; unresolved_desc_notes | f5958a94dce0bacda9e7e8abebd722ed59ab205d0491fef9ab0c1cb678058fa7 |
| 7180420 | 下注 | 造成物伤，选择：本次技能威力+40，使用后自己生命-10%或自己生命低于50%时本次技能威力+100。 | description_not_fully_supported; unresolved_desc_notes | 0db0029edb4918ad8ef01d94336faac2dc6ed26652e01271653d9ec0c6acf1dc |
| 7180430 | 杂耍 | 造成魔伤，巧变：吸血相关技能。 | description_not_fully_supported; unresolved_desc_notes | dee48e1cda50b3af109c56a709c78c570b50e247966851e14a52083fcbb25ff5 |
| 7180440 | 假冒 | 自己的生命比例变为与敌方生命比例相同，巧变：恶系攻击技能。 | description_not_fully_supported; unresolved_desc_notes | eb315f99e9ea29f12852a02f3ab313dd10be91d60da9c7e6e660f03e5e185f5b |
| 7190220 | 空间压迫 | 造成物伤，敌方获得1层星陨印记。 | description_not_fully_supported; unresolved_desc_notes | 20ab20cf76517941eebfb3f4f2b0c93b2c860fe70aec3a0870f03e246fdeae1c |
| 7190260 | 多维击打 | 造成魔伤，1连击，敌方每有1层星陨印记，本次技能连击数+1。 | description_not_fully_supported; unresolved_desc_notes | 4da1c984990085aa71617c1b4ffbd4b1de2a08f8449384201aa9c3dc43ad80a2 |
| 7190270 | 错乱 | 造成魔伤，应对状态：敌方获得3层星陨印记。 | description_not_fully_supported; unresolved_desc_notes | c413400683dcaf46bf0b353772e1bcfabccf5de42fef6e97666157c35bbc48b2 |
| 7190280 | 超维投射 | 敌方获得4层星陨印记。 | description_not_fully_supported; unresolved_desc_notes | 3baf1615bda37b78a1be2bf258ac646a456be8d8f2c1c65714c14c3fb71e88f0 |
| 7190290 | 星轨裂变 | 敌方获得2层星陨印记。 | description_not_fully_supported; unresolved_desc_notes | bc0d0b7679985ddee512225a2f35083c92086be5537427bd65f5c4e7e7359a2c |
| 7190300 | 星链 | 2连击，每次连击使敌方获得1层星陨印记。 | description_not_fully_supported; unresolved_desc_notes | a874b3eff4a38729da425d0fe3bcea2bb4a3d7029a3d1ef3773cd59e1e5785e0 |
| 7190310 | 超新星馈赠 | 敌方获得2层星陨印记，每使用1次，赋予的星陨印记层数永久+1。 | description_not_fully_supported; unresolved_desc_notes | 01de6adf97c2437b5f97db0ff4e1608a9c5335086a58af54274e6cdf77fbf2e2 |
| 7190320 | 心灵洞悉 | 敌方获得星陨印记，获得层数等于敌方印记层数。 | description_not_fully_supported; unresolved_desc_notes | a0be3370669c1cd19303fd3a46d2d6bf5b16cfb7510060b443297a11f7d03450 |
| 7190330 | 二律背反 | 敌方获得3层星陨印记，应对防御：额外使敌方星陨印记层数翻倍。 | description_not_fully_supported; unresolved_desc_notes | c94a8b9a6a71d0c1227bace878d833ff783538b3c651b4219fb99a5a5aefd2f7 |
| 7190400 | 冥想 | 减伤80%，应对攻击：敌方获得2层星陨印记。 | description_not_fully_supported; unresolved_desc_notes | 895b980c4d2182a27ce8593c9da96b20f345a2be5d71af9f85d6e2f8356dfa14 |
| 7190430 | 叠加态 | 自己获得随机16层属性增益，巧变：幻系攻击技能。 | description_not_fully_supported; unresolved_desc_notes | df9c147495c694c5bd1462c3336dc424d7c04d401075a333d4737a28b35ebb0f |
| 7190450 | 薄纱环 | 选择：敌方随机获得1种负面印记或自己随机获得1种正面印记。 | description_not_fully_supported; unresolved_desc_notes | c842fd6b0b1e415c33f57601a2e1ab8b25a7dbf8e25681bf71823c303233b08d |
| 7190460 | 重组 | 下一次攻击时，额外造成100%幻系伤害，应对防御：改为额外造成300%幻系伤害。 | description_not_fully_supported; unresolved_desc_notes | 020e81e6839cefa63040e16ba3945aa96053e1e6ad4ef05a5f45fbd0cc3d54e1 |
| 7190490 | 观测者效应 | 自己脱离，更换入场的精灵以月陨星状态登场。 | description_not_fully_supported; unresolved_desc_notes | 222e828b0caa99689d2bb502ca70ac135c69eac2d303b02178ff3ae375465f72 |
| 7190500 | 量子涨落 | 造成物伤，若敌方没有星陨印记，则敌方获得3层星陨印记。 | description_not_fully_supported; unresolved_desc_notes | 69033d907b9151dc9833572ece6399795c2dbacd3a0dfa0e6a697c39e0982465 |
| 7190510 | 奇点 | 造成魔伤，若上回合双方有精灵使用水系技能，敌方获得4层星陨印记。 | description_not_fully_supported; unresolved_desc_notes | 4a4bd3ed21e8710bd7b94fe9505cbce719036b2bb6ba94c1ae23086a8fba8592 |
| 7190520 | 引力偏转 | 减伤80%，应对攻击：以魔法伤害触发敌方的星陨效果。 | description_not_fully_supported; unresolved_desc_notes | 32cf92a9d4a598bea461f076ef4548f44bee32813887af290970d220c4d114d9 |

## Focused verification for final six

- `test_received_defense_per_hit_and_prevented_damage_receipts`: two-hit positive damage produces two stat grants; absorption heals from two validated prevented-damage receipts; source cost increases once; a resolver without explain blocks absorption.
- `test_target_cooldown_and_defense_interrupt_binding`: only the declared enemy skill is blocked on turns2/3 after turn1 application; both new interruption sources cancel the matching pending defense action.
- Direct configuration check: all three duration composites execute and validate their stored entries; 7180190 prefix changes physical cost2→6 while defense cost stays2.
- Both persistent tests passed in one focused run (2 tests,4.284s). No full-suite run was requested or performed for this batch. Full forced-switch orchestration remains owned by the existing switch integration, rather than claimed from the prefix check.

## Additional three source-resolved closures

| Skill | Source | Implementation |
|---|---|---|
|7050280水环|7050281 grants20320220→2032007, unit all-cost-1,type1,rest1|60%guard; successful attack response grants all-cost-2 via existing source ledger.|
|7020800血气|7020801 grants20380110→2038011 order38 [0],[1],[0]..., current-turn expiry,rest1|Successful guard prevents each lethal damage during its current turn; source does not specify one-use consumption. Public prevent_lethal returns damage,event. Explicit HP payment/self-consumption and freeze exhaustion are not damage callbacks.|
|7020660激怒|20320040→2032004 order32 amount3; description explicitly excludes skills released during acquisition turn, three-turn duration|Application-turn candidate release is exempt; later costs consult only actual committed history from that application turn. Interrupted/uncommitted declarations never enter the exemption. Multiple actual releases are all exempt under a named policy; application turn counts toward duration.|

The targeted test `test_guard_survival_water_cost_and_actual_turn_used_skill_exclusion` covers repeated lethal multi-hit survival, expiration, water cost reduction, precommit versus actual-history exclusions, and three-turn expiration. Source configs retain full raw records/hashes.


## Subsequent source-resolved composition closures

The inventory above is an earlier snapshot; these entries are now admitted by their complete runtime wrappers:

| Skill | Retained source and full behavior |
|---|---|
|7021170 倾泻|1004097 explicitly lists 28 positive/negative BUFF variants, count99 both sides. After magical damage, clear both members' mark slots only when explicit `opponent_defended_this_attack` is false; absent predicate blocks. Parent supplies actual committed current-actor guard response, not merely a defense declaration.|
|7040680 焚尽|1042015 clears the same source pool from self and grants five 20010010 per removed layer; actual 10% BUFF units recorded, so 3 removed mark layers become 15 dispellable patk layers.21460200→2146020 specifies fire attack clever change.|
|7050510 清洗|1004002 removes self debuffs; energy_rule19 `[0,3,0,2,0,-1]` supplies -1 per actual debuff layer.21460210→2146021 specifies water attack clever change. Cost uses validated source units and complete current debuff ledger, not number of entries.|
|7180440 假冒|1088001 order88 `[1],[1]` copies opponent HP ratio to self; preserves opponent and snapshots both max/current values. Integer floor and minimum1 for living members are named research policy.21460280 specifies evil attack clever change.|
|7130320 掩护|20110310→2011031 provides80% guard;1031142→7130321→1016005 response draw remains owned by random-devotion wrapper. Defense component adds no duplicate draw.|
|7180330 虚假破产|80% attack-response guard now has a program; existing full reviewed-health-payment source config remains the authoritative payment wrapper. No energy is fabricated.|

Type-filtered clever-change pools retain the existing catalog-candidate policy, not a claim of exact current-server pool identity. Whole raw records, source hashes, and extracted transformation bindings remain in configuration.

Focused verification: mark clear/defended branch,15 true reward layers, debuff-layer cost before/after clearing, old defense coverage assertion (2 tests passed,5.667s); copied ratio floor-to-min1, unchanged opponent, stale guard inactivity and missing-turn rejection (1 test passed,3.651s). No full suite.

Additional exact source gaps inspected:

-7060130 折射:20890020→2089001 maps carried type to18 callback chains (20640140 through20640310). These include heal15%, energy-2, ordinary stats/hits/cost/status, lifesteal3, and the phantom branch20172050→20940010 star-fall mark. A complete implementation needs that mark semantics; omitting this branch is not supported. Light branch is explicitly empty. Multiple carried-type/duplicate application timing also needs a named execution policy.
-7180430 杂耍: action metadata reports `pool_basis=unavailable_current_special_pool`, no current `pool_ids`; historical pool24 contains8 skill IDs. Current `_3_P` extraction lacks skillid. Historical candidates must not be relabeled as a verified current pool.
-7020550 魔能爆: energy_rule1 `[0]` and damage_rule36 `[1,450000,700000,900000,1100000,1350000,1550000,1650000,1800000,1900000,2000000,2100000]` are retained raw evidence. No proven interpretation/units of that array was located; dividing by10000 without a source is not justified.
-Weight skills7020990/7021000/7160150 use damage_rule35 and explicit output arrays, but extracted skill records do not contain weight-ratio threshold boundaries. Searching the available decompiled scripts and parsed table filenames did not establish those thresholds; no arbitrary bins were introduced.
