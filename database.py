import sqlite3
import json
import time
import shutil
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
DB_FILE = Path(os.getenv("PRICEBOT_DB_FILE", str(BASE_DIR / "pricebot.db")))
if not DB_FILE.is_absolute():
    DB_FILE = BASE_DIR / DB_FILE
BACKUPS_DIR = BASE_DIR / "backups"


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
    except Exception:
        pass
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _cols(conn: sqlite3.Connection, table: str) -> List[str]:
    if not _table_exists(conn, table):
        return []
    return [r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _add_col(conn: sqlite3.Connection, table: str, col: str, dtype: str):
    cols = _cols(conn, table)
    if col not in cols:
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN {col} {dtype}')


def init_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection() as conn:
        # Products table + safe migrations for old databases
        conn.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        product_required = {
            "aliases": "TEXT DEFAULT ''", "active_ingredient": "TEXT DEFAULT ''", "brand": "TEXT DEFAULT ''",
            "company": "TEXT DEFAULT ''", "form": "TEXT DEFAULT ''", "strength": "TEXT DEFAULT ''",
            "pack": "TEXT DEFAULT ''", "price": "TEXT DEFAULT ''", "available": "TEXT DEFAULT 'متوفر'",
            "notes": "TEXT DEFAULT ''", "image": "TEXT DEFAULT ''", "normalized_name": "TEXT DEFAULT ''"
        }
        for col, dtype in product_required.items():
            _add_col(conn, "products", col, dtype)
        try:
            # Fill normalized_name for old rows
            rows = conn.execute("SELECT id, name, normalized_name FROM products").fetchall()
            for row in rows:
                if not row["normalized_name"]:
                    # local tiny normalization, avoids importing matcher at DB import time
                    n = str(row["name"] or "").strip().lower()
                    conn.execute("UPDATE products SET normalized_name=? WHERE id=?", (n, row["id"]))
        except Exception:
            pass

        # Orders: compatible with old schemas (product/time columns) and new schema
        conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT DEFAULT '')")
        order_required = {
            "product_name": "TEXT DEFAULT ''",
            "price": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'pending'",
            "created_at": "TEXT DEFAULT ''"
        }
        for col, dtype in order_required.items():
            _add_col(conn, "orders", col, dtype)
        order_cols = _cols(conn, "orders")
        if "product" in order_cols:
            try:
                conn.execute("UPDATE orders SET product_name = product WHERE (product_name IS NULL OR product_name='') AND product IS NOT NULL")
            except Exception as e:
                print(f"Orders migration product_name fallback skipped: {e}")
        if "time" in order_cols:
            try:
                conn.execute("UPDATE orders SET created_at = time WHERE (created_at IS NULL OR created_at='') AND time IS NOT NULL")
            except Exception as e:
                print(f"Orders migration created_at time fallback skipped: {e}")
        try:
            conn.execute("UPDATE orders SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at='' ")
        except Exception:
            pass

        # Message dedupe table: support old/new columns
        conn.execute("CREATE TABLE IF NOT EXISTS processed_messages (message_id TEXT PRIMARY KEY)")
        for col, dtype in {
            "phone": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'processing'",
            "created_at": "TEXT DEFAULT ''",
            "updated_at": "TEXT DEFAULT ''"
        }.items():
            _add_col(conn, "processed_messages", col, dtype)
        try:
            conn.execute("UPDATE processed_messages SET updated_at=CURRENT_TIMESTAMP WHERE updated_at IS NULL OR updated_at='' ")
            conn.execute("UPDATE processed_messages SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at='' ")
        except Exception:
            pass

        # Conversation/user state table: migrate old namespace/user_key/value_json schema safely
        conn.execute("CREATE TABLE IF NOT EXISTS conversation_state (phone TEXT DEFAULT '')")
        for col, dtype in {
            "state_json": "TEXT DEFAULT '{}'",
            "value_json": "TEXT DEFAULT '{}'",
            "updated_at": "TEXT DEFAULT ''",
            "user_key": "TEXT DEFAULT ''",
            "namespace": "TEXT DEFAULT ''"
        }.items():
            _add_col(conn, "conversation_state", col, dtype)
        try:
            conn.execute("UPDATE conversation_state SET state_json=value_json WHERE (state_json IS NULL OR state_json='' OR state_json='{}') AND value_json IS NOT NULL AND value_json!='' AND value_json!='{}'")
            conn.execute("UPDATE conversation_state SET phone=user_key WHERE (phone IS NULL OR phone='') AND user_key IS NOT NULL AND user_key!=''")
        except Exception:
            pass

        # Optional legacy tables used by older versions; add columns so new code/logging never crashes
        for table in ["memory_entries", "product_inquiries", "conversation_states", "user_state", "user_memory", "memory"]:
            if _table_exists(conn, table):
                low = table.lower()
                for col, dtype in {
                    "phone": "TEXT DEFAULT ''", "state_json": "TEXT DEFAULT '{}'", "value_json": "TEXT DEFAULT '{}'",
                    "message_id": "TEXT DEFAULT ''", "status": "TEXT DEFAULT ''", "created_at": "TEXT DEFAULT ''", "updated_at": "TEXT DEFAULT ''",
                    "raw_query": "TEXT DEFAULT ''", "source": "TEXT DEFAULT ''"
                }.items():
                    try:
                        _add_col(conn, table, col, dtype)
                    except Exception:
                        pass

        conn.commit()


