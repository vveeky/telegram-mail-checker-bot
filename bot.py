from telegram.ext import MessageHandler, filters
import os
import json
import logging
import asyncio
import re
from datetime import datetime, timedelta
from datetime import time as datetime_time
from pytz import timezone
from apscheduler.triggers.cron import CronTrigger

from dotenv import load_dotenv
from imapclient import IMAPClient
from email.header import decode_header
from email.parser import BytesParser
from email.policy import default

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
)

# Logging
logging.basicConfig(
    format='%(asctime)s %(levelname)s:%(name)s: %(message)s',
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

moscow_tz = timezone('Europe/Moscow')

# Load environment
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))
IMAP_USER = os.getenv("IMAP_USER")
IMAP_PASS = os.getenv("IMAP_PASS")
STATE_FILE = 'state.json'

# Default state structure
DEFAULT_STATE = {
    "last_uid": 0,
    "auto_enabled": True,
    "auto_interval": 30,
    "snooze_until": None,
    "realtime": False
}

# Conversation states
SET_INTERVAL, SET_SNOOZE, = range(2)

# Load or init state
if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
        # Ensure all keys exist
        for key, value in DEFAULT_STATE.items():
            if key not in state:
                state[key] = value
    except (json.JSONDecodeError, FileNotFoundError):
        state = DEFAULT_STATE.copy()
        logger.warning("State file corrupted, using default state")
else:
    state = DEFAULT_STATE.copy()


# Persist state helper
def save_state():
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    logger.info(f"State saved: {state}")


# Improved subject decoding
def decode_mime_header(header):
    if header is None:
        return ""

    decoded_parts = []
    for part, encoding in decode_header(header):
        if isinstance(part, bytes):
            try:
                charset = encoding or 'utf-8'
                decoded_parts.append(part.decode(charset, errors='replace'))
            except (LookupError, UnicodeDecodeError):
                decoded_parts.append(part.decode('utf-8', errors='replace'))
        else:
            decoded_parts.append(part)

    return ''.join(decoded_parts)


# Mail checker logic
def check_mail():
    global state
    try:
        with IMAPClient('imap.gmail.com', ssl=True) as client:
            client.login(IMAP_USER, IMAP_PASS)
            client.select_folder('INBOX')
            all_uids = client.search(['ALL'])

            if not all_uids:
                logger.info("No emails found in inbox")
                return []

            # Get highest UID to update last_uid
            max_uid = max(all_uids)
            if max_uid <= state['last_uid']:
                logger.info(f"No new emails since last check (last_uid={state['last_uid']}, max_uid={max_uid})")
                return []

            # Find new UIDs since last check
            new_uids = [u for u in all_uids if u > state['last_uid']]
            if not new_uids:
                return []

            logger.info(f"Found {len(new_uids)} new emails (last_uid={state['last_uid']}, new_uids={new_uids})")
            resp = client.fetch(new_uids, ['ENVELOPE', 'BODY.PEEK[]'])

            # Update last_uid only if we successfully processed emails
            state['last_uid'] = max_uid
            save_state()

        emails = []
        for uid, data in resp.items():
            env = data.get(b'ENVELOPE')
            raw_email = data.get(b'BODY[]')

            if not env or not raw_email:
                continue

            # Parse email
            msg = BytesParser(policy=default).parsebytes(raw_email)

            # Get sender
            sender = decode_mime_header(msg.get('From', ''))

            # Get subject
            subject = decode_mime_header(msg.get('Subject', ''))
            if not subject:
                subject = "(без темы)"

            # Get body content
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))

                    # Skip attachments
                    if "attachment" in content_disposition:
                        continue

                    if content_type == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            try:
                                charset = part.get_content_charset() or 'utf-8'
                                body = payload.decode(charset, errors='replace')
                            except:
                                body = payload.decode('utf-8', errors='replace')
                        break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    try:
                        charset = msg.get_content_charset() or 'utf-8'
                        body = payload.decode(charset, errors='replace')
                    except:
                        body = payload.decode('utf-8', errors='replace')

            # Clean up content
            subject = re.sub(r'\s+', ' ', subject).strip()
            sender = re.sub(r'\s+', ' ', sender).strip()
            body = re.sub(r'\s+', ' ', body).strip()

            # Limit body length for display
            if len(body) > 300:
                body = body[:300] + "..."

            emails.append({
                'sender': sender,
                'subject': subject,
                'body': body
            })

        return emails

    except Exception as e:
        logger.error(f"Mail check error: {str(e)}", exc_info=True)
        return []


# Real-time mail checker
async def realtime_check(context: ContextTypes.DEFAULT_TYPE):
    if not state['realtime']:
        return

    logger.info("Running realtime check")
    emails = await asyncio.to_thread(check_mail)
    if emails:
        for email_info in emails:
            text = (
                f"🔔 СРОЧНО!\n"
                f"✉️ От: {email_info['sender']}\n"
                f"📌 Тема: {email_info['subject']}\n"
                f"📝 Содержание:\n{email_info['body']}"
            )
            try:
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=text,
                    reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
                )
            except Exception as e:
                logger.error(f"Realtime notify error: {str(e)}")


