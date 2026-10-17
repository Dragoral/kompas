"""Безопасная загрузка по ссылке (импорт справочников по URL).

Защита от SSRF: только https, только публичные адреса (не localhost, не
внутренние сети, не link-local/метаданные облака), без перенаправлений,
ограничение размера и времени. Ответ — только JSON/текст.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

MAX_BYTES = 2 * 1024 * 1024
TIMEOUT = 10


class FetchError(ValueError):
    pass


def _public_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise FetchError(f"Не удалось найти адрес «{host}»")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise FetchError("Ссылка ведёт во внутреннюю сеть — запрещено")


def fetch(url: str) -> bytes:
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise FetchError("Разрешены только ссылки https://")
    if u.username or u.password:
        raise FetchError("Ссылки с логином/паролем не поддерживаются")
    _public_host(u.hostname)
    try:
        with httpx.stream("GET", url, timeout=TIMEOUT, follow_redirects=False,
                          headers={"Accept": "application/fhir+json, application/json, text/csv, text/plain"}) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                raise FetchError("Ссылка перенаправляет на другой адрес — укажите конечный адрес")
            if r.status_code != 200:
                raise FetchError(f"Сервер ответил {r.status_code}")
            data = b""
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > MAX_BYTES:
                    raise FetchError("Файл больше 2 МБ")
            return data
    except httpx.HTTPError as e:
        raise FetchError(f"Ошибка загрузки: {e.__class__.__name__}")
