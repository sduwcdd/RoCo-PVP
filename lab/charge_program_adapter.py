"""Load-time, source-bound pure charge-release overlays for research turns.

Whole BWIKI descriptions and term 1007 are covered by a phase + payload split.
Game fields corroborate the payload; their entire buff graph is NOT interpreted.
No active rule bundle is edited and no combat-time natural language is parsed.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json

from lab.action_rules import ActionRules
from lab.game_runtime_defaults import ROOT, SOURCE_HASHES
from lab.phase_config import fingerprint, load_phase_config

VERSION = "bwiki-pure-charge-release-1"
SKILLS_SHA256 = '58ec4e67d14ff9bdaab615e2b32d8bede0fd3b7180dc2e33179047bcd8803de5'
NORMALIZED_SKILLS_SHA256 = 'eae107c786441217977d76f5a52a3340801433ce5349300fac62cc7e1022817b'
_BASE = "artifacts/unpack_probe_20261025/battle_analysis/tables/parsed/"
# Entire sentences, not removed prefixes or permissive suffix matching.
_SENTENCES = {
    "蓄力，对敌方造成魔法伤害。": "magical",
    "蓄力，对敌方造成物理伤害。": "physical",
    "蓄力，造成魔伤。": "magical",
    "蓄力，造成物伤。": "physical",
}


def _game_sources(verify):
    tables, hashes = {}, {}
    for name in ("SKILL_CONF", "BUFF_CONF", "BUFFBASE_CONF", "EFFECT_CONF"):
        relative = _BASE + name + ".json"
        raw = (ROOT / relative).read_bytes()
        hashes[relative] = hashlib.sha256(raw).hexdigest()
        if verify and hashes[relative] != SOURCE_HASHES[relative]:
            raise ValueError("Charge comparison game source changed: " + relative)
        tables[name] = json.loads(raw)
    return tables, hashes


def load_charge_program_overrides(catalog, *, verify_game_sources=True):
    """Return int-ID -> trusted release program for the pinned source snapshot.

    Pass the mapping to research_phases program_overrides. Its ActionRules
    phase remains responsible for setup, release readiness and leave immunity.
    This is not a full standalone charged skill execution contract.
    """
    catalog = deepcopy(catalog)
    if (catalog.get("provenance", {}).get("Skills", {}).get("content_sha256") != SKILLS_SHA256
            or fingerprint(catalog.get("moves")) != NORMALIZED_SKILLS_SHA256):
        raise ValueError("Charge skill source snapshot changed; review required")
    # Verifies the complete charge term and the reviewed phase source binding.
    ActionRules(catalog)
    phase = load_phase_config(catalog)
    tables, hashes = _game_sources(verify_game_sources)
    values = catalog["moves"].values() if isinstance(catalog["moves"], dict) else catalog["moves"]
    overlays = {}
    for record in values:
        mid = record["id"]
        charge = phase["skills"][str(mid)]["charge"]
        if not charge["declared"]:
            continue
        description = record.get("desc", {}).get("zh")
        kind = _SENTENCES.get(description)
        if (kind is None or record.get("kind") != kind or record.get("desc_notes") != [1007]
                or record.get("effect_details") or type(record.get("power")) is not int
                or record["power"] <= 0 or type(record.get("energy")) is not int
                or record["energy"] < 0):
            continue  # Extra conditions/effects stay unsupported in their entirety.
        game = tables["SKILL_CONF"].get(str(mid))
        if (not game or game.get("dam_para") != [record["power"]]
                or game.get("energy_cost") != [record["energy"]]
                or game.get("damage_type") != {"magical": 3, "physical": 2}[kind]
                or game.get("cd_round") != [0, 0]
                or game.get("skill_result") != [{"effect_id": 20880010, "cast_moment": 25}]):
            raise ValueError("Pure charge payload and game numeric/result fields differ; review required")
        buff = tables["BUFF_CONF"]["20880010"]
        bases = [tables["BUFFBASE_CONF"][str(k)] for k in buff["buff_base_ids"]]
        referenced_effects = [tables["EFFECT_CONF"][str(row["buffbase_param"][0]["params"][0])]
                              for row in bases if row["buffbase_order"] == 17]
        term = next(t for t in catalog["glossary"] if t["key"] == 1007)
        evidence = {
            "basis": "complete_bwiki_description_and_phase_config_with_game_numeric_comparison",
            "record_raw": deepcopy(record), "record_hash": fingerprint(record),
            "phase_charge": deepcopy(charge), "phase_config_hash": fingerprint(phase),
            "term_1007": deepcopy(term), "game_source_hashes": hashes,
            "game_source_hashes_verified": all(hashes[k] == SOURCE_HASHES[k] for k in hashes),
            "game_skill_raw": deepcopy(game), "game_charge_buff_raw": deepcopy(buff),
            "game_charge_bases_raw": deepcopy(bases), "game_referenced_effects_raw": deepcopy(referenced_effects),
            "game_buff_graph_fully_interpreted": False, "game_runtime_version_verified": False,
            "charge_phase_owner": "reviewed_phase_config_and_ActionRules_charge_transition",
            "unresolved_game_semantics": [
                "cast_moment=25 is retained, not promoted to authoritative scheduling.",
                "Buff 20880010 includes base 2088001/opcode88 and additional immunity/effect bases; their complete runtime semantics are not claimed.",
                "The overlay covers the whole BWIKI sentence via phase metadata plus release damage, not every game-file buff handler.",
            ],
        }
        program = {
            "game_id": mid, "name": record["name"]["zh"], "category": "skill",
            "compiler_version": VERSION, "snapshot_id": catalog["snapshot_id"],
            "source_version": catalog.get("source_version"), "source_hash": fingerprint(record),
            "source_description": description, "source_details": {"desc_notes": [1007]},
            "source": {k: deepcopy(record[k]) for k in ("wiki_id", "source_url", "source_module")},
            "static_fields": {k: deepcopy(record[k]) for k in ("kind", "type", "power", "energy")},
            "skill_source": deepcopy(catalog["provenance"]["Skills"]),
            "term_source": deepcopy(catalog["provenance"]["Terms"]),
            "status": "compiled", "blockers": [], "dependency_ids": [1007],
            "operations": [{"op": "damage", "params": {"target": "opponent", "kind": kind,
                            "power": record["power"], "type": record["type"]}}],
            "order_semantics": "release_payload_after_source_bound_charge_phase_experiment",
            "execution_scope": "charge_release_payload_requires_external_charge_phase",
            "executable": False, "real_game_verified": False, "training_eligible": False,
            "whole_game_skill_verified": False, "charge_adapter_evidence": evidence,
            "execution_blockers": ["Requires the explicit research charge phase and damage resolver; game fidelity is unverified."],
        }
        program["charge_adapter_program_sha256"] = fingerprint(program)
        overlays[mid] = program
    from lab.charge_runtime import component_programs
    overlays.update(component_programs(catalog, tables, hashes, phase))
    return overlays


def validate_charge_program_overrides(catalog, programs):
    """Reject modified programs/sources at the loading boundary."""
    if programs != load_charge_program_overrides(catalog):
        raise ValueError("Charge program overlay differs from source-bound compilation")
    return True



@lru_cache(maxsize=2)
def _jealousy_prepared(snapshot_id):
    # Reuse the current HUD snapshot once, not a separate damage or charge engine.
    from lab.live_damage import _rules
    from lab.prepared_rules import PreparedRules
    catalog,_ = _rules()
    if catalog['snapshot_id']!=snapshot_id:
        raise ValueError('Jealousy release differs from current shared snapshot')
    return PreparedRules(catalog)


def jealousy_release_metadata(prepared,member,skill_id,*,slot,turn):
    """Bind a selected charged payload to the actual prior charge without forging history."""
    from lab.prepared_rules import prepare_rules
    from lab.trait_runtime import _confirmed_member,permits_member_skill_while_charging
    prepared=prepare_rules(prepared)
    row=_confirmed_member(member)
    if row is None or row['trait_id']!=200174:
        raise ValueError('Cross-skill charge release requires the real sourced Jealousy trait')
    if prepared._rules.form(member['form_id']).get('trait_id')!=200174:
        raise ValueError('Jealousy trait does not belong to its exact current form')
    if not permits_member_skill_while_charging(prepared,member,slot):
        raise ValueError('Jealousy release must select another actual carried charge slot')
    if member['skill_slots'][slot]!=skill_id:
        raise ValueError('Jealousy selected skill does not match its carried slot')
    phases=prepared._components()[1]
    if not phases.requires_charge(skill_id):
        raise ValueError('Cross-charge payload requires a genuinely charged selected skill')
    charge=member['charge']
    transition=phases.charge_transition(charge,current_turn=turn,slot=charge['slot'],skill_id=charge['skill_id'])
    if transition['status']!='ready':
        raise ValueError('Prior Jealousy charge is not ready in its actual source-bound release window')
    identity=phases.charge_state(charge['slot'],charge['skill_id'],charge['started_turn'])
    out={'policy':'user_confirmed_jealousy_shared_charge_consume_after_success_20261030',
        'member_id':member['member_id'],'form_id':member['form_id'],'trait_id':200174,
        'trait_source_hash':row['record_hash'],'source_charge':identity,
        'selected_skill_id':skill_id,'selected_skill_hash':fingerprint(prepared._rules.skill(skill_id)),
        'selected_slot':slot,'turn':turn,'consume':'after_successful_selected_skill_commit',
        'attack_observations':'actual_prior_charge_only_no_selected_skill_setup_fabricated'}
    out['record_hash']=fingerprint(out)
    return out


def validate_jealousy_release(program,member,context):
    supplied=context.get('jealousy_release')
    if not isinstance(supplied,dict):
        raise ValueError('Jealousy release requires its complete selected-slot and prior-charge proof')
    prepared=_jealousy_prepared(program['snapshot_id'])
    expected=jealousy_release_metadata(prepared,member,program['game_id'],slot=context.get('selected_skill_slot'),turn=context.get('turn'))
    if supplied!=expected or program['source_hash']!=expected['selected_skill_hash']:
        raise ValueError('Jealousy prior charge, selected payload or source proof changed')
    return expected
