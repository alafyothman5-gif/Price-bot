# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
import time
from collections import defaultdict
from typing import Dict, List

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import database
from services.catalog_quality import analyze_products

router = APIRouter(prefix="/merchant", tags=["Merchant Portal"])
MERCHANT_COOKIE = "pricebot_merchant_session"
MERCHANT_LOGIN_CSRF_COOKIE = "pricebot_merchant_login_csrf"
MERCHANT_SESSION_MAX_AGE_SECONDS = int(os.getenv("MERCHANT_SESSION_MAX_AGE_SECONDS", str(8 * 60 * 60)))
MERCHANT_LOGIN_RATE_LIMIT_MAX = int(os.getenv("MERCHANT_LOGIN_RATE_LIMIT_MAX", "5"))
MERCHANT_LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("MERCHANT_LOGIN_RATE_LIMIT_WINDOW_SECONDS", str(10 * 60)))
MERCHANT_LOGIN_LOCKOUT_SECONDS = int(os.getenv("MERCHANT_LOGIN_LOCKOUT_SECONDS", str(15 * 60)))
_merchant_login_failures: Dict[str, List[float]] = defaultdict(list)
_merchant_login_lock_until: Dict[str, float] = {}


def h(v) -> str:
    return html.escape(str(v or ""), quote=True)


def _env_name() -> str:
    return (os.getenv("PRICEBOT_ENV") or os.getenv("ENV") or "local").strip().lower()


def _is_production_env() -> bool:
    return _env_name() in {"prod", "production", "live"}


def _truthy(value: str | None) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _cookie_secure(request: Request) -> bool:
    return _is_production_env() or str(request.headers.get("x-forwarded-proto", "")).lower() == "https" or request.url.scheme == "https"


def _request_ip(request: Request) -> str:
    forwarded = str(request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "unknown")


def _merchant_login_code() -> str:
    """Return configured merchant login code from env or DB settings.

    The old hard-coded pilot value "merchant" is intentionally rejected. If no
    code is configured, the merchant portal is disabled in production.
    """
    code = (os.getenv("MERCHANT_LOGIN_CODE") or "").strip()
    if not code:
        try:
            settings = database.get_merchant_settings()
            code = str(settings.get("merchant_login_code") or settings.get("MERCHANT_LOGIN_CODE") or "").strip()
        except Exception:
            code = ""
    if code.lower() == "merchant":
        return ""
    return code


def merchant_portal_enabled() -> bool:
    configured_code = bool(_merchant_login_code())
    flag = _truthy(os.getenv("MERCHANT_PORTAL_ENABLED"))
    if flag is False:
        return False
    if flag is True:
        return configured_code
    if _is_production_env():
        return configured_code
    return configured_code


def _require_portal_enabled() -> None:
    if not merchant_portal_enabled():
        raise HTTPException(status_code=503, detail="Merchant portal is disabled. Set MERCHANT_LOGIN_CODE and MERCHANT_PORTAL_ENABLED=true.")


def _session_secret() -> str:
    return (
        os.getenv("MERCHANT_SESSION_SECRET")
        or os.getenv("ADMIN_SESSION_SECRET")
        or os.getenv("PRICEBOT_ADMIN_SESSION_SECRET")
        or "pricebot-merchant-dev-secret-change-me"
    )


def _session_signature(ts: str) -> str:
    code = _merchant_login_code()
    if not code:
        return ""
    payload = f"merchant:{code}:{ts}".encode("utf-8")
    return hmac.new(_session_secret().encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _session_token() -> str:
    ts = str(int(time.time()))
    return f"{ts}:{_session_signature(ts)}"


def _is_merchant_authorized(request: Request) -> bool:
    if not merchant_portal_enabled():
        return False
    cookie = request.cookies.get(MERCHANT_COOKIE, "")
    try:
        ts, sig = cookie.split(":", 1)
        if time.time() - int(ts) > MERCHANT_SESSION_MAX_AGE_SECONDS:
            return False
        return bool(sig and hmac.compare_digest(sig, _session_signature(ts)))
    except Exception:
        return False


def _set_merchant_cookie(response: Response, request: Request) -> None:
    response.set_cookie(
        MERCHANT_COOKIE,
        _session_token(),
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=MERCHANT_SESSION_MAX_AGE_SECONDS,
    )


def _delete_merchant_cookie(response: Response) -> None:
    response.delete_cookie(MERCHANT_COOKIE)


def _new_login_csrf() -> str:
    return secrets.token_urlsafe(32)


def _validate_login_csrf(request: Request, token: str) -> bool:
    cookie = request.cookies.get(MERCHANT_LOGIN_CSRF_COOKIE, "")
    return bool(cookie and token and hmac.compare_digest(cookie, token))


def _csrf_token(request: Request) -> str:
    session = request.cookies.get(MERCHANT_COOKIE, "")
    if not session:
        return ""
    return hmac.new(_session_secret().encode("utf-8"), f"merchant-csrf:{session}".encode("utf-8"), hashlib.sha256).hexdigest()


def csrf_field(request: Request) -> str:
    return f'<input type="hidden" name="csrf_token" value="{h(_csrf_token(request))}">'


def require_csrf(request: Request, token: str) -> None:
    expected = _csrf_token(request)
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="CSRF token invalid.")


