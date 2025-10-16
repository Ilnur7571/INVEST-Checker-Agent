import asyncio
import base64
import time
import uuid
import httpx
from httpx import AsyncClient
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging
from typing import List, Dict, Any, Optional

from config import Config

logger = logging.getLogger("gigachat_client")


# Custom exceptions для лучшей обработки ошибок
class GigaChatError(Exception):
    """Базовое исключение для GigaChat клиента"""
    pass

class TokenExpiredError(GigaChatError):
    """Исключение для просроченного токена"""
    pass

class RateLimitError(GigaChatError):
    """Исключение для превышения лимита запросов"""
    pass

class ServerError(GigaChatError):
    """Исключение для ошибок сервера"""
    pass


class GigaChatClient:
    """Асинхронный клиент для GigaChat API с улучшенной обработкой ошибок и оптимизациями"""

    def __init__(self):
        self.auth_credentials = Config.get_auth_credentials()
        self.scope = Config.GIGACHAT_SCOPE
        self.verify = not Config.DISABLE_SSL_VERIFY

        # URLs
        self.token_url = Config.GIGACHAT_AUTH_URL
        self.api_base = Config.GIGACHAT_API_URL

        # Token management
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0

        # Statistics and caching
        self._request_count = 0
        self._error_count = 0
        self._last_request_time = 0
        self._token_cache_hits = 0
        self._response_cache = {}  # Кэш ответов для одинаковых запросов

        # Circuit breaker state (упрощенная реализация)
        self._circuit_open = False
        self._circuit_open_until = 0

        # Performance monitoring
        self._total_tokens_sent = 0
        self._total_tokens_received = 0

        logger.info("GigaChat client initialized with optimizations")

    def _get_auth_key(self) -> str:
        """Получить auth key для аутентификации"""
        if "auth_key" in self.auth_credentials:
            return self.auth_credentials["auth_key"]
        elif "client_id" in self.auth_credentials and "client_secret" in self.auth_credentials:
            raw = f"{self.auth_credentials['client_id']}:{self.auth_credentials['client_secret']}"
            return base64.b64encode(raw.encode("utf-8")).decode("utf-8")
        else:
            raise ValueError("No valid authentication credentials provided")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException))
    )
    async def get_token(self) -> str:
        """Получить access token с retry логикой и кэшированием"""
        # Проверка circuit breaker
        if self._circuit_open:
            if time.time() < self._circuit_open_until:
                raise GigaChatError("Circuit breaker is open")
            else:
                self._circuit_open = False
                logger.info("Circuit breaker closed after timeout")

        now = time.time()
        if self._access_token and now < (self._token_expiry - 60):
            self._token_cache_hits += 1
            return self._access_token

        try:
            rq_uid = str(uuid.uuid4())
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": rq_uid,
                "Authorization": f"Basic {self._get_auth_key()}",
            }
            payload = {"scope": self.scope}

            async with AsyncClient(verify=self.verify, timeout=30.0) as client:
                resp = await client.post(
                    self.token_url, headers=headers, data=payload
                )
                resp.raise_for_status()

            j = resp.json()
            access = j.get("access_token")
            expires_at = j.get("expires_at")

            if not access:
                raise RuntimeError(f"Access token not found in response: {j}")

            # Parse expiration time
            try:
                exp_int = int(expires_at)
                exp_ts = exp_int / 1000 if exp_int > 10**12 else exp_int
            except (TypeError, ValueError):
                exp_ts = now + 1800  # Fallback: 30 minutes

            self._access_token = access
            self._token_expiry = exp_ts

            logger.debug("Successfully obtained new access token")
            return access

        except httpx.HTTPStatusError as e:
            self._error_count += 1
            logger.error(f"HTTP error getting token: {e.response.status_code} - {e.response.text}")

            # Circuit breaker logic для 5xx ошибок
            if e.response.status_code >= 500:
                self._handle_circuit_breaker_failure()

            raise
        except httpx.RequestError as e:
            self._error_count += 1
            logger.error(f"Request error getting token: {e}")
            self._handle_circuit_breaker_failure()
            raise
        except Exception as e:
            self._error_count += 1
            logger.error(f"Unexpected error getting token: {e}")
            raise

    def _handle_circuit_breaker_failure(self):
        """Обработка failures для circuit breaker"""
        # Простая реализация circuit breaker
        consecutive_failures = 5  # После 5 последовательных ошибок открываем circuit
        if self._error_count >= consecutive_failures:
            self._circuit_open = True
            self._circuit_open_until = time.time() + 300  # 5 минут timeout
            logger.warning("Circuit breaker opened due to consecutive failures")

    def _get_cache_key(self, messages: List[Dict]) -> str:
        """Генерация ключа кэша для сообщений"""
        content = "".join(msg.get("content", "") for msg in messages)
        return str(hash(content))

    def _estimate_token_count(self, text: str) -> int:
        """Примерная оценка количества токенов"""
        # Для русского текста: 1 токен ≈ 2-3 символа
        return len(text) // 2.5 if text else 0

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException, TokenExpiredError))
    )
    async def get_chat_completion(self, messages: List[Dict]) -> tuple[str, List[Dict]]:
        """Получить completion от GigaChat с circuit breaker, retry и кэшированием"""
        self._request_count += 1
        self._last_request_time = time.time()

        # Проверка circuit breaker
        if self._circuit_open:
            if time.time() < self._circuit_open_until:
                raise GigaChatError("Circuit breaker is open")
            else:
                self._circuit_open = False
                logger.info("Circuit breaker closed after timeout")

        # Проверяем кэш перед обращением к API
        cache_key = self._get_cache_key(messages)
        if cache_key in self._response_cache:
            logger.debug("Using cached response for completion")
            cached_data = self._response_cache[cache_key]
            # Проверяем TTL кэша (5 минут)
            if time.time() - cached_data['timestamp'] < 300:
                return cached_data['response'], messages

        token = await self.get_token()
        url = f"{self.api_base}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }

        # Оптимизированный payload с ограничением токенов
        payload = {
            "model": Config.MODEL_NAME,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 512,  # лимит для экономии
            "top_p": 0.9
        }

        # Логируем использование токенов
        input_text = " ".join(msg.get("content", "") for msg in messages)
        input_tokens = self._estimate_token_count(input_text)
        self._total_tokens_sent += input_tokens

        try:
            async with AsyncClient(verify=self.verify, timeout=60.0) as client:
                resp = await client.post(url, headers=headers, json=payload)

                # Обработка специфичных HTTP ошибок
                if resp.status_code == 401:
                    logger.warning("Token expired, refreshing...")
                    self._access_token = None  # Инвалидируем токен
                    raise TokenExpiredError("Access token expired")
                elif resp.status_code == 429:
                    logger.warning("Rate limit exceeded, waiting...")
                    await asyncio.sleep(2)  # Backoff
                    raise RateLimitError("Rate limit exceeded")
                elif resp.status_code >= 500:
                    logger.error(f"Server error: {resp.status_code}")
                    raise ServerError(f"Server error: {resp.status_code}")

                resp.raise_for_status()

            data = resp.json()

            if "choices" not in data or not data["choices"]:
                raise ValueError("Invalid response format: no choices found")

            answer = data["choices"][0]["message"]["content"]

            # Логируем полученные токены
            output_tokens = self._estimate_token_count(answer)
            self._total_tokens_received += output_tokens

            logger.debug(f"LLM request: {input_tokens} in, {output_tokens} out tokens")

            # Кэшируем успешный ответ
            self._response_cache[cache_key] = {
                'response': (answer, messages),
                'timestamp': time.time()
            }

            # Ограничиваем размер кэша
            if len(self._response_cache) > 100:
                # Удаляем самые старые записи
                oldest_key = min(self._response_cache.keys(),
                               key=lambda k: self._response_cache[k]['timestamp'])
                del self._response_cache[oldest_key]

            # Сброс счетчика ошибок при успешном запросе
            self._error_count = max(0, self._error_count - 1)

            return answer, messages

        except httpx.HTTPStatusError as e:
            self._error_count += 1
            logger.error(f"HTTP error in chat completion: {e.response.status_code} - {e.response.text}")

            # Circuit breaker для 5xx ошибок
            if e.response.status_code >= 500:
                self._handle_circuit_breaker_failure()

            raise
        except httpx.RequestError as e:
            self._error_count += 1
            logger.error(f"Request error in chat completion: {e}")
            self._handle_circuit_breaker_failure()
            raise
        except Exception as e:
            self._error_count += 1
            logger.error(f"Unexpected error in chat completion: {e}")
            raise

    async def chat(self, messages: List[Dict]) -> str:
        """Упрощенный интерфейс для чата"""
        result = await self.get_chat_completion(messages)
        return result[0] if isinstance(result, tuple) else result

    async def health_check(self) -> bool:
        """Проверка здоровья клиента"""
        try:
            # Быстрая проверка получения токена
            token = await self.get_token()
            return bool(token)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику клиента"""
        total_requests = max(self._request_count, 1)
        return {
            "total_requests": self._request_count,
            "error_count": self._error_count,
            "error_rate": self._error_count / total_requests,
            "token_cache_hits": self._token_cache_hits,
            "token_cache_hit_rate": self._token_cache_hits / total_requests,
            "response_cache_size": len(self._response_cache),
            "circuit_open": self._circuit_open,
            "token_valid": bool(self._access_token and time.time() < self._token_expiry),
            "last_request_time": self._last_request_time,
            "total_tokens_sent": self._total_tokens_sent,
            "total_tokens_received": self._total_tokens_received,
            "estimated_cost_saved": (self._token_cache_hits * 0.002),  # Примерная экономия
        }

    async def test_connection(self) -> bool:
        """Тестирование соединения с GigaChat API"""
        try:
            test_messages = [
                {"role": "user", "content": "Привет! Ответь просто 'OK'"}
            ]
            response = await self.get_chat_completion(test_messages)
            return bool(response and response[0])
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    def reset_circuit_breaker(self):
        """Сброс circuit breaker"""
        self._circuit_open = False
        self._circuit_open_until = 0
        self._error_count = 0
        logger.info("Circuit breaker reset")

    def clear_cache(self):
        """Очистка кэшей"""
        self._response_cache.clear()
        self._access_token = None
        self._token_expiry = 0
        logger.info("Client cache cleared")

    async def close(self):
        """Закрытие клиента"""
        self._access_token = None
        self._token_expiry = 0
        self._response_cache.clear()
        logger.info("GigaChat client closed")
