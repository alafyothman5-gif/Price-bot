PriceBot FINAL STRICT V17.4 — Matching + Vision Guard

هذه نسخة محافظة مبنية فوق V17.3/V17.2 ولا تغيّر إعدادات WhatsApp/Meta/OpenRouter/Caddy/.env/pricebot.db.
التركيز فقط على مشاكل المطابقة والصور وجودة الكتالوج.

ما تم تنفيذه:
1) Matching
- منع أي exact product من brand-only مثل: Cerave / Rilastil.
- منع أي exact product من type-only مثل: غسول / كريم / لوشن / face wash.
- السماح بـ exact فقط عند وجود اسم/alias/barcode واضح أو منتج محدد بالكامل.
- fuzzy typo rescue لا يعمل إلا داخل نفس brand/type/family ولا يرجع نتائج عامة.
- Specific Product Guard: المنتج المحدد غير الموجود يرجع NOT_AVAILABLE بدون منتجات عشوائية.
- Medicine Variant Resolver: الدواء يسأل عن الشكل أو الجرعة إذا ناقصة.
- لا بدائل أدوية تلقائية.
- Cosmetic Alternatives مفلترة: نفس cosmetic type فقط، ومع علاقة قوية: نفس brand أو use_case أو skin_type أو family tokens.
- لا سعر ولا توفر في ASK_CLARIFICATION.

2) Vision
- Vision extraction فقط، لا سعر ولا توفر ولا بدائل من AI.
- Prompt محدث: Return JSON only / do not guess availability / do not guess price / do not recommend alternatives.
- دعم structured fields: brand, product_name, product_family, form, strength, size, category, visible_text, confidence, image_quality.
- LOW_CONFIDENCE إذا الصورة فيها كلمات عامة فقط مثل cream/gel/face/50ml.
- IMAGE_UNCLEAR إذا confidence < 0.75 أو الصورة blurry/partial/dark.
- multiple_products يرجع LOW_CONFIDENCE/ASK بدل اختيار منتج عشوائي.
- صورة منتج واضح غير موجود: NOT_AVAILABLE أو بدائل كوزمتك صارمة فقط.
- إضافة image_cache في SQLite لتقليل استدعاءات Vision عند تكرار نفس الصورة.

3) Catalog Quality
- /admin/catalog-quality تعرض عدد المنتجات، الجاهزة، التي تحتاج مراجعة، ومشاكل الأعمدة.
- تحميل CSV: /admin/catalog-quality.csv
- تحميل XLSX: /admin/catalog-quality.xlsx
- يكشف: missing brand/category/form/strength/use_case/skin_type/aliases/ocr_keywords، duplicates، prices، availability.

4) اختبارات
- acceptance_tests_final_v17_4.py
- tools/run_vision_acceptance_tests.py

أوامر اختبار محلية:
python -m py_compile app.py matcher.py matcher_v4.py database.py admin.py matcher_v3.py matcher_v2.py
pytest -q
python acceptance_tests_v4.py
python acceptance_tests_final_v17.py
python acceptance_tests_final_v17_1.py
python acceptance_tests_final_v17_2.py
python acceptance_tests_final_v17_4.py

ملاحظات مهمة:
- لا يوجد ملف كود يضمن صفر أخطاء إذا الكتالوج ناقص. دقة البوت تعتمد على جودة columns داخل products.
- هذه النسخة لا تمس MedMCQ.
- لا ترفع pricebot.db إلى GitHub ولا تستبدل قاعدة السيرفر.
