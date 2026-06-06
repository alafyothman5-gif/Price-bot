
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
fuzz = matcher_v3.fuzz

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




# FINAL V17.2 PRODUCT ACCURACY GUARD
# The strict engine must stay conservative, but it should tolerate small typing
# mistakes inside a safe scope (same fuzzy brand + same type/product-line). This
# prevents clear requests like "CeraVe hydratng clenser" from becoming
# unavailable while still blocking random global fuzzy matches.
TYPO_IGNORE_TOKENS = set(matcher_v3.REQUEST_STOPWORDS) | {
    "mg", "mcg", "g", "gm", "ml", "iu", "unit", "units", "spf", "%",
    "skin", "face", "body", "hair", "baby", "product", "original", "new",
    "the", "a", "an", "for", "with", "and", "plus", "extra",
}


def _ci_brand_keys(ci: CatalogIndex) -> Set[str]:
    brands = set(ci.brand_index.keys())
    for rec in ci.records:
        if rec.brand:
            brands.add(rec.brand)
    return {b for b in brands if b and len(b) >= 3}


def _best_token_similarity(token: str, choices: Iterable[str]) -> float:
    token = normalize_product_text(token)
    if not token:
        return 0.0
    best = 0.0
    for choice in choices:
        if not choice:
            continue
        if token == choice:
            return 1.0
        # Ratio is safer than partial_ratio here; it prevents tiny fragments from matching long names.
        score = fuzz.ratio(token, choice) / 100.0
        if score > best:
            best = score
    return best


def _detect_fuzzy_brand_for_query(slots: QuerySlots, ci: CatalogIndex) -> Tuple[str, float]:
    if slots.brand:
        return slots.brand, 1.0
    brands = _ci_brand_keys(ci)
    if not brands:
        return "", 0.0
    query_tokens = [t for t in tokenize(slots.cleaned_text) if len(t) >= 4]
    # Also try short adjacent phrases for brands such as "la roche" before synonym folding.
    words = slots.cleaned_text.split()
    phrases = list(query_tokens)
    for n in (2, 3):
        for i in range(0, max(0, len(words) - n + 1)):
            ph = normalize_product_text(" ".join(words[i:i+n]))
            if len(ph) >= 4:
                phrases.append(ph)
    best_brand, best_score, second = "", 0.0, 0.0
    for ph in phrases:
        for brand in brands:
            # Keep fuzzy brand very strict; one-letter typos like cerav->cerave pass,
            # unrelated words should not.
            score = max(fuzz.ratio(ph, brand), fuzz.token_set_ratio(ph, brand)) / 100.0
            if score > best_score:
                second = best_score
                best_brand, best_score = brand, score
            elif score > second:
                second = score
    if best_score >= 0.88 and best_score - second >= 0.03:
        return best_brand, best_score
    return "", 0.0


def _line_tokens_for_typo_rescue(slots: QuerySlots, fuzzy_brand: str = "") -> Set[str]:
    tokens = set(tokenize(slots.cleaned_text))
    discard = set(TYPO_IGNORE_TOKENS) | {slots.brand, fuzzy_brand, slots.cosmetic_type, slots.form}
    discard |= set(matcher_v3.ALL_TYPES)
    discard |= {"mg", "ml", "g", "gm"}
    for value in slots.strength_values | slots.size_values:
        discard.add(value)
        discard.add(re.sub(r"\D+", "", value))
    out = set()
    for tok in tokens:
        if tok in discard or len(tok) <= 1 or tok.isdigit():
            continue
        # If this token is merely a misspelled brand (cerav -> cerave), do not
        # treat it as a product-line token.
        if fuzzy_brand and fuzz.ratio(tok, fuzzy_brand) / 100.0 >= 0.88:
            continue
        out.add(tok)
    return out


