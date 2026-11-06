"""Source-bound core magic with user-confirmed wish/evolution/heal transitions.

Historical binary evidence stays intact; user-confirmed timing and inheritance
are separate from the remaining versioned rounding and token conditions.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.constants import CORE_MAGIC_ITEM_IDS


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / "data/rules/reviewed-core-magic-1.json"
REVIEWED_SHA256 = "9acea950b9f88e373d09be28c64394fe486de74f33584d96d05cf4b38547b3b2"
PROFILE = "installed_core_magic_evidence_only_v1"
SUBSET_PATH = ROOT / "data/rules/reviewed-core-magic-subset-1.json"
SUBSET_SHA256 = "c483fc40aef4db5e89e0e1c16d55860c16f0e4722359671619beaeabcba3c1fa"
POLICY = "water_heal_fire_before_joint_selection_literal_cd_experiment_v2"
ADDITIONS_PATH = ROOT / "data/rules/reviewed-core-magic-additions-1.json"
ADDITIONS_SHA256 = "85d29476597eb09d19d4fb4980b9a7abd6d181b0271a5d7b58b8b62c06a66bc4"
ADDITIONS_POLICY = "heal_fire_literal_description_max_hp_floor_cast_round_included_departure_cleans_heal_v1"
INDEX_PATH = ROOT / "data/rules/reviewed-core-magic-index-1.json"
INDEX_SHA256 = "5edfaaa39318be2e128290285f0e9fc92fd47747dfbf57069db6e0773247e4ff"
CONFIRMED_PATH = ROOT / "data/rules/reviewed-core-magic-user-confirmed-20261030.json"
CONFIRMED_SHA256 = "af97d3f217688728de7e83ab98417ed910cc94f861751b623d03956ba4fca806"
CONFIRMED_POLICY = "user_confirmed_active_optional_wish_tplus3_boss_hp_ratio_heal_three_endings_v1"


@lru_cache(maxsize=128)
def _sha(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _file_hash(path):
    stat = path.stat()
    return _sha(str(path), stat.st_size, stat.st_mtime_ns)


def load_core_magic_rules():
    """Return detached reviewed evidence, checking each extracted source file."""
    if _file_hash(RULES_PATH) != REVIEWED_SHA256:
        raise ValueError("Core-magic evidence differs from its reviewed revision")
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    if (rules.get("schema_version") != 1 or rules.get("profile") != PROFILE
            or rules.get("battle_executable") is not False
            or rules.get("training_eligible") is not False
            or rules.get("online_mount_verified") is not False):
        raise ValueError("Core-magic evidence must retain its non-executable installed-file scope")
    for source in rules["sources"]:
        path = (ROOT / source["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or _file_hash(path) != source["sha256"]:
            raise ValueError("Core-magic source changed: " + source["path"])
    for key, row in rules["records"].items():
        item, magic, skill = row["item_row"], row["player_magic_row"], row["skill_row"]
        if (str(item["id"]) != key or item["player_skill_id"] != magic["id"]
                or magic["skill_id"] != skill["id"] or row["executable"] is not False):
            raise ValueError("Core-magic item→player_magic→skill chain is inconsistent")
    return rules


def inspect_core_magic(item_id):
    """Resolve the exact installed item chain without inferring action defaults.

    Raw skill CD, PlayerMagicConf.round, inventory initialization and in-battle
    use limits remain separate fields. No universal trainer resource or online
    version is inferred from them.
    """
    if type(item_id) is not int:
        raise ValueError("Core-magic item ID must be an integer")
    if item_id in (104002, 104007):
        confirmed = load_confirmed_core_magic_rules()
        record = load_core_magic_rules()["records"][str(item_id)]
        return {"status": "supported_user_confirmed", "item_id": item_id,
                "name": record["name"], "player_magic_id": record["player_magic_row"]["id"],
                "skill_id": record["skill_row"]["id"], "source_record": deepcopy(record),
                "blockers": [], "executable": True, "battle_executable": False,
                "training_eligible": False, "online_mount_verified": False,
                "rules_sha256": CONFIRMED_SHA256, "source_scope": deepcopy(confirmed["confirmation"]),
                "required_policy": core_magic_policy()}
    if item_id in (104001, 104003):
        row = load_core_magic_additions()["records"][str(item_id)]
        return {"status": "supported_experiment", "item_id": item_id,
                "name": row["item_row"]["name"]["text"],
                "player_magic_id": row["player_magic_row"]["id"],
                "skill_id": row["skill_row"]["id"], "source_record": row, "blockers": [],
                "executable": True, "battle_executable": False, "training_eligible": False,
                "online_mount_verified": False, "rules_sha256": ADDITIONS_SHA256,
                "source_scope": load_core_magic_additions()["source_scope"], "required_policy": core_magic_policy()}
    if item_id == 104004:
        row = load_core_magic_subset()
        return {"status": "supported_experiment", "item_id": item_id,
                "name": row["item_row"]["name"]["text"], "player_magic_id": 100004,
                "skill_id": 7010040, "source_record": row, "blockers": [],
                "executable": True, "battle_executable": False, "training_eligible": False,
                "online_mount_verified": False, "rules_sha256": SUBSET_SHA256,
                "source_scope": row["source_scope"], "required_policy": core_magic_policy()}
    rules = load_core_magic_rules()
    if str(item_id) not in rules["records"]:
        indexed = load_core_magic_index()["records"].get(str(item_id))
        if indexed:
            return {"item_id": item_id, "status": "blocked", "executable": False,
                    "name": indexed["name"], "player_magic_id": indexed["player_magic_id"],
                    "skill_id": indexed["skill_id"], "source_record": deepcopy(indexed),
                    "rules_sha256": INDEX_SHA256, "source_scope": load_core_magic_index()["source_scope"],
                    "training_eligible": False, "battle_executable": False, "online_mount_verified": False,
                    "blockers": [{"code": "unadapted_magic_variant", "detail": text} for text in indexed["blockers"]]}
        return {"item_id": item_id, "status": "unsupported", "executable": False,
                "training_eligible": False, "online_mount_verified": False,
                "blockers": [{"code": "unreviewed_core_magic", "detail": "No reviewed core-magic chain exists for this item ID."}]}
    record = rules["records"][str(item_id)]
    return {"status": "blocked", "profile": PROFILE, "item_id": item_id,
            "name": record["name"], "player_magic_id": record["player_magic_row"]["id"],
            "skill_id": record["skill_row"]["id"], "source_record": deepcopy(record),
            "blockers": deepcopy(record["blockers"]), "executable": False,
            "battle_executable": False, "training_eligible": False,
            "online_mount_verified": False, "rules_sha256": REVIEWED_SHA256,
            "source_scope": rules["source_scope"]}


def execute_core_magic(state, action, context=None, *, catalog=None):
    """Execute opt-in reviewed magic, or atomically reject incomplete magic.

    The optional item selection precedes ordinary action selection under
    its experiment policy. Wish/evolution never partially spend or edit slots.
    """
    result = {"status": "blocked", "scope": "core_magic_evidence_gate",
              "state": deepcopy(state), "events": [], "blockers": [],
              "executable": False, "battle_executable": False,
              "full_turn_executed": False, "training_eligible": False,
              "calibrated": False, "real_game_verified": False}
    try:
        if not isinstance(action, dict) or action.get("kind") != "core_magic":
            raise ValueError("Expected an explicit core_magic action")
        if type(action.get("item_id")) is int and action["item_id"] in (104002, 104007):
            return _execute_confirmed_magic(state, action, context, catalog)
        if type(action.get("item_id")) is int and action["item_id"] in (104001, 104003):
            return _execute_addition_magic(state, action, context, catalog)
        if action.get("item_id") == 104004 and type(action.get("item_id")) is int:
            return _execute_water_magic(state, action, context, catalog)
        info = inspect_core_magic(action.get("item_id"))
        result.update(item_id=info["item_id"], mechanism_blockers=deepcopy(info["blockers"]))
        result["blockers"] = [item["code"] + ": " + item["detail"] for item in info["blockers"]]
        if info.get("skill_id"):
            result["skill_id"] = info["skill_id"]
            result["source_scope"] = info["source_scope"]
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result


def load_core_magic_subset():
    """Verify full water-magic source chain; return a detached small bundle."""
    if _file_hash(SUBSET_PATH) != SUBSET_SHA256:
        raise ValueError("Water-magic reviewed evidence changed")
    rules = json.loads(SUBSET_PATH.read_text(encoding="utf-8"))
    for source in rules["sources"]:
        path = (ROOT / source["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or _file_hash(path) != source["sha256"]:
            raise ValueError("Water-magic source changed: " + source["path"])
    return rules


def core_magic_policy():
    """The caller must select this full policy explicitly; none is a game fact."""
    return {"version": POLICY, "selection": "one_optional_item_before_joint_skill_selection",
            "target": "living_active_ally_water_or_fire_type_only_bloodline_route_blocked_heal_any_form",
            "cleanup": "cast_moment_6_then_10_remove_exact_20990010_20990020",
            "cost": "zero_all_skill_energy_payment_for_target_this_turn",
            "duration": "through_current_round_end_no_early_consumption",
            "inventory": "fresh_initial_use_times_decrement_each_committed_cast",
            "use_limit": "battle_item_use_time_in_battle_separate_counter",
            "cooldown": "next_ready_turn_equals_cast_turn_plus_skill_cd_first_operand",
            "runtime_version_verified": False,
            "heal_fire": ADDITIONS_POLICY,
            "heal_rounding": "floor_15_percent_current_max_hp_clip_missing_no_revive",
            "heal_duration": "cast_round_end_plus_next_two_endings_departure_cleans",
            "user_confirmation": CONFIRMED_POLICY,
            "fire_power": "base_power_times_5_over_2_all_attack_hits_no_early_consumption"}


def _int(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(label + " must be an integer >= " + str(minimum))
    return value


def _roster(state):
    _int(state.get("turn"), "turn", 1)
    if not isinstance(state.get("teams"), dict) or set(state["teams"]) != {"a", "b"}:
        raise ValueError("Water magic requires both explicit teams")
    result, ids = {}, set()
    for side, team in state["teams"].items():
        members = team.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError("Water magic requires a nonempty roster")
        slot = _int(team.get("active_slot"), "active slot")
        if slot >= len(members):
            raise ValueError("Water-magic active slot is outside the roster")
        for member in members:
            mid = member.get("member_id")
            if not isinstance(mid, str) or not mid or mid in ids:
                raise ValueError("Water magic requires globally unique member IDs")
            ids.add(mid)
            _int(member.get("hp"), "member HP")
            if member.get("buffs"):
                raise ValueError("Unadapted generic buffs cannot be omitted from magic cleanup")
        result[side] = members[slot]
    return result


def initialize_core_magic(state, *, policy):
    """Mutate a fresh turn-1 state atomically; never reset a spent ledger.

    Each team chooses a reviewed core_magic.id or None. Mid-battle imports must
    carry their complete existing ledger. Wish/evolution are not normalized
    into water magic. No trainer magic or member energy is used as inventory.
    """
    if policy != core_magic_policy():
        raise ValueError("Explicit complete water-magic research policy is required")
    if "core_magic_runtime" in state:
        validate_core_magic(state)
        return state
    _roster(state)
    if state["turn"] != 1:
        raise ValueError("Cannot invent initial core-magic counters for a mid-battle import")
    rules = load_core_magic_subset()
    load_core_magic_additions()
    players = {}
    for side, team in state["teams"].items():
        item = team.get("core_magic", {}).get("id")
        if item is not None and (type(item) is not int or item not in CORE_MAGIC_ITEM_IDS):
            raise ValueError("Only reviewed magic or an explicit empty selection can be enabled")
        if item == 104004:
            players[side] = {"item_id": item, "inventory_remaining": rules["item_row"]["initial_use_times"],
                             "battle_uses_remaining": rules["battle_item_row"]["use_time_in_battle"],
                             "next_ready_turn": 1, "casts": []}
    state["core_magic_runtime"] = {"policy": deepcopy(policy), "rules_sha256": SUBSET_SHA256,
                                    "players": players, "effects": [], "closed_turn": 0,
                                    "selections": {side: team.get("core_magic", {}).get("id") for side, team in state["teams"].items()},
                                    "roster": {side: [m["member_id"] for m in team["members"]]
                                               for side, team in state["teams"].items()}}
    _initialize_additions(state)
    _initialize_confirmed(state)
    return state


def validate_core_magic(state):
    """Validate counters, immutable selection, roster and target-bound origins."""
    active = _roster(state)
    root = state["core_magic_runtime"]
    rules = load_core_magic_subset()
    if (not isinstance(root, dict) or root.get("policy") != core_magic_policy()
            or root.get("rules_sha256") != SUBSET_SHA256):
        raise ValueError("Core-magic ledger does not match its reviewed policy/source")
    closed = _int(root.get("closed_turn"), "closed magic round")
    if closed not in (state["turn"] - 1, state["turn"]):
        raise ValueError("Core-magic lifecycle skipped a round")
    roster = {side: [m["member_id"] for m in team["members"]] for side, team in state["teams"].items()}
    if root.get("roster") != roster:
        raise ValueError("Core-magic roster changed")
    expected_sides = {side for side, team in state["teams"].items() if team.get("core_magic", {}).get("id") == 104004}
    selections = {side: team.get("core_magic", {}).get("id") for side, team in state["teams"].items()}
    if root.get("selections") != selections or any(value is not None and
            (type(value) is not int or value not in (104001, 104002, 104003, 104004, 104007)) for value in selections.values()):
        raise ValueError("Core-magic selection changed to an unadapted item")
    if not isinstance(root.get("players"), dict) or set(root["players"]) != expected_sides:
        raise ValueError("Core-magic selection changed")
    for side, ledger in root["players"].items():
        casts = ledger.get("casts")
        if ledger.get("item_id") != 104004 or not isinstance(casts, list):
            raise ValueError("Invalid core-magic cast ledger")
        last = 0
        for cast in casts:
            turn = _int(cast.get("turn"), "cast turn", 1)
            if (cast.get("target_member_id") not in roster[side] or turn > state["turn"]
                    or (last and turn < last + rules["skill_row"]["cd_round"][0])):
                raise ValueError("Core-magic cast history violates target/cooldown")
            last = turn
        expected = {"inventory_remaining": rules["item_row"]["initial_use_times"] - len(casts),
                    "battle_uses_remaining": rules["battle_item_row"]["use_time_in_battle"] - len(casts),
                    "next_ready_turn": last + rules["skill_row"]["cd_round"][0] if last else 1}
        for key, value in expected.items():
            if _int(ledger.get(key), key) != value:
                raise ValueError("Core-magic counters disagree with committed history")
    effects = root.get("effects")
    if not isinstance(effects, list):
        raise ValueError("Core-magic effects must be an explicit list")
    seen = set()
    for effect in effects:
        side = effect.get("side")
        if (side not in root["players"] or side in seen or effect.get("buff_id") != 20320320
                or effect.get("base_id") != 2032032 or effect.get("item_id") != 104004
                or effect.get("rules_sha256") != SUBSET_SHA256
                or effect.get("turn") != state["turn"] or closed == state["turn"]
                or effect.get("target_member_id") not in roster[side]
                or not root["players"][side]["casts"]
                or root["players"][side]["casts"][-1] != {"turn": effect["turn"], "target_member_id": effect["target_member_id"]}):
            raise ValueError("Stale, rebound or unverified water-magic effect")
        seen.add(side)
    expected_effects = {side for side, ledger in root["players"].items()
                        if closed != state["turn"] and ledger["casts"] and ledger["casts"][-1]["turn"] == state["turn"]}
    if seen != expected_effects:
        raise ValueError("A committed current-round core-magic effect is missing")
    _validate_additions(state)
    _validate_confirmed(state)
    return active


def _execute_water_magic(state, action, context, catalog):
    result = {"status": "blocked", "scope": "core_magic_subset_experiment", "state": deepcopy(state),
              "events": [], "blockers": [], "executable": False, "battle_executable": False,
              "full_turn_executed": False, "training_eligible": False, "calibrated": False,
              "real_game_verified": False, "online_mount_verified": False}
    try:
        if not isinstance(context, dict) or context.get("policy") != core_magic_policy():
            raise ValueError("Water magic needs its explicit complete experiment policy")
        if set(action) != {"kind", "item_id", "side", "target_slot"} or action.get("side") not in ("a", "b"):
            raise ValueError("Water magic requires kind,item_id,side,target_slot exactly")
        current = deepcopy(state)
        active = validate_core_magic(current)
        side, slot = action["side"], _int(action["target_slot"], "target slot")
        root, team = current["core_magic_runtime"], current["teams"][side]
        if slot != team["active_slot"] or active[side]["hp"] <= 0:
            raise ValueError("Water magic targets a living active ally only")
        if root["closed_turn"] == current["turn"]:
            raise ValueError("Core-magic selection is already closed for this round")
        ledger = root["players"].get(side)
        if not ledger or not ledger["inventory_remaining"] or not ledger["battle_uses_remaining"]:
            raise ValueError("Selected core magic has no remaining inventory/battle uses")
        if current["turn"] < ledger["next_ready_turn"]:
            raise ValueError("Selected core magic is cooling down")
        target = active[side]
        # A type-only route is complete; bloodline eligibility needs its own verified adapter.
        from lab.prepared_rules import prepare_rules
        prepared = prepare_rules(catalog)
        if current.get("snapshot_id") != prepared.snapshot_id:
            raise ValueError("Water-magic target must bind the battle catalog snapshot")
        types = prepared._rules.form(target["form_id"])["types"]
        if "types" in target and target["types"] != types:
            raise ValueError("Target types conflict with the exact bound form")
        if "水系" not in types:
            raise ValueError("Target lacks verified water type; water-bloodline-only eligibility remains blocked")
        states = target.get("magic_target_states")
        if states != {"drill": False, "static": False, "mimic": False}:
            raise ValueError("Explicit absent drill/static/mimic target states are required")
        rules = load_core_magic_subset()
        cleanup = [effect for effect in root["effects"] if effect["side"] == side
                   and effect["target_member_id"] == target["member_id"] and effect["buff_id"] in (20990010, 20990020)]
        root["effects"] = [effect for effect in root["effects"] if effect not in cleanup]
        ledger["inventory_remaining"] -= 1
        ledger["battle_uses_remaining"] -= 1
        ledger["next_ready_turn"] = current["turn"] + rules["skill_row"]["cd_round"][0]
        ledger["casts"].append({"turn": current["turn"], "target_member_id": target["member_id"]})
        effect = {"side": side, "target_member_id": target["member_id"], "turn": current["turn"],
                  "item_id": 104004, "buff_id": 20320320, "base_id": 2032032, "rules_sha256": SUBSET_SHA256}
        root["effects"].append(effect)
        validate_core_magic(current)
        result.update(status="applied", state=current, executable=True,
                      events=[{"op": "core_magic.cleanup", "effect_id": 1004027, "cast_moment": 6,
                               "buff_ids": [20990010, 20990020], "removed": deepcopy(cleanup)},
                              {"op": "core_magic.cast", "effect_id": 1038010, "cast_moment": 10,
                               "source": deepcopy(effect), "counters": deepcopy(ledger), "policy": POLICY}])
    except Exception as exc:
        result["blockers"] = [str(exc)]
    return result


def effective_skill_cost(state, side, cost):
    """Apply bound water magic to a resolved cost before ordinary action planning."""
    _int(cost, "resolved skill energy cost")
    if side not in ("a", "b"):
        raise ValueError("Unknown skill-cost side")
    if "core_magic_runtime" not in state:
        return cost
    active = validate_core_magic(state)
    return 0 if any(effect["side"] == side and effect["target_member_id"] == active[side]["member_id"]
                    for effect in state["core_magic_runtime"]["effects"]) else cost


def end_core_magic_round(state):
    """Mutate owned state at round end, removing all expiring buffs exactly once."""
    if "core_magic_runtime" not in state:
        return []
    validate_core_magic(state)
    root = state["core_magic_runtime"]
    if root["closed_turn"] == state["turn"]:
        return []
    events = [{"op": "core_magic.expire", "source": deepcopy(effect), "policy": POLICY}
              for effect in root["effects"]]
    events.extend(_end_additions(state))
    events.extend(_end_confirmed(state))
    root["effects"] = []
    root["closed_turn"] = state["turn"]
    return events


def load_core_magic_additions():
    """Verify the complete heal/fire chains, including binary item-use rows."""
    if _file_hash(ADDITIONS_PATH) != ADDITIONS_SHA256:
        raise ValueError("Heal/fire core-magic reviewed evidence changed")
    rules = json.loads(ADDITIONS_PATH.read_text(encoding="utf-8"))
    for source in rules["sources"]:
        path = (ROOT / source["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or _file_hash(path) != source["sha256"]:
            raise ValueError("Heal/fire core-magic source changed: " + source["path"])
    return rules


def load_core_magic_index():
    """Return all 33 mappings and specific remaining gates; no NPC aliasing."""
    if _file_hash(INDEX_PATH) != INDEX_SHA256:
        raise ValueError("Core-magic complete index changed")
    rules = json.loads(INDEX_PATH.read_text(encoding="utf8"))
    for source in rules["sources"]:
        path = (ROOT / source["path"]).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file() or _file_hash(path) != source["sha256"]:
            raise ValueError("Core-magic index source changed: " + source["path"])
    return rules


def _initialize_additions(state):
    rules = load_core_magic_additions()
    state["core_magic_additions"] = {"policy": ADDITIONS_POLICY, "rules_sha256": ADDITIONS_SHA256,
        "players": {side: {"item_id": team["core_magic"]["id"], "casts": [],
                    "inventory_remaining": rules["records"][str(team["core_magic"]["id"])]["item_row"]["initial_use_times"],
                    "battle_uses_remaining": rules["records"][str(team["core_magic"]["id"])]["battle_item_row"]["use_time_in_battle"],
                    "next_ready_turn": 1}
                    for side, team in state["teams"].items()
                    if team.get("core_magic", {}).get("id") in (104001, 104003)}}


def _validate_additions(state):
    expected = {side: team["core_magic"]["id"] for side, team in state["teams"].items()
                if team.get("core_magic", {}).get("id") in (104001, 104003)}
    root = state.get("core_magic_additions")
    if root is None and not expected:
        return
    if (not isinstance(root, dict) or root.get("policy") != ADDITIONS_POLICY
            or root.get("rules_sha256") != ADDITIONS_SHA256
            or not isinstance(root.get("players"), dict) or set(root["players"]) != set(expected)):
        raise ValueError("Heal/fire ledger must bind the reviewed policy, source and selection")
    rules = load_core_magic_additions()
    for side, item in expected.items():
        ledger = root["players"][side]
        row = rules["records"][str(item)]
        casts = ledger.get("casts")
        if ledger.get("item_id") != item or not isinstance(casts, list):
            raise ValueError("Invalid heal/fire cast ledger")
        if len(casts) > min(row["item_row"]["initial_use_times"], row["battle_item_row"]["use_time_in_battle"]):
            raise ValueError("Heal/fire casts exceed separate inventory/battle limits")
        roster = {m["member_id"] for m in state["teams"][side]["members"]}
        last = 0
        for cast in casts:
            turn = _int(cast.get("turn"), "heal/fire cast turn", 1)
            if (cast.get("target_member_id") not in roster or turn > state["turn"]
                    or (last and turn < last + row["skill_row"]["cd_round"][0])):
                raise ValueError("Heal/fire cast history violates target/cooldown")
            if set(cast) - {"turn", "target_member_id", "end_turn", "end_reason"}:
                raise ValueError("Unknown heal/fire cast-history fields")
            if "end_turn" in cast:
                ended = _int(cast["end_turn"], "heal/fire ending turn", turn)
                if ended > state["turn"] or cast.get("end_reason") not in ("duration", "departure", "exhaustion"):
                    raise ValueError("Invalid heal/fire ending history")
            elif "end_reason" in cast:
                raise ValueError("Heal/fire end reason lacks its turn")
            expiry = turn + (2 if item == 104001 else 0)
            if "end_turn" not in cast and (state["turn"] > expiry or (
                    state["core_magic_runtime"]["closed_turn"] == state["turn"] and state["turn"] >= expiry)):
                raise ValueError("Heal/fire lifecycle skipped expiration")
            if item == 104001:
                target = next(m for m in state["teams"][side]["members"] if m["member_id"] == cast["target_member_id"])
                maximum = _int(target.get("max_hp"), "heal target max HP", 1)
                if target["hp"] > maximum:
                    raise ValueError("Heal target HP exceeds max HP")
            last = turn
        counters = {"inventory_remaining": row["item_row"]["initial_use_times"] - len(casts),
                    "battle_uses_remaining": row["battle_item_row"]["use_time_in_battle"] - len(casts),
                    "next_ready_turn": last + row["skill_row"]["cd_round"][0] if last else 1}
        for key, value in counters.items():
            if _int(ledger.get(key), key) != value:
                raise ValueError("Heal/fire counters disagree with committed history")


def _heal_magic(member):
    maximum = _int(member.get("max_hp"), "heal target max HP", 1)
    hp = _int(member.get("hp"), "heal target HP")
    if hp > maximum:
        raise ValueError("Heal target HP exceeds max HP")
    amount = min(maximum - hp, maximum * 15 // 100) if hp else 0
    member["hp"] += amount
    return amount


def _execute_addition_magic(state, action, context, catalog):
    result = {"status": "blocked", "scope": "core_magic_heal_fire_experiment", "state": deepcopy(state),
              "events": [], "blockers": [], "executable": False, "battle_executable": False,
              "full_turn_executed": False, "training_eligible": False, "calibrated": False,
              "real_game_verified": False, "online_mount_verified": False}
    try:
        if not isinstance(context, dict) or context.get("policy") != core_magic_policy():
            raise ValueError("Heal/fire magic requires its complete explicit research policy")
        if set(action) != {"kind", "item_id", "side", "target_slot"} or action.get("side") not in ("a", "b"):
            raise ValueError("Heal/fire magic requires kind,item_id,side,target_slot exactly")
        current = deepcopy(state)
        active = validate_core_magic(current)
        side, item = action["side"], action["item_id"]
        team = current["teams"][side]
        if _int(action["target_slot"], "target slot") != team["active_slot"] or active[side]["hp"] <= 0:
            raise ValueError("Heal/fire magic targets a living active ally only")
        if current["core_magic_runtime"]["closed_turn"] == current["turn"]:
            raise ValueError("Core-magic selection is closed for this round")
        ledger = current["core_magic_additions"]["players"].get(side)
        if not ledger or ledger["item_id"] != item:
            raise ValueError("Selected magic differs from requested heal/fire item")
        row = load_core_magic_additions()["records"][str(item)]
        casts = ledger["casts"]
        if len(casts) >= min(row["item_row"]["initial_use_times"], row["battle_item_row"]["use_time_in_battle"]):
            raise ValueError("Heal/fire magic has no remaining inventory/battle uses")
        if casts and current["turn"] < casts[-1]["turn"] + row["skill_row"]["cd_round"][0]:
            raise ValueError("Heal/fire magic is cooling down")
        from lab.prepared_rules import prepare_rules
        prepared = prepare_rules(catalog)
        if current.get("snapshot_id") != prepared.snapshot_id:
            raise ValueError("Heal/fire target must bind the catalog snapshot")
        target = active[side]
        types = prepared._rules.form(target["form_id"])["types"]
        if "types" in target and target["types"] != types:
            raise ValueError("Heal/fire target types conflict with its bound form")
        if item == 104003 and "火系" not in types:
            raise ValueError("Fire magic requires verified fire type; bloodline-only route remains blocked")
        if target.get("magic_target_states") != {"drill": False, "static": False, "mimic": False}:
            raise ValueError("Explicit absent drill/static/mimic target states required")
        cast = {"turn": current["turn"], "target_member_id": target["member_id"]}
        casts.append(cast)
        ledger.update(inventory_remaining=row["item_row"]["initial_use_times"] - len(casts),
                      battle_uses_remaining=row["battle_item_row"]["use_time_in_battle"] - len(casts),
                      next_ready_turn=current["turn"] + row["skill_row"]["cd_round"][0])
        events = [{"op": "core_magic.cleanup", "effect_id": 1004027, "cast_moment": 6,
                   "buff_ids": [20990010, 20990020], "removed": []},
                  {"op": "core_magic.cast", "item_id": item, "cast_moment": 10,
                   "source": deepcopy(cast), "rules_sha256": ADDITIONS_SHA256,
                   "inventory_remaining": row["item_row"]["initial_use_times"] - len(casts),
                   "battle_uses_remaining": row["battle_item_row"]["use_time_in_battle"] - len(casts),
                   "next_ready_turn": current["turn"] + row["skill_row"]["cd_round"][0],
                   "policy": ADDITIONS_POLICY}]
        if item == 104001:
            events.append({"op": "core_magic.heal", "phase": "immediate", "side": side,
                           "member_id": target["member_id"], "amount": _heal_magic(target),
                           "effect_id": 1005015, "policy": ADDITIONS_POLICY})
        if item == 104001 and target['hp'] > 0:
            from lab.trait_runtime import after_hp_restore_full
            events.extend(after_hp_restore_full(current,side,target['max_hp']*15//100,
                events[-1]['amount'],{'turn':current['turn']},member_id=target['member_id']))
        validate_core_magic(current)
        result.update(status="applied", state=current, events=events, executable=True)
    except (ValueError, KeyError, TypeError) as exc:
        result["blockers"] = [str(exc)]
    return result


def effective_skill_power(state, side, power):
    """Apply fire magic to source power, before damage formula/rounding."""
    from fractions import Fraction
    import math
    if type(power) not in (int, float, Fraction) or not math.isfinite(power) or power < 0:
        raise ValueError("Core-magic source power must be a nonnegative number")
    if side not in ("a", "b"):
        raise ValueError("Unknown skill-power side")
    if "core_magic_runtime" not in state:
        return power
    active = validate_core_magic(state)
    ledger = state.get("core_magic_additions", {}).get("players", {}).get(side)
    if ledger and ledger["item_id"] == 104003 and any(
            c["turn"] == state["turn"] and "end_turn" not in c
            and c["target_member_id"] == active[side]["member_id"] for c in ledger["casts"]):
        return power * Fraction(5, 2)
    return power


def on_core_magic_departure(state, side, member_id):
    """Clean the source's heal buff on departure; never clear unrelated fields."""
    if "core_magic_runtime" not in state:
        return []
    validate_core_magic(state)
    ledger = state.get("core_magic_additions", {}).get("players", {}).get(side)
    events = []
    if ledger and ledger["item_id"] == 104001:
        for cast in ledger["casts"]:
            if cast["target_member_id"] == member_id and "end_turn" not in cast:
                cast.update(end_turn=state["turn"], end_reason="departure")
                events.append({"op": "core_magic.expire", "side": side, "item_id": 104001,
                               "member_id": member_id, "reason": "departure", "policy": ADDITIONS_POLICY})
    return events


