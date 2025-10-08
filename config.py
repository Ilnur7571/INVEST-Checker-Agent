import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("config")


class Config:
    """Конфигурация приложения"""

    # Telegram
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

    # GigaChat
    GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")
    CLIENT_ID = os.getenv("CLIENT_ID")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET")
    GIGACHAT_API_URL = os.getenv("GIGACHAT_API_URL", "https://gigachat.devices.sberbank.ru/api/v1")
    GIGACHAT_AUTH_URL = os.getenv("GIGACHAT_AUTH_URL", "https://ngw.devices.sberbank.ru:9443/api/v2/oauth")
    GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    MODEL_NAME = os.getenv("MODEL_NAME", "GigaChat")

    # Application
    SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.78"))
    DISABLE_SSL_VERIFY = os.getenv("DISABLE_SSL_VERIFY", "false").lower() == "true"
    DB_PATH = os.getenv("DB_PATH", "examples.db")

    @classmethod
    def validate(cls):
        """Валидация конфигурации"""
        if not cls.TELEGRAM_TOKEN:
            raise ValueError("TELEGRAM_TOKEN не найден в .env")

        if not cls.GIGACHAT_AUTH_KEY and not (cls.CLIENT_ID and cls.CLIENT_SECRET):
            raise ValueError("Необходимо указать либо GIGACHAT_AUTH_KEY, либо CLIENT_ID и CLIENT_SECRET")

        logger.info("Configuration validated successfully")

    @classmethod
    def get_auth_credentials(cls):
        """Получить credentials для аутентификации"""
        if cls.GIGACHAT_AUTH_KEY:
            return {"auth_key": cls.GIGACHAT_AUTH_KEY}
        elif cls.CLIENT_ID and cls.CLIENT_SECRET:
            return {
                "client_id": cls.CLIENT_ID,
                "client_secret": cls.CLIENT_SECRET
            }


# Валидация при импорте
Config.validate()