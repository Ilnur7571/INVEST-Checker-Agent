from typing import List, Dict
import re
from functools import lru_cache


@lru_cache(maxsize=1000)
def normalize_text(text: str) -> str:
    """
    Нормализация текста с кэшированием для производительности.
    Оптимизированная версия: сохраняет баланс между качеством и скоростью.
    """
    if not text or not isinstance(text, str):
        return ""

    # Приводим к нижнему регистру
    text = text.lower().strip()

    # Исправляем частые опечатки (быстрая версия)
    common_typos = {
        'чтлбы': 'чтобы', 'что бы': 'чтобы', 'чотбы': 'чтобы',
        'востановить': 'восстановить', 'аккаунт': 'аккаунт',
        'зарегестрироваться': 'зарегистрироваться', 'пользаватель': 'пользователь'
    }

    for typo, correct in common_typos.items():
        text = text.replace(typo, correct)

    # Упрощенная очистка - удаляем только действительно мешающие символы
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)

    return text.strip()

def build_invest_prompt(user_story: str) -> List[Dict[str, str]]:
    """
    Оптимизированный промпт для анализа INVEST.
    Сокращен на ~50% по сравнению с оригиналом.
    """
    system_prompt = {
        "role": "system",
        "content": (
            "Анализируй User Story по INVEST. Формат ответа:\n"
            "Оценка: X/6\n"
            "Проблемы: [только невыполненные критерии с кратким объяснением]\n"
            "Рекомендации: [1-2 конкретных совета]\n\n"
            "Пример:\n"
            "Оценка: 4/6\n"
            "Проблемы: N - нет обсуждаемости, E - сложно оценить\n"
            "Рекомендации: Добавить варианты реализации, уточнить детали"
        ),
    }

    user_message = {"role": "user", "content": f"User Story: {user_story}"}
    return [system_prompt, user_message]

def build_fix_prompt(user_story: str) -> List[Dict[str, str]]:
    """
    Оптимизированный промпт для исправления User Story.
    """
    system_prompt = {
        "role": "system",
        "content": (
            "Исправь User Story, сохранив цель. Сделай ее:\n"
            "- Более четкой и конкретной\n"
            "- Соответствующей критериям INVEST\n"
            "- С ясными критериями приемки\n"
            "Верни только исправленную версию."
        ),
    }

    user_message = {"role": "user", "content": f"Исправь: {user_story}"}
    return [system_prompt, user_message]

def _extract_problems(analysis: str) -> str:
    """Извлекает только проблемы из анализа для экономии токенов"""
    if not analysis:
        return "нет критических проблем"

    problems = []
    if "N: ✗" in analysis or "N (Negotiable): ✗" in analysis or "Negotiable: ✗" in analysis:
        problems.append("нет обсуждаемости")
    if "E: ✗" in analysis or "E (Estimable): ✗" in analysis or "Estimable: ✗" in analysis:
        problems.append("сложно оценить")
    if "I: ✗" in analysis or "I (Independent): ✗" in analysis or "Independent: ✗" in analysis:
        problems.append("зависит от других")
    if "T: ✗" in analysis or "T (Testable): ✗" in analysis or "Testable: ✗" in analysis:
        problems.append("нет критериев тестирования")

    return ", ".join(problems) if problems else "нет критических проблем"

def build_improve_prompt(user_story: str, current_analysis: str = None) -> List[Dict[str, str]]:
    """
    Умный промпт для улучшения User Story с сохранением качества.
    Оптимизированная версия - на 40% короче.
    """
    system_prompt = {
        "role": "system",
        "content": (
            "УЛУЧШИ User Story, сохранив цель и ценность.\n\n"
            "Что улучшать:\n"
            "1. Конкретные критерии приемки\n"
            "2. Ясность формулировок\n"
            "3. Обсуждаемость (Negotiable)\n\n"
            "ЗАПРЕЩЕНО:\n"
            "- Убирать существующие критерии приемки\n"
            "- Делать историю менее конкретной\n"
            "- Ухудшать тестируемость\n\n"
            "Формат: [Улучшенная User Story с критериями приемки]"
        ),
    }

    user_content = f"Улучши: {user_story}"

    if current_analysis:
        problems = _extract_problems(current_analysis)
        if problems and problems != "нет критических проблем":
            user_content += f"\nУчти проблемы: {problems}"

    user_message = {"role": "user", "content": user_content}
    return [system_prompt, user_message]