def _end_additions(state):
    events = []
    for side, ledger in state.get("core_magic_additions", {}).get("players", {}).items():
        item = ledger["item_id"]
        for cast in ledger["casts"]:
            if "end_turn" in cast:
                continue
            member = next(m for m in state["teams"][side]["members"] if m["member_id"] == cast["target_member_id"])
            if item == 104001 and state["teams"][side]["members"][state["teams"][side]["active_slot"]]["member_id"] != member["member_id"]:
                cast.update(end_turn=state["turn"], end_reason="departure")
                events.append({"op": "core_magic.expire", "side": side, "item_id": item,
                               "member_id": member["member_id"], "reason": "departure", "policy": ADDITIONS_POLICY})
                continue
            if item == 104001 and member["hp"] > 0:
                events.append({"op": "core_magic.heal", "phase": "round_end", "side": side,
                               "member_id": member["member_id"], "amount": _heal_magic(member),
                               "effect_id": 1005015, "policy": ADDITIONS_POLICY})
                from lab.trait_runtime import after_hp_restore_full
                events.extend(after_hp_restore_full(state,side,member['max_hp']*15//100,
                    events[-1]['amount'],{'turn':state['turn']},member_id=member['member_id']))
            if item == 104003 or not member["hp"] or state["turn"] >= cast["turn"] + 2:
                reason = "exhaustion" if not member["hp"] else "duration"
                cast.update(end_turn=state["turn"], end_reason=reason)
                events.append({"op": "core_magic.expire", "side": side, "item_id": item,
                               "member_id": member["member_id"], "reason": reason, "policy": ADDITIONS_POLICY})
    return events


