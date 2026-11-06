"""Shared learning-path checks for carried and generated battle skills."""


def legendary_available(catalog, member, skill_id):
    """User-confirmed: final ordinary evolution stages have legendary moves."""
    original = member.get("original_configuration", member)
    if skill_id in original.get("legendary_unlocked_ids", []):
        return True
    fid = member["form_id"]
    detail = catalog.get("details", {}).get(str(fid), {})
    family = detail.get("source_record", {}).get("evolution_id")
    forms = catalog.get("forms", [])
    form = next((row for row in forms if row["id"] == fid), {})
    stage = form.get("stage")
    if type(stage) is not int:
        return False
    if family:
        stages = [row.get("stage") for row in forms
                  if catalog.get("details", {}).get(str(row["id"]), {})
                  .get("source_record", {}).get("evolution_id") == family]
        return stage == max(value for value in stages if type(value) is int)
    return stage >= 3


def learning_path_allows(catalog, member, kind, entry):
    from lab.team_code import BLOODLINES
    original = member.get("original_configuration", member)
    form = next((row for row in catalog.get("forms", []) if row["id"] == member["form_id"]), {})
    return ((kind != "legacy" or entry.get("bloodline") == BLOODLINES.get(original.get("bloodline_id")))
            and (not entry.get("stage") or entry["stage"] <= (form.get("stage") or 0))
            and (not entry.get("level") or entry["level"] <= original.get("level", 0))
            and (kind != "legendary" or legendary_available(catalog, member, entry["move"])))
