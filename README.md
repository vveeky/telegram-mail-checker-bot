# Telegram Mail Checker Bot

**Функционал на текущий момент:**
- Периодическая проверка почты (настраиваемый интервал)
- «Реальное время» (чек каждые N секунд)
- Ежедневный отчёт в 8:00 по Московскому времени
- Inline‑кнопки и настройки прямо в боте
- Оптимизированные IMAP‑запросы

**Current functionality:**
- Periodic mail checking (customizable interval)
- "Real time" (check every N seconds)
- Daily report at 8:00 Moscow time
- Inline buttons and settings right in the bot
- Optimized IMAP requests

> **Важно:** фильтрация писем по важности (нейросеть) ещё не подключена, планируется в feature‑ветке. все письма считаются важными.

> **Important:** email filtering by importance (neural network) is not yet enabled and is planned in the feature branch. all emails are considered important.

## Установка/Install

```bash
pip install -r requirements.txt
```

## Запуск/Running

```bash
python bot.py
```