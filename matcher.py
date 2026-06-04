import re
import difflib
from typing import List, Optional, Tuple
import database

# ==========================================
# القواميس الذكية والمفردات
# ==========================================
GREETINGS = ["السلام عليكم", "مرحبا", "hi", "hello", "هلا", "مرحبتين"]
STOPWORDS = ["متوفر", "عندكم", "موجود", "بكم", "سعر", "هل", "نبي", "اريد", "في", "فيه", "عندك", "بكام", "قداش", "كم", "شنو", "ما", "ابي"]

SYNONYMS = {
    "cera ve": "cerave", "moisturising": "moisturizing", "moisturiser": "moisturizer",
    "سيرافي": "cerave", "لاروش": "laroche", "la roche": "laroche", "la roche posay": "laroche",
    "واقي شمس": "sunscreen", "sun block": "sunscreen", "غسول": "cleanser", "كريم": "cream"
}

BRANDS = ["cerave", "laroche", "cetaphil", "vichy", "eucerin", "bioderma", "acm", "svr", "uriage", "avene", "the ordinary", "سيرافي", "لاروش"]

TYPE_WORDS = {
    "cleanser": ["cleanser", "wash", "foaming", "gel moussant", "غسول", "منظف", "face wash"],
    "moisturizer": ["moisturizer", "مرطب", "moisturising"],
    "lotion": ["lotion", "لوشن"],
    "cream": ["cream", "كريم", "baume"],
    "serum": ["serum", "سيروم"],
    "sunscreen": ["sunscreen", "spf", "واقي شمس", "sunblock", "واقي"],
    "shampoo": ["shampoo", "شامبو"]
}

AREA_WORDS = {
    "face": ["face", "visage", "وجه", "بشرة"],
    "body": ["body", "corps", "جسم", "بدن"],
    "baby": ["baby", "enfant", "pediatril", "بيبي", "اطفال", "رضع", "kids"],
    "hair": ["hair", "cheveux", "شعر"],
    "mouth": ["mouth", "oral", "dental", "teeth", "فم", "اسنان"]
}

UNAVAILABLE_TERMS = ["غير متوفر", "غير موجود", "نافذ", "نفذ", "ناقص", "لا", "0", "no", "out of stock", "unavailable"]

