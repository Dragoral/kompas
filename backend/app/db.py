from pathlib import Path

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DATABASE_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    Path(DATABASE_URL.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    # Пул не меньше числа рабочих потоков сервера
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 15},
                           pool_size=50, max_overflow=50, pool_timeout=30)

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(conn, _):
        conn.isolation_level = None  # транзакциями управляем сами (см. _begin)
        cur = conn.cursor()
        # WAL + synchronous=NORMAL: подтверждённая запись переживает падение процесса
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    @event.listens_for(engine, "begin")
    def _begin(conn):
        # Пишущая транзакция сразу берёт блокировку записи и ждёт очереди (busy_timeout),
        # а не падает с «database is locked» при попытке повысить чтение до записи.
        conn.exec_driver_sql("BEGIN IMMEDIATE" if conn.get_execution_options().get("write") else "BEGIN")
else:
    engine = create_engine(DATABASE_URL, pool_size=20, max_overflow=20, pool_pre_ping=True)

SessionLocal = sessionmaker(engine, expire_on_commit=False)
WriteSession = sessionmaker(engine.execution_options(write=True), expire_on_commit=False)

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class Base(DeclarativeBase):
    pass


def defer_write(db: Session, fn) -> None:
    """Попутная запись в читающем запросе (журнал просмотра, «прочитано») —
    выполняется короткой отдельной транзакцией после основного запроса."""
    if db.info.get("write") is False:  # только читающие запросы API откладывают запись
        db.info.setdefault("deferred", []).append(fn)
    else:
        fn(db)


def run_deferred(db: Session) -> None:
    fns = db.info.pop("deferred", [])
    if not fns:
        return
    with WriteSession() as w:
        for fn in fns:
            fn(w)
        w.commit()


def get_db(request: Request):
    write = request.method in WRITE_METHODS
    db = (WriteSession if write else SessionLocal)()
    db.info["write"] = write
    try:
        yield db
    finally:
        try:
            if not write and db.in_transaction():
                db.rollback()  # читающая транзакция: снять снимок
            run_deferred(db)  # в т. ч. при ошибке/403: попытка доступа должна попасть в журнал
        finally:
            db.close()
