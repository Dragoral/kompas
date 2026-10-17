"""Нагрузочный тест: N одновременных пользователей (врачи и пациенты) выполняют
типовые сценарии в цикле. Отчёт: запросов/с, p50/p95/p99, доля ошибок —
для каждого уровня нагрузки. Запуск при работающем сервере:

    python tools/load_test.py --levels 10 50 100 200 --seconds 20
"""
import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from datetime import date

import httpx

PASSWORD = "Kompas-demo-2026"
DOCTORS = ["psychiatrist", "therapist"]
PATIENTS = ["patient1", "patient2", "patient5", "patient6"]  # с активным наблюдением


async def login(c, who):
    r = await c.post("/api/auth/login", json={"login": who, "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def doctor_flow(c, h, rec):
    r = await c.get("/api/doctor/patients", headers=h)
    rec("GET /doctor/patients", r)
    ps = r.json() if r.status_code == 200 else []
    if ps:
        pid = random.choice(ps)["id"]
        rec("GET /doctor/patients/{id}", await c.get(f"/api/doctor/patients/{pid}", headers=h))
        rec("GET /recommendations", await c.get(f"/api/doctor/patients/{pid}/recommendations", headers=h))
    rec("GET /doctor/alerts", await c.get("/api/doctor/alerts", headers=h))


async def patient_flow(c, h, rec):
    rec("GET /me/overview", await c.get("/api/me/overview", headers=h))
    rec("POST /me/diary", await c.post("/api/me/diary", headers=h, json={
        "day": date.today().isoformat(), "mood": random.randint(3, 8), "anxiety": random.randint(2, 7), "client_id": str(uuid.uuid4())}))
    ans = {str(i): random.randint(0, 2) for i in range(1, 8)}
    rec("POST /me/scales GAD7", await c.post("/api/me/scales", headers=h, json={"scale_code": "GAD7", "answers": ans, "client_id": str(uuid.uuid4())}))
    rec("GET /me/history", await c.get("/api/me/history?days=30", headers=h))


async def run_level(base, n, seconds, tokens):
    lat: dict[str, list[float]] = {}
    errors = {"n": 0, "codes": {}}
    total = 0

    def rec(name, r):
        nonlocal total
        total += 1
        lat.setdefault(name, []).append(r.elapsed.total_seconds() * 1000)
        if r.status_code == 503:  # штатный отказ под перегрузкой: клиент повторит
            errors["backpressure"] = errors.get("backpressure", 0) + 1
        elif r.status_code >= 400:
            errors["n"] += 1
            errors["codes"][r.status_code] = errors["codes"].get(r.status_code, 0) + 1

    limits = httpx.Limits(max_connections=n, max_keepalive_connections=n)
    async with httpx.AsyncClient(base_url=base, timeout=60, limits=limits) as c:
        stop = time.perf_counter() + seconds

        async def user(i):
            is_doc = i % 4 == 0  # 25% врачей, 75% пациентов
            h = tokens[DOCTORS[i % 2]] if is_doc else tokens[PATIENTS[i % len(PATIENTS)]]
            while time.perf_counter() < stop:
                try:
                    await (doctor_flow if is_doc else patient_flow)(c, h, rec)
                except httpx.HTTPError:
                    errors["n"] += 1
                await asyncio.sleep(random.uniform(0.2, 1.0))  # «время на чтение»

        t0 = time.perf_counter()
        await asyncio.gather(*(user(i) for i in range(n)))
        dur = time.perf_counter() - t0
    allv = sorted(x for v in lat.values() for x in v)
    q = lambda xs, p: round(xs[min(len(xs) - 1, int(len(xs) * p))], 1) if xs else None
    return {"users": n, "requests": total, "rps": round(total / dur, 1), "error_pct": round(errors["n"] * 100 / max(total, 1), 2),
            "error_codes": errors["codes"], "backpressure_503_pct": round(errors.get("backpressure", 0) * 100 / max(total, 1), 2), "p50_ms": q(allv, .5), "p95_ms": q(allv, .95), "p99_ms": q(allv, .99),
            "by_endpoint_p95_ms": {k: q(sorted(v), .95) for k, v in lat.items()}}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--levels", type=int, nargs="+", default=[10, 50, 100, 200])
    ap.add_argument("--seconds", type=int, default=20)
    ap.add_argument("--out", default="data/load_test.json")
    a = ap.parse_args()
    async with httpx.AsyncClient(base_url=a.base, timeout=60) as c:
        tokens = {w: await login(c, w) for w in DOCTORS + PATIENTS}
    results = []
    for n in a.levels:
        r = await run_level(a.base, n, a.seconds, tokens)
        print(json.dumps({k: v for k, v in r.items() if k != "by_endpoint_p95_ms"}, ensure_ascii=False))
        results.append(r)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"levels": results, "seconds_per_level": a.seconds}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    asyncio.run(main())