def load_confirmed_core_magic_rules():
    """User confirmation supplements, without rewriting the historical binary evidence."""
    if _file_hash(CONFIRMED_PATH) != CONFIRMED_SHA256:
        raise ValueError("User-confirmed core-magic rules changed")
    data = json.loads(CONFIRMED_PATH.read_text(encoding="utf-8"))
    if data.get("policy") != CONFIRMED_POLICY:
        raise ValueError("Unknown user-confirmed core-magic policy")
    for source in data["sources"]:
        if _file_hash(ROOT / source["path"]) != source["sha256"]:
            raise ValueError("Current core-magic source changed: " + source["path"])
    return data


def _confirmed_hash(row):
    from lab.ruleset import canonical_hash
    return canonical_hash({k: v for k, v in row.items() if k != "record_hash"})


def reviewed_wish_skill(skill_id):
    """Exact reviewed wish IDs only; no fallback for arbitrary native skills."""
    if type(skill_id) is not int:
        return None
    normal = skill_id - 100 if 7700101 <= skill_id <= 7700119 else skill_id
    if not 7700001 <= normal <= 7700019 or normal == 7700006:
        return None
    load_confirmed_core_magic_rules()
    from lab import battle_data, live_power
    from lab.ruleset import canonical_hash
    spec = live_power.specification(normal)
    if not spec or spec.get("source_policy") != "native_will_impact_normal_80_response_200":
        raise ValueError("Wish skill lacks its reviewed normal/response chain")
    native = battle_data._skills().get(str(skill_id))
    if not native or "愿力冲击" not in native.get("name", "") or "废弃" in native["name"]:
        raise ValueError("Wish skill source identity differs")
    native_hash = canonical_hash(native)
    expected = spec["native_hash"] if normal == skill_id else spec["response"]["native_hash"]
    if native_hash != expected:
        raise ValueError("Wish skill native source hash differs")
    code_to_type = {code: name + "系" for name, code in battle_data.TYPE_CODES.items()}
    return {"id": skill_id, "game_id": skill_id, "name": {"zh": native["name"]},
            "type": code_to_type[native["skill_dam_type"]], "kind": "higher",
            "energy": native["energy_cost"][0], "power": native["dam_para"][0],
            "desc": {"zh": native.get("desc", "")}, "desc_notes": [1015],
            "source_module": "NativeWishReviewed", "native_source_hash": native_hash,
            "source_url": "local://data/external/skill.json", "rules_sha256": CONFIRMED_SHA256}


