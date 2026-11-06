"""Discrete joint beliefs over explicitly supplied opponent configurations.

No population/build frequencies are invented. ``prior`` (or ``weight``) must
be supplied for every candidate. Damage ranges are supplied by the caller's
versioned simulator; this module does not claim to know the game's formula.
Explicit discrete damage distributions are also accepted with caller-declared
source identity; these source claims are preserved, never certified here.

Example::

    belief = BeliefFilter([
        {"id": "a", "nature_id": 1, "talents": {"atk": 10},
         "moves": [101, 102], "prior": 1},
    ])
    belief = belief.observe_revealed_move("turn-1-move", 101)
    belief = belief.observe_damage("turn-1-hit", 20, {"a": [19, 21]})
    restored = BeliefFilter.from_dict(belief.to_dict())

Updates return a new object. An impossible observation records a mismatch,
preserves the last consistent posterior, and blocks further updates. It must
be resolved by correcting the input/model and replaying the evidence, never
by silently resetting the prior. Revealed-move filtering assumes an observed
move was carried; callers must exclude copied/borrowed/generated moves.
Candidate moves retain their supplied order and zero-valued empty slots. Only
explicit four-slot arrays carry known slot positions; shorter legacy lists are
kept without padding. Schema-1 saves lost order in the old implementation and
therefore cannot establish original slot positions when restored.
Updates retain log probabilities so positive candidates below floating-point
display range can recover with later evidence. Summaries list their IDs instead
of declaring them eliminated. Schema 3 persists original priors and observations,
not non-finite log numbers, and replays all updates on restoration.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping, Sequence
from typing import Any


def _integer(value: Any, name: str, *, nonnegative: bool = True) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite nonnegative number")
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return value


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


class BeliefFilter:
    """Immutable Bayesian filter; ``summary()`` returns detached JSON data."""

    def __init__(self, candidates: Sequence[Mapping[str, Any]] | None = None):
        if candidates is None:
            candidates = []
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            raise ValueError("candidates must be an explicit sequence")
        parsed = []
        ids = set()
        for item in candidates:
            if not isinstance(item, Mapping):
                raise ValueError("each candidate must be an object")
            cid = _identifier(item.get("id"), "candidate id")
            if cid in ids:
                raise ValueError(f"duplicate candidate id: {cid}")
            ids.add(cid)
            nature = item.get("nature_id")
            if isinstance(nature, bool) or not isinstance(nature, (int, str)):
                raise ValueError("nature_id must be an integer or nonempty string")
            if isinstance(nature, str):
                _identifier(nature, "nature_id")
            talents = item.get("talents")
            if not isinstance(talents, Mapping) or not talents:
                raise ValueError("talents must be a nonempty dimension/value object")
            talents = {
                _identifier(k, "talent dimension"): _integer(v, "talent value")
                for k, v in talents.items()
            }
            moves = item.get("moves")
            if not isinstance(moves, (list, tuple)):
                raise ValueError("moves must be an explicit list of integer IDs")
            if len(moves) > 4:
                raise ValueError("candidate moves cannot exceed four slots; no slots are truncated")
            moves = [_integer(m, "move id") for m in moves]
            nonempty = [m for m in moves if m != 0]
            if len(set(nonempty)) != len(nonempty):
                raise ValueError("duplicate nonzero move IDs in candidate slots")
            slots_known = item.get("move_slots_known", len(moves) == 4)
            if type(slots_known) is not bool or (slots_known and len(moves) != 4):
                raise ValueError("move_slots_known requires an explicit boolean and four slots when true")
            if "prior" in item and "weight" in item:
                raise ValueError("supply either prior or weight, not both")
            if "prior" not in item and "weight" not in item:
                raise ValueError("candidate prior/weight is required; no population prior exists")
            prior = _number(item.get("prior", item.get("weight")), "candidate prior")
            parsed.append(dict(id=cid, nature_id=nature, talents=talents, moves=moves,
                               move_slots_known=slots_known, prior=prior))
        if parsed:
            dimensions = set(parsed[0]["talents"])
            if any(set(c["talents"]) != dimensions for c in parsed):
                raise ValueError("all candidates must specify the same talent dimensions")
            scale = max(c["prior"] for c in parsed)
            if scale <= 0:
                raise ValueError("candidate prior weights must have positive total mass")
            scaled = [c["prior"] / scale for c in parsed]
            total = math.fsum(scaled)
            weights = [w / total for w in scaled]
            # Keep exact zeros distinct from positive masses too small to
            # display as a float. Linear display weights are never the input
            # to the next Bayesian update.
            prior_logs = [math.log(c["prior"]) if c["prior"] > 0 else -math.inf for c in parsed]
            maximum = max(prior_logs)
            log_total = maximum + math.log(math.fsum(math.exp(v-maximum) for v in prior_logs))
            log_weights = [v-log_total for v in prior_logs]
        else:
            weights = []
            log_weights = []
        self._candidates = parsed
        self._weights = weights
        self._log_weights = log_weights
        self._events: list[dict[str, Any]] = []
        self._status = "ok" if parsed else "prior_not_established"

    @property
    def status(self) -> str:
        return self._status

    def _apply(self, event: dict[str, Any], likelihoods: list[float]) -> BeliefFilter:
        for previous in self._events:
            if previous["event_id"] == event["event_id"]:
                if previous != event:
                    raise ValueError("event_id already exists with different evidence")
                return self
        if self._status == "prior_not_established":
            raise ValueError("prior_not_established: supply explicit candidates first")
        if self._status == "model_mismatch":
            raise ValueError("model_mismatch: correct the model/evidence and replay before updating")
        result = copy.deepcopy(self)
        result._events.append(copy.deepcopy(event))
        logs = [w + math.log(p) if w != -math.inf and p > 0 else -math.inf
                for w, p in zip(self._log_weights, likelihoods)]
        maximum = max(logs)
        if maximum == -math.inf:
            result._status = "model_mismatch"
            return result
        unnormalized = [math.exp(v - maximum) for v in logs]
        total = math.fsum(unnormalized)
        result._weights = [v / total for v in unnormalized]
        log_total = maximum + math.log(total)
        result._log_weights = [v-log_total for v in logs]
        return result

    def observe_revealed_move(self, event_id: str, move_id: int) -> BeliefFilter:
        """Condition on a carried move, not on a move generated during battle."""
        move_id = _integer(move_id, "move_id")
        if move_id == 0:
            raise ValueError("empty slot 0 is not a revealed skill")
        event = dict(event_id=_identifier(event_id, "event_id"), kind="revealed_move",
                     move_id=move_id)
        return self._apply(event, [float(move_id in c["moves"]) for c in self._candidates])

    def observe_damage(self, event_id: str, damage: int,
                       predictions: Mapping[str, Sequence[int]],
                       measurement_tolerance: int = 0) -> BeliefFilter:
        """Likelihood = mass in observed ± tolerance under each uniform range.

        Inclusive integer ranges are mandatory for *every* original candidate,
        including candidates currently at zero probability. No implicit damage
        noise or rounding tolerance is added. A deterministic prediction is
        represented by [damage, damage].
        """
        event_id = _identifier(event_id, "event_id")
        damage = _integer(damage, "damage")
        tolerance = _integer(measurement_tolerance, "measurement_tolerance")
        if not isinstance(predictions, Mapping):
            raise ValueError("predictions must map each candidate id to an inclusive range")
        expected = {c["id"] for c in self._candidates}
        if set(predictions) != expected:
            raise ValueError("predictions must provide exactly every candidate id")
        ranges = {}
        likelihoods = []
        for candidate in self._candidates:
            bounds = predictions[candidate["id"]]
            if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                raise ValueError("prediction must be [minimum, maximum]")
            low, high = (_integer(b, "predicted damage") for b in bounds)
            if low > high:
                raise ValueError("prediction minimum must not exceed maximum")
            overlap = max(0, min(high, damage + tolerance) - max(low, damage - tolerance) + 1)
            likelihoods.append(overlap / (high - low + 1))
            ranges[candidate["id"]] = [low, high]
        event = dict(event_id=event_id, kind="damage", damage=damage,
                     predictions=ranges, measurement_tolerance=tolerance)
        return self._apply(event, likelihoods)

    def observe_damage_distribution(self, event_id: str, damage: int,
                                    predictions: Mapping[str, Sequence[Mapping[str, Any]]],
                                    measurement_tolerance: int = 0, *,
                                    prediction_source: Mapping[str, str]) -> BeliefFilter:
        """Condition on explicitly supplied discrete actual-damage probabilities.

        Each original candidate (including zero-prior ones) needs a nonempty
        list of distinct integer damage outcomes and probabilities summing to
        one within absolute floating-point tolerance 1e-12. The probabilities
        are never invented, merged, filled in, or renormalized. An observation
        integrates only the explicitly requested integer tolerance interval.

        ``prediction_source`` must contain exactly id and snapshot_id. It is
        unverified caller metadata, not a claim of calibration. PMF observations
        from different declared snapshots cannot be mixed in one saved belief.
        """
        event_id = _identifier(event_id, "event_id")
        damage = _integer(damage, "damage")
        tolerance = _integer(measurement_tolerance, "measurement_tolerance")
        if not isinstance(prediction_source, Mapping) or set(prediction_source) != {"id", "snapshot_id"}:
            raise ValueError("prediction_source must contain exactly id and snapshot_id; calibration claims are not accepted")
        source = {key: _identifier(prediction_source[key], "prediction_source." + key)
                  for key in ("id", "snapshot_id")}
        for previous in self._events:
            if (previous["kind"] == "damage_distribution"
                    and previous["prediction_source"]["snapshot_id"] != source["snapshot_id"]):
                raise ValueError("damage distribution snapshots differ; correct the source and replay evidence")
        if not isinstance(predictions, Mapping) or set(predictions) != {c["id"] for c in self._candidates}:
            raise ValueError("predictions must provide exactly every candidate id")
        distributions, likelihoods = {}, []
        for candidate in self._candidates:
            rows = predictions[candidate["id"]]
            if not isinstance(rows, list) or not rows:
                raise ValueError("each damage distribution must be a nonempty list")
            parsed, seen = [], set()
            for row in rows:
                if not isinstance(row, Mapping) or set(row) != {"damage", "probability"}:
                    raise ValueError("each damage outcome requires exactly damage and probability")
                outcome = _integer(row["damage"], "predicted damage")
                if outcome in seen:
                    raise ValueError("duplicate damage outcome; probabilities are not silently merged")
                seen.add(outcome)
                probability = _number(row["probability"], "damage probability")
                if probability > 1:
                    raise ValueError("damage probability must be between zero and one")
                parsed.append({"damage": outcome, "probability": probability})
            total = math.fsum(row["probability"] for row in parsed)
            if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-12):
                raise ValueError("damage probabilities must sum to one; weights are not renormalized")
            parsed.sort(key=lambda row: row["damage"])
            distributions[candidate["id"]] = parsed
            likelihoods.append(math.fsum(row["probability"] for row in parsed
                                         if abs(row["damage"] - damage) <= tolerance))
        event = dict(event_id=event_id, kind="damage_distribution", damage=damage,
                     predictions=distributions, measurement_tolerance=tolerance,
                     prediction_source=source, prediction_verified=False,
                     likelihood_model="explicit_discrete_pmf")
        return self._apply(event, likelihoods)

    def summary(self) -> dict[str, Any]:
        """Joint posterior and marginals, conditional on explicit candidates.

        When mismatched, reported probabilities are the last *consistent*
        posterior and must not be described as explaining all observations.
        Underflowed positive candidates are omitted from numeric marginals but
        explicitly listed; a displayed probability of one is not elimination
        proof while that list is nonempty. Slot completeness includes them.
        """
        joint = []
        nature: dict[tuple[type, Any], float] = {}
        talents: dict[str, dict[int, float]] = {}
        moves: dict[int, float] = {}
        underflowed = [c["id"] for c, weight, log_weight in zip(self._candidates, self._weights, self._log_weights)
                       if weight == 0 and log_weight != -math.inf]
        for c, weight in zip(self._candidates, self._weights):
            if weight <= 0:
                continue
            joint.append({**copy.deepcopy(c), "posterior": weight})
            key = (type(c["nature_id"]), c["nature_id"])
            nature[key] = nature.get(key, 0.0) + weight
            for dimension, value in c["talents"].items():
                marginal = talents.setdefault(dimension, {})
                marginal[value] = marginal.get(value, 0.0) + weight
            for move in c["moves"]:
                if move != 0:
                    moves[move] = moves.get(move, 0.0) + weight
        slots_known = bool(joint) and all(c["move_slots_known"] for c, log_weight in zip(self._candidates, self._log_weights)
                                         if log_weight != -math.inf)
        slot_marginals = None
        if slots_known:
            slot_marginals = []
            for slot in range(4):
                options: dict[int, float] = {}
                for candidate in joint:
                    move_id = candidate["moves"][slot]
                    options[move_id] = options.get(move_id, 0.0) + candidate["posterior"]
                slot_marginals.append({"slot": slot, "options": [
                    {"move_id": move_id, "probability": mass}
                    for move_id, mass in sorted(options.items())]})
        prediction_sources, source_ids, likelihood_models = [], set(), []
        for event in self._events:
            model = {"damage": "uniform_integer_range", "damage_distribution": "explicit_discrete_pmf"}.get(event["kind"])
            if model and model not in likelihood_models:
                likelihood_models.append(model)
            if event["kind"] == "damage_distribution":
                source = event["prediction_source"]
                identity = (source["id"], source["snapshot_id"])
                if identity not in source_ids:
                    source_ids.add(identity)
                    prediction_sources.append({**copy.deepcopy(source), "verified": False})
        return {
            "status": self._status,
            "probability_source": "candidate_prior" if self._candidates else None,
            "population_statistics": False,
            "posterior_scope": "last_consistent_evidence" if self._status == "model_mismatch" else "all_evidence",
            "candidates": joint,
            "nature_marginal": [{"nature_id": k[1], "probability": v} for k, v in nature.items()],
            "talent_marginals": {d: [{"value": v, "probability": p} for v, p in sorted(m.items())]
                                 for d, m in talents.items()},
            "move_marginals": [{"move_id": m, "probability": p} for m, p in sorted(moves.items())],
            "move_slots_known": slots_known,
            "move_slot_marginals": slot_marginals,
            "underflowed_candidate_ids": underflowed,
            "damage_prediction_sources": prediction_sources,
            "damage_likelihood_models": likelihood_models,
            "prediction_verified": False,
            "events": copy.deepcopy(self._events),
            "unresolved_event_id": self._events[-1]["event_id"] if self._status == "model_mismatch" else None,
            "note": "候选先验尚未建立" if not self._candidates else
                    "概率仅条件于显式候选及所给先验，不代表玩家人群统计；候选集合可能不完整。"
                    + ("部分非零候选概率低于浮点显示范围，未被排除，后续证据仍可恢复。" if underflowed else ""),
        }

    def to_dict(self) -> dict[str, Any]:
        """Persist source priors and evidence; no unsafe serialized code/state."""
        return {"schema_version": 3, "candidates": copy.deepcopy(self._candidates),
                "events": copy.deepcopy(self._events)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BeliefFilter:
        """Validate and replay saved evidence, deriving the posterior afresh."""
        if (not isinstance(data, Mapping) or type(data.get("schema_version")) is not int
                or data["schema_version"] not in (1, 2, 3)):
            raise ValueError("unsupported belief schema_version")
        if "candidates" not in data or not isinstance(data.get("events"), list):
            raise ValueError("saved belief requires candidates and an events list")
        candidates = copy.deepcopy(data["candidates"])
        if data["schema_version"] == 1:
            if not isinstance(candidates, list):
                raise ValueError("saved candidates must be a list")
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    raise ValueError("saved candidates must contain objects")
                # Old saves contain sorted, deduplicated IDs; their original
                # four-slot order and empty positions are irrecoverable here.
                candidate["move_slots_known"] = False
        result = cls(candidates)
        for event in data["events"]:
            if not isinstance(event, Mapping):
                raise ValueError("saved events must be objects")
            if event.get("kind") == "revealed_move":
                result = result.observe_revealed_move(event.get("event_id"), event.get("move_id"))
            elif event.get("kind") == "damage":
                result = result.observe_damage(event.get("event_id"), event.get("damage"),
                                               event.get("predictions"), event.get("measurement_tolerance", 0))
            elif event.get("kind") == "damage_distribution":
                if data["schema_version"] != 3:
                    raise ValueError("damage_distribution requires belief schema_version 3")
                if event.get("prediction_verified") is not False or event.get("likelihood_model") != "explicit_discrete_pmf":
                    raise ValueError("saved damage distributions must retain their unverified likelihood declaration")
                result = result.observe_damage_distribution(
                    event.get("event_id"), event.get("damage"), event.get("predictions"),
                    event.get("measurement_tolerance", 0), prediction_source=event.get("prediction_source"))
            else:
                raise ValueError("unknown observation kind")
        return result
