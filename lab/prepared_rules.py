"""Reusable, snapshot-bound rules; never caches battle state or predictions.

Construct once per worker/experiment and pass to the existing planning/execution
functions, or call plan/execute below. It is pinned to its construction snapshot;
loading a new published snapshot requires a new instance. It is not a calibrated
engine or a serialization format for training policy observations.
"""
from __future__ import annotations

from threading import Lock

from lab.ruleset import BwikiRuleset
from lab.action_rules import ActionRules
from lab.switch_rules import SwitchRules


class PreparedRules:
    def __init__(self, catalog):
        self._rules = BwikiRuleset(catalog)
        self._phase_rules = None
        self._phase_lock = Lock()

    @property
    def snapshot_id(self):
        return self._rules.snapshot_id

    @property
    def catalog_content_hash(self):
        return self._rules.catalog_content_hash

    def _components(self):
        # Build phase interpreters from the SAME owned copy as the base rules.
        # Keeping this lazy preserves rejection ordering of the original API:
        # malformed experiment contexts fail before phase-specific source checks.
        with self._phase_lock:
            if self._phase_rules is None:
                source = self._rules._catalog
                phases = ActionRules(source)
                switches = SwitchRules(source)
                self._phase_rules = (phases, switches)
        return self._rules, self._phase_rules[0], self._phase_rules[1]

    def skill_plan(self, skill_id, defender_form_id=None):
        """A detached per-skill plan; no mutable internal source is exposed."""
        return self._rules.plan(skill_id, defender_form_id)

    def execute_skill(self, skill_id, state, context, *, damage_resolver=None):
        from lab.skill_execution import execute_rule
        return execute_rule(self._rules.configuration(skill_id), state, context, damage_resolver=damage_resolver)

    def plan(self, state, actions):
        from lab.turn_plan import plan_joint_actions
        return plan_joint_actions(self, state, actions)

    def execute(self, state, actions, context, *, damage_resolver=None):
        from lab.action_runtime import execute_joint_actions
        return execute_joint_actions(self, state, actions, context, damage_resolver=damage_resolver)

    def execute_status_phase(self, state, context, *, damage_resolver=None):
        from lab.status_runtime import execute_status_phase
        return execute_status_phase(self, state, context, damage_resolver=damage_resolver)

    def execute_switch_fragment(self, state, side, target_slot, context, *, damage_resolver=None):
        from lab.switch_runtime import execute_switch_fragment
        return execute_switch_fragment(self, state, side, target_slot, context, damage_resolver=damage_resolver)

    def execute_action_status_sequence(self, state, actions, context, *, damage_resolver=None,
                                       status_damage_resolver=None):
        from lab.action_runtime import execute_action_status_sequence
        return execute_action_status_sequence(self, state, actions, context,
                                             damage_resolver=damage_resolver,
                                             status_damage_resolver=status_damage_resolver)


def prepare_rules(catalog_or_prepared):
    return catalog_or_prepared if isinstance(catalog_or_prepared, PreparedRules) else PreparedRules(catalog_or_prepared)
