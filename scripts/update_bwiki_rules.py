"""Publish source-bound rules offline before activating a new BWIKI catalog."""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab import phase_config, rule_config
from lab.skill_programs import compile_catalog


def _reviewed_transition(old, new, root):
    path = Path(root) / "data/rules/adaptations/bwiki-20261105.json"
    if not path.is_file():
        return {}
    transition = json.loads(path.read_text(encoding="utf-8"))
    if (transition.get("from_snapshot") != old["snapshot_id"]
            or transition.get("to_snapshot") != new["snapshot_id"]):
        return {}
    for category, rows in transition["records"].items():
        before, after = rule_config._index(old[category]), rule_config._index(new[category])
        for key, pair in rows.items():
            if (rule_config._hash(before.get(key)) != pair["before"]
                    or rule_config._hash(after.get(key)) != pair["after"]):
                raise ValueError("Reviewed BWIKI transition source mismatch: " + key)
    for field, expected in transition.get("catalog_fields", {}).items():
        if rule_config._hash(new.get(field)) != expected:
            raise ValueError("Reviewed BWIKI transition catalog mismatch: " + field)
    return transition


def _apply_reviewed_changes(value, recipe, path):
    if rule_config._hash(value) != recipe["before_content_hash"]:
        raise ValueError("Reviewed BWIKI transition config mismatch: " + path)
    result = deepcopy(value)
    for change in recipe["changes"]:
        target = result
        for key in change["path"][:-1]:
            target = target[key]
        key = change["path"][-1]
        if target[key] != change["before"]:
            raise ValueError("Reviewed BWIKI transition field mismatch: " + path)
        target[key] = deepcopy(change["after"])
    return result


def _check_rebinding_scope(old, new, reviewed=None):
    reviewed = reviewed or {}
    for key in ("moves", "traits"):
        before, after = rule_config._index(old[key]), rule_config._index(new[key])
        changed = []
        for sid, record in before.items():
            updated = after.get(sid)
            if updated == record:
                continue
            numeric_only = (key == "moves" and updated is not None
                            and {k: v for k, v in record.items() if k not in {"power", "energy"}}
                            == {k: v for k, v in updated.items() if k not in {"power", "energy"}}
                            and all(type(updated.get(field)) is int and updated[field] >= 0
                                    for field in ("energy", *(["power"] if "power" in record or "power" in updated else []))))
            if not numeric_only and sid not in reviewed.get(key, {}):
                changed.append(sid)
        if changed:
            raise ValueError(f"BWIKI {key} IDs require targeted mechanism review before activation: "
                             + ", ".join(changed[:12]))
    if old.get("glossary") != new.get("glossary"):
        before = {term["key"]: term for term in old.get("glossary", [])}
        after = {term["key"]: term for term in new.get("glossary", [])}
        if (len(before) != len(old.get("glossary", []))
                or len(after) != len(new.get("glossary", []))):
            raise ValueError("BWIKI glossary contains duplicate term IDs")
        changed = [str(key) for key in sorted(before, key=str) if before[key] != after.get(key)]
        if changed:
            raise ValueError("BWIKI term IDs require targeted review before activation: " + ", ".join(changed[:12]))
    before, after = old.get("chart", {}), new.get("chart", {})
    if any(value != after.get(key) for key, value in before.items()):
        raise ValueError("BWIKI chart requires targeted rule review before activation")
    for key in ("types", "chart_schema", "natures"):
        if old.get(key) != new.get(key):
            raise ValueError("BWIKI " + key + " requires targeted rule review before activation")
    configs = []
    for catalog in (old, new):
        config = deepcopy(catalog.get("config", {}))
        for key in ("current_version", "pet_count"):
            config.pop(key, None)
        config.get("build_form", {}).pop("versions", None)
        configs.append(config)
    if configs[0] != configs[1]:
        raise ValueError("BWIKI config fields beyond version/pet-count metadata require targeted review before activation")
    before, after = rule_config._index(old["forms"]), rule_config._index(new["forms"])
    if set(before) - set(after):
        raise ValueError("Removed form IDs require targeted trait/pool review before activation")
    for key, record in before.items():
        fields = set(record) | set(after[key])
        if any(record.get(field) != after[key].get(field) for field in fields - {"stats", "portrait_url"}):
            raise ValueError("BWIKI form " + key + " requires targeted identity/type/trait review before activation")


