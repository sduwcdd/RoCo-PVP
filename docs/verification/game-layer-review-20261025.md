# Archive-isolated layer-reference review — 2026-10-25

Reviewed `lab/game_layer_references.py`, `scripts/build_game_layer_references.py`, and `tests/test_game_layer_references.py`. No main code, game files, or original extraction artifacts were changed by this reviewer. Probes ran through Python stdin and left no scripts.

## Result

No blocking implementation issue was found in the reviewed scope. The dedicated suite passed all **12 tests in 34.877 seconds**. A separate complete real-source build also passed `validate_layer_references(bundle, verify_sources=True)` with an empty error list. Reviewed adapter SHA-256: `d1404682e9b4ec81f1214e3cf80d3226d5e8030bcf8778b0ad699173f49754e1`.

The output is an unresolved, version-isolated reference graph. It does not establish an executable layer count, per-stack formula, runtime archive precedence, or applicability to an online game session.

## Independent source and byte checks

Both supplied extraction manifests were loaded and all recorded payload hashes checked. Schema, binary, and available localization files were grouped by the same `pak` identity; no table from another archive was used to resolve an edge.

| Archive | SKILL_CONF | BUFF_CONF | BUFFBASE_CONF | EFFECT_CONF |
| --- | ---: | ---: | ---: | ---: |
| `pakchunk4-WindowsNoEditor.pak` | 1378 | 1925 | 1879 | 956 |
| `pakchunk4-WindowsNoEditor_3_P.pak` | 1988 | 3309 | 2810 | 1257 |

These are source-table record counts, not verified counts of playable moves. In particular, the patch-3 BUFF/EFFECT counts differ from the older highest-selected mixed candidate snapshot; the two source selections must not be substituted for each other.

The base archive's `SKILL_CONF:7020620`, slot 0, explicitly contains `buff_group_level: 10`. Its span is offset **253703**, length **4**, little-endian bytes **`0a000000`**, schema type `EUint32`. Its same-archive reference chain is `BUFF_CONF:20010010` to `BUFFBASE_CONF:2001001`. The source record does not explicitly provide `buff_level_rule`, so no numeric rule default is introduced.

The base archive's `SKILL_CONF:7020630` explicitly contains `buff_group_level: 7`, with bytes `07000000`. This is a source operand, not a layer value inferred from a strength ratio. IDs `7170280` and `7880001` do not occur in the base SKILL_CONF table.

A separate span checker inspected every explicitly present scalar application field against the corresponding extracted binary file. It verified exact coverage, offset/length slices, hexadecimal bytes, and independent little-endian integer decoding for **8854 base spans** and **6931 patch-3 spans**. Every explicit field had exactly one matching slot/field span; missing fields had none.

## Slot and version preservation

| Archive | Result slots | Empty `{}` slots | Explicit layer operands | Layer field absent in record | Layer field absent from schema |
| --- | ---: | ---: | ---: | ---: | ---: |
| Base | 2675 | 773 | 1257 | 1418 | 0 |
| Patch 3 | 6485 | 3019 | 0 | 0 | 6485 |

Of the base archive's 1257 explicit layer operands, 1117 belong to resolved BUFF references. The base graph has 1118 resolved BUFF applications in total; patch 3 has 1986. This distinction prevents counting every explicit result operand as a verified buff application.

The patch-3 schema does not declare the layer field. Its corresponding records retain `not_in_schema`, no `value`, no historical fallback, and no effective stack count. The base value 10 or 7 is not copied into patch 3. Empty slots, repeated references, zero references, and ordered base-reference positions remain represented separately.

## Validation, isolation, and publication

- Derived applications are rebuilt from their version's records and schema and compared using canonical JSON digests. Numeric, boolean, and float substitutions therefore remain distinct.
- Each graph edge is namespaced by its archive source identity. An unavailable base table remains `table_unavailable`; a same-ID cross-table collision remains ambiguous. Neither case selects another archive.
- `effective_stack_count` and `per_stack_formula` remain `None`; runtime execution, training eligibility, and active-rule modification gates remain false. A layer operand alone does not resolve its rule, trigger, target, or formula semantics.
- Normal validation checks graph consistency against the bundled variant evidence. Publication explicitly requests full source verification, reloads the original manifests and extracted payloads, reparses them, and rejects a coherent forged byte-offset variant.
- The dedicated tests cover changed operands, cross-version edges, execution/training claims, base-reference ordering, typed counts, source-payload hash mismatch, incomplete same-archive pairs, and publication immutability.
- An additional isolation probe mutated nested output references, operand values, and bundled variant rows; the caller's input and an independently built result remained unchanged.
- Saving accepts byte-identical existing output and refuses to overwrite a different existing file. Temporary test outputs were confined to automatically cleaned temporary directories.

The checks above verify the existing extracted payloads and their recorded provenance. This review did not reread the original game archive files, establish native runtime loading order, derive a per-stack formula, or map a user-provided magic-mirror description to an extracted record.
