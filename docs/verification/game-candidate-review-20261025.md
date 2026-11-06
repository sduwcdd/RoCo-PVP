# Game candidate adapter independent review — 2026-10-25

Scope: `lab/game_rule_candidates.py`, `tests/test_game_rule_candidates.py`, and `scripts/build_game_rule_candidates.py`. The reviewer read and reparsed existing evidence; no game files or original extraction artifacts were modified. Small probes were run through Python stdin and left no script files.

## Source data independently rechecked

`load_evidence` reparsed all eight binary tables and checked existing parsed JSON parity. Row counts were SKILL_CONF 1988, EFFECT_CONF 1259, BUFF_CONF 3312, BUFFBASE_CONF 2813, BATTLE_CONF 7313, PVP_CONF 10, BATTLE_RULE_CONF 263, BATTLE_GLOBAL_CONFIG 620: total 17578.

The graph had 3445 resolved SKILL_CONF result references (1988 BUFF_CONF and 1457 EFFECT_CONF), 3041 absent result IDs, 4603 resolved BUFFBASE_CONF references, and one explicit-zero buff reference. All 3041 absent-ID skill-result slots were actual empty `{}` objects; preserving them preserves array position. `SKILL_CONF:7150080` retained absent `energy_rule` and present `energy_cost: [3]` separately. The 1988 SKILL_CONF rows are source-table records, not a verified count of usable battle moves. Their IDs independently matched 579 BWIKI moves and 246 BWIKI traits, with zero overlap between those matched categories.

The initial new candidate test suite passed all 13 tests in 3.426 seconds. This alone did not cover the mutation failures below. No large historical test suite was run.

## Findings and reproduction

1. Initial graph validation accepted wrong existing targets, deleted node references, changed buff-reference status/targets, and fabricated `reference_counts`. Only dangling-target existence was checked. Reproduced with a synthetic source and with a real skill node. The subsequently added graph reconstruction comparison rejected these mutations.
2. Initial component validation accepted deleting `energy_cost` from `raw_fields`, claiming an absent result ID was present, setting cost `effect`/`target`/`params` to executable-looking values, and removing trigger uncertainty. Expected field names were derived from the submitted component, and node/reference duplicates were not compared comprehensively. The subsequently added full reconstructed-rule comparison rejected these mutations.
3. A transient reconstruction patch reused `expected` both for the rebuilt bundle and an individual reference. Two records each with `skill_result: [{}]` then caused `validate_candidates` to return `["'skills'"]`. The final patch uses `expected_bundle`; independent probes confirmed both a two-record source and the complete real source validate successfully.
4. Plain Python dictionary equality conflates JSON boolean/integer/float values. Changing a component's `energy_cost` from `[0]` to `[False]` still validated after the first reconstruction patch. The final patch compares canonical JSON digests for reconstructed nodes/rules/counts, and binary-versus-parsed JSON parity. Independent probes confirmed rejection of `[0]` to `[False]`, `[0]` to `[0.0]`, reference index `0` to `False`, and capability count `0` to `False`.

## Other boundaries inspected

- `reference` distinguishes integer zero, absent ID, missing target, ambiguous IDs across EFFECT_CONF/BUFF_CONF, and invalid boolean IDs. No cross-table preference was guessed.
- The bounded binary adapter rejects negative cursors and invalid entry-directory bounds; the pinned probe already rejects negative read lengths.
- Default extraction and BWIKI paths originate from project-root absolute paths. Explicit relative extraction/output arguments follow normal process working-directory semantics.
- Publishing uses exclusive file creation, accepts identical existing bytes, and rejects a differing revision without overwriting it. Existing publication-isolation tests passed.
- The candidate builder is imported by its build script and dedicated tests; the inspected active catalog loader reads its existing published BWIKI snapshot. The candidate schema fails current active-rule validation and retains false execution/training gates.
- Field bindings initially annotated EFFECT_CONF.effect_order and BUFFBASE_CONF.buffbase_order; the final inspected allowlist additionally includes BUFF_CONF.buff_group_reduce[].reduce_type. Result trigger domains and parameter semantics remain unresolved. Binding-code line ranges are checked for ordering and positive integers, not whether the specified lines establish semantic correctness; that remains review evidence rather than execution authorization.

## Final retest

All four reproduced findings were corrected. `python -m unittest tests.test_game_rule_candidates -v` passed 17 tests in 10.944 seconds, including the new multi-record graph-tampering, JSON-type-substitution, trait-category, and hash-verified-handler-binding regressions. The real source bundle independently returned an empty validation error list. The final inspected adapter SHA-256 was `47214cf89800b8b8ad072d9c97fbe71b3002f71dfa0f2c31351097193a47c26a`.

The updated BWIKI comparison checks both moves and traits, retains `record_kind`, and reports ambiguity instead of choosing a category if a synthetic catalog has the same ID in both. The user's description of magic-mirror stacks is user-provided evidence; this review does not establish its mapping to a specific extracted record or native handler.

No remaining blocker was found in the reviewed adapter/script/test scope. Runtime package precedence, live overrides, unresolved defaults, trigger/parameter execution semantics, and real-game calibration remain explicitly unresolved; these staging candidates are not verified usable battle rules.
