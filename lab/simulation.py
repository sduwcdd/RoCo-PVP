"""Human-facing simulation adapter over the existing source-bound rule engine.

The profile is an explicit, uncalibrated experiment. Observations and templates
are never written here. Every request owns its state; no global battle is kept.
"""
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from threading import Lock

from lab.prepared_rules import PreparedRules
from lab.ruleset import canonical_hash
from lab.trait_runtime import query_scope
from lab.numeric_candidates import arena_stat60
from lab.pvp_rules import PROFILE_ID, DEFAULT_SETTINGS, TEAM_SIZE
from lab.research_api import _sources
from lab.game_skill_adapter import experimental_game_policy
from lab.research_phases import (POLICY_V2, build_research_context_v2,
    execute_research_turn_v2, choose_research_replacements_v2, _devotion_seed)

PROFILE = PROFILE_ID
ENGINE_REVISION = "composable-battle-20261104-bwiki-authority-1"
PATCH2 = "resource-group-c40d72d37c3c43a12b3f"
DIMS = ("hp", "patk", "matk", "pdef", "mdef", "spd")
MODIFIERS = {0: None, 1: "hp", 2: "patk", 3: "matk", 4: "pdef", 5: "mdef", 6: "spd"}
_CHARGE_CACHE = {}
_CHARGE_LOCK = Lock()
ASSUMPTIONS = [
    "核心魔法独立于普通行动，仅作用于在场精灵；愿力、进化和光合接入用户2026-10-30确认规则；特殊信物、未知目标及无法绑定的新特性仍具体阻断。",
    "节流术需明确选择目标不存在钻地、静止、拟态的实验假设；缺少声明保持未知，不自动视为无状态；仅支持已核实水系类型的目标，水血脉单独条件尚未适配。",
    "历史补丁2可解释的纯效果使用对应文件，其余保留BWIKI已发布规则；每项显示来源，不代表线上版本相同。",
    "天气模块在两种资料模式下均使用解包结构化配置；先后顺序按回合开始天气，费用和伤害按实际行动时天气，含设置当回合共8次回合末结算，精确时序待校准。",
    "面板估算使用60级五星社区候选；选中个体按显示值×6输入，未填写项按无额外加成试算，不补写原配置。",
    "未填写性格时只作中性面板试算；请在准备页按游戏实际面板修正。",
    "伤害固定复用当前HUD共享查询，本系1.25、每段完整威力；未知状态或未支持投影会明确阻断，仍未全量实战校准。",
    "中毒/灼烧试算为最大生命×描述比例×层数、向下取整；烧层数衰减向下取整，不额外乘属性倍率。",
    "普通开局能量为10；精灵能量上限采用输入的max_energy，缺失时按客户端GetMaxEnergy回退10，特殊运行时上限仍以同步值为准。",
    "双方六只精灵采用解包PVP5001的4点魔力胜负；不足六只为独立机制试验，以全队力竭结束。50回合与同时魔力耗尽的裁定尚待文件核实。",
    "普通/天气冻结共用阈值；寄生按施加者绑定、最大生命每层2%向下取整，施加者在后备仍可恢复，精确接收人和层数算法待校准。",
    "防御减伤在生命裁剪前计算；使用后公共冷却覆盖下一回合。能耗、吸血、禁足由组件执行，持续期包含施加当回合；均有命名研究策略。",
    "已适配特性复用入场、离场、技能后、蓄力与回合末事件；费用条件按静态基础能耗，威力先加后乘，多来源与事件先后采用明确研究策略。",
    "印记跟随队伍继承，传动在选槽前准备；棘刺、毒印记等百分比以最大生命为研究基数。萌芽按10%属性增益一层组合，无法对应层数时阻断。星陨伤害仍未确定；暗涌完整五项池已接入，其中速度是平值降低10，其余四项是10%。传动与生成、巧变、蓄力共享槽位身份迁移，执行时序仍属实验策略。",
    "巧变与永久复制保留本局槽位来源，临时巧变使用后恢复。生成候选不筛掉未实现技能、不重抽；选中未支持结果会显示具体阻断。",
    "随机奉献与暗涌分别使用文件中的完整五候选池，以种子0独立均匀有放回抽取；这不是已校准游戏概率。",
    "生命代能按缺少能量×最大生命5%合计下取整；致死或取整为零的边界暂阻断。连击数先加后乘、最低1，威力按共享HUD每段完整威力策略。",
    "未执行全部特性、核心魔法、印记及全部触发；不进入正式训练。",
]


