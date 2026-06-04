import os
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv
import database

load_dotenv()
# جلب مفتاح الأدمن من .env أو استخدام الافتراضي
ADMIN_KEY = os.getenv("ADMIN_KEY", "PriceBotAdmin2026")

router = APIRouter(prefix="/admin", tags=["Admin Panel"])

# ==========================================
# (النقطة 5) دالة الحماية: تتأكد من الرابط السري
# ==========================================
def verify_admin(key: str = Query(None)):
    if key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="عذراً، غير مصرح لك بالدخول. تأكد من الرابط والمفتاح السري.")
    return key

def get_html_header(key: str, title="لوحة تحكم الصيدلية"):
    """توليد واجهة HTML مع تمرير المفتاح السري في كل الروابط لضمان بقاء الجلسة آمنة"""
    return f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <title>{title}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; }}
            .container {{ max-width: 900px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
            h1, h2 {{ color: #2c3e50; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; border: 1px solid #ddd; text-align: right; }}
            th {{ background-color: #34495e; color: white; }}
            .btn {{ display: inline-block; padding: 10px 15px; margin: 5px; color: white; background-color: #3498db; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; }}
            .btn-success {{ background-color: #2ecc71; }}
            .btn-danger {{ background-color: #e74c3c; }}
            input[type="text"], input[type="file"] {{ padding: 8px; margin: 5px 0; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; }}
        </style>
    </head>
    <body>
    <div class="container">
        <div style="margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px;">
            <a href="/admin?key={key}" class="btn">🏠 الرئيسية</a>
            <a href="/admin/products?key={key}" class="btn">📦 إدارة الأدوية</a>
        </div>
    """

@router.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Depends(verify_admin)):
    products = database.load_products()
    html = get_html_header(key, "الرئيسية - PriceBot")
    html += f"""
        <h1>مرحباً بك في لوحة تحكم الصيدلية 🌿</h1>
        <div style="background: #ecf0f1; padding: 20px; border-radius: 8px; text-align: center;">
            <h2>إحصائيات المخزون</h2>
            <p style="font-size: 24px;">إجمالي المنتجات: <b>{len(products)}</b> منتج</p>
        </div>
    </div></body></html>
    """
    return html

@router.get("/products", response_class=HTMLResponse)
async def manage_products(key: str = Depends(verify_admin)):
    products = database.load_products()
    html = get_html_header(key, "إدارة الأدوية")
    html += f"""
        <h2>رفع قائمة الأدوية (CSV)</h2>
        <form action="/admin/upload_csv?key={key}" method="post" enctype="multipart/form-data" style="background: #e8f8f5; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
            <label>اختر ملف CSV:</label><br>
            <input type="file" name="file" accept=".csv" required><br><br>
            
            <input type="checkbox" id="replace_all" name="replace_all" value="yes">
            <label for="replace_all" style="color: red; font-weight: bold;">استبدال كامل (حذف كل المنتجات القديمة)</label>
            <p style="font-size: 12px; color: gray;">* إذا لم تقم بتحديد المربع، سيتم تحديث الأدوية الموجودة وإضافة الجديدة فقط (آمن).</p>
            
            <button type="submit" class="btn btn-success">رفع وتحديث 🚀</button>
        </form>

        <h2>قائمة الأدوية المتوفرة</h2>
        <table>
            <tr><th>الرقم</th><th>الاسم</th><th>السعر</th><th>الشكل الدوائي</th><th>إجراء</th></tr>
    """
    for p in products[:50]: 
        html += f"""
            <tr>
                <td>{p['id']}</td><td>{p['name']}</td><td>{p['price']}</td><td>{p.get('form', '-')}</td>
                <td>
                    <form action="/admin/products/delete/{p['id']}?key={key}" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-danger" onclick="return confirm('هل أنت متأكد من حذف هذا المنتج؟')">حذف</button>
                    </form>
                </td>
            </tr>
        """
    html += "</table><p style='text-align:center; color:gray; font-size:12px;'>يتم عرض أول 50 منتج فقط لتسريع الصفحة.</p></div></body></html>"
    return html

# ==========================================
# (النقطة 6) رفع الملفات بأسلوب التحديث الآمن
# ==========================================
@router.post("/upload_csv")
async def upload_csv(
    file: UploadFile = File(...), 
    replace_all: str = Form(None),
    key: str = Depends(verify_admin)
):
    # أخذ نسخة احتياطية قبل أي تعديل
    database.backup_database()
    
    content = await file.read()
    decoded = content.decode('utf-8-sig') # لدعم ملفات الإكسيل العربية
    reader = csv.DictReader(io.StringIO(decoded))
    
    with database.get_db_connection() as conn:
        # خيار الحذف الكامل إذا طلبه المستخدم صراحة
        if replace_all == "yes":
            conn.execute("DELETE FROM products")
            
        for row in reader:
            name = row.get("name", "").strip()
            if not name: continue
            
            price = row.get("price", "")
            form = row.get("form", "")
            aliases = row.get("aliases", "")
            active_ingredient = row.get("active_ingredient", "")
            company = row.get("company", "")
            available = row.get("available", "متوفر")
            
            # Safe Upsert: البحث عن المنتج وتحديثه أو إضافته
            existing = conn.execute("SELECT id FROM products WHERE name=?", (name,)).fetchone()
            if existing:
                conn.execute("""
                    UPDATE products 
                    SET price=?, form=?, aliases=?, active_ingredient=?, company=?, available=? 
                    WHERE name=?
                """, (price, form, aliases, active_ingredient, company, available, name))
            else:
                conn.execute("""
                    INSERT INTO products (name, price, form, aliases, active_ingredient, company, available) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (name, price, form, aliases, active_ingredient, company, available))
        conn.commit()
        
    return RedirectResponse(url=f"/admin/products?key={key}", status_code=303)

@router.post("/products/delete/{product_id}")
async def delete_product(product_id: int, key: str = Depends(verify_admin)):
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
    return RedirectResponse(url=f"/admin/products?key={key}", status_code=303)
