import asyncio
import os
import shutil
import tempfile
import time
from pathlib import Path


TMP_DIR = tempfile.mkdtemp(prefix="pricebot_acceptance_")
os.environ["PRICEBOT_DB_FILE"] = str(Path(TMP_DIR) / "acceptance.db")
os.environ.setdefault("PRICEBOT_ADMIN_KEY", "test-admin-key")

import app  # noqa: E402
import admin  # noqa: E402
import database  # noqa: E402
import matcher  # noqa: E402

database.init_db()


def seed_products():
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM conversation_state")
        conn.execute("DELETE FROM processed_messages")
        products = [
            {
                "name": "Panadol 500mg Tablets",
                "brand": "Panadol",
                "company": "GSK",
                "form": "tablet",
                "aliases": "بانادول|بنادول|بندول|panadol",
                "price": "5.50",
                "available": "متوفر",
            },
            {
                "name": "123",
                "brand": "123",
                "company": "123",
                "form": "code product",
                "aliases": "123|1 2 3|1,2,3",
                "price": "18",
                "available": "متوفر",
            },
            {
                "name": "Congestal 20tab",
                "brand": "Congestal",
                "company": "Congestal",
                "form": "tablet cold flu",
                "aliases": "كونجيستال|كونجستال|congestal",
                "price": "20",
                "available": "متوفر",
            },
            {
                "name": "Amoclan 145mg susp",
                "brand": "Amoclan",
                "company": "Amoclan",
                "form": "syrup susp antibiotic",
                "strength": "145mg",
                "aliases": "اموكلان شراب|اموكلان معلق|amoclan syrup|amoclan susp",
                "price": "26",
                "available": "متوفر",
            },
            {
                "name": "Amoclan 228mg susp",
                "brand": "Amoclan",
                "company": "Amoclan",
                "form": "syrup susp antibiotic",
                "strength": "228mg",
                "aliases": "اموكلان شراب|اموكلان معلق|amoclan syrup|amoclan susp",
                "price": "32",
                "available": "متوفر",
            },
            {
                "name": "Amoclan 457mg susp",
                "brand": "Amoclan",
                "company": "Amoclan",
                "form": "syrup susp antibiotic",
                "strength": "457mg",
                "aliases": "اموكلان شراب|اموكلان معلق|amoclan syrup|amoclan susp",
                "price": "45",
                "available": "متوفر",
            },
            {
                "name": "Amoclan 1g tablets",
                "brand": "Amoclan",
                "company": "Amoclan",
                "form": "tablet antibiotic",
                "strength": "1g",
                "aliases": "اموكلان اقراص|amoclan tab|amoclan tablet",
                "price": "60",
                "available": "متوفر",
            },
            {
                "name": "Cicaplast b5+",
                "brand": "Cicaplast",
                "company": "La Roche Posay",
                "form": "face cream repair",
                "aliases": "لاروش سيكا|لاروش سيكابلاست|cicaplast b5|cica plast",
                "price": "78",
                "available": "متوفر",
            },
            {
                "name": "CeraVe Moisturising Lotion Baume",
                "brand": "CeraVe",
                "company": "CeraVe",
                "form": "lotion moisturizer face",
                "aliases": "Cerave moisturising lotion Baume|Cerave moisturizing lotion Baume",
                "price": "120",
                "available": "متوفر",
            },
            {
                "name": "CeraVe Daily Moisturizing Lotion",
                "brand": "CeraVe",
                "company": "CeraVe",
                "form": "lotion moisturizer face",
                "aliases": "CeraVe Daily Moisturizing Lotion",
                "price": "115",
                "available": "متوفر",
            },
            {
                "name": "La Roche Effaclar Purifying Foaming Gel Face Cleanser Oily Skin",
                "brand": "La Roche",
                "company": "La Roche Posay",
                "form": "face cleanser oily skin",
                "aliases": "غسول لاروش ايفاكلار بشرة دهنية|effaclar cleanser",
                "price": "98",
                "available": "متوفر",
            },
            {
                "name": "Bioderma Sebium Gel Moussant Face Cleanser",
                "brand": "Bioderma",
                "company": "Bioderma",
                "form": "face cleanser oily skin",
                "aliases": "face cleanser|gel moussant",
                "price": "88",
                "available": "متوفر",
            },
            {
                "name": "Normaderm Vichy",
                "brand": "Vichy",
                "company": "Vichy",
                "form": "",
                "aliases": "",
                "price": "138",
                "available": "متوفر",
            },
            {
                "name": "Generic Baby Shampoo",
                "brand": "BabyCare",
                "company": "BabyCare",
                "form": "baby shampoo",
                "price": "22",
                "available": "متوفر",
            },
            {
                "name": "Fresh Body Wash",
                "brand": "Fresh",
                "company": "Fresh",
                "form": "body wash cleanser",
                "price": "30",
                "available": "متوفر",
            },
            {
                "name": "Dental Mouth Wash",
                "brand": "Dental",
                "company": "Dental",
                "form": "mouth wash oral",
                "price": "18",
                "available": "متوفر",
            },
            {
                "name": "Hair Repair Shampoo",
                "brand": "HairCo",
                "company": "HairCo",
                "form": "hair shampoo",
                "price": "40",
                "available": "متوفر",
            },
        ]
        for product in products:
            normalized_name = matcher.normalize_text(product["name"])
            conn.execute(
                """
                INSERT INTO products
                (name, brand, company, form, strength, aliases, price, available, normalized_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product["name"],
                    product.get("brand", ""),
                    product.get("company", ""),
                    product.get("form", ""),
                    product.get("strength", ""),
                    product.get("aliases", ""),
                    product.get("price", ""),
                    product.get("available", "متوفر"),
                    normalized_name,
                ),
            )
        conn.commit()
    matcher.invalidate_product_cache()


def reply(phone: str, text: str) -> str:
    return matcher.handle_text_query(phone, text, database.get_user_state(phone))


def assert_contains(text: str, needle: str, label: str):
    assert needle in text, f"{label}: expected {needle!r} in {text!r}"


def assert_not_contains(text: str, needle: str, label: str):
    assert needle not in text, f"{label}: did not expect {needle!r} in {text!r}"


def order_count() -> int:
    return len(database.get_all_orders())


def text_tests():
    assert_contains(reply("t1", "السلام عليكم"), "مرحباً", "greeting")

    test_reply = reply("t2", "test123")
    assert_contains(test_reply, "لم أفهم", "noise fallback")
    assert_not_contains(test_reply, "غير متوفر", "noise is not unavailable")

    assert_contains(reply("t3", "CeraVe"), "يرجى تحديد", "brand only")
    assert_contains(reply("t4", "cleanser"), "يوجد أكثر من نوع", "category only")
    assert_contains(reply("t5", "غسول وجه"), "يوجد أكثر من نوع", "arabic category only")

    assert_contains(reply("t6", "متوفر عندكم بانادول"), "Panadol 500mg Tablets", "panadol lookup")
    assert_contains(reply("t6_code", "متوفر عندكم 123"), "123", "numeric product lookup")
    assert_contains(reply("t6_congestal", "متوفر كونجيستال"), "Congestal 20tab", "arabic congestal lookup")
    amoclan_form = reply("t6_amoclan_form", "متوفر اموكلان")
    assert_contains(amoclan_form, "أكثر من شكل", "amoclan asks form when form missing")

    amoclan_strength = reply("t6_amoclan_strength", "متوفر عندكم اموكلان شراب")
    assert_contains(amoclan_strength, "أكثر من جرعة", "amoclan syrup asks strength")
    assert_contains(amoclan_strength, "145", "amoclan shows 145")
    assert_contains(amoclan_strength, "228", "amoclan shows 228")
    assert_contains(amoclan_strength, "457", "amoclan shows 457")
    amoclan_selected = reply("t6_amoclan_strength", "457")
    assert_contains(amoclan_selected, "Amoclan 457mg susp", "amoclan selects requested strength")

    amoclan_direct = reply("t6_amoclan_direct", "متوفر اموكلان 228 شراب")
    assert_contains(amoclan_direct, "Amoclan 228mg susp", "amoclan direct strength")

    # Pending variant menus must not hijack a fresh product query from the same customer.
    assert_contains(reply("t6_state_panadol", "متوفر اموكلان"), "أكثر من شكل", "state starts amoclan menu")
    assert_contains(reply("t6_state_panadol", "متوفر بنادول"), "Panadol 500mg Tablets", "fresh panadol overrides old amoclan menu")
    assert_contains(reply("t6_state_123", "متوفر اموكلان"), "أكثر من شكل", "state starts amoclan menu before numeric")
    assert_contains(reply("t6_state_123", "متوفر عندكم 123"), "✅ المنتج: 123", "fresh numeric product overrides old amoclan menu")
    assert_contains(reply("t6_state_bad_strength", "متوفر اموكلان شراب"), "أكثر من جرعة", "state starts amoclan strength menu")
    assert_contains(reply("t6_state_bad_strength", "456"), "الجرعة التي كتبتها غير موجودة", "bad strength stays within pending amoclan")

    assert_contains(reply("t6_cica", "متوفر لاروش سيكا"), "Cicaplast b5+", "arabic laroche cica lookup")
    assert_contains(reply("t7", "Cerave moisturising lotion Baume"), "CeraVe Moisturising Lotion Baume", "cerave lotion lookup")
    assert_contains(reply("t8", "متوفر عندكم Cerave moisturising lotion Baume"), "CeraVe Moisturising Lotion Baume", "cerave lotion with stopwords")

    lr_reply = reply("t9", "غسول لاروش ايفاكلار بشرة دهنية")
    assert_contains(lr_reply, "La Roche Effaclar", "laroche effaclar")
    for forbidden in ["Body Wash", "Mouth Wash", "Baby Shampoo", "Hair Repair Shampoo"]:
        assert_not_contains(lr_reply, forbidden, f"laroche no wrong alternative {forbidden}")

    assert_contains(reply("t10_vichy", "Vichy Normaderm Daily Deep Cleansing Gel 200ml"), "Normaderm Vichy", "weak excel vichy reverse-order lookup")
    med_missing = reply("t11_medicine_missing", "متوفر اوجمنتين 1000")
    assert_contains(med_missing, "غير متوفر", "missing medicine unavailable")
    assert_not_contains(med_missing, "بدائل متوفرة", "medicine does not suggest alternatives")


async def image_tests():
    cleanser_image = {
        "image_type": "product_packaging",
        "brand": "CeraVe",
        "product_name": "Renewing SA Cleanser",
        "product_names": ["CeraVe Renewing SA Cleanser"],
        "visible_text": "CeraVe\nRenewing SA Cleanser\nFor Normal Skin\n8 FL OZ",
        "product_type": "cleanser",
        "target_area": "face",
        "confidence": 0.94,
        "clarity": "good",
        "requires_admin_review": False,
    }
    cleanser_reply = await app.run_image_matching("img1", cleanser_image, {})
    assert_contains(cleanser_reply, "غير متوفر حالياً", "missing cleanser unavailable")
    assert_contains(cleanser_reply, "بدائل متوفرة", "missing cleanser alternatives")
    for forbidden in ["Baby Shampoo", "Body Wash", "Mouth Wash", "Hair Repair Shampoo", "Daily Moisturizing Lotion"]:
        assert_not_contains(cleanser_reply, forbidden, f"cleanser alternative excludes {forbidden}")

    lotion_image = {
        "image_type": "product_packaging",
        "brand": "CeraVe",
        "product_name": "Daily Moisturizing Lotion",
        "product_names": ["CeraVe Daily Moisturizing Lotion"],
        "visible_text": "CeraVe\nDaily Moisturizing Lotion",
        "product_type": "lotion",
        "target_area": "face",
        "confidence": 0.92,
        "clarity": "good",
        "requires_admin_review": False,
    }
    lotion_reply = await app.run_image_matching("img2", lotion_image, {})
    assert_contains(lotion_reply, "CeraVe Daily Moisturizing Lotion", "lotion image match")
    assert_not_contains(lotion_reply, "Cleanser", "lotion image does not pick cleanser")
    assert_not_contains(lotion_reply, "Serum", "lotion image does not pick serum")

    vichy_image = {
        "image_type": "product_packaging",
        "brand": "Vichy",
        "product_name": "Normaderm Daily Deep Cleansing Gel",
        "product_names": ["Vichy Normaderm Daily Deep Cleansing Gel"],
        "visible_text": "VICHY\nNORMADERM\nDAILY DEEP CLEANSING GEL\nSALICYLIC ACID ACNE TREATMENT\n200ml",
        "product_type": "cleanser",
        "target_area": "face",
        "skin_concern": "acne oily skin",
        "usage_purpose": "face cleanser for acne oily skin",
        "confidence": 0.94,
        "clarity": "good",
        "requires_admin_review": False,
    }
    vichy_reply = await app.run_image_matching("img_vichy", vichy_image, {})
    assert_contains(vichy_reply, "Normaderm Vichy", "vichy image weak excel match")

    unclear_reply = await app.run_image_matching(
        "img3",
        {"image_type": "unclear", "confidence": 0.2, "clarity": "bad", "requires_admin_review": False},
        {},
    )
    assert_contains(unclear_reply, "الصورة غير واضحة", "unclear image")

    prescription_reply = await app.run_image_matching(
        "img4",
        {"image_type": "prescription", "confidence": 0.9, "clarity": "good", "requires_admin_review": False},
        {},
    )
    assert_contains(prescription_reply, "روشتة", "prescription")
    assert_not_contains(prescription_reply, "✅ المنتج", "prescription does not invent product")


def booking_tests():
    before = order_count()
    assert_contains(reply("b1", "متوفر عندكم بانادول"), "للحجز اكتب: نعم", "available product reservation prompt")
    assert_contains(reply("b1", "نعم"), "تم تسجيل طلب الحجز", "available product creates order")
    assert order_count() == before + 1, "available product order count"
    assert "Panadol" in database.get_all_orders()[0]["product_name"], "available product order item"

    alt_reply = reply("b2", "CeraVe Renewing SA Cleanser")
    assert_contains(alt_reply, "بدائل متوفرة", "alternatives offered")
    assert_contains(reply("b2", "1"), "للحجز اكتب: نعم", "alternative selection stores product")
    assert_contains(reply("b2", "نعم"), "تم تسجيل طلب الحجز", "alternative creates order")
    latest = database.get_all_orders()[0]["product_name"]
    assert "Renewing SA Cleanser" not in latest, "alternative order is not old missing product"

    before_unavailable_yes = order_count()
    assert_contains(reply("b3", "CeraVe Renewing SA Cleanser"), "غير متوفر حالياً", "unavailable before yes")
    no_order_reply = reply("b3", "نعم")
    assert_contains(no_order_reply, "لا يوجد منتج متاح للحجز", "unavailable yes rejected")
    assert order_count() == before_unavailable_yes, "unavailable yes does not create order"


def upload_mapping_tests():
    csv_content = (
        "product name,final_price,brand,image_ocr_keywords,type,status,size\n"
        "Mapped Product,10.75,TestBrand,front label words,tablet,available,500mg\n"
    ).encode("utf-8")
    products, headers = admin.parse_upload(csv_content, "products.csv")
    assert "name" in headers, "upload maps product name"
    assert products[0]["name"] == "Mapped Product", "upload parsed name"
    assert products[0]["price"] == "10.75", "upload parsed price"
    assert products[0]["brand"] == "TestBrand", "upload parsed brand"
    assert products[0]["image_ocr_keywords"] == "front label words", "upload parsed OCR keywords"
    assert products[0]["form"] == "tablet", "upload parsed form/type"
    assert products[0]["strength"] == "500mg", "upload parsed strength/size"


def seed_performance_products():
    with database.get_db_connection() as conn:
        conn.execute("DELETE FROM products")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM conversation_state")
        conn.execute("DELETE FROM processed_messages")
        base_products = [
            ("Panadol 500mg Tablets", "Panadol", "GSK", "tablet", "بانادول|بنادول|بندول|panadol", "5.50", "متوفر"),
            ("123", "123", "123", "code product", "123|1 2 3|1,2,3", "18", "متوفر"),
            ("Congestal 20tab", "Congestal", "Congestal", "tablet cold flu", "كونجيستال|كونجستال|congestal", "20", "متوفر"),
            ("Cicaplast b5+", "Cicaplast", "La Roche Posay", "face cream repair", "لاروش سيكا|لاروش سيكابلاست|cicaplast b5|cica plast", "78", "متوفر"),
            ("CeraVe Moisturising Lotion Baume", "CeraVe", "CeraVe", "lotion moisturizer face", "Cerave moisturising lotion Baume|Cerave moisturizing lotion Baume", "120", "متوفر"),
            ("CeraVe Daily Moisturizing Lotion", "CeraVe", "CeraVe", "lotion moisturizer face", "CeraVe Daily Moisturizing Lotion", "115", "متوفر"),
            ("La Roche Effaclar Purifying Foaming Gel Face Cleanser Oily Skin", "La Roche", "La Roche Posay", "face cleanser oily skin", "غسول لاروش ايفاكلار بشرة دهنية|effaclar cleanser", "98", "متوفر"),
            ("Bioderma Sebium Gel Moussant Face Cleanser", "Bioderma", "Bioderma", "face cleanser oily skin", "face cleanser|gel moussant", "88", "متوفر"),
            ("Generic Baby Shampoo", "BabyCare", "BabyCare", "baby shampoo", "", "22", "متوفر"),
            ("Fresh Body Wash", "Fresh", "Fresh", "body wash cleanser", "", "30", "متوفر"),
            ("Dental Mouth Wash", "Dental", "Dental", "mouth wash oral", "", "18", "متوفر"),
            ("Hair Repair Shampoo", "HairCo", "HairCo", "hair shampoo", "", "40", "متوفر"),
        ]
        rows = []
        for name, brand, company, form, aliases, price, available in base_products:
            rows.append((name, brand, company, form, aliases, price, available, name.lower()))
        filler_count = 4991 - len(rows)
        for idx in range(filler_count):
            name = f"Filler Product {idx:04d} Tablets"
            rows.append((name, "FillerBrand", "FillerCo", "tablet", "", "1.00", "متوفر", name.lower()))
        conn.executemany(
            """
            INSERT INTO products
            (name, brand, company, form, aliases, price, available, normalized_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    matcher.invalidate_product_cache()


def timed_reply(label: str, phone: str, text: str, max_seconds: float) -> str:
    start = time.perf_counter()
    result = reply(phone, text)
    elapsed = time.perf_counter() - start
    print(f"PERF {label}: {elapsed:.4f}s")
    assert elapsed < max_seconds, f"{label} took {elapsed:.4f}s, limit {max_seconds}s"
    return result


def performance_tests_4991():
    seed_performance_products()

    # These generic queries must not build or scan the product index.
    timed_reply("السلام عليكم", "p1", "السلام عليكم", 2.0)
    timed_reply("test123", "p2", "test123", 2.0)
    timed_reply("CeraVe", "p3", "CeraVe", 2.0)
    timed_reply("cleanser", "p4", "cleanser", 2.0)
    timed_reply("غسول وجه", "p5", "غسول وجه", 2.0)

    index_start = time.perf_counter()
    matcher.get_product_index()
    print(f"PERF product_index_build: {time.perf_counter() - index_start:.4f}s")

    assert_contains(timed_reply("Cerave moisturising lotion Baume", "p6", "Cerave moisturising lotion Baume", 2.0), "CeraVe Moisturising Lotion Baume", "perf cerave lotion")
    assert_contains(timed_reply("متوفر عندكم بانادول", "p7", "متوفر عندكم بانادول", 2.0), "Panadol 500mg Tablets", "perf panadol")
    assert_contains(timed_reply("متوفر عندكم 123", "p7_code", "متوفر عندكم 123", 2.0), "123", "perf numeric product")
    assert_contains(timed_reply("متوفر كونجيستال", "p7_congestal", "متوفر كونجيستال", 2.0), "Congestal 20tab", "perf arabic congestal")
    assert_contains(timed_reply("متوفر لاروش سيكا", "p7_cica", "متوفر لاروش سيكا", 2.0), "Cicaplast b5+", "perf arabic cica")
    assert_contains(timed_reply("CeraVe Renewing SA Cleanser", "p8", "CeraVe Renewing SA Cleanser", 3.0), "غير متوفر حالياً", "perf missing cleanser")


def main():
    try:
        seed_products()
        text_tests()
        asyncio.run(image_tests())
        booking_tests()
        upload_mapping_tests()
        performance_tests_4991()
        print("ACCEPTANCE_TESTS_OK")
    finally:
        try:
            asyncio.run(app.http_client.aclose()) if app.http_client else None
        except Exception:
            pass
        shutil.rmtree(TMP_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