def _integer(value, label, lo=0, hi=1_000_000):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{label}必须为{lo}–{hi}的整数")
    return value


def settings(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_SETTINGS) or value.get("profile_id") != PROFILE:
        raise ValueError("请选择完整的本地试战规则版本")
    out = deepcopy(value)
    if out != DEFAULT_SETTINGS or any(type(out[key]) is not type(default) for key, default in DEFAULT_SETTINGS.items()):
        raise ValueError("当前PVP规则固定使用共享HUD版本；旧公式或自定义规则请重建局面")
    return out


@lru_cache(maxsize=1)
def _file_programs():
    adapter = _sources()
    policy = experimental_game_policy(PATCH2)
    report = adapter.coverage(PATCH2, policy)
    return {int(mid): adapter.compile(PATCH2, int(mid), policy) for mid in report["supported_ids"]}


def _file_static_matches(program, skill):
    """Historical effects cannot override current BWIKI cost or base damage."""
    if program.get("research_action_fields", {}).get("base_energy_cost") != skill.get("energy"):
        return False
    for operation in program.get("operations", []):
        if operation.get("op") in ("damage", "damage.sequence"):
            params = operation.get("params", {})
            if any(params.get(key) != skill.get(key) for key in ("power", "kind", "type")):
                return False
    return True


def _programs(prepared, selected, ids):
    ids = tuple(ids)
    available = _file_programs() if selected["source_mode"] == "patch2_components_then_bwiki" else {}
    from lab.charge_program_adapter import load_charge_program_overrides
    with _CHARGE_LOCK:
        key = prepared.catalog_content_hash
        if key not in _CHARGE_CACHE:
            loaded = load_charge_program_overrides(prepared._rules._catalog)
            _CHARGE_CACHE.clear()
            _CHARGE_CACHE[key] = loaded
        charge_programs = _CHARGE_CACHE[key]
    from lab import weather_runtime
    weather_programs = {**weather_runtime.weather_programs(prepared), **weather_runtime.weather_attack_programs(prepared)}
    from lab.runtime_programs import reviewed_programs
    from lab.mark_runtime import blocked_mark_programs
    from lab.runtime_capabilities import inspect_program
    reviewed = {**blocked_mark_programs(prepared), **reviewed_programs(prepared, ids)}
    overrides, info = {}, {}
    for mid in sorted(set(ids) - {0}):
        skill = prepared._rules.skill(mid)
        use_file = mid in available and _file_static_matches(available[mid], skill)
        program = deepcopy(available[mid]) if use_file else deepcopy(charge_programs[mid]) if mid in charge_programs else prepared._rules.program(mid)
        if use_file:
            overrides[mid] = program
            cost = program["research_action_fields"]["base_energy_cost"]
            source = "解包补丁2（历史规则试验）"
        else:
            cost = skill.get("energy")
            source = "蓄力规则适配（BWIKI及文件数值对照）" if mid in charge_programs else "BWIKI结构化规则"
            if mid in charge_programs:
                overrides[mid] = program
        if mid in reviewed:
            program = reviewed[mid]
            overrides[mid] = program
            cost = skill["energy"]
            source = "来源绑定的通用机制配置（未实战校准）"
        if mid in weather_programs:
            program = weather_programs[mid]
            overrides[mid] = program
            setter = weather_runtime.rules()["setters"].get(str(mid))
            if setter:
                cost = setter["energy_cost"]
            source = "解包天气配置与BWIKI技能数据（未实战校准）"
        _integer(cost, "技能基础费用", 0, 1000)
        capability = inspect_program(program)
        if not capability["supported"]:
            overrides.pop(mid, None)
        info[str(mid)] = {"skill_id": mid, "name": skill["name"]["zh"], "cost": cost,
            "priority": 0, "priority_basis": "ordinary_priority_zero_experiment",
            "source": source, "source_hash": program["source_hash"], "snapshot_id": program["snapshot_id"],
            **capability,
            "charge_skill": prepared._components()[1].requires_charge(mid),
            "choice_required": "choice_components" in program,
            "requires_replacement": (program.get('forced_switch_components', {}).get('cause') == 'detach' and program.get('forced_switch_components', {}).get('target') in ('self', 'both')) or (program.get('defense_components', {}).get('departure', {}).get('cause') == 'detach' and program.get("defense_components", {}).get("departure", {}).get("target") in ('self', 'both')),
            "requires_opponent_replacement": (program.get('forced_switch_components', {}).get('cause') == 'detach' and program.get('forced_switch_components', {}).get('target') in ('opponent', 'both')) or (program.get('defense_components', {}).get('departure', {}).get('cause') == 'detach' and program.get("defense_components", {}).get("departure", {}).get("target") in ('opponent', 'both')) }
    return overrides, info


