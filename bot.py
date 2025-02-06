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
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler
)

# СТАНИ (ConversationHandler)
MAIN_MENU, ADDING_GROUP, REMOVING_GROUP, GROUP_MENU, ADDING_CHANNEL, REMOVING_CHANNEL, SETTING_TARGET = range(7)

# Логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Читаємо токен
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не задано у змінних середовища!")
    exit(1)

# Шлях до бази
DB_PATH = "channels.db"


# ------------------------------------------------------------------------------------
#                         РОБОТА З БАЗОЮ ДАНИХ
# ------------------------------------------------------------------------------------

def init_db():
    """Створює таблиці для груп (з user_id) та каналів у групах."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            target_channel TEXT,
            UNIQUE(user_id, name)
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS group_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            UNIQUE(group_id, channel),
            FOREIGN KEY(group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()


# --- Робота з GROUPS ---
def add_group_db(user_id: int, name: str) -> bool:
    """Створює нову групу для користувача user_id з назвою name."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO groups (user_id, name) VALUES (?, ?)", (user_id, name))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_group_db(user_id: int, name: str) -> bool:
    """Видаляє групу (і пов'язані канали) у даного user_id."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE user_id = ? AND name = ?", (user_id, name))
    conn.commit()
    deleted = (c.rowcount > 0)
    conn.close()
    return deleted

def list_groups_db(user_id: int) -> list[tuple[str, str|None]]:
    """Повертає список (name, target_channel) усіх груп користувача user_id."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT name, target_channel FROM groups WHERE user_id=? ORDER BY id", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_group_id_by_name(user_id: int, name: str) -> int|None:
    """Повертає id групи з назвою name для user_id, або None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id FROM groups WHERE user_id=? AND name=?", (user_id, name))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


# --- Робота з group_channels ---
def add_channel_to_group_db(group_id: int, channel: str) -> bool:
    """Додає канал до групи group_id."""
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
    """Видаляє канал із групи."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM group_channels WHERE group_id=? AND channel=?", (group_id, channel))
    conn.commit()
    deleted = (c.rowcount > 0)
    conn.close()
    return deleted

def list_channels_in_group_db(group_id: int) -> list[str]:
    """Повертає список каналів (str) у групі group_id."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT channel FROM group_channels WHERE group_id=?", (group_id,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


# --- Робота з target_channel ---
def set_group_target_db(group_id: int, target_channel: str):
    """Задає (або змінює) target_channel для групи group_id."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE groups SET target_channel=? WHERE id=?", (target_channel, group_id))
    conn.commit()
    conn.close()

