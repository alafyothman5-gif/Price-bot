# -*- coding: utf-8 -*-
"""Catalog Quality Gate and V19 catalog diagnostics.

This module is intentionally deterministic and conservative. It never invents
product facts; it only scores what is present in the catalog and reports what
needs human review.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

GENERIC_ALIAS_BLOCKLIST = {
    "cream", "gel", "cleanser", "lotion", "غسول", "كريم", "لوشن", "serum", "سيروم",
    "shampoo", "شامبو", "tablet", "syrup", "capsule", "دواء", "علاج", "medicine",
}
MEDICINE_FORMS = {"tablet", "capsule", "syrup", "suspension", "injection", "drops", "cream", "ointment", "gel", "suppository", "pessary", "spray", "solution", "sachet"}
COSMETIC_FORMS = {"cleanser", "face wash", "cream", "lotion", "serum", "gel", "shampoo", "conditioner", "sunscreen", "toner", "mask", "scrub", "oil", "moisturizer", "balm", "body wash", "deodorant"}
REQUIRED_SCHEMA = [
    "product_id", "name", "normalized_name", "brand", "company", "product_family", "category", "subcategory",
    "active_ingredient", "form", "strength", "size", "pack", "barcode", "aliases", "ocr_keywords",
    "use_case", "skin_type", "body_area", "age_group", "gender", "medicine_route", "requires_clarification",
    "available", "price", "currency", "substitution_group_id", "is_substitutable", "image_refs",
    "review_status", "review_notes", "last_updated", "merchant_id",
]


def normalize_text(text: str) -> str:
    value = str(text or "").strip().lower()
    table = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    value = value.translate(table)
    for src, dst in {"أ":"ا", "إ":"ا", "آ":"ا", "ة":"ه", "ى":"ي", "ؤ":"و", "ئ":"ي", "ٱ":"ا", "ڤ":"ف", "گ":"ك", "ک":"ك", "ی":"ي"}.items():
        value = value.replace(src, dst)
    value = re.sub(r"[^\w\u0600-\u06ff.%/+-]+", " ", value)
    return " ".join(value.split())


def split_tokens(value: str) -> List[str]:
    return [x.strip() for x in re.split(r"[,،|;\n]+", str(value or "")) if x.strip()]


def _is_medicine(row: dict) -> bool:
    category = normalize_text(row.get("category"))
    return category == "medicine" or bool(str(row.get("active_ingredient") or "").strip())


def _is_cosmetic(row: dict) -> bool:
    category = normalize_text(row.get("category"))
    form = normalize_text(row.get("form"))
    return category == "cosmetic" or form in COSMETIC_FORMS


def _price_ok(value) -> bool:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return False
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        return False
    try:
        return float(m.group(0)) >= 0
    except Exception:
        return False


def analyze_products(products: Iterable[dict]) -> dict:
    rows = [dict(p) for p in products or []]
    total = len(rows)
    norm_names = Counter(normalize_text(r.get("normalized_name") or r.get("name")) for r in rows if normalize_text(r.get("normalized_name") or r.get("name")))
    alias_map: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        for field in ("aliases", "ocr_keywords", "image_ocr_keywords"):
            for alias in split_tokens(r.get(field, "")):
                n = normalize_text(alias)
                if n:
                    alias_map[n].append(r)
    duplicate_aliases = {k:v for k, v in alias_map.items() if len({str(x.get("id") or x.get("product_id") or x.get("name")) for x in v}) > 1}

    issue_counts = Counter()
    reviewed = []
    missing_form = missing_brand = medicine_missing_strength = missing_price = 0
    medicines = cosmetics = 0
    for r in rows:
        issues = []
        category = normalize_text(r.get("category"))
        form = normalize_text(r.get("form"))
        if not str(r.get("brand") or r.get("company") or "").strip():
            issues.append("missing_brand"); missing_brand += 1
        if not category:
            issues.append("missing_category")
        if not form:
            issues.append("missing_form_or_type"); missing_form += 1
        if not _price_ok(r.get("price")):
            issues.append("missing_or_invalid_price"); missing_price += 1
        name_norm = normalize_text(r.get("normalized_name") or r.get("name"))
        if name_norm and norm_names[name_norm] > 1:
            issues.append("duplicate_normalized_name")
        aliases = [normalize_text(a) for a in split_tokens(r.get("aliases", ""))]
        if not aliases:
            issues.append("missing_aliases")
        if any(a in GENERIC_ALIAS_BLOCKLIST for a in aliases):
            issues.append("dangerous_generic_alias")
        if any(a in duplicate_aliases for a in aliases):
            issues.append("duplicate_alias")
        if _is_medicine(r):
            medicines += 1
            if not form:
                issues.append("medicine_missing_form")
            if not str(r.get("strength") or "").strip():
                issues.append("medicine_missing_strength"); medicine_missing_strength += 1
            if not str(r.get("active_ingredient") or "").strip():
                issues.append("medicine_missing_active_ingredient")
        if _is_cosmetic(r):
            cosmetics += 1
            if not form:
                issues.append("cosmetic_missing_type")
            if not str(r.get("use_case") or "").strip():
                issues.append("cosmetic_missing_use_case")
            if not str(r.get("ocr_keywords") or r.get("image_ocr_keywords") or "").strip():
                issues.append("missing_ocr_keywords")
        for issue in issues:
            issue_counts[issue] += 1
        r["quality_issues"] = ";".join(sorted(set(issues)))
        r["review_status"] = r.get("review_status") or ("needs_review" if issues else "approved")
        reviewed.append(r)

    dangerous_duplicate_aliases = len([k for k in duplicate_aliases if k in GENERIC_ALIAS_BLOCKLIST or len(k.split()) <= 2])
    duplicate_name_groups = sum(1 for _, c in norm_names.items() if c > 1)
    duplicate_name_rows = sum(c for _, c in norm_names.items() if c > 1)
    form_missing_ratio = missing_form / max(total, 1)
    brand_missing_ratio = missing_brand / max(total, 1)
    med_strength_ratio = medicine_missing_strength / max(medicines, 1)
    price_missing_ratio = missing_price / max(total, 1)

    decision = "ACCEPT"
    reasons = []
    if form_missing_ratio > 0.20:
        decision = "REJECT"; reasons.append("أكثر من 20% من المنتجات بدون form/type")
    if med_strength_ratio > 0.10:
        decision = "REJECT"; reasons.append("أكثر من 10% من الأدوية بدون strength")
    if brand_missing_ratio > 0.10:
        decision = "REJECT"; reasons.append("أكثر من 10% من المنتجات بدون brand")
    if dangerous_duplicate_aliases:
        decision = "REJECT"; reasons.append("يوجد duplicate aliases خطيرة")
    if duplicate_name_groups and duplicate_name_rows / max(total, 1) > 0.05:
        decision = "REJECT"; reasons.append("أسماء مكررة بدون تمييز كافٍ")
    if price_missing_ratio > 0:
        decision = "REJECT"; reasons.append("يوجد أسعار فارغة أو غير رقمية")
    if decision == "ACCEPT" and any(issue_counts[k] for k in ["missing_ocr_keywords", "cosmetic_missing_use_case", "duplicate_normalized_name"]):
        decision = "ACCEPT_WITH_WARNINGS"
        reasons.append("يوجد تحذيرات جودة تحتاج مراجعة")

    score = max(0, min(100, round(100 - (len([r for r in reviewed if r.get("quality_issues")]) / max(total, 1) * 100))))
    return {
        "decision": decision,
        "reasons": reasons,
        "total": total,
        "issue_counts": dict(issue_counts),
        "review_rows": [r for r in reviewed if r.get("quality_issues")],
        "duplicate_aliases": {k: len(v) for k, v in duplicate_aliases.items()},
        "duplicate_name_groups": duplicate_name_groups,
        "duplicate_name_rows": duplicate_name_rows,
        "catalog_readiness_score": score,
        "medicines": medicines,
        "cosmetics": cosmetics,
    }


def quality_gate(products: Iterable[dict]) -> Tuple[str, List[str], dict]:
    report = analyze_products(products)
    return report["decision"], list(report["reasons"]), report


def report_to_csv(report: dict) -> str:
    output = io.StringIO()
    fieldnames = ["id", "product_id", "name", "brand", "category", "form", "strength", "size", "price", "review_status", "quality_issues"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in report.get("review_rows", []):
        writer.writerow({k: row.get(k, "") for k in fieldnames})
    return output.getvalue()
