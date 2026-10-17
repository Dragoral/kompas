"""Извлечение ключевых сведений из историй болезни произвольного шаблона.

Не опирается на порядок и названия разделов: ищет сущности по всему тексту
с учётом русской морфологии (по основе слова) и отрицаний («отрицает»,
«не выявлено», «без …»). Результат — черновик, который врач проверяет и
переносит в карточку (/documents/{id}/apply).

Опционально (LLM_URL) результат дополняется локальной LLM через
OpenAI-совместимый API; данные не покидают контур. При ошибке LLM остаётся
детерминированный результат.
"""
from __future__ import annotations

import json
import re
import time

from ..config import LLM_API_KEY, LLM_MODEL, LLM_URL

ICD = re.compile(r"\b([A-ZА-Я])\s?(\d{2})(?:\s?\.\s?(\d{1,2}))?\b")
_LAT = str.maketrans("АВЕКМНОРСТХ", "ABEKMHOPCTX")  # кириллица, похожая на латиницу в кодах МКБ

# Диагнозы, записанные словами (без кода МКБ)
DX_TEXT = [
    (r"смешанн\w*\s+тревожн\w*\s+и\s+депрессивн\w*", "F41.2", "Смешанное тревожное и депрессивное расстройство"),
    (r"генерализ\w*\s+тревожн\w*\s+расстройств\w*|\bГТР\b", "F41.1", "Генерализованное тревожное расстройство"),
    (r"паническ\w*\s+расстройств\w*", "F41.0", "Паническое расстройство"),
    (r"рекуррентн\w*\s+депрессивн\w*", "F33", "Рекуррентное депрессивное расстройство"),
    (r"тяж[её]л\w*\s+депрессивн\w*\s+эпизод\w*", "F32.2", "Тяжёлый депрессивный эпизод"),
    (r"депрессивн\w*\s+эпизод\w*\s+средн\w*|умеренн\w*\s+депрессивн\w*\s+эпизод\w*", "F32.1", "Депрессивный эпизод средней степени"),
    (r"л[её]гк\w*\s+депрессивн\w*\s+эпизод\w*|депрессивн\w*\s+эпизод\w*\s+л[её]гк\w*", "F32.0", "Лёгкий депрессивный эпизод"),
    (r"депрессивн\w*\s+эпизод\w*", "F32.9", "Депрессивный эпизод"),
    (r"посттравматическ\w*\s+стрессов\w*|\bПТСР\b", "F43.1", "Посттравматическое стрессовое расстройство"),
    (r"(?:расстройств\w*|нарушени\w*)\s+адаптаци\w*", "F43.2", "Расстройство адаптации"),
    (r"остр\w*\s+реакци\w*\s+на\s+стресс", "F43.0", "Острая реакция на стресс"),
    (r"гипертоническ\w*\s+болезн\w*|артериальн\w*\s+гипертензи\w*", "I10", "Артериальная гипертензия"),
    (r"сахарн\w*\s+диабет\w*\s*(?:2|II|второго)", "E11", "Сахарный диабет 2 типа"),
    (r"ишемическ\w*\s+болезн\w*\s+сердца|\bИБС\b", "I25", "Ишемическая болезнь сердца"),
    (r"гипотиреоз\w*", "E03", "Гипотиреоз"),
    (r"эпилепси\w*", "G40", "Эпилепсия"),
    (r"хроническ\w*\s+болезн\w*\s+почек|\bХБП\b", "N18", "Хроническая болезнь почек"),
]

CONDITIONS = [
    (r"эпилепси\w*|судорожн\w*\s+синдром", "epilepsy"),
    (r"органическ\w*\s+(?:поражени\w*|заболевани\w*|расстройств\w*)|черепно-мозгов\w*\s+травм\w*|\bЧМТ\b|инсульт\w*|\bОНМК\b", "organic_brain_disease"),
    (r"\bИБС\b|ишемическ\w*\s+болезн\w*|инфаркт\w*|гипертони\w*|гипертензи\w*|аритми\w*|фибрилляци\w*|сердечн\w*\s+недостаточн\w*", "cardiovascular"),
    (r"сахарн\w*\s+диабет\w*", "diabetes"),
    (r"гипотиреоз\w*|гипертиреоз\w*|тиреоидит\w*|эндокрин\w*\s+заболевани\w*", "endocrine"),
    (r"(?:синдром\w*\s+)?зависимост\w*\s+от\s+алкогол\w*|алкогольн\w*\s+зависимост\w*|алкоголизм\w*", "alcohol_dependence"),
    (r"зависимост\w*\s+от\s+(?:опиоид|каннабино|психоактивн|ПАВ)\w*|наркотическ\w*\s+зависимост\w*", "substance_dependence"),
    (r"биполярн\w*", "bipolar"),
    (r"маниакальн\w*\s+эпизод\w*|гипомани\w*", "mania_history"),
    (r"галлюцинац\w*|бредов\w*|\bбред\w*|психотическ\w*\s+симптом\w*", "psychotic_symptoms"),
    (r"удлинени\w*\s+(?:интервала\s+)?QT", "long_qt"),
]

