import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import database
import product_intelligence as intel
import matcher_v2
import matcher_v3
import matcher_v4

try:
    from rapidfuzz import fuzz
except Exception:  # Safe fallback if requirements were not installed yet.
    from _fuzzy_compat import fuzz


PHARMACY_HEADER = os.getenv("PHARMACY_HEADER") or f"🌿 {os.getenv('PHARMACY_NAME', 'صيدلية بدر البشرية')}"

GREETINGS = [
    "السلام عليكم",
    "السلام عليكم ورحمة الله",
    "مرحبا",
    "مرحبتين",
    "هلا",
    "hi",
    "hello",
    "السلام",
]

YES_WORDS = ["نعم", "اي", "إي", "حجز", "yes", "تمام", "أكيد", "اكد", "ok"]
NO_WORDS = ["لا", "الغاء", "إلغاء", "no", "cancel"]

STOPWORDS = [
    "متوفر عندكم",
    "موجود عندكم",
    "هل يوجد",
    "هل في",
    "لو سمحت",
    "من فضلك",
    "كم سعر",
    "شنو سعر",
    "قداش",
    "سعره",
    "سعر",
    "بكم",
    "بكام",
    "متوفر",
    "موجود",
    "عندكم",
    "عنديكم",
    "عندكمش",
    "عندك",
    "هل",
    "نبي",
    "نبو",
    "اريد",
    "أريد",
    "ابي",
    "أبي",
    "بالله",
    "يوجد",
    "فيه",
    "في",
    "لو",
    "سمحت",
    "please",
    "price",
    "available",
    "do you have",
    "have",
]

SYNONYMS = {
    "cera ve": "cerave",
    "cera-ve": "cerave",
    "ceravé": "cerave",
    "سيرافي": "cerave",
    "سيرا في": "cerave",
    "moisturising": "moisturizing",
    "moisturiser": "moisturizer",
    "la roche posay": "laroche",
    "la roche": "laroche",
    "لاروش بوزيه": "laroche",
    "لاروش": "laroche",
    "لاروشي": "laroche",
    "ايفاكلار": "effaclar",
    "إيفاكلار": "effaclar",
    "the ordinary": "theordinary",
    "ذا اورديناري": "theordinary",
    "اورديناري": "theordinary",
    "اوريدناري": "theordinary",
    "واقي شمس": "sunscreen",
    "كريم شمس": "sunscreen",
    "حمايه شمس": "sunscreen",
    "حماية شمس": "sunscreen",
    "سن بلوك": "sunscreen",
    "sun block": "sunscreen",
    "sunblock": "sunscreen",
    "غسول وجه": "face cleanser",
    "غسول بشرة": "face cleanser",
    "غسول للبشرة": "face cleanser",
    "غسول البشره": "face cleanser",
    "غسول": "cleanser",
    "منظف": "cleanser",
    "مرطب": "moisturizer",
    "ترطيب": "moisturizer",
    "كريم": "cream",
    "لوشن": "lotion",
    "سيروم": "serum",
    "شامبو": "shampoo",
    "بشرة دهنية": "oily skin",
    "البشرة الدهنية": "oily skin",
    "بشره دهنيه": "oily skin",

    "بيوديرما": "bioderma",
    "بايوديرما": "bioderma",
    "بيودرما": "bioderma",
    "بايودرما": "bioderma",
    "bioderma photoderm": "bioderma photoderm",
    "فوتوديرم": "photoderm",
    "اكوا فلويد": "aquafluide",
    "اكو فلويد": "aquafluide",
    "ناقش شمس": "sunscreen",
    "ناقص شمس": "sunscreen",
    "نقص شمس": "sunscreen",
    "بانادول": "panadol",
    "crea ve": "cerave",
    "creave": "cerave",
    "cearave": "cerave",
    "cearve": "cerave",
    "cerave": "cerave",
    "cera v": "cerave",
    "كونجيستال": "congestal",
    "كونجستال": "congestal",
    "كونجستال": "congestal",
    "لاروش سيكا": "cicaplast",
    "لاروش سيكابلاست": "cicaplast",
    "لاروش سيكابلاست ب5": "cicaplast b5",
    "la roche cica": "cicaplast",
    "laroche cica": "cicaplast",
    "cica plast": "cicaplast",
    "سيكا بلاست": "cicaplast",
    "سيكابلاست": "cicaplast",
    "سيكا": "cica",
    "بنادول": "panadol",
    "بندول": "panadol",
    "ادول": "adol",
    "أدول": "adol",
    "ادول شراب": "adol syrup",
    "براسيتامول": "paracetamol",
    "باراسيتامول": "paracetamol",
    "اموكلان": "amoclan",
    "اوموكلان": "amoclan",
    "اوجمنتين": "augmentin",
    "اوقمنتين": "augmentin",
    "زيرتك": "zyrtec",
    "تلفاست": "telfast",
    "كلاريتين": "claritine",
    "كلارتين": "claritine",
    "فولتارين": "voltaren",
    "كتافلام": "cataflam",
    "بروفين": "brufen",
    "فلاجيل": "flagyl",
    "اوميبرازول": "omeprazole",
    "كونكور": "concor",
    "جلوكوفاج": "glucophage",
}

SYNONYMS.update(intel.EXTRA_SYNONYMS)

COSMETIC_BRANDS = [
    "cerave",
    "laroche",
    "cetaphil",
    "vichy",
    "eucerin",
    "bioderma",
    "acm",
    "svr",
    "uriage",
    "avene",
    "theordinary",
    "ordinary",
    "isispharma",
    "isis",
    "arvea",
    "anivagen",
    "mustela",
    "nuxe",
    "babaria",
    "dr.rashel",
    "dr rashel",
]
COSMETIC_BRANDS = list(dict.fromkeys(COSMETIC_BRANDS + intel.EXTRA_COSMETIC_BRANDS))

MEDICINE_BRANDS = [
    "panadol",
    "adol",
    "amoclan",
    "augmentin",
    "zyrtec",
    "telfast",
    "claritine",
    "voltaren",
    "cataflam",
    "brufen",
    "flagyl",
    "omeprazole",
    "concor",
    "glucophage",
]

BRANDS = COSMETIC_BRANDS + MEDICINE_BRANDS

TYPE_WORDS = {
    "cleanser": ["face cleanser", "cleanser", "face wash", "wash", "foaming", "gel moussant", "moussant", "غسول", "منظف"],
    "sunscreen": ["sunscreen", "spf", "sunblock", "sun block", "واقي شمس", "واقي", "حماية"],
    "serum": ["serum", "سيروم"],
    "shampoo": ["shampoo", "شامبو"],
    "lotion": ["lotion", "لوشن"],
    "moisturizer": ["moisturizer", "moisturizing", "moisturising", "hydrating", "hydratant", "مرطب", "ترطيب"],
    "cream": ["cream", "baume", "كريم", "بلسم"],
    "syrup": ["syrup", "susp", "suspension", "susp.", "معلق", "شراب"],
    "tablet": ["tablet", "tab", "caplet", "capsule", "قرص", "اقراص", "كبسول", "حبوب"],
    "drops": ["drops", "drop", "قطرة", "قطره"],
    "spray": ["spray", "بخاخ"],
}

for _kind, _words in intel.EXTRA_TYPE_WORDS.items():
    TYPE_WORDS.setdefault(_kind, []).extend(_words)

TYPE_ORDER = ["cleanser", "sunscreen", "serum", "shampoo", "lotion", "moisturizer", "cream", "syrup", "tablet", "drops", "spray"]

AREA_WORDS = {
    "mouth": ["mouth", "oral", "dental", "teeth", "فم", "اسنان", "أسنان", "غسول فم"],
    "baby": ["baby", "enfant", "pediatril", "بيبي", "اطفال", "أطفال", "رضع", "kids", "طفل"],
    "hair": ["hair", "cheveux", "شعر", "scalp", "فروة"],
    "body": ["body", "corps", "جسم", "بدن"],
    "face": ["face", "visage", "وجه", "وجة", "بشرة", "بشره", "skin", "acne", "حبوب", "دهنية", "دهنيه", "oily", "normal skin"],
}
for _area, _words in intel.EXTRA_AREA_WORDS.items():
    AREA_WORDS.setdefault(_area, []).extend(_words)

