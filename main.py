import logging
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ======================================================================
# SOZLAMALAR — shu qatorlarni o'zingiznikiga almashtiring
# ======================================================================
BOT_TOKEN = "8790540529:AAE6PFQXK7Xns0dGzxqXlZXaiFf0J0s2dbA"        # @BotFather bergan token

ADMIN_IDS = [8252424738, 2049500709]        # ikkinchi adminning ID'sini shu yerga yozing

CHANNEL_ID = -1004378756719                 # kinolar SAQLANADIGAN yopiq kanal ID (@getidsbot dan)

FORCE_SUB_CHANNEL = "@kadamkh"              # majburiy OBUNA kanali (ochiq, username bilan)

PREMIUM_CARD_NUMBER = "5614 6821 1353 0267"  # premium to'lov uchun karta raqami
PREMIUM_PRICE_TEXT = "15 000 so'm / oy"

# ======================================================================

logging.basicConfig(level=logging.INFO)

# ==== BAZA ====
conn = sqlite3.connect("movies.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS movies (
    code INTEGER PRIMARY KEY,
    message_id INTEGER NOT NULL,
    views INTEGER DEFAULT 0
)
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    premium INTEGER DEFAULT 0,
    joined_at TEXT DEFAULT (datetime('now'))
)
""")
conn.commit()

# Eski bazada ustun bo'lmasa ham xato bermasligi uchun
for stmt in [
    "ALTER TABLE movies ADD COLUMN views INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN premium INTEGER DEFAULT 0",
]:
    try:
        cur.execute(stmt)
        conn.commit()
    except sqlite3.OperationalError:
        pass

# Vaqtinchalik holatlar
awaiting_broadcast = set()   # kim "Xabar yuborish" bosgan (admin)
awaiting_receipt = set()     # kim Premium chek yuborishi kutilmoqda

MAIN_MENU_SEARCH = "🔍 Kino qidirish"
MAIN_MENU_LIST = "📚 Kinolar ro'yxati"
MAIN_MENU_TOP = "🔥 Eng ko'p ko'rilgan"
MAIN_MENU_PREMIUM = "⭐ Premium tarif"


# ==== YORDAMCHI FUNKSIYALAR ====

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_premium(user_id: int) -> bool:
    cur.execute("SELECT premium FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    return bool(row and row[0])


def set_premium(user_id: int, value: int = 1):
    cur.execute("UPDATE users SET premium=? WHERE user_id=?", (value, user_id))
    conn.commit()


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


def main_menu_keyboard():
    keyboard = [
        [MAIN_MENU_SEARCH, MAIN_MENU_LIST],
        [MAIN_MENU_TOP, MAIN_MENU_PREMIUM],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """Foydalanuvchi majburiy obuna kanaliga a'zo yoki yo'qligini tekshiradi"""
    if not FORCE_SUB_CHANNEL:
        return True

    try:
        member = await context.bot.get_chat_member(
            chat_id=FORCE_SUB_CHANNEL, user_id=user_id
        )
        if member.status not in ("member", "administrator", "creator"):
            return False
    except Exception as e:
        logging.error(f"Obunani tekshirishda xato: {e}")
        # Tekshirib bo'lmasa (masalan bot admin emas), botni butunlay to'xtatmaslik uchun ruxsat beramiz
        return True

    return True


def subscribe_keyboard():
    channel_username = FORCE_SUB_CHANNEL.lstrip("@")
    keyboard = [
        [InlineKeyboardButton("📢 Kanalga qo'shilish", url=f"https://t.me/{channel_username}")],
        [InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_sub")],
    ]
    return InlineKeyboardMarkup(keyboard)


def premium_text() -> str:
    return (
        "⭐ <b>Premium tarif</b>\n\n"
        "Premium tarifga o'tib, quyidagi imkoniyatlarga ega bo'ling:\n"
        "🚫 Reklamalarsiz foydalanish\n"
        "🚫 Majburiy obunasiz kirish\n"
        "🔥 \"Eng ko'p ko'rilgan kinolar\" bo'limiga kirish\n"
        "⚡ Tezkor va qulay xizmat\n\n"
        f"💳 Narxi: <b>{PREMIUM_PRICE_TEXT}</b>\n\n"
        f"To'lovni quyidagi karta raqamiga o'tkazing:\n"
        f"<code>{PREMIUM_CARD_NUMBER}</code>\n\n"
        "✅ To'lovni amalga oshirgach, chek (skrinshot) rasmini shu yerga yuboring.\n"
        "Admin tasdiqlagach, Premium tarif faollashadi."
    )


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

        cur.execute("SELECT user_id, username FROM users ORDER BY joined_at DESC")
        rows = cur.fetchall()

        lines = []
        for uid, username in rows:
            if username:
                lines.append(f"• @{username} — <code>{uid}</code>")
            else:
                lines.append(f"• (username yo'q) — <code>{uid}</code>")

        users_list_text = "\n".join(lines) if lines else "Hozircha foydalanuvchi yo'q."

        if len(users_list_text) > 3500:
            users_list_text = users_list_text[:3500] + "\n\n... (ro'yxat uzun, qisqartirildi)"

        text = (
            f"📊 Statistika\n\n"
            f"👥 Foydalanuvchilar soni: {users_count}\n"
            f"🎬 Kinolar soni: {movies_count}\n\n"
            f"👤 Foydalanuvchilar ro'yxati:\n{users_list_text}"
        )
        keyboard = [[InlineKeyboardButton("⬅️ Orqaga", callback_data="admin_back")]]
        await query.edit_message_text(
            text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML"
        )

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
            "(Matn, rasm, video — istalgani bo'lishi mumkin)\n\n"
            "Xabar bot nomidan boradi, kim yuborgani ko'rinmaydi.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    elif query.data == "admin_cancel_broadcast":
        awaiting_broadcast.discard(query.from_user.id)
        await query.edit_message_text("Bekor qilindi.", reply_markup=admin_menu_keyboard())

    elif query.data == "admin_back":
        await query.edit_message_text("🛠 Admin panel", reply_markup=admin_menu_keyboard())


async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'✅ Obuna bo'ldim' tugmasi bosilganda ishlaydi"""
    query = update.callback_query
    user_id = query.from_user.id

    if await is_subscribed(context, user_id):
        await query.answer("✅ Rahmat, obuna tasdiqlandi!")
        await query.message.delete()
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Salom! 🎬\nKino kodini yuboring yoki pastdagi tugmalardan foydalaning.",
            reply_markup=main_menu_keyboard(),
        )
    else:
        await query.answer("❌ Siz hali kanalga qo'shilmagansiz!", show_alert=True)


