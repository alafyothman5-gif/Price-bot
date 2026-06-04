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
ADMIN_KEY = os.getenv("ADMIN_KEY", "PriceBotAdmin2026")

# (النقطة 24) ضبط مسار اللوحة
router = APIRouter(prefix="/admin", tags=["Admin Panel"])

# ==========================================
# الحماية وتوليد الواجهة المشتركة
# ==========================================
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
            #searchInput {{ width: 100%; padding: 12px; margin-bottom: 10px; border: 1px solid #ccc; border-radius: 5px; box-sizing: border-box; font-size: 16px; }}
        </style>
    </head>
    <body>
    <div class="container">
        <div style="margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 10px;">
            <a href="/admin?key={key}" class="btn">🏠 الرئيسية</a>
            <a href="/admin/products?key={key}" class="btn">📦 إدارة الأدوية</a>
            <a href="/admin/orders?key={key}" class="btn" style="background-color: #9b59b6;">🛒 الطلبات والحجوزات</a>
        </div>
    """

# ==========================================
# صفحة الرئيسية
# ==========================================
@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Depends(verify_admin)):
    products = database.load_products()
    orders = database.get_all_orders()
    pending_orders = len([o for o in orders if o.get('status') == 'pending'])
    
    html_content = get_html_header(key, "الرئيسية - PriceBot")
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

# ==========================================
# صفحة إدارة المنتجات ورفع الملفات
# ==========================================
@router.get("/products", response_class=HTMLResponse)
async def manage_products(key: str = Depends(verify_admin)):
    products = database.load_products()
    html_content = get_html_header(key, "إدارة الأدوية")
    html_content += f"""
        <h2>رفع قائمة الأدوية (CSV أو Excel XLSX)</h2>
        <form action="/admin/upload?key={key}" method="post" enctype="multipart/form-data" style="background: #e8f8f5; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
            <label>اختر ملف CSV أو XLSX:</label><br><br>
            <input type="file" name="file" accept=".csv, .xlsx" required style="margin-bottom: 15px;"><br>
            
            <input type="checkbox" id="replace_all" name="replace_all" value="yes">
            <label for="replace_all" style="color: red; font-weight: bold;">استبدال كامل (حذف كل المنتجات القديمة)</label>
            <p style="font-size: 12px; color: gray;">* إذا لم تقم بتحديد المربع، سيتم تحديث الأدوية الموجودة وإضافة الجديدة فقط بشكل آمن.</p>
            
            <button type="submit" class="btn btn-success">رفع وتحديث 🚀</button>
        </form>

        <h2>قائمة الأدوية المتوفرة</h2>
        <input type="text" id="searchInput" onkeyup="searchTable()" placeholder="🔍 ابحث عن منتج بالاسم...">
        
        <table id="productsTable">
            <tr><th>الرقم</th><th>الاسم</th><th>السعر</th><th>الشركة</th><th>إجراء</th></tr>
    """
    
    # عرض أول 250 منتج لتخفيف الحمل على المتصفح
    for p in products[:250]: 
        # (النقطة 27) حماية XSS
        safe_name = html.escape(str(p.get('name', '')))
        safe_price = html.escape(str(p.get('price', '')))
        safe_company = html.escape(str(p.get('company', '-')))
        
        html_content += f"""
            <tr>
                <td>{p['id']}</td><td>{safe_name}</td><td>{safe_price}</td><td>{safe_company}</td>
                <td>
                    <form action="/admin/products/delete/{p['id']}?key={key}" method="post" style="display:inline;">
                        <button type="submit" class="btn btn-danger" onclick="return confirm('تأكيد الحذف؟ سيتم أخذ نسخة احتياطية أولاً.')">حذف</button>
                    </form>
                </td>
            </tr>
        """
        
    html_content += """
        </table>
        <p style='text-align:center; color:gray; font-size:12px; margin-top:10px;'>يتم عرض أحدث 250 منتج لتسريع اللوحة. يمكنك البحث ضمنها.</p>
        
        <script>
        function searchTable() {
            var input, filter, table, tr, td, i, txtValue;
            input = document.getElementById("searchInput");
            filter = input.value.toUpperCase();
            table = document.getElementById("productsTable");
            tr = table.getElementsByTagName("tr");
            for (i = 1; i < tr.length; i++) {
                td = tr[i].getElementsByTagName("td")[1]; // البحث يتم في عمود الاسم
                if (td) {
                    txtValue = td.textContent || td.innerText;
                    if (txtValue.toUpperCase().indexOf(filter) > -1) {
                        tr[i].style.display = "";
                    } else {
                        tr[i].style.display = "none";
                    }
                }       
            }
        }
        </script>
    </div></body></html>
    """
    return html_content

# (النقطة 21) التعرف الذكي على أسماء الأعمدة في الإكسيل
def map_header(header: str) -> str:
    h = str(header).strip().lower()
    if h in ['name', 'product', 'product_name', 'اسم المنتج', 'المنتج', 'الاسم', 'الصنف']: return 'name'
    if h in ['price', 'السعر', 'سعر', 'cost']: return 'price'
    if h in ['company', 'brand', 'الشركة', 'ماركة', 'الوكيل', 'البراند']: return 'company'
    if h in ['available', 'status', 'الحالة', 'التوفر', 'توفر', 'الكمية', 'qty']: return 'available'
    if h in ['form', 'الشكل الدوائي', 'النوع', 'شكل']: return 'form'
    if h in ['aliases', 'اسماء بديلة', 'اسم بديل']: return 'aliases'
    if h in ['active_ingredient', 'المادة الفعالة', 'المادة']: return 'active_ingredient'
    return h

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...), 
    replace_all: str = Form(None),
    key: str = Depends(verify_admin)
):
    # أخذ نسخة احتياطية قبل الرفع
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
                for row in rows[1:]:
                    parsed_data.append(dict(zip(headers, row)))
                    
        elif filename.endswith(".xlsx"):
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            sheet = wb.active
            rows = list(sheet.values)
            if len(rows) > 0:
                headers = [map_header(h) for h in rows[0]]
                for row in rows[1:]:
                    parsed_data.append(dict(zip(headers, row)))
        else:
            raise HTTPException(400, "صيغة الملف غير مدعومة. يرجى رفع CSV أو XLSX")
            
        with database.get_db_connection() as conn:
            if replace_all == "yes":
                conn.execute("DELETE FROM products")
                
            for row in parsed_data:
                name = str(row.get("name", "")).strip()
                if not name or name.lower() == 'none': continue
                
                price = str(row.get("price", "")).strip()
                form = str(row.get("form", "")).strip()
                aliases = str(row.get("aliases", "")).strip()
                active_ingredient = str(row.get("active_ingredient", "")).strip()
                company = str(row.get("company", "")).strip()
                available = str(row.get("available", "متوفر")).strip()
                
                # (النقطة 22) إنشاء اسم مفلتر لمنع التكرار
                norm_name = matcher.normalize_text(name)
                
                existing = conn.execute("SELECT id FROM products WHERE normalized_name=? OR name=?", (norm_name, name)).fetchone()
                
                if existing:
                    conn.execute("""
                        UPDATE products 
                        SET price=?, form=?, aliases=?, active_ingredient=?, company=?, available=?, normalized_name=? 
                        WHERE id=?
                    """, (price, form, aliases, active_ingredient, company, available, norm_name, existing['id']))
                else:
                    conn.execute("""
                        INSERT INTO products (name, price, form, aliases, active_ingredient, company, available, normalized_name) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (name, price, form, aliases, active_ingredient, company, available, norm_name))
            conn.commit()
            
    except Exception as e:
        raise HTTPException(500, f"حدث خطأ أثناء معالجة الملف: {str(e)}")
        
    return RedirectResponse(url=f"/admin/products?key={key}", status_code=303)

