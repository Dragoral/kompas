"""Схемы справочников (JSON Schema, draft 2020-12) и смысловые проверки.

Схема описывает структуру — по ней интерфейс строит формы, а внешние
инструменты проверяют файлы. Смысловые проверки ловят то, что схемой не
выразить: градации шкалы покрывают весь диапазон баллов без пересечений,
правила ссылаются на существующие переменные и действия, пункты не дублируются.

Ошибки возвращаются списком [{"path": "items.3.options", "message": "..."}],
предупреждения — отдельно (не блокируют сохранение).
"""
from __future__ import annotations

from jsonschema import Draft202012Validator

from . import logic, variables

_OPTION = {"type": "object", "required": ["value", "label"],
           "properties": {"value": {"type": "number"}, "label": {"type": "string", "minLength": 1}}}
_BAND = {"type": "object", "required": ["min", "max", "label"],
         "properties": {"min": {"type": "number"}, "max": {"type": "number"}, "label": {"type": "string", "minLength": 1},
                        "severity": {"type": "integer", "minimum": 0, "maximum": 5}}}
_COND = {"type": "object", "minProperties": 1, "maxProperties": 1}
_SOURCE = {"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}, "url": {"type": "string"}}}

SCHEMAS: dict[str, dict] = {
    "scale": {
        "title": "Психометрическая шкала / опросник",
        "type": "object",
        "required": ["code", "title", "respondent", "items", "bands", "license", "validation"],
        "properties": {
            "code": {"type": "string", "pattern": "^[A-Z0-9_]{2,16}$", "description": "Латиница, цифры, _ (напр. PHQ9)"},
            "title": {"type": "string", "minLength": 3},
            "respondent": {"enum": ["patient", "clinician"], "description": "Кто заполняет"},
            "period": {"type": "string", "description": "Период оценки, показывается перед вопросами"},
            "license": {"type": "string", "minLength": 3, "description": "Условия использования / правообладатель"},
            "validation": {"type": "array", "minItems": 1, "items": {"type": "string"},
                           "description": "Публикации: оригинал и валидация русскоязычной версии"},
            "verified": {"type": "boolean", "description": "Текст сверен с валидированной версией"},
            "items": {"type": "array", "minItems": 1, "items": {
                "type": "object", "required": ["n", "text"],
                "properties": {
                    "n": {"type": "integer", "minimum": 1}, "text": {"type": "string", "minLength": 2},
                    "type": {"enum": ["choice", "yes_no", "number"]},
                    "options": {"type": "array", "minItems": 2, "items": _OPTION},
                    "min": {"type": "number"}, "max": {"type": "number"},
                    "reverse": {"type": "boolean"}, "weight": {"type": "number"},
                    "required": {"type": "boolean"}, "critical": {"type": "boolean"}}}},
            "scoring": {"type": "object", "properties": {
                "method": {"enum": ["sum", "mean", "weighted_sum", "max_item_positive"]},
                "subscales": {"type": "object", "additionalProperties": {
                    "type": "object", "required": ["items"],
                    "properties": {"title": {"type": "string"}, "items": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
                                   "method": {"enum": ["sum", "mean", "weighted_sum"]}, "bands": {"type": "array", "items": _BAND}}}}}},
            "bands": {"type": "array", "minItems": 1, "items": _BAND},
            "mcid": {"type": "number", "description": "Клинически значимое изменение балла"},
        },
    },
    "drug": {
        "title": "Лекарственный препарат (по инструкции из ГРЛС)",
        "type": "object",
        "required": ["id", "trade_name", "inn", "indications", "registration", "sources"],
        "properties": {
            "id": {"type": "string", "pattern": "^[a-z0-9_]{2,40}$"},
            "trade_name": {"type": "string"}, "inn": {"type": "string"}, "atc": {"type": "string"},
            "classes": {"type": "array", "items": {"type": "string"}},
            "registration": {"type": "object", "required": ["number"], "properties": {"number": {"type": "string"}}},
            "sources": {"type": "object", "additionalProperties": _SOURCE, "minProperties": 1},
            "indications": {"type": "array", "minItems": 1, "items": {
                "type": "object", "required": ["id", "title", "icd10"],
                "properties": {"id": {"type": "string"}, "title": {"type": "string"},
                               "icd10": {"type": "array", "minItems": 1, "items": {"type": "string", "pattern": "^[A-Z][0-9]{2}(\\.[0-9]{1,2})?$"}},
                               "requires": _COND,
                               "regimen": {"type": "object", "properties": {"dose_mg": {"type": "number"}, "times_per_day": {"type": "number"},
                                                                            "daily_mg": {"type": "number"}, "max_daily_mg": {"type": "number"}}}}}},
            "contraindications": {"type": "array", "items": {"type": "object", "required": ["id", "title", "when"],
                                                             "properties": {"when": _COND}}},
            "cautions": {"type": "array", "items": {"type": "object", "required": ["id", "title", "when"], "properties": {"when": _COND}}},
            "interactions": {"type": "array", "items": {"type": "object", "required": ["classes", "severity", "text"],
                                                        "properties": {"severity": {"enum": ["contraindicated", "major", "moderate"]}}}},
        },
    },
    "rules": {
        "title": "Набор правил (алертинг / маршрутизация)",
        "type": "object",
        "required": ["rules"],
        "properties": {
            "rules": {"type": "array", "minItems": 1, "items": {
                "type": "object", "required": ["id", "when"],
                "properties": {"id": {"type": "string", "pattern": "^[a-z0-9_]{2,64}$"}, "when": _COND,
                               "severity": {"enum": ["critical", "high", "medium"]},
                               "level": {"enum": ["mandatory", "desirable"]}, "title": {"type": "string"},
                               "source": {"type": "string"}, "actions": {"type": "array"}}}},
            "thresholds": {"type": "object", "additionalProperties": {
                "type": "object", "required": ["default"], "properties": {"default": {"type": "number"}, "title": {"type": "string"}}}},
        },
    },
    "guideline": {
        "title": "Клинические рекомендации Минздрава России",
        "type": "object",
        "required": ["code", "id", "title", "icd10", "status", "url", "theses", "published"],
        "properties": {"theses": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["section", "text"], "properties": {"section": {"type": "string"}, "text": {"type": "string"}}}}},
    },
    "dictionary": {"title": "Словарь", "type": "object"},
}


