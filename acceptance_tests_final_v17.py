"""Final launch acceptance tests for stable-v17-final-strict-v4.

These tests focus on the production safety rules:
- V4 is the only final decision path.
- Clarification menus do not show price before exact selection.
- Medicine alternatives are not generated automatically.
- Cosmetic alternatives stay same-type.
- Weak/unclear image evidence never falls back to legacy text/fuzzy matching.
"""
import asyncio
import os
import tempfile
from pathlib import Path

TMP_DIR = tempfile.mkdtemp(prefix="pricebot_v17_acceptance_")
os.environ["PRICEBOT_DB_FILE"] = str(Path(TMP_DIR) / "acceptance_v17.db")
os.environ.setdefault("PRICEBOT_ADMIN_KEY", "test-admin-key")

import app  # noqa: E402
import database  # noqa: E402
import matcher  # noqa: E402


def seed_products():
    database.init_db()
    rows = [
        {"name": "Flagyl 250mg tablet", "brand": "Flagyl", "category": "medicine", "form": "tablet", "strength": "250mg", "aliases": "فلاجيل|flagyl", "price": "12", "available": "متوفر"},
        {"name": "Flagyl 500mg tablet", "brand": "Flagyl", "category": "medicine", "form": "tablet", "strength": "500mg", "aliases": "فلاجيل|flagyl", "price": "15", "available": "متوفر"},
        {"name": "Flagyl syrup 125mg/5ml", "brand": "Flagyl", "category": "medicine", "form": "syrup", "strength": "125mg/5ml", "aliases": "فلاجيل شراب|flagyl syrup", "price": "18", "available": "متوفر"},
        {"name": "Flagyl syrup 200mg/5ml", "brand": "Flagyl", "category": "medicine", "form": "syrup", "strength": "200mg/5ml", "aliases": "فلاجيل شراب|flagyl syrup", "price": "22", "available": "متوفر"},
        {"name": "CeraVe Hydrating Cleanser 236ml", "brand": "CeraVe", "category": "cosmetic", "form": "cleanser", "product_family": "hydrating cleanser", "size": "236ml", "use_case": "dry_skin hydration", "skin_type": "dry_skin", "aliases": "cerave hydrating cleanser", "price": "95", "available": "غير متوفر"},
        {"name": "Bioderma Atoderm Gel Douche Cleanser 200ml", "brand": "Bioderma", "category": "cosmetic", "form": "cleanser", "product_family": "atoderm cleanser", "size": "200ml", "use_case": "dry_skin hydration", "skin_type": "dry_skin", "aliases": "bioderma atoderm cleanser", "price": "88", "available": "متوفر"},
        {"name": "CeraVe Moisturising Lotion 236ml", "brand": "CeraVe", "category": "cosmetic", "form": "lotion", "product_family": "moisturising lotion", "size": "236ml", "use_case": "dry_skin hydration", "skin_type": "dry_skin", "aliases": "cerave lotion", "price": "120", "available": "متوفر"},
        {"name": "Unknown Availability Product", "brand": "SafeTest", "category": "other", "form": "", "aliases": "safetest unknown", "price": "11", "available": ""},
    ]
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM conversation_state")
        for p in rows:
            conn.execute(
                """
                INSERT INTO products(name, brand, category, form, strength, product_family, size, use_case, skin_type, aliases, price, available, normalized_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    p.get("name", ""), p.get("brand", ""), p.get("category", ""), p.get("form", ""), p.get("strength", ""),
                    p.get("product_family", ""), p.get("size", ""), p.get("use_case", ""), p.get("skin_type", ""),
                    p.get("aliases", ""), p.get("price", ""), p.get("available", ""), matcher.normalize_text(p.get("name", "")),
                ),
            )
        conn.commit()
    matcher.invalidate_product_cache()


def reply(phone: str, text: str) -> str:
    return matcher.handle_text_query(phone, text, database.get_user_state(phone))


def assert_in(text: str, needle: str, label: str):
    assert needle in text, f"{label}: expected {needle!r} in {text!r}"


def assert_not_in(text: str, needle: str, label: str):
    assert needle not in text, f"{label}: did not expect {needle!r} in {text!r}"


def main():
    seed_products()

    r = reply("u1", "فلاجيل")
    assert_in(r, "أكثر من شكل", "medicine form clarification")
    assert_not_in(r, " د.ل", "no price in form clarification")

    r = reply("u2", "فلاجيل شراب")
    assert_in(r, "أكثر من جرعة", "medicine strength clarification")
    assert_not_in(r, " د.ل", "no price in strength clarification")

    r = reply("u2", "125")
    assert_in(r, "Flagyl syrup 125mg", "pending strength selection")
    assert_in(r, "السعر", "price after exact selection only")

    r = reply("u3", "CeraVe Hydrating Cleanser")
    assert_in(r, "غير متوفر", "known unavailable cosmetic")
    assert_in(r, "Cleanser", "same type cosmetic alternative")
    assert_not_in(r, "Lotion", "no cross-type cosmetic alternative")

    r = reply("u4", "safetest unknown")
    assert_in(r, "التوفر غير مؤكد", "empty availability is unknown, not available")
    assert_not_in(r, "للحجز اكتب", "cannot reserve unknown availability")

    img = asyncio.run(app.run_image_matching("u5", {
        "image_type": "product_packaging",
        "clarity": "good",
        "confidence": 0.50,
        "brand": "CeraVe",
        "product_name": "Hydrating Cleanser",
        "product_type": "cleanser",
    }, {}))
    assert_in(img, "الصورة غير واضحة", "low confidence image does not fallback")

    img = asyncio.run(app.run_image_matching("u6", {
        "image_type": "product_packaging",
        "clarity": "good",
        "confidence": 0.95,
        "brand": "CeraVe",
        "product_name": "Hydrating Cleanser",
        "product_type": "cleanser",
    }, {}))
    assert_in(img, "غير متوفر", "strong image follows V4 decision")
    assert_not_in(img, "Lotion", "image alternatives do not cross type")

    print("ACCEPTANCE_TESTS_FINAL_V17_OK")


if __name__ == "__main__":
    main()
