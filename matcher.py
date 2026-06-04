import re
import difflib
from typing import List, Optional, Tuple, Dict, Set
import database

GREETINGS = ["السلام عليكم", "السلام عليكم ورحمة الله", "مرحبا", "مرحبتين", "هلا", "hi", "hello", "السلام"]

STOPWORDS = [
    "متوفر عندكم", "لو سمحت", "هل يوجد", "هل في", "عندكمش", "كم سعر", "شنو سعر", "سعره", "سعر", "بكم", "بكام", "قداش",
    "متوفر", "عندكم", "عنديكم", "موجود", "موجود عندكم", "هل", "نبي", "نبو", "اريد", "ابي", "أبي", "بالله", "يوجد", "توا", "عندك", "فيه", "في", "من فضلك", "لو سمحت"
]

# Common Arabic/English spelling fixes. This does not invent stock/price; it only helps match names already in the pharmacy DB.
SYNONYMS = {
    "cera ve": "cerave", "ceravé": "cerave", "سيرافي": "cerave", "سيرا في": "cerave",
    "moisturising": "moisturizing", "moisturiser": "moisturizer", "moisturising": "moisturizing",
    "la roche posay": "laroche", "la roche": "laroche", "لاروش بوزيه": "laroche", "لاروش": "laroche", "لاروشي": "laroche",
    "the ordinary": "theordinary", "ذا اورديناري": "theordinary", "اورديناري": "theordinary", "اوريدناري": "theordinary",
    "واقي شمس": "sunscreen", "sun block": "sunscreen", "sunblock": "sunscreen",
    "غسول وجه": "face cleanser", "غسول بشرة": "face cleanser", "غسول للبشرة": "face cleanser", "غسول البشره": "face cleanser", "غسول": "cleanser", "منظف": "cleanser",
    "مرطب": "moisturizer", "ترطيب": "moisturizer", "كريم": "cream", "لوشن": "lotion", "سيروم": "serum", "شامبو": "shampoo",
    # frequent medicine spellings in Libya/Arabic input
    "بانادول": "panadol", "بنادول": "panadol", "بندول": "panadol", "بانادول": "panadol", "بنادول": "panadol",
    "ادول": "adol", "أدول": "adol", "ادول شراب": "adol syrup",
    "براسيتامول": "paracetamol", "باراسيتامول": "paracetamol", "باراسيتامول": "paracetamol",
    "اموكلان": "amoclan", "اوموكلان": "amoclan", "اوجمنتين": "augmentin", "اوقمنتين": "augmentin",
    "زيرتك": "zyrtec", "تلفاست": "telfast", "كلاريتين": "claritine", "كلارتين": "claritine",
    "فولتارين": "voltaren", "كتافلام": "cataflam", "بروفين": "brufen", "بروفين": "brufen",
    "فلاجيل": "flagyl", "اوميبرازول": "omeprazole", "كونكور": "concor", "جلوكوفاج": "glucophage",
}

COSMETIC_BRANDS = [
    "cerave", "laroche", "cetaphil", "vichy", "eucerin", "bioderma", "acm", "svr", "uriage", "avene", "theordinary",
    "isispharma", "isis", "arvea", "anivagen", "mustela", "nuxe", "bioderma", "babaria", "ordinary", "dr.rashel", "dr rashel"
]

BRANDS = COSMETIC_BRANDS + ["panadol", "adol", "amoclan", "augmentin", "zyrtec", "telfast", "claritine", "voltaren", "cataflam", "brufen", "flagyl"]

TYPE_WORDS = {
    "cleanser": ["cleanser", "wash", "face wash", "foaming", "gel moussant", "moussant", "غسول", "منظف"],
    "sunscreen": ["sunscreen", "spf", "sunblock", "sun block", "واقي شمس", "واقي", "حماية"],
    "serum": ["serum", "سيروم"],
    "lotion": ["lotion", "لوشن"],
    "cream": ["cream", "كريم", "baume", "بلسم"],
    "moisturizer": ["moisturizer", "moisturizing", "moisturising", "hydrating", "مرطب", "ترطيب"],
    "shampoo": ["shampoo", "شامبو"],
    "syrup": ["syrup", "شراب"],
    "tablet": ["tablet", "tab", "قرص", "اقراص", "حبوب"],
    "drops": ["drops", "drop", "قطرة", "قطره"],
    "spray": ["spray", "بخاخ"],
}

