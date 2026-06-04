import re
import difflib
from typing import List, Optional, Tuple
import database

# ==========================================
# 1. القواميس والمفردات الذكية
# ==========================================
GREETINGS = ["السلام عليكم", "مرحبا", "hi", "hello", "هلا", "مرحبتين"]

# (النقطة 7 و 13) كلمات الطلب التي يجب حذفها قبل المطابقة
STOPWORDS = [
    "متوفر", "عندكم", "موجود", "بكم", "سعر", "هل", "نبي", "اريد", "في", "فيه", "عندك", "بكام", 
    "قداش", "كم", "شنو", "ما", "ابي", "نبو", "لو سمحت", "بالله", "يوجد", "توا", "عندكمش", "أبي"
]

SYNONYMS = {
    "cera ve": "cerave", "moisturising": "moisturizing", "moisturiser": "moisturizer",
    "سيرافي": "cerave", "لاروش": "laroche", "la roche": "laroche", "la roche posay": "laroche",
    "واقي شمس": "sunscreen", "sun block": "sunscreen", "غسول": "cleanser", "كريم": "cream",
    "the ordinary": "theordinary", "ذا اورديناري": "theordinary", "اوريدناري": "theordinary"
}

BRANDS = [
    "cerave", "laroche", "cetaphil", "vichy", "eucerin", "bioderma", "acm", "svr", 
    "uriage", "avene", "theordinary", "سيرافي", "لاروش", "يوسيرين", "سيتافيل", "فيشي"
]

