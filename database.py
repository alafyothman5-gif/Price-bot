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
    """تهيئة الجداول وعمل Migration للبيانات القديمة"""
    with get_db_connection() as conn:
        # 1. جدول المنتجات
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL
            )
        """)
        
        # Migration الآمن لكل الأعمدة التي طلبها المشرف
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
            "normalized_name": "TEXT DEFAULT ''" # جديد لضمان دقة الرفع وعدم التكرار (النقطة 22)
        }
        
        for col, dtype in required_columns.items():
            if col not in existing_columns:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {dtype}")
                print(f"Migration: Added column '{col}' to products table.")

        # 2. جدول الطلبات
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT,
                product_name TEXT,
                price TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 3. (النقطة 3) جدول منع التكرار المحدث
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processed_messages (
                message_id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'processing',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 4. جدول حالة الزبون
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_state (
                phone TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.commit()

# ==========================================
# (النقطة 3) نظام الحماية من تكرار الرسائل (المعدل)
# ==========================================
def start_processing_message(message_id: str) -> bool:
    """إرجاع True إذا كانت الرسالة جديدة وتم تسجيلها للبدء. إرجاع False إذا تمت معالجتها أو جاري معالجتها."""
    if not message_id: return False
    with get_db_connection() as conn:
        row = conn.execute("SELECT status FROM processed_messages WHERE message_id=?", (message_id,)).fetchone()
        if row:
            # إذا كانت status = done، نتجاهلها. إذا failed، ممكن نسمح بمعالجتها مرة أخرى لاحقاً لو طلبنا.
            # حالياً نمنع التكرار طالما هي مسجلة.
            return False
            
        conn.execute("INSERT INTO processed_messages (message_id, status) VALUES (?, 'processing')", (message_id,))
        conn.commit()
        return True

def mark_message_done(message_id: str, final_status: str = 'done'):
    """يتم استدعاءها فقط بعد الإرسال النهائي لضمان عدم ضياع الرسالة في حال حدوث Error (النقطة 3)"""
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
    """نسخ احتياطي منظم في مجلد backups"""
    if not DB_FILE.exists(): return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"pricebot_backup_{timestamp}.db"
    backup_path = BACKUPS_DIR / backup_name
    try:
        shutil.copy(DB_FILE, backup_path)
        print(f"✅ Backup created successfully: {backup_path}")
    except Exception as e:
        print(f"❌ Backup failed: {e}")

# التأكد من التهيئة
init_db()

