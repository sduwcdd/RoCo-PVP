"""Seeded, explicitly experimental per-round borrow/mind-read/rewrite slots.

Pools contain distinct skill IDs, with *all* candidate IDs retained, including
unsupported skills and generators. Both teams' current slots are frozen before
any draw. Rewrite excludes the member's original four carried slots. These are
named research choices, not recovered server RNG/timing. Executability of a
sampled ordinary skill remains the caller's normal compiled-program check.

``refresh_round(catalog, state)`` mutates state and returns new events. Repeating
the same round returns no events or draws. Copying/rolling back the complete
state also copies/rolls back its counter and therefore replays the same draw.
Expected pool/recursion failures are committed as stable per-slot blockers;
they never cause rejection sampling or a retry with a smaller supported pool.
"""
from copy import deepcopy
import hashlib

from lab.action_mechanics import GENERATORS, build_action_mechanics
from lab.ruleset import canonical_hash


SIDES = ("a", "b")
POLICY = "sha256_counter_uniform_unique_skill_ids_frozen_round_v1"
TIMING_POLICY = "round_start_all_members_hold_generated_charge_until_release_experiment"
POOL_POLICY = "user_confirmed_opponent_original_carried_rewrite_legal_learnset_20261030"


def _catalog(catalog):
    # PreparedRules owns one immutable catalog copy; no source is modified.
    return catalog._rules._catalog if hasattr(catalog, "_rules") else catalog


def _members(state):
    if type(state.get("turn")) is not int or state["turn"] < 1:
        raise ValueError("Dynamic generation requires a positive integer turn")
    result, seen = [], set()
    for side in SIDES:
        for member in state["teams"][side]["members"]:
            mid, slots = member.get("member_id"), member.get("skill_slots")
            if (not isinstance(mid, str) or not mid or mid in seen or not isinstance(slots, list)
                    or len(slots) != 4 or any(type(sid) is not int or sid < 0 for sid in slots)):
                raise ValueError("Dynamic generation requires unique member IDs and four integer slots")
            seen.add(mid)
            result.append((side, member))
    return result


def _digest_record(record):
    return canonical_hash({key: value for key, value in record.items() if key != "record_hash"})


def carried_slot_order(member):
    """Current positions map to immutable original carried-slot identities."""
    order = member.get("carried_slot_order", [0, 1, 2, 3])
    if (not isinstance(order, list) or len(order) != 4
            or any(type(slot) is not int for slot in order) or sorted(order) != [0, 1, 2, 3]):
        raise ValueError("Invalid original carried-slot identity order")
    return order


def carried_slot_owner(member):
    """A transferred four-slot bundle retains its immutable original snapshot."""
    owner = member.get('carried_slot_owner', member.get('member_id'))
    if not isinstance(owner, str) or not owner:
        raise ValueError('Invalid original carried-slot bundle owner')
    return owner


