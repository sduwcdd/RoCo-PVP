"""Fail-closed execution of the current HUD damage path on owned battle state.

The HUD remains an uncalibrated preview. This adapter shares its calculation,
and refuses unresolved ranges or state that cannot be represented faithfully.
"""
from copy import deepcopy
from functools import lru_cache
from fractions import Fraction
import math

from lab import action_traits, forced_trait_runtime, live_damage, live_power, trait_runtime, weather_runtime

STAT_FIELDS = {"patk": "phyAtk", "matk": "magAtk", "pdef": "phyDef",
               "mdef": "magDef", "spd": "spd"}
UNMAPPED_FIELDS = ("adjacent_power_grants",)


def member_capability_issues(member):
    issues = []
    if "statuses" not in member or not isinstance(member["statuses"], dict):
        issues.append("explicit status state is required")
    else:
        for status, count in member["statuses"].items():
            if status not in ("poison", "burn", "freeze", "leech") or type(count) is not int or count < 0:
                issues.append("unsupported canonical status " + str(status))
    for status, count in member.get("weather_statuses", {}).items():
        if status not in weather_runtime.rules()["status_rules"] or type(count) is not int or count < 0:
            issues.append("unsupported canonical weather status " + str(status))
    if member.get("battleBuffs") or member.get("buffs"):
        issues.append("additional native BUFF state is not projected")
    for field in UNMAPPED_FIELDS:
        if member.get(field):
            issues.append("unmapped " + field)
    tid = member.get("trait_id")
    row = trait_runtime._rows().get(tid)
    action_row = action_traits.source_evidence(live_damage._rules()[1], member) if tid in action_traits.ROWS else None
    forced_row = (forced_trait_runtime.source_evidence(live_damage._rules()[1], member)
                  if tid and row is None and action_row is None else None)
    if tid and row is None and action_row is None and forced_row is None and str(tid) not in weather_runtime.rules().get("trait_modifiers", {}):
        issues.append("unreviewed HUD trait " + str(tid))
    dynamic_stats = ((row or {}).get("event") == "stats.query"
                     or (row or {}).get("stat_query_components"))
    if dynamic_stats and any(record.get("source_kind") == "trait" and record.get("source_id") == tid
            for records in member.get("stat_modifier_sources", {}).values() for record in records):
        issues.append("trait-installed stat terms need proven HUD duplicate attribution")
    return issues


def skill_capability_issues(skill_id):
    # State-dependent queries validate their exact inputs when damage is requested.
    live_power.specification(skill_id)
    return []


def _pet(member, context, *, attacking=False):
    issues = member_capability_issues(member)
    if issues:
        raise ValueError("HUD state unsupported: " + "; ".join(issues))
    for key in ("hp", "max_hp", "energy"):
        value = member.get(key)
        if type(value) is not int or value < 0 or (key == "max_hp" and value == 0):
            raise ValueError("HUD requires exact integer " + key)
    if member["hp"] > member["max_hp"]:
        raise ValueError("HUD HP exceeds its exact maximum")
    panels = {}
    for short, field in STAT_FIELDS.items():
        value = member.get("stats", {}).get(short)
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError("HUD requires an explicit positive base panel: " + short)
        panels[field] = value
    actor = deepcopy(member)
    rules = live_damage._rules()[1]
    if attacking and member.get('trait_id') in action_traits.ROWS:
        action_row = action_traits.source_evidence(rules, member)
        if 'allowed_slots' in action_row['components']:
            action_traits.check_evidence_slot(action_row, context.get('selected_skill_slot'))
    if 'trait_current_skill_types' not in actor:
        from .ruleset import RuleUnavailable
        current_types = []
        for sid in member['skill_slots']:
            if not sid:
                current_types.append(None)
                continue
            try:
                current_types.append(rules.skill(sid)['type'])
            except RuleUnavailable:
                if not (live_power.specification(sid) or {}).get('native_only'):
                    raise
                current_types.append(live_damage._CODE_TO_TYPE[live_damage.battle_data.skill_info(sid)['type_code']])
        actor['trait_current_skill_types'] = current_types
    costs = context.get("trait_carried_costs", {})
    relative = "self" if attacking else "opponent"
    if relative in costs:
        actor["trait_carried_costs"] = deepcopy(costs[relative])
    pet = {"petBaseId": member["form_id"], "petId": member["member_id"],
           "currentHp": member["hp"], "maxHp": member["max_hp"],
           "energy": member["energy"], "battleStats": panels,
           "battleStatsBasis": "natured_base", "battleBuffs": [],
           "carriedSkillIds": list(member["skill_slots"]),
           "liveContext": {"turn": context.get("turn"), "weather": context.get("weather"),
                           "rosters": deepcopy(member.get("trait_team_roster", {}))},
           "_simulation_actor": actor}
    if relative in costs:
        pet["carriedSkillCosts"] = deepcopy(costs[relative])
    if attacking:
        pet["_execution_context"] = deepcopy(context)
        if "energy_before_cast" in context:
            pet["energyBeforeCast"] = context["energy_before_cast"]
        for source, target in (("mark_first_attack", "_resolved_first_attack"),
                               ("mark_first_action", "_resolved_first_action")):
            if type(context.get(source)) is not bool:
                raise ValueError("HUD execution requires explicit " + source)
            pet[target] = context[source]
        slot = context.get("selected_skill_slot")
        if type(slot) is int:
            pet["selectedSlot"] = slot + 1
    return pet