def get_group_target_db(group_id: int) -> str|None:
    """Повертає target_channel для групи group_id, або None."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT target_channel FROM groups WHERE id=?", (group_id,))
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
    """Меню для поточної групи."""
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

# --- /start ---
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Старт розмови з користувачем."""
    await update.message.reply_text(
        "Вітаю! Кожен користувач має свої групи.\nОберіть дію:",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

# 1) MAIN_MENU: обробляє текст, що приходить із кнопок «Add Group», «Remove Group» тощо.
async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "➕ Add Group":
        await update.message.reply_text("Введіть назву нової групи:")
        return ADDING_GROUP

    elif text == "➖ Remove Group":
        await update.message.reply_text("Введіть назву групи, яку треба видалити:")
        return REMOVING_GROUP

    elif text == "📋 List Groups":
        groups = list_groups_db(user_id)
        if groups:
            lines = []
            for (gname, tgt) in groups:
                lines.append(f"- **{gname}** (target: {tgt if tgt else 'не задано'})")
            msg = "Ваші групи:\n" + "\n".join(lines)
        else:
            msg = "У вас немає груп."
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    elif text == "🔽 Select Group":
        # Показуємо inline-клавіатуру з переліком груп
        groups = list_groups_db(user_id)
        if not groups:
            await update.message.reply_text("У вас немає груп для вибору!", reply_markup=main_menu_keyboard())
            return MAIN_MENU

        keyboard = []
        for (gname, _) in groups:
            # callback_data зберігатиме ім'я групи
            keyboard.append([InlineKeyboardButton(gname, callback_data=f"selectgroup|{gname}")])
        markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("Оберіть групу:", reply_markup=markup)
        # Залишаємося у стані MAIN_MENU, але тепер чекаємо CallbackQuery
        return MAIN_MENU

    elif text == "❌ Exit":
        await update.message.reply_text("Бувай!", reply_markup=None)
        return ConversationHandler.END

    else:
        await update.message.reply_text(
            "Будь ласка, скористайтеся кнопками меню.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

# 2) Додавання групи
async def adding_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    group_name = update.message.text.strip()

    if add_group_db(user_id, group_name):
        await update.message.reply_text(
            f"✅ Групу '{group_name}' створено!",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            f"⚠️ Група '{group_name}' вже існує або помилка.",
            reply_markup=main_menu_keyboard()
        )
    return MAIN_MENU

# 3) Видалення групи
async def removing_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    group_name = update.message.text.strip()

    if remove_group_db(user_id, group_name):
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


# --- CALLBACKQUERY для вибору групи (натисканні на InlineKeyboard) ---
async def select_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка callback_data='selectgroup|...' при натисканні на Inline-кнопку."""
    query = update.callback_query
    await query.answer()  # Відповідаємо, щоб «зникла» анімація завантаження

    data = query.data  # Наприклад, "selectgroup|MyGroupName"
    prefix, gname = data.split("|", 1)

    if prefix != "selectgroup":
        return  # Ігноруємо інші callback'и

    user_id = update.effective_user.id
    group_id = get_group_id_by_name(user_id, gname)
    if not group_id:
        # Можливо, групу видалили міжчасом
        await query.edit_message_text(
            text=f"Групу '{gname}' не знайдено.",
        )
        return MAIN_MENU

    # Запам'ятовуємо поточну групу
    context.user_data["current_group_id"] = group_id
    context.user_data["current_group_name"] = gname

    # Редагуємо повідомлення, де були кнопки, і показуємо, що ми вибрали групу
    await query.edit_message_text(
        text=f"Обрано групу '{gname}'.",
    )
    # Надсилаємо окреме повідомлення з меню групи
    await query.message.reply_text(
        f"Тепер ви працюєте з групою '{gname}'.",
        reply_markup=group_menu_keyboard()
    )
    return GROUP_MENU


# 4) Меню групи
async def group_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    group_id = context.user_data.get("current_group_id")
    group_name = context.user_data.get("current_group_name")

    if not group_id:
        # Якщо чомусь немає поточної групи, повертаємося в головне меню
        await update.message.reply_text(
            "Не обрано групу.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    if text == "➕ Add Channel":
        await update.message.reply_text("Введіть @username або ID каналу:")
        return ADDING_CHANNEL

    elif text == "➖ Remove Channel":
        await update.message.reply_text("Введіть @username або ID каналу для видалення:")
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
            msg = f"У групи '{group_name}' не задано target-каналу."
        await update.message.reply_text(msg, reply_markup=group_menu_keyboard())
        return GROUP_MENU

    elif text == "⬅️ Back to Main Menu":
        await update.message.reply_text(
            "Повертаємось у головне меню.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    else:
        await update.message.reply_text(
            "Скористайтеся кнопками меню.",
            reply_markup=group_menu_keyboard()
        )
        return GROUP_MENU


# --- Додавання каналу у групу ---
async def adding_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel = update.message.text.strip()
    group_id = context.user_data["current_group_id"]
    group_name = context.user_data["current_group_name"]

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
    channel = update.message.text.strip()
    group_id = context.user_data["current_group_id"]
    group_name = context.user_data["current_group_name"]

    if remove_channel_from_group_db(group_id, channel):
        await update.message.reply_text(
            f"🗑 Канал {channel} видалено з групи '{group_name}'.",
            reply_markup=group_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            f"❌ Канал {channel} не знайдено в групі '{group_name}'.",
            reply_markup=group_menu_keyboard()
        )
    return GROUP_MENU

# --- Задання target-каналу ---
async def setting_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel = update.message.text.strip()
    group_id = context.user_data["current_group_id"]
    group_name = context.user_data["current_group_name"]

    set_group_target_db(group_id, channel)
    await update.message.reply_text(
        f"🎯 Цільовий канал для групи '{group_name}' тепер: {channel}",
        reply_markup=group_menu_keyboard()
    )
    return GROUP_MENU


# --- Завершення розмови ---
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cancel - завершує розмову."""
    await update.message.reply_text("Вихід.", reply_markup=None)
    return ConversationHandler.END


# ------------------------------------------------------------------------------------
#               ОБРОБНИК ПОВІДОМЛЕНЬ ІЗ КАНАЛІВ (пересилання постів)
# ------------------------------------------------------------------------------------
async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Коли приходить повідомлення з каналу,
    перевіряємо, чи належить цей канал одній або кільком групам.
    Якщо так – пересилаємо у їхній target, якщо він заданий.
    """
    channel_id = update.channel_post.chat.id
    username = update.channel_post.chat.username  # None, якщо приватний канал без username
    msg_id = update.channel_post.message_id

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Витягаємо всі групи (у всіх користувачів)
    c.execute("SELECT id, name, target_channel FROM groups")
    all_groups = c.fetchall()

    for (g_id, g_name, g_target) in all_groups:
        # Перевіряємо, чи в group_channels є канал = channel_id (str) або = @username
        c.execute("""
            SELECT COUNT(*) FROM group_channels
             WHERE group_id=?
               AND (channel=? OR channel=?)
        """, (g_id, str(channel_id), f"@{username}" if username else "_no_username_"))
        (count_chan,) = c.fetchone()

        if count_chan > 0:
            # Цей канал входить до групи g_id
            if g_target:
                try:
                    await context.bot.forward_message(
                        chat_id=g_target,
                        from_chat_id=channel_id,
                        message_id=msg_id
                    )
                    logger.info(f"[Group: {g_name}] Переслано з {channel_id} до {g_target}.")
                except Exception as e:
                    logger.error(f"[Group: {g_name}] Помилка пересилання: {e}")
            else:
                logger.info(f"[Group: {g_name}] Target не задано, не пересилаємо.")

    conn.close()


# ------------------------------------------------------------------------------------
#                          ГОЛОВНА ФУНКЦІЯ
# ------------------------------------------------------------------------------------
def main():
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    # Створюємо ConversationHandler зі станами
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],

        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
                # Обробник inline-кнопок у тому ж стані:
                CallbackQueryHandler(select_group_callback, pattern=r"^selectgroup\|.+$"),
            ],
            ADDING_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, adding_group)
            ],
            REMOVING_GROUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, removing_group)
            ],
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
    app.add_handler(conv_handler)

    # Обробляємо пости з каналів
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.CHANNEL, channel_post_handler))

    logger.info("Бот запущено. Очікуємо повідомлення...")
    app.run_polling()


if __name__ == "__main__":
    main()