def remap_member_slots(member, previous_slots, *, previous_member_id=None, transfer_source=None, turn=None, event_token=None):
    """Apply a permutation to live bindings; leave pool/frozen history intact."""
    if any(type(slot) is not int for slot in previous_slots) or sorted(previous_slots) != [0, 1, 2, 3]:
        raise ValueError("Slot movement requires a four-slot permutation")
    from lab.slot_runtime import validate_slot_permutation
    validate_slot_permutation(member, previous_slots)
    order = carried_slot_order(member)
    previous_member_id = previous_member_id or member.get('member_id')
    transferred = previous_member_id != member.get('member_id')
    if transferred and (not isinstance(transfer_source, dict)
            or transfer_source.get('policy') != 'source_bound_slot_permutation_and_bundle_transfer_v1'
            or type(transfer_source.get('turn')) is not int
            or not isinstance(transfer_source.get('source_hash'), str)
            or not isinstance(transfer_source.get('event_token'), str)):
        raise ValueError('Cross-member slot bindings require their source-bound transfer event')

    def moved_origin(row, old_slot, new_slot):
        if (not isinstance(row, dict) or row.get("slot") != old_slot
                or row.get("member_id") != previous_member_id
                or row.get("record_hash") != _digest_record(row)):
            raise ValueError("Slot movement requires intact nested origin records")
        row = deepcopy(row)
        row["slot"] = new_slot
        if transferred:
            row['transfer_history'] = [*deepcopy(row.get('transfer_history', [])),
                {**deepcopy(transfer_source), 'from_member_id': previous_member_id,
                 'to_member_id': member['member_id'], 'from_slot': old_slot,
                 'to_slot': new_slot, 'previous_record_hash': row['record_hash']}]
            row['member_id'] = member['member_id']
        for key in ("prior_dynamic_origin", "prior_transformation_origin"):
            if row.get(key) is not None:
                row[key] = moved_origin(row[key], old_slot, new_slot)
        row["record_hash"] = _digest_record(row)
        return row

    for key in ("dynamic_skill_origins", "transformation_skill_origins", "skill_history"):
        if key in member:
            member[key] = {str(new): moved_origin(member[key][str(old)], old, new)
                           for new, old in enumerate(previous_slots) if str(old) in member[key]}
    if member.get("charge") is not None:
        charge = member["charge"]
        old = charge.get("slot") if isinstance(charge, dict) else None
        if (type(old) is not int or not 0 <= old < 4
                or charge.get("skill_id") != member["skill_slots"][previous_slots.index(old)]):
            raise ValueError("Charging skill must match its moving slot")
        charge["slot"] = previous_slots.index(old)
    member["carried_slot_order"] = [order[old] for old in previous_slots]
    from lab.skill_history_runtime import on_slot_remap
    return on_slot_remap(member,previous_slots,turn=turn if turn is not None else (transfer_source or {}).get('turn'),event_token=event_token)


def initialize_dynamic_skills(state, *, seed=0):
    """Choose an experiment seed once; preserve existing valid generator state."""
    if type(seed) is not int or seed < 0:
        raise ValueError("Dynamic-skill seed must be a nonnegative integer")
    members = _members(state)
    if "dynamic_skills" in state:
        _validate_root(state)
        if state["dynamic_skills"]["prng"]["seed"] != seed:
            raise ValueError("Dynamic-skill seed cannot change within a battle")
        return state
    originals = {}
    for _, member in members:
        if carried_slot_owner(member) != member['member_id']:
            raise ValueError('Transferred bundles require the retained original dynamic-skill root')
        slots = member["skill_slots"]
        filled = [sid for sid in slots if sid]
        if len(filled) != len(set(filled)):
            raise ValueError("Original carried slots cannot contain duplicate skills")
        if member.get("dynamic_skill_origins"):
            raise ValueError("Dynamic slot origins require their matching PRNG state")
        order = carried_slot_order(member)
        originals[member["member_id"]] = [slots[order.index(slot)] for slot in range(4)]
    state["dynamic_skills"] = {"policy": POLICY, "timing_policy": TIMING_POLICY,
                               "pool_policy": POOL_POLICY,
                               "prng": {"seed": seed, "counter": 0},
                               "original_slots": originals, "refreshed_turn": 0,
                               "catalog_hash": None, "blockers": []}
    return state