def _replace_bindings(value, bindings, provenance, records):
    if isinstance(value, str):
        return bindings.get(value, value)
    if isinstance(value, list):
        return [_replace_bindings(item, bindings, provenance, records) for item in value]
    if isinstance(value, dict):
        replacement = records.get(value.get("id"))
        if replacement is not None and value == replacement[0]:
            return deepcopy(replacement[1])
        result = {_replace_bindings(key, bindings, provenance, records): _replace_bindings(item, bindings, provenance, records)
                  for key, item in value.items()}
        for before, after in provenance:
            if (value.get("content_sha256") == before.get("content_sha256")
                    and "content_sha256" in before):
                for key in set(before) & set(after) & set(value):
                    if value[key] == before[key]:
                        result[key] = deepcopy(after[key])
        source = next((records[value[key]] for key in ("source_hash", "record_hash", "skill_record_hash")
                       if isinstance(value.get(key), str) and value[key] in records), None)
        if source:
            before, after = source
            for key in ("source_description", "raw_text", "description"):
                if key in value and value[key] == _description(before):
                    result[key] = _description(after)
        return result
    return value


def _baked_damage(value, power):
    if isinstance(value, list):
        return any(_baked_damage(item, power) for item in value)
    if not isinstance(value, dict):
        return False
    op = value.get("op", value.get("effect", ""))
    if isinstance(op, str) and op.startswith("damage") and value.get("params", {}).get("power") == power:
        return True
    return any(_baked_damage(item, power) for item in value.values())


def _check_baked_damage(config, changed, path):
    rows = config.get("skills", {})
    if isinstance(rows, list):
        rows = {str(row.get("skill_id")): row for row in rows if isinstance(row, dict)}
    if not isinstance(rows, dict):
        return
    for key, (before, after) in changed.items():
        if key not in rows:
            continue
        row = rows[key]
        if (before.get("power") != after.get("power")
                and (_baked_damage(row, before.get("power")) or "dam_para" in row)):
            raise ValueError("Skill " + key + " has baked reviewed damage power in " + path
                             + "; targeted component review required before activation")
        if before.get("energy") != after.get("energy") and "energy_cost" in row:
            raise ValueError("Skill " + key + " has baked reviewed energy cost in " + path
                             + "; targeted component review required before activation")


def _replace_literals(raw, bindings):
    tree = ast.parse(raw)
    lines = raw.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    fstring_nodes = {id(node) for joined in ast.walk(tree) if isinstance(joined, ast.JoinedStr)
                     for node in ast.walk(joined)}
    changes = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value in bindings and id(node) not in fstring_nodes):
            start = offsets[node.lineno - 1] + node.col_offset
            end = offsets[node.end_lineno - 1] + node.end_col_offset
            changes.append((start, end, repr(bindings[node.value]).encode("utf-8")))
    for start, end, replacement in sorted(changes, reverse=True):
        raw = raw[:start] + replacement + raw[end:]
    ast.parse(raw)
    return raw