class HUDDamageResolver:
    def __init__(self, catalog, policy=None):
        from lab.prepared_rules import PreparedRules
        from lab.ruleset import canonical_hash
        supplied = catalog._rules._catalog if isinstance(catalog, PreparedRules) else catalog
        actual, self._rules = live_damage._rules()
        if canonical_hash(supplied) != canonical_hash(actual):
            raise ValueError("HUD resolver catalog differs from the HUD snapshot")
        self._metadata = {"kind": "shared_current_hud_damage_adapter",
            "source": "live_damage.skill_math + live_damage._damage_case",
            "calibrated": False, "real_game_verified": False, "training_eligible": False,
            "limitations": ["Unmapped native BUFF state fails closed",
                            "Unresolved HUD ranges fail closed", "No old research-power fallback"]}

    @property
    def metadata(self):
        return deepcopy(self._metadata)

    def explain(self, params, state, context):
        if context.get("snapshot_id") != self._rules.snapshot_id:
            raise ValueError("HUD execution requires its exact source snapshot")
        if params.get("target") != "opponent":
            raise ValueError("HUD supports direct opponent damage only")
        if params.get("kind") not in ("physical", "magical"):
            raise ValueError("HUD execution needs a resolved physical/magical branch")
        if params.get("power_basis") == "source_power_total":
            raise ValueError("HUD uses full source power per hit")
        sid = context.get("weather_skill_id")
        issues = skill_capability_issues(sid)
        if issues:
            raise ValueError("HUD skill unsupported: " + "; ".join(issues))
        attacker, defender = _pet(state["self"], context, attacking=True), _pet(state["opponent"], context)
        profile = live_damage.skill_math(sid, state["self"]["form_id"], state["opponent"]["form_id"])
        if profile.get("reason"):
            raise ValueError(profile["reason"])
        if profile["kind"] not in ("higher", params["kind"]):
            raise ValueError("Resolved physical/magical kind differs from HUD")
        # The committed response selects an existing source-checked HUD variant.
        variant = live_power.response_variant(sid) if context.get("response_success") is True else None
        if variant:
            profile = live_damage.skill_math(variant, state["self"]["form_id"], state["opponent"]["form_id"])
        burst_powers = live_power.entry_burst_powers(attacker, sid, profile)
        if burst_powers is not None and (
                len(burst_powers) != 1 or params.get('power') != burst_powers[0]
                or params.get('base_power', profile['power']) != profile['power']):
            raise ValueError('Resolved entry-burst power differs from its reviewed source')
        source_power = params.get("base_power", params.get("power"))
        base = live_damage.skill_math(sid, state["self"]["form_id"], state["opponent"]["form_id"])
        if source_power not in (base["power"], profile["power"]):
            # Execution may have already materialized a reviewed dynamic power.
            powers, _ = live_power.source_power(attacker, defender, variant or sid, profile)
            if params.get("power") not in powers:
                raise ValueError("Resolved source power differs from HUD; no legacy-power fallback")
        raw_factor = params.get("damage_multiplier", {"numerator": 1, "denominator": 1})
        if (not isinstance(raw_factor, dict) or set(raw_factor) != {"numerator", "denominator"}
                or type(raw_factor["numerator"]) is not int or type(raw_factor["denominator"]) is not int
                or raw_factor["denominator"] <= 0):
            raise ValueError("Conditional damage needs an exact resolved source ratio")
        factor = Fraction(**raw_factor)
        if factor != 1:
            _, intrinsic_factors = live_power.source_power(attacker, defender, variant or sid, profile)
            response_ratio = Fraction(str(profile["power"])) / Fraction(str(base["power"])) if variant else Fraction(1)
            if factor not in intrinsic_factors and factor != response_ratio:
                raise ValueError("Conditional damage factor differs from the resolved HUD source variant")
        resolved_type = weather_runtime.resolved_skill_type(context.get("weather"), sid, params.get("type"))
        hud_type = weather_runtime.resolved_skill_type(context.get("weather"), sid, profile["skillType"])
        if resolved_type != hud_type:
            raise ValueError("Resolved attack type differs from HUD")
        if bool(params.get("ignore_type_resistance")) != bool(profile.get("ignoreResistance")):
            raise ValueError("Resistance policy differs from the resolved HUD skill")
        profile = {**profile, "skillId": variant or sid, "selectedSlot": attacker.get("selectedSlot")}
        attacker["_execution_params"] = deepcopy(params)
        case = live_damage._damage_case(attacker, defender, profile, params["kind"])
        if case["minimum"] != case["maximum"] or any(case[k][0] != case[k][1]
                for k in ("atkRange", "defRange", "powerRange", "finalMultiplierRange")):
            raise ValueError("HUD execution remains an unresolved range")
        nominal = case["minimum"]
        from lab.defense_runtime import mitigate_damage, prevent_lethal
        mitigation = mitigate_damage(nominal, state["opponent"], context["turn"], damage_kind=params["kind"])
        protection = prevent_lethal(state["opponent"], mitigation["damage"], context["turn"])
        actual = min(state["opponent"]["hp"], protection["damage"])
        return {"actual_hp_loss": actual, "nominal_damage": nominal,
                "final_unclipped_damage": protection["damage"], "hud_case": case,
                "defense_mitigation": mitigation, "lethal_protection": protection["event"],
                "metadata": self.metadata, "source_power": profile["power"]}

    def predict_single_hit(self, state, skill_id, context):
        """Sentry query: normal current-state single hit, without response/marks/crit."""
        sid = live_damage.battle_data.canonical_skill(skill_id).get("skill_id", skill_id)
        query_context = {**context, "response_success": False, "weather_skill_id": sid,
                         "energy_before_cast": state["self"]["energy"]}
        attacker = _pet(state["self"], query_context, attacking=True)
        defender = _pet(state["opponent"], query_context)
        profile = {**live_damage.skill_math(sid, state["self"]["form_id"], state["opponent"]["form_id"]),
                   "skillId": sid, "selectedSlot": attacker.get("selectedSlot")}
        if profile.get("reason"):
            raise ValueError(profile["reason"])
        kind = profile["kind"]
        if kind == "higher":
            branches = live_damage._higher_attack_values(attacker, defender)
            choices = [candidate for candidate, values in branches.items() if values]
            if len(choices) != 1:
                raise ValueError("Sentry damage branch is not uniquely determined")
            kind = choices[0]
        case = live_damage._damage_case(attacker, defender, profile, kind)
        if (case["minimum"] != case["maximum"] or any(case[key][0] != case[key][1]
                for key in ("atkRange", "defRange", "powerRange", "finalMultiplierRange"))):
            raise ValueError("Sentry single-hit damage remains an unresolved range")
        return case["minimum"]

    def retaliation(self, descriptor, state, context):
        """Confirmed untyped thorns packet through the same exact HUD formula."""
        from lab.trait_switch_components import retaliation_source
        if (context.get('snapshot_id') != self._rules.snapshot_id
                or context.get('damage_source_kind') != 'trait.retaliation'
                or descriptor != retaliation_source(state['self'])):
            raise ValueError('Retaliation requires its exact bound source and execution context')
        attacker, defender = _pet(state['self'], context), _pet(state['opponent'], context)
        profile = {'skillId': 200103, 'retaliationTraitId': 200103,
                   'retaliationSource': deepcopy(descriptor), 'power': 50, 'kind': 'physical',
                   'skillType': '无系别', 'stab': 1, 'multiplier': 1, 'combined': 1}
        case = live_damage._damage_case(attacker, defender, profile, 'physical')
        if case['minimum'] != case['maximum'] or any(case[key][0] != case[key][1]
                for key in ('atkRange', 'defRange', 'powerRange', 'finalMultiplierRange')):
            raise ValueError('Retaliation HUD calculation remains an unresolved range')
        from lab.defense_runtime import mitigate_damage, prevent_lethal
        mitigation = mitigate_damage(case['minimum'], state['opponent'], context['turn'], damage_kind='physical')
        protection = prevent_lethal(state['opponent'], mitigation['damage'], context['turn'])
        if protection['event']:
            mitigation = {**mitigation, 'survival_event': protection['event']}
        return {'actual_hp_loss': min(state['opponent']['hp'], protection['damage']),
                'nominal_damage': case['minimum'], 'hud_case': case,
                'defense_mitigation': mitigation, 'metadata': self.metadata}

    def mark_damage(self, descriptor, state, context):
        """Resolve a reviewed star explosion; mutation/protection stays in mark_runtime."""
        from lab import mark_runtime
        if descriptor.get("op") == "mark.damage_ratio":
            return mark_runtime.ratio_damage(descriptor, state, context)
        if descriptor.get("op") != "mark.star_damage" or descriptor.get("mark_id") != 1035:
            raise ValueError("HUD mark resolver only supports the reviewed star damage")
        spec = mark_runtime.rules()["marks"]["1035"]["effects"][0]
        if spec.get("damage_owner") != "triggering_attacker":
            raise ValueError("Star damage attacker attribution remains unconfirmed")
        kind = context.get("skill_kind") if spec.get("damage_kind") == "triggering_skill_kind" else None
        attacker, defender = _pet(state["self"], context), _pet(state[descriptor["target"]], context)
        from lab.live_modifiers import star_damage_profile
        profile = star_damage_profile(attacker, defender, descriptor["stacks"], kind=kind)
        if descriptor.get("power") != profile["power"]:
            raise ValueError("Star source power differs from its confirmed layer rule")
        case = live_damage._damage_case(attacker, defender, profile, kind)
        if case["minimum"] != case["maximum"]:
            raise ValueError("Star HUD execution remains an unresolved range")
        from lab.defense_runtime import mitigate_damage
        nominal = mitigate_damage(case["minimum"], state[descriptor["target"]], context["turn"], damage_kind=kind)["damage"]
        return min(state[descriptor["target"]]["hp"], nominal)

    def __call__(self, params, state, context):
        return self.explain(params, state, context)["actual_hp_loss"]