def reviewed_wish_program(prepared, skill_id):
    """Caller resolves 'higher' using the same HUD panel query before preflight."""
    skill = reviewed_wish_skill(skill_id)
    if skill is None:
        return None
    from lab.ruleset import canonical_hash
    return {"game_id": skill_id, "category": "skill", "name": skill["name"]["zh"],
            "status": "compiled", "blockers": [], "snapshot_id": prepared.snapshot_id,
            "source_hash": canonical_hash(skill), "dependency_ids": [1015],
            "execution_blockers": ["尚未通过当前版本的真实对战校准。"],
            "static_fields": {k: skill[k] for k in ("kind", "energy", "power", "type")},
            "source_description": skill["desc"]["zh"], "source": {"rules_sha256": CONFIRMED_SHA256,
                "native_source_hash": skill["native_source_hash"], "basis": "installed_skill_and_user_confirmed_core"},
            "wish_adaptive_damage": True, "response_kinds": ["status"],
            "operations": [{"op": "damage", "params": {"target": "opponent", "kind": "higher",
                "power": skill["power"], "type": skill["type"]}}],
            "executable": False, "real_game_verified": False}


def _initialize_confirmed(state):
    load_confirmed_core_magic_rules()
    state["core_magic_runtime"]["confirmed"] = {"policy": CONFIRMED_POLICY,
        "rules_sha256": CONFIRMED_SHA256,
        "players": {side: {"item_id": team["core_magic"]["id"], "casts": [],
                           "uses_remaining": 2 if team["core_magic"]["id"] == 104002 else 1,
                           "next_ready_turn": 1}
                    for side, team in state["teams"].items()
                    if team.get("core_magic", {}).get("id") in (104002, 104007)}}


