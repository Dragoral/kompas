"""Справочники для авторов (врачи и администраторы): шкалы, препараты, правила, КР.

Всё, что нужно, чтобы менять систему без программиста и без риска:
  * схемы (JSON Schema) — по ним строятся формы и проверяются файлы;
  * каталог переменных и действий — на что можно опираться в правилах;
  * проверка черновика (ошибки по полям + предупреждения);
  * пробный подсчёт шкалы на тестовых ответах;
  * проверка условия правила на реальном пациенте с пошаговым объяснением;
  * импорт шкал из HL7 FHIR Questionnaire (файл или ссылка) и CSV, экспорт в FHIR;
  * предложение изменения -> черновик -> одобрение рецензентом (не автором) -> в работе.
"""
from __future__ import annotations

import csv
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, safe_fetch
from ..db import get_db
from ..engine import alerts, context, knowledge, logic, questionnaire, scales, schemas, variables
from ..models import KnowledgeItem, KnowledgeVersion, User

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
author = auth.require("doctor", "admin")
KINDS = set(schemas.SCHEMAS)


def _kind(kind: str) -> str:
    if kind not in KINDS:
        raise HTTPException(404, f"Тип справочника: {', '.join(sorted(KINDS))}")
    return kind


@router.get("")
def list_items(user: User = Depends(author), db: Session = Depends(get_db)):
    drafts = {(v.kind, v.code) for v in db.scalars(select(KnowledgeVersion).where(KnowledgeVersion.status == "draft"))}
    return [{"kind": r.kind, "code": r.code, "version": r.version, "active": r.active, "updated_at": r.updated_at,
             "title": r.body.get("title") or r.body.get("trade_name") or r.code, "verified": r.body.get("verified"),
             "has_draft": (r.kind, r.code) in drafts}
            for r in db.scalars(select(KnowledgeItem).order_by(KnowledgeItem.kind, KnowledgeItem.code))]


@router.get("/schemas/{kind}")
def schema(kind: str, user: User = Depends(author)):
    return schemas.SCHEMAS[_kind(kind)]


@router.get("/variables")
def variable_catalogue(user: User = Depends(author)):
    return variables.catalogue()


@router.get("/actions")
def action_catalogue(user: User = Depends(author)):
    titles = {"notify_doctor": "Мгновенное уведомление лечащего врача", "crisis_screen": "Экран экстренной помощи пациенту",
              "escalate": "Эскалация дежурному при отсутствии реакции ({escalate: {after_min: N}})",
              "request_scale": "Назначить пациенту внеплановую шкалу ({request_scale: CODE})",
              "propose_visit": "Предложить врачу внеплановый визит", "propose_hold_therapy": "Предложить приостановить терапию",
              "pharmacovigilance_draft": "Черновик сообщения о нежелательной реакции"}
    return [{"name": n, "description": titles.get(n, "")} for n in alerts.ACTIONS]


@router.get("/scoring-methods")
def scoring_methods(user: User = Depends(author)):
    return sorted(scales.METHODS)


@router.get("/{kind}/{code}")
def get_item(kind: str, code: str, user: User = Depends(author), db: Session = Depends(get_db)):
    r = db.scalar(select(KnowledgeItem).where(KnowledgeItem.kind == _kind(kind), KnowledgeItem.code == code))
    if not r:
        raise HTTPException(404, "Не найдено")
    return {"kind": r.kind, "code": r.code, "version": r.version, "active": r.active, "body": r.body}


class BodyIn(BaseModel):
    kind: str
    body: dict


@router.post("/validate")
def validate(data: BodyIn, user: User = Depends(author)):
    errors, warnings = knowledge.check(_kind(data.kind), data.body)
    return {"valid": not errors, "errors": errors, "warnings": warnings}


class PreviewIn(BaseModel):
    scale: dict
    answers: dict[str, float]
    sex: str | None = Field(None, pattern="^(m|f)$")  # для шкал с нормами по полу/возрасту
    age: int | None = Field(None, ge=0, le=120)


@router.post("/scales/preview")
def preview_scale(data: PreviewIn, user: User = Depends(author)):
    """Пробный подсчёт черновика шкалы — до отправки на одобрение."""
    errors, warnings = knowledge.check("scale", data.scale)
    if errors:
        raise HTTPException(422, {"message": "Шкала не прошла проверку", "errors": errors})
    try:
        r = scales.evaluate(data.scale, data.answers, {"patient": {"sex": data.sex, "age": data.age}})
    except ValueError as e:
        raise HTTPException(422, str(e))
    lo, hi = scales.theoretical_range(data.scale)
    return {**r, "range": [lo, hi], "warnings": warnings}


