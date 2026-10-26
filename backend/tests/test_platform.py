"""Каркас: формат ошибок, идентификатор запроса, готовность, устойчивость к сбоям."""
from app import observability
from app.engine import logic


def test_validation_error_is_problem_json_in_russian(client, tokens):
    r = client.post("/api/me/diary", headers=tokens["patient1"], json={"day": "не-дата", "mood": 15})
    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["title"] == "Ошибка в данных" and body["request_id"] == r.headers["X-Request-ID"]
    fields = {e["field"]: e["message"] for e in body["errors"]}
    assert fields["body.mood"] == "Значение должно быть не больше 10"
    assert "body.day" in fields


def test_request_id_is_propagated(client):
    r = client.get("/api/health", headers={"X-Request-ID": "demo-request-0001"})
    assert r.headers["X-Request-ID"] == "demo-request-0001"
    bad = client.get("/api/health", headers={"X-Request-ID": "<script>"})
    assert bad.headers["X-Request-ID"] != "<script>"  # небезопасный идентификатор заменяется


def test_errors_have_uniform_shape(client, tokens):
    for r in (client.get("/api/me/overview"),  # 401
              client.get("/api/doctor/patients", headers=tokens["patient1"]),  # 403
              client.get("/api/scales/NOPE", headers=tokens["patient1"])):  # 404
        b = r.json()
        assert {"type", "title", "status", "detail", "request_id"} <= set(b) and b["status"] == r.status_code


def test_body_size_limit(client, tokens):
    r = client.post("/api/me/messages", headers={**tokens["patient1"], "Content-Length": str(10 * 1024 * 1024)}, content=b"x")
    assert r.status_code == 413


def test_ready_and_admin_system(client, tokens):
    r = client.get("/api/ready")
    assert r.status_code == 200 and r.json() == {"status": "ready"}
    # Public readiness endpoint must not disclose component diagnostics or task errors.
    assert "checks" not in r.json() and "last_error" not in r.text
    s = client.get("/api/admin/system", headers=tokens["admin"]).json()
    assert {"checks", "components", "problems", "queues"} <= set(s)
    assert client.get("/api/admin/system", headers=tokens["psychiatrist"]).status_code == 403


def test_broken_rule_does_not_break_request_and_is_reported():
    before = len(observability.problems(500))
    assert logic.safe_eval({"unknown_op": [1, 2]}, {}, "test:broken") is False
    probs = observability.problems(500)
    assert len(probs) == before + 1 and probs[0]["ref"] == "test:broken"


def test_ready_hides_internal_diagnostics(client, monkeypatch):
    from app.api import system

    monkeypatch.setattr(system, "_checks", lambda _db: {
        "job:notification_sender": {"ok": False, "last_error": "secret internal failure"},
        "database": {"ok": True},
    })
    r = client.get("/api/ready")
    assert r.status_code == 503
    assert "secret internal failure" not in r.text
    assert "job:notification_sender" not in r.text
    assert r.json()["detail"] == "Сервис временно не готов"


def test_resolved_alert_without_dated_evidence_is_quiet_for_a_week():
    from datetime import timedelta
    from types import SimpleNamespace

    from app.engine import alerts
    from app.models import now
    rule = {"when": {">=": [{"var": "therapy.weeks_on_current"}, 4]}}
    closed = SimpleNamespace(resolved_at=now() - timedelta(days=2), acknowledged_at=None, created_at=now() - timedelta(days=3))
    assert not alerts._may_repeat_after_resolve(rule, {"_observed_at": {}}, closed)
    closed.resolved_at = now() - timedelta(days=8)
    assert alerts._may_repeat_after_resolve(rule, {"_observed_at": {}}, closed)
    dated = {"when": {">=": [{"var": "scales.PHQ9.score"}, 20]}}
    assert alerts._may_repeat_after_resolve(dated, {"_observed_at": {"scales.PHQ9": now()}}, closed)
