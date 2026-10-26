"""Модель данных.

* Прямые идентификаторы пациента (ФИО, дата рождения, контакты) и любой
  свободный текст хранятся только в зашифрованном виде (поля *_enc, AES-256-GCM,
  ключ на пациента — см. crypto.py). Доступ к ним — через дескриптор Sealed.
* Структурированные клинические данные (баллы шкал, коды МКБ, дозы) хранятся
  псевдонимизированно (связь с личностью — только через patient_id), чтобы
  работали выборки, фильтры и аналитика.
* Гибкие атрибуты — в JSON-колонках: модель расширяется без миграций.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, object_session

from .crypto import vault
from .db import Base, SessionLocal


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC: одинаково для SQLite и PostgreSQL


class Sealed:
    """Прозрачное шифрование поля ключом пациента.

    Шифртекст привязан (AAD) к таблице, полю и пациенту. Объект должен быть
    добавлен в сессию до присваивания значения.
    """

    def __init__(self, column: str, patient_attr: str = "patient_id"):
        self.column, self.patient_attr = column, patient_attr

    def __set_name__(self, owner, name):
        self.name = name

    def _ctx(self, obj):
        field = f"{type(obj).__tablename__}.{self.name}"
        return field, getattr(obj, self.patient_attr)

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        token = getattr(obj, self.column)
        if token is None:
            return None
        field, pid = self._ctx(obj)
        sess = object_session(obj)
        if sess is not None:
            return vault.open(sess, pid, field, token)
        with SessionLocal() as s:
            return vault.open(s, pid, field, token)

    def __set__(self, obj, value):
        sess = object_session(obj)
        if sess is None:
            raise RuntimeError(f"{self.name}: объект нужно добавить в сессию до записи защищённого поля")
        if getattr(obj, self.patient_attr) is None:
            sess.flush()
        field, pid = self._ctx(obj)
        setattr(obj, self.column, vault.seal(sess, pid, field, value))


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))  # Argon2id
    role: Mapped[str] = mapped_column(String(16), index=True)  # patient | doctor | admin
    full_name: Mapped[str] = mapped_column(String(128))  # ФИО сотрудника (публичная информация по 193н п. 37)
    specialty: Mapped[str | None] = mapped_column(String(32))  # psychiatrist | therapist | neurologist ...
    frmr_id: Mapped[str | None] = mapped_column(String(32))  # Федеральный регистр медработников (193н п. 9)
    is_duty: Mapped[bool] = mapped_column(Boolean, default=False)  # дежурный врач: экстренное реагирование (193н п. 44)
    is_reviewer: Mapped[bool] = mapped_column(Boolean, default=False)  # клинический рецензент изменений справочников
    # Рабочие часы для экстренных уведомлений: {"days": [1..7], "start": "09:00", "end": "18:00"}; None — по политике клиники
    working_hours: Mapped[dict | None] = mapped_column(JSON)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)  # 2FA, зашифрован ключом приложения
    totp_last_step: Mapped[int | None] = mapped_column(Integer)  # исключает повтор кода в том же временном окне
    phone_enc: Mapped[str | None] = mapped_column(Text)  # для экстренных SMS, зашифрован ключом приложения
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    password_changed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    @property
    def totp_secret(self) -> str | None:
        return vault.open_app("users.totp", self.totp_secret_enc) if self.totp_secret_enc else None

    @totp_secret.setter
    def totp_secret(self, v: str | None):
        self.totp_secret_enc = vault.seal_app("users.totp", v) if v else None

    @property
    def phone(self) -> str | None:
        return vault.open_app("users.phone", self.phone_enc) if self.phone_enc else None

    @phone.setter
    def phone(self, v: str | None):
        self.phone_enc = vault.seal_app("users.phone", v) if v else None


class AuthSession(Base):
    """Сессия: в БД только SHA-256 от 256-битного токена — утечка БД не даёт войти."""
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    mfa_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    user_agent: Mapped[str | None] = mapped_column(String(256))
    ip: Mapped[str | None] = mapped_column(String(64))


class PatientKey(Base):
    """Обёрнутый ключ данных пациента. wrapped_dek = NULL — ключ уничтожен (крипто-шреддинг)."""
    __tablename__ = "patient_keys"
    patient_id: Mapped[int] = mapped_column(primary_key=True)
    wrapped_dek: Mapped[str | None] = mapped_column(Text)
    kek_id: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    destroyed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)  # псевдоним для отчётов/выгрузок
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)  # ведущий лечащий врач

    full_name_enc: Mapped[str | None] = mapped_column(Text)
    birth_date_enc: Mapped[str | None] = mapped_column(Text)
    contacts_enc: Mapped[str | None] = mapped_column(Text)  # JSON: телефон, экстренный контакт
    name_bidx: Mapped[str | None] = mapped_column(String(64), index=True)  # слепой индекс для поиска
    full_name = Sealed("full_name_enc", "id")
    _birth_date = Sealed("birth_date_enc", "id")
    contacts = Sealed("contacts_enc", "id")

    sex: Mapped[str] = mapped_column(String(1))  # m | f
    # Клинический профиль: pregnant, lactating, egfr, child_pugh, conditions[], allergies[],
    # post_covid, drives_professionally, alcohol_use
    profile: Mapped[dict] = mapped_column(JSON, default=dict)
    diagnoses: Mapped[list] = mapped_column(JSON, default=list)      # [{icd10, title, primary}]
    current_meds: Mapped[list] = mapped_column(JSON, default=list)   # [{name, inn, classes[], dose, since}]
    # Предшествующие курсы: [{inn, dose, weeks, outcome: response|partial|no_response|intolerance}]
    # — по ним определяется этап терапии по КР
    therapy_history: Mapped[list] = mapped_column(JSON, default=list)
    maoi_stopped_at: Mapped[date | None] = mapped_column(Date)
    alert_thresholds: Mapped[dict] = mapped_column(JSON, default=dict)  # индивидуальные пороги (193н п. 46 «и»)

    # Очный приём — условие дистанционного наблюдения и коррекции терапии (193н п. 38, 43)
    in_person_visit_at: Mapped[datetime | None] = mapped_column(DateTime)
    diagnosis_confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    monitoring_active: Mapped[bool] = mapped_column(Boolean, default=False)
    diary_reminded_on: Mapped[date | None] = mapped_column(Date)  # push-напоминание о дневнике отправлено в этот день

    # Согласие на обработку ПДн — отдельный документ (152-ФЗ ст. 9 ред. 156-ФЗ, ст. 10)
    consent_version: Mapped[str | None] = mapped_column(String(16))
    consent_text_sha256: Mapped[str | None] = mapped_column(String(64))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime)
    consent_withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime)
    erase_after: Mapped[datetime | None] = mapped_column(DateTime)  # срок уничтожения после отзыва (≤ 30 дней)
    erased_at: Mapped[datetime | None] = mapped_column(DateTime)

    risk_score: Mapped[int] = mapped_column(Integer, default=0, index=True)  # автотриаж списка
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    @property
    def birth_date(self) -> date | None:
        v = self._birth_date
        return date.fromisoformat(v) if v and v[0].isdigit() else None

    @birth_date.setter
    def birth_date(self, v: date):
        self._birth_date = v.isoformat()


class PatientReassignmentRequest(Base):
    """Two-person control for reassignment of a patient's treating doctor."""
    __tablename__ = "patient_reassignment_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    from_doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    to_doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decision_comment: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    drug_id: Mapped[str] = mapped_column(String(64))
    indication_id: Mapped[str | None] = mapped_column(String(64))
    regimen: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | paused | stopped
    off_label: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale_enc: Mapped[str | None] = mapped_column(Text)
    rationale = Sealed("rationale_enc")
    mode: Mapped[str] = mapped_column(String(16), default="in_person")  # in_person | remote (коррекция)
    confirmed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime)


