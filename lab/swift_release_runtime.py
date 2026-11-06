"""疾风涡轮 7150170 + 疾风连袭 7150320: wing-charge auto release and swift re-release.

Evidence (unpacked SKILL_CONF / BUFF_CONF / BUFFBASE_CONF, snapshot 20261025T013619+0800):
- 7150170 疾风涡轮: desc "造成物伤，无法主动使用，在使用3次翼系技能后会自动使用此技能。"
  energy_cost [0], dam_para [100], skill_dam_type 15 (翼系), describe_type [5].
  Buff 20060110 (add_max 1) base 2006010 params [4],[1],[2006010],[7150170]
  (charge counter / increment / self buff / auto skill id).
- 7150320 疾风连袭: desc "释放自己释放过的迅捷技能，其能耗之和的二分之一加至本技能能耗，每次使用后能耗+1。"
  energy_rule 6, energy_cost [0,0,1,-5000]; buff 20640870 base 2064087 params
  [7],[7150320],[2],[1],[1],[6],[0],[0]; second effect 1033003 (type 1, params [0],[2]).
- Swift skills (迅捷, desc_id 1005) in catalog: 7150080 翼击, 7150110 龙卷风, 7150150 风墙,
  7150260 飞羽, 7150300 羽化加速, 7150320 疾风连袭, 7150400 月影交错, 7150410 惊鸿一瞥.

Mechanics implemented:
- Wing counter: after each 翼系 skill the side releases, increment; at 3, queue 7150170
  for auto release (cost 0), reset counter (rechargeable).
- 7150320: on active use, queue a re-release of every swift skill the owner has released
  this battle; cost = floor(sum(energy of released swift skills) / 2) + 1 * prior uses.
- Auto / re releases are drained by the caller (research_phases) after the turn's main loop
  through the normal attack execution path.

Experimental / uncalibrated: the charge threshold (3) and the /2 rounding are read from the
desc and energy_rule 6; the buff-base param [4] suggests a different internal counter value
that is not decoded field by field.
"""
import hashlib
import json
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data/rules/reviewed-swift-release-1.json"
POLICY = "source_bound_wing_charge_and_swift_rerelease_experiment_v1"
UNCERTAINTIES = (
    "Charge threshold taken from desc (3 翼系技能); buff base 2006010 param[0]=4 is not "
    "field-decoded. 7150320 cost rounding floor(sum/2) per energy_rule 6 reading; the -5000 "
    "sentinel in energy_cost is not decoded.",
)


def deepcopy(value):
    import copy
    return copy.deepcopy(value)


def _configuration(stamp):
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if data.get("schema") != "reviewed-swift-release-1":
        raise ValueError("Swift release configuration schema mismatch")
    return data


def _data():
    return _configuration(CONFIG.stat().st_mtime_ns)


