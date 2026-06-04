import csv
import html
import io
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from urllib.parse import quote

import openpyxl
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

import database
import matcher


load_dotenv()

ADMIN_KEY = os.getenv("PRICEBOT_ADMIN_KEY") or os.getenv("ADMIN_KEY")
router = APIRouter(prefix="/admin", tags=["Admin Panel"])


# =============================
# Admin auth + utilities
# =============================

def admin_key_configured() -> bool:
    return bool(ADMIN_KEY)


def verify_admin(key: str = Query(None)):
    if not ADMIN_KEY:
        raise HTTPException(status_code=503, detail="Admin key is not configured. Set PRICEBOT_ADMIN_KEY or ADMIN_KEY.")
    if key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="غير مصرح بالدخول.")
    return key


def h(value) -> str:
    return html.escape(str(value or ""), quote=True)


def admin_path(path: str, key: str, **params) -> str:
    query = {"key": key, **params}
    pairs = [f"{quote(str(k))}={quote(str(v))}" for k, v in query.items() if v is not None]
    return f"{path}?{'&'.join(pairs)}"


def parse_float(value) -> float:
    text = str(value or "").replace("د.ل", " ").replace("دينار", " ")
    text = text.replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except Exception:
        return 0.0


def parse_dt(value):
    if not value:
        return None
    text = str(value)[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            pass
    return None


def order_product_name(order: dict) -> str:
    return str(order.get("product_name") or order.get("product") or order.get("message") or "").strip()


def order_price(order: dict) -> float:
    return parse_float(order.get("price"))


def order_created_at(order: dict):
    return parse_dt(order.get("created_at") or order.get("time"))


def safe_status(order: dict) -> str:
    return str(order.get("status") or "pending").lower().strip()


def get_db_tables() -> List[str]:
    try:
        with database.get_db_connection() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return [row[0] for row in rows]
    except Exception:
        return []


def get_top_queries(limit: int = 10) -> List[Tuple[str, int]]:
    try:
        tables = get_db_tables()
        if "product_inquiries" not in tables:
            return []
        with database.get_db_connection() as conn:
            cols = [row[1] for row in conn.execute('PRAGMA table_info("product_inquiries")').fetchall()]
            query_col = "query" if "query" in cols else "raw_query" if "raw_query" in cols else "normalized_query" if "normalized_query" in cols else ""
            if not query_col:
                return []
            rows = conn.execute(f'SELECT "{query_col}" AS q FROM product_inquiries').fetchall()
            counter = Counter(str(row["q"] or "").strip() for row in rows if str(row["q"] or "").strip())
            return counter.most_common(limit)
    except Exception as exc:
        print(f"ADMIN_TOP_QUERIES_ERROR: {exc}")
        return []


def products_health(products: List[dict]) -> dict:
    total = len(products)
    available = 0
    unavailable = 0
    missing_price = 0
    missing_brand = 0
    missing_aliases = 0
    missing_form = 0
    brands = Counter()
    forms = Counter()
    norm_names = Counter()

    for product in products:
        if matcher.is_available(product.get("available", "متوفر")):
            available += 1
        else:
            unavailable += 1
        if not str(product.get("price") or "").strip():
            missing_price += 1
        brand = str(product.get("brand") or product.get("company") or "").strip()
        if not brand:
            missing_brand += 1
        else:
            brands[brand] += 1
        if not str(product.get("aliases") or "").strip() and not str(product.get("image_ocr_keywords") or "").strip():
            missing_aliases += 1
        form = str(product.get("form") or product.get("category") or product.get("category_guess") or "").strip()
        if not form:
            missing_form += 1
        else:
            forms[form] += 1
        norm = matcher.normalize_text(product.get("name", ""))
        if norm:
            norm_names[norm] += 1

    duplicates = sum(count - 1 for count in norm_names.values() if count > 1)
    return {
        "total": total,
        "available": available,
        "unavailable": unavailable,
        "missing_price": missing_price,
        "missing_brand": missing_brand,
        "missing_aliases": missing_aliases,
        "missing_form": missing_form,
        "duplicates": duplicates,
        "top_brands": brands.most_common(8),
        "top_forms": forms.most_common(8),
    }


def order_stats(orders: List[dict]) -> dict:
    now = datetime.now()
    today = now.date()
    last_7_start = now - timedelta(days=7)
    last_30_start = now - timedelta(days=30)

    total = len(orders)
    pending = sum(1 for order in orders if safe_status(order) == "pending")
    completed = sum(1 for order in orders if safe_status(order) == "completed")
    canceled = sum(1 for order in orders if safe_status(order) == "canceled")
    unknown = total - pending - completed - canceled

    today_count = 0
    week_count = 0
    month_count = 0
    daily_counter = Counter()
    product_counter = Counter()
    product_revenue = defaultdict(float)
    phone_counter = Counter()
    status_revenue = defaultdict(float)

    for order in orders:
        product_name = order_product_name(order) or "غير محدد"
        product_counter[product_name] += 1
        product_revenue[product_name] += order_price(order)
        phone = str(order.get("phone") or "").strip() or "غير معروف"
        phone_counter[phone] += 1
        status_revenue[safe_status(order)] += order_price(order)

        dt = order_created_at(order)
        if dt:
            if dt.date() == today:
                today_count += 1
            if dt >= last_7_start:
                week_count += 1
            if dt >= last_30_start:
                month_count += 1
            daily_counter[dt.date().isoformat()] += 1

    last_7_days = []
    for i in range(6, -1, -1):
        day = (today - timedelta(days=i)).isoformat()
        last_7_days.append((day, daily_counter.get(day, 0)))

    completion_rate = round((completed / total) * 100, 1) if total else 0.0
    cancel_rate = round((canceled / total) * 100, 1) if total else 0.0
    total_revenue = sum(order_price(order) for order in orders)

    top_products = []
    for name, count in product_counter.most_common(10):
        top_products.append((name, count, product_revenue.get(name, 0.0)))

    return {
        "total": total,
        "pending": pending,
        "completed": completed,
        "canceled": canceled,
        "unknown": unknown,
        "today": today_count,
        "week": week_count,
        "month": month_count,
        "completion_rate": completion_rate,
        "cancel_rate": cancel_rate,
        "total_revenue": total_revenue,
        "pending_revenue": status_revenue.get("pending", 0.0),
        "completed_revenue": status_revenue.get("completed", 0.0),
        "top_products": top_products,
        "top_customers": phone_counter.most_common(8),
        "last_7_days": last_7_days,
    }


def metric_card(title: str, value: str, hint: str = "", tone: str = "blue") -> str:
    return f'''
    <div class="metric metric-{tone}">
        <div class="metric-title">{h(title)}</div>
        <div class="metric-value">{h(value)}</div>
        <div class="metric-hint">{h(hint)}</div>
    </div>
    '''


def progress_bar(label: str, value: int, max_value: int) -> str:
    pct = 0 if max_value <= 0 else min(100, round((value / max_value) * 100))
    return f'''
    <div class="bar-row">
        <div class="bar-label">{h(label)}</div>
        <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
        <div class="bar-value">{h(value)}</div>
    </div>
    '''


def get_html_header(key: str, title: str = "لوحة الصيدلية") -> str:
    safe_title = h(title)
    return f"""
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{safe_title}</title>
    <style>
        :root {{
            --bg:#f3f6fb; --card:#ffffff; --ink:#172033; --muted:#637083; --line:#e1e7ef;
            --blue:#2563eb; --green:#16a34a; --orange:#f59e0b; --red:#dc2626; --purple:#7c3aed;
        }}
        * {{ box-sizing:border-box; }}
        body {{ font-family: Tahoma, Arial, sans-serif; background:var(--bg); margin:0; color:var(--ink); }}
        .layout {{ max-width:1280px; margin:auto; padding:18px; }}
        .topbar {{ background:linear-gradient(135deg,#0f172a,#1e3a8a); color:#fff; border-radius:20px; padding:18px; box-shadow:0 12px 28px rgba(15,23,42,.18); }}
        .topbar h1 {{ margin:0 0 6px; font-size:24px; }}
        .topbar p {{ margin:0; opacity:.85; }}
        .nav {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; }}
        .nav a {{ color:#fff; text-decoration:none; padding:9px 12px; border-radius:999px; background:rgba(255,255,255,.13); }}
        .nav a:hover {{ background:rgba(255,255,255,.22); }}
        .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-top:16px; }}
        .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:16px; }}
        .card {{ background:var(--card); border:1px solid var(--line); border-radius:18px; padding:16px; box-shadow:0 8px 22px rgba(17,24,39,.06); }}
        .card h2 {{ margin:0 0 12px; font-size:18px; }}
        .metric {{ background:#fff; border:1px solid var(--line); border-radius:18px; padding:16px; min-height:120px; box-shadow:0 8px 22px rgba(17,24,39,.06); position:relative; overflow:hidden; }}
        .metric:before {{ content:""; position:absolute; inset:0 auto 0 0; width:6px; background:var(--blue); }}
        .metric-green:before {{ background:var(--green); }} .metric-orange:before {{ background:var(--orange); }} .metric-red:before {{ background:var(--red); }} .metric-purple:before {{ background:var(--purple); }}
        .metric-title {{ color:var(--muted); font-size:13px; }}
        .metric-value {{ font-size:30px; font-weight:800; margin:8px 0 4px; }}
        .metric-hint {{ color:var(--muted); font-size:12px; line-height:1.6; }}
        table {{ width:100%; border-collapse:collapse; margin-top:10px; overflow:hidden; border-radius:12px; }}
        th, td {{ padding:10px; border-bottom:1px solid var(--line); text-align:right; vertical-align:top; }}
        th {{ color:#475569; background:#f8fafc; font-size:12px; }}
        tr:hover td {{ background:#fbfdff; }}
        input, select {{ font:inherit; }}
        .btn {{ display:inline-block; padding:9px 13px; margin:4px 0; color:#fff; background:var(--blue); text-decoration:none; border-radius:10px; border:0; cursor:pointer; }}
        .btn-success {{ background:var(--green); }} .btn-danger {{ background:var(--red); }} .btn-muted {{ background:#64748b; }}
        .box {{ background:#f8fafc; padding:14px; border:1px solid var(--line); border-radius:14px; margin:14px 0; }}
        .danger-box {{ background:#fff1f2; border-color:#fecdd3; }}
        .search-box {{ width:100%; padding:11px; border:1px solid #ccd6dd; border-radius:12px; }}
        .badge {{ padding:4px 9px; border-radius:12px; color:#fff; font-size:12px; white-space:nowrap; }}
        .bg-pending {{ background:var(--orange); }} .bg-completed {{ background:var(--green); }} .bg-canceled {{ background:var(--red); }}
        .muted {{ color:var(--muted); font-size:13px; }}
        .bar-row {{ display:grid; grid-template-columns:130px 1fr 50px; align-items:center; gap:10px; margin:10px 0; }}
        .bar-label {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#334155; }}
        .bar-track {{ height:10px; background:#e5e7eb; border-radius:999px; overflow:hidden; }}
        .bar-fill {{ height:100%; background:linear-gradient(90deg,#2563eb,#06b6d4); border-radius:999px; }}
        .bar-value {{ text-align:left; color:#334155; font-weight:700; }}
        .pill {{ display:inline-block; background:#eef2ff; color:#3730a3; padding:4px 8px; border-radius:999px; font-size:12px; margin:2px; }}
        .pagination a {{ color:var(--blue); margin:0 4px; text-decoration:none; }}
        @media(max-width:900px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .grid-2 {{ grid-template-columns:1fr; }} }}
        @media(max-width:560px) {{ .layout {{ padding:10px; }} .grid {{ grid-template-columns:1fr; }} .bar-row {{ grid-template-columns:90px 1fr 34px; }} table {{ font-size:12px; }} th,td {{ padding:7px; }} }}
    </style>
</head>
<body>
<div class="layout">
    <div class="topbar">
        <h1>{safe_title}</h1>
        <p>PriceBot — صيدلية بدر البشرية / أجدابيا</p>
        <div class="nav">
            <a href="{admin_path('/admin', key)}">الرئيسية</a>
            <a href="{admin_path('/admin/analytics', key)}">الإحصائيات</a>
            <a href="{admin_path('/admin/products', key)}">المنتجات</a>
            <a href="{admin_path('/admin/orders', key)}">الطلبات</a>
        </div>
    </div>
"""


def html_footer() -> str:
    return "</div></body></html>"


# =============================
# Dashboard + analytics
# =============================

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Depends(verify_admin)):
    products = database.load_products()
    orders = database.get_all_orders()
    ostats = order_stats(orders)
    pstats = products_health(products)

    content = get_html_header(key, "لوحة التحكم")
    content += '<div class="grid">'
    content += metric_card("طلبات اليوم", str(ostats["today"]), "عدد الطلبات المسجلة اليوم", "blue")
    content += metric_card("طلبات آخر 7 أيام", str(ostats["week"]), "مؤشر نشاط الصيدلية خلال الأسبوع", "green")
    content += metric_card("طلبات قيد الانتظار", str(ostats["pending"]), "تحتاج تأكيد أو متابعة", "orange")
    content += metric_card("إجمالي المنتجات", str(pstats["total"]), f"متوفر: {pstats['available']} / غير متوفر: {pstats['unavailable']}", "purple")
    content += '</div>'

    content += '<div class="grid">'
    content += metric_card("معدل إكمال الطلبات", f"{ostats['completion_rate']}%", f"ملغاة: {ostats['cancel_rate']}%", "green")
    content += metric_card("قيمة الطلبات التقريبية", f"{ostats['total_revenue']:.2f} د.ل", "محسوبة من الأسعار المخزنة في الطلبات", "blue")
    content += metric_card("منتجات بلا سعر", str(pstats["missing_price"]), "يفضل إكمالها لتحسين الردود", "red" if pstats["missing_price"] else "green")
    content += metric_card("منتجات بلا aliases/OCR", str(pstats["missing_aliases"]), "تؤثر على فهم الصور والأسماء", "orange")
    content += '</div>'

    max_day = max([v for _, v in ostats["last_7_days"]] or [1])
    content += '<div class="grid-2">'
    content += '<div class="card"><h2>نشاط آخر 7 أيام</h2>'
    for day, count in ostats["last_7_days"]:
        content += progress_bar(day, count, max_day)
    content += '</div>'

    content += '<div class="card"><h2>أكثر المنتجات طلباً</h2>'
    if ostats["top_products"]:
        content += '<table><tr><th>المنتج</th><th>الطلبات</th><th>قيمة تقريبية</th></tr>'
        for name, count, revenue in ostats["top_products"][:7]:
            content += f'<tr><td>{h(name)}</td><td>{h(count)}</td><td>{revenue:.2f} د.ل</td></tr>'
        content += '</table>'
    else:
        content += '<p class="muted">لا توجد طلبات بعد.</p>'
    content += '</div></div>'

    content += '<div class="grid-2">'
    content += '<div class="card"><h2>صحة ملف المنتجات</h2>'
    content += f'<span class="pill">بلا brand: {pstats["missing_brand"]}</span>'
    content += f'<span class="pill">بلا form: {pstats["missing_form"]}</span>'
    content += f'<span class="pill">تكرار أسماء محتمل: {pstats["duplicates"]}</span>'
    content += '<h2 style="margin-top:18px;">أكثر البراندات</h2>'
    max_brand = max([c for _, c in pstats["top_brands"]] or [1])
    for brand, count in pstats["top_brands"]:
        content += progress_bar(brand, count, max_brand)
    content += '</div>'

    content += '<div class="card"><h2>آخر الطلبات</h2>'
    recent = orders[:8]
    if recent:
        content += '<table><tr><th>الزبون</th><th>المنتج</th><th>الحالة</th></tr>'
        for order in recent:
            status = safe_status(order)
            badge_class = "bg-pending" if status == "pending" else "bg-completed" if status == "completed" else "bg-canceled"
            content += f'<tr><td dir="ltr">{h(order.get("phone"))}</td><td>{h(order_product_name(order))}</td><td><span class="badge {badge_class}">{h(status)}</span></td></tr>'
        content += '</table>'
    else:
        content += '<p class="muted">لا توجد طلبات بعد.</p>'
    content += '</div></div>'

    return content + html_footer()


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(key: str = Depends(verify_admin)):
    products = database.load_products()
    orders = database.get_all_orders()
    ostats = order_stats(orders)
    pstats = products_health(products)
    top_queries = get_top_queries(12)

    content = get_html_header(key, "الإحصائيات المتقدمة")
    content += '<div class="grid">'
    content += metric_card("كل الطلبات", str(ostats["total"]), f"آخر 30 يوم: {ostats['month']}", "blue")
    content += metric_card("مكتملة", str(ostats["completed"]), f"قيمة مكتملة: {ostats['completed_revenue']:.2f} د.ل", "green")
    content += metric_card("قيد الانتظار", str(ostats["pending"]), f"قيمة معلقة: {ostats['pending_revenue']:.2f} د.ل", "orange")
    content += metric_card("ملغاة", str(ostats["canceled"]), f"معدل الإلغاء: {ostats['cancel_rate']}%", "red")
    content += '</div>'

    content += '<div class="grid-2">'
    content += '<div class="card"><h2>Top Requested Products</h2><table><tr><th>المنتج</th><th>عدد الطلبات</th><th>القيمة</th></tr>'
    for name, count, revenue in ostats["top_products"]:
        content += f'<tr><td>{h(name)}</td><td>{h(count)}</td><td>{revenue:.2f} د.ل</td></tr>'
    if not ostats["top_products"]:
        content += '<tr><td colspan="3" class="muted">لا توجد بيانات.</td></tr>'
    content += '</table></div>'

    content += '<div class="card"><h2>أكثر الزبائن طلباً</h2><table><tr><th>الرقم</th><th>عدد الطلبات</th></tr>'
    for phone, count in ostats["top_customers"]:
        content += f'<tr><td dir="ltr">{h(phone)}</td><td>{h(count)}</td></tr>'
    if not ostats["top_customers"]:
        content += '<tr><td colspan="2" class="muted">لا توجد بيانات.</td></tr>'
    content += '</table></div></div>'

    content += '<div class="grid-2">'
    content += '<div class="card"><h2>أكثر عبارات البحث</h2><table><tr><th>العبارة</th><th>العدد</th></tr>'
    for q, count in top_queries:
        content += f'<tr><td>{h(q)}</td><td>{h(count)}</td></tr>'
    if not top_queries:
        content += '<tr><td colspan="2" class="muted">جدول product_inquiries غير متوفر أو لا يحتوي بيانات كافية.</td></tr>'
    content += '</table></div>'

    content += '<div class="card"><h2>تصنيفات المنتجات الأكثر وجوداً</h2>'
    max_form = max([c for _, c in pstats["top_forms"]] or [1])
    for form, count in pstats["top_forms"]:
        content += progress_bar(form, count, max_form)
    content += '</div></div>'

    return content + html_footer()


