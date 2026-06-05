"""
PriceBot fast safe matcher.

Purpose: avoid WhatsApp timeout replies while the heavy V4 catalog index is not
ready. This resolver is deliberately conservative: it uses exact/contained local
catalog evidence only and never returns a random fuzzy product.
"""
from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

import database
import matcher

_CACHE = {"ts": 0.0, "rows": [], "prepared": []}
CACHE_TTL_SECONDS = 60

_REQUEST_WORDS = {
    "متوفر", "متوفره", "موجود", "موجوده", "عندكم", "عندك", "السعر", "سعر", "كم", "بكم", "هل", "لو", "سمحت", "من", "في", "فيه",
    "available", "price", "do", "you", "have", "is", "please", "pls", "كم سعر", "نبي", "ابي", "اريد", "اريد", "نريد",
}

_GENERIC_TYPES = {
    "cream", "كريم", "كريمه", "gel", "جل", "gell", "lotion", "لوشن", "cleanser", "غسول", "wash", "serum", "سيروم", "shampoo", "شامبو",
    "tablet", "tab", "قرص", "اقراص", "حبوب", "syrup", "شراب", "capsule", "caps", "كبسول", "كبسولات", "injection", "حقن", "قطره", "drop",
}

_BRAND_ALIASES = {
    "cera ve": "cerave", "cera-ve": "cerave", "سيرا في": "cerave", "سيرافي": "cerave", "سيراڤي": "cerave",
    "vichy": "vichy", "فيشي": "vichy", "ڤيشي": "vichy",
    "rilastil": "rilastil", "ريلاستيل": "rilastil",
}

_AR_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ک": "ك", "ی": "ي", "ڤ": "ف", "گ": "ك", "پ": "ب",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})


def _norm(value: Any) -> str:
    s = str(value or "").lower().strip().translate(_AR_MAP)
    for src, dst in _BRAND_ALIASES.items():
        s = s.replace(src, dst)
    s = re.sub(r"[^a-z0-9\u0600-\u06ff]+", " ", s)
    s = " ".join(s.split())
    return s


def _tokens(value: Any) -> List[str]:
    n = _norm(value)
    out: List[str] = []
    for tok in n.split():
        if tok in _REQUEST_WORDS:
            continue
        if len(tok) <= 1 and not tok.isdigit():
            continue
        out.append(tok)
    return out


def _split_multi(value: Any) -> List[str]:
    parts = re.split(r"[|,;\n\r]+", str(value or ""))
    return [p.strip() for p in parts if p and p.strip()]


def _get_name(row: Dict[str, Any]) -> str:
    return str(row.get("name") or row.get("original_name") or "").strip()


def _prepare(row: Dict[str, Any]) -> Dict[str, Any]:
    name = _get_name(row)
    brand = _norm(row.get("brand") or row.get("company") or "")
    form = _norm(row.get("form") or row.get("cosmetic_type") or "")
    family = _norm(row.get("product_family") or "")
    active = _norm(row.get("active_ingredient") or "")
    strength = _norm(row.get("strength") or "")
    size = _norm(row.get("size") or row.get("pack") or "")
    exact_values = [name, row.get("original_name"), row.get("normalized_name")]
    exact_values += _split_multi(row.get("aliases"))
    exact_values += _split_multi(row.get("ocr_keywords") or row.get("image_ocr_keywords") or row.get("keywords"))
    exact_norms = {n for n in (_norm(x) for x in exact_values) if n}
    identity = _norm(" ".join(str(x or "") for x in [
        name, row.get("original_name"), row.get("aliases"), row.get("ocr_keywords"), row.get("image_ocr_keywords"),
        brand, family, active, form, strength, size, row.get("barcode"), row.get("code"), row.get("sku"), row.get("item_code"), row.get("product_code"),
    ]))
    return {"row": row, "name": name, "brand": brand, "form": form, "family": family, "identity": identity, "exact_norms": exact_norms, "tokens": set(identity.split())}


def _load_prepared() -> List[Dict[str, Any]]:
    now = time.time()
    if _CACHE["prepared"] and now - float(_CACHE["ts"] or 0) < CACHE_TTL_SECONDS:
        return _CACHE["prepared"]
    rows = database.load_products()
    prepared = [_prepare(dict(r)) for r in rows if _get_name(dict(r))]
    _CACHE.update({"ts": now, "rows": rows, "prepared": prepared})
    return prepared


