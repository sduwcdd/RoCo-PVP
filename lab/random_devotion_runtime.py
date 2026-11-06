"""Complete extracted devotion pool, with explicit experimental sampling only."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import random

from lab.phase_config import fingerprint

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "data/rules/reviewed-random-devotion-1.json"
CONFIG_HASH = '679f1e3001832508075a8dceba566d7dc5481230f794c9141ffa7b335584af39'
POLICIES = {"sampling": "uniform_independent_with_replacement_experiment_v1",
            "pool": "complete_extracted_effect_1016003_five_candidates",
            "stacking": "team_persistent_uncapped_fixed_enhancements_experiment",
            "prng": "python_random_MT19937_seed_v2_per_draw_3bit_rejection_v1",
            "probability_calibrated": False, "training_eligible": False}


@lru_cache(maxsize=16)
def _hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rules():
    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    if fingerprint(data) != CONFIG_HASH:
        raise ValueError("Random devotion configuration changed; review required")
    for source in data["sources"]:
        path = (ROOT / source["path"]).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _hash(str(path), stat.st_size, stat.st_mtime_ns) != source["sha256"]:
            raise ValueError("Random devotion source changed; review required")
    return data


def research_context(seed):
    if type(seed) is not int or seed < 0:
        raise ValueError("Random devotion requires a nonnegative integer seed")
    return {"random_devotion_policies": deepcopy(POLICIES), "random_devotion_seed": seed}


def apply(state, side, source_id=7130200, *, context):
    """Return a detached whole-state fragment after the skill payment commits.

    This hook supplies all two choices, never filters candidates by support, and
    preserves a sampled unsupported choice in a blocked result rather than rerolling.
    """
    data = rules()
    if not isinstance(context, dict) or context.get("random_devotion_policies") != POLICIES:
        raise ValueError("Explicit random devotion experimental policies required")
    seed = context.get("random_devotion_seed")
    research_context(seed)
    source = data if source_id == data['skill_id'] else (data.get('trait_sources', {}).get(str(source_id)) or data.get('skill_sources', {}).get(str(source_id)))
    if side not in ("a", "b") or type(source_id) is not int or source is None:
        raise ValueError("Unreviewed random devotion source or side")
    if state.get("snapshot_id") != data["snapshot_id"]:
        raise ValueError("Random devotion snapshot differs from reviewed evidence")
    count = source['count']
    if 'condition' in source:
        condition = source['condition']
        if 'previous_turn_type' in condition:
            from lab.action_outcome_runtime import committed_history
            history = [e for team in state['teams'].values() for member in team['members'] for e in committed_history(member)]
            turn = state.get('turn')
            if type(turn) is not int or turn < 1:
                raise ValueError('Conditional devotion needs explicit turn')
            matched = any(e['turn']==turn-1 and e['effective_type']==condition['previous_turn_type'] for e in history)
        else:
            key,expected = next(iter(condition.items()))
            if type(context.get(key)) is not bool:
                raise ValueError('Conditional devotion requires explicit '+key)
            matched = context[key] == expected
        if matched:
            count += source['conditional_count']
    current = deepcopy(state)
    cursor = current.get("random_devotion_rng", {"seed": seed, "draw_index": 0})
    if (set(cursor) != {"seed", "draw_index"} or type(cursor["seed"]) is not int
            or cursor["seed"] != seed or type(cursor["draw_index"]) is not int or cursor["draw_index"] < 0):
        raise ValueError("Random devotion seed/cursor changed or invalid")
    values = current["teams"][side].get("devotion", {})
    supported = {"power", "hits", "poison", "cost", "lifesteal"}
    if (not isinstance(values, dict) or set(values) - supported
            or any(type(v) is not int or v < 0 for v in values.values())):
        raise ValueError("Invalid team devotion state")
    values = deepcopy(values)
    events, blockers = [], []
    for offset in range(count):
        index = cursor["draw_index"] + offset
        material = f"random-devotion-v1:{seed}:{index}"
        rng = random.Random()
        rng.seed(material, version=2)
        raw = [rng.getrandbits(3)]
        while raw[-1] >= len(source["pool"]):
            raw.append(rng.getrandbits(3))
        selected = source["pool"][raw[-1]]
        event = {"op": "devotion.random_draw", "side": side, "source_id": source_id,
                 "effect_id": source["effect_id"], "config_hash": CONFIG_HASH,
                 "trigger_policy": source.get('trigger_policy', 'whole_skill_after_payment'),
                 "source_hash": source.get('record_hash', SKILL_RECORD_HASH),
                 "policies": deepcopy(POLICIES), "seed": seed, "draw_index": index,
                 "seed_material": material, "raw_3bit_draws": raw, "pool_index": raw[-1],
                 "selection": deepcopy(selected), "source_hashes": {
                     row["path"]: row["sha256"] for row in data["sources"]}}
        key = selected["enhancement"]
        if key not in supported:
            blockers.append(f"Unsupported original random devotion selection: {selected}")
            event["status"] = "unsupported"
        else:
            event.update(status="applied", before=values.get(key, 0), after=values.get(key, 0) + 1)
            values[key] = event["after"]
        events.append(event)
    current["random_devotion_rng"] = {"seed": seed, "draw_index": cursor["draw_index"] + count}
    current["teams"][side]["devotion"] = values
    return {"status": "blocked" if blockers else "applied", "state": current,
            "events": events, "blockers": blockers, "training_eligible": False}


def programs(catalog):
    from lab.prepared_rules import prepare_rules
    prepared = prepare_rules(catalog)
    data = rules()
    record = prepared._rules.skill(data['skill_id'])
    if prepared.snapshot_id != data['snapshot_id'] or fingerprint(record) != SKILL_RECORD_HASH:
        raise ValueError('Random devotion whole skill source changed')
    program = deepcopy(prepared._rules.program(data['skill_id']))
    program.pop('native_rule', None)
    program.update(status='compiled', blockers=[], operations=[],
        random_devotion_components={'count':data['count'], 'effect_id':data['effect_id']},
        random_devotion_config_hash=CONFIG_HASH, random_devotion_record=deepcopy(record),
        executable=False, real_game_verified=False, training_eligible=False)
    result = {data['skill_id']:program}
    for key,row in data.get('skill_sources',{}).items():
        mid = int(key)
        record = prepared._rules.skill(mid)
        if record != row['record'] or fingerprint(record) != row['record_hash']:
            raise ValueError('Conditional devotion whole source differs')
        if record['kind'] == 'defense':
            from lab.defense_runtime import defense_programs
            candidate = defense_programs(prepared).get(mid)
            if candidate is None:
                continue
        else:
            candidate = deepcopy(prepared._rules.program(mid))
            candidate.pop('native_rule',None)
            candidate.update(status='compiled',blockers=[],operations=([{'op':'damage','params':{
                'target':'opponent','kind':record['kind'],'power':record['power'],'type':record['type']}}]
                if record['kind'] in ('physical','magical') else []))
        candidate.update(random_devotion_components={'count':row['count'],'condition':deepcopy(row['condition']),
            'conditional_count':row['conditional_count'],'effect_id':row['effect_id']},
            random_devotion_config_hash=CONFIG_HASH,random_devotion_record=deepcopy(record),
            executable=False,real_game_verified=False,training_eligible=False)
        result[mid]=candidate
    return result

SKILL_RECORD_HASH = '13732b20cd1331fc51c21fe69cbe029d7d485849bfe8c51cc886a2beff83c73d'
