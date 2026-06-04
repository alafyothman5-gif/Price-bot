"""Acceptance tests for matcher_v2 production-grade resolver."""
from matcher_v2 import DecisionType, MatchDecision, resolve_product_query, resolve_image_extraction

CATALOG = [
    {"id": 1, "name": "Cerave moisturising lotion Baume", "brand": "CeraVe", "form": "lotion moisturizer face", "aliases": "Cerave moisturizing lotion Baume", "price": "100", "available": "متوفر"},
    {"id": 2, "name": "CeraVe Hydrating Cleanser", "brand": "CeraVe", "form": "face cleanser", "aliases": "CeraVe Hydrating Cleanser", "price": "95", "available": "غير متوفر"},
    {"id": 3, "name": "CeraVe H.A Serum", "brand": "CeraVe", "form": "serum face", "price": "120", "available": "متوفر"},
    {"id": 4, "name": "La Roche Effaclar Face Cleanser Oily Skin", "brand": "La Roche", "form": "face cleanser oily skin", "aliases": "غسول لاروش ايفاكلار بشرة دهنية", "price": "98", "available": "متوفر"},
    {"id": 5, "name": "Bioderma Sebium Gel Moussant Face Cleanser", "brand": "Bioderma", "form": "face cleanser oily skin", "price": "88", "available": "متوفر"},
    {"id": 6, "name": "Baby Shampoo", "brand": "BabyCare", "form": "baby shampoo", "price": "30", "available": "متوفر"},
    {"id": 7, "name": "Body Wash", "brand": "Fresh", "form": "body wash cleanser", "price": "25", "available": "متوفر"},
    {"id": 8, "name": "Flagyl 250mg tablet", "brand": "Flagyl", "form": "tablet", "strength": "250mg", "aliases": "فلاجيل", "price": "12", "available": "متوفر"},
    {"id": 9, "name": "Flagyl 500mg tablet", "brand": "Flagyl", "form": "tablet", "strength": "500mg", "aliases": "فلاجيل", "price": "15", "available": "متوفر"},
    {"id": 10, "name": "Flagyl syrup 125mg", "brand": "Flagyl", "form": "syrup", "strength": "125mg", "aliases": "فلاجيل شراب", "price": "18", "available": "متوفر"},
    {"id": 11, "name": "Panadol Advance", "brand": "Panadol", "form": "tablet", "aliases": "بنادول", "price": "20", "available": "متوفر"},
    {"id": 12, "name": "Panadol Baby Syrup", "brand": "Panadol", "form": "syrup", "aliases": "بنادول شراب", "price": "22", "available": "متوفر"},
]


def names(items):
    return [x.get("name", "") for x in items]


def assert_decision(query, expected):
    d = resolve_product_query(query, CATALOG)
    assert d.decision_type == expected, f"{query}: expected {expected}, got {d.decision_type} {d.reason}"
    return d



def test_image_ask_clarification_does_not_fallback_to_safe_match():
    """Image flow must respect matcher_v2 ASK_CLARIFICATION and never call legacy safe_match."""
    import asyncio
    import app
    import matcher

    original_resolve = matcher.resolve_product_query_decision
    original_safe_match = matcher.safe_match
    original_builder = matcher.build_v2_clarification_reply
    original_inspect = matcher.inspect_query
    try:
        matcher.resolve_product_query_decision = lambda query: MatchDecision(
            decision_type=DecisionType.ASK_CLARIFICATION,
            confidence=0.8,
            clarification_options=[{"name": "CeraVe Hydrating Cleanser", "price": "95"}],
            clarification_type="product",
            question="ASK_V2_SENTINEL",
            reason="test_ask",
        )

        def fail_safe_match(query):
            raise AssertionError("legacy safe_match must not be called after ASK_CLARIFICATION")

        matcher.safe_match = fail_safe_match
        matcher.build_v2_clarification_reply = lambda phone, decision: "ASK_V2_REPLY_SENTINEL"
        matcher.inspect_query = lambda query: {"clean_query": query, "detected_brand": "cerave", "detected_type": "cleanser", "detected_area": "face", "match_result": "TEST", "matched_product": ""}
        reply = asyncio.run(app.run_image_matching(
            "218000000000",
            {
                "image_type": "product_packaging",
                "clarity": "good",
                "confidence": 0.95,
                "brand": "CeraVe",
                "product_name": "Hydrating Cleanser",
                "product_type": "cleanser",
            },
            {},
        ))
        assert reply == "ASK_V2_REPLY_SENTINEL", reply
    finally:
        matcher.resolve_product_query_decision = original_resolve
        matcher.safe_match = original_safe_match
        matcher.build_v2_clarification_reply = original_builder
        matcher.inspect_query = original_inspect


