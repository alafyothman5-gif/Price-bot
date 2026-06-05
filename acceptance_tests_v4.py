#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance tests for Product Intelligence Engine V4.

Run:
    python acceptance_tests_v4.py
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path

_TEST_DB = Path("/tmp/pricebot_acceptance_v4.db")
os.environ.setdefault("PRICEBOT_DB_FILE", str(_TEST_DB))
atexit.register(lambda: _TEST_DB.exists() and _TEST_DB.unlink())

import matcher_v4 as matcher
from matcher_v2 import DecisionType

CATALOG = [
    {"id": 1, "name": "Flagyl 250 mg tablets", "brand": "flagyl", "form": "tablet", "strength": "250mg", "active_ingredient": "metronidazole", "price": "10", "available": "متوفر", "category": "medicine"},
    {"id": 2, "name": "Flagyl 500 mg tablets", "brand": "flagyl", "form": "tablet", "strength": "500mg", "active_ingredient": "metronidazole", "price": "12", "available": "متوفر", "category": "medicine"},
    {"id": 3, "name": "Flagyl syrup 125mg/5ml", "brand": "flagyl", "form": "syrup", "strength": "125mg/5ml", "active_ingredient": "metronidazole", "price": "15", "available": "متوفر", "category": "medicine"},
    {"id": 4, "name": "Panadol Advance 500mg tablets", "brand": "panadol", "form": "tablet", "strength": "500mg", "active_ingredient": "paracetamol", "price": "8", "available": "متوفر", "category": "medicine"},
    {"id": 5, "name": "Panadol Extra tablets", "brand": "panadol", "form": "tablet", "strength": "500mg/65mg", "active_ingredient": "paracetamol caffeine", "price": "9", "available": "متوفر", "category": "medicine"},
    {"id": 6, "name": "Amoclan 625mg tablets", "brand": "amoclan", "form": "tablet", "strength": "625mg", "active_ingredient": "amoxicillin clavulanate", "substitution_group": "amoxclav_625", "price": "20", "available": "متوفر", "category": "medicine"},
    {"id": 7, "name": "Augmentin 625mg tablets", "brand": "augmentin", "form": "tablet", "strength": "625mg", "active_ingredient": "amoxicillin clavulanate", "substitution_group": "amoxclav_625", "price": "25", "available": "متوفر", "category": "medicine"},
    {"id": 8, "name": "CeraVe Hydrating Cleanser 236ml", "brand": "cerave", "form": "cleanser", "size": "236ml", "category": "cosmetic", "price": "50", "available": "متوفر", "use_case": "hydration", "skin_type": "dry_skin", "aliases": "cerave hydrating cleanser"},
    {"id": 9, "name": "CeraVe Foaming Cleanser 236ml", "brand": "cerave", "form": "cleanser", "size": "236ml", "category": "cosmetic", "price": "55", "available": "متوفر", "use_case": "oily_skin", "skin_type": "oily_skin"},
    {"id": 10, "name": "CeraVe Moisturizing Lotion 236ml", "brand": "cerave", "form": "lotion", "size": "236ml", "category": "cosmetic", "price": "60", "available": "متوفر", "use_case": "hydration", "skin_type": "dry_skin"},
    {"id": 11, "name": "CeraVe Hydrating Cleanser 473ml", "brand": "cerave", "form": "cleanser", "size": "473ml", "category": "cosmetic", "price": "80", "available": "متوفر", "use_case": "hydration", "skin_type": "dry_skin"},
    {"id": 12, "name": "Rilastil Xerolact Balm 400ml", "brand": "rilastil", "form": "balm", "size": "400ml", "category": "cosmetic", "price": "70", "available": "متوفر", "use_case": "dry_skin", "skin_type": "dry_skin"},
    {"id": 13, "name": "Bioderma Sebium Gel Moussant 200ml", "brand": "bioderma", "form": "cleanser", "size": "200ml", "category": "cosmetic", "price": "65", "available": "متوفر", "use_case": "acne", "skin_type": "oily_skin"},
]

CI = matcher.build_catalog_index(CATALOG)


def resolve(q: str):
    return matcher.resolve_product_query_from_index(q, CI)


def names(decision):
    return [x.get("name", "") for x in decision.clarification_options or decision.alternatives or []]


def assert_decision(q: str, expected: DecisionType, contains: str = ""):
    d = resolve(q)
    assert d.decision_type == expected, f"{q!r}: expected {expected}, got {d.decision_type}, reason={d.reason}, product={(d.product or {}).get('name')}, options={names(d)}"
    if contains:
        product_name = (d.product or {}).get("name", "")
        option_text = " | ".join(names(d))
        assert contains.lower() in (product_name + " " + option_text).lower(), f"{q!r}: expected {contains!r} in result; product={product_name}, options={option_text}"
    return d


