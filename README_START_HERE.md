# PriceBot Final Stable Build — No Merchant Code Change UI

هذه نسخة نهائية نظيفة جاهزة للرفع إلى GitHub. لا ترفع ملفات الأسرار أو قاعدة البيانات.

## أهم الميزات

- بوت واتساب للاستعلام عن السعر والتوفر والحجز.
- منع النصائح الطبية والجرعات بالكامل.
- قراءة صور المنتجات عبر Gemini عند توفر المفتاح.
- الروشتات والصور غير الواضحة تتحول للصيدلي/الأدمن.
- SQLite `pricebot.db` للمنتجات والطلبات والذاكرة والكاش والإحصائيات.
- ذاكرة وكاش للأسئلة والصور لتقليل استخدام AI.
- دعم الأنواع والبدائل والشركات والتركيزات لكل الأدوية.
- لوحة أدمن كاملة لك فقط.
- لوحة تاجر منفصلة بدخول برمز ثابت افتراضي يمكن تغييره يدويًا من ملف .env فقط عند الحاجة.
- رابط واتساب و QR للزبائن داخل لوحة التاجر.
- إحصائيات أكثر المنتجات سؤالاً اليوم/الأسبوع/الشهر.
- تقرير يومي واتساب للأدمن.
- الطلب لا يعتبر مؤكداً حتى يضغط التاجر/الأدمن تأكيد.

## لا ترفع إلى GitHub

- `.env`
- `pricebot.db`
- `*.db-wal`
- `*.db-shm`
- `venv/`
- `__pycache__/`
- `*.pyc`
- ملفات النسخ الاحتياطي

## أمر التشغيل على السيرفر

بعد رفع الملفات إلى GitHub وتشغيل git pull أو نشر النسخة:

```bash
cd /opt/pricebot && bash DEPLOY_ON_SERVER.sh
```

لو تريد نشر كامل من GitHub مع الحفاظ على `.env` وقاعدة البيانات الحالية، استخدم سكربت النشر الذي أعطاه لك ChatGPT في المحادثة.

## الروابط الافتراضية

لوحة الأدمن:

```text
https://46.101.148.246.sslip.io/admin?key=PriceBotAdmin2026
```

لوحة التاجر:

```text
https://46.101.148.246.sslip.io/merchant/login
```

رمز التاجر الافتراضي:

```text
BADR2026
```

رابط الزبائن:

```text
https://wa.me/218918874659
```

## إعدادات مهمة في `.env`

```text
PRICEBOT_ADMIN_KEY=PriceBotAdmin2026
MERCHANT_CODE=BADR2026
CUSTOMER_WHATSAPP_NUMBER=218918874659
ADMIN_NOTIFY_PHONE=2189XXXXXXXX
WHATSAPP_ACCESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
AI_ENABLED=yes
AI_PROVIDER_ORDER=gemini,openrouter,groq
AI_GEMINI_KEYS=
```

## ملف المنتجات

الأعمدة المفضلة:

```text
name,aliases,active_ingredient,company,form,strength,pack,price,available,notes,image
```

كلما كان الملف منظمًا بهذه الأعمدة، كان البوت أفضل في التفريق بين الأصناف والبدائل.


## ملاحظة عن رمز التاجر

تم إلغاء تغيير الرمز من الواجهة للحفاظ على الاستقرار. الرمز الافتراضي `BADR2026`، ويمكن تغييره يدويًا فقط من `.env` عبر `MERCHANT_CODE` إذا احتجت لاحقًا.
