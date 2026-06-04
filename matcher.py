import re
import difflib
from typing import List, Optional, Tuple
import database

# ==========================================
# القواميس الذكية للفلترة (النقطة 13)
# ==========================================
SYNONYMS = {
    "cera ve": "cerave", "moisturising": "moisturizing", "moisturiser": "moisturizer",
    "سيرافي": "cerave", "غسول": "cleanser", "منظف": "cleanser", "مرطب": "moisturizer",
    "لوشن": "lotion", "كريم": "cream", "سيروم": "serum", "لاروش": "laroche",
    "la roche": "laroche", "la roche posay": "laroche",
    "واقي شمس": "sunscreen", "شامبو": "shampoo"
}

TYPE_WORDS = {
    "cleanser": ["cleanser", "wash", "foaming", "gel moussant", "غسول", "منظف", "face wash"],
    "moisturizer": ["moisturizer", "مرطب", "moisturising"],
    "lotion": ["lotion", "لوشن"],
    "cream": ["cream", "كريم", "baume"],
    "serum": ["serum", "سيروم"],
    "sunscreen": ["sunscreen", "spf", "واقي شمس", "sunblock"],
    "shampoo": ["shampoo", "شامبو"]
}

# قوائم لمنع البحث بكلمة واحدة عامة
BRANDS = ["cerave", "laroche", "cetaphil", "vichy", "eucerin", "bioderma", "سيرافي", "لاروش", "سيتافيل", "فيشي", "يوسيرين"]
CATEGORIES = ["cleanser", "moisturizer", "lotion", "cream", "serum", "sunscreen", "shampoo", "غسول", "مرطب", "لوشن", "كريم", "سيروم", "واقي", "شامبو"]

def normalize_text(text: str) -> str:
    s = str(text or "").strip().lower()
    for src, dst in {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ط": "ط"}.items():
        s = s.replace(src, dst)
    s = re.sub(r"[^\w\s\u0600-\u06FF]+", " ", s)
    for src, dst in sorted(SYNONYMS.items(), key=lambda x: len(x[0]), reverse=True):
        s = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, s)
    return re.sub(r"\s+", " ", s).strip()

def detect_type(norm_text: str) -> Optional[str]:
    for t_key, words in TYPE_WORDS.items():
        if any(w in norm_text.split() for w in words):
            return t_key
    return None

def get_product_identity(item: dict) -> str:
    return normalize_text(f"{item.get('name', '')} {item.get('aliases', '')} {item.get('brand', '')} {item.get('form', '')}")

# ==========================================
# محرك البحث الجبار المطابق للشروط
# ==========================================
def safe_match(query: str) -> Tuple[str, Optional[dict]]:
    """يرجع حالة البحث: MATCHED, BRAND_ONLY, CATEGORY_ONLY, NOT_FOUND"""
    q_norm = normalize_text(query)
    if not q_norm:
        return "NOT_FOUND", None
        
    # منع CeraVe فقط أو cleanser فقط
    if any(q_norm == b for b in BRANDS): return "BRAND_ONLY", None
    if any(q_norm == c for c in CATEGORIES): return "CATEGORY_ONLY", None

    products = database.load_products()
    q_type = detect_type(q_norm)
    
    # 1. المطابقة الدقيقة جداً (الاسم أو الاسم البديل)
    for p in products:
        p_name = normalize_text(p.get("name", ""))
        aliases = [normalize_text(a) for a in str(p.get("aliases", "")).split(",") if a.strip()]
        if q_norm == p_name or q_norm in aliases:
            return "MATCHED", p
            
    # 2. المطابقة التقريبية الآمنة (منع تداخل غسول مع لوشن)
    best_match, best_score = None, 0
    for p in products:
        p_id = get_product_identity(p)
        if q_norm in p_id:
            p_type = detect_type(p_id)
            if q_type and p_type and q_type != p_type: continue # منع التداخل (Conflict)
            return "MATCHED", p
            
        score = difflib.SequenceMatcher(None, q_norm, p_id).ratio()
        if score > 0.85: # نسبة دقة عالية لتجنب الأخطاء
            p_type = detect_type(p_id)
            if q_type and p_type and q_type != p_type: continue
            if score > best_score:
                best_score = score
                best_match = p
                
    if best_match: return "MATCHED", best_match
    return "NOT_FOUND", None

# ==========================================
# استخراج البدائل (النقطة 14)
# ==========================================
def get_cosmetic_alternatives(query: str, limit: int = 3) -> List[dict]:
    q_norm = normalize_text(query)
    target_type = detect_type(q_norm)
    if not target_type: return []
        
    products = database.load_products()
    alts = []
    for p in products:
        if str(p.get("available", "متوفر")).strip() == "غير متوفر": continue
        if detect_type(get_product_identity(p)) == target_type:
            alts.append(p)
            if len(alts) >= limit: break
    return alts

# ==========================================
# مدير الردود (النقطة 17)
# ==========================================
def build_product_reply(item: dict) -> str:
    name, price, available = item.get("name", ""), item.get("price", ""), item.get("available", "متوفر")
    price_str = f"{price} د.ل" if price and "د" not in str(price) else str(price)
    return f"🌿 صيدلية بدر البشرية\n\n✅ المنتج: {name}\n📦 الحالة: {available}\n💰 السعر: {price_str}\n\nللحجز اكتب: نعم"

def build_unavailable_reply(query: str) -> str:
    alts = get_cosmetic_alternatives(query)
    base_msg = "🌿 صيدلية بدر البشرية\n\nالمنتج المطلوب غير متوفر حالياً في قائمة الصيدلية."
    if alts:
        base_msg += "\n\n⭐ بدائل متوفرة قريبة من نفس النوع:\n"
        for i, alt in enumerate(alts, 1):
            base_msg += f"{i}) {alt.get('name')} - {alt.get('price', '')}\n"
    return base_msg

def build_unclear_image_reply() -> str: # (النقطة 15)
    return "الصورة غير واضحة، الرجاء إرسال صورة أوضح أو كتابة اسم المنتج."

# ==========================================
# الدالة الرئيسية التي تعالج النصوص
# ==========================================
def handle_text_query(phone: str, text: str, user_state: dict) -> str:
    q_norm = normalize_text(text)
    
    if q_norm in ["نعم", "اي", "حجز", "yes"]:
        if "last_product" in user_state:
            item = user_state["last_product"]
            database.clear_user_state(phone)
            return f"🌿 صيدلية بدر البشرية\n\nتم تسجيل طلب الحجز للمنتج: {item.get('name')}\nسيتم التواصل معك للتأكيد."
        return "لا يوجد منتج للحجز حالياً. الرجاء البحث عن منتج أولاً."
            
    if q_norm in ["لا", "الغاء", "no"]:
        database.clear_user_state(phone)
        return "🌿 صيدلية بدر البشرية\n\nتم الإلغاء. يمكنك البحث عن منتج آخر."

    status, item = safe_match(text)
    if status == "BRAND_ONLY": return "الرجاء تحديد اسم المنتج بالكامل أو إرسال صورته (مثال: غسول سيرافي للبشرة الدهنية)."
    elif status == "CATEGORY_ONLY": return "الرجاء تحديد الشركة المصنعة أو اسم المنتج بالكامل (مثال: غسول سيرافي)."
    elif status == "MATCHED" and item:
        database.update_user_state(phone, {"last_product": item})
        return build_product_reply(item)
    else:
        return build_unavailable_reply(text)