async def do_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin broadcast rejimida bo'lsa, keyingi xabarini hammaga yuboradi"""
    user_id = update.effective_user.id

    cur.execute("SELECT user_id FROM users")
    all_users = [row[0] for row in cur.fetchall()]

    sent, failed = 0, 0
    for uid in all_users:
        try:
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


# ==== PREMIUM ====

async def send_premium_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    awaiting_receipt.add(user_id)
    await update.message.reply_text(premium_text(), parse_mode="HTML")


async def show_top_movies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔥 Eng ko'p ko'rilgan tugmasi — faqat Premium foydalanuvchilar uchun"""
    user_id = update.effective_user.id

    if not is_admin(user_id) and not is_premium(user_id):
        awaiting_receipt.add(user_id)
        await update.message.reply_text(
            "🔒 Bu bo'lim faqat <b>Premium</b> foydalanuvchilar uchun.\n\n" + premium_text(),
            parse_mode="HTML",
        )
        return

    cur.execute("SELECT code, views FROM movies ORDER BY views DESC LIMIT 5")
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("Hozircha statistika yo'q.")
        return

    lines = [f"{i + 1}. Kod {code} — {views} marta ko'rilgan" for i, (code, views) in enumerate(rows)]
    text = "🔥 Eng ko'p ko'rilgan kinolar:\n\n" + "\n".join(lines)
    await update.message.reply_text(text)


async def handle_receipt_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi Premium uchun chek (rasm) yuborsa, adminlarga forward qilinadi"""
    user = update.effective_user
    awaiting_receipt.discard(user.id)

    username_display = user.username or "username yo'q"
    caption = (
        f"💳 Yangi Premium to'lov cheki!\n\n"
        f"👤 Foydalanuvchi: @{username_display}\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"Tasdiqlash uchun: /premium {user.id}"
    )

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.copy_message(
                chat_id=admin_id,
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
            await context.bot.send_message(chat_id=admin_id, text=caption, parse_mode="HTML")
        except Exception as e:
            logging.error(f"Adminga chek yuborishda xato ({admin_id}): {e}")

    await update.message.reply_text(
        "✅ Chekingiz qabul qilindi! Admin tasdiqlashi bilan Premium tarif faollashadi."
    )


async def grant_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/premium <user_id> — faqat admin, foydalanuvchiga Premium beradi"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Sizda ruxsat yo'q ❌")
        return

    if not context.args:
        await update.message.reply_text("Foydalanuvchi ID sini kiriting. Masalan: /premium 123456789")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID raqam bo'lishi kerak!")
        return

    set_premium(target_id, 1)
    await update.message.reply_text(f"✅ {target_id} endi Premium foydalanuvchi!")

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                "🎉 Tabriklaymiz! Sizga Premium tarif faollashtirildi.\n"
                "Endi reklamalarsiz, majburiy obunasiz foydalanishingiz mumkin."
            ),
        )
    except Exception as e:
        logging.error(f"Foydalanuvchiga xabar berishda xato: {e}")


