import os
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

BITRIX_URL = os.getenv("BITRIX_WEBHOOK_URL")
DATABASE_URL = os.getenv("DATABASE_URL")


def api(method: str, params: dict = None) -> dict:
    response = requests.post(f"{BITRIX_URL}{method}", json=params or {}, timeout=10)
    response.raise_for_status()
    return response.json()


def already_saved(source_id: str) -> bool:
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM messages WHERE source = 'bitrix' AND source_id = %s",
        (source_id,)
    )
    exists = cur.fetchone() is not None
    cur.close()
    conn.close()
    return exists


def save_message(source_id: str, sender: str, text: str):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (source, source_id, sender, text) VALUES (%s, %s, %s, %s)",
        ("bitrix", source_id, sender, text)
    )
    conn.commit()
    cur.close()
    conn.close()


def fetch_tasks(limit: int = 20) -> int:
    result = api("tasks.task.list", {
        "order": {"CREATED_DATE": "desc"},
        "select": ["ID", "TITLE", "DESCRIPTION", "CREATED_BY", "RESPONSIBLE_ID", "DEADLINE", "STATUS"],
        "params": {"START": 0},
        "limit": limit
    })

    tasks = result.get("result", {}).get("tasks", [])
    saved = 0

    for task in tasks:
        source_id = f"task_{task['id']}"
        if already_saved(source_id):
            continue

        status_map = {"1": "ждёт", "2": "в работе", "3": "отложена", "4": "завершена", "5": "одобрена"}
        status = status_map.get(str(task.get("status", "")), "неизвестно")
        deadline = task.get("deadline", "")
        deadline_str = f", дедлайн: {deadline[:10]}" if deadline else ""

        text = f"Задача: {task['title']}. Статус: {status}{deadline_str}."
        if task.get("description"):
            text += f" Описание: {task['description'][:200]}"

        sender = f"Bitrix24 (исполнитель ID:{task.get('responsibleId', '?')})"
        save_message(source_id, sender, text)
        print(f"  + Задача: {task['title']}")
        saved += 1

    return saved


def fetch_leads(limit: int = 20) -> int:
    result = api("crm.lead.list", {
        "order": {"DATE_CREATE": "DESC"},
        "select": ["ID", "TITLE", "NAME", "PHONE", "STATUS_ID", "COMMENTS", "DATE_CREATE"],
        "start": 0
    })

    leads = result.get("result", [])
    saved = 0

    for lead in leads:
        source_id = f"lead_{lead['ID']}"
        if already_saved(source_id):
            continue

        name = lead.get("NAME") or lead.get("TITLE") or "Без имени"
        status = lead.get("STATUS_ID", "")
        comment = lead.get("COMMENTS", "")[:200]
        text = f"Лид: {lead.get('TITLE', name)}. Статус: {status}."
        if comment:
            text += f" Комментарий: {comment}"

        save_message(source_id, "CRM (лид)", text)
        print(f"  + Лид: {lead.get('TITLE', name)}")
        saved += 1

    return saved


def create_task(title: str, description: str = "", deadline: str = "") -> str:
    fields = {
        "TITLE": title,
        "DESCRIPTION": description,
        "RESPONSIBLE_ID": "1",
        "PRIORITY": "2",
    }
    if deadline:
        fields["DEADLINE"] = deadline

    result = api("tasks.task.add", {"fields": fields})
    task_id = result.get("result", {}).get("task", {}).get("id", "")

    if task_id:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO tasks (description, bitrix_task_id) VALUES (%s, %s)",
            (title, str(task_id))
        )
        conn.commit()
        cur.close()
        conn.close()

    return str(task_id)


def fetch_all() -> int:
    total = 0
    total += fetch_tasks()
    total += fetch_leads()
    return total


if __name__ == "__main__":
    print("Загружаю данные из Bitrix24...")
    count = fetch_all()
    print(f"Сохранено записей: {count}")
