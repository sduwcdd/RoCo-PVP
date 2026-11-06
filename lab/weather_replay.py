"""Read-only weather projection from recorded actions, sharing simulation rules."""
from copy import deepcopy
import re

from lab.weather_rules import get_weather_rules
from lab.weather_runtime import (POLICY, NUMERIC_POLICY, advance_weather,
                                 is_weather_skill, apply_weather_skill, on_departure)

SIDES = {"my": "a", "opponent": "b"}


def replay_weather_records(catalog, session):
    if not isinstance(session, dict):
        raise ValueError("天气推演需要对战记录")
    if session.get("snapshot_id") != catalog["snapshot_id"]:
        raise ValueError("对战记录与当前图鉴快照不一致")
    rules = get_weather_rules(catalog)
    forms = {str(f["id"]): f for f in catalog["forms"]}
    moves = {str(m["id"]): m for m in catalog["moves"].values()}
    uncertainty = list(rules.get("uncertainties", []))
    rounds = session.get("rounds", [])
    if not isinstance(rounds, list) or len(rounds) > 2000:
        raise ValueError("回合记录必须为列表，最多2000回合")
    shadows, active, frames, seen = {}, {}, [], set()
    weather, previous = None, 0

    def read_teams(raw):
        if not isinstance(raw, dict):
            raise ValueError("缺少双方阵容")
        result, ids = {}, set()
        for side in SIDES:
            records = raw.get(side, [])
            if not isinstance(records, list) or len(records) > 6:
                raise ValueError("每方最多六只精灵")
            result[side] = {}
            for member in records:
                if not isinstance(member, dict):
                    raise ValueError("精灵配置必须为对象")
                mid = member.get("member_id")
                if not isinstance(mid, str) or not mid or len(mid) > 200 or mid in ids:
                    raise ValueError("精灵记录标识无效或重复")
                form = forms.get(str(member.get("form_id")))
                if form is None:
                    raise ValueError("精灵形态无法匹配：" + str(member.get("form_id")))
                ids.add(mid)
                result[side][mid] = {"member_id": mid, "name": form["name"]["zh"],
                    "types": list(form["types"]), "form_id": form["id"],
                    "weather_trait_id": form.get("trait_id"),
                    "base_speed": form["stats"]["spd"], "config": member}
        return result

    current_teams = read_teams(session.get("teams"))

    def member_state(member):
        result = {k: deepcopy(v) for k, v in member.items() if k not in ("config", "base_speed")}
        result.update(deepcopy(shadows.get(member["member_id"], {})))
        return result

    def affected(current, members):
        out = []
        for side, member in members.items():
            texts = []
            if member.get("hp_percent") == 0:
                texts.append("已倒下，不再结算天气效果")
            elif current:
                spec = rules["weather"][current["kind"]]
                texts.append(spec["description"])
                for effect in spec.get("effects", []):
                    if set(effect.get("when", {}).get("exclude_target_types", [])) & set(member["types"]):
                        texts.append("该精灵属性免疫此天气附加的状态")
                for effect in rules.get("trait_modifiers", {}).get(str(member.get("weather_trait_id")), []):
                    when = effect.get("when", {})
                    if when.get("weather") == current["kind"] or current["kind"] in when.get("weather_or_environment", []):
                        description = effect.get("source", {}).get("description")
                        if description:
                            texts.append("特性：" + re.sub(r"<[^>]*>", "", description))
            for status, count in member.get("weather_statuses", {}).items():
                if count:
                    texts.append("预计" + {"freeze": "冻结", "conductive": "引电"}[status] + f" {count} 层（以实战为准）")
            out.append({"side": side, "name": member["name"], "member_id": member["member_id"],
                        "effects": texts, "weather_statuses": member.get("weather_statuses", {})})
        return out

    for index, record in enumerate(rounds):
        if not isinstance(record, dict):
            raise ValueError("回合记录无效")
        turn, eid = record.get("turn"), record.get("event_id")
        if type(turn) is not int or turn != previous + 1:
            raise ValueError("天气推演需要从第1回合开始的连续记录")
        if not isinstance(eid, str) or not eid or eid in seen:
            raise ValueError("回合标识无效或重复")
        if record.get("snapshot_id", catalog["snapshot_id"]) != catalog["snapshot_id"]:
            raise ValueError("历史回合的图鉴快照不同")
        seen.add(eid)
        previous = turn
        teams = read_teams(record.get("teams_snapshot", session["teams"]))
        if "teams_snapshot" not in record:
            uncertainty.append(f"第{turn}回合缺少当时阵容快照，使用当前配置重建")
        if index == 0 and (record.get("opening_full_hp") or session.get("opening_full_hp")):
            for team in teams.values():
                for mid in team:
                    shadows[mid] = {"hp_percent": 100}
        before, events, actors, actions = deepcopy(weather), [], {}, {}
        for side, internal in SIDES.items():
            action = record.get(side, {})
            if not isinstance(action, dict):
                raise ValueError("回合行动必须为对象")
            actions[side] = action
            if action.get("kind") in (None, "unknown"):
                note = "存在未记录的实际行动；天气仅由已知行动重建，未知行动造成的天气变化尚不能还原"
                if note not in uncertainty:
                    uncertainty.append(note)
            mid = action.get("member_id") or active.get(side)
            if mid and mid not in teams[side]:
                raise ValueError(f"第{turn}回合{side}行动精灵不在阵容中")
            if mid:
                actors[side] = teams[side][mid]
            if action.get("kind") == "switch":
                if side in actors:
                    departing = member_state(actors[side])
                    events.extend(on_departure(departing, internal))
                    shadows.setdefault(departing["member_id"], {})["weather_statuses"] = departing.get("weather_statuses", {})
                mid = action.get("target_member_id")
                if mid not in teams[side]:
                    raise ValueError("换人目标不在该方阵容中")
            if mid:
                active[side] = mid
            observed = action.get("hp_observed_member_id") or mid
            hp = action.get("remaining_hp_percent")
            if side == "my" and action.get("remaining_hp_exact") is not None:
                remaining, maximum = action["remaining_hp_exact"], action.get("max_hp_exact")
                if type(remaining) is not int or type(maximum) is not int or maximum < 1 or not 0 <= remaining <= maximum:
                    raise ValueError("我方精确血量必须同时包含有效的剩余值和总值")
                hp = 0 if remaining == 0 else max(1, (remaining * 100 + maximum - 1) // maximum)
            if hp is not None:
                if type(hp) is not int or not 0 <= hp <= 100 or observed not in teams[side]:
                    raise ValueError("血量观测必须绑定己方成员且为0–100整数")
                shadows.setdefault(observed, {})["hp_percent"] = hp
            elif action.get("received_damage"):
                shadows.setdefault(observed, {}).pop("hp_percent", None)
        setters = [s for s in SIDES if actions[s].get("kind") == "move"
                   and is_weather_skill(actions[s].get("move_id"))]
        order = record.get("action_order")
        if order is not None:
            if order not in (["my", "opponent"], ["opponent", "my"], ["a", "b"], ["b", "a"]):
                raise ValueError("行动顺序必须包含双方各一次")
            order = [{"a": "my", "b": "opponent"}.get(s, s) for s in order]
            order_policy = "recorded_action_order"
        else:
            order = sorted(SIDES, key=lambda s: (
                -moves.get(str(actions[s].get("move_id")), {}).get("priority", 0),
                -actors.get(s, {}).get("base_speed", 0), list(SIDES).index(s)))
            order_policy = "base_speed_my_tie_fallback"
            if len(setters) > 1:
                uncertainty.append(f"第{turn}回合双方同时开启天气但未记录顺序，暂按图鉴基础速度、同速我方先动推演；覆盖结果待核实")
        for side in order:
            action = actions[side]
            if action.get("kind") == "move" and action.get("move_id") is not None:
                if str(action["move_id"]) not in moves:
                    raise ValueError("未知技能：" + str(action["move_id"]))
                if side not in actors:
                    raise ValueError("技能缺少施放者")
                weather, emitted = apply_weather_skill(weather, action["move_id"], turn,
                    response_success=action.get("response_success") is True)
                events.extend({**e, "source_side": SIDES[side]} for e in emitted)
        members = {SIDES[s]: member_state(teams[s][mid]) for s, mid in active.items() if mid in teams[s]}
        weather, members, emitted = advance_weather(weather, members, turn, apply_effects=False)
        events.extend(emitted)
        for member in members.values():
            shadows.setdefault(member["member_id"], {})["weather_statuses"] = member.get("weather_statuses", {})
        frames.append({"event_id": eid, "turn": turn, "before": before, "after": deepcopy(weather),
                       "events": events, "affected": affected(weather, members), "order_policy": order_policy})
    for side in SIDES:
        draft_mid = session.get("draft", {}).get(side, {}).get("active_member_id")
        if draft_mid in current_teams[side]:
            active[side] = draft_mid
    members = {SIDES[s]: member_state(current_teams[s][mid]) for s, mid in active.items() if mid in current_teams[s]}
    return {"current": weather, "frames": frames, "affected": affected(weather, members),
            "rules_version": rules["profile"], "lifecycle_policy": POLICY, "numeric_policy": NUMERIC_POLICY,
            "uncertainty": uncertainty, "training_eligible": False, "real_game_calibrated": False,
            "observation_policy": "Recorded skills drive weather; predicted effects never overwrite observed HP or energy"}
