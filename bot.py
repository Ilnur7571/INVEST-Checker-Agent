import time
import logging

from collections import OrderedDict
from typing import Any, Optional, Dict #, Tuple, List


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