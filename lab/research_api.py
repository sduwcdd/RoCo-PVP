"""Server-owned source adapters for explicitly versioned research execution.

Programs and formula callbacks are never accepted from HTTP clients. Game-file
effects and community numerical candidates retain separate provenance.
"""
from copy import deepcopy
from functools import lru_cache

from lab.game_skill_adapter import (
    VERSION, load_game_skill_adapter, experimental_game_policy,
    game_skill_context, execute_game_skill,
)
from lab.research_battle import execute_research_turn, choose_research_replacements
from lab.research_damage import make_research_damage_resolver


@lru_cache(maxsize=1)
def _sources():
    # A process owns one verified immutable snapshot. Restart to adopt new files.
    return load_game_skill_adapter(verify_sources=True)


@lru_cache(maxsize=128)
def _program(source_id, skill_id, version):
    if version != VERSION:
        raise ValueError("Explicit supported game-file policy_version required")
    if not isinstance(source_id, str) or type(skill_id) is not int or skill_id <= 0:
        raise ValueError("source_id and positive integer skill_id required")
    return _sources().compile(source_id, skill_id, experimental_game_policy(source_id))


def research_request(path, payload, catalog):
    if not isinstance(payload, dict):
        raise ValueError("Research request must be an object")
    if any(key in payload for key in ("program", "program_overrides", "damage_resolver", "predicted_damage")):
        raise ValueError("Client programs or predicted damage cannot become execution rules")
    if path == "/api/research/game-skill":
        program = deepcopy(_program(payload.get("source_id"), payload.get("skill_id"), payload.get("policy_version")))
        context = game_skill_context(program, resolved_energy_cost=payload.get("resolved_energy_cost"))
        result = execute_game_skill(program, payload.get("state"), context)
        result["program"] = program
        return result
    if path == "/api/research/replace":
        return choose_research_replacements(catalog, payload.get("state"), payload.get("selections"), payload.get("context"))
    if path != "/api/research/turn":
        raise ValueError("Unknown research endpoint")
    context = deepcopy(payload.get("context"))
    bindings = payload.get("game_sources", {})
    if not isinstance(bindings, dict) or len(bindings) > 8:
        raise ValueError("game_sources must be at most eight explicit skill/source bindings")
    overrides = {}
    for key, binding in bindings.items():
        if (not isinstance(key, str) or not key.isascii() or not key.isdigit()
                or str(int(key)) != key or int(key) <= 0 or not isinstance(binding, dict)):
            raise ValueError("Game-file bindings must use canonical positive skill IDs")
        overrides[int(key)] = deepcopy(_program(binding.get("source_id"), int(key), binding.get("policy_version")))
    if overrides:
        if not isinstance(context, dict) or not isinstance(context.get("fragments"), dict):
            raise ValueError("Both fragment contexts required")
        state, actions = payload.get("state"), payload.get("actions")
        if (not isinstance(state, dict) or not isinstance(state.get("teams"), dict)
                or not isinstance(actions, dict)):
            raise ValueError("Battle state, teams and actions must be objects")
        for side in ("a", "b"):
            team, action = state["teams"].get(side), actions.get(side)
            if not isinstance(team, dict) or not isinstance(action, dict):
                raise ValueError("Each side needs a team and action object")
            if action.get("kind") == "skill":
                active, slot = team.get("active_slot"), action.get("slot")
                members = team.get("members")
                if (type(active) is not int or not isinstance(members, list)
                        or not 0 <= active < len(members) or type(slot) is not int or not 0 <= slot < 4):
                    raise ValueError("Invalid active member or ordered skill slot")
                if not isinstance(members[active], dict):
                    raise ValueError("Active member must be an object")
                slots = members[active].get("skill_slots")
                if not isinstance(slots, list) or len(slots) != 4:
                    raise ValueError("Exactly four ordered skill slots required")
                skill_id = slots[slot]
                if skill_id in overrides:
                    context["fragments"][side] = game_skill_context(
                        overrides[skill_id], resolved_energy_cost=action["effective_cost"])
    resolver = None
    if "numeric_policy" in payload:
        resolver = make_research_damage_resolver(catalog, payload["numeric_policy"])
    result = execute_research_turn(catalog, payload.get("state"), payload.get("actions"), context,
                                  damage_resolver=resolver, program_overrides=overrides)
    result["numeric_policy"] = deepcopy(resolver.metadata) if resolver is not None else None
    result["game_file_bindings"] = {str(key): {"source_hash": program["source_hash"],
        "source_id": program["game_file_evidence"]["source_id"],
        "policy": deepcopy(program["game_file_evidence"]["policy"]),
        "operations": deepcopy(program["operations"])} for key, program in overrides.items()}
    return result
