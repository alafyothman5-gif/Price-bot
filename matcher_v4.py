
"""
PriceBot matcher_v4.py
Product Intelligence Engine V4.

V4 keeps matcher_v3's conservative resolver and adds production guards:
- product identity must be fully explained by local catalog evidence
- no price/availability until medicine/cosmetic variants are resolved
- no medicine alternatives unless explicit substitution_group support is added later
- image AI may provide structured JSON only; final decision is local catalog matching
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import matcher_v3
from matcher_v2 import DecisionType, MatchDecision

VERSION = "product-intelligence-v4-deterministic-safe"

# Re-export core v3 types/functions for compatibility.
ProductRecord = matcher_v3.ProductRecord
QuerySlots = matcher_v3.QuerySlots
CatalogIndex = matcher_v3.CatalogIndex
normalize_product_text = matcher_v3.normalize_product_text
clean_request_text = matcher_v3.clean_request_text
tokenize = matcher_v3.tokenize
extract_strength_values = matcher_v3.extract_strength_values
extract_size_values = matcher_v3.extract_size_values
refresh_synonym_rules = matcher_v3.refresh_synonym_rules
build_catalog_index = matcher_v3.build_catalog_index
resolve_product_query = lambda query, catalog: resolve_product_query_from_index(query, build_catalog_index(catalog))

GENERIC_SLOT_TOKENS = set(matcher_v3.REQUEST_STOPWORDS) | set(matcher_v3.ALL_TYPES) | {
    "mg", "mcg", "g", "gm", "ml", "iu", "unit", "units", "spf", "skin", "face", "body", "hair", "baby",
    "daily", "active", "normal", "dry", "oily", "sensitive",
    "for", "with", "and", "plus", "extra",  # `extra` is allowed when present in product tokens; see coverage below.
}
# Terms that should stay product-specific even when short. PB in Rilastil Xerolact PB is a real variant signal.
FORCE_SPECIFIC_TOKENS = {"pb", "b5", "ds", "ar", "ac", "xr", "sr", "mr", "plus", "extra"}


def invalidate_cache() -> None:
    try:
        matcher_v3.get_catalog_index.cache_clear()
    except Exception:
        pass


def _field(item: Dict[str, Any], *names: str) -> str:
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return str(value)
    return ""


def _record_id(rec: ProductRecord) -> str:
    return str(rec.id or rec.raw.get("id", "") or rec.normalized_name)


def _same_product(a: ProductRecord, b: ProductRecord) -> bool:
    return _record_id(a) == _record_id(b)


def _find_record_for_product(product: Optional[Dict[str, Any]], ci: CatalogIndex) -> Optional[ProductRecord]:
    if not product:
        return None
    pid = str(product.get("id", "") or "")
    pname = normalize_product_text(product.get("name", "") or product.get("original_name", ""))
    for rec in ci.records:
        if pid and str(rec.raw.get("id", "") or rec.id) == pid:
            return rec
        if pname and rec.normalized_name == pname:
            return rec
    return None


def extract_product_slots(query: Any) -> Dict[str, Any]:
    """Public V4 slot extractor for tests/admin/debug.

    Output is plain JSON-serializable data: brand, family, active ingredient,
    form, strength, size, category intent, cosmetic type/use/skin target, and
    token evidence. It never consults AI or returns stock/price.
    """
    slots = matcher_v3.extract_query_slots(query)
    return {
        "cleaned_text": slots.cleaned_text,
        "brand": slots.brand,
        "family": slots.product_family,
        "active_ingredient": slots.active_ingredient,
        "form": slots.form,
        "strength": slots.strength,
        "strength_values": sorted(slots.strength_values),
        "size": slots.size,
        "size_values": sorted(slots.size_values),
        "category": "medicine" if slots.is_medicine_query else "cosmetic" if slots.is_cosmetic_query else "unknown",
        "cosmetic_type": slots.cosmetic_type,
        "use_case": slots.use_case,
        "skin_type": slots.skin_type,
        "is_specific_named_product": slots.is_specific_named_product,
        "strong_tokens": sorted(slots.strong_tokens),
        "weak_tokens": sorted(slots.weak_tokens),
    }


def _query_specific_tokens(slots: QuerySlots) -> Set[str]:
    toks = set(tokenize(slots.cleaned_text))
    remove = set(GENERIC_SLOT_TOKENS)
    remove.update({slots.brand, slots.form, slots.cosmetic_type, slots.active_ingredient, slots.use_case, slots.skin_type})
    remove.update({"mg", "ml", "g", "gm", "mcg", "iu"})
    # numeric strength/size values are variant slots, not product-family tokens
    for val in slots.strength_values | slots.size_values:
        remove.add(val)
        remove.add(re.sub(r"\D+", "", val))
    out: Set[str] = set()
    for tok in toks:
        if tok in FORCE_SPECIFIC_TOKENS:
            out.add(tok)
            continue
        if tok in remove or tok.isdigit() or len(tok) <= 1:
            continue
        # keep non-generic short alphanumeric product codes
        out.add(tok)
    return out


def _token_is_covered(token: str, rec: ProductRecord) -> bool:
    rec_tokens = set(rec.tokens)
    if token in rec_tokens:
        return True
    if f" {token} " in f" {rec.identity} ":
        return True
    # Conservative typo tolerance only; do not let unrelated product-line suffixes pass.
    try:
        best = max((matcher_v3.fuzz.ratio(token, rt) / 100.0 for rt in rec_tokens if abs(len(token) - len(rt)) <= 2), default=0.0)
    except Exception:
        best = 0.0
    return best >= 0.92 and len(token) >= 4


def _uncovered_specific_tokens(slots: QuerySlots, rec: ProductRecord) -> Set[str]:
    specific = _query_specific_tokens(slots)
    return {tok for tok in specific if not _token_is_covered(tok, rec)}


def _same_identity_scope(slots: QuerySlots, ci: CatalogIndex) -> List[ProductRecord]:
    """Return records in the same brand/family/active scope without global fuzzy fallback."""
    scope: List[ProductRecord] = []
    family_tokens = _query_specific_tokens(slots)
    for rec in ci.records:
        if slots.brand and rec.brand and rec.brand != slots.brand:
            continue
        if slots.active_ingredient and slots.active_ingredient not in rec.identity:
            continue
        if slots.form and not matcher_v3._type_compatible(slots, rec):
            continue
        if slots.brand and not family_tokens:
            scope.append(rec)
            continue
        if family_tokens and family_tokens & rec.tokens:
            scope.append(rec)
    return matcher_v3._unique(scope)


def build_variant_groups(ci: CatalogIndex) -> Dict[str, List[ProductRecord]]:
    groups: Dict[str, List[ProductRecord]] = {}
    for rec in ci.records:
        if rec.is_medicine:
            key = "medicine|" + "|".join([rec.active_ingredient or rec.product_family or rec.brand, rec.brand])
        elif rec.is_cosmetic:
            key = "cosmetic|" + "|".join([rec.brand, rec.product_family or rec.use_case, rec.cosmetic_type or rec.form])
        else:
            key = "unknown|" + (rec.brand or rec.product_family or rec.normalized_name)
        groups.setdefault(key, []).append(rec)
    return groups


def _variant_guard(decision: MatchDecision, slots: QuerySlots, ci: CatalogIndex) -> MatchDecision:
    """Refuse a price if the resolved record sits in an unresolved variant group."""
    if decision.decision_type != DecisionType.EXACT_MATCH or not decision.product:
        return decision
    rec = getattr(decision, "product_record", None) or _find_record_for_product(decision.product, ci)
    if not rec:
        return decision

    # Medicine: if same family has multiple forms and form missing, ask. If one form but multiple strengths and strength missing, ask.
    if rec.is_medicine:
        scope = _same_identity_scope(slots, ci) or [rec]
        scope = [r for r in scope if r.is_medicine]
        forms, strengths, _sizes = matcher_v3._variant_sets(scope)
        if len(scope) > 1 and not slots.form and len(forms) > 1:
            return matcher_v3._ask("متوفر أكثر من شكل دوائي. الرجاء تحديد الشكل المطلوب:", scope, slots, "form", "v4_missing_medicine_form")
        if len(scope) > 1 and (slots.form or len(forms) <= 1) and not slots.strength_values and len(strengths) > 1:
            return matcher_v3._ask("يوجد من هذا الدواء أكثر من جرعة. الرجاء تحديد الجرعة المطلوبة:", scope, slots, "strength", "v4_missing_medicine_strength")

    # Cosmetics: same brand/type/family variants must not collapse when type/size/use is missing.
    if rec.is_cosmetic:
        q_specific = _query_specific_tokens(slots)
        scope: List[ProductRecord] = []
        for r in ci.records:
            if not r.is_cosmetic:
                continue
            if rec.brand and r.brand != rec.brand:
                continue
            if slots.cosmetic_type and (r.cosmetic_type or r.form) != slots.cosmetic_type:
                continue
            # Same visible product-line tokens from the query, ignoring size. This catches
            # CeraVe Hydrating Cleanser 236ml vs 473ml even if the catalog family field
            # accidentally includes the size.
            if q_specific and not all(_token_is_covered(tok, r) for tok in q_specific):
                continue
            if not q_specific and rec.product_family and r.product_family != rec.product_family:
                continue
            scope.append(r)
        scope = matcher_v3._unique(scope) or [rec]
        if len(scope) > 1:
            types = {r.cosmetic_type or r.form for r in scope if r.cosmetic_type or r.form}
            if not slots.cosmetic_type and len(types) > 1:
                return matcher_v3._ask("يوجد أكثر من نوع لهذا المنتج. الرجاء تحديد النوع المطلوب:", scope, slots, "product", "v4_missing_cosmetic_type")
            same_type = [r for r in scope if not slots.cosmetic_type or (r.cosmetic_type or r.form) == slots.cosmetic_type]
            _f, _s, same_sizes = matcher_v3._variant_sets(same_type)
            canonical_sizes = {re.sub(r"[^0-9.]+", "", str(x)) for x in same_sizes if str(x).strip()}
            canonical_sizes.discard("")
            if len(same_type) > 1 and not slots.size_values and len(canonical_sizes) > 1:
                return matcher_v3._ask("متوفر أكثر من حجم. الرجاء تحديد الحجم المطلوب:", same_type, slots, "size", "v4_missing_cosmetic_size")
    return decision



def _availability_for_record(rec: ProductRecord, slots: QuerySlots, ci: CatalogIndex) -> MatchDecision:
    return matcher_v3._availability_decision(rec, slots, ci)


def _refine_clarification(decision: MatchDecision, slots: QuerySlots, ci: CatalogIndex) -> MatchDecision:
    """When v3 asks because of broad candidates, V4 may resolve only if every
    product-specific token is covered by exactly one candidate. This is still
    deterministic and never falls back to global fuzzy matching.
    """
    if decision.decision_type != DecisionType.ASK_CLARIFICATION or not decision.clarification_options:
        return decision
    specific = _query_specific_tokens(slots)
    if not specific:
        return decision
    option_records = []
    for item in decision.clarification_options:
        rec = _find_record_for_product(item, ci)
        if rec:
            option_records.append(rec)
    fully = [rec for rec in option_records if not _uncovered_specific_tokens(slots, rec)]
    if len(fully) == 1:
        return _availability_for_record(fully[0], slots, ci)
    return decision

def _identity_guard(decision: MatchDecision, slots: QuerySlots, ci: CatalogIndex) -> MatchDecision:
    """Block partial-name matches when query contains product-line tokens absent from the chosen record."""
    if decision.decision_type != DecisionType.EXACT_MATCH or not decision.product:
        return decision
    rec = getattr(decision, "product_record", None) or _find_record_for_product(decision.product, ci)
    if not rec:
        return decision
    missing = _uncovered_specific_tokens(slots, rec)
    if not missing:
        return decision
    # If a query includes an unknown product-line suffix within a known brand/family, do not return a nearby item.
    reason = f"v4_uncovered_specific_tokens:{','.join(sorted(missing))}"
    if rec.is_cosmetic and slots.is_cosmetic_query and (slots.cosmetic_type or slots.form):
        # For known missing cosmetics, alternatives may be offered only by strict same type/use logic.
        return matcher_v3._not_available(slots, reason, ci.records)
    return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.0, reason=reason, query_slots=slots)


def _brand_or_type_only_guard(slots: QuerySlots, ci: CatalogIndex) -> Optional[MatchDecision]:
    # Brand-only and type-only must ask, even if catalog happens to contain one product today.
    specific = _query_specific_tokens(slots)
    if slots.brand and not specific and not slots.form and not slots.strength_values and not slots.size_values:
        options = ci.brand_index.get(slots.brand, [])[:12]
        if not options:
            return MatchDecision(DecisionType.LOW_CONFIDENCE, reason="v4_brand_only_no_catalog", query_slots=slots)
        forms, strengths, _sizes = matcher_v3._variant_sets(options)
        if any(r.is_medicine for r in options) and len(forms) > 1:
            return matcher_v3._ask("يوجد من هذا المنتج أكثر من شكل. اختر الشكل المطلوب أو اكتب رقمه:", options, slots, "form", "v4_brand_only_medicine_forms")
        if any(r.is_medicine for r in options) and len(strengths) > 1:
            return matcher_v3._ask("يوجد من هذا الدواء أكثر من جرعة. الرجاء تحديد الجرعة المطلوبة:", options, slots, "strength", "v4_brand_only_medicine_strengths")
        return matcher_v3._ask("يرجى تحديد المنتج المطلوب من هذه الشركة:", options, slots, "product", "v4_brand_only")
    if (slots.cosmetic_type or slots.form) and not slots.brand and not specific and not slots.strength_values:
        qtype = slots.cosmetic_type or slots.form
        options = [r for r in ci.records if (r.cosmetic_type or r.form) == qtype][:12]
        return matcher_v3._ask("يوجد أكثر من نوع. يرجى تحديد الشركة أو المنتج المطلوب:", options, slots, "product", "v4_type_only") if options else MatchDecision(DecisionType.LOW_CONFIDENCE, reason="v4_type_only_no_catalog", query_slots=slots)
    return None


def resolve_product_query_from_index(query: str, ci: CatalogIndex) -> MatchDecision:
    slots = matcher_v3.extract_query_slots(query)
    if not slots.cleaned_text or not ci.records:
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v4_empty_query_or_catalog", query_slots=slots)

    forced = _brand_or_type_only_guard(slots, ci)
    if forced is not None:
        return forced

    decision = matcher_v3.resolve_product_query_from_index(query, ci)
    decision = _refine_clarification(decision, slots, ci)
    # Upgrade reason marker while preserving conservative v3 behavior.
    if decision.reason and decision.reason.startswith("v3_"):
        decision.reason = "v4_" + decision.reason[3:]
    decision = _identity_guard(decision, slots, ci)
    decision = _variant_guard(decision, slots, ci)
    return decision


def _strong_image_evidence(ai_data: Dict[str, Any]) -> Tuple[bool, str, str]:
    brand = normalize_product_text(ai_data.get("brand", ""))
    barcode = normalize_product_text(ai_data.get("barcode", ""))
    product_type = normalize_product_text(ai_data.get("product_type", "") or ai_data.get("type", "") or ai_data.get("form", ""))
    visible = " ".join(str(ai_data.get(k) or "") for k in ["product_name", "visible_text", "ocr_text", "skin_concern", "usage_purpose", "size", "strength"])
    for name in ai_data.get("product_names") or []:
        visible += " " + str(name)
    cleaned = clean_request_text(visible)
    toks = {t for t in tokenize(cleaned) if t not in GENERIC_SLOT_TOKENS and not t.isdigit()}
    visual_id = str(ai_data.get("visual_similarity_product_id") or ai_data.get("candidate_product_id") or "").strip()
    if barcode:
        return True, "barcode", barcode
    if brand and product_type and (len(toks) >= 1 or normalize_product_text(ai_data.get("product_name", ""))):
        return True, "ocr_brand_type", " ".join(x for x in [brand, visible, product_type] if x)
    if visual_id and brand and product_type:
        return True, "visual_plus_ocr", " ".join(x for x in [brand, visible, product_type] if x)
    return False, "weak_image_evidence", " ".join(x for x in [brand, visible, product_type] if x)


def resolve_image_extraction_from_index(ai_data: Dict[str, Any], ci: CatalogIndex) -> MatchDecision:
    ai_data = dict(ai_data or {})
    image_type = str(ai_data.get("image_type") or "unknown").lower().strip()
    clarity = str(ai_data.get("clarity") or "").lower().strip()
    try:
        confidence = float(ai_data.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0
    if image_type in {"prescription", "prescription_or_unclear"}:
        return MatchDecision(DecisionType.IMAGE_UNCLEAR, confidence=confidence, reason="v4_image_prescription_needs_admin")
    if image_type in {"unclear", "other", "unknown"} or clarity == "bad" or confidence < 0.75:
        return MatchDecision(DecisionType.IMAGE_UNCLEAR, confidence=confidence, reason="v4_image_unclear")
    ok, evidence, query = _strong_image_evidence(ai_data)
    if not ok or not query.strip():
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=confidence, reason=f"v4_{evidence}")
    decision = resolve_product_query_from_index(query, ci)
    decision.confidence = max(decision.confidence, confidence if decision.decision_type != DecisionType.NOT_AVAILABLE else decision.confidence)
    if decision.reason:
        decision.reason = f"{decision.reason}|image_evidence={evidence}"
    else:
        decision.reason = f"v4_image_evidence={evidence}"
    return decision


def resolve_image_extraction(ai_data: Dict[str, Any], catalog: Sequence[Dict[str, Any]]) -> MatchDecision:
    return resolve_image_extraction_from_index(ai_data, build_catalog_index(catalog))


def build_catalog_quality_rows(catalog: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ci = build_catalog_index(catalog)
    rows: List[Dict[str, Any]] = []
    dupes: Dict[str, int] = {}
    groups = build_variant_groups(ci)
    for r in ci.records:
        dupes[r.normalized_name] = dupes.get(r.normalized_name, 0) + 1
    group_sizes = {gid: len(items) for gid, items in groups.items() for _ in items}
    for r in ci.records:
        issues: List[str] = []
        if not r.brand:
            issues.append("missing_brand")
        if not r.form:
            issues.append("missing_form_or_type")
        if r.is_medicine and not r.strength:
            issues.append("missing_strength")
        if r.is_cosmetic and not (r.cosmetic_type or r.form):
            issues.append("missing_cosmetic_type")
        if not r.aliases and not r.image_keywords:
            issues.append("weak_aliases_or_ocr_keywords")
        if dupes.get(r.normalized_name, 0) > 1:
            issues.append("duplicate_normalized_name")
        if not r.is_medicine and not r.is_cosmetic:
            issues.append("unclassified")
        if r.is_medicine and not _field(r.raw, "substitution_group"):
            issues.append("no_substitution_group")
        rows.append({
            "id": r.id,
            "name": r.original_name,
            "brand": r.brand,
            "family": r.product_family,
            "active_ingredient": r.active_ingredient,
            "form": r.form,
            "strength": r.strength,
            "size": r.size,
            "category": "medicine" if r.is_medicine else "cosmetic" if r.is_cosmetic else "unknown",
            "cosmetic_type": r.cosmetic_type,
            "use_case": r.use_case,
            "skin_type": r.skin_type,
            "variant_group_size": "",
            "issues": ";".join(issues),
        })
    return rows


def generate_catalog_quality_report(catalog: Sequence[Dict[str, Any]], output_path: str = "catalog_quality_report.csv") -> str:
    rows = build_catalog_quality_rows(catalog)
    fieldnames = ["id", "name", "brand", "family", "active_ingredient", "form", "strength", "size", "category", "cosmetic_type", "use_case", "skin_type", "variant_group_size", "issues"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_path
