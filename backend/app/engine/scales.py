from __future__ import annotations


def score(scale: dict, answers: dict) -> tuple[int, dict]:
    """Возвращает (балл, градация). Бросает ValueError при неполных/неверных ответах."""
    answers = {str(k): v for k, v in answers.items()}
    for it in scale["items"]:
        key = str(it["n"])
        if key not in answers:
            raise ValueError(f"Нет ответа на пункт {key}")
        allowed = {o["value"] for o in it["options"]}
        if answers[key] not in allowed:
            raise ValueError(f"Недопустимый ответ {answers[key]!r} на пункт {key}")

    method = scale.get("scoring", {}).get("method", "sum")
    if method == "sum":
        total = sum(int(answers[str(it["n"])]) for it in scale["items"])
    elif method == "max_item_positive":
        # номер самого «тяжёлого» положительного пункта (C-SSRS скрининг)
        total = max((int(it["n"]) for it in scale["items"] if answers[str(it["n"])]), default=0)
    else:
        raise ValueError(f"Неизвестный метод подсчёта {method}")

    band = next((b for b in scale["bands"] if b["min"] <= total <= b["max"]), {"label": "—", "severity": 0})
    return total, band


def critical_items(scale: dict, answers: dict) -> list[dict]:
    return [it for it in scale["items"] if it.get("critical") and answers.get(str(it["n"]), 0)]
