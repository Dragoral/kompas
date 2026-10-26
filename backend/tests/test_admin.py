import copy

from conftest import PASSWORD, pid


def _login(client, who):
    r = client.post("/api/auth/login", json={"login": who, "password": PASSWORD}).json()
    return {"Authorization": f"Bearer {r['token']}"}


def test_knowledge_change_requires_clinical_approval(client, tokens):
    adm, rev = tokens["admin"], tokens["psychiatrist"]
    cur = client.get("/api/admin/knowledge/rules/alerts", headers=adm).json()
    body = copy.deepcopy(cur["body"])
    body["thresholds"]["no_contact_days"]["default"] = 7
    bad = copy.deepcopy(body)
    bad["rules"][0]["when"] = {"eval": ["__import__('os')"]}
    assert client.put("/api/admin/knowledge/rules/alerts", headers=adm, json={"body": bad, "change_note": "плохое правило"}).status_code == 422
    r = client.put("/api/admin/knowledge/rules/alerts", headers=adm, json={"body": body, "change_note": "Порог «нет связи» 7 дней"}).json()
    # до одобрения — действует старая версия
    assert client.get("/api/admin/knowledge/rules/alerts", headers=adm).json()["version"] == cur["version"]
    assert client.post(f"/api/review/knowledge/{r['draft_id']}", headers=tokens["therapist"], json={"decision": "approve"}).status_code == 403
    pending = client.get("/api/review/knowledge", headers=rev).json()
    assert any(p["id"] == r["draft_id"] for p in pending)
    ok = client.post(f"/api/review/knowledge/{r['draft_id']}", headers=rev, json={"decision": "approve", "comment": "согласовано"}).json()
    assert ok["status"] == "approved" and ok["version"] == cur["version"] + 1
    vs = client.get("/api/admin/knowledge/rules/alerts/versions", headers=adm).json()
    assert [v["status"] for v in vs][:2] == ["approved", "superseded"]
    # откат — тоже через одобрение
    old = vs[1]["id"]
    rb = client.post("/api/admin/knowledge/rules/alerts/rollback", headers=adm, json={"to_version_id": old, "change_note": "вернуть 4 дня"}).json()
    assert client.post(f"/api/review/knowledge/{rb['draft_id']}", headers=rev, json={"decision": "approve"}).json()["status"] == "approved"


def test_user_management_and_reassignment(client, tokens):
    adm = tokens["admin"]
    r = client.post("/api/admin/users", headers=adm, json={"login": "newdoc", "full_name": "Новый Врач Тестович", "role": "doctor", "specialty": "therapist"}).json()
    login = client.post('/api/auth/login', json={'login': 'newdoc', 'password': r['temporary_password']}).json()
    h = {"Authorization": f"Bearer {login['token']}"}
    # Временный пароль блокирует клинические данные до обязательной смены.
    assert client.get("/api/doctor/patients", headers=h).status_code == 403
    assert client.post('/api/auth/password', headers=h, json={
        'old_password': r['temporary_password'], 'new_password': 'Safe-Test-Password-9482'
    }).status_code == 200
    h = {"Authorization": f"Bearer {client.post('/api/auth/login', json={'login': 'newdoc', 'password': 'Safe-Test-Password-9482'}).json()['token']}"}
    assert client.get("/api/doctor/patients", headers=h).json() == []

    # Второй администратор подтверждает перевод пациента, чтобы один человек
    # не мог единолично менять лечащего врача.
    a2 = client.post('/api/admin/users', headers=adm, json={
        'login': 'adminsecond', 'full_name': 'Второй Администратор', 'role': 'admin'
    }).json()
    a2login = client.post('/api/auth/login', json={'login': 'adminsecond', 'password': a2['temporary_password']}).json()
    a2h = {'Authorization': f"Bearer {a2login['token']}"}
    assert client.post('/api/auth/password', headers=a2h, json={
        'old_password': a2['temporary_password'], 'new_password': 'Safe-Admin-Password-9482'
    }).status_code == 200
    a2h = {'Authorization': f"Bearer {client.post('/api/auth/login', json={'login': 'adminsecond', 'password': 'Safe-Admin-Password-9482'}).json()['token']}"}

    p = pid(client, tokens, "psychiatrist", "P-DEMO6")
    request = client.post(f"/api/admin/patients/{p}/attending", headers=adm,
                          json={"doctor_id": r["id"], "reason": "смена участка"})
    assert request.status_code == 200 and request.json()['status'] == 'pending'
    assert client.get(f"/api/doctor/patients/{p}", headers=h).status_code == 403
    assert client.post(f"/api/admin/attending-requests/{request.json()['request_id']}/approve",
                       headers=a2h, json={'comment': 'проверено'}).status_code == 200
    assert client.get(f"/api/doctor/patients/{p}", headers=h).status_code == 200
    assert client.get(f"/api/doctor/patients/{p}", headers=tokens["psychiatrist"]).status_code == 403

    back = client.post(f"/api/admin/patients/{p}/attending", headers=a2h,
                       json={"doctor_id": 1, "reason": "вернуть прежнего врача"})
    assert back.status_code == 200
    assert client.post(f"/api/admin/attending-requests/{back.json()['request_id']}/approve",
                       headers=adm, json={'comment': 'возврат согласован'}).status_code == 200
    client.patch(f"/api/admin/users/{r['id']}", headers=adm, json={"active": False})
    assert client.get("/api/auth/me", headers=h).status_code == 401  # блокировка — сессии отозваны


