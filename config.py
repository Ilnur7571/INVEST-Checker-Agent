# import os
# import logging
# from dotenv import load_dotenv

# load_dotenv()
# logger = logging.getLogger("config")

# class Config:
#     TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
#     GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")
#     GIGACHAT_API_URL = os.getenv("GIGACHAT_API_URL")
#     MODEL_NAME = os.getenv("MODEL_NAME")
#     GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE")
#     SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", 0.78) or 0.78)
#     DISABLE_SSL_VERIFY = os.getenv("DISABLE_SSL_VERIFY", "false").lower() == "true"
#     CLIENT_ID = os.getenv("CLIENT_ID")
#     CLIENT_SECRET = os.getenv("CLIENT_SECRET")
#     GIGACHAT_AUTH_URL = os.getenv("GIGACHAT_AUTH_URL")

#     @classmethod
#     def validate(cls, strict: bool = True):
#         """Проверяем, что ключи из .env заданы"""
#         required_keys = [
#             "TELEGRAM_TOKEN",
#             "GIGACHAT_AUTH_KEY",
#             "GIGACHAT_API_URL",
#             "CLIENT_ID",
#             "CLIENT_SECRET",
#             "GIGACHAT_AUTH_URL"
#         ]

#         for key in required_keys:
#             if not getattr(cls, key):
#                 msg = f"[WARN] {key} не задан"
#                 if strict:
#                     raise ValueError(f"Отсутствует обязательный параметр {key}")
#                 else:
#                     logger.warning(msg)


# config.py
import os
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("config")

class Config:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    GIGACHAT_AUTH_KEY = os.getenv("GIGACHAT_AUTH_KEY")
    GIGACHAT_API_URL = os.getenv("GIGACHAT_API_URL")
    MODEL_NAME = os.getenv("MODEL_NAME")
    GIGACHAT_SCOPE = os.getenv("GIGACHAT_SCOPE")
    SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", 0.78) or 0.78)
    DISABLE_SSL_VERIFY = os.getenv("DISABLE_SSL_VERIFY", "false").lower() == "true"
    CLIENT_ID = os.getenv("CLIENT_ID")
    CLIENT_SECRET = os.getenv("CLIENT_SECRET")
    GIGACHAT_AUTH_URL = os.getenv("GIGACHAT_AUTH_URL")

    @classmethod
    def validate(cls, strict: bool = True):
        required_keys = [
            "TELEGRAM_TOKEN",
            "GIGACHAT_AUTH_KEY",
            "GIGACHAT_API_URL",
            "CLIENT_ID",
            "CLIENT_SECRET",
            "GIGACHAT_AUTH_URL"
        ]

        for key in required_keys:
            if not getattr(cls, key):
                msg = f"[WARN] {key} не задан"
                if strict:
                    raise ValueError(f"Отсутствует обязательный параметр {key}")
                else:
                    logger.warning(msg)
