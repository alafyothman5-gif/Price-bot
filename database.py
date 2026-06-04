import sqlite3
import json
import time
import shutil
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

# ==========================================
# قاعدة البيانات في مسار آمن وثابت
# ==========================================
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "pricebot.db"
BACKUPS_DIR = BASE_DIR / "backups"

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    """تهيئة الجداول وعمل Migration للبيانات القديمة باحترافية"""
    with get_db_connection() as conn:
        # -------------------------------------------
        # 1. جدول المنتجات (Migration)
        # -------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """)
        
        cursor = conn.execute("PRAGMA table_info(products)")
        existing_columns = [col["name"] for col in cursor.fetchall()]
        
        required_columns = {
            "aliases": "TEXT DEFAULT ''",
            "active_ingredient": "TEXT DEFAULT ''",
            "brand": "TEXT DEFAULT ''",
            "company": "TEXT DEFAULT ''",
            "form": "TEXT DEFAULT ''",
            "strength": "TEXT DEFAULT ''",
            "pack": "TEXT DEFAULT ''",
            "price": "TEXT DEFAULT ''",
            "available": "TEXT DEFAULT 'متوفر'",
            "notes": "TEXT DEFAULT ''",
            "image": "TEXT DEFAULT ''",
            "normalized_name": "TEXT DEFAULT ''"
        }
        for col, dtype in required_columns.items():
            if col not in existing_columns:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {dtype}")
                print(f"Migration: Added column '{col}' to products table.")

        # -------------------------------------------
        # 2. جدول الطلبات (Migration لإصلاح النقطة 1)
        # -------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT
            )
        """)
        
        cursor_orders = conn.execute("PRAGMA table_info(orders)")
        existing_order_cols = [col["name"] for col in cursor_orders.fetchall()]
        
        order_cols_needed = {
            "product_name": "TEXT",
            "price": "TEXT",
            "status": "TEXT DEFAULT 'pending'",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        }
        
        for col, dtype in order_cols_needed.items():
            if col not in existing_order_cols:
                conn.execute(f"ALTER TABLE orders ADD COLUMN {col} {dtype}")
                print(f"Migration: Added column '{col}' to orders table.")
                
        # نقل البيانات من العمود القديم (product) إذا كان موجوداً لحفظ الطلبات السابقة
        if "product" in existing_order_cols and "product_name" not in existing_order_cols:
            try:
                conn.execute("UPDATE orders SET product_name = product WHERE product_name IS NULL")
                print("Migration: Migrated old 'product' data to 'product_name'.")
            except Exception as e:
                print(f"Migration Orders Error: {e}")

        # -------------------------------------------
        # 3. جدول منع التكرار (النقطة 5)
        # -------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'processing',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # -------------------------------------------
        # 4. جدول حالة الزبون
        # -------------------------------------------
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_state (
                phone TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.commit()

# ==========================================
# الحماية من التكرار مع نظام Retry الذكي (النقطة 5)
# ==========================================
def start_processing_message(message_id: str) -> bool:
    """يسمح بمعالجة الرسالة إذا كانت جديدة، أو فاشلة، أو عالقة لأكثر من 5 دقائق"""
    if not message_id: return False
    with get_db_connection() as conn:
        row = conn.execute("SELECT status, updated_at FROM processed_messages WHERE message_id=?", (message_id,)).fetchone()
        
        if row:
            status = row["status"]
            updated_at_str = row["updated_at"]
            
            try:
                # حساب فرق الوقت منذ آخر تحديث (لمعالجة الرسائل العالقة بسبب Restart)
                updated_at = datetime.strptime(updated_at_str, "%Y-%m-%d %H:%M:%S")
                diff_minutes = (datetime.utcnow() - updated_at).total_seconds() / 60.0
            except:
                diff_minutes = 10 # السماح بالمحاولة إذا فشل حساب الوقت
                
            if status == "done":
                return False # تمت بنجاح مسبقاً، تجاهل.
                
            if status == "failed" or (status == "processing" and diff_minutes > 5):
                # إعادة المحاولة وتحديث الوقت
                conn.execute("UPDATE processed_messages SET status='processing', updated_at=CURRENT_TIMESTAMP WHERE message_id=?", (message_id,))
                conn.commit()
                return True
                
            return False # قيد المعالجة حديثاً، تجاهل.
            
        # رسالة جديدة تماماً
        conn.execute("INSERT INTO processed_messages (message_id, status, updated_at) VALUES (?, 'processing', CURRENT_TIMESTAMP)", (message_id,))
        conn.commit()
        return True

def mark_message_done(message_id: str, final_status: str = 'done'):
    if not message_id: return
    with get_db_connection() as conn:
        conn.execute("UPDATE processed_messages SET status=?, updated_at=CURRENT_TIMESTAMP WHERE message_id=?", (final_status, message_id))
        conn.commit()

# ==========================================
# الطلبات وحالة الزبون
# ==========================================
def add_order(phone: str, product_name: str, price: str = ""):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO orders (phone, product_name, price) VALUES (?, ?, ?)", (phone, product_name, price))
        conn.commit()

def get_all_orders() -> List[dict]:
    with get_db_connection() as conn:
        rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

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

def clear_user_state(phone: str):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM conversation_state WHERE phone=?", (phone,))
        conn.commit()

# ==========================================
# إدارة المنتجات والنسخ الاحتياطي
# ==========================================
def load_products() -> List[dict]:
    try:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT * FROM products").fetchall()
            return [dict(row) for row in rows]
    except Exception as e:
        print(f"Error loading products: {e}")
        return []

def backup_database():
    if not DB_FILE.exists(): return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"pricebot_backup_{timestamp}.db"
    backup_path = BACKUPS_DIR / backup_name
    try:
        shutil.copy(DB_FILE, backup_path)
        print(f"✅ Backup created: {backup_name}")
    except Exception as e:
        print(f"❌ Backup failed: {e}")

# التأكد من التهيئة عند بدء التشغيل
init_db()
