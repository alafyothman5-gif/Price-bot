PriceBot FINAL STRICT V17.5 PRODUCTION REVIEW

الهدف:
نسخة مراجعة إنتاجية قبل الاعتماد، مبنية على V17.4 بدون إعادة legacy fuzzy fallback وبدون كسر سياسة المطابقة المحافظة.

أهم الإصلاحات:
1) Vision invalid output guard
- إذا رجع نموذج الصور price / availability / recommendation / alternatives يتم رفض نتيجة Vision فوراً.
- القرار يصبح LOW_CONFIDENCE بسبب v17_5_invalid_vision_output_claims.

2) matcher_v4.py clean rewrite
- تم إزالة التعريفات المكررة الخطيرة.
- توجد دالة واحدة فقط لكل entry point مهم:
  resolve_product_query_from_index
  resolve_product_query
  resolve_image_extraction_from_index
  resolve_image_extraction
  _v17_4_pre_guard
  _v17_4_filter_cosmetic_alternative_decision
  _v17_4_strong_image_query
  build_catalog_quality_rows
  generate_catalog_quality_report

3) brand + cosmetic type only
- Cerave cream / Cerave cleanser / Rilastil lotion / Bioderma cleanser لا ترجع سعر حتى لو الكتالوج فيه منتج واحد.
- الاسم الكامل أو alias كامل أو product family واضح ما زال يسمح بالمطابقة.

4) Medicine clarification options
- إذا المستخدم كتب strength مثل: فلاجيل 500، خيارات التوضيح تُفلتر على نفس الجرعة فقط.
- لا تظهر جرعات أخرى مثل 125 أو 250 في قائمة 500.

5) Real Vision manual test tool
- تمت إضافة:
  tools/run_real_vision_tests.py
- الاستخدام:
  python tools/run_real_vision_tests.py --cases vision_real_test_cases.xlsx --out vision_real_test_report.xlsx
- لا يعمل داخل pytest لأنه يحتاج API وصور اختبار حقيقية.
- إذا لا يوجد API key يخرج برسالة واضحة بدون طباعة أسرار.

6) Image cache
- exact hash cache بقي كما هو.
- تمت إضافة perceptual hash lookup محافظ لمسافة hamming <= 5.
- لا يستخدم perceptual cache إلا لقرارات EXACT_MATCH و NOT_AVAILABLE عالية الثقة.
- TTL:
  EXACT_MATCH = 90 days
  NOT_AVAILABLE = 14 days
  LOW_CONFIDENCE = 1 day
  IMAGE_UNCLEAR = 1 day

7) Test endpoints
- /test_local و /test_local_image مغلقة افتراضياً.
- تعمل فقط عند:
  PRICEBOT_DEBUG_ENDPOINTS=true

8) WhatsApp webhook signature
- POST /webhook/whatsapp يتحقق من X-Hub-Signature-256 إذا META_APP_SECRET موجود أو إذا PRICEBOT_REQUIRE_META_SIGNATURE=true أو PRICEBOT_ENV=production.
- GET webhook verification لم يتغير.
- لا توجد secrets داخل الكود.

اختبارات نجحت:
python -m compileall -q .
python -m pytest -q
python acceptance_tests_v3.py
python acceptance_tests_v4.py
python acceptance_tests_final_v17.py
python acceptance_tests_final_v17_1.py
python acceptance_tests_final_v17_2.py
python acceptance_tests_final_v17_4.py
python acceptance_tests_final_v17_5.py

ملاحظات مهمة قبل الإنتاج:
- ضع META_APP_SECRET في .env على السيرفر حتى يتم تفعيل حماية توقيع Meta.
- لا تضع secret داخل GitHub.
- لا تشغل PRICEBOT_DEBUG_ENDPOINTS=true في الإنتاج.
