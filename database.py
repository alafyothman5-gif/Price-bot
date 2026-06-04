import sqlite3
import json
import time
import shutil
import os
from pathlib import Path
from typing import List

DB_FILE = Path("pricebot.db")

def get_db_connection() -> sqlite3.Connection:
    """اتصال آمن وسريع بقاعدة البيانات مع تفعيل نمط WAL"""
    conn = sqlite3.connect(str(DB_FILE), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    """
    (النقطة 7) - التأكد من وجود الجداول وعدم حذف أي بيانات سابقة.
    يتم إنشاء الجداول فقط إذا لم تكن موجودة.
    """
    with get_db_connection() as conn:
        # 1. جدول المنتجات
        conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, aliases TEXT DEFAULT '', active_ingredient TEXT DEFAULT '',
                brand TEXT DEFAULT '', company TEXT DEFAULT '', form TEXT DEFAULT '',
                strength TEXT DEFAULT '', pack TEXT DEFAULT '', price TEXT DEFAULT '',
                available TEXT DEFAULT 'متوفر', notes TEXT DEFAULT '', image TEXT DEFAULT ''
            )
        """)
        
        # 2. جدول الطلبات (للحفاظ على طلبات الزبائن)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT, product_name TEXT, status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 3. جدول ذاكرة المحادثات
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_state (
                phone TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.commit()

# ==========================================
# إدارة حالة الزبون (إصلاح البج - النقطة 8)
# ==========================================
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

def clear_user_state(phone: str):
    """
    (النقطة 8) - تم إضافة هذه الدالة لتفريغ ذاكرة الزبون 
    بعد أن يكتب (نعم/لا) لمنع حدوث الـ Error.
    """
    with get_db_connection() as conn:
        conn.execute("DELETE FROM conversation_state WHERE phone=?", (phone,))
        conn.commit()

# ==========================================
# إدارة المنتجات والنسخ الاحتياطي (النقطة 6)
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
    """
    (النقطة 6) - أخذ نسخة احتياطية من القاعدة قبل أي رفع CSV
    """
    if DB_FILE.exists():
        backup_name = f"pricebot_backup_{int(time.time())}.db"
        shutil.copy(DB_FILE, backup_name)
        print(f"✅ تم أخذ نسخة احتياطية بنجاح: {backup_name}")

# تشغيل التهيئة عند استدعاء الملف للتأكد من سلامة القاعدة
init_db()
