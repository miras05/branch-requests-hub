import os
import imaplib
import email
from email.header import decode_header
import psycopg2
from dotenv import load_dotenv

load_dotenv()

MAIL_HOST = os.getenv("MAIL_HOST")
MAIL_USER = os.getenv("MAIL_USER")
MAIL_PASS = os.getenv("MAIL_PASS")
DATABASE_URL = os.getenv("DATABASE_URL")

# Без фильтра рассылки и уведомления забивают весь дайджест.
SKIP_SENDERS = ("noreply", "no-reply", "newsletter", "notification", "mailer", "donotreply")


def is_service_sender(sender: str) -> bool:
    return any(s in sender.lower() for s in SKIP_SENDERS)


def decode_str(value) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    result = []
    for part, encoding in parts:
        if isinstance(part, bytes):
            result.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def get_text(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def save_email(source_id: str, sender: str, subject: str, body: str):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM messages WHERE source = 'email' AND source_id = %s",
        (source_id,)
    )
    if cur.fetchone():
        cur.close()
        conn.close()
        return False

    text = f"Тема: {subject}\n\n{body[:2000]}"
    cur.execute(
        "INSERT INTO messages (source, source_id, sender, text) VALUES (%s, %s, %s, %s)",
        ("email", source_id, sender, text)
    )
    conn.commit()
    cur.close()
    conn.close()
    return True


def fetch_new_emails(limit: int = 20) -> int:
    imap = imaplib.IMAP4_SSL(MAIL_HOST)
    imap.login(MAIL_USER, MAIL_PASS)
    imap.select("INBOX")

    _, data = imap.search(None, "UNSEEN")
    ids = data[0].split()
    ids = ids[-limit:]

    saved = 0
    for uid in ids:
        _, msg_data = imap.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        source_id = msg.get("Message-ID", uid.decode())
        sender = decode_str(msg.get("From", ""))
        subject = decode_str(msg.get("Subject", "(без темы)"))
        body = get_text(msg)

        if is_service_sender(sender):
            continue

        if save_email(source_id, sender, subject, body):
            print(f"  + [{sender}] {subject}")
            saved += 1

    imap.logout()
    return saved


if __name__ == "__main__":
    print("Проверяю почту...")
    count = fetch_new_emails()
    print(f"Сохранено писем: {count}")
