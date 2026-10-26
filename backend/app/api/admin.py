"""Администрирование клиники.

* Справочники (шкалы, препараты, КР, правила алертинга и маршрутизации) меняются
  без изменения ядра: правка -> черновик (валидация) -> клиническое одобрение
  врачом-рецензентом, который не является автором (принцип «четырёх глаз») ->
  ввод в действие с новой версией. Вся история версий хранится, откат — тем же
  путём (предложить прежнюю версию).
* Пользователи: врачи, роли и флаги доступа (дежурный, рецензент), блокировка,
  сброс пароля; смена лечащего врача пациента.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_db
from ..engine import knowledge
from ..models import AuditLog, KnowledgeItem, KnowledgeVersion, Patient, PatientReassignmentRequest, User, now

router = APIRouter(prefix="/api/admin", tags=["admin"])
review = APIRouter(prefix="/api/review", tags=["review"])
admin_only = auth.require("admin")
KINDS = {"scale", "drug", "rules", "dictionary", "guideline"}


# --- справочники -----------------------------------------------------------
@router.get("/knowledge")
def list_knowledge(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    drafts = {(v.kind, v.code) for v in db.scalars(select(KnowledgeVersion).where(KnowledgeVersion.status == "draft"))}
    return [{"kind": r.kind, "code": r.code, "version": r.version, "active": r.active, "updated_at": r.updated_at,
             "title": r.body.get("title") or r.body.get("trade_name") or r.code, "has_draft": (r.kind, r.code) in drafts}
            for r in db.scalars(select(KnowledgeItem).order_by(KnowledgeItem.kind, KnowledgeItem.code))]


@router.get("/knowledge/{kind}/{code}")
def get_item(kind: str, code: str, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    r = db.scalar(select(KnowledgeItem).where(KnowledgeItem.kind == kind, KnowledgeItem.code == code))
    if not r:
        raise HTTPException(404, "Не найдено")
    return {"kind": r.kind, "code": r.code, "version": r.version, "active": r.active, "body": r.body}


def version_dict(v: KnowledgeVersion, with_body: bool = False) -> dict:
    d = {"id": v.id, "kind": v.kind, "code": v.code, "version": v.version, "status": v.status, "sha256": v.body_sha256,
         "change_note": v.change_note, "proposed_by": v.proposed_by, "proposed_at": v.proposed_at,
         "decided_by": v.decided_by, "decided_at": v.decided_at, "decision_comment": v.decision_comment}
    if with_body:
        d["body"] = v.body
    return d


@router.get("/knowledge/{kind}/{code}/versions")
def versions(kind: str, code: str, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [version_dict(v) for v in db.scalars(select(KnowledgeVersion).where(
        KnowledgeVersion.kind == kind, KnowledgeVersion.code == code).order_by(KnowledgeVersion.id.desc()))]


class ProposeIn(BaseModel):
    body: dict
    change_note: str = Field(min_length=5, max_length=2000)


@router.put("/knowledge/{kind}/{code}")
def propose(kind: str, code: str, data: ProposeIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Предложить изменение (то же, что PUT /api/knowledge/{kind}/{code}). Вступает в силу после одобрения."""
    from .knowledge import ProposeIn as KP, propose_change
    if kind not in KINDS:
        raise HTTPException(422, f"Тип справочника: {sorted(KINDS)}")
    return propose_change(db, user, kind, code, KP(body=data.body, change_note=data.change_note), auth.client_ip(request))


class RollbackIn(BaseModel):
    to_version_id: int
    change_note: str = Field(min_length=5, max_length=2000)


