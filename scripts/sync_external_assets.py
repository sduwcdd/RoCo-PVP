"""Copy read-only reference assets from the third-party 青空洛克PVP助手 package.

The source tree is never modified. Everything lands in new directories so the
existing workspace files are untouched:

  web/assets/roco/skill-icons/     skill icon PNGs, named by icon resource id
  web/assets/roco/pet-avatars/     pet head icons, named by petbase id
  web/assets/roco/type-icons/      element icons, named by Chinese element name
  web/assets/roco/bloodline-icons/ bloodline icons, named by bloodline id
  web/assets/roco/manifest.json    id -> file mapping consumed by the workbench
  data/external/                   authoritative game data (skill/petbase/buff...)

Run:  python scripts/sync_external_assets.py
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"E:\洛克PVP助手\app\wwwroot")

TARGET_ASSETS = ROOT / "web" / "assets" / "roco"
TARGET_DATA = ROOT / "data" / "external"

AUTHORITY_FILES = {
    "skill.json": "authority/skill.json",
    "petbase.json": "authority/petbase.json",
    "buff.json": "authority/buff.json",
    "roco_buff_calc_map.json": "roco_buff_calc_map.json",
    "pokedex_pvp_usage.json": "pokedex_800_pvp_usage_v340.json",
    "level_skill.json": "authority/level_skill.json",
}


def load_catalog():
    import sys

    sys.path.insert(0, str(ROOT))
    from lab.server import load_catalog as loader

    catalog, _, _ = loader()
    return catalog


def icon_resource_id(skill_entry: dict) -> str:
    raw = str(skill_entry.get("icon") or "")
    found = re.findall(r"([0-9]{5,8})", raw)
    return found[-1] if found else ""


def copy_file(src: Path, dst: Path) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst.stat().st_size


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit(f"source missing: {SOURCE}")

    catalog = load_catalog()
    moves = catalog["moves"]
    details = catalog["details"]
    types = catalog["types"]

    authority = json.loads((SOURCE / "native-data" / "authority" / "skill.json").read_text(encoding="utf-8"))
    icon_dir = SOURCE / "roco-skill-icons"
    avatar_dir = SOURCE / "roco-pet-avatars-id"

    skill_icons: dict[str, str] = {}
    skill_missing: list[str] = []
    skill_bytes = 0
    for move_id in moves:
        entry = authority.get(str(move_id)) or {}
        resource = icon_resource_id(entry)
        src = icon_dir / f"{resource}.png"
        if not resource or not src.is_file():
            skill_missing.append(str(move_id))
            continue
        name = f"{resource}.png"
        if not (TARGET_ASSETS / "skill-icons" / name).is_file():
            skill_bytes += copy_file(src, TARGET_ASSETS / "skill-icons" / name)
        skill_icons[str(move_id)] = name

    pet_avatars: dict[str, str] = {}
    pet_missing: list[str] = []
    pet_bytes = 0
    # The HUD resolves avatars by petbase id (including the "_1" shiny variants),
    # so the whole folder is mirrored; the manifest only publishes catalog forms.
    for src in sorted(avatar_dir.iterdir()):
        if not src.is_file():
            continue
        if not (TARGET_ASSETS / "pet-avatars" / src.name).is_file():
            pet_bytes += copy_file(src, TARGET_ASSETS / "pet-avatars" / src.name)
    for form_id in details:
        src = avatar_dir / f"{form_id}.png"
        if not src.is_file():
            pet_missing.append(str(form_id))
            continue
        pet_avatars[str(form_id)] = src.name

    type_icons: dict[str, str] = {}
    type_bytes = 0
    for type_name in types:
        stem = str(type_name).replace("系", "")
        src = SOURCE / "roco-type-icons" / f"{stem}.png"
        if src.is_file():
            type_bytes += copy_file(src, TARGET_ASSETS / "type-icons" / src.name)
            type_icons[str(type_name)] = src.name

    bloodline_icons: dict[str, str] = {}
    for src in sorted((SOURCE / "bloodline-icons").iterdir()):
        if src.is_file():
            copy_file(src, TARGET_ASSETS / "bloodline-icons" / src.name)
            bloodline_icons[src.stem] = src.name

    data_bytes = 0
    for target_name, relative in AUTHORITY_FILES.items():
        src = SOURCE / "native-data" / relative
        if src.is_file():
            data_bytes += copy_file(src, TARGET_DATA / target_name)

    manifest = {
        "source": str(SOURCE),
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "note": "只读同步自第三方发行版；id 与本地图鉴一致（技能 id / 形态 id）。",
        "skill_icons": skill_icons,
        "pet_avatars": pet_avatars,
        "type_icons": type_icons,
        "bloodline_icons": bloodline_icons,
    }
    TARGET_ASSETS.mkdir(parents=True, exist_ok=True)
    (TARGET_ASSETS / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    print(f"skill icons      : {len(skill_icons)} mapped, {len(skill_missing)} missing, {skill_bytes/1024/1024:.1f} MB copied")
    print(f"pet avatars      : {len(pet_avatars)} mapped, {len(pet_missing)} missing, {pet_bytes/1024/1024:.1f} MB copied")
    print(f"type icons       : {len(type_icons)} of {len(types)}, {type_bytes/1024:.0f} KB")
    print(f"bloodline icons  : {len(bloodline_icons)}")
    print(f"authority data   : {data_bytes/1024/1024:.1f} MB")
    if skill_missing:
        print("missing skill icons:", ",".join(skill_missing[:20]))
    if pet_missing:
        print("missing pet avatars:", ",".join(pet_missing[:20]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
