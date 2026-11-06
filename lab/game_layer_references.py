"""Version-isolated skill -> buff -> base-buff reference candidates.

Layer operands come from verified schema and bytes, never from prose ratios.
Cross-archive schemas require an explicit resource-group manifest; the original
archive loader remains strict. This module does not execute effects.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

from lab.game_rule_candidates import (COMMIT, bounded_reader, digest, file_hash,
                                      read_json, reference)

SCHEMA = "roco-game-layer-references-1"
TABLES = ("SKILL_CONF", "BUFF_CONF", "BUFFBASE_CONF", "EFFECT_CONF")
APPLICATION_FIELDS = ("effect_id", "cast_moment", "result_target_type", "success_rate",
                      "buff_level_rule", "buff_group_level")


def tracing_reader(base):
    """Retain byte spans for scalar skill_result fields while the parser reads them."""
    class TracedBin(bounded_reader(base)):
        def __init__(self, *args, **kwargs):
            self.result_spans = {}
            self._contexts = []
            self._spans = []
            self._slot = 0
            super().__init__(*args, **kwargs)

        def parse_struct(self, schema, loc, depth=0):
            if depth == 0:
                self._contexts, self._spans, self._slot = [], [], 0
            value = super().parse_struct(schema, loc, depth)
            if depth == 0 and "id" in value:
                self.result_spans[str(value["id"])] = deepcopy(self._spans)
            return value

        def prop(self, prop, loc, depth):
            offset = self.p
            is_result = prop["Name"] == "skill_result" and prop["Type"] == "EStruct"
            if is_result:
                self._contexts.append(self._slot)
                self._slot += 1
            try:
                value = super().prop(prop, loc, depth)
                if self._contexts and prop["Name"] in APPLICATION_FIELDS and prop["Type"] != "EStruct":
                    self._spans.append({"slot": self._contexts[-1], "field": prop["Name"],
                        "type": prop["Type"], "offset": offset, "length": self.p - offset,
                        "raw_hex": self.b[offset:self.p].hex(), "value": deepcopy(value)})
                return value
            finally:
                if is_result:
                    self._contexts.pop()
    return TracedBin


def _verified_reader(probe_dir):
    probe_dir = Path(probe_dir).resolve()
    provenance_path = probe_dir / "battle_analysis/provenance.json"
    provenance = read_json(provenance_path)
    parser_path = probe_dir / "parse_roco_tables.py"
    parser_hash = file_hash(parser_path)
    expected = [e for e in provenance["analysis_scripts"] if e["file"] == parser_path.name]
    if (provenance["cue4parse_commit"] != COMMIT or len(expected) != 1
            or expected[0]["sha256"] != parser_hash):
        raise ValueError("Unreviewed binary parser provenance")
    spec = importlib.util.spec_from_file_location("layer_reference_verified_probe", parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    Reader = tracing_reader(parser.Bin)
    return Reader, parser_hash


def load_archive_variants(manifests, probe_dir):
    """Accept extraction manifests; require schema/data from the SAME archive."""
    probe_dir = Path(probe_dir).resolve()
    Reader, parser_hash = _verified_reader(probe_dir)
    groups = {}
    for manifest_path in manifests:
        manifest_path = Path(manifest_path).resolve()
        manifest = read_json(manifest_path)
        if isinstance(manifest, dict):
            manifest = manifest["files"]
        for entry in manifest:
            name = Path(entry["path"]).stem
            if name not in TABLES:
                continue
            remote = entry["path"].replace("\\", "/")
            role = next((role for segment, role in (("/BinConf/", "schema"),
                ("/BinDataCompressed/", "binary"), ("/BinLocalize/dev_CN/", "localization"))
                if segment in remote), None)
            if role is None:
                continue
            path = (manifest_path.parent / entry["output"].replace("\\", "/")).resolve()
            if not path.is_relative_to(manifest_path.parent):
                raise ValueError("Extraction path escapes manifest directory")
            if file_hash(path) != entry["payload_sha256"]:
                raise ValueError("Payload hash mismatch: " + str(path))
            files = groups.setdefault(entry["pak"], {}).setdefault(name, {})
            if role in files:
                raise ValueError("Duplicate archive/table/role in manifests")
            files[role] = {"path": str(path), "manifest": str(manifest_path),
                "manifest_sha256": file_hash(manifest_path), "extraction": deepcopy(entry)}
    variants = {}
    for archive, table_files in sorted(groups.items()):
        if "SKILL_CONF" not in table_files or "BUFF_CONF" not in table_files:
            raise ValueError("Archive needs its own skill and buff tables: " + archive)
        tables, sources, spans = {}, {}, {}
        for name, files in sorted(table_files.items()):
            if not {"schema", "binary"} <= files.keys():
                raise ValueError("Incomplete same-archive schema/data pair")
            schema = read_json(files["schema"]["path"])
            binary = Reader(Path(files["binary"]["path"]).read_bytes())
            loc = Reader(Path(files["localization"]["path"]).read_bytes(), True) if "localization" in files else None
            rows = binary.parse_rows(schema, loc)
            tables[name] = rows
            sources[name] = {"schema": schema, "files": files, "rows": len(rows),
                "declared_rows": binary.count, "rows_content_sha256": digest(rows),
                "all_row_lengths_verified": True, "unresolved_localization_ids": sorted(set(binary.unresolved))}
            if name == "SKILL_CONF":
                spans = binary.result_spans
        identity = {t: {r: f["extraction"]["payload_sha256"] for r, f in s["files"].items()}
                    for t, s in sources.items()}
        source_id = "archive-" + digest({"archive": archive, "payloads": identity})[:20]
        variants[source_id] = {"source_id": source_id, "archive": archive, "tables": tables,
            "table_sources": sources, "result_field_spans": spans, "parser_sha256": parser_hash,
            "probe_dir": str(probe_dir),
            "adapter_sha256": file_hash(__file__), "cue4parse_commit": COMMIT,
            "runtime_precedence_verified": False, "online_applicability_verified": False}
    return variants


def load_resource_group_variants(resource_groups, probe_dir):
    """Load only explicitly selected resources; never search for a fallback.

    A group declares each role's extraction manifest, manifest hash, archive,
    resource path, payload hash and selection basis. Cross-archive selection is
    limited to schemas; it is a parsing candidate, not mounted-version evidence.
    """
    probe_dir = Path(probe_dir).resolve()
    Reader, parser_hash = _verified_reader(probe_dir)
    variants = {}
    segments = {"schema": "/BinConf/", "binary": "/BinDataCompressed/",
                "localization": "/BinLocalize/dev_CN/"}
    for group_path in resource_groups:
        group_path = Path(group_path).resolve()
        group = read_json(group_path)
        if (group.get("schema_version") != "roco-explicit-resource-group-1"
                or group.get("runtime_precedence_verified") is not False
                or group.get("online_applicability_verified") is not False):
            raise ValueError("Resource group must declare unverified runtime applicability")
        if not {"SKILL_CONF", "BUFF_CONF"} <= group["tables"].keys():
            raise ValueError("Resource group needs skill and buff tables")
        tables, sources, spans = {}, {}, {}
        for name, resources in sorted(group["tables"].items()):
            if name not in TABLES or not {"schema", "binary"} <= resources.keys():
                raise ValueError("Incomplete or unsupported resource-group table")
            files = {}
            for role, selection in sorted(resources.items()):
                if role not in segments or not selection["selection_basis"].strip():
                    raise ValueError("Resource selection needs a supported role and explicit basis")
                if role != "schema" and selection["archive"] != group["archive"]:
                    raise ValueError("Only explicit schema selection may cross archives")
                manifest_path = (group_path.parent / selection["manifest"]).resolve()
                if file_hash(manifest_path) != selection["manifest_sha256"]:
                    raise ValueError("Resource-group manifest hash mismatch")
                entries = read_json(manifest_path)
                if isinstance(entries, dict):
                    entries = entries["files"]
                matches = [entry for entry in entries if entry["pak"] == selection["archive"]
                           and entry["path"] == selection["resource_path"]
                           and entry["payload_sha256"] == selection["payload_sha256"]]
                if len(matches) != 1:
                    raise ValueError("Resource selection must identify one manifest entry")
                entry = matches[0]
                if (Path(entry["path"]).stem != name
                        or segments[role] not in entry["path"].replace("\\", "/")):
                    raise ValueError("Resource selection disagrees with table/role")
                path = (manifest_path.parent / entry["output"].replace("\\", "/")).resolve()
                if not path.is_relative_to(manifest_path.parent):
                    raise ValueError("Extraction path escapes manifest directory")
                if file_hash(path) != selection["payload_sha256"]:
                    raise ValueError("Payload hash mismatch: " + str(path))
                files[role] = {"path": str(path), "manifest": str(manifest_path),
                    "manifest_sha256": selection["manifest_sha256"], "extraction": deepcopy(entry),
                    "selection_basis": selection["selection_basis"]}
            schema = read_json(files["schema"]["path"])
            binary = Reader(Path(files["binary"]["path"]).read_bytes())
            loc = Reader(Path(files["localization"]["path"]).read_bytes(), True) if "localization" in files else None
            rows = binary.parse_rows(schema, loc)
            tables[name] = rows
            sources[name] = {"schema": schema, "files": files, "rows": len(rows),
                "declared_rows": binary.count, "rows_content_sha256": digest(rows),
                "all_row_lengths_verified": True, "unresolved_localization_ids": sorted(set(binary.unresolved)),
                "same_archive_schema_data": files["schema"]["extraction"]["pak"] == files["binary"]["extraction"]["pak"]}
            if name == "SKILL_CONF":
                spans = binary.result_spans
        source_id = "resource-group-" + digest(group)[:20]
        if source_id in variants:
            raise ValueError("Duplicate explicit resource group")
        variants[source_id] = {"source_id": source_id, "archive": group["archive"], "tables": tables,
            "table_sources": sources, "result_field_spans": spans, "parser_sha256": parser_hash,
            "probe_dir": str(probe_dir), "adapter_sha256": file_hash(__file__), "cue4parse_commit": COMMIT,
            "resource_group": {"path": str(group_path), "sha256": file_hash(group_path), "declaration": group},
            "runtime_precedence_verified": False, "online_applicability_verified": False}
    return variants


def field_operand(raw, descriptors, name):
    descriptor = descriptors.get(name)
    if descriptor is None and name in raw:
        raise ValueError("Raw field absent from its own schema: " + name)
    return {"state": "not_in_schema" if descriptor is None else "explicit" if name in raw else "absent_in_record",
            "schema_declared": descriptor is not None, "schema_type": descriptor.get("Type") if descriptor else None,
            "present": name in raw, **({"value": deepcopy(raw[name])} if name in raw else {})}


def _result_descriptors(variant):
    props = variant["table_sources"]["SKILL_CONF"]["schema"]["Properties"]
    results = [p for p in props if p["Name"] == "skill_result"]
    if len(results) != 1 or results[0]["Type"] != "EStruct":
        raise ValueError("Expected one structured skill_result field")
    return {p["Name"]: p for p in results[0]["Struct"]["Properties"]}


def build_layer_references(variants):
    nodes, applications, comparisons, counts = {}, {}, {}, {}
    for source_id, variant in sorted(variants.items()):
        if source_id != variant["source_id"]:
            raise ValueError("Variant source identity mismatch")
        tables = {t: variant["tables"].get(t, {}) for t in TABLES}
        descriptors = _result_descriptors(variant)
        for table, rows in variant["tables"].items():
            if table not in TABLES:
                raise ValueError("Unsupported reference table")
            if digest(rows) != variant["table_sources"][table]["rows_content_sha256"]:
                raise ValueError("Variant table content changed")
            for key, raw in rows.items():
                if str(raw.get("id")) != key:
                    raise ValueError("Variant primary key mismatch")
                node_id = f"{source_id}/{table}:{key}"
                nodes[node_id] = {"source_id": source_id, "table": table, "row_key": key,
                    "raw": deepcopy(raw), "record_sha256": digest(raw)}
        summary = {"skill_records": len(tables["SKILL_CONF"]), "result_slots": 0, "buff_references": 0,
                   "explicit_layer_operands": 0, "buff_refs_with_explicit_layer_operand": 0,
                   "layer_field_absent_in_record": 0, "layer_field_not_in_schema": 0}
        for key, row in tables["SKILL_CONF"].items():
            refs = []
            for index, raw in enumerate(row.get("skill_result", [])):
                hit = reference(tables, ("BUFF_CONF", "EFFECT_CONF"), raw["effect_id"]) if "effect_id" in raw else {"status": "absent_id", "targets": []}
                target = hit["targets"][0] if hit["status"] == "resolved" else None
                is_buff = target is not None and target.startswith("BUFF_CONF:")
                operands = {name: field_operand(raw, descriptors, name) for name in APPLICATION_FIELDS}
                buff = tables["BUFF_CONF"][str(raw["effect_id"])] if is_buff else None
                base_refs = []
                for base_index, base_id in enumerate(buff.get("buff_base_ids", []) if buff else []):
                    base_hit = reference(tables, ("BUFFBASE_CONF",), base_id)
                    if "BUFFBASE_CONF" not in variant["tables"] and base_id != 0:
                        base_hit = {"status": "table_unavailable", "targets": []}
                    base_refs.append({"index": base_index, "raw_id": base_id, "status": base_hit["status"],
                        "targets": [source_id + "/" + t for t in base_hit["targets"]]})
                item_id = f"{source_id}/SKILL_CONF:{key}/skill_result:{index}"
                spans = [s for s in variant.get("result_field_spans", {}).get(key, []) if s["slot"] == index]
                component = {"id": item_id, "kind": "state_application_reference" if is_buff else "result_reference",
                    "source_node": f"{source_id}/SKILL_CONF:{key}", "slot": index,
                    "raw_reference": deepcopy(raw), "status": hit["status"],
                    "targets": [source_id + "/" + t for t in hit["targets"]], "operands": operands,
                    "operand_byte_spans": deepcopy(spans), "base_references": base_refs,
                    "effective_stack_count": None, "per_stack_formula": None,
                    "runtime_executable": False, "training_eligible": False,
                    "blockers": ["runtime_version_unverified", "layer_rule_and_default_semantics_unverified",
                        "target_and_trigger_semantics_unverified", "per_stack_formula_unverified"],
                    "historical_fallback_applied": False}
                applications[item_id] = component
                refs.append(item_id)
                summary["result_slots"] += 1
                summary["buff_references"] += int(is_buff)
                state = operands["buff_group_level"]["state"]
                if state == "explicit":
                    summary["explicit_layer_operands"] += 1
                    summary["buff_refs_with_explicit_layer_operand"] += int(is_buff)
                else:
                    summary["layer_field_" + state] += 1
            comparisons.setdefault(key, []).append({"source_id": source_id, "archive": variant["archive"],
                "skill_node": f"{source_id}/SKILL_CONF:{key}", "ordered_applications": refs})
        counts[source_id] = summary
    return {"schema_version": SCHEMA, "variants": deepcopy(variants), "nodes": nodes,
        "applications": applications, "skills_by_version": comparisons, "counts": counts,
        "active_rules_modified": False, "training_eligible": False, "runtime_executable": False}


def validate_layer_references(bundle, verify_sources=False):
    """Check derived graph; publishing additionally reparses hash-checked sources."""
    try:
        if bundle["schema_version"] != SCHEMA:
            raise ValueError("Unknown layer reference schema")
        expected = build_layer_references(bundle["variants"])
        if digest(bundle) != digest(expected):
            raise ValueError("Layer graph differs from source records and schemas")
        for variant in bundle["variants"].values():
            for key, spans in variant.get("result_field_spans", {}).items():
                row = variant["tables"]["SKILL_CONF"][key]
                for span in spans:
                    value = row["skill_result"][span["slot"]][span["field"]]
                    if digest(value) != digest(span["value"]):
                        raise ValueError("Byte evidence disagrees with parsed operand")
        if verify_sources:
            probe_dirs = {v["probe_dir"] for v in bundle["variants"].values()}
            if len(probe_dirs) != 1:
                raise ValueError("Expected one verified parser source")
            strict_variants = [v for v in bundle["variants"].values() if "resource_group" not in v]
            manifests = sorted({f["manifest"] for v in strict_variants
                for s in v["table_sources"].values() for f in s["files"].values()})
            reparsed = load_archive_variants(manifests, next(iter(probe_dirs))) if manifests else {}
            groups = [v["resource_group"]["path"] for v in bundle["variants"].values() if "resource_group" in v]
            if groups:
                reparsed.update(load_resource_group_variants(groups, next(iter(probe_dirs))))
            if digest(bundle["variants"]) != digest(reparsed):
                raise ValueError("Variant evidence differs from reverified files")
        return []
    except (KeyError, ValueError, TypeError, IndexError) as error:
        return [str(error)]


def save_layer_references(bundle, output):
    errors = validate_layer_references(bundle, verify_sources=True)
    if errors:
        raise ValueError("Invalid layer references: " + "; ".join(errors))
    raw = (json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    output = Path(output)
    if output.exists():
        if output.read_bytes() != raw:
            raise ValueError("Choose a new revision; existing layer artifact differs")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(raw)
    return {"path": str(output), "sha256": file_hash(output), "counts": bundle["counts"],
            "runtime_executable": False, "training_eligible": False}