AREA_WORDS = {
    "face": ["face", "visage", "وجه", "وجة", "بشرة", "بشره", "skin", "acne", "حبوب", "دهنية", "دهنيه", "oily", "normal skin"],
    "body": ["body", "corps", "جسم", "بدن"],
    "baby": ["baby", "enfant", "pediatril", "بيبي", "اطفال", "أطفال", "رضع", "kids", "طفل"],
    "hair": ["hair", "cheveux", "شعر", "scalp", "فروة"],
    "mouth": ["mouth", "oral", "dental", "teeth", "فم", "اسنان", "أسنان", "غسول فم"],
}

UNAVAILABLE_TERMS = ["غير متوفر", "غير موجود", "نافذ", "نفذ", "ناقص", "لا", "0", "no", "out of stock", "unavailable"]
SHARED_TERMS = ["acne", "oily", "dry", "sensitive", "sa", "foaming", "hydrating", "moisturizing", "دهنية", "دهنيه", "جافة", "حساسة"]
GENERIC_TERMS = set(["cleanser", "wash", "face wash", "غسول", "غسول وجه", "مرطب", "moisturizer", "lotion", "cream", "serum", "shampoo", "sunscreen", "واقي", "واقي شمس", "كريم", "لوشن", "سيروم", "شامبو", "face", "skin", "بشره", "بشرة", "وجه"] + COSMETIC_BRANDS)

TOKEN_STOP = set(["and", "or", "the", "for", "with", "normal", "to", "skin", "ل", "لل", "مع", "من", "في", "على"])