_TYPES = {"string": "строка", "number": "число", "integer": "целое число", "boolean": "да/нет", "array": "список", "object": "объект"}


def _ru(e) -> str:
    v, val = e.validator, e.validator_value
    if v == "required":
        missing = e.message.split("'")[1] if "'" in e.message else ""
        return f"Обязательное поле «{missing}»"
    if v == "type":
        return f"Ожидается {_TYPES.get(val, val) if isinstance(val, str) else ' или '.join(_TYPES.get(t, t) for t in val)}"
    if v == "minLength":
        return f"Не короче {val} символов"
    if v == "minItems":
        return f"Нужно не меньше {val} элементов"
    if v == "minProperties":
        return "Не должно быть пустым"
    if v == "maxProperties":
        return "Условие должно содержать один оператор"
    if v == "enum":
        return f"Допустимые значения: {', '.join(map(str, val))}"
    if v == "pattern":
        return "Не соответствует формату"
    if v == "minimum":
        return f"Не меньше {val}"
    if v == "maximum":
        return f"Не больше {val}"
    return e.message


def _schema_errors(kind: str, body: dict) -> list[dict]:
    v = Draft202012Validator(SCHEMAS[kind])
    return [{"path": ".".join(str(x) for x in e.absolute_path) or "(корень)", "message": _ru(e)}
            for e in sorted(v.iter_errors(body), key=lambda e: list(e.absolute_path))]


def _check_condition(cond, path: str, errors: list, thresholds: set | None = None) -> None:
    try:
        logic.validate(cond)
    except Exception as e:  # noqa: BLE001
        errors.append({"path": path, "message": f"Некорректное условие: {e}"})
        return
    for var in variables.referenced(cond):
        if not variables.known(var):
            errors.append({"path": path, "message": f"Неизвестная переменная «{var}» (см. каталог переменных)"})
        elif thresholds is not None and var.startswith("thresholds.") and var.split(".", 1)[1] not in thresholds:
            errors.append({"path": path, "message": f"Порог «{var}» не объявлен в разделе thresholds"})


