import json
import os
import re
import shutil
import sqlite3
import time
from threading import Lock
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_DIR = Path(__file__).resolve().parent
DB_FILE = Path(os.getenv("PRICEBOT_DB_FILE", str(BASE_DIR / "pricebot.db")))
if not DB_FILE.is_absolute():
    DB_FILE = BASE_DIR / DB_FILE
BACKUPS_DIR = BASE_DIR / "backups"
_WAL_LOCK = Lock()
_WAL_CONFIGURED = False
_MIGRATION_BACKUP_DONE = False


def _is_db_locked(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()


def _retry_db(fn, attempts: int = 6, base_delay: float = 0.15):
    last_exc = None
    for attempt in range(max(1, attempts)):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if not _is_db_locked(exc) or attempt >= attempts - 1:
                raise
            time.sleep(base_delay * (attempt + 1))
    if last_exc:
        raise last_exc


def get_db_connection() -> sqlite3.Connection:
    global _WAL_CONFIGURED
    conn = sqlite3.connect(str(DB_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        # journal_mode=WAL can briefly require a write lock. Do not run it on every
        # request connection; that was causing intermittent `database is locked`
        # errors during WhatsApp message bursts. Configure it once per process.
        if not _WAL_CONFIGURED:
            with _WAL_LOCK:
                if not _WAL_CONFIGURED:
                    try:
                        conn.execute("PRAGMA journal_mode=WAL")
                        conn.execute("PRAGMA synchronous=NORMAL")
                    except Exception as exc:
                        print(f"DB_WAL_PRAGMA_WARNING: {exc}")
                    _WAL_CONFIGURED = True
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
    for src, dst in {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ٱ": "ا", "ڤ": "ف", "ک": "ك", "ی": "ي", "گ": "ك", "چ": "ج", "پ": "ب"}.items():
        value = value.replace(src, dst)
    value = value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    return " ".join(value.split())


def _safe_execute(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> None:
    try:
        conn.execute(sql, params)
    except Exception as exc:
        print(f"DB_MIGRATION_WARNING: {exc} | SQL={sql[:160]}")


def init_db() -> None:
    """Safe startup migration. Does not delete user data.

    If an existing production DB is present, create a backup before applying
    CREATE TABLE/ADD COLUMN migrations. This is intentionally additive only.
    """
    global _MIGRATION_BACKUP_DONE
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    if DB_FILE.exists() and not _MIGRATION_BACKUP_DONE and os.getenv("PRICEBOT_SKIP_MIGRATION_BACKUP", "").lower() not in {"1", "true", "yes"}:
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        backup_path = BACKUPS_DIR / f"pre_migration_pricebot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        try:
            shutil.copy2(DB_FILE, backup_path)
            print(f"DB_PRE_MIGRATION_BACKUP_OK: {backup_path}")
        except Exception as exc:
            print(f"DB_PRE_MIGRATION_BACKUP_WARNING: {exc}")
        _MIGRATION_BACKUP_DONE = True
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
            "product_id": "TEXT DEFAULT ''",
            "product_family": "TEXT DEFAULT ''",
            "size": "TEXT DEFAULT ''",
            "use_case": "TEXT DEFAULT ''",
            "skin_type": "TEXT DEFAULT ''",
            "substitution_group_id": "TEXT DEFAULT ''",
            "review_status": "TEXT DEFAULT ''",
            "review_notes": "TEXT DEFAULT ''",
            "code": "TEXT DEFAULT ''",
            "barcode": "TEXT DEFAULT ''",
            "sku": "TEXT DEFAULT ''",
            "item_code": "TEXT DEFAULT ''",
            "product_code": "TEXT DEFAULT ''",
            "source_serial": "TEXT DEFAULT ''",
            "original_name": "TEXT DEFAULT ''",
            "price": "TEXT DEFAULT ''",
            "available": "TEXT DEFAULT 'متوفر'",
            "notes": "TEXT DEFAULT ''",
            "image": "TEXT DEFAULT ''",
            "image_ocr_keywords": "TEXT DEFAULT ''",
            "ocr_keywords": "TEXT DEFAULT ''",
            "keywords": "TEXT DEFAULT ''",
            "normalized_name": "TEXT DEFAULT ''",
            "currency": "TEXT DEFAULT 'LYD'",
            "subcategory": "TEXT DEFAULT ''",
            "body_area": "TEXT DEFAULT ''",
            "age_group": "TEXT DEFAULT ''",
            "gender": "TEXT DEFAULT ''",
            "medicine_route": "TEXT DEFAULT ''",
            "requires_clarification": "TEXT DEFAULT ''",
            "is_substitutable": "TEXT DEFAULT '0'",
            "image_refs": "TEXT DEFAULT ''",
            "last_updated": "TEXT DEFAULT ''",
            "merchant_id": "TEXT DEFAULT 'default'",
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
            "notified_stale_at": "TEXT DEFAULT ''",
            "merchant_id": "TEXT DEFAULT 'default'",
            "quantity": "TEXT DEFAULT '1'",
            "confirmed_by": "TEXT DEFAULT ''",
            "notes": "TEXT DEFAULT ''",
            "customer_phone_masked": "TEXT DEFAULT ''",
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
        _safe_execute(conn, "UPDATE conversation_state SET phone=user_key WHERE (phone IS NULL OR phone='') AND user_key IS NOT NULL AND user_key!=''")
        _safe_execute(conn, "UPDATE conversation_state SET user_key=phone WHERE (user_key IS NULL OR user_key='') AND phone IS NOT NULL AND phone!=''")
        _safe_execute(conn, "UPDATE conversation_state SET namespace='default' WHERE namespace IS NULL OR namespace=''")
        _safe_execute(conn, "UPDATE conversation_state SET updated_at=CURRENT_TIMESTAMP WHERE updated_at IS NULL OR updated_at=''")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS product_inquiries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT DEFAULT '',
                message_id TEXT DEFAULT '',
                raw_query TEXT DEFAULT '',
                normalized_query TEXT DEFAULT '',
                source TEXT DEFAULT '',
                status TEXT DEFAULT '',
                product_name TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for col, dtype in {
            "phone": "TEXT DEFAULT ''",
            "message_id": "TEXT DEFAULT ''",
            "raw_query": "TEXT DEFAULT ''",
            "normalized_query": "TEXT DEFAULT ''",
            "source": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT ''",
            "product_name": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        }.items():
            _add_col(conn, "product_inquiries", col, dtype)
        _safe_execute(conn, "UPDATE product_inquiries SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at=''")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS query_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT DEFAULT '',
                raw_query TEXT DEFAULT '',
                clean_query TEXT DEFAULT '',
                decision TEXT DEFAULT '',
                ts TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for col, dtype in {
            "phone": "TEXT DEFAULT ''",
            "raw_query": "TEXT DEFAULT ''",
            "clean_query": "TEXT DEFAULT ''",
            "decision": "TEXT DEFAULT ''",
            "ts": "TEXT DEFAULT ''",
        }.items():
            _add_col(conn, "query_logs", col, dtype)
        _safe_execute(conn, "UPDATE query_logs SET ts=CURRENT_TIMESTAMP WHERE ts IS NULL OR ts=''")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS synonyms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT UNIQUE NOT NULL,
                target TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for col, dtype in {
            "source": "TEXT DEFAULT ''",
            "target": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        }.items():
            _add_col(conn, "synonyms", col, dtype)
        _safe_execute(conn, "UPDATE synonyms SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at=''")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS product_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER DEFAULT 0,
                image_path TEXT DEFAULT '',
                ocr_text TEXT DEFAULT '',
                barcode TEXT DEFAULT '',
                perceptual_hash TEXT DEFAULT '',
                embedding_meta TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for col, dtype in {
            "product_id": "INTEGER DEFAULT 0",
            "image_path": "TEXT DEFAULT ''",
            "ocr_text": "TEXT DEFAULT ''",
            "barcode": "TEXT DEFAULT ''",
            "perceptual_hash": "TEXT DEFAULT ''",
            "embedding_meta": "TEXT DEFAULT ''",
            "merchant_id": "TEXT DEFAULT 'default'",
            "image_hash": "TEXT DEFAULT ''",
            "image_type": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        }.items():
            _add_col(conn, "product_images", col, dtype)
        _safe_execute(conn, "UPDATE product_images SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at=''")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alias_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_query TEXT DEFAULT '',
                clean_query TEXT DEFAULT '',
                target_product_id INTEGER DEFAULT 0,
                target_product_name TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for col, dtype in {
            "source_query": "TEXT DEFAULT ''",
            "clean_query": "TEXT DEFAULT ''",
            "target_product_id": "INTEGER DEFAULT 0",
            "target_product_name": "TEXT DEFAULT ''",
            "status": "TEXT DEFAULT 'pending'",
            "note": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
            "updated_at": "TEXT DEFAULT ''",
        }.items():
            _add_col(conn, "alias_suggestions", col, dtype)
        _safe_execute(conn, "UPDATE alias_suggestions SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at=''")
        _safe_execute(conn, "UPDATE alias_suggestions SET updated_at=CURRENT_TIMESTAMP WHERE updated_at IS NULL OR updated_at=''");

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ai_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT DEFAULT '',
                provider TEXT DEFAULT 'openrouter',
                model TEXT DEFAULT '',
                image_type TEXT DEFAULT '',
                success INTEGER DEFAULT 0,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                estimated_cost REAL DEFAULT 0,
                error TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for col, dtype in {
            "phone": "TEXT DEFAULT ''",
            "merchant_id": "TEXT DEFAULT 'default'",
            "customer_phone_masked": "TEXT DEFAULT ''",
            "purpose": "TEXT DEFAULT ''",
            "provider": "TEXT DEFAULT 'openrouter'",
            "model": "TEXT DEFAULT ''",
            "image_type": "TEXT DEFAULT ''",
            "success": "INTEGER DEFAULT 0",
            "prompt_tokens": "INTEGER DEFAULT 0",
            "completion_tokens": "INTEGER DEFAULT 0",
            "total_tokens": "INTEGER DEFAULT 0",
            "estimated_cost": "REAL DEFAULT 0",
            "error": "TEXT DEFAULT ''",
            "created_at": "TEXT DEFAULT ''",
        }.items():
            _add_col(conn, "ai_usage", col, dtype)
        _safe_execute(conn, "UPDATE ai_usage SET created_at=CURRENT_TIMESTAMP WHERE created_at IS NULL OR created_at=''")

        legacy_tables = ["memory_entries", "conversation_states", "user_state", "user_memory", "memory"]
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
            "CREATE INDEX IF NOT EXISTS idx_inquiries_status_created ON product_inquiries(status, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage(created_at)",
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


def cleanup_old_processed_messages(days: int = 30) -> int:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cur = conn.execute("DELETE FROM processed_messages WHERE datetime(updated_at) < datetime(?)", (cutoff,))
        conn.commit()
        return int(cur.rowcount or 0)


def cleanup_old_conversation_state(days: int = 30) -> int:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cur = conn.execute("DELETE FROM conversation_state WHERE datetime(updated_at) < datetime(?)", (cutoff,))
        conn.commit()
        return int(cur.rowcount or 0)


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


def get_stale_pending_orders(hours: int = 6, limit: int = 50) -> List[dict]:
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM orders
            WHERE status='pending'
              AND datetime(created_at) <= datetime(?)
              AND (notified_stale_at IS NULL OR notified_stale_at='')
            ORDER BY datetime(created_at) ASC
            LIMIT ?
            """,
            (cutoff, int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_order_stale_notified(order_id: int) -> None:
    with get_db_connection() as conn:
        conn.execute("UPDATE orders SET notified_stale_at=CURRENT_TIMESTAMP WHERE id=?", (order_id,))
        conn.commit()


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
    """Merge conversation state safely.

    Older versions replaced the whole state on every write. That made
    multi-step WhatsApp flows fragile. This function now merges keys and treats
    a value of None as delete-key. Call clear_user_state() when a full reset is
    required.
    """
    if not phone:
        return
    incoming = state_data or {}
    with get_db_connection() as conn:
        row = conn.execute("SELECT rowid, state_json FROM conversation_state WHERE phone=? ORDER BY rowid DESC LIMIT 1", (phone,)).fetchone()
        current = {}
        if row:
            try:
                current = json.loads(row["state_json"] or "{}")
                if not isinstance(current, dict):
                    current = {}
            except Exception:
                current = {}
        merged = dict(current)
        for key, value in incoming.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        data = _safe_json(merged)
        if row:
            conn.execute(
                "UPDATE conversation_state SET state_json=?, value_json=?, namespace='default', user_key=?, updated_at=CURRENT_TIMESTAMP WHERE rowid=?",
                (data, data, phone, row["rowid"]),
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


def count_products() -> int:
    try:
        with get_db_connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()
            return int(row["c"] or 0)
    except Exception as exc:
        print(f"COUNT_PRODUCTS_ERROR: {exc}")
        return 0


def get_product(product_id: int) -> Optional[dict]:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        return dict(row) if row else None


def _invalidate_matcher_cache() -> None:
    try:
        import matcher
        if hasattr(matcher, "refresh_synonym_rules"):
            matcher.refresh_synonym_rules()
        else:
            matcher.invalidate_product_cache()
    except Exception as exc:
        print(f"MATCHER_CACHE_INVALIDATE_WARNING: {exc}")


def update_product(product_id: int, fields: Dict[str, Any]) -> None:
    allowed = {
        "product_id", "name", "price", "brand", "company", "category", "product_family", "form", "size",
        "aliases", "image_ocr_keywords", "ocr_keywords", "active_ingredient", "use_case", "skin_type",
        "strength", "pack", "available", "substitution_group_id", "review_status", "review_notes",
        "code", "barcode", "sku", "item_code", "product_code", "normalized_name", "subcategory",
        "body_area", "age_group", "gender", "medicine_route", "requires_clarification", "currency",
        "is_substitutable", "image_refs", "last_updated", "merchant_id"
    }
    updates = [(key, str(value or "")) for key, value in fields.items() if key in allowed]
    if not updates:
        return
    if "name" in dict(updates):
        updates.append(("normalized_name", _basic_normalize(dict(updates)["name"])))
    set_clause = ", ".join(f'"{key}"=?' for key, _ in updates) + ", updated_at=CURRENT_TIMESTAMP"
    params = [value for _, value in updates] + [product_id]
    with get_db_connection() as conn:
        conn.execute(f"UPDATE products SET {set_clause} WHERE id=?", params)
        conn.commit()
    _invalidate_matcher_cache()


def log_product_inquiry(phone: str, raw_query: str, normalized_query: str, source: str, status: str, product_name: str = "", message_id: str = "") -> None:
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO product_inquiries(phone, message_id, raw_query, normalized_query, source, status, product_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (phone or "", message_id or "", raw_query or "", normalized_query or "", source or "", status or "", product_name or ""),
            )
            conn.commit()
    except Exception as exc:
        print(f"LOG_PRODUCT_INQUIRY_ERROR: {exc}")


def ensure_query_logs_table() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS query_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT DEFAULT '',
                raw_query TEXT DEFAULT '',
                clean_query TEXT DEFAULT '',
                decision TEXT DEFAULT '',
                ts TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def log_query_miss(phone: str, raw_query: str, clean_query: str, decision: str) -> None:
    try:
        ensure_query_logs_table()
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO query_logs (phone, raw_query, clean_query, decision, ts) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (phone or "", raw_query or "", clean_query or "", decision or ""),
            )
            conn.commit()
    except Exception as exc:
        print(f"LOG_QUERY_MISS_ERROR: {exc}")


def get_query_misses(limit: int = 100) -> List[dict]:
    ensure_query_logs_table()
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT raw_query, clean_query, decision, COUNT(*) AS freq, MAX(ts) AS last_seen
            FROM query_logs
            WHERE decision IN ('fallback','unavailable','ambiguous','matched_unavailable','variant_strength_not_found','low_confidence')
            GROUP BY clean_query, decision
            ORDER BY freq DESC, datetime(last_seen) DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]


def ensure_synonyms_table() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS synonyms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT UNIQUE NOT NULL,
                target TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def load_dynamic_synonyms() -> dict:
    try:
        ensure_synonyms_table()
        with get_db_connection() as conn:
            rows = conn.execute("SELECT source, target FROM synonyms WHERE TRIM(source)!='' AND TRIM(target)!=''").fetchall()
            return {str(row["source"]): str(row["target"]) for row in rows}
    except Exception as exc:
        print(f"LOAD_DYNAMIC_SYNONYMS_ERROR: {exc}")
        return {}


def load_dynamic_synonyms_clean() -> Dict[str, str]:
    """Return one cleaned dynamic synonym mapping for all matcher modules.

    Keeping the cleanup here prevents matcher_v2/matcher_v3/matcher_v4 from
    maintaining separate synonym-loading implementations that can drift.
    """
    raw = load_dynamic_synonyms() or {}
    return {
        str(source).strip(): str(target).strip()
        for source, target in raw.items()
        if str(source or "").strip() and str(target or "").strip()
    }


def add_synonym(source: str, target: str) -> None:
    source = str(source or "").strip()
    target = str(target or "").strip()
    if not source or not target:
        raise ValueError("source and target are required")
    ensure_synonyms_table()
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO synonyms (source, target, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (source, target),
        )
        conn.commit()
    _invalidate_matcher_cache()


def list_synonyms(limit: int = 200) -> List[dict]:
    ensure_synonyms_table()
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, source, target, created_at FROM synonyms ORDER BY datetime(created_at) DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]


def log_ai_usage(phone: str = "", provider: str = "openrouter", model: str = "", image_type: str = "", success: bool = False,
                 prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0, estimated_cost: float = 0.0, error: str = "") -> None:
    try:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO ai_usage(phone, provider, model, image_type, success, prompt_tokens, completion_tokens, total_tokens, estimated_cost, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (phone or "", provider or "openrouter", model or "", image_type or "", 1 if success else 0, int(prompt_tokens or 0), int(completion_tokens or 0), int(total_tokens or 0), float(estimated_cost or 0.0), error or ""),
            )
            conn.commit()
    except Exception as exc:
        print(f"LOG_AI_USAGE_ERROR: {exc}")


def get_ai_usage_summary(days: int = 30) -> dict:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total, SUM(success) AS success_count, SUM(total_tokens) AS tokens,
                   SUM(estimated_cost) AS cost
            FROM ai_usage WHERE datetime(created_at) >= datetime(?)
            """,
            (cutoff,),
        ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "success": int(row["success_count"] or 0),
            "tokens": int(row["tokens"] or 0),
            "cost": float(row["cost"] or 0.0),
        }


def get_failed_queries(limit: int = 50) -> List[dict]:
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT raw_query, normalized_query, source, status, COUNT(*) AS count, MAX(created_at) AS last_seen
            FROM product_inquiries
            WHERE status IN ('fallback','unavailable','ambiguous','matched_unavailable','variant_strength_not_found','timeout_fallback','error_fallback','unclear_image')
            GROUP BY raw_query, normalized_query, source, status
            ORDER BY count DESC, datetime(last_seen) DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [dict(row) for row in rows]


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



# ---------------- PriceBot V19 platform helpers ----------------
def ensure_v19_tables() -> None:
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS merchants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id TEXT UNIQUE DEFAULT 'default',
                pharmacy_name TEXT DEFAULT '',
                city TEXT DEFAULT '',
                working_hours TEXT DEFAULT '',
                delivery_enabled TEXT DEFAULT 'false',
                whatsapp_number TEXT DEFAULT '',
                phone_number_id TEXT DEFAULT '',
                welcome_message TEXT DEFAULT '',
                currency TEXT DEFAULT 'LYD',
                logo_url TEXT DEFAULT '',
                subscription_plan TEXT DEFAULT 'pilot',
                status TEXT DEFAULT 'active',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS merchant_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id TEXT DEFAULT 'default',
                key TEXT DEFAULT '',
                value TEXT DEFAULT '',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(merchant_id, key)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS review_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER DEFAULT 0,
                merchant_id TEXT DEFAULT 'default',
                name TEXT DEFAULT '',
                review_reason TEXT DEFAULT '',
                review_status TEXT DEFAULT 'needs_review',
                payload_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id TEXT DEFAULT 'default',
                event_type TEXT DEFAULT '',
                actor TEXT DEFAULT '',
                entity_type TEXT DEFAULT '',
                entity_id TEXT DEFAULT '',
                old_value TEXT DEFAULT '',
                new_value TEXT DEFAULT '',
                ip TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id TEXT DEFAULT 'default',
                customer_phone_masked TEXT DEFAULT '',
                model TEXT DEFAULT '',
                purpose TEXT DEFAULT '',
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                image_count INTEGER DEFAULT 0,
                cost_estimate REAL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                success INTEGER DEFAULT 0,
                error TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS failed_query_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                merchant_id TEXT DEFAULT 'default',
                raw_query TEXT DEFAULT '',
                action TEXT DEFAULT '',
                product_id INTEGER DEFAULT 0,
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for table in ["products", "orders", "product_inquiries", "query_logs", "synonyms", "image_cache", "product_images", "alias_suggestions"]:
            try:
                _add_col(conn, table, "merchant_id", "TEXT DEFAULT 'default'")
            except Exception:
                pass
        # default merchant/settings from environment, no secrets.
        defaults = {
            "pharmacy_name": os.getenv("PHARMACY_NAME", "صيدلية بدر البشرية"),
            "city": os.getenv("PHARMACY_CITY", "Ajdabiya"),
            "working_hours": os.getenv("PHARMACY_HOURS", "24h"),
            "delivery_enabled": os.getenv("DELIVERY_ENABLED", "false"),
            "whatsapp_number": os.getenv("BOT_WHATSAPP_NUMBER", ""),
            "currency": os.getenv("PRICEBOT_CURRENCY", "LYD"),
            "welcome_message": os.getenv("WELCOME_MESSAGE", "أهلاً بك، اكتب اسم المنتج أو أرسل صورة واضحة للعلبة."),
        }
        conn.execute("""
            INSERT OR IGNORE INTO merchants(merchant_id, pharmacy_name, city, working_hours, delivery_enabled, whatsapp_number, currency, welcome_message)
            VALUES('default', ?, ?, ?, ?, ?, ?, ?)
        """, (defaults["pharmacy_name"], defaults["city"], defaults["working_hours"], defaults["delivery_enabled"], defaults["whatsapp_number"], defaults["currency"], defaults["welcome_message"]))
        for k, v in defaults.items():
            conn.execute("INSERT OR IGNORE INTO merchant_settings(merchant_id, key, value) VALUES('default', ?, ?)", (k, str(v)))
        conn.commit()


def get_merchant_settings(merchant_id: str = "default") -> dict:
    ensure_v19_tables()
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM merchants WHERE merchant_id=?", (merchant_id,)).fetchone()
        data = dict(row) if row else {"merchant_id": merchant_id}
        rows = conn.execute("SELECT key, value FROM merchant_settings WHERE merchant_id=?", (merchant_id,)).fetchall()
        for r in rows:
            data[str(r["key"])] = r["value"]
        return data


def set_merchant_setting(key: str, value: str, merchant_id: str = "default") -> None:
    ensure_v19_tables()
    with get_db_connection() as conn:
        conn.execute("INSERT INTO merchant_settings(merchant_id, key, value, updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(merchant_id,key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP", (merchant_id, key, value))
        if key in {"pharmacy_name", "city", "working_hours", "delivery_enabled", "whatsapp_number", "currency", "welcome_message"}:
            conn.execute(f"UPDATE merchants SET {key}=?, updated_at=CURRENT_TIMESTAMP WHERE merchant_id=?", (value, merchant_id))
        conn.commit()


def log_audit(event_type: str, actor: str = "admin", entity_type: str = "", entity_id: str = "", old_value: str = "", new_value: str = "", ip: str = "", merchant_id: str = "default") -> None:
    ensure_v19_tables()
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO audit_logs(merchant_id,event_type,actor,entity_type,entity_id,old_value,new_value,ip,created_at)
            VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """, (merchant_id, event_type, actor, entity_type, str(entity_id or ""), str(old_value or "")[:2000], str(new_value or "")[:2000], ip or ""))
        conn.commit()


def get_audit_logs(limit: int = 100, merchant_id: str = "default") -> List[dict]:
    ensure_v19_tables()
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM audit_logs WHERE merchant_id=? ORDER BY datetime(created_at) DESC, id DESC LIMIT ?", (merchant_id, int(limit))).fetchall()
        return [dict(r) for r in rows]


def add_review_queue_item(product: dict, reason: str, merchant_id: str = "default") -> None:
    ensure_v19_tables()
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO review_queue(product_id, merchant_id, name, review_reason, review_status, payload_json, created_at, updated_at)
            VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
        """, (int(product.get("id") or 0), merchant_id, product.get("name", ""), reason or "", "needs_review", _safe_json(product)))
        conn.commit()


def rebuild_review_queue_from_products(limit: int = 10000, merchant_id: str = "default") -> int:
    from services.catalog_quality import analyze_products
    products = load_products()
    report = analyze_products(products)
    count = 0
    with get_db_connection() as conn:
        conn.execute("DELETE FROM review_queue WHERE merchant_id=?", (merchant_id,))
        for row in report.get("review_rows", [])[:int(limit)]:
            conn.execute("""
                INSERT INTO review_queue(product_id, merchant_id, name, review_reason, review_status, payload_json, created_at, updated_at)
                VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            """, (int(row.get("id") or 0), merchant_id, row.get("name", ""), row.get("quality_issues", ""), "needs_review", _safe_json(row)))
            count += 1
        conn.commit()
    return count


def get_review_queue(limit: int = 250, merchant_id: str = "default") -> List[dict]:
    ensure_v19_tables()
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM review_queue WHERE merchant_id=? ORDER BY id DESC LIMIT ?", (merchant_id, int(limit))).fetchall()
        return [dict(r) for r in rows]


def log_ai_usage_v19(merchant_id: str = "default", customer_phone_masked: str = "", model: str = "", purpose: str = "vision", tokens_in: int = 0, tokens_out: int = 0, image_count: int = 0, cost_estimate: float = 0.0, success: bool = False, error: str = "") -> None:
    ensure_v19_tables()
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO ai_usage_logs(merchant_id,customer_phone_masked,model,purpose,tokens_in,tokens_out,image_count,cost_estimate,created_at,success,error)
            VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,?,?)
        """, (merchant_id, customer_phone_masked, model, purpose, int(tokens_in or 0), int(tokens_out or 0), int(image_count or 0), float(cost_estimate or 0.0), 1 if success else 0, error or ""))
        conn.commit()


def get_ai_usage_logs(limit: int = 100, merchant_id: str = "default") -> List[dict]:
    ensure_v19_tables()
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM ai_usage_logs WHERE merchant_id=? ORDER BY datetime(created_at) DESC, id DESC LIMIT ?", (merchant_id, int(limit))).fetchall()
        return [dict(r) for r in rows]


def add_product_image(product_id: int, image_path: str, image_hash: str = "", perceptual_hash: str = "", ocr_text: str = "", image_type: str = "front", merchant_id: str = "default") -> None:
    ensure_product_images_table(); ensure_v19_tables()
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO product_images(product_id, merchant_id, image_path, image_hash, perceptual_hash, ocr_text, image_type, created_at)
            VALUES(?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        """, (int(product_id or 0), merchant_id, image_path or "", image_hash or "", perceptual_hash or "", ocr_text or "", image_type or "front"))
        conn.commit()


def list_product_images(product_id: int, merchant_id: str = "default") -> List[dict]:
    ensure_product_images_table(); ensure_v19_tables()
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM product_images WHERE product_id=? AND merchant_id=? ORDER BY id DESC", (int(product_id or 0), merchant_id)).fetchall()
        return [dict(r) for r in rows]


def get_duplicate_name_groups(limit: int = 100) -> List[dict]:
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT normalized_name, COUNT(*) AS count, GROUP_CONCAT(id) AS ids, GROUP_CONCAT(name, ' || ') AS names
            FROM products WHERE normalized_name IS NOT NULL AND normalized_name != ''
            GROUP BY normalized_name HAVING COUNT(*) > 1
            ORDER BY count DESC LIMIT ?
        """, (int(limit),)).fetchall()
        return [dict(r) for r in rows]

# ---------------- Product Intelligence V4 support tables ----------------
def ensure_product_images_table() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS product_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER DEFAULT 0,
                image_path TEXT DEFAULT '',
                ocr_text TEXT DEFAULT '',
                barcode TEXT DEFAULT '',
                perceptual_hash TEXT DEFAULT '',
                embedding_meta TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def ensure_alias_suggestions_table() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alias_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_query TEXT DEFAULT '',
                clean_query TEXT DEFAULT '',
                target_product_id INTEGER DEFAULT 0,
                target_product_name TEXT DEFAULT '',
                status TEXT DEFAULT 'pending',
                note TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def add_alias_suggestion(source_query: str, clean_query: str = "", target_product_id: int = 0, target_product_name: str = "", status: str = "pending", note: str = "") -> None:
    ensure_alias_suggestions_table()
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO alias_suggestions (source_query, clean_query, target_product_id, target_product_name, status, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
            (source_query or "", clean_query or "", int(target_product_id or 0), target_product_name or "", status or "pending", note or ""),
        )
        conn.commit()


def list_alias_suggestions(limit: int = 100, status: str = "pending") -> List[dict]:
    ensure_alias_suggestions_table()
    with get_db_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM alias_suggestions WHERE status=? ORDER BY datetime(updated_at) DESC, id DESC LIMIT ?",
                (status, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM alias_suggestions ORDER BY datetime(updated_at) DESC, id DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(row) for row in rows]


def add_product_alias(product_id: int, alias: str) -> dict:
    alias = str(alias or "").strip()
    if not alias:
        raise ValueError("alias is required")
    with get_db_connection() as conn:
        row = conn.execute("SELECT id, name, aliases FROM products WHERE id=?", (int(product_id),)).fetchone()
        if not row:
            raise ValueError("product not found")
        aliases = [x.strip() for x in re.split(r"[,،|;\n]+", row["aliases"] or "") if x and x.strip()]
        if alias.lower() not in {x.lower() for x in aliases}:
            aliases.append(alias)
        conn.execute("UPDATE products SET aliases=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (", ".join(aliases), int(product_id)))
        conn.commit()
        return dict(row)


def approve_alias_learning(source_query: str, clean_query: str, product_id: int) -> dict:
    product = add_product_alias(product_id, source_query or clean_query)
    add_alias_suggestion(source_query, clean_query, int(product_id), product.get("name", ""), "approved", "alias_added_to_product")
    _invalidate_matcher_cache()
    return product


def reject_alias_suggestion(suggestion_id: int, note: str = "") -> None:
    ensure_alias_suggestions_table()
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE alias_suggestions SET status='rejected', note=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (note or "", int(suggestion_id)),
        )
        conn.commit()

# ---------------- Vision cache V17.4 ----------------
def ensure_image_cache_table() -> None:
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS image_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_hash TEXT UNIQUE,
                perceptual_hash TEXT DEFAULT '',
                vision_output_json TEXT NOT NULL,
                matched_product_id TEXT DEFAULT '',
                decision TEXT DEFAULT '',
                confidence REAL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
                used_count INTEGER DEFAULT 1
            )
            """
        )
        for col, dtype in {
            "image_hash": "TEXT UNIQUE",
            "perceptual_hash": "TEXT DEFAULT ''",
            "vision_output_json": "TEXT NOT NULL DEFAULT '{}'",
            "matched_product_id": "TEXT DEFAULT ''",
            "decision": "TEXT DEFAULT ''",
            "confidence": "REAL DEFAULT 0",
            "created_at": "TEXT DEFAULT ''",
            "last_used_at": "TEXT DEFAULT ''",
            "used_count": "INTEGER DEFAULT 1",
        }.items():
            try:
                _add_col(conn, "image_cache", col, dtype)
            except Exception as exc:
                print(f"IMAGE_CACHE_MIGRATION_WARNING: {exc}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_image_cache_hash ON image_cache(image_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_image_cache_perceptual_hash ON image_cache(perceptual_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_image_cache_last_used ON image_cache(last_used_at)")
        conn.commit()


