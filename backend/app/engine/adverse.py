"""Анализ сообщения пациента о нежелательной реакции.

Пациент описывает самочувствие своими словами — список возможных реакций ему не
показывается (эффект ноцебо). Здесь текст переводится в стандартные термины по
словарю `adverse_terms` (разговорные формулировки, формы слов, опечатки, отрицания)
и сравнивается с разделом «Побочное действие» инструкций: текущего препарата,
недавно отменённого (возможный синдром отмены) и сопутствующей терапии.

Результат видит только врач и подтверждает классификацию сам. Нераспознанный текст
никогда не классифицируется как «не описано в инструкции» автоматически.
"""
from __future__ import annotations

import difflib
import re
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Patient, Prescription, now
from . import knowledge
from .extract import _negated

FREQUENCY = {
    "very_common": "очень часто",
    "common": "часто",
    "uncommon": "нечасто",
    "rare": "редко",
    "very_rare": "очень редко",
}
RECENTLY_STOPPED = timedelta(days=14)
_WORD = re.compile(r"[а-яa-z]+")


def _norm(text: str) -> str:
    return (text or "").lower().replace("ё", "е")


def _clauses(text: str) -> list[str]:
    return [c for c in re.split(r"[.!?;\n]+", _norm(text)) if c.strip()]


def _dictionary(kb: dict) -> dict:
    return kb.get("dictionary", {}).get("adverse_terms", {}) or {}


def _found(pattern: str, clauses: list[str]) -> bool:
    """Упоминание без отрицания в той же клаузе («тошноты нет» не засчитывается)."""
    for c in clauses:
        for m in re.finditer(pattern, c):
            if not _negated(c, m.start(), m.end()):
                return True
    return False


def _fuzzy(term: str, clauses: list[str]) -> bool:
    """Опечатки: однословный термин сравнивается со словами пациента нечётко,
    с той же проверкой отрицаний, что и для формулировок словаря."""
    if " " in term or len(term) < 6:
        return False
    target = _norm(term)
    for c in clauses:
        for m in _WORD.finditer(c):
            if difflib.SequenceMatcher(None, target, m.group()).ratio() >= 0.84 and not _negated(c, m.start(), m.end()):
                return True
    return False


def recognize(text: str, kb: dict) -> tuple[list[str], list[dict]]:
    """Стандартные термины и тревожные признаки в тексте пациента."""
    d = _dictionary(kb)
    clauses = _clauses(text)
    terms = []
    for t in d.get("terms", []):
        if any(_found(p, clauses) for p in t.get("patterns", [])) or _fuzzy(t["term"], clauses):
            terms.append(t["term"])
    flags = []
    for f in d.get("red_flags", []):
        hit = (all(_found(p, clauses) for p in f["all"]) if f.get("all")
               else any(_found(p, clauses) for p in f.get("any", [])))
        if hit:
            flags.append({"id": f["id"], "title": f["title"], "level": f.get("level", "high")})
    return terms, flags


def _canonical(entry: str, kb: dict) -> str:
    """Название реакции из инструкции -> стандартный термин словаря (если есть)."""
    e = _norm(entry)
    for t in _dictionary(kb).get("terms", []):
        names = [_norm(t["term"])] + [_norm(a) for a in t.get("aliases", [])]
        if e in names or any(re.search(p, e) for p in t.get("patterns", [])):
            return t["term"]
    return entry


def drug_reactions(drug: dict, kb: dict) -> dict[str, str]:
    """{стандартный термин: частота} из раздела «Побочное действие» препарата."""
    out: dict[str, str] = {}
    for freq, items in (drug.get("adverse_reactions") or {}).items():
        for x in items:
            out.setdefault(_canonical(x, kb), freq)
    return out


def _candidate_drugs(db: Session, patient: Patient, kb: dict) -> list[tuple[dict, str]]:
    out: list[tuple[dict, str]] = []
    rxs = db.scalars(select(Prescription).where(Prescription.patient_id == patient.id)
                     .order_by(Prescription.started_at.desc())).all()
    for rx in rxs:
        drug = kb["drug"].get(rx.drug_id)
        if not drug:
            continue
        if rx.status in ("active", "paused"):
            out.append((drug, "current"))
        elif rx.stopped_at and now() - rx.stopped_at <= RECENTLY_STOPPED:
            out.append((drug, "recently_stopped"))
    seen = {d["id"] for d, _ in out}
    for m in patient.current_meds or []:
        inn, _ = knowledge.classes_for(kb, m.get("inn") or m.get("name") or "")
        drug = next((d for d in kb["drug"].values() if inn and d.get("inn") == inn and d["id"] not in seen), None)
        if drug:
            out.append((drug, "concomitant"))
            seen.add(drug["id"])
    return out


def analyze(db: Session, patient: Patient, text: str, kb: dict) -> dict:
    """Результат для врача: термины, совпадения с инструкциями, тревожные признаки.
    Свободный текст пациента в результат не копируется (он хранится зашифрованным)."""
    terms, flags = recognize(text, kb)
    drugs = _candidate_drugs(db, patient, kb)
    tables = {d["id"]: drug_reactions(d, kb) for d, _ in drugs}
    matches = []
    for term in terms:
        found = [{"drug_id": d["id"], "trade_name": d.get("trade_name", d["id"]), "relation": rel,
                  "frequency": tables[d["id"]].get(term),
                  "frequency_label": FREQUENCY.get(tables[d["id"]].get(term) or "", None)}
                 for d, rel in drugs if term in tables[d["id"]]]
        matches.append({"term": term, "in_instructions": found})
    current = [m for m in matches if any(x["relation"] == "current" for x in m["in_instructions"])]
    has_current = any(rel == "current" for _, rel in drugs)
    if not terms or not has_current:
        expected = None  # нечего сравнивать — решает врач
    else:
        expected = bool(current)
    return {
        "terms": matches,
        "red_flags": flags,
        "recognized": bool(terms),
        "expected": expected,
        "drugs_checked": [{"drug_id": d["id"], "trade_name": d.get("trade_name", d["id"]), "relation": rel} for d, rel in drugs],
        "dictionary_version": kb.get("versions", {}).get(("dictionary", "adverse_terms")),
    }