TYPE_WORDS = {
    "cleanser": ["cleanser", "wash", "foaming", "gel moussant", "غسول", "منظف", "face wash"],
    "moisturizer": ["moisturizer", "مرطب", "moisturising", "hydrating"],
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
# 2. دوال التنظيف والمعالجة
# ==========================================
def normalize_text(text: str) -> str:
    s = str(text or "").strip().lower()
    for src, dst in {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"}.items():
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
    """(النقطة 33) تقسيم الأسماء البديلة مهما كان الفاصل"""
    if not alias_str: return []
    raw = re.split(r"[,،|;\n]", str(alias_str))
    return [normalize_text(a) for a in raw if a.strip()]

def extract_features(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """استخراج الخصائص بذكاء باستخدام Substring بدل Split (النقطة 8)"""
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

def is_cosmetic(p_type: Optional[str]) -> bool:
    """(النقطة 16) التأكد من أن المنتج كوزمتك لاقتراح بدائل"""
    return bool(p_type)

def get_product_identity(item: dict) -> str:
    """(النقطة 5) هوية المنتج الشاملة لمنع ضياع البراند لو كان مسجلاً في حقل الشركة"""
    parts = [
        item.get('name', ''), item.get('brand', ''), item.get('company', ''), 
        item.get('form', ''), item.get('active_ingredient', ''), 
        item.get('aliases', ''), item.get('strength', ''), item.get('pack', '')
    ]
    return normalize_text(" ".join([str(p) for p in parts if p]))

# ==========================================
# 3. محرك البحث الصارم
# ==========================================
def safe_match(q_clean: str) -> Tuple[str, Optional[dict]]:
    if not q_clean or len(q_clean) < 2: return "FALLBACK", None

    q_brand, q_type, q_area = extract_features(q_clean)
    
    # (النقطة 6 و 12 و 14) التمييز بين النص العشوائي، والبحث العام، والبحث الدقيق
    if not q_brand and not q_type and len(q_clean.split()) == 1 and not any(q_clean in w for words in TYPE_WORDS.values() for w in words):
        return "FALLBACK", None

    if q_brand and not q_type and len(q_clean.split()) <= 2: return "BRAND_ONLY", None
    if q_type and not q_brand and not q_area and len(q_clean.split()) <= 2: return "CATEGORY_ONLY", None

    products = database.load_products()

    # 1. Exact Match (Name or Alias)
    for p in products:
        if q_clean == normalize_text(p.get("name", "")) or q_clean in get_aliases(p.get("aliases", "")):
            return "MATCHED", p

    # 2. Full Phrase Contains
    for p in products:
        p_id = get_product_identity(p)
        if q_clean in p_id:
            p_brand, p_type, p_area = extract_features(p_id)
            if q_brand and p_brand and q_brand != p_brand: continue
            if q_type and p_type and q_type != p_type: continue
            return "MATCHED", p

    # 3. Filtered Fuzzy Match (النقطة 34 و 35)
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
        if score > 0.70 and score > best_score:
            best_score = score
            best_match = p

    if best_match: return "MATCHED", best_match
    return "UNAVAILABLE", None

# ==========================================
# 4. توليد وترتيب البدائل الذكية
# ==========================================
def get_cosmetic_alternatives(target_product: dict, query_clean: str, limit: int = 3) -> List[dict]:
    target_id = get_product_identity(target_product) if target_product else query_clean
    t_brand, t_type, t_area = extract_features(target_id)

    # لا توجد بدائل إلا للكوزمتك
    if not is_cosmetic(t_type): return [] 

    products = database.load_products()
    valid_alts = []
    
    for p in products:
        if not is_available(p.get("available", "متوفر")): continue
        if target_product and str(p.get("id")) == str(target_product.get("id")): continue

        p_id = get_product_identity(p)
        p_brand, p_type, p_area = extract_features(p_id)

        if p_type == t_type:
            # (النقطة 15 و 36 و 37) فلترة المناطق الصارمة
            if t_area == "face":
                if any(w in p_id for w in AREA_WORDS["body"] + AREA_WORDS["baby"] + AREA_WORDS["hair"] + AREA_WORDS["mouth"]):
                    continue
            elif t_area and p_area and t_area != p_area: 
                continue
                
            # حساب سكور للترتيب
            score = 0
            if t_brand and p_brand == t_brand: score += 50
            if t_area and p_area == t_area: score += 30
            score += difflib.SequenceMatcher(None, query_clean, p_id).ratio() * 20
            
            valid_alts.append((score, p))

    valid_alts.sort(key=lambda x: x[0], reverse=True)
    return [alt[1] for alt in valid_alts[:limit]]

# ==========================================
# 5. معالجة النصوص وبناء الردود
# ==========================================
def handle_text_query(phone: str, text: str, user_state: dict) -> str:
    q_norm = normalize_text(text)
    q_clean = clean_query(text)

    # الترحيب (النقطة 5)
    if q_norm in GREETINGS or q_clean in GREETINGS:
        return "مرحباً بك في صيدلية بدر البشرية 🌿\nأرسل اسم المنتج أو صورته للبحث عن السعر والتوفر."

    # (النقطة 18) الحجز بعد اختيار البديل
    if q_norm in ["نعم", "اي", "حجز", "yes"]:
        if "last_product" in user_state:
            item = user_state["last_product"]
            database.add_order(phone, item.get('name'), item.get('price', ''))
            database.clear_user_state(phone)
            return f"🌿 صيدلية بدر البشرية\n\n✅ تم تسجيل طلب الحجز للمنتج:\n{item.get('name')}\nسيتم التواصل معك قريباً."
        return "لا يوجد منتج متاح للحجز حالياً. الرجاء البحث عن منتج أولاً."

    if q_norm in ["لا", "الغاء", "no"]:
        database.clear_user_state(phone)
        return "🌿 صيدلية بدر البشرية\n\nتم الإلغاء. يمكنك البحث عن منتج آخر."

    # (النقطة 15 من طلبات المشرف السابقة) اختيار رقم البديل
    if q_norm.isdigit() and "pending_alternatives" in user_state:
        idx = int(q_norm) - 1
        alts = user_state["pending_alternatives"]
        if 0 <= idx < len(alts):
            selected_item = alts[idx]
            database.clear_user_state(phone) # تفريغ البدائل
            # (النقطة 19) تخزين المنتج فقط إذا كان متوفراً
            if is_available(selected_item.get("available", "متوفر")):
                database.update_user_state(phone, {"last_product": selected_item})
            return build_product_reply(selected_item)

    status, item = safe_match(q_clean)

    if status == "FALLBACK":
        return "لم أفهم اسم المنتج المطلوب. الرجاء إرسال اسم المنتج أو صورته بوضوح."
    elif status == "BRAND_ONLY":
        return "الرجاء تحديد اسم المنتج بالكامل أو إرسال صورته (مثال: غسول سيرافي للبشرة الدهنية)."
    elif status == "CATEGORY_ONLY":
        return "الرجاء تحديد الشركة المصنعة أو اسم المنتج بالكامل (مثال: غسول سيرافي)."
    elif status == "MATCHED" and item:
        # (النقطة 19) تخزين المنتج للحجز فقط إذا كان متوفراً
        if is_available(item.get("available", "متوفر")):
            database.update_user_state(phone, {"last_product": item})
        else:
            database.clear_user_state(phone)
        return build_product_reply(item)
    else:
        return build_unavailable_reply(q_clean, None, phone)

def build_product_reply(item: dict) -> str:
    name = item.get("name", "")
    price = str(item.get("price", ""))
    status_str = str(item.get("available", "متوفر"))
    price_str = f"{price} د.ل" if price and "د" not in price else price

    reply = f"🌿 صيدلية بدر البشرية\n\n✅ المنتج: {name}\n💰 السعر: {price_str}\n"

    # (النقطة 12) إظهار زر الحجز فقط عند التوفر
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
    else:
        database.clear_user_state(phone)
        
    return reply

def build_unclear_image_reply() -> str:
    return "الصورة غير واضحة، الرجاء إرسال صورة أوضح أو كتابة اسم المنتج."
