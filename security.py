# -*- coding: utf-8 -*-
from __future__ import annotations
import re


def mask_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if not digits:
        return ""
    if len(digits) < 7:
        return "MASKED"
    return f"{digits[:5]}****{digits[-3:]}"


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return "HIDDEN" if len(value) < 8 else f"{value[:4]}...HIDDEN"
