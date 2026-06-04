import re
import json
import difflib
from typing import List, Optional, Tuple
import database

# ==========================================
# 1. القواميس الذكية (Smart Dictionaries)
# ==========================================
SYNONYMS = {
    "cera ve": "cerave", "moisturising": "moisturizing", "moisturiser": "moisturizer",
    "سيرافي": "cerave", "غسول": "cleanser", "منظف": "cleanser", "مرطب": "moisturizer",
    "لوشن": "lotion", "كريم": "cream", "سيروم": "serum", "لاروش": "la roche",
    "واقي شمس": "sunscreen", "شامبو": "shampoo", "بنادول": "panadol", "بروفين": "brufen"
}

TYPE_WORDS = {
    "cleanser": ["cleanser", "wash", "foaming", "gel moussant", "غسول", "منظف"],
    "moisturizer": ["moisturizer", "مرطب"], "lotion": ["lotion", "لوشن"],
    "cream": ["cream", "كريم"], "serum": ["serum", "سيروم"],
    "sunscreen": ["sunscreen", "spf", "واقي شمس"], "shampoo": ["shampoo", "شامبو"],
    "tablets": ["tablet", "tab", "اقراص", "حبوب"], "syrup": ["syrup", "شراب"],
}

# ==========================================
# 2. معالجة وتوحيد النصوص (Normalization)
# ==========================================
def normalize_text(text: str) -> str:
    s = str(text or "").strip().lower()
    for src, dst in {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"}.items():
        s = s.replace(src, dst)
    s = re.sub(r"[^\w\s\u0600-\u06FF]+", " ", s) # إزالة الرموز مع الاحتفاظ بالعربي والإنجليزي
    
    # تطبيق المرادفات الذكية
    for src, dst in sorted(SYNONYMS.items(), key=lambda x: len(x[0]), reverse=True):
        s = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, s)
        
    return re.sub(r"\s+", " ", s).strip()

def extract_code_tokens(text: str) -> List[str]:
    """استخراج الأكواد والأرقام بدقة (مثل 123syp أو 500mg) من ترقيعة V1"""
    q = normalize_text(text)
    raw = re.findall(r"[a-zA-Z]*\d+[a-zA-Z]*", q)
    tokens = []
    for t in raw:
        if len(re.sub(r"\D+", "", t)) <= 8: # تجاهل أرقام الهواتف
            tokens.append(t)
    return tokens

# ==========================================
# 3. محرك المطابقة الآمن (Safe Matcher V5)
# ==========================================
def product_identity_text(item: dict) -> str:
    """تجميع بيانات المنتج في نص واحد للبحث"""
    return " ".join([
        str(item.get("name", "")), str(item.get("aliases", "")),
        str(item.get("company", "")), str(item.get("form", "")),
        str(item.get("strength", ""))
    ]).lower()

def exact_safe_product_match(query: str) -> Optional[dict]:
    """البحث الدقيق والآمن جداً لمنع عرض أدوية خاطئة"""
    q_norm = normalize_text(query)
    if not q_norm or len(q_norm) < 2:
        return None
        
    products = database.load_products()
    code_tokens = extract_code_tokens(query)
    
    # 1. مطابقة الاسم الدقيق أولاً
    for item in products:
        if q_norm == normalize_text(item.get("name", "")):
            return item

    # 2. فلترة صارمة بالأكواد والأرقام (إذا الزبون كتب تركيز أو كود، لا نعرض منتجاً لا يحتويه)
    if code_tokens:
        products = [p for p in products if any(t in normalize_text(product_identity_text(p)) for t in code_tokens)]

    # 3. مطابقة الأسماء البديلة (Aliases)
    for item in products:
        aliases = [normalize_text(a) for a in str(item.get("aliases", "")).split(",") if a.strip()]
        if q_norm in aliases:
            return item
            
    # 4. البحث التقريبي (Fuzzy Search) للكلمات الطويلة
    if len(q_norm) >= 4:
        best_score = 0.0
        best_match = None
        for item in products:
            target = normalize_text(product_identity_text(item))
            score = difflib.SequenceMatcher(None, q_norm, target).ratio()
            if q_norm in target:
                score += 0.2 # رفع أولوية التطابق الجزئي
            if score > best_score and score >= 0.75:
                best_score = score
                best_match = item
        return best_match

    return None

