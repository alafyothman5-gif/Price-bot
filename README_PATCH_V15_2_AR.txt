PriceBot stable-v15.2 STARTUP SAFE MATCHER INDEX

ما تم إصلاحه:
1) لم يعد Uvicorn ينتظر بناء MATCHER_V3_INDEX أثناء startup.
2) /health يفتح بسرعة، وبناء فهرس matcher_v3 يتم في background task.
3) إذا وصل طلب قبل جاهزية الفهرس، يرد البوت برسالة آمنة قصيرة ولا يعلق.
4) لا يوجد fallback إلى matcher.safe_match القديم في ردود النصوص أو الصور.
5) matcher_v3 يستخدم process-level cache جاهز ولا يعيد فحص الكتالوج في كل رسالة.
6) تم تسريع بناء matcher_v3 عبر build_catalog_index_direct و caching للـ normalize.
7) /health يعرض matcher_v3_ready / matcher_v3_building / matcher_v3_records / matcher_v3_error.

اختبارات تم تشغيلها:
python -m py_compile app.py admin.py database.py matcher.py matcher_v2.py matcher_v3.py product_intelligence.py catalog_quality_report.py acceptance_tests_v2.py acceptance_tests_v3.py
python acceptance_tests_v3.py
python acceptance_tests_v2.py

مهم:
لا ترفع .env أو pricebot.db أو venv أو backups أو media/uploads إلى GitHub.
انشر الكود فقط، واحتفظ بقاعدة بيانات السيرفر الحالية.
