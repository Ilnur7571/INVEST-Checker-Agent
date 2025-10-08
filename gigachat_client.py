#import os
import time
import uuid
import base64
import requests
import urllib3
from requests.exceptions import RequestException
from config import Config

class GigaChatClient:
    def __init__(self):
        self.client_id = Config.CLIENT_ID
        self.client_secret = Config.CLIENT_SECRET
        self.auth_key = Config.GIGACHAT_AUTH_KEY
        self.scope = Config.GIGACHAT_SCOPE

        # Если auth_key не задан, формируем из client_id и client_secret
        if not self.auth_key and self.client_id and self.client_secret:
            raw = f"{self.client_id}:{self.client_secret}"
            self.auth_key = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
            print(f"DEBUG: Generated auth_key from credentials")

        if not self.auth_key:
            raise ValueError("Не удалось установить auth_key или client_id/secret")

        self.token_url = Config.GIGACHAT_AUTH_URL
        self.api_base = Config.GIGACHAT_API_URL

        # Отключаем SSL предупреждения если нужно
        if Config.DISABLE_SSL_VERIFY:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Токен и время жизни токена
        self._access_token = None
        self._token_expiry = 0

        print(f"DEBUG: GigaChatClient initialized with auth_url={self.token_url}")

    def get_token(self) -> str:
        now = time.time()
        # Возвращаем токен, если он ещё валиден (с запасом 60 секунд)
        if self._access_token and now < (self._token_expiry - 60):
            return self._access_token

        rq_uid = str(uuid.uuid4())
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": rq_uid,
            "Authorization": f"Basic {self.auth_key}"
        }
        payload = {"scope": self.scope}

        print(f"DEBUG: Requesting token from {self.token_url}")

        try:
            resp = requests.post(
                self.token_url,
                headers=headers,
                data=payload,
                verify=not Config.DISABLE_SSL_VERIFY
            )
            resp.raise_for_status()
        except RequestException as e:
            raise RuntimeError(f"Ошибка при запросе токена: {e}")

        j = resp.json()
        access = j.get("access_token")
        expires_at = j.get("expires_at")
        if not access or expires_at is None:
            raise RuntimeError(f"Неполный ответ токена: {j}")

        try:
            exp_int = int(expires_at)
            # Если таймстамп в миллисекундах, переводим в секунды
            if exp_int > 10**12:
                exp_ts = exp_int / 1000
            else:
                exp_ts = exp_int
        except Exception:
            exp_ts = now + 1800  # по умолчанию 30 минут

        self._access_token = access
        self._token_expiry = exp_ts

        print(f"DEBUG: Token obtained successfully, expires at {exp_ts}")
        return access

    def get_chat_completion(self, messages):
        """
        messages: список словарей вида {"role": ..., "content": ...}
        Возвращает (answer, messages)
        """
        token = self.get_token()
        url = f"{self.api_base}/api/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        print(f"DEBUG: Sending chat request to {url}")
        print(f"DEBUG: Messages: {messages}")

        try:
            resp = requests.post(
                url,
                headers=headers,
                json={
                    "model": Config.MODEL_NAME,
                    "messages": messages,
                    "temperature": 0.7
                },
                verify=not Config.DISABLE_SSL_VERIFY,
            )
            resp.raise_for_status()
        except RequestException as e:
            raise RuntimeError(f"Ошибка при chat_completion: {e}")

        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
        return answer, messages

    # gigachat_client.py (добавьте этот метод)
    def chat(self, messages):
        """Интерфейс для совместимости с bot.py"""
        result = self.get_chat_completion(messages)
        # Возвращаем в формате, который понимает bot.py
        if isinstance(result, tuple):
            return result[0]  # возвращаем только ответ
        return result

    # ДОБАВИТЬ асинхронный метод для совместимости:
    async def achat(self, messages):
        """Асинхронная версия метода chat"""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.chat, messages)