def _record_typo_score(slots: QuerySlots, rec: ProductRecord, line_tokens: Set[str], fuzzy_brand: str, fuzzy_brand_score: float) -> float:
    if fuzzy_brand and rec.brand and rec.brand != fuzzy_brand:
        return 0.0
    if slots.brand and rec.brand and rec.brand != slots.brand:
        return 0.0
    if slots.active_ingredient and slots.active_ingredient not in rec.identity:
        return 0.0
    rtype = rec.cosmetic_type or rec.form
    if slots.form and not matcher_v3._type_compatible(slots, rec):
        # Exception for one-letter type typos: "clenser" should be allowed to
        # reach a cleanser record, but "lotion" must not reach a cleanser.
        if not (rtype and any(_best_token_similarity(tok, {rtype}) >= 0.86 for tok in line_tokens)):
            return 0.0
    if slots.cosmetic_type and rtype != slots.cosmetic_type:
        if not (rtype and any(_best_token_similarity(tok, {rtype}) >= 0.86 for tok in line_tokens)):
            return 0.0
    if slots.skin_type and rec.skin_type and rec.skin_type != slots.skin_type:
        return 0.0
    if slots.use_case and rec.use_case and rec.use_case != slots.use_case and not fuzzy_brand:
        return 0.0

    rec_terms = set(rec.tokens)
    rec_terms.update(tokenize(rec.product_family or ""))
    rec_terms.update(tokenize(rec.normalized_name or ""))
    for alias in rec.aliases | rec.image_keywords:
        rec_terms.update(tokenize(alias))
    rec_terms = {t for t in rec_terms if t and len(t) > 1}

    if line_tokens:
        sims = [_best_token_similarity(tok, rec_terms) for tok in line_tokens]
        # One-token product-line typo needs strong evidence. Two-token mistakes can average high.
        min_required = 0.86 if len(line_tokens) <= 1 else 0.80
        if any(s < min_required for s in sims):
            return 0.0
        coverage = sum(sims) / len(sims)
    else:
        coverage = 0.0

    phrase = fuzz.token_set_ratio(slots.cleaned_text, rec.identity) / 100.0
    score = 0.55 * coverage + 0.25 * phrase
    if fuzzy_brand and rec.brand == fuzzy_brand:
        score += 0.12 * fuzzy_brand_score
    if slots.brand and rec.brand == slots.brand:
        score += 0.12
    if slots.cosmetic_type and (rec.cosmetic_type or rec.form) == slots.cosmetic_type:
        score += 0.10
    if slots.form and rec.form == slots.form:
        score += 0.10
    if slots.use_case and rec.use_case == slots.use_case:
        score += 0.05
    if slots.skin_type and rec.skin_type == slots.skin_type:
        score += 0.05
    return min(score, 1.0)


def _typo_rescue_decision(current: MatchDecision, slots: QuerySlots, ci: CatalogIndex) -> Optional[MatchDecision]:
    # Only rescue failures. Never override an exact match or a clarification that was already safe.
    if current.decision_type not in {DecisionType.NOT_AVAILABLE, DecisionType.COSMETIC_ALTERNATIVES, DecisionType.LOW_CONFIDENCE}:
        return None
    fuzzy_brand, brand_score = _detect_fuzzy_brand_for_query(slots, ci)
    line_tokens = _line_tokens_for_typo_rescue(slots, fuzzy_brand)

    # Brand-only typo, e.g. "Cerav" or "Falgyl": ask within that brand/family instead of saying unavailable.
    if fuzzy_brand and not line_tokens and not slots.form and not slots.strength_values and not slots.size_values:
        options = ci.brand_index.get(fuzzy_brand, [])[:12]
        if options:
            return matcher_v3._ask("يرجى تحديد المنتج المطلوب من هذه الشركة:", options, slots, "product", "v17_2_fuzzy_brand_only")

    # Do not do global typo rescue from generic queries. Need either a known/fuzzy brand or at least
    # two product-line tokens with a concrete type.
    if not fuzzy_brand and not (len(line_tokens) >= 2 and (slots.cosmetic_type or slots.form or slots.active_ingredient)):
        return None
    if not line_tokens and not slots.form and not slots.strength_values:
        return None

    candidates = ci.brand_index.get(fuzzy_brand, []) if fuzzy_brand else ci.records
    scored: List[Tuple[float, ProductRecord]] = []
    for rec in candidates:
        score = _record_typo_score(slots, rec, line_tokens, fuzzy_brand, brand_score)
        if score >= 0.83:
            scored.append((score, rec))
    if not scored:
        return None
    scored.sort(key=lambda p: p[0], reverse=True)
    best_score = scored[0][0]
    # Keep all near-top records so the normal variant resolver can ask for size/form/strength.
    near = [rec for score, rec in scored if score >= max(0.83, best_score - 0.06)]
    if not near:
        return None

    slots_for_resolve = slots
    # If the only conflict came from a misspelled type token (e.g. clenser -> cleanser),
    # let the normal resolver see the corrected type so it can return exact/ask-size.
    near_types = {r.cosmetic_type or r.form for r in near if (r.cosmetic_type or r.form)}
    if len(near_types) == 1:
        near_type = next(iter(near_types))
        if (slots.cosmetic_type or slots.form) and near_type != (slots.cosmetic_type or slots.form):
            if any(_best_token_similarity(tok, {near_type}) >= 0.86 for tok in line_tokens):
                data = asdict(slots)
                data["form"] = near_type
                data["cosmetic_type"] = near_type if near_type in matcher_v3.COSMETIC_TYPES else ""
                slots_for_resolve = QuerySlots(**data)

    decision = matcher_v3._resolve_candidates(near, slots_for_resolve, ci, "v17_2_typo_rescue")
    if decision.reason:
        decision.reason = "v17_2_" + decision.reason
    return decision




