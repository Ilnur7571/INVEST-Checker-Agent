import io
import logging
import re

from bot import LRUCache
from datetime import datetime
from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from telegram.error import BadRequest
from keyboards import (
    main_menu_keyboard,
    help_keyboard,
    navigation_keyboard,
    similar_stories_keyboard,
    analysis_result_keyboard,
    improved_story_keyboard,
    export_menu_keyboard,
    improvement_history_keyboard,
    database_keyboard,
    database_story_keyboard,
)

from utils import (
    normalize_text,
    build_invest_prompt,
    build_fix_prompt,
    build_improve_prompt,
    extract_score_from_analysis,
    safe_truncate_text,
    should_show_add_to_db_button,
    format_analysis_for_display,
)

logger = logging.getLogger("handlers")

# Кэш для валидации User Stories
_user_story_cache = LRUCache(max_size=1000, ttl=3600)    #Dict[str, bool] = {}

# Класс для хранения цепочки улучшений
class ImprovementChain:
    def __init__(self):
        self.versions = []

    def add_version(self, story: str, analysis: str = None, timestamp: str = None):
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        self.versions.append({
            'story': story,
            'analysis': analysis,
            'timestamp': timestamp,
            'version': len(self.versions) + 1
        })

    def get_initial(self):
        return self.versions[0] if self.versions else None

    def get_latest(self):
        return self.versions[-1] if self.versions else None

    def get_all_versions(self):
        return self.versions

    def get_version_count(self):
        return len(self.versions)

