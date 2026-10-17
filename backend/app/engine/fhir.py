"""Экспорт карты наблюдения в HL7 FHIR R4 (Bundle/collection) для интеграции с МИС."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AdverseEvent, Alert, ClinicalAction, Patient, Prescription, ScaleResult
from . import knowledge

LOINC = {"PHQ9": ("44261-6", "PHQ-9 total score"), "GAD7": ("70274-6", "GAD-7 total score")}


def _ts(d):
    return d.isoformat() + "Z" if d else None


def bundle(db: Session, p: Patient) -> dict:
    kb = knowledge.get(db)
    ref = f"Patient/{p.code}"
    res: list[dict] = [{
        "resourceType": "Patient", "id": p.code,
        "name": [{"text": p.full_name}], "gender": {"m": "male", "f": "female"}[p.sex],
        "birthDate": p.birth_date.isoformat() if p.birth_date else None,
    }]
    for i, d in enumerate(p.diagnoses):
        res.append({"resourceType": "Condition", "id": f"{p.code}-dx{i}", "subject": {"reference": ref},
                    "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10", "code": d["icd10"], "display": d.get("title")}]}})
    for rx in db.scalars(select(Prescription).where(Prescription.patient_id == p.id)):
        drug = kb["drug"].get(rx.drug_id, {})
        res.append({"resourceType": "MedicationRequest", "id": f"rx{rx.id}", "subject": {"reference": ref},
                    "status": {"active": "active", "paused": "on-hold", "stopped": "stopped"}[rx.status], "intent": "order",
                    "authoredOn": _ts(rx.started_at),
                    "medicationCodeableConcept": {"text": f"{drug.get('trade_name')} ({drug.get('inn')})",
                                                  "coding": [{"system": "http://www.whocc.no/atc", "code": drug.get("atc")}]},
                    "dosageInstruction": [{"text": f"{rx.regimen.get('dose_mg')} мг × {rx.regimen.get('times_per_day')} р/сут"}]})
    for r in db.scalars(select(ScaleResult).where(ScaleResult.patient_id == p.id)):
        code = LOINC.get(r.scale_code)
        res.append({"resourceType": "Observation", "id": f"obs{r.id}", "status": "final", "subject": {"reference": ref},
                    "effectiveDateTime": _ts(r.created_at), "valueInteger": r.score,
                    "interpretation": [{"text": r.band}],
                    "code": {"coding": [{"system": "http://loinc.org", "code": code[0], "display": code[1]}] if code else [],
                             "text": r.scale_code}})
    for a in db.scalars(select(AdverseEvent).where(AdverseEvent.patient_id == p.id)):
        res.append({"resourceType": "AdverseEvent", "id": f"ae{a.id}", "actuality": "actual", "subject": {"reference": ref},
                    "date": _ts(a.created_at), "event": {"text": a.title},
                    "seriousness": {"text": "serious" if a.serious else "non-serious"}})
    for al in db.scalars(select(Alert).where(Alert.patient_id == p.id, Alert.status != "resolved")):
        res.append({"resourceType": "Flag", "id": f"flag{al.id}", "status": "active", "subject": {"reference": ref},
                    "code": {"text": al.title}, "period": {"start": _ts(al.created_at)}})
    for c in db.scalars(select(ClinicalAction).where(ClinicalAction.patient_id == p.id, ClinicalAction.kind == "referral",
                                                     ClinicalAction.status == "confirmed")):
        res.append({"resourceType": "ServiceRequest", "id": f"ref{c.id}", "status": "active", "intent": "order",
                    "priority": "urgent" if c.level == "mandatory" else "routine", "subject": {"reference": ref},
                    "code": {"text": "Консультация врача-психиатра"}, "authoredOn": _ts(c.decided_at)})
    return {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": r} for r in res]}
