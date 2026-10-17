"""Рекомендации по терапии и маршрутизации.

Детерминированно и объяснимо: каждый вывод сопровождается источником (пункт
инструкции, клиническая рекомендация, шкала). Система ничего не назначает —
результат показывается врачу, который подтверждает или отклоняет.
"""
from __future__ import annotations

import time

from . import guidelines, knowledge, logic

SEVERITY_ORDER = {"contraindicated": 3, "major": 2, "moderate": 1}


def evaluate_drug(drug: dict, ctx: dict, kb: dict) -> dict:
    instr = drug.get("sources", {}).get("instruction", {})
    icds = ctx["patient"]["icd10"]

    indication = None
    for ind in drug["indications"]:
        if any(code.startswith(i) for code in icds for i in ind["icd10"]):
            if "requires" in ind and not logic.evaluate(ind["requires"], ctx):
                continue
            indication = ind
            break

    contra = [
        {"id": c["id"], "title": c["title"], "note": c.get("note"), "source": instr.get("title", "") + ", раздел «Противопоказания»"}
        for c in drug.get("contraindications", []) if logic.evaluate(c["when"], ctx)
    ]
    cautions = [
        {"id": c["id"], "title": c["title"], "source": instr.get("title", "") + ", раздел «С осторожностью»"}
        for c in drug.get("cautions", []) if logic.evaluate(c["when"], ctx)
    ]
    by_class = ctx["meds"].get("by_class", {})
    interactions = []
    for it in drug.get("interactions", []):
        hit = [c for c in it["classes"] if c in by_class]
        if hit:
            titles = kb["dictionary"].get("drug_classes", {}).get("class_titles", {})
            interactions.append({
                "severity": it["severity"],
                "text": it["text"],
                "with": sorted({n for c in hit for n in by_class[c]}),
                "classes": [titles.get(c, c) for c in hit],
                "source": instr.get("title", "") + ", раздел «Взаимодействие»",
            })
    interactions.sort(key=lambda x: -SEVERITY_ORDER.get(x["severity"], 0))

    # Ранее применялся у пациента (анамнез курсов)
    outcome_titles = {"no_response": "без эффекта", "partial": "частичный эффект", "intolerance": "непереносимость",
                      "response": "был эффективен", "unknown": "исход не указан"}
    prior = [c for c in ctx.get("history", {}).get("courses", []) if c.get("inn") == drug["inn"]]
    prior_courses = [{"dose": c.get("dose"), "weeks": c.get("weeks"), "outcome": c.get("outcome"),
                      "outcome_title": outcome_titles.get(c.get("outcome"), c.get("outcome"))} for c in prior]
    if any(c.get("outcome") in ("no_response", "intolerance") for c in prior):
        cautions.append({"id": "prior_failure", "title": "В анамнезе пациента курс этого препарата: " +
                         "; ".join(f"{c['dose'] or ''} {c['weeks'] or '?'} нед. — {c['outcome_title']}".strip() for c in prior_courses),
                         "source": "Анамнез терапии (карта пациента)"})

    blocked = bool(contra) or any(i["severity"] == "contraindicated" for i in interactions)
    if blocked:
        status = "contraindicated"
    elif indication is None:
        status = "off_label"
    else:
        status = "indicated"

    return {
        "drug_id": drug["id"],
        "trade_name": drug["trade_name"],
        "inn": drug["inn"],
        "pharm_group": drug.get("pharm_group"),
        "status": status,
        "indication": indication and {"id": indication["id"], "title": indication["title"], "icd10": indication["icd10"]},
        "regimen": indication["regimen"] if indication else None,
        "contraindications": contra,
        "cautions": cautions,
        "interactions": interactions,
        "monitoring": drug.get("monitoring"),
        "additional_monitoring": drug.get("additional_monitoring", False),
        "verified": drug.get("verified", False),
        "registration": drug.get("registration"),
        "guideline_positions": guidelines.drug_position(drug, kb, ctx),
        "prior_courses": prior_courses,
        "sources": [s for s in drug.get("sources", {}).values()],
        "note": {
            "indicated": "Показан в рамках зарегистрированных показаний. Назначение — после подтверждения врачом.",
            "off_label": "Нет зарегистрированного показания для диагнозов пациента. Применение вне инструкции — только решением врача.",
            "contraindicated": "Есть противопоказания по инструкции — назначение заблокировано.",
        }[status],
    }


