"""
PriceBot matcher_v2.py
Production-grade safe product resolver.

Core rule: this module never decides price/availability from AI or memory.
It only resolves customer text against the local catalog passed to resolve_product_query().
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:
    from rapidfuzz import fuzz
except Exception:  # conservative fallback
    import difflib

    class _FuzzFallback:
        @staticmethod
        def ratio(a, b):
            return difflib.SequenceMatcher(None, str(a or ""), str(b or "")).ratio() * 100

        @staticmethod
        def partial_ratio(a, b):
            a = str(a or "")
            b = str(b or "")
            if not a or not b:
                return 0
            short, long = (a, b) if len(a) <= len(b) else (b, a)
            if short in long:
                return 100
            return max(
                difflib.SequenceMatcher(None, short, long[i:i + len(short)]).ratio() * 100
                for i in range(max(len(long) - len(short) + 1, 1))
            )

        @staticmethod
        def token_set_ratio(a, b):
            sa = set(str(a or "").split())
            sb = set(str(b or "").split())
            if not sa or not sb:
                return 0
            inter = sa & sb
            return (2 * len(inter) / (len(sa) + len(sb))) * 100

    fuzz = _FuzzFallback()


class DecisionType(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    COSMETIC_ALTERNATIVES = "COSMETIC_ALTERNATIVES"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    IMAGE_UNCLEAR = "IMAGE_UNCLEAR"


@dataclass
class ProductRecord:
    product_id: str
    original_name: str
    normalized_name: str
    brand: str = ""
    category: str = ""
    is_medicine: bool = False
    is_cosmetic: bool = False
    active_ingredient: str = ""
    product_family: str = ""
    form: str = ""
    route: str = ""
    strength: str = ""
    size: str = ""
    concentration: str = ""
    skin_type: str = ""
    use_case: str = ""
    cosmetic_type: str = ""
    aliases: Set[str] = field(default_factory=set)
    keywords: Set[str] = field(default_factory=set)
    price: str = ""
    availability: str = "متوفر"
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def identity(self) -> str:
        parts = [
            self.normalized_name, self.brand, self.category, self.active_ingredient,
            self.product_family, self.form, self.strength, self.size, self.concentration,
            self.skin_type, self.use_case, self.cosmetic_type,
            " ".join(sorted(self.aliases)), " ".join(sorted(self.keywords)),
        ]
        return normalize_product_text(" ".join(p for p in parts if p))

    @property
    def tokens(self) -> Set[str]:
        return set(tokenize(self.identity))


@dataclass
class QuerySlots:
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
    has_specific_variant: bool = False
    normalized_query: str = ""
    meaningful_tokens: Set[str] = field(default_factory=set)


@dataclass
class MatchDecision:
    decision_type: DecisionType
    confidence: float = 0.0
    product: Optional[Dict[str, Any]] = None
    product_record: Optional[ProductRecord] = None
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    clarification_options: List[Dict[str, Any]] = field(default_factory=list)
    clarification_type: str = ""
    question: str = ""
    reason: str = ""
    query_slots: Optional[QuerySlots] = None


ARABIC_MAP = {
    "أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ٱ": "ا",
    "ڤ": "ف", "ک": "ك", "ی": "ي", "گ": "ك", "چ": "ج", "پ": "ب",
}
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

STATIC_SYNONYMS = {
    # product/brand spelling
    "cera ve": "cerave", "cera-ve": "cerave", "ceravé": "cerave", "crea ve": "cerave",
    "creave": "cerave", "cearave": "cerave", "cearve": "cerave", "cera v": "cerave",
    "سيرافي": "cerave", "سيرا في": "cerave", "سيراڤي": "cerave",
    "la roche posay": "laroche", "la roche": "laroche", "laroche posay": "laroche",
    "لاروش بوزيه": "laroche", "لاروش": "laroche", "لاروشي": "laroche",
    "ايفاكلار": "effaclar", "إيفاكلار": "effaclar",
    "بيوديرما": "bioderma", "بايوديرما": "bioderma", "بيودرما": "bioderma", "بايودرما": "bioderma",
    "فوتوديرم": "photoderm", "اكوا فلويد": "aquafluide", "اكو فلويد": "aquafluide",
    "ذا اورديناري": "theordinary", "اورديناري": "theordinary", "اوريدناري": "theordinary", "the ordinary": "theordinary",
    # medicines
    "بنادول": "panadol", "بندول": "panadol", "بانادول": "panadol",
    "ادول": "adol", "أدول": "adol", "باراسيتامول": "paracetamol", "براسيتامول": "paracetamol",
    "فلاجيل": "flagyl", "فلجيل": "flagyl", "فلاجل": "flagyl", "flgyl": "flagyl",
    "اموكلان": "amoclan", "اوموكلان": "amoclan", "اموكلين": "amoclan",
    "اوجمنتين": "augmentin", "اوقمنتين": "augmentin",
    "كونجيستال": "congestal", "كونجستال": "congestal",
    # forms/types
    "tab": "tablet", "tabs": "tablet", "tablet": "tablet", "tablets": "tablet", "حبوب": "tablet", "اقراص": "tablet", "أقراص": "tablet",
    "cap": "capsule", "caps": "capsule", "capsule": "capsule", "capsules": "capsule", "كبسول": "capsule", "كبسولات": "capsule",
    "syrup": "syrup", "syrop": "syrup", "susp": "syrup", "suspension": "syrup", "شراب": "syrup", "معلق": "syrup",
    "supp": "suppository", "suppository": "suppository", "suppositories": "suppository", "تحاميل": "suppository", "لبوس": "suppository",
    "inj": "injection", "injection": "injection", "injections": "injection", "حقن": "injection", "حقنه": "injection",
    "drop": "drops", "drops": "drops", "قطره": "drops", "قطرة": "drops",
    "spray": "spray", "بخاخ": "spray",
    "cleanser": "cleanser", "face wash": "cleanser", "face cleanser": "cleanser", "wash": "cleanser", "غسول وجه": "cleanser", "غسول": "cleanser", "منظف": "cleanser",
    "lotion": "lotion", "لوشن": "lotion",
    "serum": "serum", "سيروم": "serum",
    "cream": "cream", "كريم": "cream",
    "sunscreen": "sunscreen", "sun screen": "sunscreen", "sunblock": "sunscreen", "sun block": "sunscreen", "واقي شمس": "sunscreen", "واقي": "sunscreen", "سن بلوك": "sunscreen",
    "shampoo": "shampoo", "شامبو": "shampoo",
    "moisturising": "moisturizing", "moisturiser": "moisturizer", "مرطب": "moisturizer", "ترطيب": "moisturizer",
    # use cases / skin
    "بشره دهنيه": "oily skin", "بشرة دهنية": "oily skin", "البشره الدهنيه": "oily skin", "البشرة الدهنية": "oily skin",
    "بشره جافه": "dry skin", "بشرة جافة": "dry skin", "حساسه": "sensitive skin", "حساسة": "sensitive skin",
    "حب الشباب": "acne", "حبووب": "acne", "تصبغات": "pigmentation",
}

# Keep multi-word replacements first.
SYNONYM_RULES = sorted(
    [(normalize_src, normalize_dst) for normalize_src, normalize_dst in []], key=lambda x: 0
)

COSMETIC_BRANDS = {
    "cerave", "laroche", "bioderma", "vichy", "eucerin", "acm", "svr", "uriage", "avene",
    "cetaphil", "theordinary", "ordinary", "isispharma", "isis", "mustela", "nuxe", "babaria",
}
MEDICINE_FAMILIES = {
    "panadol", "adol", "paracetamol", "flagyl", "metronidazole", "amoclan", "augmentin", "congestal",
    "zyrtec", "telfast", "claritine", "voltaren", "cataflam", "brufen", "omeprazole", "concor", "glucophage",
}
BRANDS = COSMETIC_BRANDS | MEDICINE_FAMILIES

FORM_WORDS = {
    "tablet": {"tablet"}, "capsule": {"capsule"}, "syrup": {"syrup"}, "suppository": {"suppository"},
    "injection": {"injection"}, "drops": {"drops"}, "spray": {"spray"},
    "cream": {"cream"}, "ointment": {"ointment", "مرهم"}, "gel": {"gel"}, "lotion": {"lotion"},
    "cleanser": {"cleanser"}, "serum": {"serum"}, "sunscreen": {"sunscreen"}, "shampoo": {"shampoo"}, "balm": {"balm", "baume"}, "mask": {"mask"},
}
MEDICINE_FORMS = {"tablet", "capsule", "syrup", "suppository", "injection", "drops", "spray"}
COSMETIC_TYPES = {"cleanser", "moisturizer", "lotion", "cream", "serum", "sunscreen", "toner", "gel", "oil", "shampoo", "balm", "mask"}
STRICT_TYPES = MEDICINE_FORMS | COSMETIC_TYPES | {"ointment"}

USE_CASE_WORDS = {
    "acne": {"acne", "anti acne", "حب", "حبوب", "salicylic", "effaclar", "normaderm", "sebium", "keracnyl"},
    "dry_skin": {"dry skin", "جاف", "جافه", "hydrating", "moisturizing", "moisturizer", "hydratant"},
    "oily_skin": {"oily skin", "دهنية", "دهنيه", "oil control"},
    "sensitive_skin": {"sensitive skin", "حساسه", "حساسة", "sensibio", "toleriane"},
    "hydration": {"hydrating", "hydration", "moisturizing", "ترطيب", "مرطب"},
    "anti_dandruff": {"dandruff", "قشره", "قشرة", "anti dandruff"},
    "sun_protection": {"sunscreen", "spf", "sun protection", "واقي"},
    "barrier_repair": {"barrier", "repair", "cicaplast", "cicalfate", "baume", "balm"},
    "anti_pigmentation": {"pigmentation", "depigment", "depiwhite", "تصبغ", "تصبغات"},
}
SKIN_TYPE_WORDS = {
    "oily_skin": {"oily skin", "دهنية", "دهنيه"},
    "dry_skin": {"dry skin", "جاف", "جافه"},
    "sensitive_skin": {"sensitive skin", "حساس", "حساسه", "حساسة"},
    "normal_skin": {"normal skin"},
}
AREA_WORDS = {
    "face": {"face", "visage", "وجه", "بشره", "بشرة", "skin", "acne", "oily skin", "dry skin"},
    "body": {"body", "corps", "جسم"},
    "mouth": {"mouth", "oral", "dental", "فم", "اسنان", "أسنان"},
    "hair": {"hair", "cheveux", "شعر", "scalp", "فروة"},
    "baby": {"baby", "enfant", "اطفال", "أطفال", "بيبي", "رضع"},
}

IMPORTANT_WORDS = {
    "baume", "balm", "serum", "cleanser", "lotion", "cream", "foaming", "hydrating", "daily", "moisturizing", "moisturising",
    "gel", "oil", "sunscreen", "shampoo", "toner", "syrup", "tablet", "capsule", "suppository", "injection", "drops", "spray",
}
WEAK_WORDS = {
    "cerave", "vichy", "bioderma", "eucerin", "acm", "svr", "uriage", "avene", "laroche", "panadol", "augmentin", "flagyl", "flgyl",
    "lotion", "cream", "serum", "gel", "skin", "daily", "hydrating", "moisturizing", "cleanser",
}
STOPWORDS = {
    "متوفر", "عندكم", "موجود", "هل", "يوجد", "نبي", "ابي", "أبي", "اريد", "أريد", "بالله", "لو", "سمحت", "من", "فضلك",
    "كم", "سعر", "بكم", "قداش", "في", "فيه", "please", "price", "available", "do", "you", "have", "with", "and", "the", "for",
}

STRENGTH_RE = re.compile(r"(?<!\w)(\d+(?:[\.,]\d+)?)(?:\s*(mg|mcg|g|ml|iu|unit|units|%|مجم|ملجم|مل|جم|وحدة))?", re.I)
SIZE_RE = re.compile(r"(?<!\w)(\d+(?:[\.,]\d+)?)(?:\s*(ml|g|gm|kg|l|oz|fl oz|مل|جم))", re.I)


def _normalize_no_syn(text: Any) -> str:
    value = str(text or "").strip().lower()
    for src, dst in ARABIC_MAP.items():
        value = value.replace(src, dst)
    value = value.translate(ARABIC_DIGITS)
    value = value.replace("ـ", "")
    value = re.sub(r"[\u064b-\u065f]", "", value)
    value = re.sub(r"(.)\1{2,}", r"\1\1", value)
    value = re.sub(r"[^\w\s%\.]+", " ", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    return value


_STATIC_RULES_CACHE: Optional[List[Tuple[str, str]]] = None
_SINGLE_RULES_CACHE: Optional[List[Tuple[str, str]]] = None


def _load_dynamic_synonyms() -> Dict[str, str]:
    """Load admin-managed synonyms without making matcher_v2 depend on app startup.

    The import is intentionally local to avoid circular imports. If the database
    is unavailable during tests or startup, matcher_v2 falls back to static rules.
    """
    try:
        import database  # local import: database may import matcher elsewhere
        dynamic = database.load_dynamic_synonyms()
        return {str(k): str(v) for k, v in (dynamic or {}).items() if str(k or "").strip() and str(v or "").strip()}
    except Exception:
        return {}


def _synonym_rules() -> List[Tuple[str, str]]:
    global _STATIC_RULES_CACHE
    if _STATIC_RULES_CACHE is not None:
        return _STATIC_RULES_CACHE
    rules = []
    combined = dict(STATIC_SYNONYMS)
    combined.update(_load_dynamic_synonyms())
    for src, dst in combined.items():
        s = _normalize_no_syn(src)
        d = _normalize_no_syn(dst)
        if s and d:
            rules.append((s, d))
    _STATIC_RULES_CACHE = sorted(rules, key=lambda p: len(p[0]), reverse=True)
    return _STATIC_RULES_CACHE


def _single_synonym_rules() -> List[Tuple[str, str]]:
    global _SINGLE_RULES_CACHE
    if _SINGLE_RULES_CACHE is None:
        _SINGLE_RULES_CACHE = [(s, d) for s, d in _synonym_rules() if " " not in s and len(s) >= 4]
    return _SINGLE_RULES_CACHE


def normalize_product_text(text: Any, fuzzy_synonyms: bool = False) -> str:
    value = _normalize_no_syn(text)
    for src, dst in _synonym_rules():
        if src in value:
            value = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, value)
    # canonical form folds that must not delete important terms
    folds = {
        "moisturising": "moisturizing", "moisturiser": "moisturizer",
        "tabs": "tablet", "tablets": "tablet", "caps": "capsule", "capsules": "capsule",
        "syrop": "syrup", "suppositories": "suppository", "injections": "injection",
        "sun screen": "sunscreen",
    }
    for src, dst in sorted(folds.items(), key=lambda p: len(p[0]), reverse=True):
        if src in value:
            value = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, value)

    if fuzzy_synonyms:
        # Conservative single-token fuzzy synonym pass for common typos: بنادووول -> panadol, Cearave -> cerave.
        single_rules = _single_synonym_rules()
        out = []
        for token in value.split():
            repl = token
            if len(token) >= 4:
                best_score = 0.0
                best_target = ""
                for src, dst in single_rules:
                    if abs(len(token) - len(src)) > 3:
                        continue
                    score = max(fuzz.ratio(token, src) / 100.0, (fuzz.partial_ratio(token, src) / 100.0) * 0.85)
                    if score > best_score:
                        best_score = score
                        best_target = dst
                if best_score >= 0.86 and best_target:
                    repl = best_target
            out.append(repl)
        value = " ".join(out)
    return re.sub(r"\s+", " ", value).strip()


def tokenize(norm_text: str) -> List[str]:
    return [t for t in str(norm_text or "").split() if t and t not in STOPWORDS and len(t) > 1]


def _split_field(value: Any) -> List[str]:
    if value is None:
        return []
    return [part.strip() for part in re.split(r"[,،|;\n/]+", str(value)) if part and part.strip()]


def _field(item: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return str(value)
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
    values: Set[str] = set()
    for number, unit in STRENGTH_RE.findall(norm):
        n = _num(number)
        if not n:
            continue
        unit_norm = normalize_product_text(unit)
        values.add(n)
        if unit_norm:
            values.add(f"{n}{unit_norm}")
    return values


def extract_size_values(text: Any) -> Set[str]:
    norm = normalize_product_text(text)
    values: Set[str] = set()
    for number, unit in SIZE_RE.findall(norm):
        n = _num(number)
        u = normalize_product_text(unit)
        if n:
            values.add(n)
            if u:
                values.add(f"{n}{u}")
    return values


def _contains_phrase(norm_text: str, phrase: str) -> bool:
    phrase = normalize_product_text(phrase)
    if not norm_text or not phrase:
        return False
    return f" {phrase} " in f" {norm_text} "


def _detect_from_map(norm: str, mapping: Dict[str, Set[str]]) -> str:
    for canonical, words in mapping.items():
        for word in sorted(words, key=len, reverse=True):
            if _contains_phrase(norm, word):
                return canonical
    return ""


def _detect_form(norm: str) -> str:
    # order matters: cleanser should win over generic gel if both exist.
    order = ["suppository", "injection", "capsule", "tablet", "syrup", "drops", "spray", "cleanser", "sunscreen", "serum", "shampoo", "lotion", "cream", "ointment", "balm", "gel", "mask"]
    for form in order:
        for word in FORM_WORDS.get(form, {form}):
            if _contains_phrase(norm, word):
                return form
    if _contains_phrase(norm, "moisturizer") or _contains_phrase(norm, "moisturizing"):
        return "moisturizer"
    return ""


def _detect_brand(norm: str) -> str:
    for brand in sorted(BRANDS, key=len, reverse=True):
        if _contains_phrase(norm, brand):
            return brand
    return ""


def _detect_use_case(norm: str) -> str:
    return _detect_from_map(norm, USE_CASE_WORDS)


def _detect_skin_type(norm: str) -> str:
    return _detect_from_map(norm, SKIN_TYPE_WORDS)


def _detect_area(norm: str) -> str:
    return _detect_from_map(norm, AREA_WORDS)


def _availability_ok(value: Any) -> bool:
    norm = normalize_product_text(value or "متوفر")
    if not norm:
        return True
    unavailable = {"غير متوفر", "غير موجود", "نافذ", "نفذ", "ناقص", "out of stock", "unavailable", "no", "0"}
    return not any(u and (u == norm or u in norm) for u in unavailable)


def _route_for_form(form: str) -> str:
    return {
        "tablet": "oral", "capsule": "oral", "syrup": "oral", "drops": "local", "spray": "local",
        "suppository": "rectal", "injection": "parenteral", "cream": "topical", "ointment": "topical", "gel": "topical",
        "lotion": "topical", "cleanser": "topical", "serum": "topical", "sunscreen": "topical", "shampoo": "topical",
    }.get(form, "")


def _meaningful_tokens(norm: str) -> Set[str]:
    blocked = STOPWORDS | {"mg", "ml", "g", "gm", "مجم", "ملجم", "مل", "جم"}
    return {t for t in tokenize(norm) if t not in blocked and len(t) >= 2}


def _product_family_from(norm: str, brand: str, form: str, cosmetic_type: str) -> str:
    toks = list(_meaningful_tokens(norm))
    remove = set(STOPWORDS) | set(STRICT_TYPES) | {"mg", "ml", "g", "gm", "مجم", "ملجم", "مل", "جم"}
    remove.update({"daily", "deep", "with", "for", "skin", "face", "spf", "normal"})
    # Keep medicine/cosmetic family words; remove pure form/type/use-case words.
    family = []
    for tok in toks:
        if tok in remove or tok.isdigit() or tok == form or tok == cosmetic_type:
            continue
        if tok in {"moisturizing", "hydrating", "cleanser", "lotion", "cream", "serum", "sunscreen", "shampoo"}:
            continue
        family.append(tok)
    if brand and brand not in family:
        family.insert(0, brand)
    return " ".join(family[:5]).strip()


def to_product_record(item: Dict[str, Any]) -> ProductRecord:
    name = _field(item, "name", "original_name")
    identity_raw = " ".join(
        _field(item, field) for field in [
            "name", "original_name", "normalized_name", "brand", "company", "category", "category_guess", "form",
            "active_ingredient", "strength", "pack", "size", "concentration", "aliases", "image_ocr_keywords", "ocr_keywords", "keywords",
            "code", "barcode", "sku", "item_code", "product_code", "source_serial",
        ]
    )
    norm_identity = normalize_product_text(identity_raw)
    norm_name = normalize_product_text(_field(item, "normalized_name") or name)
    brand = normalize_product_text(_field(item, "brand", "company")) or _detect_brand(norm_identity)
    explicit_form_norm = normalize_product_text(_field(item, "form"))
    form = _detect_form(explicit_form_norm) or (explicit_form_norm if explicit_form_norm in STRICT_TYPES else "") or _detect_form(norm_identity)
    cosmetic_type = form if form in COSMETIC_TYPES else (_detect_form(explicit_form_norm) or _detect_form(norm_identity))
    if cosmetic_type not in COSMETIC_TYPES:
        cosmetic_type = "moisturizer" if _contains_phrase(norm_identity, "moisturizer") else ""
    active = normalize_product_text(_field(item, "active_ingredient"))
    category = normalize_product_text(_field(item, "category", "category_guess"))
    strength = normalize_product_text(_field(item, "strength"))
    size = normalize_product_text(_field(item, "pack", "size"))
    concentration = normalize_product_text(_field(item, "concentration"))
    skin_type = _detect_skin_type(norm_identity)
    use_case = _detect_use_case(norm_identity)
    family = _product_family_from(norm_identity, brand, form, cosmetic_type)

    aliases = set()
    for field in ["aliases", "image_ocr_keywords", "ocr_keywords", "keywords", "code", "barcode", "sku", "item_code", "product_code", "source_serial", "original_name"]:
        for part in _split_field(item.get(field, "")):
            n = normalize_product_text(part)
            if n:
                aliases.add(n)
    for value in {norm_name, normalize_product_text(name)}:
        if value:
            aliases.add(value)
            parts = value.split()
            if 2 <= len(parts) <= 6:
                aliases.add(" ".join(reversed(parts)))
    if brand and norm_name:
        aliases.add(f"{brand} {norm_name}")
        aliases.add(f"{norm_name} {brand}")

    keywords = set(_meaningful_tokens(norm_identity))
    is_cosmetic = bool(brand in COSMETIC_BRANDS or cosmetic_type in COSMETIC_TYPES or any(w in norm_identity for w in ["skin", "face", "spf", "acne", "بشرة", "بشره", "وجه"]))
    is_medicine = bool(active or form in MEDICINE_FORMS or brand in MEDICINE_FAMILIES or (not is_cosmetic and any(w in norm_identity for w in ["mg", "tablet", "syrup", "capsule", "suppository", "injection"])))
    if is_cosmetic and brand in COSMETIC_BRANDS:
        is_medicine = False

    return ProductRecord(
        product_id=str(item.get("id") or item.get("product_id") or name),
        original_name=name,
        normalized_name=norm_name,
        brand=brand,
        category=category,
        is_medicine=is_medicine,
        is_cosmetic=is_cosmetic,
        active_ingredient=active,
        product_family=family,
        form=form,
        route=_route_for_form(form),
        strength=strength,
        size=size,
        concentration=concentration,
        skin_type=skin_type,
        use_case=use_case,
        cosmetic_type=cosmetic_type,
        aliases=aliases,
        keywords=keywords,
        price=str(item.get("price") or ""),
        availability=str(item.get("available") or item.get("availability") or "متوفر"),
        raw=item,
    )


_CACHE_SIGNATURE: Optional[Tuple[Any, ...]] = None
_CACHE_RECORDS: List[ProductRecord] = []


def _catalog_signature(catalog: Sequence[Dict[str, Any]]) -> Tuple[Any, ...]:
    items = list(catalog or [])
    if not items:
        return (0,)
    # Cheap, stable-enough signature for SQLite product table snapshots.
    first = items[0]
    last = items[-1]
    return (
        len(items),
        str(first.get("id", "")), str(first.get("name", "")), str(first.get("updated_at", "")),
        str(last.get("id", "")), str(last.get("name", "")), str(last.get("updated_at", "")),
    )


def invalidate_cache() -> None:
    global _CACHE_SIGNATURE, _CACHE_RECORDS
    _CACHE_SIGNATURE = None
    _CACHE_RECORDS = []


def refresh_synonym_rules() -> None:
    """Reload static + dynamic synonyms and clear catalog-derived caches.

    Called after /admin/addsynonym so matcher_v2 can use new synonyms without restart.
    """
    global _STATIC_RULES_CACHE, _SINGLE_RULES_CACHE
    _STATIC_RULES_CACHE = None
    _SINGLE_RULES_CACHE = None
    invalidate_cache()


def build_product_records(catalog: Sequence[Dict[str, Any]]) -> List[ProductRecord]:
    return [to_product_record(dict(item)) for item in (catalog or []) if dict(item).get("name") or dict(item).get("original_name")]


def get_product_records(catalog: Sequence[Dict[str, Any]]) -> List[ProductRecord]:
    global _CACHE_SIGNATURE, _CACHE_RECORDS
    sig = _catalog_signature(catalog)
    if _CACHE_SIGNATURE == sig and _CACHE_RECORDS:
        return _CACHE_RECORDS
    _CACHE_RECORDS = build_product_records(catalog)
    _CACHE_SIGNATURE = sig
    return _CACHE_RECORDS


def extract_query_slots(query: str) -> QuerySlots:
    norm_raw = normalize_product_text(query, fuzzy_synonyms=True)
    # Customer request words are not product identity. Keep numbers and product words.
    norm = " ".join(t for t in norm_raw.split() if t not in STOPWORDS)
    form = _detect_form(norm)
    cosmetic_type = form if form in COSMETIC_TYPES else ("moisturizer" if _contains_phrase(norm, "moisturizer") else "")
    brand = _detect_brand(norm)
    active = ""
    if _contains_phrase(norm, "paracetamol"):
        active = "paracetamol"
    elif _contains_phrase(norm, "metronidazole") or _contains_phrase(norm, "flagyl"):
        active = "metronidazole"
    strengths = extract_strength_values(norm)
    sizes = extract_size_values(norm)
    use_case = _detect_use_case(norm)
    skin_type = _detect_skin_type(norm)
    family = _product_family_from(norm, brand, form, cosmetic_type)
    is_cosmetic_query = bool(brand in COSMETIC_BRANDS or cosmetic_type in COSMETIC_TYPES or use_case or skin_type)
    is_medicine_query = bool(active or brand in MEDICINE_FAMILIES or form in MEDICINE_FORMS)
    meaningful = _meaningful_tokens(norm)
    has_specific = bool(form or strengths or sizes or cosmetic_type or use_case or skin_type or len(meaningful - {brand}) >= 2)
    return QuerySlots(
        brand=brand,
        product_family=family,
        active_ingredient=active,
        form=form,
        strength=" ".join(sorted(strengths)),
        strength_values=strengths,
        size=" ".join(sorted(sizes)),
        size_values=sizes,
        cosmetic_type=cosmetic_type,
        use_case=use_case,
        skin_type=skin_type,
        is_medicine_query=is_medicine_query,
        is_cosmetic_query=is_cosmetic_query,
        has_specific_variant=has_specific,
        normalized_query=norm,
        meaningful_tokens=meaningful,
    )


def _is_weak_only(slots: QuerySlots) -> bool:
    toks = {t for t in slots.meaningful_tokens if not t.isdigit()}
    if (slots.strength_values or slots.size_values) and (slots.brand or toks):
        return False
    if not toks:
        return True
    if len(toks) == 1 and next(iter(toks)) in WEAK_WORDS:
        return True
    if toks and toks.issubset(WEAK_WORDS) and not (slots.strength_values or slots.size_values):
        return True
    # brand-only is always weak.
    if slots.brand and toks.issubset({slots.brand}):
        return True
    # category-only is weak.
    if slots.form and toks.issubset({slots.form}):
        return True
    return False


def _type_compatible(slots: QuerySlots, record: ProductRecord) -> bool:
    q_type = slots.form or slots.cosmetic_type
    if not q_type:
        return True
    p_type = record.form or record.cosmetic_type
    if not p_type:
        return True
    if q_type == p_type:
        return True
    # moisturizer is an umbrella; exact lotion/cream/serum rules stay strict.
    if q_type == "moisturizer" and p_type in {"moisturizer", "lotion", "cream", "balm"}:
        return True
    if q_type == "balm" and p_type in {"balm", "cream", "lotion", "moisturizer"}:
        return True
    return False


def _has_type_conflict(slots: QuerySlots, record: ProductRecord) -> bool:
    q_type = slots.form or slots.cosmetic_type
    p_type = record.form or record.cosmetic_type
    if q_type and p_type and not _type_compatible(slots, record):
        return True
    if slots.form == "syrup" and p_type in {"tablet", "capsule", "suppository", "injection"}:
        return True
    if slots.form in {"tablet", "capsule"} and p_type in {"syrup", "suppository", "injection"}:
        return True
    if slots.form == "suppository" and p_type != "suppository" and p_type:
        return True
    if slots.cosmetic_type == "cleanser" and p_type in {"moisturizer", "lotion", "cream", "serum", "sunscreen"}:
        return True
    if slots.cosmetic_type == "serum" and p_type in {"lotion", "cream", "cleanser", "sunscreen"}:
        return True
    if slots.cosmetic_type == "lotion" and p_type in {"serum", "cleanser", "sunscreen"}:
        return True
    if slots.cosmetic_type == "cream" and p_type in {"cleanser", "serum", "sunscreen"}:
        return True
    return False


def _family_overlap(slots: QuerySlots, record: ProductRecord) -> bool:
    q_tokens = slots.meaningful_tokens - {slots.form, slots.cosmetic_type} - slots.strength_values - slots.size_values
    if slots.brand:
        q_tokens.add(slots.brand)
    q_tokens = {t for t in q_tokens if t and t not in STOPWORDS and not t.isdigit()}
    if not q_tokens:
        return False
    rec_text = record.identity
    rec_tokens = record.tokens | set(record.product_family.split())
    # all non-generic family tokens should be present/fuzzy close.
    required = [t for t in q_tokens if t not in STRICT_TYPES and t not in {"mg", "ml", "skin", "face"}]
    if not required:
        return False
    hits = 0
    for token in required:
        if token in rec_tokens or _contains_phrase(rec_text, token):
            hits += 1
        else:
            best = max((fuzz.ratio(token, rt) / 100.0 for rt in rec_tokens if abs(len(token) - len(rt)) <= 3), default=0.0)
            if best >= 0.86:
                hits += 1
    return hits >= max(1, len(required) - 1)


def _score_record(slots: QuerySlots, record: ProductRecord) -> float:
    q = slots.normalized_query
    q_tokens = list(slots.meaningful_tokens)
    if not q_tokens:
        return 0.0
    if _has_type_conflict(slots, record):
        return 0.0
    rec_tokens = record.tokens
    hits = 0.0
    for token in q_tokens:
        if token in rec_tokens:
            hits += 1.0
        else:
            best = max((fuzz.ratio(token, rt) / 100.0 for rt in rec_tokens if abs(len(token) - len(rt)) <= 3), default=0.0)
            partial = max(((fuzz.partial_ratio(token, rt) / 100.0) * 0.85 for rt in rec_tokens if abs(len(token) - len(rt)) <= 5), default=0.0)
            best = max(best, partial)
            if best >= 0.86:
                hits += best * 0.9
            elif len(token) >= 3 and any(token in rt or rt in token for rt in rec_tokens if len(rt) >= 3):
                hits += 0.75
    coverage = hits / max(len(q_tokens), 1)
    token_set = fuzz.token_set_ratio(q, record.identity) / 100.0
    seq_bonus = fuzz.ratio(q, record.normalized_name) / 100.0
    score = coverage * 0.54 + token_set * 0.28 + seq_bonus * 0.18
    if q and (_contains_phrase(record.identity, q) or _contains_phrase(q, record.normalized_name)):
        score += 0.14
    if slots.brand and slots.brand == record.brand:
        score += 0.06
    if slots.form and slots.form == record.form:
        score += 0.08
    if slots.strength_values and slots.strength_values & (extract_strength_values(record.strength) | extract_strength_values(record.identity)):
        score += 0.08
    return min(score, 1.0)


def _exact_match(slots: QuerySlots, records: List[ProductRecord]) -> List[ProductRecord]:
    q = slots.normalized_query
    if not q:
        return []
    barcode_fields = {"code", "barcode", "sku", "item_code", "product_code", "source_serial"}
    exact: List[ProductRecord] = []
    for rec in records:
        if _has_type_conflict(slots, rec):
            continue
        if q == rec.normalized_name:
            exact.append(rec)
            continue
        if q in rec.aliases:
            # Do not let generic aliases such as "cleanser" or "lotion" become exact product matches.
            if q not in WEAK_WORDS and q not in STRICT_TYPES:
                exact.append(rec)
                continue
        for field in barcode_fields:
            value = normalize_product_text(rec.raw.get(field, ""))
            if value and q == value:
                exact.append(rec)
                break
    return _unique_records(exact)


def _full_phrase_contains(slots: QuerySlots, records: List[ProductRecord]) -> List[ProductRecord]:
    q = slots.normalized_query
    if not q or _is_weak_only(slots):
        return []
    hits = []
    q_tokens = slots.meaningful_tokens
    for rec in records:
        if _has_type_conflict(slots, rec):
            continue
        if q in rec.identity or rec.normalized_name in q:
            if len(q_tokens & rec.tokens) >= 2 or slots.brand or slots.strength_values:
                hits.append(rec)
                continue
        important = {t for t in rec.tokens if t not in WEAK_WORDS and t not in STOPWORDS and not t.isdigit()}
        if len(important) >= 2 and important.issubset(q_tokens):
            hits.append(rec)
    return _unique_records(hits)


def _unique_records(records: Iterable[ProductRecord]) -> List[ProductRecord]:
    seen = set()
    out = []
    for rec in records:
        key = rec.product_id or rec.normalized_name
        if key not in seen:
            seen.add(key)
            out.append(rec)
    return out


def _filter_structured(slots: QuerySlots, records: List[ProductRecord]) -> List[ProductRecord]:
    out = []
    for rec in records:
        if _has_type_conflict(slots, rec):
            continue
        if slots.brand and rec.brand and slots.brand != rec.brand:
            # do not reject if family/alias strongly matches; reject cosmetic brand conflicts.
            if slots.brand in COSMETIC_BRANDS or rec.brand in COSMETIC_BRANDS:
                continue
        if slots.strength_values:
            rec_strengths = extract_strength_values(rec.strength) | extract_strength_values(rec.identity)
            if rec_strengths and not (slots.strength_values & rec_strengths):
                continue
        if slots.size_values:
            rec_sizes = extract_size_values(rec.size) | extract_size_values(rec.identity)
            if rec_sizes and not (slots.size_values & rec_sizes):
                continue
        if slots.use_case and rec.use_case and slots.use_case != rec.use_case:
            # use case is helpful, not absolute; keep only if family/brand also good.
            if not (slots.brand and slots.brand == rec.brand):
                continue
        if slots.skin_type and rec.skin_type and slots.skin_type != rec.skin_type:
            if not (slots.brand and slots.brand == rec.brand):
                continue
        if _family_overlap(slots, rec) or slots.brand == rec.brand or (slots.active_ingredient and slots.active_ingredient in rec.identity):
            out.append(rec)
    return _unique_records(out)


def _variant_keys(records: Sequence[ProductRecord]) -> Tuple[Set[str], Set[str], Set[str]]:
    forms = {r.form for r in records if r.form}
    strengths = set()
    sizes = set()
    for rec in records:
        strengths.update(extract_strength_values(rec.strength) | extract_strength_values(rec.identity))
        sizes.update(extract_size_values(rec.size) | extract_size_values(rec.identity))
    return forms, strengths, sizes


def _ask(question: str, options: List[ProductRecord], slots: QuerySlots, kind: str, reason: str) -> MatchDecision:
    return MatchDecision(
        decision_type=DecisionType.ASK_CLARIFICATION,
        confidence=0.0,
        clarification_options=[r.raw for r in _unique_records(options)[:12]],
        clarification_type=kind,
        question=question,
        reason=reason,
        query_slots=slots,
    )


def _variant_resolution(slots: QuerySlots, candidates: List[ProductRecord]) -> Optional[MatchDecision]:
    candidates = _unique_records(candidates)
    if len(candidates) <= 1:
        return None
    forms, strengths, sizes = _variant_keys(candidates)
    # If user omitted form and multiple real forms exist, ask first.
    if not slots.form and len(forms) > 1:
        return _ask("متوفر أكثر من شكل. الرجاء اختيار الشكل أو المنتج المطلوب:", candidates, slots, "form", "missing_form")
    # If form is known, restrict to that form.
    same_form = candidates
    if slots.form:
        same_form = [r for r in candidates if _type_compatible(slots, r)] or candidates
        sf_forms, sf_strengths, sf_sizes = _variant_keys(same_form)
        if not slots.strength_values and len(sf_strengths) > 1 and any(r.is_medicine for r in same_form):
            return _ask("يوجد من هذا المنتج أكثر من جرعة. اختر الجرعة المطلوبة أو اكتب رقمها:", same_form, slots, "strength", "missing_strength")
        if not slots.size_values and len(sf_sizes) > 1 and all(r.is_cosmetic for r in same_form):
            return _ask("متوفر أكثر من حجم. الرجاء اختيار الحجم المطلوب:", same_form, slots, "size", "missing_size")
    # If strength is known but more than one form has same strength, ask form.
    if slots.strength_values:
        strength_hits = [r for r in candidates if slots.strength_values & (extract_strength_values(r.strength) | extract_strength_values(r.identity))]
        if len(strength_hits) > 1:
            hit_forms = {r.form for r in strength_hits if r.form}
            if len(hit_forms) > 1 and not slots.form:
                return _ask("هذه الجرعة موجودة بأكثر من شكل. الرجاء اختيار الشكل:", strength_hits, slots, "form", "same_strength_multiple_forms")
    return None


def _availability_decision(record: ProductRecord, slots: QuerySlots, records: List[ProductRecord]) -> MatchDecision:
    if _availability_ok(record.availability):
        return MatchDecision(DecisionType.EXACT_MATCH, confidence=1.0, product=record.raw, product_record=record, reason="safe_available_match", query_slots=slots)
    if record.is_cosmetic:
        alts = cosmetic_alternatives(record, slots, records)
        if alts:
            return MatchDecision(DecisionType.COSMETIC_ALTERNATIVES, confidence=0.95, product=record.raw, product_record=record, alternatives=[r.raw for r in alts], reason="cosmetic_known_unavailable", query_slots=slots)
    return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.9, product=record.raw, product_record=record, reason="known_product_unavailable", query_slots=slots)


def _choose_safe_best(slots: QuerySlots, candidates: List[ProductRecord], records: List[ProductRecord], source: str) -> MatchDecision:
    candidates = _unique_records([c for c in candidates if not _has_type_conflict(slots, c)])
    if not candidates:
        return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.0, reason=f"no_candidates_{source}", query_slots=slots)
    vr = _variant_resolution(slots, candidates)
    if vr:
        return vr
    ranked = sorted(((r, _score_record(slots, r)) for r in candidates), key=lambda p: p[1], reverse=True)
    best, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    if len(ranked) > 1 and best_score - second_score < 0.06 and best_score < 0.96:
        return _ask("يوجد أكثر من منتج قريب من طلبك. الرجاء اختيار المطلوب:", [r for r, _ in ranked[:8]], slots, "product", "close_candidates")
    if best_score >= 0.92 or source in {"exact", "contains", "structured_single"}:
        decision = _availability_decision(best, slots, records)
        decision.confidence = max(decision.confidence, best_score)
        decision.reason = f"{source}:{decision.reason}"
        return decision
    if 0.75 <= best_score < 0.92:
        return _ask("لم أتأكد من المنتج المقصود. هل تقصد أحد هذه المنتجات؟", [r for r, _ in ranked[:6]], slots, "product", "medium_confidence")
    return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=best_score, reason="low_confidence", query_slots=slots)


def _brand_or_category_options(slots: QuerySlots, records: List[ProductRecord]) -> List[ProductRecord]:
    opts = []
    for rec in records:
        if slots.brand and rec.brand != slots.brand and not _contains_phrase(rec.identity, slots.brand):
            continue
        if slots.form:
            if not (rec.form or rec.cosmetic_type):
                continue
            if not _type_compatible(slots, rec):
                continue
        if slots.cosmetic_type:
            if not (rec.cosmetic_type or rec.form):
                continue
            if not _type_compatible(slots, rec):
                continue
        opts.append(rec)
    return _unique_records(opts)


def _is_same_family_query(slots: QuerySlots, rec: ProductRecord) -> bool:
    if slots.brand and slots.brand == rec.brand:
        return True
    if slots.active_ingredient and slots.active_ingredient in rec.identity:
        return True
    return _family_overlap(slots, rec)


def cosmetic_alternatives(target: Optional[ProductRecord], slots: QuerySlots, records: List[ProductRecord], limit: int = 3) -> List[ProductRecord]:
    target_type = ""
    target_use = ""
    target_skin = ""
    target_brand = ""
    if target:
        target_type = target.cosmetic_type or target.form
        target_use = target.use_case
        target_skin = target.skin_type
        target_brand = target.brand
    target_type = target_type or slots.cosmetic_type or slots.form
    target_use = target_use or slots.use_case
    target_skin = target_skin or slots.skin_type
    target_brand = target_brand or slots.brand
    if not target_type or target_type not in COSMETIC_TYPES:
        return []
    allowed = {target_type}
    if target_type == "moisturizer":
        allowed = {"moisturizer", "lotion", "cream", "balm"}
    # strict exclusions
    if target_type == "cleanser":
        allowed = {"cleanser"}
    if target_type == "serum":
        allowed = {"serum"}
    if target_type == "lotion":
        allowed = {"lotion"}
    if target_type == "sunscreen":
        allowed = {"sunscreen"}
    scored = []
    for rec in records:
        if target and rec.product_id == target.product_id:
            continue
        if not rec.is_cosmetic or not _availability_ok(rec.availability):
            continue
        rtype = rec.cosmetic_type or rec.form
        if rtype not in allowed:
            continue
        # Face cleanser queries must not suggest body wash, baby shampoo, mouth wash, or hair products.
        candidate_area = _detect_area(rec.identity)
        query_area = _detect_area(slots.normalized_query)
        if target_type == "cleanser":
            if not query_area:
                query_area = "face"
            if query_area == "face" and candidate_area in {"body", "mouth", "hair", "baby"}:
                continue
            if candidate_area and query_area and candidate_area != query_area:
                continue
        score = 50.0
        if rtype == target_type:
            score += 30
        if target_use and rec.use_case == target_use:
            score += 18
        if target_skin and rec.skin_type == target_skin:
            score += 16
        if target_brand and rec.brand == target_brand:
            score += 10
        elif target_brand:
            score -= 4
        if target:
            score += (fuzz.token_set_ratio(target.normalized_name, rec.normalized_name) / 100.0) * 12
        if slots.normalized_query:
            score += (fuzz.token_set_ratio(slots.normalized_query, rec.identity) / 100.0) * 10
        scored.append((score, rec))
    scored.sort(key=lambda p: p[0], reverse=True)
    return [rec for _, rec in scored[:limit]]


def _not_available_or_cosmetic_alt(slots: QuerySlots, records: List[ProductRecord]) -> MatchDecision:
    if slots.is_cosmetic_query or slots.cosmetic_type in COSMETIC_TYPES:
        # Virtual target from the query; alternatives only same type/use.
        alts = cosmetic_alternatives(None, slots, records)
        if alts:
            return MatchDecision(DecisionType.COSMETIC_ALTERNATIVES, confidence=0.82, alternatives=[r.raw for r in alts], reason="missing_cosmetic_with_safe_alternatives", query_slots=slots)
    return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.0, reason="not_in_catalog", query_slots=slots)


def resolve_product_query(query: str, catalog: Sequence[Dict[str, Any]]) -> MatchDecision:
    records = get_product_records(catalog)
    slots = extract_query_slots(query)
    if not slots.normalized_query or not records:
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="empty_query_or_catalog", query_slots=slots)

    # A/B/C exact normalized product name, exact alias, or exact barcode/code must run before weak/noise checks.
    exact = _exact_match(slots, records)
    if exact:
        return _choose_safe_best(slots, exact, records, "exact")

    # Code-like query with digits was not found by exact code/name lookup: do not fuzzy-match it into an unrelated product.
    if re.fullmatch(r"[a-z]*\d+[a-z\d]*", slots.normalized_query or ""):
        return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.0, reason="code_like_not_found", query_slots=slots)

    # Brand-only/category-only queries must never select a random product.
    if _is_weak_only(slots):
        opts = _brand_or_category_options(slots, records)
        if opts:
            if len(opts) == 1 and not (slots.form and not slots.brand):
                return _availability_decision(opts[0], slots, records)
            forms, strengths, sizes = _variant_keys(opts)
            if slots.form and not slots.brand:
                question, kind = "يوجد أكثر من نوع. اكتب اسم الشركة أو أرسل صورة المنتج:", "product"
            elif len(forms) > 1:
                question, kind = "متوفر أكثر من شكل. الرجاء اختيار الشكل أو المنتج المطلوب:", "form"
            elif len(strengths) > 1:
                question, kind = "يوجد من هذا المنتج أكثر من جرعة. اختر الجرعة المطلوبة أو اكتب رقمها:", "strength"
            elif len(sizes) > 1:
                question, kind = "متوفر أكثر من حجم. الرجاء اختيار الحجم المطلوب:", "size"
            else:
                question, kind = ("يرجى تحديد المنتج المطلوب:" if not slots.form else "يوجد أكثر من نوع. الرجاء تحديد المنتج أو الشركة:"), "product"
            return _ask(question, opts[:10], slots, kind, "weak_brand_or_category_only")
        return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.0, reason="weak_query_no_options", query_slots=slots)

    # D. full phrase contains
    phrase_hits = _full_phrase_contains(slots, records)
    if phrase_hits:
        return _choose_safe_best(slots, phrase_hits, records, "contains")

    # E. structured slot match
    structured = _filter_structured(slots, records)
    if structured:
        # If it is the same family but variants exist, ask before price.
        return _choose_safe_best(slots, structured, records, "structured_single" if len(structured) == 1 else "structured")

    # Find same-family candidates even when type/strength caused no strict structured match.
    family_candidates = [r for r in records if _is_same_family_query(slots, r)]
    if family_candidates:
        # Requested strength not present: ask/show available strengths instead of guessing.
        if slots.strength_values:
            matching_strength = [r for r in family_candidates if slots.strength_values & (extract_strength_values(r.strength) | extract_strength_values(r.identity))]
            if not matching_strength:
                return _ask("الجرعة المطلوبة غير موجودة ضمن الخيارات المتوفرة. الخيارات الموجودة:", family_candidates, slots, "strength", "strength_not_found")
        if slots.form:
            matching_form = [r for r in family_candidates if _type_compatible(slots, r)]
            if not matching_form:
                if slots.is_cosmetic_query or slots.cosmetic_type in COSMETIC_TYPES:
                    return _not_available_or_cosmetic_alt(slots, records)
                return _ask("الشكل المطلوب غير موجود ضمن الخيارات المتوفرة. الخيارات الموجودة:", family_candidates, slots, "form", "form_not_found")
        return _choose_safe_best(slots, family_candidates, records, "family")

    # F. high confidence fuzzy only.
    ranked = sorted(((r, _score_record(slots, r)) for r in records if not _has_type_conflict(slots, r)), key=lambda p: p[1], reverse=True)
    if ranked:
        best, best_score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        if best_score >= 0.92 and (best_score - second >= 0.06):
            return _availability_decision(best, slots, records)
        if 0.75 <= best_score < 0.92:
            return _ask("لم أتأكد من المنتج المقصود. هل تقصد أحد هذه المنتجات؟", [r for r, _ in ranked[:6]], slots, "product", "medium_fuzzy")

    return _not_available_or_cosmetic_alt(slots, records)


def resolve_image_extraction(ai_data: Dict[str, Any], catalog: Sequence[Dict[str, Any]]) -> MatchDecision:
    clarity = str(ai_data.get("clarity") or "").strip().lower()
    try:
        confidence = float(ai_data.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    if clarity == "bad" or confidence < 0.70:
        return MatchDecision(DecisionType.IMAGE_UNCLEAR, confidence=confidence, reason="image_unclear")
    query = " ".join(
        str(ai_data.get(k) or "") for k in ["brand", "product_name", "type", "product_type", "form", "strength", "size"]
    ).strip()
    if not query:
        return MatchDecision(DecisionType.IMAGE_UNCLEAR, confidence=confidence, reason="image_no_product_query")
    return resolve_product_query(query, catalog)