UNAVAILABLE_TERMS = ["غير متوفر", "غير موجود", "نافذ", "نفذ", "ناقص", "لا", "0", "no", "out of stock", "unavailable"]
TOKEN_STOP = {"and", "or", "the", "for", "with", "normal", "to", "ل", "لل", "مع", "من", "على"}
SHARED_TERMS = ["acne", "oily", "dry", "sensitive", "sa", "foaming", "hydrating", "moisturizing", "effaclar", "دهنية", "دهنيه", "جافة", "حساسة"]
GENERIC_TERMS = {
    "cleanser",
    "wash",
    "face wash",
    "face cleanser",
    "غسول",
    "غسول وجه",
    "مرطب",
    "moisturizer",
    "lotion",
    "cream",
    "serum",
    "shampoo",
    "sunscreen",
    "واقي",
    "واقي شمس",
    "كريم",
    "لوشن",
    "سيروم",
    "شامبو",
    "face",
    "skin",
    "بشره",
    "بشرة",
    "وجه",
}
MOISTURIZER_TYPES = {"lotion", "moisturizer", "cream"}


def normalize_text_no_syn(text: str) -> str:
    value = str(text or "").strip().lower()
    arabic_map = {
        "أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي",
        "ؤ": "و", "ئ": "ي", "ٱ": "ا",
        # Wider Arabic/Persian/Gulf/Libyan character normalization.
        "ڤ": "ف", "ک": "ك", "ی": "ي", "گ": "ك", "چ": "ج", "پ": "ب",
    }
    for src, dst in arabic_map.items():
        value = value.replace(src, dst)
    value = value.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    value = value.replace("ـ", "")
    value = re.sub(r"[\u064b-\u065f]", "", value)
    value = re.sub(r"(.)\1{2,}", r"\1\1", value)
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()

def _contains_norm_phrase(text_norm: str, phrase_norm: str) -> bool:
    if not text_norm or not phrase_norm:
        return False
    return f" {phrase_norm} " in f" {text_norm} "


def _replace_norm_phrase(text_norm: str, phrase_norm: str, replacement_norm: str) -> str:
    if not phrase_norm or phrase_norm not in text_norm:
        return text_norm
    return re.sub(rf"(?<!\w){re.escape(phrase_norm)}(?!\w)", replacement_norm, text_norm)


def _build_synonym_rules():
    static = dict(SYNONYMS)
    try:
        dynamic = database.load_dynamic_synonyms_clean()
    except Exception as exc:
        print(f"DYNAMIC_SYNONYMS_LOAD_WARNING: {exc}")
        dynamic = {}
    combined = {**static, **dynamic}
    return sorted(
        [(normalize_text_no_syn(src), normalize_text_no_syn(dst)) for src, dst in combined.items() if str(src or "").strip() and str(dst or "").strip()],
        key=lambda pair: len(pair[0]),
        reverse=True,
    )


SYNONYM_RULES = _build_synonym_rules()


def refresh_synonym_rules() -> None:
    """Reload dynamic synonyms without restarting the bot."""
    global SYNONYM_RULES
    SYNONYM_RULES = _build_synonym_rules()
    try:
        matcher_v2.refresh_synonym_rules()
    except Exception as exc:
        print(f"MATCHER_V2_SYNONYM_REFRESH_WARNING: {exc}")
    try:
        matcher_v3.refresh_synonym_rules()
    except Exception as exc:
        print(f"MATCHER_V3_SYNONYM_REFRESH_WARNING: {exc}")
    try:
        matcher_v4.refresh_synonym_rules()
    except Exception as exc:
        print(f"MATCHER_V4_SYNONYM_REFRESH_WARNING: {exc}")
    invalidate_product_cache()


def _fuzzy_token_score(q_token: str, p_token: str) -> float:
    if q_token == p_token:
        return 1.0
    if len(q_token) < 3 or len(p_token) < 3:
        return 0.0
    ratio = fuzz.ratio(q_token, p_token) / 100
    partial = fuzz.partial_ratio(q_token, p_token) / 100
    return max(ratio, partial * 0.85)


def _apply_fuzzy_single_token_synonyms(value: str) -> str:
    # Handles small spelling mistakes in common synonyms, e.g. بنادووول -> بنادول -> panadol.
    # Kept conservative: only single-token synonyms, similar length, high score.
    out = []
    for token in str(value or "").split():
        replacement = token
        if len(token) >= 4:
            best_score = 0.0
            best_target = ""
            for src_norm, dst_norm in SYNONYM_RULES:
                if " " in src_norm or not src_norm or abs(len(token) - len(src_norm)) > 2:
                    continue
                score = max(fuzz.ratio(token, src_norm) / 100.0, (fuzz.partial_ratio(token, src_norm) / 100.0) * 0.85)
                if score > best_score:
                    best_score = score
                    best_target = dst_norm
            if best_score >= 0.88 and best_target:
                replacement = best_target
        out.append(replacement)
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def normalize_text(text: str, apply_fuzzy_synonyms: bool = False) -> str:
    value = normalize_text_no_syn(text)
    for src_norm, dst_norm in SYNONYM_RULES:
        value = _replace_norm_phrase(value, src_norm, dst_norm)
    if apply_fuzzy_synonyms:
        value = _apply_fuzzy_single_token_synonyms(value)
    return re.sub(r"\s+", " ", value).strip()


STOPWORDS_NORM = sorted({normalize_text(word) for word in STOPWORDS if normalize_text(word)}, key=len, reverse=True)
GREETINGS_NORM = {normalize_text(word) for word in GREETINGS}
YES_WORDS_NORM = {normalize_text(word) for word in YES_WORDS}
NO_WORDS_NORM = {normalize_text(word) for word in NO_WORDS}
COSMETIC_BRANDS_NORM = {normalize_text(word) for word in COSMETIC_BRANDS}
MEDICINE_BRANDS_NORM = {normalize_text(word) for word in MEDICINE_BRANDS}
BRANDS_NORM = sorted({normalize_text(word) for word in BRANDS}, key=len, reverse=True)
TYPE_WORDS_NORM = {kind: sorted({normalize_text(word) for word in words}, key=len, reverse=True) for kind, words in TYPE_WORDS.items()}
AREA_WORDS_NORM = {area: sorted({normalize_text(word) for word in words}, key=len, reverse=True) for area, words in AREA_WORDS.items()}
UNAVAILABLE_TERMS_NORM = {normalize_text(word) for word in UNAVAILABLE_TERMS}
SHARED_TERMS_NORM = {normalize_text(word) for word in SHARED_TERMS}
GENERIC_TERMS_NORM = {normalize_text(word) for word in GENERIC_TERMS}
GENERIC_ALIAS_TERMS_NORM = GENERIC_TERMS_NORM | COSMETIC_BRANDS_NORM
ALL_GENERIC_TOKEN_TERMS_NORM = GENERIC_TERMS_NORM | COSMETIC_BRANDS_NORM | MEDICINE_BRANDS_NORM
for _words in TYPE_WORDS_NORM.values():
    ALL_GENERIC_TOKEN_TERMS_NORM.update(_words)
for _words in AREA_WORDS_NORM.values():
    ALL_GENERIC_TOKEN_TERMS_NORM.update(_words)
BLOCKED_FACE_ALT_TERMS_NORM = set(AREA_WORDS_NORM["body"] + AREA_WORDS_NORM["baby"] + AREA_WORDS_NORM["hair"] + AREA_WORDS_NORM["mouth"])
BLOCKED_FACE_ALT_TERMS_NORM.update({normalize_text(word) for word in ["mouth wash", "body wash", "baby wash", "oral", "dental", "shampoo", "شامبو"]})


def clean_query(text: str) -> str:
    value = normalize_text(text, apply_fuzzy_synonyms=True)
    for phrase_norm in STOPWORDS_NORM:
        value = _replace_norm_phrase(value, phrase_norm, " ")
    return re.sub(r"\s+", " ", value).strip()


def tokens_norm(text_norm: str) -> List[str]:
    return [token for token in str(text_norm or "").split() if len(token) > 1 and token not in TOKEN_STOP]


def tokens(text: str) -> List[str]:
    return tokens_norm(normalize_text(text))


def get_aliases(alias_str: str) -> List[str]:
    if not alias_str:
        return []
    raw = re.split(r"[,،|;\n/]+", str(alias_str))
    return [normalize_text(alias) for alias in raw if alias and str(alias).strip()]


def _contains_phrase(text: str, phrase: str) -> bool:
    return _contains_norm_phrase(normalize_text(text), normalize_text(phrase))