class ScaleResult(Base):
    __tablename__ = "scale_results"
    __table_args__ = (UniqueConstraint("patient_id", "client_id"), Index("ix_scale_patient_code_time", "patient_id", "scale_code", "created_at"))
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    scale_code: Mapped[str] = mapped_column(String(32))
    scale_version: Mapped[int] = mapped_column(Integer, default=1)
    answers: Mapped[dict] = mapped_column(JSON)  # {"1": 2, "2": 0, ...}
    score: Mapped[float] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSON, default=dict)  # подшкалы, критические пункты
    band: Mapped[str] = mapped_column(String(64))
    severity: Mapped[int] = mapped_column(Integer)
    respondent: Mapped[str] = mapped_column(String(16))  # patient | clinician
    entered_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    client_id: Mapped[str | None] = mapped_column(String(64))  # идемпотентность офлайн-очереди
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now)  # документирование получения (193н п. 46 «д»)


class ScaleAssignment(Base):
    __tablename__ = "scale_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    scale_code: Mapped[str] = mapped_column(String(32))
    every_days: Mapped[int | None] = mapped_column(Integer)  # None — разово
    next_due: Mapped[date] = mapped_column(Date)
    reminded_on: Mapped[date | None] = mapped_column(Date)  # push-напоминание о шкале отправлено в этот день
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str | None] = mapped_column(String(256))


