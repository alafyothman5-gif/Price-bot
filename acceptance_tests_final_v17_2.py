"""Final V17.2 acceptance tests: safe typo tolerance + cosmetic alternatives.

These tests protect the current strict behavior while fixing two real launch blockers:
1) clear product names with one-letter typos should resolve inside the same brand/type scope.
2) missing/unavailable cosmetics should offer same-type targeted alternatives only.
"""
import matcher_v4
from matcher_v2 import DecisionType


def catalog():
    return [
        {"product_id":"C1","name":"CeraVe Hydrating Cleanser 236ml","brand":"CeraVe","product_family":"Hydrating Cleanser","category":"cosmetic","form":"cleanser","size":"236ml","aliases":"cerave hydrating cleanser|cera ve hydrating cleanser","ocr_keywords":"cerave|hydrating|cleanser|236ml","use_case":"hydration","price":"35","available":"true"},
        {"product_id":"C2","name":"Bioderma Sebium Gel Moussant 200ml","brand":"Bioderma","product_family":"Sebium Gel Moussant","category":"cosmetic","form":"cleanser","size":"200ml","aliases":"bioderma sebium cleanser|sebium gel moussant","ocr_keywords":"bioderma|sebium|gel|moussant|cleanser","use_case":"acne","skin_type":"oily_skin","price":"48","available":"true"},
        {"product_id":"C3","name":"La Roche Effaclar Gel Cleanser 200ml","brand":"La Roche Posay","product_family":"Effaclar Gel","category":"cosmetic","form":"cleanser","size":"200ml","aliases":"laroche effaclar cleanser|effaclar gel","ocr_keywords":"laroche|effaclar|gel|cleanser","use_case":"acne","skin_type":"oily_skin","price":"62","available":"true"},
        {"product_id":"M1","name":"Flagyl Syrup 125mg/5ml","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"syrup","strength":"125mg/5ml","aliases":"flagyl syrup|فلاجيل شراب","price":"8","available":"true"},
        {"product_id":"M2","name":"Flagyl 500mg Tablets","brand":"Flagyl","product_family":"Flagyl","category":"medicine","active_ingredient":"metronidazole","form":"tablet","strength":"500mg","aliases":"flagyl tablet|فلاجيل اقراص","price":"12","available":"true"},
    ]


def resolve(q):
    return matcher_v4.resolve_product_query(q, catalog())


def assert_type(q, dtype):
    d = resolve(q)
    assert d.decision_type == dtype, f"{q}: expected {dtype}, got {d.decision_type} reason={d.reason}"
    return d


def main():
    # Clear exact product available -> price path/exact product path.
    d = assert_type("CeraVe Hydrating Cleanser 236ml", DecisionType.EXACT_MATCH)
    assert d.product and d.product["product_id"] == "C1", d

    # One-letter mistakes should not become unavailable when brand/type scope is safe.
    for q in ["CeraVe hydratng cleanser", "CeraVe hydrating clenser", "Cerav hydrating cleanser"]:
        d = assert_type(q, DecisionType.EXACT_MATCH)
        assert d.product and d.product["product_id"] == "C1", (q, d)

    # Brand typo alone should ask, not randomly choose one product.
    d = assert_type("Cerav", DecisionType.ASK_CLARIFICATION)
    assert not d.product, d

    # Missing specific cosmetic with a target should offer same-type oily/acne cleanser alternatives.
    d = assert_type("Cerave acne cleanser oily skin", DecisionType.COSMETIC_ALTERNATIVES)
    alt_names = " | ".join(a.get("name", "") for a in d.alternatives or [])
    assert "Cleanser" in alt_names or "Moussant" in alt_names, alt_names
    assert all((a.get("form") == "cleanser") for a in d.alternatives), alt_names
    assert all((a.get("skin_type") in ("oily_skin", "")) for a in d.alternatives), alt_names

    # Medicine still stays conservative: do not pick price from family name only.
    d = assert_type("Flagyl", DecisionType.ASK_CLARIFICATION)
    assert not d.product, d

    # Specific unknown medicine: no automatic medicine alternatives.
    d = assert_type("Flagyl cream 999", DecisionType.NOT_AVAILABLE)
    assert not d.alternatives, d

    print("ACCEPTANCE_TESTS_FINAL_V17_2_OK")


if __name__ == "__main__":
    main()
