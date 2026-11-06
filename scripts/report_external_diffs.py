"""Produce a human-checkable diff sheet: catalog vs unpacked game data.

Writes artifacts/external_diff_report.json plus two markdown tables:
  artifacts/external_diff_report.md   (what to verify in-game by hand)
  artifacts/pvp_usage_sample.md       (what "ladder usage" data actually looks like)

Run:  python scripts/report_external_diffs.py
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
ART = ROOT / "artifacts"

DIM_LABELS = {
    "hp": ("hp", "hp_max_race", "生命"),
    "patk": ("patk", "phy_attack_race", "物攻"),
    "matk": ("matk", "spe_attack_race", "魔攻"),
    "pdef": ("pdef", "phy_defence_race", "物防"),
    "mdef": ("mdef", "spe_defence_race", "魔防"),
    "spd": ("spd", "speed_race", "速度"),
}


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def name_of(node) -> str:
    if isinstance(node, dict):
        zh = (node.get("name") or {})
        if isinstance(zh, dict) and zh.get("zh"):
            return str(zh["zh"])
        detail = node.get("form") or {}
        zh2 = (detail.get("name") or {})
        if isinstance(zh2, dict) and zh2.get("zh"):
            return str(zh2["zh"])
    return ""


def main() -> int:
    catalog, _, _ = load_catalog()
    moves, details = catalog["moves"], catalog["details"]
    skill_auth, pet_auth = load("skill.json"), load("petbase.json")

    # ---- 1. base stats -------------------------------------------------
    stat_rows, missing_forms = [], []
    stat_ok = stat_diff = 0
    for fid, detail in details.items():
        form = detail.get("form") or {}
        auth = pet_auth.get(str(fid))
        if not auth:
            missing_forms.append((fid, name_of(form)))
            continue
        for key, (local_key, auth_key, label) in DIM_LABELS.items():
            ours, theirs = (form.get("stats") or {}).get(local_key), auth.get(auth_key)
            if ours is None or theirs is None:
                continue
            if int(ours) == int(theirs):
                stat_ok += 1
            else:
                stat_diff += 1
                stat_rows.append({
                    "form_id": fid, "form_name": name_of(form), "dim": key, "dim_label": label,
                    "catalog": int(ours), "unpacked": int(theirs), "delta_catalog_minus_unpacked": int(ours) - int(theirs),
                })

    # ---- 2. hit counts -------------------------------------------------
    hit_rows, hit_ok = [], 0
    for mid in moves:
        auth = skill_auth.get(str(mid))
        if not auth:
            continue
        desc = str(auth.get("desc") or "")
        found = re.findall(r"([0-9]+)\s*连击", desc)
        if not found:
            continue
        theirs, ours = int(found[0]), base_hits(catalog, mid)[0]
        if ours == theirs:
            hit_ok += 1
        else:
            hit_rows.append({
                "skill_id": mid, "skill_name": str((auth.get("name") or "")), "catalog_hits": ours,
                "desc_hits": theirs, "desc": desc[:160],
                "catalog_power": moves[mid].get("power"),
            })

    # ---- 3. power ------------------------------------------------------
    power_rows, power_ok, power_marker_only = [], 0, 0
    for mid, move in moves.items():
        auth = skill_auth.get(str(mid))
        dam = (auth or {}).get("dam_para") or []
        ours = move.get("power")
        if not dam or not isinstance(ours, (int, float)):
            continue
        if int(dam[0]) == int(ours):
            power_ok += 1
        elif len(dam) > 1 and int(dam[1]) == int(ours):
            # dam_para[0] is a formula marker; dam_para[1] is the base power.
            power_marker_only += 1
        else:
            power_rows.append({
                "skill_id": mid, "skill_name": name_of(move), "catalog_power": int(ours),
                "dam_para": dam, "desc": str((auth or {}).get("desc") or "")[:200],
            })

    report = {
        "counts": {
            "base_stats_match": stat_ok, "base_stats_differ": stat_diff,
            "forms_without_unpacked_record": len(missing_forms),
            "hit_counts_match": hit_ok, "hit_counts_differ": len(hit_rows),
            "power_match_direct": power_ok, "power_match_via_marker": power_marker_only,
            "power_differ": len(power_rows),
        },
        "base_stat_diffs": stat_rows,
        "hit_count_diffs": hit_rows,
        "power_diffs": power_rows,
        "missing_unpacked_forms": missing_forms,
    }
    (ART / "external_diff_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- markdown ------------------------------------------------------
    lines = ["# 图鉴 vs 解包数据：不一致清单（供游戏内核对）", "",
             "> **2026-10-28 已裁定**：六维种族值以图鉴（BWIKI）为准，解包为滞后补丁，平台不改值；",
             "> 连击段数以技能描述为准，三连破/电离爆破/耍赖 已按描述改为 3/2/2；",
             "> 3872–3878 七个形态属解包未收录的补丁形态，不做处理。", "",
             f"- 六维种族值：一致 {stat_ok} 项 / 不一致 {stat_diff} 项",
             f"- 连击段数：一致 {hit_ok} 条 / 不一致 {len(hit_rows)} 条",
             f"- 技能威力：直接一致 {power_ok} 条 / 经标记位一致 {power_marker_only} 条 / 不一致 {len(power_rows)} 条",
             f"- 解包表未收录的形态：{len(missing_forms)} 个", ""]

    if stat_rows:
        by_form: dict[str, list] = {}
        for row in stat_rows:
            by_form.setdefault(f"{row['form_id']} {row['form_name']}", []).append(row)
        lines += ["## 1. 六维种族值", "",
                  "| 形态 | 生命 | 物攻 | 魔攻 | 物防 | 魔防 | 速度 |",
                  "|---|---|---|---|---|---|---|"]
        for label, rows in by_form.items():
            rows.sort(key=lambda r: list(DIM_LABELS).index(r["dim"]))
            lines.append("| " + label + " | " + " | ".join(
                f"图鉴 {r['catalog']} / 解包 {r['unpacked']}" for r in rows) + " |")
        lines += ["", "> 图鉴=当前平台使用的 BWIKI 快照；解包=游戏文件 `petbase.json`。", ""]

    if hit_rows:
        lines += ["## 2. 连击段数", "",
                  "| 技能 | ID | 图鉴段数 | 解包描述段数 | 威力 | 描述原文（截断） |",
                  "|---|---|---|---|---|---|"]
        for row in hit_rows:
            lines.append(f"| {row['skill_name']} | {row['skill_id']} | {row['catalog_hits']} | "
                         f"{row['desc_hits']} | {row['catalog_power']} | {row['desc']} |")
        lines += ["", "> 这三条都是状态技（威力为空），段数不影响伤害计算。", ""]

    if power_rows:
        lines += ["## 3. 技能威力", "",
                  "| 技能 | ID | 图鉴威力 | dam_para | 描述（截断） |", "|---|---|---|---|---|"]
        for row in power_rows:
            lines.append(f"| {row['skill_name']} | {row['skill_id']} | {row['catalog_power']} | "
                         f"{row['dam_para']} | {row['desc']} |")
        lines += ["", "> `dam_para[0]` 是公式标记（0=按公式），基础威力取 `dam_para[1]`。", ""]

    if missing_forms:
        lines += ["## 4. 解包表未收录的形态", "",
                  "| 形态 ID | 名称 |", "|---|---|"]
        for fid, label in missing_forms:
            lines.append(f"| {fid} | {label} |")
        lines.append("")

    (ART / "external_diff_report.md").write_text("\n".join(lines), encoding="utf-8")

    # ---- usage sample --------------------------------------------------
    usage = load("pokedex_pvp_usage.json")
    meta = usage.get("metadata") or {}
    pets = usage.get("pets") or {}
    picks = [k for k in pets if pets[k].get("nature_usage")][:3] or list(pets)[:3]
    out = ["# 天梯使用率数据长什么样（真实条目）", "",
           "## 数据来源", "",
           f"- `source_endpoint`：{meta.get('source_endpoint')}",
           f"- `collected_at`：{meta.get('collected_at')}",
           f"- `revision`：{meta.get('revision')}，模式 {meta.get('mode')}，队伍类型 {meta.get('team_type')}",
           f"- 覆盖：目录 {meta.get('catalog_count')} 条、唯一基础形态 {meta.get('unique_base_count')}、"
           f"返回 {meta.get('returned_base_count')}；各维度覆盖 {meta.get('coverage')}", ""]
    for key in picks:
        pet = pets[key]
        out += [f"## {pet.get('name')}（pet_base_id {pet.get('pet_base_id')}，当前形态 {pet.get('current_id')}）", ""]
        for field, title in (("nature_usage", "性格使用率"), ("individual_value_usage", "个体值使用率"),
                             ("bloodline_usage", "血脉使用率"), ("skill_usage", "技能使用率")):
            rows = pet.get(field) or []
            if not rows:
                continue
            top = sorted(rows, key=lambda r: r.get("percent") or 0, reverse=True)[:5]
            out.append(f"**{title}**（共 {len(rows)} 项，前 5）")
            out.append("")
            out.append("| 名称 | id | percent | ratio | rank |")
            out.append("|---|---|---|---|---|")
            for row in top:
                out.append(f"| {row.get('name')} | {row.get('id')} | {row.get('percent')} | "
                           f"{row.get('ratio')} | {row.get('rank')} |")
            out.append("")
    (ART / "pvp_usage_sample.md").write_text("\n".join(out), encoding="utf-8")

    print(json.dumps(report["counts"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
