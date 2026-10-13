"""Интеграционный тест на настоящем PostgreSQL: балансировка источников в дайджесте.

Запускается, если задан DATABASE_URL (в CI поднимается сервис postgres).
"""

import os
from datetime import date, datetime, timedelta

import pytest

psycopg2 = pytest.importorskip("psycopg2")

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL не задан")


@pytest.fixture
def conn(monkeypatch):
    from db import init

    monkeypatch.setattr(init, "DATABASE_URL", DATABASE_URL)
    init.init_db()
    connection = psycopg2.connect(DATABASE_URL)
    with connection.cursor() as cur:
        cur.execute("TRUNCATE tasks, messages RESTART IDENTITY CASCADE")
    connection.commit()
    yield connection
    connection.close()


def _insert(conn, source, text, created_at, source_id=None):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO messages (source, source_id, sender, text, created_at) VALUES (%s, %s, %s, %s, %s)",
            (source, source_id, "тест", text, created_at),
        )
    conn.commit()


def test_noisy_source_does_not_crowd_out_others(conn):
    from ai.digest import fetch_balanced

    now = datetime.now()
    for i in range(20):
        _insert(conn, "email", f"рассылка {i}", now - timedelta(minutes=i))
    _insert(conn, "telegram", "в филиале сломался терминал", now)
    _insert(conn, "bitrix", "Задача: отгрузка", now - timedelta(days=7), source_id="task_1")
    _insert(conn, "telegram", "вчерашнее", now - timedelta(days=1))

    rows = fetch_balanced(conn, date.today(), per_source=7)
    by_source = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row["text"])

    assert len(by_source["email"]) == 7, "почта ограничена N сообщениями"
    assert by_source["telegram"] == ["в филиале сломался терминал"], "только сегодняшний Telegram"
    assert by_source["bitrix"] == ["Задача: отгрузка"], "Bitrix — без фильтра по дате"


def test_duplicate_source_id_is_rejected(conn):
    _insert(conn, "bitrix", "Задача", datetime.now(), source_id="task_42")
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _insert(conn, "bitrix", "Задача", datetime.now(), source_id="task_42")