def _image_cache_ttl_days(decision: str) -> int:
    d = str(decision or "").upper()
    if d == "EXACT_MATCH":
        return 90
    if d == "NOT_AVAILABLE":
        return 14
    if d in {"LOW_CONFIDENCE", "IMAGE_UNCLEAR"}:
        return 1
    return 30




def _hex_hamming_distance(a: str, b: str) -> int:
    try:
        if not a or not b or len(a) != len(b):
            return 999
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 999


def _image_cache_row_is_fresh(data: dict) -> bool:
    decision = str(data.get("decision") or "")
    ttl = _image_cache_ttl_days(decision)
    last = data.get("last_used_at") or data.get("created_at") or ""
    try:
        dt = datetime.strptime(str(last)[:19], "%Y-%m-%d %H:%M:%S")
        if (datetime.utcnow() - dt).days > ttl:
            return False
    except Exception:
        pass
    return True


def _hydrate_image_cache_row(data: dict) -> dict:
    try:
        data["vision_output"] = json.loads(data.get("vision_output_json") or "{}")
    except Exception:
        data["vision_output"] = {}
    return data


def get_image_cache(image_hash: str) -> Optional[dict]:
    image_hash = str(image_hash or "").strip()
    if not image_hash:
        return None
    try:
        ensure_image_cache_table()
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM image_cache WHERE image_hash=?", (image_hash,)).fetchone()
            if not row:
                return None
            data = dict(row)
            decision = str(data.get("decision") or "")
            ttl = _image_cache_ttl_days(decision)
            last = data.get("last_used_at") or data.get("created_at") or ""
            try:
                dt = datetime.strptime(str(last)[:19], "%Y-%m-%d %H:%M:%S")
                if (datetime.utcnow() - dt).days > ttl:
                    return None
            except Exception:
                pass
            conn.execute("UPDATE image_cache SET used_count=COALESCE(used_count,0)+1, last_used_at=CURRENT_TIMESTAMP WHERE image_hash=?", (image_hash,))
            conn.commit()
            try:
                data["vision_output"] = json.loads(data.get("vision_output_json") or "{}")
            except Exception:
                data["vision_output"] = {}
            return data
    except Exception as exc:
        print(f"IMAGE_CACHE_GET_ERROR: {exc}")
        return None


