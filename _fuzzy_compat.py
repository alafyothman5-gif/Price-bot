"""Shared rapidfuzz compatibility fallback for PriceBot matchers."""
from __future__ import annotations

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
        short, long = (a, b) if len(a) <= len(b) else (b, a)
        if short in long:
            return 100
        window = max(len(short), 1)
        return max(
            difflib.SequenceMatcher(None, short, long[i:i + window]).ratio() * 100
            for i in range(max(len(long) - window + 1, 1))
        )

    @staticmethod
    def token_set_ratio(a, b):
        sa, sb = set(str(a or "").split()), set(str(b or "").split())
        if not sa or not sb:
            return 0
        inter = sa & sb
        if not inter:
            return 0
        return len(inter) / max(len(sa), len(sb)) * 100

    @staticmethod
    def token_sort_ratio(a, b):
        return difflib.SequenceMatcher(
            None,
            " ".join(sorted(str(a or "").split())),
            " ".join(sorted(str(b or "").split())),
        ).ratio() * 100


fuzz = _FuzzFallback()
