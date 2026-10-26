"""Нежелательные реакции: слова пациента -> стандартные термины -> сравнение с инструкциями."""
import uuid

from conftest import pid

from app.db import SessionLocal
from app.engine import adverse, knowledge


def _kb():
    with SessionLocal() as db:
        return knowledge.get(db)


def test_colloquial_negation_and_typos(client):
    kb = _kb()
    terms, flags = adverse.recognize("По утрам кружится голова и подташнивает", kb)
    assert set(terms) == {"головокружение", "тошнота"} and flags == []
    terms, _ = adverse.recognize("Тошноты нет, но болит голова", kb)
    assert terms == ["головная боль"]
    terms, _ = adverse.recognize("головакружене уже неделю", kb)  # две опечатки
    assert terms == ["головокружение"]
    assert adverse.recognize("головокружения нет", kb)[0] == []


def test_instruction_synonyms_are_matched(client):
    # в инструкции Авиандра — «гипергидроз», пациент пишет «сильно потею»
    table = adverse.drug_reactions(_kb()["drug"]["aviandr"], _kb())
    assert table["гипергидроз"] == "uncommon" and table["головокружение"] == "common"
    assert adverse.recognize("сильно потею ночью", _kb())[0] == ["гипергидроз"]


def _report(client, tokens, text):
    r = client.post("/api/me/adverse-events", headers=tokens["patient1"],
                    json={"description": text, "intensity": "moderate", "client_id": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    card = client.get(f"/api/doctor/patients/{pid(client, tokens, 'psychiatrist', 'P-DEMO1')}", headers=tokens["psychiatrist"]).json()
    return r.json(), next(a for a in card["adverse_events"] if a["id"] == r.json()["id"])


def test_expected_unexpected_and_unrecognized(client, tokens):
    _, ae = _report(client, tokens, "Голова кружится после утренней таблетки")
    assert ae["expected"] is True and ae["title"] == "головокружение"
    m = ae["analysis"]["terms"][0]["in_instructions"][0]
    assert m["drug_id"] == "aviandr" and m["relation"] == "current" and m["frequency_label"] == "часто"
    assert ae["description"] == "Голова кружится после утренней таблетки"  # слова пациента — врачу, в зашифрованном поле

    _, ae = _report(client, tokens, "Всё тело чешется")
    assert ae["expected"] is False and ae["title"] == "кожный зуд"  # распознано, но в инструкции нет

    _, ae = _report(client, tokens, "Какое-то странное ощущение")
    assert ae["expected"] is None and ae["analysis"]["recognized"] is False  # решает врач, не система


def test_red_flags_raise_alert_and_advise_patient(client, tokens):
    r, ae = _report(client, tokens, "Отекло лицо, трудно дышать")
    assert r["urgent"] is True and r["crisis"] is True
    assert ae["analysis"]["red_flags"][0]["id"] == "anaphylaxis"
    alerts = client.get("/api/doctor/alerts", headers=tokens["psychiatrist"]).json()
    assert any(a["rule_id"] == "ae_red_flag_critical" for a in alerts)
    # «судороги в ногах» — мышечный симптом, а не судорожный приступ
    assert adverse.recognize("ночью судороги в ногах", _kb())[1] == []


def test_doctor_confirms_classification(client, tokens):
    _, ae = _report(client, tokens, "Снизился аппетит")
    r = client.post(f"/api/doctor/adverse-events/{ae['id']}/review", headers=tokens["psychiatrist"], json={"expected": True})
    assert r.status_code == 200
    log = client.get("/api/admin/audit?action=adverse_event_reviewed", headers=tokens["admin"]).json()[0]
    assert log["details"]["expected"] is True and log["details"]["system_expected"] is True