def _validate_root(state):
    root = state["dynamic_skills"]
    if (not isinstance(root, dict) or root.get("policy") != POLICY
            or root.get("timing_policy") != TIMING_POLICY or root.get("pool_policy") != POOL_POLICY
            or not isinstance(root.get("prng"), dict)
            or any(type(root["prng"].get(key)) is not int or root["prng"][key] < 0 for key in ("seed", "counter"))
            or type(root.get("refreshed_turn")) is not int
            or not 0 <= root["refreshed_turn"] <= state["turn"]
            or not isinstance(root.get("blockers"), list)):
        raise ValueError("Invalid dynamic-skill PRNG or timing state")
    members = _members(state)
    if (not isinstance(root.get("original_slots"), dict)
            or set(root["original_slots"]) != {member["member_id"] for _, member in members}):
        raise ValueError("Dynamic-skill original member roster changed")
    if sorted(carried_slot_owner(member) for _, member in members) != sorted(root['original_slots']):
        raise ValueError('Original carried-slot bundle ownership is not a roster permutation')
    for _, member in members:
        original = root["original_slots"][carried_slot_owner(member)]
        if (not isinstance(original, list) or len(original) != 4
                or any(type(sid) is not int or sid < 0 for sid in original)
                or len([sid for sid in original if sid]) != len({sid for sid in original if sid})):
            raise ValueError("Invalid original carried skill slots")
        validate_dynamic_member(member)
        for key, row in member.get("dynamic_skill_origins", {}).items():
            if (row["original_slots"] != original
                    or original[carried_slot_order(member)[int(key)]] != row["origin_skill_id"]):
                raise ValueError("Dynamic generator no longer matches original carried slots")


def validate_dynamic_member(member):
    """Validate source-tracked generated slots; suitable for the joint planner."""
    order = carried_slot_order(member)
    if member.get('skill_history'):
        from lab.skill_history_runtime import validate_member
        validate_member(member)
    if member.get("transformation_skill_origins"):
        from lab.transformation_runtime import validate_member
        validate_member(member)
    origins = member.get("dynamic_skill_origins", {})
    if not isinstance(origins, dict):
        raise ValueError("Dynamic skill origins must be a slot mapping")
    if set(origins) & set(member.get("transformation_skill_origins", {})):
        raise ValueError("A slot cannot have two active generation origins")
    for key, row in origins.items():
        if (key not in ("0", "1", "2", "3") or not isinstance(row, dict)
                or row.get("policy") != POLICY or row.get("origin_skill_id") not in GENERATORS
                or row.get("record_hash") != _digest_record(row)
                or row.get("member_id") != member["member_id"]
                or row.get("slot") != int(key)
                or type(row.get("generated_skill_id")) is not int
                or member["skill_slots"][int(key)] != row["generated_skill_id"]
                or row.get("energy_delta") != GENERATORS[row["origin_skill_id"]][2]
                or not isinstance(row.get("original_slots"), list) or len(row["original_slots"]) != 4
                or row["original_slots"][order[int(key)]] != row["origin_skill_id"]
                or not isinstance(row.get("pool_ids"), list)
                or (not row.get("blocker") and row["generated_skill_id"] not in row["pool_ids"])):
            raise ValueError("Invalid source-tracked dynamic skill slot")


def duplicate_slots_allowed(member):
    """Only copied/generated occurrences may duplicate one ordinary occurrence."""
    validate_dynamic_member(member)
    origins = {**member.get("dynamic_skill_origins", {}), **member.get("transformation_skill_origins", {})}
    groups = {}
    for slot, sid in enumerate(member["skill_slots"]):
        if sid:
            groups.setdefault(sid, []).append(slot)
    for slots in groups.values():
        if len(slots) > 1:
            ordinary = [slot for slot in slots if str(slot) not in origins]
            if len(ordinary) > 1 or any(origins[str(slot)].get("blocker") for slot in slots if str(slot) in origins):
                return False
    return True


def cost_delta(member, slot):
    """Return 0 for borrow/plain slots or -2 for mind-read/rewrite outputs."""
    if type(slot) is not int or not 0 <= slot < 4:
        raise ValueError("Dynamic cost requires a slot in 0..3")
    validate_dynamic_member(member)
    row = member.get("transformation_skill_origins", {}).get(str(slot),
        member.get("dynamic_skill_origins", {}).get(str(slot)))
    if row and row.get("blocker"):
        raise ValueError(row["blocker"])
    from lab.trait_runtime import cost_delta as trait_cost_delta
    return trait_cost_delta(member, row["energy_delta"] if row else 0)


