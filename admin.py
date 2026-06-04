from fastapi import APIRouter, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
import database
import csv
import io

router = APIRouter(prefix="/admin", tags=["Admin Panel"])

def get_html_header(title="لوحة تحكم الصيدلية"):
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
            input {{ padding: 8px; margin: 5px 0; width: 100%; box-sizing: border-box; border: 1px solid #ccc; border-radius: 4px; }}
        </style>
    </head>
    <body>
    <div class="container">
        <div style="margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px;">
            <a href="/admin" class="btn">🏠 الرئيسية</a>
            <a href="/admin/products" class="btn">📦 إدارة الأدوية</a>
        </div>
    """

@router.get("/", response_class=HTMLResponse)
async def dashboard():
    products = database.load_products()
    html = get_html_header("الرئيسية - PriceBot")
    html += f"""
        <h1>مرحباً بك في لوحة تحكم PriceBot 🌿</h1>
        <div style="background: #ecf0f1; padding: 20px; border-radius: 8px; text-align: center;">
            <h2>إحصائيات المخزون</h2>
            <p style="font-size: 24px;">إجمالي المنتجات: <b>{len(products)}</b> منتج</p>
        </div>
    </div></body></html>
    """
    return html

@router.get("/products", response_class=HTMLResponse)
async def manage_products():
    products = database.load_products()
    html = get_html_header("إدارة الأدوية")
    html += """
        <h2>رفع قائمة الأدوية (CSV)</h2>
        <form action="/admin/upload_csv" method="post" enctype="multipart/form-data" style="background: #e8f8f5; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
            <label>اختر ملف CSV (سيتم تحديث قاعدة البيانات):</label><br><br>
            <input type="file" name="file" accept=".csv" required style="width: auto;">
            <button type="submit" class="btn btn-success">رفع وتحديث 🚀</button>
        </form>

        <h2>قائمة الأدوية المتوفرة</h2>
        <table>
            <tr><th>الرقم</th><th>الاسم</th><th>السعر</th><th>الشكل الدوائي</th><th>إجراء</th></tr>
    """
    for p in products[:50]: # عرض أول 50 لتسريع الصفحة
        html += f"""
            <tr>
                <td>{p['id']}</td><td>{p['name']}</td><td>{p['price']}</td><td>{p.get('form', '-')}</td>
                <td>
                    <form action="/admin/products/delete/{p['id']}" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-danger" onclick="return confirm('تأكيد الحذف؟')">حذف</button>
                    </form>
                </td>
            </tr>
        """
    html += "</table><p style='text-align:center; color:gray; font-size:12px;'>يتم عرض أول 50 منتج فقط.</p></div></body></html>"
    return html

@router.post("/upload_csv")
async def upload_csv(file: UploadFile = File(...)):
    content = await file.read()
    decoded = content.decode('utf-8-sig') # لدعم اللغة العربية
    reader = csv.DictReader(io.StringIO(decoded))
    
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products") # مسح القديم لتجنب التكرار
        for row in reader:
            conn.execute("""
                INSERT INTO products (name, price, form, aliases, active_ingredient, company, available) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get("name", ""), row.get("price", ""), row.get("form", ""), 
                row.get("aliases", ""), row.get("active_ingredient", ""), 
                row.get("company", ""), row.get("available", "متوفر")
            ))
        conn.commit()
    return RedirectResponse(url="/admin/products", status_code=303)

@router.post("/products/delete/{product_id}")
async def delete_product(product_id: int):
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
    return RedirectResponse(url="/admin/products", status_code=303)
