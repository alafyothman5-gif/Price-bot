#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance tests for matcher_v3 strict safe resolver."""
from matcher_v3 import DecisionType, resolve_product_query, resolve_image_extraction, generate_catalog_quality_report

CATALOG = [
    {"id": 1, "name": "Cerave moisturising lotion Baume", "brand": "CeraVe", "form": "balm", "aliases": "Cerave baume|CeraVe balm", "price": "100", "available": "متوفر", "category": "cosmetic", "image_ocr_keywords": "cerave baume moisturizing balm"},
    {"id": 2, "name": "CeraVe H.A Serum", "brand": "CeraVe", "form": "serum", "aliases": "Cerave serum|HA serum", "price": "120", "available": "متوفر", "category": "cosmetic"},
    {"id": 3, "name": "CeraVe Daily Moisturizing Lotion", "brand": "CeraVe", "form": "lotion", "price": "110", "available": "متوفر", "category": "cosmetic"},
    {"id": 4, "name": "La Roche Effaclar Purifying Foaming Gel Cleanser", "brand": "La Roche", "form": "cleanser", "aliases": "laroche effaclar cleanser", "price": "95", "available": "متوفر", "category": "cosmetic", "use_case": "acne"},
    {"id": 5, "name": "Bioderma Sebium Gel Moussant Cleanser", "brand": "Bioderma", "form": "cleanser", "price": "90", "available": "متوفر", "category": "cosmetic", "use_case": "acne"},
    {"id": 6, "name": "Flagyl tablet 250mg", "brand": "Flagyl", "form": "tablet", "strength": "250mg", "price": "10", "available": "متوفر", "category": "medicine", "active_ingredient": "metronidazole"},
    {"id": 7, "name": "Flagyl tablet 500mg", "brand": "Flagyl", "form": "tablet", "strength": "500mg", "price": "16", "available": "متوفر", "category": "medicine", "active_ingredient": "metronidazole"},
    {"id": 8, "name": "Flagyl syrup 125mg", "brand": "Flagyl", "form": "syrup", "strength": "125mg", "price": "18", "available": "متوفر", "category": "medicine", "active_ingredient": "metronidazole"},
    {"id": 9, "name": "Flagyl suppository 500mg", "brand": "Flagyl", "form": "suppository", "strength": "500mg", "price": "20", "available": "متوفر", "category": "medicine", "active_ingredient": "metronidazole"},
    {"id": 10, "name": "Panadol Advance tablet", "brand": "Panadol", "form": "tablet", "price": "12", "available": "متوفر", "category": "medicine", "active_ingredient": "paracetamol"},
    {"id": 11, "name": "Panadol Baby Syrup", "brand": "Panadol", "form": "syrup", "price": "14", "available": "متوفر", "category": "medicine", "active_ingredient": "paracetamol"},
    {"id": 12, "name": "Rilastil Xerolact PB Balm", "brand": "Rilastil", "form": "balm", "aliases": "rilastil xerolact pb", "price": "130", "available": "متوفر", "category": "cosmetic", "use_case": "dry_skin"},
    {"id": 13, "name": "Adult Diaper Large", "brand": "Care", "form": "", "price": "30", "available": "متوفر", "category": "other"},
    {"id": 14, "name": "بديل الزيت للشعر", "brand": "Hair", "form": "oil", "price": "22", "available": "متوفر", "category": "cosmetic"},
]

CATALOG_NO_RILASTIL = [x for x in CATALOG if x["id"] != 12]
CATALOG_NO_CERAVE_CLEANSER = CATALOG
CATALOG_WITH_CERAVE_CLEANSER = CATALOG + [
    {"id": 20, "name": "CeraVe Hydrating Cleanser", "brand": "CeraVe", "form": "cleanser", "aliases": "cerave hydrating cleanser", "price": "105", "available": "متوفر", "category": "cosmetic", "use_case": "hydration"}
]

def assert_decision(query, catalog, expected):
    d = resolve_product_query(query, catalog)
    assert d.decision_type == expected, f"{query}: expected {expected}, got {d.decision_type} reason={d.reason} product={(d.product or {}).get('name')}"
    return d

# 1 specific product not in catalog: no random products/alternatives
r = assert_decision("Rilastil xerolact PB متوفر", CATALOG_NO_RILASTIL, DecisionType.NOT_AVAILABLE)
assert not r.product and not r.alternatives

