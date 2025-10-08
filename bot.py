import asyncio
import logging
import time
import json
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from collections import OrderedDict

from telegram.ext import Application
#from telegram.error import TelegramError

from db import ExamplesDB
from handlers import register_handlers

logger = logging.getLogger("bot")


class LRUCache:
    """Простая реализация LRU кэша с TTL"""

    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        self.max_size = max_size
        self.ttl = ttl
        self.cache = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        if key not in self.cache:
            return None

        value, timestamp = self.cache[key]
        if time.time() - timestamp > self.ttl:
            del self.cache[key]
            return None

        # Перемещаем в конец (самый свежий)
        self.cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any):
        if key in self.cache:
            # Если ключ уже есть, перемещаем в конец
            self.cache.move_to_end(key)
        else:
            # Если достигли максимума, удаляем самый старый
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)

        self.cache[key] = (value, time.time())

    def clear_expired(self):
        """Очистка просроченных записей"""
        current_time = time.time()
        keys_to_remove = []

        for key, (value, timestamp) in self.cache.items():
            if current_time - timestamp > self.ttl:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self.cache[key]

        if keys_to_remove:
            logger.debug(f"Cleared {len(keys_to_remove)} expired cache entries")

    def clear(self):
        """Полная очистка кэша"""
        self.cache.clear()
        logger.info("Cache cleared completely")

    def size(self) -> int:
        return len(self.cache)

    def stats(self) -> Dict[str, Any]:
        return {
            "size": self.size(),
            "max_size": self.max_size,
            "ttl": self.ttl,
            "keys": list(self.cache.keys())[:10]  # Первые 10 ключей для отладки
        }


