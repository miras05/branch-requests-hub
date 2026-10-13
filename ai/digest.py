import os
import sys
import psycopg2
from datetime import date
from dotenv import load_dotenv
from groq import Groq

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from integrations.bitrix import create_task

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
MODEL = "llama-3.3-70b-versatile"

# Лимит Groq — 12 000 токенов в минуту. Сколько сообщений и символов уходит в
# модель, подобрано под него: увеличивать только с пересчётом, иначе 413.
PER_SOURCE = 7
MAX_TEXT_CHARS = 120

BALANCED_QUERY = """
    SELECT source, sender, text, created_at FROM (
        SELECT source, sender, text, created_at,
               ROW_NUMBER() OVER (PARTITION BY source ORDER BY created_at DESC) AS rn
        FROM messages
        WHERE (source IN ('telegram', 'email') AND DATE(created_at) = %s)
           OR source = 'bitrix'
    ) t WHERE rn <= %s
    ORDER BY source, created_at DESC
"""

_client = None


def _groq() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


def fetch_balanced(conn, day: date, per_source: int = PER_SOURCE) -> list:
    """По N свежих сообщений от каждого источника.

    Простой ORDER BY ... LIMIT давал перекос: два десятка рассылок с почты
    вытесняли из дайджеста задачи и лиды Bitrix24. Telegram и почта — только
    за день, Bitrix — без фильтра по дате: задача, открытая неделю назад,
    всё ещё может требовать внимания.
    """
    cur = conn.cursor()
    cur.execute(BALANCED_QUERY, (day, per_source))
    rows = cur.fetchall()
    cur.close()
    return [{"source": r[0], "sender": r[1], "text": r[2], "time": r[3].strftime("%H:%M")} for r in rows]


def get_todays_messages() -> list:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        return fetch_balanced(conn, date.today())
    finally:
        conn.close()


def build_prompt(messages: list[dict]) -> str:
    source_label = {"telegram": "Telegram", "email": "Почта", "bitrix": "Bitrix24"}
    lines = "\n".join(
        f"[{source_label.get(m['source'], m['source'])}] {m['sender'][:40]}: {m['text'][:MAX_TEXT_CHARS]}"
        for m in messages
    )
    return f"""Ты — ИИ-ассистент для руководителя компании с 7 филиалами.
Проанализируй сообщения из Telegram-групп филиалов, почты и Bitrix24 за сегодня и составь краткий дайджест.

Формат дайджеста:
🔴 КРИТИЧНО — требует немедленного внимания
🟡 ВАЖНО — требует решения сегодня
🔵 ИНФОРМАЦИЯ — для общего сведения
⚪ ФОН — не требует действий

Для каждого пункта укажи: суть, кто написал, что нужно сделать (если нужно).
Пиши кратко, по-русски, деловым языком.

СООБЩЕНИЯ ЗА СЕГОДНЯ:
{lines}

ДАЙДЖЕСТ:"""


def generate_digest(auto_create_tasks: bool = False) -> str:
    messages = get_todays_messages()

    if not messages:
        return "📭 За сегодня сообщений не поступало."

    prompt = build_prompt(messages)

    response = _groq().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    digest = response.choices[0].message.content

    if auto_create_tasks:
        _auto_create_critical_tasks(digest)

    return digest


def extract_critical(digest: str) -> list:
    """Строки из раздела 🔴 КРИТИЧНО — до следующего раздела."""
    critical, in_critical = [], False
    for line in digest.split("\n"):
        if "🔴" in line:
            in_critical = True
            continue
        if any(emoji in line for emoji in ("🟡", "🔵", "⚪")):
            in_critical = False
        if in_critical and line.strip():
            critical.append(line.strip())
    return critical


def _auto_create_critical_tasks(digest: str):
    critical_lines = extract_critical(digest)
    if critical_lines:
        title = f"[АВТО] {critical_lines[0][:80]}"
        task_id = create_task(title=title, description="\n".join(critical_lines))
        if task_id:
            print(f"Авто-задача создана в Bitrix24: {task_id}")


if __name__ == "__main__":
    print("Генерирую дайджест...\n")
    digest = generate_digest()
    print(digest)
