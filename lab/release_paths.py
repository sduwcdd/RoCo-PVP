"""Frozen-build identity and per-user storage; source checkout behavior is unchanged."""
import os
from pathlib import Path
import sys

_MOBILE_CONTEXT = None


def configure_mobile(files_root, identity):
    """Configure the embedded runtime before importing the HTTP/battle modules."""
    global _MOBILE_CONTEXT
    import re
    if (not isinstance(identity, dict) or set(identity) != {'release_id', 'source_hash'}
            or not re.fullmatch(r'[A-Za-z0-9_-]+', identity.get('release_id', ''))
            or not re.fullmatch(r'[0-9a-f]{64}', identity.get('source_hash', ''))):
        raise ValueError('Invalid embedded runtime identity')
    root = Path(files_root)
    if not root.is_absolute():
        raise ValueError('Embedded storage must be an absolute application directory')
    root = root.resolve()
    context = (root, dict(identity))
    if _MOBILE_CONTEXT is not None and _MOBILE_CONTEXT != context:
        raise RuntimeError('Embedded runtime is already bound to another storage or build')
    root.mkdir(parents=True, exist_ok=True)
    _MOBILE_CONTEXT = context


def frozen():
    return bool(getattr(sys, 'frozen', False))


def user_root():
    if _MOBILE_CONTEXT is not None:
        return _MOBILE_CONTEXT[0]
    if not frozen():
        return None
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise RuntimeError('Windows LocalAppData is unavailable')
    root = Path(base) / 'RocoPVP'
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_identity():
    if _MOBILE_CONTEXT is not None:
        return dict(_MOBILE_CONTEXT[1])
    if not frozen():
        return None
    from _release_secrets import BUILD_ID, SOURCE_HASH
    return {'release_id': BUILD_ID, 'source_hash': SOURCE_HASH}