def routing(ctx: dict, kb: dict) -> dict | None:
    """Маршрутизация по целям: консультация психиатра (для непсихиатров), госпитализация,
    психотерапия. Для каждой цели — уровень «обязательно»/«желательно» и причины с источниками.
    Если ничего не сработало — маршрут по умолчанию (наблюдение у лечащего врача)."""
    rs = kb["rules"].get("routing")
    if not rs:
        return None
    applies = {k: logic.evaluate(v, ctx) for k, v in (rs.get("applies") or {}).items()}
    by_target: dict[str, list[dict]] = {}
    for r in rs["rules"]:
        if not applies.get(r.get("applies", "all"), True) or not logic.evaluate(r["when"], ctx):
            continue
        by_target.setdefault(r.get("target", "psychiatrist"), []).append(
            {"id": r["id"], "title": r["title"], "level": r["level"], "urgency": r.get("urgency"), "source": r.get("source")})
    routes = []
    for target, hits in by_target.items():
        hits.sort(key=lambda h: h["level"] != "mandatory")
        level = "mandatory" if any(h["level"] == "mandatory" for h in hits) else "desirable"
        routes.append({"target": target, "title": rs.get("targets", {}).get(target, target), "level": level,
                       "urgency": hits[0].get("urgency"), "reasons": hits})
    routes.sort(key=lambda x: (x["level"] != "mandatory", x["target"] != "hospitalization"))
    if not routes:
        d = rs.get("default_route", {"target": "observation", "title": "Наблюдение у лечащего врача"})
        routes = [{"target": d["target"], "title": d["title"], "level": None, "urgency": None, "reasons": []}]
    psy = next((x for x in routes if x["target"] == "psychiatrist"), None)
    return {
        "routes": routes,
        # совместимость: направление к психиатру (ТЗ п. 8)
        "level": psy["level"] if psy else None,
        "reasons": psy["reasons"] if psy else [],
        "applies_to_psychiatrist_referral": applies.get("non_psychiatrist", True),
        "verified": rs.get("verified", False),
    }


def recommend(ctx: dict, kb: dict, drug_ids: list[str] | None = None) -> dict:
    t0 = time.perf_counter()
    order = {"indicated": 0, "off_label": 1, "contraindicated": 2}
    drugs = [evaluate_drug(d, ctx, kb) for code, d in kb["drug"].items() if not drug_ids or code in drug_ids]
    failed_before = lambda d: any(c["outcome"] in ("no_response", "intolerance") for c in d["prior_courses"])
    # Порядок: статус по инструкции -> соответствие этапу по КР и номер линии -> анамнез -> название.
    # Никаких предпочтений отдельным препаратам.
    def kr_rank(d):
        pos = d["guideline_positions"]
        if not pos:
            return (1, 9)
        best = min(pos, key=lambda x: ({"consistent": 0, "earlier_lines_first": 1}.get(x["status"], 2), x.get("line") or 9))
        return ({"consistent": 0, "earlier_lines_first": 1}.get(best["status"], 2), best.get("line") or 9)
    drugs.sort(key=lambda d: (order[d["status"]], kr_rank(d), failed_before(d), d["trade_name"]))
    return {
        "drugs": drugs,
        "routing": routing(ctx, kb),
        "guidelines": guidelines.evaluate(ctx, kb),
        "guidelines_note": None if guidelines.applicable(ctx, kb) else
            "Для диагнозов пациента клинические рекомендации в справочнике не загружены — рекомендации только по инструкции к препаратам",
        "knowledge_versions": {f"{k}:{c}": v for (k, c), v in kb.get("versions", {}).items()
                               if k in ("drug", "guideline") or (k, c) == ("rules", "routing")},
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
