# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Iterable, Tuple, List
from services.catalog_quality import quality_gate


def evaluate_catalog_before_import(products: Iterable[dict]) -> Tuple[str, List[str], dict]:
    """Return ACCEPT / ACCEPT_WITH_WARNINGS / REJECT before writing products."""
    return quality_gate(products)
