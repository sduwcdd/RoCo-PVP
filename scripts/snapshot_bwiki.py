"""Snapshot BWIKI's public, revisioned data modules; never execute Lua.

Usage: python scripts/snapshot_bwiki.py [--resume SNAPSHOT_ID]
Run with the source APP stopped. A successful update activates immediately.
The normalized catalog is a database snapshot, not a validated battle engine.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.bwiki import WikiDataError, parse_lua_data
from lab.bwiki_update_lock import maintenance

BASE = "https://wiki.biligame.com/nrc/"
MODULES = ("Index", "Catalog", "Skills", "Learnsets", "Terms", "Types", "Config", "Natures")
SEASON_TITLES = {
    "SeasonConfig": "Module:Pets/SeasonConfig",
    "VisibilityConfig": "Module:ContentVisibility/Config",
    "SeasonData": "Module:Pets/SeasonData",
    "VisibilityAdapter": "Module:ContentVisibility",
    "SeasonAdapter": "Module:精灵图鉴/S5",
    "SeasonManifest": "Module:精灵图鉴/S5/配置",
}
ADAPTER_HASHES = {
    "SeasonData": "48c0461b8e90551e41c2ff580e9646a0532f8672affa1b201befa3c4d2ecace3",
    "VisibilityAdapter": "d6c736555dea8dc5c3938a108d6ebbeb6f3b878fed68b3f7da0423da0e7658e2",
    "SeasonAdapter": "8d58673f8b3b8df2f677c975cc87a3855ab1553ced9b3649b1b405425cc06114",
}
TZ = timezone(timedelta(hours=8))


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def title_of(short):
    return "Module:Natures/data" if short == "Natures" else "Module:Pets/data/" + short


def pages_of(response):
    pages = response["query"]["pages"]
    return list(pages.values()) if isinstance(pages, dict) else pages


def revision_content(revision):
    main = revision["slots"]["main"]
    return main["content"] if "content" in main else main["*"]


def page_for_revision(response, revision_id):
    pages = [page for page in pages_of(response)
             if page.get("revisions", [{}])[0].get("revid") == revision_id]
    if len(pages) != 1:
        raise WikiDataError("Source response cannot uniquely match revision " + str(revision_id))
    return pages[0]


def read_url(url):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (RocoResearchSnapshot)", "Accept-Encoding": "identity"})
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise WikiDataError("Source response exceeds size limit")
            return raw
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def revision_heads(titles=None):
    """Small revision queries first. Full content is downloaded only on change."""
    titles = titles or {short: title_of(short) for short in MODULES}
    params = {"action": "query", "prop": "revisions",
              "titles": "|".join(titles.values()),
              "rvprop": "ids|timestamp", "format": "json"}
    result = json.loads(read_url(BASE + "api.php?" + urllib.parse.urlencode(params, safe=":/")))
    if result.get("error"):
        raise WikiDataError(str(result["error"]))
    pages = {page["title"]: page for page in pages_of(result)}
    normalized = {item["from"]: item["to"] for item in result["query"].get("normalized", [])}
    heads = {}
    for short, title in titles.items():
        page = pages[normalized.get(title, title)]
        revision = page["revisions"][0]
        heads[short] = {"revision_id": revision["revid"], "revision_timestamp": revision["timestamp"]}
    return heads


def reuse_module(previous, out, short, head, manifest):
    """Reuse only locally verified bytes of the exact remote revision."""
    if previous is None:
        return False
    record = previous["manifest"].get("pages", {}).get(short)
    if not record or record.get("revision_id") != head["revision_id"]:
        return False
    raw_path = previous["folder"] / "raw" / (short + ".gz")
    if not raw_path.is_file() or not record.get("sha256"):
        return False
    raw = gzip.decompress(raw_path.read_bytes())
    if sha(raw) != record["sha256"]:
        raise WikiDataError("Retained source hash mismatch: " + short)
    response = json.loads(raw)
    revision = page_for_revision(response, head["revision_id"])["revisions"][0]
    source = revision_content(revision)
    if revision["revid"] != head["revision_id"] or sha(source.encode("utf8")) != record["content_sha256"]:
        raise WikiDataError("Retained revision content mismatch: " + short)
    shutil.copyfile(raw_path, out / "raw" / (short + ".gz"))
    manifest["pages"][short] = {**record, "checked_at": now(), "reused": True}
    return True


def recover_update(root):
    """Finish a committed update, or restore every file after interruption."""
    root = Path(root).resolve()
    journal = root / "data/.bwiki-update.json"
    if not journal.exists():
        return
    transaction = json.loads(journal.read_text(encoding="utf8"))
    files = {}
    for relative, entry in transaction["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not (relative.startswith(("lab/", "data/rules/", "data/bwiki/"))
                or relative == "artifacts/weather_rules_20261025/weather_rules.json"):
            raise ValueError("Invalid interrupted-update path")
        files[path] = (base64.b64decode(entry["before"], validate=True), entry["after_sha256"])
    committed = all(path.is_file() and sha(path.read_bytes()) == expected
                    for path, (_, expected) in files.items())
    if not committed:
        for path, (raw, _) in files.items():
            temp = path.with_suffix(path.suffix + ".bwiki-rollback")
            temp.write_bytes(raw)
            temp.replace(path)
    journal.unlink()


def verify_activation(root, catalog):
    """Fresh-process static loading checks before committing the active pointer."""
    digest = sha((Path(root) / "data/bwiki" / catalog["snapshot_id"] / "catalog.json").read_bytes())
    code = """
