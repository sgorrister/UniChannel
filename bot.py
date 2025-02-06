import os
import sqlite3
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Логування ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Читання змінної середовища для токена ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ Не вказано BOT_TOKEN у змінних середовища!")
    exit(1)

# --- Файл бази даних ---
DB_PATH = "channels.db"

# --- Функції для роботи з базою даних ---
def init_db():
    """Створює таблиці для зберігання каналів"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT UNIQUE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS target_channel (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            channel TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_channel_db(channel: str) -> bool:
    """Додає канал (ID або @username) у список моніторингу"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO channels (channel) VALUES (?)", (channel,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_channel_db(channel: str) -> bool:
    """Видаляє канал зі списку"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE channel = ?", (channel,))
    conn.commit()
    result = c.rowcount > 0
    conn.close()
    return result

def list_channels_db() -> list:
    """Отримує список моніторюваних каналів"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel FROM channels")
    channels = c.fetchall()
    conn.close()
    return [ch[0] for ch in channels]

def set_target_channel_db(channel: str):
    """Задає канал для пересилання"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO target_channel (id, channel) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET channel=?", (channel, channel))
    conn.commit()
    conn.close()

def get_target_channel_db():
    """Отримує канал для пересилання"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel FROM target_channel WHERE id = 1")
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

# --- Обробники команд ---
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Додає канал до списку моніторингу"""
    if not context.args:
        await update.message.reply_text("📝 Використання: `/add_channel @channelname` або `/add_channel -1001234567890`", parse_mode="Markdown")
        return
    channel = context.args[0]
    if add_channel_db(channel):
        await update.message.reply_text(f"✅ Канал {channel} додано до моніторингу.")
    else:
        await update.message.reply_text(f"⚠️ Канал {channel} вже є у списку.")

async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Видаляє канал із моніторингу"""
    if not context.args:
        await update.message.reply_text("📝 Використання: `/remove_channel @channelname` або `/remove_channel -1001234567890`", parse_mode="Markdown")
        return
    channel = context.args[0]
    if remove_channel_db(channel):
        await update.message.reply_text(f"🗑 Канал {channel} видалено.")
    else:
        await update.message.reply_text(f"❌ Канал {channel} не знайдено у списку.")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Виводить список каналів"""
    channels = list_channels_db()
    if channels:
        text = "📋 Моніторяться такі канали:\n" + "\n".join(str(ch) for ch in channels)
    else:
        text = "ℹ️ Немає моніторюваних каналів."
    await update.message.reply_text(text)

async def set_target_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Задає канал для пересилання"""
    if not context.args:
        await update.message.reply_text("📝 Використання: `/set_target @mytargetchannel` або `/set_target -1009876543210`", parse_mode="Markdown")
        return
    channel = context.args[0]
    set_target_channel_db(channel)
    await update.message.reply_text(f"✅ Канал для пересилання встановлено: {channel}")

async def get_target_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує поточний канал пересилання"""
    channel = get_target_channel_db()
    if channel:
        await update.message.reply_text(f"🎯 Поточний канал пересилання: {channel}")
    else:
        await update.message.reply_text("ℹ️ Канал пересилання не задано.")

# --- Обробник постів з каналів ---
async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пересилає пости з моніторюваних каналів у цільовий канал"""
    channel_id = update.channel_post.chat.id
    monitored_channels = list_channels_db()
    target_channel = get_target_channel_db() or update.channel_post.chat.id  # Якщо немає - пересилає в себе

    # Перевіряємо чи є канал у списку моніторингу (за ID або username)
    if str(channel_id) in monitored_channels or any(f"@{update.channel_post.chat.username}" == ch for ch in monitored_channels):
        try:
            await context.bot.forward_message(
                chat_id=target_channel,
                from_chat_id=channel_id,
                message_id=update.channel_post.message_id
            )
            logger.info(f"Переслано повідомлення з {channel_id} у {target_channel}.")
        except Exception as e:
            logger.error(f"Помилка пересилання: {e}")

# --- Головна функція ---
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("add_channel", add_channel))
    app.add_handler(CommandHandler("remove_channel", remove_channel))
    app.add_handler(CommandHandler("list_channels", list_channels))
    app.add_handler(CommandHandler("set_target", set_target_channel))
    app.add_handler(CommandHandler("get_target", get_target_channel))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.CHANNEL, channel_post_handler))

    app.run_polling()

if __name__ == "__main__":
    main()
