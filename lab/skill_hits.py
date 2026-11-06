"""Base hit count of a damaging skill, recovered from its wiki description.

The platform catalog records one ``power`` per skill and no explicit hit-count
column. Where the description declares "N连击", the simulator's
``damage.sequence`` resolves N separate hits. The default ``multi_hit_power``
policy is now ``source_power_per_hit``: every hit uses the full recorded power
(a 40-power 3-hit skill deals 40 three times), matching what the battle screen
shows in game. ``source_power_total`` (split power ÷ N) is kept as an explicit
alternative for comparison. This module recovers N from the description text
only, and reports that provenance so no caller can present it as a game-file
fact.

Clauses that describe a *change* to the count (response bonus, position bonus,
permanent growth, fixed counts, "不含连击"/"连击数" wording) are deliberately
ignored: they are conditional and cannot be applied without the actual turn.
"""
from __future__ import annotations

import re

_CLAUSE = re.compile(r"[，,。；;\n]")
_HITS = re.compile(r"(\d+)\s*连击")
_NOT_A_COUNT = ("不含连击", "连击数")
# "自己获得…3连击" / "敌方获得…2连击" name the buff an effect grants, then state the
# skill's own hit count, so they are not conditions. 2026-10-28 review of the three
# remaining differences (三连破 3, 电离爆破 2, 耍赖 2) confirmed the description wins.
_CONDITIONAL = ("应对", "若", "每次", "使用后", "队伍中",
                "改为", "每携带", "每受", "时连击")

SOURCE_PARSED = "wiki_desc_parsed"
SOURCE_DEFAULT = "single_hit_default"


def _description(move):
    desc = move.get("desc")
    if isinstance(desc, dict):
        return str(desc.get("zh") or "")
    return "" if desc is None else str(desc)


def base_hits(catalog, skill_id):
    """Return ``(hits, source)`` for one skill; hits >= 1."""
    moves = catalog.get("moves") or {}
    move = moves.get(str(skill_id)) if isinstance(moves, dict) else None
    if not isinstance(move, dict):
        return 1, SOURCE_DEFAULT
    for clause in _CLAUSE.split(_description(move)):
        if any(marker in clause for marker in _NOT_A_COUNT):
            continue
        if any(marker in clause for marker in _CONDITIONAL):
            break
        found = _HITS.search(clause)
        if found:
            hits = int(found.group(1))
            return (hits, SOURCE_PARSED) if hits >= 1 else (1, SOURCE_DEFAULT)
    return 1, SOURCE_DEFAULT