import json, sys
from lab import catalog_store
# The parent exclusively owns maintenance. Only this isolated check reads the
# not-yet-active snapshot, with ordinary checksum/schema/source validation.
catalog_store._PINNED = (sys.argv[1], sys.argv[2])
catalog = catalog_store.runtime_catalog()[0]
from lab.prepared_rules import PreparedRules
from lab.runtime_programs import reviewed_programs
from lab.phase_config import load_phase_config
from lab.live_damage import _rules
prepared = PreparedRules(catalog)
prepared._components()
prepared._rules.programs()
load_phase_config(catalog)
reviewed_programs(prepared)
assert _rules()[0]['snapshot_id'] == catalog['snapshot_id']
print(json.dumps({'snapshot_id': catalog['snapshot_id'], 'static_loading': 'ok'}))
"""
    result = subprocess.run([sys.executable, "-c", code, catalog["snapshot_id"], digest],
                            cwd=root, capture_output=True, timeout=120)
    if result.returncode:
        detail = (result.stderr or result.stdout).decode("utf8", errors="replace")[-2400:]
        raise ValueError("更新规则加载失败，当前版本已保留。需要继续适配的具体原因\n" + detail)


def activate(base, out, catalog, previous, *, root=ROOT):
    """Prepare rules, then commit the complete source update and active pointer."""
    from scripts.update_bwiki_rules import migrate_rules, plan_root_rebinding
    if previous is None:
        raise WikiDataError("首次导入缺少现有已核查规则，请在本项目已有快照基础上更新。")
    changes = plan_root_rebinding(previous["catalog"], catalog, root=root)
    migrate_rules(previous["catalog"], catalog, root=root)
    # Retain original evidence JSON. Python source is never put in release data.
    retained = out / "previous-reviewed"
    retained.mkdir(exist_ok=True)
    originals = {}
    for relative in changes:
        path = (Path(root) / relative).resolve()
        if not path.is_relative_to(Path(root).resolve()) or not path.is_file():
            raise ValueError("Update target leaves the source project")
        originals[path] = path.read_bytes()
        if relative.startswith("data/rules/") or relative == "artifacts/weather_rules_20261025/weather_rules.json":
            target = retained / path.name
            if target.exists() and target.read_bytes() != originals[path]:
                raise ValueError("Retained rule evidence already differs")
            target.write_bytes(originals[path])
    pointer = {"snapshot_id": catalog["snapshot_id"], "catalog_sha256": sha((out / "catalog.json").read_bytes())}
    pointer_raw = json.dumps(pointer, ensure_ascii=False, indent=2).encode("utf8")
    changes = {**changes, "data/bwiki/latest.json": pointer_raw}
    pointer_path = Path(root) / "data/bwiki/latest.json"
    originals[pointer_path] = pointer_path.read_bytes()
    journal = Path(root) / "data/.bwiki-update.json"
    save(journal, {"files": {relative: {
        "before": base64.b64encode(originals[(Path(root) / relative).resolve()]).decode("ascii"),
        "after_sha256": sha(raw)} for relative, raw in changes.items()}})
    try:
        for relative, raw in changes.items():
            if relative == "data/bwiki/latest.json":
                verify_activation(root, catalog)
            path = Path(root) / relative
            temp = path.with_suffix(path.suffix + ".bwiki-tmp")
            temp.write_bytes(raw)
            temp.replace(path)
        journal.unlink()
    except BaseException:
        recover_update(root)
        raise
    return pointer


def normalize(modules, snapshot_id, provenance, portraits=None):
    pets, skills, pools = modules["Catalog"], modules["Skills"], modules["Learnsets"]
    moves, traits, details, forms = {}, {}, {}, []
    errors = []
    stat_map = {"hp": "hp", "patk": "atk", "matk": "spa", "pdef": "def", "mdef": "spd", "spd": "spe"}
    kinds = {"物攻": "physical", "魔攻": "magical", "状态": "status", "防御": "defense", "特性": "trait"}
    skill_ids = {sid: record["game_id"] for sid, record in skills.items()}
    if len(set(skill_ids.values())) != len(skill_ids):
        errors.append("Duplicate game skill IDs")
    if len({pet["game_id"] for pet in pets.values()}) != len(pets):
        errors.append("Duplicate game pet IDs")
    for sid, source in skills.items():
        kind = kinds.get(source.get("damage_class", source["category"]))
        if kind is None:
            errors.append(f"Unknown skill category: {sid}")
        record = {"id": source["game_id"], "wiki_id": sid, "name": {"zh": source["name"]},
                  "type": source["element"], "kind": kind, "energy": source.get("energy"),
                  "desc": {"zh": source.get("desc", "")},
                  "source_url": BASE + urllib.parse.quote(modules.get("Targets", {}).get(
                      "trait" if kind == "trait" else "skill", {}).get(sid, source["name"])),
                  "source_module": "Skills"}
        for key in ["power", "power_text", "effect_details", "desc_notes"]:
            if key in source:
                record[key] = source[key]
        (traits if kind == "trait" else moves)[str(record["id"])] = record

    def resolve(sid, context):
        if sid not in skill_ids:
            errors.append(f"Missing skill {sid}: {context}")
            return None
        return skill_ids[sid]

    for pid, source in pets.items():
        if source.get("learnset_id") not in pools:
            errors.append(f"Missing learnset: {pid}")
            continue
        learn = pools[source["learnset_id"]]
        feature = resolve(source["feature_skill_id"], pid)
        form = {"id": source["game_id"], "wiki_id": pid, "number": source.get("number"),
                "slug": source["title"], "name": {"zh": source["name"]}, "title": source["title"],
                "types": source["types"], "relation_key": source.get("relation_key"),
                "stats": {key: source["stats"][original] for key, original in stat_map.items()},
                "trait_id": feature, "stage": source.get("stage"),
                "source_url": BASE + urllib.parse.quote(modules.get("Targets", {}).get("pet", {}).get(pid, source["title"])), "source_module": "Catalog"}
        if portraits and pid in portraits:
            form["portrait_url"] = portraits[pid]
        if source.get("number") is None or len(form["stats"]) != 6:
            errors.append(f"Missing core pet fields: {pid}")
        forms.append(form)
        native = [{**entry, "move": resolve(entry["skill"], pid)} for entry in learn.get("native_skills", [])]
        blood = [{"move": resolve(entry["skill"], pid), "bloodline": entry["blood"], "level": entry.get("level")}
                 for entry in learn.get("blood_skills", [])]
        stones = [resolve(sid, pid) for sid in learn.get("skill_stones", [])]
        legendary = learn.get("legendary")
        normalized_legend = []
        if legendary:
            normalized_legend = [{"move": resolve(legendary["skill"], pid), "requires": legendary.get("requires")}]
        refs = list(dict.fromkeys([entry["move"] for entry in native] + stones +
                                 [entry["move"] for entry in blood] + [entry["move"] for entry in normalized_legend]))
        for mid in refs:
            if str(mid) not in moves:
                errors.append(f"Non-move/missing move {mid}: {pid}")
        if str(feature) not in traits:
            errors.append(f"Non-trait/missing trait {feature}: {pid}")
        detail = {"form": form, "trait": traits.get(str(feature)),
                  "learnset": {"pool": [entry["move"] for entry in native], "stones": stones,
                               "legacy": blood, "legendary": normalized_legend, "native": native},
                  "moves": [moves[str(mid)] for mid in refs if str(mid) in moves],
                  "source_record": source, "source_learnset_id": source["learnset_id"]}
        details[str(form["id"])] = detail
    type_names = sorted({element for pet in pets.values() for element in pet["types"]})
    for pet in pets.values():
        if pet.get("relation_key") not in modules["Types"]:
            errors.append(f"Missing type relation: {pet['id']}")
    expected = modules.get("_expected_forms", modules["Config"].get("pet_count"))
    if expected != len(forms):
        errors.append(f"Declared pet_count {expected} != parsed {len(forms)}")
    nature_stat_keys = {"物攻": "patk", "物防": "pdef", "魔攻": "matk", "魔防": "mdef", "速度": "spd", "生命": "hp"}
    nature_stats = {entry["id"]: nature_stat_keys[entry["name"]] for entry in modules["Natures"]["stats"]}
    natures = [{"id": entry["id"], "name": {"zh": entry["name"]},
                "up": nature_stats[entry["up"]], "down": nature_stats[entry["down"]],
                "subnatures": entry.get("subnatures", []), "source_module": "Natures"}
               for entry in modules["Natures"]["rows"]]
    validation = {"complete": not errors, "expected_forms": expected, "parsed_forms": len(forms),
                  "declared_base_forms": modules["Config"].get("pet_count"),
                  "season_added_forms": expected - modules["Config"].get("pet_count", expected),
                  "move_count": len(moves), "trait_count": len(traits), "learnset_count": len(pools),
                  "term_count": len(modules["Terms"]), "type_combination_count": len(modules["Types"]), "nature_count": len(natures),
                  "consistency_errors": sorted(set(errors)), "mechanics_verified": False,
                  "missing_mechanics_data": ["nature multipliers and talent stat formula", "executable skill and trait effects", "action and event resolution order"],
                  "note": "Complete means selected public BWIKI modules parsed with resolved core references, not full gameplay coverage."}
    return {"schema_version": 1, "source": BASE + urllib.parse.quote("精灵图鉴"),
            "source_name": "BWIKI 洛克王国世界", "snapshot_id": snapshot_id,
            "source_version": modules["Config"].get("current_version"), "provenance": provenance,
            "forms": forms, "details": details, "moves": moves, "traits": traits,
            "natures": natures, "types": type_names, "chart": modules["Types"],
            "chart_schema": "defender_type_combination_to_attacker_weak_resist; explicit double-type multiplier",
            "glossary": [{"key": key, "zh": value["note"], "definition": value["desc"]} for key, value in modules["Terms"].items()],
            "config": modules["Config"], "validation": validation}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume")
    args = parser.parse_args()
    with maintenance(ROOT):
        recover_update(ROOT)
        return update(args)


def update(args):
    base = ROOT / "data" / "bwiki"
    base.mkdir(parents=True, exist_ok=True)
    previous = None
    if (base / "latest.json").exists():
        # Maintenance reads the disk pointer, independently of runtime caches.
        from lab.catalog_store import _read_catalog
        old_catalog, _, old_path = _read_catalog(base)
        old_manifest = old_path.parent / "manifest.json"
        previous = {"catalog": old_catalog, "folder": old_path.parent,
                    "manifest": (json.loads(old_manifest.read_text(encoding="utf8")) if old_manifest.is_file()
                                 else {"pages": old_catalog.get("provenance", {})})}
    source_titles = {**{short: title_of(short) for short in MODULES}, **SEASON_TITLES}
    if previous:
        source_titles.update(previous["manifest"].get("module_titles", {}))
    heads = revision_heads(source_titles)
    if previous and not args.resume and all(
            previous["manifest"].get("pages", {}).get(short, {}).get("revision_id") == heads[short]["revision_id"]
            for short in source_titles):
        print("BWIKI 所需数据模块均无新修订，当前版本保持有效。", flush=True)
        return 0
    snapshot_id = args.resume or datetime.now(TZ).strftime("%Y%m%dT%H%M%S%z")
    if not re.fullmatch(r"[A-Za-z0-9_+\-]+", snapshot_id):
        raise ValueError("Invalid snapshot identifier")
    out = base / snapshot_id
    out.mkdir(exist_ok=bool(args.resume))
    (out / "raw").mkdir(exist_ok=True)
    (out / "modules").mkdir(exist_ok=True)
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("complete"):
            if previous and previous["catalog"]["snapshot_id"] == snapshot_id:
                raise ValueError("Complete active snapshots are immutable")
            required_titles = manifest.get("module_titles", source_titles)
            latest_heads = revision_heads(required_titles)
            if any(manifest["pages"].get(short, {}).get("revision_id") != latest_heads[short]["revision_id"]
                   for short in required_titles):
                raise WikiDataError("已保存快照不再是 BWIKI 最新修订，请重新运行且省略 --resume。")
            catalog = json.loads((out / "catalog.json").read_text(encoding="utf8"))
            if sha((out / "catalog.json").read_bytes()) != manifest["catalog_sha256"]:
                raise WikiDataError("Saved catalog hash mismatch")
            activate(base, out, catalog, previous)
            print("已启用 BWIKI 快照 " + snapshot_id + "，请重新启动 APP。", flush=True)
            return 0
    else:
        manifest = {"schema_version": 1, "snapshot_id": snapshot_id, "started_at": now(),
                    "timezone": "Asia/Shanghai", "source": BASE, "complete": False, "pages": {}}
    save(manifest_path, manifest)

    def fetch(url, name):
        record = manifest["pages"].get(name)
        raw_path = out / "raw" / (name + ".gz")
        if record and raw_path.exists():
            raw = gzip.decompress(raw_path.read_bytes())
            if sha(raw) != record["sha256"]:
                raise WikiDataError(f"Retained source hash mismatch: {name}")
            return raw
        for attempt in range(3):
            try:
                time.sleep(.4 + attempt)
                request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (RocoResearchSnapshot)", "Accept-Encoding": "identity"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read(8_000_001)
                if len(raw) > 8_000_000:
                    raise WikiDataError("Source response exceeds size limit")
                raw_path.write_bytes(gzip.compress(raw, mtime=0))
                manifest["pages"][name] = {"url": url, "fetched_at": now(), "sha256": sha(raw),
                                            "bytes": len(raw), "raw_file": f"raw/{name}.gz"}
                save(manifest_path, manifest)
                return raw
            except Exception:
                if attempt == 2:
                    raise
        raise AssertionError("Unreachable")

    data, provenance = {}, {}

    def load_source(short, title):
        params = {"action": "query", "prop": "revisions", "titles": title,
                  "rvprop": "ids|timestamp|content", "rvslots": "main", "format": "json"}
        # Preserve title separators; fully encoded slashes are rejected by the site's edge.
        url = BASE + "api.php?" + urllib.parse.urlencode(params, safe=":/")
        if short not in manifest["pages"]:
            reuse_module(previous, out, short, heads[short], manifest)
        response = json.loads(fetch(url, short))
        if response.get("error"):
            raise WikiDataError(str(response["error"]))
        page = page_for_revision(response, heads[short]["revision_id"])
        revision = page["revisions"][0]
        if revision["revid"] != heads[short]["revision_id"]:
            raise WikiDataError("Revision changed during snapshot acquisition: " + short)
        source = revision_content(revision)
        if short in ADAPTER_HASHES:
            if sha(source.encode("utf8")) != ADAPTER_HASHES[short]:
                raise WikiDataError("BWIKI 赛季加载逻辑已变化，需核对后更新适配器：" + title)
            parsed = None
        else:
            parsed = parse_lua_data(source)
            save(out / "modules" / (short + ".json"), parsed)
        provenance[short] = {"title": title, "page_id": page["pageid"], "revision_id": revision["revid"],
                             "revision_timestamp": revision["timestamp"], "content_sha256": sha(source.encode("utf-8")),
                             "url": BASE + "index.php?" + urllib.parse.urlencode({"title": title, "oldid": revision["revid"]}, safe=":/")}
        manifest["pages"][short].update(provenance[short])
        save(manifest_path, manifest)
        print(f"Loaded {short}: revision {revision['revid']}", flush=True)
        return parsed

    for short in MODULES:
        data[short] = load_source(short, source_titles[short])
    controls = {short: load_source(short, title) for short, title in SEASON_TITLES.items()}
    if controls["SeasonConfig"].get("view_namespace") != "精灵图鉴/S5":
        raise WikiDataError("BWIKI 当前赛季入口已变化，需核对新入口的公开加载规则。")
    season_manifest = controls["SeasonManifest"]
    season_code = season_manifest["current"]["season"]
    if controls["VisibilityConfig"].get("hidden_seasons", {}).get(season_code) is True:
        raise WikiDataError("BWIKI 当前赛季数据暂未公开，本次保持已有适配数据。")
    from lab.bwiki_seasons import SHARDS, merge_seasons, validate_manifest
    shard_titles = {}
    for index, season in enumerate(validate_manifest(season_manifest)):
        for name in SHARDS:
            shard_titles[f"Season{index}{name}"] = "Module:" + season["namespace"] + "/" + season.get("modules", {}).get(name, name)
    source_titles.update(shard_titles)
    heads.update(revision_heads(shard_titles))
    shards = {}
    for index, season in enumerate(season_manifest["seasons"]):
        for name in SHARDS:
            key = f"Season{index}{name}"
            shards[(season["namespace"], name)] = load_source(key, shard_titles[key])
    base_ids = set(data["Catalog"])
    if data["Config"].get("pet_count") != len(base_ids):
        raise WikiDataError("BWIKI 基础图鉴数量与自身声明不一致。")
    data = merge_seasons(data, season_manifest, shards)
    data["_expected_forms"] = len(base_ids) + len(set(data["Catalog"]) - base_ids)
    for module in MODULES:
        if module == "Natures":
            continue
        # The base revision and every overlay remain attached to the effective view.
        provenance[module]["season_sources"] = {key: value for key, value in provenance.items()
            if key.startswith("Season") or key in ("VisibilityConfig", "VisibilityAdapter")}
    manifest["module_titles"] = source_titles

    portraits = {}
    try:
        html = fetch(BASE + urllib.parse.quote("精灵图鉴"), "dex-html").decode("utf-8")
        for pid, image in re.findall(r'class="npc-card"[^>]*data-id="([^"]+)"(?:(?!class="npc-card").)*?<img[^>]*src="([^"]+)"', html, re.S):
            if image.startswith("https://patchwiki.biligame.com/"):
                portraits[pid] = image
    except Exception as exc:
        manifest["portrait_warning"] = str(exc)
    catalog = normalize(data, snapshot_id, provenance, portraits)
    if revision_heads(source_titles) != heads:
        raise WikiDataError("BWIKI 在本次下载过程中有新修订，请重新运行以获得一致版本。")
    save(out / "catalog.json", catalog)
    manifest.update({"complete": catalog["validation"]["complete"], "completed_at": now(),
                     "source_version": catalog["source_version"], "validation": catalog["validation"],
                     "catalog_sha256": sha((out / "catalog.json").read_bytes()),
                     "popular_builds_enabled": False, "portrait_count": len(portraits)})
    save(manifest_path, manifest)
    if manifest["complete"]:
        activate(base, out, catalog, previous)
    print(json.dumps({"snapshot_id": snapshot_id, **catalog["validation"]}, ensure_ascii=False), flush=True)
    return 0 if manifest["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