def invalidate_cache() -> None:
    _CACHE.update({"ts": 0.0, "rows": [], "prepared": []})


def _is_brand_only(q_tokens: List[str], prepared: List[Dict[str, Any]]) -> Tuple[bool, str, List[Dict[str, Any]]]:
    if not q_tokens:
        return False, "", []
    qset = set(q_tokens)
    brands = {p["brand"] for p in prepared if p.get("brand")}
    # single brand token or all tokens equal the same normalized brand tokens
    for brand in brands:
        btoks = set(brand.split())
        if qset == btoks:
            opts = [p for p in prepared if p.get("brand") == brand]
            return True, brand, opts
    return False, "", []


def _is_type_only(q_tokens: List[str]) -> bool:
    return bool(q_tokens) and all(t in _GENERIC_TYPES for t in q_tokens)


def _coverage_candidates(q_tokens: List[str], prepared: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not q_tokens:
        return []
    qset = set(q_tokens)
    # Ignore pure generic type words for identity, but keep them as filters.
    strong = [t for t in q_tokens if t not in _GENERIC_TYPES]
    type_filter = {t for t in q_tokens if t in _GENERIC_TYPES}
    if not strong:
        return []
    candidates: List[Tuple[int, Dict[str, Any]]] = []
    for p in prepared:
        toks = p["tokens"]
        if not all(t in toks or f" {t} " in f" {p['identity']} " for t in strong):
            continue
        if type_filter:
            # If customer specified a type, do not cross from cream to shampoo etc.
            if not any(t in toks or t == p.get("form") for t in type_filter):
                continue
        score = len(strong) * 10 + sum(1 for t in q_tokens if t in toks)
        # Prefer shorter identity/name when all tokens are covered.
        score -= min(len(p["tokens"]), 50) // 10
        candidates.append((score, p))
    candidates.sort(key=lambda x: x[0], reverse=True)
    unique: List[Dict[str, Any]] = []
    seen = set()
    for _score, p in candidates:
        pid = str(p["row"].get("id") or p["name"])
        if pid not in seen:
            seen.add(pid)
            unique.append(p)
    return unique


def _option_lines(options: List[Dict[str, Any]], max_items: int = 8) -> str:
    lines = []
    for i, p in enumerate(options[:max_items], 1):
        row = p["row"]
        price = str(row.get("price") or "").strip()
        form = str(row.get("form") or "").strip()
        strength = str(row.get("strength") or "").strip()
        size = str(row.get("size") or row.get("pack") or "").strip()
        detail = " / ".join(x for x in [form, strength, size] if x)
        detail = f" ({detail})" if detail else ""
        price_txt = f" - {price} د.ل" if price and "د" not in price else f" - {price}" if price else ""
        lines.append(f"{i}) {_get_name(row)}{detail}{price_txt}")
    return "\n".join(lines)


def _ask_options(phone: str, query: str, options: List[Dict[str, Any]], question: str) -> matcher.QueryResult:
    rows = [p["row"] for p in options[:12]]
    try:
        database.update_user_state(phone, {"pending_variant_options": rows, "pending_variant_kind": "product", "pending_variant_query": query})
    except Exception as exc:
        print(f"FAST_MATCHER_STATE_WARNING: {exc}")
    body = question
    if rows:
        body += "\n\n" + _option_lines(options)
    return matcher.QueryResult(reply=matcher.with_header(body.rstrip()), decision="fast_ask", normalized_query=query)


def _product_result(phone: str, row: Dict[str, Any], query: str) -> matcher.QueryResult:
    try:
        if matcher.is_available(row.get("available", "")):
            database.update_user_state(phone, {"last_product": row})
        else:
            database.clear_user_state(phone)
    except Exception as exc:
        print(f"FAST_MATCHER_STATE_WARNING: {exc}")
    return matcher.QueryResult(reply=matcher.build_product_reply(row), decision="fast_exact", product=row, normalized_query=query)


def _not_available(query: str) -> matcher.QueryResult:
    return matcher.QueryResult(
        reply=matcher.with_header("المنتج المطلوب غير موجود في قائمة الصيدلية حالياً. الرجاء كتابة الاسم كاملاً كما هو على العلبة أو إرسال صورة أوضح."),
        decision="fast_not_available",
        normalized_query=query,
    )


def fast_text_query_result(phone: str, text: str, user_state: Optional[dict] = None) -> Optional[matcher.QueryResult]:
    query = str(text or "").strip()
    q_norm = _norm(query)
    q_tokens = _tokens(query)
    if not q_norm:
        return matcher.QueryResult(reply=matcher.build_fallback_reply(), decision="fast_empty", normalized_query="")

    prepared = _load_prepared()
    if not prepared:
        return matcher.QueryResult(reply=matcher.with_header("لا توجد منتجات مرفوعة حالياً في قاعدة الصيدلية."), decision="fast_no_catalog", normalized_query=q_norm)

    # Exact name / alias / barcode/code only.
    exact = [p for p in prepared if q_norm in p["exact_norms"]]
    if len(exact) == 1:
        return _product_result(phone, exact[0]["row"], q_norm)
    if len(exact) > 1:
        return _ask_options(phone, q_norm, exact, "يوجد أكثر من منتج بنفس الاسم. الرجاء اختيار المطلوب:")

    brand_only, brand, brand_options = _is_brand_only(q_tokens, prepared)
    if brand_only:
        return _ask_options(phone, q_norm, brand_options, "يرجى تحديد المنتج المطلوب من هذه الشركة:")

    if _is_type_only(q_tokens):
        return matcher.QueryResult(reply=matcher.with_header("يرجى كتابة اسم الشركة أو اسم المنتج كاملاً. النوع وحده غير كافٍ للبحث."), decision="fast_type_only", normalized_query=q_norm)

    candidates = _coverage_candidates(q_tokens, prepared)
    if len(candidates) == 1 and len([t for t in q_tokens if t not in _GENERIC_TYPES]) >= 2:
        return _product_result(phone, candidates[0]["row"], q_norm)
    if 1 < len(candidates) <= 12:
        return _ask_options(phone, q_norm, candidates, "وجدت أكثر من منتج قريب من طلبك. الرجاء اختيار المطلوب:")
    if len(candidates) > 12:
        return matcher.QueryResult(reply=matcher.with_header("يوجد عدد كبير من المنتجات القريبة. الرجاء كتابة الاسم كاملاً أو الحجم/الجرعة."), decision="fast_too_many", normalized_query=q_norm)

    return _not_available(q_norm)


def _image_query_from_ai(ai_data: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ["brand", "product_name", "product_type", "form", "visible_text", "ocr_text", "skin_concern", "usage_purpose", "size", "strength"]:
        value = ai_data.get(key)
        if value:
            parts.append(str(value))
    for value in ai_data.get("product_names") or []:
        if value:
            parts.append(str(value))
    return " ".join(parts).strip()


def fast_image_reply(phone: str, ai_data: Dict[str, Any]) -> Optional[str]:
    ai_data = dict(ai_data or {})
    image_type = str(ai_data.get("image_type") or "unknown").lower().strip()
    clarity = str(ai_data.get("clarity") or "").lower().strip()
    try:
        confidence = float(ai_data.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    if image_type in {"prescription", "prescription_or_unclear"}:
        return matcher.build_prescription_reply()
    if image_type in {"unclear", "other", "unknown"} or clarity == "bad" or confidence < 0.55:
        return matcher.build_unclear_image_reply()
    query = _image_query_from_ai(ai_data)
    if len(_tokens(query)) < 2:
        return matcher.with_header("لم أتأكد من المنتج المقصود من الصورة. الرجاء كتابة اسم المنتج كاملاً كما هو على العلبة أو إرسال صورة أوضح.")
    result = fast_text_query_result(phone, query, {})
    return result.reply if result else None


# FINAL_STRICT_V4_GUARD_V1
# This module is kept for backward compatibility only. It must not produce
# customer-facing final decisions; matcher_v4 is the only final decision engine.
def fast_text_query_result(phone: str, text: str, user_state: Optional[dict] = None):  # type: ignore[override]
    return None

def fast_image_reply(phone: str, ai_data: Dict[str, Any]):  # type: ignore[override]
    return None
