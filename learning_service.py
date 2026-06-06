# -*- coding: utf-8 -*-
from __future__ import annotations
import database


def add_alias_from_failed_query(product_id: int, query: str) -> None:
    database.add_product_alias(product_id, query)
    database.log_audit("alias_added", "admin", "product", str(product_id), new_value=query)
