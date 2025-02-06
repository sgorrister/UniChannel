import os
import sqlite3
import logging

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    CallbackQueryHandler
)


# СТАНИ розмови (ConversationHandler)
MAIN_MENU, ADDING_GROUP, REMOVING_GROUP, SELECTING_GROUP_TEXT, GROUP_MENU, \
    ADDING_CHANNEL, REMOVING_CHANNEL, SETTING_TARGET = range(8)

# Логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Читаємо токен
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не задано в змінних середовища!")
    exit(1)

DB_PATH = "channels.db"


# ------------------------------------------------------------------------------------
#                         РОБОТА З БАЗОЮ ДАНИХ
# ------------------------------------------------------------------------------------

def init_db():
    """Створює таблиці для груп та їхніх каналів, якщо вони відсутні."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            target_channel TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS group_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            UNIQUE (group_id, channel),
            FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()


# ----------------------- Робота з GROUPS -----------------------

def add_group_db(name: str) -> bool:
    """
    Додає нову групу з переданою назвою.
    Повертає True, якщо створено успішно. Якщо така група існує – False.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO groups (name) VALUES (?)", (name,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_group_db(name: str) -> bool:
    """
    Видаляє групу за назвою (і всі її канали).
    Повертає True, якщо групу видалено.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE name = ?", (name,))
    conn.commit()
    deleted = c.rowcount > 0
    conn.close()
    return deleted

def list_groups_db() -> list:
    """Повертає список (id, name, target_channel) усіх груп."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, name, target_channel FROM groups ORDER BY id")
    rows = c.fetchall()
    conn.close()
    return rows  # [(group_id, name, target), ...]

def get_group_id_by_name(name: str):
    """За назвою групи отримуємо її id, або None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM groups WHERE name = ?", (name,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def get_group_name_by_id(group_id: int):
    """За group_id отримуємо name."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name FROM groups WHERE id = ?", (group_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ----------------------- Робота з group_channels -----------------------

def add_channel_to_group_db(group_id: int, channel: str) -> bool:
    """
    Додає канал (ID або @username) в групу group_id.
    Повертає True, якщо додано. Якщо вже було або помилка – False.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO group_channels (group_id, channel) VALUES (?, ?)", (group_id, channel))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_channel_from_group_db(group_id: int, channel: str) -> bool:
    """
    Видаляє канал із групи.
    Повертає True, якщо щось видалено.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM group_channels WHERE group_id = ? AND channel = ?", (group_id, channel))
    conn.commit()
    deleted = c.rowcount > 0
    conn.close()
    return deleted

def list_channels_in_group_db(group_id: int) -> list:
    """Повертає список каналів у зазначеній групі."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel FROM group_channels WHERE group_id = ?", (group_id,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ----------------------- Робота з target_channel -----------------------

def set_group_target_db(group_id: int, target_channel: str):
    """Задає (або змінює) target_channel у таблиці groups."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE groups SET target_channel = ? WHERE id = ?", (target_channel, group_id))
    conn.commit()
    conn.close()

def get_group_target_db(group_id: int):
    """Повертає target_channel для групи group_id, або None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT target_channel FROM groups WHERE id = ?", (group_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


# ------------------------------------------------------------------------------------
#                         КЛАВІАТУРИ
# ------------------------------------------------------------------------------------

def main_menu_keyboard():
    """Головне меню: керування списком груп."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ Add Group"), KeyboardButton("➖ Remove Group")],
            [KeyboardButton("📋 List Groups"), KeyboardButton("🔽 Select Group")],
            [KeyboardButton("❌ Exit")],
        ],
        resize_keyboard=True
    )

