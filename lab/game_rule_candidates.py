"""Read-only extracted evidence -> inactive, source-bound rule candidates.

No game scripts execute. Field domains, missing values, reference slots and
parameter order remain distinct. This staging schema is NOT a published rule.
"""
from copy import deepcopy
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path

TABLES = ("SKILL_CONF", "EFFECT_CONF", "BUFF_CONF", "BUFFBASE_CONF", "BATTLE_CONF",
          "PVP_CONF", "BATTLE_RULE_CONF", "BATTLE_GLOBAL_CONFIG")
SCHEMA = "roco-game-rule-candidates-1"
COMMIT = "460fc477bad0f9db3cfc387365a6699ee246377e"
BLOCKERS = ["runtime_package_precedence_unverified", "online_overrides_unverified",
            "field_defaults_require_native_and_callsite_review", "execution_semantics_require_code_binding"]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def reject(value):
        raise ValueError("Nonfinite JSON: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)


def _inside(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Evidence path escapes its directory")
    return path


def bounded_reader(base):
    class BoundedBin(base):
        def read(self, count):
            if self.p < 0 or self.p > len(self.b):
                raise ValueError("Negative or out-of-bounds binary position")
            return super().read(count)

        def entries(self, offset, count):
            if offset < 0 or offset > len(self.b) or count < 0 or offset + count * 16 > len(self.b):
                raise ValueError("Invalid binary entry section")
            return super().entries(offset, count)
    return BoundedBin


def load_evidence(analysis_dir):
    """Recheck extraction hashes and binary/JSON parity using the pinned probe."""
    root = Path(analysis_dir).resolve()
    provenance = read_json(root / "provenance.json")
    if provenance.get("cue4parse_commit") != COMMIT:
        raise ValueError("Unreviewed CUE4Parse version")
    parser_path = root.parent / "parse_roco_tables.py"
    expected = [p for p in provenance["analysis_scripts"] if p["file"] == parser_path.name]
    if len(expected) != 1 or expected[0]["sha256"] != file_hash(parser_path):
        raise ValueError("Probe parser source changed; review required")
    manifests, entries = {}, {}
    for name in ("table_manifest.json", "effect_table_manifest.json"):
        manifest = read_json(root / name)
        manifests[name] = file_hash(root / name)
        for entry in manifest["files"]:
            path = _inside(root.parent / entry["output"].replace("\\", "/"), root)
            if path in entries:
                raise ValueError("Ambiguous extraction manifest")
            if file_hash(path) != entry["payload_sha256"]:
                raise ValueError("Extracted payload hash mismatch: " + path.name)
            entries[path] = deepcopy(entry)
    spec = importlib.util.spec_from_file_location("verified_roco_table_probe", parser_path)
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)

    BoundedBin = bounded_reader(parser.Bin)

    tables, sources = {}, {}
    for name in TABLES:
        folder = root / "tables"
        paths = {"schema": folder / "BinConf" / (name + ".non"),
                 "binary": folder / "BinDataCompressed" / (name + ".bytes")}
        local = folder / "BinLocalize" / "dev_CN" / (name + ".bytes")
        if local.exists():
            paths["localization"] = local
        if any(p not in entries for p in paths.values()):
            raise ValueError("Missing extraction provenance for " + name)
        schema = read_json(paths["schema"])
        binary = BoundedBin(paths["binary"].read_bytes())
        localization = BoundedBin(local.read_bytes(), True) if local.exists() else None
        rows = binary.parse_rows(schema, localization)
        parsed = folder / "parsed" / (name + ".json")
        if digest(rows) != digest(read_json(parsed)):
            raise ValueError("Parsed JSON differs from binary: " + name)
        tables[name] = rows
        sources[name] = {"records": len(rows), "declared_rows": binary.count,
                         "row_lengths_reverified": True, "parsed_sha256": file_hash(parsed),
                         "rows_content_sha256": digest(rows), "schema": schema,
                         "unresolved_localization_ids": sorted(set(binary.unresolved)),
                         "files": {role: {"local_path": str(p), **entries[p]} for role, p in paths.items()}}
    identity = {name: {role: source["payload_sha256"] for role, source in s["files"].items()}
                for name, s in sources.items()}
    return {"source_id": "local-game-" + digest(identity)[:20], "tables": tables, "table_sources": sources,
            "provenance": {"cue4parse_commit": COMMIT, "parser_sha256": file_hash(parser_path),
                           "adapter_sha256": file_hash(__file__), "manifest_sha256": manifests,
                           "provenance_sha256": file_hash(root / "provenance.json")},
            "validation": {"extracted_payload_hashes_verified": True, "binary_json_parity": True,
                           "runtime_applicability_verified": False, "archive_reread_this_step": False}}


def fields(row, names):
    return {name: {"present": name in row, **({"value": deepcopy(row[name])} if name in row else {})}
            for name in names}


def reference(tables, names, value):
    if type(value) is not int:
        return {"status": "invalid_id", "targets": []}
    if value == 0:
        return {"status": "explicit_zero", "targets": []}
    hits = [f"{name}:{value}" for name in names if str(value) in tables[name]]
    return {"status": "resolved" if len(hits) == 1 else "ambiguous" if hits else "missing", "targets": hits}


def bwiki_match(row, catalog):
    hits = [(kind, catalog.get(kind, {}).get(str(row["id"]))) for kind in ("moves", "traits")]
    hits = [(kind, record) for kind, record in hits if record is not None]
    if not hits:
        return {"status": "absent_from_bwiki_snapshot", "active_pvp_eligibility": "unknown"}
    if len(hits) != 1:
        return {"status": "ambiguous_bwiki_record_kind", "kinds": [kind for kind, _ in hits],
                "active_pvp_eligibility": "unknown"}
    kind, other = hits[0]
    comparisons = {}
    for game, wiki in (("energy_cost", "energy"), ("dam_para", "power")):
        value = row.get(game)
        comparison = "not_comparable"
        if isinstance(value, list) and len(value) == 1 and type(value[0]) is int and type(other.get(wiki)) is int:
            comparison = "numeric_equal" if value[0] == other[wiki] else "numeric_different"
        comparisons[game] = {"status": comparison, "game_raw": fields(row, [game])[game],
                             "bwiki_raw": fields(other, [wiki])[wiki], "semantic_equivalence_verified": False}
    return {"status": "same_game_id", "record_kind": kind, "snapshot_id": catalog.get("snapshot_id"), "record_hash": digest(other),
            "name": deepcopy(other.get("name")), "fields": comparisons, "active_pvp_eligibility": "unknown"}


def load_field_bindings(report_path, project_root):
    if report_path is None:
        return {}
    bindings = deepcopy(read_json(report_path).get("field_bindings", {}))
    for field, binding in bindings.items():
        if field not in {"EFFECT_CONF.effect_order", "BUFFBASE_CONF.buffbase_order", "BUFF_CONF.buff_group_reduce[].reduce_type"}:
            raise ValueError("Unreviewed field domain: " + field)
        if not binding.get("binding_evidence") or not binding.get("enum_evidence") or not isinstance(binding.get("mapping"), dict):
            raise ValueError("Field binding needs code evidence and explicit map")
        for evidence in binding["binding_evidence"] + binding["enum_evidence"]:
            path = _inside(Path(project_root) / evidence["file"], project_root)
            if file_hash(path) != evidence["sha256"]:
                raise ValueError("Field binding source changed: " + field)
            if (type(evidence.get("line_start")) is not int or type(evidence.get("line_end")) is not int
                    or not 1 <= evidence["line_start"] <= evidence["line_end"]):
                raise ValueError("Invalid field binding source lines")
            if evidence["line_end"] > len(path.read_text(encoding="utf-8").splitlines()):
                raise ValueError("Field binding lines exceed source length")
        if any(not k.isdecimal() or not isinstance(v, str) or not v for k, v in binding["mapping"].items()):
            raise ValueError("Invalid enum map")
    return bindings


def build_candidates(evidence, bwiki_catalog, field_bindings=None):
    tables = evidence["tables"]
    if set(tables) != set(TABLES):
        raise ValueError("Expected all eight reviewed tables")
    for name, rows in tables.items():
        key_field = evidence["table_sources"][name]["schema"]["UniqueKey"]
        if any(str(row.get(key_field)) != key for key, row in rows.items()):
            raise ValueError("Candidate input primary key mismatch: " + name)
    bindings, nodes, counts = deepcopy(field_bindings or {}), {}, Counter()
    for name, rows in tables.items():
        for key, row in rows.items():
            node = {"id": f"{name}:{key}", "table": name, "row_key": key, "raw": deepcopy(row),
                    "evidence": {"source_id": evidence["source_id"], "table": name, "row_key": key,
                                 "record_sha256": digest(row)}, "references": [], "uncertainties": list(BLOCKERS)}
            refs = []
            if name == "SKILL_CONF":
                for index, item in enumerate(row.get("skill_result", [])):
                    resolved = reference(tables, ("EFFECT_CONF", "BUFF_CONF"), item["effect_id"]) if "effect_id" in item else {"status": "absent_id", "targets": []}
                    refs.append({"field": "skill_result", "index": index, "raw": deepcopy(item),
                                 "id_present": "effect_id" in item, **resolved})
            elif name == "BUFF_CONF":
                for index, value in enumerate(row.get("buff_base_ids", [])):
                    refs.append({"field": "buff_base_ids", "index": index, "raw": value,
                                 **reference(tables, ("BUFFBASE_CONF",), value)})
            for ref in refs:
                counts[name + ".references." + ref["status"]] += 1
                if ref["status"] == "resolved":
                    counts[name + ".targets." + ref["targets"][0].split(":")[0]] += 1
            node["references"] = refs
            field = "effect_order" if name == "EFFECT_CONF" else "buffbase_order" if name == "BUFFBASE_CONF" else None
            domain = f"{name}.{field}" if field else None
            if domain in bindings and field in row:
                binding = bindings[domain]
                node["handler_annotation"] = {"field_domain": domain, "raw_value": row[field],
                    "enum_namespace": binding["enum_namespace"], "symbol": binding["mapping"].get(str(row[field])),
                    "binding_evidence": deepcopy(binding["binding_evidence"]),
                    "enum_evidence": deepcopy(binding["enum_evidence"]),
                    "parameter_semantics_verified": False, "execution_order_verified": False}
            nodes[node["id"]] = node
    candidates = {}
    for key, row in tables["SKILL_CONF"].items():
        node, components = nodes[f"SKILL_CONF:{key}"], []
        groups = {"cost": ("energy_rule", "energy_cost"), "damage": ("damage_rule", "dam_para", "damage_type"),
                  "target": ("target_type", "target_field", "target_blood_limit"),
                  "ordering": ("skill_priority",), "cooldown": ("cd_round",)}
        for role, names in groups.items():
            components.append({"id": role, "kind": "unresolved_game_component", "role": role,
                "raw_fields": fields(row, names), "evidence": deepcopy(node["evidence"]),
                "effect": None, "target": None, "params": None,
                "uncertainties": ["field_semantics_and_defaults_unresolved"]})
        for ref in node["references"]:
            components.append({"id": "result:" + str(ref["index"]), "kind": "unresolved_game_component",
                "role": "result_reference", "reference": deepcopy(ref),
                "trigger_domain": "SKILL_CONF.skill_result.cast_moment",
                "trigger": fields(ref["raw"], ["cast_moment"])["cast_moment"],
                "evidence": deepcopy(node["evidence"]),
                "uncertainties": ["reference_order_is_not_verified_execution_order", "trigger_domain_not_bound"]})
        candidates[key] = {"rule_id": "skill:" + key, "source_node": node["id"], "status": "candidate_not_published",
            "components": components, "bwiki_comparison": bwiki_match(row, bwiki_catalog),
            "capabilities": {"file_configuration_parsed": True,
                "references_resolved": all(r["status"] in ("resolved", "explicit_zero") for r in node["references"]),
                "runtime_rule_validated": False, "components_executable": False,
                "full_battle_executable": False, "real_game_calibrated": False}, "blockers": list(BLOCKERS)}
    return {"schema_version": SCHEMA, "source_id": evidence["source_id"],
            "source_provenance": deepcopy(evidence["provenance"]), "source_validation": deepcopy(evidence["validation"]),
            "table_sources": deepcopy(evidence["table_sources"]), "nodes": nodes, "skills": candidates,
            "reference_counts": dict(counts), "field_bindings": bindings,
            "active_rules_modified": False, "training_eligible": False,
            "capability_counts": {"file_configurations_read": len(candidates), "runtime_rules_validated": 0,
                "components_executable": 0, "full_battle_executable": 0, "real_game_calibrated": 0}}


def validate_candidates(bundle):
    """Check graph integrity without promoting uncertain mechanics to execution."""
    errors = []
    try:
        if bundle["schema_version"] != SCHEMA:
            raise ValueError("Unknown candidate schema")
        if bundle["training_eligible"] is not False or bundle["active_rules_modified"] is not False:
            raise ValueError("Candidates cannot authorize training or replace active rules")
        nodes = bundle["nodes"]
        tables = {name: {} for name in TABLES}
        for key, node in nodes.items():
            if node["table"] not in tables or key != f"{node['table']}:{node['row_key']}":
                raise ValueError("Invalid graph node identity")
            if node["id"] != key or digest(node["raw"]) != node["evidence"]["record_sha256"]:
                raise ValueError("Graph raw record identity/hash mismatch")
            if node["evidence"]["source_id"] != bundle["source_id"]:
                raise ValueError("Graph source mismatch")
            tables[node["table"]][node["row_key"]] = node["raw"]
        for name, rows in tables.items():
            if digest(rows) != bundle["table_sources"][name]["rows_content_sha256"]:
                raise ValueError("Graph table content differs from source: " + name)
        if set(bundle["skills"]) != set(tables["SKILL_CONF"]):
            raise ValueError("Candidate skill inventory differs from source")
        expected_bundle = build_candidates({"source_id": bundle["source_id"], "tables": tables,
            "table_sources": bundle["table_sources"], "provenance": bundle["source_provenance"],
            "validation": bundle["source_validation"]}, {}, bundle["field_bindings"])
        if digest(nodes) != digest(expected_bundle["nodes"]) or digest(bundle["reference_counts"]) != digest(expected_bundle["reference_counts"]):
            raise ValueError("Candidate references/annotations/counts differ from raw records")
        for key, rule in bundle["skills"].items():
            actual_rule = {k: v for k, v in rule.items() if k != "bwiki_comparison"}
            expected_rule = {k: v for k, v in expected_bundle["skills"][key].items() if k != "bwiki_comparison"}
            if digest(actual_rule) != digest(expected_rule):
                raise ValueError("Candidate components differ from raw records")
            node = nodes["SKILL_CONF:" + key]
            if rule["rule_id"] != "skill:" + key or rule["source_node"] != node["id"]:
                raise ValueError("Candidate identity mismatch")
            for flag in ("runtime_rule_validated", "components_executable", "full_battle_executable", "real_game_calibrated"):
                if rule["capabilities"][flag] is not False:
                    raise ValueError("Unresolved candidate claims execution")
            expected_ids = ["cost", "damage", "target", "ordering", "cooldown"]
            expected_ids += ["result:" + str(i) for i in range(len(node["raw"].get("skill_result", [])))]
            if [c["id"] for c in rule["components"]] != expected_ids:
                raise ValueError("Candidate component order changed")
            for component in rule["components"]:
                if component["kind"] != "unresolved_game_component" or component["evidence"] != node["evidence"]:
                    raise ValueError("Candidate component source/state changed")
                if "raw_fields" in component and component["raw_fields"] != fields(node["raw"], component["raw_fields"]):
                    raise ValueError("Missing/zero/raw field distinction changed")
                if component["role"] == "result_reference":
                    index = component["reference"]["index"]
                    raw = node["raw"]["skill_result"][index]
                    expected = reference(tables, ("EFFECT_CONF", "BUFF_CONF"), raw["effect_id"]) if "effect_id" in raw else {"status": "absent_id", "targets": []}
                    if (component["reference"]["raw"] != raw or
                            any(component["reference"][name] != expected[name] for name in ("status", "targets")) or
                            component["trigger_domain"] != "SKILL_CONF.skill_result.cast_moment" or
                            component["trigger"] != fields(raw, ["cast_moment"])["cast_moment"]):
                        raise ValueError("Candidate reference or field domain changed")
        for key, node in nodes.items():
            for ref in node["references"]:
                for target in ref["targets"]:
                    if target not in nodes:
                        raise ValueError("Dangling candidate graph edge")
        expected_counts = {"file_configurations_read": len(bundle["skills"]), "runtime_rules_validated": 0,
                           "components_executable": 0, "full_battle_executable": 0, "real_game_calibrated": 0}
        if digest(bundle["capability_counts"]) != digest(expected_counts):
            raise ValueError("Candidate capability counts disagree")
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        errors.append(str(exc))
    return errors


def publish_candidates(bundle, output):
    errors = validate_candidates(bundle)
    if errors:
        raise ValueError("Invalid candidate graph: " + "; ".join(errors))
    output = Path(output)
    raw = (json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    if output.exists():
        if output.read_bytes() != raw:
            raise ValueError("Candidate artifact differs; choose a new revision instead of overwriting")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as stream:
            stream.write(raw)
    return {"path": str(output), "sha256": hashlib.sha256(raw).hexdigest(), "source_id": bundle["source_id"],
            "counts": bundle["capability_counts"], "reference_counts": bundle["reference_counts"], "training_eligible": False}