class RuleTestIn(BaseModel):
    condition: dict
    patient_id: int


@router.post("/rules/test")
def test_rule(data: RuleTestIn, request: Request, user: User = Depends(auth.require("doctor")), db: Session = Depends(get_db)):
    """Проверить условие правила на своём пациенте: результат и пошаговое объяснение."""
    errors: list = []
    schemas._check_condition(data.condition, "condition", errors)
    if errors:
        raise HTTPException(422, {"message": "Условие не прошло проверку", "errors": errors})
    p = auth.patient_for(user, data.patient_id, db)
    ctx = context.build(db, p)
    auth.audit(db, user, "rule_tested", "patient", p.id, patient_id=p.id)
    db.commit()
    return {"result": bool(logic.evaluate(data.condition, ctx)), "explain": logic.explain(data.condition, ctx)}


class ImportIn(BaseModel):
    url: str | None = Field(None, max_length=2000)
    resource: dict | None = None


@router.post("/import/fhir-questionnaire")
def import_fhir(data: ImportIn, user: User = Depends(author)):
    """Шкала из HL7 FHIR Questionnaire: по ссылке (https) или из файла. Возвращает черновик."""
    if bool(data.url) == bool(data.resource):
        raise HTTPException(422, "Укажите ссылку или содержимое ресурса (одно из двух)")
    res = data.resource
    if data.url:
        try:
            res = json.loads(safe_fetch.fetch(data.url))
        except safe_fetch.FetchError as e:
            raise HTTPException(422, str(e))
        except ValueError:
            raise HTTPException(422, "По ссылке не JSON")
    try:
        body, todo = questionnaire.from_fhir(res)
    except ValueError as e:
        raise HTTPException(422, str(e))
    errors, warnings = knowledge.check("scale", body)
    return {"draft": body, "todo": todo, "errors": errors, "warnings": warnings}


class CsvIn(BaseModel):
    csv: str = Field(max_length=500_000)
    code: str = Field(min_length=2, max_length=16)
    title: str = Field(min_length=3, max_length=200)


@router.post("/import/csv")
def import_csv(data: CsvIn, user: User = Depends(author)):
    try:
        body, todo = questionnaire.from_csv(data.csv, data.code, data.title)
    except (ValueError, csv.Error) as e:
        raise HTTPException(422, f"Не удалось разобрать таблицу: {e}")
    errors, warnings = knowledge.check("scale", body)
    return {"draft": body, "todo": todo, "errors": errors, "warnings": warnings}


@router.get("/scales/{code}/fhir")
def export_fhir(code: str, user: User = Depends(author), db: Session = Depends(get_db)):
    r = db.scalar(select(KnowledgeItem).where(KnowledgeItem.kind == "scale", KnowledgeItem.code == code))
    if not r:
        raise HTTPException(404, "Шкала не найдена")
    return questionnaire.to_fhir(r.body)


class ProposeIn(BaseModel):
    body: dict
    change_note: str = Field(min_length=5, max_length=2000)


def propose_change(db: Session, user: User, kind: str, code: str, data: ProposeIn, ip: str | None) -> dict:
    code_in_body = data.body.get("code") or data.body.get("id")
    if kind in ("scale", "drug", "guideline") and code_in_body and code_in_body != code:
        raise HTTPException(422, f"Код в описании («{code_in_body}») не совпадает с адресом («{code}»)")
    try:
        v = knowledge.propose(db, kind, code, data.body, user.id, data.change_note)
    except knowledge.KnowledgeError as e:
        raise HTTPException(422, {"message": "Справочник не прошёл проверку", "errors": e.errors, "warnings": e.warnings})
    auth.audit(db, user, "knowledge_proposed", "knowledge_version", v.id, ip=ip, kind=kind, code=code)
    db.commit()
    return {"draft_id": v.id, "status": "draft", "warnings": knowledge.check(kind, data.body)[1],
            "note": "Изменение вступит в силу после одобрения врачом-рецензентом (не автором)"}


@router.put("/{kind}/{code}")
def propose(kind: str, code: str, data: ProposeIn, request: Request, user: User = Depends(author), db: Session = Depends(get_db)):
    return propose_change(db, user, _kind(kind), code, data, auth.client_ip(request))
