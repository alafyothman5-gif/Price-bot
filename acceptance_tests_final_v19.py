#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final V19 company-level acceptance tests.

These tests verify that V18 safety rules still hold while V19 platform layers
(catalog quality, review queue, merchant portal, audit, AI usage) are present.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from pathlib import Path

TMP_DIR = tempfile.mkdtemp(prefix="pricebot_v19_acceptance_")
os.environ["PRICEBOT_DB_FILE"] = str(Path(TMP_DIR) / "acceptance_v19.db")
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["ADMIN_SESSION_SECRET"] = "test-admin-session-secret-long"
os.environ["PRICEBOT_DEBUG_ENDPOINTS"] = "false"
os.environ["META_APP_SECRET"] = "test-meta-secret"
os.environ["PRICEBOT_REQUIRE_META_SIGNATURE"] = "true"
os.environ["PRICEBOT_ENV"] = "production"
os.environ["PHARMACY_NAME"] = "Test Pharmacy V19"
os.environ["MERCHANT_LOGIN_CODE"] = "test-merchant-v19-code"
os.environ["MERCHANT_PORTAL_ENABLED"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402
import admin  # noqa: E402
import database  # noqa: E402
import matcher_v4 as matcher  # noqa: E402
from matcher_v2 import DecisionType  # noqa: E402
from services.catalog_quality import analyze_products, quality_gate  # noqa: E402

CATALOG = [
    {"id":"F1","product_id":"F1","name":"Flagyl tablet 500mg","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"tablet","strength":"500mg","aliases":"فلاجيل|flagyl tablet","price":"12","available":"متوفر"},
    {"id":"F2","product_id":"F2","name":"Flagyl suppository 500mg","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"suppository","strength":"500mg","aliases":"فلاجيل|flagyl supp","price":"10","available":"متوفر"},
    {"id":"F3","product_id":"F3","name":"Flagyl syrup 125mg/5ml","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"syrup","strength":"125mg/5ml","aliases":"فلاجيل شراب|flagyl syrup","price":"8","available":"متوفر"},
    {"id":"A1","product_id":"A1","name":"Amoclan syrup 156mg/5ml","brand":"Amoclan","product_family":"Amoclan","category":"medicine","active_ingredient":"amoxicillin clavulanate","form":"syrup","strength":"156mg/5ml","aliases":"amoclan syrup 156","price":"18","available":"متوفر"},
    {"id":"A2","product_id":"A2","name":"Amoclan syrup 457mg/5ml","brand":"Amoclan","product_family":"Amoclan","category":"medicine","active_ingredient":"amoxicillin clavulanate","form":"syrup","strength":"457mg/5ml","aliases":"amoclan syrup 457","price":"22","available":"متوفر"},
    {"id":"C1","product_id":"C1","name":"CeraVe Moisturizing Cream 454g","brand":"CeraVe","product_family":"Moisturizing Cream","category":"cosmetic","form":"cream","size":"454g","aliases":"cerave moisturizing cream","ocr_keywords":"cerave|moisturizing|cream","use_case":"hydration","skin_type":"dry_skin","price":"60","available":"متوفر"},
    {"id":"C2","product_id":"C2","name":"CeraVe Hydrating Cleanser 236ml","brand":"CeraVe","product_family":"Hydrating Cleanser","category":"cosmetic","form":"cleanser","size":"236ml","aliases":"cerave hydrating cleanser","ocr_keywords":"cerave|hydrating|cleanser","use_case":"hydration","skin_type":"dry_skin","price":"70","available":"متوفر"},
]
CI = matcher.build_catalog_index(CATALOG)


def assert_decision(q: str, expected: DecisionType):
    d = matcher.resolve_product_query_from_index(q, CI)
    assert d.decision_type == expected, f"{q}: expected {expected}, got {d.decision_type}, reason={d.reason}, product={(d.product or {}).get('name')}"
    return d


def _signed_body(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _extract_csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, html[:600]
    return m.group(1)


def _login_admin(client: TestClient):
    page = client.get("/admin/login")
    assert page.status_code == 200
    csrf = _extract_csrf(page.text)
    res = client.post("/admin/login", data={"key":"test-admin-password", "csrf_token":csrf}, follow_redirects=False)
    assert res.status_code in {302, 303}


def seed_product() -> int:
    database.init_db(); database.ensure_v19_tables()
    with database.get_db_connection() as conn:
        cur = conn.execute("""
            INSERT INTO products(name, normalized_name, brand, category, form, strength, price, available, aliases, product_id)
            VALUES('Test Medicine 500mg tablet', 'test medicine 500mg tablet', 'TestBrand', 'medicine', 'tablet', '500mg', '10', 'متوفر', 'test medicine 500', 'TM1')
        """)
        conn.commit()
        return int(cur.lastrowid)


def test_v18_matching_rules_still_pass():
    assert_decision("Cerave", DecisionType.ASK_CLARIFICATION)      # brand-only no price
    assert_decision("غسول", DecisionType.ASK_CLARIFICATION)        # type-only no price
    assert_decision("Cerave cream", DecisionType.ASK_CLARIFICATION)  # brand+type no price
    assert_decision("Rilastil xerolact PB", DecisionType.NOT_AVAILABLE)
    assert_decision("فلاجيل", DecisionType.ASK_CLARIFICATION)     # ambiguous medicine form
    assert_decision("Amoclan syrup", DecisionType.ASK_CLARIFICATION)  # ambiguous strength
    med_missing = assert_decision("Panadol 500", DecisionType.NOT_AVAILABLE)
    assert not med_missing.alternatives, "medicine alternatives forbidden"
    cosmetic_missing = assert_decision("Cerave SA Cleanser", DecisionType.COSMETIC_ALTERNATIVES)
    assert cosmetic_missing.alternatives
    assert all(str(a.get("form") or "").lower() == "cleanser" for a in cosmetic_missing.alternatives)
    invalid = matcher.resolve_image_extraction_from_index({"invalid_vision_output": True, "brand":"CeraVe", "product_name":"Hydrating Cleanser", "confidence":0.95}, CI)
    assert invalid.decision_type == DecisionType.LOW_CONFIDENCE
    blurry = matcher.resolve_image_extraction_from_index({"image_type":"unclear", "confidence":0.9, "clarity":"bad"}, CI)
    assert blurry.decision_type == DecisionType.IMAGE_UNCLEAR
    weak = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging", "visible_text":"cream", "confidence":0.95, "clarity":"good"}, CI)
    assert weak.decision_type == DecisionType.LOW_CONFIDENCE


def test_v19_catalog_quality_gate_and_review_queue():
    bad = [
        {"id":"1", "name":"Bad Cream", "brand":"", "category":"cosmetic", "form":"", "aliases":"cream", "price":""},
        {"id":"2", "name":"Bad Medicine 500mg", "brand":"", "category":"medicine", "form":"", "strength":"", "aliases":"same", "price":"abc"},
        {"id":"3", "name":"Bad Medicine 500mg", "brand":"", "category":"medicine", "form":"", "strength":"", "aliases":"same", "price":""},
    ]
    report = analyze_products(bad)
    assert report["issue_counts"].get("missing_form_or_type", 0) >= 2
    assert report["issue_counts"].get("duplicate_alias", 0) >= 1
    decision, reasons, _ = quality_gate(bad)
    assert decision == "REJECT" and reasons

    database.init_db(); database.ensure_v19_tables()
    with database.get_db_connection() as conn:
        conn.execute("INSERT INTO products(name, normalized_name, brand, category, form, price, aliases) VALUES('Review Bad Product', 'review bad product', '', 'medicine', '', '', 'cream')")
        conn.commit()
    count = database.rebuild_review_queue_from_products()
    rows = database.get_review_queue(20)
    assert count >= 1 and any("Review Bad Product" in r.get("name", "") for r in rows)


def test_v19_admin_security_routes_and_dynamic_settings():
    database.init_db(); database.ensure_v19_tables()
    client = TestClient(app.app, base_url="https://testserver")
    app.PRICEBOT_DEBUG_ENDPOINTS = False
    assert client.get("/test_local?q=Cerave").status_code in {403, 404}
    app.META_APP_SECRET = "test-meta-secret"; app.PRICEBOT_REQUIRE_META_SIGNATURE = True
    body = json.dumps({"entry": []}, separators=(",", ":")).encode()
    assert client.post("/webhook/whatsapp", data=body, headers={"content-type":"application/json"}).status_code == 403
    assert client.post("/webhook/whatsapp", data=body, headers={"content-type":"application/json", "X-Hub-Signature-256":"sha256=bad"}).status_code == 403
    assert client.post("/webhook/whatsapp", data=body, headers={"content-type":"application/json", "X-Hub-Signature-256":_signed_body(app.META_APP_SECRET, body)}).status_code == 200
    assert client.get("/health").json() == {"ok": True, "service": "pricebot"}

    _login_admin(client)
    database.set_merchant_setting("pharmacy_name", "Dynamic Pharmacy Name")
    page = client.get("/admin/dashboard")
    assert page.status_code == 200 and "Dynamic Pharmacy Name" in page.text
    for path in ["/admin/products/review", "/admin/products/duplicates", "/admin/quality-dashboard", "/admin/learning-center", "/admin/ai-usage", "/admin/security", "/admin/logs", "/admin/merchants", "/admin/vision-tests", "/admin/golden-tests"]:
        assert client.get(path).status_code == 200, path


def test_v19_merchant_portal_product_validation_audit_ai_usage():
    pid = seed_product()
    client = TestClient(app.app, base_url="https://testserver")
    _login_admin(client)
    edit_page = client.get(f"/admin/products/edit/{pid}")
    csrf = _extract_csrf(edit_page.text)
    invalid = client.post(f"/admin/products/edit/{pid}", data={"csrf_token": csrf, "name":"Test Medicine", "category":"medicine", "form":"", "strength":"", "price":"abc"})
    assert invalid.status_code == 400
    valid = client.post(f"/admin/products/edit/{pid}", data={"csrf_token": csrf, "name":"Test Medicine 500mg tablet", "category":"medicine", "form":"tablet", "strength":"500mg", "price":"11", "available":"متوفر"}, follow_redirects=False)
    assert valid.status_code in {302, 303}
    logs = database.get_audit_logs(20)
    assert any(r.get("event_type") == "product_edit" for r in logs)

    database.log_ai_usage_v19(customer_phone_masked="21891****659", model="test-model", purpose="vision", image_count=1, cost_estimate=0.001, success=True)
    ai_rows = database.get_ai_usage_logs(10)
    assert any(r.get("model") == "test-model" for r in ai_rows)

    assert client.get("/merchant/login").status_code == 200
    logged = client.post("/merchant/login", data={"code":"test-merchant-v19-code", "csrf_token":_extract_csrf(client.get("/merchant/login").text)}, follow_redirects=False)
    assert logged.status_code in {302, 303}
    for path in ["/merchant/dashboard", "/merchant/products", "/merchant/products/import", "/merchant/products/review", "/merchant/orders", "/merchant/customer-link", "/merchant/settings", "/merchant/catalog-quality", "/merchant/failed-queries"]:
        assert client.get(path).status_code == 200, path


def main():
    test_v18_matching_rules_still_pass()
    test_v19_catalog_quality_gate_and_review_queue()
    test_v19_admin_security_routes_and_dynamic_settings()
    test_v19_merchant_portal_product_validation_audit_ai_usage()
    print("ACCEPTANCE_TESTS_FINAL_V19_OK")

if __name__ == "__main__":
    main()
