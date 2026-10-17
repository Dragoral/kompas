"""Управление справочниками без изменения ядра: шкалы, препараты, правила
алертинга и маршрутизации. Каждое изменение валидируется (некорректное правило
не попадёт в работу), версионируется и пишется в журнал."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_db
from ..engine import knowledge
from ..models import AuditLog, KnowledgeItem, User, now

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin_only = auth.require("admin")
KINDS = {"scale", "drug", "rules", "dictionary"}


@router.get("/knowledge")
def list_knowledge(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [{"kind": r.kind, "code": r.code, "version": r.version, "active": r.active, "updated_at": r.updated_at,
             "title": r.body.get("title") or r.body.get("trade_name") or r.code}
            for r in db.scalars(select(KnowledgeItem).order_by(KnowledgeItem.kind, KnowledgeItem.code))]


@router.get("/knowledge/{kind}/{code}")
def get_item(kind: str, code: str, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    r = db.scalar(select(KnowledgeItem).where(KnowledgeItem.kind == kind, KnowledgeItem.code == code))
    if not r:
        raise HTTPException(404, "Не найдено")
    return {"kind": r.kind, "code": r.code, "version": r.version, "active": r.active, "body": r.body}


class ItemIn(BaseModel):
    body: dict
    active: bool = True


@router.put("/knowledge/{kind}/{code}")
def put_item(kind: str, code: str, data: ItemIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    if kind not in KINDS:
        raise HTTPException(422, f"Тип справочника: {sorted(KINDS)}")
    try:
        knowledge.validate(kind, data.body)
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422, f"Справочник не прошёл проверку: {e}")
    r = db.scalar(select(KnowledgeItem).where(KnowledgeItem.kind == kind, KnowledgeItem.code == code))
    if r:
        r.body, r.active, r.version, r.updated_at, r.updated_by = data.body, data.active, r.version + 1, now(), user.id
    else:
        r = KnowledgeItem(kind=kind, code=code, body=data.body, active=data.active, updated_by=user.id)
        db.add(r)
    auth.audit(db, user, "knowledge_updated", "knowledge", None, ip=auth.client_ip(request), kind=kind, code=code)
    db.commit()
    knowledge.invalidate()
    return {"kind": kind, "code": code, "version": r.version}


@router.post("/knowledge/reload")
def reload(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Перезагрузить справочники из YAML (под версионным контролем)."""
    n = knowledge.seed(db, overwrite=True)
    auth.audit(db, user, "knowledge_reloaded", "knowledge", None, items=n)
    db.commit()
    return {"updated": n}


@router.get("/audit")
def audit_log(patient_id: int | None = None, limit: int = 200, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if patient_id:
        stmt = stmt.where(AuditLog.patient_id == patient_id)
    return [{"id": r.id, "at": r.created_at, "user_id": r.user_id, "action": r.action, "entity": r.entity, "entity_id": r.entity_id,
             "patient_id": r.patient_id, "details": r.details, "ip": r.ip, "hash": r.hash} for r in db.scalars(stmt)]


@router.get("/audit/verify")
def audit_verify(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    auth.seal_audit()
    return auth.verify_audit(db)