def plan_root_rebinding(old_catalog, new_catalog, root=ROOT):
    """Return offline metadata-only replacements after a bounded semantic check.

    The caller preserves old bytes and applies this plan transactionally while
    the application is stopped. Existing reviewed effects and policies never
    acquire changed skill/term semantics through a hash substitution.
    """
    transition = _reviewed_transition(old_catalog, new_catalog, root)
    _check_rebinding_scope(old_catalog, new_catalog, transition.get("records"))
    root = Path(root)
    _folder(root, old_catalog["snapshot_id"])
    _folder(root, new_catalog["snapshot_id"])
    old_path = "data/bwiki/" + old_catalog["snapshot_id"] + "/catalog.json"
    new_path = "data/bwiki/" + new_catalog["snapshot_id"] + "/catalog.json"
    old_raw, new_raw = (root / old_path).read_bytes(), (root / new_path).read_bytes()
    if json.loads(old_raw) != old_catalog or json.loads(new_raw) != new_catalog:
        raise ValueError("Catalog file does not match the requested rule binding")
    bindings = {old_catalog["snapshot_id"]: new_catalog["snapshot_id"], old_path: new_path,
                hashlib.sha256(old_raw).hexdigest(): hashlib.sha256(new_raw).hexdigest(),
                rule_config._hash(old_catalog): rule_config._hash(new_catalog)}
    for key in set(old_catalog) & set(new_catalog):
        bindings[rule_config._hash(old_catalog[key])] = rule_config._hash(new_catalog[key])
    if old_catalog.get("source_version") != new_catalog.get("source_version"):
        bindings[old_catalog["source_version"]] = new_catalog["source_version"]
    provenance = []
    for key, before in old_catalog.get("provenance", {}).items():
        after = new_catalog.get("provenance", {}).get(key)
        if not isinstance(after, dict):
            raise ValueError("Missing BWIKI module provenance: " + key)
        provenance.append((before, after))
        for field in ("content_sha256", "url", "revision_timestamp"):
            if isinstance(before.get(field), str) and isinstance(after.get(field), str):
                bindings[before[field]] = after[field]
    records = {}
    changed_moves = {}
    for category in ("moves", "traits"):
        before = rule_config._index(old_catalog[category])
        for key, record in rule_config._index(new_catalog[category]).items():
            if key in before and before[key] != record:
                records[record["id"]] = (before[key], record)
                records[rule_config._hash(before[key])] = (before[key], record)
                bindings[rule_config._hash(before[key])] = rule_config._hash(record)
                if category == "moves":
                    changed_moves[key] = (before[key], record)
    before_forms = rule_config._index(old_catalog["forms"])
    for key, record in rule_config._index(new_catalog["forms"]).items():
        if key in before_forms:
            bindings[rule_config._hash(before_forms[key])] = rule_config._hash(record)
            if before_forms[key] != record:
                records[record["id"]] = (before_forms[key], record)
    bindings = {before: after for before, after in bindings.items() if before != after}
    originals = {str(path.relative_to(root)).replace("\\", "/"): path.read_bytes()
                 for path in sorted((root / "data/rules").glob("reviewed-*.json"))}
    recipes = transition.get("configs", {})
    for path in recipes:
        target = (root / path).resolve()
        if not target.is_relative_to(root.resolve()):
            raise ValueError("Reviewed BWIKI transition path leaves project")
        originals.setdefault(path, target.read_bytes())
    reviewed_configs = {path: _apply_reviewed_changes(json.loads(originals[path]), recipe, path)
                        for path, recipe in recipes.items()}
    for path, raw in originals.items():
        remaining = {key: pair for key, pair in changed_moves.items()
                     if key not in recipes.get(path, {}).get("reviewed_skill_ids", [])}
        _check_baked_damage(reviewed_configs.get(path, json.loads(raw)), remaining, path)
    replacements = {}
    # Config source references can depend on other reviewed config hashes.
    for _ in range(len(originals) + 1):
        updated = {}
        additions = {}
        for path, raw in originals.items():
            before = json.loads(raw)
            after = _replace_bindings(reviewed_configs.get(path, before), bindings, provenance, records)
            encoded = raw if before == after else (json.dumps(after, ensure_ascii=False, indent=2) + "\n").encode()
            if encoded != raw:
                updated[path] = encoded
                additions[hashlib.sha256(raw).hexdigest()] = hashlib.sha256(encoded).hexdigest()
                additions[rule_config._hash(before)] = rule_config._hash(after)
        if updated == replacements:
            break
        replacements = updated
        bindings.update(additions)
    else:
        raise ValueError("Reviewed config source references contain an unresolved hash cycle")
    for path in sorted((root / "lab").glob("*.py")):
        raw = path.read_bytes()
        encoded = _replace_literals(raw, bindings)
        if encoded != raw:
            replacements[str(path.relative_to(root)).replace("\\", "/")] = encoded
    return replacements


