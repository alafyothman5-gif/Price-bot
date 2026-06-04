import difflib
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

import database


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
    "بانادول": "panadol",
    "crea ve": "cerave",
    "creave": "cerave",
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
    "syrup": ["syrup", "شراب"],
    "tablet": ["tablet", "tab", "caplet", "capsule", "قرص", "اقراص", "كبسول", "حبوب"],
    "drops": ["drops", "drop", "قطرة", "قطره"],
    "spray": ["spray", "بخاخ"],
}

TYPE_ORDER = ["cleanser", "sunscreen", "serum", "shampoo", "lotion", "moisturizer", "cream", "syrup", "tablet", "drops", "spray"]

AREA_WORDS = {
    "mouth": ["mouth", "oral", "dental", "teeth", "فم", "اسنان", "أسنان", "غسول فم"],
    "baby": ["baby", "enfant", "pediatril", "بيبي", "اطفال", "أطفال", "رضع", "kids", "طفل"],
    "hair": ["hair", "cheveux", "شعر", "scalp", "فروة"],
    "body": ["body", "corps", "جسم", "بدن"],
    "face": ["face", "visage", "وجه", "وجة", "بشرة", "بشره", "skin", "acne", "حبوب", "دهنية", "دهنيه", "oily", "normal skin"],
}

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
    arabic_map = {"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ٱ": "ا"}
    for src, dst in arabic_map.items():
        value = value.replace(src, dst)
    value = value.replace("ـ", "")
    value = re.sub(r"[\u064b-\u065f]", "", value)
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


SYNONYM_RULES = sorted(
    [(normalize_text_no_syn(src), normalize_text_no_syn(dst)) for src, dst in SYNONYMS.items()],
    key=lambda pair: len(pair[0]),
    reverse=True,
)


def normalize_text(text: str) -> str:
    value = normalize_text_no_syn(text)
    for src_norm, dst_norm in SYNONYM_RULES:
        value = _replace_norm_phrase(value, src_norm, dst_norm)
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
    value = normalize_text(text)
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
    status_norm = normalize_text(status_str)
    if not status_norm:
        return True
    return not any(term == status_norm or term in status_norm for term in UNAVAILABLE_TERMS_NORM)


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


