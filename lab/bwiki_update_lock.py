"""Keep offline data maintenance separate from a running source service."""
from contextlib import contextmanager
import os
from pathlib import Path


def acquire(root, *, updating):
    path = Path(root) / "data" / ".bwiki-update.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a+b")
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"\0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            mode = msvcrt.LK_NBLCK if updating else msvcrt.LK_NBRLCK
            msvcrt.locking(stream.fileno(), mode, 1)
        else:
            import fcntl
            mode = fcntl.LOCK_EX if updating else fcntl.LOCK_SH
            fcntl.flock(stream.fileno(), mode | fcntl.LOCK_NB)
    except OSError as exc:
        stream.close()
        raise ValueError("BWIKI 数据正在使用或更新，请退出本项目 APP 和工作台服务后重试更新。") from exc
    return stream


@contextmanager
def maintenance(root):
    stream = acquire(root, updating=True)
    try:
        yield
    finally:
        stream.close()
