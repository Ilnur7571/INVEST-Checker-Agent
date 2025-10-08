# Telegram INVEST-Checker Agent (GigaChat)

Проект: AI-агент для проверки User Story по INVEST через Telegram-бота.
Он отправляет запросы в GigaChat API, сравнивает с базой предыдущих вопросов/ответов,
и при нахождении похожих случаев использует их для ускорения и уточнения ответа.

Файлы:
- bot.py — Telegram bot (uses python-telegram-bot).
- gigachat_client.py — thin client for GigaChat REST API.
- db.py — simple SQLite DB for storing past requests and "gold" answers.
- utils.py — helper functions (similarity, prompt building, caching).
- main.py — entrypoint to start the bot.
- .env.example — example environment variables.