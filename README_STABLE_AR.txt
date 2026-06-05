# PriceBot stable-v15-final-safe-engine

نسخة نهائية آمنة مبنية على v14 strict matcher engine مع إصلاح جذري لتعليق event loop.

التغييرات الأساسية:
- matcher_v3 هو محرك القرار النهائي.
- لا fallback إلى matcher.safe_match في ردود الزبائن.
- إزالة matcher.inspect_query من المسار الحي للنص والصور.
- كل عمليات SQLite الحساسة في مسار الرسائل تعمل خارج event loop مع timeout.
- /health لا يعلق إذا قاعدة البيانات تأخرت.
- cleanup الدوري لا يحبس التطبيق.
- image matching لا يستخدم debug catalog scan ولا safe_match.

لا ترفع إلى GitHub:
.env
pricebot.db
*.db
*.sqlite
*.sqlite3
venv
media
backups
__pycache__
