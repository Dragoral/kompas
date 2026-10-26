"""Авторинг справочников: врач добавляет шкалу без программиста."""
import uuid

from conftest import pid

CSV = """n;text;options
1;Мне трудно расслабиться;0=Нет|1=Иногда|2=Часто|3=Постоянно
2;Я чувствую напряжение;0=Нет|1=Иногда|2=Часто|3=Постоянно
3;Мне спокойно (обратный пункт);0=Нет|1=Иногда|2=Часто|3=Постоянно
"""


def test_doctor_adds_scale_from_csv_to_patient_result(client, tokens):
    doc, rev = tokens["therapist"], tokens["psychiatrist"]
    imp = client.post("/api/knowledge/import/csv", headers=doc, json={"csv": CSV, "code": "TST3", "title": "Тестовый опросник"}).json()
    draft = imp["draft"]
    assert len(draft["items"]) == 3 and imp["errors"]  # без градаций и источника не пройдёт
    draft["items"][2]["reverse"] = True
    draft["bands"] = [{"min": 0, "max": 3, "label": "Низкий", "severity": 0}, {"min": 4, "max": 9, "label": "Высокий", "severity": 2}]
    draft["validation"] = ["Тестовая публикация"]
    draft["license"] = "Свободно"
    draft["scoring"]["subscales"] = {"tension": {"title": "Напряжение", "items": [1, 2]}}
    v = client.post("/api/knowledge/validate", headers=doc, json={"kind": "scale", "body": draft}).json()
    assert v["valid"], v
    pv = client.post("/api/knowledge/scales/preview", headers=doc, json={"scale": draft, "answers": {"1": 3, "2": 2, "3": 3}}).json()
    assert pv["score"] == 5 and pv["band"] == "Высокий" and pv["subscales"]["tension"]["score"] == 5  # 3+2+(3-3)
    r = client.put("/api/knowledge/scale/TST3", headers=doc, json={"body": draft, "change_note": "Новый опросник для апробации"}).json()
    assert client.post(f"/api/review/knowledge/{r['draft_id']}", headers=rev, json={"decision": "approve"}).json()["status"] == "approved"
    # шкала сразу доступна в работе: назначаем пациенту и он её заполняет
    p = pid(client, tokens, "therapist", "P-DEMO2")
    assert client.post(f"/api/doctor/patients/{p}/assignments", headers=doc, json={"scale_code": "TST3"}).status_code == 200
    res = client.post("/api/me/scales", headers=_login(client, "patient2"),
                      json={"scale_code": "TST3", "answers": {"1": 1, "2": 1, "3": 0}, "client_id": str(uuid.uuid4())}).json()
    assert res["score"] == 5 and res["band"] == "Высокий"


def _login(client, who):
    t = client.post("/api/auth/login", json={"login": who, "password": "Kompas-demo-2026"}).json()["token"]
    return {"Authorization": f"Bearer {t}"}


def test_validation_reports_field_errors(client, tokens):
    bad = {"code": "BAD", "title": "Плохая шкала", "respondent": "patient", "license": "x", "validation": ["x"],
           "items": [{"n": 1, "text": "Вопрос", "options": [{"value": 0, "label": "a"}, {"value": 1, "label": "b"}]},
                     {"n": 1, "text": "Повтор", "options": [{"value": 0, "label": "a"}, {"value": 1, "label": "b"}]}],
           "bands": [{"min": 0, "max": 1, "label": "A"}, {"min": 1, "max": 2, "label": "B"}]}
    v = client.post("/api/knowledge/validate", headers=tokens["therapist"], json={"kind": "scale", "body": bad}).json()
    msgs = " ".join(e["message"] for e in v["errors"])
    assert not v["valid"] and "Повторяются номера пунктов" in msgs
    r = client.put("/api/knowledge/scale/BAD", headers=tokens["therapist"], json={"body": bad, "change_note": "проверка ошибок"})
    assert r.status_code == 422 and r.json()["errors"]