def group_menu_keyboard():
    """Меню для вибраної групи: керування каналами, target тощо."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("➕ Add Channel"), KeyboardButton("➖ Remove Channel")],
            [KeyboardButton("📋 List Channels"), KeyboardButton("🎯 Set Target")],
            [KeyboardButton("🎯 Get Target"), KeyboardButton("⬅️ Back to Main Menu")],
        ],
        resize_keyboard=True
    )

# ------------------------------------------------------------------------------------
#                         ЛОГІКА РОЗМОВИ (ConversationHandler)
# ------------------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start – показуємо головне меню, переходимо в стан MAIN_MENU.
    """
    await update.message.reply_text(
        "Вітаю! Це бот із кількома групами.\nОберіть дію:",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU


# ------------------------ MAIN MENU ------------------------
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє вибір у головному меню."""
    text = update.message.text

    if text == "➕ Add Group":
        await update.message.reply_text("Введіть назву нової групи:")
        return ADDING_GROUP

    elif text == "➖ Remove Group":
        await update.message.reply_text("Введіть назву групи, яку треба видалити:")
        return REMOVING_GROUP

    elif text == "📋 List Groups":
        all_groups = list_groups_db()  # [(id, name, target), ...]
        if all_groups:
            lines = []
            for g_id, g_name, tgt in all_groups:
                line = f"- **{g_name}** (target: {tgt if tgt else 'не задано'})"
                lines.append(line)
            msg = "Список груп:\n" + "\n".join(lines)
        else:
            msg = "Немає жодної групи."
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    elif text == "🔽 Select Group":
        groups = list_groups_db()
        if not groups:
            await update.message.reply_text("Немає груп для вибору!", reply_markup=main_menu_keyboard())
            return MAIN_MENU
        
        # Створюємо InlineKeyboard зі списком груп
        buttons = []
        for g_id, g_name, g_target in groups:
            buttons.append([InlineKeyboardButton(text=g_name, callback_data=f"select_group_{g_id}")])

        markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text("Оберіть групу:", reply_markup=markup)

        # Ми лишаємось у тому ж стані, але очікуємо CallbackQuery
        return MAIN_MENU

    elif text == "❌ Exit":
        await update.message.reply_text("Бувай!", reply_markup=None)
        return ConversationHandler.END

    else:
        await update.message.reply_text("Будь ласка, скористайтеся кнопками меню.", reply_markup=main_menu_keyboard())
        return MAIN_MENU

async def adding_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Користувач вводить назву нової групи."""
    group_name = update.message.text.strip()
    if add_group_db(group_name):
        await update.message.reply_text(
            f"✅ Групу '{group_name}' створено!",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            f"⚠️ Група з назвою '{group_name}' вже існує або помилка.",
            reply_markup=main_menu_keyboard()
        )
    return MAIN_MENU

async def removing_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Користувач вводить назву групи, яку треба видалити."""
    group_name = update.message.text.strip()
    if remove_group_db(group_name):
        await update.message.reply_text(
            f"🗑 Групу '{group_name}' видалено.",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            f"❌ Групу '{group_name}' не знайдено.",
            reply_markup=main_menu_keyboard()
        )
    return MAIN_MENU


# ----------------------- SELECTING GROUP (CallbackQuery) -----------------------

async def select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обробляє callback_data типу "select_group_123" і переходить у GROUP_MENU з обраною групою.
    """
    query = update.callback_query
    await query.answer()  # Закриваємо "loading" іконку

    data = query.data  # Наприклад: "select_group_7"
    if data.startswith("select_group_"):
        group_id_str = data.replace("select_group_", "")
        try:
            group_id = int(group_id_str)
        except ValueError:
            await query.message.reply_text("Помилка обробки group_id.")
            return MAIN_MENU

        group_name = get_group_name_by_id(group_id)
        if not group_name:
            await query.message.reply_text("❌ Такої групи більше немає!")
            return MAIN_MENU

        # Записуємо в user_data
        context.user_data["current_group_id"] = group_id
        context.user_data["current_group_name"] = group_name

        # Відповідаємо, що групу обрано
        await query.message.reply_text(
            f"✅ Обрано групу '{group_name}'.",
            reply_markup=group_menu_keyboard()
        )
        return GROUP_MENU

    # Якщо callback_data не відповідає формату
    await query.message.reply_text("Невідомий вибір.", reply_markup=main_menu_keyboard())
    return MAIN_MENU


# ------------------------ GROUP MENU ------------------------
async def group_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Користувач натискає кнопку в меню групи:
    - Add Channel
    - Remove Channel
    - List Channels
    - Set Target
    - Get Target
    - Back to Main Menu
    """
    text = update.message.text
    group_id = context.user_data.get("current_group_id")
    group_name = context.user_data.get("current_group_name")

    if not group_id:
        # Якщо з якоїсь причини немає поточної групи, повертаємось у MAIN_MENU
        await update.message.reply_text(
            "Виникла помилка: не обрано групу.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    if text == "➕ Add Channel":
        await update.message.reply_text("Введіть @username або ID каналу, який додати:")
        return ADDING_CHANNEL

    elif text == "➖ Remove Channel":
        await update.message.reply_text("Введіть @username або ID каналу, який видалити:")
        return REMOVING_CHANNEL

    elif text == "📋 List Channels":
        channels = list_channels_in_group_db(group_id)
        if channels:
            lines = "\n".join(channels)
            msg = f"Канали у групі '{group_name}':\n{lines}"
        else:
            msg = f"У групі '{group_name}' немає каналів."
        await update.message.reply_text(msg, reply_markup=group_menu_keyboard())
        return GROUP_MENU

    elif text == "🎯 Set Target":
        await update.message.reply_text("Введіть @username або ID цільового каналу:")
        return SETTING_TARGET

    elif text == "🎯 Get Target":
        target = get_group_target_db(group_id)
        if target:
            msg = f"Цільовий канал групи '{group_name}': {target}"
        else:
            msg = f"У групи '{group_name}' немає target-каналу."
        await update.message.reply_text(msg, reply_markup=group_menu_keyboard())
        return GROUP_MENU

    elif text == "⬅️ Back to Main Menu":
        # Повертаємось до головного меню
        await update.message.reply_text(
            "Повертаємось у головне меню.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    else:
        await update.message.reply_text("Скористайтеся кнопками меню.", reply_markup=group_menu_keyboard())
        return GROUP_MENU

# --- Додавання каналу в групу ---
async def adding_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Користувач вводить канал, який треба додати в поточну групу."""
    group_id = context.user_data.get("current_group_id")
    group_name = context.user_data.get("current_group_name")
    channel = update.message.text.strip()

    if add_channel_to_group_db(group_id, channel):
        await update.message.reply_text(
            f"✅ Канал {channel} додано до групи '{group_name}'.",
            reply_markup=group_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            f"⚠️ Канал {channel} вже є у групі або помилка.",
            reply_markup=group_menu_keyboard()
        )
    return GROUP_MENU

# --- Видалення каналу з групи ---
async def removing_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Користувач вводить канал, який треба видалити з поточної групи."""
    group_id = context.user_data.get("current_group_id")
    group_name = context.user_data.get("current_group_name")
    channel = update.message.text.strip()

    if remove_channel_from_group_db(group_id, channel):
        await update.message.reply_text(
            f"🗑 Канал {channel} видалено з групи '{group_name}'.",
            reply_markup=group_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            f"❌ Канал {channel} не знайдено в групі або помилка.",
            reply_markup=group_menu_keyboard()
        )
    return GROUP_MENU

# --- Задання target-каналу ---
async def setting_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Користувач вводить target-канал для поточної групи."""
    group_id = context.user_data.get("current_group_id")
    group_name = context.user_data.get("current_group_name")
    channel = update.message.text.strip()

    set_group_target_db(group_id, channel)
    await update.message.reply_text(
        f"🎯 Цільовий канал для групи '{group_name}' тепер: {channel}",
        reply_markup=group_menu_keyboard()
    )
    return GROUP_MENU


# --------------------- Вихід із ConversationHandler ---------------------
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel або команда, що завершує розмову."""
    await update.message.reply_text("Вихід.", reply_markup=None)
    return ConversationHandler.END


# ------------------------------------------------------------------------------------
#                 ОБРОБНИК ПОВІДОМЛЕНЬ ІЗ КАНАЛІВ (пересилання постів)
# ------------------------------------------------------------------------------------

async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Перевіряємо всі групи й усі канали в них.
    Якщо channel_id / username входить у групу – пересилаємо пост у target цієї групи.
    Якщо target не задано, можна пропустити або переслати "в себе".
    """
    channel_id = update.channel_post.chat.id
    username = update.channel_post.chat.username  # None, якщо приватний
    message_id = update.channel_post.message_id

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Беремо всі групи
    c.execute("SELECT id, name, target_channel FROM groups")
    all_groups = c.fetchall()  # [(g_id, name, target), ...]

    for (g_id, g_name, g_target) in all_groups:
        # Перевіряємо, чи є (channel_id) або (@username) у group_channels
        c.execute("""
            SELECT COUNT(*) FROM group_channels
            WHERE group_id = ?
              AND (channel = ? OR channel = ?)
        """, (g_id, str(channel_id), f"@{username}" if username else "_none_"))
        count_row = c.fetchone()
        if count_row and count_row[0] > 0:
            # Цей пост належить групі g_id
            if g_target:
                # Пересилаємо
                try:
                    await context.bot.forward_message(
                        chat_id=g_target,
                        from_chat_id=channel_id,
                        message_id=message_id
                    )
                    logger.info(f"[{g_name}] Переслано з {channel_id} до {g_target}.")
                except Exception as e:
                    logger.error(f"[{g_name}] Помилка пересилання: {e}")
            else:
                logger.info(f"[{g_name}] Target не встановлено. Пропускаємо.")

    conn.close()


# ------------------------------------------------------------------------------------
#                         ГОЛОВНА ФУНКЦІЯ
# ------------------------------------------------------------------------------------
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],

        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler)
            ],
            ADDING_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, adding_group)
            ],
            REMOVING_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, removing_group)
            ],
            # SELECTING_GROUP_TEXT - більше не використовуємо, бо тепер вибір іде через InlineKeyboard

            GROUP_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, group_menu_handler)
            ],
            ADDING_CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, adding_channel)
            ],
            REMOVING_CHANNEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, removing_channel)
            ],
            SETTING_TARGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, setting_target)
            ],
        },

        fallbacks=[CommandHandler("cancel", cmd_cancel)]
    )

    # Реєструємо розмовник
    app.add_handler(conv_handler)

    # CallbackQueryHandler для натискання кнопок "Select Group"
    app.add_handler(CallbackQueryHandler(select_group_callback, pattern=r"^select_group_\d+$"))

    # Обробник постів із каналів
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.CHANNEL, channel_post_handler))

    logger.info("Бот запущено. Очікуємо повідомлення...")
    app.run_polling()


if __name__ == "__main__":
    main()