def _talent_inputs(member):
    selection = member.get("talent_selection")
    if selection is None:
        return {}, ["尚无三选六个体配置：无额外加成试算，未补写个体数值"]
    if not isinstance(selection, dict) or not isinstance(selection.get("selected"), list):
        raise ValueError("个体三选六配置无效")
    chosen, values = selection["selected"], selection.get("values", {})
    if len(chosen) > 3 or len(set(chosen)) != len(chosen) or any(dim not in DIMS for dim in chosen):
        raise ValueError("个体只能从六项中选择不重复的三项")
    if not isinstance(values, dict):
        raise ValueError("个体显示值无效")
    out = {dim: _integer(values.get(dim), "个体显示值", 0, 10) for dim in chosen}
    return out, ([] if len(chosen) == 3 else ["个体选择不足三项：未填写项按无额外加成试算，原始未知仍保留"])


def _estimate(catalog, member, form):
    chosen, notes = _talent_inputs(member)
    nature_id = member.get("nature_id")
    nature = next((n for n in catalog["natures"] if n["id"] == nature_id), None)
    if nature_id is not None and nature is None:
        raise ValueError("性格无法匹配当前BWIKI表")
    up, down = (nature.get("up"), nature.get("down")) if nature else (None, None)
    correction = member.get("nature_modifiers", {"up_id": 0, "down_id": 0})
    if not isinstance(correction, dict):
        raise ValueError("后天性格修正无效")
    for field in ("up_id", "down_id"):
        _integer(correction.get(field, 0), "后天修正", 0, 6)
    up = MODIFIERS[correction.get("up_id", 0)] or up
    down = MODIFIERS[correction.get("down_id", 0)] or down
    if nature is None and (up is None or down is None):
        notes.append("增减方向不完整：未确定方向暂用中性倍率试算")
    if up is not None and up == down:
        raise ValueError("性格增益和减益方向冲突，请先核对")
    panels, provenance = {}, {}
    for dim in DIMS:
        multiplier = 1.2 if dim == up else 0.9 if dim == down else 1
        result = arena_stat60(form["stats"][dim], chosen.get(dim, 0) * 6, multiplier, dim)
        panels[dim] = result["stat_value"]
        provenance[dim] = {"candidate_id": result["candidate_id"], "inputs": result["inputs"], "source": result["source"]}
    return panels, provenance, notes


def _prepared_snapshot(catalog, prepared_rules):
    if prepared_rules is None:
        return PreparedRules(catalog)
    if not isinstance(prepared_rules, PreparedRules) or prepared_rules.catalog_content_hash != canonical_hash(catalog):
        raise ValueError("Prepared rules do not match the supplied catalog snapshot")
    return prepared_rules


