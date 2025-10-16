import logging
import asyncio

from datetime import datetime
from dotenv import load_dotenv
from telegram.ext import Application
from config import Config
from gigachat_client import GigaChatClient
from db import ExamplesDB
from handlers import register_handlers

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

async def initialize_components():
    """Инициализация компонентов"""
    db = ExamplesDB()
    await db.create_table()
    
    # Проверяем соединение с БД
    stats = await db.get_statistics()
    logging.info(f"Database: {stats['total_stories']} stories, {stats['golden_stories']} golden")
    
    # Проверяем LLM
    llm_client = GigaChatClient()
    try:
        health = await llm_client.health_check()
        logging.info(f"LLM health: {health}")
    except Exception as e:
        logging.warning(f"LLM health check failed: {e}")
    
    return db, llm_client

class SimpleBot:
    """Простой класс бота для хранения состояния с работающей статистикой"""
    def __init__(self):
        self.start_time = datetime.now()
        self.user_history = {}
        self.stats = {
            'total_messages': 0,
            'user_sessions': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }

    def add_to_user_history(self, user_id: int, story: str, analysis: str = None):
        """Добавить запись в историю пользователя"""
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
        max_history_depth = 50
        if len(self.user_history[user_id]) > max_history_depth:
            self.user_history[user_id] = self.user_history[user_id][-max_history_depth:]

    async def get_bot_stats(self, db, llm_client):
        """Получить статистику бота"""
        try:
            # Статистика базы данных
            db_stats = await db.get_statistics()
            
            # Статистика LLM клиента
            llm_stats = llm_client.get_stats()
            
            # Время работы
            uptime = datetime.now() - self.start_time
            
            # Активные пользователи
            active_users = len(self.user_history)
            
            # Расчет эффективности кэширования
            total_cache_requests = self.stats['cache_hits'] + self.stats['cache_misses']
            cache_hit_rate = self.stats['cache_hits'] / max(total_cache_requests, 1)
            
            stats = {
                "uptime": str(uptime),
                "active_users": active_users,
                "total_users": self.stats['user_sessions'],
                "total_messages": self.stats['total_messages'],
                "cache_hits": self.stats['cache_hits'],
                "cache_misses": self.stats['cache_misses'],
                "cache_hit_rate": round(cache_hit_rate, 3),
                "analysis_cache_size": 0,
                "similarity_cache_size": 0,
            }
            
            # Добавляем статистику LLM
            stats.update({f"llm_{k}": v for k, v in llm_stats.items()})
            
            # Добавляем статистику базы данных
            stats.update(db_stats)
            
            return stats
            
        except Exception as e:
            logging.error(f"Error getting bot stats: {e}")
            return {"error": str(e)}

def main():
    load_dotenv()
    Config.validate()

    token = Config.TELEGRAM_TOKEN
    if not token:
        raise ValueError("TELEGRAM_TOKEN не найден в .env")

    try:
        # Инициализируем компоненты
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        db, llm_client = loop.run_until_complete(initialize_components())
        
        # Создаем простой объект бота
        bot = SimpleBot()
        
        # Создаем Application
        app = Application.builder().token(token).build()
        
        # Добавляем в bot_data
        app.bot_data.update({
            'db': db,
            'llm_client': llm_client,
            'bot': bot  # Добавляем объект бота
        })
        
        # Регистрируем обработчики
        register_handlers(app)
        
        # Запускаем бота
        logging.info("Starting bot polling...")
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
            poll_interval=1.0,
        )

    except KeyboardInterrupt:
        print("\nБот остановлен пользователем")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        raise

if __name__ == "__main__":
    main()
