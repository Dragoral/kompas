import uuid

from conftest import PASSWORD, pid


def phq9(item9=0, total=12):
    ans = {str(i): 0 for i in range(1, 10)}
    ans["9"] = item9
    left, i = total - item9, 1
    while left > 0:
        add = min(3, left)
        ans[str(i)] = add
        left -= add
        i += 1
    return ans


def test_s1_gad_psychiatrist_aviandr_indicated_remission(client, tokens):
    p = pid(client, tokens, "psychiatrist", "P-DEMO1")
    rec = client.get(f"/api/doctor/patients/{p}/recommendations", headers=tokens["psychiatrist"]).json()
    av = next(d for d in rec["drugs"] if d["drug_id"] == "aviandr")
    assert av["status"] == "indicated"
    assert av["regimen"]["daily_mg"] == 40
    assert av["registration"]["number"].startswith("ЛП-")
    # пациентка у психиатра, получает КПТ — маршрут по умолчанию: наблюдение у лечащего врача
    assert [r["target"] for r in rec["routing"]["routes"]] == ["observation"]
    card = client.get(f"/api/doctor/patients/{p}", headers=tokens["psychiatrist"]).json()
    assert card["context"]["scales"]["HAMA"]["score"] <= 7  # ремиссия


def test_s2_post_covid_therapist_no_referral(client, tokens):
    p = pid(client, tokens, "therapist", "P-DEMO2")
    rec = client.get(f"/api/doctor/patients/{p}/recommendations", headers=tokens["therapist"]).json()
    av = next(d for d in rec["drugs"] if d["drug_id"] == "aviandr")
    assert av["status"] == "indicated" and av["indication"]["id"] == "post_covid_anxiety"
    assert "4 недели" in av["regimen"]["duration"]
    assert rec["routing"]["level"] is None


def test_s3_depression_off_label_requires_doctor_rationale(client, tokens):
    p = pid(client, tokens, "therapist", "P-DEMO3")
    rec = client.get(f"/api/doctor/patients/{p}/recommendations", headers=tokens["therapist"]).json()
    statuses = {d["drug_id"]: d["status"] for d in rec["drugs"]}
    assert statuses["aviandr"] == "off_label"  # депрессия — нет в показаниях Авиандра
    assert statuses["escitalopram"] == "indicated" and statuses["paroxetine"] == "indicated"
    assert statuses["pregabalin"] == "off_label"
    assert rec["routing"]["level"] == "desirable"
    r = client.post(f"/api/doctor/patients/{p}/prescriptions", headers=tokens["therapist"], json={"drug_id": "aviandr"})
    assert r.status_code == 409
    r = client.post(f"/api/doctor/patients/{p}/prescriptions", headers=tokens["therapist"],
                    json={"drug_id": "aviandr", "acknowledge_off_label": True,
                          "rationale": "Выраженный тревожный компонент, решение врача после очного осмотра"})
    assert r.status_code == 422  # для off-label обязательно явно подтвердить режим
    r = client.post(f"/api/doctor/patients/{p}/prescriptions", headers=tokens["therapist"], json={
        "drug_id": "aviandr", "acknowledge_off_label": True,
        "rationale": "Выраженный тревожный компонент, решение врача после очного осмотра",
        "regimen": {"dose_mg": 20, "times_per_day": 1}
    })
    assert r.status_code == 200 and r.json()["status"] == "off_label"


def test_s4_contraindication_blocks(client, tokens):
    p = pid(client, tokens, "psychiatrist", "P-DEMO4")
    rec = client.get(f"/api/doctor/patients/{p}/recommendations", headers=tokens["psychiatrist"]).json()
    av = next(d for d in rec["drugs"] if d["drug_id"] == "aviandr")
    assert av["status"] == "contraindicated"
    assert any(c["id"] == "renal" for c in av["contraindications"])
    assert any("трамадол" in " ".join(i["with"]).lower() for i in av["interactions"])
    r = client.post(f"/api/doctor/patients/{p}/prescriptions", headers=tokens["psychiatrist"], json={"drug_id": "aviandr"})
    assert r.status_code == 409


