"""Product intelligence helpers for PriceBot.

This module is intentionally deterministic: it does not invent stock, price,
or medical advice. It only expands search vocabulary and ranks cosmetic
alternatives using product purpose signals found in the pharmacy database,
customer text, or AI image extraction.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, Set

# Extra spelling/Arabic/brand/line synonyms used before matching.
# Keep values canonical and short so the matcher can compare tokens reliably.
EXTRA_SYNONYMS: Dict[str, str] = {
    # Vichy / lines
    "فيشي": "vichy",
    "ڤيشي": "vichy",
    "فيتشي": "vichy",
    "نورماديرم": "normaderm",
    "نورما ديرم": "normaderm",
    "نورما ديرم فيشي": "normaderm vichy",
    "norma derm": "normaderm",
    "normaderm vichy": "normaderm vichy",
    "daily deep cleansing gel": "deep cleansing gel",
    "cleansing gel": "cleanser",
    "deep cleansing gel": "cleanser",
    "gel nettoyant": "cleanser",
    "gel moussant": "cleanser",
    "غسول جل": "cleanser",
    "جل غسول": "cleanser",
    "غسول فيشي": "vichy cleanser",
    "غسول نورماديرم": "normaderm cleanser",
    "حب الشباب": "acne",
    "الحبوب": "acne",
    "للحبوب": "acne",
    # Bioderma / lines
    "سيبيوم": "sebium",
    "سيبيام": "sebium",
    "سب يوم": "sebium",
    "سينسيبيو": "sensibio",
    "سنسبيو": "sensibio",
    "اتوديرم": "atoderm",
    "اتوديرم": "atoderm",
    "اتوديرم": "atoderm",
    "فوتوديرم": "photoderm",
    # La Roche-Posay / lines
    "لاروش بوزاي": "laroche",
    "لاروش بوزية": "laroche",
    "لاروش بوسي": "laroche",
    "لاروش بوزيه": "laroche",
    "انثيليوس": "anthelios",
    "انتيليوس": "anthelios",
    "انتليوس": "anthelios",
    "توليريان": "toleriane",
    "توليرين": "toleriane",
    "ليبيكار": "lipikar",
    # Uriage / Avene / SVR / Eucerin / ACM common spellings
    "يورياج": "uriage",
    "اورياج": "uriage",
    "هييساك": "hyseac",
    "هيسياك": "hyseac",
    "هيساك": "hyseac",
    "افين": "avene",
    "أفين": "avene",
    "افيني": "avene",
    "كلينانس": "cleanance",
    "سيكالفيت": "cicalfate",
    "اس في ار": "svr",
    "إس في ار": "svr",
    "ايucerin": "eucerin",
    "يوسرين": "eucerin",
    "ايسي ام": "acm",
    "اي سي ام": "acm",
    "ديبي وايت": "depiwhite",
    "ديبيوايت": "depiwhite",
    # General product types / areas
    "غسول الوجه": "face cleanser",
    "غسول للوجه": "face cleanser",
    "غسول وجة": "face cleanser",
    "غسول بشرتي": "face cleanser",
    "فيس واش": "face cleanser",
    "منظف وجه": "face cleanser",
    "منظف البشرة": "face cleanser",
    "مزيل مكياج": "makeup remover",
    "ماء ميسيلار": "micellar water",
    "ميسيلار": "micellar",
    "جل منظف": "cleanser",
    "جل تنظيف": "cleanser",
    "كريم مرطب": "moisturizer cream",
    "مرطب وجه": "face moisturizer",
    "كريم ترطيب": "moisturizer cream",
    "لوشن جسم": "body lotion",
    "مرطب جسم": "body moisturizer",
    "واقي الشمس": "sunscreen",
    "واقى شمس": "sunscreen",
    "واقي للوجه": "face sunscreen",
    "حماية من الشمس": "sunscreen",
    "spf50": "spf 50",
    "spf 50+": "spf 50",
    "spf50+": "spf 50",
    "بيبي": "baby",
    "اطفال": "baby",
    "للاطفال": "baby",
    "فروة الرأس": "scalp",
    # Skin concerns / purposes
    "بشرة دهنيه": "oily skin",
    "البشره الدهنيه": "oily skin",
    "للبشرة الدهنية": "oily skin",
    "للبشره الدهنيه": "oily skin",
    "بشرة جافة": "dry skin",
    "البشرة الجافة": "dry skin",
    "للبشرة الجافة": "dry skin",
    "بشرة حساسة": "sensitive skin",
    "للبشرة الحساسة": "sensitive skin",
    "تصبغات": "pigmentation",
    "تفتيح": "brightening",
    "بقع": "pigmentation",
    "كلف": "pigmentation",
    "اصلاح": "repair",
    "ترميم": "repair",
    "حاجز البشرة": "barrier repair",
    "قشرة": "dandruff",
    "القشرة": "dandruff",
    "ضد القشرة": "anti dandruff",
}

EXTRA_COSMETIC_BRANDS = [
    "isispharma", "isis pharma", "isis", "filorga", "sesderma", "babe", "bioderma", "vichy",
    "ducray", "noreva", "isis pharma", "pharmaceris", "acnemy", "mixa", "garnier",
    "neutrogena", "skinceuticals", "cantu", "topicrem", "novaclear", "dermedic",
]

EXTRA_TYPE_WORDS = {
    "cleanser": [
        "cleansing gel", "deep cleansing gel", "daily deep cleansing gel", "gel nettoyant", "nettoyant",
        "gel moussant", "foaming cleanser", "foaming gel", "purifying gel", "purifying cleanser",
        "face wash", "facial wash", "micellar gel", "غسول وجه", "غسول للوجه", "فيس واش",
        "منظف وجه", "جل منظف", "جل تنظيف",
    ],
    "sunscreen": ["spf 50", "spf50", "spf 30", "spf30", "anthelios", "photoderm", "medisun", "sun fluid", "sun cream"],
    "serum": ["ampoule", "ampoules", "booster", "سيروم", "امبول", "امبولات"],
    "moisturizer": ["hydrating cream", "moisturising cream", "moisturizing cream", "baume", "balm", "barrier cream"],
    "lotion": ["body lotion", "hydrating lotion", "moisturizing lotion"],
    "cream": ["repair cream", "cica cream", "cicalfate", "cicaplast", "barrier cream"],
    "shampoo": ["anti dandruff shampoo", "scalp shampoo", "شامبو قشرة", "شامبو للشعر"],
}

EXTRA_AREA_WORDS = {
    "face": ["facial", "visage", "anti acne", "acne", "sebium", "normaderm", "effaclar", "hyseac", "cleanance"],
    "body": ["body lotion", "body wash", "corps", "جسم", "للجسم"],
    "hair": ["scalp", "anti dandruff", "dandruff", "فروة", "شعر", "قشرة"],
    "mouth": ["mouthwash", "mouth wash", "oral rinse", "غسول فم", "فم", "اسنان"],
    "baby": ["baby", "kids", "pediatric", "enfant", "اطفال", "للأطفال", "بيبي"],
}

# Terms used to rank alternatives by purpose. A target and a candidate that share
# these terms are more likely to solve the same customer need.
PURPOSE_TERMS = {
    "acne_oily": ["acne", "anti acne", "oily", "sebium", "normaderm", "effaclar", "hyseac", "cleanance", "salicylic", "zinc", "دهنية", "حبوب"],
    "dry_hydration": ["dry", "very dry", "hydrating", "hydration", "atoderm", "lipikar", "xera", "moisturizing", "جافة", "ترطيب"],
    "sensitive": ["sensitive", "sensibio", "toleriane", "حساسة"],
    "repair_barrier": ["repair", "barrier", "cica", "cicaplast", "cicalfate", "baume", "panthenol", "b5", "ترميم", "اصلاح"],
    "pigmentation_brightening": ["pigment", "pigmentation", "brightening", "depiwhite", "white", "vitamin c", "تصبغات", "تفتيح", "كلف"],
    "sunscreen": ["sunscreen", "spf", "photoderm", "anthelios", "medisun", "واقي"],
    "dandruff_scalp": ["dandruff", "anti dandruff", "scalp", "ds", "قشرة", "فروة"],
    "baby": ["baby", "kids", "enfant", "اطفال", "بيبي"],
    "mouth_oral": ["mouth", "oral", "dental", "teeth", "فم", "اسنان"],
}

LINE_PRIORITY = {
    "acne_oily": ["effaclar", "sebium", "normaderm", "hyseac", "cleanance"],
    "dry_hydration": ["atoderm", "lipikar", "xera", "toleriane", "hydrating"],
    "sensitive": ["sensibio", "toleriane", "avene", "uriage"],
    "repair_barrier": ["cicaplast", "cicalfate", "cica", "baume", "b5"],
    "pigmentation_brightening": ["depiwhite", "pigment", "bright", "vitamin c"],
    "sunscreen": ["anthelios", "photoderm", "medisun", "spf"],
}


def purpose_tags(norm_text: str) -> Set[str]:
    """Return broad purpose tags found in already-normalized text."""
    text = f" {str(norm_text or '').lower()} "
    tags: Set[str] = set()
    for tag, words in PURPOSE_TERMS.items():
        for word in words:
            w = str(word).lower().strip()
            if not w:
                continue
            if f" {w} " in text or w in text:
                tags.add(tag)
                break
    return tags


def line_terms(norm_text: str) -> Set[str]:
    text = str(norm_text or '').lower()
    terms: Set[str] = set()
    for words in LINE_PRIORITY.values():
        for word in words:
            if word in text:
                terms.add(word)
    return terms


def same_purpose_score(target_norm: str, candidate_norm: str) -> float:
    target_tags = purpose_tags(target_norm)
    cand_tags = purpose_tags(candidate_norm)
    score = 0.0
    overlap = target_tags & cand_tags
    if overlap:
        score += 35.0 * len(overlap)
    # Stronger boost if both share a recognizable dermocosmetic line/purpose term.
    line_overlap = line_terms(target_norm) & line_terms(candidate_norm)
    if line_overlap:
        score += 18.0 * len(line_overlap)
    # Penalize purpose conflict. Example: acne/oily cleanser should not rank dry-skin first.
    conflicting_pairs = [
        ("acne_oily", "dry_hydration"),
        ("baby", "acne_oily"),
        ("mouth_oral", "acne_oily"),
        ("dandruff_scalp", "acne_oily"),
    ]
    for a, b in conflicting_pairs:
        if a in target_tags and b in cand_tags:
            score -= 45.0
        if b in target_tags and a in cand_tags:
            score -= 45.0
    return score


def looks_like_medicine(norm_text: str) -> bool:
    text = f" {str(norm_text or '').lower()} "
    medicine_terms = [
        "tablet", "tab", "capsule", "syrup", "susp", "suspension", "drops", "ampoule", "injection",
        "mg", "mcg", "iu", "antibiotic", "paracetamol", "amoxicillin", "clavulanic",
        "شراب", "معلق", "اقراص", "حبوب", "كبسول", "قطرة", "حقن", "مضاد",
    ]
    return any(f" {term} " in text or term in text for term in medicine_terms)


def normalize_visible_label(text: str) -> str:
    """Remove common packaging clutter but keep line/product words."""
    value = str(text or '')
    value = re.sub(r"\b\d+(?:[\.,]\d+)?\s*(?:ml|oz|fl\s*oz|g|mg|kg|l)\b", " ", value, flags=re.I)
    value = re.sub(r"\b(?:dermatologically|tested|laboratoires|laboratories|with|and|for)\b", " ", value, flags=re.I)
    return " ".join(value.split())
