"""Opt-in trainer-magic accounting from pinned installed-file evidence.

``initialize_victory`` mutates a fresh/imported state to opt in, taking its
present HP as the observation baseline (never inventing historical defeats).
``reconcile_knockouts`` mutates only the ledger and returns new events. Call it
after *each* committed HP phase, including revival, so every living->zero edge
is counted once. ``terminal`` is read-only; unresolved simultaneous depletion,
round-limit adjudication and roster-only exhaustion explicitly block play.

States lacking ``victory`` retain the old research battle policy. This module
does not implement revival or claim installed assets are current online rules.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path

from lab.phase_config import fingerprint
from lab.trait_runtime import cached_source_query
from lab.pvp_rules import INITIAL_MAGIC, TEAM_SIZE, MAX_ROUND, PVP_ID, BATTLE_CONFIG


SIDES = ("a", "b")
VERSION = "installed-pvp5001-trainer-magic-v1"
ROOT = Path(__file__).resolve().parents[1]
BASE = "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/"
SOURCE_HASHES = {
    BASE + "PVP_CONF.json": "2d434e55969132f82bcbefdf77bebd930c86c280ee53d86d853086187b0945cd",
    BASE + "BATTLE_CONF.json": "6ce385575f8faa39be236c4f517aa3ffed4fca7ce4249cb924d17a46ec451c3e",
    BASE + "BATTLE_GLOBAL_CONFIG.json": "0e43b58db5cc6cf04771c6e17af7c5a4564b3bee671da236706c3667dd9a527e",
}
LOSS_CONFIG = ROOT / 'data/rules/reviewed-trainer-magic-loss-1.json'
LOSS_CONFIG_SHA256 = '1cb43011eca7a93145a81dad6f30a850d55a73a1571fcc7af83138e1af3d79b1'
LOSS_POLICY = 'source_bound_self_knockout_magic_loss_components_v1'
RETALIATION_POLICY = 'audited_source_pet_direct_retaliation_defeat_magic_accounting_v1'


@lru_cache(maxsize=2)
def _loss_configuration(stamp):
    raw = LOSS_CONFIG.read_bytes()
    if hashlib.sha256(raw).hexdigest() != LOSS_CONFIG_SHA256:
        raise ValueError('Trainer-magic loss components changed; source review required')
    return json.loads(raw)


@lru_cache(maxsize=16)
def _loss_source_hash(path, size, stamp):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@cached_source_query
def _loss_data():
    config = _loss_configuration(LOSS_CONFIG.stat().st_mtime_ns)
    for relative, expected in config['sources'].items():
        path = (ROOT / relative).resolve()
        stat = path.stat()
        if not path.is_relative_to(ROOT) or _loss_source_hash(str(path), stat.st_size, stat.st_mtime_ns) != expected:
            raise ValueError('Trainer-magic loss extracted source changed')
    return config


def _trait_losses_enabled(state):
    from lab.trait_runtime import POLICY
    if state.get('trait_policy') is None:
        return False
    if state['trait_policy'] != POLICY:
        raise ValueError('Unknown trait policy for trainer-magic loss')
    return True


def _loss_trait(state, member, config):
    from lab.trait_runtime import POLICY
    form = config['forms'].get(str(member.get('form_id')))
    if form is None:
        return None
    if (state.get('snapshot_id') != config['snapshot_id'] or member.get('trait_policy') != POLICY
            or member.get('trait_id') != form['trait_id']):
        raise ValueError('Trainer-magic trait loss form/source binding changed')
    return str(form['trait_id'])


def _loss_amount(source, config):
    if source == {'kind': 'base', 'rule_version': VERSION}:
        return 1
    if source.get('kind') == 'trait_retaliation.loss':
        proof=source.get('proof')
        validate_retaliation_defeat(proof,config=config)
        extras=_direct_extra_sources(proof,config)
        base=source.get('base_source')
        if (source.get('policy')!=LOSS_POLICY or source.get('config_sha256')!=LOSS_CONFIG_SHA256
                or source.get('extras')!=extras or not isinstance(base,dict)
                or base.get('kind') not in ('base','trait.loss')):
            raise ValueError('Retaliation magic loss differs from its independent trait-defeat proof')
        return _loss_amount(base,config)+sum(item['amount'] for item in extras)
    if source.get('kind') == 'direct_defeat.loss':
        from lab.action_outcome_runtime import validate_direct_defeat
        from lab.trait_runtime import POLICY
        proof = source.get('proof')
        validate_direct_defeat(proof)
        expected = _direct_extra_sources(proof, config)
        base = source.get('base_source')
        if (source.get('policy') != LOSS_POLICY or source.get('config_sha256') != LOSS_CONFIG_SHA256
                or proof.get('trait_policy') != POLICY or proof.get('accounting_scope') != 'victory'
                or source.get('extras') != expected or not expected
                or not isinstance(base, dict) or base.get('kind') not in ('base', 'trait.loss')):
            raise ValueError('Direct-defeat extra magic loss source differs from its proved roles')
        return _loss_amount(base, config) + sum(item['amount'] for item in expected)
    row = config['traits'].get(str(source.get('trait_id')))
    form = config['forms'].get(str(source.get('form_id')))
    if (not row or not form or source.get('kind') != 'trait.loss' or source.get('policy') != LOSS_POLICY
            or source.get('config_sha256') != LOSS_CONFIG_SHA256
            or source.get('source_hash') != row['record_hash']
            or form['trait_id'] != row['trait_id'] or source.get('form_hash') != form['record_hash']
            or source.get('scope') != row['scope']):
        raise ValueError('Trainer-magic loss event has an unreviewed trait source')
    amount = 1
    for component in row['components']:
        if component['op'] == 'loss.add':
            amount += component['amount']
        elif component['op'] == 'loss.set':
            amount = component['amount']
        else:
            raise ValueError('Unknown trainer-magic loss component')
    return max(0, amount)


def _direct_extra_sources(proof, config):
    extras = []
    for role in ('attacker', 'target'):
        row = config.get('direct_defeat_extras', {}).get(str(proof[role]['trait_id']))
        if row and role in row['roles']:
            extras.append({'role': role, 'trait_id': row['trait_id'],
                           'source_hash': row['record_hash'], 'amount': row['amount']})
    return extras


def _knockout_loss_source(state, side, member, config):
    if not _trait_losses_enabled(state):
        return {'kind': 'base', 'rule_version': VERSION}
    tid = _loss_trait(state, member, config)
    other = 'b' if side == 'a' else 'a'
    opposing = state['teams'][other]
    active = opposing['members'][opposing['active_slot']]
    opposing_tid = _loss_trait(state, active, config)
    row = config['traits'].get(tid)
    if row is None:
        base = {'kind': 'base', 'rule_version': VERSION}
    else:
        form = config['forms'][str(member['form_id'])]
        base = {'kind': 'trait.loss', 'trait_id': row['trait_id'], 'source_hash': row['record_hash'],
            'form_id': member['form_id'], 'form_hash': form['record_hash'], 'scope': row['scope'],
            'policy': LOSS_POLICY, 'config_sha256': LOSS_CONFIG_SHA256}
    proof = state.get('knockout_provenance', {}).get(side, {}).get(member['member_id'])
    if proof is not None:
        from lab.action_outcome_runtime import validate_direct_defeat
        validate_direct_defeat(proof)
        if (proof.get('accounting_scope') != 'victory' or proof['target_side'] != side or proof['target']['member_id'] != member['member_id']
                or proof['target']['form_id'] != member['form_id'] or proof['turn'] > state['turn']
                or proof['occurrence'] != state['victory']['knockouts'][side][member['member_id']] + 1):
            # An old proof is not evidence for a later poison/revival knockout.
            proof = None
    retaliation=state.get('trait_defeat_provenance',{}).get(side,{}).get(member['member_id'])
    if retaliation is not None:
        validate_retaliation_defeat(retaliation,config=config)
        if (retaliation['target_side']!=side or retaliation['target']['member_id']!=member['member_id']
                or retaliation['target']['form_id']!=member['form_id'] or retaliation['turn']>state['turn']
                or retaliation['occurrence']!=state['victory']['knockouts'][side][member['member_id']]+1):
            retaliation=None
    if retaliation is not None:
        if proof is not None:
            raise ValueError('Conflicting skill and retaliation defeat proofs for the same knockout occurrence')
        return {'kind':'trait_retaliation.loss','base_source':base,'proof':deepcopy(retaliation),
            'extras':_direct_extra_sources(retaliation,config),'policy':LOSS_POLICY,'config_sha256':LOSS_CONFIG_SHA256}
    if proof is not None:
        extras = _direct_extra_sources(proof, config)
        if extras:
            return {'kind': 'direct_defeat.loss', 'base_source': base, 'proof': deepcopy(proof),
                'extras': extras, 'policy': LOSS_POLICY, 'config_sha256': LOSS_CONFIG_SHA256}
        return base  # A proved different attacker does not inherit the active one's trait.
    for candidate in (tid, opposing_tid):
        if candidate in config['unadapted_traits']:
            raise ValueError('Unadapted trait ' + candidate + ': ' + config['unadapted_traits'][candidate]['reason'])
    return base


def _validate_component_ledger(victory, alive, current_turn):
    ledger = victory['loss_components']
    config = _loss_data()
    if (not isinstance(ledger, dict) or ledger.get('policy') != LOSS_POLICY
            or ledger.get('config_sha256') != LOSS_CONFIG_SHA256
            or not isinstance(ledger.get('baseline'), dict) or not isinstance(ledger.get('events'), list)):
        raise ValueError('Malformed trainer-magic loss component ledger')
    baseline = ledger['baseline']
    counts, magic = deepcopy(baseline.get('knockouts')), deepcopy(baseline.get('magic'))
    if (not isinstance(counts, dict) or set(counts) != set(SIDES)
            or not isinstance(magic, dict) or set(magic) != set(SIDES)):
        raise ValueError('Malformed legacy trainer-magic loss baseline')
    for side in SIDES:
        if (not isinstance(counts[side], dict) or set(counts[side]) != set(alive[side])
                or any(type(v) is not int or v < 0 for v in counts[side].values())
                or type(magic[side]) is not int or magic[side] != max(0, INITIAL_MAGIC - sum(counts[side].values()))):
            raise ValueError('Legacy trainer-magic loss baseline disagrees with its counts')
    previous_turn = 0
    for event in ledger['events']:
        if not isinstance(event, dict) or event.get('side') not in SIDES:
            raise ValueError('Invalid trainer-magic loss event')
        if type(event.get('turn')) is not int or not max(1, previous_turn) <= event['turn'] <= current_turn:
            raise ValueError('Trainer-magic loss event has an invalid observation turn')
        previous_turn = event['turn']
        side, member_id = event['side'], event.get('member_id')
        other = 'b' if side == 'a' else 'a'
        if member_id not in counts[side] or not isinstance(event.get('loss_source'), dict):
            raise ValueError('Trainer-magic loss event member/source changed')
        requested = _loss_amount(event['loss_source'], config)
        if event['loss_source'].get('kind') in ('direct_defeat.loss','trait_retaliation.loss'):
            proof = event['loss_source']['proof']
            if (proof['target_side'] != side or proof['target']['member_id'] != member_id
                    or proof['occurrence'] != counts[side][member_id] + 1 or proof['turn'] > event['turn']):
                raise ValueError('Attributed magic loss proof belongs to a different knockout occurrence')
        expected = {'op': 'victory.knockout', 'occurrence': counts[side][member_id] + 1, 'requested_magic_loss': requested,
            'actual_magic_loss': min(requested, magic[side]), 'magic_before': magic[side],
            'magic_after': magic[side] - min(requested, magic[side]), 'winning_side': other,
            'winning_points_delta': min(requested, magic[side]), 'rule_version': VERSION}
        if any(type(event.get(key)) is not type(value) or event[key] != value for key, value in expected.items()):
            raise ValueError('Trainer-magic loss event amounts or occurrence disagree with its source')
        counts[side][member_id] += 1
        magic[side] = event['magic_after']
    for side in SIDES:
        other = 'b' if side == 'a' else 'a'
        if (counts[side] != victory['knockouts'][side] or type(victory['magic'][side]) is not int
                or victory['magic'][side] != magic[side]
                or type(victory['winning_points'][other]) is not int
                or victory['winning_points'][other] != INITIAL_MAGIC - magic[side]):
            raise ValueError('Trainer-magic counts, source losses and winning points disagree')


def load_victory_rules():
    """Verify the three small source tables and return a compact source binding."""
    documents = {}
    for relative, expected in SOURCE_HASHES.items():
        payload = (ROOT / relative).read_bytes()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("Trainer-magic source changed; review required: " + relative)
        documents[Path(relative).stem] = json.loads(payload)
    pvp = documents["PVP_CONF"][str(PVP_ID)]
    battle = documents["BATTLE_CONF"][str(pvp["battle_config"])]
    depict = documents["BATTLE_GLOBAL_CONFIG"]["battle_solo_depict"]["str"]["text"]
    if (pvp["battle_config"] != BATTLE_CONFIG or pvp["team_num"] != TEAM_SIZE
            or battle["role_available_HP"] != INITIAL_MAGIC or battle["rival_available_HP"] != INITIAL_MAGIC
            or battle["max_round"] != MAX_ROUND
            or "精灵被击败会损耗1点魔力" not in depict
            or "每点魔力损耗会让己方获得1制胜点数" not in depict):
        raise ValueError("Unsupported trainer-magic evidence")
    return {"version": VERSION, "pvp_id": PVP_ID, "battle_config": BATTLE_CONFIG,
            "initial_magic": {"a": INITIAL_MAGIC, "b": INITIAL_MAGIC}, "max_round": MAX_ROUND,
            "source_hashes": dict(SOURCE_HASHES),
            "runtime_version_verified": False,
            "simultaneous_depletion_policy": "unresolved_block",
            "round_limit_policy": "unresolved_block"}


def _members(state):
    result = {}
    if type(state.get("turn")) is not int or state["turn"] < 1:
        raise ValueError("Victory accounting requires a positive integer turn")
    for side in SIDES:
        members = state["teams"][side]["members"]
        if not isinstance(members, list) or not members:
            raise ValueError("Victory accounting requires nonempty teams")
        result[side] = {}
        for member in members:
            member_id, hp = member.get("member_id"), member.get("hp")
            if (not isinstance(member_id, str) or not member_id or member_id in result[side]
                    or type(hp) is not int or hp < 0):
                raise ValueError("Victory accounting requires unique member IDs and nonnegative integer HP")
            result[side][member_id] = hp > 0
    return result


def initialize_victory(state, *, pvp_id=PVP_ID):
    """Enable pinned PVP5001 rules in-place; an existing valid ledger is retained.

    Imported defeated members are an HP baseline, not evidence of prior magic
    loss. Callers importing mid-battle must supply their existing valid ledger.
    """
    if type(pvp_id) is not int or pvp_id != PVP_ID:
        raise ValueError("Only source-bound PVP5001 trainer-magic rules are supported")
    if "victory" in state:
        validate_victory(state)
        return state
    alive = _members(state)
    rules = load_victory_rules()
    state["victory"] = {"rules": rules, "magic": deepcopy(rules["initial_magic"]),
                        "winning_points": {side: 0 for side in SIDES},
                        "observed_alive": alive,
                        "knockouts": {side: {key: 0 for key in alive[side]} for side in SIDES}}
    return state


def validate_victory(state):
    """Validate an enabled ledger; absent ledger is a compatible legacy state."""
    if "victory" not in state:
        return
    alive = _members(state)
    victory = state["victory"]
    rules = {"version": VERSION, "pvp_id": PVP_ID, "battle_config": BATTLE_CONFIG,
             "initial_magic": {"a": INITIAL_MAGIC, "b": INITIAL_MAGIC}, "max_round": MAX_ROUND,
             "source_hashes": SOURCE_HASHES, "runtime_version_verified": False,
             "simultaneous_depletion_policy": "unresolved_block", "round_limit_policy": "unresolved_block"}
    if not isinstance(victory, dict) or victory.get("rules") != rules:
        raise ValueError("Victory state is not bound to the reviewed trainer-magic rules")
    for field in ("magic", "winning_points", "observed_alive", "knockouts"):
        if not isinstance(victory.get(field), dict) or set(victory[field]) != set(SIDES):
            raise ValueError("Invalid trainer-magic ledger: " + field)
    for side in SIDES:
        observed, counts = victory["observed_alive"][side], victory["knockouts"][side]
        if (not isinstance(observed, dict) or not isinstance(counts, dict)
                or set(observed) != set(alive[side]) or set(counts) != set(alive[side])
                or any(type(v) is not bool for v in observed.values())
                or any(type(v) is not int or v < 0 for v in counts.values())):
            raise ValueError("Trainer-magic member ledger changed or is invalid")
        magic = victory["magic"][side]
        other = "b" if side == "a" else "a"
        points = victory["winning_points"][other]
        if 'loss_components' not in victory and (type(magic) is not int or magic != max(0, INITIAL_MAGIC - sum(counts.values()))
                or type(points) is not int or points != INITIAL_MAGIC - magic):
            raise ValueError("Trainer-magic loss and winning-point ledger disagree")
    if 'loss_components' in victory:
        _validate_component_ledger(victory, alive, state['turn'])


def reconcile_knockouts(state):
    """Count new observed living->zero edges once; observing revival rearms them."""
    if "victory" not in state:
        return []
    validate_victory(state)
    # A late unresolved attribution cannot leave earlier edges half-accounted.
    current = {**state, 'victory': deepcopy(state['victory'])}
    alive, victory, events = _members(state), current['victory'], []
    enabled = _trait_losses_enabled(state)
    config = _loss_data() if enabled or 'loss_components' in victory else None
    if enabled and 'loss_components' not in victory:
        victory['loss_components'] = {'policy': LOSS_POLICY, 'config_sha256': LOSS_CONFIG_SHA256,
            'baseline': {'knockouts': deepcopy(victory['knockouts']), 'magic': deepcopy(victory['magic'])},
            'events': []}
    for side in SIDES:
        other = "b" if side == "a" else "a"
        for member_id, living in alive[side].items():
            if victory["observed_alive"][side][member_id] and not living:
                before = victory["magic"][side]
                member = next(m for m in state['teams'][side]['members'] if m['member_id'] == member_id)
                source = _knockout_loss_source(state, side, member, config) if enabled else {'kind': 'base', 'rule_version': VERSION}
                requested = _loss_amount(source, config) if config is not None else 1
                loss = min(requested, before)
                victory["magic"][side] -= loss
                victory["winning_points"][other] += loss
                victory["knockouts"][side][member_id] += 1
                event = {"op": "victory.knockout", "side": side, "member_id": member_id,
                               "occurrence": victory["knockouts"][side][member_id],
                               "magic_before": before, "magic_after": before - loss,
                               "winning_side": other, "winning_points_delta": loss,
                               "rule_version": VERSION}
                if 'loss_components' in victory:
                    event.update(turn=state['turn'], requested_magic_loss=requested, actual_magic_loss=loss, loss_source=source)
                    victory['loss_components']['events'].append(deepcopy(event))
                events.append(event)
            victory["observed_alive"][side][member_id] = living
    validate_victory(current)
    state['victory'] = victory
    return events


def terminal(state, *, completed_turn=False):
    """Read the enabled ledger, returning explicit terminal/winner/blockers.

    ``completed_turn`` means all supported phases of ``state['turn']`` have
    completed. Turn 50 may execute; adjudication at its end is not recovered.
    A blocked terminal boundary has ``terminal=True`` and ``winner=None``.
    """
    result = {"terminal": False, "winner": None, "blockers": [], "reason": None}
    if "victory" not in state:
        return result
    validate_victory(state)
    victory = state["victory"]
    exhausted = [side for side in SIDES if victory["magic"][side] == 0]
    if len(exhausted) == 2:
        result.update(terminal=True, reason="simultaneous_magic_depletion",
                      blockers=["Simultaneous trainer-magic depletion adjudication is unresolved; no winner inferred"])
    elif exhausted:
        result.update(terminal=True, reason="trainer_magic_depleted",
                      winner="b" if exhausted[0] == "a" else "a")
    elif state["turn"] > victory["rules"]["max_round"] or (completed_turn and state["turn"] >= victory["rules"]["max_round"]):
        result.update(terminal=True, reason="round_limit",
                      blockers=["Turn 50 limit reached; round-limit adjudication is unresolved; no winner inferred"])
    else:
        depleted = [side for side,values in _members(state).items() if not any(values.values())]
        if len(depleted)==1:
            result.update(terminal=True,reason='roster_exhausted',winner='b' if depleted[0]=='a' else 'a',
                          source='user_confirmation_20261030_last_living_exhausted_even_pending_revival')
        elif len(depleted)==2:
            result.update(terminal=True,reason='simultaneous_roster_exhaustion',
                          blockers=['Simultaneous last-member exhaustion adjudication remains unresolved'])
    return result



_RETALIATION_FIELDS=('op','source_trait_id','source_hash','config_sha256','policy','actor_side',
    'actor_member_id','actor_form_id','target_side','target_member_id','target_form_id',
    'before','after','damage','power','damage_kind','damage_type','stab','type_multiplier',
    'turn','token','can_trigger_retaliation')


def _retaliation_roles(event,config):
    from lab.action_outcome_runtime import _data as action_sources,_identity
    from lab.trait_runtime import POLICY as TRAIT_POLICY
    from lab.trait_switch_components import retaliation_source
    if not isinstance(event,dict) or any(field not in event for field in _RETALIATION_FIELDS):
        raise ValueError('Retaliation defeat requires the complete audited direct-event receipt')
    source=config.get('retaliation_defeat_sources',{}).get(str(event.get('source_trait_id')))
    if source is None or event['op']!='trait.retaliation' or event['source_hash']!=source['record_hash']:
        raise ValueError('Unreviewed trait cannot claim a retaliation defeat')
    if (event['actor_side'] not in SIDES or event['target_side']!=('b' if event['actor_side']=='a' else 'a')
            or type(event['turn']) is not int or event['turn']<1 or not isinstance(event['token'],str) or not event['token']
            or any(type(event[key]) is not int for key in ('before','after','damage'))
            or event['before']<=0 or event['after']!=0 or event['damage']!=event['before']):
        raise ValueError('Trait defeat requires an opposing direct living-to-zero HP receipt')
    for key in ('power','damage_kind','damage_type','stab','type_multiplier','can_trigger_retaliation'):
        if event[key]!=source[key]:raise ValueError('Retaliation damage profile differs from the audited trait')
    native=action_sources()
    attacker=_identity({'member_id':event['actor_member_id'],'form_id':event['actor_form_id'],
        'trait_id':event['source_trait_id']},native)
    target=_identity({'member_id':event['target_member_id'],'form_id':event['target_form_id']},native)
    receipt=retaliation_source({**attacker,'trait_policy':TRAIT_POLICY,'trait_source_hash':source['record_hash']})
    if (receipt is None or event['config_sha256']!=receipt['config_sha256'] or event['policy']!=receipt['policy']):
        raise ValueError('Retaliation component version or exact owner source changed')
    return attacker,target


def validate_retaliation_defeat(proof,*,config=None):
    config=_loss_data() if config is None else config
    if (not isinstance(proof,dict) or proof.get('policy')!=RETALIATION_POLICY
            or proof.get('config_sha256')!=LOSS_CONFIG_SHA256
            or proof.get('proof_hash')!=fingerprint({k:v for k,v in proof.items() if k!='proof_hash'})
            or type(proof.get('occurrence')) is not int or proof['occurrence']<1):
        raise ValueError('Invalid independent trait-retaliation defeat proof')
    attacker,target=_retaliation_roles(proof.get('damage_event'),config)
    event=proof['damage_event']
    if (proof.get('attacker')!=attacker or proof.get('target')!=target
            or proof.get('attacker_side')!=event['actor_side'] or proof.get('target_side')!=event['target_side']
            or proof.get('turn')!=event['turn'] or proof.get('action_token')!=event['token']
            or proof.get('accounting_scope')!='victory'):
        raise ValueError('Retaliation defeat roles or knockout occurrence source changed')
    return True


def record_retaliation_defeat(state,event):
    """Record a committed thorns KO; a zero-HP source can finish its final retaliation.

    Call after the real event enters owned world state and before the ordinary
    knockout observer. This function never subtracts magic or invents a skill.
    """
    if not isinstance(event,dict) or event.get('op')!='trait.retaliation' or event.get('after')!=0:
        return []
    config=_loss_data()
    attacker,target=_retaliation_roles(event,config)
    if not _trait_losses_enabled(state) or 'victory' not in state:
        raise ValueError('Retaliation KO attribution requires the enabled owned victory ledger')
    validate_victory(state)
    if event['turn']!=state['turn']:
        raise ValueError('Retaliation receipt belongs to another battle turn')
    current={}
    for role,side,identity in (('attacker',event['actor_side'],attacker),('target',event['target_side'],target)):
        member=next((m for m in state['teams'][side]['members'] if m['member_id']==identity['member_id']),None)
        if member is None or member['form_id']!=identity['form_id'] or member.get('trait_id')!=identity['trait_id']:
            raise ValueError('Retaliation receipt member differs from the committed world')
        current[role]=member
    if current['target']['hp']!=0:
        raise ValueError('Retaliation defeat target is not actually exhausted')
    semantic={key:deepcopy(event[key]) for key in _RETALIATION_FIELDS}
    event_hash=fingerprint(semantic)
    key=fingerprint({'turn':event['turn'],'member_id':attacker['member_id'],'token':event['token']})
    tokens=state.get('retaliation_defeat_tokens',{})
    if not isinstance(tokens,dict):raise ValueError('Retaliation defeat token ledger malformed')
    if key in tokens:
        if tokens[key]!=event_hash:raise ValueError('Retaliation token reused for a different direct packet')
        return []
    side=event['target_side'];mid=target['member_id']
    if not state['victory']['observed_alive'][side][mid]:
        raise ValueError('Retaliation KO must be an uncounted living-to-zero occurrence')
    proof={'policy':RETALIATION_POLICY,'config_sha256':LOSS_CONFIG_SHA256,'turn':state['turn'],
        'action_token':event['token'],'attacker_side':event['actor_side'],'target_side':side,
        'attacker':attacker,'target':target,'damage_event':semantic,'accounting_scope':'victory',
        'occurrence':state['victory']['knockouts'][side][mid]+1}
    proof['proof_hash']=fingerprint(proof)
    validate_retaliation_defeat(proof,config=config)
    old=state.get('trait_defeat_provenance',{}).get(side,{}).get(mid)
    if old and old.get('occurrence')==proof['occurrence'] and old!=proof:
        raise ValueError('Conflicting retaliation proofs for the same knockout occurrence')
    state.setdefault('trait_defeat_provenance',{}).setdefault(side,{})[mid]=proof
    state.setdefault('retaliation_defeat_tokens',{})[key]=event_hash
    return [{'op':'trait.retaliation_defeat','proof':deepcopy(proof)}]
