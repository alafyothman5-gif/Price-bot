# -*- coding: utf-8 -*-
from __future__ import annotations
from collections import Counter
from datetime import datetime
from typing import List


def summarize_decisions(rows: List[dict]) -> dict:
    c = Counter(str(r.get("decision") or r.get("status") or "unknown") for r in rows or [])
    total = sum(c.values()) or 1
    return {k: {"count": v, "pct": round(v * 100 / total, 1)} for k, v in c.items()}


def today_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")
