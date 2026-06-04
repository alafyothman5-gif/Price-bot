import csv
import hashlib
import hmac
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
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

import database
import matcher


load_dotenv()

ADMIN_KEY = os.getenv("PRICEBOT_ADMIN_KEY") or os.getenv("ADMIN_KEY")
SESSION_COOKIE = "pricebot_admin_session"
SESSION_SALT = os.getenv("PRICEBOT_ADMIN_SESSION_SALT", "pricebot-admin-v6")
router = APIRouter(prefix="/admin", tags=["Admin Panel"])


def admin_key_configured() -> bool:
    return bool(ADMIN_KEY)


def _session_token() -> str:
    if not ADMIN_KEY:
        return ""
    return hashlib.sha256(f"{ADMIN_KEY}:{SESSION_SALT}".encode()).hexdigest()


def _is_authorized(request: Request, key: str = None) -> bool:
    if not ADMIN_KEY:
        return False
    if key and hmac.compare_digest(str(key), ADMIN_KEY):
        return True
    cookie = request.cookies.get(SESSION_COOKIE, "")
    return bool(cookie and hmac.compare_digest(cookie, _session_token()))


def require_admin(request: Request, key: str = Query(None)):
    if not ADMIN_KEY:
        raise HTTPException(status_code=503, detail="Admin key is not configured. Set PRICEBOT_ADMIN_KEY or ADMIN_KEY.")
    if not _is_authorized(request, key):
        raise HTTPException(status_code=401, detail="غير مصرح بالدخول. افتح /admin/login")
    return True


def h(value) -> str:
    return html.escape(str(value or ""), quote=True)


def admin_path(path: str, **params) -> str:
    pairs = [f"{quote(str(k))}={quote(str(v))}" for k, v in params.items() if v is not None and v != ""]
    return f"{path}?{'&'.join(pairs)}" if pairs else path


def parse_float(value) -> float:
    text = str(value or "").replace("د.ل", " ").replace("دينار", " ").replace(",", ".")
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


def get_html_header(title: str = "لوحة الصيدلية") -> str:
    return f"""
<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{h(title)}</title>
<style>
:root{{--bg:#f3f6fb;--card:#fff;--ink:#172033;--muted:#637083;--line:#e1e7ef;--blue:#2563eb;--green:#16a34a;--orange:#f59e0b;--red:#dc2626;--purple:#7c3aed}}
*{{box-sizing:border-box}}body{{font-family:Tahoma,Arial,sans-serif;background:var(--bg);margin:0;color:var(--ink)}}.layout{{max-width:1280px;margin:auto;padding:18px}}
.topbar{{background:linear-gradient(135deg,#0f172a,#1e3a8a);color:#fff;border-radius:20px;padding:18px;box-shadow:0 12px 28px rgba(15,23,42,.18)}}.topbar h1{{margin:0 0 6px;font-size:24px}}.topbar p{{margin:0;opacity:.85}}
.nav{{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}}.nav a{{color:#fff;text-decoration:none;padding:9px 12px;border-radius:999px;background:rgba(255,255,255,.13)}}.nav a:hover{{background:rgba(255,255,255,.22)}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-top:16px}}.grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:16px}}
.card,.metric{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;box-shadow:0 6px 20px rgba(15,23,42,.06)}}.metric-title{{font-size:13px;color:var(--muted)}}.metric-value{{font-size:27px;font-weight:800;margin-top:7px}}.metric-hint{{font-size:12px;color:var(--muted);margin-top:6px}}
.metric-blue{{border-top:4px solid var(--blue)}}.metric-green{{border-top:4px solid var(--green)}}.metric-orange{{border-top:4px solid var(--orange)}}.metric-red{{border-top:4px solid var(--red)}}.metric-purple{{border-top:4px solid var(--purple)}}
table{{width:100%;border-collapse:collapse;margin-top:12px;background:#fff;border-radius:12px;overflow:hidden}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}}th{{background:#f8fafc;color:#334155}}input,select,textarea{{font:inherit;padding:10px;border:1px solid #cbd5e1;border-radius:10px;width:100%;margin:4px 0}}textarea{{min-height:80px}}.btn{{display:inline-block;padding:10px 14px;margin:4px;color:#fff;background:var(--blue);text-decoration:none;border-radius:10px;border:0;cursor:pointer}}.btn-success{{background:var(--green)}}.btn-danger{{background:var(--red)}}.btn-muted{{background:#64748b}}.muted{{color:var(--muted);font-size:13px}}.badge{{padding:5px 10px;border-radius:999px;color:#fff;font-size:12px}}.bg-pending{{background:var(--orange)}}.bg-completed{{background:var(--green)}}.bg-canceled{{background:var(--red)}}
.bar-row{{display:grid;grid-template-columns:130px 1fr 45px;gap:10px;align-items:center;margin:10px 0}}.bar-track{{background:#e2e8f0;border-radius:999px;height:10px;overflow:hidden}}.bar-fill{{background:linear-gradient(90deg,#2563eb,#16a34a);height:100%}}
@media(max-width:900px){{.grid,.grid-2{{grid-template-columns:1fr}}}}
</style></head><body><div class="layout"><div class="topbar"><h1>{h(title)}</h1><p>PriceBot — صيدلية بدر البشرية</p><div class="nav">
<a href="/admin">الرئيسية</a><a href="/admin/analytics">الإحصائيات</a><a href="/admin/products">المنتجات</a><a href="/admin/orders">الطلبات</a><a href="/admin/failed-queries">الاستعلامات الفاشلة</a><a href="/admin/logout">خروج</a>
</div></div>
"""


