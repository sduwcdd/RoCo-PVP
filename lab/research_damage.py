"""Opt-in, uncalibrated damage adapter for explicit research experiments.

This connects named community expressions to the fragment callback contract;
it is not an extracted game formula. Supplied stats are current base panels,
not species stats, nature/talent estimates, or values inferred from HP bars.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import math

from .numeric_candidates import arena_documented_damage60, showdown_documented_damage60
from .ruleset import BwikiRuleset


_CANDIDATES = {
    "arena_documented_damage60_v1": arena_documented_damage60,
    "showdown_documented_damage60_v1": showdown_documented_damage60,
}
_REQUIRED_STATS = frozenset({"patk", "matk", "pdef", "mdef"})
_STATS = _REQUIRED_STATS | {"hp", "spd"}


def _number(value, label, *, positive=True):
    if type(value) not in (int, float) or not 0 <= value <= 1_000_000:
        raise ValueError(f"{label} must be an explicit finite number in the candidate domain")
    if not math.isfinite(value) or (positive and value == 0):
        raise ValueError(f"{label} must be finite and {'positive' if positive else 'nonnegative'}")
    return value


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an explicit integer >= {minimum}")
    return value


def _ratio(value, label):
    if not isinstance(value, dict) or set(value) != {"numerator", "denominator"}:
        raise ValueError(f"{label} must retain numerator and denominator")
    if type(value["numerator"]) is not int:
        raise ValueError(f"{label}.numerator must be an integer")
    _integer(value["denominator"], label + ".denominator", 1)
    return Fraction(value["numerator"], value["denominator"])


class ResearchDamageResolver:
    """Pure callback; ``explain`` returns diagnostics without retaining state.

    ``resolver(params, state, context)`` returns clipped integer HP loss.
    ``resolver.explain(...)`` returns the same loss and source/policy trace.
    ``resolver.metadata`` is an owned copy suitable for research-run records.
    """

    def __init__(self, catalog, policy):
        if (not isinstance(policy, dict)
                or set(policy) != {"candidate_id", "same_type_multiplier", "stat_modifier_policy"}
                or not isinstance(policy.get("candidate_id"), str)
                or policy.get("candidate_id") not in _CANDIDATES
                or policy.get("stat_modifier_policy") != "linear_signed_terms_experiment"):
            raise ValueError("explicit named candidate, same-type multiplier, and linear research policy are required")
        _number(policy["same_type_multiplier"], "same_type_multiplier")
        self._policy = deepcopy(policy)
        from lab.prepared_rules import PreparedRules
        self._rules = catalog._rules if isinstance(catalog, PreparedRules) else BwikiRuleset(catalog)
        self._formula = _CANDIDATES[policy["candidate_id"]]
        self._metadata = {
            "kind": "explicit_research_damage_adapter", "policy": deepcopy(policy),
            "snapshot_id": self._rules.snapshot_id,
            "catalog_content_hash": self._rules.catalog_content_hash,
            "source": self._formula(1, 1, 1, 1)["source"],
            "stat_inputs": "caller_supplied_current_base_panels",
            "stat_modifier_application": "base_panel * (1 + sum(signed rational terms))",
            "same_type_application": "explicit multiplier only when attack type is in attacker form types",
            "multi_hit_application": "one callback per hit; total source power divided once by hit_count",
            "conditional_application": "floor(nominal_integer_damage * rational_damage_multiplier), then HP clip",
            "calibrated": False, "real_game_verified": False, "training_eligible": False,
            "uncertainties": ["Community documented expression, not a game-file formula.",
                              "Panel modifiers, same-type bonus, hit power basis and final rounding are explicit research assumptions.",
                              "No simulator fidelity or real-game calibration is established."],
        }

    @property
    def metadata(self):
        return deepcopy(self._metadata)

    def _member(self, actor, label):
        if not isinstance(actor, dict):
            raise ValueError(f"{label} actor must be supplied")
        form = self._rules.form(actor.get("form_id"))
        types = actor.get("types")
        if (not isinstance(types, list) or not types or any(not isinstance(t, str) for t in types)
                or len(set(types)) != len(types) or set(types) != set(form.get("types", []))):
            raise ValueError(f"{label}.types must match the supplied snapshot form; transformed types are unsupported")
        stats, modifiers = actor.get("stats"), actor.get("stat_modifiers")
        if (not isinstance(stats, dict) or not _REQUIRED_STATS <= set(stats)
                or set(stats) - _STATS):
            raise ValueError(f"{label}.stats requires explicit patk, matk, pdef and mdef panels")
        for key, value in stats.items():
            _number(value, f"{label}.stats.{key}")
        if not isinstance(modifiers, dict) or set(modifiers) - _STATS:
            raise ValueError(f"{label}.stat_modifiers must explicitly retain signed rational term lists")
        for key, terms in modifiers.items():
            if not isinstance(terms, list):
                raise ValueError(f"{label}.{key} modifiers must be a list")
            for term in terms:
                _ratio(term, f"{label}.{key}")
        return form

    @staticmethod
    def _effective(actor, stat, turn=None, opponent=None):
        from lab.trait_runtime import stat_terms
        terms = [*actor["stat_modifiers"].get(stat, []), *stat_terms(actor, stat, turn, opponent=opponent)]
        factor = 1 + sum((_ratio(t, stat) for t in terms), Fraction(0))
        effective = Fraction(str(actor["stats"][stat])) * factor
        if effective <= 0 or effective > 1_000_000:
            raise ValueError(f"effective {stat} must be positive and within the candidate domain")
        return float(effective), {"stat": stat, "base_panel": actor["stats"][stat],
                                  "terms": deepcopy(terms),
                                  "linear_factor": {"numerator": factor.numerator, "denominator": factor.denominator},
                                  "effective_panel": float(effective)}

    def explain(self, params, state, context):
        if not isinstance(params, dict) or params.get("target") not in ("self", "opponent"):
            raise ValueError("only an explicit self/opponent target is supported")
        if not isinstance(context, dict) or context.get("snapshot_id") != self._rules.snapshot_id:
            raise ValueError("research callback must bind the same catalog snapshot")
        if not isinstance(state, dict):
            raise ValueError("state must supply both actors")
        attacker = state.get("self")
        attacker_form = self._member(attacker, "self")
        self._member(state.get("opponent"), "opponent")
        cost_snapshots = context.get('trait_carried_costs', {})
        if cost_snapshots:
            if not isinstance(cost_snapshots,dict) or set(cost_snapshots) != {'self','opponent'}:
                raise ValueError('Trait cost snapshots must explicitly cover both relative actors')
            state = {key:{**value,'trait_carried_costs':deepcopy(cost_snapshots[key])}
                     for key,value in state.items() if key in ('self','opponent')}
            attacker = state['self']
        defender = state[params["target"]]
        hp = _integer(defender.get("hp"), "target HP")
        if params.get('op') == 'status.trigger':
            if (params.get('status') != 'burn' or params.get('rate') != {'numerator':2,'denominator':100}
                    or params.get('policy') != 'immediate_existing_status_damage_no_decay_experiment_v1'
                    or type(params.get('stacks')) is not int or params['stacks'] < 1
                    or params['stacks'] != defender.get('statuses',{}).get('burn')):
                raise ValueError('Immediate periodic damage descriptor differs from the explicit burn snapshot/policy')
            nominal = Fraction(defender['max_hp'] * params['stacks'] * 2, 100)
            loss = min(hp, nominal.numerator // nominal.denominator)
            from lab.defense_runtime import prevent_lethal
            protection = prevent_lethal(defender, loss, context.get('turn'))
            loss = protection['damage']
            return {'actual_hp_loss':loss,'lethal_protection':protection['event'],'target':params['target'],'hp_before':hp,'hp_after':hp-loss,
                'source':'status.trigger','status':'burn','stacks':params['stacks'],
                'prediction':{'nominal_damage':float(nominal)}, 'metadata':self.metadata,
                'policy':params['policy'],'decay_applied':False,'calibrated':False}
        kind = params.get("kind")
        if kind not in ("physical", "magical"):
            raise ValueError("damage kind must explicitly be physical or magical")
        if not isinstance(params.get("type"), str):
            raise ValueError("attack type must be an explicit catalog type")
        from lab.weather_runtime import resolved_skill_type, modifiers
        weather, skill_id = context.get("weather"), context.get("weather_skill_id")
        params = deepcopy(params)
        params["type"] = resolved_skill_type(weather, skill_id, params["type"])
        attack_stat, defense_stat = ("patk", "pdef") if kind == "physical" else ("matk", "mdef")
        attack, attack_trace = self._effective(attacker, attack_stat, context.get("turn"), defender)
        defense, defense_trace = self._effective(defender, defense_stat, context.get("turn"), attacker)
        from lab.power_query import quote_damage_power
        from lab import mark_runtime
        power_quote = quote_damage_power(self._rules, params, state, context)
        params, power = power_quote['params'], power_quote['power']
        before_marks, after_marks = power_quote['before_marks'], power_quote['after_marks']
        for modifier in modifiers(weather, "before_damage", skill_id, params["type"], attacker):
            if modifier["op"] == "stat_multiplier":
                attack_trace["before_weather_panel"] = attack
                attack *= modifier["value"]
                attack_trace["weather_multiplier"] = modifier["value"]
                attack_trace["effective_panel"] = attack
                attack_trace["weather_source"] = deepcopy(modifier.get("source"))
        hit_count, power_basis = params.get("hit_count"), params.get("power_basis")
        if any(k in params for k in ("hits", "hit_index", "hit_count", "power_basis")):
            _integer(hit_count, "hit_count", 1)
            index = _integer(params.get("hit_index"), "hit_index")
            if "hits" in params:
                _integer(params["hits"], "source hits", 1)
            if index >= hit_count or ("hits" in params and params["hits"] != hit_count):
                raise ValueError("hit index/count disagree with the source-declared sequence")
            if power_basis not in ("source_power_per_hit", "source_power_total"):
                raise ValueError("multi-hit power_basis must be explicitly supplied")
            if power_basis == "source_power_total":
                power = power / hit_count
        matchup = self._rules.type_multiplier(params.get("type"), defender["form_id"])
        type_ratio = _ratio(matchup["multiplier"], "type multiplier")
        ignore_resistance = params.get('ignore_type_resistance', False)
        if type(ignore_resistance) is not bool:
            raise ValueError('Ignore resistance must be an explicit boolean')
        if ignore_resistance and 0 < type_ratio < 1:
            matchup = {**matchup, 'original_multiplier':deepcopy(matchup['multiplier']),
                'multiplier':{'numerator':1,'denominator':1}, 'resistance_ignored':True}
            type_ratio = Fraction(1)

        same_type = self._policy["same_type_multiplier"] if params.get("type") in attacker_form["types"] else 1
        combined_multiplier = float(type_ratio) * same_type
        prediction = self._formula(attack, defense, power, combined_multiplier)
        conditional = _ratio(params["damage_multiplier"], "damage_multiplier") if "damage_multiplier" in params else Fraction(1)
        if conditional < 0:
            raise ValueError("damage_multiplier must be nonnegative")
        nominal = prediction["nominal_damage"]
        trait_damage_multiplier = Fraction(1)
        if skill_id is not None:
            from lab import trait_runtime
            carried_types = [self._rules.skill(mid)['type'] for mid in defender.get('skill_slots', []) if mid]
            trait_damage_multiplier = trait_runtime.damage_multiplier(defender, attacker,
                {**self._rules.skill(skill_id), 'type': params['type']},
                carried_types=carried_types, attacker_types=attacker_form['types'])
        final_unclipped = math.floor(nominal * conditional * trait_damage_multiplier)
        mitigation = None
        lethal_protection = None
        if "turn" in context:
            from lab.defense_runtime import mitigate_damage, prevent_lethal
            mitigation = mitigate_damage(final_unclipped, defender, context["turn"], damage_kind=kind)
            final_unclipped = mitigation["damage"]
            protection = prevent_lethal(defender, final_unclipped, context["turn"])
            final_unclipped = protection["damage"]
            lethal_protection = protection["event"]
        actual = min(hp, final_unclipped)
        return {"actual_hp_loss": actual, "nominal_damage": nominal,
                "final_unclipped_damage": final_unclipped, "target_hp_before": hp,
                "attack": attack_trace, "defense": defense_trace,
                "source_power": params["power"], "effective_power_this_hit": power,
                "mark_power": {"before": before_marks, "after": after_marks,
                               "policy": mark_runtime.POLICY},
                "hit_count": hit_count, "power_basis": power_basis,
                "same_type_multiplier_applied": same_type, "type_matchup": matchup,
                "conditional_damage_multiplier": {"numerator": conditional.numerator, "denominator": conditional.denominator},
                "prediction": prediction, "metadata": self.metadata, "weather": deepcopy(weather),
                "trait_damage_multiplier": {"numerator": trait_damage_multiplier.numerator,
                                            "denominator": trait_damage_multiplier.denominator},
                "defense_mitigation": mitigation, "lethal_protection": lethal_protection}

    def __call__(self, params, state, context):
        return self.explain(params, state, context)["actual_hp_loss"]


def make_research_damage_resolver(catalog, policy):
    return ResearchDamageResolver(catalog, policy)
