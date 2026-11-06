# Mechanism completion wave 20261026 — batch b2

## Engine
- ENGINE_REVISION: `composable-battle-20261026-8` → `composable-battle-20261026-9`
- Admission snapshot on entry: 84 unadmitted of 579 (the prior remaining JSON recorded 75; the delta of 9
  water/rock/ice/electric skills is a concurrent/snapshot drift, not a regression introduced here).
- Admission snapshot after this batch: **83 unadmitted of 579**.

## What was actually wired this batch

### 硬化 7080230 (地系 defense) — admitted
Source evidence (parsed game tables):
- SKILL_CONF 7080230: `energy_rule 14`, `energy_cost [2,1,0,-2,0,0]`, `skill_result` → buff 20110230,
  effect 1031068, buff 20620060, all cast_moment 11.
- BUFF_CONF 20110230 = "减伤"; BUFFBASE_CONF 2011023 `buffbase_param[4]=[-9000]` → confirms 90% reduction.
- effect_order 31 (1031068) references sub-skill 7080231 "应对！硬化" → confirms 应对攻击 response.
- BUFF_CONF 20620060 (buffbase_order 62) = shared defense cooldown marker, same shape as existing 7020780.

Wired as a reviewed defense program in `data/rules/reviewed-defense-components-1.json`:
- `reduction {90,100}`, `responses ["attack"]`, `shared_cooldown_rounds 1`.
- New reviewed field `conditional_cost` = `{when_previous_kind:[physical,magical], discount:2,
  policy:floor_zero_experiment}`.

### New runtime hook: reviewed defense conditional energy cost
- `lab/defense_runtime.py`: added `conditional_cost(state, side, skill_id, value)`. It reads the reviewed
  defense_components; only when a `conditional_cost` block is present does it inspect the active member's
  `committed_skill_history`, apply the discount when the member committed a listed-kind skill on turn-1, and
  floor at zero. Skills without the block return cost unchanged (one config scan, no history read).
- `lab/research_phases.py`: `_resolved_cost` now calls `defense.conditional_cost(...)` in the cost chain.
- This is an explicit experimental policy: the live trigger boundary (turn-1 attack vs. "last attack skill"
  across switches) is NOT calibrated. Documented in `installation_uncertainty`.

## Verification actually run this batch
- `tests.test_defense_runtime`: **16 tests OK** (added
  `test_hardening_conditional_cost_discounts_after_previous_attack` covering: no-attack turn keeps cost,
  previous physical → discount, previous magical → discount, stale history → no discount, non-conditional
  skill → ignored).
- Admission scan after wiring: 7080230 `supported=True, blockers=[]`; defense programs count 39→40.

## Pre-existing failures (NOT introduced here, flagged for next owner)
`tests.test_research_phases` has 2 failures that reproduce even with the new cost line commented out:
- `test_speed_terms_floor_then_tie_and_nonpositive_rejection` — expects `blocked`/"effective speed must be
  positive", gets `applied`.
- `test_uncompiled_charge_sets_up_but_does_not_fake_complete_release` — expects `blocked`, gets `applied`.
These point to speed-floor and charge-setup admission being looser than the tests expect; they pre-date this
batch and need a separate decision (experiment drift vs. real bug).

## Not done this batch (next priorities, with reason)
- 排气 7070260: needs a received-resisted-attack counter that grows an OPPONENT power debuff and resets on
  use — new component (skill_history currently applies to self power, not opponent debuff).
- 气沉丹田 7140170: heal 60% + patk buff + per-response cost −3 that resets on use — needs a response-
  triggered, self-resetting cost ledger distinct from permanent skill_history.
- 疾风涡轮 7150170 / 疾风连袭 7150320: auto-release after 3 Flying skills, and Swift-release replay with
  accumulated energy — new auto-cast / replay dispatch (the audit's whole_release_dispatch_gap).
- Slot-transmission family (轴承支撑/联动装置/能量守恒/啮合传递/减压阀/相位移动/过山车), 萌化 lifecycle,
  trait 200294 gain-event boundary, star-field/连击/复活/体重/属性差威力 — untouched this batch.
