import logging
import sqlite3
import os
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

BOT_TOKEN = "8811167886:AAHN2AigN919e-y63G8QQHKL_UiOeL1F3Mc"
GURUH_ID = -1004321288260
ADMIN_ID = 8252424738

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kinolar.db")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS kinolar (
            id INTEGER PRIMARY KEY,
            raqam INTEGER UNIQUE,
            nomi TEXT,
            file_id TEXT,
            file_type TEXT
        )
    """)
    conn.commit()
    conn.close()


def kino_qosh(raqam, nomi, file_id, file_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO kinolar (raqam, nomi, file_id, file_type) VALUES (?,?,?,?)",
        (raqam, nomi, file_id, file_type)
    )
    conn.commit()
    conn.close()


def kino_ol(raqam):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT raqam, nomi, file_id, file_type FROM kinolar WHERE raqam=?", (raqam,))
    row = c.fetchone()
    conn.close()
    return row


def jami_kinolar():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM kinolar")
    jami = c.fetchone()[0]
    conn.close()
    return jami


def barcha_kinolar():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT raqam, nomi FROM kinolar ORDER BY raqam")
    rows = c.fetchall()
    conn.close()
    return rows


async def guruh_xabar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    # Guruh ID tekshirish
    if msg.chat_id != GURUH_ID:
        return

    caption = msg.caption or ""
    parts = caption.strip().split()

    if not parts or not parts[0].isdigit():
        return

    raqam = int(parts[0])
    nomi = " ".join(parts[1:]) if len(parts) > 1 else f"Kino {raqam}"

    if msg.video:
        file_id = msg.video.file_id
        file_type = "video"
    elif msg.document:
        file_id = msg.document.file_id
        file_type = "document"
    else:
        return

    kino_qosh(raqam, nomi, file_id, file_type)
    logger.info(f"Kino saqlandi: {raqam} - {nomi}")

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"Kino saqlandi! Raqam: {raqam} | Nom: {nomi}"
        )
    except Exception as e:
        logger.error(f"Admin xabar xatosi: {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jami = jami_kinolar()
    await update.message.reply_text(
        f"Kino botga xush kelibsiz!\n\n"
        f"Bazada: {jami} ta kino\n\n"
        f"Kino raqamini yozing, yuborib beraman.\n"
        f"Masalan: 1, 25, 100"
    )


async def kino_yuborish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    matn = update.message.text.strip()

    if not matn.isdigit():
        await update.message.reply_text("Faqat raqam yozing. Masalan: 1")
        return

    raqam = int(matn)
    kino = kino_ol(raqam)

    if not kino:
        jami = jami_kinolar()
        await update.message.reply_text(
            f"{raqam}-raqamda kino yoq.\n"
            f"Bazada jami {jami} ta kino bor."
        )
        return

    raqam, nomi, file_id, file_type = kino

    try:
        if file_type == "video":
            await update.message.reply_video(
                video=file_id,
                caption=f"{raqam}. {nomi}"
            )
        else:
            await update.message.reply_document(
                document=file_id,
                caption=f"{raqam}. {nomi}"
            )
    except Exception as e:
        logger.error(f"Kino yuborishda xato: {e}")
        await update.message.reply_text("Kino yuborishda xato. Keyinroq urinib koring.")


async def royxat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    kinolar = barcha_kinolar()
    if not kinolar:
        await update.message.reply_text("Bazada kino yoq.")
        return
    matn = f"Jami {len(kinolar)} ta kino:\n\n"
    for raqam, nomi in kinolar[:50]:
        matn += f"{raqam}. {nomi}\n"
    if len(kinolar) > 50:
        matn += f"\n...va yana {len(kinolar)-50} ta"
    await update.message.reply_text(matn)


async def kino_ochirish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        raqam = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Yozing: /ochir 5")
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM kinolar WHERE raqam=?", (raqam,))
    ta = c.rowcount
    conn.commit()
    conn.close()
    if ta:
        await update.message.reply_text(f"{raqam}-kino ochirildi.")
    else:
        await update.message.reply_text(f"{raqam}-raqamda kino yoq.")


async def statistika(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    jami = jami_kinolar()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT MAX(raqam) FROM kinolar")
    max_raqam = c.fetchone()[0] or 0
    conn.close()
    await update.message.reply_text(
        f"Statistika:\nJami: {jami} ta\nEng yuqori raqam: {max_raqam}"
    )


def main():
    init_db()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("royxat", royxat))
    application.add_handler(CommandHandler("ochir", kino_ochirish))
    application.add_handler(CommandHandler("stat", statistika))

    # Guruhdan video/hujjat qabul qilish
    application.add_handler(MessageHandler(
        filters.VIDEO | filters.Document.ALL,
        guruh_xabar
    ))

    # Foydalanuvchidan raqam qabul qilish
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        kino_yuborish
    ))

    logger.info("Kino bot ishga tushdi!")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
