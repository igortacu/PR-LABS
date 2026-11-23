"""Peer-to-peer UDP LAN chat engine."""

from __future__ import annotations

import socket
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Callable

from .constants import (
    DEFAULT_BROADCAST_ADDRESS,
    DISCOVERY_WAIT,
    HEARTBEAT_INTERVAL,
    MAX_DATAGRAM_BYTES,
    PEER_TIMEOUT,
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
)
from .crypto import CryptoError, decrypt_private, derive_key, encrypt_private
from .event_log import DatagramLogger
from .peers import PeerDirectory, duplicate_name_loser
from .protocol import (
    InvalidMessage,
    decode_message,
    encode_message,
    validate_chat_text,
    validate_name,
)


class ChatError(RuntimeError):
    pass


class OfflinePeerError(ChatError):
    pass


class NameInUseError(ChatError):
    pass


class LanChatPeer:
    """One serverless chat peer with a shared and a private UDP socket."""

    def __init__(
        self,
        name: str,
        port: int,
        passphrase: str,
        *,
        broadcast_address: str = DEFAULT_BROADCAST_ADDRESS,
        log_path: str | Path | None = None,
        on_event: Callable[[str], None] | None = None,
        discovery_wait: float = DISCOVERY_WAIT,
        heartbeat_interval: float = HEARTBEAT_INTERVAL,
        peer_timeout: float = PEER_TIMEOUT,
        peer_id: str | None = None,
    ) -> None:
        validate_name(name, "name")
        if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError("port must be an integer from 1 to 65535")
        self.name = name
        self.port = port
        self.peer_id = peer_id or str(uuid.uuid4())
        self.broadcast_address = broadcast_address
        self.discovery_wait = discovery_wait
        self.heartbeat_interval = heartbeat_interval
        self.peer_timeout = peer_timeout
        self.key = derive_key(passphrase, port)
        default_log = Path("logs") / f"{_safe_filename(name)}-{self.peer_id[:8]}.log"
        self.log = DatagramLogger(log_path or default_log)
        self.on_event = on_event or print
        self.peers = PeerDirectory()

        self._broadcast_socket: socket.socket | None = None
        self._private_socket: socket.socket | None = None
        self._private_port: int | None = None
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._conflict_event = threading.Event()
        self._state_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._seen_lock = threading.Lock()
        self._seen_message_ids: OrderedDict[str, None] = OrderedDict()
        self._state = "stopped"

    @property
    def private_port(self) -> int:
        if self._private_port is None:
            raise ChatError("peer has not started")
        return self._private_port

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._state != "stopped"

    def start(self) -> None:
        with self._state_lock:
            if self._state != "stopped":
                raise ChatError("peer is already running")
            self._stop_event = threading.Event()
            self._conflict_event = threading.Event()
            self._open_sockets()
            self._state = "starting"

        self._threads = [
            threading.Thread(
                target=self._receive_loop,
                args=(self._broadcast_socket,),
                name=f"lan-chat-broadcast-{self.name}",
                daemon=True,
            ),
            threading.Thread(
                target=self._receive_loop,
                args=(self._private_socket,),
                name=f"lan-chat-private-{self.name}",
                daemon=True,
            ),
            threading.Thread(
                target=self._maintenance_loop,
                name=f"lan-chat-heartbeat-{self.name}",
                daemon=True,
            ),
        ]
        for thread in self._threads:
            thread.start()

        try:
            self._send_broadcast(self._base_message("join"))
        except Exception:
            self.stop(announce=False)
            raise
        if self._conflict_event.wait(self.discovery_wait):
            self.stop(announce=False)
            raise NameInUseError(f"the name {self.name!r} is already in use")
        with self._state_lock:
            if self._state == "starting":
                self._state = "joined"

    def stop(self, announce: bool = True) -> None:
        with self._state_lock:
            if self._state in {"stopped", "stopping"}:
                return
            should_announce = announce and self._state == "joined"
            self._state = "stopping"
        if should_announce:
            try:
                self._send_broadcast(self._base_message("leave"))
            except OSError:
                pass
        self._stop_event.set()
        for sock in (self._broadcast_socket, self._private_socket):
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        current = threading.current_thread()
        for thread in self._threads:
            if thread is not current:
                thread.join(timeout=1.0)
        self._threads = []
        self._broadcast_socket = None
        self._private_socket = None
        self._private_port = None
        with self._state_lock:
            self._state = "stopped"

    def send_general(self, text: str) -> None:
        self._require_joined()
        validate_chat_text(text)
        message = {
            **self._base_message("general"),
            "message_id": str(uuid.uuid4()),
            "text": text,
        }
        self._remember_message(message["message_id"])
        try:
            self._send_broadcast(message)
        except Exception:
            self._forget_message(message["message_id"])
            raise
        self._emit(f"[general] {self.name}: {text}")

    def send_private(self, recipient: str, text: str) -> None:
        peer = self.peers.get_by_name(recipient)
        if peer is None:
            raise OfflinePeerError(f"{recipient} is not online")
        self._require_joined()
        validate_chat_text(text)
        message = {
            **self._base_message("private"),
            "message_id": str(uuid.uuid4()),
            "recipient": recipient,
        }
        aad = self._private_aad(message)
        nonce, ciphertext = encrypt_private(self.key, text, aad)
        message["nonce"] = nonce
        message["ciphertext"] = ciphertext
        self._send_unicast(message, peer.endpoint)
        self._emit(f"[private -> {recipient}] {self.name}: {text}")

    def online_users(self) -> tuple[str, ...]:
        names = [self.name]
        names.extend(peer.name for peer in self.peers.snapshot())
        return tuple(sorted(set(names), key=str.casefold))

    def _open_sockets(self) -> None:
        broadcast = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        private = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            broadcast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    broadcast.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            broadcast.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            broadcast.bind(("0.0.0.0", self.port))
            private.bind(("0.0.0.0", 0))
            broadcast.settimeout(0.2)
            private.settimeout(0.2)
        except Exception:
            broadcast.close()
            private.close()
            raise
        self._broadcast_socket = broadcast
        self._private_socket = private
        self._private_port = private.getsockname()[1]

    def _base_message(self, kind: str) -> dict:
        return {
            "protocol": PROTOCOL_NAME,
            "version": PROTOCOL_VERSION,
            "type": kind,
            "sender": self.name,
            "sender_id": self.peer_id,
            "private_port": self.private_port,
        }

    def _send_broadcast(self, message: dict) -> None:
        if self._broadcast_socket is None:
            raise ChatError("peer has not started")
        self._send(self._broadcast_socket, message, (self.broadcast_address, self.port))

    def _send_unicast(self, message: dict, endpoint: tuple[str, int]) -> None:
        if self._private_socket is None:
            raise ChatError("peer has not started")
        self._send(self._private_socket, message, endpoint)

    def _send(self, sock: socket.socket, message: dict, endpoint: tuple[str, int]) -> None:
        data = encode_message(message)
        with self._send_lock:
            sent = sock.sendto(data, endpoint)
        if sent != len(data):
            raise OSError(f"short UDP send: {sent} of {len(data)} bytes")
        self.log.sent(endpoint, message["type"], len(data))

    def _receive_loop(self, sock: socket.socket | None) -> None:
        if sock is None:
            return
        while not self._stop_event.is_set():
            try:
                # Read the complete UDP payload, then enforce our smaller protocol
                # limit in decode_message. This also avoids WSAEMSGSIZE on Windows,
                # allowing oversized datagrams to be logged with source and size.
                data, source = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    return
                continue
            try:
                message = decode_message(data)
                self._handle_message(message, source)
            except (InvalidMessage, CryptoError, UnicodeError, ValueError) as error:
                self.log.dropped(source, "invalid", len(data), str(error))
            except Exception as error:  # A hostile datagram must never kill reception.
                self.log.dropped(source, "handler-error", len(data), repr(error))
            else:
                self.log.received(source, message["type"], len(data))

    def _handle_message(self, message: dict, source: tuple[str, int]) -> None:
        sender_id = message["sender_id"]
        if sender_id == self.peer_id:
            return
        kind = message["type"]
        endpoint = (source[0], message["private_port"])

        if kind == "conflict":
            if message["target_id"] == self.peer_id and message["name"] == self.name:
                with self._state_lock:
                    local_state = self._state
                if local_state == "starting" or duplicate_name_loser(self.peer_id, sender_id):
                    self._lose_name_conflict()
            return

        if message["sender"] == self.name:
            with self._state_lock:
                local_state = self._state
            if kind == "presence" and message.get("target_id") == self.peer_id:
                self._lose_name_conflict()
                return
            if kind == "join" and local_state == "joined":
                self._send_name_conflict(sender_id, endpoint)
                return
            if duplicate_name_loser(self.peer_id, sender_id):
                self._lose_name_conflict()
            else:
                self._send_name_conflict(sender_id, endpoint)
            return

        if kind == "join":
            joined = self.peers.upsert(sender_id, message["sender"], endpoint)
            if joined:
                self._emit(f"* {message['sender']} joined the chat")
            response = {**self._base_message("presence"), "target_id": sender_id}
            self._send_unicast(response, endpoint)
            return

        if kind == "presence":
            if message["target_id"] != self.peer_id:
                return
            joined = self.peers.upsert(sender_id, message["sender"], endpoint)
            if joined:
                self._emit(f"* {message['sender']} joined the chat")
            return

        if kind == "heartbeat":
            joined = self.peers.upsert(sender_id, message["sender"], endpoint)
            if joined:
                self._emit(f"* {message['sender']} joined the chat")
            return

        if kind == "leave":
            departed = self.peers.remove(sender_id)
            if departed is not None:
                self._emit(f"* {departed.name} left the chat")
            return

        if kind == "general":
            self._observe_sender(message, endpoint)
            if not self._remember_message(message["message_id"]):
                return
            self._emit(f"[general] {message['sender']}: {message['text']}")
            return

        if kind == "private":
            if message["recipient"] != self.name:
                raise InvalidMessage("private message addressed to another user")
            text = decrypt_private(
                self.key,
                message["nonce"],
                message["ciphertext"],
                self._private_aad(message),
            )
            validate_chat_text(text)
            self._observe_sender(message, endpoint)
            self._emit(f"[private] {message['sender']}: {text}")

    def _observe_sender(self, message: dict, endpoint: tuple[str, int]) -> None:
        joined = self.peers.upsert(message["sender_id"], message["sender"], endpoint)
        if joined:
            self._emit(f"* {message['sender']} joined the chat")

    def _private_aad(self, message: dict) -> bytes:
        fields = (
            self.port,
            message["sender"],
            message["sender_id"],
            message["private_port"],
            message["recipient"],
            message["message_id"],
        )
        return "|".join(str(field) for field in fields).encode("utf-8")

    def _maintenance_loop(self) -> None:
        next_heartbeat = time.monotonic() + self.heartbeat_interval
        poll_interval = min(0.1, self.heartbeat_interval)
        while not self._stop_event.wait(poll_interval):
            now = time.monotonic()
            with self._state_lock:
                joined = self._state == "joined"
            if joined and now >= next_heartbeat:
                try:
                    self._send_broadcast(self._base_message("heartbeat"))
                except OSError:
                    pass
                next_heartbeat = now + self.heartbeat_interval
            for peer in self.peers.expire(now=now, timeout=self.peer_timeout):
                self._emit(f"* {peer.name} left the chat (timeout)")

    def _send_name_conflict(self, target_id: str, endpoint: tuple[str, int]) -> None:
        conflict = {
            **self._base_message("conflict"),
            "target_id": target_id,
            "name": self.name,
        }
        self._send_unicast(conflict, endpoint)

    def _lose_name_conflict(self) -> None:
        self._conflict_event.set()
        with self._state_lock:
            already_joined = self._state == "joined"
            if already_joined:
                self._state = "conflicted"
        if already_joined:
            self._emit(f"* name conflict: {self.name!r} is already in use; disconnecting")
            threading.Thread(
                target=self.stop,
                kwargs={"announce": False},
                name=f"lan-chat-conflict-stop-{self.name}",
                daemon=True,
            ).start()

    def _remember_message(self, message_id: str) -> bool:
        with self._seen_lock:
            if message_id in self._seen_message_ids:
                return False
            self._seen_message_ids[message_id] = None
            while len(self._seen_message_ids) > 2048:
                self._seen_message_ids.popitem(last=False)
            return True

    def _forget_message(self, message_id: str) -> None:
        with self._seen_lock:
            self._seen_message_ids.pop(message_id, None)

    def _require_joined(self) -> None:
        with self._state_lock:
            if self._state != "joined":
                raise ChatError("peer is not joined")

    def _emit(self, text: str) -> None:
        self.on_event(text)


def _safe_filename(value: str) -> str:
    safe = "".join(character if character.isalnum() or character in "-_" else "_" for character in value)
    return safe or "peer"