# Состояния бота
class BotState:
    MAIN_MENU = "main_menu"
    ANALYZING = "analyzing"
    SHOWING_RESULTS = "showing_results"
    SHOWING_SIMILAR = "showing_similar"
    IMPROVING = "improving"
    EXPORT_MENU = "export_menu"
    HELP = "help"
    STATS = "stats"
    SHOWING_HISTORY = "showing_history"
    SHOWING_DATABASE = "showing_database"
    SHOWING_STORY_DETAILS = "showing_story_details"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start"""
    try:
        user_id = update.effective_user.id

        # Инициализация истории пользователя в bot_data
        if 'user_history' not in context.bot_data:
            context.bot_data['user_history'] = {}
        if 'stats' not in context.bot_data:
            context.bot_data['stats'] = {
                'total_messages': 0,
                'user_sessions': 0
            }

        if user_id not in context.bot_data['user_history']:
            context.bot_data['user_history'][user_id] = []
            context.bot_data['stats']['user_sessions'] += 1

        welcome_text = (
            "🤖 **Добро пожаловать в INVEST-Checker!**\n\n"
            "Я помогу проанализировать ваши User Stories по критериям INVEST:\n\n"
            "• *I*ndependent (независимая)\n"
            "• *N*egotiable (обсуждаемая)\n"
            "• *V*aluable (ценная)\n"
            "• *E*stimable (оцениваемая)\n"
            "• *S*mall (маленькая)\n"
            "• *T*estable (тестируемая)\n\n"
            "Отправьте User Story в формате:\n"
            "_Как <роль>, я хочу <действие>, чтобы <цель>_"
        )

        await update.message.reply_text(
            welcome_text,
            reply_markup=main_menu_keyboard(),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in start handler: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка. Попробуйте позже.",
            reply_markup=main_menu_keyboard()
        )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help"""
    try:
        help_text = (
            "📖 **Помощь по INVEST-Checker**\n\n"
            "*INVEST критерии:*\n"
            "• *I* - Независимая (Independent)\n"
            "• *N* - Обсуждаемая (Negotiable) \n"
            "• *V* - Ценная (Valuable)\n"
            "• *E* - Оцениваемая (Estimable)\n"
            "• *S* - Маленькая (Small)\n"
            "• *T* - Тестируемая (Testable)\n\n"
            "*Формат User Story:*\n"
            "```\nКак <роль>, я хочу <действие>, чтобы <цель>\n```\n"
            "*Пример:*\n"
            "_Как пользователь, я хочу регистрироваться по email, чтобы получить доступ к личному кабинету._\n\n"
            "*Доступные команды:*\n"
            "/start - Начать работу\n"
            "/help - Эта справка\n"
            "/stats - Статистика бота"
        )

        await update.message.reply_text(
            help_text,
            reply_markup=help_keyboard(),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error in help handler: {e}")
        await update.message.reply_text(
            "❌ Ошибка при показе справки.",
            reply_markup=navigation_keyboard()
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /stats"""
    try:
        bot = context.bot_data['bot']
        db = context.bot_data['db']
        llm_client = context.bot_data['llm_client']
        
        stats_data = await bot.get_bot_stats(db, llm_client)

        stats_text = "📊 *Статистика системы:*\n\n"

        if 'error' in stats_data:
            stats_text += "❌ Ошибка при получении статистики"
        else:
            stats_text += (
                f"• ⏱ Аптайм: {stats_data.get('uptime', 'N/A')}\n"
                f"• 👥 Пользователей: {stats_data.get('active_users', 0)}\n"
                f"• 📚 Всего историй: {stats_data.get('total_stories', 0)}\n"
                f"• ⭐ Золотых историй: {stats_data.get('golden_stories', 0)}\n"
                f"• 📈 Общее использование: {stats_data.get('total_messages', 0)}\n"
                f"• 🎯 Средний score: {stats_data.get('average_score', 0):.2f}\n"
                f"• 💾 Эффективность кэша: {stats_data.get('cache_hit_rate', 0):.1%}"
            )

        # Получаем статистику LLM клиента
        llm_stats = llm_client.get_stats()
        stats_text += "\n\n🤖 *Статистика LLM:*\n"
        stats_text += f"• 📞 Всего запросов: {llm_stats.get('total_requests', 0)}\n"
        stats_text += f"• 💾 Кэш токенов: {llm_stats.get('token_cache_hit_rate', 0):.1%}\n"
        stats_text += f"• ⚡ Кэш ответов: {llm_stats.get('response_cache_size', 0)} записей\n"
        stats_text += f"• 📨 Токены отправлено: {llm_stats.get('total_tokens_sent', 0)}\n"
        stats_text += f"• 📩 Токены получено: {llm_stats.get('total_tokens_received', 0)}"

        # Определяем, откуда пришел запрос
        if update.message:
            await update.message.reply_text(
                stats_text,
                reply_markup=navigation_keyboard(),
                parse_mode='Markdown'
            )
        elif update.callback_query:
            await update.callback_query.edit_message_text(
                stats_text,
                reply_markup=navigation_keyboard(),
                parse_mode='Markdown'
            )

    except Exception as e:
        logger.error(f"Error in stats handler: {e}")
        error_msg = "❌ Ошибка при получении статистики."

        if update.message:
            await update.message.reply_text(error_msg, reply_markup=navigation_keyboard())
        elif update.callback_query:
            await update.callback_query.edit_message_text(error_msg, reply_markup=navigation_keyboard())

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик текстовых сообщений"""
    try:
        text = update.message.text.strip()

        # Сохраняем исходную историю
        context.user_data['initial_story'] = text

        # Проверяем кэш бота перед анализом
        cache_key = f"analysis_{hash(text.lower().strip())}"
        cached_analysis = context.bot_data.get('analysis_cache', {}).get(cache_key)

        if cached_analysis:
            # Увеличиваем счетчик попаданий в кэш
            if 'bot' in context.bot_data:
                context.bot_data['bot'].stats['cache_hits'] += 1
            logger.info("Using cached analysis for user story")
            # Используем кэшированный анализ
            context.user_data['last_analysis'] = cached_analysis
            keyboard = analysis_result_keyboard(
                show_add_to_db=should_show_add_to_db_button(cached_analysis['analysis']),
                has_improvement_history='improvement_chain' in context.user_data,
                analysis_text=cached_analysis['analysis']
            )

            response_text = format_analysis_for_display(cached_analysis['analysis'], text)
            await update.message.reply_text(
                response_text,
                reply_markup=keyboard,
                parse_mode='Markdown'
            )
            return

        # Увеличиваем счетчик промахов кэша
        if 'bot' in context.bot_data:
            context.bot_data['bot'].stats['cache_misses'] += 1

        # Более информативное сообщение о невалидности
        if not _is_valid_user_story(text):
            # Проверяем, похоже ли хоть немного на User Story
            text_lower = text.lower()
            has_structure = any(word in text_lower for word in ["как", "хочу", "чтобы", "что бы", "мне нужно"])

            if has_structure and len(text) > 15:
                # Если похоже, но не прошло валидацию - все равно анализируем
                await update.message.reply_text(
                    "⚠️ Формулировка немного нестандартная, но я попробую проанализировать...",
                    reply_markup=main_menu_keyboard()
                )
                await _analyze_user_story(update, context, text)
            else:
                await update.message.reply_text(
                    "❌ Это не похоже на User Story.\n\n*Правильный формат:*\n"
                    "_Как <роль>, я хочу <действие>, чтобы <цель>_\n\n"
                    "*Пример:*\n"
                    "_Как пользователь, я хочу регистрироваться, чтобы получить доступ к системе._\n\n"
                    "*Возможные варианты:*\n"
                    "• Как менеджер, мне нужно видеть отчеты, чтобы принимать решения\n"
                    "• Как клиент, я могу фильтровать товары, чтобы найти нужный",
                    reply_markup=main_menu_keyboard(),
                    parse_mode='Markdown'
                )
        else:
            await _analyze_user_story(update, context, text)

    except Exception as e:
        logger.error(f"Error in message handler: {e}")
        await update.message.reply_text(
            "❌ Ошибка обработки сообщения. Попробуйте позже или упростите формулировку.",
            reply_markup=navigation_keyboard()
        )

def _is_valid_user_story(text: str) -> bool:
    """Проверка валидности User Story с улучшенной логикой и кэшированием"""
    if len(text) > 2000:  # увеличили лимит
        return False

    # Проверка кэша - используем LRUCache вместо простого словаря
    cache_key = text.lower().strip()
    cached_result = _user_story_cache.get(cache_key)
    if cached_result is not None:
        return cached_result

    # Более гибкая проверка паттерна
    patterns = [
        r"^как\s+.+?,\s*я\s+хочу\s+.+?,\s*чтобы\s+.+?$",  # оригинальный
        r"^как\s+.+?,\s*я\s+хочу\s+.+?,\s*что\s+бы\s+.+?$",  # с опечаткой
        r"^как\s+.+?,\s*мне\s+нужно\s+.+?,\s*чтобы\s+.+?$",  # альтернативная формулировка
        r"^как\s+.+?,\s*я\s+могу\s+.+?,\s*чтобы\s+.+?$",  # еще вариант
    ]

    text_lower = text.lower().strip()
    is_valid = any(re.match(pattern, text_lower) for pattern in patterns)

    # Если не прошло по паттерну, но содержит ключевые слова - считаем валидным
    if not is_valid:
        keywords = ["как", "хочу", "чтобы"]
        has_keywords = all(keyword in text_lower for keyword in keywords) or \
                     ("как" in text_lower and "хочу" in text_lower and "что бы" in text_lower)

        if has_keywords and len(text_lower) > 20:  # минимальная длина
            is_valid = True

    # Сохраняем в кэш (LRUCache автоматически управляет размером и TTL)
    _user_story_cache.set(cache_key, is_valid)

    return is_valid

async def _analyze_user_story(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             user_story: str, show_add_to_db: bool = False,
                             is_improved: bool = False, is_callback: bool = False,
                             skip_similar_search: bool = False) -> None:
    """Анализ User Story с улучшенным поиском похожих историй"""
    try:
        db = context.bot_data['db']
        llm_client = context.bot_data['llm_client']
        user_id = update.effective_user.id

        # Проверяем длину истории
        if len(user_story) > 2000:
            error_msg = "❌ Слишком длинная история. Максимум 2000 символов."
            if is_callback:
                await update.callback_query.edit_message_text(error_msg, reply_markup=navigation_keyboard())
            else:
                await update.message.reply_text(error_msg, reply_markup=navigation_keyboard())
            return

        norm = normalize_text(user_story)
        logger.info(f"Analyzing user story: {user_story[:100]}...")

        # Если не нужно пропускать поиск похожих (обычный сценарий)
        similar_high = []
        similar_medium = []
        similar_low = []
        
        if not skip_similar_search:
            # Ищем похожие истории с разными порогами
            similar_high = await db.find_similar(user_story, threshold=0.95)  # Очень похожие
            similar_medium = await db.find_similar(user_story, threshold=0.75)  # Похожие
            similar_low = await db.find_similar(user_story, threshold=0.60)  # Слабые совпадения

            logger.info(f"Search results - High: {len(similar_high)}, Medium: {len(similar_medium)}, Low: {len(similar_low)}")

            # Если нашли ИДЕНТИЧНЫЕ истории (95%+), используем их без LLM
            if similar_high and not is_improved:
                best_match = similar_high[0]  # Берем самую похожую
                story, answer, ratio, score = best_match

                logger.info(f"Found highly similar story: {ratio:.1%} - {story[:50]}...")

                # Увеличиваем счетчик использования
                await db.increment_usage_count(normalize_text(story))

                # Форматируем ответ БЕЗ дублирования User Story
                formatted_answer = format_analysis_for_display(answer)

                response_text = (
                    f"🎯 **Найдена похожая история в базе** ({ratio:.0%} совпадение)\n\n"
                    f"**User Story:**\n_{story}_\n\n{formatted_answer}"
                )

                # Для точных совпадений НЕ показываем кнопку добавления (уже в базе)
                keyboard = analysis_result_keyboard(
                    show_add_to_db=False,
                    has_improvement_history='improvement_chain' in context.user_data,
                    analysis_text=formatted_answer
                )

                if is_callback:
                    await update.callback_query.edit_message_text(
                        response_text,
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )
                else:
                    await update.message.reply_text(
                        response_text,
                        reply_markup=keyboard,
                        parse_mode='Markdown'
                    )

                # Сохраняем в историю и кэш
                _add_to_user_history(context, user_id, story, formatted_answer)
                _cache_analysis(context, story, {
                    'story': story,
                    'analysis': formatted_answer,
                    'timestamp': datetime.now().isoformat()
                })

                context.user_data['last_analysis'] = {
                    'story': story,
                    'analysis': formatted_answer,
                    'timestamp': datetime.now().isoformat()
                }
                return

            # Если есть несколько похожих историй (75%+), показываем их для выбора
            elif similar_medium and not is_improved:
                logger.info(f"Found {len(similar_medium)} similar stories, showing selection")
                
                # Берем топ-3 самые похожие истории
                top_similar = similar_medium[:3]
                
                keyboard = similar_stories_keyboard(top_similar, user_story)
                message_text = (
                    f"🔍 **Найдены похожие истории в базе** (сходство от {top_similar[0][2]:.0%}):\n\n"
                    "Вы можете выбрать одну из них или продолжить с вашим вариантом:"
                )

                if is_callback:
                    await update.callback_query.edit_message_text(
                        message_text,
                        reply_markup=keyboard
                    )
                else:
                    await update.message.reply_text(
                        message_text,
                        reply_markup=keyboard
                    )

                context.user_data['similar_stories'] = top_similar
                context.user_data['original'] = user_story
                return

            # Если есть слабые совпадения (60%+), предлагаем улучшить или использовать свой вариант
            elif similar_low and not is_improved:
                logger.info(f"Found {len(similar_low)} weak matches, offering improvement")
                
                keyboard = similar_stories_keyboard(similar_low[:2], user_story)
                message_text = (
                    f"🔍 **Найдены частично похожие истории** (сходство от {similar_low[0][2]:.0%}):\n\n"
                    "Вы можете выбрать одну из них, улучшить вашу историю через ИИ или использовать свой вариант:"
                )

                if is_callback:
                    await update.callback_query.edit_message_text(
                        message_text,
                        reply_markup=keyboard
                    )
                else:
                    await update.message.reply_text(
                        message_text,
                        reply_markup=keyboard
                    )

                context.user_data['similar_stories'] = similar_low[:2]
                context.user_data['original'] = user_story
                return

        # Только если нет похожих в базе ИЛИ мы пропустили поиск (use_own) - идем в LLM
        logger.info("No similar stories found or skipping search, using LLM analysis")
        analysis_msg = None
        if is_callback:
            await update.callback_query.edit_message_text("🔍 Анализирую историю...")
        else:
            analysis_msg = await update.message.reply_text("🔍 Анализирую историю...")

        try:
            # Анализ через LLM
            prompt = build_invest_prompt(user_story)
            response = await llm_client.get_chat_completion(prompt)

            # УЛУЧШЕННАЯ ОБРАБОТКА ОТВЕТА ОТ LLM
            answer_text = ""
            if isinstance(response, tuple) and len(response) >= 1:
                answer_text = response[0]
            elif isinstance(response, str):
                answer_text = response
            else:
                # Если ответ не tuple и не str, преобразуем в строку
                answer_text = str(response)
            
            # Дополнительная проверка и очистка
            if not isinstance(answer_text, str):
                logger.warning(f"Unexpected response type from LLM: {type(answer_text)}")
                answer_text = str(answer_text)
            
            # Убираем возможные лишние символы
            answer_text = answer_text.strip()

            analysis = format_analysis_for_display(answer_text, user_story)

            # Определяем, показывать ли кнопку добавления в базу
            should_show_add_button = should_show_add_to_db_button(analysis, is_improved)

            keyboard = analysis_result_keyboard(
                show_add_to_db=should_show_add_button,
                has_improvement_history='improvement_chain' in context.user_data,
                analysis_text=analysis
            )

            if is_callback:
                await update.callback_query.edit_message_text(
                    analysis,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )
            else:
                await analysis_msg.edit_text(
                    analysis,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )

            # Сохраняем в историю и кэш
            _add_to_user_history(context, user_id, user_story, analysis)
            _cache_analysis(context, user_story, {
                'story': user_story,
                'analysis': analysis,
                'timestamp': datetime.now().isoformat()
            })

            context.user_data['last_analysis'] = {
                'story': user_story,
                'analysis': analysis,
                'timestamp': datetime.now().isoformat()
            }

            # Автоматически добавляем улучшенные истории в golden
            if is_improved and extract_score_from_analysis(analysis) >= 4:
                await db.add_example(
                    user_story, norm, analysis, is_golden=True, score=extract_score_from_analysis(analysis)
                )
                logger.info(f"Added improved story to golden examples: {user_story[:50]}...")

        except Exception as e:
            logger.error(f"Error in LLM analysis: {e}")
            error_msg = "❌ Ошибка при анализе через GigaChat. Проверьте подключение к интернету."
            if is_callback:
                await update.callback_query.edit_message_text(error_msg, reply_markup=navigation_keyboard())
            else:
                await analysis_msg.edit_text(error_msg, reply_markup=navigation_keyboard())

    except Exception as e:
        logger.error(f"Error in story analysis: {e}")
        error_msg = "❌ Ошибка при анализе истории. Попробуйте позже или упростите формулировку."

        if is_callback:
            await update.callback_query.edit_message_text(error_msg, reply_markup=navigation_keyboard())
        else:
            await update.message.reply_text(error_msg, reply_markup=navigation_keyboard())

        logger.error(f"Error in story analysis: {e}")
        error_msg = "❌ Ошибка при анализе истории. Попробуйте позже или упростите формулировку."

        if is_callback:
            await update.callback_query.edit_message_text(error_msg, reply_markup=navigation_keyboard())
        else:
            await update.message.reply_text(error_msg, reply_markup=navigation_keyboard())

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик callback запросов с улучшенной навигацией и кэшированием"""
    query = update.callback_query
    if not query:
        return  #если нет callback_query выходим

    data = query.data
    if not data:
        return  #если нет данных выходим

    try:
        await query.answer()
    except BadRequest as e:
        if "Query is too old" in str(e):
            logger.warning(f"Ignoring old callback query: {e}")
            return
        else:
            logger.error(f"Error in callback answer: {e}")

    llm_client = context.bot_data['llm_client']
    db = context.bot_data['db']

    try:
        # Сохраняем предыдущее состояние
        previous_state = context.user_data.get('current_state')

        if data == "analyze_invest":
            context.user_data['current_state'] = BotState.ANALYZING
            await query.edit_message_text(
                "✍️ *Отправьте User Story для анализа*\n\nФормат: _Как <роль>, я хочу <действие>, чтобы <цель>_",
                reply_markup=navigation_keyboard(previous_state),
                parse_mode='Markdown'
            )

        elif data.startswith("use_similar_"):
            context.user_data['current_state'] = BotState.SHOWING_RESULTS
            index = int(data.split('_')[-1])
            similar = context.user_data.get('similar_stories', [])

            if index < len(similar):
                story, answer, ratio, score = similar[index]

                # Увеличиваем счетчик использования
                await db.increment_usage_count(normalize_text(story))

                # Форматируем ответ
                formatted_answer = format_analysis_for_display(answer)

                response_text = (
                    f"📚 *Использую похожую историю* (сходство: {ratio:.0%})\n\n"
                    f"**User Story:**\n_{story}_\n\n{formatted_answer}"
                )

                keyboard = analysis_result_keyboard(
                    show_add_to_db=False,  # История уже в базе!
                    has_improvement_history='improvement_chain' in context.user_data,
                    analysis_text=formatted_answer
                )

                await query.edit_message_text(
                    response_text,
                    reply_markup=keyboard,
                    parse_mode='Markdown'
                )

                # Сохраняем в историю и кэш
                user_id = update.effective_user.id
                _add_to_user_history(context, user_id, story, formatted_answer)
                _cache_analysis(context, story, {
                    'story': story,
                    'analysis': formatted_answer,
                    'timestamp': datetime.now().isoformat()
                })

                context.user_data['last_analysis'] = {
                    'story': story,
                    'analysis': formatted_answer,
                    'timestamp': datetime.now().isoformat()
                }

            else:
                await query.edit_message_text(
                    "❌ Ошибка: некорректный выбор.",
                    reply_markup=navigation_keyboard(previous_state)
                )

        elif data == "fix_with_llm":
            context.user_data['current_state'] = BotState.IMPROVING
            original = context.user_data.get('original')
            if not original:
                await query.edit_message_text(
                    "❌ Нет исходной истории для исправления.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return

            prompt = build_fix_prompt(original)
            response = await llm_client.get_chat_completion(prompt)
            fixed = response[0].strip()

            await query.edit_message_text(
                f"✨ *Исправленная версия:*\n\n_{fixed}_\n\nХотите проанализировать исправленную версию?",
                reply_markup=improved_story_keyboard(previous_state=BotState.SHOWING_SIMILAR),
                parse_mode='Markdown'
            )
            context.user_data['llm_fix'] = fixed
            context.user_data['pending_text'] = fixed

        elif data == "use_own":
            context.user_data['current_state'] = BotState.ANALYZING
            original = context.user_data.get('original')
            if not original:
                await query.edit_message_text(
                    "❌ Нет исходной истории.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return
            await _analyze_user_story(update, context, original, show_add_to_db=True, is_callback=True, skip_similar_search=True)

        elif data == "improve_story":
            context.user_data['current_state'] = BotState.IMPROVING
            pending = (context.user_data.get('pending_text') or
                      context.user_data.get('original') or
                      context.user_data.get('last_analysis', {}).get('story'))

            if not pending:
                await query.edit_message_text(
                    "❌ Нет истории для улучшения.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return

            # Инициализируем цепочку улучшений если ее нет
            if 'improvement_chain' not in context.user_data:
                context.user_data['improvement_chain'] = ImprovementChain()

                # Добавляем исходную версию если есть последний анализ
                last_analysis = context.user_data.get('last_analysis')
                if last_analysis:
                    context.user_data['improvement_chain'].add_version(
                        last_analysis['story'],
                        last_analysis['analysis'],
                        last_analysis.get('timestamp')
                    )
                else:
                    #если нет анализа но есть исходный текст добавляем его как версию 1
                    initial_story = context.user_data.get('initial_story')
                    if initial_story:
                        context.user_data['improvement_chain'].add_version(
                            initial_story,
                            "Исходная версия - требует анализа",
                            datetime.now().isoformat()
                        )

            try:
                # Получаем текущий анализ для контекста
                current_analysis = None
                last_analysis = context.user_data.get('last_analysis')
                if last_analysis:
                    current_analysis = last_analysis.get('analysis')

                prompt = build_improve_prompt(pending, current_analysis)
                response = await llm_client.get_chat_completion(prompt)
                improved = response[0].strip()

                # Сохраняем улучшенную версию
                context.user_data['improvement_chain'].add_version(improved, "Улучшенная версия - требует анализа")

                # Создаем информативное сообщение с историей
                chain = context.user_data['improvement_chain']
                initial = chain.get_initial()
                latest = chain.get_latest()

                message_text = "🔄 *Цепочка улучшений*\n\n"

                if initial:
                    message_text += f"📝 *Исходная версия:*\n_{initial['story']}_\n\n"
                    if 'analysis' in initial and initial['analysis']:
                        # Извлекаем оценку из анализа
                        score_match = re.search(r'Оценка:\s*(\d/6)', initial['analysis'])
                        if score_match:
                            message_text += f"📊 **Исходная оценка:** {score_match.group(1)}\n\n"

                message_text += f"🚀 *Улучшенная версия (v{latest['version']}):*\n_{latest['story']}_\n\n"
                message_text += "Хотите проанализировать улучшенную версию?"

                await query.edit_message_text(
                    message_text,
                    reply_markup=improved_story_keyboard(previous_state=BotState.SHOWING_RESULTS),
                    parse_mode='Markdown'
                )
                context.user_data['improved_story'] = improved
                context.user_data['pending_text'] = improved

            except Exception as e:
                logger.error(f"Error improving story: {e}")
                await query.edit_message_text(
                    "❌ Ошибка при улучшении истории. Попробуйте позже.",
                    reply_markup=navigation_keyboard(previous_state)
                )

        elif data == "analyze_improved":
            context.user_data['current_state'] = BotState.ANALYZING
            improved = context.user_data.get('improved_story')
            if not improved:
                await query.edit_message_text(
                    "❌ Нет улучшенной истории для анализа.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return
            await _analyze_user_story(update, context, improved, show_add_to_db=True, is_improved=True, is_callback=True)

        elif data == "improve_again":
            context.user_data['current_state'] = BotState.IMPROVING
            current = (context.user_data.get('improved_story') or
                      context.user_data.get('pending_text'))

            if not current:
                await query.edit_message_text(
                    "❌ Нет истории для улучшения.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return

            context.user_data['pending_text'] = current
            prompt = build_improve_prompt(current)
            response = await llm_client.get_chat_completion(prompt)
            improved = response[0].strip()

            # Сохраняем новую улучшенную версию в цепочку
            if 'improvement_chain' in context.user_data:
                context.user_data['improvement_chain'].add_version(
                    improved,
                    "Улучшенная версия - требует анализа"
                )

            await query.edit_message_text(
                f"🚀 *Улучшенная версия:*\n\n_{improved}_\n\nХотите проанализировать улучшенную версию?",
                reply_markup=improved_story_keyboard(previous_state=BotState.IMPROVING),
                parse_mode='Markdown'
            )
            context.user_data['improved_story'] = improved

        elif data == "show_improvement_history":
            context.user_data['current_state'] = BotState.SHOWING_HISTORY

            chain = context.user_data.get('improvement_chain')
            if not chain or len(chain.versions) < 1:
                await query.edit_message_text(
                    "❌ Нет истории улучшений для показа.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return

            message_text = "📋 *История улучшений User Story*\n\n"

            # Показываем ВСЕ версии, начиная с первой
            for version in chain.versions:
                message_text += f"*Версия {version['version']}:*\n"
                message_text += f"_{version['story']}_\n"

                if version.get('analysis') and version['analysis'] != "Улучшенная версия - требует анализа":
                    # Извлекаем оценку из анализа
                    score_match = re.search(r'Оценка:\s*(\d/6)', version['analysis'])
                    if score_match:
                        message_text += f"📊 **Оценка:** {score_match.group(1)}\n"

                message_text += "\n" + "═" * 40 + "\n\n"

            message_text += "Вы можете улучшить историю еще раз или проанализировать последнюю версию."

            # Обрезаем текст если слишком длинный
            message_text = safe_truncate_text(message_text)

            await query.edit_message_text(
                message_text,
                reply_markup=improvement_history_keyboard(previous_state),
                parse_mode='Markdown'
            )

        elif data == "export_txt":
            context.user_data['current_state'] = BotState.SHOWING_RESULTS
            last_analysis = context.user_data.get('last_analysis')
            if not last_analysis:
                await query.edit_message_text(
                    "❌ Нет данных для экспорта.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return

            content = f"User Story:\n{last_analysis['story']}\n\nАнализ INVEST:\n{last_analysis['analysis']}"
            if 'timestamp' in last_analysis:
                content += f"\n\nДата анализа: {last_analysis['timestamp']}"

            bio = io.BytesIO(content.encode('utf-8'))
            bio.name = 'analysis.txt'

            await query.message.reply_document(
                document=InputFile(bio, filename='INVEST_analysis.txt'),
                caption="📄 Экспорт анализа в TXT"
            )
            bio.close()

            # Возвращаемся к результатам анализа
            await query.edit_message_text(
                f"**User Story:**\n_{last_analysis['story']}_\n\n{last_analysis['analysis']}",
                reply_markup=analysis_result_keyboard(
                    show_add_to_db=True,
                    has_improvement_history='improvement_chain' in context.user_data
                ),
                parse_mode='Markdown'
            )

        elif data == "export_csv":
            context.user_data['current_state'] = BotState.SHOWING_RESULTS
            last_analysis = context.user_data.get('last_analysis')
            if not last_analysis:
                await query.edit_message_text(
                    "❌ Нет данных для экспорта.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return

            # Экранируем кавычки для CSV
            story_escaped = last_analysis['story'].replace('"', '""')
            analysis_escaped = last_analysis['analysis'].replace('"', '""')

            content = f'"{story_escaped}";"{analysis_escaped}"'
            bio = io.BytesIO(content.encode('utf-8'))
            bio.name = 'analysis.csv'

            await query.message.reply_document(
                document=InputFile(bio, filename='INVEST_analysis.csv'),
                caption="📊 Экспорт анализа в CSV"
            )
            bio.close()

            # Возвращаемся к результатам анализа
            await query.edit_message_text(
                f"**User Story:**\n_{last_analysis['story']}_\n\n{last_analysis['analysis']}",
                reply_markup=analysis_result_keyboard(
                    show_add_to_db=True,
                    has_improvement_history='improvement_chain' in context.user_data
                ),
                parse_mode='Markdown'
            )

        elif data == "export_improved":
            context.user_data['current_state'] = BotState.IMPROVING
            improved = context.user_data.get('improved_story')
            if not improved:
                await query.edit_message_text(
                    "❌ Нет улучшенной истории для экспорта.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return

            content = f"Улучшенная User Story:\n{improved}\n\n✨ Сгенерировано INVEST-Checker"
            bio = io.BytesIO(content.encode('utf-8'))
            bio.name = 'improved_user_story.txt'

            await query.message.reply_document(
                document=InputFile(bio, filename='improved_user_story.txt'),
                caption="🚀 Экспорт улучшенной истории"
            )
            bio.close()

            # Возвращаемся к улучшенной истории
            await query.edit_message_text(
                f"🚀 **Улучшенная версия:**\n\n_{improved}_\n\nХотите проанализировать улучшенную версию?",
                reply_markup=improved_story_keyboard(previous_state=BotState.IMPROVING),
                parse_mode='Markdown'
            )

        elif data == "add_to_db":
            context.user_data['current_state'] = BotState.SHOWING_RESULTS
            last_analysis = context.user_data.get('last_analysis')
            if not last_analysis:
                await query.edit_message_text(
                    "❌ Нет данных для добавления в базу.",
                    reply_markup=navigation_keyboard(previous_state)
                )
                return

            # Используем исходную историю из цепочки улучшений если есть
            story_to_add = last_analysis['story']
            chain = context.user_data.get('improvement_chain')
            if chain and chain.get_initial():
                story_to_add = chain.get_initial()['story']  # Добавляем исходную версию

            norm = normalize_text(story_to_add)
            await db.add_example(
                story_to_add, norm, last_analysis['analysis'], is_golden=False, score=0
            )

            await query.edit_message_text(
                "✅ История добавлена в базу данных!",
                reply_markup=navigation_keyboard(BotState.SHOWING_RESULTS)
            )

        elif data == "back":
            """Улучшенная обработка кнопки Назад с проверкой состояний"""
            try:
                # Получаем предыдущее состояние
                previous_state = context.user_data.get('current_state')

                # Если состояние не определено, возвращаем в главное меню
                if not previous_state:
                    await query.edit_message_text(
                        "🏠 **Главное меню**\n\nОтправьте User Story для анализа или выберите действие:",
                        reply_markup=main_menu_keyboard()
                    )
                    context.user_data['current_state'] = BotState.MAIN_MENU
                    return

                # Обработка разных предыдущих состояний
                if previous_state == BotState.SHOWING_SIMILAR:
                    similar_stories = context.user_data.get('similar_stories', [])
                    original = context.user_data.get('original', '')

                    if similar_stories:
                        await query.edit_message_text(
                            "🔍 **Найдены похожие истории в базе:**\n\nВы можете выбрать одну из них или продолжить с вашим вариантом:",
                            reply_markup=similar_stories_keyboard(similar_stories, original)
                        )
                        context.user_data['current_state'] = BotState.SHOWING_SIMILAR
                    else:
                        await query.edit_message_text(
                            "🏠 **Главное меню**\n\nОтправьте User Story для анализа или выберите действие:",
                            reply_markup=main_menu_keyboard()
                        )
                        context.user_data['current_state'] = BotState.MAIN_MENU

                elif previous_state == BotState.SHOWING_RESULTS:
                    last_analysis = context.user_data.get('last_analysis')
                    if last_analysis:
                        # Добавляем небольшое изменение в текст, чтобы избежать ошибки "not modified"
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        response_text = (
                            f"📊 **Результат анализа** ({timestamp})\n\n"
                            f"**User Story:**\n_{last_analysis['story']}_\n\n"
                            f"{last_analysis['analysis']}"
                        )

                        # Определяем, показывать ли кнопку добавления в базу
                        should_show_add_button = should_show_add_to_db_button(
                            last_analysis['analysis'],
                            context.user_data.get('is_improved', False)
                        )

                        await query.edit_message_text(
                            response_text,
                            reply_markup=analysis_result_keyboard(
                                show_add_to_db=should_show_add_button,
                                has_improvement_history='improvement_chain' in context.user_data,
                                analysis_text=last_analysis['analysis']
                            ),
                            parse_mode='Markdown'
                        )
                        context.user_data['current_state'] = BotState.SHOWING_RESULTS
                    else:
                        await query.edit_message_text(
                            "🏠 **Главное меню**\n\nОтправьте User Story для анализа или выберите действие:",
                            reply_markup=main_menu_keyboard()
                        )
                        context.user_data['current_state'] = BotState.MAIN_MENU

                elif previous_state == BotState.IMPROVING:
                    improved = context.user_data.get('improved_story')
                    if improved:
                        # Добавляем timestamp к сообщению, чтобы избежать дублирования
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        await query.edit_message_text(
                            f"🚀 **Улучшенная версия** ({timestamp})\n\n_{improved}_\n\nХотите проанализировать улучшенную версию?",
                            reply_markup=improved_story_keyboard(previous_state=BotState.SHOWING_RESULTS),
                            parse_mode='Markdown'
                        )
                        context.user_data['current_state'] = BotState.IMPROVING
                    else:
                        await query.edit_message_text(
                            "🏠 **Главное меню**\n\nОтправьте User Story для анализа или выберите действие:",
                            reply_markup=main_menu_keyboard()
                        )
                        context.user_data['current_state'] = BotState.MAIN_MENU

                elif previous_state == BotState.EXPORT_MENU:
                    last_analysis = context.user_data.get('last_analysis')
                    if last_analysis:
                        # Добавляем небольшое изменение в форматирование
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        await query.edit_message_text(
                            f"📊 **Результат анализа** ({timestamp})\n\n"
                            f"**User Story:**\n_{last_analysis['story']}_\n\n"
                            f"{last_analysis['analysis']}",
                            reply_markup=analysis_result_keyboard(
                                show_add_to_db=True,
                                has_improvement_history='improvement_chain' in context.user_data
                            ),
                            parse_mode='Markdown'
                        )
                        context.user_data['current_state'] = BotState.SHOWING_RESULTS
                    else:
                        await query.edit_message_text(
                            "🏠 **Главное меню**\n\nОтправьте User Story для анализа или выберите действие:",
                            reply_markup=main_menu_keyboard()
                        )
                        context.user_data['current_state'] = BotState.MAIN_MENU

                elif previous_state == BotState.SHOWING_HISTORY:
                    # Возврат к истории улучшений
                    chain = context.user_data.get('improvement_chain')
                    if chain and len(chain.versions) >= 2:
                        message_text = "📋 **История улучшений User Story**\n\n"
                        for i, version in enumerate(chain.versions):
                            message_text += f"**Версия {version['version']}:**\n"
                            message_text += f"_{version['story']}_\n"
                            if 'analysis' in version and version['analysis']:
                                score_match = re.search(r'Оценка:\s*(\d/6)', version['analysis'])
                                if score_match:
                                    message_text += f"📊 Оценка: {score_match.group(1)}\n"
                            message_text += "\n" + "═" * 30 + "\n\n"
                        message_text += "Вы можете улучшить историю еще раз или проанализировать последнюю версию."

                        await query.edit_message_text(
                            message_text,
                            reply_markup=improvement_history_keyboard(BotState.SHOWING_RESULTS),
                            parse_mode='Markdown'
                        )
                        context.user_data['current_state'] = BotState.SHOWING_HISTORY
                    else:
                        # Если истории нет, возвращаем к результатам
                        await query.edit_message_text(
                            "❌ Нет истории улучшений для показа.",
                            reply_markup=navigation_keyboard(BotState.SHOWING_RESULTS)
                        )
                        context.user_data['current_state'] = BotState.SHOWING_RESULTS

                elif previous_state == BotState.SHOWING_DATABASE:
                    # Возврат к просмотру базы данных
                    current_page = context.user_data.get('current_db_page', 0)
                    await show_database(update, context, current_page)

                elif previous_state == BotState.SHOWING_STORY_DETAILS:
                    # Возврат из деталей истории к списку
                    current_page = context.user_data.get('current_db_page', 0)
                    await show_database(update, context, current_page)

                elif previous_state == BotState.EXPORT_MENU:
                    last_analysis = context.user_data.get('last_analysis')
                    if last_analysis:
                        # Используем безопасное форматирование
                        response_text = format_analysis_for_display(last_analysis['analysis'], last_analysis['story'])
                        await query.edit_message_text(
                            response_text,
                            reply_markup=analysis_result_keyboard(
                                show_add_to_db=True,
                                has_improvement_history='improvement_chain' in context.user_data,
                                analysis_text=last_analysis['analysis']
                            ),
                            parse_mode='Markdown'
                        )
                        context.user_data['current_state'] = BotState.SHOWING_RESULTS
                    else:
                        await query.edit_message_text(
                            "🏠 **Главное меню**\n\nОтправьте User Story для анализа или выберите действие:",
                            reply_markup=main_menu_keyboard()
                        )
                        context.user_data['current_state'] = BotState.MAIN_MENU


                else:
                    # По умолчанию - в главное меню
                    await query.edit_message_text(
                        "🏠 **Главное меню**\n\nОтправьте User Story для анализа или выберите действие:",
                        reply_markup=main_menu_keyboard()
                    )
                    context.user_data['current_state'] = BotState.MAIN_MENU

            except BadRequest as e:
                if "Message is not modified" in str(e):
                    # Игнорируем эту ошибку - сообщение уже в нужном состоянии
                    logger.debug("Message not modified - already in correct state")
                    return
                else:
                    logger.error(f"BadRequest in back handler: {e}")
                    try:
                        await query.edit_message_text(
                            "❌ Ошибка при навигации. Возврат в главное меню.",
                            reply_markup=main_menu_keyboard()
                        )
                        context.user_data['current_state'] = BotState.MAIN_MENU
                    except Exception as fallback_error:
                        logger.error(f"Fallback also failed: {fallback_error}")

            except Exception as e:
                logger.error(f"Unexpected error in back handler: {e}")
                try:
                    await query.edit_message_text(
                        "❌ Неожиданная ошибка при навигации. Возврат в главное меню.",
                        reply_markup=main_menu_keyboard()
                    )
                    context.user_data['current_state'] = BotState.MAIN_MENU
                except Exception as fallback_error:
                    logger.error(f"Fallback also failed: {fallback_error}")

        elif data == "restart":
            try:
                # Очищаем только временные данные, сохраняем историю
                keys_to_keep = ['initial_story', 'user_history', 'last_analysis']
                temp_data = {}
                for key in keys_to_keep:
                    if key in context.user_data:
                        temp_data[key] = context.user_data[key]

                context.user_data.clear()
                context.user_data.update(temp_data)

                await query.edit_message_text(
                    "🏠 **Главное меню**\n\nОтправьте User Story для анализа или выберите действие:",
                    reply_markup=main_menu_keyboard()
                )
                context.user_data['current_state'] = BotState.MAIN_MENU

            except Exception as e:
                logger.error(f"Error in restart: {e}")
                # Fallback - пытаемся отправить новое сообщение
                try:
                    await query.message.reply_text(
                        "🏠 **Главное меню**\n\nОтправьте User Story для анализа или выберите действие:",
                        reply_markup=main_menu_keyboard()
                    )
                except Exception as fallback_error:
                    logger.error(f"Restart fallback also failed: {fallback_error}")

        elif data == "stats":
            context.user_data['current_state'] = BotState.STATS
            await stats(update, context)

        elif data == "help":
            context.user_data['current_state'] = BotState.HELP
            help_text = (
                "📖 **Помощь по INVEST-Checker**\n\n"
                "**INVEST критерии:**\n"
                "• **I** - Независимая (Independent)\n"
                "• **N** - Обсуждаемая (Negotiable) \n"
                "• **V** - Ценная (Valuable)\n"
                "• **E** - Оцениваемая (Estimable)\n"
                "• **S** - Маленькая (Small)\n"
                "• **T** - Тестируемая (Testable)\n\n"
                "**Формат User Story:**\n"
                "```\nКак <роль>, я хочу <действие>, чтобы <цель>\n```\n"
                "**Пример:**\n"
                "_Как пользователь, я хочу регистрироваться по email, чтобы получить доступ к личному кабинету._"
            )
            await query.edit_message_text(help_text, reply_markup=help_keyboard(previous_state), parse_mode='Markdown')

        elif data == "show_database":
            context.user_data['current_state'] = BotState.SHOWING_DATABASE
            await show_database(update, context, page=0)

        elif data.startswith("db_page_"):
            page = int(data.split('_')[-1])
            await show_database(update, context, page)

        #elif data.startswith("analyze_db_"):
        #    story_id = int(data.split('_')[-1])
        #    # Здесь можно добавить дополнительную функциональность
        #    await query.answer("Функциональность в разработке", show_alert=True)


        elif data == "export":
            context.user_data['current_state'] = BotState.EXPORT_MENU
            await query.edit_message_text(
                "📤 *Экспорт результатов*\n\nВыберите формат экспорта:",
                reply_markup=export_menu_keyboard(previous_state),
                parse_mode='Markdown'
            )

        else:
            await query.edit_message_text(
                "⚠️ Неизвестная команда.",
                reply_markup=navigation_keyboard(previous_state)
            )

    except BadRequest as e:
        if "Can't parse entities" in str(e):
            logger.warning(f"Markdown parsing error, sending as plain text: {e}")
            try:
                current_text = query.message.text
                await query.edit_message_text(
                    current_text,
                    parse_mode=None,
                    reply_markup=query.message.reply_markup
                )
            except Exception as fallback_error:
                logger.error(f"Fallback also failed: {fallback_error}")
                await query.edit_message_text(
                    "❌ Произошла ошибка форматирования. Попробуйте еще раз.",
                    reply_markup=navigation_keyboard(previous_state)
                )
        elif "Message is not modified" in str(e):
            logger.debug("Message not modified - ignoring")
            return
        else:
            logger.error(f"Error in callback handler for {data}: {e}")
            try:
                await query.edit_message_text(
                    "❌ Произошла ошибка при обработке запроса. Попробуйте снова.",
                    reply_markup=navigation_keyboard(previous_state)
                )
            except Exception as edit_error:
                logger.error(f"Failed to edit message: {edit_error}")

    except Exception as e:
        logger.error(f"Error in callback handler for {data}: {e}")
        try:
            await query.edit_message_text(
                "❌ Произошла ошибка при обработке запроса. Попробуйте снова.",
                reply_markup=navigation_keyboard(previous_state)
            )
        except Exception as edit_error:
            logger.error(f"Failed to edit message: {edit_error}")

def register_handlers(app: Application) -> None:
    """Регистрация всех обработчиков"""
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

async def show_database(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    """Показать базу историй с пагинацией"""
    try:
        # Проверяем, не пытаемся ли мы загрузить ту же страницу
        current_page = context.user_data.get('current_db_page', -1)
        if current_page == page:
            # Если это та же страница, просто выходим чтобы избежать ошибки "Message is not modified"
            return

        db = context.bot_data['db']
        page_size = 5  # Показываем по 5 историй на странице

        # Получаем истории для текущей страницы
        stories = await db.get_all_stories(page, page_size)
        total_stories = await db.get_total_stories_count()
        total_pages = (total_stories + page_size - 1) // page_size if total_stories > 0 else 1

        if not stories:
            await update.callback_query.edit_message_text(
                "📁 **База User Stories пуста**\n\nПока нет сохраненных историй. Проанализируйте первую историю!",
                reply_markup=database_keyboard(page, total_pages, False, False),
                parse_mode='Markdown'
            )
            context.user_data['current_db_page'] = page
            context.user_data['current_state'] = BotState.SHOWING_DATABASE
            return

        # Информация о странице в тексте сообщения
        message_text = "📁 *База User Stories*\n\n"
        message_text += f"📄 *Страница {page+1}/{total_pages}* | Всего историй: {total_stories}\n\n"

        for i, story in enumerate(stories):
            story_number = page * page_size + i + 1
            score = story.get('score', 0)
            is_golden = story.get('is_golden', False)

            # Форматируем отображение истории
            story_text = story['query']
            if len(story_text) > 80:
                story_text = story_text[:80] + "..."

            # Определяем эмодзи для качества истории
            quality_emoji = "⭐" if is_golden else "📝"
            if score >= 5:
                quality_emoji = "🔥"
            elif score >= 4:
                quality_emoji = "✅"

            message_text += f"{quality_emoji} **{story_number}. [{score}/6]** {story_text}\n\n"

        message_text += "_Используйте кнопки ниже для навигации_"

        # Определяем наличие предыдущих/следующих страниц
        has_previous = page > 0
        has_next = (page + 1) * page_size < total_stories

        await update.callback_query.edit_message_text(
            message_text,
            reply_markup=database_keyboard(page, total_pages, has_previous, has_next),
            parse_mode='Markdown'
        )

        context.user_data['current_db_page'] = page
        context.user_data['current_state'] = BotState.SHOWING_DATABASE

    except Exception as e:
        logger.error(f"Error showing database: {e}")
        await update.callback_query.edit_message_text(
            "❌ Ошибка при загрузке базы историй.",
            reply_markup=navigation_keyboard()
        )

async def show_story_details(update: Update, context: ContextTypes.DEFAULT_TYPE, story_id: int):
    """Показать детали конкретной истории"""
    try:
        db = context.bot_data['db']
        story = await db.get_story_by_id(story_id)

        if not story:
            await update.callback_query.edit_message_text(
                "❌ История не найдена.",
                reply_markup=database_keyboard(0, 1, False, False)
            )
            return

        # Форматируем детальное отображение истории
        message_text = "📖 **Детали User Story**\n\n"
        message_text += f"**ID:** {story['id']}\n"
        message_text += f"**Оценка:** {story.get('score', 'N/A')}/6\n"
        message_text += f"**Статус:** {'⭐ Золотая история' if story.get('is_golden') else '📝 Обычная история'}\n"
        message_text += f"**Дата добавления:** {story.get('created_at', 'N/A')}\n\n"

        message_text += f"**User Story:**\n_{story['query']}_\n\n"

        if story.get('answer'):
            # Форматируем анализ для лучшего отображения
            analysis = format_analysis_for_display(story['answer'], story['query'])
            message_text += f"**Анализ INVEST:**\n{analysis}"

        current_page = context.user_data.get('current_db_page', 0)

        await update.callback_query.edit_message_text(
            message_text,
            reply_markup=database_story_keyboard(story_id, current_page),
            parse_mode='Markdown'
        )

        context.user_data['current_state'] = BotState.SHOWING_STORY_DETAILS

    except Exception as e:
        logger.error(f"Error showing story details: {e}")
        await update.callback_query.edit_message_text(
            "❌ Ошибка при загрузке деталей истории.",
            reply_markup=database_keyboard(0, 1, False, False)
        )

def _add_to_user_history(context: ContextTypes.DEFAULT_TYPE, user_id: int, story: str, analysis: str = None):
    """Добавить запись в историю пользователя"""
    # Пробуем использовать объект бота из bot_data
    if 'bot' in context.bot_data and hasattr(context.bot_data['bot'], 'add_to_user_history'):
        context.bot_data['bot'].add_to_user_history(user_id, story, analysis)
        return
    
    # Fallback: сохраняем в context.bot_data
    if 'user_history' not in context.bot_data:
        context.bot_data['user_history'] = {}
    
    if user_id not in context.bot_data['user_history']:
        context.bot_data['user_history'][user_id] = []
        # Обновляем статистику сессий
        if 'stats' in context.bot_data:
            context.bot_data['stats']['user_sessions'] += 1

    history_entry = {
        'timestamp': datetime.now().isoformat(),
        'story': story,
        'analysis': analysis,
        'type': 'user_story'
    }

    context.bot_data['user_history'][user_id].append(history_entry)
    
    # Обновляем статистику сообщений
    if 'stats' in context.bot_data:
        context.bot_data['stats']['total_messages'] += 1

    # Ограничиваем глубину истории для экономии памяти
    max_history_depth = 50
    if len(context.bot_data['user_history'][user_id]) > max_history_depth:
        context.bot_data['user_history'][user_id] = context.bot_data['user_history'][user_id][-max_history_depth:]

def _cache_analysis(context: ContextTypes.DEFAULT_TYPE, story: str, analysis_data: dict):
    """Сохранить анализ в кэш"""
    cache_key = f"analysis_{hash(story.lower().strip())}"
    if 'analysis_cache' not in context.bot_data:
        context.bot_data['analysis_cache'] = {}
    
    context.bot_data['analysis_cache'][cache_key] = analysis_data
    logger.debug(f"Cached analysis for: {story[:50]}...")

    # Ограничиваем размер кэша
    max_cache_size = 100
    if len(context.bot_data['analysis_cache']) > max_cache_size:
        # Удаляем самую старую запись (простая реализация)
        oldest_key = next(iter(context.bot_data['analysis_cache']))
        del context.bot_data['analysis_cache'][oldest_key]
