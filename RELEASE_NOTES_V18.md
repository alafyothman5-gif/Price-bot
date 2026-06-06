# RELEASE NOTES — PriceBot FINAL V18 Launch Ready

## نوع النسخة
نسخة إطلاق تجريبي Production Pilot. يجب اختبارها على كتالوج الصيدلية الحقيقي وصور منتجات حقيقية قبل البيع العام الواسع.

## ما تغير من V17.5 إلى V18
- إضافة حزمة نشر نهائية:
  - `deploy_pricebot_v18.sh`
  - `rollback_pricebot.sh`
  - `backup_pricebot.sh`
  - `smoke_test_pricebot.sh`
- إضافة `.env.example` واضح بدون أسرار.
- إضافة `.gitignore` يمنع رفع `.env` و `pricebot.db` و `venv` و backups.
- إضافة `README_DEPLOY_V18.md` و `RELEASE_NOTES_V18.md`.
- إضافة `acceptance_tests_final_v18.py`.

## ما تم إصلاحه أو تقويته
- حماية لوحة الأدمن بـ CSRF لكل POST مهم.
- rate limit لتسجيل دخول الأدمن.
- session expiry لمدة 8 ساعات افتراضياً.
- cookies آمنة في production/HTTPS: HttpOnly + SameSite=Lax + Secure.
- `/health` أصبح مختصراً ولا يعرض أسراراً أو تفاصيل قاعدة البيانات.
- logging صار يخفي التوكنات والأسرار ويعمل masking للأرقام.
- migration آمن يعمل backup تلقائي قبل تعديلات قاعدة البيانات الإضافية.
- دعم رفع CSV/XLSX، ومحاولة دعم XLS مع رسالة واضحة عند الحاجة.
- صفحة Catalog Quality تعرض مؤشرات أكثر: missing brand/category/form/strength/active ingredient/use/aliases/OCR، التكرارات، والأسعار المشبوهة.

## ما لم يتغير
- لم تتم إعادة كتابة Matching/Vision.
- لم يتم إرجاع legacy fuzzy fallback.
- القرارات الأساسية بقيت:
  - EXACT_MATCH
  - ASK_CLARIFICATION
  - NOT_AVAILABLE
  - COSMETIC_ALTERNATIVES
  - LOW_CONFIDENCE
  - IMAGE_UNCLEAR
- لا سعر عند الغموض.
- لا بدائل دوائية تلقائية.
- بدائل الكوزمتك تبقى محافظة حسب النوع والاستخدام.
- Vision يبقى extraction-only ولا يقرر السعر أو التوفر.

## اختبارات يجب تشغيلها
```bash
python -m compileall -q .
python -m pytest -q
python acceptance_tests_v3.py
python acceptance_tests_v4.py
python acceptance_tests_final_v17.py
python acceptance_tests_final_v17_1.py
python acceptance_tests_final_v17_2.py
python acceptance_tests_final_v17_4.py
python acceptance_tests_final_v17_5.py
python acceptance_tests_final_v18.py
```

## قيود النسخة
- اختبار Vision الحقيقي يحتاج صوراً حقيقية وملف `vision_real_test_cases.xlsx` ومفتاح OpenRouter.
- لا يوجد ضمان تجاري واسع قبل اختبارها على كتالوج كامل ومنظف وصور منتجات حقيقية من السوق.
- يجب ضبط `META_APP_SECRET` في الإنتاج لحماية webhook.