def _validate_confirmed(state):
    expected = {s: t["core_magic"]["id"] for s, t in state["teams"].items()
                if t.get("core_magic", {}).get("id") in (104002, 104007)}
    root = state["core_magic_runtime"].get("confirmed")
    if root is None and not expected:
        return
    load_confirmed_core_magic_rules()
    if (not isinstance(root, dict) or root.get("policy") != CONFIRMED_POLICY
            or root.get("rules_sha256") != CONFIRMED_SHA256
            or set(root.get("players", {})) != set(expected)):
        raise ValueError("User-confirmed magic ledger/source/selection differs")
    closed = state["core_magic_runtime"]["closed_turn"]
    for side, item in expected.items():
        ledger = root["players"][side]
        casts = ledger.get("casts")
        if ledger.get("item_id") != item or not isinstance(casts, list):
            raise ValueError("Invalid confirmed magic cast ledger")
        limit, offset = (2, 3) if item == 104002 else (1, 999)
        if len(casts) > limit:
            raise ValueError("Confirmed magic use limit exceeded")
        last = 0
        members = {m["member_id"]: m for m in state["teams"][side]["members"]}
        for cast in casts:
            turn = _int(cast.get("turn"), "confirmed magic cast turn", 1)
            if (turn > state["turn"] or (last and turn < last + offset)
                    or cast.get("target_member_id") not in members
                    or cast.get("record_hash") != _confirmed_hash(cast)):
                raise ValueError("Confirmed magic history changed or violates cooldown")
            last = turn
            if item == 104002:
                restored = cast.get("restored_turn")
                if restored is None:
                    if turn != state["turn"] or closed == state["turn"]:
                        raise ValueError("Wish slot restoration skipped its round boundary")
                    target = members[cast["target_member_id"]]
                    if target["skill_slots"][0] != cast["wish_skill_id"]:
                        raise ValueError("Active wish slot changed without its restore transition")
                    if target.get("wish_slot_origin") != cast["record_hash"]:
                        raise ValueError("Wish slot lost its source-bound origin")
                elif restored != turn:
                    raise ValueError("Wish restoration must happen at the cast-round boundary")
        if (ledger.get("uses_remaining") != limit - len(casts)
                or ledger.get("next_ready_turn") != (last + offset if last else 1)):
            raise ValueError("Confirmed magic counters differ from committed casts")


