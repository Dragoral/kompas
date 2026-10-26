"""CLI для первичной настройки «Клинического компаса»."""
from __future__ import annotations
import argparse
import getpass
import re
from sqlalchemy import select
from . import auth
from .db import Base, SessionLocal, engine
from .engine import knowledge
from .models import User

def create_admin(login: str, full_name: str) -> None:
    login = login.strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,64}", login):
        raise SystemExit("Логин: 3–64 символа a-z, цифры, точка, дефис или подчёркивание")
    full_name = full_name.strip()
    if not full_name or len(full_name) > 128:
        raise SystemExit("Укажите ФИО длиной до 128 символов")
    password = getpass.getpass("Новый пароль администратора: ")
    if password != getpass.getpass("Повторите пароль: "):
        raise SystemExit("Пароли не совпадают")
    auth.check_password_policy(password, login)
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.login == login)):
            raise SystemExit("Пользователь с таким логином уже существует")
        knowledge.seed(db)
        u = User(login=login, password_hash=auth.hash_password(password), role="admin", full_name=full_name,
                 active=True, is_reviewer=True)
        db.add(u)
        db.flush()
        auth.audit(db, u, "admin_created_cli", "user", u.id)
        db.commit()
        print(f"Создан администратор {login} (id={u.id}). Пароль не выводится.")

def main() -> None:
    parser = argparse.ArgumentParser(description="CLI администрирования «Клинического компаса»")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="создать администратора, не очищая базу")
    create.add_argument("--login", required=True)
    create.add_argument("--name", required=True)
    args = parser.parse_args()
    if args.command == "create-admin":
        create_admin(args.login, args.name)

if __name__ == "__main__":
    main()
