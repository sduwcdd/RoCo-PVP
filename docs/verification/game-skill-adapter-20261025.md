# Executable game-file skill components

`lab/game_skill_adapter.py` now converts source-bound extracted records into callable `stat.modify`, `energy.reduce`, and `energy.restore` operations. Selection is by enum-bound opcode and parameter structure, never skill ID, name, or description parsing. Existing active BWIKI files are not edited.

## API

```python
from lab.game_skill_adapter import (
    load_game_skill_adapter, experimental_game_policy,
    game_skill_context, execute_game_skill,
)

adapter = load_game_skill_adapter()  # Verify sources once; reuse this instance.
source_id = "resource-group-c40d72d37c3c43a12b3f"
program = adapter.compile(source_id, 7170280, experimental_game_policy(source_id))
context = game_skill_context(program, resolved_energy_cost=2)
result = execute_game_skill(program, relative_actor_state, context)
```

`adapter.sources()` exposes available source IDs and archives. `adapter.compile()` caches source/skill/policy combinations and returns isolated copies. `adapter.coverage(source_id, policy)` performs one metadata pass, then compiles only eligible rows without revalidating the complete source graph for every record. The standalone `compile_game_skill(bundle, source_id, skill_id, policy)` remains available and validates its supplied graph each call.

Base source: `archive-a45a57add3edf933f964`. Patch-2 explicit resource group: `resource-group-c40d72d37c3c43a12b3f`. Patch 3 remains separate and cannot borrow missing fields from either source.

## Executable experiment contract

The named `game-file-components-experiment-1` policy explicitly selects file-slot order, cast-moment code 11, result-target codes 1=self and 2=opponent, explicit success-rate operand 10000, literal declared layer operands when `buff_level_rule` is absent, and parameter interpretation. Those selections remain experiment assumptions, not authoritative native/server formula claims.

For `BFT_ATTR_CHANGE`, the supported three ordered parameter groups are `[AttributeType]`, `[0]`, `[basis_points]`. A known signed attribute enum is converted into one separate rational stat term using `sign * basis_points * buff_group_level / 10000`. This executes the existing runtime's stat-term update; it does not calculate a final effective panel or solve buff lifetime/refresh/cancellation rules. For `ET_CHANGE_ENERGY`, `[signed_delta]`, `[0]`, `[0]` applies that delta once with explicit experimental cap/floor policies. An EFFECT record's group operand is retained and is not treated as a buff or energy multiplier.

The current adapter requires a pure-result action layout: explicit zero primary damage, a single integer energy-cost operand, zero cooldown layout, deterministic simple hit/target metadata, and no unadapted action fields. Unknown damage/cost rules, charge fields, result fields, parameter layouts, probabilities, triggers, references or explicit layer rules reject the whole compilation. Empty and explicit-zero result slots stay in evidence as noops.

Successful programs expose `research_skill_override_allowed=True`, `whole_skill_verified=False`, and scope `isolated_game_file_skill_result_fragment`. `execution_blockers=[]` means no blocker within that selected experiment scope; unresolved native timing, duration, stacking, units and live-version applicability remain in `execution_uncertainties`. Research-turn integration still requires its own explicit policy. Runtime payment is caller resolved, including zero; it is not silently inferred from the source's base cost.

`game_file_evidence` retains source IDs, archives, per-role extraction/hash metadata, raw referenced records and ordered parameters, result slots, original layer values, byte spans, enum-source hash, and policy. Successful runtime results retain component observations and source/program hashes. Program/policy mutations reject without changing the caller's state. All results remain uncalibrated and ineligible for training.

## Verification

The dedicated regression suite covers real base strength ID 7020620 (10 layers, physical attack term +10000/10000), base magic ID 7020630 (7 layers, magical attack term +7000/10000), and patch-2 mirror ID 7170280 (5 layers, magical defense term -5000/10000 plus opponent energy reduction 3). An unrelated synthetic ID also executes through the same opcode paths, including a positive energy effect. Tests cover policy and source isolation, mutation/insufficient-payment rollback, unknown action semantics, missing fields, parameter order, and snapshot caching.

The real API integration tests additionally execute patch-2 mirror in a research turn and verify the standalone game-file endpoint's source identity and raw five-layer operand. This is executable research behavior, not a claim of a complete or calibrated battle engine.