def prepare_simulation(catalog, payload, *, prepared_rules=None):
    selected = settings(payload.get("settings"))
    teams = payload.get("teams")
    if not isinstance(teams, dict) or set(teams) != {"my", "opponent"}:
        raise ValueError("请先添加双方出战阵容")
    from lab.game_runtime_defaults import load_game_runtime_defaults
    defaults = load_game_runtime_defaults()
    fallback_cap = defaults["energy"]["pet_maximum_fallback"]
    prepared = _prepared_snapshot(catalog, prepared_rules)
    from lab.trait_runtime import POLICY as TRAIT_POLICY
    state = {"snapshot_id": catalog["snapshot_id"], "turn": 1, "teams": {}, "weather": None, "trait_policy": TRAIT_POLICY}
    if 'trait_calendar' in payload:
        calendar=payload['trait_calendar']
        if not isinstance(calendar,dict):
            raise ValueError('游戏日期实验输入必须为对象')
        from lab.trait_runtime import validate_calendar
        validate_calendar(calendar)
        state['trait_calendar']=deepcopy(calendar)
    warnings, source_ids = [], []
    for ui_side, side in (("my", "a"), ("opponent", "b")):
        records = teams[ui_side]
        if not isinstance(records, list) or not 1 <= len(records) <= 6:
            raise ValueError("每方需要1–6只精灵")
        members = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                raise ValueError("精灵配置应为对象")
            form = prepared._rules.form(record.get("form_id"))
            slots = record.get("move_ids", [])
            if not isinstance(slots, list) or len(slots) > 4:
                raise ValueError("配招需保留最多四个有序槽位")
            slots = [0 if mid is None else _integer(mid, "技能游戏ID", 0, 2**31 - 1) for mid in slots]
            slots += [0] * (4 - len(slots))
            if len([x for x in slots if x]) != len({x for x in slots if x}):
                raise ValueError("同一精灵不能重复携带技能")
            for mid in slots:
                if mid:
                    prepared._rules.skill(mid)
            cap = _integer(record.get("max_energy", fallback_cap), "精灵能量上限", 0, 1000)
            panels, provenance, notes = _estimate(catalog, record, form)
            if selected["initial_energy"] > cap:
                notes.append("试战初始能量已限制到此精灵的能量上限")
            members.append({"member_id": f"{side}:{index}", "form_id": form["id"],
                "name": form["name"]["zh"], "types": form["types"], "hp": panels["hp"],
                "max_hp": panels["hp"], "stats": {dim: panels[dim] for dim in DIMS if dim != "hp"},
                "speed": panels["spd"], "energy": min(selected["initial_energy"], cap), "max_energy": cap,
                "entered_turn": 0, "rooted": False, "charge": None, "skill_slots": slots, "committed_skill_history": [],
                "statuses": {}, "stat_modifiers": {}, "original_configuration": deepcopy(record),
                "magic_target_states": {"drill": False, "static": False, "mimic": False},
                "panel_provenance": {"mode": "estimated_candidate", "fields": provenance},
                "setup_notes": notes})
            source_ids.extend(slots)
            warnings.extend(f"{ui_side} · {form['name']['zh']}：{note}" for note in notes)
        magic_ids = {record.get("code_provenance", {}).get("core_magic", {}).get("id") for record in records
                     if record.get("code_provenance", {}).get("core_magic", {}).get("id") is not None}
        if len(magic_ids) > 1 or any(type(value) is not int for value in magic_ids):
            raise ValueError("同队阵容码的核心魔法配置冲突或ID无效，请先核对")
        state["teams"][side] = {"active_slot": 0, "members": members,
                                   "core_magic": {"id": next(iter(magic_ids), None),
                                                  "source": "code_provenance" if magic_ids else "unselected"},
                                   "marks": {"positive": None, "negative": None}}
    if all(len(t["members"]) == 6 for t in state["teams"].values()):
        from lab.victory_rules import initialize_victory
        initialize_victory(state)
    state["battle_mode"] = "pvp5001_four_magic" if "victory" in state else "reduced_roster_mechanism_experiment"
    _, info = _programs(prepared, selected, source_ids)
    from lab.weather_runtime import rules as weather_rules
    state["simulation_profile"] = {"version": PROFILE, "engine_revision": ENGINE_REVISION, "settings": selected,
        "catalog_content_hash": prepared.catalog_content_hash, "runtime_defaults_hash": canonical_hash(defaults),
        "weather_rules_hash": canonical_hash(weather_rules())}
    return {"state": state, "settings": selected, "skills": info, "warnings": warnings,
            "assumptions": deepcopy(ASSUMPTIONS), "source_defaults": defaults,
            "training_eligible": False, "calibrated": False, "full_battle_executable": False}


