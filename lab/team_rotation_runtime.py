"""过山车 7070290: whole-team cross-member downward slot rotation.

Evidence (unpacked SKILL_CONF, snapshot 20261025T013619+0800):
- desc: "使己方队伍中的所有精灵携带的技能跨精灵向下移动1个位置，巧变：机械系技能。"
- skill_result: effect 1087001 (type 3 global effect, no params) + buff 21460180
  (type 3, add_max 1); buff base 2146018 params [18],[0],[0],[3,20],[-1]
  (op 18 team slot movement; [3,20] = 3 members / down direction code 20).
- energy_cost [8], Skill_Type 2 (status), skill_dam_type 19 (机械系).

Mechanic: flatten the side's team members in order, each with 4 skill slots;
rotate every skill one position "down" (toward higher slot index), crossing
member boundaries, wrapping from the last slot to the first.

Uncalibrated / experimental parts (documented, not fabricated):
- per-slot skill-history rows are keyed by (member, slot), so a skill crossing
  members loses its per-slot history tracking; the rotation moves the skill
  itself and preserves slot-level tags, and this limitation is recorded.
- position locks block the rotation (an unknown collision rule, mirroring the
  existing slot_runtime policy).
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data/rules/reviewed-team-rotation-1.json"
POLICY = "source_bound_team_down_rotation_experiment_v1"
UNCERTAINTIES = (
    "Cross-member skill movement does not migrate per-slot skill-history rows "
    "(rows are keyed by member+slot); position locks block the rotation; the "
    "buff 21460180 is treated as a trigger marker and is not separately applied.",
)


def deepcopy(value):
    import copy
    return copy.deepcopy(value)


def _configuration(stamp):
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if data.get("schema") != "reviewed-team-rotation-1":
        raise ValueError("Team rotation configuration schema mismatch")
    return data


def _data():
    return _configuration(CONFIG.stat().st_mtime_ns)


def fingerprint(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def research_context():
    return {"team_rotation": {"policy": POLICY}}


def validate_member(member):
    slots = member.get("skill_slots")
    if slots is not None and (not isinstance(slots, list) or len(slots) != 4):
        raise ValueError("Team rotation requires four reviewed skill slots per member")
    return True


def _locked_ids():
    from lab.slot_runtime import locked_skill_ids
    return locked_skill_ids()


def rotate_team_down(members, *, event_token):
    """Rotate every skill one position down across the flattened team; return events."""
    flat = []
    for index, member in enumerate(members):
        slots = list(member.get("skill_slots") or [])
        if len(slots) != 4:
            raise ValueError("Team rotation requires four reviewed skill slots per member")
        flat.append((index, member, slots))
    count = len(flat) * 4
    locked = _locked_ids()
    old = [slots for _, _, slots in flat]
    if any(sid in locked for row in old for sid in row if sid):
        return [{"op": "team_rotation.blocked", "reason": "position_locked_skill",
                 "policy": "never_move_locked_indices_unknown_collision_blocks",
                 "event_token": event_token}]
    order = [slots[col] for _, _, slots in flat for col in range(4)]
    rotated = order[-1:] + order[:-1]  # each skill moves one slot down; last wraps to first
    events = []
    for index, (member, _slots) in enumerate([(m, s) for _, m, s in flat]):
        new_slots = rotated[index * 4:(index + 1) * 4]
        member["skill_slots"] = new_slots
        events.append({"op": "team_rotation.rotate", "member_index": index,
                       "before": _slots, "after": new_slots, "event_token": event_token,
                       "policy": POLICY})
    return events


def preflight(program, state, context, damage_resolver=None):
    """Relative-dispatch preflight. Locked-skill checks happen battle-level
    (preflight_battle); a relative fragment without team context is applied."""
    if "teams" not in state:
        return {"status": "applied"}
    from lab.slot_runtime import locked_skill_ids
    locked = locked_skill_ids()
    team = state["teams"]
    members = team["self"]["members"] if "self" in team else None
    if members is None:
        return {"status": "applied"}
    for member in members:
        if any(sid in locked for sid in (member.get("skill_slots") or []) if sid):
            return {"status": "blocked", "blockers": ["position_locked_skill"]}
    return {"status": "applied"}


def preflight_battle(prepared, current, side, program, context=None):
    from lab.slot_runtime import locked_skill_ids
    locked = locked_skill_ids()
    for member in current["teams"][side]["members"]:
        if any(sid in locked for sid in (member.get("skill_slots") or []) if sid):
            return {"status": "blocked", "blockers": ["position_locked_skill"]}
    return {"status": "applied"}


def _battle_members(state, context):
    """Resolve the side's member list: battle state via context, else unit shape."""
    battle = context.get("battle_state") if context else None
    if battle is not None:
        side = context.get("battle_side", "a")
        return battle["teams"][side]["members"], battle, side
    team = state.get("teams")
    if team is not None and "self" in team:
        return team["self"]["members"], state, None
    raise ValueError("Team rotation needs battle_state in context or a unit-shaped state")


def execute(program, state, context, damage_resolver=None):
    owned = deepcopy(state)
    actor = owned["self"]
    cost = context["resolved_energy_cost"]
    actor["energy"] -= cost
    events = [{"op": "energy.pay", "target": "self", "amount": cost}]
    from lab.slot_runtime import locked_skill_ids
    locked = locked_skill_ids()
    members, battle, side = _battle_members(state, context)
    if any(sid in locked for member in members for sid in (member.get("skill_slots") or []) if sid):
        return {"status": "blocked", "state": owned, "events": events,
                "blockers": ["position_locked_skill"]}
    token = f"{owned.get('turn')}:{context.get('selected_skill_slot')}:team_rotation"
    events.extend(rotate_team_down(members, event_token=token))
    if battle is not None:
        active_slot = battle["teams"][side]["active_slot"]
        owned["self"]["skill_slots"] = deepcopy(members[active_slot]["skill_slots"])
    return {"status": "applied", "state": owned, "events": events,
            "training_eligible": False, "calibrated": False}


def programs(prepared):
    data = _data()
    out = {}
    for mid in sorted(data["skills"]):
        spec = data["skills"][mid]
        record = prepared._rules._catalog["moves"][mid]
        program = deepcopy(prepared._rules.program(int(mid)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], team_rotation_components=deepcopy(spec),
                       team_rotation_policy=POLICY, operations=[{"op": "team_rotation.plan", "params": {}}])
        out[int(mid)] = program
    return out
