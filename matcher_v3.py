"""
PriceBot matcher_v3.py
Strict production-grade product matching engine.

This engine is intentionally conservative:
- no global random fuzzy match
- no fallback to legacy matcher.safe_match
- no medicine alternatives unless explicitly configured later
- AI vision can only supply structured text; final price/availability decisions are local catalog decisions
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    import difflib

    class _FuzzFallback:
        @staticmethod
        def ratio(a, b):
            return difflib.SequenceMatcher(None, str(a or ""), str(b or "")).ratio() * 100

        @staticmethod
        def partial_ratio(a, b):
            a, b = str(a or ""), str(b or "")
            if not a or not b:
                return 0
            if a in b or b in a:
                return 100
            return difflib.SequenceMatcher(None, a, b).ratio() * 100

        @staticmethod
        def token_set_ratio(a, b):
            sa, sb = set(str(a or "").split()), set(str(b or "").split())
            if not sa or not sb:
                return 0
            return (2 * len(sa & sb) / (len(sa) + len(sb))) * 100

    fuzz = _FuzzFallback()

# Reuse the existing decision classes so matcher.py response builders keep working.
from matcher_v2 import DecisionType, MatchDecision  # noqa: E402

VERSION = "stable-v14-matcher-v3-strict-engine"

ARABIC_MAP = {
    "أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ٱ": "ا",
    "ڤ": "ف", "ک": "ك", "ی": "ي", "گ": "ك", "چ": "ج", "پ": "ب",
}
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

REQUEST_STOPWORDS = {
    "متوفر", "موجود", "عندكم", "عندك", "السعر", "سعر", "بكم", "كم", "نبي", "نريد", "ابي", "ابى", "أبي",
    "اريد", "لو", "سمحت", "بالله", "هل", "يوجد", "في", "فيه", "من", "فضلك", "شنو", "قداش",
    "available", "price", "do", "you", "have", "need", "want", "how", "much", "please", "is", "there",
}

STATIC_SYNONYMS = {
    # brands / common spellings
    "cera ve": "cerave", "cera-ve": "cerave", "ceravé": "cerave", "cearave": "cerave", "cearve": "cerave", "creave": "cerave",
    "سيرافي": "cerave", "سيرا في": "cerave", "سيراڤي": "cerave",
    "la roche posay": "laroche", "la roche": "laroche", "laroche posay": "laroche", "لاروش بوزيه": "laroche", "لاروش": "laroche",
    "بيوديرما": "bioderma", "بايوديرما": "bioderma", "بيودرما": "bioderma", "فوتوديرم": "photoderm",
    "ذا اورديناري": "theordinary", "the ordinary": "theordinary", "اورديناري": "theordinary",
    # medicines
    "بنادول": "panadol", "بندول": "panadol", "بانادول": "panadol", "بنادووول": "panadol",
    "باراسيتامول": "paracetamol", "براسيتامول": "paracetamol",
    "فلاجيل": "flagyl", "فلجيل": "flagyl", "فلاجل": "flagyl", "flgyl": "flagyl", "metronidazol": "metronidazole",
    "اموكلان": "amoclan", "اوموكلان": "amoclan", "اموكلين": "amoclan",
    # forms/types
    "tab": "tablet", "tabs": "tablet", "tablets": "tablet", "حبوب": "tablet", "اقراص": "tablet", "أقراص": "tablet",
    "cap": "capsule", "caps": "capsule", "capsules": "capsule", "كبسول": "capsule", "كبسولات": "capsule",
    "suspension": "syrup", "susp": "syrup", "syrup": "syrup", "syrop": "syrup", "شراب": "syrup", "معلق": "syrup",
    "suppositories": "suppository", "suppository": "suppository", "supp": "suppository", "تحاميل": "suppository", "لبوس": "suppository",
    "injections": "injection", "injection": "injection", "inj": "injection", "حقن": "injection", "حقنه": "injection",
    "drops": "drops", "drop": "drops", "قطرة": "drops", "قطره": "drops",
    "spray": "spray", "بخاخ": "spray",
    "face wash": "cleanser", "face cleanser": "cleanser", "cleanser": "cleanser", "wash": "cleanser", "غسول وجه": "cleanser", "غسول": "cleanser", "منظف": "cleanser",
    "lotion": "lotion", "لوشن": "lotion",
    "serum": "serum", "سيروم": "serum",
    "cream": "cream", "كريم": "cream",
    "baume": "balm", "balm": "balm", "بلسم": "balm",
    "sunscreen": "sunscreen", "sun screen": "sunscreen", "sunblock": "sunscreen", "sun block": "sunscreen", "واقي شمس": "sunscreen", "واقي": "sunscreen", "سن بلوك": "sunscreen",
    "shampoo": "shampoo", "شامبو": "shampoo",
    "moisturising": "moisturizing", "moisturiser": "moisturizer", "مرطب": "moisturizer", "ترطيب": "moisturizer",
    # use/skin
    "بشرة دهنية": "oily skin", "بشره دهنيه": "oily skin", "دهنيه": "oily skin", "دهنية": "oily skin",
    "بشرة جافة": "dry skin", "بشره جافه": "dry skin", "جافه": "dry skin", "جافة": "dry skin",
    "حساسة": "sensitive skin", "حساسه": "sensitive skin", "حب الشباب": "acne", "تصبغات": "pigmentation",
}

KNOWN_BRANDS = {
    "cerave", "laroche", "bioderma", "vichy", "eucerin", "acm", "svr", "uriage", "avene", "rilastil", "isispharma",
    "cetaphil", "theordinary", "ordinary", "mustela", "nuxe", "babaria", "panadol", "adol", "flagyl", "metronidazole",
    "amoclan", "augmentin", "congestal", "brufen", "voltaren", "cataflam", "zyrtec", "telfast",
}
COSMETIC_BRANDS = {
    "cerave", "laroche", "bioderma", "vichy", "eucerin", "acm", "svr", "uriage", "avene", "rilastil", "isispharma",
    "cetaphil", "theordinary", "ordinary", "mustela", "nuxe", "babaria",
}
MEDICINE_FAMILIES = {
    "panadol", "adol", "paracetamol", "flagyl", "metronidazole", "amoclan", "augmentin", "congestal", "brufen",
    "voltaren", "cataflam", "zyrtec", "telfast",
}

MEDICINE_FORMS = {"tablet", "capsule", "syrup", "suppository", "injection", "drops", "spray"}
COSMETIC_TYPES = {"cleanser", "lotion", "moisturizer", "cream", "serum", "sunscreen", "toner", "gel", "oil", "shampoo", "balm", "mask"}
ALL_TYPES = MEDICINE_FORMS | COSMETIC_TYPES | {"ointment"}

USE_CASE_WORDS = {
    "hydration": {"hydrating", "hydration", "moisturizing", "moisturizer", "ترطيب"},
    "acne": {"acne", "salicylic", "effaclar", "normaderm", "sebium", "keracnyl", "حب"},
    "dry_skin": {"dry skin", "xerolact", "urea", "جاف", "جافة"},
    "oily_skin": {"oily skin", "oil control", "دهنيه", "دهنية"},
    "sensitive_skin": {"sensitive skin", "sensibio", "toleriane", "حساس"},
    "barrier_repair": {"barrier", "repair", "cicaplast", "cicalfate", "balm", "baume"},
    "anti_pigmentation": {"pigmentation", "depigment", "depiwhite", "تصبغ"},
    "anti_dandruff": {"dandruff", "anti dandruff", "قشرة", "قشره"},
    "sun_protection": {"sunscreen", "spf", "sun protection", "واقي"},
}
SKIN_WORDS = {
    "dry_skin": {"dry skin", "جاف", "جافة"},
    "oily_skin": {"oily skin", "دهنية", "دهنيه"},
    "sensitive_skin": {"sensitive skin", "حساس", "حساسة", "حساسه"},
}

WEAK_TOKENS = {
    "skin", "face", "body", "cream", "gel", "oil", "daily", "active", "hydrating", "moisturizing", "moisturizer",
    "50ml", "100ml", "ml", "mg", "pb", "lotion", "serum", "cleanser", "sunscreen", "shampoo", "balm",
}
IMPORTANT_KEEP = {
    "baume", "balm", "serum", "cleanser", "lotion", "cream", "foaming", "hydrating", "daily", "moisturizing", "moisturising",
    "gel", "oil", "sunscreen", "shampoo", "toner", "syrup", "tablet", "capsule", "suppository", "injection", "drops", "spray",
}
TYPE_CONFLICTS = {
    "cleanser": {"moisturizer", "cream", "serum", "lotion", "sunscreen", "shampoo"},
    "moisturizer": {"cleanser", "serum", "sunscreen", "shampoo"},
    "lotion": {"serum", "cleanser", "sunscreen", "shampoo"},
    "serum": {"lotion", "cleanser", "cream", "moisturizer", "sunscreen", "shampoo"},
    "cream": {"cleanser", "serum", "sunscreen", "shampoo"},
    "sunscreen": {"serum", "cleanser", "lotion", "shampoo"},
    "shampoo": {"cleanser", "cream", "serum", "lotion", "sunscreen"},
    "syrup": {"tablet", "capsule", "suppository", "injection", "drops", "spray"},
    "tablet": {"syrup", "capsule", "suppository", "injection", "drops", "spray"},
    "capsule": {"syrup", "tablet", "suppository", "injection", "drops", "spray"},
    "suppository": {"tablet", "capsule", "syrup", "injection", "drops", "spray"},
    "injection": {"tablet", "capsule", "syrup", "suppository", "drops", "spray"},
    "drops": {"tablet", "capsule", "syrup", "suppository", "injection"},
    "spray": {"tablet", "capsule", "syrup", "suppository", "injection"},
}

STRENGTH_RE = re.compile(r"(?<!\w)(\d+(?:[\.,]\d+)?)(?:\s*(mg|mcg|g|ml|iu|unit|units|%|مجم|ملجم|مل|جم))?", re.I)
SIZE_RE = re.compile(r"(?<!\w)(\d+(?:[\.,]\d+)?)(?:\s*(ml|g|gm|kg|l|oz|fl oz|مل|جم))", re.I)

@dataclass
class ProductRecord:
    id: str
    original_name: str
    normalized_name: str
    brand: str = ""
    product_family: str = ""
    active_ingredient: str = ""
    category: str = ""
    is_medicine: bool = False
    is_cosmetic: bool = False
    form: str = ""
    strength: str = ""
    size: str = ""
    concentration: str = ""
    route: str = ""
    cosmetic_type: str = ""
    use_case: str = ""
    skin_type: str = ""
    aliases: Set[str] = field(default_factory=set)
    image_keywords: Set[str] = field(default_factory=set)
    price: str = ""
    availability: str = "متوفر"
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> str:
        parts = [
            self.normalized_name, self.brand, self.product_family, self.active_ingredient, self.category, self.form,
            self.strength, self.size, self.concentration, self.cosmetic_type, self.use_case, self.skin_type,
            " ".join(sorted(self.aliases)), " ".join(sorted(self.image_keywords)),
        ]
        return normalize_product_text(" ".join(x for x in parts if x))

    @property
    def tokens(self) -> Set[str]:
        return set(tokenize(self.identity))

@dataclass
class QuerySlots:
    cleaned_text: str = ""
    brand: str = ""
    product_family: str = ""
    active_ingredient: str = ""
    form: str = ""
    strength: str = ""
    strength_values: Set[str] = field(default_factory=set)
    size: str = ""
    size_values: Set[str] = field(default_factory=set)
    cosmetic_type: str = ""
    use_case: str = ""
    skin_type: str = ""
    is_medicine_query: bool = False
    is_cosmetic_query: bool = False
    is_specific_named_product: bool = False
    weak_tokens: Set[str] = field(default_factory=set)
    strong_tokens: Set[str] = field(default_factory=set)
    # compatibility with old builders
    normalized_query: str = ""
    meaningful_tokens: Set[str] = field(default_factory=set)

@dataclass
class CatalogIndex:
    records: List[ProductRecord]
    exact_name_index: Dict[str, List[ProductRecord]] = field(default_factory=dict)
    alias_index: Dict[str, List[ProductRecord]] = field(default_factory=dict)
    barcode_index: Dict[str, List[ProductRecord]] = field(default_factory=dict)
    brand_index: Dict[str, List[ProductRecord]] = field(default_factory=dict)
    family_index: Dict[str, List[ProductRecord]] = field(default_factory=dict)
    medicine_variant_index: Dict[str, List[ProductRecord]] = field(default_factory=dict)
    cosmetic_type_index: Dict[str, List[ProductRecord]] = field(default_factory=dict)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_no_syn(text: Any) -> str:
    value = _safe_str(text).lower()
    for src, dst in ARABIC_MAP.items():
        value = value.replace(src, dst)
    value = value.translate(ARABIC_DIGITS)
    value = value.replace("ـ", "")
    value = re.sub(r"[\u064b-\u065f]", "", value)
    value = re.sub(r"(.)\1{2,}", r"\1\1", value)
    value = re.sub(r"[^\w\s%\.]+", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


_RULES_CACHE: Optional[List[Tuple[str, str]]] = None


def _load_dynamic_synonyms() -> Dict[str, str]:
    try:
        import database  # local import avoids circular import during app startup
        return {str(k): str(v) for k, v in (database.load_dynamic_synonyms() or {}).items() if str(k or '').strip() and str(v or '').strip()}
    except Exception:
        return {}


def refresh_synonym_rules() -> None:
    global _RULES_CACHE
    _RULES_CACHE = None
    get_catalog_index.cache_clear()


def _rules() -> List[Tuple[str, str]]:
    global _RULES_CACHE
    if _RULES_CACHE is not None:
        return _RULES_CACHE
    combined = dict(STATIC_SYNONYMS)
    combined.update(_load_dynamic_synonyms())
    rules: List[Tuple[str, str]] = []
    for src, dst in combined.items():
        s, d = _normalize_no_syn(src), _normalize_no_syn(dst)
        if s and d:
            rules.append((s, d))
    _RULES_CACHE = sorted(rules, key=lambda p: len(p[0]), reverse=True)
    return _RULES_CACHE


def normalize_product_text(text: Any) -> str:
    value = _normalize_no_syn(text)
    for src, dst in _rules():
        value = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, value)
    folds = {
        "moisturising": "moisturizing", "moisturiser": "moisturizer", "tabs": "tablet", "tablets": "tablet",
        "caps": "capsule", "capsules": "capsule", "syrop": "syrup", "suspension": "syrup", "suppositories": "suppository",
        "injections": "injection", "sun screen": "sunscreen", "cera ve": "cerave",
    }
    for src, dst in sorted(folds.items(), key=lambda p: len(p[0]), reverse=True):
        value = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, value)
    return re.sub(r"\s+", " ", value).strip()


def clean_request_text(text: Any) -> str:
    norm = normalize_product_text(text)
    tokens = [t for t in norm.split() if t not in REQUEST_STOPWORDS]
    return " ".join(tokens).strip()


def tokenize(norm_text: str) -> List[str]:
    return [t for t in str(norm_text or "").split() if t and t not in REQUEST_STOPWORDS and len(t) > 1]


def _field(item: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def _split_field(value: Any) -> List[str]:
    if value is None:
        return []
    return [part.strip() for part in re.split(r"[,،|;\n]+", str(value)) if part and part.strip()]


def _contains_phrase(text: str, phrase: str) -> bool:
    text, phrase = normalize_product_text(text), normalize_product_text(phrase)
    return bool(text and phrase and f" {phrase} " in f" {text} ")


def _detect_brand(norm: str) -> str:
    for b in sorted(KNOWN_BRANDS, key=len, reverse=True):
        if _contains_phrase(norm, b):
            return b
    return ""


def _detect_type(norm: str) -> str:
    # Long/specific words first; cleanser must win over gel.
    order = ["suppository", "injection", "capsule", "tablet", "syrup", "drops", "spray", "cleanser", "sunscreen", "serum", "shampoo", "lotion", "cream", "ointment", "balm", "moisturizer", "toner", "mask", "gel", "oil"]
    for typ in order:
        if _contains_phrase(norm, typ):
            return typ
    if _contains_phrase(norm, "moisturizing") or _contains_phrase(norm, "hydrating"):
        return "moisturizer"
    return ""


def _detect_use_case(norm: str) -> str:
    for use, words in USE_CASE_WORDS.items():
        for word in sorted(words, key=len, reverse=True):
            if _contains_phrase(norm, word):
                return use
    return ""


def _detect_skin_type(norm: str) -> str:
    for skin, words in SKIN_WORDS.items():
        for word in sorted(words, key=len, reverse=True):
            if _contains_phrase(norm, word):
                return skin
    return ""


def _num(value: str) -> str:
    value = str(value or "").replace(",", ".")
    try:
        f = float(value)
        return str(int(f)) if f.is_integer() else str(f).rstrip("0").rstrip(".")
    except Exception:
        return re.sub(r"\D+", "", value)


def extract_strength_values(text: Any) -> Set[str]:
    norm = normalize_product_text(text)
    out: Set[str] = set()
    for num, unit in STRENGTH_RE.findall(norm):
        n = _num(num)
        if not n:
            continue
        u = normalize_product_text(unit)
        out.add(n)
        if u:
            out.add(f"{n}{u}")
    return out


def extract_size_values(text: Any) -> Set[str]:
    norm = normalize_product_text(text)
    out: Set[str] = set()
    for num, unit in SIZE_RE.findall(norm):
        n = _num(num)
        u = normalize_product_text(unit)
        if n:
            out.add(n)
            if u:
                out.add(f"{n}{u}")
    return out


def _availability_ok(value: Any) -> bool:
    norm = normalize_product_text(value or "متوفر")
    if not norm:
        return True
    bad = {"غير متوفر", "غير موجود", "نافذ", "نفذ", "ناقص", "out of stock", "unavailable", "no", "0"}
    return not any(x and (x == norm or x in norm) for x in bad)


def _route_for_form(form: str) -> str:
    return {
        "tablet": "oral", "capsule": "oral", "syrup": "oral", "suppository": "rectal", "injection": "parenteral",
        "drops": "local", "spray": "local", "cream": "topical", "ointment": "topical", "gel": "topical", "lotion": "topical",
        "cleanser": "topical", "serum": "topical", "sunscreen": "topical", "shampoo": "topical", "balm": "topical",
    }.get(form, "")


def _infer_product_family(norm: str, brand: str, form: str, cosmetic_type: str) -> str:
    remove = set(REQUEST_STOPWORDS) | ALL_TYPES | {"mg", "ml", "g", "gm", "مجم", "مل", "جم", "spf", "daily", "skin", "face", "body"}
    if brand:
        remove.add(brand)
    keep = []
    for t in tokenize(norm):
        if t in remove or t.isdigit():
            continue
        # keep line names such as xerolact, sebium, hydrating; weak-only logic happens later
        keep.append(t)
    return " ".join(keep[:5]).strip()


def _classify_is_medicine(norm: str, brand: str, form: str, category: str, active: str) -> bool:
    if form in MEDICINE_FORMS:
        return True
    if brand in MEDICINE_FAMILIES or active in MEDICINE_FAMILIES:
        return True
    if any(_contains_phrase(norm, med) for med in MEDICINE_FAMILIES):
        return True
    if "دواء" in category or "medicine" in category or "drug" in category:
        return True
    return False


def _classify_is_cosmetic(norm: str, brand: str, form: str, category: str) -> bool:
    if form in COSMETIC_TYPES or brand in COSMETIC_BRANDS:
        return True
    if any(w in category for w in ["cosmetic", "كوز", "skin", "hair", "beauty"]):
        return True
    return False


def to_product_record(item: Dict[str, Any]) -> ProductRecord:
    name = _field(item, "name", "original_name")
    identity_raw = " ".join(_field(item, f) for f in [
        "name", "original_name", "normalized_name", "brand", "company", "category", "category_guess", "form", "active_ingredient",
        "strength", "pack", "size", "concentration", "aliases", "image_ocr_keywords", "ocr_keywords", "keywords", "code", "barcode", "sku",
        "item_code", "product_code", "source_serial",
    ])
    norm_name = normalize_product_text(_field(item, "normalized_name") or name)
    norm_identity = normalize_product_text(identity_raw)
    brand = normalize_product_text(_field(item, "brand", "company")) or _detect_brand(norm_identity)
    explicit_form = normalize_product_text(_field(item, "form"))
    form = _detect_type(explicit_form) or (explicit_form if explicit_form in ALL_TYPES else "") or _detect_type(norm_identity)
    cosmetic_type = form if form in COSMETIC_TYPES else ""
    active = normalize_product_text(_field(item, "active_ingredient"))
    category = normalize_product_text(_field(item, "category", "category_guess"))
    is_med = _classify_is_medicine(norm_identity, brand, form, category, active)
    is_cos = _classify_is_cosmetic(norm_identity, brand, form, category) and not (is_med and form in MEDICINE_FORMS)
    if is_med and form in MEDICINE_FORMS:
        cosmetic_type = ""
    use_case = normalize_product_text(_field(item, "use_case")) or _detect_use_case(norm_identity)
    skin_type = normalize_product_text(_field(item, "skin_type")) or _detect_skin_type(norm_identity)
    strength = normalize_product_text(_field(item, "strength"))
    if not strength:
        vals = extract_strength_values(norm_identity)
        strength = sorted(vals, key=len)[0] if vals else ""
    size = normalize_product_text(_field(item, "size", "pack"))
    family = normalize_product_text(_field(item, "product_family", "family")) or _infer_product_family(norm_name, brand, form, cosmetic_type)
    aliases = {normalize_product_text(x) for x in _split_field(_field(item, "aliases"))}
    image_kw = {normalize_product_text(x) for x in _split_field(_field(item, "image_ocr_keywords", "ocr_keywords", "keywords"))}
    return ProductRecord(
        id=_field(item, "id", "product_id", "code") or norm_name,
        original_name=name,
        normalized_name=norm_name,
        brand=brand,
        product_family=family,
        active_ingredient=active,
        category=category,
        is_medicine=is_med,
        is_cosmetic=is_cos,
        form=form,
        strength=strength,
        size=size,
        concentration=normalize_product_text(_field(item, "concentration")),
        route=_route_for_form(form),
        cosmetic_type=cosmetic_type,
        use_case=use_case,
        skin_type=skin_type,
        aliases={a for a in aliases if a},
        image_keywords={k for k in image_kw if k},
        price=_field(item, "price"),
        availability=_field(item, "available", "availability") or "متوفر",
        raw=item,
    )


def _add_index(index: Dict[str, List[ProductRecord]], key: str, rec: ProductRecord) -> None:
    key = normalize_product_text(key)
    if key:
        index.setdefault(key, []).append(rec)


@lru_cache(maxsize=8)
def get_catalog_index(catalog_key: Tuple[Tuple[Tuple[str, str], ...], ...]) -> CatalogIndex:
    items = [dict(pairs) for pairs in catalog_key]
    records = [to_product_record(item) for item in items if _field(item, "name", "original_name")]
    ci = CatalogIndex(records=records)
    for rec in records:
        _add_index(ci.exact_name_index, rec.normalized_name, rec)
        for alias in rec.aliases | rec.image_keywords:
            _add_index(ci.alias_index, alias, rec)
        for f in ["barcode", "code", "sku", "item_code", "product_code", "source_serial"]:
            val = normalize_product_text(rec.raw.get(f, ""))
            if val:
                _add_index(ci.barcode_index, val, rec)
        if rec.brand:
            _add_index(ci.brand_index, rec.brand, rec)
        fam_key = " ".join(x for x in [rec.brand, rec.product_family] if x).strip()
        if fam_key:
            _add_index(ci.family_index, fam_key, rec)
        med_key = " ".join(x for x in [rec.active_ingredient or rec.product_family or rec.brand, rec.form, rec.strength] if x).strip()
        if med_key:
            _add_index(ci.medicine_variant_index, med_key, rec)
        cos_key = " ".join(x for x in [rec.cosmetic_type or rec.form, rec.use_case, rec.skin_type] if x).strip()
        if cos_key:
            _add_index(ci.cosmetic_type_index, cos_key, rec)
    return ci


def _catalog_key(catalog: Sequence[Dict[str, Any]]) -> Tuple[Tuple[Tuple[str, str], ...], ...]:
    # Keep key small enough but complete for tests and app cache invalidation.
    key = []
    for item in catalog:
        pairs = tuple(sorted((str(k), str(v or "")) for k, v in dict(item).items()))
        key.append(pairs)
    return tuple(key)


def build_catalog_index(catalog: Sequence[Dict[str, Any]]) -> CatalogIndex:
    return get_catalog_index(_catalog_key(catalog))


def _strong_weak(tokens: Iterable[str]) -> Tuple[Set[str], Set[str]]:
    strong, weak = set(), set()
    for tok in tokens:
        if tok in REQUEST_STOPWORDS:
            continue
        if tok in WEAK_TOKENS or len(tok) <= 1:
            weak.add(tok)
        else:
            strong.add(tok)
    return strong, weak


def extract_query_slots(query: Any) -> QuerySlots:
    cleaned = clean_request_text(query)
    toks = set(tokenize(cleaned))
    brand = _detect_brand(cleaned)
    form = _detect_type(cleaned)
    cosmetic_type = form if form in COSMETIC_TYPES else ""
    active = ""
    for med in sorted(MEDICINE_FAMILIES, key=len, reverse=True):
        if _contains_phrase(cleaned, med):
            active = med
            break
    strength_values = extract_strength_values(cleaned)
    size_values = extract_size_values(cleaned)
    use_case = _detect_use_case(cleaned)
    skin_type = _detect_skin_type(cleaned)
    strong, weak = _strong_weak(toks)
    # Brand and type are strong only when combined with at least one product word/variant.
    non_brand_strong = set(strong)
    non_brand_strong.discard(brand)
    family_tokens = [t for t in toks if t not in REQUEST_STOPWORDS and t not in ALL_TYPES and t not in {brand, "mg", "ml", "g", "gm"} and not t.isdigit()]
    product_family = " ".join(family_tokens[:5]).strip()
    is_med_q = bool(active or form in MEDICINE_FORMS)
    is_cos_q = bool((brand in COSMETIC_BRANDS) or cosmetic_type or use_case or skin_type)
    has_specific = False
    if brand and (len(non_brand_strong) >= 1 or cosmetic_type or strength_values):
        has_specific = True
    elif active and (form or strength_values or len(non_brand_strong) >= 1):
        has_specific = True
    elif len(non_brand_strong) >= 2:
        has_specific = True
    return QuerySlots(
        cleaned_text=cleaned,
        brand=brand,
        product_family=product_family,
        active_ingredient=active,
        form=form,
        strength=next(iter(strength_values), ""),
        strength_values=strength_values,
        size=next(iter(size_values), ""),
        size_values=size_values,
        cosmetic_type=cosmetic_type,
        use_case=use_case,
        skin_type=skin_type,
        is_medicine_query=is_med_q,
        is_cosmetic_query=is_cos_q,
        is_specific_named_product=has_specific,
        weak_tokens=weak,
        strong_tokens=strong,
        normalized_query=cleaned,
        meaningful_tokens=toks,
    )


def _unique(records: Iterable[ProductRecord]) -> List[ProductRecord]:
    out, seen = [], set()
    for r in records:
        key = r.id or r.normalized_name
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _type_compatible(slots: QuerySlots, rec: ProductRecord) -> bool:
    qtype = slots.cosmetic_type or slots.form
    if not qtype:
        return True
    rtype = rec.cosmetic_type or rec.form
    if not rtype:
        return True
    if qtype == rtype:
        return True
    if qtype == "moisturizer" and rtype in {"moisturizer", "lotion", "cream", "balm"}:
        return True
    if qtype in TYPE_CONFLICTS and rtype in TYPE_CONFLICTS[qtype]:
        return False
    if qtype in MEDICINE_FORMS or rtype in MEDICINE_FORMS:
        return qtype == rtype
    if qtype in COSMETIC_TYPES and rtype in COSMETIC_TYPES:
        return False
    return True


def _has_type_conflict(slots: QuerySlots, rec: ProductRecord) -> bool:
    return not _type_compatible(slots, rec)


def _token_coverage(slots: QuerySlots, rec: ProductRecord) -> float:
    strong = set(slots.strong_tokens)
    if not strong:
        return 0.0
    rec_tokens = rec.tokens
    hits = 0.0
    for t in strong:
        if t in rec_tokens:
            hits += 1.0
        else:
            best = max((fuzz.ratio(t, rt) / 100 for rt in rec_tokens if abs(len(t) - len(rt)) <= 3), default=0.0)
            if best >= 0.88:
                hits += best * 0.85
    return hits / max(len(strong), 1)


def _score_within_scope(slots: QuerySlots, rec: ProductRecord) -> float:
    if _has_type_conflict(slots, rec):
        return 0.0
    score = 0.0
    score += _token_coverage(slots, rec) * 0.55
    score += (fuzz.token_set_ratio(slots.cleaned_text, rec.identity) / 100.0) * 0.25
    if slots.cleaned_text and (slots.cleaned_text in rec.identity or rec.normalized_name in slots.cleaned_text):
        score += 0.15
    if slots.brand and rec.brand == slots.brand:
        score += 0.10
    if slots.strength_values:
        rec_strengths = extract_strength_values(rec.strength) | extract_strength_values(rec.identity)
        if rec_strengths and slots.strength_values & rec_strengths:
            score += 0.08
        elif rec_strengths:
            score -= 0.20
    return max(0.0, min(score, 1.0))


def _exact_candidates(slots: QuerySlots, ci: CatalogIndex) -> List[ProductRecord]:
    q = slots.cleaned_text
    hits: List[ProductRecord] = []
    # Generic type/weak words like "cleanser" or "lotion" must not exact-match
    # an alias and select a random product. Barcode/code lookup remains allowed.
    if q not in WEAK_TOKENS and q not in ALL_TYPES:
        hits.extend(ci.exact_name_index.get(q, []))
        hits.extend(ci.alias_index.get(q, []))
    hits.extend(ci.barcode_index.get(q, []))
    return _unique([h for h in hits if not _has_type_conflict(slots, h)])


def _phrase_candidates(slots: QuerySlots, records: List[ProductRecord]) -> List[ProductRecord]:
    q = slots.cleaned_text
    if not q or not slots.strong_tokens:
        return []
    hits = []
    for rec in records:
        if _has_type_conflict(slots, rec):
            continue
        if q in rec.identity or rec.normalized_name in q:
            # require product-specific words, not just skin/face/cream.
            if len(slots.strong_tokens & rec.tokens) >= 1 or slots.brand or slots.strength_values:
                hits.append(rec)
    return _unique(hits)


def _same_family_scope(slots: QuerySlots, records: List[ProductRecord]) -> List[ProductRecord]:
    scoped = []
    family_tokens = set(tokenize(slots.product_family)) - WEAK_TOKENS
    for rec in records:
        if slots.brand and rec.brand and rec.brand != slots.brand:
            continue
        if slots.active_ingredient and slots.active_ingredient not in rec.identity:
            continue
        if _has_type_conflict(slots, rec):
            continue
        if slots.brand and not family_tokens:
            scoped.append(rec)
            continue
        if family_tokens:
            if family_tokens & (rec.tokens - WEAK_TOKENS):
                scoped.append(rec)
                continue
            if fuzz.token_set_ratio(" ".join(family_tokens), rec.product_family or rec.normalized_name) >= 88:
                scoped.append(rec)
    return _unique(scoped)


def _variant_sets(records: Sequence[ProductRecord]) -> Tuple[Set[str], Set[str], Set[str]]:
    forms = {r.form for r in records if r.form}
    strengths: Set[str] = set()
    sizes: Set[str] = set()
    for r in records:
        strengths.update(extract_strength_values(r.strength) | extract_strength_values(r.identity))
        sizes.update(extract_size_values(r.size) | extract_size_values(r.identity))
    return forms, strengths, sizes


def _ask(question: str, options: List[ProductRecord], slots: QuerySlots, kind: str, reason: str) -> MatchDecision:
    return MatchDecision(
        decision_type=DecisionType.ASK_CLARIFICATION,
        confidence=0.0,
        clarification_options=[r.raw for r in _unique(options)[:12]],
        clarification_type=kind,
        question=question,
        reason=reason,
        query_slots=slots,
    )


def _availability_decision(rec: ProductRecord, slots: QuerySlots, ci: CatalogIndex) -> MatchDecision:
    if _availability_ok(rec.availability):
        return MatchDecision(DecisionType.EXACT_MATCH, confidence=1.0, product=rec.raw, product_record=rec, reason="v3_exact_available", query_slots=slots)
    if rec.is_cosmetic:
        alts = cosmetic_alternatives(rec, slots, ci.records)
        if alts:
            return MatchDecision(DecisionType.COSMETIC_ALTERNATIVES, confidence=0.95, product=rec.raw, alternatives=[a.raw for a in alts], reason="v3_cosmetic_known_unavailable", query_slots=slots)
    return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.95, product=rec.raw, product_record=rec, reason="v3_known_unavailable", query_slots=slots)


def _resolve_candidates(candidates: List[ProductRecord], slots: QuerySlots, ci: CatalogIndex, source: str) -> MatchDecision:
    candidates = _unique([c for c in candidates if not _has_type_conflict(slots, c)])
    if not candidates:
        return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.0, reason=f"v3_no_candidates_{source}", query_slots=slots)
    forms, strengths, sizes = _variant_sets(candidates)
    medicines = [c for c in candidates if c.is_medicine]
    cosmetics = [c for c in candidates if c.is_cosmetic]
    if len(candidates) > 1:
        if medicines:
            if not slots.form and len(forms) > 1:
                return _ask("متوفر أكثر من شكل. الرجاء اختيار الشكل أو المنتج المطلوب:", candidates, slots, "form", "v3_missing_medicine_form")
            if slots.form:
                candidates = [c for c in candidates if _type_compatible(slots, c)] or candidates
                _f, strengths2, _s = _variant_sets(candidates)
                if not slots.strength_values and len(strengths2) > 1:
                    return _ask("يوجد من هذا المنتج أكثر من جرعة. اختر الجرعة المطلوبة أو اكتب رقمها:", candidates, slots, "strength", "v3_missing_medicine_strength")
            if slots.strength_values:
                strength_hits = [c for c in candidates if slots.strength_values & (extract_strength_values(c.strength) | extract_strength_values(c.identity))]
                hit_forms = {c.form for c in strength_hits if c.form}
                if len(strength_hits) > 1 and len(hit_forms) > 1 and not slots.form:
                    return _ask("هذه الجرعة موجودة بأكثر من شكل. الرجاء اختيار الشكل:", strength_hits, slots, "form", "v3_same_strength_multiple_forms")
                if len(strength_hits) == 1:
                    return _availability_decision(strength_hits[0], slots, ci)
        if cosmetics:
            if not slots.cosmetic_type and len({c.cosmetic_type or c.form for c in candidates if c.cosmetic_type or c.form}) > 1:
                return _ask("يوجد أكثر من نوع. الرجاء اختيار المنتج المطلوب:", candidates, slots, "product", "v3_missing_cosmetic_type")
            if slots.cosmetic_type:
                candidates = [c for c in candidates if _type_compatible(slots, c)] or candidates
                if len(candidates) > 1 and not slots.size_values:
                    _, _, sizes2 = _variant_sets(candidates)
                    if len(sizes2) > 1:
                        return _ask("متوفر أكثر من حجم. الرجاء اختيار الحجم المطلوب:", candidates, slots, "size", "v3_missing_size")
        ranked = sorted(((c, _score_within_scope(slots, c)) for c in candidates), key=lambda p: p[1], reverse=True)
        best, best_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_score >= 0.96 and best_score - second_score >= 0.08:
            return _availability_decision(best, slots, ci)
        return _ask("يوجد أكثر من احتمال. الرجاء اختيار المطلوب:", [r for r, _ in ranked[:10]], slots, "product", "v3_ambiguous_candidates")
    return _availability_decision(candidates[0], slots, ci)


def _weak_or_empty(slots: QuerySlots) -> bool:
    if not slots.cleaned_text:
        return True
    if slots.is_specific_named_product:
        return False
    if slots.strength_values and not (slots.brand or slots.active_ingredient or slots.product_family):
        return True
    # type-only or weak-only must not select a random product
    useful = set(slots.strong_tokens)
    if slots.brand:
        useful.discard(slots.brand)
    if not useful and not slots.strength_values and not slots.active_ingredient:
        return True
    if slots.cleaned_text in COSMETIC_TYPES or slots.cleaned_text in WEAK_TOKENS:
        return True
    return False


def cosmetic_alternatives(target: ProductRecord, slots: QuerySlots, records: List[ProductRecord], limit: int = 3) -> List[ProductRecord]:
    target_type = target.cosmetic_type or target.form or slots.cosmetic_type
    if target_type not in COSMETIC_TYPES:
        return []
    # Strict type. Only moisturizer may be broadened to lotion/cream/balm; cleanser/serum/lotion/sunscreen stay exact.
    allowed = {target_type}
    if target_type == "moisturizer":
        allowed = {"moisturizer", "lotion", "cream", "balm"}
    if target_type in {"cleanser", "serum", "lotion", "sunscreen", "shampoo"}:
        allowed = {target_type}
    scored: List[Tuple[float, ProductRecord]] = []
    for rec in records:
        if rec.id == target.id or not rec.is_cosmetic or not _availability_ok(rec.availability):
            continue
        rtype = rec.cosmetic_type or rec.form
        if rtype not in allowed:
            continue
        # Must share type and either use_case, skin_type, same brand, or close product family. Do not use generic face/skin/size tokens.
        strong_relation = False
        if target.brand and rec.brand == target.brand:
            strong_relation = True
        if target.use_case and rec.use_case == target.use_case:
            strong_relation = True
        if target.skin_type and rec.skin_type == target.skin_type:
            strong_relation = True
        if target.product_family and fuzz.token_set_ratio(target.product_family, rec.product_family or rec.normalized_name) >= 75:
            strong_relation = True
        if not strong_relation:
            continue
        score = 50.0
        if rtype == target_type:
            score += 30
        if target.use_case and rec.use_case == target.use_case:
            score += 20
        if target.skin_type and rec.skin_type == target.skin_type:
            score += 15
        if target.brand and rec.brand == target.brand:
            score += 10
        score += fuzz.token_set_ratio(target.normalized_name, rec.normalized_name) / 100.0 * 10
        scored.append((score, rec))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [r for _, r in scored[:limit]]


def _strict_missing_cosmetic_alternatives(slots: QuerySlots, records: List[ProductRecord], limit: int = 3) -> List[ProductRecord]:
    # Missing specific cosmetic products may offer alternatives only when the type
    # is strong and exact. Cleanser/sunscreen are safe strict buckets. Balm/cream/lotion
    # are not broadened here because they easily create wrong substitutes.
    target_type = slots.cosmetic_type or slots.form
    if target_type not in {"cleanser", "sunscreen", "shampoo", "serum"}:
        return []
    out = []
    for rec in records:
        if not rec.is_cosmetic or not _availability_ok(rec.availability):
            continue
        rtype = rec.cosmetic_type or rec.form
        if rtype != target_type:
            continue
        if target_type == "cleanser" and any(bad in rec.identity for bad in ["body", "mouth", "dental", "oral", "hair", "baby", "shampoo"]):
            continue
        if slots.use_case and rec.use_case and rec.use_case != slots.use_case:
            continue
        if slots.skin_type and rec.skin_type and rec.skin_type != slots.skin_type:
            continue
        out.append(rec)
    scored = sorted(out, key=lambda r: (r.brand == slots.brand, fuzz.token_set_ratio(slots.cleaned_text, r.identity)), reverse=True)
    return scored[:limit]


def _not_available(slots: QuerySlots, reason: str = "v3_not_available", records: Optional[List[ProductRecord]] = None) -> MatchDecision:
    if records and slots.is_cosmetic_query and (slots.cosmetic_type or slots.form):
        alts = _strict_missing_cosmetic_alternatives(slots, records)
        if alts:
            return MatchDecision(DecisionType.COSMETIC_ALTERNATIVES, confidence=0.82, alternatives=[a.raw for a in alts], reason=f"{reason}_strict_cosmetic_alternatives", query_slots=slots)
    return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.0, reason=reason, query_slots=slots)


def resolve_product_query_from_index(query: str, ci: CatalogIndex) -> MatchDecision:
    """Resolve using a prebuilt CatalogIndex.

    This is the production path used by PriceBot. It avoids rebuilding the
    4,991-product index and the huge catalog cache key on every customer
    message, which was the cause of timeout_fallback replies in v15.
    """
    slots = extract_query_slots(query)
    if not slots.cleaned_text or not ci.records:
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v3_empty_query_or_catalog", query_slots=slots)

    # A/B/C: exact name, exact alias, exact barcode/code first.
    exact = _exact_candidates(slots, ci)
    if exact:
        return _resolve_candidates(exact, slots, ci, "exact")

    # Numeric/code-like query that was not exact must not be fuzzy matched.
    if re.fullmatch(r"[a-z]*\d+[a-z\d]*", slots.cleaned_text):
        return _not_available(slots, "v3_code_like_not_found", ci.records)

    # Weak/generic/brand-only query: ask within same brand/type if possible; otherwise low confidence/not available.
    if _weak_or_empty(slots):
        if slots.brand and slots.brand in ci.brand_index:
            return _ask("يرجى تحديد المنتج المطلوب من هذه الشركة:", ci.brand_index[slots.brand][:12], slots, "product", "v3_brand_only")
        if slots.cosmetic_type:
            same_type = [r for r in ci.records if r.is_cosmetic and (r.cosmetic_type or r.form) == slots.cosmetic_type]
            if same_type:
                return _ask("يوجد أكثر من نوع. اكتب اسم الشركة أو اختر المنتج:", same_type[:12], slots, "product", "v3_type_only")
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v3_weak_query", query_slots=slots)

    # D: full phrase contains.
    phrase = _phrase_candidates(slots, ci.records)
    if phrase:
        return _resolve_candidates(phrase, slots, ci, "phrase")

    # Specific named product guard: restrict to same brand/family only. If not found, NOT_AVAILABLE.
    if slots.is_specific_named_product:
        scoped = _same_family_scope(slots, ci.records)
        if scoped:
            # If the user provided form/strength/active ingredient inside a known family,
            # let the variant resolver decide instead of forcing text fuzzy score.
            if slots.form or slots.strength_values or slots.active_ingredient:
                return _resolve_candidates(scoped, slots, ci, "specific_scope_variant")
            # Strict fuzzy only inside same brand/family/type.
            ranked = sorted(((r, _score_within_scope(slots, r)) for r in scoped), key=lambda p: p[1], reverse=True)
            strong = [r for r, s in ranked if s >= 0.86]
            if strong:
                return _resolve_candidates(strong, slots, ci, "specific_scope")
            # same brand exists but product line does not: unavailable, not random alternatives.
            return _not_available(slots, "v3_specific_product_not_found_in_scope", ci.records)
        return _not_available(slots, "v3_specific_product_no_scope", ci.records)

    # Medicine family resolver: never give price if form/strength ambiguity remains.
    med_scope = _same_family_scope(slots, [r for r in ci.records if r.is_medicine])
    if med_scope:
        return _resolve_candidates(med_scope, slots, ci, "medicine_variant")

    # Structured cosmetic match: same brand/type/use only.
    cos_scope = []
    for r in ci.records:
        if not r.is_cosmetic or _has_type_conflict(slots, r):
            continue
        if slots.brand and r.brand != slots.brand:
            continue
        if slots.cosmetic_type and (r.cosmetic_type or r.form) != slots.cosmetic_type:
            continue
        if slots.use_case and r.use_case and r.use_case != slots.use_case and not slots.brand:
            continue
        if slots.strong_tokens & (r.tokens - WEAK_TOKENS):
            cos_scope.append(r)
    if cos_scope:
        return _resolve_candidates(cos_scope, slots, ci, "cosmetic_structured")

    # No global fuzzy. Professional bot asks/declares unavailable instead of guessing.
    return _not_available(slots, "v3_no_safe_match", ci.records)


def resolve_product_query(query: str, catalog: Sequence[Dict[str, Any]]) -> MatchDecision:
    return resolve_product_query_from_index(query, build_catalog_index(catalog))


def resolve_image_extraction(ai_data: Dict[str, Any], catalog: Sequence[Dict[str, Any]]) -> MatchDecision:
    clarity = str(ai_data.get("clarity") or "").strip().lower()
    try:
        confidence = float(ai_data.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    if clarity == "bad" or confidence < 0.75:
        return MatchDecision(DecisionType.IMAGE_UNCLEAR, confidence=confidence, reason="v3_image_unclear")
    query_parts = [str(ai_data.get(k) or "").strip() for k in ["brand", "product_name", "type", "product_type", "form", "strength", "size"]]
    query = " ".join(x for x in query_parts if x)
    slots = extract_query_slots(query)
    # Generic image data like only "cream" or "50ml" must not show products.
    if not query or (not slots.brand and not slots.product_family and not slots.active_ingredient and not slots.strong_tokens):
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=confidence, reason="v3_image_low_information", query_slots=slots)
    if not slots.brand and not slots.product_family and slots.cosmetic_type:
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=confidence, reason="v3_image_generic_type_only", query_slots=slots)
    decision = resolve_product_query(query, catalog)
    decision.confidence = max(decision.confidence, confidence if decision.decision_type != DecisionType.NOT_AVAILABLE else decision.confidence)
    return decision


def generate_catalog_quality_report(catalog: Sequence[Dict[str, Any]], output_path: str = "catalog_quality_report.csv") -> str:
    ci = build_catalog_index(catalog)
    rows = []
    dupes: Dict[str, int] = {}
    for r in ci.records:
        dupes[r.normalized_name] = dupes.get(r.normalized_name, 0) + 1
    for r in ci.records:
        issues = []
        if not r.brand:
            issues.append("missing_brand")
        if not r.form:
            issues.append("missing_form")
        if r.is_medicine and not r.strength:
            issues.append("missing_strength")
        if r.is_cosmetic and not r.cosmetic_type:
            issues.append("missing_cosmetic_type")
        if not r.aliases and not r.image_keywords:
            issues.append("weak_aliases")
        if dupes.get(r.normalized_name, 0) > 1:
            issues.append("duplicate_normalized_name")
        if not r.is_medicine and not r.is_cosmetic:
            issues.append("unclassified")
        rows.append({
            "id": r.id,
            "name": r.original_name,
            "brand": r.brand,
            "form": r.form,
            "strength": r.strength,
            "cosmetic_type": r.cosmetic_type,
            "is_medicine": r.is_medicine,
            "is_cosmetic": r.is_cosmetic,
            "issues": ";".join(issues),
        })
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "name", "brand", "form", "strength", "cosmetic_type", "is_medicine", "is_cosmetic", "issues"])
        writer.writeheader()
        writer.writerows(rows)
    return output_path
