#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final V18 launch-ready acceptance tests.

These tests focus on launch packaging and safety rails around the already
accepted V17.5 strict matching/vision behavior.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from pathlib import Path

TMP_DIR = tempfile.mkdtemp(prefix="pricebot_v18_acceptance_")
os.environ["PRICEBOT_DB_FILE"] = str(Path(TMP_DIR) / "acceptance_v18.db")
os.environ["ADMIN_PASSWORD"] = "test-admin-password"
os.environ["ADMIN_SESSION_SECRET"] = "test-admin-session-secret-long"
os.environ["PRICEBOT_DEBUG_ENDPOINTS"] = "false"
os.environ["META_APP_SECRET"] = "test-meta-secret"
os.environ["PRICEBOT_REQUIRE_META_SIGNATURE"] = "true"
os.environ["PRICEBOT_ENV"] = "production"

from fastapi.testclient import TestClient  # noqa: E402

import app  # noqa: E402
import admin  # noqa: E402
import database  # noqa: E402
import matcher_v4 as matcher  # noqa: E402
from matcher_v2 import DecisionType  # noqa: E402


CATALOG = [
    {"id":"F1","product_id":"F1","name":"Flagyl tablet 500mg","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"tablet","strength":"500mg","aliases":"فلاجيل|flagyl tablet","price":"12","available":"متوفر"},
    {"id":"F2","product_id":"F2","name":"Flagyl suppository 500mg","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"suppository","strength":"500mg","aliases":"فلاجيل|flagyl supp","price":"10","available":"متوفر"},
    {"id":"F3","product_id":"F3","name":"Flagyl syrup 125mg/5ml","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"syrup","strength":"125mg/5ml","aliases":"فلاجيل شراب|flagyl syrup","price":"8","available":"متوفر"},
    {"id":"F4","product_id":"F4","name":"Flagyl syrup 250mg/5ml","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"syrup","strength":"250mg/5ml","aliases":"flagyl syrup 250","price":"9","available":"متوفر"},
    {"id":"A1","product_id":"A1","name":"Amoclan syrup 156mg/5ml","brand":"Amoclan","product_family":"Amoclan","category":"medicine","active_ingredient":"amoxicillin clavulanate","form":"syrup","strength":"156mg/5ml","aliases":"amoclan syrup 156","price":"18","available":"متوفر"},
    {"id":"A2","product_id":"A2","name":"Amoclan syrup 457mg/5ml","brand":"Amoclan","product_family":"Amoclan","category":"medicine","active_ingredient":"amoxicillin clavulanate","form":"syrup","strength":"457mg/5ml","aliases":"amoclan syrup 457","price":"22","available":"متوفر"},
    {"id":"C1","product_id":"C1","name":"CeraVe Moisturizing Cream 454g","brand":"CeraVe","product_family":"Moisturizing Cream","category":"cosmetic","form":"cream","size":"454g","aliases":"cerave moisturizing cream","ocr_keywords":"cerave|moisturizing|cream","use_case":"hydration","skin_type":"dry_skin","price":"60","available":"متوفر"},
    {"id":"C2","product_id":"C2","name":"CeraVe Hydrating Cleanser 236ml","brand":"CeraVe","product_family":"Hydrating Cleanser","category":"cosmetic","form":"cleanser","size":"236ml","aliases":"cerave hydrating cleanser","ocr_keywords":"cerave|hydrating|cleanser","use_case":"hydration","skin_type":"dry_skin","price":"70","available":"متوفر"},
    {"id":"C3","product_id":"C3","name":"CeraVe Foaming Cleanser 236ml","brand":"CeraVe","product_family":"Foaming Cleanser","category":"cosmetic","form":"cleanser","size":"236ml","aliases":"cerave foaming cleanser","ocr_keywords":"cerave|foaming|cleanser","use_case":"acne","skin_type":"oily_skin","price":"71","available":"متوفر"},
    {"id":"R1","product_id":"R1","name":"Rilastil Aqua Lotion 200ml","brand":"Rilastil","product_family":"Aqua Lotion","category":"cosmetic","form":"lotion","size":"200ml","aliases":"rilastil aqua lotion","ocr_keywords":"rilastil|aqua|lotion","use_case":"hydration","skin_type":"dry_skin","price":"80","available":"متوفر"},
]
CI = matcher.build_catalog_index(CATALOG)


def assert_decision(q: str, expected: DecisionType):
    d = matcher.resolve_product_query_from_index(q, CI)
    assert d.decision_type == expected, f"{q}: expected {expected}, got {d.decision_type}, reason={d.reason}, product={(d.product or {}).get('name')}, options={[o.get('name') for o in d.clarification_options]}, alternatives={[a.get('name') for a in d.alternatives]}"
    return d


def test_matching_safety_rules():
    assert_decision("Cerave", DecisionType.ASK_CLARIFICATION)      # brand-only
    assert_decision("غسول", DecisionType.ASK_CLARIFICATION)        # type-only
    assert_decision("Cerave cream", DecisionType.ASK_CLARIFICATION)  # brand + type only
    assert_decision("Rilastil xerolact PB", DecisionType.NOT_AVAILABLE)
    assert_decision("فلاجيل", DecisionType.ASK_CLARIFICATION)     # medicine ambiguous form
    assert_decision("Amoclan syrup", DecisionType.ASK_CLARIFICATION)  # medicine ambiguous strength
    med_missing = assert_decision("Panadol 500", DecisionType.NOT_AVAILABLE)
    assert not med_missing.alternatives, "medicine alternatives must be forbidden"
    cosmetic_missing = assert_decision("Cerave SA Cleanser", DecisionType.COSMETIC_ALTERNATIVES)
    assert cosmetic_missing.alternatives, "expected strict same-type cosmetic alternatives"
    assert all(str(a.get("form") or "").lower() == "cleanser" for a in cosmetic_missing.alternatives)


def test_vision_safety_rules():
    blurry = matcher.resolve_image_extraction_from_index({"image_type":"unclear", "confidence":0.95, "clarity":"bad"}, CI)
    assert blurry.decision_type == DecisionType.IMAGE_UNCLEAR
    weak = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging", "visible_text":"cream", "confidence":0.95, "clarity":"good"}, CI)
    assert weak.decision_type == DecisionType.LOW_CONFIDENCE
    invalid_raw = {"image_type":"product_packaging", "brand":"CeraVe", "product_name":"Hydrating Cleanser", "price":"50", "availability":"available", "confidence":0.95, "clarity":"good"}
    sanitized = app.validate_ai_data(invalid_raw)
    invalid = matcher.resolve_image_extraction_from_index(sanitized, CI)
    assert invalid.decision_type == DecisionType.LOW_CONFIDENCE
    multi = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging", "brand":"CeraVe", "product_names":["Hydrating Cleanser", "Moisturizing Cream"], "image_quality":"multiple_products", "confidence":0.95, "clarity":"good"}, CI)
    assert multi.decision_type in {DecisionType.LOW_CONFIDENCE, DecisionType.ASK_CLARIFICATION}


def _signed_body(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _extract_csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, html[:500]
    return m.group(1)


def test_launch_security_endpoints_and_admin():
    database.init_db()
    client = TestClient(app.app, base_url="https://testserver")

    app.PRICEBOT_DEBUG_ENDPOINTS = False
    assert client.get("/test_local?q=Cerave").status_code in {403, 404}
    assert client.get("/test_local_image?brand=CeraVe&name=Hydrating").status_code in {403, 404}

    app.META_APP_SECRET = "test-meta-secret"
    app.PRICEBOT_REQUIRE_META_SIGNATURE = True
    body = json.dumps({"entry": []}, separators=(",", ":")).encode("utf-8")
    assert client.post("/webhook/whatsapp", data=body, headers={"content-type":"application/json"}).status_code == 403
    assert client.post("/webhook/whatsapp", data=body, headers={"content-type":"application/json", "X-Hub-Signature-256":"sha256=bad"}).status_code == 403
    ok = client.post("/webhook/whatsapp", data=body, headers={"content-type":"application/json", "X-Hub-Signature-256":_signed_body(app.META_APP_SECRET, body)})
    assert ok.status_code == 200

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"ok": True, "service": "pricebot"}
    leaked = json.dumps(health.json()).lower()
    for forbidden in ["token", "secret", "password", "openrouter", "products_count", "queue", "db"]:
        assert forbidden not in leaked

    # Admin login must require CSRF and then issue an expiring signed secure session.
    login_page = client.get("/admin/login")
    csrf = _extract_csrf(login_page.text)
    assert client.post("/admin/login", data={"key":"test-admin-password"}).status_code == 403
    logged = client.post("/admin/login", data={"key":"test-admin-password", "csrf_token":csrf}, follow_redirects=False)
    assert logged.status_code in {302, 303}
    session_cookie = client.cookies.get(admin.SESSION_COOKIE)
    assert session_cookie and ":" in session_cookie

    # Authenticated POST without CSRF must be rejected.
    assert client.post("/admin/orders/update/1", data={"new_status":"completed"}).status_code == 403

    # Login rate limit: after repeated bad credentials, the IP is temporarily locked.
    bad_client = TestClient(app.app, base_url="https://testserver")
    headers = {"x-forwarded-for": "203.0.113.18"}
    last_status = None
    for _ in range(admin.LOGIN_RATE_LIMIT_MAX + 1):
        page = bad_client.get("/admin/login", headers=headers)
        bad_csrf = _extract_csrf(page.text)
        last_status = bad_client.post("/admin/login", data={"key":"bad", "csrf_token":bad_csrf}, headers=headers).status_code
    assert last_status == 429


def main():
    test_matching_safety_rules()
    test_vision_safety_rules()
    test_launch_security_endpoints_and_admin()
    print("ACCEPTANCE_TESTS_FINAL_V18_OK")


if __name__ == "__main__":
    main()