def get_image_cache_by_perceptual_hash(perceptual_hash: str, max_distance: int = 5) -> Optional[dict]:
    """Find a safe perceptual cache hit for resized/compressed copies.

    Perceptual reuse is intentionally conservative: only high-confidence
    EXACT_MATCH/NOT_AVAILABLE rows are reusable. LOW_CONFIDENCE and IMAGE_UNCLEAR
    remain exact-hash only with their short TTL.
    """
    perceptual_hash = str(perceptual_hash or "").strip().lower()
    if not perceptual_hash:
        return None
    try:
        ensure_image_cache_table()
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM image_cache
                WHERE perceptual_hash IS NOT NULL AND perceptual_hash != ''
                ORDER BY datetime(last_used_at) DESC
                LIMIT 200
                """
            ).fetchall()
            best = None
            best_distance = 999
            for row in rows:
                data = dict(row)
                decision = str(data.get("decision") or "").upper()
                if decision not in {"EXACT_MATCH", "NOT_AVAILABLE"}:
                    continue
                try:
                    if float(data.get("confidence") or 0.0) < 0.75:
                        continue
                except Exception:
                    continue
                if not _image_cache_row_is_fresh(data):
                    continue
                distance = _hex_hamming_distance(perceptual_hash, str(data.get("perceptual_hash") or ""))
                if distance <= int(max_distance) and distance < best_distance:
                    best = data
                    best_distance = distance
            if not best:
                return None
            conn.execute("UPDATE image_cache SET used_count=COALESCE(used_count,0)+1, last_used_at=CURRENT_TIMESTAMP WHERE id=?", (best.get("id"),))
            conn.commit()
            best["perceptual_distance"] = best_distance
            return _hydrate_image_cache_row(best)
    except Exception as exc:
        print(f"IMAGE_CACHE_PERCEPTUAL_GET_ERROR: {exc}")
        return None


def save_image_cache(image_hash: str, vision_output: dict, matched_product_id: str = "", decision: str = "", confidence: float = 0.0, perceptual_hash: str = "") -> None:
    image_hash = str(image_hash or "").strip()
    if not image_hash:
        return
    try:
        ensure_image_cache_table()
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO image_cache(image_hash, perceptual_hash, vision_output_json, matched_product_id, decision, confidence, created_at, last_used_at, used_count)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)
                ON CONFLICT(image_hash) DO UPDATE SET
                    perceptual_hash=excluded.perceptual_hash,
                    vision_output_json=excluded.vision_output_json,
                    matched_product_id=excluded.matched_product_id,
                    decision=excluded.decision,
                    confidence=excluded.confidence,
                    last_used_at=CURRENT_TIMESTAMP,
                    used_count=COALESCE(image_cache.used_count,0)+1
                """,
                (image_hash, perceptual_hash or "", _safe_json(vision_output or {}), matched_product_id or "", decision or "", float(confidence or 0.0)),
            )
            conn.commit()
    except Exception as exc:
        print(f"IMAGE_CACHE_SAVE_ERROR: {exc}")