# 2 specific product in catalog: exact/safe match
r = assert_decision("Rilastil xerolact PB متوفر", CATALOG, DecisionType.EXACT_MATCH)
assert "Xerolact" in r.product["name"]

# 3 brand-only Rilastil: ask only same brand if brand exists, not any other brand
r = assert_decision("Rilastil", CATALOG, DecisionType.ASK_CLARIFICATION)
assert r.clarification_options and all("Rilastil" in o.get("name", "") for o in r.clarification_options)
r = assert_decision("Rilastil", CATALOG_NO_RILASTIL, DecisionType.LOW_CONFIDENCE)

# 4 CeraVe cleanser not present: not available, no serum/lotion/cream
r = resolve_product_query("Cerave Hydrating Cleanser", CATALOG_NO_CERAVE_CLEANSER)
assert r.decision_type in {DecisionType.NOT_AVAILABLE, DecisionType.COSMETIC_ALTERNATIVES}
for alt in r.alternatives:
    assert "serum" not in alt.get("name", "").lower() and "lotion" not in alt.get("name", "").lower()

# 5 brand-only Cerave asks, no random product
r = assert_decision("Cerave", CATALOG, DecisionType.ASK_CLARIFICATION)
assert len(r.clarification_options) >= 2

# 6 lotion alone must not choose serum/random
r = resolve_product_query("lotion", CATALOG)
assert r.decision_type in {DecisionType.ASK_CLARIFICATION, DecisionType.LOW_CONFIDENCE}
assert not r.product

# 7 Flagyl general asks variants
r = assert_decision("فلاجيل", CATALOG, DecisionType.ASK_CLARIFICATION)
assert len(r.clarification_options) >= 3

# 8 Flagyl syrup returns syrup only if one syrup
r = assert_decision("فلاجيل شراب", CATALOG, DecisionType.EXACT_MATCH)
assert "syrup" in r.product["name"].lower()

# 9 Flagyl 500 asks if tablet and suppository exist
r = assert_decision("فلاجيل 500", CATALOG, DecisionType.ASK_CLARIFICATION)
names = " ".join(o.get("name", "") for o in r.clarification_options).lower()
assert "tablet" in names and "suppository" in names

# 10 Image Rilastil missing -> NOT_AVAILABLE, no general alternatives
r = resolve_image_extraction({"brand": "Rilastil", "product_name": "Xerolact PB", "type": "balm", "confidence": 0.93, "clarity": "good"}, CATALOG_NO_RILASTIL)
assert r.decision_type == DecisionType.NOT_AVAILABLE and not r.alternatives

# 11 Image CeraVe cleanser missing -> NOT_AVAILABLE or cleanser alternatives only
r = resolve_image_extraction({"brand": "CeraVe", "product_name": "Hydrating Cleanser", "type": "cleanser", "confidence": 0.93, "clarity": "good"}, CATALOG_NO_CERAVE_CLEANSER)
assert r.decision_type in {DecisionType.NOT_AVAILABLE, DecisionType.COSMETIC_ALTERNATIVES}
for alt in r.alternatives:
    assert "cleanser" in alt.get("name", "").lower()

# 12 Image generic cream -> low confidence / unclear, no products
r = resolve_image_extraction({"brand": "", "product_name": "", "type": "cream", "confidence": 0.80, "clarity": "good"}, CATALOG)
assert r.decision_type in {DecisionType.LOW_CONFIDENCE, DecisionType.IMAGE_UNCLEAR}
assert not r.product and not r.alternatives

# 13 Unknown specific brand + product family -> NOT_AVAILABLE, no general fuzzy
r = assert_decision("UnknownBrand SuperLine PB", CATALOG, DecisionType.NOT_AVAILABLE)
assert not r.product and not r.alternatives

# Positive cleanser when present
r = assert_decision("CeraVe Hydrating Cleanser", CATALOG_WITH_CERAVE_CLEANSER, DecisionType.EXACT_MATCH)
assert "cleanser" in r.product["name"].lower()

# Catalog report generator smoke test
path = generate_catalog_quality_report(CATALOG, "/tmp/catalog_quality_report_v3.csv")
assert path

print("ACCEPTANCE_TESTS_V3_OK")