class DiaryEntry(Base):
    __tablename__ = "diary_entries"
    __table_args__ = (UniqueConstraint("patient_id", "client_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    mood: Mapped[int | None] = mapped_column(Integer)      # 0–10
    anxiety: Mapped[int | None] = mapped_column(Integer)   # 0–10
    sleep_hours: Mapped[float | None] = mapped_column(Float)
    sleep_quality: Mapped[int | None] = mapped_column(Integer)  # 0–10
    note_enc: Mapped[str | None] = mapped_column(Text)
    note = Sealed("note_enc")
    client_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class DoseLog(Base):
    __tablename__ = "dose_logs"
    __table_args__ = (UniqueConstraint("patient_id", "client_id"), Index("ix_dose_patient_time", "patient_id", "scheduled_for"))
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"))
    prescription_id: Mapped[int] = mapped_column(ForeignKey("prescriptions.id"))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16))  # pending | taken | skipped
    taken_at: Mapped[datetime | None] = mapped_column(DateTime)
    client_id: Mapped[str | None] = mapped_column(String(64))
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime)  # push-напоминание о приёме отправлено


class AdverseEvent(Base):
    __tablename__ = "adverse_events"
    __table_args__ = (UniqueConstraint("patient_id", "client_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    prescription_id: Mapped[int | None] = mapped_column(ForeignKey("prescriptions.id"))
    title: Mapped[str] = mapped_column(String(128))
    intensity: Mapped[str] = mapped_column(String(16))  # mild | moderate | severe
    serious: Mapped[bool] = mapped_column(Boolean, default=False)
    life_threatening: Mapped[bool] = mapped_column(Boolean, default=False)
    expected: Mapped[bool | None] = mapped_column(Boolean)  # описана в инструкции (подтверждает врач)
    analysis: Mapped[dict | None] = mapped_column(JSON)  # термины, совпадения с инструкциями, тревожные признаки
    description_enc: Mapped[str | None] = mapped_column(Text)
    description = Sealed("description_enc")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | reviewed
    client_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Message(Base):
    """Сопутствующие материалы (193н п. 34, 51): хранятся 1 год."""
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("patient_id", "client_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    sender_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    sender_role: Mapped[str] = mapped_column(String(16))
    text_enc: Mapped[str | None] = mapped_column(Text)
    text = Sealed("text_enc")
    client_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    rule_id: Mapped[str] = mapped_column(String(64))
    rules_version: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(256))
    message_enc: Mapped[str | None] = mapped_column(Text)  # может цитировать текст пациента
    message = Sealed("message_enc")
    source: Mapped[str | None] = mapped_column(Text)
    actions: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)  # new | acknowledged | resolved
    escalate_after_min: Mapped[int | None] = mapped_column(Integer)
    escalated_to: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime)
    trigger_ref: Mapped[str | None] = mapped_column(String(64))
    # Документирование передачи и получения (193н п. 46 «д») и метрика времени доставки
    data_received_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    acknowledged_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    resolution_enc: Mapped[str | None] = mapped_column(Text)
    resolution = Sealed("resolution_enc")
    notified: Mapped[list] = mapped_column(JSON, default=list)  # маршрут экстренного оповещения