@router.post("/knowledge/{kind}/{code}/rollback")
def rollback(kind: str, code: str, data: RollbackIn, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    old = db.get(KnowledgeVersion, data.to_version_id)
    if not old or (old.kind, old.code) != (kind, code) or old.status not in ("approved", "superseded"):
        raise HTTPException(404, "Версия не найдена")
    try:
        v = knowledge.propose(db, kind, code, old.body, user.id, f"Откат к версии {old.version}: {data.change_note}")
    except knowledge.KnowledgeError as e:
        raise HTTPException(422, {"message": "Прежняя версия не проходит текущие проверки", "errors": e.errors})
    auth.audit(db, user, "knowledge_rollback_proposed", "knowledge_version", v.id, kind=kind, code=code, to_version=old.version)
    db.commit()
    return {"draft_id": v.id, "status": "draft"}


@router.post("/knowledge/reload")
def reload(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Изменения в YAML (репозиторий) оформляются черновиками на одобрение."""
    n = knowledge.seed(db, propose_changes=True, user_id=user.id)
    auth.audit(db, user, "knowledge_reload_proposed", "knowledge", None, drafts=n)
    db.commit()
    return {"drafts": n}


# --- клиническое одобрение ------------------------------------------------------
def reviewer(user: User = Depends(auth.require("doctor"))) -> User:
    if not user.is_reviewer:
        raise HTTPException(403, "Требуются права клинического рецензента")
    return user


@review.get("/knowledge")
def pending(user: User = Depends(reviewer), db: Session = Depends(get_db)):
    out = []
    for v in db.scalars(select(KnowledgeVersion).where(KnowledgeVersion.status == "draft").order_by(KnowledgeVersion.proposed_at)):
        cur = db.scalar(select(KnowledgeItem).where(KnowledgeItem.kind == v.kind, KnowledgeItem.code == v.code))
        out.append({**version_dict(v, with_body=True), "current_version": cur.version if cur else None,
                    "current_body": cur.body if cur else None})
    return out


class DecideIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    comment: str | None = Field(None, max_length=2000)


@review.post("/knowledge/{vid}")
def decide(vid: int, data: DecideIn, request: Request, user: User = Depends(reviewer), db: Session = Depends(get_db)):
    v = db.get(KnowledgeVersion, vid)
    if not v or v.status != "draft":
        raise HTTPException(404, "Черновик не найден")
    if v.proposed_by == user.id:
        raise HTTPException(403, "Автор изменения не может его одобрить (принцип «четырёх глаз»)")
    if data.decision == "approve":
        try:
            row = knowledge.approve(db, v, user.id, data.comment)
        except knowledge.KnowledgeError as e:
            raise HTTPException(422, {"message": "Справочник не прошёл проверку", "errors": e.errors})
        result = {"status": "approved", "version": row.version}
    else:
        v.status, v.decided_by, v.decided_at, v.decision_comment = "rejected", user.id, now(), data.comment
        result = {"status": "rejected"}
    auth.audit(db, user, f"knowledge_{result['status']}", "knowledge_version", v.id, ip=auth.client_ip(request),
               kind=v.kind, code=v.code, version=v.version)
    db.commit()
    return result


# --- пользователи ----------------------------------------------------------------
def user_dict(u: User) -> dict:
    return {"id": u.id, "login": u.login, "role": u.role, "full_name": u.full_name, "specialty": u.specialty,
            "frmr_id": u.frmr_id, "is_duty": u.is_duty, "is_reviewer": u.is_reviewer, "active": u.active,
            "mfa_enabled": bool(u.totp_secret_enc), "has_phone": bool(u.phone_enc), "locked_until": u.locked_until,
            "working_hours": u.working_hours, "created_at": u.created_at}


@router.get("/users")
def list_users(role: str | None = None, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.role, User.full_name)
    if role:
        stmt = stmt.where(User.role == role)
    return [user_dict(u) for u in db.scalars(stmt) if u.role != "patient" or role == "patient"]


class StaffIn(BaseModel):
    login: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9._-]+$")
    full_name: str = Field(min_length=3, max_length=128)
    role: str = Field(pattern="^(doctor|admin)$")
    specialty: str | None = Field(None, pattern="^(psychiatrist|psychotherapist|therapist|neurologist|gp|other)$")
    frmr_id: str | None = Field(None, max_length=32)
    is_duty: bool = False
    is_reviewer: bool = False
    phone: str | None = Field(None, pattern=r"^\+?[0-9 ()-]{10,20}$")


@router.post("/users")
def create_user(data: StaffIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    if db.scalar(select(User.id).where(User.login == data.login)):
        raise HTTPException(409, "Логин занят")
    if data.role == "doctor" and not data.specialty:
        raise HTTPException(422, "Для врача укажите специальность")
    password = secrets.token_urlsafe(12)  # выдаётся один раз; смена при первом входе
    u = User(login=data.login, password_hash=auth.hash_password(password), role=data.role, full_name=data.full_name,
             specialty=data.specialty, frmr_id=data.frmr_id, is_duty=data.is_duty, is_reviewer=data.is_reviewer,
             must_change_password=True)
    u.phone = data.phone
    db.add(u)
    db.flush()
    auth.audit(db, user, "user_created", "user", u.id, ip=auth.client_ip(request), role=data.role)
    db.commit()
    return {**user_dict(u), "temporary_password": password}


class WorkingHours(BaseModel):
    """Часы, когда врачу можно отправлять внешние уведомления (SMS); пусто — по политике клиники."""
    days: list[int] = Field(min_length=1, max_length=7)
    start: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    end: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("дни недели — от 1 (пн) до 7 (вс)")
        return sorted(set(v))

    @model_validator(mode="after")
    def _order(self):
        if self.start >= self.end:
            raise ValueError("начало рабочего времени должно быть раньше окончания")
        return self


class StaffPatch(BaseModel):
    full_name: str | None = Field(None, min_length=3, max_length=128)
    specialty: str | None = Field(None, pattern="^(psychiatrist|psychotherapist|therapist|neurologist|gp|other)$")
    frmr_id: str | None = Field(None, max_length=32)
    is_duty: bool | None = None
    is_reviewer: bool | None = None
    active: bool | None = None
    phone: str | None = Field(None, pattern=r"^\+?[0-9 ()-]{10,20}$")
    working_hours: WorkingHours | None = None


@router.patch("/users/{uid}")
def update_user(uid: int, data: StaffPatch, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    if u.role == "patient":
        raise HTTPException(403, "Администратор не изменяет учётные записи пациентов")
    if u.id == user.id and data.active is False:
        raise HTTPException(409, "Нельзя заблокировать собственную учётную запись")
    changed = data.model_dump(exclude_unset=True)
    for k, v in changed.items():  # working_hours: None — сброс к политике клиники
        setattr(u, k, v)
    if data.active is False:
        auth.revoke_all(db, u.id)  # блокировка — немедленный выход на всех устройствах
    auth.audit(db, user, "user_updated", "user", u.id, ip=auth.client_ip(request), fields=sorted(changed))
    db.commit()
    return user_dict(u)


@router.post("/users/{uid}/reset-password")
def reset_password(uid: int, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    if u.role == "patient":
        raise HTTPException(403, "Пароль пациента сбрасывает лечащий врач")
    password = secrets.token_urlsafe(12)
    u.password_hash, u.password_changed_at, u.failed_logins, u.locked_until, u.must_change_password = auth.hash_password(password), now(), 0, None, True
    auth.revoke_all(db, u.id)
    auth.audit(db, user, "password_reset", "user", u.id, ip=auth.client_ip(request))
    db.commit()
    return {"temporary_password": password}


@router.get("/patients")
def list_patients(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Пациенты для администрирования (смена лечащего врача): только код и врач — без ФИО
    и медицинских данных (минимизация доступа администратора, 152-ФЗ ст. 5 ч. 5)."""
    doctors = {u.id: u.full_name for u in db.scalars(select(User).where(User.role == "doctor"))}
    rows = db.scalars(select(Patient).where(Patient.erased_at.is_(None)).order_by(Patient.code)).all()
    return [{"id": p.id, "code": p.code, "doctor_id": p.doctor_id, "doctor_name": doctors.get(p.doctor_id),
             "monitoring_active": p.monitoring_active} for p in rows]


class ReassignIn(BaseModel):
    doctor_id: int
    reason: str = Field(min_length=5, max_length=500)


@router.post("/patients/{pid}/attending")
def reassign(pid: int, data: ReassignIn, request: Request, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Запрос смены врача; фактическое назначение требует решения второго администратора."""
    p = db.get(Patient, pid)
    d = db.get(User, data.doctor_id)
    if not p or p.erased_at:
        raise HTTPException(404, "Пациент не найден")
    if not d or d.role != "doctor" or not d.active:
        raise HTTPException(422, "Укажите действующего врача")
    if p.doctor_id == d.id:
        raise HTTPException(422, "Этот врач уже является лечащим")
    duplicate = db.scalar(select(PatientReassignmentRequest.id).where(
        PatientReassignmentRequest.patient_id == p.id,
        PatientReassignmentRequest.status == "pending"))
    if duplicate:
        raise HTTPException(409, "Для пациента уже есть ожидающий подтверждения запрос")
    item = PatientReassignmentRequest(patient_id=p.id, from_doctor_id=p.doctor_id, to_doctor_id=d.id,
                                     requested_by=user.id, reason=data.reason, status="pending")
    db.add(item)
    db.flush()
    auth.audit(db, user, "attending_reassignment_requested", "patient_reassignment_request", item.id,
               patient_id=p.id, ip=auth.client_ip(request), from_doctor=p.doctor_id, to_doctor=d.id)
    db.commit()
    return {"ok": True, "request_id": item.id, "status": item.status}


@router.get("/attending-requests")
def list_reassignments(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(PatientReassignmentRequest).where(
        PatientReassignmentRequest.status == "pending").order_by(PatientReassignmentRequest.created_at)).all()
    out = []
    for item in rows:
        patient = db.get(Patient, item.patient_id)
        old_doctor = db.get(User, item.from_doctor_id)
        new_doctor = db.get(User, item.to_doctor_id)
        requester = db.get(User, item.requested_by)
        if not patient or patient.erased_at:
            continue
        out.append({"id": item.id, "patient_id": patient.id, "patient_code": patient.code,
                    "from_doctor_id": item.from_doctor_id, "from_doctor_name": old_doctor.full_name if old_doctor else None,
                    "to_doctor_id": item.to_doctor_id, "to_doctor_name": new_doctor.full_name if new_doctor else None,
                    "requested_by": item.requested_by, "requested_by_name": requester.full_name if requester else None,
                    "reason": item.reason, "created_at": item.created_at})
    return out


class ReassignmentDecisionIn(BaseModel):
    comment: str = Field(default="", max_length=1000)


@router.post("/attending-requests/{rid}/approve")
def approve_reassignment(rid: int, data: ReassignmentDecisionIn, request: Request,
                         user: User = Depends(admin_only), db: Session = Depends(get_db)):
    item = db.get(PatientReassignmentRequest, rid)
    if not item or item.status != "pending":
        raise HTTPException(404, "Ожидающий запрос не найден")
    # Принцип двух лиц, если в организации есть другой действующий администратор;
    # при единственном администраторе подтверждение им самим фиксируется в аудите.
    other_admins = db.scalar(select(User.id).where(User.role == "admin", User.active.is_(True), User.id != user.id).limit(1))
    if item.requested_by == user.id and other_admins:
        raise HTTPException(403, "Запрос должен подтвердить другой администратор")
    patient = db.get(Patient, item.patient_id)
    target = db.get(User, item.to_doctor_id)
    if not patient or patient.erased_at:
        item.status, item.decided_by, item.decided_at = "rejected", user.id, now()
        item.decision_comment = "Пациент удалён или недоступен"
        db.commit()
        raise HTTPException(409, "Пациент недоступен; запрос отклонён")
    if patient.doctor_id != item.from_doctor_id:
        raise HTTPException(409, "Лечащий врач пациента уже изменился; создайте новый запрос")
    if not target or target.role != "doctor" or not target.active:
        raise HTTPException(409, "Целевой врач больше не активен")
    old = patient.doctor_id
    patient.doctor_id = target.id
    item.status, item.decided_by, item.decided_at = "approved", user.id, now()
    item.decision_comment = data.comment or None
    auth.audit(db, user, "attending_changed", "patient", patient.id, patient_id=patient.id,
               ip=auth.client_ip(request), request_id=item.id, from_doctor=old, to_doctor=target.id,
               requested_by=item.requested_by, single_admin=item.requested_by == user.id)
    db.commit()
    return {"ok": True, "doctor_id": target.id, "status": item.status}


@router.post("/attending-requests/{rid}/reject")
def reject_reassignment(rid: int, data: ReassignmentDecisionIn, request: Request,
                        user: User = Depends(admin_only), db: Session = Depends(get_db)):
    item = db.get(PatientReassignmentRequest, rid)
    if not item or item.status != "pending":
        raise HTTPException(404, "Ожидающий запрос не найден")
    item.status, item.decided_by, item.decided_at = "rejected", user.id, now()
    item.decision_comment = data.comment or "Отклонено без комментария"
    auth.audit(db, user, "attending_reassignment_rejected", "patient_reassignment_request", item.id,
               patient_id=item.patient_id, ip=auth.client_ip(request), requested_by=item.requested_by)
    db.commit()
    return {"ok": True, "status": item.status}


# --- журнал -------------------------------------------------------------------
@router.get("/audit")
def audit_log(patient_id: int | None = None, action: str | None = None, limit: int = 200,
              user: User = Depends(admin_only), db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if patient_id:
        stmt = stmt.where(AuditLog.patient_id == patient_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return [{"id": r.id, "at": r.created_at, "user_id": r.user_id, "action": r.action, "entity": r.entity, "entity_id": r.entity_id,
             "patient_id": r.patient_id, "details": r.details, "ip": r.ip, "hash": r.hash} for r in db.scalars(stmt)]


@router.get("/audit/verify")
def audit_verify(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    auth.seal_audit()
    return auth.verify_audit(db)
