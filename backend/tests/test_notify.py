from datetime import datetime

from app import notify
from app.db import WriteSession
from app.engine import knowledge
from app.models import Alert, Notification, Patient

MON_10_MSK = datetime(2026, 10, 19, 7, 0)   # понедельник 10:00 МСК (UTC+3)
MON_22_MSK = datetime(2026, 10, 19, 19, 0)  # понедельник 22:00 МСК


def _alert(db, p, rule="suicide_phq9"):
    a = Alert(patient_id=p.id, doctor_id=p.doctor_id, rule_id=rule, severity="critical", title="тест", actions=[])
    db.add(a)
    db.flush()
    return a


def test_working_hours_routing_and_trusted_contact(client, tokens):
    with WriteSession() as db:
        kb = knowledge.get(db)
        p = db.query(Patient).filter(Patient.code == "P-DEMO5").one()
        a = _alert(db, p)
        day = notify.route_critical(db, kb, a, p, at=MON_10_MSK)
        assert day[0].startswith("лечащий врач (рабочее время)") and any("доверенное лицо" in x for x in day)
        b = _alert(db, p)
        night = notify.route_critical(db, kb, b, p, at=MON_22_MSK)
        assert "дежурная служба" in night and not any(x.startswith("лечащий врач (рабочее") for x in night)
        assert b.escalated_to is not None
        db.flush()
        reasons = {n.reason for n in db.query(Notification).filter(Notification.alert_id == b.id)}
        assert reasons == {"duty", "trusted_contact"}  # лечащему врачу ночью SMS не уходит
        tc_sms = db.query(Notification).filter(Notification.alert_id == b.id, Notification.reason == "trusted_contact").one()
        for w in ("F43", "расстройств", "Авиандр", "PHQ", "суицид"):
            assert w not in tc_sms.text  # без диагноза и медицинских сведений
        assert "Артём" in tc_sms.text and "112" in tc_sms.text
        db.rollback()


def test_trusted_contact_requires_separate_consent(client, tokens):
    h = tokens["patient1"]
    c = client.get("/api/consent/trusted-contact").json()
    bad = client.post("/api/me/trusted-contacts", headers=h, json={"name": "Мама", "phone": "+7 900 111-22-33",
                                                                    "consent_version": c["version"], "consent_sha256": "0" * 64})
    assert bad.status_code == 409
    ok = client.post("/api/me/trusted-contacts", headers=h, json={"name": "Соколова Ирина", "phone": "+7 900 111-22-33", "relation": "мать",
                                                                   "consent_version": c["version"], "consent_sha256": c["sha256"]}).json()
    ov = client.get("/api/me/overview", headers=h).json()
    assert any("Соколова Ирина" in x["title"] for x in ov["crisis_contacts"])
    assert client.delete(f"/api/me/trusted-contacts/{ok['id']}", headers=h).status_code == 200
    assert client.get("/api/me/trusted-contacts", headers=h).json() == []


def test_card_header_bmi(client, tokens):
    from conftest import pid
    p = pid(client, tokens, "psychiatrist", "P-DEMO1")
    hdr = client.get(f"/api/doctor/patients/{p}", headers=tokens["psychiatrist"]).json()["header"]
    assert hdr["bmi"] == round(58 / 1.65 ** 2, 1) and hdr["diagnoses"] and "allergies" in hdr
    assert hdr["medications"][0]["prescribed_here"] is True
