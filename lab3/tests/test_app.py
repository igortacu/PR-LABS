import tempfile
import unittest
from pathlib import Path

from lab3.lan_chat.app import LanChatPeer, OfflinePeerError
from lab3.lan_chat.cli import CommandError, parse_command


class CommandTests(unittest.TestCase):
    def test_general_and_all_slash_commands_parse(self):
        self.assertEqual(parse_command("hello all").action, "general")
        self.assertEqual(parse_command("hello all").text, "hello all")
        private = parse_command("/msg Ion meet at five")
        self.assertEqual((private.action, private.target, private.text), ("private", "Ion", "meet at five"))
        self.assertEqual(parse_command("/users").action, "users")
        self.assertEqual(parse_command("/quit").action, "quit")

    def test_bad_and_incomplete_commands_are_rejected(self):
        for line in ("", "/msg", "/msg Ion", "/unknown", "/users extra", "/quit now"):
            with self.subTest(line=line):
                with self.assertRaises(CommandError):
                    parse_command(line)


class EngineUnitTests(unittest.TestCase):
    def test_private_message_to_offline_name_gets_actionable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            peer = LanChatPeer(
                "Ana",
                5000,
                "passphrase",
                log_path=Path(directory) / "ana.log",
            )

            with self.assertRaisesRegex(OfflinePeerError, "Ion is not online"):
                peer.send_private("Ion", "hello")


if __name__ == "__main__":
    unittest.main()