class InvestBot:
    def __init__(self, token: str, llm_client: Any):
        self.token = token
        self.llm_client = llm_client
        self.db = ExamplesDB()

        # Создаем Application
        self.app = Application.builder().token(self.token).build()

        # Глобальные данные бота
        self.app.bot_data.update({
            'db': self.db,
            'llm_client': self.llm_client,
            'bot': self,
            'start_time': datetime.now()
        })

        # Кэш для анализов (story_text -> analysis_data)
        self.analysis_cache = LRUCache(max_size=500, ttl=3600)  # 1 час TTL

        # Кэш для поиска похожих историй
        self.similarity_cache = LRUCache(max_size=200, ttl=1800)  # 30 минут TTL

        # История пользователей с ограничением по памяти
        self.user_history: Dict[int, List[Dict]] = {}
        self.max_history_depth = 50

        # Статистика использования
        self.stats = {
            'total_messages': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'llm_requests_saved': 0,
            'db_queries_saved': 0,
            'user_sessions': 0
        }

        # Время последней очистки кэша
        self._last_cache_cleanup = time.time()
        self._cleanup_interval = 300  # 5 минут

        # Регистрируем обработчики
        self._register_handlers()

        logger.info("InvestBot initialized with optimized caching")

    def _register_handlers(self):
        """Регистрация обработчиков"""
        register_handlers(self.app)

    async def initialize(self):
        """Инициализация бота с оптимизированной загрузкой"""
        logger.info("Initializing bot...")

        try:
            # Инициализация базы данных
            await self.db.create_table()

            # Быстрая проверка базы данных
            stats = await self.db.get_statistics()
            logger.info(f"Database stats: {stats['total_stories']} stories, {stats['golden_stories']} golden")

            if stats['total_stories'] == 0:
                logger.warning("Database is empty - consider running seed_examples.py")
            else:
                # Быстрый тест поиска с кэшированием
                test_query = "Как пользователь, я хочу регистрироваться, чтобы получить доступ к системе."
                similar = await self.find_similar_cached(test_query)
                logger.info(f"Test search found {len(similar)} similar stories")

            # Проверка здоровья LLM с таймаутом
            try:
                llm_health = await asyncio.wait_for(self.llm_client.health_check(), timeout=10.0)
                if not llm_health:
                    logger.warning("LLM client health check failed on startup")
                else:
                    logger.info("LLM client is healthy")
            except asyncio.TimeoutError:
                logger.warning("LLM health check timed out - proceeding without LLM")
            except Exception as e:
                logger.warning(f"LLM health check failed: {e} - proceeding without LLM")

            logger.info("Bot initialization completed successfully")

        except Exception as e:
            logger.error(f"Failed to initialize bot: {e}")
            raise

    async def find_similar_cached(self, query: str, threshold: float = 0.65, limit: int = 5) -> List[Tuple]:
        """Поиск похожих историй с кэшированием"""
        cache_key = f"similar_{hash(query)}_{threshold}_{limit}"

        # Пробуем получить из кэша
        cached_result = self.similarity_cache.get(cache_key)
        if cached_result is not None:
            self.stats['cache_hits'] += 1
            self.stats['db_queries_saved'] += 1
            logger.debug(f"Cache hit for similar stories: {query[:50]}...")
            return cached_result

        # Если нет в кэше - ищем в базе
        self.stats['cache_misses'] += 1
        result = await self.db.find_similar(query, threshold, limit)

        # Сохраняем в кэш (только если нашли результаты)
        if result:
            self.similarity_cache.set(cache_key, result)

        return result

    async def get_cached_analysis(self, story: str) -> Optional[Dict]:
        """Получить анализ из кэша"""
        cache_key = self._get_cache_key(story)
        result = self.analysis_cache.get(cache_key)

        if result is not None:
            self.stats['cache_hits'] += 1
            self.stats['llm_requests_saved'] += 1
            logger.info(f"Analysis cache hit for: {story[:50]}...")
        else:
            self.stats['cache_misses'] += 1

        return result

    async def cache_analysis(self, story: str, analysis_data: Dict):
        """Сохранить анализ в кэш"""
        cache_key = self._get_cache_key(story)
        self.analysis_cache.set(cache_key, analysis_data)
        logger.debug(f"Cached analysis for: {story[:50]}...")

    def _get_cache_key(self, story: str) -> str:
        """Генерация ключа кэша для истории"""
        # Нормализуем историю для консистентности ключей
        normalized = story.lower().strip()
        return f"analysis_{hash(normalized)}"

    def _cleanup_old_cache(self):
        """Очистка устаревшего кэша"""
        current_time = time.time()
        if current_time - self._last_cache_cleanup > self._cleanup_interval:
            self.analysis_cache.clear_expired()
            self.similarity_cache.clear_expired()
            self._last_cache_cleanup = current_time

            # Логируем статистику каждые 10 очисток
            if self.stats['total_messages'] % 10 == 0:
                logger.info(f"Cache cleanup completed. Analysis cache: {self.analysis_cache.size()}, "
                           f"Similarity cache: {self.similarity_cache.size()}")

    def add_to_user_history(self, user_id: int, story: str, analysis: str = None):
        """Добавить запись в историю пользователя с оптимизацией памяти"""
        if user_id not in self.user_history:
            self.user_history[user_id] = []
            self.stats['user_sessions'] += 1

        history_entry = {
            'timestamp': datetime.now().isoformat(),
            'story': story,
            'analysis': analysis,
            'type': 'user_story'
        }

        self.user_history[user_id].append(history_entry)
        self.stats['total_messages'] += 1

        # Ограничиваем глубину истории для экономии памяти
        if len(self.user_history[user_id]) > self.max_history_depth:
            self.user_history[user_id] = self.user_history[user_id][-self.max_history_depth:]

        # Периодическая очистка кэша
        if self.stats['total_messages'] % 20 == 0:
            self._cleanup_old_cache()

    def get_user_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Получить историю пользователя"""
        if user_id not in self.user_history:
            return []

        history = self.user_history[user_id][-limit:]
        return history[::-1]  # Возвращаем в обратном порядке (последние первыми)

    def get_user_stats(self, user_id: int) -> Dict[str, Any]:
        """Получить статистику пользователя"""
        if user_id not in self.user_history:
            return {
                'total_stories': 0,
                'last_activity': None,
                'session_duration': '0:00:00'
            }

        user_history = self.user_history[user_id]
        if not user_history:
            return {
                'total_stories': 0,
                'last_activity': None,
                'session_duration': '0:00:00'
            }

        first_activity = datetime.fromisoformat(user_history[0]['timestamp'])
        last_activity = datetime.fromisoformat(user_history[-1]['timestamp'])
        session_duration = last_activity - first_activity

        return {
            'total_stories': len(user_history),
            'last_activity': last_activity.isoformat(),
            'session_duration': str(session_duration),
            'stories_today': len([h for h in user_history
                                if datetime.fromisoformat(h['timestamp']).date() == datetime.now().date()])
        }

    async def get_bot_stats(self) -> Dict[str, Any]:
        """Получить расширенную статистику бота"""
        try:
            db_stats = await self.db.get_statistics()
            uptime = datetime.now() - self.app.bot_data['start_time']

            # Статистика LLM клиента
            llm_stats = self.llm_client.get_stats()

            # Статистика кэшей
            analysis_cache_stats = self.analysis_cache.stats()
            similarity_cache_stats = self.similarity_cache.stats()

            # Расчет эффективности кэширования
            total_requests = self.stats['cache_hits'] + self.stats['cache_misses']
            cache_hit_rate = self.stats['cache_hits'] / max(total_requests, 1)

            stats = {
                "uptime": str(uptime),
                "active_users": len(self.user_history),
                "total_users": self.stats['user_sessions'],
                "total_messages": self.stats['total_messages'],
                "cache_hits": self.stats['cache_hits'],
                "cache_misses": self.stats['cache_misses'],
                "cache_hit_rate": round(cache_hit_rate, 3),
                "llm_requests_saved": self.stats['llm_requests_saved'],
                "db_queries_saved": self.stats['db_queries_saved'],
                "analysis_cache_size": analysis_cache_stats['size'],
                "similarity_cache_size": similarity_cache_stats['size'],
            }

            # Добавляем статистику LLM
            stats.update({f"llm_{k}": v for k, v in llm_stats.items()})

            # Добавляем статистику базы данных
            stats.update(db_stats)

            return stats

        except Exception as e:
            logger.error(f"Error getting bot stats: {e}")
            return {"error": str(e)}

    async def is_healthy(self) -> bool:
        """Проверка здоровья системы с кэшированием"""
        try:
            # Упрощенная проверка БД
            try:
                # Простой запрос для проверки соединения с БД
                stats = await self.db.get_statistics()
                db_health = stats is not None
            except Exception as e:
                logger.warning(f"Database health check error: {e}")
                db_health = False

            # Проверка LLM с таймаутом
            try:
                llm_health = await asyncio.wait_for(self.llm_client.health_check(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("LLM health check timeout")
                llm_health = False
            except Exception as e:
                logger.warning(f"LLM health check error: {e}")
                llm_health = False

            # Бот считается здоровым если база данных работает
            health_status = db_health

            if not llm_health:
                logger.warning("LLM is unavailable but bot can still function with cached responses")

            return health_status

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    def run(self):
        """Запуск бота (синхронный метод для PTB 22.5)"""
        logger.info("Starting optimized bot...")

        try:
            # Инициализация (синхронно)
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.initialize())

            # Запуск polling
            self.app.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
                poll_interval=1.0,  # Уменьшили интервал опроса для отзывчивости
            )

        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            raise
        finally:
            self.shutdown()

    async def run_async(self):
        """Асинхронная версия запуска (для использования с asyncio.run)"""
        logger.info("Starting bot asynchronously...")

        try:
            await self.initialize()
            await self.app.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
                poll_interval=1.0,
            )

        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Error starting bot: {e}")
            raise
        finally:
            await self.shutdown_async()

    def shutdown(self):
        """Синхронное завершение работы с сохранением статистики"""
        logger.info("Shutting down bot...")
        try:
            # Логируем финальную статистику
            try:
                # Создаем новую event loop для синхронного вызова
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                stats = loop.run_until_complete(self.get_bot_stats())
                logger.info(f"Final stats: {json.dumps(stats, indent=2, default=str)}")
            except Exception as e:
                logger.error(f"Error getting final stats: {e}")

            # Синхронное закрытие базы данных
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self.db.close())
            except Exception as e:
                logger.error(f"Error closing database: {e}")

            # Очищаем кэши
            self.analysis_cache.clear()
            self.similarity_cache.clear()

            logger.info("Bot shutdown completed")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    async def shutdown_async(self):
        """Асинхронное завершение работы"""
        logger.info("Shutting down bot asynchronously...")
        try:
            # Логируем финальную статистику
            stats = await self.get_bot_stats()
            logger.info(f"Final stats: {json.dumps(stats, indent=2, default=str)}")

            await self.db.close()

            # Очищаем кэши
            self.analysis_cache.clear()
            self.similarity_cache.clear()

            logger.info("Bot shutdown completed")

        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    def clear_caches(self):
        """Очистка всех кэшей (для отладки и тестирования)"""
        self.analysis_cache.clear()
        self.similarity_cache.clear()
        logger.info("All caches cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Получить детальную статистику кэшей"""
        return {
            "analysis_cache": self.analysis_cache.stats(),
            "similarity_cache": self.similarity_cache.stats(),
            "performance_stats": {
                "cache_hit_rate": self.stats['cache_hits'] / max(self.stats['cache_hits'] + self.stats['cache_misses'], 1),
                "llm_requests_saved": self.stats['llm_requests_saved'],
                "db_queries_saved": self.stats['db_queries_saved'],
                "total_efficiency": self.stats['llm_requests_saved'] + self.stats['db_queries_saved']
            }
        }
