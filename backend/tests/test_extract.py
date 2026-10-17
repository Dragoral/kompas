from app.db import SessionLocal
from app.engine import extract, knowledge

H1 = """ИСТОРИЯ БОЛЕЗНИ. Пациентка 34 лет.
Жалобы: постоянная тревога, напряжение, нарушение сна.
Диагноз основной: F41.1 Генерализованное тревожное расстройство.
Сопутствующие: Гипертоническая болезнь II ст.
Принимает: сертралин 50 мг 1 р/сут, амлодипин 5 мг утром.
Аллергологический анамнез не отягощён. Беременность отрицает.
GAD-7 = 15, PHQ-9: 8."""

H2 = """Пациент М., 58 лет. Анамнез: перенёс COVID-19 в марте, после чего — тревога, раздражительность.
Сопутствующие заболевания: сахарный диабет 2 типа, ХБП 3а (СКФ 48 мл/мин). Эпилепсии нет.
Терапия: метформин 1000 мг x2 р/д. Ранее принимал феназепам — отменён.
Аллергия: непереносимость пенициллина.
Заключение: расстройство адаптации, смешанная тревожно-депрессивная реакция."""

H3 = """Dx: F32.1; F41.1
Назначено: Авиандр по 20 мг утром и вечером.
Со слов: суицидальных мыслей не высказывает, бреда нет. Беременна (12 нед.)."""


def _kb():
    with SessionLocal() as db:
        return knowledge.get(db)


def test_extract_template_1(client):
    d = extract.extract(H1, _kb())["data"]
    assert [x["icd10"] for x in d["diagnoses"]][:1] == ["F41.1"]
    inns = {m["inn"]: m for m in d["medications"]}
    assert inns["сертралин"]["dose"] == "50 мг" and inns["сертралин"]["times_per_day"] == 1
    assert "амлодипин" in inns
    assert d["allergies"] == [] and d["pregnant"] is False
    assert "cardiovascular" in d["conditions"]
    assert d["scales"] == {"GAD7": 15, "PHQ9": 8}
    assert d["sex"] == "f" and d["age"] == 34


def test_extract_template_2_negation_and_history(client):
    d = extract.extract(H2, _kb())["data"]
    codes = {x["icd10"] for x in d["diagnoses"]}
    assert "F43.2" in codes and "E11" in codes
    assert d["egfr"] == 48 and d["post_covid"] is True
    assert "epilepsy" not in d["conditions"]  # «эпилепсии нет»
    assert "diabetes" in d["conditions"]
    assert {m["inn"] for m in d["medications"]} == {"метформин"}
    assert {m["inn"] for m in d["past_medications"]} == {"феназепам"}
    assert "пенициллина" in d["allergies"] or "пенициллин" in "".join(d["allergies"])


def test_extract_template_3_short(client):
    d = extract.extract(H3, _kb())["data"]
    assert [x["icd10"] for x in d["diagnoses"]] == ["F32.1", "F41.1"]
    av = d["medications"][0]
    assert av["inn"] == "маритупирдин" and av["times_per_day"] == 2
    assert "psychotic_symptoms" not in d["conditions"]
    assert d["pregnant"] is True