def _records_matching_strength(records: Iterable[ProductRecord], strength_values: Set[str]) -> List[ProductRecord]:
    if not strength_values:
        return list(records)
    out: List[ProductRecord] = []
    for rec in records:
        values = extract_strength_values(rec.strength) | extract_strength_values(rec.identity)
        if strength_values & values:
            out.append(rec)
    return matcher_v3._unique(out)


def _filter_clarification_by_strength(decision: MatchDecision, slots: QuerySlots, ci: CatalogIndex) -> MatchDecision:
    """If the user mentioned a strength, clarification choices must stay inside that strength."""
    if decision.decision_type != DecisionType.ASK_CLARIFICATION or not slots.strength_values or not decision.clarification_options:
        return decision
    option_records: List[ProductRecord] = []
    for item in decision.clarification_options:
        rec = _find_record_for_product(item, ci)
        if rec:
            option_records.append(rec)
    filtered = _records_matching_strength(option_records, slots.strength_values)
    if not filtered:
        return decision
    decision.clarification_options = [r.raw for r in filtered[:12]]
    if decision.reason:
        decision.reason += "|v17_5_strength_filtered_options"
    else:
        decision.reason = "v17_5_strength_filtered_options"
    return decision


def _resolve_product_query_core_from_index(query: str, ci: CatalogIndex) -> MatchDecision:
    """Core V4 resolver retained from V17.4 without public duplicate definitions."""
    slots = matcher_v3.extract_query_slots(query)
    if not slots.cleaned_text or not ci.records:
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v4_empty_query_or_catalog", query_slots=slots)

    forced = _brand_or_type_only_guard(slots, ci)
    if forced is not None:
        return forced

    decision = matcher_v3.resolve_product_query_from_index(query, ci)
    decision = _refine_clarification(decision, slots, ci)
    if decision.reason and decision.reason.startswith("v3_"):
        decision.reason = "v4_" + decision.reason[3:]
    decision = _identity_guard(decision, slots, ci)

    rescued = _typo_rescue_decision(decision, slots, ci)
    if rescued is not None:
        decision = rescued

    decision = _filter_clarification_by_strength(decision, slots, ci)
    decision = _variant_guard(decision, slots, ci)
    decision = _filter_clarification_by_strength(decision, slots, ci)
    return decision


# ---------------------------------------------------------------------------
# FINAL STRICT V17.5 MATCHING + VISION SAFETY
# ---------------------------------------------------------------------------
VERSION = "product-intelligence-v17.5-production-review"
V17_4_VERSION = "stable-v17.4-matching-vision-guard"
V17_5_VERSION = "production-review-v17.5"

V17_4_GENERIC_WEAK_TOKENS = set(GENERIC_SLOT_TOKENS) | set(matcher_v3.WEAK_TOKENS) | set(matcher_v3.ALL_TYPES) | {
    "cream", "gel", "face", "skin", "lotion", "cleanser", "wash", "soap", "shampoo", "moisturizer",
    "moisturising", "moisturizing", "serum", "baume", "balm", "sunscreen", "spf", "oil", "toner",
    "كريم", "جل", "غسول", "لوشن", "شامبو", "سيروم", "بشره", "بشرة", "وجه", "مرطب", "واقي", "صابون",
    "dry", "oily", "sensitive", "acne", "جافه", "جافة", "دهنيه", "دهنية", "حساسه", "حساسة", "حبوب",
}