def html_footer() -> str:
    return "</div></body></html>"


def metric_card(title: str, value: str, hint: str = "", tone: str = "blue") -> str:
    return f'<div class="metric metric-{tone}"><div class="metric-title">{h(title)}</div><div class="metric-value">{h(value)}</div><div class="metric-hint">{h(hint)}</div></div>'


def progress_bar(label: str, value: int, max_value: int) -> str:
    pct = 0 if max_value <= 0 else min(100, round((value / max_value) * 100))
    return f'<div class="bar-row"><div>{h(label)}</div><div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div><div>{h(value)}</div></div>'


def order_product_name(order: dict) -> str:
    return str(order.get("product_name") or order.get("product") or order.get("message") or "").strip()


def safe_status(order: dict) -> str:
    return str(order.get("status") or "pending").lower().strip()


def order_stats(orders: List[dict]) -> dict:
    now = datetime.now(); today = now.date(); last_7 = now - timedelta(days=7); last_30 = now - timedelta(days=30)
    total=len(orders); pending=sum(1 for o in orders if safe_status(o)=="pending"); completed=sum(1 for o in orders if safe_status(o)=="completed"); canceled=sum(1 for o in orders if safe_status(o)=="canceled")
    today_count=week_count=month_count=0; product_counter=Counter(); product_revenue=defaultdict(float); phone_counter=Counter(); daily=Counter(); total_revenue=0.0
    for o in orders:
        product=order_product_name(o) or "غير محدد"; product_counter[product]+=1; product_revenue[product]+=parse_float(o.get("price")); phone_counter[str(o.get("phone") or "غير معروف")]+=1; total_revenue+=parse_float(o.get("price"))
        dt=parse_dt(o.get("created_at") or o.get("time"))
        if dt:
            if dt.date()==today: today_count+=1
            if dt>=last_7: week_count+=1
            if dt>=last_30: month_count+=1
            daily[dt.date().isoformat()]+=1
    return {"total":total,"pending":pending,"completed":completed,"canceled":canceled,"today":today_count,"week":week_count,"month":month_count,"completion_rate":round(completed/total*100,1) if total else 0,"cancel_rate":round(canceled/total*100,1) if total else 0,"total_revenue":total_revenue,"top_products":[(n,c,product_revenue[n]) for n,c in product_counter.most_common(10)],"top_customers":phone_counter.most_common(8),"last_7_days":[((today-timedelta(days=i)).isoformat(), daily.get((today-timedelta(days=i)).isoformat(),0)) for i in range(6,-1,-1)]}


