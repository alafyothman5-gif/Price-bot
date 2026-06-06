"""Final V17.1 acceptance test: pending clarification must not hijack a new product query."""
import database
import matcher


def run():
    database.init_db()
    phone = "ACCEPTANCE_V17_1_PENDING_STATE"
    database.clear_user_state(phone)
    products = [
        {"id": 101, "name": "flagyl 125mg", "brand": "Flagyl", "product_family": "Flagyl", "category": "medicine", "form": "", "strength": "125mg", "available": "true", "price": "10"},
        {"id": 102, "name": "flagyl 500mg", "brand": "Flagyl", "product_family": "Flagyl", "category": "medicine", "form": "tablet", "strength": "500mg", "available": "true", "price": "12"},
        {"id": 103, "name": "flagyl supp 500mg", "brand": "Flagyl", "product_family": "Flagyl", "category": "medicine", "form": "suppository/pessary", "strength": "500mg", "available": "true", "price": "14"},
        {"id": 104, "name": "Cerave hydrating cleanser", "brand": "Cerave", "product_family": "Hydrating Cleanser", "category": "cosmetic", "form": "cleanser", "size": "236ml", "available": "true", "price": "50"},
    ]
    old_index = matcher._PRODUCT_INDEX
    try:
        matcher._PRODUCT_INDEX = matcher._build_product_index(products)
        database.update_user_state(phone, {
            "pending_variant_options": products[:3],
            "pending_variant_kind": "strength",
            "pending_variant_query": "فلاجيل",
        })
        state = database.get_user_state(phone)
        result = matcher.handle_text_query_result(phone, "غسول", state)
        assert "flagyl 125mg" not in result.reply.lower(), result.reply
        assert "flagyl 500mg" not in result.reply.lower(), result.reply
        assert "flagyl supp" not in result.reply.lower(), result.reply
        assert result.decision != "variant_waiting", result.decision
    finally:
        matcher._PRODUCT_INDEX = old_index
        database.clear_user_state(phone)
    print("ACCEPTANCE_TESTS_FINAL_V17_1_OK")


if __name__ == "__main__":
    run()