@router.post("/products/delete/{product_id}")
async def delete_product(product_id: int, key: str = Depends(verify_admin)):
    # (النقطة 25) نسخة احتياطية فورية قبل الحذف الفردي
    database.backup_database()
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
    return RedirectResponse(url=f"/admin/products?key={key}", status_code=303)

# ==========================================
# صفحة إدارة الطلبات والحجوزات
# ==========================================
@router.get("/orders", response_class=HTMLResponse)
async def manage_orders(key: str = Depends(verify_admin)):
    orders = database.get_all_orders()
    html_content = get_html_header(key, "الطلبات والحجوزات")
    html_content += """
        <h2>سجل طلبات وحجوزات الزبائن</h2>
        <table>
            <tr><th>رقم الطلب</th><th>رقم الزبون</th><th>المنتج المطلوب</th><th>التاريخ</th><th>الحالة</th><th>تحديث</th></tr>
    """
    for o in orders:
        status = o.get('status', 'pending')
        badge_class = "bg-pending" if status == "pending" else "bg-completed" if status == "completed" else "bg-canceled"
        status_text = "قيد الانتظار" if status == "pending" else "مكتمل" if status == "completed" else "ملغى"
        
        safe_phone = html.escape(str(o.get('phone', '')))
        safe_product = html.escape(str(o.get('product_name', '')))
        
        html_content += f"""
            <tr>
                <td>#{o['id']}</td>
                <td dir="ltr" style="font-weight: bold; color: #2980b9;">{safe_phone}</td>
                <td>{safe_product}</td>
                <td dir="ltr" style="font-size: 13px; color: gray;">{o['created_at']}</td>
                <td><span class="badge {badge_class}">{status_text}</span></td>
                <td>
                    <form action="/admin/orders/update/{o['id']}?key={key}" method="post" style="display:flex; gap: 5px;">
                        <select name="new_status" style="padding: 5px; border-radius: 4px;">
                            <option value="pending" {'selected' if status=='pending' else ''}>قيد الانتظار</option>
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
