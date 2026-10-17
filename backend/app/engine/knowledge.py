"""Справочники: шкалы, препараты, наборы правил.

Источник по умолчанию — YAML в backend/knowledge (под версионным контролем, с
указанием источников). При первом запуске они загружаются в БД; дальше
администратор может добавлять/менять элементы через API без изменения кода и
перезапуска. Движок читает из in-memory кэша, который сбрасывается при записи.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import KNOWLEDGE_DIR
import hashlib

from ..models import KnowledgeItem, KnowledgeVersion, now
from . import logic

KINDS = {"scales": "scale", "drugs": "drug", "rules": "rules", "guidelines": "guideline", "dictionaries": "dictionary"}

_lock = threading.Lock()
_cache: dict | None = None
_cache_sig: tuple | None = None
_checked_at = 0.0
RECHECK_SEC = 5  # при нескольких процессах правка в админке видна всем за ≤ 5 с


def load_yaml_dir(root: Path = KNOWLEDGE_DIR) -> list[tuple[str, str, dict]]:
    items = []
    for sub, kind in KINDS.items():
        for f in sorted((root / sub).glob("*.yaml")):
            # JSON-нормализация: даты и прочие YAML-типы -> строки
            body = json.loads(json.dumps(yaml.safe_load(f.read_text(encoding="utf-8")), default=str, ensure_ascii=False))
            code = f.stem if kind == "dictionary" else (body.get("code") or body.get("id") or f.stem)
            items.append((kind, code, body))
    return items


def body_hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def seed(db: Session, propose_changes: bool = False, user_id: int | None = None) -> int:
    """Первичная загрузка из репозитория (версия 1, одобрена). При propose_changes
    изменения в YAML относительно действующих версий оформляются как черновики,
    которые вступают в силу только после клинического одобрения."""
    n = 0
    for kind, code, body in load_yaml_dir():
        validate(kind, body)
        row = db.scalar(select(KnowledgeItem).where(KnowledgeItem.kind == kind, KnowledgeItem.code == code))
        if row is None:
            db.add(KnowledgeItem(kind=kind, code=code, body=body))
            db.add(KnowledgeVersion(kind=kind, code=code, version=1, body=body, body_sha256=body_hash(body),
                                    status="approved", change_note="Загрузка из репозитория", decided_at=now()))
            n += 1
        elif propose_changes and body_hash(body) != body_hash(row.body):
            propose(db, kind, code, body, user_id, "Обновление из репозитория")
            n += 1
    db.commit()
    invalidate()
    return n


def propose(db: Session, kind: str, code: str, body: dict, user_id: int | None, note: str | None) -> KnowledgeVersion:
    validate(kind, body)
    v = KnowledgeVersion(kind=kind, code=code, body=body, body_sha256=body_hash(body), status="draft",
                         change_note=note, proposed_by=user_id)
    db.add(v)
    db.flush()
    return v


def approve(db: Session, v: KnowledgeVersion, reviewer_id: int, comment: str | None) -> KnowledgeItem:
    """Ввод одобренной версии в действие; предыдущая помечается superseded."""
    validate(v.kind, v.body)
    row = db.scalar(select(KnowledgeItem).where(KnowledgeItem.kind == v.kind, KnowledgeItem.code == v.code))
    for old in db.scalars(select(KnowledgeVersion).where(KnowledgeVersion.kind == v.kind, KnowledgeVersion.code == v.code,
                                                         KnowledgeVersion.status == "approved")):
        old.status = "superseded"
    if row is None:
        row = KnowledgeItem(kind=v.kind, code=v.code, body=v.body, version=1, updated_by=reviewer_id)
        db.add(row)
    else:
        row.body, row.version, row.updated_at, row.updated_by, row.active = v.body, row.version + 1, now(), reviewer_id, True
    v.status, v.version, v.decided_by, v.decided_at, v.decision_comment = "approved", row.version, reviewer_id, now(), comment
    invalidate()
    return row


def validate(kind: str, body: dict) -> None:
    """Проверка структуры перед сохранением — некорректное правило не попадёт в работу."""
    def need(*keys):
        missing = [k for k in keys if k not in body]
        if missing:
            raise ValueError(f"{kind}: отсутствуют поля {missing}")

    if kind == "scale":
        need("code", "title", "items", "bands", "respondent", "license", "validation")
        for it in body["items"]:
            if "n" not in it or "text" not in it or not it.get("options"):
                raise ValueError(f"Шкала {body['code']}: у пункта нет n/text/options")
    elif kind == "drug":
        need("id", "trade_name", "inn", "indications", "registration", "sources")
        for c in body.get("contraindications", []) + body.get("cautions", []):
            logic.validate(c["when"])
        for ind in body["indications"]:
            if "requires" in ind:
                logic.validate(ind["requires"])
    elif kind == "guideline":
        need("code", "id", "title", "icd10", "status", "url", "theses", "published")
        for k, t in body["theses"].items():
            if "text" not in t or "section" not in t:
                raise ValueError(f"КР {body['code']}: тезис {k} без text/section")
        for ln in (body.get("lines") or {}).values():
            if ln.get("thesis") and ln["thesis"] not in body["theses"]:
                raise ValueError(f"КР {body['code']}: линия ссылается на несуществующий тезис {ln['thesis']}")
    elif kind == "rules":
        need("rules")
        if "applies_when" in body:
            logic.validate(body["applies_when"])
        for cond in (body.get("applies") or {}).values():
            logic.validate(cond)
        for r in body["rules"]:
            if "applies" in r and r["applies"] not in (body.get("applies") or {}):
                raise ValueError(f"Правило {r.get('id')}: неизвестная область применения {r['applies']}")
        for r in body["rules"]:
            if "id" not in r or "when" not in r:
                raise ValueError("Правило без id/when")
            logic.validate(r["when"])


def invalidate() -> None:
    global _cache
    with _lock:
        _cache = None


def _signature(db: Session) -> tuple:
    from sqlalchemy import func
    return tuple(db.execute(select(func.count(), func.coalesce(func.sum(KnowledgeItem.version), 0),
                                   func.max(KnowledgeItem.updated_at))).one())


def get(db: Session) -> dict:
    global _cache, _cache_sig, _checked_at
    import time as _t
    with _lock:
        if _cache is not None and _t.monotonic() - _checked_at < RECHECK_SEC:
            return _cache
    sig = _signature(db)
    with _lock:
        _checked_at = _t.monotonic()
        if _cache is not None and sig == _cache_sig:
            return _cache
    rows = db.scalars(select(KnowledgeItem).where(KnowledgeItem.active.is_(True))).all()
    kb: dict = {"scale": {}, "drug": {}, "rules": {}, "dictionary": {}, "guideline": {}, "versions": {}}
    for r in rows:
        kb.setdefault(r.kind, {})[r.code] = r.body
        kb["versions"][(r.kind, r.code)] = r.version
    # обратный индекс: любое название (МНН/торговое) -> МНН
    subs = kb["dictionary"].get("drug_classes", {}).get("substances", {})
    names = {}
    for inn, meta in subs.items():
        names[inn.lower()] = inn
        for a in meta.get("aliases", []):
            names[a.lower()] = inn
    kb["name_index"] = names
    with _lock:
        _cache, _cache_sig = kb, sig
    return kb


def classes_for(kb: dict, name: str) -> tuple[str | None, list[str]]:
    inn = kb["name_index"].get(name.lower().strip())
    if not inn:
        return None, []
    return inn, kb["dictionary"]["drug_classes"]["substances"][inn]["classes"]