def _boss_target(prepared, member):
    load_confirmed_core_magic_rules()
    from lab import battle_data
    source = battle_data._load("petbase.json").get(str(member["form_id"]))
    if not source:
        raise ValueError("Current native boss source form is missing")
    candidates = source.get("bosspetbase_id_arry", [])
    if not candidates:
        raise ValueError("Current native form has no boss/evolution target")
    rule = source.get("bosspetbase_rule")
    if rule == 2:
        tokens = source.get("bosspetbase_rule_param", [])
        token = member.get("boss_token_id", member.get("original_configuration", {}).get("boss_token_id"))
        if len(tokens) != len(candidates) or token not in tokens or tokens.count(token) != 1:
            raise ValueError("This boss target requires an explicit matching leader token; candidate IDs=" + str(candidates))
        target_id = candidates[tokens.index(token)]
    elif rule is None and len(candidates) == 1:
        target_id = candidates[0]
    else:
        raise ValueError("Boss evolution rule/branch is not uniquely resolved")
    target = prepared._rules.form(target_id)
    if target_id == member["form_id"]:
        raise ValueError("Boss target must change the exact form ID")
    return target


def _execute_confirmed_magic(state, action, context, catalog):
    result = {"status": "blocked", "scope": "user_confirmed_core_magic", "state": deepcopy(state),
              "events": [], "blockers": [], "executable": False, "battle_executable": False,
              "full_turn_executed": False, "training_eligible": False, "calibrated": False,
              "real_game_verified": False, "online_mount_verified": False}
    try:
        if not isinstance(context, dict) or context.get("policy") != core_magic_policy():
            raise ValueError("Core magic requires its complete source-bound policy")
        if set(action) != {"kind", "item_id", "side", "target_slot"} or action.get("side") not in ("a", "b"):
            raise ValueError("Core magic requires kind,item_id,side,target_slot exactly")
        current = deepcopy(state)
        active = validate_core_magic(current)
        side, item = action["side"], action["item_id"]
        team = current["teams"][side]
        target = active[side]
        if _int(action["target_slot"], "target slot") != team["active_slot"] or target["hp"] <= 0:
            raise ValueError("Core magic only targets the living active ally")
        root = current["core_magic_runtime"]
        if root["closed_turn"] == current["turn"]:
            raise ValueError("Core selection is closed for this turn")
        ledger = root["confirmed"]["players"].get(side)
        if not ledger or ledger["item_id"] != item or ledger["uses_remaining"] <= 0:
            raise ValueError("Selected core magic has no remaining uses")
        if current["turn"] < ledger["next_ready_turn"]:
            raise ValueError("Core magic is cooling down")
        if target.get("magic_target_states") != {"drill": False, "static": False, "mimic": False}:
            raise ValueError("Core target drill/static/mimic states must be explicitly absent")
        from lab.prepared_rules import prepare_rules
        prepared = prepare_rules(catalog)
        if current.get("snapshot_id") != prepared.snapshot_id:
            raise ValueError("Core target must bind the catalog snapshot")
        cast = {"turn": current["turn"], "target_member_id": target["member_id"]}
        events = []
        if item == 104002:
            from lab import battle_data
            from lab.team_code import BLOODLINES
            blood = target.get("bloodline_id", target.get("original_configuration", {}).get("bloodline_id"))
            if type(blood) is not int or blood not in range(1, 19):
                raise ValueError("Wish requires an explicit elemental bloodline 1..18")
            wish = battle_data.will_impact_skill(battle_data.TYPE_CODES[BLOODLINES[blood]])
            if not wish or reviewed_wish_skill(wish["skill_id"]) is None:
                raise ValueError("Wish bloodline has no unique reviewed native skill")
            if not isinstance(target.get("skill_slots"), list) or len(target["skill_slots"]) != 4:
                raise ValueError("Wish requires four ordered skill slots")
            if target.get("charge") is not None:
                raise ValueError("Wish during a locked charge requires an explicit charge replacement rule")
            cast.update(slot_before=target["skill_slots"][0], wish_skill_id=wish["skill_id"], suspended_origins={})
            for field in ("dynamic_skill_origins", "transformation_skill_origins"):
                if "0" in target.get(field, {}):
                    cast["suspended_origins"][field] = target[field].pop("0")
            target["skill_slots"][0] = wish["skill_id"]
            cast["record_hash"] = _confirmed_hash(cast)
            target["wish_slot_origin"] = cast["record_hash"]
            events.append({"op": "core_magic.slot_replace", "side": side, "member_id": target["member_id"],
                           "slot": 0, "before": cast["slot_before"], "after": wish["skill_id"], "until_turn": current["turn"]})
        else:
            blood = target.get("bloodline_id", target.get("original_configuration", {}).get("bloodline_id"))
            if blood != 19:
                raise ValueError("Evolution requires exact leader bloodline ID 19")
            form = _boss_target(prepared, target)
            if not isinstance(target.get("original_configuration"), dict):
                raise ValueError("Evolution panel recalculation requires the original complete configuration")
            from lab.simulation import _estimate
            panels, provenance, notes = _estimate(prepared._rules._catalog, target["original_configuration"], form)
            if notes:
                raise ValueError("Evolution panel configuration is incomplete: " + "; ".join(notes))
            previous = target["form_id"]
            hp, maximum = _int(target["hp"], "evolution HP", 1), _int(target.get("max_hp"), "evolution max HP", 1)
            if hp > maximum:
                raise ValueError("Evolution HP exceeds maximum")
            evidence = {"item_id": item, "policy": CONFIRMED_POLICY, "rules_sha256": CONFIRMED_SHA256,
                "petbase_sha256": load_confirmed_core_magic_rules()["sources"][0]["sha256"],
                "source_form_id": previous, "target_form_id": form["id"], "turn": current["turn"],
                "member_id": target["member_id"], "hp_rounding": "floor_ratio_min_one_for_living"}
            target.update(form_id=form["id"], name=form["name"]["zh"], types=deepcopy(form["types"]),
                          hp=max(1, panels["hp"] * hp // maximum), max_hp=panels["hp"],
                          stats={d: v for d, v in panels.items() if d != "hp"}, speed=panels["spd"])
            target["panel_provenance"] = {"mode": "evolved_shared_panel_formula", "fields": provenance,
                                          "evolution": deepcopy(evidence)}
            from lab.trait_runtime import rebind_evolved_member
            events.extend(rebind_evolved_member(prepared, current, side, target["member_id"],
                source_form_id=previous, evolution_evidence=evidence))
            cast.update(evolution=deepcopy(evidence))
            cast["record_hash"] = _confirmed_hash(cast)
            events.append({"op": "core_magic.evolve", "side": side, **evidence,
                           "previous_hp": hp, "previous_max_hp": maximum,
                           "hp": target["hp"], "max_hp": target["max_hp"]})
        ledger["casts"].append(cast)
        ledger["uses_remaining"] -= 1
        ledger["next_ready_turn"] = current["turn"] + (3 if item == 104002 else 999)
        events.insert(0, {"op": "core_magic.cast", "item_id": item, "side": side,
                         "member_id": target["member_id"], "ordinary_action_consumed": False,
                         "uses_remaining": ledger["uses_remaining"], "next_ready_turn": ledger["next_ready_turn"],
                         "policy": CONFIRMED_POLICY, "rules_sha256": CONFIRMED_SHA256})
        validate_core_magic(current)
        result.update(status="applied", state=current, events=events, executable=True,
                      item_id=item, source_basis="用户确认＋现有文件来源", rules_sha256=CONFIRMED_SHA256)
    except (ValueError, KeyError, TypeError, ImportError) as exc:
        result["blockers"] = [str(exc)]
    return result


def _end_confirmed(state):
    events = []
    root = state["core_magic_runtime"].get("confirmed", {})
    for side, ledger in root.get("players", {}).items():
        if ledger["item_id"] != 104002:
            continue
        for cast in ledger["casts"]:
            if "restored_turn" in cast:
                continue
            target = next(m for m in state["teams"][side]["members"] if m["member_id"] == cast["target_member_id"])
            target["skill_slots"][0] = cast["slot_before"]
            target.pop("wish_slot_origin", None)
            for field, row in cast["suspended_origins"].items():
                target.setdefault(field, {})["0"] = deepcopy(row)
            cast["restored_turn"] = state["turn"]
            cast["record_hash"] = _confirmed_hash(cast)
            events.append({"op": "core_magic.slot_restore", "side": side, "member_id": target["member_id"],
                           "slot": 0, "skill_id": cast["slot_before"], "policy": CONFIRMED_POLICY})
    return events


def core_magic_available(state, side, catalog=None):
    """Quote by the real executor on a detached state, including concrete target gates."""
    if side not in ("a", "b") or "core_magic_runtime" not in state:
        return False
    team = state["teams"][side]
    result = execute_core_magic(state, {"kind": "core_magic", "item_id": team.get("core_magic", {}).get("id"),
        "side": side, "target_slot": team["active_slot"]}, {"policy": core_magic_policy()}, catalog=catalog)
    return result["status"] == "applied"