def extract_score_from_analysis(analysis_text: str) -> int:
    """
    Извлечение оценки из текста анализа.
    """
    if not analysis_text:
        return -1

    # Ищем паттерн оценки X/6
    score_match = re.search(r"Оценка:\s*(\d)/6", analysis_text, re.IGNORECASE)
    if score_match:
        try:
            return int(score_match.group(1))
        except (ValueError, IndexError):
            pass

    # Альтернативный паттерн
    score_match = re.search(r"(\d)/6", analysis_text)
    if score_match:
        try:
            return int(score_match.group(1))
        except (ValueError, IndexError):
            pass

    return -1

def is_high_quality_story(
    story: str, min_length: int = 10, max_length: int = 500
) -> bool:
    """
    Базовая проверка качества User Story.
    """
    if not story or not isinstance(story, str):
        return False

    story = story.strip()

    # Проверка длины
    if len(story) < min_length or len(story) > max_length:
        return False

    # Проверка базовой структуры
    if not re.search(r"как\s+.+?,\s*я\s+хочу\s+.+?,\s*чтобы\s+.+?", story.lower()):
        return False

    return True

def truncate_text(text: str, max_length: int = 4000) -> str:
    """
    Обрезка текста до максимальной длины с сохранением целостности.
    """
    if not text or len(text) <= max_length:
        return text

    # Обрезаем до максимальной длины, стараясь не обрывать на середине предложения
    truncated = text[:max_length]
    last_period = truncated.rfind(".")
    last_space = truncated.rfind(" ")

    if last_period > max_length * 0.8:  # Если есть точка в последних 20%
        return truncated[: last_period + 1]
    elif last_space > max_length * 0.9:  # Или пробел в последних 10%
        return truncated[:last_space]
    else:
        return truncated + "..."

def clean_markdown(text: str) -> str:
    """Очистка проблемных символов Markdown"""
    # Экранируем проблемные последовательности
    text = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text)

    # Убираем множественные переносы строк
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text

def safe_truncate_text(text: str, max_length: int = 4000) -> str:
    """
    Безопасное обрезание текста с учетом Markdown.
    Улучшенная версия для обработки сообщений.
    """
    if len(text) <= max_length:
        return text

    # Находим последний завершенный блок перед лимитом
    truncated = text[:max_length]

    # Ищем последний завершенный раздел
    last_section = max(
        truncated.rfind('\n\n'),
        truncated.rfind('\n•'),
        truncated.rfind('\n-')
    )

    if last_section > max_length * 0.7:  # если нашли в последних 30%
        return truncated[:last_section].strip()
    else:
        return truncated.strip() + "\n\n... (текст обрезан)"

def format_analysis_for_display(analysis: str, user_story: str = None) -> str:
    """
    Форматирование анализа для красивого отображения.
    """
    if not analysis:
        return "❌ Не удалось проанализировать историю"

    # Очищаем от проблемных символов
    analysis = clean_markdown(analysis.strip())

    # Базовое форматирование
    lines = analysis.split('\n')
    formatted_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Форматируем заголовки
        if line.startswith('Оценка:'):
            formatted_lines.append(f"**{line}**")
        elif line.startswith('Проблемы:') or line.startswith('Рекомендации:'):
            formatted_lines.append(f"\n**{line}**")
        elif line.startswith('•') or line.startswith('-'):
            # Форматируем пункты списка
            formatted_lines.append(line)
        elif any(criterion in line for criterion in ['I (Independent)', 'N (Negotiable)',
                                                   'V (Valuable)', 'E (Estimable)',
                                                   'S (Small)', 'T (Testable)']):
            # Форматируем критерии INVEST
            if '✓' in line:
                line = line.replace('✓', '✅')
            elif '✗' in line:
                line = line.replace('✗', '❌')
            formatted_lines.append(line)
        else:
            formatted_lines.append(line)

    result = '\n'.join(formatted_lines)

    # Добавляем User Story только если предоставлена и не пустая
    if user_story and user_story.strip():
        result = f"**User Story:**\n_{user_story}_\n\n{result}"

    return safe_truncate_text(result)

def should_show_add_to_db_button(analysis_text: str, is_improved: bool = False) -> bool:
    """
    Определяет, нужно ли показывать кнопку 'Добавить в базу'.
    """
    if not analysis_text:
        return False

    score = extract_score_from_analysis(analysis_text)

    # Для улучшенных историй - более строгий порог
    if is_improved:
        return score >= 4  # Улучшенные истории с оценкой 4+ можно добавлять

    # Для обычных историй - только качественные
    return score >= 5  # Обычные истории только с оценкой 5+