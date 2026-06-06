PriceBot stable-v15.1 FINAL SAFE ENGINE INDEX CACHE

Changes:
- matcher_v3 remains the final strict decision engine.
- No fallback to legacy safe_match for customer replies.
- Fixed v15 timeout_fallback by building matcher_v3 CatalogIndex once at startup and reusing it for every message.
- TEXT_TIMEOUT_SECONDS default increased to 12 seconds as a safety margin, but normal messages should finish much faster after index warmup.
- Added MATCHER_V3_INDEX_READY startup log.

Do not upload .env, pricebot.db, venv, media, backups, or __pycache__.
