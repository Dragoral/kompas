"""Применение клинических рекомендаций МЗ РФ к конкретному пациенту.

* какие КР применимы (по коду МКБ-10);
* на каком этапе (линии) психофармакотерапии находится пациент — по анамнезу
  курсов (therapy_history: исход response / partial / no_response / intolerance);
* место каждого препарата по КР («соответствует этапу» / «по КР — после
  неэффективности предыдущих линий» / «не упомянут в КР»);
* следующие шаги со ссылкой на тезис, раздел и УУР/УДД;
* ответ на терапию и ремиссия по критериям КР;
* критерии оценки качества медицинской помощи из КР.
Решение всегда за врачом: это справочная информация с источником.
"""
from __future__ import annotations

FAILED = {"no_response", "partial", "intolerance"}


def applicable(ctx: dict, kb: dict) -> list[dict]:
    icds = ctx["patient"]["icd10"]
    return [g for g in kb.get("guideline", {}).values()
            if any(icd.startswith(code) for icd in icds for code in g["icd10"])]


def _ref(g: dict, key: str) -> dict:
    t = g["theses"][key]
    ev = ", ".join(x for x in (t.get("uur") and f"УУР {t['uur']}", t.get("udd") and f"УДД {t['udd']}") if x) or t.get("evidence_note", "")
    return {"guideline": g["code"], "guideline_title": g["title"], "kr_id": g["id"], "section": t["section"], "text": t["text"],
            "evidence": ev, "url": g["url"]}


def line_reached(g: dict, ctx: dict) -> dict:
    """Этап, на который пациент вышел с учётом неэффективных курсов."""
    lines = {int(k): v for k, v in (g.get("lines") or {}).items()}
    courses = ctx["history"]["courses"]
    failed = [c for c in courses if c.get("outcome") in FAILED]
    failed_by_line: dict[int, list[str]] = {n: [c["inn"] for c in failed if c.get("inn") in ln.get("inn", [])] for n, ln in lines.items()}
    reached = 1
    if failed_by_line.get(1):
        reached = 2
        # вторая линия исчерпана: неэффективна сама 2-я линия или два препарата 1-й линии (смена внутри 1-й линии — стратегия 2-й линии)
        if failed_by_line.get(2) or len(set(failed_by_line[1])) >= 2:
            reached = 3
    return {"line": reached, "title": lines.get(reached, {}).get("title"), "failed": {n: v for n, v in failed_by_line.items() if v}}


def drug_position(drug: dict, kb: dict, ctx: dict) -> list[dict]:
    out = []
    for g in applicable(ctx, kb):
        lines = {int(k): v for k, v in (g.get("lines") or {}).items()}
        n = next((k for k, ln in lines.items() if drug["inn"] in ln.get("inn", [])), None)
        if n is None:
            out.append({"guideline": g["code"], "status": "not_in_guideline",
                        "note": f"В КР «{g['title']}» препарат не упомянут — назначение по инструкции, решение врача"})
            continue
        reached = line_reached(g, ctx)["line"]
        ref = _ref(g, lines[n]["thesis"])
        if n <= reached:
            out.append({"guideline": g["code"], "status": "consistent", "line": n, "reached": reached, "ref": ref,
                        "note": f"Соответствует этапу терапии по КР ({lines[n]['title'].lower()})"})
        else:
            need = ", ".join(lines[k]["title"].lower() for k in range(1, n) if k in lines)
            out.append({"guideline": g["code"], "status": "earlier_lines_first", "line": n, "ref": ref,
                        "note": f"По КР рекомендуется после неэффективности: {need}. В анамнезе пациента этого нет — назначение возможно по инструкции, решение врача"})
    return out


