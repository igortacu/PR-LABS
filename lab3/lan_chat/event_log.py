"""Append-only JSON Lines audit log for UDP datagrams."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class DatagramLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _write(
        self,
        action: str,
        endpoint: tuple[str, int],
        kind: str,
        size: int,
        reason: str | None = None,
    ) -> None:
        record = {
            "time": datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds"),
            "action": action,
            "endpoint": f"{endpoint[0]}:{endpoint[1]}",
            "kind": kind,
            "size": size,
        }
        if reason is not None:
            record["reason"] = reason
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def sent(self, endpoint: tuple[str, int], kind: str, size: int) -> None:
        self._write("sent", endpoint, kind, size)

    def received(self, endpoint: tuple[str, int], kind: str, size: int) -> None:
        self._write("received", endpoint, kind, size)

    def dropped(
        self,
        endpoint: tuple[str, int],
        kind: str,
        size: int,
        reason: str,
    ) -> None:
        self._write("dropped", endpoint, kind, size, reason)
