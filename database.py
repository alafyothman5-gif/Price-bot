import sqlite3
import json
import time
from pathlib import Path
from typing import List

DB_FILE = Path("pricebot.db")

def get_db_connection() -> sqlite3.Connection:
    """اتصال آمن وسريع بقاعدة البيانات مع دعم القراءة والكتابة المتزامنة (WAL)"""
    conn = sqlite3.connect(str(DB_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, aliases TEXT DEFAULT '', active_ingredient TEXT DEFAULT '',
                brand TEXT DEFAULT '', company TEXT DEFAULT '', form TEXT DEFAULT '',
                strength TEXT DEFAULT '', pack TEXT DEFAULT '', price TEXT DEFAULT '',
                available TEXT DEFAULT 'متوفر', notes TEXT DEFAULT '', image TEXT DEFAULT ''
            )
        """)
        # جدول حفظ حالة الزبون لمنع ضياعها عند إعادة تشغيل السيرفر
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_state (
                phone TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.commit()

def load_products() -> List[dict]:
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM products").fetchall()
        return [dict(row) for row in rows]

def get_user_state(phone: str) -> dict:
    with get_db_connection() as conn:
        row = conn.execute("SELECT state_json FROM conversation_state WHERE phone=?", (phone,)).fetchone()
        if row:
            try:
                return json.loads(row["state_json"])
            except:
                return {}
        return {}

def update_user_state(phone: str, state_data: dict):
    now = int(time.time())
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO conversation_state(phone, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(phone) DO UPDATE SET 
                state_json=excluded.state_json, 
                updated_at=excluded.updated_at
        """, (phone, json.dumps(state_data, ensure_ascii=False), now))
        conn.commit()

init_db()
