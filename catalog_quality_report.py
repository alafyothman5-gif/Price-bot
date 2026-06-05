#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate catalog_quality_report.csv for PriceBot products."""
from __future__ import annotations

import sys
import database
import matcher_v3


def main() -> None:
    output = sys.argv[1] if len(sys.argv) > 1 else "catalog_quality_report.csv"
    products = database.load_products()
    path = matcher_v3.generate_catalog_quality_report(products, output)
    print(f"CATALOG_QUALITY_REPORT_OK: {path}")


if __name__ == "__main__":
    main()
