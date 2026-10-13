import os
import datetime
import psycopg2
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai.digest import generate_digest
from integrations.mail import fetch_new_emails
from integrations.bitrix import fetch_all as fetch_bitrix, create_task

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
ALLOWED_USERS = set(
    uid.strip() for uid in os.getenv("ALLOWED_USERS", "").split(",") if uid.strip()
)


def is_allowed(update: Update) -> bool:
    return str(update.effective_user.id) in ALLOWED_USERS


def save_message(chat_id: int, sender: str, text: str):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (source, chat_id, sender, text) VALUES (%s, %s, %s, %s)",
        ("telegram", chat_id, sender, text)
    )
    conn.commit()
    cur.close()
    conn.close()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    chat_id = msg.chat.id
    sender = msg.from_user.full_name if msg.from_user else "Неизвестно"
    text = msg.text
    save_message(chat_id, sender, text)
    print(f"[{chat_id}] {sender}: {text}")


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Твой Chat ID: `{chat_id}`\n\n"
        f"Добавь его в .env файл:\n`ADMIN_CHAT_ID={chat_id}`",
        parse_mode="Markdown"
    )


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("⛔ У вас нет доступа.")
        return
    await update.message.reply_text("Генерирую дайджест, подожди...")
    digest = generate_digest()
    await update.message.reply_text(digest)


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("⛔ У вас нет доступа.")
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Использование: /search <запрос>\nПример: /search Астана Строй")
        return

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT source, sender, text, created_at
        FROM messages
        WHERE text ILIKE %s OR sender ILIKE %s
        ORDER BY created_at DESC
        LIMIT 10
    """, (f"%{query}%", f"%{query}%"))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await update.message.reply_text(f"Ничего не найдено по запросу: «{query}»")
        return

    source_label = {"telegram": "Telegram", "email": "Почта", "bitrix": "Bitrix24"}
    lines = [f"🔍 Результаты по «{query}» ({len(rows)}):\n"]
    for source, sender, text, created_at in rows:
        label = source_label.get(source, source)
        date_str = created_at.strftime("%d.%m %H:%M")
        lines.append(
            f"[{label} · {date_str}]\n"
            f"От: {sender[:50]}\n"
            f"{text[:200]}\n"
            f"{'─' * 20}"
        )

    await update.message.reply_text("\n".join(lines))


async def cmd_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("⛔ У вас нет доступа.")
        return
    query = " ".join(context.args).strip()
    if not query:
        await update.message.reply_text("Использование: /client <имя или компания или телефон>\nПример: /client Марат")
        return

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("""
        SELECT name, phone, email, company, notes, created_at
        FROM clients
        WHERE name ILIKE %s OR company ILIKE %s OR phone ILIKE %s
        ORDER BY created_at DESC
        LIMIT 5
    """, (f"%{query}%", f"%{query}%", f"%{query}%"))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await update.message.reply_text(f"Клиент не найден: «{query}»")
        return

    lines = []
    for name, phone, email, company, notes, _created_at in rows:
        lines.append(
            f"👤 *{name}*\n"
            f"🏢 {company or '—'}\n"
            f"📞 {phone or '—'}\n"
            f"✉️ {email or '—'}\n"
            f"📝 {notes or '—'}"
        )

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        await update.message.reply_text("⛔ У вас нет доступа.")
        return
    description = " ".join(context.args).strip()
    if not description:
        await update.message.reply_text("Использование: /task <описание>\nПример: /task Позвонить клиенту Марату до пятницы")
        return

    await update.message.reply_text("Создаю задачу в Bitrix24...")
    task_id = create_task(title=description)

    if task_id:
        # Сразу сохраняем в messages чтобы попало в ближайший дайджест
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (source, source_id, sender, text) VALUES (%s, %s, %s, %s)",
            ("bitrix", f"task_{task_id}", "Задача (создана вручную)", f"Задача: {description}. Статус: ждёт.")
        )
        conn.commit()
        cur.close()
        conn.close()
        await update.message.reply_text(f"✅ Задача создана в Bitrix24\nID: {task_id}\n\n📋 {description}")
    else:
        await update.message.reply_text("❌ Не удалось создать задачу. Проверь подключение к Bitrix24.")


async def send_daily_digest(context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_CHAT_ID:
        print("ADMIN_CHAT_ID не задан — дайджест не отправлен")
        return
    print("Отправляю ежедневный дайджест...")
    digest = generate_digest(auto_create_tasks=True)
    await context.bot.send_message(
        chat_id=int(ADMIN_CHAT_ID),
        text=f"📊 *Ежедневный дайджест*\n\n{digest}",
        parse_mode="Markdown"
    )


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("digest", cmd_digest))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("client", cmd_client))
    app.add_handler(CommandHandler("task", cmd_task))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    almaty = datetime.timezone(datetime.timedelta(hours=5))
    app.job_queue.run_daily(
        send_daily_digest,
        time=datetime.time(hour=9, minute=0, tzinfo=almaty),
    )

    async def poll_email(context: ContextTypes.DEFAULT_TYPE):
        count = fetch_new_emails()
        if count:
            print(f"Почта: сохранено {count} новых писем")

    app.job_queue.run_repeating(poll_email, interval=300, first=10)

    async def poll_bitrix(context: ContextTypes.DEFAULT_TYPE):
        count = fetch_bitrix()
        if count:
            print(f"Bitrix24: сохранено {count} новых записей")

    app.job_queue.run_repeating(poll_bitrix, interval=600, first=15)

    print("Бот запущен. Команды: /myid, /digest, /search")
    app.run_polling()


if __name__ == "__main__":
    main()