def _validate_profile(prepared, state, selected):
    profile = state.get("simulation_profile") if isinstance(state, dict) else None
    if (not isinstance(profile, dict) or profile.get("version") != PROFILE
            or profile.get("settings") != selected or profile.get("catalog_content_hash") != prepared.catalog_content_hash):
        raise ValueError("试战资料或设置变化，请重新准备试战，不沿用旧局面")
    if profile.get("engine_revision") != ENGINE_REVISION:
        raise ValueError("试战机制已升级，请重新准备本地试战；实战记录和固定阵容仍保留")
    from lab.game_runtime_defaults import load_game_runtime_defaults
    defaults = load_game_runtime_defaults()
    if profile.get("runtime_defaults_hash") != canonical_hash(defaults):
        raise ValueError("游戏文件基础配置变化，请重新开始试战")
    from lab.research_battle import _validate
    owned = deepcopy(state)
    from lab.status_lifecycle import POLICY as STATUS_POLICY, validate_lifecycles, validate_leech_binding
    _validate(prepared, owned, status_lifecycle_policy=STATUS_POLICY)
    for side, team in owned["teams"].items():
        for member in team["members"]:
            validate_lifecycles(member)
            if member["statuses"].get("leech", 0):
                validate_leech_binding(member, side, owned)
    from lab.weather_runtime import validate_weather_members, rules as weather_rules
    validate_weather_members(owned)
    weather_hash = canonical_hash(weather_rules())
    if profile.get("weather_rules_hash") is None:
        if owned.get("weather") or any(any(m.get("weather_statuses", {}).values())
                for team in owned["teams"].values() for m in team["members"]):
            raise ValueError("天气状态缺少规则版本，请重新准备试战")
        owned["simulation_profile"]["weather_rules_hash"] = weather_hash
    elif profile["weather_rules_hash"] != weather_hash:
        raise ValueError("天气规则资料变化，请重新准备试战")
    if "core_magic_runtime" in owned:
        from lab.core_magic_runtime import validate_core_magic
        validate_core_magic(owned)
    for side in ("a", "b"):
        for member in owned["teams"][side]["members"]:
            _integer(member["max_energy"], "精灵能量上限", 0, 1000)
            _integer(member["speed"], "速度", 1)
            if not isinstance(member.get("stats"), dict):
                raise ValueError("需提供完整试战面板")
            for dim in DIMS[1:]:
                _integer(member["stats"].get(dim), "试战面板", 1)
            if member["stats"]["spd"] != member["speed"]:
                raise ValueError("速度面板与行动速度不一致")
    return owned