def _learnset(catalog, member):
    detail = catalog.get("details", {}).get(str(member["form_id"]), {})
    learnset = detail.get("learnset", {})
    result = []
    from lab.learnset import learning_path_allows
    # Flat pools can include bloodline/legendary entries; never bypass their paths.
    structured = {entry.get("move", entry.get("id")) if isinstance(entry, dict) else entry
                  for key in ("native", "legacy", "legendary") for entry in learnset.get(key, [])}
    for key in ("pool", "native", "stones", "legacy", "legendary"):
        for entry in learnset.get(key, []):
            sid = entry.get("move", entry.get("id")) if isinstance(entry, dict) else entry
            if type(sid) is not int or sid <= 0:
                raise ValueError(f"Invalid {key} learnset candidate for {member['member_id']}")
            if key == "pool" and sid in structured:
                continue
            if key in ("native", "legacy", "legendary") and not learning_path_allows(
                    catalog, member, key, entry if isinstance(entry, dict) else {"move": sid}):
                continue
            result.append(sid)
    return sorted(set(result))


def _draw(prng, size):
    # Rejection is solely integer-range balancing, never skill-support filtering.
    bound = (1 << 256) // size * size
    while True:
        counter = prng["counter"]
        prng["counter"] += 1
        value = int(hashlib.sha256(f"{POLICY}:{prng['seed']}:{counter}".encode("ascii")).hexdigest(), 16)
        if value < bound:
            return value % size


def generator_programs(prepared):
    """Round refresh owns generation; selecting a drawn generator wastes the action."""
    source = prepared._rules._catalog
    metadata = build_action_mechanics(source)
    programs = {}
    for sid in GENERATORS:
        row = metadata['generators'].get(str(sid))
        if not row or row['status'] != 'supported':
            continue
        program = prepared._rules.program(sid)
        program.pop('native_rule', None)
        program.update(status='compiled', blockers=[], operations=[{'op': 'skill.noop', 'params': {'target': 'self'}}],
                       generator_components={'policy': POOL_POLICY, 'source_hash': row['source_hash']},
                       execution_blockers=['User-confirmed generator no-op; server RNG is not calibrated.'])
        programs[sid] = program
    return programs


