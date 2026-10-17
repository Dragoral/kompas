"""Криптография хранения: envelope encryption с ключом на каждого пациента.

    KEK (мастер-ключ, вне БД)  --AES-256-GCM-->  DEK пациента (в БД только в обёрнутом виде)
    DEK пациента               --AES-256-GCM-->  персональные данные и свободный текст

* Каждый шифртекст привязан через AAD к полю и пациенту: подмена значений между
  полями или пациентами обнаруживается при расшифровке (InvalidTag).
* Nonce 96 бит из CSPRNG на каждую запись (вероятность коллизии пренебрежима
  при << 2^32 записей на ключ).
* Ротация KEK: в шифртексте хранится идентификатор ключа (kid); старые ключи
  остаются в MASTER_KEYS для расшифровки, rewrap_all() переобёртывает DEK.
* Крипто-шреддинг: уничтожение DEK делает все данные пациента невосстановимыми
  (в том числе в резервных копиях) — реализация права на удаление (152-ФЗ, ст. 21).
* Слепой индекс: HMAC-SHA256 с отдельным ключом (HKDF от KEK) — поиск пациента
  по ФИО/телефону без хранения их в открытом виде.

Production: KEK хранится в HSM/KMS; для аттестации ИСПДн по требованиям ФСБ/ФСТЭК
провайдер шифрования заменяется на сертифицированное СКЗИ с ГОСТ Р 34.12-2015
(«Кузнечик») — интерфейс Cipher рассчитан на такую замену.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import BASE_DIR

VERSION = "v1"


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class Cipher:
    """AES-256-GCM. Формат: v1:<kid>:<base64url(nonce || ciphertext || tag)>."""

    @staticmethod
    def seal(key: bytes, kid: str, plaintext: bytes, aad: bytes) -> str:
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, plaintext, aad)
        return f"{VERSION}:{kid}:{_b64e(nonce + ct)}"

    @staticmethod
    def parse(token: str) -> tuple[str, bytes, bytes]:
        ver, kid, body = token.split(":", 2)
        if ver != VERSION:
            raise ValueError("Неизвестная версия шифртекста")
        raw = _b64d(body)
        return kid, raw[:12], raw[12:]

    @staticmethod
    def open(key: bytes, nonce: bytes, ct: bytes, aad: bytes) -> bytes:
        return AESGCM(key).decrypt(nonce, ct, aad)


def _load_master_keys() -> tuple[str, dict[str, bytes]]:
    """MASTER_KEYS="kid1:base64,kid0:base64" — первый ключ текущий.
    Для локальной разработки ключ генерируется в data/master.key (права 600)."""
    spec = os.getenv("MASTER_KEYS")
    if not spec:
        path = Path(os.getenv("MASTER_KEY_FILE", BASE_DIR / "data" / "master.key"))
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"k1:{_b64e(os.urandom(32))}")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        spec = path.read_text().strip()
    keys: dict[str, bytes] = {}
    current = None
    for part in spec.split(","):
        kid, b64 = part.strip().split(":", 1)
        k = _b64d(b64)
        if len(k) != 32:
            raise ValueError(f"Мастер-ключ {kid}: требуется 256 бит")
        keys[kid] = k
        current = current or kid
    return current, keys


class Vault:
    DEK_TTL_SEC = 300

    def __init__(self):
        self.kid, self.keks = _load_master_keys()
        self._cache: dict[int, tuple[bytes, float]] = {}
        self._lock = threading.Lock()
        self._bidx_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"blind-index-v1").derive(self.keks[self.kid])

    # --- ключи пациентов -------------------------------------------------
    def _wrap(self, patient_id: int, dek: bytes) -> str:
        return Cipher.seal(self.keks[self.kid], self.kid, dek, f"dek|patient:{patient_id}".encode())

    def _unwrap(self, patient_id: int, wrapped: str) -> bytes:
        kid, nonce, ct = Cipher.parse(wrapped)
        return Cipher.open(self.keks[kid], nonce, ct, f"dek|patient:{patient_id}".encode())

    def dek(self, db, patient_id: int, create: bool = True) -> bytes:
        from .models import PatientKey  # локальный импорт: models импортирует crypto
        with self._lock:
            hit = self._cache.get(patient_id)
            if hit and hit[1] > time.monotonic():
                return hit[0]
        row = db.get(PatientKey, patient_id)
        if row is None or row.wrapped_dek is None:
            if row is not None or not create:
                raise KeyError(f"Ключ пациента {patient_id} уничтожен")
            key = AESGCM.generate_key(bit_length=256)
            db.add(PatientKey(patient_id=patient_id, wrapped_dek=self._wrap(patient_id, key), kek_id=self.kid))
            db.flush()
        else:
            key = self._unwrap(patient_id, row.wrapped_dek)
        with self._lock:
            self._cache[patient_id] = (key, time.monotonic() + self.DEK_TTL_SEC)
        return key

    def shred(self, db, patient_id: int) -> None:
        from .models import PatientKey, now
        row = db.get(PatientKey, patient_id)
        if row:
            row.wrapped_dek, row.destroyed_at = None, now()
        with self._lock:
            self._cache.pop(patient_id, None)

    def rewrap_all(self, db) -> int:
        """Переобернуть все DEK текущим KEK (после ротации мастер-ключа)."""
        from sqlalchemy import select
        from .models import PatientKey
        n = 0
        for row in db.scalars(select(PatientKey).where(PatientKey.wrapped_dek.is_not(None), PatientKey.kek_id != self.kid)):
            row.wrapped_dek, row.kek_id = self._wrap(row.patient_id, self._unwrap(row.patient_id, row.wrapped_dek)), self.kid
            n += 1
        db.commit()
        return n

    # --- поля ------------------------------------------------------------
    def seal(self, db, patient_id: int, field: str, value: str | None) -> str | None:
        if value is None:
            return None
        return Cipher.seal(self.dek(db, patient_id), "dek", value.encode(), f"{field}|patient:{patient_id}".encode())

    def open(self, db, patient_id: int, field: str, token: str | None) -> str | None:
        if token is None:
            return None
        try:
            key = self.dek(db, patient_id, create=False)
        except KeyError:
            return "[данные удалены]"
        _, nonce, ct = Cipher.parse(token)
        return Cipher.open(key, nonce, ct, f"{field}|patient:{patient_id}".encode()).decode()

    # --- данные приложения (не привязанные к пациенту: секреты 2FA) ----------
    def _app_key(self, kid: str) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"app-data-v1").derive(self.keks[kid])

    def seal_app(self, field: str, value: str) -> str:
        return Cipher.seal(self._app_key(self.kid), self.kid, value.encode(), f"app|{field}".encode())

    def open_app(self, field: str, token: str) -> str:
        kid, nonce, ct = Cipher.parse(token)
        return Cipher.open(self._app_key(kid), nonce, ct, f"app|{field}".encode()).decode()

    def blind_index(self, value: str) -> str:
        norm = " ".join(value.lower().replace("ё", "е").split())
        return hmac.new(self._bidx_key, norm.encode(), hashlib.sha256).hexdigest()


vault = Vault()


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 бит


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