def get_cosmetic_alternatives(query: str, limit: int = 5) -> List[dict]:
    """استخراج البدائل التجميلية بذكاء بناءً على النوع (غسول، لوشن، سيروم)"""
    q_norm = normalize_text(query)
    detected_types = [typ for typ, words in TYPE_WORDS.items() if any(w in q_norm for w in words)]
    
    if not detected_types:
        return []

    products = database.load_products()
    alternatives = []
    
    for item in products:
        item_text = normalize_text(product_identity_text(item))
        # التحقق من أن المنتج البديل من نفس النوع التجميلي وأنه متوفر
        if any(t_word in item_text for t_word in TYPE_WORDS[detected_types[0]]):
            if item.get("available", "متوفر") != "غير متوفر":
                alternatives.append(item)
                if len(alternatives) >= limit:
                    break
                    
    return alternatives

# ==========================================
# 4. مدير الردود (Reply Builder)
# ==========================================
def build_product_reply(item: dict) -> str:
    name = item.get("name", "")
    price = item.get("price", "")
    available = item.get("available", "متوفر")
    
    lines = [
        "🌿 صيدلية بدر البشرية", "",
        f"✅ المنتج: {name}",
        f"📦 الحالة: {available}"
    ]
    if price:
        lines.append(f"💰 السعر: {price} د.ل" if "د" not in price else f"💰 السعر: {price}")
    lines.extend(["", "للحجز اكتب: نعم"])
    return "\n".join(lines)

def build_unavailable_reply(query: str) -> str:
    alts = get_cosmetic_alternatives(query)
    if alts:
        lines = ["🌿 صيدلية بدر البشرية", "", "المنتج المطلوب غير متوفر حالياً.", "⭐ بدائل متوفرة قريبة من نفس النوع:", ""]
        for i, alt in enumerate(alts, 1):
            lines.append(f"{i}) {alt.get('name')} - {alt.get('price', '')}")
        lines.extend(["", "للحجز اكتب رقم المنتج المطلوب."])
        return "\n".join(lines)
        
    return "🌿 صيدلية بدر البشرية\n\nالمنتج المطلوب غير متوفر حالياً في قائمة الصيدلية. يمكنك إرسال اسم منتج آخر."

def handle_text_query(phone: str, text: str, user_state: dict) -> str:
    """الدالة الرئيسية التي سيستدعيها main.py لمعالجة النصوص"""
    q_norm = normalize_text(text)
    
    # 1. التحقق من الردود المباشرة (نعم، لا) بناءً على حالة الزبون
    if q_norm in ["نعم", "اي", "حجز"]:
        if "last_product" in user_state:
            item = user_state["last_product"]
            database.clear_user_state(phone) # تفريغ الذاكرة بعد الحجز
            return f"🌿 صيدلية بدر البشرية\n\nتم تسجيل طلب الحجز للمنتج: {item.get('name')}\nسيتم التواصل معك للتأكيد."
            
    if q_norm in ["لا", "الغاء"]:
        database.clear_user_state(phone)
        return "🌿 صيدلية بدر البشرية\n\nتم الإلغاء. يمكنك البحث عن منتج آخر."

    # 2. البحث عن المنتج
    item = exact_safe_product_match(text)
    if item:
        # حفظ المنتج في قاعدة البيانات كحالة للزبون
        database.update_user_state(phone, {"last_product": item})
        return build_product_reply(item)
        
    # 3. إذا لم يوجد المنتج، نجلب البدائل
    return build_unavailable_reply(text)