def extract_features_norm(norm: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    brand = None
    for brand_norm in BRANDS_NORM:
        if _contains_norm_phrase(norm, brand_norm):
            brand = brand_norm
            break

    product_type = None
    for kind in TYPE_ORDER:
        for word_norm in TYPE_WORDS_NORM.get(kind, []):
            if _contains_norm_phrase(norm, word_norm):
                product_type = kind
                break
        if product_type:
            break

    area = None
    for area_name in ["mouth", "baby", "hair", "body", "face"]:
        for word_norm in AREA_WORDS_NORM.get(area_name, []):
            if _contains_norm_phrase(norm, word_norm):
                area = area_name
                break
        if area:
            break
    return brand, product_type, area


def extract_features(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    return extract_features_norm(normalize_text(text))


def distinctive_tokens_norm(q_clean: str) -> List[str]:
    return [token for token in tokens_norm(q_clean) if token not in ALL_GENERIC_TOKEN_TERMS_NORM]


def distinctive_tokens(q_clean: str) -> List[str]:
    return distinctive_tokens_norm(clean_query(q_clean))


def is_available(status_str: str) -> bool:
    """Strict stock check.

    Empty/unknown availability is NOT treated as available. This prevents the
    bot from accepting reservations or saying "متوفر" when the uploaded
    catalog did not explicitly provide availability.
    """
    status_norm = normalize_text(status_str)
    if not status_norm:
        return False
    unknown_terms = {normalize_text(x) for x in ["unknown", "غير معروف", "غير محدد", "uncertain", "n/a", "na", "-"]}
    if status_norm in unknown_terms:
        return False
    return not any(term == status_norm or term in status_norm for term in UNAVAILABLE_TERMS_NORM)


def is_unknown_availability(status_str: str) -> bool:
    status_norm = normalize_text(status_str)
    if not status_norm:
        return True
    unknown_terms = {normalize_text(x) for x in ["unknown", "غير معروف", "غير محدد", "uncertain", "n/a", "na", "-"]}
    return status_norm in unknown_terms


def _field(item: dict, name: str) -> str:
    value = item.get(name, "")
    return "" if value is None else str(value)


def get_product_identity(item: dict) -> str:
    parts = [
        _field(item, "name"),
        _field(item, "brand"),
        _field(item, "company"),
        _field(item, "form"),
        _field(item, "category"),
        _field(item, "category_guess"),
        _field(item, "active_ingredient"),
        _field(item, "strength"),
        _field(item, "pack"),
        _field(item, "code"),
        _field(item, "barcode"),
        _field(item, "sku"),
        _field(item, "item_code"),
        _field(item, "product_code"),
        _field(item, "source_serial"),
        _field(item, "normalized_name"),
        _field(item, "original_name"),
        _field(item, "aliases"),
        _field(item, "image_ocr_keywords"),
        _field(item, "ocr_keywords"),
        _field(item, "keywords"),
    ]
    return normalize_text(" ".join(part for part in parts if part))


def is_cosmetic_context(text: str, product_type: Optional[str] = None) -> bool:
    norm = normalize_text(text)
    brand, detected_type, area = extract_features_norm(norm)
    candidate_type = product_type or detected_type
    if brand in COSMETIC_BRANDS_NORM:
        return True
    if area in {"face", "body", "hair"} and candidate_type in {"cleanser", "moisturizer", "lotion", "cream", "serum", "sunscreen", "shampoo"}:
        return True
    if candidate_type in {"cleanser", "sunscreen", "serum", "lotion", "moisturizer"}:
        return any(word in norm for word in ["face", "skin", "بشره", "بشرة", "وجه", "acne", "oily", "dry"])
    return False


def is_cosmetic(product_type: Optional[str], context: str = "") -> bool:
    return is_cosmetic_context(context, product_type)


def _is_generic_alias_norm(alias_norm: str) -> bool:
    return not alias_norm or alias_norm in GENERIC_ALIAS_TERMS_NORM or (len(alias_norm.split()) == 1 and alias_norm in GENERIC_ALIAS_TERMS_NORM)


def _brand_required_ok(q_brand: Optional[str], identity_norm: str) -> bool:
    if not q_brand:
        return True
    return _contains_norm_phrase(identity_norm, q_brand)


def _compatible_types(q_type: Optional[str], p_type: Optional[str]) -> bool:
    if not q_type or not p_type or q_type == p_type:
        return True
    return q_type in MOISTURIZER_TYPES and p_type in MOISTURIZER_TYPES


def _conflicts(q_type: Optional[str], q_area: Optional[str], entry: "ProductEntry", q_brand: Optional[str] = None) -> bool:
    if q_type and entry.product_type and not _compatible_types(q_type, entry.product_type):
        return True
    if q_area and entry.area and q_area != entry.area:
        return True
    if q_type == "cleanser" and not q_area and q_brand in COSMETIC_BRANDS_NORM and entry.area in {"body", "baby", "hair", "mouth"}:
        return True
    return False


@dataclass
class ProductEntry:
    item: dict
    identity: str
    name_norm: str
    aliases: Set[str]
    brand: Optional[str]
    product_type: Optional[str]
    area: Optional[str]
    tokens: Set[str]


@dataclass
class ProductIndex:
    entries: List[ProductEntry]
    normalized_name_map: Dict[str, ProductEntry]
    alias_map: Dict[str, List[ProductEntry]]
    brand_index: Dict[str, List[ProductEntry]]
    type_index: Dict[str, List[ProductEntry]]
    area_index: Dict[str, List[ProductEntry]]
    compact_map: Dict[str, List[ProductEntry]]


_PRODUCT_INDEX: Optional[ProductIndex] = None
_V3_CATALOG_INDEX = None
_V3_PRODUCTS_COUNT = 0
MATCHER_ENGINE_VERSION = getattr(matcher_v4, "VERSION", "matcher_v4")


def invalidate_product_cache() -> None:
    """Clear all product/catalog indexes after product or synonym changes.

    Important: do not call refresh_synonym_rules() from here. That function may
    call invalidate_product_cache() again, and more importantly it does not
    guarantee that matcher_v4's catalog index is rebuilt after product updates.
    The production V4 decision path is backed by matcher_v3.get_catalog_index(),
    so that LRU cache must be cleared explicitly.
    """
    global _PRODUCT_INDEX, _V3_CATALOG_INDEX, _V3_PRODUCTS_COUNT
    _PRODUCT_INDEX = None
    _V3_CATALOG_INDEX = None
    _V3_PRODUCTS_COUNT = 0
    try:
        matcher_v2.invalidate_cache()
    except Exception:
        pass
    try:
        matcher_v3.get_catalog_index.cache_clear()
    except Exception:
        pass
    try:
        matcher_v4.invalidate_cache()
    except Exception:
        pass


def _entry_aliases(item: dict) -> Set[str]:
    aliases: Set[str] = set()
    for field_name in [
        "aliases",
        "image_ocr_keywords",
        "ocr_keywords",
        "keywords",
        "code",
        "barcode",
        "sku",
        "item_code",
        "product_code",
        "source_serial",
        "original_name",
    ]:
        aliases.update(get_aliases(item.get(field_name, "")))

    # Automatic aliases from weak Excel rows. This helps rows like
    # "Normaderm Vichy" match an image query such as
    # "Vichy Normaderm Daily Deep Cleansing Gel" without requiring the owner
    # to manually fill every OCR keyword first.
    name_norm = normalize_text(item.get("name", ""))
    original_norm = normalize_text(item.get("original_name", ""))
    normalized_name_norm = normalize_text(item.get("normalized_name", ""))
    brand_norm = normalize_text(item.get("brand", "") or item.get("company", ""))
    company_norm = normalize_text(item.get("company", ""))
    for value in [name_norm, original_norm, normalized_name_norm]:
        if value:
            aliases.add(value)
            parts = value.split()
            if 2 <= len(parts) <= 5:
                aliases.add(" ".join(reversed(parts)))
    for brand_value in {brand_norm, company_norm}:
        if brand_value and name_norm:
            aliases.add(f"{brand_value} {name_norm}")
            aliases.add(f"{name_norm} {brand_value}")
    return aliases


def _compact_key(norm_text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(norm_text or ""))


def _add_compact(compact_map: Dict[str, List["ProductEntry"]], key_norm: str, entry: "ProductEntry") -> None:
    key = _compact_key(key_norm)
    if not key or len(key) < 3 or not any(ch.isdigit() for ch in key):
        return
    compact_map.setdefault(key, []).append(entry)


def _build_product_index(products: List[dict]) -> ProductIndex:
    entries: List[ProductEntry] = []
    normalized_name_map: Dict[str, ProductEntry] = {}
    alias_map: Dict[str, List[ProductEntry]] = {}
    brand_index: Dict[str, List[ProductEntry]] = {}
    type_index: Dict[str, List[ProductEntry]] = {}
    area_index: Dict[str, List[ProductEntry]] = {}
    compact_map: Dict[str, List[ProductEntry]] = {}

    for item in products:
        name_norm = normalize_text(item.get("normalized_name") or item.get("name", ""))
        # Existing normalized_name may be old/basic; always include the current normalized product name.
        current_name_norm = normalize_text(item.get("name", ""))
        identity = get_product_identity(item)
        brand, product_type, area = extract_features_norm(identity)
        aliases = _entry_aliases(item)
        raw_identity = normalize_text_no_syn(" ".join(str(item.get(field, "") or "") for field in [
            "name", "brand", "company", "form", "category", "category_guess", "active_ingredient",
            "strength", "pack", "code", "barcode", "sku", "item_code", "product_code",
            "source_serial", "normalized_name", "original_name", "aliases", "image_ocr_keywords",
            "ocr_keywords", "keywords",
        ]))
        token_set = set(tokens_norm(identity)) | set(tokens_norm(raw_identity))
        entry = ProductEntry(
            item=item,
            identity=identity,
            name_norm=current_name_norm,
            aliases=aliases,
            brand=brand,
            product_type=product_type,
            area=area,
            tokens=token_set,
        )
        entries.append(entry)
        for key in {name_norm, current_name_norm}:
            if key and key not in normalized_name_map:
                normalized_name_map[key] = entry
            _add_compact(compact_map, key, entry)
        for alias in aliases:
            if alias and not _is_generic_alias_norm(alias):
                alias_map.setdefault(alias, []).append(entry)
                _add_compact(compact_map, alias, entry)
        _add_compact(compact_map, identity, entry)
        if brand:
            brand_index.setdefault(brand, []).append(entry)
        if product_type:
            type_index.setdefault(product_type, []).append(entry)
        if area:
            area_index.setdefault(area, []).append(entry)

    return ProductIndex(entries, normalized_name_map, alias_map, brand_index, type_index, area_index, compact_map)


def get_product_index() -> ProductIndex:
    global _PRODUCT_INDEX
    if _PRODUCT_INDEX is None:
        _PRODUCT_INDEX = _build_product_index(database.load_products())
    return _PRODUCT_INDEX


def _unique_entries(entries: List[ProductEntry]) -> List[ProductEntry]:
    seen = set()
    unique = []
    for entry in entries:
        key = str(entry.item.get("id") or id(entry.item))
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique


def _candidate_entries(index: ProductIndex, q_brand: Optional[str], q_type: Optional[str], q_area: Optional[str]) -> List[ProductEntry]:
    if q_brand and q_brand in index.brand_index:
        candidates = list(index.brand_index[q_brand])
    elif q_type and q_type in index.type_index:
        candidates = list(index.type_index[q_type])
    elif q_area and q_area in index.area_index:
        candidates = list(index.area_index[q_area])
    else:
        candidates = list(index.entries)

    filtered = []
    for entry in _unique_entries(candidates):
        if not _brand_required_ok(q_brand, entry.identity):
            continue
        if _conflicts(q_type, q_area, entry, q_brand):
            continue
        filtered.append(entry)
    return filtered


def _is_obvious_noise(q_clean: str, q_brand: Optional[str], q_type: Optional[str]) -> bool:
    if q_brand or q_type:
        return False
    return bool(re.fullmatch(r"[a-z]*\d+[a-z\d]*", q_clean or ""))


def _score_entry(q_clean: str, q_tokens: List[str], distinct: List[str], entry: ProductEntry) -> float:
    if not q_tokens or not entry.tokens:
        return 0.0

    entry_tokens = list(entry.tokens)
    hits = 0.0
    for token in q_tokens:
        if token in entry.tokens:
            hits += 1.0
        else:
            best_fuzzy = max(
                (_fuzzy_token_score(token, pt) for pt in entry_tokens if abs(len(token) - len(pt)) <= 3),
                default=0.0,
            )
            if best_fuzzy >= 0.82:
                hits += best_fuzzy * 0.9
            elif len(token) >= 3 and any(token in pt or pt in token for pt in entry_tokens if len(pt) >= 3):
                hits += 0.8

    coverage = hits / max(len(q_tokens), 1)

    if distinct:
        distinct_hits = 0.0
        for token in distinct:
            if token in entry.tokens:
                distinct_hits += 1.0
            else:
                best = max(
                    (_fuzzy_token_score(token, pt) for pt in entry_tokens if abs(len(token) - len(pt)) <= 3),
                    default=0.0,
                )
                if best >= 0.82:
                    distinct_hits += best * 0.9
        distinct_score = distinct_hits / len(distinct)
    else:
        distinct_score = 0.0

    seq = difflib.SequenceMatcher(None, q_clean, entry.identity).ratio()
    phrase_bonus = 0.16 if q_clean and (q_clean in entry.identity or entry.identity in q_clean) else 0.0
    purpose_bonus = min(0.22, intel.same_purpose_score(q_clean, entry.identity) / 180.0)
    return coverage * 0.52 + distinct_score * 0.28 + seq * 0.20 + phrase_bonus + purpose_bonus

def _meaningful_entry_tokens(entry: ProductEntry) -> Set[str]:
    blocked = set(ALL_GENERIC_TOKEN_TERMS_NORM) | set(TOKEN_STOP)
    values = {tok for tok in entry.tokens if tok and tok not in blocked and len(tok) >= 3}
    return values


def _short_identity_subset_hits(q_clean: str, candidates: List[ProductEntry]) -> List[ProductEntry]:
    """Match short weak rows whose important tokens are fully visible in a longer query.

    Example: DB row "Normaderm Vichy" should match image text
    "Vichy Normaderm Daily Deep Cleansing Gel". We require at least two
    meaningful tokens so brand-only rows do not hijack searches.
    """
    q_token_set = set(tokens_norm(q_clean))
    hits: List[ProductEntry] = []
    for entry in candidates:
        important = _meaningful_entry_tokens(entry)
        if len(important) >= 2 and important.issubset(q_token_set):
            hits.append(entry)
    return _unique_entries(hits)


def _exact_lookup(index: ProductIndex, q_clean: str, q_brand: Optional[str]) -> Optional[ProductEntry]:
    exact_name = index.normalized_name_map.get(q_clean)
    if exact_name:
        return exact_name

    exact_aliases = index.alias_map.get(q_clean, [])
    for entry in exact_aliases:
        if _brand_required_ok(q_brand, entry.identity):
            return entry

    compact = _compact_key(q_clean)
    if compact:
        compact_entries = index.compact_map.get(compact, [])
        if not compact_entries and compact.isdigit() and len(compact) >= 3:
            # Handles product names like "1,2,3 Extra" when customer writes "123".
            compact_entries = []
            for key, entries in index.compact_map.items():
                if key.startswith(compact):
                    compact_entries.extend(entries)
        for entry in _unique_entries(compact_entries):
            if _brand_required_ok(q_brand, entry.identity):
                return entry
    return None


def safe_match(query: str) -> Tuple[str, Optional[dict]]:
    """Deprecated legacy matcher entrypoint.

    This function used to run V4 and then fall back to legacy fuzzy scoring.
    That mixed decision path is unsafe for production because it can bypass the
    strict V4 resolver and return unexpected products. Use
    resolve_product_query_decision() or handle_text_query_result() instead.
    """
    raise NotImplementedError("safe_match is deprecated. Use resolve_product_query_decision().")


def _allowed_alternative_types(target_type: Optional[str]) -> Set[str]:
    if target_type == "cleanser":
        return {"cleanser"}
    if target_type == "serum":
        return {"serum"}
    if target_type == "sunscreen":
        return {"sunscreen"}
    if target_type == "shampoo":
        return {"shampoo"}
    if target_type in {"lotion", "moisturizer", "cream"}:
        return {"lotion", "moisturizer", "cream"}
    return {target_type} if target_type else set()


def _entry_for_item(item: Optional[dict]) -> Optional[ProductEntry]:
    if not item:
        return None
    item_id = str(item.get("id", ""))
    index = get_product_index()
    for entry in index.entries:
        if item_id and str(entry.item.get("id", "")) == item_id:
            return entry
        if not item_id and entry.item is item:
            return entry
    return None


def get_cosmetic_alternatives(target_product: Optional[dict], query_clean: str, limit: int = 3, explicit_area: str = None) -> List[dict]:
    query_clean = clean_query(query_clean)
    target_entry = _entry_for_item(target_product)
    target_id = target_entry.identity if target_entry else query_clean
    target_brand, target_type, target_area = extract_features_norm(target_id)

    if explicit_area and normalize_text(explicit_area) not in {"unknown", "none", ""}:
        target_area = normalize_text(explicit_area)
    if not target_type:
        _, target_type, _ = extract_features_norm(query_clean)
    if not is_cosmetic_context(f"{target_id} {query_clean}", target_type):
        return []

    if target_type == "cleanser" and not target_area:
        non_face_words = AREA_WORDS_NORM["body"] + AREA_WORDS_NORM["hair"] + AREA_WORDS_NORM["baby"] + AREA_WORDS_NORM["mouth"]
        if not any(_contains_norm_phrase(query_clean, word) for word in non_face_words):
            target_area = "face"

    allowed_types = _allowed_alternative_types(target_type)
    if not allowed_types:
        return []

    index = get_product_index()
    candidate_entries = []
    for allowed_type in allowed_types:
        candidate_entries.extend(index.type_index.get(allowed_type, []))

    # If uploaded Excel lacks a clean form/type column, fall back to brand/area/all index entries.
    # This keeps alternatives working for products whose type is only visible in name/alias/OCR keywords.
    if not candidate_entries:
        if target_brand and target_brand in index.brand_index:
            candidate_entries.extend(index.brand_index.get(target_brand, []))
        elif target_area and target_area in index.area_index:
            candidate_entries.extend(index.area_index.get(target_area, []))
        else:
            candidate_entries.extend(index.entries)

    scored = []
    q_tokens = tokens_norm(query_clean or target_id)
    distinct = distinctive_tokens_norm(query_clean or target_id)
    target_id_to_skip = str(target_product.get("id", "")) if target_product else ""

    same_brand_available = bool(
        target_brand and any(
            entry.brand == target_brand
            and matcher_item_available(entry.item)
            and (not target_area or not entry.area or entry.area == target_area)
            for entry in _unique_entries(candidate_entries)
        )
    )

    for entry in _unique_entries(candidate_entries):
        if not matcher_item_available(entry.item):
            continue
        if target_id_to_skip and str(entry.item.get("id", "")) == target_id_to_skip:
            continue
        # Keep type/area strict when detected, but do not punish old Excel rows with missing form/type.
        if target_type and entry.product_type and entry.product_type not in allowed_types:
            continue
        if target_area == "face" and any(term and term in entry.identity for term in BLOCKED_FACE_ALT_TERMS_NORM):
            continue
        if target_area and entry.area and target_area != entry.area:
            continue

        score = 0.0
        if target_brand and entry.brand == target_brand:
            score += 25
        elif same_brand_available and target_brand and entry.brand and entry.brand != target_brand:
            score -= 8
        if target_type and entry.product_type == target_type:
            score += 22
        if target_area and entry.area == target_area:
            score += 12
        if target_product:
            name_sim = fuzz.token_set_ratio(
                normalize_text(target_product.get("name", "")),
                entry.name_norm,
            ) / 100
            score += name_sim * 20
        score += _score_entry(query_clean or target_id, q_tokens, distinct, entry) * 32
        scored.append((score, entry.item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]


def matcher_item_available(item: dict) -> bool:
    return is_available(item.get("available", ""))



VARIANT_TYPE_LABELS = {
    "syrup": "شراب / معلق",
    "tablet": "أقراص / كبسولات",
    "drops": "قطرة",
    "spray": "بخاخ",
    "cream": "كريم",
    "lotion": "لوشن",
    "serum": "سيروم",
    "cleanser": "غسول",
    "sunscreen": "واقي شمس",
    "shampoo": "شامبو",
}

STRENGTH_RE = re.compile(r"(?<!\w)(\d+(?:[\.,]\d+)?)(?:\s*(mg|mcg|g|ml|iu|unit|units|%|مجم|ملجم|مل|جم|وحدة))?", re.I)


def _strength_number(value: str) -> str:
    value = str(value or "").replace(",", ".").strip()
    if not value:
        return ""
    try:
        f = float(value)
        if f.is_integer():
            return str(int(f))
        return str(f).rstrip("0").rstrip(".")
    except Exception:
        return re.sub(r"\D+", "", value)


def extract_strength_values_norm(norm_text: str) -> Set[str]:
    values: Set[str] = set()
    for num, unit in STRENGTH_RE.findall(str(norm_text or "")):
        n = _strength_number(num)
        if n:
            values.add(n)
            if unit:
                values.add(f"{n}{normalize_text(unit)}")
    return values


def extract_strength_values(text: str) -> Set[str]:
    return extract_strength_values_norm(normalize_text(text))


def _entry_strength_values(entry: ProductEntry) -> Set[str]:
    explicit = normalize_text(_field(entry.item, "strength"))
    values = set()
    if explicit:
        values.update(extract_strength_values_norm(explicit))
    values.update(extract_strength_values_norm(entry.identity))
    return values


def _display_strength(entry: ProductEntry) -> str:
    explicit = str(entry.item.get("strength") or "").strip()
    if explicit:
        return explicit
    name = str(entry.item.get("name") or "")
    matches = STRENGTH_RE.findall(normalize_text(name) or entry.identity)
    if matches:
        num, unit = matches[0]
        n = _strength_number(num)
        u = normalize_text(unit)
        return f"{n}{u}" if u else n
    return ""


def _canonical_type_for_entry(entry: ProductEntry) -> str:
    if entry.product_type:
        return entry.product_type
    ident = entry.identity
    if any(word in ident for word in ["susp", "suspension", "syrup", "شراب", "معلق"]):
        return "syrup"
    if any(word in ident for word in ["tab", "tablet", "capsule", "cap", "اقراص", "كبسول", "حبوب"]):
        return "tablet"
    if any(word in ident for word in ["drop", "drops", "قطره", "قطرة"]):
        return "drops"
    if any(word in ident for word in ["spray", "بخاخ"]):
        return "spray"
    return ""


def _type_matches_query(entry: ProductEntry, q_type: Optional[str]) -> bool:
    if not q_type:
        return True
    et = _canonical_type_for_entry(entry)
    if not et:
        return True
    return _compatible_types(q_type, et)


def _variant_family_tokens(q_clean: str) -> List[str]:
    q_strengths = extract_strength_values_norm(q_clean)
    remove_tokens = set()
    for values in TYPE_WORDS_NORM.values():
        remove_tokens.update(values)
    for values in AREA_WORDS_NORM.values():
        remove_tokens.update(values)
    remove_tokens.update(GENERIC_TERMS_NORM)
    tokens_out = []
    for tok in tokens_norm(q_clean):
        if tok in remove_tokens:
            continue
        if tok in q_strengths or tok.isdigit():
            continue
        tokens_out.append(tok)
    return tokens_out


def _variant_candidates_for_query(q_clean: str, selected_entry: Optional[ProductEntry] = None) -> List[ProductEntry]:
    index = get_product_index()
    q_brand, q_type, q_area = extract_features_norm(q_clean)
    family_tokens = _variant_family_tokens(q_clean)

    if q_brand and q_brand in index.brand_index:
        base = list(index.brand_index[q_brand])
    elif selected_entry and selected_entry.brand and selected_entry.brand in index.brand_index:
        base = list(index.brand_index[selected_entry.brand])
    else:
        base = list(index.entries)

    out = []
    for entry in _unique_entries(base):
        if q_brand and not _brand_required_ok(q_brand, entry.identity):
            continue
        if q_area and entry.area and entry.area != q_area:
            continue
        if not _type_matches_query(entry, q_type):
            continue
        if family_tokens and not all((tok in entry.identity or any(tok in alias for alias in entry.aliases)) for tok in family_tokens):
            continue
        # If no useful family token, do not create a huge ambiguous group.
        if not family_tokens and not q_brand:
            continue
        out.append(entry)
    return out


def _variant_option_line(entry: ProductEntry, idx: int) -> str:
    # Clarification menus must not reveal price/availability before the exact
    # product variant is selected.
    name = str(entry.item.get("name", ""))
    strength = _display_strength(entry)
    type_label = VARIANT_TYPE_LABELS.get(_canonical_type_for_entry(entry), _canonical_type_for_entry(entry))
    size = str(entry.item.get("size", "") or entry.item.get("pack", "") or "").strip()
    bits = []
    if strength:
        bits.append(strength)
    if type_label:
        bits.append(type_label)
    if size:
        bits.append(size)
    details = f" ({' - '.join(bits)})" if bits else ""
    return f"{idx}) {name}{details}"


def _ask_variant_reply(phone: str, entries: List[ProductEntry], kind: str, q_clean: str) -> str:
    entries = _unique_entries(entries)[:12]
    _safe_update_state(phone, {
        "pending_variant_options": [e.item for e in entries],
        "pending_variant_kind": kind,
        "pending_variant_query": q_clean,
    })
    if kind == "form":
        title = "يوجد من هذا المنتج أكثر من شكل. اختر الشكل المطلوب أو اكتب رقمه:"
    elif kind == "strength":
        title = "يوجد من هذا المنتج أكثر من جرعة. اختر الجرعة المطلوبة أو اكتب رقمها:"
    else:
        title = "يوجد أكثر من صنف قريب. اختر المطلوب أو اكتب رقمه:"
    lines = [title, ""]
    for i, entry in enumerate(entries, 1):
        lines.append(_variant_option_line(entry, i))
    return with_header("\n".join(lines))



def _pending_family_tokens(entries: List[ProductEntry], user_state: dict) -> Set[str]:
    """Return product-family tokens for the currently displayed variant menu.

    This prevents an old variant menu from hijacking a new product search.
    Example: after asking about Amoclan, "Panadol" or "123" must start a new
    lookup, while "شراب", "457", or "اموكلان 457" should answer the Amoclan menu.
    """
    tokens: Set[str] = set(_variant_family_tokens(str(user_state.get("pending_variant_query") or "")))
    for entry in entries:
        if entry.brand:
            tokens.add(entry.brand)
        tokens.update(_variant_family_tokens(entry.name_norm))
        for alias in entry.aliases:
            tokens.update(_variant_family_tokens(alias))
    return {tok for tok in tokens if tok and tok not in ALL_GENERIC_TOKEN_TERMS_NORM}


def _exact_entry_in_entries(exact: Optional[ProductEntry], entries: List[ProductEntry]) -> bool:
    if not exact:
        return False
    exact_id = str(exact.item.get("id", ""))
    return any(exact_id and exact_id == str(entry.item.get("id", "")) for entry in entries)

def _select_pending_variant(phone: str, q_clean: str, user_state: dict) -> Optional["QueryResult"]:
    options = user_state.get("pending_variant_options") if user_state else None
    if not options:
        return None
    entries: List[ProductEntry] = []
    index = get_product_index()
    option_ids = {str(item.get("id", "")) for item in options if isinstance(item, dict)}
    for entry in index.entries:
        if str(entry.item.get("id", "")) in option_ids:
            entries.append(entry)
    if not entries:
        _safe_clear_state(phone)
        return None

    exact = _exact_lookup(index, q_clean, None)
    exact_is_pending = _exact_entry_in_entries(exact, entries)
    q_type = extract_features_norm(q_clean)[1]
    q_strengths = extract_strength_values_norm(q_clean)
    pending_family = _pending_family_tokens(entries, user_state)
    incoming_family = set(_variant_family_tokens(q_clean))
    family_overlap = bool(pending_family & incoming_family)

    def _pending_entries_matching_type(kind: Optional[str]) -> List[ProductEntry]:
        if not kind:
            return []
        hits: List[ProductEntry] = []
        for entry in entries:
            et = _canonical_type_for_entry(entry)
            if et and _compatible_types(kind, et):
                hits.append(entry)
        return hits

    type_hits = _pending_entries_matching_type(q_type)

    # Critical state-safety rule:
    # A pending clarification menu may only consume a type word when that type
    # exists in the displayed options. Otherwise the user is starting a new
    # product search. Example: after pending Flagyl variants, "غسول" must search
    # for cleanser products, not repeat the old Flagyl menu. Unknown/blank forms
    # inside the old menu are intentionally NOT treated as compatible.
    if q_type and not type_hits and not family_overlap and not exact_is_pending and not q_strengths and not q_clean.isdigit():
        _safe_clear_state(phone)
        return None

    # Numeric messages may be either a menu index, a strength for the pending
    # product, or a completely different product/code like "123". Do not let an
    # old Amoclan menu hijack a valid numeric product search.
    if q_clean.isdigit():
        n = int(q_clean)
        if 1 <= n <= len(options):
            item = options[n - 1]
            _safe_clear_state(phone)
            if is_available(item.get("available", "")):
                _safe_update_state(phone, {"last_product": item, "pending_variant_options": None, "pending_variant_kind": None, "pending_variant_query": None, "pending_alternatives": None})
            return QueryResult(reply=build_product_reply(item), decision="matched_variant", product=item, normalized_query=q_clean)
        by_strength_all = [e for e in entries if q_strengths & _entry_strength_values(e)]
        if not by_strength_all and exact and not exact_is_pending:
            _safe_clear_state(phone)
            return None
        if not by_strength_all and not exact:
            reply = _ask_variant_reply(phone, entries, user_state.get("pending_variant_kind", "variant"), user_state.get("pending_variant_query", q_clean))
            reply += "\n\nالجرعة التي كتبتها غير موجودة ضمن الخيارات المعروضة."
            return QueryResult(reply=reply, decision="variant_strength_not_found", normalized_query=q_clean)

    # If the new message is an exact product outside the displayed menu, it is a
    # new customer query. Clear the old pending menu and continue normal lookup.
    if exact and not exact_is_pending:
        _safe_clear_state(phone)
        return None

    # If the customer typed a different product family, do not keep repeating the
    # old variant menu. Example: pending Amoclan + "بنادول" => Panadol lookup.
    if incoming_family and pending_family and not family_overlap and not exact_is_pending:
        _safe_clear_state(phone)
        return None

    # A pending menu should only consume clear selection-like replies: a form,
    # strength, menu index, or same-family product text. Otherwise treat it as a
    # fresh product search.
    if not (q_type or q_strengths or family_overlap or exact_is_pending):
        _safe_clear_state(phone)
        return None

    filtered = entries
    if q_type:
        if type_hits:
            filtered = [e for e in filtered if any(str(e.item.get("id", "")) == str(hit.item.get("id", "")) for hit in type_hits)]
        else:
            _safe_clear_state(phone)
            return None
    if q_strengths:
        by_strength = [e for e in filtered if q_strengths & _entry_strength_values(e)]
        if len(by_strength) == 1:
            item = by_strength[0].item
            _safe_clear_state(phone)
            if is_available(item.get("available", "")):
                _safe_update_state(phone, {"last_product": item, "pending_variant_options": None, "pending_variant_kind": None, "pending_variant_query": None, "pending_alternatives": None})
            return QueryResult(reply=build_product_reply(item), decision="matched_variant", product=item, normalized_query=q_clean)
        if not by_strength:
            reply = _ask_variant_reply(phone, entries, user_state.get("pending_variant_kind", "variant"), user_state.get("pending_variant_query", q_clean))
            reply += "\n\nالجرعة التي كتبتها غير موجودة ضمن الخيارات المعروضة."
            return QueryResult(reply=reply, decision="variant_strength_not_found", normalized_query=q_clean)
        filtered = by_strength

    # Try exact match inside pending options by name/alias.
    if exact_is_pending and exact:
        item = exact.item
        _safe_clear_state(phone)
        if is_available(item.get("available", "")):
            _safe_update_state(phone, {"last_product": item, "pending_variant_options": None, "pending_variant_kind": None, "pending_variant_query": None, "pending_alternatives": None})
        return QueryResult(reply=build_product_reply(item), decision="matched_variant", product=item, normalized_query=q_clean)

    return QueryResult(reply=_ask_variant_reply(phone, filtered or entries, user_state.get("pending_variant_kind", "variant"), user_state.get("pending_variant_query", q_clean)), decision="variant_waiting", normalized_query=q_clean)

def _maybe_variant_disambiguation(phone: str, q_clean: str, item: dict) -> Optional["QueryResult"]:
    selected_entry = _entry_for_item(item)
    entries = _variant_candidates_for_query(q_clean, selected_entry)
    if len(entries) <= 1:
        return None

    q_brand, q_type, q_area = extract_features_norm(q_clean)
    q_strengths = extract_strength_values_norm(q_clean)

    # If customer gave a strength, force exact strength among same family/form.
    if q_strengths:
        strength_hits = [e for e in entries if q_strengths & _entry_strength_values(e)]
        if len(strength_hits) == 1:
            hit = strength_hits[0].item
            if str(hit.get("id", "")) != str(item.get("id", "")):
                return QueryResult(reply=build_product_reply(hit), decision="matched_variant", product=hit, normalized_query=q_clean)
            return None
        if not strength_hits and len(entries) > 1:
            return QueryResult(reply=_ask_variant_reply(phone, entries, "strength", q_clean) + "\n\nالجرعة المطلوبة غير موجودة ضمن الخيارات المتوفرة.", decision="variant_strength_not_found", normalized_query=q_clean)

    # If form is missing and same product family has multiple forms, ask form first.
    if not q_type:
        forms = {(_canonical_type_for_entry(e) or "unknown") for e in entries}
        forms.discard("unknown")
        if len(forms) > 1:
            return QueryResult(reply=_ask_variant_reply(phone, entries, "form", q_clean), decision="ask_form", normalized_query=q_clean)

    # If form is known but multiple strengths exist, ask strength before choosing first item.
    if q_type:
        same_form = [e for e in entries if _type_matches_query(e, q_type)]
        strength_values = {tuple(sorted(_entry_strength_values(e))) for e in same_form if _entry_strength_values(e)}
        if len(same_form) > 1 and len(strength_values) > 1 and not q_strengths:
            return QueryResult(reply=_ask_variant_reply(phone, same_form, "strength", q_clean), decision="ask_strength", normalized_query=q_clean)

    return None

@dataclass
class QueryResult:
    reply: str
    decision: str
    product: Optional[dict] = None
    order_item: Optional[dict] = None
    normalized_query: str = ""


def with_header(body: str) -> str:
    return f"{PHARMACY_HEADER}\n\n{body}"


def build_fallback_reply() -> str:
    return with_header("لم أفهم اسم المنتج المطلوب. الرجاء إرسال اسم المنتج أو صورته بوضوح.")


def build_brand_only_reply() -> str:
    return with_header("يرجى تحديد نوع المنتج أو إرسال صورة أوضح، مثل CeraVe Lotion أو CeraVe Cleanser.")


def build_category_only_reply() -> str:
    return with_header("يوجد أكثر من نوع، اكتب اسم الشركة أو أرسل صورة المنتج.")


def build_ambiguous_reply() -> str:
    return with_header("يوجد أكثر من منتج قريب من طلبك. اكتب اسم المنتج كاملاً أو أرسل صورة العلبة.")


def build_unclear_image_reply() -> str:
    return with_header("الصورة غير واضحة. الرجاء إرسال صورة أوضح أو كتابة اسم المنتج كما هو على العلبة.")


def build_prescription_reply() -> str:
    return with_header("الصورة تبدو كروشتة طبية وتحتاج مراجعة الصيدلية. سيتم الرد عليك من الصيدلية قريباً.")


def build_product_reply(item: dict) -> str:
    name = item.get("name", "")
    price = str(item.get("price", "")).strip()
    status_str = str(item.get("available", "")).strip()
    price_str = f"{price} د.ل" if price and "د" not in price else price

    if is_available(status_str):
        if not price_str:
            price_str = "غير محدد"
        return with_header(f"✅ المنتج: {name}\n📦 الحالة: متوفر\n💰 السعر: {price_str}\n\nللحجز اكتب: نعم")
    if is_unknown_availability(status_str):
        return with_header(f"✅ المنتج: {name}\n📦 الحالة: التوفر غير مؤكد في القائمة الحالية.\n\nاكتب للصيدلية أو أرسل الاسم للتأكيد قبل الحجز.")
    # Known unavailable: do not show stale price as if it can be ordered.
    return with_header(f"✅ المنتج: {name}\n📦 الحالة: غير متوفر حالياً")




def _safe_update_state(phone: str, state: dict) -> None:
    try:
        database.update_user_state(phone, state)
    except Exception as exc:
        print(f"USER_STATE_WRITE_WARNING: {exc}")


def _safe_clear_state(phone: str) -> None:
    try:
        database.clear_user_state(phone)
    except Exception as exc:
        print(f"USER_STATE_CLEAR_WARNING: {exc}")

def get_v3_catalog_index():
    """Return the prebuilt matcher_v3 index.

    Building the v3 index on each WhatsApp message is too slow on the real
    catalog and causes timeout_fallback replies. The index is built once at
    startup and invalidated only after product/synonym changes.
    """
    global _V3_CATALOG_INDEX, _V3_PRODUCTS_COUNT
    if _V3_CATALOG_INDEX is None:
        products = database.load_products()
        _V3_PRODUCTS_COUNT = len(products)
        _V3_CATALOG_INDEX = matcher_v4.build_catalog_index(products)
    return _V3_CATALOG_INDEX


def warmup_matcher_v3_cache() -> int:
    # PRICEBOT_MATCHER_WARMUP_SAFE_V1
    # Called only in background. It may build the strict V4 index, but it must
    # never be required before FastAPI can start serving /health/webhook.
    idx = get_v3_catalog_index()
    return len(getattr(idx, "records", []) or [])


def resolve_product_query_decision(query: str) -> matcher_v2.MatchDecision:
    """Strict v3 resolver entry point used by text and image flows.

    Important: no fallback to legacy safe_match is allowed for customer replies.
    This uses a cached CatalogIndex and never scans SQLite/catalog on every
    message.
    """
    return matcher_v4.resolve_product_query_from_index(query, get_v3_catalog_index())




def resolve_image_query_decision(ai_data: dict) -> matcher_v2.MatchDecision:
    """V4 image resolver: AI extraction is only structured evidence; local catalog decides."""
    return matcher_v4.resolve_image_extraction_from_index(ai_data or {}, get_v3_catalog_index())

def get_catalog_quality_rows() -> list:
    return matcher_v4.build_catalog_quality_rows(database.load_products())

def _v2_option_line(item: dict, index: int) -> str:
    # In clarification we only show identity fields. Price appears only after
    # the customer chooses one exact product.
    name = str(item.get("name", "") or "")
    form = str(item.get("form", "") or "").strip()
    strength = str(item.get("strength", "") or "").strip()
    pack = str(item.get("pack", "") or item.get("size", "") or "").strip()
    details = " / ".join(x for x in [form, strength, pack] if x)
    details_txt = f" ({details})" if details else ""
    return f"{index}) {name}{details_txt}"


def build_v2_clarification_reply(phone: str, decision: matcher_v2.MatchDecision) -> str:
    options = [opt for opt in (decision.clarification_options or []) if isinstance(opt, dict)]
    if options:
        _safe_update_state(phone, {
            "last_product": None,
            "pending_alternatives": None,
            "pending_variant_options": options[:12],
            "pending_variant_kind": decision.clarification_type or "product",
            "pending_variant_query": (decision.query_slots.normalized_query if decision.query_slots else ""),
        })
        lines = [decision.question or "يوجد أكثر من احتمال. الرجاء اختيار المنتج المطلوب:", ""]
        for i, item in enumerate(options[:12], 1):
            lines.append(_v2_option_line(item, i))
        return with_header("\n".join(lines))
    _safe_clear_state(phone)
    return build_ambiguous_reply()


def build_v2_alternatives_reply(phone: str, decision: matcher_v2.MatchDecision) -> str:
    alts = [alt for alt in (decision.alternatives or []) if isinstance(alt, dict)]
    target = decision.product or {}
    if target:
        body = f"⚠️ المنتج {target.get('name','')} غير متوفر حالياً في الصيدلية."
    else:
        body = "المنتج المطلوب غير موجود في قائمة الصيدلية حالياً."
    if alts:
        body += "\n\nبدائل متوفرة من نفس النوع والاستخدام:\n\n"
        for i, alt in enumerate(alts[:3], 1):
            price = str(alt.get("price", "") or "").strip()
            price_txt = f" - {price} د.ل" if price and "د" not in price else f" - {price}" if price else ""
            prefix = "⭐ أفضل ترشيح: " if i == 1 else f"{i}) "
            body += f"{prefix}{alt.get('name','')}{price_txt}\n"
        body += "\nاكتب رقم البديل للحجز أو الاستفسار."
        _safe_update_state(phone, {
            "last_product": None,
            "pending_variant_options": None,
            "pending_variant_kind": None,
            "pending_variant_query": None,
            "pending_alternatives": alts[:3],
        })
    else:
        _safe_clear_state(phone)
    return with_header(body.rstrip())


def _handle_v2_decision(phone: str, raw_text: str, decision: matcher_v2.MatchDecision) -> Optional["QueryResult"]:
    q_clean = clean_query(raw_text)
    dtype = decision.decision_type
    if dtype == matcher_v2.DecisionType.EXACT_MATCH and decision.product:
        item = decision.product
        if is_available(item.get("available", "")):
            _safe_update_state(phone, {"last_product": item, "pending_variant_options": None, "pending_variant_kind": None, "pending_variant_query": None, "pending_alternatives": None})
            return QueryResult(reply=build_product_reply(item), decision="matched", product=item, normalized_query=q_clean)
        _safe_clear_state(phone)
        if is_unknown_availability(item.get("available", "")):
            return QueryResult(reply=build_product_reply(item), decision="matched_unknown_availability", product=item, normalized_query=q_clean)
        return QueryResult(reply=build_unavailable_reply(q_clean, item, phone), decision="matched_unavailable", product=item, normalized_query=q_clean)
    if dtype == matcher_v2.DecisionType.ASK_CLARIFICATION:
        return QueryResult(reply=build_v2_clarification_reply(phone, decision), decision="ambiguous", normalized_query=q_clean)
    if dtype == matcher_v2.DecisionType.COSMETIC_ALTERNATIVES:
        return QueryResult(reply=build_v2_alternatives_reply(phone, decision), decision="alternatives", normalized_query=q_clean)
    if dtype == matcher_v2.DecisionType.NOT_AVAILABLE:
        # Medicines stay safe: no therapeutic alternatives unless explicitly configured later.
        if decision.product:
            return QueryResult(reply=build_unavailable_reply(q_clean, decision.product, phone), decision="matched_unavailable", product=decision.product, normalized_query=q_clean)
        _safe_clear_state(phone)
        return QueryResult(reply=with_header("المنتج المطلوب غير موجود في قائمة الصيدلية حالياً."), decision="unavailable", normalized_query=q_clean)
    if dtype == matcher_v2.DecisionType.LOW_CONFIDENCE:
        _safe_clear_state(phone)
        return QueryResult(reply=with_header("لم أتأكد من المنتج المقصود. الرجاء كتابة اسم المنتج كاملاً أو إرسال صورة واضحة للعلبة."), decision="low_confidence", normalized_query=q_clean)
    if dtype == matcher_v2.DecisionType.IMAGE_UNCLEAR:
        return QueryResult(reply=build_unclear_image_reply(), decision="image_unclear", normalized_query=q_clean)
    return None

def build_unavailable_reply(query_clean: str, target_product: Optional[dict], phone: str, explicit_area: str = None) -> str:
    """Safe unavailable reply.

    Do not run legacy alternative search here. Cosmetic alternatives are allowed
    only when V4 explicitly returns COSMETIC_ALTERNATIVES, because V4 has strict
    same-type/use-case guards. Medicines never get automatic alternatives.
    """
    if target_product:
        body = f"⚠️ المنتج {target_product.get('name','')} غير متوفر حالياً في الصيدلية."
    else:
        body = "المنتج المطلوب غير موجود في قائمة الصيدلية حالياً."
    if not is_cosmetic_context(str(query_clean or "") + " " + str((target_product or {}).get("name", ""))):
        body += "\n\nللبدائل الدوائية أو تغيير الجرعة، راجع الطبيب أو الصيدلي."
    _safe_clear_state(phone)
    return with_header(body.rstrip())

def handle_text_query_result(phone: str, text: str, user_state: dict) -> QueryResult:
    q_norm = normalize_text(text)
    q_clean = clean_query(text)

    if q_norm in GREETINGS_NORM or q_clean in GREETINGS_NORM:
        reply = with_header("مرحباً بك. أرسل اسم المنتج أو صورته للبحث عن السعر والتوفر.")
        return QueryResult(reply=reply, decision="greeting", normalized_query=q_clean)

    if q_norm in YES_WORDS_NORM:
        item = user_state.get("last_product") if user_state else None
        if item and is_available(item.get("available", "")):
            database.add_order(phone, item.get("name", ""), item.get("price", ""))
            _safe_clear_state(phone)
            reply = with_header(f"✅ تم تسجيل طلب الحجز للمنتج:\n{item.get('name', '')}\nسيتم التواصل معك قريباً للتأكيد.")
            return QueryResult(reply=reply, decision="order_created", product=item, order_item=item, normalized_query=q_clean)
        _safe_clear_state(phone)
        reply = with_header("لا يوجد منتج متاح للحجز حالياً. الرجاء البحث عن منتج متوفر أولاً.")
        return QueryResult(reply=reply, decision="no_order_item", normalized_query=q_clean)

    if q_norm in NO_WORDS_NORM:
        _safe_clear_state(phone)
        return QueryResult(reply=with_header("تم الإلغاء. يمكنك البحث عن منتج آخر."), decision="canceled", normalized_query=q_clean)

    pending_variant_result = _select_pending_variant(phone, q_clean, user_state or {})
    if pending_variant_result is not None:
        return pending_variant_result

    if q_norm.isdigit() and user_state and "pending_alternatives" in user_state:
        selected_index = int(q_norm) - 1
        alternatives = user_state.get("pending_alternatives") or []
        if 0 <= selected_index < len(alternatives):
            selected_item = alternatives[selected_index]
            _safe_clear_state(phone)
            if is_available(selected_item.get("available", "")):
                _safe_update_state(phone, {"last_product": selected_item, "pending_variant_options": None, "pending_variant_kind": None, "pending_variant_query": None, "pending_alternatives": None})
            reply = build_product_reply(selected_item)
            return QueryResult(reply=reply, decision="matched", product=selected_item, normalized_query=q_clean)

    try:
        v3_decision = resolve_product_query_decision(text)
        v3_result = _handle_v2_decision(phone, text, v3_decision)
        if v3_result is not None:
            return v3_result
    except Exception as exc:
        print(f"MATCHER_V3_TEXT_ERROR: {exc}")
        _safe_clear_state(phone)
        return QueryResult(reply=with_header("حدث خطأ في البحث عن المنتج. الرجاء كتابة الاسم الكامل أو إرسال صورة واضحة."), decision="error", normalized_query=q_clean)

    # V3 is the final decision engine. Do not fallback to legacy safe_match.
    _safe_clear_state(phone)
    return QueryResult(reply=with_header("لم أتمكن من تحديد المنتج بدقة. الرجاء كتابة الاسم الكامل أو إرسال صورة أوضح."), decision="low_confidence", normalized_query=q_clean)



MISS_LOG_DECISIONS = {"fallback", "unavailable", "ambiguous", "matched_unavailable", "variant_strength_not_found", "low_confidence"}


def _log_query_miss_if_needed(phone: str, raw_query: str, clean: str, decision: str) -> None:
    if decision in MISS_LOG_DECISIONS:
        try:
            database.log_query_miss(phone, raw_query, clean, decision)
        except Exception as exc:
            print(f"QUERY_MISS_LOG_WARNING: {exc}")


def handle_text_query(phone: str, text: str, user_state: dict) -> str:
    result = handle_text_query_result(phone, text, user_state)
    _log_query_miss_if_needed(phone, text, result.normalized_query, result.decision)
    return result.reply

def inspect_query(text: str) -> Dict[str, str]:
    q_norm = normalize_text(text)
    q_clean = clean_query(text)
    brand, product_type, area = extract_features_norm(q_clean)
    try:
        decision = resolve_product_query_decision(text)
        status = decision.decision_type.name
        item = decision.product or {}
    except Exception as exc:
        status = f"ERROR:{exc}"
        item = {}
    return {
        "raw_query": str(text or ""),
        "normalized_query": q_norm,
        "clean_query": q_clean,
        "detected_brand": brand or "",
        "detected_type": product_type or "",
        "detected_area": area or "",
        "match_result": status,
        "matched_product": item.get("name", "") if item else "",
        "matcher_engine": MATCHER_ENGINE_VERSION,
    }