def _v17_4_specific_tokens(slots: QuerySlots) -> Set[str]:
    tokens = _query_specific_tokens(slots)
    out: Set[str] = set()
    for t in tokens:
        if t in FORCE_SPECIFIC_TOKENS:
            out.add(t)
        elif t not in V17_4_GENERIC_WEAK_TOKENS and not t.isdigit():
            out.add(t)
    return out


def _v17_4_is_brand_only(slots: QuerySlots) -> bool:
    return bool(slots.brand and not _v17_4_specific_tokens(slots) and not slots.form and not slots.cosmetic_type and not slots.strength_values and not slots.size_values)


def _v17_4_is_type_only(slots: QuerySlots) -> bool:
    return bool((slots.cosmetic_type or slots.form) and not slots.brand and not _v17_4_specific_tokens(slots) and not slots.strength_values and not slots.size_values)


def _v17_4_is_need_based_only(slots: QuerySlots) -> bool:
    return bool((slots.use_case or slots.skin_type) and not slots.brand and not _v17_4_specific_tokens(slots) and not slots.form and not slots.cosmetic_type)


def _v17_5_is_brand_type_only(slots: QuerySlots) -> bool:
    """Brand + generic product type is not a fully identified product."""
    return bool(slots.brand and slots.cosmetic_type and not slots.product_family and not _v17_4_specific_tokens(slots) and not slots.strength_values and not slots.size_values)


def classify_query_intent(query: str, ci: Optional[CatalogIndex] = None) -> str:
    slots = matcher_v3.extract_query_slots(query)
    if not slots.cleaned_text:
        return "low_confidence_query"
    if _v17_4_is_brand_only(slots):
        return "brand_only_query"
    if _v17_5_is_brand_type_only(slots):
        return "brand_type_only_query"
    if _v17_4_is_type_only(slots):
        return "type_only_query"
    if _v17_4_is_need_based_only(slots):
        return "need_based_query"
    if slots.active_ingredient and (not slots.form or not slots.strength_values):
        return "medicine_ambiguous_query"
    if slots.is_specific_named_product:
        return "specific_product_query"
    if not (slots.brand or slots.active_ingredient or _v17_4_specific_tokens(slots)):
        return "low_confidence_query"
    return "specific_product_query"


def _v17_4_first_options(records: Iterable[ProductRecord], limit: int = 12) -> List[ProductRecord]:
    return matcher_v3._unique(list(records))[:limit]


def _v17_4_record_type(rec: ProductRecord) -> str:
    return rec.cosmetic_type or rec.form or ""

def _v17_4_strict_missing_cosmetic_alternatives(slots: QuerySlots, records: Sequence[ProductRecord], limit: int = 3) -> List[ProductRecord]:
    """Alternatives for a missing cosmetic request: same cosmetic type only.

    A brand-only/type-only request is not enough to show alternatives. If the
    user provided skin/use intent, wrong known skin/use records are excluded.
    """
    target_type = slots.cosmetic_type or slots.form
    if target_type not in matcher_v3.COSMETIC_TYPES:
        return []
    # Do not produce alternatives for generic type-only or brand-only requests.
    if _v17_4_is_type_only(slots) or _v17_4_is_brand_only(slots):
        return []
    if target_type in {"moisturizer"}:
        allowed = {"moisturizer", "lotion", "cream", "balm"}
    else:
        allowed = {target_type}
    # For strict types, never cross these boundaries.
    if target_type in {"cleanser", "serum", "lotion", "cream", "gel", "oil", "shampoo", "sunscreen"}:
        allowed = {target_type}
    candidates: List[Tuple[float, ProductRecord]] = []
    for rec in records:
        if not rec.is_cosmetic or not matcher_v3._availability_ok(rec.availability):
            continue
        rtype = _v17_4_record_type(rec)
        if rtype not in allowed:
            continue
        if target_type == "cleanser" and any(bad in rec.identity for bad in ["shampoo", "hair", "body", "mouth", "dental", "oral"]):
            continue
        # If the user specified use/skin, never knowingly cross it.
        if slots.skin_type and rec.skin_type and rec.skin_type != slots.skin_type:
            continue
        if slots.use_case and rec.use_case and rec.use_case != slots.use_case:
            continue
        # Require at least one meaningful relation, unless the user only knows
        # type+use (e.g. سيروم فيتامين سي) and the record matches that use/type.
        relation = False
        if slots.brand and rec.brand == slots.brand:
            relation = True
        if slots.use_case and rec.use_case == slots.use_case:
            relation = True
        if slots.skin_type and rec.skin_type == slots.skin_type:
            relation = True
        if slots.product_family:
            fam_toks = set(tokenize(slots.product_family)) - V17_4_GENERIC_WEAK_TOKENS
            if fam_toks and fam_toks & rec.tokens:
                relation = True
        if not relation and not (slots.use_case or slots.skin_type):
            # Avoid random "any cleanser" suggestions for a named missing product.
            continue
        score = 0.0
        score += 50 if rtype == target_type else 0
        score += 20 if slots.brand and rec.brand == slots.brand else 0
        score += 15 if slots.use_case and rec.use_case == slots.use_case else 0
        score += 15 if slots.skin_type and rec.skin_type == slots.skin_type else 0
        score += fuzz.token_set_ratio(slots.cleaned_text, rec.identity) / 100.0 * 10
        candidates.append((score, rec))
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [r for _score, r in candidates[:limit]]


