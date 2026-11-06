"""Decode literal BWIKI season shards and mirror their source-defined merge order.

Lua source must first pass ``parse_lua_data``; this module never executes Lua.
"""
from __future__ import annotations

from copy import deepcopy

from lab.bwiki import WikiDataError


SHARDS = ("Roster", "Arts", "Gifts", "Aux", "Links")


def _array(value, label):
    # The literal parser represents Lua's empty table as an empty dictionary.
    if value == {}:
        return []
    if not isinstance(value, list):
        raise WikiDataError(f"{label} must be an array")
    return value


def _module_name(value):
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(char in value for char in "\\:|#?")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise WikiDataError(f"Invalid season module name: {value!r}")


def _validate_season(season):
    if not isinstance(season, dict):
        raise WikiDataError("Season must be an object")
    _module_name(season.get("namespace"))
    if not isinstance(season.get("codec"), str) or not season["codec"]:
        raise WikiDataError("Season codec must be a nonempty string")
    tags = [season.get("object_tag", 1), season.get("array_tag", 2)]
    if any(type(tag) is not int for tag in tags) or tags[0] == tags[1]:
        raise WikiDataError("Season tags must be distinct integers")
    modules = season.get("modules", {})
    if not isinstance(modules, dict):
        raise WikiDataError("Season modules must be an object")
    for name, target in modules.items():
        _module_name(name)
        _module_name(target)


def validate_manifest(manifest):
    """Validate module paths before fetching; return seasons in source order."""
    if not isinstance(manifest, dict):
        raise WikiDataError("Season manifest must be an object")
    seasons = _array(manifest.get("seasons"), "Manifest seasons")
    namespaces = set()
    for season in seasons:
        _validate_season(season)
        namespace = season["namespace"]
        if namespace in namespaces:
            raise WikiDataError(f"Duplicate season namespace: {namespace}")
        namespaces.add(namespace)
    return seasons


def decode_shard(packed, season):
    """Decode ``{codec, fields, value}`` using a validated season descriptor."""
    _validate_season(season)
    packed = _array(packed, "Packed shard")
    if len(packed) != 3 or packed[0] != season["codec"]:
        raise WikiDataError("Invalid packed shard header or codec")
    fields = _array(packed[1], "Shard fields")
    if any(type(key) not in (str, int) for key in fields):
        raise WikiDataError("Shard fields must contain string or integer keys")
    object_tag, array_tag = season.get("object_tag", 1), season.get("array_tag", 2)

    def decode(value):
        if type(value) in (str, int, float, bool, type(None)):
            return value
        tagged = _array(value, "Packed value")
        if len(tagged) != 2 or type(tagged[0]) is not int:
            raise WikiDataError("Invalid packed value tag")
        tag, items = tagged
        items = _array(items, "Packed entries")
        if tag == array_tag:
            return [decode(item) for item in items]
        if tag != object_tag:
            raise WikiDataError(f"Unknown packed value tag: {tag}")
        result = {}
        for entry in items:
            entry = _array(entry, "Object entry")
            if len(entry) != 2 or type(entry[0]) is not int or not 1 <= entry[0] <= len(fields):
                raise WikiDataError("Invalid packed field index")
            key = fields[entry[0] - 1]
            if key in result:
                raise WikiDataError(f"Duplicate decoded object key: {key!r}")
            result[key] = decode(entry[1])
        return result

    return decode(packed[2])


def merge_seasons(base_modules, manifest, shards):
    """Return merged modules; ``shards`` keys are ``(namespace, logical_name)``.

    Hidden-season selection and revision/source verification belong to the caller.
    Targets/Links route conflicts fail as they do in BWIKI's season adapter.
    """
    result = deepcopy(base_modules)
    result["Targets"], result["Links"] = {}, {}

    def table_items(value):
        if isinstance(value, dict):
            return value.items()
        if isinstance(value, list):
            return enumerate(value, 1)
        raise WikiDataError("Expected a Lua table for nested merge")

    def extend(name, data):
        if not isinstance(data, dict):
            raise WikiDataError(f"Season module {name} must be an object")
        target = result.setdefault(name, {})
        if not isinstance(target, dict):
            raise WikiDataError(f"Base module {name} must be an object")
        for key, value in data.items():
            if name in ("History", "Config") and isinstance(value, (dict, list)):
                existing = target.get(key, {})
                merged = dict(table_items(existing))
                merged.update(table_items(value))
                if isinstance(value, list) and set(merged) == set(range(1, len(merged) + 1)):
                    target[key] = [merged[index] for index in range(1, len(merged) + 1)]
                else:
                    target[key] = merged
            else:
                target[key] = value

    for season in validate_manifest(manifest):
        decoded = {}
        for name in SHARDS:
            key = (season["namespace"], name)
            if key not in shards:
                raise WikiDataError(f"Missing season shard: {key}")
            decoded[name] = decode_shard(shards[key], season)
        extend("Catalog", decoded["Roster"])
        extend("Skills", decoded["Arts"])
        extend("Skills", decoded["Gifts"])
        if not isinstance(decoded["Aux"], dict):
            raise WikiDataError("Season Aux must be an object")
        for name, data in decoded["Aux"].items():
            if not isinstance(name, str):
                raise WikiDataError("Season Aux module name must be a string")
            extend(name, data)
        season_codes = decoded["Aux"].get("CatalogSeasons", {})
        if not isinstance(season_codes, dict) or len(season_codes) != 1:
            raise WikiDataError("Season Aux must identify exactly one CatalogSeasons key")
        season_code = next(iter(season_codes))
        extend("SkillSeasons", {key: season_code for name in ("Arts", "Gifts") for key in decoded[name]})
        routing = decoded["Links"]
        if not isinstance(routing, dict):
            raise WikiDataError("Season Links must be an object")
        for name in ("Targets", "Links"):
            routes = routing.get(name)
            if not isinstance(routes, dict):
                raise WikiDataError(f"Season Links.{name} must be an object")
            for kind, mapping in routes.items():
                if not isinstance(kind, str) or not isinstance(mapping, dict):
                    raise WikiDataError(f"Invalid season routes in {name}")
                target = result[name].setdefault(kind, {})
                for key, title in mapping.items():
                    if key in target and target[key] != title:
                        raise WikiDataError(f"Conflicting season route identity: {key!r}")
                    target[key] = title
    return result