# =============================
# Products
# =============================

def product_matches(product: dict, query: str) -> bool:
    if not query:
        return True
    q_norm = matcher.normalize_text(query)
    identity = matcher.get_product_identity(product)
    return q_norm in identity


@router.get("/products", response_class=HTMLResponse)
async def manage_products(q: str = "", page: int = 1, key: str = Depends(verify_admin)):
    all_products = database.load_products()
    filtered = [product for product in all_products if product_matches(product, q)]
    per_page = 100
    page = max(page, 1)
    total_pages = max((len(filtered) + per_page - 1) // per_page, 1)
    page = min(page, total_pages)
    start = (page - 1) * per_page
    page_products = filtered[start : start + per_page]

    content = get_html_header(key, "إدارة المنتجات")
    content += f"""
    <div class="card">
    <h2>رفع Excel/CSV</h2>
    <form action="{admin_path('/admin/upload', key)}" method="post" enctype="multipart/form-data" class="box">
        <input type="file" name="file" accept=".csv,.xlsx" required><br><br>
        <label><input type="checkbox" name="replace_all" value="yes"> استبدال كامل بعد التحقق</label><br>
        <label style="color:#b42318; font-weight:bold;"><input type="checkbox" name="force_confirm" value="yes"> تأكيد صريح للاستبدال الكامل</label>
        <p class="muted">بدون الاستبدال الكامل سيتم تحديث المنتجات وإضافة الجديد فقط. لا يتم حذف القديم في safe upsert.</p>
        <button type="submit" class="btn btn-success">رفع وتحديث</button>
    </form>
    </div>

    <div class="card" style="margin-top:16px;">
    <h2>بحث المنتجات</h2>
    <form method="get" action="/admin/products" style="margin-bottom:12px;">
        <input type="hidden" name="key" value="{h(key)}">
        <input type="text" name="q" value="{h(q)}" class="search-box" placeholder="ابحث في كل المنتجات...">
    </form>
    <p class="muted">النتائج: {len(filtered)} من {len(all_products)} منتج. الصفحة {page} من {total_pages}.</p>
    <table>
        <tr><th>الرقم</th><th>الاسم</th><th>السعر</th><th>الشركة/البراند</th><th>الشكل</th><th>التوفر</th><th>إجراء</th></tr>
"""
    for product in page_products:
        brand_company = product.get("brand") or product.get("company") or "-"
        content += f"""
        <tr>
            <td>{h(product.get('id'))}</td>
            <td>{h(product.get('name'))}</td>
            <td>{h(product.get('price'))}</td>
            <td>{h(brand_company)}</td>
            <td>{h(product.get('form'))}</td>
            <td>{h(product.get('available') or 'متوفر')}</td>
            <td>
                <form action="{admin_path(f'/admin/products/delete/{product.get("id")}', key)}" method="post" style="display:inline;">
                    <button type="submit" class="btn btn-danger" onclick="return confirm('تأكيد حذف المنتج؟')">حذف</button>
                </form>
            </td>
        </tr>
"""
    content += "</table>"

    if total_pages > 1:
        content += '<div class="pagination" style="margin-top:14px;">'
        if page > 1:
            content += f'<a href="{admin_path("/admin/products", key, q=q, page=page-1)}">السابق</a>'
        if page < total_pages:
            content += f'<a href="{admin_path("/admin/products", key, q=q, page=page+1)}">التالي</a>'
        content += "</div>"

    content += "</div>"
    return content + html_footer()


# =============================
# Upload parsing
# =============================

HEADER_ALIASES = {
    "name": {"name", "product", "product_name", "product name", "اسم المنتج", "المنتج", "الاسم", "الصنف", "canonical_name", "original_name"},
    "price": {"price", "السعر", "سعر", "final_price", "box_price", "strip_price", "cost"},
    "company": {"company", "الشركة", "المصنع", "الوكيل"},
    "brand": {"brand", "الماركة", "البراند"},
    "aliases": {"aliases", "اسماء بديلة", "اسم بديل"},
    "image_ocr_keywords": {"image_ocr_keywords", "ocr_keywords", "keywords", "كلمات", "كلمات البحث"},
    "form": {"form", "type", "category", "form_or_type", "category_guess", "الشكل الدوائي", "النوع", "شكل"},
    "available": {"available", "status", "الحالة", "التوفر", "توفر", "الكمية", "qty"},
    "active_ingredient": {"active_ingredient", "المادة الفعالة", "المادة"},
    "strength": {"strength", "size", "strength_or_size", "حجم", "تركيز"},
    "pack": {"pack", "package", "عبوة", "العبوة"},
}


def map_header(header) -> str:
    raw = str(header or "").strip()
    norm = matcher.normalize_text(raw).replace("_", " ")
    low = raw.strip().lower()
    for canonical, aliases in HEADER_ALIASES.items():
        normalized_aliases = {matcher.normalize_text(alias).replace("_", " ") for alias in aliases}
        lowered_aliases = {alias.lower() for alias in aliases}
        if norm in normalized_aliases or low in lowered_aliases:
            return canonical
    return low.replace(" ", "_")


def unique_headers(headers: List[str]) -> List[str]:
    seen: Dict[str, int] = {}
    result = []
    for header in headers:
        mapped = map_header(header)
        if mapped in seen:
            seen[mapped] += 1
            mapped = f"{mapped}__{seen[mapped]}"
        else:
            seen[mapped] = 0
        result.append(mapped)
    return result


def collect(row: dict, key: str) -> str:
    values = []
    for row_key, value in row.items():
        if row_key == key or str(row_key).startswith(f"{key}__"):
            text = "" if value is None else str(value).strip()
            if text and text.lower() != "none":
                values.append(text)
    return " | ".join(values)


def product_from_row(row: dict) -> dict:
    name = collect(row, "name")
    if not name:
        return {}
    company = collect(row, "company")
    brand = collect(row, "brand") or company
    aliases = collect(row, "aliases")
    image_keywords = collect(row, "image_ocr_keywords")
    return {
        "name": name,
        "price": collect(row, "price"),
        "company": company,
        "brand": brand,
        "aliases": aliases,
        "image_ocr_keywords": image_keywords,
        "form": collect(row, "form"),
        "available": collect(row, "available") or "متوفر",
        "active_ingredient": collect(row, "active_ingredient"),
        "strength": collect(row, "strength"),
        "pack": collect(row, "pack"),
    }


def parse_csv(content: bytes) -> Tuple[List[dict], List[str]]:
    text = content.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise ValueError("الملف فارغ.")
    headers = unique_headers([str(cell or "") for cell in rows[0]])
    parsed = [dict(zip(headers, row)) for row in rows[1:] if any(str(cell or "").strip() for cell in row)]
    return parsed, headers


def find_xlsx_table(content: bytes) -> Tuple[List[dict], List[str]]:
    workbook = openpyxl.load_workbook(io.BytesIO(content), data_only=True, read_only=True)
    best_rows = []

    for sheet in workbook.worksheets:
        rows = list(sheet.iter_rows(values_only=True))
        for idx, row in enumerate(rows[:20]):
            headers = unique_headers([str(cell or "") for cell in row])
            if "name" in headers:
                parsed = [dict(zip(headers, values)) for values in rows[idx + 1 :] if any(str(cell or "").strip() for cell in values)]
                return parsed, headers
        if len(rows) > len(best_rows):
            best_rows = rows

    if best_rows:
        best_headers = unique_headers([str(cell or "") for cell in best_rows[0]])
        parsed = [dict(zip(best_headers, values)) for values in best_rows[1:] if any(str(cell or "").strip() for cell in values)]
        return parsed, best_headers
    raise ValueError("ملف Excel فارغ.")


def parse_upload(content: bytes, filename: str) -> Tuple[List[dict], List[str]]:
    lower_name = (filename or "").lower()
    if lower_name.endswith(".csv"):
        rows, headers = parse_csv(content)
    elif lower_name.endswith(".xlsx"):
        rows, headers = find_xlsx_table(content)
    else:
        raise ValueError("صيغة الملف غير مدعومة. استخدم CSV أو XLSX.")

    if "name" not in headers:
        raise ValueError("لم يتم العثور على عمود اسم المنتج.")

    products = []
    for row in rows:
        product = product_from_row(row)
        if product:
            products.append(product)
    if not products:
        raise ValueError("لم يتم العثور على منتجات صالحة داخل الملف.")
    return products, headers


def upsert_products(products: List[dict], replace_all: bool) -> int:
    with database.get_db_connection() as conn:
        if replace_all:
            conn.execute("DELETE FROM products")

        changed = 0
        for product in products:
            name = product["name"].strip()
            normalized_name = matcher.normalize_text(name)
            existing = conn.execute("SELECT id FROM products WHERE normalized_name=? OR name=? LIMIT 1", (normalized_name, name)).fetchone()
            values = (
                name,
                product.get("price", ""),
                product.get("form", ""),
                product.get("aliases", ""),
                product.get("image_ocr_keywords", ""),
                product.get("active_ingredient", ""),
                product.get("company", ""),
                product.get("brand", ""),
                product.get("available", "متوفر"),
                product.get("strength", ""),
                product.get("pack", ""),
                normalized_name,
            )
            if existing:
                conn.execute(
                    """
                    UPDATE products
                    SET name=?, price=?, form=?, aliases=?, image_ocr_keywords=?, active_ingredient=?,
                        company=?, brand=?, available=?, strength=?, pack=?, normalized_name=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    values + (existing["id"],),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO products
                    (name, price, form, aliases, image_ocr_keywords, active_ingredient, company, brand, available, strength, pack, normalized_name, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    values,
                )
            changed += 1
        conn.commit()
        matcher.invalidate_product_cache()
        return changed


def render_upload_error(key: str, message: str) -> HTMLResponse:
    content = get_html_header(key, "خطأ في الرفع")
    content += f'<div class="card danger-box"><h2>تعذر الرفع</h2><p>{h(message)}</p><a class="btn" href="{admin_path("/admin/products", key)}">عودة</a></div>'
    return HTMLResponse(content + html_footer(), status_code=400)


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    replace_all: str = Form(None),
    force_confirm: str = Form(None),
    key: str = Depends(verify_admin),
):
    try:
        content = await file.read()
        products, headers = parse_upload(content, file.filename or "")
        current_count = len(database.load_products())
        do_replace = replace_all == "yes"

        if do_replace:
            if force_confirm != "yes":
                return render_upload_error(key, "الاستبدال الكامل يحتاج تحديد خانة التأكيد الصريح.")
            if current_count >= 100 and len(products) < max(100, int(current_count * 0.5)):
                return render_upload_error(
                    key,
                    f"عدد المنتجات في الملف ({len(products)}) أقل بكثير من الموجود حالياً ({current_count}). تم رفض الاستبدال لحماية البيانات.",
                )

        database.backup_database()
        changed = upsert_products(products, do_replace)
        print(f"PRODUCT_UPLOAD_OK: changed={changed} replace_all={do_replace} headers={headers}")
    except Exception as exc:
        print(f"PRODUCT_UPLOAD_ERROR: {exc}")
        return render_upload_error(key, str(exc))

    return RedirectResponse(url=admin_path("/admin/products", key), status_code=303)


@router.post("/products/delete/{product_id}")
async def delete_product(product_id: int, key: str = Depends(verify_admin)):
    database.backup_database()
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products WHERE id=?", (product_id,))
        conn.commit()
    matcher.invalidate_product_cache()
    return RedirectResponse(url=admin_path("/admin/products", key), status_code=303)


# =============================
# Orders
# =============================

@router.get("/orders", response_class=HTMLResponse)
async def manage_orders(status: str = "", key: str = Depends(verify_admin)):
    orders = database.get_all_orders()
    if status:
        orders = [order for order in orders if safe_status(order) == status]

    content = get_html_header(key, "إدارة الطلبات")
    content += '<div class="card"><h2>طلبات الحجز</h2>'
    content += f'<p><a class="btn btn-muted" href="{admin_path("/admin/orders", key)}">الكل</a> '
    content += f'<a class="btn" href="{admin_path("/admin/orders", key, status="pending")}">قيد الانتظار</a> '
    content += f'<a class="btn btn-success" href="{admin_path("/admin/orders", key, status="completed")}">مكتملة</a> '
    content += f'<a class="btn btn-danger" href="{admin_path("/admin/orders", key, status="canceled")}">ملغاة</a></p>'
    content += '<table><tr><th>الرقم</th><th>الزبون</th><th>المنتج</th><th>السعر</th><th>التاريخ</th><th>الحالة</th><th>تحديث</th></tr>'
    for order in orders:
        current_status = safe_status(order)
        badge_class = "bg-pending" if current_status == "pending" else "bg-completed" if current_status == "completed" else "bg-canceled"
        status_text = "قيد الانتظار" if current_status == "pending" else "مكتمل" if current_status == "completed" else "ملغى"
        content += f"""
        <tr>
            <td>#{h(order.get('id'))}</td>
            <td dir="ltr">{h(order.get('phone'))}</td>
            <td>{h(order_product_name(order))}</td>
            <td>{h(order.get('price'))}</td>
            <td dir="ltr">{h(order.get('created_at') or order.get('time'))}</td>
            <td><span class="badge {badge_class}">{status_text}</span></td>
            <td>
                <form action="{admin_path(f'/admin/orders/update/{order.get("id")}', key)}" method="post" style="display:flex; gap:6px; flex-wrap:wrap;">
                    <select name="new_status">
                        <option value="pending" {'selected' if current_status == 'pending' else ''}>انتظار</option>
                        <option value="completed" {'selected' if current_status == 'completed' else ''}>مكتمل</option>
                        <option value="canceled" {'selected' if current_status == 'canceled' else ''}>إلغاء</option>
                    </select>
                    <button type="submit" class="btn btn-success" style="margin:0;">حفظ</button>
                </form>
            </td>
        </tr>
"""
    content += "</table></div>"
    return content + html_footer()


@router.post("/orders/update/{order_id}")
async def update_order(order_id: int, new_status: str = Form(...), key: str = Depends(verify_admin)):
    database.update_order_status(order_id, new_status)
    return RedirectResponse(url=admin_path("/admin/orders", key), status_code=303)
