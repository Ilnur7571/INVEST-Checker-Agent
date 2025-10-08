# #import os
# from config import Config
# import logging
# from dotenv import load_dotenv
# from gigachat_client import GigaChatClient
# from bot import InvestBot

# load_dotenv()

# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
# )

# def main():
#     Config.validate()

#     token = Config.TELEGRAM_TOKEN
#     if not token:
#         raise ValueError("TELEGRAM_TOKEN не найден в .env")

#     # Инициализация клиента GigaChat
#     llm_client = GigaChatClient()

#     # Создание и запуск бота
#     bot = InvestBot(token, llm_client)
#     bot.run()

# if __name__ == "__main__":
#     main()


# main.py
from config import Config
import logging
from dotenv import load_dotenv
from gigachat_client import GigaChatClient
from bot import InvestBot

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

def main():
    Config.validate()

    token = Config.TELEGRAM_TOKEN
    if not token:
        raise ValueError("TELEGRAM_TOKEN не найден в .env")

    llm_client = GigaChatClient()

    bot = InvestBot(token, llm_client)
    bot.run()

if __name__ == "__main__":
    main()