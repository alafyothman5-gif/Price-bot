import re
import difflib
from typing import List, Optional, Tuple
import database

# ==========================================
# 1. القواميس والمفردات الذكية (محدثة بالكامل)
# ==========================================
GREETINGS = ["السلام عليكم", "مرحبا", "hi", "hello", "هلا", "مرحبتين"]

# (النقطة 13) كلمات الطلب مرتبة من الأطول للأقصر لضمان الحذف الصحيح
STOPWORDS = [
    "متوفر عندكم", "لو سمحت", "هل يوجد", "هل في", "عندكمش",
    "متوفر", "عندكم", "موجود", "بكم", "سعر", "هل", "نبي", "اريد", "في", "فيه", "عندك", "بكام", 
    "قداش", "كم", "شنو", "ما", "ابي", "نبو", "بالله", "يوجد", "توا", "أبي"
]

SYNONYMS = {
    "cera ve": "cerave", "moisturising": "moisturizing", "moisturiser": "moisturizer",
    "سيرافي": "cerave", "لاروش": "laroche", "la roche": "laroche", "la roche posay": "laroche",
    "واقي شمس": "sunscreen", "sun block": "sunscreen", "غسول": "cleanser", "كريم": "cream",
    "the ordinary": "theordinary", "ذا اورديناري": "theordinary", "اوريدناري": "theordinary"
}

BRANDS = [
    "cerave", "laroche", "cetaphil", "vichy", "eucerin", "bioderma", "acm", "svr", 
    "uriage", "avene", "theordinary", "سيرافي", "لاروش", "يوسيرين", "سيتافيل", "فيشي", "بيوديرما"
]

TYPE_WORDS = {
    "cleanser": ["cleanser", "wash", "foaming", "gel moussant", "غسول", "منظف", "face wash"],
    "moisturizer": ["moisturizer", "مرطب", "moisturising", "hydrating", "ترطيب"],
    "lotion": ["lotion", "لوشن"],
    "cream": ["cream", "كريم", "baume"],
    "serum": ["serum", "سيروم"],
    "sunscreen": ["sunscreen", "spf", "واقي شمس", "sunblock", "واقي", "حماية"],
    "shampoo": ["shampoo", "شامبو"]
}

# سيتم توحيد نصوص هذه القواميس تلقائياً لتجنب مشاكل (ة / ه)
AREA_WORDS = {
    "face": ["face", "visage", "وجه", "بشرة", "بشره"],
    "body": ["body", "corps", "جسم", "بدن"],
    "baby": ["baby", "enfant", "pediatril", "بيبي", "اطفال", "أطفال", "رضع", "kids"],
    "hair": ["hair", "cheveux", "شعر"],
    "mouth": ["mouth", "oral", "dental", "teeth", "فم", "اسنان", "أسنان"]
}

UNAVAILABLE_TERMS = ["غير متوفر", "غير موجود", "نافذ", "نفذ", "ناقص", "لا", "0", "no", "out of stock", "unavailable"]

# كلمات مشتركة لترتيب البدائل (النقطة 17)
SHARED_TERMS = ["acne", "oily", "dry", "sensitive", "sa", "foaming", "hydrating", "دهنية", "جافة", "حساسة"]

# ==========================================
# 2. دوال التنظيف والمعالجة
# ==========================================
def normalize_text(text: str) -> str:
    """(النقطة 6) توحيد الحروف العربية والإنجليزية بشكل صارم"""
    s = str(text or "").strip().lower()
    for src, dst in {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ط": "ط"}.items():
        s = s.replace(src, dst)
    s = re.sub(r"[^\w\s]+", " ", s)
    for src, dst in sorted(SYNONYMS.items(), key=lambda x: len(x[0]), reverse=True):
        s = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, s)
    return re.sub(r"\s+", " ", s).strip()

def clean_query(text: str) -> str:
    s = normalize_text(text)
    for word in sorted(STOPWORDS, key=len, reverse=True):
        word_norm = normalize_text(word)
        s = re.sub(rf"(?<!\w){re.escape(word_norm)}(?!\w)", "", s)
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
        if any(normalize_text(w) in text for w in words): p_type = t; break
    for a, words in AREA_WORDS.items():
        if any(normalize_text(w) in text for w in words): area = a; break
    return brand, p_type, area

def is_available(status_str: str) -> bool:
    s = normalize_text(status_str)
    return not any(term == s or term in s for term in UNAVAILABLE_TERMS)

def is_cosmetic(p_type: Optional[str]) -> bool:
    """(النقطة 16) التأكد أن المنتج كوزمتك"""
    return bool(p_type)

def get_product_identity(item: dict) -> str:
    """(النقطة 5) دمج كل حقول المنتج في هوية واحدة للمطابقة"""
    parts = [
        item.get('name', ''), item.get('brand', ''), item.get('company', ''), 
        item.get('form', ''), item.get('active_ingredient', ''), 
        item.get('aliases', ''), item.get('strength', ''), item.get('pack', '')
    ]
    return normalize_text(" ".join([str(p) for p in parts if p]))

