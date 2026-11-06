# Mirror patch-2 explicit-resource review — 2026-10-25

Reviewed the explicit resource-group API and CLI extension in `lab/game_layer_references.py` and `scripts/build_game_layer_references.py`, the six `MirrorPatch2EvidenceTests`, the resource declaration `game-mirror-patch2-20261025.resources.json`, and the saved `artifacts/game_layer_references_mirror_patch2_20261025/layer_references.json` artifact. No main code or original artifact was modified.

## Result

No blocking issue found in this extension. The **six new tests passed in 11.430 seconds**. The old 18-test combined suite was not repeated. Independently reading the saved artifact and invoking `validate_layer_references(bundle, verify_sources=True)` returned `[]`.

Reviewed adapter SHA-256: `774a73e9446a01569dd1909b9c570d6d75d53a6c1a128f709dd6803d6d9d4252`.

Reviewed artifact SHA-256: `b70b11bc24423fa7f8e8e795614366ac08dccb6fe684f7460bf5e0816b5195aa`.

## Explicit resources and version boundaries

The original archive loader still requires same-archive pairs and rejects the supplied mixed/incomplete mirror manifests. Cross-archive schema selection is confined to the new explicit resource-group loader. It requires an exact extraction-manifest hash, archive name, resource path, payload hash, and nonempty selection basis for every selected role. A missing or changed selection is rejected rather than searched for or replaced automatically. Non-schema resources cannot cross the declared group's archive.

For this declaration, every binary belongs to patch 2. SKILL_CONF and EFFECT_CONF use patch-2 schemas. BUFF_CONF and BUFFBASE_CONF explicitly use patch-0 schemas, retain each role's original archive provenance and `same_archive_schema_data: false`, and carry a selection basis that disclaims verified runtime loading order. Their successful full-row parsing is evidence for a parsing candidate, not proof of the game's mounted schema selection.

The saved artifact separately retains the base archive, strict patch-3 archive, and `resource-group-c40d72d37c3c43a12b3f` patch-2 selection. The patch-2 selection contains 1894 SKILL_CONF, 3028 BUFF_CONF, 2601 BUFFBASE_CONF, and 1173 EFFECT_CONF records. Its IDs and derived edges remain namespaced by that resource-group source; the earlier mixed highest-selected snapshot is not substituted into these tables.

## Independent magic-mirror byte checks

For patch-2 SKILL_CONF ID `7170280`:

| Slot | Original result ID | Reference kind | Original group operand | Extracted binary span |
| --- | ---: | --- | ---: | --- |
| 0 | 20010080 | BUFF_CONF state reference | 5 | offset 333410, length 4, `05000000` |
| 1 | 1019013 | EFFECT_CONF result reference | 1 | offset 338169, length 4, `01000000` |

The reviewer independently read each span from the recorded SKILL_CONF binary and decoded it as a little-endian unsigned integer. Both raw byte sequences and decoded values matched the saved provenance. Slot 0 resolves to BUFF_CONF:20010080 and then BUFFBASE_CONF:2001008 within the resource group. Slot 1 resolves to EFFECT_CONF:1019013, has no base-buff chain, and is not classified as a buff merely because its result contains a group operand. Its retained effect parameters include the original `[-3]` array.

Both records preserve absent `buff_level_rule` without assigning a numeric default. Both retain `effective_stack_count: null`, `per_stack_formula: null`, `runtime_executable: false`, and `training_eligible: false`. This review confirms that the source has a group operand of 5; it does not derive a per-stack percentage or prove the live game's effective stack behavior.

## Validation and publication

The six new tests exercised role-level archive/hash evidence, exact mirror spans and slot classification, rejection of the strict mixed loader, rejection of mismatched manifest hashes or source selections, refusal of cross-archive binary selection, refusal of a runtime-verified declaration, and rejection of a coherently rebuilt forged byte-offset source during full verification.

Full source verification separates strict archive variants from explicit resource-group variants, reloads each with its corresponding loader, and compares the reparsed variant evidence with the saved bundle. The saved mixed-mode artifact passed this independent round trip. `save_layer_references` still invokes this full verification before publication and retains exclusive creation / differing-output rejection.

Only extracted files and their retained provenance were reread. Native runtime package precedence, online applicability, layer/default semantics, and actual formulas remain unverified. The webpage HP display, team-selection flow, and fixed move controls were outside this review.