def _folder(root, snapshot):
    if (not isinstance(snapshot, str) or not snapshot or snapshot in (".", "..")
            or any(c in snapshot for c in "\\/:")):
        raise ValueError("Invalid rule snapshot identifier")
    return Path(root) / "data/rules" / snapshot


def _read(folder, filename, schema):
    raw = (folder / (filename + ".json")).read_bytes()
    manifest = json.loads((folder / (filename + ".manifest.json")).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != schema or manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("Published rule checksum mismatch: " + filename)
    return json.loads(raw), manifest["sha256"]


def _terms(catalog, ids):
    return [term for term in catalog.get("glossary", []) if term.get("key") in ids]


def _same_terms(old, new, ids):
    before, after = _terms(old, ids), _terms(new, ids)
    return (before == after and len(before) == len(set(ids))
            and len({term["key"] for term in before}) == len(before))


def _description(record):
    value = record.get("desc")
    return value.get("zh") if isinstance(value, dict) else value


def _phase(catalog, previous, old_catalog, bundle, reviewed=None):
    skills = {}
    old_records = rule_config._index(old_catalog["moves"])
    for key, record in rule_config._index(catalog["moves"]).items():
        desc = _description(record)
        # Retain intrinsic classifications only with the whole source and its notes.
        notes = record.get("desc_notes", [])
        valid_notes = isinstance(notes, list) and all(type(note) in (int, str) for note in notes)
        ids = {1005, *notes} if valid_notes else {1005}
        retained = (valid_notes and (record == old_records.get(key) or key in (reviewed or {}).get("moves", {}))
                    and key in previous["skills"]
                    and _same_terms(old_catalog, catalog, ids))
        if retained:
            swift = deepcopy(previous["skills"][key]["swift_metadata"])
        else:
            swift = {"scope": "source_bound_switch_component", "term_ids": [1005],
                     "status": "unknown", "skill_id": int(key), "swift": None,
                     "metadata_scope": "intrinsic_source_only",
                     "external_swift_modifiers_resolved": False,
                     "training_eligible": False, "real_game_verified": False,
                     "full_switch_executed": False,
                     "reason": "技能或关联术语已更新，固有迅捷需要核对完整来源。"}
            program = bundle["records"]["skills"][key]["program"]
            if valid_notes and program["status"] == "compiled" and _same_terms(old_catalog, catalog, ids):
                swift.update(status="known", swift=bool(program.get("intrinsic_swift")),
                             reason="离线完整描述编译器已识别固有迅捷属性；外部修正仍需单独解析。")
        swift.update(snapshot_id=catalog["snapshot_id"], source_record=deepcopy(record),
                     skill_record_hash=phase_config.fingerprint(record),
                     skills_evidence=deepcopy(catalog.get("provenance", {}).get("Skills")),
                     evidence={**deepcopy(catalog.get("provenance", {}).get("Terms", {})),
                               "terms": deepcopy(_terms(catalog, {1005}))})
        # This is the existing offline declaration classifier, not charge execution.
        skills[key] = {"swift_metadata": swift,
                       "charge": {"declared": isinstance(desc, str) and desc.startswith("蓄力，"),
                                  "skill_record_hash": phase_config.fingerprint(record), "raw_text": desc}}
    return {"schema_version": phase_config.SCHEMA_VERSION, "snapshot_id": catalog["snapshot_id"],
            "source_content_hash": phase_config.fingerprint(phase_config.source_payload(catalog)),
            "skills": skills, "method": "offline_source_bound_update",
            "full_battle_executable": False, "real_game_calibrated": False}


def migrate_rules(old_catalog, new_catalog, root=ROOT):
    """Preserve reviewed components and compile changed descriptions offline.

    Existing snapshots remain immutable. Known complete
    descriptions use the existing compiler. Unknown or changed term semantics
    remain blocked on the affected skill or trait.
    """
    transition = _reviewed_transition(old_catalog, new_catalog, root)
    old_folder = _folder(root, old_catalog["snapshot_id"])
    folder = _folder(root, new_catalog["snapshot_id"])
    previous, previous_hash = _read(old_folder, "rule-config-1", rule_config.SCHEMA_VERSION)
    errors = rule_config.validate_config(previous, old_catalog)
    if errors:
        raise ValueError("Previous rule source failed validation: " + "; ".join(errors[:5]))
    phase, phase_hash = _read(old_folder, "phase-config-1", phase_config.SCHEMA_VERSION)
    if (phase.get("snapshot_id") != old_catalog["snapshot_id"]
            or phase.get("source_content_hash") != phase_config.fingerprint(phase_config.source_payload(old_catalog))):
        raise ValueError("Previous phase source failed validation")
    if old_catalog == new_catalog:
        return {"snapshot_id": new_catalog["snapshot_id"], "rules_ready": True}
    if folder == old_folder:
        raise ValueError("Changed catalog requires a new immutable snapshot ID")

    artifact = compile_catalog(new_catalog)
    bundle = rule_config.build_config(new_catalog, artifact)
    for category, catalog_key in (("skills", "moves"), ("traits", "traits")):
        before = rule_config._index(old_catalog[catalog_key])
        after = rule_config._index(new_catalog[catalog_key])
        for key, rule in bundle["records"][category].items():
            old_rule = previous["records"][category].get(key)
            if old_rule and before.get(key) == after[key]:
                ids = old_rule["program"]["dependency_ids"]
                if _same_terms(old_catalog, new_catalog, ids):
                    rebound = deepcopy(old_rule)
                    p = rebound["program"]
                    p.update(snapshot_id=new_catalog["snapshot_id"], source_version=new_catalog.get("source_version"),
                             skill_source=deepcopy(new_catalog.get("provenance", {}).get("Skills")))
                    if category == "skills":
                        p["term_source"] = deepcopy(new_catalog.get("provenance", {}).get("Terms"))
                    for component in rebound["components"]:
                        component["evidence"] = rule_config._evidence(p, category)
                    bundle["records"][category][key] = rebound
                    continue
            ids = rule["program"]["dependency_ids"]
            if not _same_terms(old_catalog, new_catalog, ids):
                p = rule["program"]
                p.update(status="unsupported", blockers=[*p["blockers"], "updated_term_semantics_require_review"])
                rule["components"] = []
                rule["capabilities"] = rule_config._capabilities(p, [])
    for category, records in bundle["records"].items():
        bundle["artifact_header"]["counts"][category] = {
            "total": len(records), "compiled": sum(r["program"]["status"] == "compiled" for r in records.values()),
            "unsupported": sum(r["program"]["status"] == "unsupported" for r in records.values()),
            "executable": 0, "real_game_verified": 0}
    errors = rule_config.validate_config(bundle, new_catalog)
    if errors:
        raise ValueError("Updated rule validation failed: " + "; ".join(errors[:5]))
    phase = _phase(new_catalog, phase, old_catalog, bundle, transition.get("records"))
    files = {}
    for name, config, schema in (("rule-config-1", bundle, rule_config.SCHEMA_VERSION),
                                 ("phase-config-1", phase, phase_config.SCHEMA_VERSION)):
        raw = (json.dumps(config, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        manifest = {"schema_version": schema, "snapshot_id": new_catalog["snapshot_id"],
                    "sha256": hashlib.sha256(raw).hexdigest(), "method": "offline_source_bound_update",
                    "previous_snapshot_id": old_catalog["snapshot_id"], "previous_rule_sha256": previous_hash,
                    "previous_phase_sha256": phase_hash, "real_game_calibrated": False}
        files[name + ".json"] = raw
        files[name + ".manifest.json"] = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    # Check every collision before writing so a retry cannot overwrite history.
    for name, raw in files.items():
        target = folder / name
        if target.exists() and target.read_bytes() != raw:
            raise ValueError("Immutable rule configuration already differs: " + str(target))
    folder.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        target = folder / name
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(raw)
    return {"snapshot_id": new_catalog["snapshot_id"], "rules_ready": True,
            "skills": len(bundle["records"]["skills"])}