def start_processing_message(message_id: str, phone: str = "") -> bool:
    if not message_id:
        return False
    with get_db_connection() as conn:
        row = conn.execute("SELECT status, updated_at FROM processed_messages WHERE message_id=?", (message_id,)).fetchone()
        if row:
            status = row["status"] or ""
            updated_at_str = row["updated_at"] or ""
            try:
                updated_at = datetime.strptime(updated_at_str, "%Y-%m-%d %H:%M:%S")
                diff_minutes = (datetime.utcnow() - updated_at).total_seconds() / 60.0
            except Exception:
                diff_minutes = 10
            if status == "done":
                return False
            if status in ("failed", "") or (status == "processing" and diff_minutes > 5):
                conn.execute("UPDATE processed_messages SET phone=?, status='processing', updated_at=CURRENT_TIMESTAMP WHERE message_id=?", (phone or "", message_id))
                conn.commit()
                return True
            return False
        conn.execute("INSERT INTO processed_messages (message_id, phone, status, created_at, updated_at) VALUES (?, ?, 'processing', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)", (message_id, phone or ""))
        conn.commit()
        return True


def mark_message_done(message_id: str, final_status: str = 'done'):
    if not message_id:
        return
    with get_db_connection() as conn:
        conn.execute("UPDATE processed_messages SET status=?, updated_at=CURRENT_TIMESTAMP WHERE message_id=?", (final_status, message_id))
        conn.commit()


def add_order(phone: str, product_name: str, price: str = ""):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO orders (phone, product_name, price, status, created_at) VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP)", (phone or "", product_name or "", price or ""))
        conn.commit()


def get_all_orders() -> List[dict]:
    with get_db_connection() as conn:
        try:
            return [dict(row) for row in conn.execute("SELECT * FROM orders ORDER BY datetime(created_at) DESC, id DESC").fetchall()]
        except Exception:
            return [dict(row) for row in conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()]


def update_order_status(order_id: int, status: str):
    with get_db_connection() as conn:
        conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
        conn.commit()


def get_user_state(phone: str) -> dict:
    if not phone:
        return {}
    with get_db_connection() as conn:
        row = conn.execute("SELECT state_json FROM conversation_state WHERE phone=?", (phone,)).fetchone()
        if row:
            try:
                return json.loads(row["state_json"] or "{}")
            except Exception:
                return {}
        return {}


def update_user_state(phone: str, state_data: dict):
    if not phone:
        return
    data = json.dumps(state_data or {}, ensure_ascii=False)
    now = str(int(time.time()))
    with get_db_connection() as conn:
        # works even if old table has no unique constraint on phone
        row = conn.execute("SELECT rowid FROM conversation_state WHERE phone=? LIMIT 1", (phone,)).fetchone()
        if row:
            conn.execute("UPDATE conversation_state SET state_json=?, value_json=?, updated_at=? WHERE rowid=?", (data, data, now, row["rowid"]))
        else:
            conn.execute("INSERT INTO conversation_state(phone, state_json, value_json, updated_at) VALUES (?, ?, ?, ?)", (phone, data, data, now))
        conn.commit()


def clear_user_state(phone: str):
    if not phone:
        return
    with get_db_connection() as conn:
        conn.execute("DELETE FROM conversation_state WHERE phone=?", (phone,))
        conn.commit()


def load_products() -> List[dict]:
    try:
        with get_db_connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM products").fetchall()]
    except Exception as e:
        print(f"load_products error: {e}")
        return []


def backup_database():
    if not DB_FILE.exists():
        return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy(DB_FILE, BACKUPS_DIR / f"pricebot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")
    except Exception as e:
        print(f"backup_database error: {e}")


init_db()
