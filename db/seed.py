"""Тестовые клиенты для проверки команды /client.

База живёт в Docker-volume и между устройствами не переносится — после
git clone она пустая. Этот скрипт наполняет её данными для демонстрации.

Запускать после db/init.py. Повторный запуск безопасен: клиенты
с тем же именем не дублируются.
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")

CLIENTS = [
    (
        "Марат Сейткали",
        "+77000000001",
        "marat@example.com",
        "ТОО Астана Строй",
        "Хочет автоматизацию 1С на 7 складах. Бюджет обсуждается. Контакт через Bitrix24.",
    ),
    (
        "Айгерим Нурланова",
        "+77000000002",
        "aigerim@example.com",
        "ТОО ТехКЗ",
        "Интересуется интеграцией 1С с интернет-магазином. Перезвонить в пятницу.",
    ),
    (
        "Серик Абенов",
        "+77000000003",
        "serik@example.com",
        "Холдинг 7 Филиалов",
        "Клиент на мониторинг 7 групп. Текущий проект Order 5.",
    ),
]


def seed():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    added = 0
    for name, phone, email, company, notes in CLIENTS:
        cur.execute("SELECT id FROM clients WHERE name = %s", (name,))
        if cur.fetchone():
            print(f"  = {name} — уже есть, пропускаю")
            continue

        cur.execute(
            "INSERT INTO clients (name, phone, email, company, notes) "
            "VALUES (%s, %s, %s, %s, %s)",
            (name, phone, email, company, notes),
        )
        print(f"  + {name} ({company})")
        added += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"\n✓ Добавлено клиентов: {added}")
    print("Проверка: напиши боту /client Марат")


if __name__ == "__main__":
    print("Заполняю тестовых клиентов...")
    seed()