def _v17_4_filter_cosmetic_alternative_decision(decision: MatchDecision, slots: QuerySlots, ci: CatalogIndex) -> MatchDecision:
    if decision.decision_type != DecisionType.COSMETIC_ALTERNATIVES:
        return decision
    records_by_id = {str(r.id or r.normalized_name): r for r in ci.records}
    records_by_name = {r.normalized_name: r for r in ci.records}
    filtered: List[Dict[str, Any]] = []
    target_type = slots.cosmetic_type or slots.form
    if not target_type or _v17_4_is_type_only(slots) or _v17_4_is_brand_only(slots) or _v17_5_is_brand_type_only(slots):
        return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.0, product=decision.product, reason="v17_5_alt_blocked_generic_brand_type_or_unknown_type", query_slots=slots)
    fam_tokens = set(tokenize(slots.product_family)) - V17_4_GENERIC_WEAK_TOKENS
    for alt in decision.alternatives or []:
        if not isinstance(alt, dict):
            continue
        rec = None
        pid = str(alt.get("id") or alt.get("product_id") or alt.get("code") or "")
        if pid in records_by_id:
            rec = records_by_id[pid]
        if rec is None:
            rec = records_by_name.get(normalize_product_text(alt.get("name", "")))
        if not rec or not rec.is_cosmetic or not matcher_v3._availability_ok(rec.availability):
            continue
        rtype = _v17_4_record_type(rec)
        if target_type in {"cleanser", "serum", "lotion", "cream", "gel", "oil", "shampoo", "sunscreen"} and rtype != target_type:
            continue
        if target_type == "moisturizer" and rtype not in {"moisturizer", "lotion", "cream", "balm"}:
            continue
        if slots.skin_type and rec.skin_type and rec.skin_type != slots.skin_type:
            continue
        if slots.use_case and rec.use_case and rec.use_case != slots.use_case:
            continue
        relation = False
        if slots.brand and rec.brand == slots.brand:
            relation = True
        if slots.use_case and rec.use_case == slots.use_case:
            relation = True
        if slots.skin_type and rec.skin_type == slots.skin_type:
            relation = True
        if fam_tokens and fam_tokens & rec.tokens:
            relation = True
        if not relation:
            continue
        filtered.append(alt)
    if not filtered:
        return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=decision.confidence, product=decision.product, reason="v17_4_alt_blocked_no_strong_relation", query_slots=slots)
    decision.alternatives = filtered[:3]
    decision.reason = (decision.reason + "|" if decision.reason else "") + "v17_4_filtered_alternatives"
    return decision


def _ask_brand_type_only(slots: QuerySlots, ci: CatalogIndex) -> MatchDecision:
    qtype = slots.cosmetic_type or slots.form
    options = [r for r in ci.brand_index.get(slots.brand, []) if (not qtype or (r.cosmetic_type or r.form) == qtype)]
    if not options:
        options = ci.brand_index.get(slots.brand, [])[:12]
    if options:
        return matcher_v3._ask("الطلب غير محدد كفاية. اكتب اسم المنتج الكامل أو اختر المنتج المطلوب:", options[:12], slots, "product", "v17_5_brand_type_only_query")
    return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v17_5_brand_type_only_no_catalog", query_slots=slots)


