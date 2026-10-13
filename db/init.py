import os

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin@localhost:5432/ai_system")

def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    # Включаем расширение для векторного поиска
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Все сообщения из всех источников — в одну таблицу
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            source VARCHAR(20) NOT NULL,       -- 'telegram', 'email', 'bitrix'
            source_id VARCHAR(100),            -- ID сообщения в оригинальной системе
            chat_id BIGINT,                    -- ID Telegram чата (если telegram)
            sender VARCHAR(200),               -- кто отправил
            text TEXT NOT NULL,                -- текст сообщения
            priority VARCHAR(20),              -- критично / важно / информация / фон
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)
    # Защита от дублей: одно сообщение источника сохраняется один раз
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_source
            ON messages (source, source_id) WHERE source_id IS NOT NULL;
    """)

    # Карточки клиентов
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            phone VARCHAR(50),
            email VARCHAR(200),
            company VARCHAR(200),
            notes TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    # Задачи, созданные автоматически
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY,
            message_id INT REFERENCES messages(id),
            assignee VARCHAR(200),             -- кому поставлена
            description TEXT,                  -- текст задачи
            deadline DATE,
            bitrix_task_id VARCHAR(100),       -- ID задачи в Bitrix24
            created_at TIMESTAMP DEFAULT NOW()
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("✓ Таблицы созданы успешно")

if __name__ == "__main__":
    init_db()