def _login_locked(request: Request) -> bool:
    ip = _request_ip(request)
    until = float(_merchant_login_lock_until.get(ip) or 0)
    if until and until > time.time():
        return True
    if until:
        _merchant_login_lock_until.pop(ip, None)
    return False


def _record_login_failure(request: Request) -> None:
    ip = _request_ip(request)
    now = time.time()
    recent = [t for t in _merchant_login_failures[ip] if now - t <= MERCHANT_LOGIN_RATE_LIMIT_WINDOW_SECONDS]
    recent.append(now)
    _merchant_login_failures[ip] = recent
    if len(recent) >= MERCHANT_LOGIN_RATE_LIMIT_MAX:
        _merchant_login_lock_until[ip] = now + MERCHANT_LOGIN_LOCKOUT_SECONDS


def _clear_login_failures(request: Request) -> None:
    ip = _request_ip(request)
    _merchant_login_failures.pop(ip, None)
    _merchant_login_lock_until.pop(ip, None)


def header(title: str) -> str:
    settings = database.get_merchant_settings()
    name = settings.get("pharmacy_name") or "PriceBot"
    return f'''<!doctype html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{h(title)}</title><style>
body{{margin:0;font-family:Tahoma,Arial;background:#f6f8fb;color:#172033}}.shell{{max-width:1180px;margin:auto;padding:16px}}.top{{background:linear-gradient(135deg,#064e3b,#2563eb);color:white;border-radius:22px;padding:18px;box-shadow:0 10px 28px #0002}}.nav{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}.nav a{{color:white;text-decoration:none;background:#ffffff22;border-radius:999px;padding:9px 12px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:16px}}.card{{background:white;border:1px solid #e2e8f0;border-radius:18px;padding:16px;box-shadow:0 8px 20px #0f172a0d}}.metric b{{font-size:28px}}table{{width:100%;border-collapse:collapse;background:white;border-radius:12px;overflow:hidden}}th,td{{padding:10px;border-bottom:1px solid #e2e8f0;text-align:right}}input,select,textarea{{width:100%;padding:10px;border:1px solid #cbd5e1;border-radius:10px;margin:4px 0}}.btn{{display:inline-block;background:#2563eb;color:white;text-decoration:none;border:0;border-radius:10px;padding:10px 14px;margin:4px;cursor:pointer}}.ok{{background:#16a34a}}.bad{{background:#dc2626}}.muted{{color:#64748b;font-size:13px}}@media(max-width:780px){{.grid{{grid-template-columns:1fr}}table,tr,td,th{{display:block}}th{{display:none}}td{{border-bottom:1px solid #e2e8f0}}}}
</style></head><body><div class="shell"><div class="top"><h1>{h(title)}</h1><p>{h(name)} — Merchant Portal</p><div class="nav"><a href="/merchant/dashboard">الرئيسية</a><a href="/merchant/products">المنتجات</a><a href="/merchant/products/import">رفع المنتجات</a><a href="/merchant/products/review">مراجعة</a><a href="/merchant/orders">الطلبات</a><a href="/merchant/customer-link">رابط الزبائن</a><a href="/merchant/settings">الإعدادات</a><a href="/merchant/catalog-quality">جودة الكتالوج</a><a href="/merchant/failed-queries">الأخطاء</a><a href="/merchant/logout">خروج</a></div></div>'''


def footer() -> str:
    return "</div></body></html>"


def require_merchant(request: Request):
    _require_portal_enabled()
    if not _is_merchant_authorized(request):
        raise HTTPException(status_code=401, detail="افتح /merchant/login")
    return True


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    _require_portal_enabled()
    token = _new_login_csrf()
    body = header("دخول التاجر") + f'<div class="card"><form method="post" action="/merchant/login"><input type="hidden" name="csrf_token" value="{h(token)}"><label>كود التاجر</label><input name="code" type="password" required autocomplete="current-password"><button class="btn ok">دخول</button><p class="muted">كود الدخول يضبط من .env أو إعدادات قاعدة البيانات ولا يوجد كود افتراضي آمن للإنتاج.</p></form></div>' + footer()
    response = HTMLResponse(body)
    response.set_cookie(MERCHANT_LOGIN_CSRF_COOKIE, token, httponly=True, secure=_cookie_secure(request), samesite="lax", max_age=600)
    return response


