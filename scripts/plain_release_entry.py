"""Unencrypted frozen entry; command handling stays shared with the release app."""
import hashlib
from pathlib import Path
import sys

from _release_bootstrap import main


def mount_resources():
    from lab.release_runtime import install_plain
    from _release_secrets import RESOURCE_HASH, SOURCE_HASHES
    root = Path(sys._MEIPASS)
    raw = (root / 'resources.zip').read_bytes()
    if hashlib.sha256(raw).hexdigest() != RESOURCE_HASH:
        raise RuntimeError('安装资源校验失败，请重新获取完整发布包')
    return install_plain(root, raw, source_hashes=SOURCE_HASHES)


if __name__ == '__main__':
    raise SystemExit(main(mount_resources))
