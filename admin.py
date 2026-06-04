import csv
import html
import io
import os
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
        body {{ font-family: Tahoma, Arial, sans-serif; background:#f5f7f8; margin:0; padding:20px; color:#1f2933; }}
        .container {{ max-width:1160px; margin:auto; background:#fff; padding:20px; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,.08); }}
        h1, h2 {{ color:#243b53; }}
        table {{ width:100%; border-collapse:collapse; margin-top:16px; }}
        th, td {{ padding:10px; border:1px solid #dde3ea; text-align:right; vertical-align:top; }}
        th {{ background:#34495e; color:#fff; }}
        input, select {{ font:inherit; }}
        .btn {{ display:inline-block; padding:9px 13px; margin:4px; color:#fff; background:#2f80ed; text-decoration:none; border-radius:5px; border:0; cursor:pointer; }}
        .btn-success {{ background:#219653; }}
        .btn-danger {{ background:#c0392b; }}
        .btn-muted {{ background:#607d8b; }}
        .box {{ background:#eef6f3; padding:14px; border-radius:6px; margin:14px 0; }}
        .danger-box {{ background:#fff1f0; border:1px solid #ffccc7; }}
        .search-box {{ width:100%; padding:11px; border:1px solid #ccd6dd; border-radius:5px; box-sizing:border-box; }}
        .badge {{ padding:4px 9px; border-radius:12px; color:#fff; font-size:12px; white-space:nowrap; }}
        .bg-pending {{ background:#f39c12; }}
        .bg-completed {{ background:#27ae60; }}
        .bg-canceled {{ background:#c0392b; }}
        .muted {{ color:#607080; font-size:13px; }}
        .pagination a {{ color:#2f80ed; margin:0 4px; text-decoration:none; }}
    </style>
</head>
<body>
<div class="container">
    <div style="margin-bottom:18px; border-bottom:1px solid #e5e9ef; padding-bottom:10px;">
        <a href="{admin_path('/admin', key)}" class="btn">الرئيسية</a>
        <a href="{admin_path('/admin/products', key)}" class="btn">المنتجات</a>
        <a href="{admin_path('/admin/orders', key)}" class="btn btn-muted">الطلبات</a>
    </div>
"""


def html_footer() -> str:
    return "</div></body></html>"


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(key: str = Depends(verify_admin)):
    products = database.load_products()
    orders = database.get_all_orders()
    pending_orders = len([order for order in orders if order.get("status") == "pending"])
    content = get_html_header(key, "الرئيسية")
    content += f"""
    <h1>لوحة صيدلية بدر البشرية</h1>
    <div style="display:flex; gap:16px; flex-wrap:wrap;">
        <div class="box" style="flex:1; min-width:220px;">
            <h2>إجمالي المنتجات</h2>
            <p style="font-size:24px; margin:0;"><b>{len(products)}</b></p>
        </div>
        <div class="box" style="flex:1; min-width:220px;">
            <h2>طلبات قيد الانتظار</h2>
            <p style="font-size:24px; margin:0;"><b>{pending_orders}</b></p>
        </div>
    </div>
"""
    return content + html_footer()


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

    content = get_html_header(key, "المنتجات")
    content += f"""
    <h2>رفع Excel/CSV</h2>
    <form action="{admin_path('/admin/upload', key)}" method="post" enctype="multipart/form-data" class="box">
        <input type="file" name="file" accept=".csv,.xlsx" required><br><br>
        <label><input type="checkbox" name="replace_all" value="yes"> استبدال كامل بعد التحقق</label><br>
        <label style="color:#b42318; font-weight:bold;"><input type="checkbox" name="force_confirm" value="yes"> تأكيد صريح للاستبدال الكامل</label>
        <p class="muted">بدون الاستبدال الكامل سيتم تحديث المنتجات وإضافة الجديد فقط. لا يتم حذف القديم في safe upsert.</p>
        <button type="submit" class="btn btn-success">رفع وتحديث</button>
    </form>

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
                <form action="{admin_path(f"/admin/products/delete/{product.get('id')}", key)}" method="post" style="display:inline;">
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

    return content + html_footer()


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
    best_headers = []

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
    content += f'<div class="box danger-box"><h2>تعذر الرفع</h2><p>{h(message)}</p><a class="btn" href="{admin_path("/admin/products", key)}">عودة</a></div>'
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


@router.get("/orders", response_class=HTMLResponse)
async def manage_orders(key: str = Depends(verify_admin)):
    orders = database.get_all_orders()
    content = get_html_header(key, "الطلبات")
    content += "<h2>طلبات الحجز</h2><table><tr><th>الرقم</th><th>الزبون</th><th>المنتج</th><th>السعر</th><th>التاريخ</th><th>الحالة</th><th>تحديث</th></tr>"
    for order in orders:
        status = order.get("status", "pending")
        badge_class = "bg-pending" if status == "pending" else "bg-completed" if status == "completed" else "bg-canceled"
        status_text = "قيد الانتظار" if status == "pending" else "مكتمل" if status == "completed" else "ملغى"
        content += f"""
        <tr>
            <td>#{h(order.get('id'))}</td>
            <td dir="ltr">{h(order.get('phone'))}</td>
            <td>{h(order.get('product_name'))}</td>
            <td>{h(order.get('price'))}</td>
            <td dir="ltr">{h(order.get('created_at'))}</td>
            <td><span class="badge {badge_class}">{status_text}</span></td>
            <td>
                <form action="{admin_path(f"/admin/orders/update/{order.get('id')}", key)}" method="post" style="display:flex; gap:6px;">
                    <select name="new_status">
                        <option value="pending" {'selected' if status == 'pending' else ''}>انتظار</option>
                        <option value="completed" {'selected' if status == 'completed' else ''}>مكتمل</option>
                        <option value="canceled" {'selected' if status == 'canceled' else ''}>إلغاء</option>
                    </select>
                    <button type="submit" class="btn btn-success" style="margin:0;">حفظ</button>
                </form>
            </td>
        </tr>
"""
    content += "</table>"
    return content + html_footer()


@router.post("/orders/update/{order_id}")
async def update_order(order_id: int, new_status: str = Form(...), key: str = Depends(verify_admin)):
    database.update_order_status(order_id, new_status)
    return RedirectResponse(url=admin_path("/admin/orders", key), status_code=303)
