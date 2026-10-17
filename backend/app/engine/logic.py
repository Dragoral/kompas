"""Минимальный безопасный интерпретатор JSON-logic.

Правила (алерты, маршрутизация, противопоказания) хранятся как данные, а не как
код, поэтому их можно добавлять и менять без изменения ядра. Никакого eval:
поддерживается только фиксированный набор операторов.

Отсутствующее значение (`None`) делает сравнение ложным — правило не срабатывает
на неполных данных, а не падает.
"""
from __future__ import annotations

import re
from typing import Any

_MISSING = None


def get_var(ctx: dict, path: str) -> Any:
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict):
            nxt = cur.get(part)
            if nxt is None and part.isdigit():
                nxt = cur.get(int(part))
            cur = nxt
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return _MISSING
        if cur is None:
            return _MISSING
    return cur


def _cmp(op, a, b):
    if a is None or b is None:
        return False
    try:
        return op(a, b)
    except TypeError:
        return False


_OPS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">": lambda a, b: _cmp(lambda x, y: x > y, a, b),
    ">=": lambda a, b: _cmp(lambda x, y: x >= y, a, b),
    "<": lambda a, b: _cmp(lambda x, y: x < y, a, b),
    "<=": lambda a, b: _cmp(lambda x, y: x <= y, a, b),
}


def evaluate(rule: Any, ctx: dict) -> Any:
    if not isinstance(rule, dict):
        if isinstance(rule, list):
            return [evaluate(r, ctx) for r in rule]
        return rule
    if len(rule) != 1:
        raise ValueError(f"JSON-logic: ожидался один оператор, получено {list(rule)}")
    op, args = next(iter(rule.items()))
    if op == "var":
        return get_var(ctx, args if isinstance(args, str) else args[0])
    if op == "and":
        return all(evaluate(a, ctx) for a in args)
    if op == "or":
        return any(evaluate(a, ctx) for a in args)
    if op in ("not", "!"):
        return not evaluate(args[0] if isinstance(args, list) else args, ctx)
    vals = [evaluate(a, ctx) for a in args]
    if op in _OPS:
        return _OPS[op](vals[0], vals[1])
    if op == "in":
        needle, hay = vals
        return hay is not None and needle is not None and needle in hay
    if op == "some_in":  # пересечение двух списков непусто
        a, b = vals
        return bool(a and b and set(a) & set(b))
    if op == "starts_any":  # какой-либо код из списка начинается с одного из префиксов (МКБ-10)
        prefixes, codes = vals
        return bool(prefixes and codes and any(str(c).startswith(p) for c in codes for p in prefixes))
    raise ValueError(f"JSON-logic: неизвестный оператор {op!r}")


def validate(rule: Any) -> None:
    """Проверка синтаксиса правила при загрузке/сохранении через админку."""
    evaluate(rule, {})


_TPL = re.compile(r"\{([a-zA-Z0-9_.]+)\}")


def render(template: str, ctx: dict) -> str:
    def sub(m):
        v = get_var(ctx, m.group(1))
        return "—" if v is None else str(v)
    return _TPL.sub(sub, template)


def safe_eval(rule: Any, ctx: dict, ref: str) -> bool:
    """Вычислить условие правила; при сбое — не ронять запрос: правило считается
    не сработавшим, проблема фиксируется для администратора."""
    try:
        return bool(evaluate(rule, ctx))
    except Exception as e:  # noqa: BLE001 — ошибка в данных справочника не должна ломать работу
        from ..observability import report_problem
        report_problem("rule", ref, f"{e.__class__.__name__}: {e}")
        return False


def explain(rule: Any, ctx: dict) -> dict:
    """Пошаговое объяснение вычисления условия: дерево {expr, value, args}.
    Нужно, чтобы врач видел, почему правило сработало или нет."""
    if not isinstance(rule, dict):
        return {"expr": rule, "value": rule}
    op, args = next(iter(rule.items()))
    if op == "var":
        path = args if isinstance(args, str) else args[0]
        return {"expr": f"переменная {path}", "value": get_var(ctx, path)}
    children = [explain(a, ctx) for a in (args if isinstance(args, list) else [args])]
    try:
        value = evaluate(rule, ctx)
    except Exception as e:  # noqa: BLE001
        value = f"ошибка: {e}"
    return {"expr": op, "value": value, "args": children}
