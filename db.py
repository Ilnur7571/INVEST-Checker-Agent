# db.py - исправляем метод find_similar
import sqlite3
from difflib import SequenceMatcher
from utils import normalize_text

class ExamplesDB:
    def __init__(self, db_path="examples.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.create_table()

    def __del__(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def create_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS user_stories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            norm TEXT NOT NULL UNIQUE,
            answer TEXT,
            is_golden BOOLEAN DEFAULT FALSE,
            score INTEGER DEFAULT 0,
            usage_count INTEGER DEFAULT 0,
            added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_norm ON user_stories(norm);
        CREATE INDEX IF NOT EXISTS idx_is_golden ON user_stories(is_golden);
        CREATE INDEX IF NOT EXISTS idx_score ON user_stories(score DESC);
        """
        self.conn.executescript(query)
        self.conn.commit()

    def add_example(self, query: str, norm: str, answer: str, is_golden: bool = False, score: int = 0):
        try:
            cursor = self.conn.execute(
                "INSERT INTO user_stories (query, norm, answer, is_golden, score) VALUES (?, ?, ?, ?, ?)",
                (query, norm, answer, is_golden, score),
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            self.conn.execute(
                "UPDATE user_stories SET answer = ?, is_golden = ?, score = ?, last_used = CURRENT_TIMESTAMP WHERE norm = ?",
                (answer, is_golden, score, norm),
            )
            self.conn.commit()
            return None

    def increment_usage_count(self, norm: str):
        self.conn.execute(
            "UPDATE user_stories SET usage_count = usage_count + 1, last_used = CURRENT_TIMESTAMP WHERE norm = ?",
            (norm,)
        )
        self.conn.commit()

    def get_all_examples(self, only_golden: bool = False):
        if only_golden:
            cursor = self.conn.execute("SELECT id, query, norm, answer, is_golden, score, usage_count FROM user_stories WHERE is_golden = TRUE ORDER BY score DESC, usage_count DESC")
        else:
            cursor = self.conn.execute("SELECT id, query, norm, answer, is_golden, score, usage_count FROM user_stories")

        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "query": r[1],
                "norm": r[2],
                "answer": r[3],
                "is_golden": bool(r[4]),
                "score": r[5],
                "usage_count": r[6]
            }
            for r in rows
        ]

    def find_similar(self, query: str, threshold=0.75, prefer_golden=True):
        norm = normalize_text(query)
        all_examples = self.get_all_examples()

        golden_similar = []
        regular_similar = []

        for ex in all_examples:
            ratio = SequenceMatcher(None, norm, ex["norm"]).ratio()
            if ratio >= threshold:
                # Всегда возвращаем 4 элемента для единообразия
                if ex["is_golden"]:
                    golden_similar.append((ex["query"], ex["answer"], ratio, ex["score"]))
                else:
                    regular_similar.append((ex["query"], ex["answer"], ratio, 0))  # Добавляем score=0 для обычных историй

        if prefer_golden and golden_similar:
            golden_similar.sort(key=lambda x: x[3], reverse=True)  # sort by score
            return golden_similar

        if regular_similar:
            regular_similar.sort(key=lambda x: x[2], reverse=True)  # sort by similarity
            return regular_similar

        return []

    def get_statistics(self):
        cursor = self.conn.execute("SELECT COUNT(*), SUM(usage_count) FROM user_stories")
        total_count, total_usage = cursor.fetchone()

        cursor = self.conn.execute("SELECT COUNT(*) FROM user_stories WHERE is_golden = TRUE")
        golden_count = cursor.fetchone()[0]

        cursor = self.conn.execute("SELECT AVG(score) FROM user_stories WHERE is_golden = TRUE AND score > 0")
        avg_score = cursor.fetchone()[0] or 0

        return {
            "total_stories": total_count,
            "golden_stories": golden_count,
            "total_usage": total_usage or 0,
            "average_score": round(avg_score, 2)
        }