def test_rule_with_unknown_variable_rejected_and_rule_explained(client, tokens):
    doc = tokens["psychiatrist"]
    r = client.post("/api/knowledge/rules/test", headers=doc, json={"condition": {">": [{"var": "scales.PHQ9.scroe"}, 5]}, "patient_id": 1})
    assert r.status_code == 422 and "Неизвестная переменная" in str(r.json()["errors"])
    p = pid(client, tokens, "psychiatrist", "P-DEMO1")
    ok = client.post("/api/knowledge/rules/test", headers=doc,
                     json={"condition": {"<=": [{"var": "scales.HAMA.subscales.psychic"}, 7]}, "patient_id": p}).json()
    assert isinstance(ok["result"], bool) and ok["explain"]["args"][0]["expr"] == "переменная scales.HAMA.subscales.psychic"


def test_fhir_roundtrip_and_ssrf_protection(client, tokens):
    doc = tokens["therapist"]
    fhir = client.get("/api/knowledge/scales/GAD7/fhir", headers=doc).json()
    assert fhir["resourceType"] == "Questionnaire" and len(fhir["item"]) == 7
    back = client.post("/api/knowledge/import/fhir-questionnaire", headers=doc, json={"resource": fhir}).json()
    assert len(back["draft"]["items"]) == 7 and back["draft"]["items"][0]["options"][3]["value"] == 3
    for url in ("http://example.org/q.json", "https://127.0.0.1/q.json", "https://localhost/q.json"):
        r = client.post("/api/knowledge/import/fhir-questionnaire", headers=doc, json={"url": url})
        assert r.status_code == 422, url


def test_catalogues_available_to_authors(client, tokens):
    doc = tokens["therapist"]
    assert any(v["path"] == "scales.*.score" for v in client.get("/api/knowledge/variables", headers=doc).json())
    assert "request_scale" in {a["name"] for a in client.get("/api/knowledge/actions", headers=doc).json()}
    assert client.get("/api/knowledge/schemas/scale", headers=doc).json()["required"]
    assert client.get("/api/knowledge/variables", headers=tokens["patient1"]).status_code == 403


def test_unverified_clinical_knowledge_is_reported(client, tokens):
    from app.engine import knowledge
    from app.db import SessionLocal

    with SessionLocal() as db:
        kb = knowledge.get(db)
        issues = set(knowledge.unverified_clinical_items(kb))
    assert "scale:PHQ9" in issues
    assert "rules:routing" in issues
    assert "rules:alerts" in issues
    assert "drug:sertraline" in issues
    assert "drug:aviandr" not in issues
    assert "guideline:kr301" not in issues


def test_itt_norms_by_sex_and_daily_plan(client, tokens):
    from app.db import SessionLocal
    from app.engine import knowledge, scales
    with SessionLocal() as db:
        itt = knowledge.get(db)["scale"]["ITT"]
    ans = {str(n): 1 for n in range(1, 16)}  # сырой балл 15
    assert scales.evaluate(itt, ans, {"patient": {"sex": "m"}})["band"].startswith("6 станайн")
    female = scales.evaluate(itt, ans, {"patient": {"sex": "f"}})
    assert female["band"].startswith("5 станайн") and female["norm_group"] == "Нормы для женщин"
    # пациентка: результат считается по женским нормам
    r = client.post("/api/me/scales", headers=tokens["patient1"],
                    json={"scale_code": "ITT", "answers": ans, "client_id": str(uuid.uuid4())}).json()
    assert r["score"] == 15 and r["band"].startswith("5 станайн")
    # базовый план: ИТТ ежедневно, GAD-7 и PHQ-9 раз в 2 недели
    p = pid(client, tokens, "psychiatrist", "P-DEMO1")
    plan = {a["scale_code"]: a["every_days"] for a in
            client.get(f"/api/doctor/patients/{p}", headers=tokens["psychiatrist"]).json()["assignments"] if a["every_days"]}
    assert plan == {"ITT": 1, "GAD7": 14, "PHQ9": 14}


def test_norm_group_bands_are_validated(client, tokens):
    from app.engine import schemas
    body = {"code": "NG", "title": "Нормы", "respondent": "patient", "license": "Свободно", "validation": ["x"],
            "items": [{"n": 1, "text": "Вопрос", "options": [{"value": 0, "label": "a"}, {"value": 3, "label": "b"}]}],
            "bands": [{"min": 0, "max": 3, "label": "Все"}],
            "norm_groups": [{"when": {"==": [{"var": "patient.sex"}, "f"]},
                             "bands": [{"min": 0, "max": 1, "label": "Низко"}]}]}
    errors, _ = schemas.check("scale", body)
    assert any(e["path"] == "norm_groups.0.bands" and "не покрывают" in e["message"] for e in errors)