NEG = re.compile(r"(?:\bне\s+(?:выявлен|отмечает|отмечалось|было|обнаружен|наблюдал)\w*|\bнет\b|\bбез\b|\bотрица\w*|\bисключен\w*|\bне\s+страда\w*)", re.I)

DOSE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(мг|мкг|г)\b", re.I)
FREQ = [
    (re.compile(r"(\d)\s*р(?:аза|аз)?\.?\s*(?:в|/)\s*(?:сут|день|д)", re.I), lambda m: int(m.group(1))),
    (re.compile(r"[xх×]\s*(\d)\s*р", re.I), lambda m: int(m.group(1))),
    (re.compile(r"утром\s+и\s+вечером|дважды", re.I), lambda m: 2),
    (re.compile(r"однократно|1\s*р/сут|на\s+ночь|утром\b", re.I), lambda m: 1),
]

SCALES = {
    "PHQ9": re.compile(r"PHQ[\s-]?9\D{0,15}?(\d{1,2})\b", re.I),
    "GAD7": re.compile(r"GAD[\s-]?7\D{0,15}?(\d{1,2})\b", re.I),
    "HAMA": re.compile(r"(?:HAM[\s-]?A|HARS|SIGH[\s-]?A|шкал\w*\s+(?:тревоги\s+)?Гамильтона\s+(?:для\s+оценки\s+)?тревоги)\D{0,15}?(\d{1,2})\b", re.I),
}


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?;\n])\s+", text) if s.strip()]


def _negated(sentence: str, start: int) -> bool:
    """Есть ли отрицание перед упоминанием в пределах той же клаузы."""
    clause = re.split(r"[,:]", sentence[:start])[-1]
    return bool(NEG.search(clause))


def _find_all(pattern: str, text: str):
    for s in _sentences(text):
        for m in re.finditer(pattern, s, re.I):
            yield s, m