def fingerprint(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def research_context():
    return {"swift_release": {"policy": POLICY}}


def _runtime(member):
    runtime = member.setdefault("swift_runtime", {"wing_uses": 0, "swift_released": [], "swift_uses": 0})
    runtime.setdefault("wing_uses", 0)
    runtime.setdefault("swift_released", [])
    runtime.setdefault("swift_uses", 0)
    return runtime


def validate_member(member):
    runtime = member.get("swift_runtime")
    if runtime is None:
        return True
    if not isinstance(runtime, dict) or type(runtime.get("wing_uses")) is not int or runtime["wing_uses"] < 0:
        raise ValueError("Swift runtime wing counter invalid")
    if not isinstance(runtime.get("swift_released"), list) or not all(
            isinstance(x, int) for x in runtime["swift_released"]):
        raise ValueError("Swift released list invalid")
    if type(runtime.get("swift_uses")) is not int or runtime["swift_uses"] < 0:
        raise ValueError("Swift uses counter invalid")
    return True


def is_wing_type(prepared, skill_id):
    skill = prepared._rules.skill(skill_id)
    return skill.get("type") == "翼系"


def swift_skill_ids(prepared):
    return [int(k) for k, v in _data()["swift_skills"].items() if v.get("is_swift")]


def observe_after_skill(owned, side, skill_id, *, prepared, turn):
    """Post-skill bookkeeping: wing charge + swift release record. Return events + queued flag."""
    actor = owned["teams"][side]["members"][owned["teams"][side]["active_slot"]]
    runtime = _runtime(actor)
    events = []
    queued = []
    if is_wing_type(prepared, skill_id):
        runtime["wing_uses"] += 1
        events.append({"op": "swift.wing_count", "wing_uses": runtime["wing_uses"], "skill_id": skill_id,
                       "policy": POLICY})
        threshold = _data()["skills"]["7150170"]["wing_threshold"]
        if runtime["wing_uses"] >= threshold:
            runtime["wing_uses"] = 0
            queued.append(7150170)
            events.append({"op": "swift.auto_queued", "skill_id": 7150170, "policy": POLICY})
    if skill_id in swift_skill_ids(prepared) and skill_id not in runtime["swift_released"]:
        runtime["swift_released"].append(skill_id)
        events.append({"op": "swift.released_recorded", "skill_id": skill_id, "policy": POLICY})
    return events, queued


def pending_queue(state, side):
    return state.setdefault("swift_pending", {}).setdefault(side, [])


def swift_release_cost(owned, side, *, prepared, turn):
    """疾风连袭 cost: floor(sum of released swift skill costs / 2) + 1 per prior use."""
    actor = owned["teams"][side]["members"][owned["teams"][side]["active_slot"]]
    runtime = _runtime(actor)
    swift_costs = _data()["swift_skills"]
    total = 0
    for sid in runtime["swift_released"]:
        spec = swift_costs.get(str(sid))
        cost = spec.get("energy_cost") if spec else None
        if isinstance(cost, list) and cost and type(cost[0]) is int:
            total += cost[0]
        elif isinstance(cost, int):
            total += cost
    half = total // 2
    return half + runtime["swift_uses"]


def preflight(program, state, context, damage_resolver=None):
    mid = program["game_id"]
    if mid == 7150170:
        if context.get("swift_auto_release") is True:
            return {"status": "applied"}
        return {"status": "blocked", "blockers": ["cannot_be_actively_used"]}
    return {"status": "applied"}


def execute(program, state, context, damage_resolver=None):
    mid = program["game_id"]
    owned = deepcopy(state)
    actor = owned["self"]
    events = []
    if mid == 7150170:
        if context.get("swift_auto_release") is not True:
            return {"status": "blocked", "state": owned, "events": events,
                    "blockers": ["cannot_be_actively_used"]}
        # Auto release: a free physical wing attack with the skill's table power.
        from lab.skill_execution import execute_skill
        spec = _data()["skills"]["7150170"]
        raw = spec.get("raw", {})
        program = deepcopy(program)
        program["operations"] = [{"op": "damage", "params": {
            "target": "opponent", "kind": "physical", "power": 100,
            "type": raw.get("type", "翼系")}}]
        return execute_skill(program, owned, context, damage_resolver=damage_resolver)
    if mid == 7150320:
        cost = context.get("swift_release_cost")
        if cost is None:
            raise ValueError("Swift re-release requires a caller-resolved swift_release_cost")
        actor["energy"] -= cost
        events.append({"op": "energy.pay", "target": "self", "amount": cost,
                       "source": "swift_rerelease_cost"})
        runtime = _runtime(actor)
        runtime["swift_uses"] += 1
        for sid in list(runtime["swift_released"]):
            if sid == 7150320:
                continue
            pending_queue(owned, "self").append({"skill_id": sid, "kind": "swift_rerelease"})
            events.append({"op": "swift.rerelease_queued", "skill_id": sid, "policy": POLICY})
        return {"status": "applied", "state": owned, "events": events,
                "training_eligible": False, "calibrated": False}
    raise ValueError("Swift release runtime does not own this skill")


def programs(prepared):
    data = _data()
    out = {}
    for mid in sorted(data["skills"]):
        spec = data["skills"][mid]
        record = prepared._rules._catalog["moves"][mid]
        program = deepcopy(prepared._rules.program(int(mid)))
        program.pop("native_rule", None)
        program.update(status="compiled", blockers=[], swift_release_components=deepcopy(spec),
                       swift_release_policy=POLICY, operations=[{"op": "swift_release.plan", "params": {}}])
        out[int(mid)] = program
    return out
