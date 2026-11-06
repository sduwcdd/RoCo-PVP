"""Relocate recorded project evidence without rewriting its original provenance."""
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[1]


def _recorded_relative(value):
    windows = PureWindowsPath(str(value))
    if windows.drive:
        parts = windows.parts
        markers = [i for i, part in enumerate(parts) if part.casefold() == "roco_pvp"]
        if not markers:
            raise ValueError("Recorded evidence is outside the known project: " + str(value))
        relative = Path(*parts[markers[-1] + 1:])
        if ".." in relative.parts:
            raise ValueError("Recorded evidence traverses its project")
        return relative
    return None


def evidence_path(value, root=ROOT):
    root = Path(root).resolve()
    relative = _recorded_relative(value)
    path = root / relative if relative is not None else Path(value)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Evidence path leaves the deployed project: " + str(value))
    return path


def _canonical_locations(value):
    """Only physical project locations differ; data, hashes and schemas do not."""
    if isinstance(value, dict):
        return {key: _canonical_locations(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_locations(item) for item in value]
    if isinstance(value, str):
        # Normalize the deployed root before treating Windows paths as historical
        # checkout locations (a release can also live below the old checkout).
        current = Path(value)
        if current.is_absolute() and current.is_relative_to(ROOT):
            return '$PROJECT/' + current.relative_to(ROOT).as_posix()
        if PureWindowsPath(value).drive:
            try:
                relative = _recorded_relative(value)
            except ValueError:
                return value
            return "$PROJECT/" + relative.as_posix()
        if value.startswith(str(ROOT)):
            path = evidence_path(value)
            return "$PROJECT/" + path.relative_to(ROOT).as_posix()
    return value


def validate_relocated_layer_sources(bundle):
    """Reparse the same hashed bytes with the original, pinned parser/adapter."""
    from lab.game_layer_references import (validate_layer_references,
        load_archive_variants, load_resource_group_variants)
    from lab.game_rule_candidates import digest
    errors = validate_layer_references(bundle, verify_sources=False)
    if errors:
        return errors
    try:
        variants = bundle["variants"]
        probe_dirs = {str(evidence_path(v["probe_dir"])) for v in variants.values()}
        if len(probe_dirs) != 1:
            raise ValueError("Expected one relocated verified parser source")
        strict = [v for v in variants.values() if "resource_group" not in v]
        manifests = sorted({str(evidence_path(f["manifest"])) for v in strict
            for table in v["table_sources"].values() for f in table["files"].values()})
        probe = next(iter(probe_dirs))
        reparsed = load_archive_variants(manifests, probe) if manifests else {}
        groups = [str(evidence_path(v["resource_group"]["path"])) for v in variants.values()
                  if "resource_group" in v]
        if groups:
            reparsed.update(load_resource_group_variants(groups, probe))
        if digest(_canonical_locations(variants)) != digest(_canonical_locations(reparsed)):
            raise ValueError("Relocated evidence differs from the same hash-checked parsed sources")
        return []
    except (OSError, KeyError, ValueError, TypeError, IndexError) as error:
        return [str(error)]
