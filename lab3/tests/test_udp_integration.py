import base64
import json
import socket
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from lab3.lan_chat.app import LanChatPeer, NameInUseError
from lab3.lan_chat.crypto import encrypt_private
from lab3.lan_chat.protocol import MessageTooLarge, encode_message


def unused_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition did not become true before timeout")


class EventCollector:
    def __init__(self):
        self.items = []
        self.lock = threading.Lock()

    def __call__(self, text):
        with self.lock:
            self.items.append(text)

    def count(self, text):
        with self.lock:
            return self.items.count(text)

    def contains(self, text):
        with self.lock:
            return text in self.items


class UdpIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.peers = []

    def add_peer(self, name, port, events, **overrides):
        options = {
            "broadcast_address": "255.255.255.255",
            "discovery_wait": 0.25,
            "heartbeat_interval": 0.2,
            "peer_timeout": 0.65,
            "on_event": events,
            "log_path": Path(self.temporary.name) / f"{name}-{len(self.peers)}.log",
        }
        options.update(overrides)
        peer = LanChatPeer(name, port, "shared secret", **options)
        self.peers.append(peer)
        self.addCleanup(peer.stop)
        return peer

    def test_two_peers_discover_chat_privately_survive_junk_and_leave(self):
        port = unused_udp_port()
        ana_events = EventCollector()
        ion_events = EventCollector()
        ana = self.add_peer("Ana", port, ana_events)
        ion = self.add_peer("Ion", port, ion_events)

        ana.start()
        ion.start()
        wait_for(lambda: ana.peers.get_by_name("Ion") is not None)
        wait_for(lambda: ion.peers.get_by_name("Ana") is not None)
        self.assertNotEqual(ana.private_port, ion.private_port)

        ana.send_general("hello everyone")
        wait_for(lambda: ion_events.contains("[general] Ana: hello everyone"))
        wait_for(lambda: ana_events.contains("[general] Ana: hello everyone"))
        self.assertEqual(ana_events.count("[general] Ana: hello everyone"), 1)

        ana.send_private("Ion", "see you at five")
        wait_for(lambda: ion_events.contains("[private] Ana: see you at five"))
        self.assertFalse(ana_events.contains("[private] Ana: see you at five"))

        sent_general_before = sum(
            json.loads(line)["action"] == "sent" and json.loads(line)["kind"] == "general"
            for line in ana.log.path.read_text().splitlines()
        )
        with self.assertRaises(MessageTooLarge):
            ana.send_general("😀" * 500)
        sent_general_after = sum(
            json.loads(line)["action"] == "sent" and json.loads(line)["kind"] == "general"
            for line in ana.log.path.read_text().splitlines()
        )
        self.assertEqual(sent_general_after, sent_general_before)

        common = {
            "protocol": "lan-chat",
            "version": 1,
            "type": "general",
            "sender": "Mallory",
            "sender_id": str(uuid.uuid4()),
            "private_port": 49999,
            "message_id": str(uuid.uuid4()),
            "text": "not displayed",
        }
        malformed_packets = [
            b"\xff",
            b'{"broken"',
            json.dumps({**common, "type": "unknown"}).encode(),
            json.dumps({key: value for key, value in common.items() if key != "sender_id"}).encode(),
        ]
        dropped_before = sum(
            json.loads(line)["action"] == "dropped"
            for line in ion.log.path.read_text().splitlines()
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as junk:
            junk.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for packet in malformed_packets:
                junk.sendto(packet, ("255.255.255.255", port))
            junk.sendto(b"x" * 2000, ("127.0.0.1", ion.private_port))
        wait_for(
            lambda: sum(
                json.loads(line)["action"] == "dropped"
                for line in ion.log.path.read_text().splitlines()
            )
            >= dropped_before + len(malformed_packets) + 1
        )

        tampered_id = str(uuid.uuid4())
        aad = "|".join(
            str(value)
            for value in (port, ana.name, ana.peer_id, ana.private_port, ion.name, tampered_id)
        ).encode()
        nonce, ciphertext = encrypt_private(ana.key, "tampered secret", aad)
        changed = bytearray(base64.b64decode(ciphertext))
        changed[0] ^= 1
        tampered = {
            "protocol": "lan-chat",
            "version": 1,
            "type": "private",
            "sender": ana.name,
            "sender_id": ana.peer_id,
            "private_port": ana.private_port,
            "message_id": tampered_id,
            "recipient": ion.name,
            "nonce": nonce,
            "ciphertext": base64.b64encode(changed).decode(),
        }
        dropped_before_tamper = sum(
            json.loads(line)["action"] == "dropped"
            for line in ion.log.path.read_text().splitlines()
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as attacker:
            attacker.sendto(encode_message(tampered), ("127.0.0.1", ion.private_port))
        wait_for(
            lambda: sum(
                json.loads(line)["action"] == "dropped"
                for line in ion.log.path.read_text().splitlines()
            )
            > dropped_before_tamper
        )
        self.assertFalse(ion_events.contains("[private] Ana: tampered secret"))

        ion.send_general("still alive")
        wait_for(lambda: ana_events.contains("[general] Ion: still alive"))

        ion.stop()
        wait_for(lambda: ana_events.contains("* Ion left the chat"))

    def test_existing_name_is_rejected_and_stale_private_send_remains_healthy(self):
        port = unused_udp_port()
        first_events = EventCollector()
        first = self.add_peer("Ana", port, first_events)
        duplicate = self.add_peer("Ana", port, EventCollector())
        first.start()

        with self.assertRaises(NameInUseError):
            duplicate.start()

        ion = self.add_peer("Ion", port, EventCollector())
        ion.start()
        wait_for(lambda: first.peers.get_by_name("Ion") is not None)
        ion.stop(announce=False)
        first.send_private("Ion", "this UDP datagram may be lost")
        self.assertTrue(first.is_running)
        wait_for(lambda: first_events.contains("* Ion left the chat (timeout)"), timeout=2.0)

    def test_lost_startup_packets_still_converge_to_one_duplicate_name(self):
        port = unused_udp_port()
        first = self.add_peer(
            "Ana",
            port,
            EventCollector(),
            broadcast_address="127.255.255.255",
            heartbeat_interval=0.15,
        )
        second = self.add_peer(
            "Ana",
            port,
            EventCollector(),
            broadcast_address="127.255.255.255",
            heartbeat_interval=0.15,
        )
        first.start()
        second.start()
        self.assertTrue(first.is_running and second.is_running)

        first.broadcast_address = "255.255.255.255"
        second.broadcast_address = "255.255.255.255"
        wait_for(lambda: first.is_running != second.is_running, timeout=2.0)

        self.assertEqual(sum((first.is_running, second.is_running)), 1)

    def test_timeout_is_detected_close_to_configured_deadline(self):
        port = unused_udp_port()
        observer_events = EventCollector()
        observer = self.add_peer(
            "Ana",
            port,
            observer_events,
            discovery_wait=0.1,
            heartbeat_interval=1.0,
            peer_timeout=0.25,
        )
        departing = self.add_peer(
            "Ion",
            port,
            EventCollector(),
            discovery_wait=0.1,
            heartbeat_interval=1.0,
            peer_timeout=0.25,
        )
        observer.start()
        departing.start()
        wait_for(lambda: observer.peers.get_by_name("Ion") is not None)

        started = time.monotonic()
        departing.stop(announce=False)
        wait_for(lambda: observer_events.contains("* Ion left the chat (timeout)"), timeout=0.7)

        self.assertLess(time.monotonic() - started, 0.7)


if __name__ == "__main__":
    unittest.main()
