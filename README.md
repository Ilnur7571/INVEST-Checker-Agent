# 🤖 INVEST-Checker Bot (GigaChat)

AI-агент для анализа User Stories по критериям INVEST через Telegram-бота с использованием GigaChat API.

## 🚀 Возможности

- **🔍 Анализ INVEST** - автоматическая проверка User Stories по 6 критериям
- **🚀 Улучшение историй** - AI-помощник для исправления и оптимизации
- **💾 База знаний** - хранение и поиск по истории запросов
- **📊 Статистика** - мониторинг использования и эффективности
- **📤 Экспорт** - выгрузка результатов в TXT/CSV форматах
- **⚡ Оптимизация** - кэширование, асинхронность, circuit breaker

## 🛠 Технологии

- **Python 3.8+** - основной язык
- **python-telegram-bot 20.x** - фреймворк для бота
- **GigaChat API** - AI-модель для анализа
- **SQLite** - база данных
- **RapidFuzz** - поиск похожих историй
- **HTTpx** - асинхронные HTTP-запросы

## 📦 Быстрый старт

### 1. Клонирование и настройка
```bash
git clone <repository-url>
cd tg_bot_final
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
