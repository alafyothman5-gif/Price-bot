import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


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
    except Exception as exc:
        print(f"DB_PRAGMA_WARNING: {exc}")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return bool(row)


def _cols(conn: sqlite3.Connection, table: str) -> List[str]:
    if not _table_exists(conn, table):
        return []
    return [row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _add_col(conn: sqlite3.Connection, table: str, col: str, dtype: str) -> None:
    if col not in _cols(conn, table):
        conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{col}" {dtype}')


def _safe_json(data: Any) -> str:
    return json.dumps(data or {}, ensure_ascii=False)


def _basic_normalize(text: str) -> str:
    value = str(text or "").strip().lower()
    for src, dst in {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ٱ": "ا"}.items():
        value = value.replace(src, dst)
    return " ".join(value.split())


def _safe_execute(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    try:
        conn.execute(sql, params)
    except Exception as exc:
        print(f"DB_MIGRATION_WARNING: {exc} | SQL={sql[:120]}")


def init_db() -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)")
        product_required = {
            "aliases": "TEXT DEFAULT ''",
            "active_ingredient": "TEXT DEFAULT ''",
            "brand": "TEXT DEFAULT ''",
            "company": "TEXT DEFAULT ''",
            "form": "TEXT DEFAULT ''",
            "category": "TEXT DEFAULT ''",
            "category_guess": "TEXT DEFAULT ''",
            "strength": "TEXT DEFAULT ''",
            "pack": "TEXT DEFAULT ''",
            "price": "TEXT DEFAULT ''",
            "available": "TEXT DEFAULT 'متوفر'",
            "notes": "TEXT DEFAULT ''",
            "image": "TEXT DEFAULT ''",
            "image_ocr_keywords": "TEXT DEFAULT ''",
            "ocr_keywords": "TEXT DEFAULT ''",
            "keywords": "TEXT DEFAULT ''",
            "normalized_name": "TEXT DEFAULT ''",
            "updated_at": "TEXT DEFAULT ''",
        }
        for col, dtype in product_required.items():
            _add_col(conn, "products", col, dtype)

        rows = conn.execute("SELECT id, name, normalized_name FROM products").fetchall()
        for row in rows:
            if not row["normalized_name"]:
                conn.execute("UPDATE products SET normalized_name=? WHERE id=?", (_basic_normalize(row["name"]), row["id"]))

        conn.execute("CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT DEFAULT '')")
        order_required = {
            "product_name": "TEXT DEFAULT ''",
            "price": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'pending'",
            "created_at": "TEXT DEFAULT ''",
        }
        for col, dtype in order_required.items():
            _add_col(conn, "orders", col, dtype)
        order_cols = _cols(conn, "orders")
        if "product" in order_cols:
            _safe_execute(conn, "UPDATE orders SET product_name=product WHERE (product_name IS NULL OR product_name='') AND product IS NOT NULL")
        if "time" in order_cols:
            _safe_execute(conn, "UPDATE orders SET created_at=time WHERE (created_at IS NULL OR created_at='') AND time IS NOT NULL")
        _safe_execute(conn, "UPDATE orders SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at=''")

        conn.execute("CREATE TABLE IF NOT EXISTS processed_messages (message_id TEXT PRIMARY KEY)")
        for col, dtype in {
            "phone": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'processing'",
            "created_at": "TEXT DEFAULT ''",
            "updated_at": "TEXT DEFAULT ''",
        }.items():
            _add_col(conn, "processed_messages", col, dtype)
        _safe_execute(conn, "UPDATE processed_messages SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at=''")
        _safe_execute(conn, "UPDATE processed_messages SET updated_at=CURRENT_TIMESTAMP WHERE updated_at IS NULL OR updated_at=''")

        conn.execute("CREATE TABLE IF NOT EXISTS conversation_state (phone TEXT DEFAULT '')")
        for col, dtype in {
            "phone": "TEXT DEFAULT ''",
            "state_json": "TEXT DEFAULT '{}'",
            "value_json": "TEXT DEFAULT '{}'",
            "updated_at": "TEXT DEFAULT ''",
            "user_key": "TEXT DEFAULT ''",
            "namespace": "TEXT DEFAULT ''",
        }.items():
            _add_col(conn, "conversation_state", col, dtype)
        _safe_execute(
            conn,
            "UPDATE conversation_state SET state_json=value_json "
            "WHERE (state_json IS NULL OR state_json='' OR state_json='{}') "
            "AND value_json IS NOT NULL AND value_json!='' AND value_json!='{}'",
        )
        _safe_execute(
            conn,
            "UPDATE conversation_state SET phone=user_key "
            "WHERE (phone IS NULL OR phone='') AND user_key IS NOT NULL AND user_key!=''",
        )
        _safe_execute(conn, "UPDATE conversation_state SET updated_at=CURRENT_TIMESTAMP WHERE updated_at IS NULL OR updated_at=''")

        legacy_tables = ["memory_entries", "product_inquiries", "conversation_states", "user_state", "user_memory", "memory"]
        for table in legacy_tables:
            if not _table_exists(conn, table):
                continue
            for col, dtype in {
                "phone": "TEXT DEFAULT ''",
                "state_json": "TEXT DEFAULT '{}'",
                "value_json": "TEXT DEFAULT '{}'",
                "message_id": "TEXT DEFAULT ''",
                "status": "TEXT DEFAULT ''",
                "created_at": "TEXT DEFAULT ''",
                "updated_at": "TEXT DEFAULT ''",
                "raw_query": "TEXT DEFAULT ''",
                "normalized_query": "TEXT DEFAULT ''",
                "source": "TEXT DEFAULT ''",
            }.items():
                try:
                    _add_col(conn, table, col, dtype)
                except Exception as exc:
                    print(f"LEGACY_MIGRATION_WARNING: table={table} col={col} error={exc}")

        for sql in [
            "CREATE INDEX IF NOT EXISTS idx_products_normalized_name ON products(normalized_name)",
            "CREATE INDEX IF NOT EXISTS idx_products_name ON products(name)",
            "CREATE INDEX IF NOT EXISTS idx_orders_status_created ON orders(status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_processed_status_updated ON processed_messages(status, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_conversation_phone ON conversation_state(phone)",
        ]:
            _safe_execute(conn, sql)

        conn.commit()


def _minutes_since_sqlite_time(value: str) -> float:
    if not value:
        return 999.0
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(value[:19], fmt)
            return (datetime.utcnow() - dt).total_seconds() / 60.0
        except Exception:
            pass
    try:
        return (datetime.utcnow().timestamp() - float(value)) / 60.0
    except Exception:
        return 999.0


def start_processing_message(message_id: str, phone: str = "") -> bool:
    if not message_id:
        return False
    with get_db_connection() as conn:
        row = conn.execute("SELECT status, updated_at FROM processed_messages WHERE message_id=?", (message_id,)).fetchone()
        if row:
            status = row["status"] or ""
            age_minutes = _minutes_since_sqlite_time(row["updated_at"] or "")
            if status == "done":
                return False
            if status in {"failed", ""} or (status == "processing" and age_minutes > 5):
                conn.execute(
                    "UPDATE processed_messages SET phone=?, status='processing', updated_at=CURRENT_TIMESTAMP WHERE message_id=?",
                    (phone or "", message_id),
                )
                conn.commit()
                return True
            return False

        conn.execute(
            "INSERT INTO processed_messages (message_id, phone, status, created_at, updated_at) VALUES (?, ?, 'processing', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (message_id, phone or ""),
        )
        conn.commit()
        return True


def mark_message_done(message_id: str, final_status: str = "done") -> None:
    if not message_id:
        return
    status = final_status if final_status in {"done", "failed", "processing"} else "failed"
    with get_db_connection() as conn:
        conn.execute("UPDATE processed_messages SET status=?, updated_at=CURRENT_TIMESTAMP WHERE message_id=?", (status, message_id))
        conn.commit()


def add_order(phone: str, product_name: str, price: str = "") -> int:
    with get_db_connection() as conn:
        cur = conn.execute(
            "INSERT INTO orders (phone, product_name, price, status, created_at) VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP)",
            (phone or "", product_name or "", price or ""),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_all_orders() -> List[dict]:
    with get_db_connection() as conn:
        try:
            rows = conn.execute("SELECT * FROM orders ORDER BY datetime(created_at) DESC, id DESC").fetchall()
        except Exception:
            rows = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]


def update_order_status(order_id: int, status: str) -> None:
    safe_status = status if status in {"pending", "completed", "canceled"} else "pending"
    with get_db_connection() as conn:
        conn.execute("UPDATE orders SET status=? WHERE id=?", (safe_status, order_id))
        conn.commit()


def get_user_state(phone: str) -> dict:
    if not phone:
        return {}
    with get_db_connection() as conn:
        row = conn.execute("SELECT state_json FROM conversation_state WHERE phone=? ORDER BY rowid DESC LIMIT 1", (phone,)).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row["state_json"] or "{}")
        except Exception as exc:
            print(f"USER_STATE_JSON_ERROR: phone={phone} error={exc}")
            return {}


def update_user_state(phone: str, state_data: dict) -> None:
    if not phone:
        return
    data = _safe_json(state_data)
    with get_db_connection() as conn:
        row = conn.execute("SELECT rowid FROM conversation_state WHERE phone=? ORDER BY rowid DESC LIMIT 1", (phone,)).fetchone()
        if row:
            conn.execute(
                "UPDATE conversation_state SET state_json=?, value_json=?, updated_at=CURRENT_TIMESTAMP WHERE rowid=?",
                (data, data, row["rowid"]),
            )
        else:
            conn.execute(
                "INSERT INTO conversation_state(namespace, user_key, phone, state_json, value_json, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                ("default", phone, phone, data, data),
            )
        conn.commit()


def clear_user_state(phone: str) -> None:
    if not phone:
        return
    with get_db_connection() as conn:
        conn.execute("DELETE FROM conversation_state WHERE phone=?", (phone,))
        conn.commit()


def load_products() -> List[dict]:
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM products").fetchall()
            return [dict(row) for row in rows]
    except Exception as exc:
        print(f"LOAD_PRODUCTS_ERROR: {exc}")
        return []


def backup_database() -> Optional[str]:
    if not DB_FILE.exists():
        return None
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUPS_DIR / f"pricebot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    try:
        shutil.copy2(DB_FILE, backup_path)
        print(f"DB_BACKUP_OK: {backup_path}")
        return str(backup_path)
    except Exception as exc:
        print(f"DB_BACKUP_ERROR: {exc}")
        return None


init_db()
