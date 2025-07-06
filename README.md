# Telegram Mail Checker Bot (AI Filtering)

**Функционал / Current functionality:**
- Проверка новых писем через IMAP (Gmail, Yandex и др.)  
- Нейросетевая фильтрация писем по важности (DeepSeek / OpenRouter)  
- Периодическая проверка (настраиваемый интервал)  
- «Реальное время» — проверка каждые N секунд  
- Ежедневный отчёт в 8:00 по Московскому времени  
- Управление ботом через inline‑кнопки и команды  
- Оптимизированные IMAP‑запросы и сохранение состояния UID  

**Features:**
- IMAP-based new mail checking (Gmail, Yandex, etc.)  
- Neural importance filtering (DeepSeek via OpenRouter)  
- Periodic polling with customizable interval  
- Real‑time mode — polling every N seconds  
- Daily report at 08:00 Moscow time  
- Inline buttons & commands for bot control  
- Optimized IMAP usage and UID state persistence  

> **Важно:** используется бесплатная модель DeepSeek на OpenRouter, при желании можно использовать другую.

> **Important:** The free DeepSeek model on OpenRouter is used, but you can use another one if you wish.

## 📦 Установка зависимостей / Install requirements

```bash
pip install -r requirements.txt
```
## Запуск

```bash
python bot.py
```