def test_dynamic_synonym_works_in_matcher_v2_without_restart():
    """matcher_v2 must load database dynamic synonyms after refresh_synonym_rules()."""
    import database
    import matcher_v2

    original_loader = database.load_dynamic_synonyms
    try:
        database.load_dynamic_synonyms = lambda: {"سيرافي بوم": "cerave moisturising lotion baume"}
        matcher_v2.refresh_synonym_rules()
        d = resolve_product_query("سيرافي بوم", CATALOG)
        assert d.decision_type == DecisionType.EXACT_MATCH, (d.decision_type, d.reason)
        assert "Baume" in d.product["name"], d.product
    finally:
        database.load_dynamic_synonyms = original_loader
        matcher_v2.refresh_synonym_rules()


def test_cerave_baume_never_selects_serum_or_cleanser():
    d = resolve_product_query("Cerave baume", CATALOG)
    forbidden = []
    if d.product:
        forbidden.append(d.product.get("name", ""))
    forbidden.extend(x.get("name", "") for x in (d.clarification_options or []))
    forbidden.extend(x.get("name", "") for x in (d.alternatives or []))
    assert not any("Serum" in name or "Cleanser" in name for name in forbidden), (d.decision_type, forbidden)
    assert d.decision_type in {DecisionType.EXACT_MATCH, DecisionType.ASK_CLARIFICATION, DecisionType.NOT_AVAILABLE}, (d.decision_type, d.reason)
    if d.decision_type == DecisionType.EXACT_MATCH:
        assert "Baume" in d.product["name"], d.product
    if d.decision_type == DecisionType.ASK_CLARIFICATION:
        assert d.clarification_options, d.reason
        assert all("Baume" in x.get("name", "") for x in d.clarification_options), d.clarification_options

def main():
    d = assert_decision("Cerave moisturising lotion Baume", DecisionType.EXACT_MATCH)
    assert d.product["price"] == "100"

    assert_decision("cerave", DecisionType.ASK_CLARIFICATION)
    assert_decision("lotion", DecisionType.ASK_CLARIFICATION)

    d = assert_decision("CeraVe Hydrating Cleanser", DecisionType.COSMETIC_ALTERNATIVES)
    alt_names = names(d.alternatives)
    assert alt_names and all("Cleanser" in n for n in alt_names), alt_names
    assert not any("Serum" in n or "lotion" in n.lower() or "Shampoo" in n or "Body Wash" in n for n in alt_names), alt_names

    d = assert_decision("CeraVe H.A Serum", DecisionType.EXACT_MATCH)
    assert "Serum" in d.product["name"]

    d = assert_decision("فلاجيل", DecisionType.ASK_CLARIFICATION)
    assert len(d.clarification_options) >= 3

    d = assert_decision("فلاجيل شراب", DecisionType.EXACT_MATCH)
    assert "syrup" in d.product["name"].lower()

    d = assert_decision("فلاجيل 500", DecisionType.EXACT_MATCH)
    assert "500" in d.product["name"]

    assert_decision("بنادول", DecisionType.ASK_CLARIFICATION)
    d = assert_decision("بنادول شراب", DecisionType.EXACT_MATCH)
    assert "Syrup" in d.product["name"]

    unclear = resolve_image_extraction({"confidence": 0.4, "clarity": "bad"}, CATALOG)
    assert unclear.decision_type == DecisionType.IMAGE_UNCLEAR

    image_lotion = resolve_image_extraction({"brand": "CeraVe", "product_name": "moisturising lotion Baume", "type": "lotion", "confidence": 0.91, "clarity": "good"}, CATALOG)
    assert image_lotion.decision_type == DecisionType.EXACT_MATCH and "lotion" in image_lotion.product["name"].lower()

    # Medicine unavailable must not produce treatment alternatives.
    d = assert_decision("Flagyl injection", DecisionType.ASK_CLARIFICATION)
    assert not d.alternatives

    test_image_ask_clarification_does_not_fallback_to_safe_match()
    test_dynamic_synonym_works_in_matcher_v2_without_restart()
    test_cerave_baume_never_selects_serum_or_cleanser()

    print("ACCEPTANCE_TESTS_V2_OK")


if __name__ == "__main__":
    main()