def test_s5_suicide_signal_alert_crisis_referral(client, tokens):
    r = client.post("/api/me/scales", headers=tokens["patient5"],
                    json={"scale_code": "PHQ9", "answers": phq9(item9=2, total=16), "client_id": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    assert r.json()["crisis"] is True
    p = pid(client, tokens, "therapist", "P-DEMO5")
    alerts = client.get("/api/doctor/alerts", headers=tokens["therapist"]).json()
    a = next(x for x in alerts if x["patient_id"] == p and x["rule_id"] == "suicide_phq9")
    assert a["severity"] == "critical" and a["pushed_at"]
    assert "crisis_screen" in a["actions"] and "escalate" in a["actions"]
    acts = client.get("/api/doctor/actions", headers=tokens["therapist"]).json()
    ref = next(x for x in acts if x["patient_id"] == p and x["kind"] == "referral")
    assert ref["level"] == "mandatory" and ref["status"] == "proposed"  # только предложено, решает врач
    ov = client.get("/api/me/overview", headers=tokens["patient5"]).json()
    assert ov["crisis"] is True
    assert any(s["code"] == "CSSRS" for s in ov["due_scales"])  # внеплановая C-SSRS
    d = client.post(f"/api/doctor/alerts/{a['id']}/delivered", headers=tokens["therapist"])
    assert d.json()["delivery_ms"] >= 0
    r = client.post(f"/api/doctor/actions/{ref['id']}/decide", headers=tokens["therapist"], json={"decision": "confirm"})
    assert r.json()["status"] == "confirmed"
    assert client.post(f"/api/doctor/actions/{ref['id']}/decide", headers=tokens["therapist"], json={"decision": "reject"}).status_code == 409


def test_s6_adverse_event_pharmacovigilance(client, tokens):
    p = pid(client, tokens, "psychiatrist", "P-DEMO6")
    acts = client.get("/api/doctor/actions", headers=tokens["psychiatrist"]).json()
    pv = next(x for x in acts if x["patient_id"] == p and x["kind"] == "pv_report")
    rep = client.get(f"/api/doctor/actions/{pv['id']}/pv-report", headers=tokens["psychiatrist"]).json()
    assert rep["suspected_drug"]["trade_name"] == "Авиандр"
    assert rep["reaction"]["expected_by_instruction"] is True
    assert rep["additional_monitoring"] is True
    assert rep["mandatory"] is False and rep["deadline"] is None  # несерьёзная НР — п. 20 приказа № 3518
    assert "3518" in rep["legal_basis"]
    assert "full_name" not in rep["patient"]  # обезличено
    alerts = client.get("/api/doctor/alerts", headers=tokens["psychiatrist"]).json()
    assert any(x["patient_id"] == p and x["rule_id"] == "low_adherence" for x in alerts)


def test_access_control(client, tokens):
    p1 = pid(client, tokens, "psychiatrist", "P-DEMO1")
    assert client.get(f"/api/doctor/patients/{p1}", headers=tokens["therapist"]).status_code == 403
    assert client.get("/api/doctor/patients", headers=tokens["patient1"]).status_code == 403
    assert client.get("/api/admin/knowledge", headers=tokens["psychiatrist"]).status_code == 403
    assert client.get("/api/me/overview").status_code == 401


def test_idempotent_offline_sync(client, tokens):
    cid = str(uuid.uuid4())
    item = {"kind": "diary", "data": {"day": "2026-10-17", "mood": 6, "anxiety": 3, "client_id": cid}}
    r1 = client.post("/api/me/sync", headers=tokens["patient1"], json={"items": [item, item]}).json()
    r2 = client.post("/api/me/sync", headers=tokens["patient1"], json={"items": [item]}).json()
    ids = {x["id"] for x in r1["results"] + r2["results"]}
    assert len(ids) == 1 and all(x["ok"] for x in r1["results"] + r2["results"])


def test_invalid_inputs_rejected_not_crash(client, tokens):
    h = tokens["patient1"]
    assert client.post("/api/me/scales", headers=h, json={"scale_code": "PHQ9", "answers": {"1": 2}}).status_code == 422
    assert client.post("/api/me/scales", headers=h, json={"scale_code": "PHQ9", "answers": {str(i): 7 for i in range(1, 10)}}).status_code == 422
    assert client.post("/api/me/diary", headers=h, json={"day": "2026-10-17", "mood": 15}).status_code == 422
    assert client.post("/api/me/scales", headers=h, json={"scale_code": "HAMA", "answers": {}}).status_code in (403, 422)
    r = client.post("/api/me/sync", headers=h, json={"items": [{"kind": "scale", "data": {"scale_code": "NOPE", "answers": {}}}]})
    assert r.status_code == 200 and r.json()["results"][0]["ok"] is False


def test_self_harm_text_in_chat_raises_alert(client, tokens):
    r = client.post("/api/me/messages", headers=tokens["patient6"], json={"text": "Устала, иногда думаю что не хочу жить"})
    assert r.json()["crisis"] is True


def test_monitoring_requires_consent_and_in_person_visit(client, tokens):
    r = client.post("/api/doctor/patients", headers=tokens["therapist"], json={
        "full_name": "Тестов Тест Тестович", "birth_date": "1990-01-01", "sex": "m", "in_person_visit": False,
        "diagnoses": [{"icd10": "F41.1", "title": "ГТР"}]})
    new = r.json()
    assert client.post(f"/api/doctor/patients/{new['id']}/monitoring", headers=tokens["therapist"], json={"active": True}).status_code == 409
    login = client.post("/api/auth/login", json={"login": new["login"], "password": new["temporary_password"]}).json()
    h = {"Authorization": f"Bearer {login['token']}"}
    # Новому пациенту сначала нужно заменить временный пароль.
    assert client.post("/api/auth/password", headers=h, json={
        "old_password": new["temporary_password"], "new_password": "Patient-Test-Password-3492"
    }).status_code == 200
    login = client.post("/api/auth/login", json={"login": new["login"], "password": "Patient-Test-Password-3492"}).json()
    h = {"Authorization": f"Bearer {login['token']}"}
    assert client.post("/api/me/diary", headers=h, json={"day": "2026-10-17", "mood": 5}).status_code == 403  # нет согласия
    c = client.get("/api/consent").json()
    assert client.post("/api/me/consent", headers=h, json={"version": c["version"], "sha256": c["sha256"]}).status_code == 200
    assert client.post("/api/me/diary", headers=h, json={"day": "2026-10-17", "mood": 5}).status_code == 409  # нет наблюдения
    client.post(f"/api/doctor/patients/{new['id']}/visit", headers=tokens["therapist"])
    client.post(f"/api/doctor/patients/{new['id']}/monitoring", headers=tokens["therapist"], json={"active": True})
    assert client.post("/api/me/diary", headers=h, json={"day": "2026-10-17", "mood": 5}).status_code == 200


def test_login_lockout(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"login": "patient4", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"login": "patient4", "password": PASSWORD}).status_code == 429


def test_critical_alert_queues_sms_without_phi(client, tokens):
    from app import notify
    from app.db import WriteSession
    from app.models import Notification
    r = client.post("/api/me/scales", headers=tokens["patient5"],
                    json={"scale_code": "PHQ9", "answers": phq9(item9=1, total=10), "client_id": str(uuid.uuid4())})
    assert r.json()["crisis"] is True
    with WriteSession() as db:
        pend = db.query(Notification).filter(Notification.status == "pending").all()
        assert any("P-DEMO5" in n.text for n in pend)
        forbidden = ("Лебедев", "Новикова", "PHQ", "суицид", "мысли", "Авиандр")
        assert all(not any(w in n.text for w in forbidden) for n in pend)
        notify.send_pending(db)
        assert db.query(Notification).filter(Notification.status == "pending").count() == 0
        assert db.query(Notification).filter(Notification.status == "sent").count() >= 1


def test_patient_list_filters(client, tokens):
    h = tokens["psychiatrist"]
    by_name = client.get("/api/doctor/patients", headers=h, params={"q": "соколова"}).json()
    assert [p["code"] for p in by_name] == ["P-DEMO1"]
    gad = client.get("/api/doctor/patients", headers=h, params={"icd": "F41.1"}).json()
    assert {p["code"] for p in gad} >= {"P-DEMO1", "P-DEMO4"}
    low = client.get("/api/doctor/patients", headers=h, params={"adherence_below": 80}).json()
    assert "P-DEMO6" in {p["code"] for p in low} and "P-DEMO1" not in {p["code"] for p in low}
    r = client.get("/api/doctor/patients", headers=h, params={"sort": "age", "desc": False, "limit": 1})
    assert len(r.json()) == 1 and int(r.headers["X-Total-Count"]) >= 3
    assert client.get("/api/doctor/patients", headers=h, params={"severity": "bad"}).status_code == 422


def test_critical_alert_not_repeated_on_unrelated_events(client, tokens):
    """Старый ответ PHQ-9 п. 9 не порождает новые критические алерты на каждое событие
    пациента; новый ответ с тем же признаком — порождает. Внеплановая C-SSRS не дублируется."""
    h = tokens["patient6"]
    p = pid(client, tokens, "psychiatrist", "P-DEMO6")

    def suicide_alerts():
        return [a for a in client.get("/api/doctor/alerts", headers=tokens["psychiatrist"]).json()
                if a["patient_id"] == p and a["rule_id"] == "suicide_phq9"]

    def cssrs_due():
        return sum(s["code"] == "CSSRS" for s in client.get("/api/me/overview", headers=h).json()["due_scales"])

    before = len(suicide_alerts())
    client.post("/api/me/scales", headers=h, json={"scale_code": "PHQ9", "answers": phq9(item9=1, total=10), "client_id": str(uuid.uuid4())})
    assert len(suicide_alerts()) == before + 1
    for _ in range(2):
        client.post("/api/me/scales", headers=h, json={"scale_code": "GAD7", "answers": {str(i): 1 for i in range(1, 8)},
                                                       "client_id": str(uuid.uuid4())})
    assert len(suicide_alerts()) == before + 1
    client.post("/api/me/scales", headers=h, json={"scale_code": "PHQ9", "answers": phq9(item9=2, total=12), "client_id": str(uuid.uuid4())})
    assert len(suicide_alerts()) == before + 2
    assert cssrs_due() == 1


def test_resolved_alert_not_recreated_by_resolve_itself(client, tokens):
    p = pid(client, tokens, "psychiatrist", "P-DEMO6")
    doc = tokens["psychiatrist"]
    open_ = [a for a in client.get("/api/doctor/alerts", headers=doc).json() if a["patient_id"] == p and a["severity"] != "critical"]
    a = open_[0]
    assert client.post(f"/api/doctor/alerts/{a['id']}/resolve", headers=doc, json={"resolution": "Связалась с пациентом"}).status_code == 200
    after = [x for x in client.get("/api/doctor/alerts", headers=doc).json() if x["patient_id"] == p and x["rule_id"] == a["rule_id"]]
    assert after == []


def test_prescription_rejects_unmatched_indication_and_oversized_dose(client, tokens):
    p = pid(client, tokens, "psychiatrist", "P-DEMO1")
    wrong_indication = client.post(f"/api/doctor/patients/{p}/prescriptions", headers=tokens["psychiatrist"], json={
        "drug_id": "aviandr", "indication_id": "post_covid_anxiety"
    })
    assert wrong_indication.status_code == 422
    too_high = client.post(f"/api/doctor/patients/{p}/prescriptions", headers=tokens["psychiatrist"], json={
        "drug_id": "aviandr", "regimen": {"dose_mg": 30, "times_per_day": 2}
    })
    assert too_high.status_code == 422


def test_unverified_drug_prescribed_with_warning_and_plan_not_duplicated(client, tokens):
    """Непроверенный справочник не блокирует решение врача, но предупреждает; при смене
    препарата план мониторинга заменяется, а не дублируется."""
    p = pid(client, tokens, "therapist", "P-DEMO3")
    h = tokens["therapist"]
    rationale = "Решение врача после очного осмотра, обсуждено с пациентом"
    for drug, dose in (("sertraline", 50), ("escitalopram", 10)):
        r = client.post(f"/api/doctor/patients/{p}/prescriptions", headers=h, json={
            "drug_id": drug, "acknowledge_off_label": True, "acknowledge_contraindications": True,
            "rationale": rationale, "regimen": {"dose_mg": dose, "times_per_day": 1}})
        assert r.status_code == 200, r.text
        assert any("не сверены" in w for w in r.json()["warnings"])
    plan = [a for a in client.get(f"/api/doctor/patients/{p}", headers=h).json()["assignments"]
            if (a["reason"] or "").startswith("План мониторинга")]
    codes = [a["scale_code"] for a in plan]
    assert len(codes) == len(set(codes)) and all("Эсциталопрам" in a["reason"] or "Ципралекс" in a["reason"] for a in plan)


def test_patient_api_rejects_malformed_diagnosis(client, tokens):
    response = client.post(
        "/api/doctor/patients",
        headers=tokens["therapist"],
        json={
            "full_name": "Тестовый Пациент",
            "birth_date": "1990-01-01",
            "sex": "f",
            "diagnoses": [{"title": "Диагноз без кода МКБ-10"}],
        },
    )
    assert response.status_code == 422
    assert "МКБ-10" in response.text