def test_visits(client, tokens):
    p = pid(client, tokens, "psychiatrist", "P-DEMO1")
    v = client.post(f"/api/doctor/patients/{p}/visits", headers=tokens["psychiatrist"],
                    json={"kind": "telemedicine", "reason": "контроль", "notes": "Самочувствие стабильное", "plan": {"next": "4 нед"}}).json()
    assert v["kind"] == "telemedicine" and v["notes"] == "Самочувствие стабильное"
    vs = client.get(f"/api/doctor/patients/{p}/visits", headers=tokens["psychiatrist"]).json()
    assert len(vs) >= 2 and {x["kind"] for x in vs} >= {"in_person", "telemedicine"}


def test_anonymized_analytics_suppresses_small_groups(client, tokens):
    assert client.get("/api/analytics/summary", headers=tokens["therapist"]).status_code == 403
    r = client.get("/api/analytics/summary", headers=tokens["admin"]).json()
    assert r["k_anonymity"] == 5
    text = str(r)
    for name in ("Соколова", "Лебедев", "P-DEMO"):
        assert name not in text  # ни ФИО, ни псевдонимов
    assert all(v == "< 5" or (isinstance(v, int) and v >= 5) for v in r["patients_by_diagnosis"].values())
    assert client.get("/api/analytics/summary", headers=tokens["admin"], params={"k": 2}).status_code == 422


def test_admin_patient_list_has_no_medical_data(client, tokens):
    rows = client.get("/api/admin/patients", headers=tokens["admin"]).json()
    assert rows and set(rows[0]) == {"id", "code", "doctor_id", "doctor_name", "monitoring_active"}
    assert client.get("/api/admin/patients", headers=tokens["psychiatrist"]).status_code == 403


def test_doctor_working_hours_validated_and_saved(client, tokens):
    adm = tokens["admin"]
    uid = next(u["id"] for u in client.get("/api/admin/users", headers=adm).json() if u["login"] == "therapist")
    bad = client.patch(f"/api/admin/users/{uid}", headers=adm, json={"working_hours": {"days": [1], "start": "18:00", "end": "09:00"}})
    assert bad.status_code == 422
    ok = client.patch(f"/api/admin/users/{uid}", headers=adm, json={"working_hours": {"days": [5, 1, 1], "start": "08:00", "end": "16:00"}})
    assert ok.json()["working_hours"] == {"days": [1, 5], "start": "08:00", "end": "16:00"}
    assert client.patch(f"/api/admin/users/{uid}", headers=adm, json={"working_hours": None}).json()["working_hours"] is None


def test_admin_cannot_mutate_patient_account(client, tokens):
    from app.models import Patient, User
    from app.db import SessionLocal
    with SessionLocal() as db:
        patient = db.query(Patient).filter(Patient.code == "P-DEMO1").one()
        uid = patient.user_id
    assert client.patch(f"/api/admin/users/{uid}", headers=tokens["admin"], json={"active": False}).status_code == 403
    assert client.post(f"/api/admin/users/{uid}/reset-password", headers=tokens["admin"]).status_code == 403