def test_medicine_variant_clarification():
    assert_decision("Flagyl", DecisionType.ASK_CLARIFICATION, "Flagyl")
    assert_decision("Flagyl tablets", DecisionType.ASK_CLARIFICATION, "500")
    assert_decision("Flagyl tablets 500", DecisionType.EXACT_MATCH, "500")
    assert_decision("Flagyl syrup", DecisionType.EXACT_MATCH, "syrup")


def test_panadol_brand_and_family():
    assert_decision("Panadol", DecisionType.ASK_CLARIFICATION, "Panadol")
    assert_decision("Panadol Extra", DecisionType.EXACT_MATCH, "Extra")
    assert_decision("Panadol Advance", DecisionType.EXACT_MATCH, "Advance")


def test_amoclan_augmentin_no_random_substitution():
    assert_decision("Amoclan 625", DecisionType.EXACT_MATCH, "Amoclan")
    assert_decision("Augmentin 625", DecisionType.EXACT_MATCH, "Augmentin")
    # Same active/substitution group can be displayed as clarification, not an automatic medicine alternative.
    d = assert_decision("amoxicillin clavulanate 625", DecisionType.ASK_CLARIFICATION, "Amoclan")
    assert not d.alternatives, "Medicine alternatives must not be emitted automatically."


def test_cosmetic_brand_type_size_clarification():
    assert_decision("CeraVe", DecisionType.ASK_CLARIFICATION, "CeraVe")
    assert_decision("غسول", DecisionType.ASK_CLARIFICATION, "Cleanser")
    assert_decision("lotion", DecisionType.ASK_CLARIFICATION, "Lotion")
    assert_decision("CeraVe cleanser", DecisionType.ASK_CLARIFICATION, "CeraVe")
    assert_decision("CeraVe Hydrating Cleanser", DecisionType.ASK_CLARIFICATION, "236")
    assert_decision("CeraVe Hydrating Cleanser 236ml", DecisionType.EXACT_MATCH, "236")


def test_specific_unknown_not_available():
    d = assert_decision("Rilastil xerolact PB", DecisionType.NOT_AVAILABLE)
    assert not d.alternatives, "Specific unknown cosmetic without safe same-type evidence must not show alternatives."
    assert_decision("Rilastil xerolact cleanser", DecisionType.NOT_AVAILABLE)
    assert_decision("unknownmedicine 500", DecisionType.NOT_AVAILABLE)


def test_no_cross_type_cosmetic_alternatives():
    d = assert_decision("CeraVe unknown serum", DecisionType.NOT_AVAILABLE)
    assert not d.alternatives or all("serum" in x.get("form", "").lower() or "serum" in x.get("name", "").lower() for x in d.alternatives), "No cross-type cosmetic alternatives allowed."


def test_image_rules():
    unclear = matcher.resolve_image_extraction_from_index({"image_type": "product_packaging", "brand": "cerave", "product_type": "cream", "confidence": 0.90, "clarity": "good"}, CI)
    assert unclear.decision_type == DecisionType.LOW_CONFIDENCE, f"weak image evidence should not match: {unclear}"
    bad = matcher.resolve_image_extraction_from_index({"image_type": "unclear", "confidence": 0.9, "clarity": "bad"}, CI)
    assert bad.decision_type == DecisionType.IMAGE_UNCLEAR
    good = matcher.resolve_image_extraction_from_index({"image_type": "product_packaging", "brand": "cerave", "product_name": "Hydrating Cleanser", "product_type": "cleanser", "size": "236ml", "confidence": 0.92, "clarity": "good"}, CI)
    assert good.decision_type == DecisionType.EXACT_MATCH and "236" in good.product.get("name", ""), good


def test_slot_extraction_and_quality_report():
    slots = matcher.extract_product_slots("فلاجيل شراب 125")
    assert slots["brand"] == "flagyl"
    assert slots["form"] == "syrup"
    assert "125" in slots["strength_values"]
    rows = matcher.build_catalog_quality_rows(CATALOG)
    assert rows and all("issues" in row for row in rows)


if __name__ == "__main__":
    test_medicine_variant_clarification()
    test_panadol_brand_and_family()
    test_amoclan_augmentin_no_random_substitution()
    test_cosmetic_brand_type_size_clarification()
    test_specific_unknown_not_available()
    test_no_cross_type_cosmetic_alternatives()
    test_image_rules()
    test_slot_extraction_and_quality_report()
    print("ACCEPTANCE_TESTS_V4_OK")
