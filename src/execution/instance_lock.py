"""OS-held single-process lock shared by local checkouts of an account."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile


class InstanceLock:
    def __init__(self, identity: str, directory: Path | None = None):
        key = hashlib.sha256(identity.encode()).hexdigest()[:24]
        self.path = (directory or Path(tempfile.gettempdir())) / f"forex-sentinel-{key}.lock"
        self.handle = None

    def __enter__(self):
        self.handle = self.path.open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                self.handle.write(b"0")
                self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.handle.close()
            self.handle = None
            raise RuntimeError("Another Forex Sentinel process holds this account lock") from exc
        return self

    def __exit__(self, *args):
        if self.handle is not None:
            self.handle.close()  # OS releases the lock, including after crashes.
            self.handle = None
        # Never unlink: another process may already have opened this inode.
