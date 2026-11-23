"""Authenticated encryption for private chat datagrams."""

from __future__ import annotations

import base64
import binascii
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class CryptoError(ValueError):
    """A private message could not be authenticated or decoded."""


def derive_key(passphrase: str, chat_port: int) -> bytes:
    if not isinstance(passphrase, str) or not passphrase:
        raise ValueError("passphrase must not be empty")
    if isinstance(chat_port, bool) or not isinstance(chat_port, int) or not (1 <= chat_port <= 65535):
        raise ValueError("chat port must be an integer from 1 to 65535")
    salt_material = f"lan-chat-v1|port={chat_port}".encode("ascii")
    salt = hashlib.sha256(salt_material).digest()[:16]
    derivation = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    return derivation.derive(passphrase.encode("utf-8"))


def encrypt_private(key: bytes, plaintext: str, associated_data: bytes) -> tuple[str, str]:
    if not isinstance(plaintext, str):
        raise ValueError("plaintext must be a string")
    nonce = os.urandom(12)
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, plaintext.encode("utf-8"), associated_data)
    return (
        base64.b64encode(nonce).decode("ascii"),
        base64.b64encode(ciphertext).decode("ascii"),
    )


def decrypt_private(
    key: bytes,
    nonce_b64: str,
    ciphertext_b64: str,
    associated_data: bytes,
) -> str:
    try:
        nonce = base64.b64decode(nonce_b64, validate=True)
        ciphertext = base64.b64decode(ciphertext_b64, validate=True)
        if len(nonce) != 12:
            raise CryptoError("nonce must be 12 bytes")
        plaintext = ChaCha20Poly1305(key).decrypt(nonce, ciphertext, associated_data)
        return plaintext.decode("utf-8")
    except (binascii.Error, InvalidTag, UnicodeDecodeError, ValueError) as error:
        if isinstance(error, CryptoError):
            raise
        raise CryptoError("private message authentication failed") from error