def products_health(products: List[dict]) -> dict:
    brands=Counter(); forms=Counter(); norm=Counter(); missing_price=missing_brand=missing_aliases=missing_form=available=unavailable=0
    for p in products:
        if matcher.is_available(p.get("available","متوفر")): available+=1
        else: unavailable+=1
        if not str(p.get("price") or "").strip(): missing_price+=1
        brand=str(p.get("brand") or p.get("company") or "").strip()
        if brand: brands[brand]+=1
        else: missing_brand+=1
        form=str(p.get("form") or p.get("category") or p.get("category_guess") or "").strip()
        if form: forms[form]+=1
        else: missing_form+=1
        if not str(p.get("aliases") or "").strip() and not str(p.get("image_ocr_keywords") or "").strip(): missing_aliases+=1
        n=matcher.normalize_text(p.get("name", ""));
        if n: norm[n]+=1
    duplicates=sum(c-1 for c in norm.values() if c>1)
    return {"total":len(products),"available":available,"unavailable":unavailable,"missing_price":missing_price,"missing_brand":missing_brand,"missing_aliases":missing_aliases,"missing_form":missing_form,"duplicates":duplicates,"top_brands":brands.most_common(8),"top_forms":forms.most_common(8)}


@router.get("/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(get_html_header("تسجيل دخول الأدمن") + '<div class="card"><form method="post" action="/admin/login"><label>كلمة مرور الأدمن</label><input type="password" name="key" required><button class="btn btn-success" type="submit">دخول</button></form></div>' + html_footer())


@router.post("/login")
async def login(key: str = Form(...)):
    if not ADMIN_KEY or not hmac.compare_digest(key, ADMIN_KEY):
        raise HTTPException(status_code=401, detail="غير مصرح.")
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(SESSION_COOKIE, _session_token(), httponly=True, samesite="lax", max_age=60*60*24*30)
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, key: str = Query(None)):
    if key and _is_authorized(request, key):
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(SESSION_COOKIE, _session_token(), httponly=True, samesite="lax", max_age=60*60*24*30)
        return response
    require_admin(request)
    products = database.load_products(); orders = database.get_all_orders(); stats=order_stats(orders); health=products_health(products); ai=database.get_ai_usage_summary(30)
    content=get_html_header("لوحة التحكم")
    content += '<div class="grid">'+ metric_card("المنتجات", str(len(products)), "إجمالي قائمة الصيدلية") + metric_card("طلبات اليوم", str(stats["today"]), "آخر 24 ساعة", "green") + metric_card("قيد الانتظار", str(stats["pending"]), "تحتاج متابعة", "orange") + metric_card("AI صور 30 يوم", str(ai["total"]), f"نجاح {ai['success']} — Tokens {ai['tokens']}", "purple") + '</div>'
    content += '<div class="grid-2"><div class="card"><h2>أكثر المنتجات طلباً</h2><table><tr><th>المنتج</th><th>العدد</th><th>القيمة</th></tr>'
    for name,count,revenue in stats["top_products"][:8]: content += f'<tr><td>{h(name)}</td><td>{count}</td><td>{revenue:.2f}</td></tr>'
    content += '</table></div><div class="card"><h2>صحة ملف المنتجات</h2>' + progress_bar("بلا سعر", health["missing_price"], max(health["total"],1)) + progress_bar("بلا براند", health["missing_brand"], max(health["total"],1)) + progress_bar("بلا aliases/OCR", health["missing_aliases"], max(health["total"],1)) + progress_bar("تكرار محتمل", health["duplicates"], max(health["total"],1)) + '</div></div>'
    return HTMLResponse(content + html_footer())


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request, _: bool = Depends(require_admin)):
    products=database.load_products(); orders=database.get_all_orders(); stats=order_stats(orders); health=products_health(products); ai=database.get_ai_usage_summary(30); failed=database.get_failed_queries(10)
    content=get_html_header("الإحصائيات")
    content += '<div class="grid">'+ metric_card("طلبات اليوم", str(stats["today"]), "اليوم", "green")+metric_card("آخر 7 أيام", str(stats["week"]), "أسبوع", "blue")+metric_card("آخر 30 يوم", str(stats["month"]), "شهر", "purple")+metric_card("معدل الإكمال", f"{stats['completion_rate']}%", "طلبات مكتملة", "green")+'</div>'
    content += '<div class="grid">'+metric_card("قيد الانتظار", str(stats["pending"]), "", "orange")+metric_card("مكتملة", str(stats["completed"]), "", "green")+metric_card("ملغاة", str(stats["canceled"]), f"إلغاء {stats['cancel_rate']}%", "red")+metric_card("قيمة الطلبات", f"{stats['total_revenue']:.2f}", "تقريبية", "blue")+'</div>'
    content += '<div class="grid-2"><div class="card"><h2>أكثر المنتجات طلباً</h2><table><tr><th>المنتج</th><th>العدد</th><th>قيمة تقريبية</th></tr>'
    for name,count,revenue in stats["top_products"]: content += f'<tr><td>{h(name)}</td><td>{count}</td><td>{revenue:.2f}</td></tr>'
    content += '</table></div><div class="card"><h2>AI Usage آخر 30 يوم</h2>'+metric_card("صور/محاولات", str(ai["total"]), "", "purple")+metric_card("نجاح", str(ai["success"]), "", "green")+metric_card("Tokens", str(ai["tokens"]), "", "blue")+metric_card("تكلفة تقريبية", f"{ai['cost']:.4f}$", "حسب env", "orange")+'</div></div>'
    content += '<div class="grid-2"><div class="card"><h2>أكثر الزبائن طلباً</h2><table><tr><th>الرقم</th><th>عدد الطلبات</th></tr>'
    for phone,count in stats["top_customers"]: content += f'<tr><td dir="ltr">{h(phone)}</td><td>{count}</td></tr>'
    content += '</table></div><div class="card"><h2>استعلامات فاشلة/غير متوفرة</h2><table><tr><th>الاستعلام</th><th>الحالة</th><th>العدد</th></tr>'
    for row in failed: content += f'<tr><td>{h(row.get("raw_query"))}</td><td>{h(row.get("status"))}</td><td>{h(row.get("count"))}</td></tr>'
    content += '</table></div></div>'
    return HTMLResponse(content+html_footer())


