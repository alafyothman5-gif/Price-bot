# PriceBot READY Fast Startup Fix

هذه النسخة معدلة حتى لا يعلق التشغيل عند:
`Waiting for application startup`

التعديلات الأساسية:
- منع بناء فهرس 4991 منتج أثناء Startup بشكل blocking.
- بناء فهرس V4 strict في الخلفية بعد تشغيل FastAPI.
- تسريع بناء الفهرس بإلغاء cache-key الضخم داخل matcher_v3.
- الحفاظ على سلوك V4 المحافظ: لا fallback عشوائي، لا سعر قبل تحديد المنتج، ولا بدائل أدوية.
- ملف خدمة systemd نظيف يشغل: `python -m uvicorn app:app`.

طريقة الاستخدام:
1. ارفع محتوى هذا الملف إلى GitHub repo.
2. شغّل الأمر الموجود في `DEPLOY_PRICEBOT_V4_ONE_COMMAND.txt` على السيرفر.
3. يجب أن تظهر `active (running)` و `/health` يعمل.