# ==== ODDIY HANDLERLAR ====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)

    if not is_admin(update.effective_user.id) and not is_premium(update.effective_user.id):
        if not await is_subscribed(context, update.effective_user.id):
            await update.message.reply_text(
                "Botdan foydalanish uchun avval kanalimizga qo'shiling, "
                "so'ng '✅ Obuna bo'ldim' tugmasini bosing.",
                reply_markup=subscribe_keyboard(),
            )
            return

    await update.message.reply_text(
        "Salom! 🎬\nKino kodini yuboring yoki pastdagi tugmalardan foydalaning.",
        reply_markup=main_menu_keyboard(),
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
    forwarded = None

    # 0-urinish: agar bu xabar KINOLAR KANALIDAN forward qilingan bo'lsa,
    # faylni qayta yuklamasdan, asl joyini eslab qolamiz (50MB+ fayllar uchun yagona yo'l)
    origin_chat = getattr(replied, "forward_from_chat", None)
    origin_message_id = getattr(replied, "forward_from_message_id", None)

    if origin_chat is None:
        forward_origin = getattr(replied, "forward_origin", None)
        if forward_origin is not None:
            origin_chat = getattr(forward_origin, "chat", None)
            origin_message_id = getattr(forward_origin, "message_id", None)

    if origin_chat is not None and origin_chat.id == CHANNEL_ID and origin_message_id:
        cur.execute(
            "INSERT OR REPLACE INTO movies (code, message_id) VALUES (?, ?)",
            (code, origin_message_id),
        )
        conn.commit()
        await update.message.reply_text(f"✅ Kino {code}-kod bilan saqlandi! (katta fayl usuli)")
        return

    # 1-urinish: copy_message (tez, aksariyat holatda ishlaydi, lekin 50MB dan katta bo'lsa ishlamaydi)
    try:
        forwarded = await context.bot.copy_message(
            chat_id=CHANNEL_ID,
            from_chat_id=update.effective_chat.id,
            message_id=replied.message_id,
        )
    except Exception as e:
        logging.warning(f"copy_message ishlamadi, file_id orqali sinaymiz: {e}")

    # 2-urinish: himoyalangan kontent bo'lsa, file_id orqali qayta yuboramiz
    if forwarded is None:
        try:
            caption = replied.caption or None
            if replied.video:
                forwarded = await context.bot.send_video(
                    chat_id=CHANNEL_ID, video=replied.video.file_id, caption=caption
                )
            elif replied.document:
                forwarded = await context.bot.send_document(
                    chat_id=CHANNEL_ID, document=replied.document.file_id, caption=caption
                )
            elif replied.animation:
                forwarded = await context.bot.send_animation(
                    chat_id=CHANNEL_ID, animation=replied.animation.file_id, caption=caption
                )
            elif replied.photo:
                forwarded = await context.bot.send_photo(
                    chat_id=CHANNEL_ID, photo=replied.photo[-1].file_id, caption=caption
                )
        except Exception as e:
            logging.error(f"/add xatosi (file_id usuli ham ishlamadi): {e}")
            await update.message.reply_text(
                "❌ Kinoni saqlab bo'lmadi. Agar fayl 50MB dan katta bo'lsa: "
                "videoni to'g'ridan-to'g'ri kinolar kanaliga qo'lda yuklang, so'ng o'sha "
                "kanal xabarini botga forward qilib, shunga Reply qilib /add yozing."
            )
            return

    if forwarded is None:
        await update.message.reply_text(
            "❌ Bu xabar turi qo'llab-quvvatlanmaydi. Video, fayl yoki rasm yuboring."
        )
        return

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


async def show_movies_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📚 Kinolar ro'yxati tugmasi — barcha foydalanuvchilarga mavjud kodlarni ko'rsatadi"""
    cur.execute("SELECT code FROM movies ORDER BY code")
    rows = cur.fetchall()
    if rows:
        codes = ", ".join(str(r[0]) for r in rows)
        text = f"🎬 Mavjud kino kodlari:\n\n{codes}\n\nKodni yuboring, kino keladi."
    else:
        text = "Hozircha hech qanday kino qo'shilmagan."
    await update.message.reply_text(text)


async def send_movie(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi raqam yozganda kino yuboriladi, yoki menyu tugmalarini bajaradi"""
    save_user(update.effective_user)

    user_id = update.effective_user.id

    # Agar admin hozir "xabar yuborish" rejimida bo'lsa
    if user_id in awaiting_broadcast and is_admin(user_id):
        await do_broadcast(update, context)
        return

    text = (update.message.text or "").strip()

    if text == MAIN_MENU_LIST:
        await show_movies_list(update, context)
        return

    if text == MAIN_MENU_SEARCH:
        await update.message.reply_text("Kino kodini yuboring, masalan: 1")
        return

    if text == MAIN_MENU_TOP:
        await show_top_movies(update, context)
        return

    if text == MAIN_MENU_PREMIUM:
        await send_premium_info(update, context)
        return

    # Majburiy obuna tekshiruvi (adminlar va Premium foydalanuvchilar uchun shart emas)
    if not is_admin(user_id) and not is_premium(user_id) and not await is_subscribed(context, user_id):
        await update.message.reply_text(
            "Botdan foydalanish uchun avval kanalimizga qo'shiling, "
            "so'ng '✅ Obuna bo'ldim' tugmasini bosing.",
            reply_markup=subscribe_keyboard(),
        )
        return

    if not text.isdigit():
        await update.message.reply_text("Iltimos, faqat kino kodini (raqam) yuboring.")
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
        cur.execute("UPDATE movies SET views = views + 1 WHERE code=?", (code,))
        conn.commit()
    except Exception as e:
        logging.error(e)
        await update.message.reply_text("Xatolik yuz berdi, keyinroq urinib ko'ring.")


async def broadcast_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin broadcast rejimida rasm/video/fayl yuborsa, yoki foydalanuvchi Premium chek yuborsa"""
    user_id = update.effective_user.id

    if user_id in awaiting_broadcast and is_admin(user_id):
        await do_broadcast(update, context)
        return

    if user_id in awaiting_receipt and update.message.photo:
        await handle_receipt_photo(update, context)
        return


# ==== RENDER UCHUN PING SERVER ====

class PingHandler(BaseHTTPRequestHandler):
    """Render'ga 'tirikman' deb javob beruvchi kichik HTTP server"""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot ishlab turibdi")

    def log_message(self, format, *args):
        pass


def run_ping_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()


def main():
    threading.Thread(target=run_ping_server, daemon=True).start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("add", add_movie))
    app.add_handler(CommandHandler("delete", delete_movie))
    app.add_handler(CommandHandler("premium", grant_premium))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    app.add_handler(CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"))
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
