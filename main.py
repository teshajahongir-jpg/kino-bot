import logging
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ==== SOZLAMALAR (shu 3 ta qatorni o'zgartiring) ====
BOT_TOKEN = "8790540529:AAHMnT8hvu6DvZ7TyzxxwQALjc9MkX6X8ZA"        # @BotFather bergan token
ADMIN_IDS = [8252424738]                    # sizning Telegram ID (@userinfobot dan)
CHANNEL_ID = -1004378756719                 # yopiq kanal ID (@getidsbot dan)

logging.basicConfig(level=logging.INFO)

# ==== BAZA ====
conn = sqlite3.connect("movies.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS movies (
    code INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    joined_at TEXT DEFAULT (datetime('now'))
)
""")
conn.commit()

# Broadcast holatini vaqtincha eslab turish uchun (kim /broadcast bosgan)
awaiting_broadcast = set()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def save_user(user):
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
        (user.id, user.username or ""),
    )
    conn.commit()


def get_users_count() -> int:
    cur.execute("SELECT COUNT(*) FROM users")
    return cur.fetchone()[0]


def get_movies_count() -> int:
    cur.execute("SELECT COUNT(*) FROM movies")
    return cur.fetchone()[0]


# ==== ADMIN PANEL ====

def admin_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton("🎬 Kinolar ro'yxati", callback_data="admin_movies")],
        [InlineKeyboardButton("📢 Xabar yuborish", callback_data="admin_broadcast")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Sizda ruxsat yo'q ❌")
        return

    await update.message.reply_text(
        "🛠 Admin panel",
        reply_markup=admin_menu_keyboard(),
    )


async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(query.from_user.id):
        await query.edit_message_text("Sizda ruxsat yo'q ❌")
        return

    if query.data == "admin_stats":
        users_count = get_users_count()
        movies_count = get_movies_count()
        text = (
            f"📊 Statistika\n\n"
            f"👥 Foydalanuvchilar soni: {users_count}\n"
            f"🎬 Kinolar soni: {movies_count}"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "admin_movies":
        cur.execute("SELECT code FROM movies ORDER BY code")
        rows = cur.fetchall()
        if rows:
            codes = ", ".join(str(r[0]) for r in rows)
            text = f"🎬 Mavjud kino kodlari:\n\n{codes}"
        else:
            text = "Hozircha hech qanday kino qo'shilmagan."
        keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "admin_broadcast":
        awaiting_broadcast.add(query.from_user.id)
        keyboard = [[InlineKeyboardButton("❌ Bekor qilish", callback_data="admin_cancel_broadcast")]]
        await query.edit_message_text(
            "📢 Endi barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yozing.\n"
            "(Matn, rasm, video — istalgani bo'lishi mumkin)",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data == "admin_cancel_broadcast":
        awaiting_broadcast.discard(query.from_user.id)
        await query.edit_message_text("Bekor qilindi.", reply_markup=admin_menu_keyboard())

    elif query.data == "admin_back":
        await query.edit_message_text("🛠 Admin panel", reply_markup=admin_menu_keyboard())


async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin broadcast rejimida bo'lsa, keyingi xabarini hammaga yuboradi"""
    user_id = update.effective_user.id

    cur.execute("SELECT user_id FROM users")
    all_users = [row[0] for row in cur.fetchall()]

    sent, failed = 0, 0
    for uid in all_users:
        try:
            # copy_message orqali yuboriladi — "kimdan kelgani" ko'rinmaydi,
            # oddiy bot xabari sifatida boradi
            await context.bot.copy_message(
                chat_id=uid,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
            sent += 1
        except Exception:
            failed += 1

    awaiting_broadcast.discard(user_id)
    await update.message.reply_text(
        f"✅ Xabar yuborildi!\n\n📨 Yuborildi: {sent}\n⚠️ Yetib bormadi: {failed}"
    )


# ==== ODDIY HANDLERLAR ====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.reply_text(
        "Salom! 🎬\nKino kodini yuboring, masalan: 1"
    )


async def add_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/add <kod> — video xabariga reply qilib yuboriladi (faqat admin)"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("Sizda ruxsat yo'q ❌")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "Video xabariga reply qilib /add <kod> deb yozing.\nMasalan: /add 1"
        )
        return

    if not context.args:
        await update.message.reply_text("Kodni kiriting. Masalan: /add 1")
        return

    try:
        code = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Kod raqam bo'lishi kerak!")
        return

    replied = update.message.reply_to_message

    # Videoni yopiq kanalga nusxalab joylaymiz
    forwarded = await context.bot.copy_message(
        chat_id=CHANNEL_ID,
        from_chat_id=update.effective_chat.id,
        message_id=replied.message_id,
    )

    cur.execute(
        "INSERT OR REPLACE INTO movies (code, message_id) VALUES (?, ?)",
        (code, forwarded.message_id),
    )
    conn.commit()

    await update.message.reply_text(f"✅ Kino {code}-kod bilan saqlandi!")


async def delete_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/delete <kod> — faqat admin"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Sizda ruxsat yo'q ❌")
        return

    if not context.args:
        await update.message.reply_text("Kodni kiriting. Masalan: /delete 1")
        return

    try:
        code = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Kod raqam bo'lishi kerak!")
        return

    cur.execute("DELETE FROM movies WHERE code=?", (code,))
    conn.commit()
    await update.message.reply_text(f"🗑 {code}-kod o'chirildi.")


async def send_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi raqam yozganda kino yuboriladi (yoki admin broadcast yozayotgan bo'lsa, shu qabul qilinadi)"""
    save_user(update.effective_user)

    user_id = update.effective_user.id

    # Agar admin hozir "xabar yuborish" rejimida bo'lsa
    if user_id in awaiting_broadcast and is_admin(user_id):
        await do_broadcast(update, context)
        return

    text = (update.message.text or "").strip()

    if not text.isdigit():
        await update.message.reply_text(
            "Iltimos, faqat kino kodini (raqam) yuboring."
        )
        return

    code = int(text)
    cur.execute("SELECT message_id FROM movies WHERE code=?", (code,))
    row = cur.fetchone()

    if row is None:
        await update.message.reply_text("❌ Bunday kodli kino topilmadi.")
        return

    message_id = row[0]
    try:
        await context.bot.copy_message(
            chat_id=update.effective_chat.id,
            from_chat_id=CHANNEL_ID,
            message_id=message_id,
        )
    except Exception as e:
        logging.error(e)
        await update.message.reply_text("Xatolik yuz berdi, keyinroq urinib ko'ring.")


async def broadcast_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Agar admin broadcast rejimida rasm/video/fayl yuborsa"""
    user_id = update.effective_user.id
    if user_id in awaiting_broadcast and is_admin(user_id):
        await do_broadcast(update, context)


class PingHandler(BaseHTTPRequestHandler):
    """Render'ga 'tirikman' deb javob beruvchi kichik HTTP server"""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot ishlab turibdi")

    def log_message(self, format, *args):
        pass  # konsolni keraksiz loglar bilan to'ldirmaslik uchun


def run_ping_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()


def main():
    # Render "Web Service" port kutgani uchun fon jarayonida kichik server ishga tushiramiz
    threading.Thread(target=run_ping_server, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("add", add_movie))
    app.add_handler(CommandHandler("delete", delete_movie))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, send_movie))
    app.add_handler(
        MessageHandler(
            (filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
            broadcast_media,
        )
    )

    print("Bot ishga tushdi...")
    app.run_polling()


if __name__ == "__main__":
    main()
