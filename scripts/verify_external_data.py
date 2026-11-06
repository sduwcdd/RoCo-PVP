"""Cross-check the local catalog against the authoritative unpacked game data.

Reads data/external/*.json (copied by scripts/sync_external_assets.py) and reports
agreement for: skill power, skill energy cost, hit counts, base stats, trait ids.

Run:  python scripts/verify_external_data.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab.server import load_catalog  # noqa: E402
from lab.skill_hits import base_hits  # noqa: E402

DATA = ROOT / "data" / "external"


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def main() -> int:
    catalog, _, _ = load_catalog()
    moves = catalog["moves"]
    details = catalog["details"]

    skill_auth = load("skill.json")
    pet_auth = load("petbase.json")

    # --- 1. power / energy -------------------------------------------------
    power_ok = power_diff = 0
    energy_ok = energy_diff = 0
    energy_diffs = []
    power_diffs = []
    for mid, move in moves.items():
        auth = skill_auth.get(str(mid))
        if not auth:
            continue
        dam = auth.get("dam_para") or []
        cost = auth.get("energy_cost") or []
        if dam and isinstance(move.get("power"), (int, float)):
            if int(dam[0]) == int(move["power"]):
                power_ok += 1
            else:
                power_diff += 1
                power_diffs.append((mid, move["power"], dam[0]))
        if cost and isinstance(move.get("energy"), (int, float)):
            if int(cost[0]) == int(move["energy"]):
                energy_ok += 1
            else:
                energy_diff += 1
                energy_diffs.append((mid, move["energy"], cost[0]))

    # --- 2. hit counts -----------------------------------------------------
    hit_ok = hit_diff = 0
    hit_diffs = []
    for mid in moves:
        auth = skill_auth.get(str(mid))
        if not auth:
            continue
        text = str(auth.get("desc") or "")
        if "连击" not in text:
            continue
        found = re.findall(r"([0-9]+)\s*连击", text)
        if not found:
            continue
        authoritative = int(found[0])
        ours = base_hits(catalog, mid)[0]
        if ours == authoritative:
            hit_ok += 1
        else:
            hit_diff += 1
            hit_diffs.append((mid, ours, authoritative))

    # --- 3. base stats -----------------------------------------------------
    stat_keys = {"hp": "hp_max_race", "patk": "phy_attack_race", "matk": "spe_attack_race",
                 "pdef": "phy_defence_race", "mdef": "spe_defence_race", "spd": "speed_race"}
    stat_ok = stat_diff = 0
    stat_diffs = []
    for fid, detail in details.items():
        auth = pet_auth.get(str(fid))
        if not auth:
            continue
        ours = (detail.get("form") or {}).get("stats") or {}
        for local_key, auth_key in stat_keys.items():
            if local_key in ours and auth_key in auth:
                if int(ours[local_key]) == int(auth[auth_key]):
                    stat_ok += 1
                else:
                    stat_diff += 1
                    if len(stat_diffs) < 20:
                        stat_diffs.append((fid, local_key, ours[local_key], auth[auth_key]))

    # --- 4. trait ids ------------------------------------------------------
    trait_ok = trait_diff = 0
    trait_diffs = []
    for fid, detail in details.items():
        auth = pet_auth.get(str(fid))
        if not auth:
            continue
        ours = (detail.get("form") or {}).get("trait_id")
        theirs = auth.get("pet_feature")
        if ours is None or theirs is None:
            continue
        if int(ours) == int(theirs):
            trait_ok += 1
        else:
            trait_diff += 1
            if len(trait_diffs) < 20:
                trait_diffs.append((fid, ours, theirs))

    print("== skill power ==")
    print(f"match {power_ok} / differ {power_diff}")
    print("  diffs:", power_diffs[:10])
    print("== skill energy cost ==")
    print(f"match {energy_ok} / differ {energy_diff}")
    print("  diffs:", energy_diffs[:10])
    print("== hit counts (authoritative desc) ==")
    print(f"match {hit_ok} / differ {hit_diff}")
    print("  diffs:", hit_diffs[:10])
    print("== base stats (6 dimensions per form) ==")
    print(f"match {stat_ok} / differ {stat_diff}")
    print("  diffs:", stat_diffs)
    print("== trait ids ==")
    print(f"match {trait_ok} / differ {trait_diff}")
    print("  diffs:", trait_diffs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
