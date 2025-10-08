import logging
from dotenv import load_dotenv

from config import Config
from gigachat_client import GigaChatClient
from bot import InvestBot

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

def main():
    load_dotenv()
    Config.validate()

    token = Config.TELEGRAM_TOKEN
    if not token:
        raise ValueError("TELEGRAM_TOKEN не найден в .env")

    try:
        llm_client = GigaChatClient()
        bot = InvestBot(token, llm_client)
        bot.run()

    except KeyboardInterrupt:
        print("\nБот остановлен пользователем")
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        raise

if __name__ == "__main__":
    main()