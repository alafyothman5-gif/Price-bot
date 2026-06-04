PriceBot / WhatsPrice Bot - stable-v6-hardening

نسخة حماية واستقرار مبنية على stable-v5، مع إصلاحات جوهرية:

- General Product Resolver: أي رسالة ليست تحية/حجز/إلغاء تعتبر طلب منتج، تبحث في Excel، وإذا لا يوجد تطابق قوي تقول غير متوفر.
- المنتجات الرقمية والأكواد مثل 123 / 1,2,3 / ABC123 تبحث في name/aliases/OCR/code/barcode/sku قبل اعتبارها noise.
- دعم code/barcode/sku/item_code/product_code داخل المطابقة ورفع Excel.
- PHARMACY_HEADER و PHARMACY_NAME من .env بدل hard-code.
- Queue bounded عبر PRICEBOT_QUEUE_MAXSIZE لمنع flood.
- Rate limiting لكل رقم عبر PRICEBOT_RATE_LIMIT_MESSAGES و PRICEBOT_RATE_LIMIT_WINDOW_SECONDS.
- user_locks تعمل كـ LRU مع cleanup دوري حتى لا تتراكم في الذاكرة.
- processed_messages cleanup للأقدم من 30 يوم عند startup ودورياً.
- health لا يعمل full table scan؛ يستخدم COUNT وكاش قصير.
- FastAPI lifespan بدل @app.on_event.
- AI JSON validation + retry للمفاتيح + تسجيل ai_usage في قاعدة البيانات.
- تسجيل product_inquiries لكل رسالة: matched/unavailable/fallback/error/timeout.
- لوحة Admin احترافية مع Cookie login بدل تمرير key في كل روابط اللوحة.
- لا تزال /admin?key=... تعمل مرة واحدة لتسجيل cookie ثم يتم التحويل إلى /admin بدون key.
- لوحة analytics تعرض الطلبات، المنتجات الأكثر طلباً، الاستعلامات الفاشلة، AI usage، تكلفة تقريبية.
- تعديل منتج واحد من الأدمن، وتعديل سعر مباشرة بدون رفع Excel.
- إشعار أدمن للطلبات المعلقة أكثر من PRICEBOT_STALE_ORDER_HOURS.
- قاعدة البيانات لم تعد تعمل init_db عند import؛ يتم تشغيل init_db في app lifespan أو acceptance_tests.

متغيرات اختيارية في .env:
PHARMACY_NAME=صيدلية بدر البشرية
PHARMACY_HEADER=🌿 صيدلية بدر البشرية
PRICEBOT_QUEUE_MAXSIZE=500
PRICEBOT_WORKERS=5
PRICEBOT_RATE_LIMIT_MESSAGES=20
PRICEBOT_RATE_LIMIT_WINDOW_SECONDS=60
PRICEBOT_LOCK_CACHE_MAX=2000
PRICEBOT_STALE_ORDER_HOURS=6
OPENROUTER_ESTIMATED_COST_PER_1K_TOKENS=0
PRICEBOT_ADMIN_SESSION_SALT=change_me_optional

لا يحتوي هذا التسليم على:
.env
pricebot.db
venv
media
backups
__pycache__

اختبارات:
python -m py_compile app.py admin.py database.py matcher.py acceptance_tests.py
python acceptance_tests.py
