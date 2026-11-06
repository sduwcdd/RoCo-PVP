"""Local research imports. Recognition never supplies unobserved configurations."""
from __future__ import annotations

import re
from collections import Counter
from hashlib import sha256

from lab.team_code import parse_team_code


def parse_team_codes(text, catalog):
    if not isinstance(text, str) or len(text) > 100_000:
        raise ValueError("阵容码文本应为不超过 100000 字符的字符串")
    lines = [(i, s) for i, s in enumerate(text.splitlines(), 1) if s.strip()]
    if not 1 <= len(lines) <= 200:
        raise ValueError("每次请提供 1～200 条阵容码，每行一条")
    return {"record_count": len(lines), "results": [
        {"line": i, "result": parse_team_code(s, catalog)} for i, s in lines
    ], "notice": "空白行忽略；保留原行号。每条独立校验，不补齐、不合并、不自动导入。"}


def _name(value):
    return value if isinstance(value, str) else value.get("zh", "") if isinstance(value, dict) else ""


def _normal(value):
    return value.strip().replace("（", "(").replace("）", ")")


def recognize_opponent(text, catalog):
    if not isinstance(text, str) or len(text) > 4000 or not text.strip():
        raise ValueError("请输入对方 1～6 只精灵的名称或游戏 ID")
    forms = catalog.get("forms", [])
    labels = {_normal(f.get("title") or _name(f.get("name"))) for f in forms}
    tokens = [t.strip() for t in re.split(r"[\n\r,，、;；]+", text) if t.strip()]
    if len(tokens) == 1 and _normal(tokens[0]) not in labels:
        tokens = text.split()
    result = {"input_type": "opponent_names", "raw_text": text,
              "snapshot_id": catalog.get("snapshot_id"), "members": [], "issues": [],
              "format_valid": 1 <= len(tokens) <= 6, "importable": False, "training_eligible": False}
    def issue(category, code, message, slot=None, raw=None):
        result["issues"].append({"category": category, "code": code, "message": message,
                                 "member_slot": slot, "field": "opponent_names", "raw_value": raw,
                                 "evidence": {"source": "BWIKI snapshot", "snapshot_id": result["snapshot_id"]}})
    if not result["format_valid"]:
        issue("format_error", "member_count", "名称列表须包含 1～6 只精灵；请用逗号或换行分隔。", raw=len(tokens))
        return result
    for slot, token in enumerate(tokens, 1):
        normalized = _normal(token)
        # Base names can identify several forms. Never prefer the first matching ID.
        matches = [f for f in forms if (
            str(f.get("game_id", f.get("id"))) == token if token.isascii() and token.isdigit()
            else normalized in {_normal(f.get("title", "")), _normal(_name(f.get("name")))}
        )]
        candidates = [{"id": f.get("game_id", f.get("id")),
                       "title": f.get("title") or _name(f.get("name"))} for f in matches]
        member = {"slot": slot, "raw_input": token, "form_id": None, "form_name": None,
                  "form": None, "move_ids": [0, 0, 0, 0], "nature_id": 0, "bloodline_id": 0,
                  "talents": {d: None for d in ("hp", "patk", "matk", "pdef", "mdef", "spd")},
                  "candidates": candidates, "importable": len(matches) == 1}
        if len(matches) == 1:
            member.update(form_id=candidates[0]["id"], form_name=candidates[0]["title"],
                          form={"id": candidates[0]["id"], "title": candidates[0]["title"]})
        elif matches:
            issue("unverified", "ambiguous_form", f"第 {slot} 只“{token}”匹配多个形态，请填写完整形态名称或游戏 ID。", slot, token)
        else:
            issue("database_conflict", "unknown_form", f"第 {slot} 只“{token}”无法匹配当前图鉴；未猜测或替换。", slot, token)
        result["members"].append(member)
    issue("unverified", "configuration_unknown", "名称只能识别精灵；性格、血脉、四槽配招及六维资质仍未知，不能据此生成概率或正式训练配置。")
    result["importable"] = all(m["importable"] for m in result["members"])
    return result


def search_opponent_teams(text, catalog, library_text):
    """Set containment is a search filter, not a posterior or popularity estimate."""
    if not isinstance(text, str):
        raise ValueError("请提供精灵名称文本")
    query = recognize_opponent(text, catalog) if text.strip() else None
    library = parse_team_codes(library_text, catalog)
    required = Counter(str(m["form_id"]) for m in query["members"]) if query and query["importable"] else Counter()
    matches = []
    if query is None or query["importable"]:
        for entry in library["results"]:
            parsed = entry["result"]
            available = Counter(str(m["form_id"]) for m in parsed["members"] if m.get("form_id") is not None)
            if required and (not parsed["format_valid"] or any(available[f] < count for f, count in required.items())):
                continue
            matches.append({"library_id": sha256(parsed["raw_code"].encode()).hexdigest(),
                            "line": entry["line"], "result": parsed})
    return {"query": query, "matches": matches, "total_teams": library["record_count"],
            "matched_teams": len(matches), "snapshot_id": catalog.get("snapshot_id"),
            "probability_source": None, "population_statistics": False,
            "notice": "按已输入精灵同时包含匹配，仅检索用户提供的阵容码库；不是热门阵容或概率先验。错误阵容保留用于核对，不能直接导入。"}
