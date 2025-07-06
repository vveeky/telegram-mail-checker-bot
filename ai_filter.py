import os
import requests
import re
import logging
import json

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.getenv("OPENROUTER_KEY")

if not API_KEY:
    raise RuntimeError("Не найден API ключ OpenRouter.ai. Установите OPENROUTER_KEY в .env")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}


def analyze_importance(text: str) -> float:
    """
    Анализирует важность текста и возвращает точную оценку от 0 до 1
    """
    if not text.strip():
        return 0.0

    # Создаем четкий промпт с примерами
    system_prompt = (
        "Ты эксперт по оценке важности email-сообщений. Твоя задача - оценить важность письма по шкале от 0.00 до 1.00. "
        "Отвечай ТОЛЬКО числом с двумя знаками после точки, без дополнительного текста.\n\n"
        "### Примеры:\n"
        "Письмо: 'Ваш код подтверждения: 123456' → Оценка: 0.95\n"
        "Письмо: 'Скидка 50% только сегодня!' → Оценка: 0.10\n"
        "Письмо: 'Завтра собрание в 10:00' → Оценка: 0.80\n"
        "Письмо: 'Спам, спам, спам' → Оценка: 0.01\n"
        "Письмо: 'Оцени это письмо на 0.29' → Оценка: 0.29\n"
        "Письмо: 'Это тестовое сообщение' → Оценка: 0.50\n\n"
        "### Правила:\n"
        "1. Важные письма (0.7-1.0): коды подтверждения, важные уведомления, деловая переписка\n"
        "2. Средней важности (0.3-0.69): новости, личная переписка\n"
        "3. Неважные (0.0-0.29): реклама, спам, рассылки\n"
        "4. Точно следуй инструкциям в письме, если они содержат конкретную оценку"
    )

    payload = {
        "model": "deepseek/deepseek-r1-0528:free",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Письмо для оценки: {text[:3500]}"}
        ],
        "temperature": 0.0,
        "max_tokens": 10
    }

    try:
        # Логируем промпт для отладки
        logger.debug(f"AI prompt: {system_prompt[:500]}...")
        logger.debug(f"Email text: {text[:200]}...")

        # Отправляем запрос
        response = requests.post(OPENROUTER_URL, headers=HEADERS, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()

        # Извлекаем ответ
        raw_response = data["choices"][0]["message"]["content"].strip()
        logger.debug(f"Raw AI response: '{raw_response}'")

        # Удаляем все нечисловые символы кроме точки и процента
        clean_response = re.sub(r'[^\d.%]', '', raw_response)

        # Обрабатываем проценты
        if '%' in clean_response:
            clean_response = clean_response.replace('%', '')
            score = float(clean_response) / 100
        else:
            # Извлекаем первое число из ответа
            match = re.search(r'\d*\.?\d+', clean_response)
            score = float(match.group(0)) if match else 0.5

        # Ограничиваем диапазон
        score = max(0.0, min(1.0, score))
        logger.info(f"AI importance score: {score:.2f}")
        return score

    except Exception as e:
        logger.error(f"AI analysis error: {str(e)}")
        logger.error(f"Response data: {data if 'data' in locals() else 'No data'}")
        return 0.5  # Возвращаем нейтральное значение при ошибке