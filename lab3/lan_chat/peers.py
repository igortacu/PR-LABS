"""Thread-safe online-peer directory."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .constants import PEER_TIMEOUT


@dataclass(frozen=True, slots=True)
class PeerInfo:
    peer_id: str
    name: str
    endpoint: tuple[str, int]
    last_seen: float


class PeerDirectory:
    def __init__(self) -> None:
        self._peers: dict[str, PeerInfo] = {}
        self._lock = threading.RLock()

    def upsert(
        self,
        peer_id: str,
        name: str,
        endpoint: tuple[str, int],
        now: float | None = None,
    ) -> bool:
        seen_at = time.monotonic() if now is None else now
        with self._lock:
            joined = peer_id not in self._peers
            self._peers[peer_id] = PeerInfo(peer_id, name, endpoint, seen_at)
            return joined

    def get(self, peer_id: str) -> PeerInfo | None:
        with self._lock:
            return self._peers.get(peer_id)

    def get_by_name(self, name: str) -> PeerInfo | None:
        with self._lock:
            return next((peer for peer in self._peers.values() if peer.name == name), None)

    def remove(self, peer_id: str) -> PeerInfo | None:
        with self._lock:
            return self._peers.pop(peer_id, None)

    def expire(
        self,
        now: float | None = None,
        timeout: float = PEER_TIMEOUT,
    ) -> list[PeerInfo]:
        current = time.monotonic() if now is None else now
        with self._lock:
            expired_ids = [
                peer_id
                for peer_id, peer in self._peers.items()
                if current - peer.last_seen >= timeout
            ]
            return [self._peers.pop(peer_id) for peer_id in expired_ids]

    def snapshot(self) -> tuple[PeerInfo, ...]:
        with self._lock:
            return tuple(sorted(self._peers.values(), key=lambda peer: peer.name.casefold()))


def duplicate_name_loser(local_id: str, remote_id: str) -> bool:
    """Return True when this local peer loses a simultaneous-name race.

    UUIDs are compared lexically. Exactly one side loses, independent of packet
    order; the smaller UUID wins.
    """

    if local_id == remote_id:
        return False
    return local_id > remote_id
