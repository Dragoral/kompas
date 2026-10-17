"""Конфигурация — только через переменные окружения (12-factor). В production
сервер не стартует с небезопасными настройками: список проблем выводится в лог
и процесс завершается с понятным сообщением."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"

APP_ENV = os.getenv("APP_ENV", "development")  # development | production
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'data' / 'app.db').as_posix()}")
ESCALATION_CHECK_SEC = int(os.getenv("ESCALATION_CHECK_SEC", "20"))
CORS_ORIGINS = [o for o in os.getenv("CORS_ORIGINS", "*").split(",") if o]
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "data" / "logs"))
DOCS_ENABLED = os.getenv("DOCS_ENABLED", "1" if APP_ENV != "production" else "0") == "1"
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", str(2 * 1024 * 1024)))

# LLM для извлечения данных из историй болезни. Пусто — работает только
# детерминированный экстрактор (всё локально, данные никуда не уходят).
LLM_URL = os.getenv("LLM_URL", "")          # OpenAI-совместимый endpoint, напр. Ollama http://localhost:11434/v1
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")


def production_problems() -> list[str]:
    """Небезопасные настройки, с которыми production-стенд не должен работать."""
    if APP_ENV != "production":
        return []
    p = []
    if not os.getenv("MASTER_KEYS"):
        p.append("MASTER_KEYS не задан (мастер-ключ шифрования должен приходить из окружения/KMS, не из файла)")
    if DATABASE_URL.startswith("sqlite"):
        p.append("DATABASE_URL: для production используйте PostgreSQL")
    if "*" in CORS_ORIGINS:
        p.append("CORS_ORIGINS='*' — укажите адрес(а) интерфейса")
    if os.getenv("DEMO_PASSWORD", "Kompas-demo-2026") == "Kompas-demo-2026":
        p.append("DEMO_PASSWORD по умолчанию — задайте собственный или не загружайте демо-данные")
    if os.getenv("REQUIRE_MFA", "0") != "1":
        p.append("REQUIRE_MFA=1 — второй фактор для врачей и администраторов обязателен")
    return p