def _scale_semantics(b: dict, errors: list, warnings: list) -> None:
    from .scales import theoretical_range
    ns = [it.get("n") for it in b.get("items", [])]
    dup = sorted({n for n in ns if ns.count(n) > 1})
    if dup:
        errors.append({"path": "items", "message": f"Повторяются номера пунктов: {dup}"})
    for i, it in enumerate(b.get("items", [])):
        t = it.get("type", "choice")
        if t in ("choice", "yes_no") and not it.get("options"):
            errors.append({"path": f"items.{i}.options", "message": "Для пункта с выбором ответа нужны варианты"})
        if t == "number" and ("min" not in it or "max" not in it):
            errors.append({"path": f"items.{i}", "message": "Для числового пункта нужны min и max"})
        vals = [o["value"] for o in it.get("options", [])]
        if len(vals) != len(set(vals)):
            errors.append({"path": f"items.{i}.options", "message": "Повторяются значения вариантов ответа"})
    for key, sub in (b.get("scoring", {}).get("subscales") or {}).items():
        missing = [n for n in sub.get("items", []) if n not in ns]
        if missing:
            errors.append({"path": f"scoring.subscales.{key}", "message": f"Подшкала ссылается на несуществующие пункты: {missing}"})
    bands = sorted(b.get("bands", []), key=lambda x: x["min"])
    for a, c in zip(bands, bands[1:]):
        if c["min"] <= a["max"]:
            errors.append({"path": "bands", "message": f"Градации пересекаются: «{a['label']}» и «{c['label']}»"})
    if errors or not bands:
        return
    lo, hi = theoretical_range(b)
    if bands[0]["min"] > lo or bands[-1]["max"] < hi:
        errors.append({"path": "bands", "message": f"Градации не покрывают диапазон баллов {lo:g}–{hi:g}"})
    integer = b.get("scoring", {}).get("method", "sum") in ("sum", "max_item_positive")
    for a, c in zip(bands, bands[1:]):
        if integer and c["min"] - a["max"] > 1:
            errors.append({"path": "bands", "message": f"Пропуск между градациями «{a['label']}» и «{c['label']}»"})
    if not b.get("verified"):
        warnings.append({"path": "verified", "message": "Текст шкалы не отмечен как сверенный с валидированной версией"})


def _drug_semantics(b: dict, errors: list, warnings: list) -> None:
    for key in ("contraindications", "cautions"):
        ids = [c.get("id") for c in b.get(key, [])]
        if len(ids) != len(set(ids)):
            errors.append({"path": key, "message": "Повторяются идентификаторы"})
        for i, c in enumerate(b.get(key, [])):
            _check_condition(c.get("when"), f"{key}.{i}.when", errors)
    for i, ind in enumerate(b.get("indications", [])):
        if "requires" in ind:
            _check_condition(ind["requires"], f"indications.{i}.requires", errors)
    if not b.get("verified"):
        warnings.append({"path": "verified", "message": "Данные не отмечены как сверенные с инструкцией в ГРЛС"})


def _rules_semantics(b: dict, errors: list, warnings: list) -> None:
    from .alerts import ACTIONS
    ids = [r.get("id") for r in b.get("rules", [])]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errors.append({"path": "rules", "message": f"Повторяются идентификаторы правил: {dup}"})
    th = set((b.get("thresholds") or {}).keys())
    for k, cond in (b.get("applies") or {}).items():
        _check_condition(cond, f"applies.{k}", errors)
    for i, r in enumerate(b.get("rules", [])):
        _check_condition(r.get("when"), f"rules.{i}.when", errors, th if th else None)
        for a in r.get("actions", []):
            name = a if isinstance(a, str) else next(iter(a), "")
            if name not in ACTIONS:
                errors.append({"path": f"rules.{i}.actions", "message": f"Неизвестное действие «{name}». Доступные: {sorted(ACTIONS)}"})
        if "applies" in r and r["applies"] not in (b.get("applies") or {}):
            errors.append({"path": f"rules.{i}.applies", "message": f"Неизвестная область применения «{r['applies']}»"})
        if not r.get("source"):
            warnings.append({"path": f"rules.{i}.source", "message": "Не указан источник правила"})


def _guideline_semantics(b: dict, errors: list, warnings: list) -> None:
    for n, ln in (b.get("lines") or {}).items():
        if ln.get("thesis") and ln["thesis"] not in b.get("theses", {}):
            errors.append({"path": f"lines.{n}.thesis", "message": f"Ссылка на несуществующий тезис «{ln['thesis']}»"})


SEMANTICS = {"scale": _scale_semantics, "drug": _drug_semantics, "rules": _rules_semantics, "guideline": _guideline_semantics}


def check(kind: str, body: dict) -> tuple[list[dict], list[dict]]:
    """(ошибки, предупреждения). Ошибки блокируют сохранение."""
    if kind not in SCHEMAS:
        return [{"path": "kind", "message": f"Неизвестный тип справочника «{kind}»"}], []
    if not isinstance(body, dict):
        return [{"path": "(корень)", "message": "Ожидается объект"}], []
    errors = _schema_errors(kind, body)
    warnings: list[dict] = []
    if kind in SEMANTICS:
        sem: list[dict] = []
        try:  # смысловые проверки — и при ошибках структуры, насколько это возможно
            SEMANTICS[kind](body, sem, warnings)
        except Exception:  # noqa: BLE001 — неполная структура: о ней уже сообщила схема
            pass
        errors += [e for e in sem if e not in errors]
    return errors, warnings
