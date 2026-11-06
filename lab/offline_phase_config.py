"""Offline migration of previously reviewed phase classifiers; never imported by runtime."""
from copy import deepcopy
import hashlib
import json
from lab.switch_rules import SwitchRules, _integer

SKILLS_SHA256 = '58ec4e67d14ff9bdaab615e2b32d8bede0fd3b7180dc2e33179047bcd8803de5'
NORMALIZED_SKILLS_SHA256 = 'eae107c786441217977d76f5a52a3340801433ce5349300fac62cc7e1022817b'
# Reviewed complete records, not substring recognition. 7150320 mentions
# replaying earlier Swift skills but does not itself declare Swift. 7150400
# gains Swift only under a prior-turn condition; history is not resolved here.
REVIEWED_SWIFT = {
    7150080: (True, "91460ebff088e150742cf9d00413f5a3ebba4be9ceab43c6dedc80e48f91600d"),
    7150110: (True, "c0041320dba12a3f8a14517764ad37012dc9e5d02dc9522d481230b44b6cb8ce"),
    7150150: (True, "84f42e24d21599bb84e8e19319d2ba5d9443427c15f3da7595bb818de2046e97"),
    7150260: (True, "459e430c89bc70962f2df8a2cdf3b98af5d4719e958c2feb93f52ceaf7f3a084"),
    7150300: (True, "dacb8ccc90c91fc0c5a04f847c4337b535aba1ab28df732946a6193bdf50c155"),
    7150320: (False, "c1ad0240d70e55ab198b1170757a116083743e2700b95d2e542c301e2edc47a9"),
    7150400: (None, "b5259a6c3fd78f47957ab97afd5f1dedb5a84868e7d8c50f809d49756342a318"),
    7150410: (True, "80c54df0e078236bb1313450dc9a99ec197086c7fbe2dff956f8c1f43e3bc27d"),
}

class OfflineSwiftClassifier(SwitchRules):
    def __init__(self, catalog):
        super().__init__(catalog)
        self._skills = deepcopy(catalog.get("moves", {}))
        self._skills_verified = False
        self._glossary = deepcopy(catalog.get("glossary", []))

    def skill_swift_metadata(self, skill_id):
        """Inspect intrinsic source metadata, never caller-provided Swift flags.

        External grants/removals, copied skills and dynamic effects are outside
        this helper. A known False describes only the source skill's intrinsic
        property. Unknown conditional/history metadata stays None; neither a
        base energy value nor source description is an effective entry cost.
        """
        _integer(skill_id, "skill_id", 1)
        if self._skill_source.get("content_sha256") != SKILLS_SHA256:
            raise ValueError("BWIKI Skills changed or are missing; intrinsic Swift needs source review")
        if not self._skills_verified:
            raw_skills = json.dumps(self._skills, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False)
            if hashlib.sha256(raw_skills.encode()).hexdigest() != NORMALIZED_SKILLS_SHA256:
                raise ValueError("Owned skill records differ from reviewed snapshot; intrinsic Swift needs source review")
            self._skills_verified = True
        values = self._skills.values() if isinstance(self._skills, dict) else self._skills
        if not isinstance(values, (list, tuple)) and not isinstance(self._skills, dict):
            raise ValueError("Skill records are unavailable")
        matches = [record for record in values if isinstance(record, dict) and record.get("id") == skill_id]
        if len(matches) != 1:
            raise ValueError("Skill ID must uniquely match the owned source snapshot")
        record = deepcopy(matches[0])
        raw = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        description = record.get("desc", {}).get("zh") if isinstance(record.get("desc"), dict) else None
        result = self._result([1005], status="unknown", skill_id=skill_id, swift=None,
                              source_record=record, skill_record_hash=digest,
                              skills_evidence=deepcopy(self._skill_source),
                              metadata_scope="intrinsic_source_only",
                              external_swift_modifiers_resolved=False,
                              reason="迅捷条件或补充描述尚未审查，不能按无迅捷处理。")
        if skill_id in REVIEWED_SWIFT:
            swift, reviewed_hash = REVIEWED_SWIFT[skill_id]
            if digest != reviewed_hash:
                result["reason"] = "已审查的迅捷相关技能记录发生变化，需重新核对来源。"
                return result
            result.update(status="unknown" if swift is None else "known", swift=swift,
                          reason=("历史条件决定是否获得迅捷；缺少已核对的上回合记录。" if swift is None
                                  else "已核对完整技能记录的固有迅捷标识；不包含外部授予或移除。"))
            return result
        notes = record.get("desc_notes", [])
        if (not isinstance(description, str) or not description.strip()
                or not isinstance(notes, list) or any(type(note) is not int for note in notes)
                or "迅捷" in raw):
            return result
        for note in notes:
            terms = [entry for entry in self._glossary if entry.get("key") == note]
            if len(terms) != 1 or not isinstance(terms[0].get("definition"), str):
                result["reason"] = "补充术语无法唯一核对，不能排除固有迅捷条件。"
                return result
            if note == 1005 or "迅捷" in terms[0]["definition"]:
                return result
        # Absence refers to this source record only, not the current combatant.
        result.update(status="known", swift=False,
                      reason="当前完整技能记录及补充术语未声明固有迅捷；外部修正仍需单独排除或解析。")
        return result

