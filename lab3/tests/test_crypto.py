import base64
import unittest

from lab3.lan_chat.crypto import (
    CryptoError,
    decrypt_private,
    derive_key,
    encrypt_private,
)


class CryptoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = derive_key("correct horse battery staple", 5000)

    def test_derivation_is_stable_and_bound_to_passphrase_and_chat_port(self):
        same = derive_key("correct horse battery staple", 5000)
        other_passphrase = derive_key("different", 5000)
        other_port = derive_key("correct horse battery staple", 5001)

        self.assertEqual(self.key, same)
        self.assertEqual(len(self.key), 32)
        self.assertNotEqual(self.key, other_passphrase)
        self.assertNotEqual(self.key, other_port)

    def test_encryptions_use_unique_12_byte_nonces_and_unicode_round_trips(self):
        aad = b"lan-chat-v1|port=5000|from=Ana|to=Ion|id=123"

        nonce_one, ciphertext_one = encrypt_private(self.key, "Ne vedem la cinci 😀", aad)
        nonce_two, ciphertext_two = encrypt_private(self.key, "Ne vedem la cinci 😀", aad)

        self.assertNotEqual(nonce_one, nonce_two)
        self.assertNotEqual(ciphertext_one, ciphertext_two)
        self.assertEqual(len(base64.b64decode(nonce_one)), 12)
        self.assertEqual(
            decrypt_private(self.key, nonce_one, ciphertext_one, aad),
            "Ne vedem la cinci 😀",
        )

    def test_wrong_key_nonce_ciphertext_and_metadata_are_rejected(self):
        aad = b"lan-chat-v1|port=5000|from=Ana|to=Ion|id=123"
        nonce, ciphertext = encrypt_private(self.key, "secret", aad)
        wrong_key = derive_key("wrong", 5000)
        changed_nonce = bytearray(base64.b64decode(nonce))
        changed_nonce[0] ^= 1
        changed_ciphertext = bytearray(base64.b64decode(ciphertext))
        changed_ciphertext[0] ^= 1

        cases = [
            (wrong_key, nonce, ciphertext, aad),
            (self.key, base64.b64encode(changed_nonce).decode(), ciphertext, aad),
            (self.key, nonce, base64.b64encode(changed_ciphertext).decode(), aad),
            (self.key, nonce, ciphertext, aad + b"-changed"),
        ]
        for args in cases:
            with self.subTest(args=args[1:]):
                with self.assertRaises(CryptoError):
                    decrypt_private(*args)

    def test_empty_passphrase_and_invalid_port_are_rejected(self):
        for passphrase, port in (("", 5000), ("ok", 0), ("ok", 70000)):
            with self.subTest(passphrase=passphrase, port=port):
                with self.assertRaises(ValueError):
                    derive_key(passphrase, port)


if __name__ == "__main__":
    unittest.main()
