PriceBot Product Intelligence Engine V4

هذا الإصدار يضيف matcher_v4.py فوق matcher_v3 المحافظ، ولا يرجع إلى legacy safe_match في مسار ردود الزبائن.

أهم التغييرات:
- لا يتم عرض السعر أو التوفر إلا بعد حل هوية المنتج بالكامل.
- Brand-only مثل CeraVe أو Panadol يسأل للتوضيح ولا يختار عشوائياً.
- Type-only مثل غسول أو lotion يسأل للتوضيح.
- الأدوية متعددة الشكل أو الجرعة تسأل عن الشكل/الجرعة قبل السعر.
- الكوزمتك متعدد النوع/الحجم يسأل عن النوع/الحجم قبل السعر.
- المنتجات المحددة غير الموجودة مثل Rilastil xerolact PB ترجع NOT_AVAILABLE ولا تطابق منتجاً قريباً.
- بدائل الأدوية ممنوعة افتراضياً. substitution_group محفوظ للتطوير الآمن لاحقاً ولا يستخدم تلقائياً لإعطاء بديل.
- بدائل الكوزمتك مقيدة بنفس النوع/الاستخدام/الجلد ولا توجد cross-type suggestions.
- AI Vision يستخرج JSON فقط. القرار النهائي من الكتالوج المحلي عبر matcher_v4.
- الصور غير الواضحة أو التي لا تحتوي evidence قوي تطلب صورة أمامية أو اسم مكتوب.
- تمت إضافة product_images و alias_suggestions في database.py كمهاجرات آمنة عند تشغيل init_db.
- تمت إضافة صفحات Admin:
  /admin/catalog-quality
  /admin/catalog-quality.csv
  /admin/alias-learning

فحص محلي مطلوب قبل التشغيل:
python -m py_compile app.py database.py matcher.py matcher_v3.py matcher_v4.py
python acceptance_tests_v4.py

مهم:
- لا يحتوي هذا ZIP على .env أو tokens أو venv أو backups أو pricebot.db حقيقي.
- عند النشر على السيرفر، احتفظ بقاعدة /opt/pricebot/pricebot.db الموجودة ولا تستبدلها من GitHub.
