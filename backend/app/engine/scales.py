"""Движок психометрических шкал — полностью управляется описанием шкалы (данными).

Пункт шкалы:
    n        — номер (уникальный)
    text     — формулировка
    type     — choice (выбор варианта, по умолчанию) | yes_no | number
    options  — [{value, label}] для choice/yes_no
    min/max  — диапазон для number
    reverse  — обратный пункт: балл = (min + max) − ответ
    weight   — вес пункта (по умолчанию 1)
    required — обязателен ли ответ (по умолчанию да)
    critical — критический пункт (ответ > 0 — сигнал для правил алертинга)

Подсчёт (scoring):
    method    — метод из реестра METHODS: sum | mean | weighted_sum | max_item_positive
    subscales — {key: {title, items: [n…], method?, bands?}} — подшкалы
Градации (bands) — по общему баллу: [{min, max, label, severity}].

Новый метод подсчёта добавляется одной функцией в реестр METHODS — ядро не меняется.
"""
from __future__ import annotations

from typing import Callable


def _item_range(it: dict) -> tuple[float, float]:
    if it.get("type") == "number":
        return float(it.get("min", 0)), float(it.get("max", 0))
    vals = [o["value"] for o in it.get("options", [])]
    return (min(vals), max(vals)) if vals else (0, 0)


def item_value(it: dict, raw) -> float:
    lo, hi = _item_range(it)
    v = float(raw)
    return (lo + hi - v) if it.get("reverse") else v


def _sum(items: list[dict], ans: dict) -> float:
    return sum(item_value(it, ans[str(it["n"])]) for it in items if str(it["n"]) in ans)


def _mean(items: list[dict], ans: dict) -> float:
    vals = [item_value(it, ans[str(it["n"])]) for it in items if str(it["n"]) in ans]
    return round(sum(vals) / len(vals), 2) if vals else 0


def _weighted_sum(items: list[dict], ans: dict) -> float:
    return sum(item_value(it, ans[str(it["n"])]) * float(it.get("weight", 1)) for it in items if str(it["n"]) in ans)


def _max_item_positive(items: list[dict], ans: dict) -> float:
    """Номер самого «тяжёлого» положительного пункта (скрининг C-SSRS)."""
    return max((int(it["n"]) for it in items if ans.get(str(it["n"]))), default=0)


METHODS: dict[str, Callable[[list[dict], dict], float]] = {
    "sum": _sum, "mean": _mean, "weighted_sum": _weighted_sum, "max_item_positive": _max_item_positive,
}


def _num(x: float):
    return int(x) if float(x).is_integer() else round(x, 2)


def _band(bands: list[dict], total: float) -> dict:
    return next((b for b in bands if b["min"] <= total <= b["max"]), {"label": "—", "severity": 0})


def validate_answers(scale: dict, answers: dict) -> dict:
    """Проверка ответов; возвращает нормализованный словарь {"n": значение}."""
    ans = {str(k): v for k, v in answers.items()}
    known = {str(it["n"]) for it in scale["items"]}
    extra = sorted(set(ans) - known)
    if extra:
        raise ValueError(f"Неизвестные пункты: {', '.join(extra)}")
    for it in scale["items"]:
        key = str(it["n"])
        if key not in ans:
            if it.get("required", True):
                raise ValueError(f"Нет ответа на пункт {key}")
            continue
        v = ans[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"Пункт {key}: ожидается число")
        if it.get("type") == "number":
            lo, hi = _item_range(it)
            if not lo <= v <= hi:
                raise ValueError(f"Пункт {key}: значение вне диапазона {_num(lo)}–{_num(hi)}")
        elif v not in {o["value"] for o in it.get("options", [])}:
            raise ValueError(f"Недопустимый ответ {v!r} на пункт {key}")
        if float(v).is_integer():
            ans[key] = int(v)
    return ans


def norm_bands(scale: dict, subject: dict | None) -> tuple[list[dict], str | None]:
    """Градации с учётом норм для групп (пол, возраст): первая группа, чьё условие
    выполняется для пациента; иначе — общие градации шкалы."""
    from . import logic
    for g in scale.get("norm_groups") or []:
        if subject is not None and logic.evaluate(g["when"], subject):
            return g["bands"], g.get("title")
    return scale.get("bands", []), None


def evaluate(scale: dict, answers: dict, subject: dict | None = None) -> dict:
    """subject — данные пациента для выбора норм: {"patient": {"sex": "f", "age": 34}}."""
    ans = validate_answers(scale, answers)
    sc = scale.get("scoring", {})
    method = METHODS.get(sc.get("method", "sum"))
    if method is None:
        raise ValueError(f"Неизвестный метод подсчёта {sc.get('method')!r}")
    total = _num(method(scale["items"], ans))
    bands, norm_group = norm_bands(scale, subject)
    band = _band(bands, total)
    by_n = {str(it["n"]): it for it in scale["items"]}
    subscales = {}
    for key, sub in (sc.get("subscales") or {}).items():
        items = [by_n[str(n)] for n in sub["items"] if str(n) in by_n]
        val = _num(METHODS[sub.get("method", sc.get("method", "sum"))](items, ans))
        entry = {"title": sub.get("title", key), "score": val}
        if sub.get("bands"):
            entry["band"] = _band(sub["bands"], val)["label"]
        subscales[key] = entry
    return {
        "score": total, "band": band["label"], "severity": band.get("severity", 0), "subscales": subscales,
        "norm_group": norm_group,
        "critical_items": [int(it["n"]) for it in scale["items"] if it.get("critical") and ans.get(str(it["n"]))],
        "answers": ans,
    }


def score(scale: dict, answers: dict) -> tuple[int, dict]:
    """Совместимость: (общий балл, градация)."""
    r = evaluate(scale, answers)
    return r["score"], {"label": r["band"], "severity": r["severity"]}


def critical_items(scale: dict, answers: dict) -> list[dict]:
    return [it for it in scale["items"] if it.get("critical") and answers.get(str(it["n"]), 0)]


def theoretical_range(scale: dict) -> tuple[float, float]:
    """Минимально и максимально возможный общий балл (для проверки градаций)."""
    sc = scale.get("scoring", {})
    m = sc.get("method", "sum")
    if m == "max_item_positive":
        return 0, max(int(it["n"]) for it in scale["items"])
    lows, highs = [], []
    for it in scale["items"]:
        lo, hi = _item_range(it)
        w = float(it.get("weight", 1)) if m == "weighted_sum" else 1
        lows.append(lo * w)
        highs.append(hi * w)
    if m == "mean":
        return min(lows), max(highs)
    return sum(lows), sum(highs)
