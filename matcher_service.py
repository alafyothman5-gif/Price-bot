# -*- coding: utf-8 -*-
"""Thin V19 service wrapper around the accepted V18 matcher.
Do not add fuzzy fallback here; this wrapper exists for future route separation.
"""
from __future__ import annotations
import matcher_v4 as matcher

resolve_text = matcher.resolve_product_query_from_index
resolve_image = matcher.resolve_image_extraction_from_index
build_catalog_index = matcher.build_catalog_index
