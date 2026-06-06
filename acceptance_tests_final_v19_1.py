#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final V19.1 safety acceptance tests.

Covers the merchant portal hardening layer without changing Matching/Vision.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

TMP_DIR = tempfile.mkdtemp(prefix="pricebot_v19_1_acceptance_")
os.environ["PRICEBOT_DB_FILE"] = str(Path(TMP_DIR) / "acceptance_v19_1.db")
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["ADMIN_SESSION_SECRET"] = "test-admin-session-secret-long"
os.environ["MERCHANT_SESSION_SECRET"] = "test-merchant-session-secret-long"
os.environ["PRICEBOT_DEBUG_ENDPOINTS"] = "false"
os.environ["META_APP_SECRET"] = "test-meta-secret"
os.environ["PRICEBOT_REQUIRE_META_SIGNATURE"] = "true"
os.environ["PRICEBOT_ENV"] = "production"
os.environ.pop("MERCHANT_LOGIN_CODE", None)
os.environ.pop("MERCHANT_PORTAL_ENABLED", None)

from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402
import database  # noqa: E402
from routes import merchant as merchant_routes  # noqa: E402


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, html[:500]
    return match.group(1)


def _reset_merchant_rate_limit() -> None:
    merchant_routes._merchant_login_failures.clear()
    merchant_routes._merchant_login_lock_until.clear()


def _seed_product() -> int:
    database.init_db(); database.ensure_v19_tables()
    with database.get_db_connection() as conn:
        cur = conn.execute("""
            INSERT INTO products(name, normalized_name, brand, category, form, strength, price, available, aliases, product_id)
            VALUES('Merchant Quick Product', 'merchant quick product', 'MerchantBrand', 'medicine', 'tablet', '500mg', '10', 'متوفر', 'merchant quick product', 'MQP1')
        """)
        conn.commit()
        return int(cur.lastrowid)


def _enable_merchant(code: str = "test-merchant-safe-code") -> None:
    os.environ["PRICEBOT_ENV"] = "production"
    os.environ["MERCHANT_PORTAL_ENABLED"] = "true"
    os.environ["MERCHANT_LOGIN_CODE"] = code
    _reset_merchant_rate_limit()


def _merchant_login(client: TestClient, code: str = "test-merchant-safe-code"):
    page = client.get("/merchant/login")
    assert page.status_code == 200
    csrf = _extract_csrf(page.text)
    res = client.post("/merchant/login", data={"code": code, "csrf_token": csrf}, follow_redirects=False)
    assert res.status_code in {302, 303}
    return res


def test_merchant_disabled_without_code_in_production():
    os.environ.pop("MERCHANT_LOGIN_CODE", None)
    os.environ.pop("MERCHANT_PORTAL_ENABLED", None)
    os.environ["PRICEBOT_ENV"] = "production"
    _reset_merchant_rate_limit()
    client = TestClient(app.app, base_url="https://testserver")
    assert client.get("/merchant/login").status_code == 503
    assert client.get("/merchant/dashboard").status_code == 503


def test_default_merchant_code_is_not_accepted():
    os.environ["PRICEBOT_ENV"] = "production"
    os.environ["MERCHANT_PORTAL_ENABLED"] = "true"
    os.environ["MERCHANT_LOGIN_CODE"] = "merchant"
    _reset_merchant_rate_limit()
    client = TestClient(app.app, base_url="https://testserver")
    assert client.get("/merchant/login").status_code == 503


def test_merchant_login_requires_csrf_and_secure_cookie():
    _enable_merchant()
    client = TestClient(app.app, base_url="https://testserver")
    assert client.post("/merchant/login", data={"code": "test-merchant-safe-code"}).status_code == 403
    page = client.get("/merchant/login")
    assert "Pilot default" not in page.text and "merchant." not in page.text.lower()
    csrf = _extract_csrf(page.text)
    res = client.post("/merchant/login", data={"code": "test-merchant-safe-code", "csrf_token": csrf}, follow_redirects=False)
    assert res.status_code in {302, 303}
    set_cookie = "; ".join(res.headers.get_list("set-cookie"))
    assert merchant_routes.MERCHANT_COOKIE in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    assert "Secure" in set_cookie
    assert "Max-Age=28800" in set_cookie or "max-age=28800" in set_cookie.lower()


def test_merchant_post_routes_require_csrf():
    _enable_merchant()
    pid = _seed_product()
    client = TestClient(app.app, base_url="https://testserver")
    _merchant_login(client)
    assert client.post(f"/merchant/products/{pid}/quick", data={"price":"12", "available":"متوفر"}).status_code == 403
    assert client.post("/merchant/settings", data={"pharmacy_name":"Unsafe Change"}).status_code == 403

    products_page = client.get("/merchant/products")
    csrf = _extract_csrf(products_page.text)
    ok = client.post(f"/merchant/products/{pid}/quick", data={"price":"12", "available":"متوفر", "csrf_token": csrf}, follow_redirects=False)
    assert ok.status_code in {302, 303}

    settings_page = client.get("/merchant/settings")
    csrf2 = _extract_csrf(settings_page.text)
    ok2 = client.post("/merchant/settings", data={"pharmacy_name":"Safe Merchant Pharmacy", "csrf_token": csrf2}, follow_redirects=False)
    assert ok2.status_code in {302, 303}


def test_merchant_login_rate_limit():
    _enable_merchant()
    client = TestClient(app.app, base_url="https://testserver")
    headers = {"x-forwarded-for": "198.51.100.25"}
    last_status = None
    for _ in range(merchant_routes.MERCHANT_LOGIN_RATE_LIMIT_MAX + 1):
        page = client.get("/merchant/login", headers=headers)
        csrf = _extract_csrf(page.text)
        last_status = client.post("/merchant/login", data={"code":"wrong-code", "csrf_token":csrf}, headers=headers).status_code
    assert last_status == 429


def main():
    test_merchant_disabled_without_code_in_production()
    test_default_merchant_code_is_not_accepted()
    test_merchant_login_requires_csrf_and_secure_cookie()
    test_merchant_post_routes_require_csrf()
    test_merchant_login_rate_limit()
    print("ACCEPTANCE_TESTS_FINAL_V19_1_OK")


if __name__ == "__main__":
    main()
