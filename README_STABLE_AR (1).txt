PriceBot / WhatsPrice Bot - stable-v3

هذه نسخة نظيفة مخصصة لصيدلية بدر البشرية - أجدابيا.

ما تغير:
- تحسين matching للنص العربي والإنجليزي مع إزالة كلمات الطلب العامة مثل: متوفر، عندكم، بكم، كم سعر.
- حسم الاستعلامات العامة مثل CeraVe فقط أو cleanser فقط قبل تحميل المنتجات من قاعدة البيانات.
- بناء product index/cache عند startup: normalized_name_map, alias_map, brand_index, type_index, area_index.
- تقليل normalize المتكرر وتجهيز القوائم normalized مرة واحدة داخل matcher.py.
- منع التخمين عند الطلبات العامة مثل CeraVe فقط أو cleanser فقط.
- تشديد المطابقة حسب brand + type + area قبل أي fuzzy matching.
- دعم aliases وcompany وbrand وform وactive_ingredient وstrength وpack وimage_ocr_keywords/ocr_keywords/keywords.
- تحسين تحليل الصور عبر OpenRouter/Gemini Vision مع JSON واضح وretry للمفاتيح بدون طباعة الأسرار.
- بناء internal query من الصورة بدون إدخال الحجم أو target_area في المطابقة.
- بدائل الكوزمتك أصبحت من نفس النوع والمنطقة فقط، خصوصاً face cleanser.
- كل رسالة تنتهي برد نهائي: matched, unavailable, alternatives, unclear_image, fallback, timeout_fallback, error_fallback.
- migrations آمنة للجداول القديمة: products, orders, processed_messages, conversation_state, product_inquiries والجداول القديمة المشابهة.
- processed_messages لا تصبح done إلا بعد SEND_OK.
- per-phone lock يحافظ على ترتيب رسائل نفس الزبون.
- لوحة admin محمية فقط عبر PRICEBOT_ADMIN_KEY أو ADMIN_KEY ولا تستخدم مفتاحاً افتراضياً.
- بحث المنتجات في admin يتم على كل المنتجات مع pagination.
- رفع Excel/CSV أصبح safe upsert، وreplace_all لا يتم إلا بعد validation وbackup وتأكيد صريح.
- إضافة acceptance_tests.py لاختبارات محلية بقاعدة بيانات مؤقتة.
- إضافة اختبار أداء على 4991 منتج داخل acceptance_tests.py.

التشغيل على السيرفر:
1. ارفع ملفات النسخة إلى /opt/pricebot مع الحفاظ على:
   .env
   pricebot.db
   media
   backups
2. ثبّت المتطلبات إذا لزم:
   pip install -r requirements.txt
3. شغّل الخدمة كما هي:
   uvicorn app:app --host 127.0.0.1 --port 8090

ملاحظات:
- لا يحتوي هذا التسليم على .env أو أي مفاتيح أو قاعدة بيانات.
- لا يحتاج تغيير Meta أو webhook أو Caddy أو systemd.
- الموديل الافتراضي للصور: google/gemini-2.5-flash-lite.