def extract_rules(text: str, kb: dict) -> dict:
    out: dict = {"diagnoses": [], "medications": [], "allergies": [], "conditions": [], "scales": {},
                 "egfr": None, "child_pugh": None, "pregnant": None, "lactating": None, "post_covid": None, "sex": None, "age": None}

    # Диагнозы по кодам МКБ-10
    seen = set()
    for s in _sentences(text):
        for m in ICD.finditer(s):
            letter = m.group(1).translate(_LAT)
            if letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                continue
            code = f"{letter}{m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")
            if code in seen or _negated(s, m.start()):
                continue
            seen.add(code)
            title = re.sub(r"^[\s:—–-]+", "", s[m.end():m.end() + 120]).split(".")[0].split(";")[0].strip(" ()")
            out["diagnoses"].append({"icd10": code, "title": title[:120] or code, "source": "code"})
    # Диагнозы словами — если кода с той же рубрикой нет
    for pattern, code, title in DX_TEXT:
        for s, m in _find_all(pattern, text):
            if _negated(s, m.start()):
                continue
            if not any(d["icd10"].startswith(code[:3]) for d in out["diagnoses"]):
                out["diagnoses"].append({"icd10": code, "title": title, "source": "text"})
            break
    if out["diagnoses"]:
        psych = [d for d in out["diagnoses"] if d["icd10"].startswith("F")]
        (psych or out["diagnoses"])[0]["primary"] = True

    # Препараты (по основе слова: «сертралина», «сертралином») + доза и кратность рядом
    names = kb.get("name_index", {})
    meds: dict[str, dict] = {}
    allergy_text = " ".join(s for s in _sentences(text) if re.search(r"аллерг|непереносим", s, re.I))
    for name, inn in sorted(names.items(), key=lambda x: -len(x[0])):
        stem = re.escape(name[:-1] if len(name) > 6 else name)
        for s, m in _find_all(rf"\b{stem}\w*", text):
            if s in allergy_text:
                continue
            if inn in meds:
                break
            tail = s[m.end():m.end() + 60]
            dose = DOSE.search(tail)
            freq = next((f(mm) for rx, f in FREQ if (mm := rx.search(tail))), None)
            cancelled = bool(re.search(r"отмен\w*|прекращ\w*|ранее\s+принимал|в\s+анамнезе", s[max(0, m.start() - 40):m.end() + 40], re.I))
            meds[inn] = {"name": m.group(0), "inn": inn, "dose": f"{dose.group(1)} {dose.group(2)}" if dose else None,
                         "times_per_day": freq, "current": not cancelled}
            break
    out["medications"] = [m for m in meds.values() if m["current"]]
    out["past_medications"] = [m for m in meds.values() if not m["current"]]

    # Аллергии
    if allergy_text and not re.search(r"(?:не\s+отягощ|отрица|нет\b|не\s+выявлен)", allergy_text, re.I):
        for name, inn in names.items():
            if re.search(rf"\b{re.escape(name[:-1] if len(name) > 6 else name)}\w*", allergy_text, re.I):
                out["allergies"].append("maritupirdine_allergy" if inn == "маритупирдин" else inn)
        for m in re.finditer(r"(пенициллин\w*|сульфаниламид\w*|лактоз\w*|йод\w*)", allergy_text, re.I):
            out["allergies"].append(m.group(1).lower())
        out["allergies"] = sorted(set(out["allergies"]))

    # Состояния, влияющие на противопоказания и маршрутизацию
    conds = set()
    for pattern, tag in CONDITIONS:
        for s, m in _find_all(pattern, text):
            if not _negated(s, m.start()):
                conds.add(tag)
                break
    out["conditions"] = sorted(conds)

    if (m := re.search(r"(?:СКФ|eGFR|скорость\s+клубочковой\s+фильтрации)\D{0,20}?(\d{1,3})", text, re.I)):
        out["egfr"] = int(m.group(1))
    if (m := re.search(r"Чайлд[\s-]*Пью\D{0,15}?([ABCАВС])\b", text, re.I)):
        out["child_pugh"] = m.group(1).upper().translate(_LAT)
    for s, m in _find_all(r"беременн\w*", text):
        out["pregnant"] = not _negated(s, m.start()) and not re.search(r"планир", s, re.I)
        break
    for s, m in _find_all(r"грудн\w*\s+вскармлив\w*|лактаци\w*", text):
        out["lactating"] = not _negated(s, m.start())
        break
    for s, m in _find_all(r"COVID|коронавирус\w*|ковид\w*|SARS-CoV-2", text):
        out["post_covid"] = not _negated(s, m.start())
        break

    for code, rx in SCALES.items():
        if (m := rx.search(text)):
            out["scales"][code] = int(m.group(1))
    if (m := re.search(r"\bпол\s*[:—-]?\s*(муж|жен)", text, re.I)):
        out["sex"] = "m" if m.group(1).lower().startswith("м") else "f"
    elif re.search(r"\bпациентк\w*", text, re.I):
        out["sex"] = "f"
    elif re.search(r"\bпациент\b", text, re.I):
        out["sex"] = "m"
    if (m := re.search(r"(?:возраст\s*[:—-]?\s*|\b)(\d{2})\s*(?:лет|год)", text, re.I)):
        out["age"] = int(m.group(1))
    return out


def extract_llm(text: str) -> dict | None:
    if not LLM_URL:
        return None
    import httpx
    prompt = ("Извлеки из истории болезни JSON с полями: diagnoses [{icd10, title}], medications [{name, dose, times_per_day}], "
              "allergies [строки], conditions [теги из: epilepsy, organic_brain_disease, cardiovascular, diabetes, endocrine, "
              "alcohol_dependence, substance_dependence, bipolar, psychotic_symptoms, long_qt], egfr (число|null), pregnant (bool|null), "
              "post_covid (bool|null). Учитывай отрицания. Только JSON.")
    try:
        r = httpx.post(f"{LLM_URL.rstrip('/')}/chat/completions", timeout=60,
                       headers={"Authorization": f"Bearer {LLM_API_KEY}"} if LLM_API_KEY else {},
                       json={"model": LLM_MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                             "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": text[:20000]}]})
        r.raise_for_status()
        return json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception:
        return None


def extract(text: str, kb: dict) -> dict:
    t0 = time.perf_counter()
    data = extract_rules(text, kb)
    extractor = "rules"
    llm = extract_llm(text)
    if llm:
        extractor = "rules+llm"
        codes = {d["icd10"] for d in data["diagnoses"]}
        for d in llm.get("diagnoses") or []:
            if isinstance(d, dict) and d.get("icd10") and d["icd10"] not in codes:
                data["diagnoses"].append({"icd10": d["icd10"], "title": d.get("title", ""), "source": "llm"})
        for k in ("conditions", "allergies"):
            data[k] = sorted(set(data[k]) | {x for x in llm.get(k) or [] if isinstance(x, str)})
        for k in ("egfr", "pregnant", "post_covid"):
            if data.get(k) is None and llm.get(k) is not None:
                data[k] = llm[k]
    return {"data": data, "extractor": extractor, "elapsed_ms": round((time.perf_counter() - t0) * 1000)}