def _status_damage(descriptor, state, context):
    actor = state["teams"][descriptor["target_side"]]
    actor = actor["members"][actor["active_slot"]]
    rate = Fraction(descriptor["rate"]["numerator"], descriptor["rate"]["denominator"])
    nominal = actor["max_hp"] * descriptor["stacks"] * rate
    return min(actor["hp"], nominal.numerator // nominal.denominator)


def _refresh_dynamic(prepared, state):
    from lab.mark_runtime import prepare_battle_transmission
    events = prepare_battle_transmission(state)
    from lab.dynamic_skills import refresh_round
    from lab.action_mechanics import GENERATORS
    if "dynamic_skills" in state or any(mid in GENERATORS for team in state["teams"].values()
            for member in team["members"] for mid in member["skill_slots"]):
        events.extend(refresh_round(prepared, state))
    return events


def _refresh_result(prepared, result, selected, *, diagnostics=True):
    if result.get("status") == "applied" and result.get("turn_advanced"):
        result["events"].extend(_refresh_dynamic(prepared, result["state"]))
    if diagnostics:
        ids = [mid for team in result["state"]["teams"].values() for m in team["members"] for mid in m["skill_slots"]]
        result["skills"] = _programs(prepared, selected, ids)[1]
    else:
        for key in ("skills", "damage_traces", "numeric_policy", "assumptions"):
            result.pop(key, None)
    return result


@query_scope()
def act_simulation(catalog, payload, *, replace=False, random_seed=None, prepared_rules=None, diagnostics=True):
    """Resolve one joint turn (or a faint-replacement choice).

    ``random_seed`` seeds the battle's state-cursor random stream (random
    devotion). The state cursor is the single authority: the first call writes
    ``state["random_devotion_rng"] = {"seed": seed, "draw_index": 0}``, later
    calls require the same seed, and every isolated fragment context derives
    its seed from that cursor. ``None`` keeps whatever the battle already
    carries (0 for a battle prepared without a seed).
    """
    if type(diagnostics) is not bool:
        raise ValueError("diagnostics must be a Boolean")
    if random_seed is not None and (type(random_seed) is not int or random_seed < 0):
        raise ValueError("random_seed must be a nonnegative integer")
    selected = settings(payload.get("settings"))
    prepared = _prepared_snapshot(catalog, prepared_rules)
    state = _validate_profile(prepared, payload.get("state"), selected)
    _refresh_dynamic(prepared, state)
    cursor = state.get("random_devotion_rng")
    if random_seed is not None:
        if cursor is None:
            state["random_devotion_rng"] = {"seed": random_seed, "draw_index": 0}
        elif not isinstance(cursor, dict) or cursor.get("seed") != random_seed:
            raise ValueError("random_seed differs from this battle's random devotion cursor")
    random_seed = _devotion_seed(state)
    ids = [mid for side in ("a", "b") for m in state["teams"][side]["members"] for mid in m["skill_slots"]]
    overrides, info = _programs(prepared, selected, ids)
    if replace:
        # Factory builds the same source-bound phase policy; dummy recharge
        # contexts are not executed by the replacement operation.
        dummy = {side: {"kind": "recharge", "effective_cost": 0, "effective_priority": 0} for side in ("a", "b")}
        context = build_research_context_v2(prepared, state, dummy, tie_break_side=selected["tie_break_side"],
                                            random_seed=random_seed)
        result = choose_research_replacements_v2(prepared, state, payload.get("selections"), context)
        result.update(settings=selected)
        if diagnostics:
            result.update(skills=info, assumptions=deepcopy(ASSUMPTIONS))
        return _refresh_result(prepared, result, selected, diagnostics=diagnostics)
    submitted = payload.get("actions")
    if not isinstance(submitted, dict) or set(submitted) != {"a", "b"}:
        raise ValueError("需同时选择双方行动")
    actions = {}
    for side in ("a", "b"):
        action = submitted[side]
        if not isinstance(action, dict):
            raise ValueError("行动应为对象")
        kind = action.get("kind")
        actor = state["teams"][side]["members"][state["teams"][side]["active_slot"]]
        if kind == "skill":
            slot = _integer(action.get("slot"), "技能槽位", 0, 3)
            mid = actor["skill_slots"][slot]
            if not mid:
                raise ValueError("不能使用空技能槽")
            priority = _integer(action.get("priority", 0), "本轮先手度", -100, 100)
            skill_info = info[str(mid)]
            if not skill_info["supported"]:
                return {"status": "blocked", "state": deepcopy(state), "events": [],
                    "blockers": [skill_info["name"] + "：" + reason for reason in skill_info["blockers"]],
                    "committed_actions": [], "turn_advanced": False, "skills": info,
                    "settings": selected, "assumptions": deepcopy(ASSUMPTIONS),
                    "training_eligible": False, "calibrated": False}
            from lab.dynamic_skills import cost_delta
            delta = cost_delta(actor, slot)
            from lab.duration_runtime import charge_bypass
            default_cost = 0 if skill_info["charge_skill"] and actor["charge"] is None and not charge_bypass(actor, state["turn"]) else max(0, skill_info["cost"] + delta)
            cost = _integer(action.get("cost", default_cost), "本轮费用", 0, 1000)
            actions[side] = {"kind": kind, "slot": slot, "effective_cost": cost, "effective_priority": priority}
            if skill_info.get("choice_required"):
                actions[side]["choice_option"] = _integer(action.get("choice_option"), "明暗选择", 0, 1)
            if "opponent_replacement_slot" in action:
                opposite = "b" if side == "a" else "a"
                actions[side]["opponent_replacement_slot"] = _integer(action["opponent_replacement_slot"], "敌方效果换入槽位", 0, len(state["teams"][opposite]["members"]) - 1)
            if 'replacement_slot' in action:
                actions[side]['replacement_slot'] = _integer(action['replacement_slot'], '效果换入槽位', 0, len(state['teams'][side]['members']) - 1)
        elif kind == "switch":
            target = _integer(action.get("target_slot"), "换入槽位", 0, len(state["teams"][side]["members"]) - 1)
            planned = {"kind": kind, "target_slot": target}
            if "switch_cooldown" in action:
                if not isinstance(action["switch_cooldown"], dict):
                    raise ValueError("换人冷却输入必须为对象")
                planned["switch_cooldown"] = deepcopy(action["switch_cooldown"])
            actions[side] = planned
        elif kind == "recharge":
            actions[side] = {"kind": kind, "effective_cost": 0, "effective_priority": 0}
        else:
            raise ValueError("请选择技能、主动换人或聚能")
        if 'replacement_slot' in action and kind == 'recharge':
            actions[side]['replacement_slot'] = _integer(action['replacement_slot'], '效果换入槽位', 0, len(state['teams'][side]['members']) - 1)
    fragments = {side: {"multi_hit_policy": {"power_basis": selected["multi_hit_power"],
                    "timing": "sequential_experiment"}} for side in ("a", "b")}
    from lab.dynamic_skills import cost_delta
    incoming_costs = {}
    for side, action in actions.items():
        if action["kind"] == "switch":
            incoming = state["teams"][side]["members"][action["target_slot"]]
            incoming_costs[side] = [max(0, info[str(mid)]["cost"] + cost_delta(incoming, slot)) if mid else None
                                    for slot, mid in enumerate(incoming["skill_slots"])]
    context = build_research_context_v2(prepared, state, actions, program_overrides=overrides,
        tie_break_side=selected["tie_break_side"], fragment_overrides=fragments,
        incoming_effective_costs=incoming_costs, random_seed=random_seed)
    from lab.hud_damage_runtime import make_hud_damage_resolver
    resolver = make_hud_damage_resolver(prepared)
    traces = []
    def traced_damage(params, current, execution_context):
        trace = resolver.explain(params, current, execution_context)
        if diagnostics:
            traces.append(trace)
        return trace["actual_hp_loss"]
    traced_damage.explain = resolver.explain
    traced_damage.mark_damage = resolver.mark_damage
    traced_damage.retaliation = resolver.retaliation
    result = execute_research_turn_v2(prepared, state, actions, context, damage_resolver=traced_damage,
        status_damage_resolver=_status_damage, program_overrides=overrides)
    result.update(settings=selected, submitted_actions=actions,
        status_damage_policy="max_hp_per_layer_floor_no_type_bonus_experiment")
    if diagnostics:
        result.update(skills=info, damage_traces=traces, numeric_policy=resolver.metadata,
                      assumptions=deepcopy(ASSUMPTIONS))
    return _refresh_result(prepared, result, selected, diagnostics=diagnostics)


def start_simulation(catalog, payload, *, prepared_rules=None):
    selected = settings(payload.get("settings"))
    prepared = _prepared_snapshot(catalog, prepared_rules)
    state = _validate_profile(prepared, payload.get("state"), selected)
    if state["turn"] != 1 or "research_battle" in state:
        raise ValueError("开始试战需使用准备页初始局面；现有试战请继续或重置")
    from lab.core_magic_runtime import initialize_core_magic, core_magic_policy
    if any(row['casts'] for name in ('core_magic_runtime', 'core_magic_additions') for row in state.get(name, {}).get('players', {}).values()):
        raise ValueError("已使用核心魔法的局面不能重新初始化")
    for team in state["teams"].values():
        experiment = team.get("core_magic_experiment", {})
        if experiment not in ({}, {"target_states": "assume_absent_drill_static_mimic_experiment"}):
            raise ValueError("未知核心魔法目标状态实验配置")
        if experiment:
            for member in team["members"]:
                member["magic_target_states"] = {"drill": False, "static": False, "mimic": False}
    if any(team.get("core_magic", {}).get("id") in (104001, 104002, 104003, 104004, 104007) for team in state["teams"].values()):
        initialize_core_magic(state, policy=core_magic_policy())
    state["simulation_profile"]["started"] = True
    from lab import trait_runtime
    trait_runtime.bind(prepared, state)
    from lab import trait_attack_hooks
    from lab import skill_history_runtime
    from lab.user_skill_extensions import initialize_repeats
    initialize_repeats(state)
    dynamic_events = trait_runtime.initialize(prepared, state) + trait_attack_hooks.initialize(prepared, state) + skill_history_runtime.initialize(prepared, state) + _refresh_dynamic(prepared, state)
    ids = [mid for side in ("a", "b") for m in state["teams"][side]["members"] for mid in m["skill_slots"]]
    _, info = _programs(prepared, selected, ids)
    return {"status": "ready", "state": state, "skills": info, "settings": selected, "events": dynamic_events,
            "assumptions": deepcopy(ASSUMPTIONS), "training_eligible": False, "calibrated": False}


def magic_simulation(catalog, payload):
    """Independent optional item selection; ordinary action drafts stay separate."""
    selected = settings(payload.get("settings"))
    prepared = PreparedRules(catalog)
    state = _validate_profile(prepared, payload.get("state"), selected)
    side = payload.get("side")
    if side not in ("a", "b"):
        raise ValueError("请选择使用核心魔法的一方")
    if not state["simulation_profile"].get("started"):
        raise ValueError("请先按准备配置开始试战")
    if state.get("research_battle", {}).get("phase", "ready") != "ready":
        raise ValueError("当前需先处理替补、阻断或结束状态，不能追加核心魔法")
    from lab.core_magic_runtime import execute_core_magic, core_magic_policy
    team = state["teams"][side]
    result = execute_core_magic(state, {"kind": "core_magic", "item_id": team.get("core_magic", {}).get("id"),
                                       "side": side, "target_slot": team["active_slot"]},
                                {"policy": core_magic_policy()}, catalog=prepared)
    result.update(settings=selected, assumptions=deepcopy(ASSUMPTIONS), committed_actions=[])
    return _refresh_result(prepared, result, selected)


def demo_rosters(catalog):
    """A labelled, detached example from pool entries; never a user's team."""
    prepared = PreparedRules(catalog)
    chosen, seen_types = [], set()
    for form in catalog["forms"]:
        if tuple(form["types"]) in seen_types:
            continue
        detail = catalog["details"].get(str(form["id"]), {})
        slots = []
        for mid in detail.get("learnset", {}).get("pool", []):
            program = prepared._rules.program(mid)
            if program["status"] == "compiled" and all(op["op"] in {"damage", "energy.restore", "hp.restore", "stat.modify"} for op in program["operations"]):
                slots.append(mid)
            if len(slots) == 4:
                break
        if len(slots) < 2:
            continue
        chosen.append({"form_id": form["id"], "move_ids": slots, "nature_id": None,
            "talent_selection": {"selected": ["hp", "patk", "spd"],
                                 "values": {"hp": 10, "patk": 10, "spd": 10}},
            "demo_configuration": True})
        seen_types.add(tuple(form["types"]))
        if len(chosen) == TEAM_SIZE * 2:
            return {"my": chosen[:TEAM_SIZE], "opponent": chosen[TEAM_SIZE:]}
    raise ValueError("当前快照中没有足够的可演示基础配招")


def simulation_request(path, payload, catalog):
    if not isinstance(payload, dict):
        raise ValueError("试战请求应为对象")
    if any(key in payload for key in ("program", "program_overrides", "damage_resolver", "predicted_damage", "context")):
        raise ValueError("试战规则由服务器读取，不接受客户端规则或伤害替代")
    if path == "/api/simulation/prepare":
        teams = payload.get("teams")
        if not isinstance(teams, dict) or any(not isinstance(teams.get(side), list) or len(teams[side]) != TEAM_SIZE for side in ("my", "opponent")):
            raise ValueError("PVP试战要求双方各六只精灵，请补齐阵容")
    elif path in ("/api/simulation/start", "/api/simulation/act", "/api/simulation/replace", "/api/simulation/magic"):
        state = payload.get("state")
        teams = state.get("teams", {}) if isinstance(state, dict) else {}
        if not isinstance(teams, dict) or any(not isinstance(teams.get(side), dict) or len(teams[side].get("members", [])) != TEAM_SIZE for side in ("a", "b")):
            raise ValueError("当前PVP试战仅接受6v6；旧小阵容局面请重新准备")
    if path == "/api/simulation/prepare":
        return prepare_simulation(catalog, payload)
    if path == "/api/simulation/demo":
        result = prepare_simulation(catalog, {"teams": demo_rosters(catalog), "settings": payload.get("settings")})
        result["warnings"].insert(0, "演示阵容与数值试算，不是你的真实配置，也未通过完整阵容合法性验证")
        result["demo"] = True
        return result
    if path == "/api/simulation/start":
        payload = deepcopy(payload)
        state = payload["state"]
        from lab.victory_rules import initialize_victory
        for team in state["teams"].values():
            for member in team["members"]:
                member["energy"] = min(DEFAULT_SETTINGS["initial_energy"], member["max_energy"])
        initialize_victory(state)
        return start_simulation(catalog, payload)
    if path == "/api/simulation/magic":
        return magic_simulation(catalog, payload)
    if path in ("/api/simulation/act", "/api/simulation/replace"):
        return act_simulation(catalog, payload, replace=path.endswith("/replace"))
    raise ValueError("未知试战接口")
