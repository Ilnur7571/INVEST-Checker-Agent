import asyncio
import io
import re
import logging
import time
from typing import Any, List, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

from db import ExamplesDB
from utils import normalize_text, build_invest_prompt, build_fix_prompt, build_improve_prompt

logger = logging.getLogger("bot")

class InvestBot:
    def __init__(self, token: str, llm_client: Any):
        self.token = token
        self.llm_client = llm_client
        self.db = ExamplesDB()

        self.app = Application.builder().token(self.token).build()
        self._register_handlers()

        self.user_history = {}
        self.last_cleanup = time.time()
        self.max_history_depth = 20

    def _register_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("help", self.help))
        self.app.add_handler(CallbackQueryHandler(self.callback_handler))
        self.app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_message))
        self.app.add_handler(CommandHandler("stats", self.stats))

    def main_menu_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("Анализ INVEST", callback_data="analyze_invest")],
            [InlineKeyboardButton("Помощь", callback_data="help")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def help_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("⬅️ Свернуть", callback_data="close_help")],
            [InlineKeyboardButton("🔄 В начало", callback_data="restart")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def navigation_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("⬅️ Назад", callback_data="back"),
             InlineKeyboardButton("🔄 В начало", callback_data="restart")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def similar_stories_keyboard(self, similar_stories: List[Tuple], original_text: str):
        keyboard = []

        for i, item in enumerate(similar_stories[:3]):
            story = item[0]
            ratio = item[2]
            keyboard.append([
                InlineKeyboardButton(
                    f"📚 Вариант {i+1} ({ratio:.0%})",
                    callback_data=f"use_similar_{i}"
                )
            ])

        keyboard.extend([
            [InlineKeyboardButton("🔁 Исправить через LLM", callback_data="fix_with_llm")],
            [InlineKeyboardButton("✅ Использовать свой вариант", callback_data="use_own")]
        ])

        keyboard.append([
            InlineKeyboardButton("⬅️ Назад", callback_data="back"),
            InlineKeyboardButton("🔄 В начало", callback_data="restart")
        ])

        return InlineKeyboardMarkup(keyboard)

    def analysis_result_keyboard(self, show_add_to_db: bool = True, score: int = 0):
        keyboard = []

        keyboard.append([
            InlineKeyboardButton("📤 Экспорт", callback_data="export_menu"),
            InlineKeyboardButton("📋 Копировать в Jira", callback_data="jira_copy")
        ])

        if show_add_to_db:
            if score >= 5:
                keyboard.append([InlineKeyboardButton("💾 Добавить в базу", callback_data="add_to_db")])
            else:
                keyboard.append([InlineKeyboardButton("✨ Улучшить историю", callback_data="improve_story")])

        keyboard.append([
            InlineKeyboardButton("⬅️ Назад", callback_data="back"),
            InlineKeyboardButton("🔄 В начало", callback_data="restart")
        ])

        return InlineKeyboardMarkup(keyboard)

    def export_menu_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("📄 TXT", callback_data="export_txt"),
             InlineKeyboardButton("📊 CSV", callback_data="export_csv")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back"),
             InlineKeyboardButton("🔄 В начало", callback_data="restart")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def invalid_story_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("🔁 Исправить через LLM", callback_data="fix_with_llm")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back"),
            InlineKeyboardButton("🔄 В начало", callback_data="restart")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def fix_result_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("✅ Проанализировать исправленный вариант", callback_data="analyze_fixed")],
            [InlineKeyboardButton("🔄 Исправить ещё раз", callback_data="fix_with_llm")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back"),
             InlineKeyboardButton("🔄 В начало", callback_data="restart")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def improved_story_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("✅ Проанализировать улучшенную версию", callback_data="analyze_improved")],
            [InlineKeyboardButton("🔄 Улучшить ещё раз", callback_data="improve_again")],
            [InlineKeyboardButton("📤 Экспорт улучшенной версии", callback_data="export_improved")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back"),
             InlineKeyboardButton("🔄 В начало", callback_data="restart")]
        ]
        return InlineKeyboardMarkup(keyboard)

    def _cleanup_old_states(self):
        current_time = time.time()

        if current_time - self.last_cleanup < 1800:
            return

        for chat_id in list(self.user_history.keys()):
            if len(self.user_history[chat_id]) > 50:
                self.user_history[chat_id] = self.user_history[chat_id][-20:]

        self.last_cleanup = current_time

    def _save_state(self, chat_id: int, text: str, reply_markup, parse_mode=None, state_name=""):
        self._cleanup_old_states()

        if chat_id not in self.user_history:
            self.user_history[chat_id] = []

        if len(self.user_history[chat_id]) >= self.max_history_depth:
            self.user_history[chat_id].pop(0)

        self.user_history[chat_id].append({
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
            "state_name": state_name
        })

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = (
            "Привет! Я AI-агент для проверки User Story по критериям INVEST.\n\n"
            "Нажмите «Анализ INVEST», чтобы отправить историю для проверки."
        )

        context.user_data.clear()
        context.user_data["mode"] = None

        chat_id = update.effective_chat.id
        self.user_history[chat_id] = []

        self._save_state(chat_id, text, self.main_menu_keyboard(), state_name="main_menu")

        if update.message:
            await update.message.reply_text(text, reply_markup=self.main_menu_keyboard())
        else:
            await update.callback_query.edit_message_text(text, reply_markup=self.main_menu_keyboard())

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        help_text = (
            "ℹ️ **Помощь:**\n\n"
            "Отправьте User Story в формате:\n"
            "`Как <роль>, я хочу <действие>, чтобы <цель>`\n\n"
            "**Кнопки:**\n"
            "• ⬅️ Назад - вернуться на предыдущий шаг\n"
            "• 🔄 В начало - вернуться в главное меню\n"
            "• 📤 Экспорт - сохранить результат анализа\n"
            "• 📋 Копировать в Jira - интеграция с Jira (в разработке)\n"
            "• 🔁 Исправить - автоматически улучшить User Story\n"
            "• 💾 Добавить в базу - сохранить историю для будущего использования\n\n"
            "**Пример:**\n"
            "`Как пользователь, я хочу войти в систему, чтобы получить доступ к моим данным`"
        )

        chat_id = update.effective_chat.id
        self._save_state(chat_id, help_text, self.help_keyboard(), parse_mode='Markdown', state_name="help")

        if update.message:
            await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=self.help_keyboard())
        else:
            await update.callback_query.edit_message_text(help_text, parse_mode='Markdown', reply_markup=self.help_keyboard())

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        mode = context.user_data.get("mode")

        if mode != "analyze":
            await update.message.reply_text(
                "Нажмите «Анализ INVEST» в меню, чтобы проверить User Story.",
                reply_markup=self.main_menu_keyboard()
            )
            return

        context.user_data["pending_text"] = text

        if not self._is_valid_user_story(text):
            error_text = (
                "⚠️ Это не похоже на User Story. Нужен формат:\n"
                "`Как <роль>, я хочу <действие>, чтобы <цель>`\n\n"
                "Хотите, чтобы я исправил это автоматически?"
            )

            chat_id = update.effective_chat.id
            self._save_state(chat_id, error_text, self.invalid_story_keyboard(), parse_mode='Markdown', state_name="invalid_story")

            await update.message.reply_text(
                error_text,
                parse_mode='Markdown',
                reply_markup=self.invalid_story_keyboard()
            )
            return

        await update.message.reply_text("🔎 Ищу похожие истории в базе знаний...")

        similar_stories = self.db.find_similar(text, threshold=0.7, prefer_golden=True)

        if similar_stories:
            context.user_data["similar_stories"] = similar_stories

            similar_text = "📚 **Найдены похожие User Story в базе знаний:**\n\n"
            for i, item in enumerate(similar_stories[:3]):
                story = item[0]
                ratio = item[2]
                similar_text += f"**Вариант {i+1} (сходство: {ratio:.0%}):**\n`{story}`\n\n"

            similar_text += "Выберите подходящий вариант или используйте другие опции:"

            chat_id = update.effective_chat.id
            self._save_state(chat_id, similar_text, self.similar_stories_keyboard(similar_stories, text), state_name="similar_stories")

            await update.message.reply_text(
                similar_text,
                parse_mode='Markdown',
                reply_markup=self.similar_stories_keyboard(similar_stories, text)
            )
            return

        await self._analyze_user_story(update, context, text, show_add_to_db=True, is_callback=False)

    async def _analyze_user_story(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                            user_story: str, show_add_to_db: bool = True, is_callback: bool = False,
                            is_improved: bool = False):
        if is_callback:
            query = update.callback_query
            message_text = "🔍 Анализирую улучшенную историю..." if is_improved else "🔍 Анализирую..."
            await query.edit_message_text(message_text)
        else:
            message_text = "🔍 Анализирую улучшенную историю..." if is_improved else "🔍 Анализирую..."
            await update.message.reply_text(message_text)

        try:
            prompt = build_invest_prompt(user_story)
            llm_response = await self._call_llm(prompt)
            analysis_result = self._extract_llm_text(llm_response)

            logger.info(f"Raw LLM response: {analysis_result}")

            clean_analysis = self._format_brief_analysis(analysis_result)
            logger.info(f"Cleaned analysis: {clean_analysis}")

            score = self._extract_score_from_analysis(clean_analysis)
            context.user_data["last_score"] = score

            context.user_data["last_analysis"] = {
                "story": user_story,
                "analysis": clean_analysis,
                "score": score
            }

            fixed_text = context.user_data.get("fixed_text")
            await self._auto_add_to_quality_story(context, user_story, clean_analysis, fixed_text)

            context.user_data["show_add_to_db"] = show_add_to_db

            result_text = f"📊 **Результат анализа:**\n\n{clean_analysis}"

            chat_id = update.effective_chat.id
            self._save_state(
                chat_id,
                result_text,
                self.analysis_result_keyboard(show_add_to_db=show_add_to_db, score=score),
                state_name="analysis_result"
            )

            if is_callback:
                await query.edit_message_text(
                    result_text,
                    reply_markup=self.analysis_result_keyboard(show_add_to_db=show_add_to_db, score=score)
                )
            else:
                await update.message.reply_text(
                    result_text,
                    reply_markup=self.analysis_result_keyboard(show_add_to_db=show_add_to_db, score=score)
                )

        except Exception as e:
            logger.error(f"Ошибка анализа: {e}")
            error_text = "❌ Произошла ошибка при анализе. Попробуйте еще раз."

            if is_callback:
                await query.edit_message_text(
                    error_text,
                    reply_markup=self.main_menu_keyboard()
                )
            else:
                await update.message.reply_text(
                    error_text,
                    reply_markup=self.main_menu_keyboard()
                )

    async def callback_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        data = query.data
        chat_id = query.message.chat.id

        if data == "back":
            await self._handle_back(update, context, chat_id)
            return
        elif data == "close_help":
            await self._handle_close_help(update, context, chat_id)
            return
        elif data == "restart":
            await self._handle_restart(update, context, chat_id)
            return

        handlers = {
            "analyze_invest": self._handle_analyze_invest,
            "help": self.help,
            "fix_with_llm": self._handle_fix_with_llm,
            "use_own": self._handle_use_own,
            "analyze_fixed": self._handle_analyze_fixed,
            "export_menu": self._handle_export_menu,
            "add_to_db": self._add_to_database,
            "jira_copy": self._handle_jira_copy,
            "improve_story": self._improve_story,
            "analyze_improved": self._handle_analyze_improved,
            "improve_again": self._handle_improve_again,
            "export_improved": self._handle_export_improved
        }

        if data.startswith("use_similar_"):
            await self._handle_use_similar(update, context, data)
        elif data.startswith("export_"):
            await self._export_analysis(update, context, data)
            return
        elif data in handlers:
            await handlers[data](update, context)
        else:
            await query.edit_message_text("Неизвестная команда.")

    async def _handle_back(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        history = self.user_history.get(chat_id, [])

        if len(history) > 1:
            history.pop()
            prev_state = history[-1]

            await update.callback_query.edit_message_text(
                text=prev_state["text"],
                reply_markup=prev_state["reply_markup"],
                parse_mode=prev_state.get("parse_mode")
            )
        else:
            await self.start(update, context)

    async def _handle_close_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        history = self.user_history.get(chat_id, [])

        if len(history) > 1:
            history.pop()
            prev_state = history[-1]

            await update.callback_query.edit_message_text(
                text=prev_state["text"],
                reply_markup=prev_state["reply_markup"],
                parse_mode=prev_state.get("parse_mode")
            )
        else:
            await self.start(update, context)

    async def _handle_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
        self.user_history[chat_id] = []
        await self.start(update, context)

    async def _handle_analyze_invest(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = query.message.chat.id

        context.user_data["mode"] = "analyze"
        text = (
            "Отправьте User Story для анализа в формате:\n"
            "`Как <роль>, я хочу <действие>, чтобы <цель>`\n\n"
            "Пример: `Как пользователь, я хочу войти в систему, чтобы получить доступ к моим данным`"
        )

        self._save_state(chat_id, text, self.navigation_keyboard(), parse_mode='Markdown', state_name="waiting_user_story")

        await query.edit_message_text(
            text=text,
            parse_mode='Markdown',
            reply_markup=self.navigation_keyboard()
        )

    async def _handle_fix_with_llm(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_text = context.user_data.get("pending_text", "")

        if not user_text:
            await query.edit_message_text("Нет исходной истории — пожалуйста, пришлите текст для исправления.")
            context.user_data["mode"] = "waiting_correction"
            return

        is_retry = context.user_data.get("fix_retry_count", 0) > 0
        context.user_data["fix_retry_count"] = context.user_data.get("fix_retry_count", 0) + 1

        await self._fix_with_llm(update, context, user_text, is_retry=is_retry)

    async def _handle_use_similar(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        query = update.callback_query
        idx = int(data.split("_")[2])
        similar_stories = context.user_data.get("similar_stories", [])
        chat_id = query.message.chat.id

        if 0 <= idx < len(similar_stories):
            story = similar_stories[idx][0]
            analysis = similar_stories[idx][1]

            clean_analysis = self._clean_analysis_text(analysis)
            score = self._extract_score_from_analysis(clean_analysis)

            context.user_data["last_analysis"] = {
                "story": story,
                "analysis": clean_analysis,
                "score": score
            }

            result_text = f"📊 **Результат анализа (из базы):**\n\n{clean_analysis}"

            self._save_state(chat_id, result_text, self.analysis_result_keyboard(show_add_to_db=False, score=score), state_name="analysis_from_db")

            await query.edit_message_text(
                result_text,
                reply_markup=self.analysis_result_keyboard(show_add_to_db=False, score=score)
            )
        else:
            await query.edit_message_text("❌ Неверный выбор похожей истории.")

    async def _handle_use_own(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        original_text = context.user_data.get("pending_text", "")
        if original_text:
            await self._analyze_user_story(update, context, original_text, show_add_to_db=True, is_callback=True)
        else:
            await update.callback_query.edit_message_text("❌ Не найден оригинальный текст.")

    async def _handle_analyze_fixed(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        fixed_text = context.user_data.get("fixed_text", "")
        if fixed_text:
            await self._analyze_user_story(update, context, fixed_text, show_add_to_db=True, is_callback=True)
        else:
            await update.callback_query.edit_message_text("❌ Не найден исправленный текст.")

    async def _handle_export_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        chat_id = query.message.chat.id

        export_text = "📤 **Выберите формат экспорта:**\n\nФайл будет отправлен в этот чат."

        self._save_state(chat_id, export_text, self.export_menu_keyboard(), parse_mode='Markdown', state_name="export_menu")

        await query.edit_message_text(
            export_text,
            parse_mode='Markdown',
            reply_markup=self.export_menu_keyboard()
        )

    async def _handle_jira_copy(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = query.message.chat.id

        jira_text = (
            "❌ Интеграция с Jira в настоящее время недоступна.\n\n"
            "Функция находится в разработке. Пожалуйста, используйте экспорт для сохранения результатов."
        )

        show_add_to_db = context.user_data.get("show_add_to_db", True)
        self._save_state(chat_id, jira_text, self.analysis_result_keyboard(show_add_to_db=show_add_to_db), state_name="jira_error")

        await query.edit_message_text(
            jira_text,
            reply_markup=self.analysis_result_keyboard(show_add_to_db=show_add_to_db)
        )

    async def _fix_with_llm(self, update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, is_retry: bool = False):
        query = update.callback_query

        if not is_retry:
            await query.edit_message_text("🔎 Ищу похожие истории в базе знаний...")

            similar_stories = self.db.find_similar(text, threshold=0.7, prefer_golden=True)

            if similar_stories:
                context.user_data["similar_stories"] = similar_stories

                similar_text = "📚 **Найдены похожие User Story в базе знаний:**\n\n"
                for i, item in enumerate(similar_stories[:3]):
                    story, answer, ratio, score = item
                    similar_text += f"**Вариант {i+1} (сходство: {ratio:.0%}):**\n`{story}`\n\n"

                similar_text += "Выберите подходящий вариант:"

                chat_id = update.callback_query.message.chat.id
                self._save_state(chat_id, similar_text, self.similar_stories_keyboard(similar_stories, text), state_name="similar_stories_fix")

                await query.edit_message_text(
                    similar_text,
                    parse_mode='Markdown',
                    reply_markup=self.similar_stories_keyboard(similar_stories, text)
                )
                return

        await query.edit_message_text("🤖 Запрашиваю улучшенный вариант у LLM...")

        try:
            prompt = build_fix_prompt(text)
            llm_response = await self._call_llm(prompt)
            fixed_text = self._extract_llm_text(llm_response)

            if not fixed_text or len(fixed_text.strip()) < 10:
                raise ValueError("LLM вернул пустой или слишком короткий текст")

            improved_text = await self._check_and_improve_story(text, fixed_text)
            if improved_text != fixed_text:
                logger.info(f"История была улучшена: {fixed_text} -> {improved_text}")
                fixed_text = improved_text

            context.user_data["fixed_text"] = fixed_text

            is_valid = self._is_valid_user_story(fixed_text)
            validity_status = "✅ Валидная user story" if is_valid else "⚠️ Требует дополнительной проверки"

            result_text = (
                f"✅ **Улучшенный вариант:**\n\n"
                f"`{fixed_text}`\n\n"
                f"**{validity_status}**\n\n"
                f"Хотите проанализировать этот вариант по INVEST?"
            )

            chat_id = update.callback_query.message.chat.id
            self._save_state(chat_id, result_text, self.fix_result_keyboard(), parse_mode='Markdown', state_name="fix_result")

            await query.edit_message_text(
                result_text,
                parse_mode='Markdown',
                reply_markup=self.fix_result_keyboard()
            )

        except Exception as e:
            logger.error(f"Ошибка исправления: {e}")
            await query.edit_message_text(
                "❌ Не удалось исправить текст. Попробуйте еще раз или введите другой вариант.",
                reply_markup=self.invalid_story_keyboard()
            )

    async def _export_analysis(self, update: Update, context: ContextTypes.DEFAULT_TYPE, format_type: str):
        query = update.callback_query
        await query.answer()

        logger.info(f"=== EXPORT CALLED ===")
        logger.info(f"Format type: {format_type}")

        analysis_data = context.user_data.get("last_analysis")

        if not analysis_data:
            logger.error("No analysis data found for export")
            await query.edit_message_text("❌ Нет данных для экспорта.")
            return

        story = analysis_data["story"]
        analysis = analysis_data["analysis"]
        score = analysis_data.get("score", 0)

        logger.info(f"Exporting story: {story[:50]}...")

        try:
            if format_type == "export_txt":
                content = f"User Story:\n{story}\n\nАнализ INVEST:\n{analysis}"
                filename = "user_story_analysis.txt"
                format_name = "TXT"
            else:
                story_escaped = story.replace('"', '""')
                analysis_escaped = analysis.replace('"', '""')
                content = f'"User Story";"Анализ INVEST"\n"{story_escaped}";"{analysis_escaped}"'
                filename = "user_story_analysis.csv"
                format_name = "CSV"

            file_buffer = io.BytesIO(content.encode('utf-8'))
            file_buffer.seek(0)

            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=InputFile(file_buffer, filename=filename),
                caption=f"📤 Экспорт в формате {format_name}"
            )

            success_text = f"✅ Файл экспортирован в формате {format_name} и отправлен в чат"

            chat_id = query.message.chat_id
            show_add_to_db = context.user_data.get("show_add_to_db", True)

            self._save_state(
                chat_id,
                success_text,
                self.analysis_result_keyboard(show_add_to_db=show_add_to_db, score=score),
                state_name="export_success"
            )

            await query.edit_message_text(
                success_text,
                reply_markup=self.analysis_result_keyboard(show_add_to_db=show_add_to_db, score=score)
            )

        except Exception as e:
            logger.error(f"Ошибка экспорта: {e}")
            error_text = f"❌ Ошибка при экспорте: {str(e)}"
            await query.edit_message_text(error_text)

    async def _add_to_database(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        analysis_data = context.user_data.get("last_analysis")

        if not analysis_data:
            await query.edit_message_text("❌ Нет данных для добавления в базу.")
            return

        story = analysis_data["story"]
        analysis = analysis_data["analysis"]

        try:
            norm_text = normalize_text(story)
            self.db.add_example(story, norm_text, analysis, is_golden=False, score=0)

            success_text = (
                "✅ User Story и анализ успешно добавлены в базу данных!\n\n"
                "Теперь они будут использоваться для поиска похожих историй в будущем."
            )

            chat_id = query.message.chat.id
            self._save_state(chat_id, success_text, self.analysis_result_keyboard(show_add_to_db=False), state_name="add_to_db_success")

            await query.edit_message_text(
                success_text,
                reply_markup=self.analysis_result_keyboard(show_add_to_db=False)
            )

        except Exception as e:
            logger.error(f"Ошибка добавления в базу: {e}")
            await query.edit_message_text(
                "❌ Ошибка при добавлении в базу данных.",
                reply_markup=self.analysis_result_keyboard(show_add_to_db=True)
            )

    def _is_valid_user_story(self, text: str) -> bool:
        text_lower = text.lower().strip()

        pattern = r'как\s+[^,]+\s*,\s*я\s+(хочу|могу|нужно)\s+[^,]+\s*,\s*чтобы\s+.+'
        has_structure = re.search(pattern, text_lower) is not None

        has_min_length = len(text_lower) > 25
        has_meaning = any(word in text_lower for word in ["хочу", "могу", "нужно"])

        return has_structure and has_min_length and has_meaning

    async def _call_llm(self, messages):
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.llm_client.chat(messages)
            )
            return self._extract_llm_text(result)
        except Exception as e:
            logger.error(f"LLM call error: {e}")
            raise

    def _extract_llm_text(self, response) -> str:
        if isinstance(response, str):
            return response

        if isinstance(response, dict):
            if 'choices' in response and response['choices']:
                choice = response['choices'][0]
                if 'message' in choice and 'content' in choice['message']:
                    return choice['message']['content']
                elif 'text' in choice:
                    return choice['text']
            elif 'text' in response:
                return response['text']

        return str(response)

    def _clean_analysis_text(self, analysis_text: str) -> str:
        if len(analysis_text.strip()) < 300:
            return analysis_text.strip()

        clean_text = analysis_text

        clean_text = re.sub(r'(system|user|assistant):\s*', '', clean_text, flags=re.IGNORECASE)
        clean_text = re.sub(r'[\{\}\[\]]', '', clean_text)
        clean_text = re.sub(r'[*#\-_`]', '', clean_text)

        lines = clean_text.split('\n')
        clean_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if any(tech in line.lower() for tech in ['json', 'role:', 'content:', '```']):
                continue
            if len(line) > 10:
                clean_lines.append(line)

        clean_text = '\n'.join(clean_lines)

        if len(clean_text) > 500:
            lines = clean_text.split('\n')
            if len(lines) > 8:
                clean_text = '\n'.join(lines[:8]) + "\n..."
            elif len(clean_text) > 500:
                clean_text = clean_text[:497] + "..."

        return clean_text.strip()

    def _format_brief_analysis(self, analysis_text: str) -> str:
        if "Оценка:" in analysis_text and any(marker in analysis_text for marker in ["I:", "N:", "V:"]):
            return analysis_text

        score = None
        criteria = {"I": "?", "N": "?", "V": "?", "E": "?", "S": "?", "T": "?"}
        recommendations = []

        lines = analysis_text.split('\n')

        for line in lines:
            line_lower = line.lower()
            if any(word in line_lower for word in ['оценка', 'балл', 'score']):
                numbers = re.findall(r'\d+', line)
                if numbers:
                    score = numbers[0]
                    if len(numbers) > 1:
                        score = f"{numbers[0]}/{numbers[1]}"
                    else:
                        score = f"{numbers[0]}/6"
                break

        for line in lines:
            line_lower = line.lower()

            criteria_patterns = {
                "I": ['independent', 'независим'],
                "N": ['negotiable', 'обсуждаем'],
                "V": ['valuable', 'ценн'],
                "E": ['estimable', 'оценива'],
                "S": ['small', 'маленьк'],
                "T": ['testable', 'тестируем']
            }

            for criterion, patterns in criteria_patterns.items():
                if any(pattern in line_lower for pattern in patterns):
                    if any(good in line_lower for good in ['хорош', 'good', 'да', 'yes', '✓', '+']):
                        criteria[criterion] = "✓"
                    elif any(bad in line_lower for bad in ['плох', 'bad', 'нет', 'no', '✗', '-']):
                        criteria[criterion] = "✗"

        for line in lines:
            line_clean = line.strip()
            if any(word in line_clean.lower() for word in ['рекомендац', 'совет', 'recommend', 'улучш', 'improve']):
                if len(line_clean) > 20 and not line_clean.endswith(':'):
                    rec_text = re.sub(r'^[•\-*\d\.\s]+', '', line_clean)
                    if rec_text and len(rec_text) > 10 and len(recommendations) < 3:
                        recommendations.append(rec_text)
            elif line_clean.startswith(('•', '-', '*', '1.', '2.', '3.')):
                rec_text = re.sub(r'^[•\-*\d\.\s]+', '', line_clean)
                if rec_text and len(rec_text) > 10 and len(recommendations) < 3:
                    recommendations.append(rec_text)

        result_lines = ["📊 **Анализ INVEST:**"]

        if score:
            result_lines.append(f"⭐ Оценка: {score}")
        else:
            result_lines.append("⭐ Оценка: не указана")

        criteria_line = "🔍 Критерии: "
        criteria_line += f"I:{criteria['I']} N:{criteria['N']} V:{criteria['V']} "
        criteria_line += f"E:{criteria['E']} S:{criteria['S']} T:{criteria['T']}"
        result_lines.append(criteria_line)

        if recommendations:
            result_lines.append("\n💡 Рекомендации:")
            for rec in recommendations:
                if len(rec) > 100:
                    rec = rec[:97] + "..."
                result_lines.append(f"• {rec}")

        result = '\n'.join(result_lines)

        if len(result) < 100 and len(analysis_text) > 200:
            return self._clean_analysis_text(analysis_text)

        return result

    def run(self):
        logger.info("Starting bot...")

        self.app.add_error_handler(self.error_handler)

        self.app.run_polling()

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.error(f"Exception while handling an update: {context.error}")

        try:
            if update and update.effective_chat:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="❌ Произошла ошибка при обработке запроса. Попробуйте еще раз."
                )
        except Exception as e:
            logger.error(f"Error in error handler: {e}")

    async def _check_and_improve_story(self, original_story: str, fixed_story: str, max_attempts: int = 2) -> str:
        if not self._is_valid_user_story(fixed_story):
            if max_attempts > 0:
                logger.info(f"Исправленная история невалидна, пробуем улучшить (осталось попыток: {max_attempts})")
                prompt = build_fix_prompt(original_story)
                new_fixed = await self._call_llm(prompt)
                new_fixed_text = self._extract_llm_text(new_fixed)
                return await self._check_and_improve_story(original_story, new_fixed_text, max_attempts - 1)
            else:
                logger.warning("Не удалось получить валидную историю после нескольких попыток")
                return fixed_story

        if len(fixed_story.split(',')) < 2 or "хочу" not in fixed_story.lower() or "чтобы" not in fixed_story.lower():
            if max_attempts > 0:
                logger.info(f"Исправленная история слишком общая, пробуем улучшить (осталось попыток: {max_attempts})")
                specific_prompt = [
                    {
                        "role": "system",
                        "content": "Сделай эту user story более конкретной и соответствующей INVEST. Убедись, что есть конкретная роль, конкретное действие и измеримая цель."
                    },
                    {
                        "role": "user",
                        "content": f"Сделай более конкретной: {fixed_story}"
                    }
                ]
                new_fixed = await self._call_llm(specific_prompt)
                new_fixed_text = self._extract_llm_text(new_fixed)
                return await self._check_and_improve_story(original_story, new_fixed_text, max_attempts - 1)

        return fixed_story

    def _extract_score_from_analysis(self, analysis_text: str) -> int:
        lines = analysis_text.split('\n')
        for line in lines:
            line_lower = line.lower()
            if any(word in line_lower for word in ['оценка', 'балл', 'score']):
                numbers = []
                current_number = ""
                for char in line:
                    if char.isdigit():
                        current_number += char
                    elif current_number:
                        numbers.append(int(current_number))
                        current_number = ""
                if current_number:
                    numbers.append(int(current_number))

                if numbers:
                    return min(numbers[0], 6)
        return 0

    def _is_high_quality_story(self, analysis_text: str, fixed_text: str = None) -> bool:
        score = self._extract_score_from_analysis(analysis_text)

        is_high_score = score >= 5
        is_valid = fixed_text and self._is_valid_user_story(fixed_text)
        has_content = len(analysis_text.strip()) > 100

        return is_high_score and is_valid and has_content

    async def _auto_add_to_quality_story(self, context: ContextTypes.DEFAULT_TYPE, story: str, analysis: str, fixed_text: str = None):
        try:
            if self._is_high_quality_story(analysis, fixed_text):
                score = self._extract_score_from_analysis(analysis)
                norm_text = normalize_text(story)

                self.db.add_example(story, norm_text, analysis, is_golden=True, score=score)
                logger.info(f"Автоматически добавлено в базу: {story} (оценка: {score})")
                return True
        except Exception as e:
            logger.error(f"Ошибка при автоматическом добавлении в золотую коллекцию: {e}")

        return False

    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        stats = self.db.get_statistics()

        stats_text = (
            "📊 **Статистика базы знаний:**\n\n"
            f"• Всего историй: {stats['total_stories']}\n"
            f"• Качественных историй: {stats['golden_stories']}\n"
            f"• Средняя оценка: {stats['average_score']}/6\n"
            f"• Всего использований: {stats['total_usage']}\n\n"
            "✨ Система постоянно учится на качественных примерах!"
        )

        await update.message.reply_text(stats_text, parse_mode='Markdown')

    async def _improve_story(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        original_story = context.user_data.get("pending_text", "")
        if not original_story:
            await query.edit_message_text("❌ Не найдена исходная история для улучшения.")
            return

        await query.edit_message_text("🔎 Ищу похожие качественные истории в базе...")

        similar_stories = self.db.find_similar(original_story, threshold=0.7, prefer_golden=True)

        if similar_stories:
            context.user_data["similar_stories"] = similar_stories

            similar_text = "📚 **Найдены качественные User Story в базе знаний:**\n\n"
            for i, item in enumerate(similar_stories[:3]):
                story, answer, ratio, score = item
                score_display = f"оценка: {score}/6, " if score > 0 else ""
                similar_text += f"**Вариант {i+1} ({score_display}сходство: {ratio:.0%}):**\n`{story}`\n\n"

            similar_text += "Выберите подходящий вариант или улучшите текущую историю:"

            chat_id = update.callback_query.message.chat.id
            self._save_state(chat_id, similar_text, self.similar_stories_keyboard(similar_stories, original_story), state_name="similar_stories_improve")

            await query.edit_message_text(
                similar_text,
                parse_mode='Markdown',
                reply_markup=self.similar_stories_keyboard(similar_stories, original_story)
            )
            return

        await query.edit_message_text("✨ Улучшаю историю до качества 5/6+...")

        try:
            improve_prompt = build_improve_prompt(original_story)

            llm_response = await self._call_llm(improve_prompt)
            improved_story = self._extract_llm_text(llm_response).strip()

            if not self._is_valid_user_story(improved_story):
                retry_prompt = [
                    {
                        "role": "system",
                        "content": "Исправь User Story строго в формате: 'Как <роль>, я хочу <действие>, чтобы <цель>'. Только исправленная версия."
                    },
                    {
                        "role": "user",
                        "content": f"Исправь формат: {improved_story}"
                    }
                ]
                llm_response = await self._call_llm(retry_prompt)
                improved_story = self._extract_llm_text(llm_response).strip()

            context.user_data["pending_text"] = improved_story
            context.user_data["improved_story"] = improved_story

            improved_text = (
                "✨ **Улучшенная User Story:**\n\n"
                f"`{improved_story}`\n\n"
                "Хотите проанализировать этот вариант?"
            )

            chat_id = update.callback_query.message.chat.id
            self._save_state(chat_id, improved_text, self.improved_story_keyboard(), parse_mode='Markdown', state_name="improved_story_preview")

            await query.edit_message_text(
                improved_text,
                parse_mode='Markdown',
                reply_markup=self.improved_story_keyboard()
            )

        except Exception as e:
            logger.error(f"Ошибка улучшения истории: {e}")
            await query.edit_message_text(
                "❌ Не удалось улучшить историю. Попробуйте еще раз.",
                reply_markup=self.analysis_result_keyboard(show_add_to_db=True)
            )

    async def _handle_improve_again(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        current_story = context.user_data.get("improved_story", context.user_data.get("pending_text", ""))

        if not current_story:
            await query.edit_message_text("❌ Не найдена история для улучшения.")
            return

        context.user_data["pending_text"] = current_story

        await self._improve_story(update, context)

    async def _handle_analyze_improved(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        improved_story = context.user_data.get("improved_story", "")
        if not improved_story:
            await query.edit_message_text("❌ Не найдена улучшенная история для анализа.")
            return

        await self._analyze_user_story(update, context, improved_story, show_add_to_db=True, is_callback=True, is_improved=True)

    async def _handle_export_improved(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        improved_story = context.user_data.get("improved_story", "")
        if not improved_story:
            await query.edit_message_text("❌ Не найдена улучшенная история для экспорта.")
            return

        context.user_data["last_analysis"] = {
            "story": improved_story,
            "analysis": "✨ Улучшенная версия User Story (еще не проанализирована)",
            "score": 0
        }

        await self._handle_export_menu(update, context)
