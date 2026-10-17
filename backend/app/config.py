import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'data' / 'app.db').as_posix()}")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_TTL_MIN = int(os.getenv("JWT_TTL_MIN", "720"))
ESCALATION_CHECK_SEC = int(os.getenv("ESCALATION_CHECK_SEC", "20"))
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# LLM для извлечения данных из историй болезни. Пусто — работает только
# детерминированный экстрактор (всё локально, данные никуда не уходят).
LLM_URL = os.getenv("LLM_URL", "")          # OpenAI-совместимый endpoint, напр. Ollama http://localhost:11434/v1
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:7b-instruct")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
