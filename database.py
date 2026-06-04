import sqlite3
import json
import time
import shutil
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "pricebot.db"
BACKUPS_DIR = BASE_DIR / "backups"

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        cursor = conn.execute("PRAGMA table_info(products)")
        existing_columns = [col["name"] for col in cursor.fetchall()]
        required_columns = {
            "aliases": "TEXT DEFAULT ''", "active_ingredient": "TEXT DEFAULT ''", "brand": "TEXT DEFAULT ''",
            "company": "TEXT DEFAULT ''", "form": "TEXT DEFAULT ''", "strength": "TEXT DEFAULT ''",
            "pack": "TEXT DEFAULT ''", "price": "TEXT DEFAULT ''", "available": "TEXT DEFAULT 'متوفر'",
            "notes": "TEXT DEFAULT ''", "image": "TEXT DEFAULT ''", "normalized_name": "TEXT DEFAULT ''"
        }
        for col, dtype in required_columns.items():
            if col not in existing_columns:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {dtype}")

        # --- الـ Migration الآمن لجدول الطلبات ---
        conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT)")
        cursor_orders = conn.execute("PRAGMA table_info(orders)")
        existing_order_cols = [col["name"] for col in cursor_orders.fetchall()]
        
        if "product_name" not in existing_order_cols:
            conn.execute("ALTER TABLE orders ADD COLUMN product_name TEXT DEFAULT ''")
            if "product" in existing_order_cols:
                try: conn.execute("UPDATE orders SET product_name = product WHERE product_name IS NULL OR product_name = ''")
                except Exception as e: print(f"Orders Migration Error (product_name): {e}")

        if "price" not in existing_order_cols:
            conn.execute("ALTER TABLE orders ADD COLUMN price TEXT DEFAULT ''")

        if "status" not in existing_order_cols:
            conn.execute("ALTER TABLE orders ADD COLUMN status TEXT DEFAULT 'pending'")

        if "created_at" not in existing_order_cols:
            # إضافة العمود كـ TEXT فارغ أولاً لتجنب OperationalError في SQLite
            conn.execute("ALTER TABLE orders ADD COLUMN created_at TEXT DEFAULT ''")
            # تحديث الأسطر القديمة بالوقت الحالي
            try: conn.execute("UPDATE orders SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at = ''")
            except Exception as e: print(f"Orders Migration Error (created_at): {e}")

        conn.execute("CREATE TABLE IF NOT EXISTS processed_messages (message_id TEXT PRIMARY KEY, status TEXT DEFAULT 'processing', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS conversation_state (phone TEXT PRIMARY KEY, state_json TEXT NOT NULL, updated_at INTEGER NOT NULL)")
        conn.commit()

def start_processing_message(message_id: str) -> bool:
    if not message_id: return False
    with get_db_connection() as conn:
        row = conn.execute("SELECT status, updated_at FROM processed_messages WHERE message_id=?", (message_id,)).fetchone()
        if row:
            status, updated_at_str = row["status"], row["updated_at"]
            try:
                updated_at = datetime.strptime(updated_at_str, "%Y-%m-%d %H:%M:%S")
                diff_minutes = (datetime.utcnow() - updated_at).total_seconds() / 60.0
            except: diff_minutes = 10
            
            if status == "done": return False
            if status == "failed" or (status == "processing" and diff_minutes > 5):
                conn.execute("UPDATE processed_messages SET status='processing', updated_at=CURRENT_TIMESTAMP WHERE message_id=?", (message_id,))
                conn.commit()
                return True
            return False
            
        conn.execute("INSERT INTO processed_messages (message_id, status, updated_at) VALUES (?, 'processing', CURRENT_TIMESTAMP)", (message_id,))
        conn.commit()
        return True

def mark_message_done(message_id: str, final_status: str = 'done'):
    if not message_id: return
    with get_db_connection() as conn:
        conn.execute("UPDATE processed_messages SET status=?, updated_at=CURRENT_TIMESTAMP WHERE message_id=?", (final_status, message_id))
        conn.commit()

def add_order(phone: str, product_name: str, price: str = ""):
    with get_db_connection() as conn:
        # إدخال created_at صراحة لتجنب الاعتماد على الـ default
        conn.execute("INSERT INTO orders (phone, product_name, price, status, created_at) VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP)", (phone, product_name, price))
        conn.commit()

def get_all_orders() -> List[dict]:
    with get_db_connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()]

def update_order_status(order_id: int, status: str):
    with get_db_connection() as conn:
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        conn.commit()

def get_user_state(phone: str) -> dict:
    with get_db_connection() as conn:
        row = conn.execute("SELECT state_json FROM conversation_state WHERE phone=?", (phone,)).fetchone()
        if row:
            try: return json.loads(row["state_json"])
            except: return {}
        return {}

def update_user_state(phone: str, state_data: dict):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO conversation_state(phone, state_json, updated_at) VALUES (?, ?, ?) ON CONFLICT(phone) DO UPDATE SET state_json=excluded.state_json, updated_at=excluded.updated_at", (phone, json.dumps(state_data, ensure_ascii=False), int(time.time())))
        conn.commit()

def clear_user_state(phone: str):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM conversation_state WHERE phone=?", (phone,))
        conn.commit()

def load_products() -> List[dict]:
    try:
        with get_db_connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM products").fetchall()]
    except: return []

def backup_database():
    if not DB_FILE.exists(): return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    try: shutil.copy(DB_FILE, BACKUPS_DIR / f"pricebot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    except: pass

init_db()
