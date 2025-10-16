import difflib
import logging
import asyncpg
import re

from typing import List, Tuple, Optional, Dict
from functools import lru_cache


logger = logging.getLogger("database")

class ExamplesDB:
    def __init__(self):
        self._pool: Optional[asyncpg.Pool] = None
        self._connection_string = self._get_connection_string()
        
    def _get_connection_string(self):
        """Получить строку подключения из конфигурации"""
        from config import Config
        return Config.DATABASE_URL

    async def get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    self._connection_string,
                    min_size=5,
                    max_size=20,
                    command_timeout=60,
                    server_settings={
                        'search_path': 'public',
                        'application_name': 'invest_bot'
                    }
                )
                logger.info("PostgreSQL connection pool created successfully")
            except Exception as e:
                logger.error(f"Failed to create connection pool: {e}")
                raise
        return self._pool

    async def create_table(self) -> None:
        """Создание таблиц в PostgreSQL (аналог старого create_table)"""
        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                # Включаем расширение для триграммного поиска (если нужно)
                try:
                    await conn.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
                except Exception:
                    logger.warning("pg_trgm extension not available, using basic search")
                
                await conn.execute('''
                    CREATE TABLE IF NOT EXISTS user_stories (
                        id SERIAL PRIMARY KEY,
                        query TEXT NOT NULL,
                        normalized_query TEXT NOT NULL,
                        answer TEXT NOT NULL,
                        is_golden BOOLEAN NOT NULL DEFAULT FALSE,
                        score INTEGER NOT NULL DEFAULT 0,
                        usage_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Создаем индексы для производительности
                await conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_normalized_query 
                    ON user_stories(normalized_query)
                ''')
                await conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_is_golden 
                    ON user_stories(is_golden)
                ''')
                await conn.execute('''
                    CREATE INDEX IF NOT EXISTS idx_score 
                    ON user_stories(score)
                ''')
                
            logger.info("PostgreSQL tables created with indexes")
        except Exception as e:
            logger.error(f"Error creating tables: {e}")
            raise

    async def find_similar(self, query: str, threshold: float = 0.65, limit: int = 5) -> List[Tuple]:
        """Улучшенный поиск похожих историй с семантическим сравнением"""
        normalized_query = self._normalize_query(query)
        logger.info(f"Searching for similar to: '{normalized_query}' with threshold {threshold}")

        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                # Получаем все истории для семантического сравнения
                stories = await conn.fetch('''
                    SELECT query, answer, normalized_query, score 
                    FROM user_stories 
                    ORDER BY is_golden DESC, score DESC
                ''')

                similar = []
                for row in stories:
                    stored_norm = row['normalized_query']
                    
                    # Улучшенное сравнение с использованием SequenceMatcher
                    seq_matcher = difflib.SequenceMatcher(None, normalized_query, stored_norm)
                    sequence_similarity = seq_matcher.ratio()
                    
                    # Если схожесть высокая (> 0.95), считаем практически идентичными
                    if sequence_similarity >= 0.95:
                        # Для практически идентичных историй возвращаем 99%+ схожесть
                        similar.append((row['query'], row['answer'], 0.99, row['score']))
                    elif sequence_similarity >= threshold:
                        # Используем комбинированную метрику для менее похожих историй
                        query_words = set(normalized_query.split())
                        stored_words = set(stored_norm.split())
                        
                        common_words = query_words.intersection(stored_words)
                        total_words = len(query_words.union(stored_words))
                        
                        word_similarity = len(common_words) / total_words if total_words > 0 else 0
                        
                        # Комбинируем метрики с весом в пользу sequence similarity
                        combined_similarity = (sequence_similarity * 0.7 + word_similarity * 0.3)
                        
                        if combined_similarity >= threshold:
                            similar.append((row['query'], row['answer'], combined_similarity, row['score']))

                # Сортируем по убыванию схожести
                similar.sort(key=lambda x: x[2], reverse=True)
                return similar[:limit]

        except Exception as e:
            logger.error(f"Error in find_similar: {e}")
            return []

    async def add_example(self, query: str, normalized_query: str, answer: str,
                         is_golden: bool, score: int) -> int:
        """Добавление примера - совместимый интерфейс"""
        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow('''
                    INSERT INTO user_stories
                    (query, normalized_query, answer, is_golden, score, usage_count)
                    VALUES ($1, $2, $3, $4, $5, 0)
                    RETURNING id
                ''', query, normalized_query, answer, is_golden, score)
                
                logger.info(f"Added example with ID {row['id']}")
                return row['id']
        except Exception as e:
            logger.error(f"Error adding example: {e}")
            raise

    async def add_examples_batch(self, examples: List[Tuple]) -> None:
        """Пакетное добавление примеров - совместимый интерфейс"""
        if not examples:
            return
            
        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    for example in examples:
                        query, norm, answer, is_golden, score = example
                        await conn.execute('''
                            INSERT INTO user_stories
                            (query, normalized_query, answer, is_golden, score, usage_count)
                            VALUES ($1, $2, $3, $4, $5, 0)
                        ''', query, norm, answer, is_golden, score)
                        
            logger.info(f"Added {len(examples)} examples in batch")
        except Exception as e:
            logger.error(f"Error adding examples batch: {e}")
            raise

    async def increment_usage_count(self, normalized_query: str) -> None:
        """Увеличение счетчика использования - совместимый интерфейс"""
        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                await conn.execute('''
                    UPDATE user_stories
                    SET usage_count = usage_count + 1, 
                        updated_at = CURRENT_TIMESTAMP
                    WHERE normalized_query = $1
                ''', normalized_query)
        except Exception as e:
            logger.error(f"Error incrementing usage count: {e}")
            raise

    async def get_statistics(self) -> dict:
        """Получение статистики - совместимый интерфейс"""
        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                total = await conn.fetchval("SELECT COUNT(*) FROM user_stories")
                golden = await conn.fetchval("SELECT COUNT(*) FROM user_stories WHERE is_golden = TRUE")
                avg_score = await conn.fetchval("SELECT AVG(score) FROM user_stories")
                
                return {
                    "total_stories": total,
                    "golden_stories": golden,
                    "average_score": round(float(avg_score or 0), 2),
                }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {"total_stories": 0, "golden_stories": 0, "average_score": 0}

    async def get_all_stories(self, page: int = 0, page_size: int = 10) -> List[Dict]:
        """Получить все истории с пагинацией - совместимый интерфейс"""
        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                offset = page * page_size
                rows = await conn.fetch('''
                    SELECT id, query, answer, is_golden, score, created_at
                    FROM user_stories
                    ORDER BY created_at DESC, score DESC
                    LIMIT $1 OFFSET $2
                ''', page_size, offset)
                
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all stories: {e}")
            return []

    async def get_story_by_id(self, story_id: int) -> Optional[Dict]:
        """Получить историю по ID - совместимый интерфейс"""
        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT id, query, answer, is_golden, score, created_at
                    FROM user_stories
                    WHERE id = $1
                ''', story_id)
                
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting story by ID: {e}")
            return None

    async def get_total_stories_count(self) -> int:
        """Получить общее количество историй - совместимый интерфейс"""
        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                return await conn.fetchval("SELECT COUNT(*) FROM user_stories")
        except Exception as e:
            logger.error(f"Error getting total stories count: {e}")
            return 0

    async def close(self) -> None:
        """Улучшенное закрытие соединений"""
        if self._pool:
            try:
                # Даем время на завершение текущих операций
                await self._pool.close()
                self._pool = None
                logger.info("Database connection pool closed successfully")
            except Exception as e:
                logger.error(f"Error closing database pool: {e}")

    async def health_check(self) -> bool:
        """Проверка здоровья базы данных - совместимый интерфейс"""
        try:
            pool = await self.get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                return result == 1
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

    @lru_cache(maxsize=1000)
    def _normalize_query(self, text: str) -> str:
        """Улучшенная нормализация для поиска - игнорирует знаки препинания и регистр"""
        if not text:
            return ""
        
        text = text.lower().strip()
        
        # удаление знаков препинания
        import string
        punctuation_chars = string.punctuation + '«»„“‚‘‛"'
        text = text.translate(str.maketrans('', '', punctuation_chars))
        
        # Удаляем лишние пробелы
        text = ' '.join(text.split())
        
        # Дополнительная нормализация для User Stories
        text = re.sub(r'\s*,\s*', ' ', text)  # заменяем запятые на пробелы
        text = re.sub(r'\s+', ' ', text)  # удаляем множественные пробелы
        
        return text
