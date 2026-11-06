"""Versioned data configurations and static validation; never parses prose at runtime.

The v1 migration lifts previously reviewed programs into ordered effect components.
It does not infer semantics for blocked descriptions. Source fingerprints, the
published manifest and component evidence are checked before the compatibility
adapter can supply a program to the existing interpreters.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = "roco-rule-config-1"
ROOT = Path(__file__).resolve().parents[1]
EFFECTS = frozenset({"damage", "damage.sequence", "damage.conditional", "energy.restore",
                     "energy.reduce", "hp.restore", "stat.modify", "status.add", "defense.plan"})
STATS = frozenset({"patk", "matk", "pdef", "mdef", "spd"})
PROGRAM_REQUIRED = frozenset({"game_id", "name", "category", "compiler_version", "source_description",
    "source_details", "source_hash", "source", "static_fields", "status", "blockers", "dependency_ids",
    "snapshot_id", "source_version", "order_semantics", "executable", "real_game_verified",
    "execution_blockers", "skill_source"})
PROGRAM_OPTIONAL = frozenset({"term_source", "intrinsic_swift", "entry_trigger", "swift_term"})
CONSTRAINT_KEYS = ("priority", "response_success", "turn_order_condition", "entry_trigger",
                   "duration", "cooldown", "execution_limits")


class ConfigError(ValueError):
    pass


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _source_payload(catalog):
    # Forms/charts are separately validated by BwikiRuleset; they do not rewrite
    # skill semantics. All rule-bearing text, notes, terms and revisions bind here.
    return {k: catalog.get(k) for k in ("snapshot_id", "source_version", "moves", "traits", "glossary", "provenance")}


def _index(records):
    values = records.values() if isinstance(records, dict) else records
    result = {}
    for record in values:
        key = record.get("game_id", record.get("id"))
        if type(key) is not int or key <= 0 or str(key) in result:
            raise ConfigError("Source contains invalid or duplicate game IDs")
        result[str(key)] = record
    return result


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ConfigError(label + ": unexpected or missing fields")


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ConfigError(label + ": invalid integer")


def _parameter_integer(value, label, minimum=0):
    if isinstance(value, dict) and set(value) == {"expr"}:
        from lab.rule_expressions import validate_expression
        validate_expression(value["expr"])
    else:
        _integer(value, label, minimum)


def _ratio(value, label, positive=False):
    _keys(value, {"numerator", "denominator"}, label)
    if not positive and isinstance(value['numerator'], dict) and set(value['numerator']) == {'expr'}:
        from lab.rule_expressions import validate_expression
        validate_expression(value['numerator']['expr'])
        _integer(value['denominator'], label + '.denominator', 1)
        return
    if type(value["numerator"]) is not int or (positive and value["numerator"] <= 0):
        raise ConfigError(label + ": invalid numerator")
    _integer(value["denominator"], label + ".denominator", 1)


def validate_effect(effect, target, params):
    """Raise a concrete error for an invalid declarative primitive schema.

    Recognition is independent of execution availability: defense plans and
    freeze/leech can be structurally valid but remain execution-blocked.
    """
    if effect not in EFFECTS:
        raise ConfigError("unknown effect: " + str(effect))
    if target not in ("self", "opponent"):
        raise ConfigError("unknown target selector: " + str(target))
    if effect.startswith("damage"):
        expected = {"kind", "power", "type"}
        if effect == "damage.sequence": expected.add("hits")
        if effect == "damage.conditional": expected.update(("condition", "modifier"))
        _keys(params, expected, effect)
        if params["kind"] not in ("physical", "magical") or not isinstance(params["type"], str) or not params["type"]:
            raise ConfigError("invalid damage kind/type")
        _parameter_integer(params["power"], "power", 1)
        if effect == "damage.sequence": _parameter_integer(params["hits"], "hits", 1)
        if effect == "damage.conditional":
            c, m = params["condition"], params["modifier"]
            _keys(c, {"target", "attribute", "comparison", "value", "source_timing"}, "condition")
            if (c["target"] not in ("self", "opponent") or c["attribute"] != "energy"
                    or c["comparison"] not in ("eq", "lte") or c["source_timing"] not in ("after_use", "unspecified")):
                raise ConfigError("unsupported conditional predicate")
            _integer(c["value"], "condition value")
            _keys(m, {"kind", "amount"}, "modifier")
            if m["kind"] not in ("power_add", "damage_multiply"):
                raise ConfigError("unsupported damage modifier")
            _integer(m["amount"], "modifier amount", 1)
    elif effect in ("energy.restore", "energy.reduce"):
        _keys(params, {"amount"}, effect)
        _parameter_integer(params["amount"], effect + ".amount", 1)
    elif effect == "hp.restore":
        _keys(params, {"percent"}, effect)
        _ratio(params["percent"], "HP percent", positive=True)
    elif effect == "stat.modify":
        _keys(params, {"attributes", "percent"}, effect)
        attrs = params["attributes"]
        if (not isinstance(attrs, list) or not attrs or any(not isinstance(x, str) or x not in STATS for x in attrs)
                or len(set(attrs)) != len(attrs)):
            raise ConfigError("unknown or duplicated stat attributes")
        _ratio(params["percent"], "stat percent")
    elif effect == "status.add":
        _keys(params, {"status", "stacks"}, effect)
        if params["status"] not in ("poison", "burn", "freeze", "leech"):
            raise ConfigError("unknown status")
        _integer(params["stacks"], "status stacks", 1)
    elif effect == "defense.plan":
        _keys(params, {"reduction", "response"}, effect)
        _ratio(params["reduction"], "defense reduction", positive=True)
        if params["reduction"]["numerator"] > params["reduction"]["denominator"] or params["response"] != "attack":
            raise ConfigError("invalid defense/response plan")


def _supported(component):
    return (component["effect"] != "defense.plan" and not
            (component["effect"] == "status.add" and component["params"]["status"] in ("freeze", "leech")))


def _capabilities(program, components):
    structured = program["status"] == "compiled"
    return {"description_structured": structured,
            "isolated_components_supported": structured and bool(components) and all(_supported(c) for c in components),
            "full_battle_executable": False, "real_game_calibrated": False}


def _constraints(program):
    result = {k: {"status": "not_migrated"} for k in CONSTRAINT_KEYS}
    if program.get("entry_trigger"):
        result["entry_trigger"] = {"status": "source_declared", "value": deepcopy(program["entry_trigger"])}
    return result


def _evidence(program, category):
    return {"snapshot_id": program["snapshot_id"], "source_hash": program["source_hash"],
            "raw_text": program["source_description"], "module": "Skills" if category == "skills" else "Traits",
            "source_url": program["source"].get("source_url"),
            "basis": "reviewed_v6_program_migration"}


def build_config(catalog, legacy_artifact):
    """Offline, lossless migration of an already-reviewed artifact, not NLP."""
    header = {k: deepcopy(v) for k, v in legacy_artifact.items() if k not in ("skills", "traits", "snapshot_sha256")}
    result = {"schema_version": SCHEMA_VERSION, "snapshot_id": catalog["snapshot_id"],
              "catalog_content_hash": _hash(catalog), "source_content_hash": _hash(_source_payload(catalog)),
              "artifact_header": header, "records": {"skills": {}, "traits": {}},
              "migration": {"source_compiler": legacy_artifact["compiler_version"],
                            "source_artifact_hash": _hash(legacy_artifact), "method": "lossless_components_no_nlp"}}
    for category in ("skills", "traits"):
        for key, program in legacy_artifact[category].items():
            components = []
            for i, operation in enumerate(program["operations"]):
                params = deepcopy(operation["params"])
                target = params.pop("target")
                components.append({"id": "effect:" + str(i), "kind": "effect", "effect": operation["op"],
                    "target": target, "params": params, "evidence": _evidence(program, category),
                    "uncertainties": deepcopy(program["execution_blockers"])})
            result["records"][category][key] = {
                "rule_id": ("skill:" if category == "skills" else "trait:") + key,
                "program": {k: deepcopy(v) for k, v in program.items() if k != "operations"},
                "components": components,
                "trigger": {"event": "skill.use" if category == "skills" else "unknown",
                            "order": "source_text_order_experiment" if category == "skills" else "unknown"},
                "constraints": _constraints(program), "capabilities": _capabilities(program, components)}
    errors = validate_config(result, catalog)
    if errors:
        raise ConfigError("Cannot publish invalid migration: " + "; ".join(errors[:10]))
    return result


def rule_to_program(rule):
    """Compatibility view derives ALL operations from ordered components."""
    def has_expression(value):
        if isinstance(value, dict):
            return "expr" in value or any(has_expression(x) for x in value.values())
        return isinstance(value, list) and any(has_expression(x) for x in value)
    if any("when" in c or has_expression(c["params"]) for c in rule["components"]):
        raise ConfigError("Conditional/expression components require the compositional executor; compatibility adapter cannot discard them")
    out = deepcopy(rule["program"])
    out["operations"] = [{"op": c["effect"], "params": {"target": c["target"], **deepcopy(c["params"])}}
                         for c in rule["components"]]
    return out


def _validate_rule(rule):
    _keys(rule, {"rule_id", "program", "components", "trigger", "constraints", "capabilities"}, "rule")
    p = rule["program"]
    if not isinstance(p, dict) or not PROGRAM_REQUIRED <= set(p) or set(p) - PROGRAM_REQUIRED - PROGRAM_OPTIONAL:
        raise ConfigError("program header: missing/unknown fields or inline operations")
    if p["status"] not in ("compiled", "unsupported") or p["category"] not in ("skill", "trait"):
        raise ConfigError("invalid program status/category")
    for flag in ("executable", "real_game_verified"):
        if p[flag] is not False: raise ConfigError("unverified program cannot claim " + flag)
    for key in ("blockers", "execution_blockers", "dependency_ids"):
        if not isinstance(p[key], list): raise ConfigError("invalid " + key)
    if any(type(x) is not int or x <= 0 for x in p["dependency_ids"]):
        raise ConfigError("invalid term dependencies")
    components = rule["components"]
    if not isinstance(components, list): raise ConfigError("components must be ordered list")
    if p["status"] == "unsupported" and components: raise ConfigError("blocked rule cannot contain executable partial effects")
    if p["status"] == "compiled" and (not components or p["blockers"]): raise ConfigError("structured rule has no complete components or has blockers")
    for i, component in enumerate(components):
        expected_keys = {"id", "kind", "effect", "target", "params", "evidence", "uncertainties"}
        if "when" in component: expected_keys.add("when")
        _keys(component, expected_keys, "component")
        if component["id"] != "effect:" + str(i) or component["kind"] != "effect":
            raise ConfigError("component identity/order invalid")
        validate_effect(component["effect"], component["target"], component["params"])
        if "when" in component:
            from lab.rule_expressions import validate_condition
            validate_condition(component["when"])
        expected = _evidence(p, "skills" if p["category"] == "skill" else "traits")
        if component["evidence"] != expected: raise ConfigError("component source evidence conflict")
        if component["uncertainties"] != p["execution_blockers"]:
            raise ConfigError("component uncertainty cannot drop source-program blockers")
    if rule["capabilities"] != _capabilities(p, components): raise ConfigError("capability flags conflict with supported components")
    if rule["constraints"] != _constraints(p): raise ConfigError("unknown duration/cooldown/order constraints cannot be promoted to game facts")
    expected_trigger = {"event": "skill.use", "order": "source_text_order_experiment"} if p["category"] == "skill" else {"event": "unknown", "order": "unknown"}
    if rule["trigger"] != expected_trigger: raise ConfigError("trigger is not supported by this migrated schema")


def validate_rule(rule):
    """Return concrete static errors; bundle loading additionally binds the source."""
    try:
        _hash(rule)
        _validate_rule(rule)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return [str(exc)]
    return []


def validate_config(bundle, catalog):
    """Return path-specific static errors for all records, never drop a bad record."""
    errors = []
    try:
        _hash(bundle)
        _keys(bundle, {"schema_version", "snapshot_id", "catalog_content_hash", "source_content_hash", "artifact_header", "records", "migration"}, "bundle")
        if bundle["schema_version"] != SCHEMA_VERSION: raise ConfigError("unknown config schema")
        _keys(bundle["migration"], {"source_compiler", "source_artifact_hash", "method"}, "migration")
        if bundle["migration"]["method"] != "lossless_components_no_nlp":
            raise ConfigError("unknown migration method")
        if bundle["snapshot_id"] != catalog["snapshot_id"]: raise ConfigError("snapshot mismatch")
        if bundle["source_content_hash"] != _hash(_source_payload(catalog)):
            raise ConfigError("source fingerprint changed; explicit config review/republication required")
        if not isinstance(bundle["catalog_content_hash"], str) or len(bundle["catalog_content_hash"]) != 64:
            raise ConfigError("missing original catalog content hash")
        _keys(bundle["records"], {"skills", "traits"}, "records")
        source_indices = {"skills": _index(catalog["moves"]), "traits": _index(catalog["traits"])}
        for category, source_index in source_indices.items():
            rules = bundle["records"][category]
            if not isinstance(rules, dict) or set(rules) != set(source_index):
                errors.append(category + ": missing, extra or invalid IDs")
                if not isinstance(rules, dict): continue
            for key, rule in rules.items():
                path = category + "." + str(key)
                try:
                    rule_errors = validate_rule(rule)
                    if rule_errors: raise ConfigError("; ".join(rule_errors))
                    p = rule["program"]
                    record = source_index.get(key)
                    if record is None: raise ConfigError("source ID absent")
                    expected_category = "skill" if category == "skills" else "trait"
                    if p["game_id"] != int(key) or type(p["game_id"]) is not int or p["category"] != expected_category or rule["rule_id"] != expected_category + ":" + key:
                        raise ConfigError("game ID/category mismatch")
                    if p["source_hash"] != _hash(record): raise ConfigError("record source hash mismatch")
                    if p["snapshot_id"] != catalog["snapshot_id"] or p["source_version"] != catalog.get("source_version"):
                        raise ConfigError("record snapshot/version mismatch")
                    desc = record.get("desc")
                    if p["source_description"] != (desc.get("zh") if isinstance(desc, dict) else desc):
                        raise ConfigError("raw source description mismatch")
                    name = record.get("name")
                    if p["name"] != (name.get("zh") if isinstance(name, dict) else name):
                        raise ConfigError("source name mismatch")
                    if p["source"] != {k: record[k] for k in ("wiki_id", "source_url", "source_module") if k in record}:
                        raise ConfigError("record source reference mismatch")
                    if p["source_details"] != {k: record[k] for k in ("effect_details", "desc_notes") if k in record}:
                        raise ConfigError("record source notes mismatch")
                    if p["skill_source"] != catalog.get("provenance", {}).get("Skills"):
                        raise ConfigError("record module provenance mismatch")
                    if category == "skills" and p.get("term_source") != catalog.get("provenance", {}).get("Terms"):
                        raise ConfigError("term module provenance mismatch")
                    if p["static_fields"] != {k: record[k] for k in ("kind", "type", "power", "energy") if k in record}:
                        raise ConfigError("source static fields mismatch")
                    for c in rule["components"]:
                        if c["effect"].startswith("damage") and c["params"]["type"] not in catalog["types"]:
                            raise ConfigError("unknown source damage type")
                except (ValueError, TypeError, KeyError, AttributeError) as exc:
                    errors.append(path + ": " + str(exc))
        header = bundle["artifact_header"]
        _keys(header, {"compiler_version", "counts", "executable", "real_game_verified", "snapshot_id",
                      "source_hash", "source_provenance", "source_version", "training_allowed"}, "artifact_header")
        for flag in ("training_allowed", "executable", "real_game_verified"):
            if header.get(flag) is not False: errors.append("artifact_header: unverified " + flag)
        if header.get("snapshot_id") != catalog["snapshot_id"]:
            errors.append("artifact_header: snapshot mismatch")
        if header.get("source_provenance") != catalog.get("provenance", {}) or header.get("source_version") != catalog.get("source_version"):
            errors.append("artifact_header: source provenance/version mismatch")
        for category in ("skills", "traits"):
            rules = bundle["records"][category]
            expected_counts = {"total": len(rules), "compiled": sum(r["program"]["status"] == "compiled" for r in rules.values()),
                "unsupported": sum(r["program"]["status"] == "unsupported" for r in rules.values()), "executable": 0, "real_game_verified": 0}
            if header.get("counts", {}).get(category) != expected_counts:
                errors.append("artifact_header.counts." + category + ": counts disagree with actual records")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        errors.append("bundle: " + str(exc))
    return errors


def load_bundle(catalog):
    snapshot = catalog.get("snapshot_id")
    # An external snapshot identifier cannot turn into a filesystem path.
    if not isinstance(snapshot, str) or not snapshot or snapshot in (".", "..") or Path(snapshot).name != snapshot or any(c in snapshot for c in "\\/:"):
        raise ConfigError("Invalid snapshot path identifier")
    folder = ROOT / "data" / "rules" / snapshot
    path, manifest_path = folder / "rule-config-1.json", folder / "rule-config-1.manifest.json"
    try:
        raw = path.read_bytes()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError("Reviewed rule config unavailable; run offline migration/review, not runtime parsing") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ConfigError("Published rule config checksum mismatch")
    bundle = json.loads(raw)
    errors = validate_config(bundle, catalog)
    if errors: raise ConfigError("Rule config blocked: " + "; ".join(errors[:12]))
    return bundle


def load_config(catalog):
    bundle = load_bundle(catalog)
    out = deepcopy(bundle["artifact_header"])
    out.update({category: {key: execution_program(rule) for key, rule in bundle["records"][category].items()}
                for category in ("skills", "traits")})
    return out


def requires_native_execution(rule):
    def dynamic(value):
        if isinstance(value, dict):
            return set(value) == {'expr'} or any(dynamic(v) for v in value.values())
        return isinstance(value, list) and any(dynamic(v) for v in value)
    return any('when' in c or dynamic(c['params']) for c in rule['components'])


def execution_program(rule):
    """Keep dynamic components intact for native dispatch, never flatten them.

    Static records preserve the old API bit for bit. A dynamic record carries
    an explicit native rule, not an executable empty legacy operation list.
    """
    errors = validate_rule(rule)
    if errors:
        raise ConfigError("; ".join(errors))
    if requires_native_execution(rule):
        return {**deepcopy(rule["program"]), "operations": [], "native_rule": deepcopy(rule)}
    return rule_to_program(rule)
