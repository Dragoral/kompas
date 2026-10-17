from conftest import pid


def _rec(client, tokens, doctor, code):
    p = pid(client, tokens, doctor, code)
    return client.get(f"/api/doctor/patients/{p}/recommendations", headers=tokens[doctor]).json()


def test_aviandr_consistent_after_two_failed_lines(client, tokens):
    rec = _rec(client, tokens, "psychiatrist", "P-DEMO1")
    g = rec["guidelines"][0]
    assert g["code"] == "KR457" and g["kr_id"] == "457_3" and g["status"] == "Применяется"
    assert g["line"]["line"] == 3
    av = next(d for d in rec["drugs"] if d["drug_id"] == "aviandr")
    pos = av["guideline_positions"][0]
    assert pos["status"] == "consistent" and pos["ref"]["evidence"] == "УУР B, УДД 2"
    esc = next(d for d in rec["drugs"] if d["drug_id"] == "escitalopram")
    assert any(c["id"] == "prior_failure" for c in esc["cautions"])  # уже был неэффективен
    assert g["response"]["remission"] is True and g["response"]["scale"] == "HAMA"


def test_aviandr_not_first_line_without_history(client, tokens):
    rec = _rec(client, tokens, "psychiatrist", "P-DEMO4")
    g = rec["guidelines"][0]
    assert g["line"]["line"] == 1
    assert any("Первая линия" in (s.get("action") or "") for s in g["next_steps"])
    av = next(d for d in rec["drugs"] if d["drug_id"] == "aviandr")
    assert av["guideline_positions"][0]["status"] == "earlier_lines_first"


def test_depression_guideline_and_cssrs_step(client, tokens):
    rec = _rec(client, tokens, "therapist", "P-DEMO3")
    g = rec["guidelines"][0]
    assert g["code"] == "KR301"
    av = next(d for d in rec["drugs"] if d["drug_id"] == "aviandr")
    assert av["guideline_positions"][0]["status"] == "not_in_guideline"
    assert any(s.get("action") == "Провести C-SSRS" for s in g["next_steps"])


def test_no_guideline_note_for_adjustment_disorder(client, tokens):
    rec = _rec(client, tokens, "therapist", "P-DEMO2")
    assert rec["guidelines"] == [] and rec["guidelines_note"]


def test_quality_criteria_flag_missing_suicide_assessment(client, tokens):
    rec = _rec(client, tokens, "psychiatrist", "P-DEMO6")
    q = {x["id"]: x["met"] for x in rec["guidelines"][0]["quality"]}
    assert q["q1"] is False and q["q4"] is True


def test_therapy_history_validation(client, tokens):
    p = pid(client, tokens, "psychiatrist", "P-DEMO4")
    r = client.patch(f"/api/doctor/patients/{p}", headers=tokens["psychiatrist"], json={"therapy_history": [{"inn": "x", "outcome": "bad"}]})
    assert r.status_code == 422


def test_routing_for_psychiatrist_patient_psychotherapy(client, tokens):
    rec = _rec(client, tokens, "psychiatrist", "P-DEMO4")
    routes = {r["target"]: r for r in rec["routing"]["routes"]}
    assert routes["psychotherapy"]["level"] == "desirable"  # КР 457, 3.3
    assert "psychiatrist" not in routes  # ведёт психиатр


def test_dependence_from_icd_code_makes_referral_mandatory(client, tokens):
    p = pid(client, tokens, "therapist", "P-DEMO2")
    card = client.get(f"/api/doctor/patients/{p}", headers=tokens["therapist"]).json()
    dx = card["patient"]["diagnoses"] + [{"icd10": "F10.2", "title": "Синдром зависимости от алкоголя"}]
    client.patch(f"/api/doctor/patients/{p}", headers=tokens["therapist"], json={"diagnoses": dx})
    rec = _rec(client, tokens, "therapist", "P-DEMO2")
    psy = next(r for r in rec["routing"]["routes"] if r["target"] == "psychiatrist")
    assert psy["level"] == "mandatory" and any(x["id"] == "dependence" for x in psy["reasons"])
    client.patch(f"/api/doctor/patients/{p}", headers=tokens["therapist"], json={"diagnoses": card["patient"]["diagnoses"]})


def test_high_suicide_risk_routes_to_hospitalization(client, tokens):
    import uuid
    ans = {str(i): 1 for i in range(1, 7)}
    r = client.post("/api/me/scales", headers=tokens["patient6"], json={"scale_code": "CSSRS", "answers": ans, "client_id": str(uuid.uuid4())})
    assert r.status_code == 200
    rec = _rec(client, tokens, "psychiatrist", "P-DEMO6")
    hosp = next(x for x in rec["routing"]["routes"] if x["target"] == "hospitalization")
    assert hosp["level"] == "mandatory" and rec["routing"]["routes"][0]["target"] == "hospitalization"
    acts = client.get("/api/doctor/actions", headers=tokens["psychiatrist"]).json()
    assert any(a["kind"] == "referral" and a["payload"]["target"] == "hospitalization" for a in acts)
