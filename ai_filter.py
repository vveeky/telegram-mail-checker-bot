# ai_filter.py

import os
import requests
import re

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.getenv("OPENROUTER_KEY")
if not API_KEY:
    print("DEBUG OPENROUTER_KEY =", API_KEY)
    raise RuntimeError("Не найден API ключ OpenRouter.ai. Установите OPENROUTER_KEY в .env")

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

BASE_PAYLOAD = {
    "model": "deepseek/deepseek-r1-0528:free",
    "messages": [
        {
            "role": "system",
            "content": (
                "Ты помощник, который оценивает важность email-сообщений. Ответь только числом от 0 до 1, где 1 — максимально важно. например письма с кодами подтверждения - важно, уведомления о каких-то действиях в аккаунте - тоже важно. письмо с работы(найм) - важно. все что с реддита - неважно. ну в общем сам решай дальше по важности. порог будет 0.5, то есть если важность будет >= 0.5 письмо будет считаться важным. Ответь ТОЛЬКО числом от 0 до 1, например 0, 1, 0.1, 0.15, 0.53. округляй до двух знаков после запятой. кроме числа ничего абсолютно не пиши. если точно не уверен в важности, лучше поставь 0.5 "
            )
        },
        {"role": "user", "content": None}
    ],
    "temperature": 0.0
}

def analyze_importance(text: str, threshold: float = 0.5) -> bool:
    """
    Отправляет текст в модель DeepSeek и возвращает:
      - True, если важность >= threshold
      - False, если важность < threshold

    text    – содержимое письма (тема + тело)
    threshold – порог важности (по умолчанию 0.5)
    """
    # подставляем текст (обрезаем до 2000 символов)
    payload = BASE_PAYLOAD.copy()
    payload["messages"][1]["content"] = text[:2000]

    resp = requests.post(OPENROUTER_URL, headers=HEADERS, json=payload, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    raw = data["choices"][0]["message"]["content"].strip()
    # пытаемся вытащить float
    try:
        score = float(raw)
    except ValueError:
        m = re.search(r"0?\.\d+|1(?:\.0+)?", raw)
        score = float(m.group(0)) if m else 0.0

    return score >= threshold


if __name__ == "__main__":
    # Пример использования
    test = "Уважаемый клиент, ваше соглашение требует немедленного ответа."
    if analyze_importance(test):
        print("Письмо важно — отправляем уведомление")
    else:
        print("Письмо неважно — в уведомления не попадает")