def _v17_4_pre_guard(slots: QuerySlots, ci: CatalogIndex) -> Optional[MatchDecision]:
    intent = classify_query_intent(slots.cleaned_text, ci)
    if intent == "brand_only_query":
        options = ci.brand_index.get(slots.brand, [])[:12]
        if options:
            forms, strengths, _sizes = matcher_v3._variant_sets(options)
            if any(r.is_medicine for r in options) and len(forms) > 1:
                return matcher_v3._ask("يوجد من هذا المنتج أكثر من شكل. اختر الشكل المطلوب أو اكتب رقمه:", options, slots, "form", "v17_4_brand_only_medicine_forms")
            if any(r.is_medicine for r in options) and len(strengths) > 1:
                return matcher_v3._ask("يوجد من هذا الدواء أكثر من جرعة. الرجاء تحديد الجرعة المطلوبة:", options, slots, "strength", "v17_4_brand_only_medicine_strengths")
            return matcher_v3._ask("شنو المنتج المطلوب من هذه الشركة؟ اكتب النوع أو اختر من القائمة:", options, slots, "product", "v17_4_brand_only_query")
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v17_4_brand_only_unknown_brand", query_slots=slots)
    if intent == "brand_type_only_query":
        return _ask_brand_type_only(slots, ci)
    if intent == "type_only_query":
        qtype = slots.cosmetic_type or slots.form
        options = [r for r in ci.records if r.is_cosmetic and (r.cosmetic_type or r.form) == qtype][:12]
        if options:
            return matcher_v3._ask("تقصد أي منتج بالضبط؟ اكتب الشركة أو الاستخدام المطلوب، أو اختر من القائمة:", options, slots, "product", "v17_4_type_only_query")
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v17_4_type_only_no_catalog", query_slots=slots)
    if intent == "need_based_query":
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v17_4_need_based_query_requires_clarification", query_slots=slots)
    if intent == "low_confidence_query":
        qtype = slots.cosmetic_type or slots.form
        if qtype:
            options = [r for r in ci.records if r.is_cosmetic and (r.cosmetic_type or r.form) == qtype][:12]
            if options:
                return matcher_v3._ask("الطلب غير محدد كفاية. اكتب اسم الشركة أو المنتج المطلوب:", options, slots, "product", "v17_4_low_confidence_type_query")
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v17_4_low_confidence_generic_query", query_slots=slots)
    return None


FORBIDDEN_VISION_OUTPUT_KEYS = {"price", "availability", "available", "stock", "recommendation", "alternative", "alternatives", "is_available"}