def product_matches(product: dict, query: str) -> bool:
    if not query: return True
    q_norm = matcher.normalize_text(query); identity = matcher.get_product_identity(product)
    return q_norm in identity


@router.get("/products", response_class=HTMLResponse)
async def manage_products(request: Request, q: str = "", page: int = 1, _: bool = Depends(require_admin)):
    all_products=database.load_products(); filtered=[p for p in all_products if product_matches(p,q)]; per_page=100; page=max(1,page); total_pages=max((len(filtered)+per_page-1)//per_page,1); page=min(page,total_pages); page_products=filtered[(page-1)*per_page:page*per_page]
    content=get_html_header("المنتجات")
    content += '<div class="card"><h2>رفع Excel/CSV</h2><form action="/admin/upload" method="post" enctype="multipart/form-data"><input type="file" name="file" accept=".csv,.xlsx" required><label><input type="checkbox" name="replace_all" value="yes" style="width:auto"> استبدال كامل بعد التحقق</label><br><label><input type="checkbox" name="force_confirm" value="yes" style="width:auto"> تأكيد صريح للاستبدال الكامل</label><br><button class="btn btn-success" type="submit">رفع وتحديث</button></form></div>'
    content += f'<div class="card"><form method="get" action="/admin/products"><input type="text" name="q" value="{h(q)}" placeholder="ابحث في كل المنتجات..."></form><p class="muted">النتائج: {len(filtered)} من {len(all_products)} — الصفحة {page}/{total_pages}</p><table><tr><th>ID</th><th>الاسم</th><th>السعر</th><th>البراند</th><th>الشكل</th><th>التوفر</th><th>إجراءات</th></tr>'
    for p in page_products:
        content += f'<tr><td>{h(p.get("id"))}</td><td>{h(p.get("name"))}</td><td>{h(p.get("price"))}</td><td>{h(p.get("brand") or p.get("company"))}</td><td>{h(p.get("form"))}</td><td>{h(p.get("available"))}</td><td><a class="btn" href="/admin/products/edit/{h(p.get("id"))}">تعديل</a><form action="/admin/products/delete/{h(p.get("id"))}" method="post" style="display:inline"><button class="btn btn-danger" onclick="return confirm(\'تأكيد حذف المنتج؟\')">حذف</button></form></td></tr>'
    content += '</table>'
    if page>1: content += f'<a class="btn btn-muted" href="{admin_path("/admin/products",q=q,page=page-1)}">السابق</a>'
    if page<total_pages: content += f'<a class="btn btn-muted" href="{admin_path("/admin/products",q=q,page=page+1)}">التالي</a>'
    content += '</div>'
    return HTMLResponse(content+html_footer())


@router.get("/products/edit/{product_id}", response_class=HTMLResponse)
async def edit_product(product_id: int, request: Request, _: bool = Depends(require_admin)):
    p=database.get_product(product_id)
    if not p: raise HTTPException(status_code=404, detail="Product not found")
    fields=["name","price","brand","company","form","aliases","image_ocr_keywords","active_ingredient","strength","pack","available","code","barcode","sku","item_code","product_code"]
    content=get_html_header("تعديل منتج") + f'<div class="card"><h2>تعديل #{product_id}</h2><form method="post" action="/admin/products/edit/{product_id}">'
    for f in fields:
        value=h(p.get(f,"")); textarea=f in {"aliases","image_ocr_keywords"}
        content += f'<label>{f}</label>' + (f'<textarea name="{f}">{value}</textarea>' if textarea else f'<input name="{f}" value="{value}">')
    content += '<button class="btn btn-success" type="submit">حفظ</button><a class="btn btn-muted" href="/admin/products">رجوع</a></form></div>'
    return HTMLResponse(content+html_footer())


@router.post("/products/edit/{product_id}")
async def save_product(product_id: int, request: Request, _: bool = Depends(require_admin)):
    form=await request.form(); database.backup_database(); database.update_product(product_id, dict(form)); matcher.invalidate_product_cache()
    return RedirectResponse(url=f"/admin/products/edit/{product_id}", status_code=303)


HEADER_ALIASES={"name":{"name","product","product_name","product name","اسم المنتج","المنتج","الاسم","الصنف","canonical_name"},"price":{"price","السعر","سعر","final_price","box_price","strip_price","cost"},"company":{"company","الشركة","المصنع","الوكيل"},"brand":{"brand","الماركة","البراند"},"aliases":{"aliases","اسماء بديلة","اسم بديل"},"image_ocr_keywords":{"image_ocr_keywords","ocr_keywords","keywords","كلمات","كلمات البحث"},"form":{"form","type","category","form_or_type","category_guess","الشكل الدوائي","النوع","شكل"},"available":{"available","status","الحالة","التوفر","توفر","الكمية","qty"},"active_ingredient":{"active_ingredient","المادة الفعالة","المادة"},"strength":{"strength","size","strength_or_size","حجم","تركيز"},"pack":{"pack","package","عبوة","العبوة"},"code":{"code","كود"},"barcode":{"barcode","باركود"},"sku":{"sku"},"item_code":{"item_code"},"product_code":{"product_code"}}


def map_header(header)->str:
    raw=str(header or "").strip(); norm=matcher.normalize_text(raw).replace("_"," "); low=raw.lower()
    for canon,aliases in HEADER_ALIASES.items():
        if norm in {matcher.normalize_text(a).replace("_"," ") for a in aliases} or low in {a.lower() for a in aliases}: return canon
    return low.replace(" ","_")


def unique_headers(headers: List[str])->List[str]:
    seen={}; result=[]
    for header in headers:
        mapped=map_header(header); count=seen.get(mapped,0); seen[mapped]=count+1; result.append(mapped if count==0 else f"{mapped}__{count}")
    return result


def collect(row: dict, key: str) -> str:
    vals=[]
    for k,v in row.items():
        if k==key or str(k).startswith(f"{key}__"):
            t="" if v is None else str(v).strip()
            if t and t.lower()!="none": vals.append(t)
    return " | ".join(vals)


def product_from_row(row: dict)->dict:
    name=collect(row,"name")
    if not name: return {}
    company=collect(row,"company"); brand=collect(row,"brand") or company
    return {"name":name,"price":collect(row,"price"),"company":company,"brand":brand,"aliases":collect(row,"aliases"),"image_ocr_keywords":collect(row,"image_ocr_keywords"),"form":collect(row,"form"),"available":collect(row,"available") or "متوفر","active_ingredient":collect(row,"active_ingredient"),"strength":collect(row,"strength"),"pack":collect(row,"pack"),"code":collect(row,"code"),"barcode":collect(row,"barcode"),"sku":collect(row,"sku"),"item_code":collect(row,"item_code"),"product_code":collect(row,"product_code")}


def parse_csv(content: bytes)->Tuple[List[dict],List[str]]:
    text=content.decode("utf-8-sig"); rows=list(csv.reader(io.StringIO(text)))
    if not rows: raise ValueError("الملف فارغ.")
    headers=unique_headers([str(c or "") for c in rows[0]]); parsed=[dict(zip(headers,row)) for row in rows[1:] if any(str(c or "").strip() for c in row)]
    return parsed, headers


def find_xlsx_table(content: bytes)->Tuple[List[dict],List[str]]:
    workbook=openpyxl.load_workbook(io.BytesIO(content),data_only=True,read_only=True)
    best=[]
    for sheet in workbook.worksheets:
        rows=list(sheet.iter_rows(values_only=True))
        for idx,row in enumerate(rows[:20]):
            headers=unique_headers([str(c or "") for c in row])
            if "name" in headers:
                return [dict(zip(headers,values)) for values in rows[idx+1:] if any(str(c or "").strip() for c in values)], headers
        if len(rows)>len(best): best=rows
    if best:
        headers=unique_headers([str(c or "") for c in best[0]]); return [dict(zip(headers,values)) for values in best[1:] if any(str(c or "").strip() for c in values)], headers
    raise ValueError("ملف Excel فارغ.")


def parse_upload(content: bytes, filename: str)->Tuple[List[dict],List[str]]:
    lower=(filename or "").lower(); rows,headers = parse_csv(content) if lower.endswith(".csv") else find_xlsx_table(content) if lower.endswith(".xlsx") else (_ for _ in ()).throw(ValueError("صيغة الملف غير مدعومة."))
    if "name" not in headers: raise ValueError("لم يتم العثور على عمود اسم المنتج.")
    products=[product_from_row(row) for row in rows]; products=[p for p in products if p]
    if not products: raise ValueError("لم يتم العثور على منتجات صالحة داخل الملف.")
    return products, headers


def upsert_products(products: List[dict], replace_all: bool)->int:
    with database.get_db_connection() as conn:
        if replace_all: conn.execute("DELETE FROM products")
        changed=0
        for product in products:
            name=product["name"].strip(); normalized=matcher.normalize_text(name)
            existing=conn.execute("SELECT id FROM products WHERE normalized_name=? OR name=? LIMIT 1",(normalized,name)).fetchone()
            values=(name,product.get("price",""),product.get("form",""),product.get("aliases",""),product.get("image_ocr_keywords",""),product.get("active_ingredient",""),product.get("company",""),product.get("brand",""),product.get("available","متوفر"),product.get("strength",""),product.get("pack",""),product.get("code",""),product.get("barcode",""),product.get("sku",""),product.get("item_code",""),product.get("product_code",""),normalized)
            if existing:
                conn.execute("""UPDATE products SET name=?, price=?, form=?, aliases=?, image_ocr_keywords=?, active_ingredient=?, company=?, brand=?, available=?, strength=?, pack=?, code=?, barcode=?, sku=?, item_code=?, product_code=?, normalized_name=?, updated_at=CURRENT_TIMESTAMP WHERE id=?""", values+(existing["id"],))
            else:
                conn.execute("""INSERT INTO products (name, price, form, aliases, image_ocr_keywords, active_ingredient, company, brand, available, strength, pack, code, barcode, sku, item_code, product_code, normalized_name, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""", values)
            changed+=1
        conn.commit(); matcher.invalidate_product_cache(); return changed


def render_upload_error(message: str)->HTMLResponse:
    return HTMLResponse(get_html_header("خطأ في الرفع")+f'<div class="card"><h2>تعذر الرفع</h2><p>{h(message)}</p><a class="btn" href="/admin/products">عودة</a></div>'+html_footer(), status_code=400)


@router.post("/upload")
async def upload_file(request: Request, file: UploadFile = File(...), replace_all: str = Form(None), force_confirm: str = Form(None), _: bool = Depends(require_admin)):
    try:
        content=await file.read(); products,headers=parse_upload(content,file.filename or ""); current=database.count_products(); do_replace=replace_all=="yes"
        if do_replace:
            if force_confirm!="yes": return render_upload_error("الاستبدال الكامل يحتاج تحديد خانة التأكيد الصريح.")
            if current>=100 and len(products)<max(100,int(current*0.5)): return render_upload_error(f"عدد المنتجات في الملف ({len(products)}) أقل بكثير من الموجود حالياً ({current}). تم رفض الاستبدال.")
        database.backup_database(); changed=upsert_products(products,do_replace); print(f"PRODUCT_UPLOAD_OK: changed={changed} replace_all={do_replace} headers={headers}")
    except Exception as exc:
        print(f"PRODUCT_UPLOAD_ERROR: {exc}"); return render_upload_error(str(exc))
    return RedirectResponse(url="/admin/products", status_code=303)


@router.post("/products/delete/{product_id}")
async def delete_product(product_id: int, request: Request, _: bool = Depends(require_admin)):
    database.backup_database()
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products WHERE id=?",(product_id,)); conn.commit()
    matcher.invalidate_product_cache(); return RedirectResponse(url="/admin/products", status_code=303)


@router.get("/orders", response_class=HTMLResponse)
async def manage_orders(request: Request, _: bool = Depends(require_admin)):
    orders=database.get_all_orders(); content=get_html_header("الطلبات")+'<div class="card"><h2>طلبات الحجز</h2><table><tr><th>الرقم</th><th>الزبون</th><th>المنتج</th><th>السعر</th><th>التاريخ</th><th>الحالة</th><th>تحديث</th></tr>'
    for o in orders:
        status=safe_status(o); badge='bg-pending' if status=='pending' else 'bg-completed' if status=='completed' else 'bg-canceled'; text='قيد الانتظار' if status=='pending' else 'مكتمل' if status=='completed' else 'ملغى'
        content += f'<tr><td>#{h(o.get("id"))}</td><td dir="ltr">{h(o.get("phone"))}</td><td>{h(order_product_name(o))}</td><td>{h(o.get("price"))}</td><td dir="ltr">{h(o.get("created_at"))}</td><td><span class="badge {badge}">{text}</span></td><td><form action="/admin/orders/update/{h(o.get("id"))}" method="post"><select name="new_status"><option value="pending" {"selected" if status=="pending" else ""}>انتظار</option><option value="completed" {"selected" if status=="completed" else ""}>مكتمل</option><option value="canceled" {"selected" if status=="canceled" else ""}>إلغاء</option></select><button class="btn btn-success">حفظ</button></form></td></tr>'
    return HTMLResponse(content+'</table></div>'+html_footer())


@router.post("/orders/update/{order_id}")
async def update_order(order_id: int, request: Request, new_status: str = Form(...), _: bool = Depends(require_admin)):
    database.update_order_status(order_id,new_status); return RedirectResponse(url="/admin/orders", status_code=303)


@router.get("/failed-queries", response_class=HTMLResponse)
async def failed_queries(request: Request, _: bool = Depends(require_admin)):
    rows=database.get_failed_queries(100); content=get_html_header("الاستعلامات الفاشلة")+'<div class="card"><h2>Fallback / Unavailable</h2><table><tr><th>الاستعلام</th><th>بعد التنظيف</th><th>المصدر</th><th>الحالة</th><th>العدد</th><th>آخر مرة</th></tr>'
    for r in rows: content += f'<tr><td>{h(r.get("raw_query"))}</td><td>{h(r.get("normalized_query"))}</td><td>{h(r.get("source"))}</td><td>{h(r.get("status"))}</td><td>{h(r.get("count"))}</td><td>{h(r.get("last_seen"))}</td></tr>'
    return HTMLResponse(content+'</table></div>'+html_footer())
