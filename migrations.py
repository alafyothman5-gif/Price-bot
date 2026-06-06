# -*- coding: utf-8 -*-
from __future__ import annotations
import database


def run_safe_migrations() -> None:
    database.init_db()