def _v17_4_vision_value(ai_data: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = ai_data.get(key)
        if val not in (None, ""):
            if isinstance(val, list):
                return " ".join(str(x) for x in val if str(x).strip())
            return str(val).strip()
    return ""


def _v17_4_has_forbidden_vision_claims(ai_data: Dict[str, Any]) -> bool:
    return any(k in ai_data and ai_data.get(k) not in (None, "", [], {}) for k in FORBIDDEN_VISION_OUTPUT_KEYS)


def _v17_4_strong_image_query(ai_data: Dict[str, Any]) -> Tuple[bool, str, str]:
    brand = normalize_product_text(_v17_4_vision_value(ai_data, "brand"))
    barcode = normalize_product_text(_v17_4_vision_value(ai_data, "barcode"))
    product_name = _v17_4_vision_value(ai_data, "product_name", "product_family")
    product_names = _v17_4_vision_value(ai_data, "product_names")
    form = _v17_4_vision_value(ai_data, "product_type", "form", "type")
    strength = _v17_4_vision_value(ai_data, "strength")
    size = _v17_4_vision_value(ai_data, "size")
    if barcode:
        return True, "barcode", barcode
    product_bits = " ".join(x for x in [product_name, product_names] if x).strip()
    norm_product_bits = normalize_product_text(product_bits)
    norm_form = normalize_product_text(form)
    if not brand or not product_bits:
        return False, "image_missing_brand_or_product_name", " ".join(x for x in [brand, product_bits, form] if x)
    if norm_product_bits in {"", norm_form, "cream", "gel", "lotion", "serum", "cleanser", "wash", "face", "skin"}:
        return False, "image_generic_words_only", " ".join(x for x in [brand, product_bits, form] if x)
    return True, "brand_product_fields", " ".join(x for x in [brand, product_bits, form, strength, size] if x)


def resolve_product_query_from_index(query: str, ci: CatalogIndex) -> MatchDecision:
    slots = matcher_v3.extract_query_slots(query)
    if not slots.cleaned_text or not ci.records:
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v17_5_empty_query_or_catalog", query_slots=slots)

    code_like = bool(re.fullmatch(r"[a-z]*\d+[a-z\d]*", slots.cleaned_text))
    if code_like:
        exact = matcher_v3._exact_candidates(slots, ci)
        if exact:
            decision = matcher_v3._resolve_candidates(exact, slots, ci, "v17_5_code_exact_first")
            decision = _variant_guard(decision, slots, ci)
            return _filter_clarification_by_strength(decision, slots, ci)
        return MatchDecision(DecisionType.NOT_AVAILABLE, confidence=0.0, reason="v17_5_code_like_not_found", query_slots=slots)

    # Brand-only/type-only/need-only aliases must not bypass clarification.
    if _v17_4_is_brand_only(slots) or _v17_4_is_type_only(slots) or _v17_4_is_need_based_only(slots):
        guarded = _v17_4_pre_guard(slots, ci)
        if guarded is not None:
            return _filter_clarification_by_strength(guarded, slots, ci)

    # Exact full name/alias/barcode may win before the brand+type-only guard.
    exact = matcher_v3._exact_candidates(slots, ci)
    if exact:
        decision = matcher_v3._resolve_candidates(exact, slots, ci, "v17_5_exact_first")
        decision = _variant_guard(decision, slots, ci)
        decision = _filter_clarification_by_strength(decision, slots, ci)
        return _v17_4_filter_cosmetic_alternative_decision(decision, slots, ci)

    guarded = _v17_4_pre_guard(slots, ci)
    if guarded is not None:
        return _filter_clarification_by_strength(guarded, slots, ci)

    decision = _resolve_product_query_core_from_index(query, ci)
    if decision.query_slots is None:
        decision.query_slots = slots
    if decision.decision_type == DecisionType.EXACT_MATCH and (_v17_4_is_brand_only(slots) or _v17_4_is_type_only(slots) or _v17_4_is_need_based_only(slots) or _v17_5_is_brand_type_only(slots)):
        return _v17_4_pre_guard(slots, ci) or MatchDecision(DecisionType.LOW_CONFIDENCE, reason="v17_5_generic_query_exact_blocked", query_slots=slots)
    if decision.decision_type == DecisionType.NOT_AVAILABLE and slots.is_cosmetic_query and (slots.cosmetic_type or slots.form):
        alts = _v17_4_strict_missing_cosmetic_alternatives(slots, ci.records)
        if alts:
            alt_decision = MatchDecision(DecisionType.COSMETIC_ALTERNATIVES, confidence=0.82, alternatives=[a.raw for a in alts], reason="v17_4_missing_cosmetic_strict_alternatives", query_slots=slots)
            return _v17_4_filter_cosmetic_alternative_decision(alt_decision, slots, ci)
    decision = _v17_4_filter_cosmetic_alternative_decision(decision, slots, ci)
    decision = _variant_guard(decision, slots, ci)
    decision = _filter_clarification_by_strength(decision, slots, ci)
    return decision


def resolve_product_query(query: str, catalog: Sequence[Dict[str, Any]]) -> MatchDecision:
    return resolve_product_query_from_index(query, build_catalog_index(catalog))


def resolve_image_extraction_from_index(ai_data: Dict[str, Any], ci: CatalogIndex) -> MatchDecision:
    ai_data = dict(ai_data or {})
    image_type = str(ai_data.get("image_type") or "unknown").lower().strip()
    image_quality = str(ai_data.get("image_quality") or ai_data.get("clarity") or "").lower().strip()
    try:
        confidence = float(ai_data.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0

    if ai_data.get("invalid_vision_output") or _v17_4_has_forbidden_vision_claims(ai_data):
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=0.0, reason="v17_5_invalid_vision_output_claims")
    if image_type in {"prescription", "prescription_or_unclear"}:
        return MatchDecision(DecisionType.IMAGE_UNCLEAR, confidence=confidence, reason="v17_4_image_prescription_needs_admin")
    if image_type in {"multiple_products", "shelf"} or image_quality in {"multiple_products", "multiple", "many_products"}:
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=confidence, reason="v17_4_image_multiple_products")
    if image_type in {"unclear", "other", "unknown"} or image_quality in {"bad", "blurry", "partial", "dark"} or confidence < 0.75:
        return MatchDecision(DecisionType.IMAGE_UNCLEAR, confidence=confidence, reason="v17_4_image_unclear")

    ok, evidence, query = _v17_4_strong_image_query(ai_data)
    if not ok:
        slots = matcher_v3.extract_query_slots(query)
        return MatchDecision(DecisionType.LOW_CONFIDENCE, confidence=confidence, reason=f"v17_4_{evidence}", query_slots=slots)
    decision = resolve_product_query_from_index(query, ci)
    decision.confidence = max(decision.confidence, confidence if decision.decision_type != DecisionType.NOT_AVAILABLE else decision.confidence)
    decision.reason = (decision.reason + "|" if decision.reason else "") + f"image_evidence={evidence}"
    return decision


