import os
import sqlite3
import logging
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    CallbackQueryHandler,
    PicklePersistence
)

# Для ConversationHandler (стани):
from telegram.ext import (
    ConversationHandler
)

# --- Логування ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Читання змінної середовища для токена ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ Не вказано BOT_TOKEN у змінних середовища!")
    exit(1)

# --- Шлях до файлу бази ---
DB_PATH = "channels.db"

# --- Список станів для ConversationHandler ---
CHOOSING, ADDING, REMOVING, SETTING_TARGET = range(4)

# --- Функції для роботи з базою даних ---
def init_db():
    """Створює таблиці для зберігання каналів і цільового каналу."""
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
    """Додає канал (ID або @username) у список моніторингу."""
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
    """Видаляє канал зі списку."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM channels WHERE channel = ?", (channel,))
    conn.commit()
    result = c.rowcount > 0
    conn.close()
    return result

def list_channels_db() -> list:
    """Отримує список моніторюваних каналів."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel FROM channels")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def set_target_channel_db(channel: str):
    """Задає канал для пересилання."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO target_channel (id, channel)
        VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET channel=excluded.channel
    """, (channel,))
    conn.commit()
    conn.close()

def get_target_channel_db():
    """Отримує канал для пересилання."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel FROM target_channel WHERE id = 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


# --- Допоміжні функції ---

def main_menu_keyboard():
    """Створює клавіатуру основного меню."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ Add channel"), KeyboardButton("➖ Remove channel")],
            [KeyboardButton("📋 List channels"), KeyboardButton("🎯 Set target")],
            [KeyboardButton("🎯 Get target"), KeyboardButton("❌ Exit")]
        ],
        resize_keyboard=True
    )

# --- Логіка ConversationHandler ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /start: Виводить меню.
    Переходимо у стан CHOOSING, де чекаємо вибору дії.
    """
    await update.message.reply_text(
        "Привіт! Оберіть дію з меню нижче:",
        reply_markup=main_menu_keyboard()
    )
    return CHOOSING

async def choose_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Користувач натискає кнопку в меню (Add channel, Remove channel тощо).
    Залежно від вибору — переходимо в інший стан або виконуємо дію.
    """
    text = update.message.text

    if text == "➕ Add channel":
        await update.message.reply_text("Введіть ID або @username каналу, який потрібно додати:")
        return ADDING

    elif text == "➖ Remove channel":
        await update.message.reply_text("Введіть ID або @username каналу, який потрібно видалити:")
        return REMOVING

    elif text == "📋 List channels":
        channels = list_channels_db()
        if channels:
            msg = "📋 Моніторяться такі канали:\n" + "\n".join(channels)
        else:
            msg = "ℹ️ Немає моніторюваних каналів."
        await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
        return CHOOSING

    elif text == "🎯 Set target":
        await update.message.reply_text("Введіть ID або @username каналу, куди пересилати пости:")
        return SETTING_TARGET

    elif text == "🎯 Get target":
        channel = get_target_channel_db()
        if channel:
            await update.message.reply_text(f"Поточний канал для пересилання: {channel}",
                                            reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text("Цільовий канал ще не задано.",
                                            reply_markup=main_menu_keyboard())
        return CHOOSING

    elif text == "❌ Exit":
        await update.message.reply_text("Бувай!", reply_markup=None)
        return ConversationHandler.END

    else:
        # Якщо прийшов невідомий текст, повертаємось до меню
        await update.message.reply_text("Будь ласка, скористайтеся кнопками меню.",
                                        reply_markup=main_menu_keyboard())
        return CHOOSING

# --- Обробка введених даних від користувача після натискання кнопок ---
async def adding_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Користувач вводить ID або @username каналу, щоб додати."""
    channel = update.message.text.strip()
    if add_channel_db(channel):
        await update.message.reply_text(f"✅ Канал {channel} успішно додано.",
                                        reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(f"⚠️ Канал {channel} вже є у списку або помилка.",
                                        reply_markup=main_menu_keyboard())
    return CHOOSING

async def removing_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Користувач вводить ID або @username каналу, щоб видалити."""
    channel = update.message.text.strip()
    if remove_channel_db(channel):
        await update.message.reply_text(f"🗑 Канал {channel} видалено.",
                                        reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(f"❌ Канал {channel} не знайдено у списку.",
                                        reply_markup=main_menu_keyboard())
    return CHOOSING

async def setting_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Користувач вводить ID або @username каналу, який стане цільовим для пересилання."""
    channel = update.message.text.strip()
    set_target_channel_db(channel)
    await update.message.reply_text(f"🎯 Цільовий канал встановлено: {channel}",
                                    reply_markup=main_menu_keyboard())
    return CHOOSING

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обробник на випадок, якщо користувач хоче вийти з розмови достроково.
    """
    await update.message.reply_text("Вихід із меню.", reply_markup=None)
    return ConversationHandler.END

# --- Обробник постів із каналів ---
async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Пересилає пости з моніторюваних каналів у цільовий канал.
    Якщо цільового каналу немає, пересилає у той самий канал (умовно "в себе").
    """
    channel_id = update.channel_post.chat.id
    monitored_channels = list_channels_db()
    target_channel = get_target_channel_db() or channel_id  # Якщо не задано, пересилає в джерело

    # Перевіряємо, чи є канал у списку моніторингу (за ID або @username)
    # channel_id (int) у Telegram часто виглядає як -1001234567890
    # username = update.channel_post.chat.username
    username = update.channel_post.chat.username

    in_list_by_id = str(channel_id) in monitored_channels
    in_list_by_username = (f"@{username}" in monitored_channels) if username else False

    if in_list_by_id or in_list_by_username:
        try:
            await context.bot.forward_message(
                chat_id=target_channel,
                from_chat_id=channel_id,
                message_id=update.channel_post.message_id
            )
            logger.info(f"Переслано з {channel_id} у {target_channel}.")
        except Exception as e:
            logger.error(f"Помилка пересилання: {e}")


# --- Головна функція ---
def main():
    init_db()

    # Створюємо застосунок (бот)
    # Можна додати persistence для зберігання стану розмов, якщо потрібно.
    app = Application.builder().token(BOT_TOKEN).build()

    # Описуємо ConversationHandler, який керуватиме "прикріпленим меню"
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],

        states={
            CHOOSING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, choose_action)
            ],
            ADDING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, adding_channel)
            ],
            REMOVING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, removing_channel)
            ],
            SETTING_TARGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, setting_target)
            ],
        },

        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Реєструємо його
    app.add_handler(conv_handler)

    # Обробник постів із каналів (не плутаємо з особистим листуванням)
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.CHANNEL, channel_post_handler))

    logger.info("Бот запущено. Очікуємо повідомлення...")
    app.run_polling()

if __name__ == "__main__":
    main()
