"""Version 1 community team codes, decoded without treating them as Base64.

Protocol evidence is a user-verified Roco Showdown implementation, not an
official specification. BWIKI supplies names and learning evidence only.
This format does not contain full IVs, a level, or a verifiable data version.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
PROTOCOL_SOURCE = "https://roco-showdown.com/_next/static/chunks/2427-9b9809421a06aa9e.js"
PROTOCOL_SOURCE_SHA256 = "962014668381461fcab5b3c818fded43b0926cf0ac7c05e7f7df5bfc8ddf700c"
ATTRIBUTES = ("hp", "patk", "matk", "pdef", "mdef", "spd")
BLOODLINES = dict(enumerate(("未指定", "普通", "草", "火", "水", "光", "地", "冰", "龙", "电", "毒", "虫", "武", "翼", "萌", "幽", "恶", "机械", "幻", "首领")))
MODIFIERS = dict(enumerate((None, *ATTRIBUTES)))
TALENT_MARKERS = {0: None, **dict(zip(range(79, 85), ATTRIBUTES))}
CORE_NAMES = {104002: "愿力强化", 104007: "进化之力"}
NATURE_ORDER = ("patk", "pdef", "matk", "mdef", "spd", "hp")
NATURE_DIRECTIONS = {0: (None, None)}
for _i, _up in enumerate(NATURE_ORDER):
    for _j, _down in enumerate(x for x in NATURE_ORDER if x != _up):
        NATURE_DIRECTIONS[1 + 5 * _i + _j] = (_up, _down)


def decode_number(field: str, *, zero_compat: bool = False) -> int:
    """Decode one fixed-width integer; zero compatibility is opt-in only."""
    if not isinstance(field, str) or not field:
        raise ValueError("数字字段为空")
    if zero_compat and set(field) == {"0"}:
        return 0
    value = field.rstrip("~").replace("+", "-").replace("/", "_")
    if not value:
        raise ValueError("数字字段仅含填充符")
    if any(c not in ALPHABET for c in value):
        raise ValueError("数字字段含非法字符或内部填充符")
    if len(value) > 1 and value[0] == "A":
        raise ValueError("多字符数字存在多余前导 A")
    result = 0
    for char in value:
        result = result * 64 + ALPHABET.index(char)
    return result


def _records(value):
    return list(value.values()) if isinstance(value, dict) else list(value or [])


def _id(record):
    value = record.get("game_id", record.get("id"))
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _index(records):
    out = {}
    for record in _records(records):
        out.setdefault(_id(record), []).append(record)
    return out


def _name(record):
    name = record.get("title") or record.get("name")
    return name.get("zh") if isinstance(name, dict) else name


def parse_team_code(code, catalog):
    """Return evidence-bearing diagnostics; never repair or normalize the code.

    ``importable`` permits a research configuration, not a legal team verdict.
    Unknown IDs, duplicate moves and user-confirmed errors block import. All
    unresolved conditions block training, and full IVs are never invented.
    """
    result = {"raw_code": code, "protocol_version": None, "team_type_id": None,
              "core_magic": {"id": None, "name": None, "source": None},
              "snapshot_id": catalog.get("snapshot_id"),
              "source_version": catalog.get("source_version"),
              "protocol_source": {"url": PROTOCOL_SOURCE, "kind": "community_implementation",
                                  "official_protocol": False, "basis": "user_verified_rules",
                                  "sha256": PROTOCOL_SOURCE_SHA256,
                                  "archive": "data/reference/team-code-20261025/showdown-parser-source.js"},
              "members": [], "issues": [], "format_valid": False,
              "importable": False, "training_eligible": False}

    def issue(category, key, message, slot=None, field=None, raw=None, evidence=None):
        item = {"category": category, "code": key, "message": message,
                "member_slot": slot, "field": field, "raw_value": raw,
                "evidence": evidence or {"source": PROTOCOL_SOURCE}}
        result["issues"].append(item)
        return item

    def number(raw, field, slot=None, allowed=None, compat=False):
        try:
            val = decode_number(raw, zero_compat=compat)
        except ValueError as exc:
            issue("format_error", "invalid_number", str(exc), slot, field, raw)
            return None
        if allowed is not None and val not in allowed:
            issue("format_error", "field_out_of_range", "字段值不在已支持范围内", slot, field, val)
        return val

    if not isinstance(code, str):
        issue("format_error", "not_text", "阵容码必须为字符串", field="raw_code", raw=code)
        return result
    if len(code) < 3:
        issue("format_error", "invalid_length", "阵容码不足 3 字符", field="length", raw=len(code))
        return result
    result["protocol_version"] = number(code[:2], "version", allowed={1})
    count = number(code[2:3], "member_count", allowed=range(1, 7))
    result["member_count"] = count
    if count is None or count not in range(1, 7):
        return result
    if len(code) != 8 + 39 * count:
        issue("format_error", "invalid_length", f"{count} 只精灵的阵容码应为 {8 + 39 * count} 字符", field="length", raw=len(code))
        return result
    offset = 3 + 35 * count
    core_id = number(code[offset:offset+4], "core_magic", compat=True)
    result["core_magic"]["id"] = core_id
    result["team_type_id"] = number(code[offset+4:offset+5], "team_type", allowed=range(1, 12))
    result["raw_fields"] = {"version": code[:2], "count": code[2:3],
                            "core_magic": code[offset:offset+4], "team_type": code[offset+4:offset+5]}
    for n in range(count):
        slot = n + 1
        raw = code[3+35*n:3+35*(n+1)]
        tail = code[offset+5+4*n:offset+9+4*n]
        fields = {"form_id": raw[:5], "bloodline_id": raw[5:7], "nature_id": raw[7:9],
                  "talent_markers": [raw[9+2*j:11+2*j] for j in range(3)],
                  "moves": [raw[15+5*j:20+5*j] for j in range(4)],
                  "nature_modifiers": [tail[:2], tail[2:]]}
        member = {"slot": slot, "raw_record": raw, "raw_fields": fields,
                  "form_id": number(fields["form_id"], "form_id", slot),
                  "bloodline_id": number(fields["bloodline_id"], "bloodline_id", slot, range(20)),
                  "nature_id": number(fields["nature_id"], "nature_id", slot, range(31)),
                  "raw_talent_markers": [number(x, f"talent_markers[{j}]", slot, TALENT_MARKERS, True) for j,x in enumerate(fields["talent_markers"])],
                  "move_ids": [number(x, f"moves[{j}]", slot, compat=True) for j,x in enumerate(fields["moves"])],
                  "nature_modifiers": [number(x, f"nature_modifiers[{j}]", slot, range(7)) for j,x in enumerate(fields["nature_modifiers"])],
                  "talents": dict.fromkeys(ATTRIBUTES), "moves": [], "issues": [], "importable": False}
        result["members"].append(member)
    if any(x["category"] == "format_error" for x in result["issues"]):
        for m in result["members"]:
            m["issues"] = [x for x in result["issues"] if x["member_slot"] == m["slot"]]
        return result
    result["format_valid"] = True
    evidence = {"source": catalog.get("source_name", "BWIKI"), "snapshot_id": result["snapshot_id"], "source_version": result["source_version"]}
    issue("unverified", "code_version_unknown", "阵容码没有可核对的游戏资料版本，当前数据库冲突不能单独证明游戏中不合法。", field="data_version", evidence=evidence)
    issue("unverified", "team_type_meaning_unknown", "队伍类型编号的含义尚未确认，保留原值。", field="team_type_id", raw=result["team_type_id"])
    if core_id in CORE_NAMES:
        result["core_magic"].update(name=CORE_NAMES[core_id], source="user_verified_examples")
    elif core_id == 0:
        result["core_magic"].update(name="未指定", source="community_implementation")
    else:
        issue("unverified", "unknown_core_magic", "核心魔法没有可靠名称映射，保留原始 ID。", field="core_magic", raw=core_id)
    forms, moves = _index(catalog.get("forms")), _index(catalog.get("moves"))
    natures = _records(catalog.get("natures"))
    for m in result["members"]:
        slot, fid, bid, nid = m["slot"], m["form_id"], m["bloodline_id"], m["nature_id"]
        def mi(category, key, message, field=None, raw=None, ev=None):
            return issue(category, key, message, slot, field, raw, ev or evidence)
        fs = forms.get(fid, [])
        m.update(form_name=None, form=None, bloodline_name=BLOODLINES[bid])
        if bid == 0:
            mi("unverified", "bloodline_unspecified", "血脉未指定，涉及血脉的学习条件尚不能验证。", "bloodline_id", bid)
        if len(fs) != 1:
            mi("database_conflict", "unknown_form" if not fs else "ambiguous_form", "精灵游戏 ID 无法在当前图鉴唯一匹配；不会按图鉴编号或血脉替换形态。", "form_id", fid)
        else:
            form = fs[0]
            m["form_name"] = _name(form)
            m["form"] = {k: deepcopy(form[k]) for k in ("id", "game_id", "title", "name", "stage", "source_url") if k in form}
        up, down = NATURE_DIRECTIONS[nid]
        matches = [x for x in natures if x.get("up") == up and x.get("down") == down] if nid else []
        nature = {"original": {"id": nid, "bwiki_id": None, "name": None, "up": up, "down": down},
                  "modifiers": dict(zip(("up_id", "down_id"), m["nature_modifiers"])), "final": {}}
        if nid and len(matches) != 1:
            mi("database_conflict", "nature_mapping_conflict", "原性格方向不能唯一匹配 BWIKI 性格表，未采用旧页游名称。", "nature_id", nid)
        elif nid:
            nature["original"].update(bwiki_id=_id(matches[0]), name=_name(matches[0]))
        else:
            mi("unverified", "nature_unspecified", "原性格未指定。", "nature_id", nid)
        uid, did = m["nature_modifiers"]
        nature["final"] = {"up": MODIFIERS[uid] if uid else up, "down": MODIFIERS[did] if did else down}
        if nature["final"]["up"] and nature["final"]["up"] == nature["final"]["down"]:
            mi("database_conflict", "nature_direction_conflict", "最终性格增益与减益指向同一属性，游戏语义尚待核实。", "nature_modifiers", m["nature_modifiers"])
        if (uid or did) and (not nature["final"]["up"] or not nature["final"]["down"]):
            mi("unverified", "nature_direction_incomplete", "后天修正后仍有性格方向未指定。", "nature_modifiers", m["nature_modifiers"])
        m["nature"] = nature
        m["talent_marker_attributes"] = [TALENT_MARKERS[x] for x in m["raw_talent_markers"]]
        duplicates = [x for x, amount in Counter(m["raw_talent_markers"]).items() if x != 0 and amount > 1]
        if duplicates:
            mi("unverified", "duplicate_talent_markers", "重复个体加成标记，完整资质待核实", "raw_talent_markers", m["raw_talent_markers"])
        mi("unverified", "full_talents_unknown", "个体加成标记不能恢复完整六维资质；所有未提供的数值保持未知。", "talents", m["raw_talent_markers"])
        detail = catalog.get("details", {}).get(str(fid), catalog.get("details", {}).get(fid, {}))
        learnset = detail.get("learnset") if isinstance(detail, dict) else None
        for j, mid in enumerate(m["move_ids"]):
            move = {"slot": j+1, "id": mid, "name": None, "empty": mid == 0, "learning_sources": []}
            m["moves"].append(move)
            if mid == 0:
                continue
            if m["move_ids"].count(mid) > 1 and m["move_ids"].index(mid) == j:
                mi("database_conflict", "duplicate_moves", "四个技能槽存在重复技能，不会自动去重或重排。", "move_ids", m["move_ids"])
            ms = moves.get(mid, [])
            if len(ms) != 1:
                mi("database_conflict", "unknown_move" if not ms else "ambiguous_move", "技能 ID 无法在当前图鉴唯一匹配，原始槽位保留。", f"moves[{j}]", mid)
                continue
            move["name"] = _name(ms[0])
            if not learnset or len(fs) != 1:
                mi("unverified", "learnset_missing", "缺少该具体形态的可验证学习资料。", f"moves[{j}]", mid)
                continue
            paths = []
            for source in ("native", "legacy", "legendary"):
                for entry in learnset.get(source, []):
                    if str(entry.get("move")) == str(mid):
                        paths.append({"source": source, **deepcopy(entry)})
            for source in ("stones", "pool"):
                if mid in learnset.get(source, []):
                    # Generic membership never erases any explicit conditions.
                    if source != "pool" or not paths:
                        paths.append({"source": source, "move": mid})
            move["learning_sources"] = paths
            if not paths:
                mi("database_conflict", "outside_learnset", f"{m['form_name']}的当前 BWIKI 学习范围中没有该技能；需继续核对版本或特殊机制。", f"moves[{j}]", mid)
                continue
            viable = []
            for path in paths:
                reasons = []
                if path["source"] == "legacy" and path.get("bloodline") != BLOODLINES[bid]:
                    path["status"] = "unverified" if bid == 0 else "database_conflict"
                    reasons.append("血脉未指定" if bid == 0 else "所需血脉与码内血脉不符")
                elif path.get("stage") and fs[0].get("stage") and path["stage"] > fs[0]["stage"]:
                    path["status"] = "database_conflict"
                    reasons.append("学习阶段超过当前形态阶段")
                else:
                    path["status"] = "unverified"
                    viable.append(path)
                    if path.get("level"):
                        reasons.append("阵容码不含等级")
                    if path.get("stage") and not fs[0].get("stage"):
                        reasons.append("形态阶段未知")
                    if path["source"] == "legendary":
                        reasons.append("传说技能解锁条件未提供")
                    if not reasons:
                        reasons.append("可学记录不证明实际习得或特殊条件已满足")
                path["pending"] = reasons
            if not viable and all(p["status"] == "database_conflict" for p in paths):
                mi("database_conflict", "learning_condition_conflict", f"{m['form_name']}：当前 BWIKI 的所有学习来源均与码内条件冲突。", f"moves[{j}]", mid, {**evidence, "sources": paths, "bloodline_id": bid})
            else:
                mi("unverified", "learning_conditions_unverified", f"{m['form_name']}：有可学来源，但等级、解锁或学习条件尚不能完全验证。", f"moves[{j}]", mid, {**evidence, "sources": paths})
        if fid == 3080 and bid == 4 and m["move_ids"][2] == 7060200:
            mi("user_confirmed_error", "user_confirmed_huoyu_bloodline", "火羽：阵容码指定水血脉，却携带当前图鉴列为光血脉来源的虹光冲击；用户已确认该阵容码有误。", "moves[2]", {"form_id": fid, "bloodline_id": bid, "move_id": 7060200}, {"source": "user_confirmed_example", "bwiki_snapshot_id": result["snapshot_id"]})
        m["issues"] = [x for x in result["issues"] if x["member_slot"] == slot]
        blocking = {"unknown_form", "ambiguous_form", "unknown_move", "ambiguous_move", "nature_mapping_conflict", "duplicate_moves"}
        m["importable"] = not any(x["category"] == "user_confirmed_error" or x["code"] in blocking for x in m["issues"])
    result["importable"] = all(m["importable"] for m in result["members"])
    return result
