#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Final V17.5 production review acceptance tests."""
from __future__ import annotations

import hmac
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

TMP_DIR = tempfile.mkdtemp(prefix="pricebot_v17_5_acceptance_")
os.environ["PRICEBOT_DB_FILE"] = str(Path(TMP_DIR) / "acceptance_v17_5.db")
os.environ.setdefault("PRICEBOT_ADMIN_KEY", "test-admin-key")
os.environ.setdefault("PRICEBOT_DEBUG_ENDPOINTS", "false")
os.environ.setdefault("META_APP_SECRET", "test-meta-secret")
os.environ.setdefault("PRICEBOT_REQUIRE_META_SIGNATURE", "true")
os.environ.setdefault("PRICEBOT_ENV", "production")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

import app  # noqa: E402
import database  # noqa: E402
import matcher_v4 as matcher  # noqa: E402
from matcher_v2 import DecisionType  # noqa: E402


CATALOG = [
    {"id":"F1","product_id":"F1","name":"Flagyl tablet 500mg","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"tablet","strength":"500mg","aliases":"فلاجيل|flagyl tablet","price":"12","available":"متوفر"},
    {"id":"F2","product_id":"F2","name":"Flagyl suppository 500mg","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"suppository","strength":"500mg","aliases":"فلاجيل|flagyl supp","price":"10","available":"متوفر"},
    {"id":"F3","product_id":"F3","name":"Flagyl syrup 125mg/5ml","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"syrup","strength":"125mg/5ml","aliases":"فلاجيل شراب|flagyl syrup","price":"8","available":"متوفر"},
    {"id":"F4","product_id":"F4","name":"Flagyl tablet 250mg","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"tablet","strength":"250mg","aliases":"flagyl tablet 250","price":"9","available":"متوفر"},
    {"id":"C1","product_id":"C1","name":"CeraVe Moisturizing Cream 454g","brand":"CeraVe","product_family":"Moisturizing Cream","category":"cosmetic","form":"cream","size":"454g","aliases":"cerave moisturizing cream","ocr_keywords":"cerave|moisturizing|cream","use_case":"hydration","skin_type":"dry_skin","price":"60","available":"متوفر"},
    {"id":"C2","product_id":"C2","name":"CeraVe Hydrating Cleanser 236ml","brand":"CeraVe","product_family":"Hydrating Cleanser","category":"cosmetic","form":"cleanser","size":"236ml","aliases":"cerave hydrating cleanser","ocr_keywords":"cerave|hydrating|cleanser","use_case":"hydration","skin_type":"dry_skin","price":"70","available":"متوفر"},
    {"id":"C3","product_id":"C3","name":"Bioderma Sebium Gel Moussant 200ml","brand":"Bioderma","product_family":"Sebium Gel Moussant","category":"cosmetic","form":"cleanser","size":"200ml","aliases":"bioderma sebium cleanser","ocr_keywords":"bioderma|sebium|cleanser","use_case":"acne","skin_type":"oily_skin","price":"65","available":"متوفر"},
    {"id":"R1","product_id":"R1","name":"Rilastil Aqua Lotion 200ml","brand":"Rilastil","product_family":"Aqua Lotion","category":"cosmetic","form":"lotion","size":"200ml","aliases":"rilastil aqua lotion","ocr_keywords":"rilastil|aqua|lotion","use_case":"hydration","skin_type":"dry_skin","price":"80","available":"متوفر"},
    {"id":"P123","product_id":"P123","name":"1,2,3 Extra","brand":"","category":"other","aliases":"123|1 2 3 extra","ocr_keywords":"123 extra","price":"5","available":"متوفر"},
]

CI = matcher.build_catalog_index(CATALOG)


def assert_decision(q: str, expected: DecisionType):
    d = matcher.resolve_product_query_from_index(q, CI)
    assert d.decision_type == expected, f"{q}: expected {expected}, got {d.decision_type}, reason={d.reason}, product={(d.product or {}).get('name')}, options={[o.get('name') for o in d.clarification_options]}"
    return d


def test_brand_type_only_and_exact_product_family():
    for q in ["Cerave cream", "Cerave cleanser", "Rilastil lotion", "Bioderma cleanser"]:
        d = assert_decision(q, DecisionType.ASK_CLARIFICATION)
        assert not d.product, q
    d = assert_decision("Cerave moisturizing cream", DecisionType.EXACT_MATCH)
    assert d.product and d.product.get("product_id") == "C1"
    d = assert_decision("Cerave Hydrating Cleanser", DecisionType.EXACT_MATCH)
    assert d.product and d.product.get("product_id") == "C2"


def test_strength_filtered_clarification_options():
    d = assert_decision("فلاجيل 500", DecisionType.ASK_CLARIFICATION)
    names = " | ".join(o.get("name", "") for o in d.clarification_options)
    assert "500" in names
    assert "tablet 500" in names.lower()
    assert "suppository 500" in names.lower()
    assert "125" not in names and "250" not in names, names


def test_invalid_vision_output_rejected():
    raw = {"image_type":"product_packaging", "brand":"CeraVe", "product_name":"Hydrating Cleanser", "price":"50", "availability":"available", "confidence":0.95, "clarity":"good"}
    d1 = matcher.resolve_image_extraction_from_index(raw, CI)
    assert d1.decision_type == DecisionType.LOW_CONFIDENCE and not d1.product
    sanitized = app.validate_ai_data(raw)
    assert sanitized.get("invalid_vision_output") is True
    d2 = matcher.resolve_image_extraction_from_index(sanitized, CI)
    assert d2.decision_type == DecisionType.LOW_CONFIDENCE and d2.reason == "v17_5_invalid_vision_output_claims"


def test_debug_endpoints_closed_and_signature_verification():
    database.init_db()
    client = TestClient(app.app)
    app.PRICEBOT_DEBUG_ENDPOINTS = False
    assert client.get("/test_local?q=Cerave").status_code in {403, 404}
    assert client.get("/test_local_image?brand=CeraVe&name=Hydrating").status_code in {403, 404}
    app.PRICEBOT_DEBUG_ENDPOINTS = True
    assert client.get("/test_local?q=Cerave").status_code == 200
    app.PRICEBOT_DEBUG_ENDPOINTS = False

    app.META_APP_SECRET = "test-meta-secret"
    app.PRICEBOT_REQUIRE_META_SIGNATURE = True
    body = json.dumps({"entry": []}, separators=(",", ":")).encode("utf-8")
    assert client.post("/webhook/whatsapp", data=body, headers={"content-type":"application/json"}).status_code == 403
    assert client.post("/webhook/whatsapp", data=body, headers={"content-type":"application/json", "X-Hub-Signature-256":"sha256=bad"}).status_code == 403
    sig = "sha256=" + hmac.new(app.META_APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    ok = client.post("/webhook/whatsapp", data=body, headers={"content-type":"application/json", "X-Hub-Signature-256":sig})
    assert ok.status_code == 200 and ok.json().get("queued") is True
    # GET verification must remain independent from POST signatures.
    app.VERIFY_TOKEN = "verify-token"
    verify = client.get("/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=verify-token&hub.challenge=abc")
    assert verify.status_code == 200 and verify.text == "abc"


def _jpeg_bytes(image: Image.Image, size=(128, 128), quality=85) -> bytes:
    img = image.convert("RGB").resize(size)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality)
    return out.getvalue()


def test_image_cache_exact_and_perceptual_safety():
    database.init_db()
    base = Image.new("RGB", (256, 256), "white")
    # stable high-contrast shape survives resize/compression average hashing
    for x in range(40, 180):
        for y in range(70, 150):
            base.putpixel((x, y), (0, 0, 0))
    exact_bytes = _jpeg_bytes(base, (256, 256), 95)
    resized_bytes = _jpeg_bytes(base, (128, 128), 60)
    different = Image.new("RGB", (256, 256), "black")
    different_bytes = _jpeg_bytes(different, (128, 128), 80)

    image_hash = app._v17_4_image_hash(exact_bytes)
    phash = app._v17_4_perceptual_hash(exact_bytes)
    vision_output = {"image_type":"product_packaging", "brand":"CeraVe", "product_name":"Hydrating Cleanser", "confidence":0.95, "clarity":"good"}
    database.save_image_cache(image_hash, vision_output, "C2", "EXACT_MATCH", 0.95, phash)
    exact_hit = database.get_image_cache(image_hash)
    assert exact_hit and exact_hit.get("vision_output", {}).get("brand") == "CeraVe"

    resized_hash = app._v17_4_image_hash(resized_bytes)
    assert resized_hash != image_hash
    perceptual_hit = database.get_image_cache_by_perceptual_hash(app._v17_4_perceptual_hash(resized_bytes), 5)
    assert perceptual_hit and perceptual_hit.get("matched_product_id") == "C2"
    no_hit = database.get_image_cache_by_perceptual_hash(app._v17_4_perceptual_hash(different_bytes), 5)
    assert no_hit is None


def main():
    test_brand_type_only_and_exact_product_family()
    test_strength_filtered_clarification_options()
    test_invalid_vision_output_rejected()
    test_debug_endpoints_closed_and_signature_verification()
    test_image_cache_exact_and_perceptual_safety()
    print("ACCEPTANCE_TESTS_FINAL_V17_5_OK")


if __name__ == "__main__":
    main()
