"""Демо-данные: синтетические пациенты для клинических сценариев с Авиандром.
Реальные персональные данные не используются.

    python -m app.seed --reset

Учётные записи (только для демо-стенда):
    врач-психиатр     psychiatrist / Kompas-demo-2026
    врач-терапевт     therapist    / Kompas-demo-2026
    дежурный психиатр duty         / Kompas-demo-2026
    администратор     admin        / Kompas-demo-2026
    пациенты          patient1..patient6 / Kompas-demo-2026
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from . import auth, consent
from .config import BASE_DIR
from .crypto import vault
from .db import Base, WriteSession as SessionLocal, engine
from .engine import alerts, knowledge, scales
from .models import AdverseEvent, DiaryEntry, DoseLog, Patient, Prescription, ScaleAssignment, ScaleResult, User, now
from .services import schedule_doses

PASSWORD = "Kompas-demo-2026"
rnd = random.Random(42)


def answers_for(scale: dict, total: int, critical: dict | None = None) -> dict:
    """Ответы на пункты, дающие заданный суммарный балл (для синтетической истории)."""
    items = scale["items"]
    mx = max(o["value"] for o in items[0]["options"])
    ans = {str(it["n"]): 0 for it in items}
    for k, v in (critical or {}).items():
        ans[str(k)] = v
    left = total - sum(ans.values())
    # критические пункты (PHQ-9 п.9, C-SSRS) заполняются только явно
    order = [str(it["n"]) for it in items if not it.get("critical") and str(it["n"]) not in (critical or {})]
    while left > 0:
        k = rnd.choice(order)
        if ans[k] < mx:
            ans[k] += 1
            left -= 1
    return ans


def add_scale(db, kb, p: Patient, code: str, total: int, at: datetime, by: User, critical: dict | None = None):
    sc = kb["scale"][code]
    ans = answers_for(sc, total, critical)
    score, band = scales.score(sc, ans)
    db.add(ScaleResult(patient_id=p.id, scale_code=code, answers=ans, score=score, band=band["label"], severity=band["severity"],
                       respondent=sc["respondent"], entered_by=by.id, created_at=at, received_at=at))


def user(db, login, role, full_name, specialty=None, duty=False) -> User:
    u = User(login=login, password_hash=auth.hash_password(PASSWORD), role=role, full_name=full_name, specialty=specialty, is_duty=duty)
    db.add(u)
    db.flush()
    return u


def patient(db, login, doctor: User, full_name, birth, sex, profile, diagnoses, meds=(), visit_days_ago=40, history=()) -> Patient:
    u = user(db, login, "patient", "Пациент")
    p = Patient(code=f"P-DEMO{login[-1]}", user_id=u.id, doctor_id=doctor.id, sex=sex, profile=profile, diagnoses=diagnoses,
                current_meds=list(meds), therapy_history=list(history), monitoring_active=True, consent_version=consent.VERSION,
                consent_text_sha256=consent.SHA256, consent_at=now() - timedelta(days=visit_days_ago),
                in_person_visit_at=now() - timedelta(days=visit_days_ago), diagnosis_confirmed_by=doctor.id)
    db.add(p)
    db.flush()
    p.full_name = full_name
    p.birth_date = birth
    p.contacts = json.dumps({"phone": "+7 900 000-00-0" + login[-1], "emergency_contact": None})
    p.name_bidx = vault.blind_index(full_name)
    return p


def prescribe(db, kb, p: Patient, doctor: User, drug_id: str, indication: str, days_ago: int, adherence: float):
    drug = kb["drug"][drug_id]
    ind = next(i for i in drug["indications"] if i["id"] == indication)
    rx = Prescription(patient_id=p.id, drug_id=drug_id, indication_id=indication, regimen=ind["regimen"], confirmed_by=doctor.id,
                      started_at=now() - timedelta(days=days_ago, hours=2))
    db.add(rx)
    db.flush()
    schedule_doses(db, rx)
    db.flush()
    for d in db.scalars(select(DoseLog).where(DoseLog.prescription_id == rx.id, DoseLog.scheduled_for < now())):
        if rnd.random() < adherence:
            d.status, d.taken_at = "taken", d.scheduled_for + timedelta(minutes=rnd.randint(0, 50))
    for s in drug["monitoring"]["scales"]:
        db.add(ScaleAssignment(patient_id=p.id, scale_code=s["scale"], every_days=s["every_days"],
                               next_due=date.today() + timedelta(days=rnd.randint(0, 3)), reason=f"План мониторинга: {drug['trade_name']}"))
    return rx


def diary(db, p: Patient, days: int, mood: tuple, anxiety: tuple, sleep: tuple, skip_last: int = 0):
    for i in range(days, skip_last, -1):
        f = (days - i) / max(days - 1, 1)
        lerp = lambda a: round(a[0] + (a[1] - a[0]) * f + rnd.uniform(-0.8, 0.8))
        e = DiaryEntry(patient_id=p.id, day=date.today() - timedelta(days=i - 1), mood=max(0, min(10, lerp(mood))),
                       anxiety=max(0, min(10, lerp(anxiety))), sleep_hours=round(sleep[0] + (sleep[1] - sleep[0]) * f + rnd.uniform(-.5, .5), 1),
                       sleep_quality=max(0, min(10, lerp((mood[0], mood[1])))))
        db.add(e)


def run(reset: bool) -> None:
    if reset:
        Base.metadata.drop_all(engine)
        (BASE_DIR / "data" / "audit_anchor.log").unlink(missing_ok=True)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        knowledge.seed(db)
        if db.scalar(select(User.id).limit(1)):
            print("База уже заполнена (используйте --reset)")
            return
        kb = knowledge.get(db)
        psy = user(db, "psychiatrist", "doctor", "Петрова Анна Сергеевна", "psychiatrist")
        ter = user(db, "therapist", "doctor", "Иванов Сергей Викторович", "therapist")
        user(db, "duty", "doctor", "Смирнов Олег Игоревич (дежурный)", "psychiatrist", duty=True)
        user(db, "admin", "admin", "Администратор")
        t = now()

        # 1. ГТР у психиатра: неэффективность 1-й и 2-й линии (КР 457) -> Авиандр по показаниям и по КР,
        #    ответ на терапию, ремиссия по HAM-A к 6-й неделе
        p1 = patient(db, "patient1", psy, "Соколова Мария Андреевна", date(1991, 4, 12), "f",
                     {"conditions": [], "allergies": [], "egfr": 96, "psychotherapy": "КПТ, 12 сеансов"},
                     [{"icd10": "F41.1", "title": "Генерализованное тревожное расстройство", "primary": True}],
                     history=[{"inn": "эсциталопрам", "dose": "20 мг/сут", "weeks": 6, "outcome": "no_response"},
                              {"inn": "дулоксетин", "dose": "60 мг/сут", "weeks": 3, "outcome": "intolerance"}])
        prescribe(db, kb, p1, psy, "aviandr", "gad", 40, 0.96)
        for wk, (g, h) in enumerate([(15, 24), (12, 17), (10, 13), (8, 10), (6, 8), (5, 6)]):
            add_scale(db, kb, p1, "GAD7", g, t - timedelta(days=41 - wk * 7), p1_user := db.get(User, p1.user_id))
            if wk in (0, 1, 4, 5):
                add_scale(db, kb, p1, "HAMA", h, t - timedelta(days=41 - wk * 7, hours=-1), psy)
        add_scale(db, kb, p1, "PHQ9", 8, t - timedelta(days=41), p1_user)
        add_scale(db, kb, p1, "PHQ9", 5, t - timedelta(days=13), p1_user)
        diary(db, p1, 40, (4, 7), (8, 3), (5.5, 7.5))

        # 2. Тревога после COVID-19 у терапевта: Авиандр по показаниям (курс 4 нед.), направление не требуется
        p2 = patient(db, "patient2", ter, "Кузнецов Дмитрий Павлович", date(1979, 9, 3), "m",
                     {"conditions": ["cardiovascular"], "allergies": [], "post_covid": True, "egfr": 82},
                     [{"icd10": "F43.2", "title": "Расстройство адаптации (после перенесённой COVID-19)", "primary": True},
                      {"icd10": "I10", "title": "Артериальная гипертензия"}],
                     meds=[{"name": "Амлодипин", "inn": "амлодипин", "classes": ["antihypertensive"], "dose": "5 мг 1 р/сут"}], visit_days_ago=16)
        p2_user = db.get(User, p2.user_id)
        prescribe(db, kb, p2, ter, "aviandr", "post_covid_anxiety", 14, 0.92)
        add_scale(db, kb, p2, "GAD7", 12, t - timedelta(days=15), p2_user)
        add_scale(db, kb, p2, "PHQ9", 7, t - timedelta(days=15), p2_user)
        add_scale(db, kb, p2, "GAD7", 9, t - timedelta(days=8), p2_user)
        add_scale(db, kb, p2, "GAD7", 7, t - timedelta(days=1), p2_user)
        diary(db, p2, 14, (5, 6), (7, 4), (6, 7))

        # 3. Депрессивный эпизод + тревога у терапевта: Авиандр вне показаний, эсциталопрам показан; направление ЖЕЛАТЕЛЬНО
        p3 = patient(db, "patient3", ter, "Морозова Елена Викторовна", date(1985, 1, 27), "f",
                     {"conditions": [], "allergies": []},
                     [{"icd10": "F32.1", "title": "Депрессивный эпизод средней степени", "primary": True}], visit_days_ago=2)
        p3_user = db.get(User, p3.user_id)
        add_scale(db, kb, p3, "PHQ9", 17, t - timedelta(days=2), p3_user)
        add_scale(db, kb, p3, "GAD7", 13, t - timedelta(days=2), p3_user)
        diary(db, p3, 2, (3, 3), (6, 6), (5, 5))

        # 4. ГТР с противопоказаниями: ХБП (СКФ 48) + трамадол — Авиандр заблокирован, предупреждения безопасности
        p4 = patient(db, "patient4", psy, "Волков Николай Иванович", date(1966, 6, 18), "m",
                     {"conditions": ["cardiovascular", "diabetes"], "allergies": [], "egfr": 48},
                     [{"icd10": "F41.1", "title": "Генерализованное тревожное расстройство", "primary": True},
                      {"icd10": "N18.3", "title": "Хроническая болезнь почек, стадия 3а"},
                      {"icd10": "E11", "title": "Сахарный диабет 2 типа"}],
                     meds=[{"name": "Трамадол", "inn": "трамадол", "dose": "50 мг по потребности"},
                           {"name": "Метформин", "inn": "метформин", "dose": "1000 мг 2 р/сут"}], visit_days_ago=1)
        p4_user = db.get(User, p4.user_id)
        add_scale(db, kb, p4, "GAD7", 16, t - timedelta(days=1), p4_user)
        add_scale(db, kb, p4, "PHQ9", 9, t - timedelta(days=1), p4_user)
        add_scale(db, kb, p4, "HAMA", 23, t - timedelta(days=1), psy)

        # 5. На Авиандре у терапевта — живой сценарий алерта: пациент отправит PHQ-9 с п. 9 > 0
        p5 = patient(db, "patient5", ter, "Лебедев Артём Олегович", date(1996, 11, 5), "m",
                     {"conditions": [], "allergies": [], "post_covid": True},
                     [{"icd10": "F43.2", "title": "Расстройство адаптации (после перенесённой COVID-19)", "primary": True}], visit_days_ago=12)
        p5_user = db.get(User, p5.user_id)
        prescribe(db, kb, p5, ter, "aviandr", "post_covid_anxiety", 10, 0.9)
        add_scale(db, kb, p5, "GAD7", 11, t - timedelta(days=11), p5_user)
        add_scale(db, kb, p5, "PHQ9", 9, t - timedelta(days=11), p5_user)
        add_scale(db, kb, p5, "GAD7", 10, t - timedelta(days=4), p5_user)
        diary(db, p5, 10, (5, 3), (6, 7), (6.5, 5))

        # 6. Нежелательное явление и низкая приверженность: черновик извещения о НР, алерт приверженности
        p6 = patient(db, "patient6", psy, "Новикова Ольга Сергеевна", date(1958, 3, 30), "f",
                     {"conditions": ["cardiovascular"], "allergies": []},
                     [{"icd10": "F41.1", "title": "Генерализованное тревожное расстройство", "primary": True}],
                     meds=[{"name": "Бисопролол", "inn": "бисопролол", "dose": "5 мг 1 р/сут"}], visit_days_ago=22,
                     history=[{"inn": "сертралин", "dose": "100 мг/сут", "weeks": 8, "outcome": "partial"},
                              {"inn": "прегабалин", "dose": "300 мг/сут", "weeks": 6, "outcome": "no_response"}])
        p6_user = db.get(User, p6.user_id)
        rx6 = prescribe(db, kb, p6, psy, "aviandr", "gad", 21, 0.62)
        add_scale(db, kb, p6, "GAD7", 14, t - timedelta(days=22), p6_user)
        add_scale(db, kb, p6, "GAD7", 12, t - timedelta(days=8), p6_user)
        diary(db, p6, 21, (5, 5), (7, 6), (6, 5.5))
        ae = AdverseEvent(patient_id=p6.id, prescription_id=rx6.id, title="головокружение", intensity="moderate", expected=True,
                          created_at=t - timedelta(hours=5))
        db.add(ae)
        db.flush()
        ae.description = "Головокружение по утрам после приёма, длится около часа"

        db.flush()
        for p in (p1, p2, p3, p4, p5, p6):
            alerts.process(db, p, f"seed:{p.id}")
        db.commit()
        auth.seal_audit()
        print("Демо-данные созданы. Пароль всех учётных записей:", PASSWORD)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    run(ap.parse_args().reset)
