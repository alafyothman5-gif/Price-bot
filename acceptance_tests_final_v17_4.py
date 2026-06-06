"""Final V17.4 acceptance tests: strict matching + vision safety.

Covers launch blockers:
- no price/product for brand-only/type-only/weak queries
- no medicine alternatives
- no cosmetic cross-type alternatives
- medicine variant resolver asks for missing form/strength
- vision extraction is evidence only, with LOW_CONFIDENCE/IMAGE_UNCLEAR guards
"""
from __future__ import annotations

import matcher_v4 as matcher
from matcher_v2 import DecisionType


def base_catalog(include_rilastil_pb: bool = False):
    catalog = [
        {"id":"F1","product_id":"F1","name":"Flagyl 500mg tablets","brand":"flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"tablet","strength":"500mg","aliases":"فلاجيل اقراص|flagyl tablet","price":"12","available":"متوفر"},
        {"id":"F2","product_id":"F2","name":"Flagyl syrup 125mg/5ml","brand":"flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"syrup","strength":"125mg/5ml","aliases":"فلاجيل شراب|flagyl syrup","price":"8","available":"متوفر"},
        {"id":"F4","product_id":"F4","name":"Flagyl syrup 250mg/5ml","brand":"flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"syrup","strength":"250mg/5ml","aliases":"flagyl syrup 250","price":"9","available":"متوفر"},
        {"id":"F3","product_id":"F3","name":"Flagyl supp 500mg","brand":"flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"suppository","strength":"500mg","aliases":"فلاجيل تحاميل|flagyl supp","price":"10","available":"متوفر"},
        {"id":"A1","product_id":"A1","name":"Amoclan syrup 156mg","brand":"amoclan","product_family":"Amoclan","category":"medicine","active_ingredient":"amoxicillin clavulanate","form":"syrup","strength":"156mg","price":"20","available":"متوفر"},
        {"id":"A2","product_id":"A2","name":"Amoclan syrup 457mg","brand":"amoclan","product_family":"Amoclan","category":"medicine","active_ingredient":"amoxicillin clavulanate","form":"syrup","strength":"457mg","price":"22","available":"متوفر"},
        {"id":"C1","product_id":"C1","name":"CeraVe Moisturizing Lotion 236ml","brand":"cerave","product_family":"Moisturizing Lotion","category":"cosmetic","form":"lotion","size":"236ml","aliases":"cerave moisturizing lotion","ocr_keywords":"cerave|moisturizing|lotion","use_case":"hydration","skin_type":"dry_skin","price":"60","available":"متوفر"},
        {"id":"C2","product_id":"C2","name":"Bioderma Sebium Gel Moussant 200ml","brand":"bioderma","product_family":"Sebium Gel Moussant","category":"cosmetic","form":"cleanser","size":"200ml","aliases":"bioderma sebium cleanser|sebium gel moussant","ocr_keywords":"bioderma|sebium|cleanser","use_case":"acne","skin_type":"oily_skin","price":"65","available":"متوفر"},
        {"id":"C3","product_id":"C3","name":"La Roche Effaclar Gel Cleanser 200ml","brand":"laroche","product_family":"Effaclar Gel","category":"cosmetic","form":"cleanser","size":"200ml","aliases":"laroche effaclar cleanser","ocr_keywords":"laroche|effaclar|cleanser","use_case":"acne","skin_type":"oily_skin","price":"70","available":"متوفر"},
        {"id":"S1","product_id":"S1","name":"The Ordinary Vitamin C Serum","brand":"theordinary","product_family":"Vitamin C","category":"cosmetic","form":"serum","aliases":"vitamin c serum|سيروم فيتامين سي","ocr_keywords":"vitamin c|serum","use_case":"anti_pigmentation","price":"75","available":"متوفر"},
        {"id":"P123","product_id":"P123","name":"1,2,3 Extra","brand":"","category":"other","aliases":"123|1 2 3 extra","ocr_keywords":"123 extra","price":"5","available":"متوفر"},
    ]
    if include_rilastil_pb:
        catalog.append({"id":"R1","product_id":"R1","name":"Rilastil Xerolact PB","brand":"rilastil","product_family":"Xerolact PB","category":"cosmetic","form":"balm","aliases":"rilastil xerolact pb","ocr_keywords":"rilastil|xerolact|pb","use_case":"dry_skin","skin_type":"dry_skin","price":"80","available":"متوفر"})
    return catalog


def resolve(q, include_rilastil_pb=False):
    ci = matcher.build_catalog_index(base_catalog(include_rilastil_pb))
    return matcher.resolve_product_query_from_index(q, ci)


def assert_type(q, expected, include_rilastil_pb=False):
    d = resolve(q, include_rilastil_pb)
    assert d.decision_type == expected, f"{q!r}: expected {expected}, got {d.decision_type}, reason={d.reason}, product={(d.product or {}).get('name')}, alts={[a.get('name') for a in d.alternatives]}, opts={[o.get('name') for o in d.clarification_options]}"
    return d


def assert_no_price_product(d):
    assert d.product is None, f"ambiguous query returned product: {d.product}"
    assert d.decision_type in {DecisionType.ASK_CLARIFICATION, DecisionType.LOW_CONFIDENCE, DecisionType.NOT_AVAILABLE}


def main():
    # Matching tests required by the brief.
    d = assert_type("Rilastil xerolact PB متوفر", DecisionType.NOT_AVAILABLE, include_rilastil_pb=False)
    assert not d.alternatives
    d = assert_type("Rilastil xerolact PB متوفر", DecisionType.EXACT_MATCH, include_rilastil_pb=True)
    assert d.product and d.product.get("product_id") == "R1"
    d = assert_type("Rilastil", DecisionType.LOW_CONFIDENCE, include_rilastil_pb=False)
    assert_no_price_product(d)
    d = assert_type("Cerave Hydrating Cleanser", DecisionType.NOT_AVAILABLE)
    assert all((a.get("form") == "cleanser") for a in d.alternatives), d.alternatives
    assert_type("Cerave", DecisionType.ASK_CLARIFICATION)
    assert_type("غسول", DecisionType.ASK_CLARIFICATION)
    assert_type("فلاجيل", DecisionType.ASK_CLARIFICATION)
    assert_type("فلاجيل شراب", DecisionType.ASK_CLARIFICATION)
    assert_type("فلاجيل 500", DecisionType.ASK_CLARIFICATION)
    assert_type("Amoclan syrup", DecisionType.ASK_CLARIFICATION)
    d = assert_type("123", DecisionType.EXACT_MATCH)
    assert d.product and d.product.get("product_id") == "P123"
    d = assert_type("Cerave unknown serum", DecisionType.NOT_AVAILABLE)
    assert not d.alternatives or all(a.get("form") == "serum" for a in d.alternatives)
    d = assert_type("Flagyl cream 999", DecisionType.NOT_AVAILABLE)
    assert not d.alternatives
    for q in ["Cerave", "غسول", "cream", "lotion", "face wash"]:
        d = resolve(q)
        assert_no_price_product(d)

    # Vision tests with structured extraction. Vision never decides stock/price.
    ci = matcher.build_catalog_index(base_catalog())
    image_unclear = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging","brand":"cerave","product_name":"x","confidence":0.4,"image_quality":"blurry"}, ci)
    assert image_unclear.decision_type == DecisionType.IMAGE_UNCLEAR
    cream_only = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging","visible_text":["cream"],"product_type":"cream","confidence":0.9,"image_quality":"clear"}, ci)
    assert cream_only.decision_type == DecisionType.LOW_CONFIDENCE
    product_found = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging","brand":"bioderma","product_name":"Sebium Gel Moussant","product_type":"cleanser","size":"200ml","confidence":0.9,"image_quality":"clear"}, ci)
    assert product_found.decision_type == DecisionType.EXACT_MATCH and product_found.product.get("product_id") == "C2"
    product_missing = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging","brand":"rilastil","product_name":"Xerolact PB","product_type":"balm","confidence":0.9,"image_quality":"clear"}, ci)
    assert product_missing.decision_type == DecisionType.NOT_AVAILABLE and not product_missing.alternatives
    cerave_cleanser_missing = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging","brand":"cerave","product_name":"Hydrating Cleanser","product_type":"cleanser","confidence":0.9,"image_quality":"clear"}, ci)
    assert cerave_cleanser_missing.decision_type in {DecisionType.NOT_AVAILABLE, DecisionType.COSMETIC_ALTERNATIVES}
    assert all(a.get("form") == "cleanser" for a in cerave_cleanser_missing.alternatives)
    multiple = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging","brand":"cerave","product_name":"Hydrating Cleanser","confidence":0.9,"image_quality":"multiple_products"}, ci)
    assert multiple.decision_type in {DecisionType.LOW_CONFIDENCE, DecisionType.ASK_CLARIFICATION}
    med_no_strength = matcher.resolve_image_extraction_from_index({"image_type":"product_packaging","brand":"amoclan","product_name":"Amoclan","product_type":"syrup","confidence":0.9,"image_quality":"clear"}, ci)
    assert med_no_strength.decision_type == DecisionType.ASK_CLARIFICATION

    rows = matcher.build_catalog_quality_rows(base_catalog())
    assert rows and "ready" in rows[0] and "issues" in rows[0]
    print("ACCEPTANCE_TESTS_FINAL_V17_4_OK")


if __name__ == "__main__":
    main()
