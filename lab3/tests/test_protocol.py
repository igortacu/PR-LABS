import json
import unittest
import uuid

from lab3.lan_chat.protocol import (
    InvalidMessage,
    MessageTooLarge,
    decode_message,
    encode_message,
    validate_chat_text,
)


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.sender_id = str(uuid.uuid4())

    def general(self, text="hello"):
        return {
            "protocol": "lan-chat",
            "version": 1,
            "type": "general",
            "sender": "Ana",
            "sender_id": self.sender_id,
            "private_port": 45001,
            "message_id": str(uuid.uuid4()),
            "text": text,
        }

    def test_valid_message_round_trips_as_compact_utf8_json(self):
        message = self.general("Salut, lume!")

        encoded = encode_message(message)

        self.assertEqual(decode_message(encoded), message)
        self.assertNotIn(b'": ', encoded)
        self.assertNotIn(b'", "', encoded)

    def test_500_ascii_characters_fit_but_501_are_rejected(self):
        encoded = encode_message(self.general("x" * 500))

        self.assertLessEqual(len(encoded), 1400)
        with self.assertRaises(InvalidMessage):
            encode_message(self.general("x" * 501))

    def test_500_multibyte_characters_are_rejected_when_wire_packet_is_too_large(self):
        with self.assertRaises(MessageTooLarge):
            encode_message(self.general("😀" * 500))

    def test_text_validation_rejects_empty_non_string_and_nul(self):
        for value in ("", 7, "hello\x00world"):
            with self.subTest(value=value):
                with self.assertRaises(InvalidMessage):
                    validate_chat_text(value)

    def test_decode_rejects_malformed_utf8_json_and_oversized_datagram(self):
        bad_inputs = (b"\xff", b"{broken", b"x" * 1401)

        for data in bad_inputs:
            with self.subTest(data=data[:10]):
                with self.assertRaises(InvalidMessage):
                    decode_message(data)

    def test_decode_rejects_unknown_type_missing_field_wrong_type_and_extra_field(self):
        cases = []
        unknown = self.general()
        unknown["type"] = "mystery"
        cases.append(unknown)
        missing = self.general()
        del missing["sender_id"]
        cases.append(missing)
        wrong = self.general()
        wrong["private_port"] = "45001"
        cases.append(wrong)
        extra = self.general()
        extra["unexpected"] = True
        cases.append(extra)

        for message in cases:
            with self.subTest(message=message):
                data = json.dumps(message, separators=(",", ":")).encode()
                with self.assertRaises(InvalidMessage):
                    decode_message(data)

    def test_all_protocol_message_shapes_are_accepted(self):
        common = {
            "protocol": "lan-chat",
            "version": 1,
            "sender": "Ana",
            "sender_id": self.sender_id,
            "private_port": 45001,
        }
        messages = [
            {**common, "type": kind}
            for kind in ("join", "heartbeat", "leave")
        ]
        messages.extend(
            [
                {**common, "type": "presence", "target_id": str(uuid.uuid4())},
                {
                    **common,
                    "type": "conflict",
                    "target_id": str(uuid.uuid4()),
                    "name": "Ana",
                },
                self.general(),
                {
                    **common,
                    "type": "private",
                    "message_id": str(uuid.uuid4()),
                    "recipient": "Ion",
                    "nonce": "AAECAwQFBgcICQoL",
                    "ciphertext": "YWJjZGVmZ2hpamtsbW5vcA==",
                },
            ]
        )

        for message in messages:
            with self.subTest(kind=message["type"]):
                self.assertEqual(decode_message(encode_message(message)), message)


if __name__ == "__main__":
    unittest.main()