def resolve_image_extraction(ai_data: Dict[str, Any], catalog: Sequence[Dict[str, Any]]) -> MatchDecision:
    return resolve_image_extraction_from_index(ai_data, build_catalog_index(catalog))

def build_catalog_quality_rows(catalog: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:  # type: ignore[override]
    ci = build_catalog_index(catalog)
    normalized_counts: Dict[str, int] = {}
    alias_counts: Dict[str, int] = {}
    for r in ci.records:
        normalized_counts[r.normalized_name] = normalized_counts.get(r.normalized_name, 0) + 1
        for a in r.aliases | r.image_keywords:
            alias_counts[a] = alias_counts.get(a, 0) + 1

    rows: List[Dict[str, Any]] = []
    for r in ci.records:
        issues: List[str] = []
        if not r.brand:
            issues.append("missing_brand")
        if not r.category:
            issues.append("missing_category")
        if r.is_medicine and not r.active_ingredient:
            issues.append("medicine_missing_active_ingredient")
        if r.is_medicine and not r.form:
            issues.append("medicine_missing_form")
        if r.is_medicine and not r.strength:
            issues.append("medicine_missing_strength")
        if r.is_cosmetic and not (r.cosmetic_type or r.form):
            issues.append("cosmetic_missing_product_type_form")
        if r.is_cosmetic and not r.use_case:
            issues.append("cosmetic_missing_use_case")
        if r.is_cosmetic and not r.skin_type:
            issues.append("cosmetic_missing_skin_type")
        if not r.aliases:
            issues.append("missing_aliases")
        if not r.image_keywords:
            issues.append("missing_ocr_keywords")
        if normalized_counts.get(r.normalized_name, 0) > 1:
            issues.append("duplicate_normalized_name")
        if any(alias_counts.get(a, 0) > 1 for a in (r.aliases | r.image_keywords)):
            issues.append("duplicate_alias_or_ocr_keyword")
        if not str(r.price or "").strip():
            issues.append("empty_price")
        else:
            try:
                price_num = float(re.sub(r"[^0-9.]", "", str(r.price).replace(",", ".")) or 0)
                if price_num <= 0 or price_num > 10000:
                    issues.append("suspicious_price")
            except Exception:
                issues.append("suspicious_price")
        if not matcher_v3._availability_ok(r.availability):
            issues.append("unavailable_or_unknown_availability")
        if not r.is_medicine and not r.is_cosmetic:
            issues.append("unclassified_category")
        ready = not issues
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
            "price": r.price,
            "available": r.availability,
            "ready": "yes" if ready else "no",
            "issues": ";".join(issues),
        })
    return rows


def generate_catalog_quality_report(catalog: Sequence[Dict[str, Any]], output_path: str = "catalog_quality_report.csv") -> str:  # type: ignore[override]
    rows = build_catalog_quality_rows(catalog)
    fieldnames = ["id", "name", "brand", "family", "active_ingredient", "form", "strength", "size", "category", "cosmetic_type", "use_case", "skin_type", "price", "available", "ready", "issues"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return output_path