# ==========================================
# 3. محرك المطابقة الصارم
# ==========================================
def safe_match(q_clean: str) -> Tuple[str, Optional[dict]]:
    if not q_clean or len(q_clean) < 2: return "FALLBACK", None

    products = database.load_products()
    
    # 1. المطابقة الدقيقة جداً (تفوز دائماً)
    for p in products:
        p_name_norm = normalize_text(p.get("name", ""))
        aliases = get_aliases(p.get("aliases", ""))
        if q_clean == p_name_norm or q_clean in aliases:
            return "MATCHED", p

    q_brand, q_type, q_area = extract_features(q_clean)
    
    # (النقطة 12 و 14) فحص الجودة وتصنيف البحث
    if not q_brand and not q_type and len(q_clean.split()) == 1:
        return "FALLBACK", None # كلمات مثل test123 أو خرابيط
        
    if q_type and not q_brand and len(q_clean.split()) <= 3:
        return "CATEGORY_ONLY", None # غسول وجه، face wash
        
    if q_brand and not q_type and len(q_clean.split()) <= 2:
        return "BRAND_ONLY", None # CeraVe

    # 2. المطابقة عبر العبارة الكاملة (مع فلترة البراند)
    for p in products:
        p_id = get_product_identity(p)
        if q_clean in p_id:
            p_brand, p_type, p_area = extract_features(p_id)
            if q_brand and p_brand and q_brand != p_brand: continue
            if q_type and p_type and q_type != p_type: continue
            return "MATCHED", p

    # 3. المطابقة التقريبية الآمنة
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
    return "UNAVAILABLE", None

# ==========================================
# 4. توليد البدائل (النقطة 7 و 15 و 17)
# ==========================================
def get_cosmetic_alternatives(target_product: dict, query_clean: str, limit: int = 3) -> List[dict]:
    target_id = get_product_identity(target_product) if target_product else query_clean
    t_brand, t_type, t_area = extract_features(target_id)

    if not is_cosmetic(t_type): return []

    products = database.load_products()
    valid_alts = []
    
    # القائمة السوداء لغسولات الوجه (النقطة 7)
    face_blacklist = [normalize_text(w) for w in AREA_WORDS["body"] + AREA_WORDS["baby"] + AREA_WORDS["hair"] + AREA_WORDS["mouth"] + ["shampoo", "شامبو", "mouth wash", "body wash", "baby wash"]]
    
    for p in products:
        if not is_available(p.get("available", "متوفر")): continue
        if target_product and str(p.get("id")) == str(target_product.get("id")): continue

        p_id = get_product_identity(p)
        p_brand, p_type, p_area = extract_features(p_id)

        if p_type == t_type:
            # (النقطة 7 و 15) فلترة المنطقة الصارمة جداً
            if t_area == "face":
                if any(bw in p_id for bw in face_blacklist):
                    continue
            elif t_area and p_area and t_area != p_area: 
                continue
                
            # (النقطة 17) حساب نسبة الترشيح (Ranking)
            score = 0
            if t_brand and p_brand == t_brand: score += 50
            if t_area and p_area == t_area: score += 30
            for term in SHARED_TERMS:
                if normalize_text(term) in target_id and normalize_text(term) in p_id:
                    score += 10
            score += difflib.SequenceMatcher(None, query_clean, p_id).ratio() * 20
            
            valid_alts.append((score, p))

    valid_alts.sort(key=lambda x: x[0], reverse=True)
    return [alt[1] for alt in valid_alts[:limit]]

# ==========================================
# 5. بناء الردود وادارة الحجوزات
# ==========================================
def handle_text_query(phone: str, text: str, user_state: dict) -> str:
    q_norm = normalize_text(text)
    q_clean = clean_query(text)

    # الترحيب
    if q_norm in GREETINGS or q_clean in GREETINGS:
        return "مرحباً بك في صيدلية بدر البشرية 🌿\nأرسل اسم المنتج أو صورته للبحث عن السعر والتوفر."

    # (النقطة 14 من رسائل المشرف) الحماية الإضافية للحجز
    if q_norm in ["نعم", "اي", "حجز", "yes"]:
        if "last_product" in user_state:
            item = user_state["last_product"]
            if not is_available(item.get("available", "متوفر")):
                database.clear_user_state(phone)
                return "عذراً، المنتج المطلوب غير متوفر حالياً للحجز."
                
            database.add_order(phone, item.get('name'), item.get('price', ''))
            database.clear_user_state(phone)
            return f"🌿 صيدلية بدر البشرية\n\n✅ تم تسجيل طلب الحجز للمنتج:\n{item.get('name')}\nسيتم التواصل معك قريباً للتأكيد."
        return "لا يوجد منتج متاح للحجز حالياً. الرجاء البحث عن منتج أولاً."

    if q_norm in ["لا", "الغاء", "no"]:
        database.clear_user_state(phone)
        return "🌿 صيدلية بدر البشرية\n\nتم الإلغاء. يمكنك البحث عن منتج آخر."

    # اختيار البديل بالرقم
    if q_norm.isdigit() and "pending_alternatives" in user_state:
        idx = int(q_norm) - 1
        alts = user_state["pending_alternatives"]
        if 0 <= idx < len(alts):
            selected_item = alts[idx]
            database.clear_user_state(phone)
            if is_available(selected_item.get("available", "متوفر")):
                database.update_user_state(phone, {"last_product": selected_item})
            return build_product_reply(selected_item)

    # المطابقة
    status, item = safe_match(q_clean)

    if status == "FALLBACK":
        return "لم أفهم اسم المنتج المطلوب. الرجاء إرسال اسم المنتج أو صورته بوضوح."
    elif status == "BRAND_ONLY":
        return "الرجاء تحديد اسم المنتج بالكامل أو إرسال صورته (مثال: غسول سيرافي للبشرة الدهنية)."
    elif status == "CATEGORY_ONLY":
        return "الرجاء تحديد الشركة المصنعة أو اسم المنتج بالكامل (مثال: غسول سيرافي)."
    elif status == "MATCHED" and item:
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
