from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def token_hash(value: str) -> str:
    if settings.session_secret:
        return hmac.new(
            settings.session_secret.encode("utf-8"),
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def random_token(bytes_count: int = 32) -> str:
    return base64.urlsafe_b64encode(os.urandom(bytes_count)).decode("ascii").rstrip("=")


def _master_key(value: str) -> bytes:
    if not value:
        raise RuntimeError("USER_SECRET_MASTER_KEY 未配置，不能保存用户 API Key")
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(decoded) == 32:
            return decoded
    except (ValueError, UnicodeError):
        pass
    return hashlib.sha256(value.encode("utf-8")).digest()


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: str
    nonce: str
    key_version: int = 1


class SecretCipher:
    def __init__(self, master_key: str | None = None) -> None:
        self._aes = AESGCM(_master_key(master_key if master_key is not None else settings.user_secret_master_key))

    def encrypt(self, value: str, *, user_id: int, kind: str) -> EncryptedValue:
        nonce = os.urandom(12)
        aad = self._aad(user_id, kind, 1)
        ciphertext = self._aes.encrypt(nonce, value.encode("utf-8"), aad)
        return EncryptedValue(
            ciphertext=base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            nonce=base64.urlsafe_b64encode(nonce).decode("ascii"),
        )

    def decrypt(self, ciphertext: str, nonce: str, *, user_id: int, kind: str, key_version: int = 1) -> str:
        decoded_ciphertext = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
        decoded_nonce = base64.urlsafe_b64decode(nonce.encode("ascii"))
        plaintext = self._aes.decrypt(decoded_nonce, decoded_ciphertext, self._aad(user_id, kind, key_version))
        return plaintext.decode("utf-8")

    @staticmethod
    def _aad(user_id: int, kind: str, key_version: int) -> bytes:
        return f"stock-info:{user_id}:{kind}:v{key_version}".encode("utf-8")