def invalidate_product_cache() -> None:
    global _PRODUCT_INDEX
    _PRODUCT_INDEX = None


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
        entry = ProductEntry(
            item=item,
            identity=identity,
            name_norm=current_name_norm,
            aliases=aliases,
            brand=brand,
            product_type=product_type,
            area=area,
            tokens=set(tokens_norm(identity)),
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

    hits = 0.0
    for token in q_tokens:
        if token in entry.tokens:
            hits += 1.0
        elif len(token) >= 3 and any(token in pt or pt in token for pt in entry.tokens if len(pt) >= 3):
            hits += 0.8

    coverage = hits / max(len(q_tokens), 1)
    if distinct:
        distinct_hits = sum(1 for token in distinct if token in entry.tokens or any(token in pt or pt in token for pt in entry.tokens if len(token) >= 3 and len(pt) >= 3))
        distinct_score = distinct_hits / len(distinct)
    else:
        distinct_score = 0.0

    seq = difflib.SequenceMatcher(None, q_clean, entry.identity).ratio()
    phrase_bonus = 0.16 if q_clean and (q_clean in entry.identity or entry.identity in q_clean) else 0.0
    return coverage * 0.52 + distinct_score * 0.28 + seq * 0.20 + phrase_bonus


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
    q_clean = clean_query(query)
    if not q_clean or len(q_clean) < 2:
        return "FALLBACK", None
    if q_clean in GREETINGS_NORM:
        return "FALLBACK", None

    q_brand, q_type, q_area = extract_features_norm(q_clean)
    q_words = q_clean.split()
    cosmetic_brand = q_brand in COSMETIC_BRANDS_NORM
    distinct = distinctive_tokens_norm(q_clean)

    # Exact lookup must happen before noise/brand-only/category-only checks.
    # This allows valid numeric/code products like 123, 1,2,3 Extra, ABC123, Congestal, etc.
    index = get_product_index()
    exact_entry = _exact_lookup(index, q_clean, q_brand)
    if exact_entry:
        return "MATCHED", exact_entry.item

    if _is_obvious_noise(q_clean, q_brand, q_type):
        return "FALLBACK", None

    # Critical fast path: generic brand/category queries should not scan all products.
    if cosmetic_brand and not q_type and len(q_words) <= 3:
        return "BRAND_ONLY", None
    if q_type and not q_brand and len(q_words) <= 3:
        return "CATEGORY_ONLY", None

    candidates = _candidate_entries(index, q_brand, q_type, q_area)

    if cosmetic_brand and q_type and not distinct:
        if len(candidates) == 1:
            return "MATCHED", candidates[0].item
        return "AMBIGUOUS", None

    if q_clean not in (GENERIC_TERMS_NORM | COSMETIC_BRANDS_NORM):
        contains_hits = []
        for entry in candidates:
            if len(q_clean) >= 4 and (q_clean in entry.identity or entry.identity in q_clean):
                contains_hits.append(entry)
        contains_hits = _unique_entries(contains_hits)
        if len(contains_hits) == 1:
            return "MATCHED", contains_hits[0].item
        if len(contains_hits) > 1:
            # Prefer an available item; otherwise ask/return the best score below.
            available_hits = [entry for entry in contains_hits if matcher_item_available(entry.item)]
            contains_hits = available_hits or contains_hits
            if q_brand or q_type or len(q_words) > 1:
                return "MATCHED", contains_hits[0].item

    q_tokens = tokens_norm(q_clean)
    best_entry = None
    best_score = 0.0
    second_score = 0.0
    for entry in candidates:
        score = _score_entry(q_clean, q_tokens, distinct, entry)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_entry = entry
        elif score > second_score:
            second_score = score

    if len(q_words) <= 1 and not q_brand and not q_type:
        min_score = 0.80 if len(q_clean) >= 4 else 0.88
    elif q_brand or q_type:
        min_score = 0.66 if distinct else 0.78
    else:
        min_score = 0.76

    if best_entry and best_score >= min_score:
        if cosmetic_brand and q_type and second_score and (best_score - second_score) < 0.04 and not distinct:
            return "AMBIGUOUS", None
        return "MATCHED", best_entry.item

    # General resolver rule: after exact/alias/token/fuzzy lookup, a clean product-like word
    # should be treated as a missing product, not as "I did not understand".
    return "UNAVAILABLE", None

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

    scored = []
    q_tokens = tokens_norm(query_clean or target_id)
    distinct = distinctive_tokens_norm(query_clean or target_id)
    target_id_to_skip = str(target_product.get("id", "")) if target_product else ""

    for entry in _unique_entries(candidate_entries):
        if not matcher_item_available(entry.item):
            continue
        if target_id_to_skip and str(entry.item.get("id", "")) == target_id_to_skip:
            continue
        if target_area == "face" and any(term and term in entry.identity for term in BLOCKED_FACE_ALT_TERMS_NORM):
            continue
        if target_area and entry.area and target_area != entry.area:
            continue

        score = 0.0
        if target_brand and entry.brand == target_brand:
            score += 50
        if target_area and entry.area == target_area:
            score += 25
        for term in SHARED_TERMS_NORM:
            if term in target_id and term in entry.identity:
                score += 10
        score += _score_entry(query_clean or target_id, q_tokens, distinct, entry) * 35
        scored.append((score, entry.item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]


def matcher_item_available(item: dict) -> bool:
    return is_available(item.get("available", "متوفر"))


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
    status_str = str(item.get("available", "متوفر")).strip() or "متوفر"
    price_str = f"{price} د.ل" if price and "د" not in price else price
    if not price_str:
        price_str = "غير محدد"

    if is_available(status_str):
        return with_header(f"✅ المنتج: {name}\n📦 الحالة: متوفر\n💰 السعر: {price_str}\n\nللحجز اكتب: نعم")
    return with_header(f"✅ المنتج: {name}\n📦 الحالة: غير متوفر حالياً\n💰 السعر: {price_str}")


def build_unavailable_reply(query_clean: str, target_product: Optional[dict], phone: str, explicit_area: str = None) -> str:
    alternatives = get_cosmetic_alternatives(target_product, query_clean, explicit_area=explicit_area)
    body = "المنتج المطلوب غير متوفر حالياً في قائمة الصيدلية."
    if alternatives:
        body += "\n\nبدائل متوفرة قريبة من نفس النوع:\n\n"
        for index, alt in enumerate(alternatives, 1):
            price = str(alt.get("price", "")).strip()
            price_text = f" - {price} د.ل" if price and "د" not in price else f" - {price}" if price else ""
            body += f"{index}) {alt.get('name', '')}{price_text}\n"
        body += "\nاكتب رقم البديل للحجز أو الاستفسار."
        database.update_user_state(phone, {"pending_alternatives": alternatives})
    else:
        database.clear_user_state(phone)
    return with_header(body.rstrip())


def handle_text_query_result(phone: str, text: str, user_state: dict) -> QueryResult:
    q_norm = normalize_text(text)
    q_clean = clean_query(text)

    if q_norm in GREETINGS_NORM or q_clean in GREETINGS_NORM:
        reply = with_header("مرحباً بك. أرسل اسم المنتج أو صورته للبحث عن السعر والتوفر.")
        return QueryResult(reply=reply, decision="greeting", normalized_query=q_clean)

    if q_norm in YES_WORDS_NORM:
        item = user_state.get("last_product") if user_state else None
        if item and is_available(item.get("available", "متوفر")):
            database.add_order(phone, item.get("name", ""), item.get("price", ""))
            database.clear_user_state(phone)
            reply = with_header(f"✅ تم تسجيل طلب الحجز للمنتج:\n{item.get('name', '')}\nسيتم التواصل معك قريباً للتأكيد.")
            return QueryResult(reply=reply, decision="order_created", product=item, order_item=item, normalized_query=q_clean)
        database.clear_user_state(phone)
        reply = with_header("لا يوجد منتج متاح للحجز حالياً. الرجاء البحث عن منتج متوفر أولاً.")
        return QueryResult(reply=reply, decision="no_order_item", normalized_query=q_clean)

    if q_norm in NO_WORDS_NORM:
        database.clear_user_state(phone)
        return QueryResult(reply=with_header("تم الإلغاء. يمكنك البحث عن منتج آخر."), decision="canceled", normalized_query=q_clean)

    if q_norm.isdigit() and user_state and "pending_alternatives" in user_state:
        selected_index = int(q_norm) - 1
        alternatives = user_state.get("pending_alternatives") or []
        if 0 <= selected_index < len(alternatives):
            selected_item = alternatives[selected_index]
            database.clear_user_state(phone)
            if is_available(selected_item.get("available", "متوفر")):
                database.update_user_state(phone, {"last_product": selected_item})
            reply = build_product_reply(selected_item)
            return QueryResult(reply=reply, decision="matched", product=selected_item, normalized_query=q_clean)

    status, item = safe_match(q_clean)

    if status == "FALLBACK":
        return QueryResult(reply=build_fallback_reply(), decision="fallback", normalized_query=q_clean)
    if status == "BRAND_ONLY":
        return QueryResult(reply=build_brand_only_reply(), decision="brand_only", normalized_query=q_clean)
    if status == "CATEGORY_ONLY":
        return QueryResult(reply=build_category_only_reply(), decision="category_only", normalized_query=q_clean)
    if status == "AMBIGUOUS":
        return QueryResult(reply=build_ambiguous_reply(), decision="ambiguous", normalized_query=q_clean)
    if status == "MATCHED" and item:
        if is_available(item.get("available", "متوفر")):
            database.update_user_state(phone, {"last_product": item})
            decision = "matched"
        else:
            database.clear_user_state(phone)
            decision = "matched_unavailable"
        return QueryResult(reply=build_product_reply(item), decision=decision, product=item, normalized_query=q_clean)

    reply = build_unavailable_reply(q_clean, None, phone)
    return QueryResult(reply=reply, decision="unavailable", normalized_query=q_clean)


def handle_text_query(phone: str, text: str, user_state: dict) -> str:
    return handle_text_query_result(phone, text, user_state).reply

def inspect_query(text: str) -> Dict[str, str]:
    q_norm = normalize_text(text)
    q_clean = clean_query(text)
    brand, product_type, area = extract_features_norm(q_clean)
    status, item = safe_match(q_clean)
    return {
        "raw_query": str(text or ""),
        "normalized_query": q_norm,
        "clean_query": q_clean,
        "detected_brand": brand or "",
        "detected_type": product_type or "",
        "detected_area": area or "",
        "match_result": status,
        "matched_product": item.get("name", "") if item else "",
    }
