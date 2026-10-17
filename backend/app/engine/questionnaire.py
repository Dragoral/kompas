"""Импорт/экспорт шкал: HL7 FHIR Questionnaire (R4/R5) и простая таблица CSV.

Импорт возвращает ЧЕРНОВИК описания шкалы и список того, что нужно дополнить
вручную (градации, источник валидации, лицензия) — эти сведения в
Questionnaire обычно отсутствуют, а без них шкала не пройдёт проверку.
Черновик затем отправляется на клиническое одобрение, как любое изменение.
"""
from __future__ import annotations

import csv
import io
import re

ORDINAL_EXT = ("http://hl7.org/fhir/StructureDefinition/ordinalValue",   # R4
               "http://hl7.org/fhir/StructureDefinition/itemWeight")     # R5
MIN_EXT = "http://hl7.org/fhir/StructureDefinition/minValue"
MAX_EXT = "http://hl7.org/fhir/StructureDefinition/maxValue"


def _code(s: str) -> str:
    c = re.sub(r"[^A-Z0-9_]", "", (s or "").upper().replace("-", "").replace(" ", "_"))
    return c[:16] if len(c) >= 2 else "NEW_SCALE"


def _ext(obj: dict, urls) -> float | None:
    for e in obj.get("extension", []) or []:
        if e.get("url") in (urls if isinstance(urls, tuple) else (urls,)):
            for k in ("valueDecimal", "valueInteger"):
                if k in e:
                    return e[k]
    return None


def _flatten(items: list[dict]) -> list[dict]:
    out = []
    for it in items or []:
        if it.get("type") == "group":
            out += _flatten(it.get("item", []))
        elif it.get("type") != "display":
            out.append(it)
    return out


def from_fhir(res: dict) -> tuple[dict, list[str]]:
    if res.get("resourceType") != "Questionnaire":
        raise ValueError("Ожидается ресурс FHIR Questionnaire")
    items, warnings = [], []
    for n, it in enumerate(_flatten(res.get("item", [])), start=1):
        text = it.get("text") or it.get("linkId") or f"Пункт {n}"
        t = it.get("type")
        if t in ("choice", "coding"):
            opts = []
            for i, ao in enumerate(it.get("answerOption", []) or []):
                coding = ao.get("valueCoding") or {}
                val = _ext(ao, ORDINAL_EXT)
                if val is None:
                    val = _ext(coding, ORDINAL_EXT)
                if val is None:
                    val = ao.get("valueInteger")
                if val is None and str(coding.get("code", "")).lstrip("-").isdigit():
                    val = int(coding["code"])
                if val is None:
                    val = i
                    warnings.append(f"Пункт {n}: у варианта «{coding.get('display') or ao}» нет балла — присвоен {i}, проверьте")
                label = coding.get("display") or ao.get("valueString") or str(val)
                opts.append({"value": val, "label": label})
            if not opts:
                warnings.append(f"Пункт {n}: нет вариантов ответа (answerValueSet не поддерживается) — добавьте вручную")
            items.append({"n": n, "text": text, "options": opts})
        elif t == "boolean":
            items.append({"n": n, "text": text, "type": "yes_no", "options": [{"value": 0, "label": "Нет"}, {"value": 1, "label": "Да"}]})
        elif t in ("integer", "decimal"):
            items.append({"n": n, "text": text, "type": "number", "min": _ext(it, MIN_EXT) or 0, "max": _ext(it, MAX_EXT) or 10})
            if _ext(it, MAX_EXT) is None:
                warnings.append(f"Пункт {n}: не задан максимум — установлено 10, проверьте")
        else:
            warnings.append(f"Пункт «{text[:40]}»: тип «{t}» не поддерживается — пропущен")
    body = {
        "code": _code(res.get("name") or res.get("id") or res.get("title", "")),
        "title": res.get("title") or res.get("name") or "Новая шкала",
        "respondent": "patient",
        "period": res.get("description", "")[:300] or None,
        "license": res.get("copyright") or "",
        "validation": [],
        "verified": False,
        "items": items,
        "scoring": {"method": "sum"},
        "bands": [],
        "source_import": {"format": "FHIR Questionnaire", "url": res.get("url"), "version": res.get("version")},
    }
    body = {k: v for k, v in body.items() if v is not None}
    missing = ["bands — градации баллов", "validation — публикация валидации русскоязычной версии"]
    if not body.get("license"):
        missing.append("license — условия использования")
    return body, missing + warnings


def to_fhir(scale: dict) -> dict:
    def item(it):
        t = it.get("type", "choice")
        d = {"linkId": str(it["n"]), "text": it["text"], "required": it.get("required", True)}
        if t == "number":
            d["type"] = "decimal"
            d["extension"] = [{"url": MIN_EXT, "valueDecimal": it.get("min", 0)}, {"url": MAX_EXT, "valueDecimal": it.get("max", 0)}]
        else:
            d["type"] = "choice"
            d["answerOption"] = [{"valueCoding": {"code": str(o["value"]), "display": o["label"]},
                                  "extension": [{"url": ORDINAL_EXT[0], "valueDecimal": o["value"]}]} for o in it.get("options", [])]
        return d
    return {
        "resourceType": "Questionnaire", "id": scale["code"].lower(), "name": scale["code"], "title": scale["title"],
        "status": "active", "description": scale.get("period"), "copyright": scale.get("license"),
        "item": [item(it) for it in scale["items"]],
    }


def from_csv(text: str, code: str, title: str) -> tuple[dict, list[str]]:
    """Таблица: n; text; options — варианты «0=Ни разу|1=Несколько дней|…».
    Разделитель — «;» или «,»; первая строка — заголовок."""
    sample = text[:2000]
    dialect = csv.Sniffer().sniff(sample, delimiters=";,") if sample else csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows or not {"n", "text", "options"} <= set(k.strip().lower() for k in rows[0]):
        raise ValueError("Нужны колонки: n, text, options (варианты «0=Ни разу|1=Несколько дней»)")
    items, warnings = [], []
    for r in rows:
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items()}
        opts = []
        for part in filter(None, r["options"].split("|")):
            if "=" not in part:
                warnings.append(f"Пункт {r['n']}: вариант «{part}» без балла — пропущен")
                continue
            v, label = part.split("=", 1)
            try:
                opts.append({"value": float(v) if "." in v else int(v), "label": label.strip()})
            except ValueError:
                warnings.append(f"Пункт {r['n']}: балл «{v}» не число — пропущен")
        items.append({"n": int(r["n"]), "text": r["text"], "options": opts})
    body = {"code": _code(code), "title": title, "respondent": "patient", "license": "", "validation": [],
            "verified": False, "items": items, "scoring": {"method": "sum"}, "bands": []}
    return body, ["bands — градации баллов", "validation — публикация валидации", "license — условия использования"] + warnings
