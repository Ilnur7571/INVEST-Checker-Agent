import re
from difflib import SequenceMatcher

def normalize_text(s: str) -> str:
    """
    Нормализует текст: приводит к нижнему регистру, убирает лишние пробелы,
    удаляет символы кроме букв, цифр, пробелов, дефисов, подчеркиваний, точек и запятых.
    """
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9а-яё\s\-\_.,]", "", s)
    return s


def similarity(a: str, b: str) -> float:
    """Возвращает коэффициент похожести двух строк (от 0 до 1)."""
    return SequenceMatcher(None, a, b).ratio()


def build_invest_prompt(user_story: str) -> list:
    """
    Формирует КРАТКИЙ prompt для GigaChat в режиме анализа User Story по INVEST.
    """
    system = {
        "role": "system",
        "content": (
            "Проанализируй User Story по INVEST критериям. Будь кратким.\n\n"
            "Формат ответа:\n"
            "Оценка: X/6\n"
            "I: [✓/✗] N: [✓/✗] V: [✓/✗] E: [✓/✗] S: [✓/✗] T: [✓/✗]\n"
            "Рекомендации: 1-2 кратких пункта\n\n"
            "Где:\n"
            "I - Independent (независимая)\n"
            "N - Negotiable (обсуждаемая)\n"
            "V - Valuable (ценная)\n"
            "E - Estimable (оцениваемая)\n"
            "S - Small (маленькая)\n"
            "T - Testable (тестируемая)\n\n"
            "✓ - критерий выполнен, ✗ - не выполнен"
        )
    }
    user = {"role": "user", "content": f"User Story: {user_story}"}
    return [system, user]


def build_fix_prompt(user_story: str) -> list:
    """
    Формирует КРАТКИЙ prompt для исправления user story.
    """
    system = {
        "role": "system",
        "content": (
            "Исправь user story чтобы она соответствовала INVEST. Только исправленная версия, без пояснений.\n\n"
            "Требования:\n"
            "- Формат: 'Как <роль>, я хочу <действие>, чтобы <цель>'\n"
            "- Конкретная роль, действие, цель\n"
            "- Одна цель\n"
            "- Коротко и ясно\n\n"
            "Только исправленная user story."
        )
    }
    user = {"role": "user", "content": f"Исправь: {user_story}"}
    return [system, user]


def build_improve_prompt(user_story: str) -> list:
    """
    Формирует промпт для улучшения User Story до качества 5/6+
    """
    system = {
        "role": "system",
        "content": (
            "Ты - эксперт по улучшению User Stories. Улучши историю так, чтобы она получила оценку 5/6+ по INVEST.\n\n"
            "Критерии улучшенной истории:\n"
            "- Независимая (Independent)\n"
            "- Обсуждаемая (Negotiable) \n"
            "- Ценная (Valuable)\n"
            "- Оцениваемая (Estimable)\n"
            "- Маленькая (Small)\n"
            "- Тестируемая (Testable)\n\n"
            "Формат: 'Как <роль>, я хочу <действие>, чтобы <цель>'\n"
            "Верни ТОЛЬКО улучшенную User Story без пояснений."
        )
    }
    user = {"role": "user", "content": f"Улучши: {user_story}"}
    return [system, user]
