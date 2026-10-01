"""Encryption of the secrets users store (API keys, tokens): AES-256-GCM.

* A **key ring**: ``SECRETS_ENCRYPTION_KEYS="id:key,id:key"`` (each key is 32
  random bytes, urlsafe-base64). The first entry encrypts; every entry can
  decrypt, so a key is rotated by prepending a new one, running
  ``python -m server.cli rewrap-secrets``, then dropping the old one.
* The **AAD** binds a ciphertext to its owner and kind (``user_id|kind``): a row
  copied to another user, or under another kind, fails to decrypt instead of
  handing one user's key to someone else.
* In development only, with no ring configured, a key is derived from
  ``AUTH_SECRET_KEY`` so the local stack works without setup. Production refuses
  to start without a ring (see ``Config.production_problems``).

Losing the ring means every user must enter their secrets again: back it up
apart from the database (docs/security.md).
"""

import base64
import binascii
import hashlib
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_BYTES = 12
KEY_BYTES = 32
_DEV_KEY_ID = "dev"


class CryptoError(Exception):
    """A secret can't be encrypted or decrypted. Never carries plaintext."""


def generate_key() -> str:
    """A fresh ring key, ready for ``SECRETS_ENCRYPTION_KEYS``."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode("ascii")


def _decode_key(encoded: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except (binascii.Error, ValueError) as exc:
        raise CryptoError("an encryption key is not valid base64") from exc
    if len(key) != KEY_BYTES:
        raise CryptoError(f"an encryption key must be {KEY_BYTES} bytes")
    return key


def parse_ring(raw: str) -> List[Tuple[str, bytes]]:
    """``"k2:<key>,k1:<key>"`` → ``[("k2", key), ("k1", key)]`` (first = primary)."""
    ring: List[Tuple[str, bytes]] = []
    for entry in (part.strip() for part in raw.split(",")):
        if not entry:
            continue
        key_id, sep, encoded = entry.partition(":")
        if not sep or not key_id.strip() or not encoded.strip():
            raise CryptoError("SECRETS_ENCRYPTION_KEYS entries look like 'id:key'")
        ring.append((key_id.strip(), _decode_key(encoded.strip())))
    if len({key_id for key_id, _ in ring}) != len(ring):
        raise CryptoError("SECRETS_ENCRYPTION_KEYS repeats a key id")
    return ring


def aad_for(user_id: str, kind: str) -> bytes:
    return f"{user_id}|{kind}".encode("utf-8")


@dataclass(frozen=True)
class SecretBox:
    ring: Tuple[Tuple[str, bytes], ...]

    @property
    def primary_id(self) -> str:
        return self.ring[0][0]

    def encrypt(self, plaintext: str, aad: bytes) -> Tuple[str, str]:
        """``(ciphertext, key_id)`` — the ciphertext is urlsafe-base64 of nonce‖data."""
        key_id, key = self.ring[0]
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
        return base64.urlsafe_b64encode(nonce + sealed).decode("ascii"), key_id

    def decrypt(self, ciphertext: str, key_id: str, aad: bytes) -> str:
        keys: Dict[str, bytes] = dict(self.ring)
        key = keys.get(key_id)
        if key is None:
            raise CryptoError(f"encryption key '{key_id}' is not in the key ring")
        try:
            raw = base64.urlsafe_b64decode(ciphertext + "=" * (-len(ciphertext) % 4))
            plain = AESGCM(key).decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], aad)
        except (InvalidTag, binascii.Error, ValueError) as exc:
            # Wrong key, wrong owner/kind (AAD) or a tampered value: same answer.
            raise CryptoError("the secret cannot be decrypted") from exc
        return plain.decode("utf-8")


def build_box(raw_ring: str, dev_fallback_secret: str = "") -> SecretBox:
    """The box for a configured ring, or the derived dev one when ``raw_ring`` is empty."""
    ring = parse_ring(raw_ring)
    if ring:
        return SecretBox(tuple(ring))
    if not dev_fallback_secret:
        raise CryptoError("SECRETS_ENCRYPTION_KEYS is not configured")
    derived = hashlib.sha256(b"datasetgen-dev-secrets|" + dev_fallback_secret.encode())
    return SecretBox(((_DEV_KEY_ID, derived.digest()),))
