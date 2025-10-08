import logging
from typing import List, Tuple, Optional, Dict
from functools import lru_cache
import aiosqlite
from rapidfuzz import fuzz

logger = logging.getLogger("db")

class ExamplesDB:
    def __init__(self, db_path: str = "examples.db"):
        self.db_path = db_path
        self._connection: Optional[aiosqlite.Connection] = None
        self._cache = {}  # Простой кэш для часто используемых запросов

    async def get_connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            self._connection = await aiosqlite.connect(self.db_path)
            await self._connection.execute("PRAGMA journal_mode=WAL")
            await self._connection.execute("PRAGMA synchronous=NORMAL")
            await self._connection.execute("PRAGMA cache_size=-64000")
            self._connection.row_factory = aiosqlite.Row
        return self._connection

    async def create_table(self) -> None:
        try:
            conn = await self.get_connection()
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_stories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    normalized_query TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    is_golden BOOLEAN NOT NULL,
                    score INTEGER NOT NULL,
                    usage_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Создаем индексы для быстрого поиска
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_normalized_query ON user_stories(normalized_query)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_is_golden ON user_stories(is_golden)')
            await conn.execute('CREATE INDEX IF NOT EXISTS idx_score ON user_stories(score)')
            await conn.commit()
            logger.info("Table 'user_stories' created with indexes")
        except aiosqlite.Error as e:
            logger.error(f"Error creating table: {e}")
            raise

    async def find_similar(self, query: str, threshold: float = 0.65, limit: int = 5) -> List[Tuple]:
        """Оптимизированный поиск похожих историй"""
        cache_key = f"similar_{hash(query)}_{threshold}_{limit}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        normalized_query = self._normalize_query(query)
        logger.info(f"Searching for similar to: '{normalized_query}'")

        try:
            conn = await self.get_connection()

            # 1. Поиск точных совпадений
            async with conn.execute('''
                SELECT query, answer, normalized_query, score
                FROM user_stories
                WHERE normalized_query = ?
                ORDER BY is_golden DESC, score DESC
                LIMIT ?
            ''', (normalized_query, limit)) as cursor:
                exact_matches = await cursor.fetchall()

            if exact_matches:
                results = [
                    (row['query'], row['answer'], 1.0, row['score'])
                    for row in exact_matches
                ]
                self._cache[cache_key] = results
                return results

            # 2. Поиск по ключевым словам
            keywords = self._extract_keywords(normalized_query)
            if keywords:
                keyword_results = await self._find_by_keywords(keywords, limit)
                if keyword_results:
                    self._cache[cache_key] = keyword_results
                    return keyword_results

            # 3. Семантический поиск (только если выше не нашли)
            async with conn.execute('''
                SELECT query, answer, normalized_query, score
                FROM user_stories
                WHERE is_golden = 1 OR score >= 4
                ORDER BY is_golden DESC, score DESC
                LIMIT 100
            ''') as cursor:
                candidate_stories = await cursor.fetchall()

            similar = []
            for row in candidate_stories:
                stored_norm = row['normalized_query']

                # Быстрое сравнение
                ratio = fuzz.token_sort_ratio(normalized_query, stored_norm) / 100
                if ratio >= threshold:
                    similar.append((row['query'], row['answer'], ratio, row['score']))

            similar.sort(key=lambda x: x[2], reverse=True)
            results = similar[:limit]

            self._cache[cache_key] = results
            return results

        except Exception as e:
            logger.error(f"Error in find_similar: {e}")
            return []

    def _extract_keywords(self, text: str) -> List[str]:
        """Извлекает ключевые слова для поиска"""
        stop_words = {"как", "я", "хочу", "чтобы", "мне", "нужно", "можно", "что", "бы"}
        words = text.split()
        keywords = [word for word in words if word not in stop_words and len(word) > 3]
        return keywords[:4]  # Ограничиваем количество ключевых слов

    async def _find_by_keywords(self, keywords: List[str], limit: int) -> List[Tuple]:
        """Поиск по ключевым словам"""
        if not keywords:
            return []

        try:
            conn = await self.get_connection()
            # Используем первое ключевое слово для быстрого поиска
            primary_keyword = keywords[0]

            async with conn.execute('''
                SELECT query, answer, normalized_query, score
                FROM user_stories
                WHERE normalized_query LIKE '%' || ? || '%'
                ORDER BY is_golden DESC, score DESC
                LIMIT ?
            ''', (primary_keyword, limit * 2)) as cursor:
                results = await cursor.fetchall()

            # Фильтруем по остальным ключевым словам
            filtered = []
            for row in results:
                story_text = row['normalized_query']
                # Считаем сколько ключевых слов совпало
                matches = sum(1 for keyword in keywords if keyword in story_text)
                ratio = matches / len(keywords)

                if ratio >= 0.5:  # Если хотя бы половина ключевых слов совпала
                    filtered.append((row['query'], row['answer'], ratio, row['score']))

            return sorted(filtered, key=lambda x: x[2], reverse=True)[:limit]

        except Exception as e:
            logger.error(f"Keyword search error: {e}")
            return []

    @lru_cache(maxsize=1000)
    def _normalize_query(self, text: str) -> str:
        """Быстрая нормализация для поиска"""
        text = text.lower().strip()
        return ' '.join(text.split())

    async def add_example(self, query: str, normalized_query: str, answer: str,
                         is_golden: bool, score: int) -> int:
        """Добавление примера с очисткой кэша"""
        try:
            conn = await self.get_connection()
            cursor = await conn.execute('''
                INSERT INTO user_stories
                (query, normalized_query, answer, is_golden, score, usage_count)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', (query, normalized_query, answer, is_golden, score))
            await conn.commit()

            # Очищаем кэш при добавлении новых данных
            self._cache.clear()

            row_id = cursor.lastrowid
            logger.info(f"Added example with ID {row_id}")
            return row_id
        except aiosqlite.Error as e:
            logger.error(f"Error adding example: {e}")
            raise

    async def add_examples_batch(self, examples: List[Tuple]) -> None:
        if not examples:
            return
        try:
            conn = await self.get_connection()
            async with conn.cursor() as cursor:
                await cursor.executemany('''
                    INSERT INTO user_stories
                    (query, normalized_query, answer, is_golden, score, usage_count)
                    VALUES (?, ?, ?, ?, ?, 0)
                ''', examples)
            await conn.commit()
            self._cache.clear()  # Очищаем кэш
            logger.info(f"Added {len(examples)} examples in batch")
        except aiosqlite.Error as e:
            logger.error(f"Error adding examples batch: {e}")
            raise

    async def increment_usage_count(self, normalized_query: str) -> None:
        try:
            conn = await self.get_connection()
            await conn.execute('''
                UPDATE user_stories
                SET usage_count = usage_count + 1, updated_at = CURRENT_TIMESTAMP
                WHERE normalized_query = ?
            ''', (normalized_query,))
            await conn.commit()
        except aiosqlite.Error as e:
            logger.error(f"Error incrementing usage count: {e}")
            raise

    async def get_statistics(self) -> dict:
        try:
            conn = await self.get_connection()
            async with conn.execute("SELECT COUNT(*) FROM user_stories") as cursor:
                total_stories = (await cursor.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM user_stories WHERE is_golden = 1") as cursor:
                golden_stories = (await cursor.fetchone())[0]
            async with conn.execute("SELECT AVG(score) FROM user_stories") as cursor:
                avg_score = (await cursor.fetchone())[0] or 0.0

            return {
                "total_stories": total_stories,
                "golden_stories": golden_stories,
                "average_score": round(float(avg_score), 2),
            }
        except aiosqlite.Error as e:
            logger.error(f"Error getting statistics: {e}")
            raise

    async def close(self) -> None:
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def health_check(self) -> bool:
        """Проверка здоровья базы данных"""
        try:
            conn = await self.get_connection()
            # Простой запрос для проверки соединения
            async with conn.execute("SELECT 1") as cursor:
                result = await cursor.fetchone()
                return result is not None and result[0] == 1
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return False

# В db.py добавляем новые методы
    async def get_all_stories(self, page: int = 0, page_size: int = 10) -> List[Dict]:
        """Получить все истории с пагинацией"""
        try:
            conn = await self.get_connection()
            offset = page * page_size

            async with conn.execute('''
                SELECT id, query, answer, is_golden, score, created_at
                FROM user_stories
                ORDER BY created_at DESC, score DESC
                LIMIT ? OFFSET ?
            ''', (page_size, offset)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all stories: {e}")
            return []

    async def get_golden_stories(self, page: int = 0, page_size: int = 10) -> List[Dict]:
        """Получить золотые истории с пагинацией"""
        try:
            conn = await self.get_connection()
            offset = page * page_size

            async with conn.execute('''
                SELECT id, query, answer, is_golden, score, created_at
                FROM user_stories
                WHERE is_golden = 1
                ORDER BY score DESC, created_at DESC
                LIMIT ? OFFSET ?
            ''', (page_size, offset)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting golden stories: {e}")
            return []

    async def get_story_by_id(self, story_id: int) -> Optional[Dict]:
        """Получить историю по ID"""
        try:
            conn = await self.get_connection()

            async with conn.execute('''
                SELECT id, query, answer, is_golden, score, created_at
                FROM user_stories
                WHERE id = ?
            ''', (story_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting story by ID: {e}")
            return None

    async def get_total_stories_count(self) -> int:
        """Получить общее количество историй"""
        try:
            conn = await self.get_connection()
            async with conn.execute("SELECT COUNT(*) FROM user_stories") as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Error getting total stories count: {e}")
            return 0

    async def get_golden_stories_count(self) -> int:
        """Получить количество золотых историй"""
        try:
            conn = await self.get_connection()
            async with conn.execute("SELECT COUNT(*) FROM user_stories WHERE is_golden = 1") as cursor:
                result = await cursor.fetchone()
                return result[0] if result else 0
        except Exception as e:
            logger.error(f"Error getting golden stories count: {e}")
            return 0

    async def search_stories(self, query: str, threshold: float = 0.6, limit: int = 10) -> List[Dict]:
        """Поиск историй по ключевым словам"""
        try:
            similar = await self.find_similar(query, threshold, limit)
            results = []
            for i, (story, answer, ratio, score) in enumerate(similar):
                results.append({
                    'id': f"search_{i}",  # Уникальный ID для поисковых результатов
                    'query': story,
                    'answer': answer,
                    'is_golden': False,
                    'score': score,
                    'similarity': ratio
                })
            return results
        except Exception as e:
            logger.error(f"Error searching stories: {e}")
            return []