# Notification routines
async def notify_periodic(context: ContextTypes.DEFAULT_TYPE):
    if not state['auto_enabled'] or state['realtime']:
        return

    snooze = state.get('snooze_until')
    if snooze:
        try:
            until = datetime.fromisoformat(snooze)
            if datetime.now() < until:
                logger.info(f"Snoozed until {until}")
                return
        except (TypeError, ValueError):
            pass
        state['snooze_until'] = None
        save_state()

    if state['realtime']:
        return

    logger.info("Running periodic check")
    emails = await asyncio.to_thread(check_mail)
    if emails:
        for email_info in emails:
            text = (
                f"✉️ От: {email_info['sender']}\n"
                f"📌 Тема: {email_info['subject']}\n"
                f"📝 Содержание:\n{email_info['body']}"
            )
            try:
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"[Авто] Новое письмо\n{text}",
                    reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
                )
            except Exception as e:
                logger.error(f"Periodic notify error: {str(e)}")


# Daily summary at 8:00
async def daily_report(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Running daily report")
    emails = await asyncio.to_thread(check_mail)
    if emails:
        for email_info in emails:
            text = (
                f"✉️ От: {email_info['sender']}\n"
                f"📌 Тема: {email_info['subject']}\n"
                f"📝 Содержание:\n{email_info['body']}"
            )
            try:
                await context.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"[Дневной отчет]\n{text}",
                    reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
                )
            except Exception as e:
                logger.error(f"Daily report error: {str(e)}")
    else:
        try:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text="[Дневной отчет] Нечего отчитывать",
                reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
            )
        except Exception as e:
            logger.error(f"Daily report error: {str(e)}")


# Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Create persistent menu button
    menu_button = ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)

    # Create inline menu
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📬 Проверить", callback_data='check')],
        [InlineKeyboardButton("⚙ Настройки", callback_data='settings')]
    ])

    await update.message.reply_text(
        "Бот-уведомитель приветствует!\n\n"
        "Используйте кнопку меню ниже для быстрого доступа к функциям бота.",
        reply_markup=menu_button
    )
    await update.message.reply_text("Выберите действие:", reply_markup=kb)


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for /check command"""
    logger.info("Manual check requested via command")
    emails = await asyncio.to_thread(check_mail)

    if emails:
        for email_info in emails:
            text = (
                f"✉️ От: {email_info['sender']}\n"
                f"📌 Тема: {email_info['subject']}\n"
                f"📝 Содержание:\n{email_info['body']}"
            )
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"[Ручная проверка]\n{text}",
                reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
            )
    else:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text="[Ручная проверка] 📩 Нет новых писем",
            reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
        )

    # Show menu again
    await show_main_menu(context, CHAT_ID)


async def check_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Delete the original message
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    logger.info("Manual check requested via button")
    emails = await asyncio.to_thread(check_mail)

    if emails:
        for email_info in emails:
            text = (
                f"✉️ От: {email_info['sender']}\n"
                f"📌 Тема: {email_info['subject']}\n"
                f"📝 Содержание:\n{email_info['body']}"
            )
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"[Ручная проверка]\n{text}",
                reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
            )
    else:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text="[Ручная проверка] 📩 Нет новых писем",
            reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
        )

    # Show menu again
    await show_main_menu(context, CHAT_ID)


async def settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Delete the original message
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    await show_settings_menu(context, CHAT_ID)
    return ConversationHandler.END


async def show_main_menu(context, chat_id):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📬 Проверить", callback_data='check')],
        [InlineKeyboardButton("⚙ Настройки", callback_data='settings')]
    ])
    await context.bot.send_message(
        chat_id=chat_id,
        text="Главное меню:",
        reply_markup=kb
    )


async def show_settings_menu(context, chat_id):
    # Build settings keyboard
    buttons = [
        [InlineKeyboardButton(f"Интервал: {state['auto_interval']} мин", callback_data='set_interval')],
        [InlineKeyboardButton(f"Realtime: {'ON' if state['realtime'] else 'OFF'}", callback_data='toggle_realtime')],
        [InlineKeyboardButton(f"Авто: {'ON' if state['auto_enabled'] else 'OFF'}", callback_data='toggle_auto')],
        [InlineKeyboardButton("Назад", callback_data='back')]
    ]

    # Only show snooze if auto is enabled
    if state['auto_enabled']:
        buttons.insert(1, [InlineKeyboardButton("Отложить авто", callback_data='snooze')])

    kb = InlineKeyboardMarkup(buttons)
    await context.bot.send_message(
        chat_id=chat_id,
        text="⚙ Настройки:",
        reply_markup=kb
    )


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Delete settings message
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    # Show main menu again
    await show_main_menu(context, CHAT_ID)


async def set_interval_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Delete the settings message
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    await context.bot.send_message(
        chat_id=CHAT_ID,
        text="Введите новый интервал (мин):",
        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
    )
    return SET_INTERVAL


async def set_interval_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text)
        if val < 1:
            raise ValueError("Interval too small")

        state['auto_interval'] = val
        save_state()

        # Update job schedule
        jobs = context.job_queue.get_jobs_by_name('periodic')
        if jobs:
            jobs[0].schedule_removal()

        context.job_queue.run_repeating(
            notify_periodic,
            interval=timedelta(minutes=val),
            first=0,
            name='periodic'
        )

        # Delete input message
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete message: {e}")

        # Show updated settings
        await show_settings_menu(context, CHAT_ID)
    except (ValueError, TypeError):
        # Send error message
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text="❌ Ошибка! Введите целое число больше 0",
            reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
        )
        return SET_INTERVAL

    return ConversationHandler.END


async def snooze_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state['auto_enabled'] or state['realtime']:
        await update.callback_query.answer("Авто-проверка выключена!", show_alert=True)
        return

    query = update.callback_query
    await query.answer()

    # Delete the settings message
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    await context.bot.send_message(
        chat_id=CHAT_ID,
        text="На сколько минут отложить авто?",
        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
    )
    return SET_SNOOZE


async def snooze_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        mins = int(update.message.text)
        if mins < 1:
            raise ValueError("Snooze time too small")

        until = datetime.now() + timedelta(minutes=mins)
        state['snooze_until'] = until.isoformat()
        save_state()

        # Delete input message
        try:
            await update.message.delete()
        except Exception as e:
            logger.warning(f"Could not delete message: {e}")

        # Send confirmation
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=f"⏸ Авто отложено до {until.strftime('%H:%M')}",
            reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
        )

        # Show updated settings
        await show_settings_menu(context, CHAT_ID)
    except (ValueError, TypeError):
        # Send error message
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text="❌ Ошибка! Введите целое число больше 0",
            reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
        )
        return SET_SNOOZE

    return ConversationHandler.END


async def toggle_realtime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Toggle realtime setting
    state['realtime'] = not state['realtime']
    save_state()

    # Delete the settings message
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    # Show updated settings
    await show_settings_menu(context, CHAT_ID)

    # Send confirmation
    status = "включен" if state['realtime'] else "выключен"
    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=f"Режим реального времени {status}",
        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
    )


async def toggle_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    state['auto_enabled'] = not state['auto_enabled']
    save_state()

    # Delete the settings message
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")

    # Show updated settings
    await show_settings_menu(context, CHAT_ID)

    # Send confirmation
    status = "включена" if state['auto_enabled'] else "выключена"
    await context.bot.send_message(
        chat_id=CHAT_ID,
        text=f"Автоматическая проверка {status}",
        reply_markup=ReplyKeyboardMarkup([["/start"]], resize_keyboard=True)
    )


# Main
if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    # Conversation for settings
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(set_interval_start, pattern='^set_interval$'),
                      CallbackQueryHandler(snooze_start, pattern='^snooze$')],
        states={
            SET_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_interval_done)],
            SET_SNOOZE: [MessageHandler(filters.TEXT & ~filters.COMMAND, snooze_done)],
        },
        fallbacks=[],
        per_message=True,
        allow_reentry=True
    )

    # Register handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('check', check_command))
    app.add_handler(CallbackQueryHandler(check_cb, pattern='^check$'))
    app.add_handler(CallbackQueryHandler(settings_menu, pattern='^settings$'))
    app.add_handler(CallbackQueryHandler(back_to_menu, pattern='^back$'))
    app.add_handler(CallbackQueryHandler(toggle_realtime, pattern='^toggle_realtime$'))
    app.add_handler(CallbackQueryHandler(toggle_auto, pattern='^toggle_auto$'))
    app.add_handler(conv)

    # Periodic job
    job = app.job_queue.run_repeating(
        notify_periodic,
        interval=timedelta(minutes=state['auto_interval']),
        first=0,
        name='periodic'
    )

    # Real-time(almost) job
    app.job_queue.run_repeating(
        realtime_check,
        interval=10,  # seconds
        first=0,
        name='realtime'
    )

    # Daily report at 08:00
    app.job_queue.run_daily(
        daily_report,
        time=datetime_time(8, 0, tzinfo=moscow_tz),
        name='daily'
    )

    logger.info("Bot started with simplified realtime support")
    logger.info(f"Initial state: {state}")

    try:
        app.run_polling(drop_pending_updates=True)
    except Exception as e:
        logger.error(f"Bot crashed: {str(e)}", exc_info=True)
    finally:
        logger.info("Bot stopped")