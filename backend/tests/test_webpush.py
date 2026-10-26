"""Web Push: шифрование по примеру из RFC 8291 (раздел 5), подпись VAPID, ограничение адресов."""
import json

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app import webpush

# RFC 8291, раздел 5 — «Push Message Encryption Example»
PLAINTEXT = b"When I grow up, I want to be a watermelon"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
EXPECTED = ("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_"
            "yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


def test_encryption_matches_rfc8291_example():
    as_key = ec.derive_private_key(int.from_bytes(webpush.b64u_decode(AS_PRIVATE), "big"), ec.SECP256R1())
    body = webpush.encrypt(PLAINTEXT, UA_PUBLIC, AUTH, as_key=as_key, salt=webpush.b64u_decode(SALT))
    assert webpush.b64u(body) == EXPECTED


def test_vapid_jwt_is_valid_es256():
    key = ec.generate_private_key(ec.SECP256R1())
    h = webpush.vapid_header("https://fcm.googleapis.com/fcm/send/abc", key)
    token, k = h.removeprefix("vapid t=").split(", k=")
    head, claims, sig = token.split(".")
    assert json.loads(webpush.b64u_decode(claims))["aud"] == "https://fcm.googleapis.com"
    raw = webpush.b64u_decode(sig)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), webpush.b64u_decode(k))
    pub.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # бросит исключение при неверной подписи


def test_only_known_push_services_allowed():
    assert webpush.allowed_endpoint("https://fcm.googleapis.com/fcm/send/x")
    assert webpush.allowed_endpoint("https://wns2-db5p.notify.windows.com/w/?token=x")
    for bad in ("http://fcm.googleapis.com/x", "https://127.0.0.1/x", "https://evil.example/fcm.googleapis.com",
                "https://fcm.googleapis.com.evil.example/x", "https://fcm.googleapis.com:8443/x"):
        assert not webpush.allowed_endpoint(bad), bad


def _browser_keys():
    import os
    from cryptography.hazmat.primitives import serialization
    k = ec.generate_private_key(ec.SECP256R1())
    raw = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"p256dh": webpush.b64u(raw), "auth": webpush.b64u(os.urandom(16))}


def test_push_flow_without_medical_details(client, tokens, monkeypatch):
    import uuid
    from datetime import timedelta

    from conftest import pid

    from app import jobs, notify
    from app.db import SessionLocal, WriteSession
    from app.models import DoseLog, Notification, Patient, Prescription, PushSubscription, now

    sent = []
    monkeypatch.setattr(webpush, "send", lambda endpoint, p256dh, auth, payload, **kw: sent.append((endpoint, payload)))
    patient_h, doctor_h = tokens["patient4"], tokens["psychiatrist"]
    bad = client.post("/api/push/subscriptions", headers=patient_h,
                      json={"endpoint": "https://10.0.0.5/push", "keys": _browser_keys()})
    assert bad.status_code == 422
    for h, ep in ((patient_h, "https://fcm.googleapis.com/fcm/send/patient4"), (doctor_h, "https://fcm.googleapis.com/fcm/send/psy")):
        assert client.post("/api/push/subscriptions", headers=h, json={"endpoint": ep, "keys": _browser_keys()}).status_code == 200
    assert client.get("/api/push/subscriptions", headers=patient_h).json()["devices"] == 1

    p = pid(client, tokens, "psychiatrist", "P-DEMO4")
    client.post(f"/api/doctor/patients/{p}/messages", headers=doctor_h, json={"text": "Как вы себя чувствуете после смены дозы?"})
    client.post("/api/me/messages", headers=patient_h, json={"text": "не хочу жить", "client_id": str(uuid.uuid4())})  # критическое
    with WriteSession() as db:
        notify.send_pending(db)
    to_patient = [pl for ep, pl in sent if ep.endswith("patient4")]
    to_doctor = [pl for ep, pl in sent if ep.endswith("psy")]
    assert to_patient[0]["body"] == "Новое сообщение от врача" and "дозы" not in str(to_patient)
    assert any("пациент P-DEMO4" in pl["body"] and pl["urgency"] == "high" for pl in to_doctor)
    assert "жить" not in str(to_doctor)  # слова пациента в уведомление не попадают

    # напоминание о приёме: один раз в окне после планового времени
    with WriteSession() as db:
        pt = db.query(Patient).filter(Patient.code == "P-DEMO4").one()
        rx = Prescription(patient_id=pt.id, drug_id="pregabalin", regimen={"times_per_day": 1}, status="active", mode="in_person",
                          confirmed_by=pt.doctor_id)
        db.add(rx)
        db.flush()
        db.add(DoseLog(patient_id=pt.id, prescription_id=rx.id, scheduled_for=now() - timedelta(minutes=5), status="pending"))
        db.commit()
    sent.clear()
    jobs.reminders()
    jobs.reminders()
    with WriteSession() as db:
        notify.send_pending(db)
    assert [pl["body"] for ep, pl in sent if ep.endswith("patient4")].count("Время принять лекарство") == 1

    # недействительная подписка (410) удаляется
    def gone(*a, **kw):
        raise webpush.Gone("HTTP 410")
    monkeypatch.setattr(webpush, "send", gone)
    client.post("/api/push/test", headers=patient_h)
    with WriteSession() as db:
        notify.send_pending(db)
    with SessionLocal() as db:
        assert db.query(PushSubscription).filter(PushSubscription.endpoint.endswith("patient4")).count() == 0
        assert db.query(Notification).filter(Notification.reason == "test").one().status == "failed"
