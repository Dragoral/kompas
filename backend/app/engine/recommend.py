"""Рекомендации по терапии и маршрутизации.

Детерминированно и объяснимо: каждый вывод сопровождается источником (пункт
инструкции, клиническая рекомендация, шкала). Система ничего не назначает —
результат показывается врачу, который подтверждает или отклоняет.
"""
from __future__ import annotations

import time

from . import knowledge, logic

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
        "sources": [s for s in drug.get("sources", {}).values()],
        "note": {
            "indicated": "Показан в рамках зарегистрированных показаний. Назначение — после подтверждения врачом.",
            "off_label": "Нет зарегистрированного показания для диагнозов пациента. Применение вне инструкции — только решением врача.",
            "contraindicated": "Есть противопоказания по инструкции — назначение заблокировано.",
        }[status],
    }


def routing(ctx: dict, kb: dict) -> dict | None:
    rs = kb["rules"].get("routing")
    if not rs:
        return None
    if "applies_when" in rs and not logic.evaluate(rs["applies_when"], ctx):
        return None
    hits = [
        {"id": r["id"], "title": r["title"], "level": r["level"], "urgency": r.get("urgency"), "source": r.get("source")}
        for r in rs["rules"] if logic.evaluate(r["when"], ctx)
    ]
    level = "mandatory" if any(h["level"] == "mandatory" for h in hits) else ("desirable" if hits else None)
    hits.sort(key=lambda h: h["level"] != "mandatory")
    return {"level": level, "reasons": hits}


def recommend(ctx: dict, kb: dict, drug_ids: list[str] | None = None) -> dict:
    t0 = time.perf_counter()
    order = {"indicated": 0, "off_label": 1, "contraindicated": 2}
    drugs = [evaluate_drug(d, ctx, kb) for code, d in kb["drug"].items() if not drug_ids or code in drug_ids]
    drugs.sort(key=lambda d: (order[d["status"]], d["drug_id"] != "aviandr"))
    return {
        "drugs": drugs,
        "routing": routing(ctx, kb),
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
    }
