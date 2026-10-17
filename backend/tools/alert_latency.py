"""Замер времени доставки алерта врачу: от отправки критических данных пациентом
до получения события в канале врача (SSE). Запуск при работающем сервере:

    python tools/alert_latency.py --runs 20
"""
import argparse
import json
import statistics
import threading
import time
import uuid

import httpx

PASSWORD = "Kompas-demo-2026"


def login(c, who):
    r = c.post("/api/auth/login", json={"login": who, "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--runs", type=int, default=20)
    a = ap.parse_args()
    c = httpx.Client(base_url=a.base, timeout=30)
    doc, pat = login(c, "therapist"), login(c, "patient5")
    got: dict[int, float] = {}
    ready = threading.Event()

    def listen():
        ticket = c.post("/api/auth/stream-ticket", headers=doc).json()["ticket"]
        with httpx.stream("GET", f"{a.base}/api/doctor/stream", params={"ticket": ticket}, timeout=None) as r:
            event = None
            for line in r.iter_lines():
                if line.startswith("event:"):
                    event = line[6:].strip()
                    if event == "ready":
                        ready.set()
                elif line.startswith("data:") and event == "alert":
                    got[json.loads(line[5:])["id"]] = time.perf_counter()

    threading.Thread(target=listen, daemon=True).start()
    ready.wait(10)
    lat, server = [], []
    for _ in range(a.runs):
        ans = {str(i): 1 for i in range(1, 10)}
        ans["9"] = 2
        before = set(got)
        t0 = time.perf_counter()
        r = c.post("/api/me/scales", headers=pat, json={"scale_code": "PHQ9", "answers": ans, "client_id": str(uuid.uuid4())})
        r.raise_for_status()
        while not (set(got) - before) and time.perf_counter() - t0 < 5:
            time.sleep(0.001)
        new = set(got) - before
        if new:
            aid = new.pop()
            lat.append((got[aid] - t0) * 1000)
            server.append(c.post(f"/api/doctor/alerts/{aid}/delivered", headers=doc).json()["delivery_ms"])
            c.post(f"/api/doctor/alerts/{aid}/resolve", headers=doc, json={"resolution": "замер латентности"})
    q = lambda xs, p: round(sorted(xs)[min(len(xs) - 1, int(len(xs) * p))], 1)
    print(json.dumps({
        "runs": a.runs, "delivered": len(lat),
        "end_to_end_ms": {"p50": q(lat, .5), "p95": q(lat, .95), "max": round(max(lat), 1), "mean": round(statistics.mean(lat), 1)},
        "server_receipt_ms_p50": q(server, .5),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