def normalize_text(text: str) -> str:
    s = str(text or "").strip().lower()
    arabic_map = {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ٱ": "ا"}
    for src, dst in arabic_map.items():
        s = s.replace(src, dst)
    s = s.replace("ـ", "")
    s = re.sub(r"[\u064b-\u065f]", "", s)
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    for src, dst in sorted(SYNONYMS.items(), key=lambda x: len(normalize_text_no_syn(x[0])), reverse=True):
        src_norm = normalize_text_no_syn(src)
        s = re.sub(rf"(?<!\w){re.escape(src_norm)}(?!\w)", normalize_text_no_syn(dst), s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_text_no_syn(text: str) -> str:
    s = str(text or "").strip().lower()
    for src, dst in {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ٱ": "ا"}.items():
        s = s.replace(src, dst)
    s = s.replace("ـ", "")
    s = re.sub(r"[\u064b-\u065f]", "", s)
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def clean_query(text: str) -> str:
    s = normalize_text(text)
    for word in sorted(STOPWORDS, key=len, reverse=True):
        word_norm = normalize_text(word)
        s = re.sub(rf"(?<!\w){re.escape(word_norm)}(?!\w)", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def tokens(text: str) -> List[str]:
    return [t for t in normalize_text(text).split() if len(t) > 1 and t not in TOKEN_STOP]


def get_aliases(alias_str: str) -> List[str]:
    if not alias_str:
        return []
    raw = re.split(r"[,،|;\n/]+", str(alias_str))
    return [normalize_text(a) for a in raw if a and a.strip()]


def _contains_phrase(text: str, phrase: str) -> bool:
    phrase = normalize_text(phrase)
    text = normalize_text(text)
    if not phrase:
        return False
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None or phrase in text


def extract_features(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    norm = normalize_text(text)
    brand = None
    # longest brand first, so laroche wins before roche-like fragments
    for b in sorted(BRANDS, key=len, reverse=True):
        b_norm = normalize_text(b)
        if _contains_phrase(norm, b_norm):
            brand = b_norm
            break
    p_type = None
    # cleanser should beat hydrating/moisturizing for Hydrating Cleanser
    type_order = ["cleanser", "sunscreen", "serum", "shampoo", "lotion", "cream", "moisturizer", "syrup", "tablet", "drops", "spray"]
    for t in type_order:
        for w in TYPE_WORDS.get(t, []):
            if _contains_phrase(norm, w):
                p_type = t
                break
        if p_type:
            break
    area = None
    for a, words in AREA_WORDS.items():
        for w in words:
            if _contains_phrase(norm, w):
                area = a
                break
        if area:
            break
    return brand, p_type, area


def is_available(status_str: str) -> bool:
    s = normalize_text(status_str)
    if not s:
        return True
    return not any(term == s or term in s for term in [normalize_text(x) for x in UNAVAILABLE_TERMS])


def is_cosmetic_context(text: str, p_type: Optional[str] = None) -> bool:
    norm = normalize_text(text)
    b, t, a = extract_features(norm)
    if b in [normalize_text(x) for x in COSMETIC_BRANDS]:
        return True
    if a in ["face", "body", "hair"] and t in ["cleanser", "moisturizer", "lotion", "cream", "serum", "sunscreen", "shampoo"]:
        return True
    # cream alone is not enough; many medical creams should not get random substitutes.
    if p_type in ["cleanser", "sunscreen", "serum", "lotion", "moisturizer"] and any(w in norm for w in ["face", "skin", "بشره", "بشرة", "وجه", "acne", "oily", "dry"]):
        return True
    return False


def is_cosmetic(p_type: Optional[str], context: str = "") -> bool:
    return is_cosmetic_context(context, p_type)


def get_product_identity(item: dict) -> str:
    parts = [
        item.get('name', ''), item.get('brand', ''), item.get('company', ''), item.get('form', ''),
        item.get('active_ingredient', ''), item.get('aliases', ''), item.get('strength', ''), item.get('pack', '')
    ]
    return normalize_text(" ".join(str(p) for p in parts if p is not None))


def _is_generic_alias(alias: str) -> bool:
    a = normalize_text(alias)
    return not a or a in {normalize_text(x) for x in GENERIC_TERMS} or len(a.split()) == 1 and a in {normalize_text(x) for x in GENERIC_TERMS}


def _brand_required_ok(q_brand: Optional[str], p_id: str) -> bool:
    if not q_brand:
        return True
    # If the query explicitly says CeraVe, the candidate identity must contain CeraVe. This prevents Alfa/ARVEA wins.
    return _contains_phrase(p_id, q_brand)


def _conflicts(q_type, q_area, p_id: str) -> bool:
    _, p_type, p_area = extract_features(p_id)
    if q_type and p_type and q_type != p_type:
        return True
    if q_area and p_area and q_area != p_area:
        return True
    return False


def _score_candidate(q_clean: str, p_id: str) -> float:
    q_toks = [t for t in tokens(q_clean) if t not in GENERIC_TERMS]
    p_toks = set(tokens(p_id))
    if not q_toks:
        q_toks = tokens(q_clean)
    if not q_toks:
        return 0.0
    hits = sum(1 for t in q_toks if t in p_toks or any(t in pt or pt in t for pt in p_toks if len(t) >= 3 and len(pt) >= 3))
    coverage = hits / max(len(q_toks), 1)
    seq = difflib.SequenceMatcher(None, q_clean, p_id).ratio()
    substring_bonus = 0.2 if q_clean and q_clean in p_id else 0
    return coverage * 0.65 + seq * 0.35 + substring_bonus


def safe_match(q_clean: str) -> Tuple[str, Optional[dict]]:
    q_clean = clean_query(q_clean)
    if not q_clean or len(q_clean) < 2:
        return "FALLBACK", None

    q_brand, q_type, q_area = extract_features(q_clean)
    products = database.load_products()

    # 1) Exact normalized product name or safe exact alias
    for p in products:
        p_name_norm = normalize_text(p.get("name", ""))
        aliases = get_aliases(p.get("aliases", ""))
        if q_clean == p_name_norm:
            return "MATCHED", p
        for a in aliases:
            if q_clean == a and not _is_generic_alias(a):
                if _brand_required_ok(q_brand, get_product_identity(p)):
                    return "MATCHED", p

    # 2) Full phrase contains, with strict brand/type/area constraints
    for p in products:
        p_id = get_product_identity(p)
        if not _brand_required_ok(q_brand, p_id):
            continue
        if _conflicts(q_type, q_area, p_id):
            continue
        if len(q_clean) >= 4 and (q_clean in p_id or p_id in q_clean):
            # Avoid category-only phrase accidentally matching a random generic item
            if q_clean in {normalize_text(x) for x in GENERIC_TERMS}:
                continue
            return "MATCHED", p

    # 3) Stop unsafe generic requests before fuzzy matching
    q_words = q_clean.split()
    if q_type and not q_brand and len(q_words) <= 3:
        return "CATEGORY_ONLY", None
    if q_brand in [normalize_text(x) for x in COSMETIC_BRANDS] and not q_type and len(q_words) <= 3:
        return "BRAND_ONLY", None

    # 4) Candidate scoring. Allows one-word drug/brand names like Panadol when present in DB.
    candidates = []
    for p in products:
        p_id = get_product_identity(p)
        if not _brand_required_ok(q_brand, p_id):
            continue
        if _conflicts(q_type, q_area, p_id):
            continue
        candidates.append((p, p_id))

    best_match, best_score = None, 0.0
    for p, p_id in candidates:
        score = _score_candidate(q_clean, p_id)
        if score > best_score:
            best_score = score
            best_match = p

    # Thresholds: stricter for short/generic terms, more tolerant for full product names.
    min_score = 0.82 if len(q_words) <= 1 else 0.72
    if q_brand or q_type:
        min_score -= 0.04
    if best_match and best_score >= min_score:
        return "MATCHED", best_match

    # 5) If arbitrary one-word text does not match anything, ask for clearer input rather than saying unavailable.
    if not q_brand and not q_type and len(q_words) <= 1:
        return "FALLBACK", None

    return "UNAVAILABLE", None


def get_cosmetic_alternatives(target_product: dict, query_clean: str, limit: int = 3, explicit_area: str = None) -> List[dict]:
    query_clean = clean_query(query_clean)
    target_id = get_product_identity(target_product) if target_product else query_clean
    t_brand, t_type, t_area = extract_features(target_id)
    if explicit_area and normalize_text(explicit_area) not in ["unknown", "none", ""]:
        t_area = normalize_text(explicit_area)

    if not t_type:
        _, t_type, _ = extract_features(query_clean)
    if not is_cosmetic_context(target_id + " " + query_clean, t_type):
        return []

    # Default well-known cosmetic cleansers to face unless user/AI says otherwise.
    if t_type == "cleanser" and not t_area:
        if not any(_contains_phrase(query_clean, w) for w in AREA_WORDS["body"] + AREA_WORDS["hair"] + AREA_WORDS["baby"] + AREA_WORDS["mouth"]):
            t_area = "face"

    products = database.load_products()
    valid_alts = []
    face_blacklist = [normalize_text(w) for w in AREA_WORDS["body"] + AREA_WORDS["baby"] + AREA_WORDS["hair"] + AREA_WORDS["mouth"] + ["shampoo", "شامبو", "mouth wash", "body wash", "baby wash", "oral", "dental"]]

    for p in products:
        if not is_available(p.get("available", "متوفر")):
            continue
        if target_product and str(p.get("id")) == str(target_product.get("id")):
            continue
        p_id = get_product_identity(p)
        p_brand, p_type, p_area = extract_features(p_id)
        if p_type != t_type:
            continue
        if t_area == "face":
            if any(bw and bw in p_id for bw in face_blacklist):
                continue
            # Prefer explicitly face/skin products; if area unknown, allow only if no blacklisted area words.
        elif t_area and p_area and t_area != p_area:
            continue

        score = 0.0
        if t_brand and p_brand == t_brand:
            score += 50
        if t_area and p_area == t_area:
            score += 30
        for term in SHARED_TERMS:
            if normalize_text(term) in target_id and normalize_text(term) in p_id:
                score += 10
        score += _score_candidate(query_clean or target_id, p_id) * 30
        valid_alts.append((score, p))

    valid_alts.sort(key=lambda x: x[0], reverse=True)
    return [alt[1] for alt in valid_alts[:limit]]


def handle_text_query(phone: str, text: str, user_state: dict) -> str:
    q_norm = normalize_text(text)
    q_clean = clean_query(text)

    if q_norm in [normalize_text(g) for g in GREETINGS] or q_clean in [normalize_text(g) for g in GREETINGS]:
        return "مرحباً بك في صيدلية بدر البشرية 🌿\nأرسل اسم المنتج أو صورته للبحث عن السعر والتوفر."

    if q_norm in ["نعم", "اي", "حجز", "yes", "تمام"]:
        if "last_product" in user_state:
            item = user_state["last_product"]
            if not is_available(item.get("available", "متوفر")):
                database.clear_user_state(phone)
                return "عذراً، المنتج المطلوب غير متوفر حالياً للحجز."
            database.add_order(phone, item.get('name'), item.get('price', ''))
            database.clear_user_state(phone)
            return f"🌿 صيدلية بدر البشرية\n\n✅ تم تسجيل طلب الحجز للمنتج:\n{item.get('name')}\nسيتم التواصل معك قريباً للتأكيد."
        return "لا يوجد منتج متاح للحجز حالياً. الرجاء البحث عن منتج أولاً."

    if q_norm in ["لا", "الغاء", "إلغاء", "no"]:
        database.clear_user_state(phone)
        return "🌿 صيدلية بدر البشرية\n\nتم الإلغاء. يمكنك البحث عن منتج آخر."

    if q_norm.isdigit() and "pending_alternatives" in user_state:
        idx = int(q_norm) - 1
        alts = user_state["pending_alternatives"]
        if 0 <= idx < len(alts):
            selected_item = alts[idx]
            database.clear_user_state(phone)
            if is_available(selected_item.get("available", "متوفر")):
                database.update_user_state(phone, {"last_product": selected_item})
            return build_product_reply(selected_item)

    status, item = safe_match(q_clean)

    if status == "FALLBACK":
        return "لم أفهم اسم المنتج المطلوب. الرجاء إرسال اسم المنتج أو صورته بوضوح."
    if status == "BRAND_ONLY":
        return "الرجاء تحديد اسم المنتج بالكامل أو إرسال صورته (مثال: غسول سيرافي للبشرة الدهنية)."
    if status == "CATEGORY_ONLY":
        return "الرجاء تحديد الشركة المصنعة أو اسم المنتج بالكامل (مثال: غسول سيرافي أو غسول لاروش)."
    if status == "MATCHED" and item:
        if is_available(item.get("available", "متوفر")):
            database.update_user_state(phone, {"last_product": item})
        else:
            database.clear_user_state(phone)
        return build_product_reply(item)
    return build_unavailable_reply(q_clean, None, phone)


def build_product_reply(item: dict) -> str:
    name = item.get("name", "")
    price = str(item.get("price", ""))
    status_str = str(item.get("available", "متوفر"))
    price_str = f"{price} د.ل" if price and "د" not in price else price
    reply = f"🌿 صيدلية بدر البشرية\n\n✅ المنتج: {name}\n💰 السعر: {price_str}\n"
    if is_available(status_str):
        reply += "📦 الحالة: متوفر\n\nللحجز اكتب: نعم"
    else:
        reply += f"📦 الحالة: {status_str}\n\nالمنتج موجود في قائمة الصيدلية لكنه غير متوفر حالياً."
    return reply


def build_unavailable_reply(q_clean: str, target_product: Optional[dict], phone: str, explicit_area: str = None) -> str:
    alts = get_cosmetic_alternatives(target_product, q_clean, explicit_area=explicit_area)
    reply = "🌿 صيدلية بدر البشرية\n\nالمنتج المطلوب غير متوفر حالياً في قائمة الصيدلية."
    if alts:
        reply += "\n\n⭐ بدائل متوفرة قريبة من نفس النوع:\n"
        for i, alt in enumerate(alts, 1):
            price = alt.get('price', '')
            reply += f"{i}) {alt.get('name')} - {price}\n"
        reply += "\nلاختيار بديل وحجزه، اكتب رقم المنتج (مثال: 1)."
        database.update_user_state(phone, {"pending_alternatives": alts})
    else:
        database.clear_user_state(phone)
    return reply


def build_unclear_image_reply() -> str:
    return "الصورة غير واضحة، الرجاء إرسال صورة أوضح أو كتابة اسم المنتج."
