PriceBot / WhatsPrice Bot - stable-v4-admin

نسخة مستقرة مبنية على stable-v3 مع لوحة أدمن احترافية وإصلاح توافق قاعدة البيانات القديمة.

ما تغير في هذه النسخة:
- تثبيت إصلاح conversation_state.namespace و user_key داخل database.py حتى لا يظهر خطأ NOT NULL على قاعدة السيرفر القديمة.
- لوحة أدمن جديدة بتصميم احترافي ومتجاوب مع الهاتف.
- إحصائيات رئيسية: طلبات اليوم، آخر 7 أيام، آخر 30 يوم، الطلبات قيد الانتظار، المكتملة، الملغاة، ومعدل الإكمال.
- تحليل أكثر المنتجات طلباً وقيمتها التقريبية.
- تحليل أكثر الزبائن طلباً.
- صحة ملف المنتجات: منتجات بلا سعر، بلا brand، بلا form، بلا aliases/OCR، وتكرار أسماء محتمل.
- أكثر البراندات والتصنيفات وجوداً.
- صفحة /admin/analytics للإحصائيات المتقدمة.
- الحفاظ على حماية الأدمن عبر PRICEBOT_ADMIN_KEY أو ADMIN_KEY فقط.
- الحفاظ على رفع Excel/CSV الآمن مع backup وvalidation وsafe upsert.
- لا يوجد أي .env أو توكن أو قاعدة بيانات داخل التسليم.

الملفات:
- app.py
- database.py
- matcher.py
- admin.py
- acceptance_tests.py
- requirements.txt
- start_pricebot.sh

التشغيل:
- لا تغير Meta ولا Caddy ولا webhook.
- ارفع الملفات إلى GitHub بالأسماء الصحيحة.
- على السيرفر حافظ على: .env و pricebot.db و media و backups و venv.
- شغل بنفس خدمة pricebot.service الحالية.

فحص قبل التشغيل:
python -m py_compile app.py database.py matcher.py admin.py acceptance_tests.py
python acceptance_tests.py

نتيجة الاختبار في هذه النسخة عند التجهيز: ACCEPTANCE_TESTS_OK.