@router.post("/login")
async def login(request: Request, code: str = Form(...), csrf_token: str = Form("")):
    _require_portal_enabled()
    if not _validate_login_csrf(request, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid.")
    if _login_locked(request):
        raise HTTPException(status_code=429, detail="محاولات كثيرة. حاول لاحقاً.")
    expected = _merchant_login_code()
    if not expected or not hmac.compare_digest(code, expected):
        _record_login_failure(request)
        raise HTTPException(status_code=401, detail="كود غير صحيح")
    _clear_login_failures(request)
    r = RedirectResponse("/merchant/dashboard", status_code=303)
    _set_merchant_cookie(r, request)
    r.delete_cookie(MERCHANT_LOGIN_CSRF_COOKIE)
    return r


@router.get("/logout", response_class=HTMLResponse)
async def logout_page(request: Request, _: bool = Depends(require_merchant)):
    return HTMLResponse(header("خروج التاجر") + f'<div class="card"><form method="post" action="/merchant/logout">{csrf_field(request)}<p>اضغط للخروج من بوابة التاجر.</p><button class="btn bad">خروج</button></form></div>' + footer())


@router.post("/logout")
async def logout(request: Request, csrf_token: str = Form(""), _: bool = Depends(require_merchant)):
    require_csrf(request, csrf_token)
    r = RedirectResponse("/merchant/login", status_code=303)
    _delete_merchant_cookie(r)
    return r


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(_: bool = Depends(require_merchant)):
    products = database.load_products(); orders = database.get_all_orders(); quality = analyze_products(products)
    html_s = header("لوحة التاجر") + '<div class="grid">'
    html_s += f'<div class="card metric"><span>المنتجات</span><br><b>{len(products)}</b></div>'
    html_s += f'<div class="card metric"><span>الطلبات</span><br><b>{len(orders)}</b></div>'
    html_s += f'<div class="card metric"><span>جودة الكتالوج</span><br><b>{quality.get("catalog_readiness_score",0)}%</b></div>'
    html_s += '</div><div class="card"><h2>اختصارات الهاتف</h2><a class="btn" href="/merchant/products">تعديل السعر والتوفر</a><a class="btn ok" href="/merchant/orders">إدارة الطلبات</a><a class="btn" href="/merchant/products/review">مراجعة المنتجات</a></div>'
    return HTMLResponse(html_s + footer())


@router.get("/products", response_class=HTMLResponse)
async def products(request: Request, _: bool = Depends(require_merchant)):
    rows = database.load_products()[:300]
    csrf = csrf_field(request)
    out = header("منتجات التاجر") + '<div class="card"><h2>بحث سريع وتعديل السعر/التوفر</h2><table><tr><th>ID</th><th>المنتج</th><th>السعر</th><th>التوفر</th><th>إجراء</th></tr>'
    for p in rows:
        out += f'<tr><td>{h(p.get("id"))}</td><td>{h(p.get("name"))}</td><td>{h(p.get("price"))}</td><td>{h(p.get("available"))}</td><td><form method="post" action="/merchant/products/{h(p.get("id"))}/quick">{csrf}<input name="price" value="{h(p.get("price"))}"><select name="available"><option>متوفر</option><option>غير متوفر</option></select><button class="btn ok">حفظ</button></form></td></tr>'
    out += '</table></div>'
    return HTMLResponse(out + footer())


@router.post("/products/{product_id}/quick")
async def product_quick(product_id: int, request: Request, price: str = Form(""), available: str = Form("متوفر"), csrf_token: str = Form(""), _: bool = Depends(require_merchant)):
    require_csrf(request, csrf_token)
    database.update_product(product_id, {"price": price, "available": available})
    database.log_audit("merchant_product_quick_edit", "merchant", "product", str(product_id), new_value=f"price={price};available={available}", ip=request.client.host if request.client else "")
    return RedirectResponse("/merchant/products", status_code=303)


@router.get("/products/import", response_class=HTMLResponse)
async def import_page(_: bool = Depends(require_merchant)):
    return HTMLResponse(header("Import Wizard") + '<div class="card"><h2>Import Wizard</h2><ol><li>Upload file</li><li>Preview columns</li><li>Map columns</li><li>Quality check</li><li>Review warnings</li><li>Confirm import</li><li>Import result</li></ol><p class="muted">استعمل صفحة الأدمن للرفع الفعلي في هذه النسخة، والـ Quality Gate يمنع رفع الصفوف التي تحتاج مراجعة كمنتجات جاهزة.</p><a class="btn" href="/admin/products/import">فتح معالج الأدمن</a></div>' + footer())


@router.get("/products/review", response_class=HTMLResponse)
async def review(_: bool = Depends(require_merchant)):
    database.rebuild_review_queue_from_products(limit=300)
    rows = database.get_review_queue(300)
    out = header("مراجعة منتجات التاجر") + '<div class="card"><table><tr><th>ID</th><th>المنتج</th><th>سبب المراجعة</th><th>تعديل</th></tr>'
    for r in rows:
        out += f'<tr><td>{h(r.get("product_id"))}</td><td>{h(r.get("name"))}</td><td>{h(r.get("review_reason"))}</td><td><a class="btn" href="/admin/products/edit/{h(r.get("product_id"))}">Edit</a></td></tr>'
    out += '</table></div>'
    return HTMLResponse(out + footer())


@router.get("/orders", response_class=HTMLResponse)
async def orders(_: bool = Depends(require_merchant)):
    rows = database.get_all_orders()[:200]
    out = header("طلبات التاجر") + '<div class="card"><table><tr><th>ID</th><th>الزبون</th><th>المنتج</th><th>الحالة</th><th>السعر</th></tr>'
    for o in rows:
        out += f'<tr><td>{h(o.get("id"))}</td><td>{h(o.get("customer_phone_masked") or o.get("phone"))}</td><td>{h(o.get("product_name"))}</td><td>{h(o.get("status"))}</td><td>{h(o.get("price"))}</td></tr>'
    out += '</table></div>'
    return HTMLResponse(out + footer())


@router.get("/customer-link", response_class=HTMLResponse)
async def customer_link(_: bool = Depends(require_merchant)):
    settings = database.get_merchant_settings(); number = settings.get("whatsapp_number") or ""
    link = f"https://wa.me/{number}" if number else "أضف رقم البوت في الإعدادات"
    return HTMLResponse(header("رابط الزبائن") + f'<div class="card"><h2>رابط واتساب</h2><p dir="ltr">{h(link)}</p><p class="muted">استخدم لوحة الأدمن لطباعة QR إذا كان qrcode مثبتاً.</p></div>' + footer())


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, _: bool = Depends(require_merchant)):
    s = database.get_merchant_settings()
    out = header("إعدادات التاجر") + f'<div class="card"><form method="post">{csrf_field(request)}'
    for key in ["pharmacy_name", "city", "working_hours", "delivery_enabled", "whatsapp_number", "welcome_message"]:
        out += f'<label>{h(key)}</label><input name="{h(key)}" value="{h(s.get(key,""))}">'
    out += '<button class="btn ok">حفظ</button></form></div>'
    return HTMLResponse(out + footer())