@lru_cache(maxsize=8)
def _prepared_resolver(prepared):
    # PreparedRules owns a frozen catalog; verify HUD compatibility once.
    return HUDDamageResolver(prepared)


def make_hud_damage_resolver(catalog, policy=None):
    from lab.prepared_rules import PreparedRules
    if isinstance(catalog, PreparedRules) and policy is None:
        return _prepared_resolver(catalog)
    return HUDDamageResolver(catalog, policy)


HudDamageResolver = HUDDamageResolver


def resolve_adaptive_program(program, state, context):
    """Resolve source-declared higher-attack wish through the HUD panel selector."""
    if program.get("energy_burst_components"):
        from lab.energy_burst_runtime import resolve_program
        program = resolve_program(program, state, context)
    if program.get("conditional_damage_components") or program.get("repeat_cast_components"):
        from lab.user_skill_extensions import resolve_program
        program = resolve_program(program, state, context)
    if not program.get("wish_adaptive_damage"):
        return program
    attacker = _pet(state["self"], context, attacking=True)
    defender = _pet(state["opponent"], context)
    branches = live_damage._higher_attack_values(attacker, defender)
    kinds = [kind for kind, values in branches.items() if values]
    if len(kinds) != 1:
        raise ValueError("Adaptive wish damage has no uniquely resolved public-panel branch")
    out = deepcopy(program)
    def resolve(value):
        if isinstance(value, dict):
            if value.get("kind") == "higher":
                value["kind"] = kinds[0]
            for child in value.values():
                resolve(child)
        elif isinstance(value, list):
            for child in value:
                resolve(child)
    resolve(out.get("operations", []))
    out["wish_resolved_damage_kind"] = kinds[0]
    return out
