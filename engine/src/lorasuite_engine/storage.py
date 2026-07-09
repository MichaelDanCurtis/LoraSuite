import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


_LOCKS: dict[str, RLock] = {}
_LOCKS_LOCK = RLock()


@contextmanager
def json_file_lock(path: Path) -> Iterator[None]:
    key = str(Path(path).expanduser().resolve(strict=False))
    with _LOCKS_LOCK:
        lock = _LOCKS.setdefault(key, RLock())
    with lock:
        yield


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