@router.post("/settings")
async def save_settings(request: Request, pharmacy_name: str = Form(""), city: str = Form(""), working_hours: str = Form(""), delivery_enabled: str = Form("false"), whatsapp_number: str = Form(""), welcome_message: str = Form(""), csrf_token: str = Form(""), _: bool = Depends(require_merchant)):
    require_csrf(request, csrf_token)
    for k, v in {"pharmacy_name":pharmacy_name,"city":city,"working_hours":working_hours,"delivery_enabled":delivery_enabled,"whatsapp_number":whatsapp_number,"welcome_message":welcome_message}.items():
        database.set_merchant_setting(k, v)
    database.log_audit("merchant_settings_changed", "merchant", "settings", "default", new_value="merchant_settings", ip=request.client.host if request.client else "")
    return RedirectResponse("/merchant/settings", status_code=303)


@router.get("/catalog-quality", response_class=HTMLResponse)
async def catalog_quality(_: bool = Depends(require_merchant)):
    report = analyze_products(database.load_products())
    out = header("جودة الكتالوج") + f'<div class="grid"><div class="card metric"><span>القرار</span><br><b>{h(report.get("decision"))}</b></div><div class="card metric"><span>Readiness</span><br><b>{report.get("catalog_readiness_score",0)}%</b></div><div class="card metric"><span>Needs review</span><br><b>{len(report.get("review_rows",[]))}</b></div></div>'
    out += '<div class="card"><h2>أسباب الرفض/التحذير</h2><ul>' + ''.join(f'<li>{h(x)}</li>' for x in report.get("reasons", [])) + '</ul></div>'
    return HTMLResponse(out + footer())


@router.get("/failed-queries", response_class=HTMLResponse)
async def failed(_: bool = Depends(require_merchant)):
    rows = database.get_failed_queries(100)
    out = header("الاستعلامات الفاشلة") + '<div class="card"><table><tr><th>الاستعلام</th><th>القرار</th><th>التكرار</th></tr>'
    for r in rows:
        out += f'<tr><td>{h(r.get("raw_query"))}</td><td>{h(r.get("status"))}</td><td>{h(r.get("count"))}</td></tr>'
    out += '</table></div>'
    return HTMLResponse(out + footer())