def response(ctx: dict) -> dict:
    """Ответ/ремиссия по КР 457: HARS — ответ при снижении > 50%, ремиссия < 7 баллов.
    Если HAM-A нет — ориентировочно по GAD-7 (Spitzer 2006: < 5 — минимальная тревога)."""
    s = ctx["scales"]
    if "HAMA" in s and s["HAMA"]["change_from_baseline_pct"] is not None:
        h = s["HAMA"]
        return {"scale": "HAMA", "score": h["score"], "change_pct": h["change_from_baseline_pct"],
                "response": h["change_from_baseline_pct"] < -50, "remission": h["score"] < 7,
                "source": "КР 457, раздел 3.2: ответ — снижение HARS > 50%, ремиссия — < 7 баллов"}
    if "GAD7" in s and s["GAD7"]["change_from_baseline_pct"] is not None:
        g = s["GAD7"]
        return {"scale": "GAD7", "score": g["score"], "change_pct": g["change_from_baseline_pct"],
                "response": g["change_from_baseline_pct"] <= -50, "remission": g["score"] < 5,
                "source": "Ориентировочно по GAD-7 (снижение ≥ 50%; < 5 — минимальная тревога, Spitzer 2006); для КР — подтвердить HAM-A"}
    return {"scale": None}


def quality(g: dict, ctx: dict) -> list[dict]:
    s = ctx["scales"]
    weeks = ctx["therapy"]["weeks_on_current"]
    no_resp = any(c.get("outcome") in FAILED for c in ctx["history"]["courses"])
    checks = {
        "suicide_risk_assessed": "PHQ9" in s or "CSSRS" in s,
        "pharmacotherapy_prescribed": bool(ctx["therapy"]["active_drugs"]),
        "therapy_changed_if_no_response": (bool(ctx["therapy"]["active_drugs"]) if no_resp else None),
        "psychotherapy": bool(ctx["patient"].get("psychotherapy")),
        "efficacy_reassessed": bool(weeks is not None and (s.get("HAMA", {}).get("count", 0) >= 2 or s.get("GAD7", {}).get("count", 0) >= 2)),
        "consent_recorded": ctx["monitoring"]["in_person_visit"],
    }
    return [{"id": q["id"], "text": q["text"], "met": checks.get(q["check"])} for q in g.get("quality_criteria", [])]


def next_steps(g: dict, ctx: dict) -> list[dict]:
    steps = []
    on_therapy = bool(ctx["therapy"]["active_drugs"])
    lr = line_reached(g, ctx)
    th = g["theses"]
    if not on_therapy:
        if "complex_therapy" in th:
            steps.append(_ref(g, "complex_therapy"))
        line = (g.get("lines") or {}).get(lr["line"]) or (g.get("lines") or {}).get(str(lr["line"]))
        if line:
            steps.append({**_ref(g, line["thesis"]), "action": f"{line['title']}: {', '.join(line.get('inn', []))}"})
        if "warn_side_effects" in th:
            steps.append(_ref(g, "warn_side_effects"))
    else:
        weeks = ctx["therapy"]["weeks_on_current"] or 0
        r = response(ctx)
        for key in ("assessment_schedule", "repeat_visit"):
            if key in th:
                steps.append(_ref(g, key))
        if r.get("scale") and weeks >= 4 and not r["response"]:
            if (ctx["adherence"]["pct_14d"] or 100) < 80 and "check_adherence" in th:
                steps.append({**_ref(g, "check_adherence"), "action": f"Приверженность {ctx['adherence']['pct_14d']}% — сначала исключить нарушение режима"})
            key = "response_criteria" if "response_criteria" in th else "second_stage"
            if key in th:
                steps.append({**_ref(g, key), "action": f"{weeks} нед. терапии без ответа ({r['scale']} {r['change_pct']}%) — рассмотреть смену терапии"})
        if r.get("remission") and "duration" in th:
            steps.append({**_ref(g, "duration"), "action": "Ремиссия: продолжить терапию в той же дозе"})
    if not ctx["patient"].get("psychotherapy"):
        for key in ("relaxation", "cbt"):
            if key in th:
                steps.append(_ref(g, key))
    if "suicide_risk" in th and "CSSRS" not in ctx["scales"]:
        steps.append({**_ref(g, "suicide_risk"), "action": "Провести C-SSRS"})
    return steps


def evaluate(ctx: dict, kb: dict) -> list[dict]:
    out = []
    for g in applicable(ctx, kb):
        out.append({
            "code": g["code"], "kr_id": g["id"], "title": g["title"], "status": g["status"], "published": g["published"],
            "url": g["url"], "line": line_reached(g, ctx), "response": response(ctx),
            "next_steps": next_steps(g, ctx), "quality": quality(g, ctx),
        })
    return out