class ClinicalAction(Base):
    """Очередь действий, предложенных системой. Ничего не исполняется без решения врача."""
    __tablename__ = "clinical_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # referral | visit | hold_therapy | pv_report
    level: Mapped[str | None] = mapped_column(String(16))  # mandatory | desirable (направления)
    title: Mapped[str] = mapped_column(String(256))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # только структурированные данные, без свободного текста
    sources: Mapped[list] = mapped_column(JSON, default=list)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime)  # напр. срок извещения о НР
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)  # proposed | confirmed | rejected
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    comment_enc: Mapped[str | None] = mapped_column(Text)
    comment = Sealed("comment_enc")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    filename: Mapped[str] = mapped_column(String(256))
    text_enc: Mapped[str | None] = mapped_column(Text)
    text = Sealed("text_enc")
    extracted: Mapped[dict] = mapped_column(JSON, default=dict)  # структурированные клинические поля
    extractor: Mapped[str] = mapped_column(String(32))
    extraction_ms: Mapped[int | None] = mapped_column(Integer)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class KnowledgeItem(Base):
    """Справочники (шкалы, препараты, наборы правил) — меняются без изменения ядра."""
    __tablename__ = "knowledge"
    __table_args__ = (UniqueConstraint("kind", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # scale | drug | rules | dictionary
    code: Mapped[str] = mapped_column(String(64))
    body: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditLog(Base):
    """Журнал событий. Записи сцепляются SHA-256 (hash = H(prev_hash || запись))
    последовательным «запечатывателем» — любая правка/удаление задним числом
    обнаруживается проверкой цепочки. Свободный текст и ПДн сюда не пишутся."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    patient_id: Mapped[int | None] = mapped_column(Integer, index=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    prev_hash: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str | None] = mapped_column(String(64), index=True)


class Event(Base):
    """Очередь событий реального времени (transactional outbox), см. bus.py."""
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_channel_id", "channel", "id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict] = mapped_column(JSON)  # только идентификаторы и служебные поля, без свободного текста
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)


class StreamTicket(Base):
    """Одноразовый тикет на подключение к SSE (60 с); хранится хеш."""
    __tablename__ = "stream_tickets"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Lease(Base):
    """Аренда фоновой задачи: при нескольких процессах её выполняет только один."""
    __tablename__ = "leases"
    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    holder: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class KnowledgeVersion(Base):
    """История версий справочников и клиническое одобрение изменений.
    Изменение вступает в силу только после одобрения врачом-рецензентом,
    который не является автором изменения (принцип «четырёх глаз»)."""
    __tablename__ = "knowledge_versions"
    __table_args__ = (Index("ix_kv_item", "kind", "code", "version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    code: Mapped[str] = mapped_column(String(64))
    version: Mapped[int | None] = mapped_column(Integer)  # присваивается при одобрении
    body: Mapped[dict] = mapped_column(JSON)
    body_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)  # draft | approved | rejected | superseded
    change_note: Mapped[str | None] = mapped_column(Text)
    proposed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # None — загрузка из репозитория
    proposed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_comment: Mapped[str | None] = mapped_column(Text)


class Visit(Base):
    """Визит: очный приём, телемедицинская консультация или отложенная консультация (193н п. 15)."""
    __tablename__ = "visits"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(16))  # in_person | telemedicine | async
    at: Mapped[datetime] = mapped_column(DateTime, default=now)
    reason: Mapped[str | None] = mapped_column(String(256))
    notes_enc: Mapped[str | None] = mapped_column(Text)
    notes = Sealed("notes_enc")
    plan: Mapped[dict] = mapped_column(JSON, default=dict)  # структурированный план: следующий визит, шкалы, задачи
    next_visit_at: Mapped[datetime | None] = mapped_column(DateTime)


class PushSubscription(Base):
    """Подписка браузера/установленного приложения на Web Push (RFC 8030). Создаётся по явному
    действию пользователя; ключи шифрования содержимого — от браузера (RFC 8291)."""
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(1024), unique=True)
    p256dh: Mapped[str] = mapped_column(String(128))
    auth: Mapped[str] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)


class Notification(Base):
    """Внешние уведомления (SMS/звонок) по критическим алертам. Документирование
    отправки и доставки — 193н п. 46 «д». Текст без медицинских сведений (3185-1 ст. 9)."""
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    trusted_contact_id: Mapped[int | None] = mapped_column(ForeignKey("trusted_contacts.id"))
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))  # sms | call | push
    reason: Mapped[str | None] = mapped_column(String(64))  # attending | duty | escalation | trusted_contact
    text: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | sent | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(32))
    provider_id: Mapped[str | None] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class TrustedContact(Base):
    """Доверенное лицо пациента, которому при экстренной ситуации можно сообщить, что пациенту
    нужна поддержка. Только с отдельного письменного согласия пациента (323-ФЗ ст. 13 ч. 3,
    ст. 22 ч. 3; 152-ФЗ ст. 9). Сообщение не содержит диагноза и медицинских сведений."""
    __tablename__ = "trusted_contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    name_enc: Mapped[str | None] = mapped_column(Text)
    name = Sealed("name_enc")
    phone_enc: Mapped[str | None] = mapped_column(Text)
    phone = Sealed("phone_enc")
    relation: Mapped[str | None] = mapped_column(String(32))
    consent_version: Mapped[str] = mapped_column(String(16))
    consent_text_sha256: Mapped[str] = mapped_column(String(64))
    consent_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
