import os
import csv
import io
import html
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from dotenv import load_dotenv
import openpyxl

import database
import matcher

load_dotenv()
# (النقطة 1) دعم PRICEBOT_ADMIN_KEY
ADMIN_KEY = os.getenv("PRICEBOT_ADMIN_KEY") or os.getenv("ADMIN_KEY") or "PriceBotAdmin2026"

router = APIRouter(prefix="/admin", tags=["Admin Panel"])

def verify_admin(key: str = Query(None)):
    if key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="عذراً، غير مصرح لك بالدخول. تأكد من الرابط والمفتاح السري.")
    return key

def get_html_header(key: str, title="لوحة تحكم الصيدلية"):
    return f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Arial, sans-serif; background-color: #f4f7f6; margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }}
            h1, h2 {{ color: #2c3e50; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; border: 1px solid #ddd; text-align: right; }}
            th {{ background-color: #34495e; color: white; }}
            .btn {{ display: inline-block; padding: 10px 15px; margin: 5px; color: white; background-color: #3498db; text-decoration: none; border-radius: 5px; border: none; cursor: pointer; }}
            .btn-success {{ background-color: #2ecc71; }}
            .btn-danger {{ background-color: #e74c3c; }}
            .badge {{ padding: 5px 10px; border-radius: 12px; color: white; font-size: 12px; }}
            .bg-pending {{ background-color: #f39c12; }}
            .bg-completed {{ background-color: #2ecc71; }}
            .bg-canceled {{ background-color: #e74c3c; }}
            .search-box {{ width: 100%; padding: 12px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; font-size: 16px; }}
        </style>
    </head>
    <body>
    <div class="container">
        <div style="margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px;">
            <a href="/admin?key={key}" class="btn">🏠 الرئيسية</a>
            <a href="/admin/products?key={key}" class="btn">📦 إدارة الأدوية</a>
            <a href="/admin/orders?key={key}" class="btn" style="background-color: #9b59b6;">🛒 الطلبات</a>
        </div>
    """

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Depends(verify_admin)):
    products = database.load_products()
    orders = database.get_all_orders()
    pending_orders = len([o for o in orders if o.get('status') == 'pending'])
    html_content = get_html_header(key, "الرئيسية")
    html_content += f"""
        <h1>مرحباً بك في لوحة تحكم الصيدلية 🌿</h1>
        <div style="display: flex; gap: 20px; justify-content: center; margin-top: 20px; flex-wrap: wrap;">
            <div style="background: #ecf0f1; padding: 20px; border-radius: 8px; text-align: center; flex: 1; min-width: 200px;">
                <h2>📦 إجمالي المنتجات</h2>
                <p style="font-size: 24px;"><b>{len(products)}</b> منتج</p>
            </div>
            <div style="background: #fcf3cf; padding: 20px; border-radius: 8px; text-align: center; flex: 1; min-width: 200px;">
                <h2>⏳ طلبات قيد الانتظار</h2>
                <p style="font-size: 24px; color: #d35400;"><b>{pending_orders}</b> طلب</p>
            </div>
        </div>
    </div></body></html>
    """
    return html_content

@router.get("/products", response_class=HTMLResponse)
async def manage_products(q: str = "", key: str = Depends(verify_admin)):
    products = database.load_products()
    if q:
        q_norm = matcher.normalize_text(q)
        products = [p for p in products if q_norm in matcher.normalize_text(p.get('name', '')) or q_norm in matcher.normalize_text(p.get('aliases', ''))]

    html_content = get_html_header(key, "إدارة الأدوية")
    html_content += f"""
        <h2>رفع قائمة الأدوية</h2>
        <form action="/admin/upload?key={key}" method="post" enctype="multipart/form-data" style="background: #e8f8f5; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
            <input type="file" name="file" accept=".csv, .xlsx" required style="margin-bottom: 15px;"><br>
            <input type="checkbox" id="replace_all" name="replace_all" value="yes">
            <label for="replace_all" style="color: red; font-weight: bold;">استبدال كامل (حذف القديم)</label><br>
            <input type="checkbox" id="force_confirm" name="force_confirm" value="yes">
            <label for="force_confirm" style="color: darkred; font-weight: bold;">تأكيد إجباري للحذف</label>
            <p style="font-size: 12px; color: gray;">* إذا لم تقم بالتحديد، سيتم التحديث بشكل آمن.</p>
            <button type="submit" class="btn btn-success">رفع وتحديث 🚀</button>
        </form>

        <h2>البحث وقائمة الأدوية</h2>
        <form method="get" action="/admin/products" style="margin-bottom: 20px;">
            <input type="hidden" name="key" value="{key}">
            <input type="text" name="q" value="{html.escape(q)}" class="search-box" placeholder="🔍 ابحث عن منتج...">
        </form>
        
        <table>
            <tr><th>الرقم</th><th>الاسم</th><th>السعر</th><th>الشركة</th><th>التوفر</th><th>إجراء</th></tr>
    """
    for p in products[:250]:
        html_content += f"""
            <tr>
                <td>{p['id']}</td><td>{html.escape(str(p.get('name', '')))}</td><td>{html.escape(str(p.get('price', '')))}</td>
                <td>{html.escape(str(p.get('company', '-')))}</td><td>{html.escape(str(p.get('available', 'متوفر')))}</td>
                <td>
                    <form action="/admin/products/delete/{p['id']}?key={key}" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-danger" onclick="return confirm('تأكيد الحذف؟')">حذف</button>
                    </form>
                </td>
            </tr>
        """
    html_content += "</table></div></body></html>"
    return html_content

# (النقطة 10) دعم كل أعمدة الإكسيل القديمة والجديدة
def map_header(header: str) -> str:
    h = str(header).strip().lower()
    if h in ['name', 'product', 'product_name', 'اسم المنتج', 'المنتج', 'الاسم', 'الصنف', 'canonical_name', 'original_name']: return 'name'
    if h in ['price', 'السعر', 'سعر', 'cost', 'final_price', 'box_price', 'strip_price']: return 'price'
    if h in ['company', 'brand', 'الشركة', 'ماركة', 'الوكيل', 'البراند']: return 'company'
    if h in ['available', 'status', 'الحالة', 'التوفر', 'توفر', 'الكمية', 'qty']: return 'available'
    if h in ['form', 'الشكل الدوائي', 'النوع', 'شكل', 'form_or_type', 'category_guess']: return 'form'
    if h in ['aliases', 'اسماء بديلة', 'اسم بديل', 'image_ocr_keywords', 'ocr_keywords', 'keywords']: return 'aliases'
    if h in ['active_ingredient', 'المادة الفعالة', 'المادة']: return 'active_ingredient'
    if h in ['strength', 'strength_or_size', 'size', 'حجم', 'تركيز']: return 'strength'
    return h

@router.post("/upload")
async def upload_file(file: UploadFile = File(...), replace_all: str = Form(None), force_confirm: str = Form(None), key: str = Depends(verify_admin)):
    database.backup_database()
    content = await file.read()
    filename = file.filename.lower()
    parsed_data = []

    try:
        if filename.endswith(".csv"):
            decoded = content.decode('utf-8-sig')
            reader = csv.reader(io.StringIO(decoded))
            rows = list(reader)
            if len(rows) > 0:
                headers = [map_header(h) for h in rows[0]]
                for row in rows[1:]: parsed_data.append(dict(zip(headers, row)))
                    
        elif filename.endswith(".xlsx"):
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            target_sheet = None
            
            # (النقطة 11) البحث عن صفحة تحتوي على Headers معروفة بدلاً من أكبر صفحة فقط
            for sheet in wb.worksheets:
                first_row = list(sheet.values)[0] if list(sheet.values) else []
                mapped = [map_header(str(h)) for h in first_row if h]
                if 'name' in mapped and ('price' in mapped or 'available' in mapped):
                    target_sheet = sheet
                    break
            
            if not target_sheet: target_sheet = max(wb.worksheets, key=lambda s: s.max_row)
                
            rows = list(target_sheet.values)
            if len(rows) > 0:
                headers = [map_header(h) for h in rows[0]]
                for row in rows[1:]:
                    if any(row): parsed_data.append(dict(zip(headers, row)))
        else:
            raise HTTPException(400, "صيغة الملف غير مدعومة")
            
        current_products_count = len(database.load_products())
        if replace_all == "yes":
            if len(parsed_data) < 100 or len(parsed_data) < (0.7 * current_products_count):
                if force_confirm != "yes":
                    err_msg = f"تحذير: الملف يحتوي على {len(parsed_data)} دواء فقط! الصيدلية بها {current_products_count}. تم رفض المسح."
                    return HTMLResponse(f"<div dir='rtl' style='color:red;text-align:center;margin-top:50px;'><h2>{err_msg}</h2><a href='/admin/products?key={key}'>عودة</a></div>")

        with database.get_db_connection() as conn:
            if replace_all == "yes": conn.execute("DELETE FROM products")
                
            for row in parsed_data:
                name = str(row.get("name", "")).strip()
                if not name or name.lower() == 'none': continue
                
                price = str(row.get("price", "")).strip()
                form = str(row.get("form", "")).strip()
                aliases = str(row.get("aliases", "")).strip()
                active_ingredient = str(row.get("active_ingredient", "")).strip()
                company = str(row.get("company", "")).strip()
                available = str(row.get("available", "متوفر")).strip()
                strength = str(row.get("strength", "")).strip()
                
                norm_name = matcher.normalize_text(name)
                existing = conn.execute("SELECT id FROM products WHERE normalized_name=? OR name=?", (norm_name, name)).fetchone()
                
                if existing:
                    conn.execute("UPDATE products SET price=?, form=?, aliases=?, active_ingredient=?, company=?, available=?, strength=?, normalized_name=? WHERE id=?", 
                                 (price, form, aliases, active_ingredient, company, available, strength, norm_name, existing['id']))
                else:
                    conn.execute("INSERT INTO products (name, price, form, aliases, active_ingredient, company, available, strength, normalized_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                                 (name, price, form, aliases, active_ingredient, company, available, strength, norm_name))
            conn.commit()
            
    except Exception as e:
        return HTMLResponse(f"<div dir='rtl' style='color:red;text-align:center;margin-top:50px;'><h2>خطأ: {str(e)}</h2><a href='/admin/products?key={key}'>عودة</a></div>")
        
    return RedirectResponse(url=f"/admin/products?key={key}", status_code=303)

@router.post("/products/delete/{product_id}")
async def delete_product(product_id: int, key: str = Depends(verify_admin)):
    database.backup_database()
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
    return RedirectResponse(url=f"/admin/products?key={key}", status_code=303)

@router.get("/orders", response_class=HTMLResponse)
async def manage_orders(key: str = Depends(verify_admin)):
    orders = database.get_all_orders()
    html_content = get_html_header(key, "الطلبات والحجوزات")
    html_content += "<h2>سجل طلبات الزبائن</h2><table><tr><th>الرقم</th><th>الزبون</th><th>المنتج</th><th>التاريخ</th><th>الحالة</th><th>تحديث</th></tr>"
    for o in orders:
        status = o.get('status', 'pending')
        badge_class = "bg-pending" if status == "pending" else "bg-completed" if status == "completed" else "bg-canceled"
        status_text = "قيد الانتظار" if status == "pending" else "مكتمل" if status == "completed" else "ملغى"
        
        html_content += f"""
            <tr>
                <td>#{o['id']}</td><td dir="ltr" style="font-weight: bold; color: #2980b9;">{html.escape(str(o.get('phone', '')))}</td>
                <td>{html.escape(str(o.get('product_name', '')))}</td><td dir="ltr" style="font-size: 13px; color: gray;">{o['created_at']}</td>
                <td><span class="badge {badge_class}">{status_text}</span></td>
                <td>
                    <form action="/admin/orders/update/{o['id']}?key={key}" method="post" style="display:flex; gap: 5px;">
                        <select name="new_status" style="padding: 5px; border-radius: 4px;">
                            <option value="pending" {'selected' if status=='pending' else ''}>انتظار</option>
                            <option value="completed" {'selected' if status=='completed' else ''}>مكتمل</option>
                            <option value="canceled" {'selected' if status=='canceled' else ''}>إلغاء</option>
                        </select>
                        <button type="submit" class="btn btn-success" style="padding: 5px 10px; margin: 0;">حفظ</button>
                    </form>
                </td>
            </tr>
        """
    html_content += "</table></div></body></html>"
    return html_content

@router.post("/orders/update/{order_id}")
async def update_order(order_id: int, new_status: str = Form(...), key: str = Depends(verify_admin)):
    database.update_order_status(order_id, new_status)
    return RedirectResponse(url=f"/admin/orders?key={key}", status_code=303)
