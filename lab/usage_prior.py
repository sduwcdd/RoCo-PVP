"""Real ladder (PVP) usage statistics from the unpacked game client.

The dataset is one snapshot collected from the game's own pet-stat endpoint
(``wegame.shallow.ink``), so unlike a hand-made candidate list it *is* a
population statistic. This module never invents a value the snapshot does not
contain: a dimension with no observation stays ``None`` and is reported as such.

Percentages are shares *within one dimension* (how many players that used this
pet picked that nature / individual / bloodline / skill). They are not a
probability that the opponent is carrying it, and they are not a joint
distribution: the snapshot has no nature x move cross table, so nothing here may
be multiplied together and presented as a joint likelihood.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parents[1] / "data" / "external" / "pokedex_pvp_usage.json"

# Mirrors web/battle.js BLOODLINES; the snapshot uses the same names for the
# nineteen selectable bloodlines.
BLOODLINES = ["未指定", "普通", "草", "火", "水", "光", "地", "冰", "龙", "电",
              "毒", "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻", "首领"]
_BLOODLINE_INDEX = {name: index for index, name in enumerate(BLOODLINES)}

# individual_value_usage ids observed in the snapshot -> workbench dimension.
_IV_DIMENSION = {1: "hp", 2: "patk", 3: "matk", 4: "pdef", 5: "mdef", 6: "spd"}
DIMENSIONS = ["hp", "patk", "matk", "pdef", "mdef", "spd"]


class UsageError(ValueError):
    """The snapshot cannot answer the question as asked."""


def load_usage(path: str | Path | None = None) -> dict[str, Any]:
    data = json.loads(Path(path or _DATA).read_text(encoding="utf-8"))
    pets = data.get("pets")
    if not isinstance(pets, dict):
        raise UsageError("usage snapshot has no pets table")
    return data


class UsageTable:
    """Read-only view over one ladder-usage snapshot."""

    def __init__(self, data: dict[str, Any] | None = None, path: str | Path | None = None):
        self._data = data if data is not None else load_usage(path)
        self.metadata = self._data.get("metadata") or {}
        self._pets = self._data["pets"]

    # -- lookups ---------------------------------------------------------
    def pet(self, base_id: int | str) -> dict[str, Any] | None:
        pet = self._pets.get(str(base_id))
        return pet if isinstance(pet, dict) else None

    def find(self, query: str = "", limit: int = 40) -> list[dict[str, Any]]:
        text = (query or "").strip()
        rows = []
        for base_id, pet in self._pets.items():
            name = pet.get("name") or ""
            if text and text not in name and text not in str(base_id):
                continue
            rows.append({
                "base_id": int(base_id),
                "current_id": pet.get("current_id"),
                "name": name,
                "data_status": pet.get("data_status"),
                "top_nature": self._top(pet.get("nature_usage")),
                "top_skill": self._top(pet.get("skill_usage")),
                "top_bloodline": self._top(pet.get("bloodline_usage")),
            })
        rows.sort(key=lambda row: (row["data_status"] != "ok", row["base_id"]))
        return rows[:max(1, limit)]

    @staticmethod
    def _top(rows) -> Any:
        if not isinstance(rows, list) or not rows:
            return None
        best = rows[0]
        return {"id": best.get("id"), "name": best.get("name"), "percent": best.get("percent")}

    def provenance(self) -> dict[str, Any]:
        meta = self.metadata
        return {
            "source_endpoint": meta.get("source_endpoint"),
            "revision": meta.get("revision"),
            "collected_at": meta.get("collected_at"),
            "mode": meta.get("mode"),
            "team_type": meta.get("team_type"),
            "returned_base_count": meta.get("returned_base_count"),
            "note": meta.get("note"),
            "population_statistics": True,
            "joint_distribution": False,
        }

    # -- build -----------------------------------------------------------
    def build(self, base_id: int | str, form_id: int | str | None, catalog: dict[str, Any]) -> dict[str, Any]:
        """Most used configuration of one pet, restricted to what its learnset allows.

        Moves the snapshot ranks highly but the form cannot learn are *reported*
        and skipped, never silently replaced by a lower-ranked move.
        """
        pet = self.pet(base_id)
        if pet is None or pet.get("data_status") != "ok":
            raise UsageError(f"没有该精灵的天梯样本：{base_id}")
        form_key = str(form_id if form_id is not None else pet.get("current_id") or base_id)
        detail = (catalog.get("details") or {}).get(form_key)
        learnset = set()
        if isinstance(detail, dict):
            pool = (detail.get("learnset") or {}).get("pool")
            if isinstance(pool, list):
                learnset = {int(x) for x in pool}

        natures = {int(n["id"]): n for n in catalog.get("natures") or []}
        nature_rows = pet.get("nature_usage") or []
        nature = None
        if nature_rows:
            row = nature_rows[0]
            known = natures.get(int(row["id"]))
            nature = {
                "id": int(row["id"]),
                "name": row.get("name"),
                "percent": row.get("percent"),
                "rank": row.get("rank"),
                "matched_catalog": bool(known) and (known.get("name") or {}).get("zh") == row.get("name"),
                "up": known.get("up") if known else None,
                "down": known.get("down") if known else None,
            }

        talent_rows = pet.get("individual_value_usage") or []
        selected = [row for row in talent_rows if int(row.get("id", 0)) in _IV_DIMENSION]
        top3 = selected[:3]
        talents = {dim: None for dim in DIMENSIONS}
        for row in top3:
            talents[_IV_DIMENSION[int(row["id"])]] = 10
        talent_ranking = [{
            "dimension": _IV_DIMENSION[int(row["id"])],
            "name": row.get("name"),
            "percent": row.get("percent"),
            "rank": row.get("rank"),
        } for row in selected]

        bloodline = None
        bloodline_note = None
        blood_rows = pet.get("bloodline_usage") or []
        if blood_rows:
            row = blood_rows[0]
            index = _BLOODLINE_INDEX.get(row.get("name"))
            if index is None:
                bloodline_note = f"天梯首位血脉「{row.get('name')}」不在可选血脉列表中，未填入"
            else:
                bloodline = {"id": index, "name": row.get("name"), "percent": row.get("percent"),
                             "rank": row.get("rank")}

        moves, moves_detail, skipped = [], [], []
        for row in pet.get("skill_usage") or []:
            move_id = int(row["id"])
            available = move_id in learnset
            entry = {"id": move_id, "name": row.get("name"), "percent": row.get("percent"),
                     "rank": row.get("rank"), "available": available}
            moves_detail.append(entry)
            if not available:
                skipped.append({"id": move_id, "name": row.get("name"),
                                "percent": row.get("percent"), "reason": "不在该形态学习池内"})
                continue
            if len(moves) < 4:
                moves.append(move_id)
        if len(moves) < 4:
            skipped.append({"id": None, "name": None, "percent": None,
                            "reason": f"学习池内只有 {len(moves)} 个天梯技能达到四槽，未补足"})

        form_name = None
        forms = catalog.get("forms") or []
        for form in forms:
            if str(form.get("id")) == form_key:
                form_name = (form.get("name") or {}).get("zh")
                break

        return {
            "base_id": int(base_id),
            "form_id": form_key,
            "form_name": form_name,
            "pet_name": pet.get("name"),
            "learnset_size": len(learnset),
            "nature": nature,
            "talents": talents,
            "talent_ranking": talent_ranking,
            "bloodline": bloodline,
            "bloodline_note": bloodline_note,
            "moves": moves,
            "moves_detail": moves_detail,
            "skipped": skipped,
            "provenance": self.provenance(),
        }

    # -- Complete roster records -----------------------------------------
    def roster_member(self, base_id: int | str, form_id: int | str | None,
                      catalog: dict[str, Any]) -> dict[str, Any]:
        """One source-traceable roster member built from the ladder snapshot.

        Fails closed: a missing nature or an empty move set raises instead of
        producing an incomplete configuration.
        """
        build = self.build(base_id, form_id, catalog)
        if not build["nature"] or not build["nature"].get("matched_catalog"):
            raise UsageError("天梯首位性格无法与当前性格表匹配，未构造队伍记录")
        moves = list(build["moves"])
        if not moves:
            raise UsageError("该形态学习池内没有天梯技能，未构造队伍记录")
        while len(moves) < 4:
            moves.append(0)
        selected = [row["dimension"] for row in build["talent_ranking"]][:3]
        return {
            "form_id": int(build["form_id"]),
            "move_ids": moves,
            "nature_id": int(build["nature"]["id"]),
            "talent_selection": {"selected": selected,
                                 "values": {dim: 10 for dim in selected}},
            "team_code": {"raw_markers": [79 + DIMENSIONS.index(dim) for dim in selected]},
            "usage_provenance": {
                "base_id": build["base_id"],
                "source_endpoint": build["provenance"]["source_endpoint"],
                "collected_at": build["provenance"]["collected_at"],
            },
        }

    def roster(self, base_ids: list[int | str], catalog: dict[str, Any]) -> list[dict[str, Any]]:
        return [self.roster_member(base_id, None, catalog) for base_id in base_ids]

    def prior_candidates(self, base_id: int | str, form_id: int | str | None,
                         catalog: dict[str, Any], nature_limit: int = 3) -> list[dict[str, Any]]:
        """Explicit candidate configurations for the opponent belief filter.

        One candidate per observed nature (top ``nature_limit``), all sharing the
        top four learnable moves. ``prior`` is that nature's own share, so the
        weights sum to less than one when other natures exist — the filter
        normalises them; the share is never claimed to be a joint probability.
        """
        build = self.build(base_id, form_id, catalog)
        moves = list(build["moves"])
        if not moves:
            raise UsageError("该形态没有可用的天梯技能，无法构造候选")
        while len(moves) < 4:
            moves.append(0)
        pet = self.pet(base_id) or {}
        out = []
        for row in (pet.get("nature_usage") or [])[:nature_limit]:
            percent = row.get("percent")
            if not isinstance(percent, (int, float)) or percent <= 0:
                continue
            out.append({
                "id": f"usage-{base_id}-nature-{row['id']}",
                "nature_id": int(row["id"]),
                "talents": dict(build["talents"], **{d: 0 for d in DIMENSIONS if build["talents"][d] is None}),
                "moves": list(moves),
                "move_slots_known": True,
                "prior": float(percent),
                "prior_basis": "ladder_nature_share",
                "note": "技能四槽取天梯首位且可学习的技能；个体按天梯前三项，其余按 0 处理。",
            })
        return out
