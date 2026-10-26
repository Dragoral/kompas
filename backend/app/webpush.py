"""Web Push: уведомления в браузер и установленное приложение (PWA), даже когда вкладка закрыта.

Стандарты: RFC 8030 (протокол), RFC 8291 (шифрование содержимого, aes128gcm по RFC 8188),
RFC 8292 (VAPID — подпись сервера приложения). Реализовано на `cryptography` без
дополнительных зависимостей; корректность шифрования проверяется тестом по примеру из RFC 8291.

Содержимое уведомления — без медицинских сведений («Компас: новое сообщение»):
экран блокировки телефона видят посторонние.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import BASE_DIR

# Сервер отправляет запросы только на известные push-сервисы браузеров:
# адрес подписки приходит от клиента, произвольный адрес — это SSRF.
PUSH_HOSTS = (
    "fcm.googleapis.com",            # Chrome, Edge (Android), Яндекс Браузер, Opera
    "updates.push.services.mozilla.com",
    "web.push.apple.com",            # Safari, iOS 16.4+ (установленное приложение)
    ".notify.windows.com",           # Edge (Windows)
    ".push.apple.com",
)
VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:admin@kompas.local")
RECORD_SIZE = 4096


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def allowed_endpoint(endpoint: str) -> bool:
    u = urlparse(endpoint)
    host = (u.hostname or "").lower()
    return (u.scheme == "https" and not u.port and len(endpoint) <= 1024
            and any(host == h or (h.startswith(".") and host.endswith(h)) for h in PUSH_HOSTS))


# --- ключи VAPID ---------------------------------------------------------------
_key: ec.EllipticCurvePrivateKey | None = None


def _private_key() -> ec.EllipticCurvePrivateKey:
    """VAPID_PRIVATE_KEY (base64url, 32 байта) из окружения; для разработки — файл data/vapid.key."""
    global _key
    if _key is None:
        raw = os.getenv("VAPID_PRIVATE_KEY")
        if raw:
            _key = ec.derive_private_key(int.from_bytes(b64u_decode(raw), "big"), ec.SECP256R1())
        else:
            path = Path(os.getenv("VAPID_KEY_FILE", BASE_DIR / "data" / "vapid.key"))
            if path.exists():
                _key = serialization.load_pem_private_key(path.read_bytes(), None)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                _key = ec.generate_private_key(ec.SECP256R1())
                path.write_bytes(_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                    serialization.NoEncryption()))
                os.chmod(path, 0o600)
    return _key


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def public_key() -> str:
    """Публичный ключ сервера для подписки браузера (applicationServerKey)."""
    return b64u(_raw_public(_private_key().public_key()))


def vapid_header(endpoint: str, key: ec.EllipticCurvePrivateKey | None = None, ttl_s: int = 12 * 3600) -> str:
    """Authorization: vapid t=<JWT ES256>, k=<публичный ключ> (RFC 8292)."""
    key = key or _private_key()
    u = urlparse(endpoint)
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + ttl_s, "sub": VAPID_SUBJECT},
                             separators=(",", ":")).encode())
    r, s = decode_dss_signature(key.sign(f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    sig = b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={header}.{claims}.{sig}, k={b64u(_raw_public(key.public_key()))}"


# --- шифрование содержимого (RFC 8291) ----------------------------------------------
def _hmac(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def encrypt(plaintext: bytes, ua_public_b64: str, auth_b64: str, *,
            as_key: ec.EllipticCurvePrivateKey | None = None, salt: bytes | None = None) -> bytes:
    """Тело запроса aes128gcm. as_key и salt задаются только в тесте (пример из RFC 8291)."""
    ua_public = b64u_decode(ua_public_b64)
    auth = b64u_decode(auth_b64)
    as_key = as_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = _raw_public(as_key.public_key())
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ecdh = as_key.exchange(ec.ECDH(), ua_key)
    ikm = _hmac(_hmac(auth, ecdh), b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    if len(plaintext) > RECORD_SIZE - 17 - 86:
        raise ValueError("Содержимое уведомления слишком велико")
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)  # 0x02 — последняя запись
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + ciphertext


class Gone(Exception):
    """Подписка больше не действует (404/410) — удалить."""


def send(endpoint: str, p256dh: str, auth: str, payload: dict, *, ttl: int = 3600, urgency: str = "normal",
         topic: str | None = None) -> None:
    if not allowed_endpoint(endpoint):
        raise Gone("адрес подписки не относится к известному push-сервису")
    headers = {"TTL": str(ttl), "Urgency": urgency, "Content-Encoding": "aes128gcm",
               "Content-Type": "application/octet-stream", "Authorization": vapid_header(endpoint)}
    if topic:
        headers["Topic"] = topic  # заменяет недоставленное уведомление той же темы
    body = encrypt(json.dumps(payload, ensure_ascii=False).encode(), p256dh, auth)
    r = httpx.post(endpoint, content=body, headers=headers, timeout=10, follow_redirects=False)
    if r.status_code in (404, 410):
        raise Gone(f"HTTP {r.status_code}")
    if r.status_code >= 400:
        raise RuntimeError(f"push-сервис ответил HTTP {r.status_code}")