# ==========================================
# دوال التنظيف والمعالجة
# ==========================================
def normalize_text(text: str) -> str:
    s = str(text or "").strip().lower()
    for src, dst in {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ط": "ط"}.items():
        s = s.replace(src, dst)
    s = re.sub(r"[^\w\s\u0600-\u06FF]+", " ", s)
    for src, dst in sorted(SYNONYMS.items(), key=lambda x: len(x[0]), reverse=True):
        s = s.replace(src, dst)
    return re.sub(r"\s+", " ", s).strip()

def clean_query(text: str) -> str:
    s = normalize_text(text)
    for word in STOPWORDS:
        s = re.sub(rf"(?<!\w){word}(?!\w)", "", s)
    return re.sub(r"\s+", " ", s).strip()

def get_aliases(alias_str: str) -> List[str]:
    if not alias_str: return []
    raw = re.split(r"[,،|;\n]", str(alias_str))
    return [normalize_text(a) for a in raw if a.strip()]

def extract_features(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    brand, p_type, area = None, None, None
    for b in BRANDS:
        if b in text: brand = b; break
    for t, words in TYPE_WORDS.items():
        if any(w in text for w in words): p_type = t; break
    for a, words in AREA_WORDS.items():
        if any(w in text for w in words): area = a; break
    return brand, p_type, area

def is_available(status_str: str) -> bool:
    s = normalize_text(status_str)
    return not any(term == s or term in s for term in UNAVAILABLE_TERMS)

def get_product_identity(item: dict) -> str:
    return normalize_text(f"{item.get('name', '')} {item.get('brand', '')} {item.get('active_ingredient', '')}")

# ==========================================
# محرك البحث الآمن
# ==========================================
def safe_match(q_clean: str) -> Tuple[str, Optional[dict]]:
    if not q_clean or len(q_clean) < 2: return "FALLBACK", None

    if q_clean in BRANDS: return "BRAND_ONLY", None
    if any(q_clean in words for words in TYPE_WORDS.values()): return "CATEGORY_ONLY", None

    products = database.load_products()
    q_brand, q_type, q_area = extract_features(q_clean)

    # 1. Exact Match & Alias
    for p in products:
        p_name_norm = normalize_text(p.get("name", ""))
        if q_clean == p_name_norm or q_clean in get_aliases(p.get("aliases", "")):
            return "MATCHED", p

    # 2. Full Phrase Contains
    for p in products:
        p_id = get_product_identity(p)
        if q_clean in p_id:
            p_brand, p_type, p_area = extract_features(p_id)
            if q_brand and p_brand and q_brand != p_brand: continue
            if q_type and p_type and q_type != p_type: continue
            if q_area and p_area and q_area != p_area: continue
            return "MATCHED", p

    # 3. Filtered Fuzzy Match
    candidates = []
    for p in products:
        p_id = get_product_identity(p)
        p_brand, p_type, p_area = extract_features(p_id)

        if q_brand and p_brand and q_brand != p_brand: continue
        if q_type and p_type and q_type != p_type: continue
        if q_area and p_area and q_area != p_area: continue
        candidates.append((p, p_id))

    best_match, best_score = None, 0
    for p, p_id in candidates:
        score = difflib.SequenceMatcher(None, q_clean, p_id).ratio()
        if score > 0.75 and score > best_score:
            best_score = score
            best_match = p

    if best_match: return "MATCHED", best_match
    return "NOT_FOUND", None

# ==========================================
# توليد البدائل
# ==========================================
def get_cosmetic_alternatives(target_product: dict, query_clean: str, limit: int = 3) -> List[dict]:
    target_id = get_product_identity(target_product) if target_product else query_clean
    t_brand, t_type, t_area = extract_features(target_id)

    if not t_type: return [] 

    products = database.load_products()
    valid_alts = []
    for p in products:
        if not is_available(p.get("available", "متوفر")): continue
        if target_product and p.get("id") == target_product.get("id"): continue

        p_id = get_product_identity(p)
        _, p_type, p_area = extract_features(p_id)

        if p_type == t_type:
            # Area Conflict Check (No face wash instead of body wash)
            if t_area and p_area and t_area != p_area: continue
            valid_alts.append((p, p_id))

    # Ranking
    valid_alts.sort(key=lambda x: difflib.SequenceMatcher(None, query_clean, x[1]).ratio(), reverse=True)
    return [alt[0] for alt in valid_alts[:limit]]

# ==========================================
# معالجة النصوص وبناء الردود
# ==========================================
def handle_text_query(phone: str, text: str, user_state: dict) -> str:
    q_norm = normalize_text(text)
    q_clean = clean_query(text)

    # Greeting
    if q_norm in GREETINGS or q_clean in GREETINGS:
        return "مرحباً بك في صيدلية بدر البشرية 🌿\nأرسل اسم المنتج أو صورته للبحث عن السعر والتوفر."

    # Direct Commands
    if q_norm in ["نعم", "اي", "حجز", "yes"]:
        if "last_product" in user_state:
            item = user_state["last_product"]
            database.add_order(phone, item.get('name'))
            database.clear_user_state(phone)
            return f"🌿 صيدلية بدر البشرية\n\n✅ تم تسجيل طلب الحجز للمنتج: {item.get('name')}\nسيتم التواصل معك قريباً للتأكيد."
        return "لا يوجد منتج للحجز حالياً. الرجاء البحث عن منتج أولاً."

    if q_norm in ["لا", "الغاء", "no"]:
        database.clear_user_state(phone)
        return "🌿 صيدلية بدر البشرية\n\nتم الإلغاء. يمكنك البحث عن منتج آخر."

    # Pick Alternative by Number
    if q_norm.isdigit() and "pending_alternatives" in user_state:
        idx = int(q_norm) - 1
        alts = user_state["pending_alternatives"]
        if 0 <= idx < len(alts):
            selected_item = alts[idx]
            database.update_user_state(phone, {"last_product": selected_item})
            return build_product_reply(selected_item)

    # Matching
    status, item = safe_match(q_clean)

    if status == "FALLBACK":
        return "عذراً، لم أفهم طلبك بوضوح. يرجى إرسال اسم المنتج المطلوب أو صورته للبحث عنه."
    elif status == "BRAND_ONLY":
        return "الرجاء تحديد اسم المنتج بالكامل أو إرسال صورته (مثال: غسول سيرافي للبشرة الدهنية)."
    elif status == "CATEGORY_ONLY":
        return "الرجاء تحديد الشركة المصنعة أو اسم المنتج بالكامل (مثال: غسول سيرافي)."
    elif status == "MATCHED" and item:
        database.update_user_state(phone, {"last_product": item})
        return build_product_reply(item)
    else:
        return build_unavailable_reply(q_clean, None, phone)

def build_product_reply(item: dict) -> str:
    name = item.get("name", "")
    price = item.get("price", "")
    status_str = item.get("available", "متوفر")
    price_str = f"{price} د.ل" if price and "د" not in str(price) else str(price)

    reply = f"🌿 صيدلية بدر البشرية\n\n✅ المنتج: {name}\n💰 السعر: {price_str}\n"

    if is_available(status_str):
        reply += f"📦 الحالة: متوفر\n\nللحجز اكتب: نعم"
    else:
        reply += f"📦 الحالة: {status_str}\n\nالمنتج موجود في قائمة الصيدلية لكنه غير متوفر حالياً."
    return reply

def build_unavailable_reply(q_clean: str, target_product: Optional[dict], phone: str) -> str:
    alts = get_cosmetic_alternatives(target_product, q_clean)
    reply = "🌿 صيدلية بدر البشرية\n\nالمنتج المطلوب غير متوفر حالياً في قائمة الصيدلية."

    if alts:
        reply += "\n\n⭐ بدائل متوفرة قريبة من نفس النوع:\n"
        for i, alt in enumerate(alts, 1):
            reply += f"{i}) {alt.get('name')} - {alt.get('price', '')}\n"
        reply += "\nلاختيار بديل وحجزه، اكتب رقم المنتج (مثال: 1)."
        database.update_user_state(phone, {"pending_alternatives": alts})
    return reply

def build_unclear_image_reply() -> str:
    return "الصورة غير واضحة، الرجاء إرسال صورة أوضح أو كتابة اسم المنتج."
