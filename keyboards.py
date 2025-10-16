from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from utils import extract_score_from_analysis

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню с новой кнопкой База US"""
    keyboard = [
        [InlineKeyboardButton("🔍 Анализ INVEST", callback_data="analyze_invest")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("📁 База US", callback_data="show_database")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)


def help_keyboard(previous_state: str = None) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🔍 Начать анализ", callback_data="analyze_invest")],
    ]
    if previous_state and previous_state != "main_menu":
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    keyboard.append([InlineKeyboardButton("🔄 В начало", callback_data="restart")])
    return InlineKeyboardMarkup(keyboard)


def navigation_keyboard(previous_state: str = None) -> InlineKeyboardMarkup:
    keyboard = []
    if previous_state and previous_state != "main_menu":
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    keyboard.append([InlineKeyboardButton("🔄 В начало", callback_data="restart")])
    return InlineKeyboardMarkup(keyboard)


def similar_stories_keyboard(similar_stories: list, original_text: str) -> InlineKeyboardMarkup:
    keyboard = []

    for i, item in enumerate(similar_stories[:3]):
        _, _, ratio, _ = item
        keyboard.append([
            InlineKeyboardButton(f"📚 Вариант {i+1} ({ratio:.0%})", callback_data=f"use_similar_{i}")
        ])

    keyboard.extend([
        [InlineKeyboardButton("✨ Улучшить через ИИ", callback_data="fix_with_llm")],
        [InlineKeyboardButton("✅ Использовать свой вариант", callback_data="use_own")]
    ])

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="back"),
        InlineKeyboardButton("🔄 В начало", callback_data="restart")
    ])

    return InlineKeyboardMarkup(keyboard)


def analysis_result_keyboard(show_add_to_db: bool = False, previous_state: str = None,
                           has_improvement_history: bool = False, analysis_text: str = None) -> InlineKeyboardMarkup:
    """
    Улучшенная клавиатура с правильной логикой показа кнопки добавления в базу
    """
    if previous_state == "main_menu":
        previous_state = None

    keyboard = [
        [InlineKeyboardButton("🚀 Улучшить историю", callback_data="improve_story")],
    ]

    # кнопка истории улучшений если есть история
    if has_improvement_history:
        keyboard.append([InlineKeyboardButton("📋 Показать историю улучшений", callback_data="show_improvement_history")])

    # Дополнительные кнопки
    keyboard.append([InlineKeyboardButton("📤 Экспорт", callback_data="export")])

    # кнопки "Добавить в базу"
    if show_add_to_db and analysis_text:
        score = extract_score_from_analysis(analysis_text)
        # Показываем кнопку только для историй с оценкой 5/6 или 6/6
        if score >= 5:
            keyboard.insert(0, [InlineKeyboardButton("💾 Добавить в базу", callback_data="add_to_db")])

    # Навигационные кнопки
    if previous_state and previous_state != "main_menu":
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    keyboard.append([InlineKeyboardButton("🔄 В начало", callback_data="restart")])

    return InlineKeyboardMarkup(keyboard)


def improved_story_keyboard(previous_state: str = None) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🔍 Проанализировать улучшенную", callback_data="analyze_improved")],
        [InlineKeyboardButton("🔄 Улучшить заново", callback_data="improve_again")],
        [InlineKeyboardButton("📤 Экспорт улучшенной", callback_data="export_improved")],
    ]

    if previous_state and previous_state != "main_menu":
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    keyboard.append([InlineKeyboardButton("🔄 В начало", callback_data="restart")])

    return InlineKeyboardMarkup(keyboard)


def improvement_history_keyboard(previous_state: str = None) -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🔄 Улучшить еще раз", callback_data="improve_again")],
        [InlineKeyboardButton("🔍 Анализировать последнюю", callback_data="analyze_improved")],
    ]

    if previous_state and previous_state != "main_menu":
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    keyboard.append([InlineKeyboardButton("🔄 В начало", callback_data="restart")])

    return InlineKeyboardMarkup(keyboard)


def export_menu_keyboard(previous_state: str = None) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📄 TXT", callback_data="export_txt"),
            InlineKeyboardButton("📊 CSV", callback_data="export_csv")
        ],
    ]
    if previous_state and previous_state != "main_menu":
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
    keyboard.append([InlineKeyboardButton("🔄 В начало", callback_data="restart")])

    return InlineKeyboardMarkup(keyboard)


def database_keyboard(page: int = 0, total_pages: int = 1, has_previous: bool = False, has_next: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура для навигации по базе историй"""
    keyboard = []

    # Кнопки навигации
    nav_buttons = []
    if has_previous:
        nav_buttons.append(InlineKeyboardButton("⬅️ Предыдущие", callback_data=f"db_page_{page-1}"))
    if has_next:
        nav_buttons.append(InlineKeyboardButton("Следующие ➡️", callback_data=f"db_page_{page+1}"))

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.append([
        InlineKeyboardButton("⬅️ Назад", callback_data="back"),
        InlineKeyboardButton("🔄 В начало", callback_data="restart")
    ])

    return InlineKeyboardMarkup(keyboard)


def database_story_keyboard(story_id: int, current_page: int = 0) -> InlineKeyboardMarkup:
    """Клавиатура для отдельной истории из базы"""
    keyboard = [
        [InlineKeyboardButton("📊 Проанализировать эту историю", callback_data=f"analyze_db_{story_id}")],
        [InlineKeyboardButton("🚀 Улучшить эту историю", callback_data=f"improve_db_{story_id}")],
        [InlineKeyboardButton("⬅️ К списку", callback_data=f"db_page_{current_page}")],
        [InlineKeyboardButton("🔄 В начало", callback_data="restart")]
    ]
    return InlineKeyboardMarkup(keyboard)