def refresh_round(catalog, state):
    """Refresh every carried generator atomically once at a round's start.

    Expected blocked samples commit their actual draw and stable blockers to
    state. Structural/source errors raise without mutating the input state.
    ``state['dynamic_skills']['blockers']`` lists current-round failures. A
    charging generated slot is held under the named experimental timing policy.
    """
    source = _catalog(catalog)
    current = deepcopy(state)
    if "dynamic_skills" not in current:
        initialize_dynamic_skills(current, seed=current.get("random_devotion_rng", {}).get("seed", 0))
    _validate_root(current)
    root = current["dynamic_skills"]
    catalog_hash = canonical_hash(source)
    if root["catalog_hash"] not in (None, catalog_hash):
        raise ValueError("Dynamic-skill catalog changed; start a new battle")
    if root["refreshed_turn"] == current["turn"]:
        return []
    if root["refreshed_turn"] not in (0, current["turn"] - 1):
        raise ValueError("Dynamic-skill round skipped; missing random draws cannot be reconstructed")
    metadata = build_action_mechanics(source)
    moves = source.get("moves", {})
    moves = {row["id"]: row for row in (moves.values() if isinstance(moves, dict) else moves)}
    members = _members(current)
    frozen = {member["member_id"]: list(member["skill_slots"]) for _, member in members}
    root.update(catalog_hash=catalog_hash, blockers=[], frozen_slots=deepcopy(frozen))
    events = []
    # Canonical member IDs keep draw assignment independent of dictionary order.
    for side, member in sorted(members, key=lambda item: (item[0], item[1]["member_id"])):
        original = root["original_slots"][carried_slot_owner(member)]
        for original_slot, origin_id in enumerate(original):
            slot = carried_slot_order(member).index(original_slot)
            if origin_id not in GENERATORS:
                continue
            # A copied/permanent replacement owns its slot until overwritten;
            # a clever output is held until use, including across round refresh.
            if str(slot) in member.get("transformation_skill_origins", {}):
                continue
            meta = metadata["generators"].get(str(origin_id))
            if not meta or meta["status"] != "supported":
                raise ValueError(f"Generator {origin_id} source description is unverified for {member['member_id']} slot {slot}")
            origins = member.setdefault("dynamic_skill_origins", {})
            previous = origins.get(str(slot))
            charge = member.get("charge")
            if isinstance(charge, dict) and charge.get("slot") == slot and previous and not previous.get("blocker"):
                events.append({"op": "dynamic.charge_held", "status": "held_charge", "member_id": member["member_id"],
                               "side": side, "slot": slot, "skill_id": member["skill_slots"][slot],
                               "turn": current["turn"], "timing_policy": TIMING_POLICY})
                continue
            pool_sources = {}
            kind = GENERATORS[origin_id][0]
            if kind == "borrow":
                for candidate_side, candidate in members:
                    if candidate_side == side and candidate["member_id"] != member["member_id"]:
                        for source_slot, sid in enumerate(frozen[candidate["member_id"]]):
                            if sid:
                                pool_sources.setdefault(sid, []).append({"member_id": candidate["member_id"],
                                                                        "slot": source_slot, "basis": "frozen_carried"})
            elif kind == "mind_read":
                for candidate_side, candidate in members:
                    if candidate_side != side:
                        for source_slot, sid in enumerate(root["original_slots"][candidate["member_id"]]):
                            if sid:
                                pool_sources.setdefault(sid, []).append({"member_id": candidate["member_id"],
                                    "slot": source_slot, "basis": "user_confirmed_opponent_original_carried"})
            else:
                candidates = [candidate for candidate_side, candidate in members
                              if candidate_side != side] if kind == "mind_read" else [member]
                for candidate in candidates:
                    for sid in _learnset(source, candidate):
                        if kind != "rewrite" or sid not in original:
                            pool_sources.setdefault(sid, []).append({"member_id": candidate["member_id"],
                                                                    "form_id": candidate["form_id"], "basis": "learnset_union"})
            pool = sorted(pool_sources)
            selected = pool[_draw(root["prng"], len(pool))] if pool else origin_id
            code, blocker = None, None
            if not pool:
                code, blocker = "empty_pool", f"Generator {origin_id} {member['member_id']} slot {slot}: candidate pool is empty"
            elif selected not in moves:
                code, blocker = "missing_candidate_record", f"Generator {origin_id} {member['member_id']} slot {slot} sampled missing skill {selected}; no reroll allowed"
            if isinstance(charge, dict) and charge.get("slot") == slot:
                selected = member["skill_slots"][slot]
                code, blocker = "unresolved_charging_generator", f"Generator {origin_id} {member['member_id']} slot {slot} has a charge without a prior generated-slot binding"
            row = {"policy": POLICY, "member_id": member["member_id"], "slot": slot,
                   "origin_skill_id": origin_id, "original_slots": list(original),
                   "generated_skill_id": selected, "energy_delta": GENERATORS[origin_id][2],
                   "refreshed_turn": current["turn"], "pool_ids": pool,
                   "pool_sources": {str(sid): pool_sources[sid] for sid in pool},
                   "generator_source_hash": meta["source_hash"], "catalog_hash": catalog_hash,
                   "game_evidence": deepcopy(metadata.get("game_evidence")),
                   "blocker": blocker, "blocker_code": code}
            row["record_hash"] = _digest_record(row)
            origins[str(slot)] = row
            member["skill_slots"][slot] = selected
            if blocker:
                root["blockers"].append(blocker)
            events.append({"op": "dynamic.skill_generated", "status": "blocked" if blocker else "generated",
                           "side": side, "member_id": member["member_id"], "slot": slot,
                           "origin_skill_id": origin_id, "skill_id": selected,
                           "energy_delta": row["energy_delta"], "turn": current["turn"],
                           "pool_ids": list(pool), "blocker": blocker, "blocker_code": code,
                           "policy": POLICY, "record_hash": row["record_hash"]})
    root["refreshed_turn"] = current["turn"]
    _validate_root(current)
    state.clear()
    state.update(current)
    return events
