"""Read-only scoped admission audit; description tags are indexing, not execution."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lab.action_mechanics import GENERATORS
from lab.phase_config import fingerprint
from lab.prepared_rules import PreparedRules
from lab.runtime_capabilities import inspect_program
from lab.runtime_programs import reviewed_programs
from lab.server import load_catalog

TAGS = {'release_count': ('使用次数', '额外释放'), 'departure_entry': ('脱离', '返场', '离场', '入场'),
    'slot_bundle': ('位置', '携带技能', '携带的技能', '相邻', '两侧技能'), 'delayed': ('回合结束', '下回合'),
    'history': ('每次使用', '每使用', '永久', '每击败', '每次击败', '每应对', '每先于'), 'charge': ('蓄力',)}

REMAINING = {
    7020810: ('defense_composition', 'Absorbed damage to HP plus permanent own cost; requires mitigation outcome hook, not ordinary flat restore.'),
    7021160: ('interrupt_stun_composition', 'Defense-response interrupt plus next-turn stun lifecycle; existing interrupt gate was status-specific.'),
    7021230: ('choice_history_composition', 'Choice branch must retain permanent growth versus response power; choice/runtime owner.'),
    7030270: ('interrupt_stun_composition', 'Flat hit bonus is reusable, but defense-response interrupt and next-turn stun remain whole-description requirements.'),
    7060120: ('source_selector_gap', 'damage_rule5 dam_para[60,-1,0,0,30,1,0]; distinct skill/type versus repeated uses selector not decoded.'),
    7070030: ('adjacent_power_expression', 'Sum adjacent skill power/3 plus transmission; edge selector and whether dynamic power history/aura counts require a source-bound adjacent power query.'),
    7070020: ('source_installation_gap', 'Use installs21060020/106 then three21080281/108; per-turn position snapshot and exact grant layers unresolved, not initial carried passive.'),
    7070060: ('slot_modifier_composition', 'Persistent growing adjacent discount needs source-bound per-target-slot modifiers and edge-neighbor selector; existing global skill-ID discounts differ.'),
    7070070: ('slot_modifier_composition', 'Adjacent slot power+20/+30 needs per-slot source target identity across movement and the edge selector.'),
    7070080: ('slot_modifier_composition', 'Defense response adjacent permanent cost-1 requires the same per-slot modifier target contract.'),
    7070200: ('adjacent_power_expression', 'Quarter adjacent power difference plus transmission; directional/absolute difference, edge selector and dynamic power query must be explicit.'),
    7070250: ('slot_modifier_composition', 'Growing adjacent power aura plus transmission needs per-slot modifier target contract and edge selector.'),
    7070290: ('cross_member_identity_gap', 'Cross-member one-slot rotation splits original bundles; current original-owner identity supports whole bundles only. Requires per-slot origin migration, not dropping histories.'),
    7100250: ('charge_action_admission', 'Defense usable during charge requires selected-action admission without discarding pending charge; cannot be replaced by next-charge bypass alone.'),
    7100300: ('charge_choice_stun_composition', 'During-charge alternate action, choice, defense interrupt and next-turn stun all need the full composite contract.'),
    7110350: ('whole_release_dispatch_gap', '20930100/93 ->21080090/108; historical108 says consecutive skill release+1, not hit+1. See release-count-sources.'),
    7110360: ('whole_action_dispatch_gap', '20171061/17 ->20150070/15 says next extra cast and historical15 says act twice; return is reusable but cannot admit only that prefix.'),
    7110380: ('whole_release_dispatch_gap', '20730110/73 ->20640560/64 ->21080091/108; departure growth source known, release payment/hooks dispatch still missing.'),
    7110420: ('whole_action_dispatch_gap', 'Defense response grants next-turn selected skill extra use; same15 dispatch boundary as overload.'),
    7110460: ('burst_history_copy_gap', 'Requires actual previously-triggered burst effect history and copied-effect replay pool, not just first-action predicate or return.'),
    7130220: ('incoming_defense_composition', 'Response21120010/base2112001 opcode112 parameter791337 matches BATTLE_GLOBAL_CONFIG.yanhu_buff112; the new-entry transfer algorithm/window remains unread, not a missing ordinary guard buff.'),
    7150320: ('whole_release_dispatch_gap', 'Replay actual past Swift releases plus sum-cost/2 and own cost growth; whole-skill release queue and retained Swift source trace needed.'),
    7150360: ('choice_history_composition', 'Choice between permanent own power and hits; branch-specific source history required.'),
    7150370: ('choice_duration_composition', 'Choice between current cost discount and defense-response permanent whole skill power; cannot make temporary default permanent.'),
    7160170: ('external_menghua_formula', 'Menghua conversion lifecycle/source semantics intentionally remain unresolved; outside slot/history implementation.'),
    7160180: ('external_menghua_formula', 'Same Menghua lifecycle boundary; do not admit only cost prefix.'),
    7160250: ('external_menghua_formula', 'Same Menghua lifecycle boundary; do not admit only three-hit prefix.'),
    7160400: ('choice_random_history_composition', 'Count committed choice uses, three random stat layers per use, then reset; random-stat/choice owners.'),
    7170310: ('choice_random_history_composition', 'Same choice-use count/reset with opponent random debuffs; random-stat/choice owners.'),
    7180190: ('root_in_progress', 'Root owns detach plus response enemy attack-skill cost+4; excluded from parallel edits.'),
    7190310: ('external_starmark_formula', 'Star-mark lifecycle/numeric trigger boundary; permanent grant-stack history alone cannot admit whole skill.'),
    7190490: ('external_form_transition', 'Next entrant forced Moonfall state needs complete form/stat/skill/source transition; no partial form-name substitution.'),
}


def audit():
    prepared = PreparedRules(load_catalog()[0])
    overrides = reviewed_programs(prepared)
    missing, scope = [], []
    for key, record in prepared._rules._catalog['moves'].items():
        mid = int(key)
        program = overrides.get(mid, prepared._rules.program(mid))
        capability = inspect_program(program)
        if capability['supported']:
            continue
        tags = [name for name, words in TAGS.items() if any(word in record['desc']['zh'] for word in words)]
        classification, reason = REMAINING.get(mid, ('outside_scope', 'No reviewed composable implementation in the current merged program registry.'))
        if mid in GENERATORS:
            classification, reason = 'dynamic_original_excluded', 'Runtime-generated candidate is checked after draw; original generator is not an unimplemented ordinary executable skill.'
        entry = {'skill_id': mid, 'name': record['name']['zh'], 'description': record['desc']['zh'],
            'record_hash': fingerprint(record), 'record': record, 'tags': tags, 'classification': classification,
            'reason': reason, 'blockers': capability['blockers']}
        missing.append(entry)
        if tags or mid in GENERATORS:
            scope.append(entry)
    return {'snapshot_id': prepared.snapshot_id, 'catalog_hash': prepared.catalog_content_hash,
        'reviewed_overrides': len(overrides), 'all_unadmitted_count': len(missing),
        'all_non_dynamic_unadmitted_count': len([r for r in missing if r['classification'] != 'dynamic_original_excluded']),
        'scope_non_dynamic_unadmitted_count': len([r for r in scope if r['classification'] != 'dynamic_original_excluded']),
        'dynamic_originals_excluded': sorted(GENERATORS), 'scope_unadmitted': scope}


if __name__ == '__main__':
    data = audit()
    path = ROOT / 'docs/verification/switch-slot-history-remaining-20261026.json'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    lines = ['# 当前换人、槽位与历史剩余项', '', '运行 `python scripts/audit_switch_slot_history.py` 可按当前合并程序刷新。标签仅用于离线审计，不参与运行时句子识别。', '',
        f"原始准入扫描：全目录 {data['all_unadmitted_count']} 项，本范围 {len(data['scope_unadmitted'])} 项；排除借用/取念/复写原技能后分别为 {data['all_non_dynamic_unadmitted_count']} / {data['scope_non_dynamic_unadmitted_count']} 项。其他组并发修改可能使快照随后变化。", '',
        '| 技能 | 分类 | 具体依据或缺口 |', '|---|---|---|']
    lines += [f"| {r['skill_id']} {r['name']} | {r['classification']} | {r['reason']} |" for r in data['scope_unadmitted']]
    (path.with_suffix('.md')).write_text('\n'.join(lines) + '\n', encoding='utf8')
    print(json.dumps({'all_unadmitted': data['all_unadmitted_count'], 'scope': len(data['scope_unadmitted']),
        'classified': sorted(set(r['classification'] for r in data['scope_unadmitted']))}, ensure_ascii=False))
